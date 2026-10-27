"""Scene understanding: references, calibration, object selection in millimetres,
caliper readings, and the summary the agent works from.

Numbers come from measurement, not from the language model: SAM 3.1 gives masks,
the reference object gives a homography and a camera pose, and Muse Spark only
interprets (which object is the reference, what the caliper display says).
"""
from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from typing import Any

import cv2
import numpy as np

from .. import quotas
from ..config import settings
from ..db import get_db, new_id, now
from ..llm.client import CostMeter, meta
from . import geometry as g
from .common import as_list, asset_image, data_url, norm_box_to_px
from .refine import contrast_image, refine_polyline
from .sam import Mask, largest_component, load_mask_png, polygons, save_mask_png, segment

log = logging.getLogger(__name__)

SAM_PHRASE = {"sheet": "sheet of paper", "card": "bank card", "coin": "coin", "cylinder": "battery", "box": "lego brick"}
EDGE_PX = 1.0  # SAM boundary uncertainty
ASSUMED_THICKNESS_MM = 3.0  # parallax term when the part height is unknown


@lru_cache
def references() -> dict[str, dict[str, Any]]:
    data = json.loads(settings().standards_path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.get("references", {}).items() if not k.startswith("_")}


def _ref_lookup(name: str | None) -> tuple[str, dict[str, Any]] | None:
    if not name:
        return None
    refs = references()
    n = name.strip().lower()
    for k, v in refs.items():
        if k.lower() == n:
            return k, v
    for k, v in refs.items():
        if n in k.lower() or k.lower() in n:
            return k, v
    aliases = {"paper": "A4", "sheet": "A4", "a4 paper": "A4", "letter paper": "Letter", "bank card": "ID-1 card", "credit card": "ID-1 card",
               "card": "ID-1 card", "aa": "AA battery", "aaa": "AAA battery", "lego": "LEGO 2x4 brick"}
    for a, k in aliases.items():
        if a in n and k in refs:
            return k, refs[k]
    return None


async def _update_meta(asset_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    row = await db.one("SELECT * FROM assets WHERE id = ?", asset_id)
    if not row:
        raise ValueError("asset not found")
    meta_ = {**row["meta"], **patch}
    await db.update("assets", "id", asset_id, {"meta": meta_})
    row["meta"] = meta_
    return row


def _is_image(asset: dict[str, Any]) -> bool:
    return asset["kind"] in ("photo", "sketch", "caliper", "concept", "render", "print")


# ------------------------------------------------------------------ detect
DETECT_SCHEMA = {
    "type": "object",
    "properties": {
        "references": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "one of the known reference names, 'caliper', 'ruler' or 'other'"},
                    "bbox": {"type": "array", "items": {"type": "number"}, "description": "[x_min, y_min, x_max, y_max] on a 0-1000 grid"},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "bbox", "confidence"],
            },
        },
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "bbox": {"type": "array", "items": {"type": "number"}},
                    "suggested_role": {"type": "string", "enum": ["target", "mating", "context"]},
                },
                "required": ["label", "bbox", "suggested_role"],
            },
        },
    },
    "required": ["references", "objects"],
}


