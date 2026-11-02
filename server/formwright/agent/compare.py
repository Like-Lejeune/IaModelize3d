"""Likeness feedback for copy tasks: the object in the photo next to the model seen from about the same
viewpoint, and how well their silhouettes agree. The designer gets it after every build, the critic
before judging. A calibrated photo uses its real camera, so the model is drawn over the photo instead."""
from __future__ import annotations

import base64
import math
from typing import Any

import cv2
import numpy as np

from .. import storage
from ..db import get_db
from ..geom import geom

BANDS = (0.2, 0.35, 0.5, 0.65, 0.8)
PANEL_H = 420
LABEL_H = 30


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if ys.size else None


def _crop(img: np.ndarray, box: tuple[int, int, int, int], pad: float = 0.06) -> np.ndarray:
    x0, y0, x1, y1 = box
    h, w = img.shape[:2]
    px, py = int((x1 - x0) * pad), int((y1 - y0) * pad)
    return img[max(0, y0 - py): min(h, y1 + py), max(0, x0 - px): min(w, x1 + px)]


def _to_height(img: np.ndarray, h: int = PANEL_H) -> np.ndarray:
    return cv2.resize(img, (max(1, round(img.shape[1] * h / img.shape[0])), h), interpolation=cv2.INTER_AREA)


def _widths(mask: np.ndarray) -> list[float]:
    """Width at fractions of the height from the top, in units of the object's height (scale-free)."""
    x0, y0, x1, y1 = _bbox(mask)  # type: ignore[misc]
    out = []
    for f in BANDS:
        xs = np.nonzero(mask[int(y0 + f * (y1 - y0))])[0]
        out.append((xs.max() - xs.min() + 1) / (y1 - y0) if xs.size else 0.0)
    return out


