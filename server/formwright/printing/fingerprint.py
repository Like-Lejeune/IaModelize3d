"""Printer fingerprint: print one coupon, photograph it on a reference sheet, and learn
how this printer distorts geometry. The deltas feed the geom PrinterProfile, so every
later hole, peg and fit is compensated automatically.

Coupon features (all nominal, *not* compensated):
- plate 70x40x2.4 with through holes 3/5/8/10 mm; holes are chamfered at the bottom so
  the top view shows the true bore, not the squished first layer;
- block A 20x20x5, plain: its silhouette includes the elephant foot;
- block B 20x20x5 with a 1 mm bottom chamfer and a 4 mm marker hole: its silhouette is
  the true outer size; (A - B) / 2 is the elephant foot;
- pegs 5 and 8 mm with bottom chamfers: outer diameter growth.
"""
from __future__ import annotations

import base64
import json
import math
import statistics
from typing import Any

import numpy as np

from ..config import settings
from ..db import get_db, new_id, now

HOLES = (3.0, 5.0, 8.0, 10.0)
PEGS = (5.0, 8.0)
BLOCK = 20.0
PLATE = (70.0, 40.0)


def coupon_source() -> str:
    return f"""
const meta = {{ title: 'Printer fingerprint coupon', pack: 'calibration', description: 'Print, then photograph from above on an A4 sheet.' }};
const params = {{}};
const HOLES = {json.dumps(list(HOLES))};
const PEGS = {json.dumps(list(PEGS))};
function build(p, lib) {{
  const {{ std, M }} = lib;
  // nominal geometry on purpose: no std.holeZ compensation here
  let plate = std.box([{PLATE[0]}, {PLATE[1]}, 2.4], {{ center: false }});
  const xs = [10, 22, 37, 56];
  HOLES.forEach((d, i) => {{
    plate = plate.subtract(M.cylinder(4, d / 2, d / 2, 96).translate([xs[i], 20, -0.5]));
    plate = plate.subtract(M.cylinder(0.6, d / 2 + 0.6, d / 2, 96).translate([xs[i], 20, -0.001]));
  }});
  const blockA = std.box([{BLOCK}, {BLOCK}, 5], {{ center: false }}).translate([0, 48, 0]);
  const blockB = std.box([{BLOCK}, {BLOCK}, 5], {{ center: false, chamferBottom: 1.0 }})
    .subtract(M.cylinder(7, 2, 2, 48).translate([{BLOCK / 2}, {BLOCK / 2}, -1]))
    .translate([28, 48, 0]);
  const pegs = PEGS.map((d, i) => std.extrude(std.circle(d), 4, {{ chamferBottom: 0.5 }}).translate([58, 52 + i * 13, 0]));
  return [
    lib.part(plate, {{ name: 'plate' }}),
    lib.part(blockA, {{ name: 'block_plain' }}),
    lib.part(blockB, {{ name: 'block_chamfered' }}),
    ...pegs.map((s, i) => lib.part(s, {{ name: 'peg_' + PEGS[i] }})),
  ];
}}
return {{ meta, params, build }};
"""


