"""Board scan: a photo of an electronics board -> a fw.board/1 JSON (packages/geom/src/board.schema.json)
that lib.elec builds a case around.

SAM 3.1 finds the board, its mounting holes and the USB port; Muse Spark then reads the silkscreen
literally (on a crop of the board when it is small in the photo), picks the board from the dataset
(boards.json) when the marking or the layout matches, and boxes the parts that matter for a case. The scale comes from the board's own mounting holes: once the board is known
the dataset says where its holes are, so the photo needs no A4 sheet (the 4 holes give a homography;
which mask is which hole is decided by the fit, the mirror of a top view and where the USB ends up).
Boards without holes, or unknown ones, fall back to the A4 sheet or bank card (scene.calibrate) and the
board's outline. Dataset numbers win: the photo gives deltas to check them and replaces a 'verify'
position only when it measured it more precisely. Heights never come from a top view (parallax):
they are the dataset's or the typical part's, marked verify.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import re
from functools import lru_cache
from itertools import combinations, permutations
from typing import Any

import cv2
import numpy as np

from ..config import settings
from ..llm.client import CostMeter, meta
from .common import asset_image, data_url, norm_box_to_px
from .sam import Mask, largest_component, segment

log = logging.getLogger(__name__)

HOLE_PROMPT = "mounting hole"
PORT_PROMPT = "USB port"
BOARD_PROMPT = "circuit board"
MIN_SCORE = 0.3
EDGE_MM = 1.5  # a part this close to (or past) the outline is a connector on that edge
SPARK_BOX_MM = 0.8  # 1-sigma of a part centre from a Spark box
DATASET_MM = 0.5  # 1-sigma of a dataset number marked verify (scaled from a drawing), unless it says otherwise
MAX_HOLE_CANDIDATES = 8
REFINE_MAX = 2  # buttons refined by a SAM box prompt (one call each)
SPARK_SIDE = 1280  # a crop smaller than this is enlarged for Spark: small silkscreen reads better
IMAGE_KINDS = ("photo", "sketch", "caliper", "concept", "render", "print")

# Spark's part types -> keys of the dataset's `typical` table (heights, depths and plug sizes of common parts)
TYPICAL = {"usb_c": "usb_c", "usb_micro_b": "usb_micro_b", "usb_mini_b": "usb_mini_b", "usb_a": "usb_a_single", "usb_b": "usb_b",
           "rj45": "rj45", "hdmi": "hdmi_micro", "dc_jack": "dc_barrel_5_5", "audio_jack": "audio_3_5", "sd_card": "microsd_push",
           "fpc": "fpc_22p_0_5", "led": "led_0603", "pin_header": "pin_header_2_54", "module": "wroom_32_module"}
CONNECTORS = {"usb_c", "usb_micro_b", "usb_mini_b", "usb_a", "usb_b", "rj45", "hdmi", "dc_jack", "audio_jack", "sd_card", "fpc"}
SHIELD_H = 1.6  # a typical RF shield can (no `typical` entry)


@lru_cache
def dataset() -> dict[str, Any]:
    return json.loads((settings().geom_dir / "src" / "boards.json").read_text(encoding="utf-8"))


@lru_cache
def board_schema() -> dict[str, Any]:
    return json.loads((settings().geom_dir / "src" / "board.schema.json").read_text(encoding="utf-8"))


def boards() -> list[dict[str, Any]]:
    return dataset()["boards"]


def find_board(key: str | None) -> dict[str, Any] | None:
    """A dataset board by id, name or one of its markings (case-insensitive), as a fresh copy."""
    if not key:
        return None
    k = key.strip().lower()
    for b in boards():
        if k == b["id"].lower() or k == b["name"].lower() or k in (a.lower() for a in b.get("aliases", [])):
            return copy.deepcopy(b)
    return None


def catalog_text() -> str:
    return "\n".join(f"- {b['id']}: {b['name']} (markings: {', '.join(b.get('aliases', []))}; "
                     f"{b['pcb']['outline']['w']} x {b['pcb']['outline']['h']} mm, {len(b['pcb']['holes'])} mounting holes)" for b in boards())


# ------------------------------------------------------------------ fw.board/1 validation
def schema_errors(doc: Any, schema: dict[str, Any] | None = None) -> list[str]:
    """Errors of `doc` against board.schema.json: the subset of JSON Schema 2020-12 it uses
    (type, const, enum, required, properties, additionalProperties, items, min/maxItems, numeric bounds,
    oneOf, allOf, if/then/else, local $ref). Empty when the board is valid."""
    root = schema or board_schema()

    def resolve(ref: str) -> dict[str, Any]:
        node: Any = root
        for key in ref.lstrip("#/").split("/"):
            node = node[key]
        return node

    def is_type(v: Any, t: str) -> bool:
        return {"object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str), "boolean": isinstance(v, bool),
                "null": v is None, "integer": isinstance(v, int) and not isinstance(v, bool),
                "number": isinstance(v, (int, float)) and not isinstance(v, bool)}.get(t, True)

    def check(v: Any, s: dict[str, Any], path: str) -> list[str]:
        if "$ref" in s:
            return check(v, resolve(s["$ref"]), path)
        errs: list[str] = []
        t = s.get("type")
        if t and not any(is_type(v, x) for x in ([t] if isinstance(t, str) else t)):
            return [f"{path}: must be {t}"]
        if "const" in s and v != s["const"]:
            errs.append(f"{path}: must be {s['const']!r}")
        if "enum" in s and v not in s["enum"]:
            errs.append(f"{path}: must be one of {s['enum']}")
        if is_type(v, "number"):
            if "minimum" in s and v < s["minimum"]:
                errs.append(f"{path}: must be >= {s['minimum']}")
            if "maximum" in s and v > s["maximum"]:
                errs.append(f"{path}: must be <= {s['maximum']}")
            if "exclusiveMinimum" in s and v <= s["exclusiveMinimum"]:
                errs.append(f"{path}: must be > {s['exclusiveMinimum']}")
        if isinstance(v, dict):
            errs += [f"{path}: missing {k}" for k in s.get("required", []) if k not in v]
            props = s.get("properties", {})
            for k, sub in props.items():
                if k in v:
                    errs += check(v[k], sub, f"{path}.{k}")
            extra = s.get("additionalProperties")
            if isinstance(extra, dict):
                for k in v:
                    if k not in props:
                        errs += check(v[k], extra, f"{path}.{k}")
        if isinstance(v, list):
            if "minItems" in s and len(v) < s["minItems"]:
                errs.append(f"{path}: needs at least {s['minItems']} items")
            if "maxItems" in s and len(v) > s["maxItems"]:
                errs.append(f"{path}: at most {s['maxItems']} items")
            if isinstance(s.get("items"), dict):
                for i, x in enumerate(v):
                    errs += check(x, s["items"], f"{path}[{i}]")
        if "oneOf" in s:
            fits = sum(1 for sub in s["oneOf"] if not check(v, sub, path))
            if fits != 1:
                errs.append(f"{path}: must match exactly one of {len(s['oneOf'])} shapes (matches {fits})")
        for sub in s.get("allOf", []):
            errs += check(v, sub, path)
        if "if" in s:
            branch = s.get("then") if not check(v, s["if"], path) else s.get("else")
            if branch:
                errs += check(v, branch, path)
        return errs

    return check(doc, root, "board")


# ------------------------------------------------------------------ identify (Muse Spark)
PART_TYPES = ["usb_c", "usb_micro_b", "usb_mini_b", "usb_a", "usb_b", "rj45", "hdmi", "dc_jack", "audio_jack", "sd_card", "fpc",
              "button", "led", "pin_header", "mounting_hole", "antenna", "shield", "module", "other"]
IDENTIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "board_id": {"type": "string", "description": "id from the catalog, or 'unknown'"},
        "marking": {"type": "string", "description": "the silkscreen / chip text you actually read"},
        "confidence": {"type": "number"},
        "side": {"type": "string", "enum": ["top", "bottom"]},
        "board_box": {"type": "array", "items": {"type": "number"}, "description": "the whole board, [x_min, y_min, x_max, y_max] on a 0-1000 grid"},
        "parts": {"type": "array", "items": {"type": "object", "properties": {
            "type": {"type": "string", "enum": PART_TYPES},
            "label": {"type": "string"},
            "box": {"type": "array", "items": {"type": "number"}, "description": "[x_min, y_min, x_max, y_max] on a 0-1000 grid"},
            "at_edge": {"type": "boolean"}}, "required": ["type", "label", "box", "at_edge"]}},
    },
    "required": ["board_id", "marking", "confidence", "side", "board_box", "parts"],
}
IDENTIFY_SYSTEM = (
    "You identify electronics dev boards on photos for an enclosure designer. Read the silkscreen and chip markings "
    "literally (do not guess text you cannot read). Pick the board from the catalog only when the marking or the layout "
    "matches; otherwise answer 'unknown'. Box the whole board, then every part that matters for an enclosure: connectors "
    "on the board edge, buttons, LEDs, mounting holes, antenna area, shield cans, modules. Boxes are tight, on a 0-1000 grid "
    "of the image. A sheet of paper or a card under the board is only a scale reference. Catalog:\n"
)


async def identify(meter: CostMeter, img: np.ndarray, hint: str | None, model: str) -> dict[str, Any]:
    text = "Which board is this, and where are its enclosure-relevant parts?"
    if hint:
        text += f" The person says: {hint[:200]}"
    return await meta().json(meter, model=model, system=IDENTIFY_SYSTEM + catalog_text(),
                             content=[{"type": "input_text", "text": text}, {"type": "input_image", "image_url": data_url(img, 1600, quality=92)}],
                             schema=IDENTIFY_SCHEMA, name="board_identify", effort="low", max_output_tokens=6000, purpose="board identification")


# ------------------------------------------------------------------ transforms (pixels -> board mm)
def apply_h(H: np.ndarray, pts: Any) -> np.ndarray:
    p = np.asarray(pts, dtype=float).reshape(-1, 2)
    hom = np.hstack([p, np.ones((len(p), 1))]) @ H.T
    return hom[:, :2] / hom[:, 2:3]


def jacobian_det(H: np.ndarray, at: Any) -> float:
    """Signed area scale of px -> mm at a pixel: negative for a top view (image y points down, board y up)."""
    x, y = float(at[0]), float(at[1])
    p = apply_h(H, [[x, y], [x + 1, y], [x, y + 1]])
    a, b = p[1] - p[0], p[2] - p[0]
    return float(a[0] * b[1] - a[1] * b[0])


def similarity(src: np.ndarray, dst: np.ndarray, mirror: bool) -> tuple[np.ndarray, float]:
    """Least-squares similarity src -> dst (Umeyama) with a fixed handedness, and its worst residual."""
    s = np.asarray(src, float).copy()
    if mirror:
        s[:, 0] = -s[:, 0]
    d = np.asarray(dst, float)
    ms, md = s.mean(axis=0), d.mean(axis=0)
    a, b = s - ms, d - md
    var = (a ** 2).sum() / len(s)
    if var < 1e-9:
        return np.eye(3), math.inf
    U, S, Vt = np.linalg.svd(b.T @ a / len(s))
    D = np.diag([1.0, -1.0 if np.linalg.det(U @ Vt) < 0 else 1.0])
    R = U @ D @ Vt
    k = float(np.trace(np.diag(S) @ D) / var)
    M = np.eye(3)
    M[:2, :2] = k * R
    M[:2, 2] = md - k * R @ ms
    if mirror:
        M = M @ np.diag([-1.0, 1.0, 1.0])
    res = float(np.abs(apply_h(M, src) - d).max())
    return M, res


def mm_per_px(H: np.ndarray, at: Any) -> float:
    return math.sqrt(abs(jacobian_det(H, at)))


def _r(v: float, nd: int = 2) -> float:
    return round(float(v), nd)


# ------------------------------------------------------------------ detections
def _centroid(m: Mask) -> np.ndarray:
    ys, xs = np.nonzero(m.mask)
    return np.array([xs.mean(), ys.mean()]) if len(xs) else np.array([(m.bbox_px[0] + m.bbox_px[2]) / 2, (m.bbox_px[1] + m.bbox_px[3]) / 2])


def _size_px(m: Mask) -> float:
    return float(max(m.bbox_px[2] - m.bbox_px[0], m.bbox_px[3] - m.bbox_px[1]))


def _rect_mm(H: np.ndarray, m: Mask) -> list[float] | None:
    """Extents [x0, y0, x1, y1] in mm of a mask's largest blob: its outline moved onto the pixel edges, through H."""
    from .scene import offset_px

    cs, _ = cv2.findContours(largest_component(m.mask).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(float)
    if len(c) < 4:
        return None
    pts = apply_h(H, offset_px(c, 0.5))
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    return [float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])]


