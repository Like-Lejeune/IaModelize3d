"""Sub-pixel edge refinement of SAM outlines.

SAM masks get the topology right but their borders sit a few pixels off (halos,
soft edges, downsampled rasters). Each outline point is moved along its normal to
the strongest intensity edge between "object colour" and "background colour".
"""
from __future__ import annotations

import cv2
import numpy as np
from scipy.ndimage import map_coordinates


def contrast_image(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Project colours on the inside-minus-outside colour axis: bright = object."""
    m = mask.astype(np.uint8)
    ring = cv2.dilate(m, np.ones((15, 15), np.uint8)) & (1 - cv2.dilate(m, np.ones((5, 5), np.uint8)))
    core = cv2.erode(m, np.ones((5, 5), np.uint8))
    f = img.astype(np.float32)
    if f.ndim == 2:
        f = f[..., None]
    inside = f[core > 0].mean(axis=0) if core.any() else f[m > 0].mean(axis=0)
    outside = f[ring > 0].mean(axis=0) if ring.any() else f.reshape(-1, f.shape[-1]).mean(axis=0)
    d = inside - outside
    n = float(np.linalg.norm(d))
    if n < 8:
        return np.zeros(mask.shape, np.float32)
    proj = (f @ (d / n)).astype(np.float32)
    return cv2.GaussianBlur(proj, (0, 0), 1.0)


def resample(poly: np.ndarray, step: float = 1.5) -> np.ndarray:
    p = np.asarray(poly, dtype=float)
    q = np.vstack([p, p[:1]])
    seg = np.hypot(*np.diff(q, axis=0).T)
    total = seg.sum()
    if total < step * 4:
        return p
    s = np.concatenate([[0], np.cumsum(seg)])
    ts = np.arange(0, total, step)
    x = np.interp(ts, s, q[:, 0])
    y = np.interp(ts, s, q[:, 1])
    return np.column_stack([x, y])


def refine_polyline(proj: np.ndarray, mask: np.ndarray, poly: np.ndarray, search: float = 5.0, step: float = 1.5) -> tuple[np.ndarray, float]:
    """Returns (refined points, fraction of points that snapped to an edge)."""
    if not proj.any():
        return np.asarray(poly, float), 0.0
    pts = resample(poly, step)
    n = len(pts)
    prev = np.roll(pts, 1, axis=0)
    nxt = np.roll(pts, -1, axis=0)
    tang = nxt - prev
    tl = np.hypot(tang[:, 0], tang[:, 1])
    tl[tl == 0] = 1
    normal = np.column_stack([tang[:, 1], -tang[:, 0]]) / tl[:, None]
    # orient normals from object to background using the mask
    probe = np.round(pts + normal * 2.5).astype(int)
    probe[:, 0] = probe[:, 0].clip(0, mask.shape[1] - 1)
    probe[:, 1] = probe[:, 1].clip(0, mask.shape[0] - 1)
    flip = mask[probe[:, 1], probe[:, 0]]
    normal[flip] *= -1
    offs = np.arange(-search, search + 1e-6, 0.25)
    xs = pts[:, 0:1] + normal[:, 0:1] * offs[None, :]
    ys = pts[:, 1:2] + normal[:, 1:2] * offs[None, :]
    prof = map_coordinates(proj, [ys.ravel(), xs.ravel()], order=1, mode="nearest").reshape(n, -1)
    grad = -np.gradient(prof, offs, axis=1)  # object -> background: intensity drops
    k = grad.argmax(axis=1)
    peak = grad[np.arange(n), k]
    contrast = prof.max(axis=1) - prof.min(axis=1)
    ok = (peak > 0.15 * np.maximum(contrast, 1e-6)) & (contrast > 6) & (k > 0) & (k < len(offs) - 1)
    # parabolic sub-sample peak
    kk = np.clip(k, 1, len(offs) - 2)
    y0, y1, y2 = grad[np.arange(n), kk - 1], grad[np.arange(n), kk], grad[np.arange(n), kk + 1]
    den = y0 - 2 * y1 + y2
    frac = np.where(np.abs(den) > 1e-9, 0.5 * (y0 - y2) / den, 0.0).clip(-0.5, 0.5)
    shift = (offs[kk] + frac * 0.25) * ok
    out = pts + normal * shift[:, None]
    return out, float(ok.mean())
