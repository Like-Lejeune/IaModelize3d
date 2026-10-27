"""Pure geometry for metric measurement from photos (no IO, no API calls).

World frame of a calibrated photo: the reference plane in millimetres. Origin at the
reference's bottom-left corner as seen in the image, x to the right, y away from the
viewer, z up out of the plane (towards the camera). Camera convention is OpenCV:
Xc = R Xw + t, x right, y down, z forward — the same as the geometry renderer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

SHEETS = {"A4": (210.0, 297.0), "A5": (148.0, 210.0), "Letter": (215.9, 279.4)}


# ------------------------------------------------------------------ corners
def order_corners(pts: np.ndarray) -> np.ndarray:
    """Image-space order TL, TR, BR, BL (y down)."""
    pts = np.asarray(pts, dtype=float).reshape(4, 2)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]
    start = int(np.argmin(pts.sum(axis=1)))
    return np.roll(pts, -start, axis=0)


def _line_intersection(l1: np.ndarray, l2: np.ndarray) -> np.ndarray | None:
    # lines as (vx, vy, x0, y0)
    vx1, vy1, x1, y1 = l1
    vx2, vy2, x2, y2 = l2
    den = vx1 * vy2 - vy1 * vx2
    if abs(den) < 1e-9:
        return None
    s = ((x2 - x1) * vy2 - (y2 - y1) * vx2) / den
    return np.array([x1 + s * vx1, y1 + s * vy1])


def fit_quad(mask: np.ndarray) -> np.ndarray | None:
    """Corners of a (perspective) quadrilateral mask, sub-pixel, ordered TL, TR, BR, BL.

    Rough corners come from the convex hull; each side is then re-fitted to the
    boundary points of its middle part (robust to rounded card corners) and the
    sides are intersected.
    """
    m = mask.astype(np.uint8)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 400:
        return None
    hull = cv2.convexHull(c)
    peri = cv2.arcLength(hull, True)
    approx = None
    for k in np.linspace(0.005, 0.12, 40):
        a = cv2.approxPolyDP(hull, k * peri, True)
        if len(a) == 4:
            approx = a.reshape(4, 2).astype(float)
            break
    if approx is None:
        approx = cv2.boxPoints(cv2.minAreaRect(c)).astype(float)
    rough = order_corners(approx)
    # boundary points (pixel edge centres) for line fitting
    pts = c.reshape(-1, 2).astype(float)
    lines = []
    for i in range(4):
        a, b = rough[i], rough[(i + 1) % 4]
        d = b - a
        L = float(np.hypot(*d))
        if L < 5:
            return rough
        u = d / L
        n = np.array([-u[1], u[0]])
        rel = pts - a
        along = rel @ u
        across = rel @ n
        sel = (along > 0.12 * L) & (along < 0.88 * L) & (np.abs(across) < max(3.0, 0.02 * L))
        if sel.sum() < 8:
            lines.append(np.array([u[0], u[1], a[0], a[1]]))
            continue
        vx, vy, x0, y0 = cv2.fitLine(pts[sel].astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).reshape(-1)
        lines.append(np.array([vx, vy, x0, y0], dtype=float))
    corners = []
    for i in range(4):
        p = _line_intersection(lines[(i - 1) % 4], lines[i])
        if p is None or np.hypot(*(p - rough[i])) > 0.1 * peri:
            p = rough[i]
        corners.append(p)
    corners = np.array(corners)
    # contour points are pixel centres of boundary pixels; the true edge is ~0.5 px further out
    centre = corners.mean(axis=0)
    out = centre + (corners - centre) * (1 + 0.5 * math.sqrt(2) / max(1.0, float(np.mean(np.hypot(*(corners - centre).T)))))
    return order_corners(out)


# ------------------------------------------------------------------ camera
def default_focal(width: int, height: int) -> float:
    return 0.85 * max(width, height)


def focal_from_35mm(f35: float, width: int, height: int) -> float:
    """35 mm-equivalent focal length is defined on the 43.27 mm diagonal."""
    return f35 * math.hypot(width, height) / 43.2666


def intrinsics(f: float, width: int, height: int) -> np.ndarray:
    return np.array([[f, 0, width / 2], [0, f, height / 2], [0, 0, 1.0]])


def focal_from_homography(H_mm2px: np.ndarray, width: int, height: int) -> float | None:
    """Zhang's constraint with a known principal point (image centre) and square pixels."""
    T = np.array([[1, 0, -width / 2], [0, 1, -height / 2], [0, 0, 1.0]])
    Hc = T @ H_mm2px
    a1, b1, c1 = Hc[:, 0]
    a2, b2, c2 = Hc[:, 1]
    cands = []
    if abs(c1 * c2) > 1e-12:
        f2 = -(a1 * a2 + b1 * b2) / (c1 * c2)
        if f2 > 0:
            cands.append(math.sqrt(f2))
    den = c2 * c2 - c1 * c1
    if abs(den) > 1e-12:
        f2 = (a1 * a1 + b1 * b1 - a2 * a2 - b2 * b2) / den
        if f2 > 0:
            cands.append(math.sqrt(f2))
    lo, hi = 0.3 * max(width, height), 3.0 * max(width, height)
    cands = [f for f in cands if lo < f < hi]
    if not cands:
        return None
    return float(np.median(cands))