def _box_corners(box_px: list[float]) -> np.ndarray:
    x1, y1, x2, y2 = box_px
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], float)


def _grid_px(box: list[float], view: tuple[int, int, int, int]) -> list[int]:
    """A Spark box (0-1000 grid of the image it saw) in pixels of the whole photo; view = (x0, y0, w, h) of what it saw."""
    x0, y0, w, h = view
    b = norm_box_to_px(box, w, h)
    return [b[0] + x0, b[1] + y0, b[2] + x0, b[3] + y0]


def _spark_parts(ident: dict[str, Any], view: tuple[int, int, int, int]) -> list[dict[str, Any]]:
    out = []
    for p in ident.get("parts") or []:
        if not isinstance(p, dict) or len(p.get("box") or []) != 4:
            continue
        box = _grid_px(p["box"], view)
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            continue
        out.append({"type": p.get("type") or "other", "label": str(p.get("label") or p.get("type") or "part")[:40], "box": box,
                    "at_edge": bool(p.get("at_edge")), "centre": np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])})
    return out


def _port_point(c: dict[str, Any], W: float, H: float) -> np.ndarray:
    """Where a dataset connector meets its edge, in the board frame."""
    at = float(c.get("at", 0))
    return {"+y": np.array([at, H]), "-y": np.array([at, 0.0]), "-x": np.array([0.0, at]), "+x": np.array([W, at])}.get(c.get("edge", "+y"), np.array([at, H]))


