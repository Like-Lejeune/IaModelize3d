"""The server's half of the instant 3D sticker: SAM mask + photo -> outline loops (with holes) and a relief heightmap.

Height = a dome from the distance to the outline (the puffy body) plus a little photo detail (high-pass luminance),
so slats, legs and faces read on the print. The result feeds inputs.outlines / inputs.heightmaps / inputs.values of
a lib.collect program (packages/geom/src/lib/collect.ts), which makes the printable sticker in the kernel in 1-2 s.
People get no photo detail: a tap on a passer-by must not press their face into plastic.
"""
from __future__ import annotations

import time
from typing import Any

import cv2
import numpy as np

GRID = 180  # heightmap cells along the crop's long side (~0.3 mm on a 50 mm sticker)
DETAIL = 0.35  # photo detail on top of the dome, as a share of its height
SIZES = (40, 50, 60)  # mm along the longest side, the chips on the snap screen

# The saved program of an instant sticker (author 'instant'); the browser builds the same source for its preview.
STICKER_SOURCE = """const meta = { title: 'Snap sticker', pack: 'collect', printNotes: 'Flat side down, no supports. Two colours: swap filament at the top of the base (1.6 mm): dark base, light relief.' };
const params = {
  size:   { value: 50,  min: 25,  max: 90, unit: 'mm', label: 'Longest side', source: 'design' },
  puff:   { value: 4,   min: 1.5, max: 9,  unit: 'mm', label: 'Relief',       source: 'design' },
  base:   { value: 1.6, min: 1.2, max: 4,  unit: 'mm', label: 'Base',         source: 'design' },
  border: { value: 2.2, min: 1,   max: 5,  unit: 'mm', label: 'Border',       source: 'design' },
};
function build(p, lib) { return lib.collect.sticker('subject', { ...p, name: lib.inputs.values.name }); }
return { meta, params, build };
"""


def relief(img: np.ndarray, mask: np.ndarray, n: int = GRID, detail: float = DETAIL) -> dict[str, Any]:
    """BGR photo + boolean mask of the same size -> {loops_px, crop_px, heightmap {w, h, data}, ms}."""
    t = time.perf_counter()
    if img.shape[:2] != mask.shape[:2]:
        img = cv2.resize(img, (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_AREA)
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("empty mask")
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    pad = int(0.04 * max(x1 - x0, y1 - y0)) + 2
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(mask.shape[1], x1 + pad), min(mask.shape[0], y1 + pad)
    m = (mask[y0:y1, x0:x1] > 0).astype(np.uint8)
    crop = img[y0:y1, x0:x1]
    # loops with holes, in photo pixels; the kernel fills them even-odd and simplifies at 0.08 mm itself
    cs, _ = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    area_min = 0.002 * float(m.sum())
    eps = max(0.6, 0.0015 * max(m.shape))  # ~0.08 mm on the sticker, whatever the photo's resolution
    loops = []
    for c in cs:
        if cv2.contourArea(c) < area_min:
            continue
        c = cv2.approxPolyDP(c, eps, True)[:, 0, :]
        if len(c) >= 3:
            loops.append([[float(x + x0), float(y + y0)] for x, y in c])
    if not loops:
        raise ValueError("the outline is too small")
    # heightmap on a coarse grid over the crop
    s = n / max(m.shape)
    W, H = max(2, round(m.shape[1] * s)), max(2, round(m.shape[0] * s))
    mb = (cv2.resize(m * 255, (W, H), interpolation=cv2.INTER_AREA) > 127).astype(np.uint8)
    dist = cv2.distanceTransform(mb, cv2.DIST_L2, 5)
    R = max(2.0, 0.22 * min(W, H), float(np.percentile(dist[mb > 0], 90)) if mb.any() else 2.0)
    tt = np.clip(dist / R, 0, 1)
    dome = np.sqrt(1 - (1 - tt) ** 2)
    hfield = dome
    if detail > 0 and mb.any():
        gray = cv2.cvtColor(cv2.resize(crop, (W, H), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        hp = gray - cv2.GaussianBlur(gray, (0, 0), 3.0)
        # adaptive amplitude: normalised by the texture's own spread, with a floor so a dark or flat photo's noise
        # is not blown up into bumps
        spread = max(float(np.std(hp[mb > 0])) * 2.5, 0.05)
        hp = np.clip(hp / spread, -1, 1)
        hfield = dome + detail * hp * np.minimum(1, tt * 3)
    hfield = np.where(mb > 0, np.clip(hfield, 0, 1.3), 0)
    hfield = cv2.GaussianBlur(hfield.astype(np.float32), (0, 0), 0.6)
    return {
        "loops_px": loops,
        "crop_px": [x0, y0, x1, y1],
        "heightmap": {"w": int(W), "h": int(H), "data": [round(float(v), 3) for v in hfield.ravel()]},
        "ms": round((time.perf_counter() - t) * 1000, 1),
    }


def inputs_for(r: dict[str, Any], key: str = "subject", name: str = "") -> dict[str, Any]:
    """Program inputs of one relief under `key` (a plate merges several under their own keys)."""
    x0, y0, x1, y1 = r["crop_px"]
    values: dict[str, Any] = {f"{key}_x0": x0, f"{key}_y0": y0, f"{key}_x1": x1, f"{key}_y1": y1}
    if name:
        values[f"{key}_name"] = name
    return {"outlines": {key: r["loops_px"]}, "heightmaps": {key: r["heightmap"]}, "values": values}


def outline_mm(r: dict[str, Any], size: float) -> list[float]:
    """The figure's outline in mm when its longest side is `size` (the die-cut rim and the name tab come on top)."""
    pts = np.array([p for loop in r["loops_px"] for p in loop], float)
    w, h = (pts.max(axis=0) - pts.min(axis=0)).tolist()
    k = size / max(w, h, 1e-6)
    return [round(w * k, 1), round(h * k, 1)]


def sticker(img: np.ndarray, mask: np.ndarray, *, name: str = "", size: float = 50, detail: float = DETAIL) -> dict[str, Any]:
    """Everything a client needs to build the sticker: {source, inputs, params, size_mm, detail, ms}."""
    r = relief(img, mask, detail=detail)
    inputs = inputs_for(r, "subject")
    inputs["values"]["name"] = name
    return {"source": STICKER_SOURCE, "inputs": inputs, "params": {"size": size}, "size_mm": outline_mm(r, size),
            "detail": detail, "ms": r["ms"]}
