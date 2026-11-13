"""Experimental: 3D shape from silhouettes (visual hull / space carving).

Each view is a calibrated camera (OpenCV convention, world in mm) plus a part mask.
Voxels whose centre projects inside every mask survive. With a turntable of ArUco
markers the poses come from the markers, so a 10-second turn of the phone around
the part gives a metric 3D envelope without a scanner.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import cv2
import numpy as np


def _camera(c: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    R = np.asarray(c["R"], dtype=float).reshape(3, 3)
    t = np.asarray(c["t"], dtype=float).reshape(3)
    K = np.array([[c["fx"], 0, c["cx"]], [0, c["fy"], c["cy"]], [0, 0, 1.0]])
    return R, t, K, int(c["width"]), int(c["height"])


def carve(views: Sequence[dict[str, Any]], bounds: tuple[Sequence[float], Sequence[float]], voxel: float) -> dict[str, Any]:
    """views: [{"camera": geom Camera json, "mask": bool HxW}] -> occupancy grid."""
    lo = np.asarray(bounds[0], dtype=float)
    hi = np.asarray(bounds[1], dtype=float)
    n = np.maximum(1, np.ceil((hi - lo) / voxel).astype(int))
    xs = lo[0] + (np.arange(n[0]) + 0.5) * voxel
    ys = lo[1] + (np.arange(n[1]) + 0.5) * voxel
    zs = lo[2] + (np.arange(n[2]) + 0.5) * voxel
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    keep = np.ones(len(pts), dtype=bool)
    for v in views:
        R, t, K, w, h = _camera(v["camera"])
        mask = np.asarray(v["mask"], dtype=bool)
        cam = pts[keep] @ R.T + t
        z = cam[:, 2]
        ok = z > 1e-6
        u = np.full(len(cam), -1, int)
        vv = np.full(len(cam), -1, int)
        u[ok] = np.floor(K[0, 0] * cam[ok, 0] / z[ok] + K[0, 2]).astype(int)
        vv[ok] = np.floor(K[1, 1] * cam[ok, 1] / z[ok] + K[1, 2]).astype(int)
        inside = ok & (u >= 0) & (u < w) & (vv >= 0) & (vv < h)
        hit = np.zeros(len(cam), dtype=bool)
        hit[inside] = mask[vv[inside], u[inside]]
        idx = np.flatnonzero(keep)
        keep[idx[~hit]] = False
    occ = keep.reshape(n)
    return {"occupancy": occ, "origin": lo.tolist(), "voxel": voxel, "shape": n.tolist(), "volume_mm3": float(occ.sum()) * voxel**3}


def heightmap(result: dict[str, Any]) -> dict[str, Any]:
    """Top surface per XY column (mm above the plane), as a geom `inputs.heightmaps` entry."""
    occ = result["occupancy"]
    v = result["voxel"]
    nx, ny, nz = occ.shape
    top = np.where(occ.any(axis=2), (nz - np.argmax(occ[:, :, ::-1], axis=2)) * v + result["origin"][2], 0.0)
    # rows go from +y to -y like a picture (geom terrain convention)
    data = top.T[::-1].ravel().tolist()
    return {"w": nx, "h": ny, "data": data, "sizeX": nx * v, "sizeY": ny * v}


def surface_points(result: dict[str, Any], max_points: int = 4000) -> list[list[float]]:
    """Centres of boundary voxels, for `inputs.points`."""
    occ = result["occupancy"]
    padded = np.pad(occ, 1)
    interior = padded[1:-1, 1:-1, 1:-1] & padded[2:, 1:-1, 1:-1] & padded[:-2, 1:-1, 1:-1] & padded[1:-1, 2:, 1:-1] & padded[1:-1, :-2, 1:-1] \
        & padded[1:-1, 1:-1, 2:] & padded[1:-1, 1:-1, :-2]
    surf = np.argwhere(occ & ~interior)
    if len(surf) > max_points:
        surf = surf[np.linspace(0, len(surf) - 1, max_points).astype(int)]
    o = np.asarray(result["origin"])
    return ((surf + 0.5) * result["voxel"] + o).round(3).tolist()


# ------------------------------------------------------------------ ArUco turntable
DICT = cv2.aruco.DICT_4X4_50


def ring_layout(n: int = 12, radius_mm: float = 85.0, marker_mm: float = 18.0) -> dict[int, np.ndarray]:
    """Marker id -> its 4 corners (TL, TR, BR, BL as printed) in world mm on z=0, ring around the origin."""
    out: dict[int, np.ndarray] = {}
    s = marker_mm / 2
    for i in range(n):
        a = 2 * math.pi * i / n
        cx, cy = radius_mm * math.cos(a), radius_mm * math.sin(a)
        # marker "up" points away from the centre
        up = np.array([math.cos(a), math.sin(a)])
        right = np.array([up[1], -up[0]])
        c = np.array([cx, cy])
        corners = [c - right * s + up * s, c + right * s + up * s, c + right * s - up * s, c - right * s - up * s]
        out[i] = np.array([[p[0], p[1], 0.0] for p in corners])
    return out


def ring_sheet(n: int = 12, radius_mm: float = 85.0, marker_mm: float = 18.0, dpi: int = 300) -> np.ndarray:
    """Printable A4 image (portrait) of the marker ring, centred."""
    px = dpi / 25.4
    W, H = round(210 * px), round(297 * px)
    img = np.full((H, W), 255, np.uint8)
    d = cv2.aruco.getPredefinedDictionary(DICT)
    size = round(marker_mm * px)
    for mid, corners in ring_layout(n, radius_mm, marker_mm).items():
        tile = cv2.aruco.generateImageMarker(d, mid, size)
        src = np.array([[0, 0], [size - 1, 0], [size - 1, size - 1], [0, size - 1]], np.float32)
        dst = np.array([[W / 2 + p[0] * px, H / 2 - p[1] * px] for p in corners], np.float32)
        M = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(tile, M, (W, H), borderValue=255)
        region = cv2.warpPerspective(np.full_like(tile, 255), M, (W, H), borderValue=0) > 0
        img[region] = warped[region]
    cv2.circle(img, (W // 2, H // 2), round(3 * px), 0, 2)
    return img


def turntable_pose(frame: np.ndarray, K: np.ndarray, layout: dict[int, np.ndarray]) -> dict[str, Any] | None:
    """Camera pose from visible ring markers (needs >= 2 markers)."""
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(DICT), cv2.aruco.DetectorParameters())
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    corners, ids, _ = det.detectMarkers(gray)
    if ids is None:
        return None
    obj, img = [], []
    for c, i in zip(corners, ids.reshape(-1)):
        if int(i) in layout:
            obj.append(layout[int(i)])
            img.append(c.reshape(4, 2))
    if len(obj) < 2:
        return None
    obj_a = np.concatenate(obj).astype(np.float64)
    img_a = np.concatenate(img).astype(np.float64)
    ok, rvec, tvec = cv2.solvePnP(obj_a, img_a, K, None, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None
    R, _ = cv2.Rodrigues(rvec)
    proj, _ = cv2.projectPoints(obj_a, rvec, tvec, K, None)
    err = float(np.mean(np.hypot(*(proj.reshape(-1, 2) - img_a).T)))
    h, w = gray.shape[:2]
    return {"camera": {"width": w, "height": h, "R": R.reshape(-1).tolist(), "t": tvec.reshape(-1).tolist(),
                       "fx": float(K[0, 0]), "fy": float(K[1, 1]), "cx": float(K[0, 2]), "cy": float(K[1, 2])},
            "markers": len(obj), "reproj_px": err}
