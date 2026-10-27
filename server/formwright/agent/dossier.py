"""Object dossier: a thorough, structured analysis before any modelling.

Rules that keep it useful instead of long:
- numbers come from tools, not from looking: SAM masks of the object and of every
  instance of its motif give scale-free ratios (height/width, taper, elements per row,
  rows, element size) even when there is no reference in the photo;
- competing hypotheses are kept with confidences instead of one confident guess;
- the output is a schema, not prose, and doubles as the critic's checklist;
- depth adapts: full for copies, landmarks, stylized and generative work from images,
  short (interfaces, loads, unknowns, checklist) for parts described in text.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

import numpy as np

from .. import storage
from ..knowledge.facts import search_dimensions
from ..llm.client import meta
from .runner import JobContext

log = logging.getLogger(__name__)

IMAGE_KINDS = ("photo", "sketch", "concept", "print")


def depth_for(pack: str, assets: list[dict[str, Any]], mode: str) -> str:
    if mode in ("off", "full", "short"):
        return mode
    has_images = any(a["kind"] in IMAGE_KINDS for a in assets)
    if has_images and pack in ("copy", "forms", "landmark", "stylize", "household", "adapter", "mechanisms"):
        return "full"
    if pack in ("landmark", "stylize"):
        return "full"
    return "short"


# ------------------------------------------------------------------ scale-free measurement
def _row_extent(mask: np.ndarray, y: int) -> tuple[int, int] | None:
    xs = np.flatnonzero(mask[max(0, min(mask.shape[0] - 1, y))])
    return (int(xs[0]), int(xs[-1])) if xs.size else None


def silhouette_ratios(mask: np.ndarray) -> dict[str, Any]:
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return {}
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    h, w = y1 - y0 + 1, x1 - x0 + 1
    widths = {}
    # the top and bottom ~15% are skipped: seen from above, a round rim and base are ellipse arcs,
    # whose narrowing is perspective, not taper
    for f in (0.2, 0.35, 0.5, 0.65, 0.8):
        ext = _row_extent(mask, int(y0 + f * h))
        widths[f"{round(f * 100)}%"] = round((ext[1] - ext[0] + 1) / w, 3) if ext else None
    return {"height_to_width": round(h / w, 3), "width_profile": widths,
            "profile_note": "width / max width at % of height from the top; top and bottom 15% not measured (perspective)",
            "bbox_px": [x0, y0, x1, y1]}


def motif_stats(obj_mask: np.ndarray, instances: list[np.ndarray]) -> dict[str, Any]:
    """Elements of a pattern on a (roughly cylindrical) object seen from the side.

    Rows: centers clustered by height. Elements per row: from the pitch between neighbours
    near the object's centre line (least foreshortened), per_row ≈ π·width / pitch."""
    ys, xs = np.nonzero(obj_mask)
    if ys.size == 0 or len(instances) < 3:
        return {"instances_found": len(instances)}
    x0, x1 = xs.min(), xs.max()
    width = x1 - x0 + 1
    cx_obj = (x0 + x1) / 2
    items = []
    for m in instances:
        my, mx = np.nonzero(m)
        if my.size < 8:
            continue
        cx, cy = mx.mean(), my.mean()
        if not obj_mask[int(cy), int(cx)] and not (x0 <= cx <= x1):
            continue
        items.append((cx, cy, mx.max() - mx.min() + 1, my.max() - my.min() + 1))
    if len(items) < 3:
        return {"instances_found": len(items)}
    arr = np.array(items, float)
    med_w, med_h = float(np.median(arr[:, 2])), float(np.median(arr[:, 3]))
    order = arr[np.argsort(arr[:, 1])]
    rows: list[list[np.ndarray]] = [[order[0]]]
    for it in order[1:]:
        if abs(it[1] - np.mean([r[1] for r in rows[-1]])) > 0.45 * med_h:
            rows.append([it])
        else:
            rows[-1].append(it)
    pitches = []
    for row in rows:
        central = sorted(r[0] for r in row if abs(r[0] - cx_obj) < 0.35 * width)
        pitches += [b - a for a, b in zip(central, central[1:]) if b - a > 0.3 * med_w]
    pitch = float(np.median(pitches)) if pitches else None
    row_ys = sorted(np.mean([r[1] for r in row]) for row in rows)
    v_pitch = float(np.median(np.diff(row_ys))) if len(row_ys) > 1 else None
    oy = np.nonzero(obj_mask.any(axis=1))[0]
    obj_h = oy.max() - oy.min() + 1
    out: dict[str, Any] = {
        "instances_found": len(items),
        "visible_rows": len(rows),
        "element_width_to_object_width": round(med_w / width, 3),
        "element_height_to_object_height": round(med_h / obj_h, 3),
    }
    if pitch:
        out["horizontal_pitch_to_width"] = round(pitch / width, 3)
        # staggered rows put neighbours of one row two half-pitches apart
        out["estimated_per_row"] = int(round(math.pi * width / pitch))
    if v_pitch:
        out["estimated_rows_total"] = int(round(obj_h / v_pitch))
        out["vertical_pitch_to_height"] = round(v_pitch / obj_h, 3)
    return out