def _comp_centre(c: dict[str, Any], W: float, H: float) -> np.ndarray:
    return _port_point(c, W, H) if c.get("access") == "port" else np.array([float(c.get("x", 0)), float(c.get("y", 0))])


def _matches(spec: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Dataset components a detection of `kind` can be."""
    comps = spec.get("components", [])
    if kind == "usb":
        return [c for c in comps if c.get("access") == "port" and str(c.get("type", "")).startswith("usb")]
    if kind == "button":
        return [c for c in comps if c.get("access") == "press"]
    if kind == "led":
        return [c for c in comps if c.get("access") == "light"]
    if kind == "shield":
        return [c for c in comps if c.get("type") == "shield"]
    if kind in CONNECTORS:
        return [c for c in comps if c.get("access") == "port"]
    return []


def _kind(spark_type: str) -> str:
    return "usb" if spark_type.startswith("usb") else spark_type


def orientation_term(H: np.ndarray, spec: dict[str, Any], usb: list[Mask], parts: list[dict[str, Any]]) -> tuple[float, int]:
    """Mean distance (mm) from the detected parts, mapped through H, to the dataset parts they can be:
    small for the right placement of the board, tens of mm for a hole pattern turned the wrong way round."""
    W, Hh = float(spec["pcb"]["outline"]["w"]), float(spec["pcb"]["outline"]["h"])
    terms: list[tuple[float, float]] = []
    for m in usb[:3]:
        cands = _matches(spec, "usb")
        if cands:
            p = apply_h(H, [_centroid(m)])[0]
            terms.append((min(float(np.hypot(*(p - _comp_centre(c, W, Hh)))) for c in cands), 1.0))
    for sp in parts:
        cands = _matches(spec, _kind(sp["type"]))
        if cands and not (usb and _kind(sp["type"]) == "usb"):
            p = apply_h(H, [sp["centre"]])[0]
            terms.append((min(float(np.hypot(*(p - _comp_centre(c, W, Hh)))) for c in cands), 0.5))
    if not terms:
        return 0.0, 0
    return sum(d * w for d, w in terms) / sum(w for _, w in terms), len(terms)


# ------------------------------------------------------------------ calibration
def calibrate_by_holes(holes: list[Mask], spec: dict[str, Any], side: str, usb: list[Mask], parts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Which hole masks are the dataset's mounting holes, and the pixel -> board homography they give.
    Every assignment of the largest masks to the template is fitted as a similarity of the right handedness;
    the fit residual rejects wrong sets, the parts term picks between the turns of a symmetric pattern."""
    mounts = [h for h in spec["pcb"]["holes"] if h.get("use", "mount") == "mount"]
    template = np.array([[h["x"], h["y"]] for h in mounts], float)
    k = len(template)
    if k < 2:
        return None
    cands = sorted([m for m in holes if m.score >= MIN_SCORE], key=_size_px, reverse=True)[:MAX_HOLE_CANDIDATES]
    if len(cands) < min(k, 4):
        return None
    pts = np.array([_centroid(m) for m in cands])
    use_k = min(k, 4)
    span = float(np.ptp(template, axis=0).max())
    hole_d = float(np.median([h["d"] for h in mounts]))
    mirror = side != "bottom"
    best = None
    for tsel in combinations(range(k), use_k):
        dst = template[list(tsel)]
        for csel in combinations(range(len(cands)), use_k):
            sizes = [_size_px(cands[i]) for i in csel]
            if max(sizes) > 1.6 * min(sizes):
                continue  # a mounting hole and a pin pad are not the same feature
            for perm in permutations(csel):
                src = pts[list(perm)]
                M, res = similarity(src, dst, mirror)
                if not math.isfinite(res) or res > max(0.8, 0.06 * span):
                    continue
                k_mm = mm_per_px(M, src.mean(axis=0))
                ring = float(np.mean(sizes)) * k_mm
                if not 0.6 * hole_d <= ring <= 3 * hole_d:
                    continue  # SAM's mask is the hole, sometimes with some of its pad
                Hm = cv2.findHomography(src, dst)[0] if use_k == 4 else M
                if Hm is None:
                    continue
                term, n = orientation_term(Hm, spec, usb, parts)
                score = res + 0.5 * term
                if best is None or score < best["score"]:
                    best = {"score": score, "H": Hm, "src": src, "dst": dst, "sel": list(perm), "pattern_mm": res, "parts_mm": term, "parts_n": n}
    if best is None or (use_k == 2 and best["parts_n"] == 0):
        return None  # two holes alone fit any pair of masks; without a part to place them it is a guess
    H = best["H"]
    reproj = float(np.abs(apply_h(H, best["src"]) - best["dst"]).max())
    centre = best["src"].mean(axis=0)
    return {
        "method": "board_holes", "H": H, "holes_px": [[_r(v, 1) for v in p] for p in best["src"]], "holes_mm": best["dst"].round(3).tolist(),
        "mask_ids": [cands[i].id for i in best["sel"]], "residual_mm": _r(reproj, 3), "pattern_mm": _r(best["pattern_mm"], 3),
        "parts_mm": _r(best["parts_mm"], 2), "parts_matched": best["parts_n"], "mm_per_px": _r(mm_per_px(H, centre), 5),
        "uncertainty_mm": _r(math.hypot(best["pattern_mm"] / 2, 1.0 * mm_per_px(H, centre)), 3),
    }


def calibrate_by_corners(corners_px: np.ndarray, to_sheet: np.ndarray | None, W: float, Hh: float, side: str,
                         spec: dict[str, Any] | None, usb: list[Mask], parts: list[dict[str, Any]], method: str) -> dict[str, Any] | None:
    """The board's own corners (from its SAM outline) onto the rectangle W x Hh: through the reference plane
    when `to_sheet` (pixels -> sheet mm) is given, else straight from pixels. Every turn of the rectangle is
    tried; side lengths and, for a dataset board, the parts decide."""
    src_px = np.asarray(corners_px, float).reshape(4, 2)
    rect = np.array([[0, 0], [W, 0], [W, Hh], [0, Hh]], float)
    top = side != "bottom"
    best = None
    for shift in range(4):
        for order in (1, -1):
            src = src_px[[(shift + order * i) % 4 for i in range(4)]]
            if to_sheet is not None:
                # the sheet is seen from above like the board: sheet -> board is a plain rotation for its top side
                sheet = apply_h(to_sheet, src)
                _, res = similarity(sheet, rect, not top)
                Hs = cv2.findHomography(sheet, rect)[0]
                H = None if Hs is None else Hs @ to_sheet
            else:
                _, res = similarity(src, rect, top)
                H = cv2.findHomography(src, rect)[0]
            if H is None or not math.isfinite(res) or (jacobian_det(H, src.mean(axis=0)) < 0) != top:
                continue
            if spec:
                term, n = orientation_term(H, spec, usb, parts)
                score = res + 0.5 * term
            else:
                # an unknown board has no ends to tell apart: its x runs the way the photo reads
                term, n = 0.0, 0
                a, b = apply_h(np.linalg.inv(H), [[0, 0], [1, 0]])
                score = res + 0.01 * (1 - (b[0] - a[0]) / max(1e-9, float(np.hypot(*(b - a)))))
            if best is None or score < best["score"]:
                best = {"score": score, "H": H, "res": res, "term": term, "n": n, "src": src}
    if best is None or best["res"] > max(1.5, 0.08 * max(W, Hh)):
        return None
    H = best["H"]
    centre = best["src"].mean(axis=0)
    out = {"method": method, "H": H, "corners_px": [[_r(v, 1) for v in p] for p in best["src"]], "residual_mm": _r(best["res"], 3),
           "parts_mm": _r(best["term"], 2), "parts_matched": best["n"], "mm_per_px": _r(mm_per_px(H, centre), 5),
           "uncertainty_mm": _r(math.hypot(best["res"] / 2, 1.5 * mm_per_px(H, centre)), 3)}
    if to_sheet is not None:
        sheet = apply_h(to_sheet, best["src"])
        sides = [float(np.hypot(*(sheet[(i + 1) % 4] - sheet[i]))) for i in range(4)]
        out["measured_mm"] = [_r((sides[0] + sides[2]) / 2), _r((sides[1] + sides[3]) / 2)]
    return out


def _quad(mask: np.ndarray) -> np.ndarray | None:
    from .geometry import fit_quad

    m = largest_component(mask)
    q = fit_quad(m)
    if q is not None:
        return q
    cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return None
    return cv2.boxPoints(cv2.minAreaRect(max(cs, key=cv2.contourArea))).astype(float)


def _sheet_h(cal: dict[str, Any]) -> np.ndarray | None:
    """Pixels -> reference-plane mm of a scene calibration (A4 / card homography, or a coin's scale)."""
    from . import geometry as g

    plane = g.calibration_from_dict(cal)
    if plane is not None:
        return plane.H_px2mm
    if cal.get("kind") == "scale_only":
        k, c = float(cal["mm_per_px"]), np.array(cal.get("center_px", [0, 0]), float)
        return np.array([[k, 0, -k * c[0]], [0, -k, k * c[1]], [0, 0, 1.0]])
    return None


def _corner_calibration(mask: np.ndarray, cal: dict[str, Any] | None, W: float | None, Hh: float | None, side: str,
                        spec: dict[str, Any] | None, usb: list[Mask], parts: list[dict[str, Any]],
                        offset: tuple[int, int] = (0, 0)) -> dict[str, Any] | None:
    """Scale from the board's outline: through the reference plane of the whole photo (`cal`, A4 or card) when there is
    one, else onto the dataset's rectangle. `mask` is in the pixels of a crop that starts at `offset` in the photo."""
    corners = _quad(mask)
    if corners is None:
        return None
    to_sheet = _sheet_h(cal) if cal else None
    if to_sheet is not None:
        to_sheet = to_sheet @ np.array([[1, 0, offset[0]], [0, 1, offset[1]], [0, 0, 1.0]])
    kind = (cal or {}).get("reference_kind")
    method = "board_outline" if to_sheet is None else "card" if kind == "card" else "a4" if kind == "sheet" else str(kind or "reference")
    if W is None or Hh is None:
        if to_sheet is None:
            return None
        sheet = apply_h(to_sheet, corners)
        sides = [float(np.hypot(*(sheet[(i + 1) % 4] - sheet[i]))) for i in range(4)]
        a, b = (sides[0] + sides[2]) / 2, (sides[1] + sides[3]) / 2
        W, Hh = round(max(a, b), 1), round(min(a, b), 1)  # unknown boards: x along the long side
    out = calibrate_by_corners(corners, to_sheet, W, Hh, side, spec, usb, parts, method)
    if out:
        out["size_mm"] = [W, Hh]
        if to_sheet is not None:
            out["reference"] = cal.get("reference")  # type: ignore[union-attr]
    return out


def pin_rows(H: np.ndarray, holes: list[Mask], used: set[str], spec: dict[str, Any]) -> dict[str, Any] | None:
    """Castellated pads on the photo against the dataset's rows: an independent check of the scale."""
    cast = spec["pcb"].get("castellations") or {}
    rows = cast.get("rows_x") or []
    if not rows:
        return None
    Hh = float(spec["pcb"]["outline"]["h"])
    pts = apply_h(H, [_centroid(m) for m in holes if m.id not in used and m.score >= MIN_SCORE]) if holes else np.zeros((0, 2))
    found = []
    for x in rows:
        near = [p[0] for p in pts if abs(p[0] - x) < 1.0 and -1 <= p[1] <= Hh + 1]
        found.append({"x": x, "photo": _r(float(np.mean(near))) if near else None, "pads": len(near)})
    return {"rows_x": [f["photo"] for f in found], "dataset_rows_x": rows, "pads": [f["pads"] for f in found]}


# ------------------------------------------------------------------ parts on the board
def _edge_of(rect: list[float], W: float, Hh: float) -> tuple[str, float] | None:
    x0, y0, x1, y1 = rect
    gaps = {"-x": x0, "+x": W - x1, "-y": y0, "+y": Hh - y1}
    edge = min(gaps, key=gaps.get)  # type: ignore[arg-type]
    return (edge, gaps[edge]) if gaps[edge] <= EDGE_MM else None


def _port_numbers(rect: list[float], edge: str, W: float, Hh: float) -> dict[str, float]:
    x0, y0, x1, y1 = rect
    if edge in ("+y", "-y"):
        at, w = (x0 + x1) / 2, x1 - x0
        protrude = (y1 - Hh) if edge == "+y" else -y0
    else:
        at, w = (y0 + y1) / 2, y1 - y0
        protrude = (x1 - W) if edge == "+x" else -x0
    return {"at": _r(at), "w": _r(w), "protrude": _r(max(0.0, protrude))}


def _typical(key: str | None) -> dict[str, Any]:
    return dict(dataset().get("typical", {}).get(key or "", {})) if key else {}


def _component(det: dict[str, Any], rect: list[float], W: float, Hh: float, n: int, unc: float) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """A detection on an unknown board -> (component, keep-out). Heights, depths and plugs are typical, marked verify."""
    typ = det["type"]
    x0, y0, x1, y1 = rect
    cx, cy, w, d = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
    ev = det.get("evidence") or {}
    if typ == "antenna":
        r = [_r(max(-0.5, x0)), _r(max(-0.5, y0)), _r(min(W + 0.5, x1)), _r(min(Hh + 0.5, y1))]
        return None, {"id": f"antenna{n or ''}", "rect": r, "z": [-20, 40], "rule": "no_metal", "verify": ["rect"],
                      "note": "antenna area boxed on the photo: no metal fasteners here"}
    if typ in ("mounting_hole", "other"):
        return None, None
    cid = re.sub(r"[^a-z0-9_]+", "_", det["label"].lower()).strip("_")[:24] or typ
    edge = _edge_of(rect, W, Hh) if typ in CONNECTORS else None
    tkey = TYPICAL.get(typ) or ("tact_3x4_smd" if typ == "button" and max(w, d) < 4.6 else "tact_6x6" if typ == "button" else None)
    t = _typical(tkey)
    if typ in CONNECTORS and edge:
        nums = _port_numbers(rect, edge[0], W, Hh)
        comp = {"id": cid, "type": tkey or typ, "side": "top", "access": "port", "edge": edge[0], "at": nums["at"], "w": nums["w"],
                "h": float(t.get("h", 3.0)), "d": float(t.get("d", max(w, d))), "z0": 0, "protrude": nums["protrude"],
                "plug": list(t["plug"]) if t.get("plug") else None, "verify": ["h", "d", "protrude"] + (["plug"] if t.get("plug") else []),
                "uncertainty_mm": unc, "evidence": ev,
                "note": "measured on a top view: the overhang includes parallax of the tall shell; height, depth and plug are typical"}
        return comp, None
    access = "press" if typ == "button" else "light" if typ == "led" else "cable" if typ in CONNECTORS or typ == "pin_header" else "none"
    h = float(t.get("h", t.get("body_h", SHIELD_H if typ == "shield" else 1.0)))
    if typ == "pin_header":
        h = 0.0  # unpopulated until the person says otherwise
    comp = {"id": cid, "type": tkey or typ, "side": "top", "access": access, "x": _r(cx), "y": _r(cy), "w": _r(w), "d": _r(d), "h": h,
            "normal": [0, 0, 1], "verify": ["h"], "uncertainty_mm": unc, "evidence": ev}
    if typ == "pin_header":
        comp["note"] = "header footprint; h 0 means no pins soldered (set h and heights.bottom_max if they are)"
    return comp, None


def _unique_ids(comps: list[dict[str, Any]]) -> None:
    seen: dict[str, int] = {}
    for c in comps:
        base = c["id"]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            c["id"] = f"{base}{seen[base]}"


# ------------------------------------------------------------------ the scan
async def _segment(meter: CostMeter, img: np.ndarray, **kw: Any) -> list[Mask]:
    try:
        return await segment(meter, img, **kw)
    except Exception as e:  # noqa: BLE001 - one prompt failing leaves the others
        log.warning("board scan: SAM %s failed: %s", kw.get("text") or "box", e)
        return []


async def _refine_button(meter: CostMeter, img: np.ndarray, sp: dict[str, Any]) -> Mask | None:
    """SAM by box on a Spark button box: SAM's concept prompt misses small buttons, a box prompt usually does not."""
    x1, y1, x2, y2 = sp["box"]
    pad = 0.15 * max(x2 - x1, y2 - y1)
    masks = await _segment(meter, img, box=[x1 - pad, y1 - pad, x2 + pad, y2 + pad])
    area = (x2 - x1) * (y2 - y1)
    for m in masks:
        c = _centroid(m)
        if m.score >= MIN_SCORE and 0.25 * area <= m.area <= 1.6 * area and x1 <= c[0] <= x2 and y1 <= c[1] <= y2:
            return m
    return None


def _box(label: str, box: list[float], score: float | None, kind: str, source: str, emphasis: str) -> dict[str, Any]:
    return {"label": label, "box": [int(round(v)) for v in box], "score": None if score is None else _r(score, 3), "kind": kind,
            "source": source, "emphasis": emphasis}


async def scan_board(meter: CostMeter, asset: dict[str, Any], hint: str | None = None, name: str = "board", *, model: str | None = None,
                     refine: bool = True) -> dict[str, Any]:
    """A photo of a board -> {board (fw.board/1), boxes [{label, box px, score, kind, source, emphasis}], calibration, deltas,
    identified, selection, warnings}. Raises ValueError when the photo gives no scale and the board is not in the dataset."""
    if asset.get("kind") not in IMAGE_KINDS:
        raise ValueError("board scans work on photos")
    img = asset_image(asset)
    h, w = img.shape[:2]
    model = model or settings().model_fast
    # The board first (SAM, about 2 s). On a whole A4 sheet the board is small: SAM's concept prompts then miss its
    # holes and connectors (seen on a 3200 px photo), and Spark reads less. Both look at a crop of the board instead;
    # everything below works in the crop's pixels and only the boxes go back to the photo's.
    board_full = _pick_board(await _segment(meter, img, text=BOARD_PROMPT), w, h)
    view = _view(board_full, w, h)
    x0, y0, vw, vh = view
    crop = img[y0:y0 + vh, x0:x0 + vw]
    board_mask = board_full[y0:y0 + vh, x0:x0 + vw] if board_full is not None else None
    ident, holes, usb = await asyncio.gather(identify(meter, _at_least(crop, SPARK_SIDE), hint, model), _segment(meter, crop, text=HOLE_PROMPT),
                                             _segment(meter, crop, text=PORT_PROMPT))
    holes = [m for m in holes if m.score >= MIN_SCORE]
    usb = [m for m in usb if m.score >= MIN_SCORE]
    parts = _spark_parts(ident, (0, 0, vw, vh))
    side = "bottom" if ident.get("side") == "bottom" else "top"
    board_id = str(ident.get("board_id") or "unknown")
    spec = find_board(board_id) if board_id != "unknown" else None
    warnings: list[str] = []
    if spec is None and hint and find_board(hint):
        spec = find_board(hint)
        warnings.append(f"the photo did not identify the board; using the dataset board the request names ({spec['id']})")  # type: ignore[index]
    marking = str(ident.get("marking") or "")[:120]

    # buttons are refined by SAM box prompts while the scale is worked out
    buttons = [p for p in parts if p["type"] == "button"][:REFINE_MAX] if refine else []
    refined = await asyncio.gather(*(_refine_button(meter, crop, b) for b in buttons)) if buttons else []
    for btn, m in zip(buttons, refined):
        if m is not None:
            btn["mask"] = m

    # ---- scale
    cal: dict[str, Any] | None = None
    if spec is not None:
        cal = calibrate_by_holes(holes, spec, side, usb, parts)
    if cal is None:
        if board_mask is None:
            board_mask = await _board_by_box(meter, crop, ident, (0, 0, vw, vh))
        ref = None
        if asset.get("project_id"):
            from . import scene

            ref = await scene.calibrate(meter, asset)
            ref = ref if ref.get("ok") else None
        if board_mask is not None:
            W = float(spec["pcb"]["outline"]["w"]) if spec else None
            Hh = float(spec["pcb"]["outline"]["h"]) if spec else None
            cal = _corner_calibration(board_mask, ref, W, Hh, side, spec, usb, parts, (x0, y0))
        if cal is None:
            if spec is None:
                raise ValueError("this board is not in the dataset and the photo has no scale: put it on an A4 sheet (or next to a bank card) "
                                 "and take the photo from straight above")
            warnings.append("the photo gave no scale (no holes found, no A4 sheet): the board is the dataset's, unchecked against the photo")
    if cal and spec is not None and cal.get("parts_matched", 0) == 0:
        warnings.append("no part was found to tell the board's ends apart: its orientation on the photo is a guess (deltas may be mirrored)")

    H = cal["H"] if cal else None
    deltas: list[dict[str, Any]] = []
    used = set(cal.get("mask_ids", [])) if cal else set()
    if spec is not None:
        board = _photo_dataset(spec, asset, cal, H, usb, parts, deltas, marking)
        if cal and cal["method"] == "board_holes":
            rows = pin_rows(H, holes, used, spec)  # type: ignore[arg-type]
            if rows:
                cal["pin_rows"] = rows
    else:
        board, used = _photo_only(asset, cal, H, holes, usb, parts, marking, warnings)  # type: ignore[arg-type]
    calibration = {k: v for k, v in (cal or {"method": "none"}).items() if k != "H"}
    for k in ("holes_px", "corners_px"):  # photo pixels, like the boxes
        if k in calibration:
            calibration[k] = [[_r(p[0] + x0, 1), _r(p[1] + y0, 1)] for p in calibration[k]]
    board["source"]["calibration"] = {k: calibration[k] for k in ("method", "residual_mm", "pattern_mm", "mm_per_px", "uncertainty_mm", "reference")
                                      if calibration.get(k) is not None}

    # the labelled boxes the studio draws: mounting holes and connectors bright, pads dim
    boxes: list[dict[str, Any]] = []
    for m in holes:
        mount = m.id in used
        boxes.append(_box("mounting hole" if mount else "pad", m.bbox_px, m.score, "mount" if mount else "pin", "sam", "strong" if mount else "dim"))
    for m in usb:
        boxes.append(_box("USB", m.bbox_px, m.score, "port", "sam", "strong"))
    for p in parts:
        if (p["type"] == "mounting_hole" and holes) or (p["type"].startswith("usb") and usb):
            continue  # SAM's own masks are drawn instead
        m = p.get("mask")
        boxes.append(_box(p["label"], m.bbox_px if m is not None else p["box"], m.score if m is not None else None, p["type"],
                          "sam" if m is not None else "spark", "normal"))
    for bx in boxes:
        bx["box"] = [bx["box"][0] + x0, bx["box"][1] + y0, bx["box"][2] + x0, bx["box"][3] + y0]
    errors = schema_errors(board)
    if errors:
        log.warning("board scan produced an invalid board: %s", errors[:5])
    bb = ident.get("board_box") or []
    if board_mask is not None:
        ys, xs = np.nonzero(board_mask)
        board_box = [int(xs.min()) + x0, int(ys.min()) + y0, int(xs.max()) + 1 + x0, int(ys.max()) + 1 + y0]
    else:
        board_box = _grid_px(bb, view) if len(bb) == 4 else None
    out = {"board": board, "boxes": boxes, "calibration": calibration, "deltas": deltas, "warnings": warnings, "schema_errors": errors,
           "board_box_px": board_box, "view_px": list(view),
           "identified": {"board_id": spec["id"] if spec else "unknown", "marking": marking, "confidence": _r(float(ident.get("confidence") or 0), 2),
                          "side": side, "parts": len(parts)}}
    out["selection"] = await _save_selection(asset, name, out) if asset.get("project_id") else None
    return out


def _at_least(img: np.ndarray, side: int) -> np.ndarray:
    """A small crop enlarged for Spark (its boxes are on a 0-1000 grid, so they do not change)."""
    h, w = img.shape[:2]
    if max(h, w) >= side:
        return img
    k = side / max(h, w)
    return cv2.resize(img, (round(w * k), round(h * k)), interpolation=cv2.INTER_CUBIC)


def _pick_board(masks: list[Mask], w: int, h: int) -> np.ndarray | None:
    """SAM's 'circuit board' answer: the confident, sizeable mask (not a chip or a module on the board)."""
    big = [m for m in masks if m.score >= MIN_SCORE and 0.002 * w * h < m.area < 0.9 * w * h]
    return max(big, key=lambda m: m.score * math.sqrt(m.area)).mask if big else None


def _view(board_mask: np.ndarray | None, w: int, h: int) -> tuple[int, int, int, int]:
    """What Spark looks at: the board with a margin when it is small in the photo, else the whole photo."""
    if board_mask is None:
        return 0, 0, w, h
    ys, xs = np.nonzero(board_mask)
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    if bw * bh > 0.35 * w * h:
        return 0, 0, w, h
    pad = int(0.25 * max(bw, bh))
    x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
    x1, y1 = min(w, int(xs.max()) + 1 + pad), min(h, int(ys.max()) + 1 + pad)
    return x0, y0, x1 - x0, y1 - y0


async def _board_by_box(meter: CostMeter, img: np.ndarray, ident: dict[str, Any], view: tuple[int, int, int, int]) -> np.ndarray | None:
    """The board's outline when SAM's concept prompt missed it: SAM by Spark's board box."""
    bb = ident.get("board_box") or []
    if len(bb) != 4:
        return None
    box = _grid_px(bb, view)
    pad = 0.03 * max(box[2] - box[0], box[3] - box[1])
    masks = [m for m in await _segment(meter, img, box=[box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad]) if m.score >= MIN_SCORE]
    return masks[0].mask if masks else None


def _plausible(rect: list[float] | None, size_mm: float) -> bool:
    """A SAM mask refined from a Spark box is that part only if it is about the part's size (a box off by a few mm
    gets a neighbour's mask: seen on a real photo)."""
    if not rect or size_mm <= 0:
        return bool(rect)
    big = max(rect[2] - rect[0], rect[3] - rect[1])
    return 0.5 * size_mm <= big <= 2.0 * size_mm


def _measured(H: np.ndarray, det: dict[str, Any] | Mask) -> tuple[list[float] | None, np.ndarray, str, float | None]:
    """(rect mm, centre mm, source, score) of a SAM mask or a Spark part (refined by SAM when it could be)."""
    m = det if isinstance(det, Mask) else det.get("mask")
    if m is not None:
        return _rect_mm(H, m), apply_h(H, [_centroid(m)])[0], "sam", m.score
    c = apply_h(H, _box_corners(det["box"]))  # type: ignore[index]
    return [float(c[:, 0].min()), float(c[:, 1].min()), float(c[:, 0].max()), float(c[:, 1].max())], apply_h(H, [det["centre"]])[0], "spark", None  # type: ignore[index]


def _photo_dataset(spec: dict[str, Any], asset: dict[str, Any], cal: dict[str, Any] | None, H: np.ndarray | None, usb: list[Mask],
                   parts: list[dict[str, Any]], deltas: list[dict[str, Any]], marking: str) -> dict[str, Any]:
    """The dataset board, checked against the photo: deltas per measured field; a 'verify' position is replaced
    only when the photo measured it more precisely than the dataset's own uncertainty."""
    board = copy.deepcopy(spec)
    dataset_id = spec["id"]
    board.update({"id": f"photo-{dataset_id}", "name": f"{spec['name']} (from photo)",
                  "aliases": list(dict.fromkeys(([marking] if marking else []) + list(spec.get("aliases", []))))})
    board["source"] = {"kind": "photo+dataset", "dataset_id": dataset_id, "urls": list(spec.get("source", {}).get("urls", [])),
                       **({"asset_id": asset["id"]} if asset.get("id") else {}), **({"checked": spec["source"]["checked"]} if spec.get("source", {}).get("checked") else {})}
    if H is None:
        return board
    W, Hh = float(spec["pcb"]["outline"]["w"]), float(spec["pcb"]["outline"]["h"])
    for field, ds, got in zip(("w", "h"), (W, Hh), (cal or {}).get("measured_mm") or []):
        deltas.append({"part": "pcb", "field": field, "dataset": ds, "photo": got, "delta": _r(got - ds), "source": "sam",
                       "uncertainty_mm": (cal or {}).get("uncertainty_mm"), "applied": False})
    base_unc = float((cal or {}).get("uncertainty_mm") or 0.3)
    comps = {c["id"]: c for c in board["components"]}
    taken: set[str] = set()

    def note(c: dict[str, Any], field: str, photo: float, source: str, unc: float) -> None:
        ds = c.get(field)
        if not isinstance(ds, (int, float)):
            return
        ds_unc = float(c.get("uncertainty_mm") or spec.get("uncertainty_mm") or DATASET_MM)
        # more precise, and not so far off that it is more likely the wrong thing measured
        apply = field in (c.get("verify") or []) and field in ("x", "y", "at") and unc < ds_unc and abs(photo - ds) <= 3 * ds_unc
        deltas.append({"part": c["id"], "field": field, "dataset": ds, "photo": _r(photo), "delta": _r(photo - ds), "source": source,
                       "uncertainty_mm": _r(unc), "applied": apply})
        if apply:
            c[field] = _r(photo)
            c["verify"] = [v for v in c.get("verify", []) if v != field]
            c["uncertainty_mm"] = _r(unc)

    dets: list[tuple[str, Any]] = [("usb", m) for m in usb[:4]] + [(_kind(p["type"]), p) for p in parts if not (usb and p["type"].startswith("usb"))]
    for kind, det in dets:
        cands = [c for c in _matches(spec, kind) if c["id"] not in taken]
        if not cands:
            continue
        rect, centre, source, score = _measured(H, det)
        if source == "sam" and isinstance(det, dict) and not _plausible(rect, max(float(c.get("w", 0)) for c in cands)):
            rect, centre, source, score = _measured(H, {k: v for k, v in det.items() if k != "mask"})
        c = comps[min(cands, key=lambda c: float(np.hypot(*(centre - _comp_centre(c, W, Hh)))))["id"]]
        if float(np.hypot(*(centre - _comp_centre(c, W, Hh)))) > 6:
            continue  # nothing of that kind there in the dataset: not this part
        taken.add(c["id"])
        unc = math.hypot(base_unc, 0.15) if source == "sam" else SPARK_BOX_MM
        if c.get("access") == "port" and rect:
            nums = _port_numbers(rect, c.get("edge", "+y"), W, Hh)
            note(c, "at", nums["at"], source, unc)
            note(c, "w", nums["w"], source, unc)
            note(c, "protrude", nums["protrude"], source, max(unc, 0.5))  # a tall shell seen from above looks longer
        else:
            note(c, "x", float(centre[0]), source, unc)
            note(c, "y", float(centre[1]), source, unc)
        c["evidence"] = {"sam": {"prompt": PORT_PROMPT if isinstance(det, Mask) else "box", "score": _r(score or 0, 3)}} if source == "sam" else \
            {"spark_box": [int(v) for v in det["box"]], "label": det["label"]}
    return board


def _mount_holes(holes: list[Mask], H: np.ndarray, W: float, Hh: float) -> tuple[list[dict[str, Any]], set[str]]:
    """Mounting holes of an unknown board: the cluster of the largest hole masks inside the outline. SAM's mask is
    about the hole (on the Pico W 2.2 mm for a 2.1 mm drill), so the drill is its size less a little, marked verify."""
    inside = []
    for m in holes:
        c = apply_h(H, [_centroid(m)])[0]
        if 1.0 <= c[0] <= W - 1.0 and 1.0 <= c[1] <= Hh - 1.0:
            inside.append((m, c))
    inside.sort(key=lambda t: -_size_px(t[0]))
    sizes = [_size_px(m) for m, _ in inside]
    cut = next((i for i in range(1, len(sizes)) if sizes[i - 1] > 1.25 * sizes[i]), len(sizes))
    big = inside[:cut]
    if not big or len(big) > 6:
        return [], set()  # many equal masks are pads or pins, not mounting holes
    out, used = [], set()
    for m, c in big:
        d = 2 * math.sqrt(m.area / math.pi) * mm_per_px(H, _centroid(m)) - 0.1
        if 1.0 <= d <= 4.5:  # bigger openings are cut-outs, not holes for a peg or a screw
            out.append({"x": _r(c[0]), "y": _r(c[1]), "d": _r(d, 1), "use": "mount", "verify": ["d"], "uncertainty_mm": 0.3})
            used.add(m.id)
    return out, used


def _photo_only(asset: dict[str, Any], cal: dict[str, Any], H: np.ndarray, holes: list[Mask], usb: list[Mask], parts: list[dict[str, Any]],
                marking: str, warnings: list[str]) -> tuple[dict[str, Any], set[str]]:
    """An unknown board measured on the photo alone (scale from an A4 sheet or a card), and the hole masks it used."""
    W, Hh = cal["size_mm"]
    unc = float(cal.get("uncertainty_mm") or 0.5)
    comps: list[dict[str, Any]] = []
    keepouts: list[dict[str, Any]] = []
    usb_type = next((p["type"] for p in parts if p["type"].startswith("usb")), "usb_c")
    dets: list[dict[str, Any]] = [{"type": usb_type, "label": "usb", "mask": m, "evidence": {"sam": {"prompt": PORT_PROMPT, "score": _r(m.score, 3)}}}
                                  for m in usb[:4]]
    for p in parts:
        if usb and p["type"].startswith("usb"):
            continue
        m = p.get("mask")
        dets.append({**p, "evidence": {"sam": {"prompt": "box", "score": _r(m.score, 3)}} if m is not None else {"spark_box": [int(v) for v in p["box"]]}})
    for d in dets:
        rect, _, source, _ = _measured(H, d)
        if source == "sam" and d["type"] == "button" and not _plausible(rect, 4.5):
            d = {**{k: v for k, v in d.items() if k != "mask"}, "evidence": {"spark_box": [int(v) for v in d["box"]]}}
            rect, _, source, _ = _measured(H, d)
        if rect is None:
            continue
        comp, ko = _component(d, rect, W, Hh, len(keepouts), _r(math.hypot(unc, SPARK_BOX_MM if source == "spark" else 0.15)))
        if ko:
            keepouts.append(ko)
        if comp:
            comps.append(comp)
    _unique_ids(comps)
    mounts, used = _mount_holes(holes, H, W, Hh)
    if mounts:
        warnings.append(f"{len(mounts)} mounting holes found; their diameters are estimated from the pads: offer a peg-fit probe or measure one")
    if not usb and not any(c.get("access") == "port" for c in comps):
        warnings.append("no connector found on the board's edge: say which side the cable goes in")
    slug = re.sub(r"[^a-z0-9]+", "-", (marking or "board").lower()).strip("-")[:40] or "board"
    top = max([c["h"] + float(c.get("z0", 0)) for c in comps if c.get("side") == "top"] + [1.0])
    board = {
        "schema": "fw.board/1", "id": f"photo-{slug}", "name": f"{marking or 'Board'} (from photo)", "aliases": [marking] if marking else [],
        "source": {"kind": "photo", **({"asset_id": asset["id"]} if asset.get("id") else {})},
        "frame": dataset()["frame"],
        "pcb": {"outline": {"kind": "rect", "w": _r(W, 1), "h": _r(Hh, 1), "r": 0, "verify": []}, "thickness": 1.6, "holes": mounts,
                "thickness_verify": True},
        "uncertainty_mm": _r(unc),
        "components": comps,
        "keepouts": keepouts,
        "heights": {"top_max": _r(top), "bottom_max": 0, "verify": ["top_max", "bottom_max"],
                    "note": "from a top view: heights are typical; with pins soldered under the board set bottom_max (about 8.5 for 0.1 inch headers)"},
    }
    return board, used


async def _save_selection(asset: dict[str, Any], name: str, out: dict[str, Any]) -> dict[str, Any]:
    """The scan as a selection on its photo, so the studio can draw the labelled boxes (selection.added)."""
    from .scene import _insert_selection, _unique_name

    board = out["board"]
    xs = [b["box"] for b in out["boxes"]]
    bbox = out.get("board_box_px") or ([min(b[0] for b in xs), min(b[1] for b in xs), max(b[2] for b in xs), max(b[3] for b in xs)] if xs else None)
    data = {"kind": "board_scan", "found": True, "board_id": out["identified"]["board_id"], "marking": out["identified"]["marking"],
            "confidence": out["identified"]["confidence"], "board": board["id"], "input": f"inputs.boards.{name}",
            "board_mm": [board["pcb"]["outline"]["w"], board["pcb"]["outline"]["h"]], "boxes": out["boxes"], "bbox_px": bbox,
            "calibration": {k: v for k, v in out["calibration"].items() if k in ("method", "residual_mm", "pattern_mm", "mm_per_px", "uncertainty_mm", "pin_rows", "reference")},
            "deltas": out["deltas"]}
    sel_name = await _unique_name(asset["project_id"], f"board_{name}" if name != "board" else "board")
    return await _insert_selection(asset["project_id"], asset["id"], "context", sel_name, {"text": "board scan", "by": "auto"}, None, data)