def _rect_world(w_mm: float, h_mm: float) -> np.ndarray:
    # TL, TR, BR, BL image order -> world (0,h), (w,h), (w,0), (0,0)
    return np.array([[0, h_mm], [w_mm, h_mm], [w_mm, 0], [0, 0]], dtype=float)


def _ortho_score(H_mm2px: np.ndarray, K: np.ndarray) -> float:
    M = np.linalg.inv(K) @ H_mm2px
    h1, h2 = M[:, 0], M[:, 1]
    n1, n2 = np.linalg.norm(h1), np.linalg.norm(h2)
    if n1 < 1e-12 or n2 < 1e-12:
        return 1e9
    return abs(math.log(n1 / n2)) + abs(float(h1 @ h2) / (n1 * n2))


@dataclass
class PlaneCalibration:
    corners_px: np.ndarray
    size_mm: tuple[float, float]  # along TL->TR, along BL->TL
    H_px2mm: np.ndarray
    H_mm2px: np.ndarray
    K: np.ndarray
    R: np.ndarray
    t: np.ndarray
    rvec: np.ndarray
    reproj_px: float
    focal_source: str
    width: int
    height: int

    @property
    def camera_center(self) -> np.ndarray:
        return -self.R.T @ self.t

    @property
    def camera_height_mm(self) -> float:
        return float(self.camera_center[2])

    def mm_per_px_at(self, px: np.ndarray) -> float:
        """Local scale (sqrt of the Jacobian determinant of px->mm) at a pixel."""
        x, y = float(px[0]), float(px[1])
        e = 1.0
        p = apply_h(self.H_px2mm, np.array([[x, y], [x + e, y], [x, y + e]]))
        a, b = p[1] - p[0], p[2] - p[0]
        return math.sqrt(abs(a[0] * b[1] - a[1] * b[0]))

    def to_dict(self) -> dict[str, Any]:
        centre = self.corners_px.mean(axis=0)
        return {
            "ok": True,
            "kind": "plane",
            "corners_px": self.corners_px.round(3).tolist(),
            "size_mm": list(self.size_mm),
            "H_px2mm": self.H_px2mm.tolist(),
            "H_mm2px": self.H_mm2px.tolist(),
            "K": self.K.tolist(),
            "R": self.R.tolist(),
            "t": self.t.reshape(-1).tolist(),
            "rvec": self.rvec.reshape(-1).tolist(),
            "reproj_px": round(self.reproj_px, 4),
            "focal_source": self.focal_source,
            "mm_per_px": round(self.mm_per_px_at(centre), 5),
            "camera_height_mm": round(self.camera_height_mm, 2),
            "width": self.width,
            "height": self.height,
        }


def apply_h(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype=float).reshape(-1, 2)
    hom = np.hstack([pts, np.ones((len(pts), 1))]) @ H.T
    return hom[:, :2] / hom[:, 2:3]