# ------------------------------------------------------------------ analyst
NAMES_SCHEMA = {
    "type": "object",
    "properties": {
        "object_phrase": {"type": "string", "description": "short noun phrase for the main object, e.g. 'planter'"},
        "motif_phrase": {"type": "string", "description": "short noun phrase for ONE repeated surface element, e.g. 'cube tile'; empty if none"},
        "motif_alternatives": {"type": "array", "items": {"type": "string"},
                               "description": "1-2 simpler single nouns for the same element, e.g. 'cube', 'bump'"},
    },
    "required": ["object_phrase", "motif_phrase", "motif_alternatives"],
}

DOSSIER_SCHEMA = {
    "type": "object",
    "properties": {
        "object": {"type": "object", "properties": {
            "what": {"type": "string"}, "function": {"type": "string"}, "construction": {"type": "string", "description": "how it is built: body type, wall, base, rim, parts"},
        }, "required": ["what", "function", "construction"]},
        "size": {"type": "object", "properties": {
            "basis": {"type": "string", "enum": ["measured", "reference", "stated", "assumed"]},
            "main_mm": {"type": "array", "items": {"type": "number"}, "description": "best estimate of overall size [x,y,z] in mm"},
            "uncertainty_mm": {"type": "number"}, "note": {"type": "string"},
        }, "required": ["basis", "main_mm", "uncertainty_mm", "note"]},
        "proportions": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "value": {"type": "number"}, "source": {"type": "string", "enum": ["measured", "estimated", "stated", "standard"]},
        }, "required": ["name", "value", "source"]}},
        "interfaces": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "value_mm": {"type": "number"}, "tolerance_mm": {"type": "number"},
            "source": {"type": "string"}, "how_to_confirm": {"type": "string"},
        }, "required": ["name", "value_mm", "tolerance_mm", "source", "how_to_confirm"]}},
        "motif": {"type": "object", "properties": {
            "hypotheses": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "library_element": {"type": "string", "description": "cubeCorner, hexPyramid, dome, stud, ribs, twist, facets, none, custom"},
                "confidence": {"type": "number"}, "evidence": {"type": "string"},
            }, "required": ["name", "library_element", "confidence", "evidence"]}},
            "per_row": {"type": "number"}, "rows": {"type": "number"}, "relief_to_element": {"type": "number", "description": "relief height / element width"},
            "arrangement": {"type": "string", "description": "staggered hex, square grid, spiral, ribs..."},
        }, "required": ["hypotheses", "per_row", "rows", "relief_to_element", "arrangement"]},
        "print_plan": {"type": "object", "properties": {
            "orientation": {"type": "string"}, "supports_needed": {"type": "boolean"}, "risks": {"type": "array", "items": {"type": "string"}},
        }, "required": ["orientation", "supports_needed", "risks"]},
        "unknowns": {"type": "array", "items": {"type": "object", "properties": {
            "question": {"type": "string"}, "resolve_by": {"type": "string", "enum": ["ask", "search", "assume", "probe"]}, "assumption": {"type": "string"},
        }, "required": ["question", "resolve_by", "assumption"]}},
        "search_queries": {"type": "array", "items": {"type": "string"}, "description": "at most 2, only for recognizable products/standards/landmarks"},
        "checklist": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "check": {"type": "string", "description": "verifiable statement about the finished model"},
            "verify_by": {"type": "string", "enum": ["photo", "render", "numbers"]}, "must": {"type": "boolean"},
        }, "required": ["id", "check", "verify_by", "must"]}},
    },
    "required": ["object", "size", "proportions", "interfaces", "motif", "print_plan", "unknowns", "search_queries", "checklist"],
}