async def _detect(meter: CostMeter, asset: dict[str, Any], model: str) -> dict[str, Any]:
    img = asset_image(asset)
    h, w = img.shape[:2]
    names = ", ".join(references())
    out = await meta().json(
        meter,
        model=model,
        system=(
            "You find measurement references and objects in workshop photos for a 3D-printing tool. "
            f"Known references: {names}, plus 'caliper' and 'ruler'. Report only what is clearly visible. "
            "A plain sheet of paper is a reference (A4 unless it is clearly US Letter). "
            "Boxes are [x_min, y_min, x_max, y_max] on a 0-1000 grid of the image. "
            "Objects: the item(s) the user probably wants to copy or fit (target), surfaces/holes something must fit into (mating), "
            "everything else relevant (context). At most 6 objects."
        ),
        content=[{"type": "input_text", "text": "Locate references and objects."}, {"type": "input_image", "image_url": data_url(img, 1280)}],
        schema=DETECT_SCHEMA,
        name="detect",
        effort="low",
    )
    refs = []
    for r in out.get("references", []):
        hit = _ref_lookup(r.get("name"))
        kind = hit[1]["kind"] if hit else ("caliper" if "caliper" in str(r.get("name", "")).lower() else "ruler" if "ruler" in str(r.get("name", "")).lower() else "other")
        refs.append({"name": hit[0] if hit else r.get("name"), "kind": kind, "bbox": norm_box_to_px(r.get("bbox", [0, 0, 0, 0]), w, h),
                     "confidence": float(r.get("confidence", 0.5))})
    objs = []
    for o in out.get("objects", []):
        label = str(o.get("label", "object"))
        bbox = norm_box_to_px(o.get("bbox", [0, 0, 0, 0]), w, h)
        # the model sometimes files a reference under objects ("white sheet of paper")
        hit = _ref_lookup(label) if o.get("suggested_role") == "context" or any(
            k in label.lower() for k in ("paper", "sheet", "card", "coin", "battery", "lego")) else None
        if hit and not any(r["name"] == hit[0] for r in refs):
            refs.append({"name": hit[0], "kind": hit[1]["kind"], "bbox": bbox, "confidence": 0.6, "from_object": label})
            continue
        if any(k in label.lower() for k in ("caliper", "ruler")):
            refs.append({"name": "caliper" if "caliper" in label.lower() else "ruler", "kind": "caliper" if "caliper" in label.lower() else "ruler",
                         "bbox": bbox, "confidence": 0.6, "from_object": label})
            continue
        objs.append({"label": label, "bbox": bbox, "suggested_role": o.get("suggested_role", "target")})
    refs.sort(key=lambda r: -r["confidence"])
    return {"references": refs, "objects": objs}


GROUND_SCHEMA = {
    "type": "object",
    "properties": {"found": {"type": "boolean"}, "bbox": {"type": "array", "items": {"type": "number"}, "description": "[x_min, y_min, x_max, y_max], 0-1000 grid"}},
    "required": ["found", "bbox"],
}


async def _ground_box(meter: CostMeter, img: np.ndarray, phrase: str, model: str) -> list[float] | None:
    h, w = img.shape[:2]
    out = await meta().json(meter, model=model, system="You locate objects in photos. Boxes are [x_min, y_min, x_max, y_max] on a 0-1000 grid, tight around the object.",
                            content=[{"type": "input_text", "text": f"Box the {phrase}."}, {"type": "input_image", "image_url": data_url(img, 1280)}],
                            schema=GROUND_SCHEMA, name="ground", effort="low")
    if not out.get("found") or len(out.get("bbox") or []) != 4:
        return None
    x1, y1, x2, y2 = norm_box_to_px(out["bbox"], w, h)
    pad = 0.04 * max(x2 - x1, y2 - y1)
    return [max(0, x1 - pad), max(0, y1 - pad), min(w - 1, x2 + pad), min(h - 1, y2 + pad)]


