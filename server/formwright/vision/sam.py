"""SAM 3.1 segmentation: prompts (phrase, points, box), decoding, outlines.

SAM returns special-token text; `meta_sam_parser` decodes it. Each mask raster
covers exactly its bounds (right/bottom exclusive) and already excludes holes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import cv2
import meta_sam_parser as msp
import numpy as np

from ..llm.client import CostMeter, meta
from .common import data_url, encode_png, read_image, write_bytes

# SAM can take the stored image as is; keep requests reasonable for very large photos.
MAX_SAM_SIDE = 4096


@dataclass
class Mask:
    id: str
    bbox_px: list[int]  # [x1, y1, x2, y2], x2/y2 exclusive
    score: float
    mask: np.ndarray = field(repr=False)  # bool, full image size

    @property
    def area(self) -> int:
        return int(self.mask.sum())


def _records(raw: str) -> list[Any]:
    parser = msp.image_segmentation_format().create_parser()
    parser.push(raw)
    return list(parser.finish(msp.CompletedOutcome()).result.records)


def fit_raster(raster: bytes, mw: int, mh: int, bw: int, bh: int) -> np.ndarray:
    """SAM caps mask rasters (about 1024 px on the long side); the raster always spans the
    record's box, so large objects come back downsampled and must be stretched to the box."""
    m = np.frombuffer(raster, dtype=np.uint8).reshape(mh, mw)
    if (mw, mh) == (bw, bh) or bw <= 0 or bh <= 0:
        return m > 0
    up = cv2.resize(m.astype(np.float32), (bw, bh), interpolation=cv2.INTER_LINEAR)
    return up >= 0.5


def decode(raw: str, width: int, height: int) -> list[Mask]:
    """SAM token text -> full-size masks, highest score first."""
    boxes: dict[str, float | None] = {}
    out: list[Mask] = []
    for r in _records(raw):
        if isinstance(r, msp.SegmentationBoxRecord):
            boxes[r.object_id] = r.confidence
    for r in _records(raw):
        if not isinstance(r, msp.SegmentationMaskRecord):
            continue
        l, t = int(round(r.bounds.left)), int(round(r.bounds.top))
        box = fit_raster(msp.decode_mask_to_raster(r.mask), r.mask.width, r.mask.height,
                         int(round(r.bounds.right)) - l, int(round(r.bounds.bottom)) - t)
        full = np.zeros((height, width), dtype=bool)
        h = min(box.shape[0], height - t)
        w = min(box.shape[1], width - l)
        if h > 0 and w > 0:
            full[t : t + h, l : l + w] = box[:h, :w]
        score = r.confidence if r.confidence is not None else (boxes.get(r.object_id) or 0.0)
        out.append(Mask(id=str(r.object_id), bbox_px=[l, t, l + w, t + h], score=float(score), mask=full))
    out.sort(key=lambda m: -m.score)
    return out


def object_prompt(width: int, height: int, points: Sequence[dict[str, Any]] | None = None, box: Sequence[float] | None = None) -> str:
    """Point/box prompt in SAM's token grammar (one object)."""
    pb = None
    if box:
        x1, y1, x2, y2 = (int(round(v)) for v in box[:4])
        x1, x2 = sorted((max(0, x1), min(width, x2)))
        y1, y2 = sorted((max(0, y1), min(height, y2)))
        pb = msp.PromptBox(x1, y1, max(x1 + 1, x2), max(y1 + 1, y2))
    pts = [
        msp.PromptPoint(
            int(round(min(max(p["x"], 0), width - 1))),
            int(round(min(max(p["y"], 0), height - 1))),
            label="positive" if p.get("positive", True) else "negative",
        )
        for p in (points or [])
    ]
    if pb is None and not pts:
        raise ValueError("need points or a box")
    return msp.build_object_prompt(size=(width, height), objects=[msp.PromptObject(id=1, prompts=[msp.FramePrompt(frame=0, box=pb, points=pts)])])


async def segment(
    meter: CostMeter,
    image: np.ndarray | str | Path,
    *,
    text: str | None = None,
    points: Sequence[dict[str, Any]] | None = None,
    box: Sequence[float] | None = None,
) -> list[Mask]:
    """Segment by a short noun phrase, or by positive/negative points and/or a box.

    points: [{"x", "y", "positive"}] in image pixels; box: [x1, y1, x2, y2] in pixels.
    """
    img = read_image(image)
    h, w = img.shape[:2]
    scale = 1.0
    if max(h, w) > MAX_SAM_SIDE:
        scale = MAX_SAM_SIDE / max(h, w)
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    sh, sw = img.shape[:2]
    if text:
        prompt = text.strip()
    else:
        sp = [{**p, "x": p["x"] * scale, "y": p["y"] * scale} for p in (points or [])]
        sb = [v * scale for v in box] if box else None
        prompt = object_prompt(sw, sh, sp, sb)
    raw = await meta().sam(meter, data_url(img, quality=93), prompt)
    masks = decode(raw, sw, sh)
    if scale != 1.0:
        for m in masks:
            m.mask = cv2.resize(m.mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
            m.bbox_px = [round(v / scale) for v in m.bbox_px]
    return masks


def save_mask_png(rel: str, mask: np.ndarray) -> str:
    return write_bytes(rel, encode_png(mask.astype(np.uint8) * 255))


def load_mask_png(path: str | Path) -> np.ndarray:
    img = read_image(path)
    return img[..., 0] > 127


def largest_component(mask: np.ndarray) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n <= 2:
        return mask.astype(bool)
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == best


def polygons(mask: np.ndarray, epsilon_px: float = 1.0, min_area_px: float = 30.0) -> list[dict[str, Any]]:
    """Outer contours with their holes: [{"outer": Nx2, "holes": [Mx2, ...]}], largest first.

    Points are pixel coordinates of the boundary (contour of the pixel centers + 0.5 so
    edges sit on pixel borders on average).
    """
    m = mask.astype(np.uint8)
    contours, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hier is None:
        return []
    hier = hier[0]
    out: list[dict[str, Any]] = []
    for i, c in enumerate(contours):
        if hier[i][3] != -1:
            continue  # a hole; collected with its parent
        if cv2.contourArea(c) < min_area_px:
            continue
        outer = cv2.approxPolyDP(c, epsilon_px, True).reshape(-1, 2).astype(float)
        holes = []
        child = hier[i][2]
        while child != -1:
            hc = contours[child]
            if cv2.contourArea(hc) >= min_area_px * 0.3:
                holes.append(cv2.approxPolyDP(hc, epsilon_px, True).reshape(-1, 2).astype(float))
            child = hier[child][0]
        out.append({"outer": outer, "holes": holes, "area_px": float(cv2.contourArea(c)), "raw": c.reshape(-1, 2), "raw_holes": [contours[j].reshape(-1, 2) for j in _children(hier, i)]})
    out.sort(key=lambda p: -p["area_px"])
    return out


def _children(hier: np.ndarray, i: int) -> list[int]:
    res = []
    child = hier[i][2]
    while child != -1:
        res.append(child)
        child = hier[child][0]
    return res