ANALYST = """You are the analyst of a 3D-printing design team. Before anyone models, you write the object dossier.
Be exhaustive about what matters for reproducing and printing the object, and terse in wording.
- Use the MEASURED numbers given to you (from segmentation) for proportions and pattern counts; adjust them only
  with a stated reason (e.g. partial occlusion). outline_mm is metrology on a calibrated photo: use it as the size
  (basis 'measured', its uncertainty) and never replace it with a visual estimate. Do not invent millimetres: if there is no reference, size.basis
  is 'assumed' and you say what the assumption rests on (a typical product, a plant, a hand, a known object).
- Name the surface motif precisely and keep competing hypotheses with confidences summing to ~1. Map each to the
  library element that reproduces it:
  cubeCorner = a cube protruding corner-first: three square faces (rhombi in the photo) meet at an outward apex,
    a hexagonal outline ("isometric cubes", "cube studs on point", "diamond cubes");
  hexPyramid = six triangular faces meeting at an apex; dome = smooth round bump; stud = round peg (cylinder or
    cone), never for cubes; ribs; twist; facets (flat polygonal faces of the body itself).
  Use "custom" only when none fits, and say in evidence why the closest one does not.
- Interfaces are what must fit (pot inside, socket, screw, edge): give value, tolerance, source, how to confirm.
- Measured numbers come from one photo: perspective, shadows and occlusion distort them. Treat a ratio as a fact
  only when it is clearly visible; never turn a small deviation (under ~10%) into a requirement.
- The checklist is what a reviewer will verify on the finished model: 5-10 concrete, checkable items about what is
  visible in the photo or stated by the user (motif identity, counts, presence of features, interfaces,
  printability). Mark as must only the identity of the object and motif, stated sizes, interfaces and
  printability; proportions and counts estimated from the photo are not must.
- Never add requirements the user did not ask for (multi-part splits, extra features, finishes, colours): put such
  ideas in print_plan as options, not in the checklist.
- Short depth: when told depth=short, fill object, interfaces, unknowns, print_plan and checklist; keep the rest minimal."""


def _crop(img: np.ndarray, bbox: list[int], pad: float = 0.08) -> np.ndarray:
    x0, y0, x1, y1 = bbox
    h, w = img.shape[:2]
    px, py = int((x1 - x0) * pad), int((y1 - y0) * pad)
    return img[max(0, y0 - py): min(h, y1 + py), max(0, x0 - px): min(w, x1 + px)]