def silhouette_agreement(photo_mask: np.ndarray, model_mask: np.ndarray) -> dict[str, Any]:
    """Both outlines cut to their bounding boxes and scaled to the same height (scale-free):
    IoU, height/width, and the model's width relative to the photo's at five heights."""
    def norm(m: np.ndarray) -> np.ndarray:
        x0, y0, x1, y1 = _bbox(m)  # type: ignore[misc]
        c = cv2.resize(m[y0:y1, x0:x1].astype(np.uint8) * 255, (max(1, round((x1 - x0) * 256 / (y1 - y0))), 256), interpolation=cv2.INTER_NEAREST)
        out = np.zeros((256, 768), np.uint8)
        x = max(0, (768 - c.shape[1]) // 2)
        out[:, x: x + min(c.shape[1], 768)] = c[:, :768]
        return out > 127

    a, b = norm(photo_mask), norm(model_mask)
    union = np.logical_or(a, b).sum()
    pa, pb = _bbox(photo_mask), _bbox(model_mask)
    wp, wm = _widths(photo_mask), _widths(model_mask)
    return {
        "silhouette_iou": round(float(np.logical_and(a, b).sum() / union), 3) if union else 0.0,
        "height_to_width": {"photo": round((pa[3] - pa[1]) / (pa[2] - pa[0]), 3), "model": round((pb[3] - pb[1]) / (pb[2] - pb[0]), 3)},  # type: ignore[index]
        "model_width_vs_photo": {f"{round(f * 100)}% from top": round(m / p, 2) for f, m, p in zip(BANDS, wm, wp) if p},
    }


def view_camera(bbox: dict[str, list[float]], elevation: float, azimuth: float = 0.0, px: int = 640) -> dict[str, Any]:
    """Perspective camera looking at the model's front (from -Y) from `elevation` degrees above."""
    lo, hi = np.array(bbox["min"], float), np.array(bbox["max"], float)
    c, diag = (lo + hi) / 2, float(np.linalg.norm(hi - lo)) or 1.0
    dist = 3.0 * float(max(hi - lo))
    e, a = math.radians(elevation), math.radians(azimuth)
    eye = c + dist * np.array([math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)])
    fwd = (c - eye) / np.linalg.norm(c - eye)
    right = np.cross(fwd, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    R = np.stack([right, -up, fwd])
    f = 0.6 * px * dist / diag
    return {"width": px, "height": px, "R": R.reshape(-1).tolist(), "t": (-R @ eye).tolist(), "fx": f, "fy": f, "cx": px / 2, "cy": px / 2}


def _decode(r: dict[str, Any], cam: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    rgba = cv2.imdecode(np.frombuffer(base64.b64decode(r["png"]), np.uint8), cv2.IMREAD_UNCHANGED)
    bits = np.unpackbits(np.frombuffer(base64.b64decode(r["mask"]), np.uint8))[: cam["width"] * cam["height"]]
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA), bits.reshape(cam["height"], cam["width"]).astype(bool)


def _label(img: np.ndarray, text: str) -> np.ndarray:
    """A caption band above the image: written over a tight crop it ran into the model ("deg abovee")."""
    (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
    out = cv2.copyMakeBorder(img, LABEL_H, 0, 0, max(0, tw + 20 - img.shape[1]), cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(out, text, (10, LABEL_H - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 40), 1, cv2.LINE_AA)
    return out


async def targets(project_id: str, limit: int = 2) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """The latest target selection on each photo or picked concept image: (asset, selection)."""
    db = await get_db()
    sels = await db.all("SELECT * FROM selections WHERE project_id = ? AND role = 'target' AND mask_path IS NOT NULL ORDER BY created_at DESC", project_id)
    out, seen = [], set()
    for s in sels:
        if s["asset_id"] in seen:
            continue
        a = await db.one("SELECT * FROM assets WHERE id = ?", s["asset_id"])
        if a and a["kind"] in ("photo", "concept"):
            seen.add(s["asset_id"])
            out.append((a, s))
    return out[:limit]


async def panel(project_id: str, state: Any, asset: dict[str, Any], sel: dict[str, Any],
                elevation: float = 15.0, azimuth: float = 0.0, *, printer: dict[str, Any] | None = None,
                inputs: dict[str, Any] | None = None) -> tuple[dict[str, Any], str] | None:
    """(facts, image path) comparing the current model with the selected object on one photo.
    `printer` and `inputs` as the build got them let the engine reuse that build instead of running the program again."""
    from ..vision import overlay, scene
    from ..vision.common import asset_image, encode_jpeg
    from ..vision.sam import load_mask_png

    if not state.source or not state.last_build:
        return None
    photo = asset_image(asset)
    pmask = load_mask_png(sel["mask_path"])
    if _bbox(pmask) is None:
        return None
    extra: dict[str, Any] = {"inputs": state.inputs if inputs is None else inputs, **({"printer": printer} if printer else {})}
    cam = scene.camera_for_render(asset)
    if cam:
        r = await geom().render(state.source, state.params, camera=cam, **extra)
        rgba, mmask = _decode(r, cam)
        if _bbox(mmask) is None:
            return None
        # a model centred at the origin instead of kept in the photo frame is compared by shape, not position
        (py, px), (my, mx) = np.argwhere(pmask).mean(axis=0), np.argwhere(mmask).mean(axis=0)
        shift = np.float32([[1, 0, px - mx], [0, 1, py - my]])
        size = (rgba.shape[1], rgba.shape[0])
        rgba = cv2.warpAffine(rgba, shift, size)
        mmask = cv2.warpAffine(mmask.astype(np.uint8), shift, size, flags=cv2.INTER_NEAREST) > 0
        union = np.logical_or(pmask, mmask)
        img = _crop(overlay.blend(photo, rgba, 0.6), _bbox(union), 0.12)  # type: ignore[arg-type]
        img = _label(_to_height(img, 480), "model over the photo (real camera)")
        facts = {"view": "the photo's own camera (calibrated)", "outline_iou": round(float(np.logical_and(pmask, mmask).sum() / union.sum()), 3),
                 "offset_px": round(float(math.hypot(px - mx, py - my)))}
    else:
        cam = view_camera(state.last_build["checks"]["stats"]["bbox"], elevation, azimuth)
        r = await geom().render(state.source, state.params, camera=cam, **extra)
        rgba, mmask = _decode(r, cam)
        if _bbox(mmask) is None:
            return None
        a = rgba[..., 3:4].astype(np.float32) / 255
        model = (np.full(rgba.shape[:2] + (3,), 236, np.float32) * (1 - a) + rgba[..., :3] * a).astype(np.uint8)
        left = _label(_to_height(_crop(photo, _bbox(pmask))), "concept image" if asset["kind"] == "concept" else "photo")  # type: ignore[arg-type]
        right = _label(_to_height(_crop(model, _bbox(mmask))), f"model, {elevation:.0f} deg above")  # type: ignore[arg-type]
        img = np.hstack([left, np.full((PANEL_H + LABEL_H, 12, 3), 255, np.uint8), right])
        facts = {"view": f"model from {elevation:.0f} deg above, azimuth {azimuth:.0f} deg (match the photo's angle with look elevation=...)",
                 **silhouette_agreement(pmask, mmask),
                 "reading": "0.9+ is a close match; past that, judge counts and element shape by eye instead of chasing the number"}
    rel = storage.save_bytes(project_id, "renders", f"v{state.version}_compare_{asset['id'][-6:]}.jpg", encode_jpeg(img, 88))
    return {"photo": asset["id"], **facts}, rel