def calibrate_plane(corners_px: np.ndarray, short_mm: float, long_mm: float, width: int, height: int, focal: float | None = None,
                    focal_source: str = "default") -> PlaneCalibration:
    """Homography + pose from the 4 corners of a rectangle of known size.

    Which image side is the long one is decided by which assignment gives a
    rotation-like (orthogonal, equal-norm) homography for the camera.
    """
    corners = order_corners(corners_px)
    best = None
    for w_mm, h_mm in ((short_mm, long_mm), (long_mm, short_mm)):
        world = _rect_world(w_mm, h_mm)
        H = cv2.getPerspectiveTransform(world.astype(np.float32), corners.astype(np.float32)).astype(float)
        f, src = focal, focal_source
        if f is None:
            est = focal_from_homography(H, width, height)
            f, src = (est, "estimated") if est else (default_focal(width, height), "default")
        K = intrinsics(f, width, height)
        score = _ortho_score(H, K)
        if best is None or score < best[0]:
            best = (score, w_mm, h_mm, H, K, src)
    _, w_mm, h_mm, H_mm2px, K, src = best  # type: ignore[misc]
    world = _rect_world(w_mm, h_mm)
    obj = np.hstack([world, np.zeros((4, 1))]).astype(np.float64)
    ok, rvec, tvec = cv2.solvePnP(obj, corners.astype(np.float64), K, None, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        raise ValueError("pose estimation failed")
    R, _ = cv2.Rodrigues(rvec)
    if (-R.T @ tvec)[2] < 0:  # camera must be above the plane (z up)
        ok, rvecs, tvecs, _ = cv2.solvePnPGeneric(obj, corners.astype(np.float64), K, None, flags=cv2.SOLVEPNP_IPPE)
        for rv, tv in zip(rvecs, tvecs):
            Rr, _ = cv2.Rodrigues(rv)
            if (-Rr.T @ tv)[2] > 0:
                rvec, tvec, R = rv, tv, Rr
                break
    proj, _ = cv2.projectPoints(obj, rvec, tvec, K, None)
    reproj = float(np.mean(np.hypot(*(proj.reshape(-1, 2) - corners).T)))
    return PlaneCalibration(
        corners_px=corners, size_mm=(w_mm, h_mm), H_px2mm=np.linalg.inv(H_mm2px), H_mm2px=H_mm2px, K=K, R=R, t=tvec.reshape(3),
        rvec=rvec.reshape(3), reproj_px=reproj, focal_source=src, width=width, height=height,
    )


def calibration_from_dict(d: dict[str, Any]) -> PlaneCalibration | None:
    if not d or not d.get("ok") or d.get("kind") != "plane":
        return None
    return PlaneCalibration(
        corners_px=np.array(d["corners_px"]), size_mm=tuple(d["size_mm"]), H_px2mm=np.array(d["H_px2mm"]), H_mm2px=np.array(d["H_mm2px"]),
        K=np.array(d["K"]), R=np.array(d["R"]), t=np.array(d["t"]), rvec=np.array(d["rvec"]), reproj_px=d["reproj_px"],
        focal_source=d["focal_source"], width=d["width"], height=d["height"],
    )


def pixels_to_plane(cal: PlaneCalibration, px: np.ndarray, height_mm: float = 0.0) -> np.ndarray:
    """Back-project pixels onto the plane z = height_mm (parallax correction for tall parts)."""
    px = np.asarray(px, dtype=float).reshape(-1, 2)
    if abs(height_mm) < 1e-9:
        return apply_h(cal.H_px2mm, px)
    Kinv = np.linalg.inv(cal.K)
    rays = (np.hstack([px, np.ones((len(px), 1))]) @ Kinv.T) @ cal.R  # == (R^T d) per row
    C = cal.camera_center
    lam = (height_mm - C[2]) / rays[:, 2]
    world = C[None, :] + lam[:, None] * rays
    return world[:, :2]


def project_world(cal: PlaneCalibration, pts_mm: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts_mm, dtype=float)
    if pts.shape[1] == 2:
        pts = np.hstack([pts, np.zeros((len(pts), 1))])
    proj, _ = cv2.projectPoints(pts, cal.rvec, cal.t, cal.K, None)
    return proj.reshape(-1, 2)


# ------------------------------------------------------------------ scale-only references
def scale_from_circle(mask: np.ndarray, diameter_mm: float) -> dict[str, Any] | None:
    """Coins: under perspective a circle becomes an ellipse; its major axis keeps the
    true scale along one direction, so major-axis px/mm is a fair local scale."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if len(c) < 20:
        return None
    (cx, cy), (a, b), ang = cv2.fitEllipse(c)
    major = max(a, b)
    return {"ok": True, "kind": "scale_only", "mm_per_px": diameter_mm / major, "center_px": [cx, cy], "axes_px": [a, b], "angle": ang,
            "tilt_deg": round(math.degrees(math.acos(min(1.0, min(a, b) / major))), 1)}


def scale_from_length(mask: np.ndarray, length_mm: float) -> dict[str, Any] | None:
    """Batteries, bricks: the long side of the minimum-area rectangle."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    (cx, cy), (w, h), ang = cv2.minAreaRect(max(contours, key=cv2.contourArea))
    long_px = max(w, h)
    if long_px < 10:
        return None
    return {"ok": True, "kind": "scale_only", "mm_per_px": length_mm / long_px, "center_px": [cx, cy], "rect_px": [w, h], "angle": ang}


# ------------------------------------------------------------------ shapes in mm
def signed_area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def orient(poly: np.ndarray, ccw: bool) -> np.ndarray:
    a = signed_area(poly)
    return poly if (a > 0) == ccw else poly[::-1]


def fit_circle(pts: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Algebraic (Kasa) circle fit: centre, radius, RMS residual."""
    pts = np.asarray(pts, dtype=float)
    A = np.column_stack([2 * pts[:, 0], 2 * pts[:, 1], np.ones(len(pts))])
    b = (pts**2).sum(axis=1)
    (cx, cy, c), *_ = np.linalg.lstsq(A, b, rcond=None)
    r = math.sqrt(max(c + cx * cx + cy * cy, 0.0))
    res = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - r
    return np.array([cx, cy]), r, float(np.sqrt(np.mean(res**2)))


def polygon_area(poly: np.ndarray) -> float:
    return abs(signed_area(np.asarray(poly, dtype=float)))
