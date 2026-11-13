"""Compare a printed part's outline (measured from a photo) with the target outline.

Both inputs are outlines in mm: a list of [x, y] points or a list of loops (first or
largest = outer, others = holes). The printed outline is aligned rigidly (rotation,
translation, optional mirror if the part was photographed upside down) by PCA + ICP,
then deviations are measured along the target contour.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

Poly = list[list[float]]


def _loops(outline: Any) -> list[np.ndarray]:
    arr = outline
    if len(arr) and isinstance(arr[0][0], (int, float)):
        arr = [arr]
    loops = [np.asarray(l, dtype=np.float64) for l in arr if len(l) >= 3]
    loops.sort(key=lambda l: -_area(l))
    return loops


def _area(p: np.ndarray) -> float:
    x, y = p[:, 0], p[:, 1]
    return float(abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))) / 2)


def _resample(p: np.ndarray, n: int) -> np.ndarray:
    closed = np.vstack([p, p[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], n, endpoint=False)
    return np.column_stack([np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])])


def _inside(pt: np.ndarray, poly: np.ndarray) -> bool:
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _rigid(src: np.ndarray, dst: np.ndarray, allow_reflection: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Best rotation R and translation t with R @ src + t ≈ dst (Kabsch, no scaling)."""
    cs, cd = src.mean(0), dst.mean(0)
    u, _, vt = np.linalg.svd((src - cs).T @ (dst - cd))
    r = (u @ vt).T
    if np.linalg.det(r) < 0 and not allow_reflection:
        vt[-1] *= -1
        r = (u @ vt).T
    return r, cd - r @ cs


def _icp(src: np.ndarray, dst: np.ndarray, iters: int = 40) -> tuple[np.ndarray, float]:
    tree = cKDTree(dst)
    cur = src.copy()
    err = math.inf
    for _ in range(iters):
        d, idx = tree.query(cur)
        r, t = _rigid(cur, dst[idx])
        cur = cur @ r.T + t
        new = float(np.sqrt(np.mean(d * d)))
        if abs(err - new) < 1e-6:
            break
        err = new
    return cur, err


def _pca_starts(src: np.ndarray, dst: np.ndarray, allow_mirror: bool) -> list[np.ndarray]:
    def frame(p: np.ndarray) -> np.ndarray:
        c = p - p.mean(0)
        _, vecs = np.linalg.eigh(c.T @ c)
        return vecs

    fd = frame(dst)
    starts = []
    mirrors = [False, True] if allow_mirror else [False]
    for mirror in mirrors:
        s = src * np.array([-1.0, 1.0]) if mirror else src
        fs_m = frame(s)
        for sx in (1, -1):
            for sy in (1, -1):
                r = fd @ np.diag([sx, sy]) @ fs_m.T
                out = (s - s.mean(0)) @ r.T + dst.mean(0)
                starts.append(out)
    return starts


def _signed_dist(points: np.ndarray, target: np.ndarray, printed_dense: np.ndarray) -> np.ndarray:
    """Distance from each target point to the printed contour, + when printed is outside."""
    tree = cKDTree(printed_dense)
    d, idx = tree.query(points)
    signs = np.array([1.0 if not _inside(printed_dense[i], target) else -1.0 for i in idx])
    return d * signs


def compare_outlines(target_mm: Any, printed_mm: Any, *, allow_mirror: bool = True, regions: int = 8) -> dict[str, Any]:
    tl, pl = _loops(target_mm), _loops(printed_mm)
    if not tl or not pl:
        raise ValueError("both outlines need at least one closed loop")
    target, printed = tl[0], pl[0]
    t_s = _resample(target, 400)
    best = None
    for start in _pca_starts(_resample(printed, 400), t_s, allow_mirror):
        aligned, err = _icp(start, t_s)
        if best is None or err < best[1]:
            best = (aligned, err)
    assert best is not None
    aligned = best[0]
    # transform used for the outer loop also applies to the holes: recover it
    r, t = _rigid(_resample(printed, 400), aligned, allow_reflection=True)
    dense = _resample(aligned, 2000)
    sd = _signed_dist(t_s, target, dense)
    area_t, area_p = _area(target), _area(printed)
    scale = math.sqrt(area_p / area_t) if area_t else 1.0
    report: dict[str, Any] = {
        "max_mm": round(float(np.max(np.abs(sd))), 3),
        "mean_mm": round(float(np.mean(np.abs(sd))), 3),
        "rms_mm": round(float(np.sqrt(np.mean(sd * sd))), 3),
        "bias_mm": round(float(np.mean(sd)), 3),
        "scale": round(scale, 4),
        "area_target_mm2": round(area_t, 1),
        "area_printed_mm2": round(area_p, 1),
        "regions": [],
        "holes": [],
        "suggestions": [],
    }
    n = len(t_s)
    for k in range(regions):
        sl = slice(k * n // regions, (k + 1) * n // regions)
        seg = sd[sl]
        c = t_s[sl].mean(0)
        report["regions"].append({"index": k, "center": [round(float(c[0]), 1), round(float(c[1]), 1)],
                                  "mean_mm": round(float(np.mean(seg)), 3), "max_mm": round(float(seg[np.argmax(np.abs(seg))]), 3)})
    # holes: match by nearest centroid after alignment
    p_holes = [(h @ r.T + t) for h in pl[1:]]
    for th in tl[1:]:
        if not p_holes:
            break
        tc = th.mean(0)
        j = int(np.argmin([np.linalg.norm(h.mean(0) - tc) for h in p_holes]))
        ph = p_holes.pop(j)
        dt = 2 * math.sqrt(_area(th) / math.pi)
        dp = 2 * math.sqrt(_area(ph) / math.pi)
        report["holes"].append({"center": [round(float(tc[0]), 1), round(float(tc[1]), 1)], "target_d": round(dt, 3), "printed_d": round(dp, 3), "delta": round(dp - dt, 3)})
    bias = report["bias_mm"]
    if abs(bias) > 0.08:
        report["suggestions"].append({"param": "outerDelta", "delta": round(2 * bias, 3),
                                      "text": f"outer contour is {abs(bias):.2f} mm {'too big' if bias > 0 else 'too small'} per side; "
                                              f"{'shrink' if bias > 0 else 'grow'} outer dimensions by {abs(2 * bias):.2f} mm"})
    if report["holes"]:
        hd = float(np.mean([h["delta"] for h in report["holes"]]))
        if abs(hd) > 0.05:
            report["suggestions"].append({"param": "holeDelta", "delta": round(-hd, 3),
                                          "text": f"holes print {abs(hd):.2f} mm {'small' if hd < 0 else 'large'}; "
                                                  f"{'enlarge' if hd < 0 else 'reduce'} hole compensation by {abs(hd):.2f} mm"})
    for reg in report["regions"]:
        if abs(reg["mean_mm"] - bias) > 0.4:
            report["suggestions"].append({"param": None, "region": reg["index"],
                                          "text": f"local deviation {reg['mean_mm']:+.2f} mm near ({reg['center'][0]}, {reg['center'][1]}): "
                                                  "warping, elephant foot or a wrong feature size there"})
    report["ok"] = report["max_mm"] <= 0.5 and not any(s.get("region") is not None for s in report["suggestions"])
    return report