def _num_map(d: dict | None) -> dict[float, float]:
    out: dict[float, float] = {}
    for k, v in (d or {}).items():
        try:
            out[float(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def compute_fingerprint(measured: dict[str, Any]) -> dict[str, Any]:
    """measured: {"holes": {"3": 2.81, ...}, "pegs": {"5": 5.08, ...}, "block": 20.31, "block_chamfered": 20.06}
    All values are diameters/side lengths in mm. Deltas are diametral (added to a diameter)."""
    holes = _num_map(measured.get("holes"))
    pegs = _num_map(measured.get("pegs"))
    hole_d = [nom - got for nom, got in holes.items()]  # positive: holes print small -> enlarge
    outer_d = [got - nom for nom, got in pegs.items()]
    if measured.get("block_chamfered") is not None:
        outer_d.append(float(measured["block_chamfered"]) - BLOCK)
    hole_delta = statistics.fmean(hole_d) if hole_d else None
    outer_delta = statistics.fmean(outer_d) if outer_d else None
    ef = None
    if measured.get("block") is not None and measured.get("block_chamfered") is not None:
        ef = max(0.0, (float(measured["block"]) - float(measured["block_chamfered"])) / 2)

    def spread(values: list[float]) -> float:
        return statistics.pstdev(values) if len(values) > 1 else 0.15

    samples = len(hole_d) + len(outer_d)
    # consistent samples and more of them -> higher confidence; > 0.15 mm spread is suspicious
    conf = max(0.15, min(0.95, (1 - min(1.0, max(spread(hole_d), spread(outer_d)) / 0.15)) * min(1.0, samples / 6) + 0.15))
    clamp = lambda v, lo, hi: None if v is None else round(min(hi, max(lo, v)), 3)  # noqa: E731
    result = {
        "holeDelta": clamp(hole_delta, -0.3, 0.8),
        "outerDelta": clamp(outer_delta, -0.5, 0.5),
        "elephantFoot": clamp(ef, 0.0, 0.6),
        "fitDelta": clamp(max(0.0, outer_delta) if outer_delta is not None else None, 0.0, 0.5),
        "confidence": round(conf, 2),
        "samples": samples,
        "detail": {
            "holes": {f"{k:g}": round(v, 3) for k, v in holes.items()},
            "pegs": {f"{k:g}": round(v, 3) for k, v in pegs.items()},
            "block": measured.get("block"),
            "block_chamfered": measured.get("block_chamfered"),
        },
    }
    return result


# ------------------------------------------------------------------ measuring from a photo
def _poly_area(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return float(abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))) / 2)


def edge_correct(contour_px: np.ndarray, delta_px: float) -> np.ndarray:
    """OpenCV contours run through boundary pixel *centers*: outlines come out half a pixel
    small and holes half a pixel large. Offset by `delta_px` (+outward) around the centroid,
    which is exact for the convex shapes on the coupon."""
    pts = contour_px.reshape(-1, 2).astype(np.float64)
    c = pts.mean(axis=0)
    x, y = pts[:, 0], pts[:, 1]
    area = abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))) / 2
    perim = float(np.sum(np.linalg.norm(np.diff(np.vstack([pts, pts[:1]]), axis=0), axis=1)))
    r_eff = 2 * area / perim if perim else 0
    if r_eff <= abs(delta_px):
        return pts
    return c + (pts - c) * (1 + delta_px / r_eff)


def classify(objects: list[dict[str, Any]]) -> dict[str, Any]:
    """objects: [{"outer": Nx2 mm array, "holes": [Nx2 mm arrays]}] -> measured dict.
    Pure geometry so it can be tested without a photo."""
    import cv2

    measured: dict[str, Any] = {"holes": {}, "pegs": {}}
    items = []
    for o in objects:
        outer = np.asarray(o["outer"], dtype=np.float32)
        area = _poly_area(outer)
        if area < 5:
            continue
        (w, h) = cv2.minAreaRect(outer)[1]
        # convex hull perimeter: a pixel-staircase contour would make small circles look square
        hull = cv2.convexHull(outer.reshape(-1, 1, 2))
        perim = float(cv2.arcLength(hull, True))
        circ = 4 * math.pi * float(cv2.contourArea(hull)) / (perim * perim) if perim else 0
        items.append({"outer": outer, "holes": [np.asarray(hh, dtype=np.float32) for hh in o.get("holes", [])], "area": area, "w": w, "h": h, "circ": circ})
    if not items:
        raise ValueError("no coupon parts found in the photo")
    plate = max(items, key=lambda i: i["area"])
    if len(plate["holes"]) >= 3:
        hole_d = sorted(2 * math.sqrt(_poly_area(hh) / math.pi) for hh in plate["holes"] if _poly_area(hh) > 3)
        for nom, got in zip(HOLES, hole_d[-len(HOLES):] if len(hole_d) >= len(HOLES) else hole_d):
            measured["holes"][f"{nom:g}"] = round(got, 3)
    others = [i for i in items if i is not plate]
    blocks = [i for i in others if 15 < (i["w"] + i["h"]) / 2 < 25 and 0.85 < i["w"] / max(i["h"], 1e-6) < 1.15 and i["circ"] < 0.85]
    for b in blocks:
        side = (b["w"] + b["h"]) / 2
        measured["block_chamfered" if b["holes"] else "block"] = round(side, 3)
    pegs = [i for i in others if i["circ"] > 0.85 and not i["holes"]]
    for peg in pegs:
        d = 2 * math.sqrt(peg["area"] / math.pi)
        nom = min(PEGS, key=lambda n: abs(n - d))
        if abs(nom - d) < 1.0:
            measured["pegs"][f"{nom:g}"] = round(d, 3)
    return measured


