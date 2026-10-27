"""Synthetic photos with exact ground truth: a pinhole camera looking at an A4 sheet
with a part on it. Shared by the vision tests (and has its own sanity test)."""
from __future__ import annotations

import math

import cv2
import numpy as np

W, H = 2000, 1500
F = 1700.0
K = np.array([[F, 0, W / 2], [0, F, H / 2], [0, 0, 1.0]])
SHIFT = 4  # sub-pixel polygon filling


def look_at(eye, target, up=(0, 0, 1)):
    eye, target, up = (np.asarray(v, float) for v in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, up)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    R = np.stack([r, -u, f])
    return R, -R @ eye


def default_camera():
    # ~420 mm above the sheet, looking down at ~25° from vertical
    return look_at((105 + 60, 148.5 - 170, 380), (105, 148.5, 0))


def project(R, t, pts, K_=K):
    pts = np.asarray(pts, float)
    if pts.shape[1] == 2:
        pts = np.hstack([pts, np.zeros((len(pts), 1))])
    cam = pts @ R.T + t
    uv = cam[:, :2] / cam[:, 2:3]
    return np.column_stack([K_[0, 0] * uv[:, 0] + K_[0, 2], K_[1, 1] * uv[:, 1] + K_[1, 2]])


SS = 8  # supersampling: a pixel belongs to the shape iff >= 50% of it is covered


def fill(mask_shape, polys_px, value=1):
    big = np.zeros((mask_shape[0] * SS, mask_shape[1] * SS), np.uint8)
    # pixel centres sit at integer coordinates: shift by half a pixel into the supersampled grid
    pts = [np.round(((p + 0.5) * SS - 0.5) * (1 << SHIFT)).astype(np.int32) for p in polys_px]
    cv2.fillPoly(big, pts, 255, lineType=cv2.LINE_8, shift=SHIFT)
    small = cv2.resize(big, (mask_shape[1], mask_shape[0]), interpolation=cv2.INTER_AREA)
    return (small >= 128).astype(np.uint8) * value


def circle_pts(cx, cy, r, n=180):
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a)])


def sheet_world(w=210.0, h=297.0):
    return np.array([[0, 0], [w, 0], [w, h], [0, h]], float)


def part_world(x0=80.0, y0=120.0, w=60.0, h=40.0):
    return np.array([[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]], float)


def scene(R=None, t=None, part_z=0.0, hole_d=10.0, rotate_sheet=False):
    """Returns (bgr image, sheet mask, part mask, R, t). Part: 60x40 mm with a centred hole."""
    if R is None:
        R, t = default_camera()
    sheet = sheet_world()
    if rotate_sheet:  # landscape: sheet spans 297 along x
        sheet = np.array([[0, 0], [297, 0], [297, 210], [0, 210]], float)
    sheet_px = project(R, t, sheet)
    part = part_world()
    hole = circle_pts(110, 140, hole_d / 2)
    part_px = project(R, t, np.hstack([part, np.full((4, 1), part_z)]))
    hole_px = project(R, t, np.hstack([hole, np.full((len(hole), 1), part_z)]))
    sheet_mask = fill((H, W), [sheet_px])
    part_mask = fill((H, W), [part_px])
    part_mask[fill((H, W), [hole_px]) > 0] = 0
    img = np.full((H, W, 3), (60, 85, 120), np.uint8)
    img[sheet_mask > 0] = (232, 232, 228)
    img[part_mask > 0] = (40, 40, 190)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    return img, sheet_mask > 0, part_mask > 0, R, t


def test_synthetic_scene_is_sane():
    img, sheet, part, R, t = scene()
    assert sheet.sum() > part.sum() > 1000
    assert (part & ~sheet).sum() == 0
    assert img.shape == (H, W, 3)