async def build(ctx: JobContext, *, pack: str, request: str, assets: list[dict[str, Any]], scene: dict[str, Any] | None,
                depth: str, language: str) -> dict[str, Any] | None:
    if depth == "off":
        return None
    from ..vision.common import asset_image, data_url
    from ..vision.sam import segment
    from ..vision.scene import measure_mask, without_reference

    images = [a for a in assets if a["kind"] in IMAGE_KINDS][:3]
    measured: dict[str, Any] = {}
    content: list[dict[str, Any]] = []
    cal = ((images[0].get("meta") or {}).get("calibration") or {}) if images else {}
    # a dark part on a white sheet is easily read as "a white plate with a hole"
    reference_note = (f"\nThe {cal.get('reference')} in the photo is only a scale reference, not the object: the object lies on it "
                      "or next to it.") if cal.get("ok") else ""
    if depth == "full" and images:
        await ctx.emit("tool.call", {"name": "dossier", "kind": "scene", "title": "Изучаю объект на фото" if language.startswith("ru") else "Studying the object in the photo"})
        img = asset_image(images[0])
        names = await meta().json(ctx.meter, model=ctx.models.fast, system="Name the main object and its repeated surface element.",
                                  content=[{"type": "input_text", "text": (request or "(photo only)") + reference_note},
                                           {"type": "input_image", "image_url": data_url(img, 1024)}],
                                  schema=NAMES_SCHEMA, name="names", effort="minimal")
        obj_phrase = names.get("object_phrase") or "object"
        try:
            objs = await segment(ctx.meter, img, text=obj_phrase)
        except Exception as e:  # noqa: BLE001
            log.info("dossier object segmentation failed: %s", e)
            objs = []
        objs = without_reference(objs, cal)
        if objs:
            obj = max(objs, key=lambda m: m.mask.sum())
            measured["silhouette"] = silhouette_ratios(obj.mask)
            if cal.get("ok"):  # a reference in the photo: millimetres from metrology, not from the eye
                mm = measure_mask(obj.mask, cal, image=img)
                if mm.get("calibrated"):
                    measured["outline_mm"] = {k: mm.get(k) for k in ("size_mm", "uncertainty_mm", "holes_mm")} | {"reference": cal.get("reference")}
            phrases = [p for p in [names.get("motif_phrase"), *(names.get("motif_alternatives") or [])[:2]] if p]
            for motif in phrases:  # a precise phrase can find nothing where a plain noun finds every element
                try:
                    inst = await segment(ctx.meter, img, text=motif)
                except Exception as e:  # noqa: BLE001
                    log.info("dossier motif segmentation failed: %s", e)
                    continue
                stats = {"phrase": motif, **motif_stats(obj.mask, [m.mask for m in inst])}
                if stats["instances_found"] > measured.get("motif", {}).get("instances_found", -1):
                    measured["motif"] = stats
                if stats["instances_found"] >= 6:
                    break
            crop = _crop(img, measured["silhouette"]["bbox_px"])
            content.append({"type": "input_text", "text": "Close-up of the object:"})
            content.append({"type": "input_image", "image_url": data_url(crop, 1400)})
        measured["object_phrase"] = obj_phrase
    lines = [f"Depth: {depth}. Pack: {pack}. Reply language for human-readable strings: {language}.",
             f"Request: {request or '(photo only)'}{reference_note}",
             "Measured by segmentation (pixels, scale-free): " + json.dumps(measured, ensure_ascii=False) if measured else "No segmentation measurements.",]
    if scene:
        lines.append("Calibrated scene measurements (mm): " + json.dumps({k: v for k, v in scene.items() if k != "inputs"}, ensure_ascii=False)[:4000])
    content = [{"type": "input_text", "text": "\n".join(lines)}] + [
        {"type": "input_image", "image_url": storage.data_url(a["path"], 1280)} for a in images
    ] + content
    dossier = await meta().json(ctx.meter, model=ctx.models.fast, system=ANALYST, content=content, schema=DOSSIER_SCHEMA,
                                name="dossier", effort="high" if depth == "full" else "low", max_output_tokens=14000)
    if not dossier:
        return None
    dossier["depth"] = depth
    dossier["measured"] = measured
    facts = []
    for q in (dossier.get("search_queries") or [])[:2 if depth == "full" else 1]:
        try:
            r = await search_dimensions(ctx.meter, q, ctx.user["id"], ctx.models.fast)
            facts += [{k: f.get(k) for k in ("subject", "attribute", "value", "unit", "source_url", "confidence")} for f in r["facts"]][:8]
        except Exception as e:  # noqa: BLE001
            log.info("dossier search failed: %s", e)
    if facts:
        dossier["facts"] = facts
        await ctx.emit("facts", {"items": facts})
    return dossier


def summary_title(d: dict[str, Any], language: str) -> str:
    ru = language.startswith("ru")
    motif = (d.get("motif") or {})
    hyp = sorted(motif.get("hypotheses") or [], key=lambda h: -h.get("confidence", 0))
    parts = [d.get("object", {}).get("what", "")]
    if hyp and hyp[0].get("library_element") not in (None, "none"):
        parts.append(f"{hyp[0]['name']} {int(hyp[0].get('confidence', 0) * 100)}%")
        if motif.get("per_row"):
            parts.append((f"{int(motif['per_row'])} в ряду × {int(motif.get('rows') or 0)} рядов") if ru else f"{int(motif['per_row'])} per row × {int(motif.get('rows') or 0)} rows")
    parts.append((f"пунктов проверки: {len(d.get('checklist') or [])}") if ru else f"checklist items: {len(d.get('checklist') or [])}")
    return ("Досье: " if ru else "Dossier: ") + "; ".join(p for p in parts if p)


def for_designer(d: dict[str, Any]) -> str:
    keep = {k: d.get(k) for k in ("object", "size", "proportions", "interfaces", "motif", "print_plan", "unknowns", "checklist", "facts", "measured")}
    return "# Object dossier (analysis done before modelling; measured values come from segmentation)\n" + json.dumps(keep, ensure_ascii=False)[:9000]