async def _calibration(meter: Any, user: dict, asset: dict) -> np.ndarray:
    from ..vision import scene  # written in parallel; imported lazily

    cal = (asset.get("meta") or {}).get("calibration")
    if not (isinstance(cal, dict) and cal.get("ok")):
        cal = await scene.calibrate(meter, asset)
    if not isinstance(cal, dict) or not cal.get("ok"):
        reason = cal.get("reason") if isinstance(cal, dict) else None
        raise ValueError(reason or "no reference found in the photo; put the coupon on an A4 sheet")
    H = cal.get("H_px2mm") or cal.get("H")
    if H is not None:
        return np.asarray(H, dtype=np.float64).reshape(3, 3)
    if cal.get("mm_per_px"):
        # scale-only references (coin, battery): fine for a coupon shot straight from above
        s = float(cal["mm_per_px"])
        return np.array([[s, 0, 0], [0, s, 0], [0, 0, 1]], dtype=np.float64)
    raise ValueError("the reference gave no usable scale")


async def measure(meter: Any, user: dict, asset: dict, prompt: str = "3D printed plastic part") -> dict[str, Any]:
    """Photo of the printed coupon on a reference -> fingerprint (not yet saved)."""
    import cv2
    import meta_sam_parser as msp

    from ..llm.client import meta

    H = await _calibration(meter, user, asset)
    path = settings().data_dir / "files" / asset["path"]
    data = path.read_bytes()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    raw = await meta().sam(meter, f"data:{mime};base64,{base64.b64encode(data).decode()}", prompt)
    parser = msp.image_segmentation_format().create_parser()
    parser.push(raw)
    result = parser.finish(msp.CompletedOutcome()).result
    objects = []
    for rec in getattr(result, "records", []):
        if not isinstance(rec, msp.SegmentationMaskRecord):
            continue
        b = rec.bounds
        mask = np.frombuffer(msp.decode_mask_to_raster(rec.mask), dtype=np.uint8).reshape(rec.mask.height, rec.mask.width)
        contours, hierarchy = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        if hierarchy is None:
            continue
        def to_mm(c: np.ndarray, grow: float) -> np.ndarray:
            px = edge_correct(c, grow) + np.array([b.left, b.top], dtype=np.float64)
            return cv2.perspectiveTransform(px.reshape(-1, 1, 2), H).reshape(-1, 2)

        for i, c in enumerate(contours):
            if hierarchy[0][i][3] != -1 or len(c) < 8:
                continue
            holes = [to_mm(contours[j], -0.5) for j in range(len(contours)) if hierarchy[0][j][3] == i and len(contours[j]) >= 8]
            objects.append({"outer": to_mm(c, 0.5), "holes": holes})
    measured = classify(objects)
    return {"measured": measured, "fingerprint": compute_fingerprint(measured)}


async def save(user_id: str, printer_id: str, fingerprint: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    row = await db.one("SELECT * FROM printers WHERE user_id = ? AND name = ?", user_id, printer_id)
    if row:
        await db.update("printers", "id", row["id"], {"fingerprint": fingerprint})
        return {**row, "fingerprint": fingerprint}
    rec = {"id": new_id("pr_"), "user_id": user_id, "name": printer_id, "preset": {"printer_id": printer_id}, "fingerprint": fingerprint, "created_at": now()}
    await db.insert("printers", rec)
    return rec


async def load(user_id: str, printer_id: str | None) -> dict[str, Any] | None:
    if not printer_id:
        return None
    db = await get_db()
    row = await db.one("SELECT fingerprint FROM printers WHERE user_id = ? AND name = ?", user_id, printer_id)
    return row["fingerprint"] if row and row["fingerprint"] else None