async def detect(user: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    if not _is_image(asset):
        raise ValueError("detection works on photos")
    meter = CostMeter(budget_usd=0.05)
    model = (await quotas.choose_models(user)).fast
    try:
        found = await _detect(meter, asset, model)
    finally:
        await quotas.settle(user["id"], meter.usd)
    await _update_meta(asset["id"], {"detected": found})
    return found


# ------------------------------------------------------------------ calibrate
def _focal(asset: dict[str, Any], w: int, h: int) -> tuple[float | None, str]:
    exif = asset.get("meta", {}).get("exif") or {}
    if exif.get("focal_35mm"):
        return g.focal_from_35mm(float(exif["focal_35mm"]), w, h), "exif"
    return None, "default"


def calibration_from_mask(asset: dict[str, Any], mask: np.ndarray, ref_name: str, ref: dict[str, Any]) -> dict[str, Any]:
    h, w = mask.shape[:2]
    kind = ref["kind"]
    if kind in ("sheet", "card"):
        corners = g.fit_quad(largest_component(mask))
        if corners is None:
            return {"ok": False, "reason": f"could not find the four corners of the {ref_name}"}
        short, long_ = sorted((float(ref["w"]), float(ref["h"])))
        f, src = _focal(asset, w, h)
        cal = g.calibrate_plane(corners, short, long_, w, h, focal=f, focal_source=src)
        d = cal.to_dict()
        if d["camera_height_mm"] <= 0 or d["reproj_px"] > 5:
            d["warning"] = "pose looks unreliable; keep the whole reference flat and in view"
    elif kind == "coin":
        d = g.scale_from_circle(mask, float(ref["d"])) or {"ok": False, "reason": "coin outline not found"}
    elif kind == "cylinder":
        d = g.scale_from_length(mask, float(ref["l"])) or {"ok": False, "reason": "battery outline not found"}
    elif kind == "box":
        d = g.scale_from_length(mask, float(ref["w"])) or {"ok": False, "reason": "brick outline not found"}
    else:
        return {"ok": False, "reason": f"{ref_name} cannot be used for scale"}
    d.update({"reference": ref_name, "reference_kind": kind, "width": w, "height": h})
    return d


async def calibrate(meter: CostMeter, asset: dict[str, Any], reference: str | None = None, *, mask: np.ndarray | None = None,
                    box: list[float] | None = None) -> dict[str, Any]:
    """Find the reference, fit it, and store `asset.meta.calibration`."""
    if not _is_image(asset):
        return {"ok": False, "reason": "not a photo"}
    img = asset_image(asset)
    candidates: list[tuple[str, dict[str, Any], list[int] | None]] = []
    if reference:
        hit = _ref_lookup(reference)
        if not hit:
            return {"ok": False, "reason": f"unknown reference {reference}"}
        candidates.append((hit[0], hit[1], box))
    else:
        for r in (asset.get("meta", {}).get("detected") or {}).get("references", []):
            hit = _ref_lookup(r.get("name"))
            if hit and r.get("confidence", 0) >= 0.3:
                candidates.append((hit[0], hit[1], r.get("bbox")))
        if not candidates:
            candidates = [("A4", references()["A4"], None), ("ID-1 card", references()["ID-1 card"], None)]
    last = {"ok": False, "reason": "no reference found (put the part on an A4 sheet or next to a bank card)"}
    for name, ref, rbox in candidates:
        if mask is not None:
            ref_mask = mask
        else:
            if rbox and rbox[2] > rbox[0] and rbox[3] > rbox[1]:
                pad = 0.04 * max(rbox[2] - rbox[0], rbox[3] - rbox[1])
                pbox = [rbox[0] - pad, rbox[1] - pad, rbox[2] + pad, rbox[3] + pad]
                masks = await segment(meter, img, box=pbox)
            else:
                masks = await segment(meter, img, text=SAM_PHRASE.get(ref["kind"], name))
            masks = [m for m in masks if m.score >= 0.3]
            if not masks:
                continue
            ref_mask = max(masks, key=lambda m: m.area).mask if ref["kind"] == "sheet" else masks[0].mask
        cal = calibration_from_mask(asset, ref_mask, name, ref)
        if cal.get("ok"):
            rel = save_mask_png(f"{asset['project_id']}/{asset['id']}_ref_mask.png", ref_mask)
            cal["mask_path"] = rel
            await _update_meta(asset["id"], {"calibration": cal})
            asset["meta"] = {**asset.get("meta", {}), "calibration": cal}
            return cal
        last = cal
    await _update_meta(asset["id"], {"calibration": {"ok": False, "reason": last.get("reason")}})
    return last


def camera_for_render(asset: dict[str, Any]) -> dict[str, Any] | None:
    cal = g.calibration_from_dict((asset.get("meta") or {}).get("calibration") or {})
    if cal is None:
        return None
    K = cal.K
    return {
        "width": int(cal.width), "height": int(cal.height),
        "R": [float(v) for v in cal.R.reshape(-1)], "t": [float(v) for v in cal.t.reshape(-1)],
        "fx": float(K[0, 0]), "fy": float(K[1, 1]), "cx": float(K[0, 2]), "cy": float(K[1, 2]),
    }


# ------------------------------------------------------------------ outlines in mm
def offset_px(poly: np.ndarray, d: float) -> np.ndarray:
    """Move each vertex along its outward bisector by d px (positive = grow)."""
    p = np.asarray(poly, dtype=float)
    if len(p) < 3:
        return p
    sign = 1.0 if g.signed_area(p) > 0 else -1.0
    prev = np.roll(p, 1, axis=0)
    nxt = np.roll(p, -1, axis=0)

    def normals(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        e = b - a
        n = np.column_stack([e[:, 1], -e[:, 0]]) * sign
        ln = np.hypot(n[:, 0], n[:, 1])
        ln[ln == 0] = 1
        return n / ln[:, None]

    n1, n2 = normals(prev, p), normals(p, nxt)
    # miter: moving the vertex by (n1 + n2) / (1 + n1.n2) * d shifts both edges by exactly d
    denom = 1 + (n1 * n2).sum(axis=1)
    denom = np.maximum(denom, 0.25)  # cap spikes at very sharp corners
    return p + (n1 + n2) / denom[:, None] * d


def _simplify(poly: np.ndarray, eps: float = 0.4) -> np.ndarray:
    return cv2.approxPolyDP(np.asarray(poly, np.float32).reshape(-1, 1, 2), eps, True).reshape(-1, 2).astype(float)


def find_holes(proj: np.ndarray, mask: np.ndarray, outer_raw: np.ndarray) -> list[np.ndarray] | None:
    """Holes from the photo itself: background colour showing through the part.

    SAM tends to fill or shrink small holes; inside the part's outline, pixels that look
    like the background are holes. Each hole edge is then snapped like the outline.
    """
    filled = np.zeros(mask.shape, np.uint8)
    cv2.fillPoly(filled, [np.asarray(outer_raw, np.int32).reshape(-1, 1, 2)], 1)
    inner = cv2.erode(filled, np.ones((5, 5), np.uint8)) > 0
    ring = (cv2.dilate(filled, np.ones((15, 15), np.uint8)) > 0) & ~(cv2.dilate(filled, np.ones((5, 5), np.uint8)) > 0)
    solid = inner & mask
    if solid.sum() < 50 or ring.sum() < 50:
        return None
    hi, lo = float(np.median(proj[solid])), float(np.median(proj[ring]))
    if hi - lo < 8:
        return None
    cand = (inner & (proj < (hi + lo) / 2)).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(cand, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    holes = []
    for c in contours:
        if cv2.contourArea(c) < 20:
            continue
        hole = np.zeros(mask.shape, np.uint8)
        cv2.drawContours(hole, [c], -1, 1, -1)
        solid_mask = (filled > 0) & ~(hole > 0)
        pts, frac = refine_polyline(proj, solid_mask, c.reshape(-1, 2).astype(float))
        holes.append(_simplify(pts) if frac >= 0.5 else c.reshape(-1, 2).astype(float))
    return holes


def robust_size(poly_mm: np.ndarray, angle_deg: float) -> list[float]:
    """Extents along the min-area-rectangle axes, ignoring single-point spikes
    (corner overshoot of edge snapping): 0.2/99.8 % quantiles of a dense resampling."""
    from .refine import resample

    dense = resample(poly_mm, step=0.2)
    a = np.radians(angle_deg)
    u = np.array([np.cos(a), np.sin(a)])
    v = np.array([-u[1], u[0]])
    ext = []
    for axis in (u, v):
        pr = dense @ axis
        ext.append(float(np.quantile(pr, 0.998) - np.quantile(pr, 0.002)))
    return sorted(ext, reverse=True)


def measure_mask(mask: np.ndarray, cal: dict[str, Any], height_mm: float = 0.0, height_known: bool = False,
                 image: np.ndarray | None = None) -> dict[str, Any]:
    """Pixel mask -> outline, holes, size and uncertainty in mm (world frame of the photo).

    With the photo given, outlines are snapped to the real image edges (sub-pixel),
    which removes SAM's typical 1-4 px border bias.
    """
    polys = polygons(mask, epsilon_px=0.75)
    if not polys:
        return {"found": False}
    main = polys[0]
    outer_px = offset_px(main["outer"], 0.5)  # boundary pixels -> pixel edges
    # hole contours run over the solid pixel centres around the hole: the true edge is half a pixel inside
    holes_px = [offset_px(hp, -0.5) for hp in main["holes"]]
    snapped = None
    if image is not None:
        proj = contrast_image(image, mask)
        ref_outer, frac = refine_polyline(proj, mask, main["raw"])
        if frac >= 0.5:
            outer_px = _simplify(ref_outer)
            found = find_holes(proj, mask, main["raw"])
            if found is not None:
                holes_px = found
        snapped = round(frac, 3)
    out: dict[str, Any] = {
        "found": True,
        "components": len(polys),
        "outline_px": as_list(outer_px, 2),
        "area_px": int(mask.sum()),
        "edge_snap": snapped,
    }
    plane = g.calibration_from_dict(cal) if cal else None
    if plane is not None:
        to_mm = lambda pts: g.pixels_to_plane(plane, pts, height_mm)  # noqa: E731
        mm_per_px = plane.mm_per_px_at(np.asarray(main["outer"]).mean(axis=0))
    elif cal and cal.get("ok") and cal.get("kind") == "scale_only":
        k = float(cal["mm_per_px"])
        c = np.array(cal.get("center_px", [0, 0]), dtype=float)
        to_mm = lambda pts: np.column_stack([(np.asarray(pts)[:, 0] - c[0]) * k, -(np.asarray(pts)[:, 1] - c[1]) * k])  # noqa: E731
        mm_per_px = k
    else:
        out["calibrated"] = False
        return out
    outer = g.orient(to_mm(outer_px), ccw=True)
    holes_mm = [g.orient(to_mm(hp), ccw=False) for hp in holes_px]
    rect = cv2.minAreaRect(outer.astype(np.float32))
    size = robust_size(outer, rect[2])
    lo, hi = outer.min(axis=0), outer.max(axis=0)
    area = g.polygon_area(outer) - sum(g.polygon_area(hh) for hh in holes_mm)
    circles = []
    for hh in holes_mm:
        c, r, rms = g.fit_circle(hh)
        circles.append({"center": [round(float(c[0]), 3), round(float(c[1]), 3)], "d": round(2 * r, 3), "rms": round(rms, 3),
                        "circular": bool(rms < 0.06 * r + 0.05)})
    # uncertainty: edge quantization, reference fit, unknown height (parallax), scale-only tilt
    e_edge = (0.4 if (snapped or 0) >= 0.5 else EDGE_PX) * mm_per_px
    e_ref = float(cal.get("reproj_px", 0.5)) * mm_per_px
    cam_h = float(cal.get("camera_height_mm") or 0)
    if height_known:
        e_par = 0.1
    elif cam_h > 0:
        e_par = max(size) * ASSUMED_THICKNESS_MM / cam_h
    else:
        e_par = 0.03 * max(size)
    e_scale = 0.02 * max(size) if cal.get("kind") == "scale_only" else 0.0
    unc = math.sqrt(e_edge**2 + e_ref**2 + e_par**2 + e_scale**2)
    out.update({
        "calibrated": True,
        "calibration_kind": cal.get("kind"),
        "reference": cal.get("reference"),
        "height_mm": height_mm,
        "outline_mm": [as_list(outer, 3)] + [as_list(hh, 3) for hh in holes_mm],
        "area_mm2": round(area, 2),
        "size_mm": [round(float(v), 2) for v in size],
        "bbox_mm": [round(float(lo[0]), 2), round(float(lo[1]), 2), round(float(hi[0]), 2), round(float(hi[1]), 2)],
        "centroid_mm": [round(float(v), 2) for v in outer.mean(axis=0)],
        "rotation_deg": round(float(rect[2]), 2),
        "mm_per_px": round(mm_per_px, 5),
        "holes_mm": circles,
        "uncertainty_mm": round(unc, 3),
        "uncertainty_parts": {"edge": round(e_edge, 3), "reference": round(e_ref, 3), "parallax": round(e_par, 3), "scale_only": round(e_scale, 3)},
    })
    return out


# ------------------------------------------------------------------ select
CALIPER_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "value": {"type": "number", "description": "the number shown on the display / read from the scale"},
        "unit": {"type": "string", "enum": ["mm", "in"]},
        "raw_text": {"type": "string"},
        "caliper_type": {"type": "string", "enum": ["digital", "dial", "vernier", "unknown"]},
        "confidence": {"type": "number"},
        "jaw_bbox": {"type": "array", "items": {"type": "number"}, "description": "jaws and the measured feature, 0-1000 grid"},
        "measured_feature": {"type": "string", "description": "what the jaws are on, e.g. 'shelf board thickness'"},
    },
    "required": ["found", "value", "unit", "raw_text", "caliper_type", "confidence", "jaw_bbox", "measured_feature"],
}


async def read_caliper(meter: CostMeter, asset: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    img = asset_image(asset)
    h, w = img.shape[:2]
    out = await meta().json(
        meter,
        model=model or settings().model_fast,
        system=("Read a caliper in a photo. For digital calipers read the LCD exactly as shown (decimal point matters). "
                "For dial/vernier calipers combine main scale and dial/vernier. Say which feature the jaws measure. "
                "If no caliper is visible set found=false."),
        content=[{"type": "input_text", "text": "Read the caliper."}, {"type": "input_image", "image_url": data_url(img, 1600)}],
        schema=CALIPER_SCHEMA,
        name="caliper",
        effort="medium",
    )
    if not out.get("found"):
        reading = {"found": False}
    else:
        value = float(out.get("value", 0))
        value_mm = value * 25.4 if out.get("unit") == "in" else value
        reading = {
            "found": True, "value_mm": round(value_mm, 3), "raw_text": out.get("raw_text", ""), "unit": out.get("unit", "mm"),
            "confidence": float(out.get("confidence", 0.5)), "jaw_bbox": norm_box_to_px(out.get("jaw_bbox", [0, 0, 0, 0]), w, h),
            "feature": out.get("measured_feature", ""), "type": out.get("caliper_type", "unknown"),
            # display resolution of typical calipers
            "uncertainty_mm": 0.02 if out.get("caliper_type") == "digital" else 0.05,
        }
    await _update_meta(asset["id"], {"caliper": reading})
    return reading


async def _insert_selection(project_id: str, asset_id: str, role: str, name: str, prompt: dict[str, Any], mask_path: str | None,
                            data: dict[str, Any], sel_id: str | None = None) -> dict[str, Any]:
    db = await get_db()
    sid = sel_id or new_id("s_")
    await db.insert("selections", {"id": sid, "project_id": project_id, "asset_id": asset_id, "role": role, "name": name, "prompt": prompt,
                                   "mask_path": mask_path, "data": data, "created_at": now()})
    return await db.one("SELECT * FROM selections WHERE id = ?", sid)  # type: ignore[return-value]


async def _unique_name(project_id: str, base: str) -> str:
    db = await get_db()
    rows = await db.all("SELECT name FROM selections WHERE project_id = ?", project_id)
    taken = {r["name"] for r in rows}
    if base not in taken:
        return base
    i = 2
    while f"{base}{i}" in taken:
        i += 1
    return f"{base}{i}"


async def select(user: dict[str, Any], project_id: str, asset: dict[str, Any], req: Any) -> dict[str, Any]:
    """Segment what the user pointed at and measure it. `req` is models.SelectRequest."""
    if not _is_image(asset):
        raise ValueError("selection works on photos; use video tracking for clips")
    meter = CostMeter(budget_usd=0.10)
    choice = await quotas.choose_models(user)
    prompt = {"points": [p.model_dump() for p in req.points], "box": req.box, "text": req.text}
    name = await _unique_name(project_id, (req.name or req.role).strip().replace(" ", "_")[:40] or req.role)
    try:
        if req.role == "caliper":
            reading = await read_caliper(meter, asset, choice.fast)
            return await _insert_selection(project_id, asset["id"], "caliper", name, prompt, None, {"caliper": reading, "found": reading.get("found", False)})
        img = asset_image(asset)
        masks: list[Mask] = await segment(meter, img, text=req.text or None,
                                          points=[p.model_dump() for p in req.points] if not req.text else None,
                                          box=req.box if not req.text else None)
        masks = [m for m in masks if m.score >= 0.2] or masks
        if not masks and req.text:
            # SAM's concept prompts miss unusual objects; let Spark ground the phrase to a box, then SAM refines it.
            box = await _ground_box(meter, img, req.text, choice.fast)
            if box:
                masks = await segment(meter, img, box=box)
        if not masks:
            raise ValueError("nothing found there; tap the middle of the object or drag a box around it")
        mask = masks[0].mask
        sid = new_id("s_")
        mask_path = save_mask_png(f"{project_id}/{sid}_mask.png", mask)
        if req.role == "reference":
            hit = _ref_lookup(req.name) or ("A4", references()["A4"])
            cal = calibration_from_mask(asset, mask, hit[0], hit[1])
            if cal.get("ok"):
                cal["mask_path"] = mask_path
                await _update_meta(asset["id"], {"calibration": cal})
            data = {"found": True, "calibration": {k: v for k, v in cal.items() if k in ("ok", "reason", "reference", "kind", "mm_per_px", "reproj_px", "camera_height_mm", "focal_source", "warning")},
                    "bbox_px": masks[0].bbox_px, "confidence": masks[0].score}
            return await _insert_selection(project_id, asset["id"], "reference", name, prompt, mask_path, data, sid)
        cal = (asset.get("meta") or {}).get("calibration") or {}
        if not cal.get("ok") and not cal.get("reason"):
            cal = await calibrate(meter, asset)
        data = measure_mask(mask, cal if cal.get("ok") else {}, image=img)
        data.update({"bbox_px": masks[0].bbox_px, "confidence": round(masks[0].score, 4)})
        if not data.get("calibrated"):
            data["calibration_note"] = cal.get("reason") or "no reference in the photo: sizes are in pixels only"
        return await _insert_selection(project_id, asset["id"], req.role, name, prompt, mask_path, data, sid)
    finally:
        await quotas.settle(user["id"], meter.usd)


async def remeasure(project_id: str, selection_id: str, height_mm: float) -> dict[str, Any]:
    """Recompute a selection on the plane z = height_mm (the part's top), once its thickness is known."""
    db = await get_db()
    sel = await db.one("SELECT * FROM selections WHERE id = ? AND project_id = ?", selection_id, project_id)
    if not sel or not sel["mask_path"]:
        raise ValueError("selection has no mask")
    asset = await db.one("SELECT * FROM assets WHERE id = ?", sel["asset_id"])
    cal = (asset or {}).get("meta", {}).get("calibration") or {}
    mask = load_mask_png(sel["mask_path"])
    data = {**sel["data"], **measure_mask(mask, cal if cal.get("ok") else {}, height_mm=height_mm, height_known=True,
                                          image=asset_image(asset) if asset else None)}
    await db.update("selections", "id", selection_id, {"data": data})
    sel["data"] = data
    return sel


# ------------------------------------------------------------------ summary for the agent
async def scene_summary(project_id: str) -> dict[str, Any]:
    db = await get_db()
    assets = await db.all("SELECT * FROM assets WHERE project_id = ? ORDER BY created_at", project_id)
    sels = await db.all("SELECT * FROM selections WHERE project_id = ? ORDER BY created_at", project_id)
    out_assets = []
    measurements: list[dict[str, Any]] = []
    for a in assets:
        m = a.get("meta") or {}
        cal = m.get("calibration") or {}
        entry: dict[str, Any] = {"id": a["id"], "kind": a["kind"], "width": a["width"], "height": a["height"]}
        if cal:
            entry["calibration"] = {k: cal.get(k) for k in ("ok", "reason", "reference", "kind", "mm_per_px", "reproj_px", "camera_height_mm", "focal_source", "warning")
                                    if cal.get(k) is not None}
        if m.get("transcript"):
            entry["transcript"] = m["transcript"]
        if m.get("caliper", {}).get("found"):
            c = m["caliper"]
            entry["caliper"] = c
            measurements.append({"name": c.get("feature") or "caliper reading", "value_mm": c["value_mm"], "source": "caliper",
                                 "confidence": c.get("confidence", 0.5), "uncertainty_mm": c.get("uncertainty_mm", 0.05), "asset_id": a["id"]})
        if m.get("detected"):
            entry["detected"] = {"references": [r["name"] for r in m["detected"].get("references", [])],
                                 "objects": [o["label"] for o in m["detected"].get("objects", [])]}
        out_assets.append(entry)
    out_sels = []
    outlines: dict[str, list] = {}
    for s in sels:
        d = s["data"] or {}
        item = {"id": s["id"], "name": s["name"], "role": s["role"], "asset_id": s["asset_id"]}
        for k in ("found", "calibrated", "reference", "size_mm", "bbox_mm", "area_mm2", "holes_mm", "uncertainty_mm", "height_mm", "confidence",
                  "components", "calibration_note"):
            if k in d:
                item[k] = d[k]
        if d.get("caliper"):
            item["caliper"] = d["caliper"]
        out_sels.append(item)
        if d.get("outline_mm") and s["role"] in ("target", "mating", "context"):
            outlines[s["name"]] = d["outline_mm"]
        if d.get("size_mm"):
            unc = d.get("uncertainty_mm", 1.0)
            measurements.append({"name": f"{s['name']} length", "value_mm": d["size_mm"][0], "source": "photo", "confidence": d.get("confidence", 0.5),
                                 "uncertainty_mm": unc, "selection_id": s["id"]})
            measurements.append({"name": f"{s['name']} width", "value_mm": d["size_mm"][1], "source": "photo", "confidence": d.get("confidence", 0.5),
                                 "uncertainty_mm": unc, "selection_id": s["id"]})
            for i, hole in enumerate(d.get("holes_mm", [])):
                if hole.get("circular"):
                    measurements.append({"name": f"{s['name']} hole {i + 1} diameter", "value_mm": hole["d"], "source": "photo",
                                         "confidence": d.get("confidence", 0.5), "uncertainty_mm": unc, "selection_id": s["id"]})
        if d.get("caliper", {}).get("found"):
            c = d["caliper"]
            measurements.append({"name": c.get("feature") or s["name"], "value_mm": c["value_mm"], "source": "caliper",
                                 "confidence": c.get("confidence", 0.5), "uncertainty_mm": c.get("uncertainty_mm", 0.05), "selection_id": s["id"]})
    return {
        "assets": out_assets,
        "selections": out_sels,
        "measurements": measurements,
        "inputs": {"outlines": outlines},
        "frame": "Outlines are in the reference plane of their photo: mm, origin at the reference's bottom-left corner, x right, y away, z up.",
    }
