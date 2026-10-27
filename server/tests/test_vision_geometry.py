"""Deterministic measurement pipeline on synthetic photos with exact ground truth."""
from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from formwright.vision import geometry as g
from formwright.vision.scene import calibration_from_mask, measure_mask, offset_px
from formwright.vision.sam import object_prompt, polygons

import test_vision_synth as syn

A4 = {"kind": "sheet", "w": 210.0, "h": 297.0}
CARD = {"kind": "card", "w": 85.60, "h": 53.98}


def asset(exif=None):
    return {"id": "a_test", "project_id": "p_test", "meta": {"exif": exif} if exif else {}}


def test_fit_quad_subpixel():
    _, sheet, _, R, t = syn.scene()
    truth = g.order_corners(syn.project(R, t, syn.sheet_world()))
    corners = g.fit_quad(sheet)
    err = np.hypot(*(corners - truth).T)
    assert err.max() < 0.8, err


@pytest.mark.parametrize("known_focal", [True, False])
def test_plane_pose_and_focal(known_focal):
    _, sheet, _, R, t = syn.scene()
    corners = syn.project(R, t, syn.sheet_world())
    cal = g.calibrate_plane(corners, 210, 297, syn.W, syn.H, focal=syn.F if known_focal else None, focal_source="test")
    assert cal.size_mm == (210, 297)
    assert cal.reproj_px < 0.01
    assert abs(cal.K[0, 0] - syn.F) / syn.F < (1e-6 if known_focal else 0.05)
    true_c = -R.T @ t
    assert np.linalg.norm(cal.camera_center - true_c) < (1e-3 if known_focal else 20)


def test_landscape_sheet_orientation():
    _, sheet, _, R, t = syn.scene(rotate_sheet=True)
    cal = calibration_from_mask(asset(), sheet, "A4", A4)
    assert cal["ok"] and tuple(cal["size_mm"]) == (297, 210)


def _measure(part_z=0.0, height=0.0, known=False, exif=None):
    _, sheet, part, R, t = syn.scene(part_z=part_z)
    cal = calibration_from_mask(asset(exif), sheet, "A4", A4)
    assert cal["ok"], cal
    return measure_mask(part, cal, height_mm=height, height_known=known), cal


def test_part_size_and_hole_within_half_mm():
    m, cal = _measure()
    assert m["calibrated"]
    long_, short = m["size_mm"]
    assert abs(long_ - 60) < 0.5 and abs(short - 40) < 0.5, m["size_mm"]
    lo = m["bbox_mm"]
    assert abs(lo[0] - 80) < 0.5 and abs(lo[1] - 120) < 0.5, lo
    assert len(m["holes_mm"]) == 1
    hole = m["holes_mm"][0]
    assert hole["circular"] and abs(hole["d"] - 10) < 0.5, hole
    assert abs(hole["center"][0] - 110) < 0.5 and abs(hole["center"][1] - 140) < 0.5
    assert abs(m["area_mm2"] - (60 * 40 - math.pi * 25)) < 40
    # outer CCW, hole CW: ready for lib.std.poly with NonZero fill
    assert g.signed_area(np.array(m["outline_mm"][0])) > 0 > g.signed_area(np.array(m["outline_mm"][1]))
    assert 0 < m["uncertainty_mm"] < 2


def test_focal_from_exif_35mm():
    # true F=1700 px on a 2000x1500 image: f35 = F * 43.27 / diag
    f35 = syn.F * 43.2666 / math.hypot(syn.W, syn.H)
    m, cal = _measure(exif={"focal_35mm": f35})
    assert cal["focal_source"] == "exif"
    assert abs(m["size_mm"][0] - 60) < 0.5


def test_parallax_correction_for_thick_parts():
    raw, _ = _measure(part_z=12.0)
    assert raw["size_mm"][0] - 60 > 1.0  # top face is closer to the camera: looks bigger
    fixed, _ = _measure(part_z=12.0, height=12.0, known=True)
    assert abs(fixed["size_mm"][0] - 60) < 0.5 and abs(fixed["size_mm"][1] - 40) < 0.5, fixed["size_mm"]
    assert fixed["uncertainty_mm"] < raw["uncertainty_mm"]


def test_bank_card_with_rounded_corners():
    R, t = syn.default_camera()
    # card lying flat at (60..145.6, 100..154) with 3.18 mm corner radius
    card = np.array([[60, 100], [145.6, 100], [145.6, 153.98], [60, 153.98]], float)
    poly = cv2.approxPolyDP(np.round(card).astype(np.int32), 1, True)  # noqa: F841 (shape reference)
    rounded = []
    r = 3.18
    for cx, cy, a0 in ((145.6 - r, 100 + r, -90), (145.6 - r, 153.98 - r, 0), (60 + r, 153.98 - r, 90), (60 + r, 100 + r, 180)):
        for a in np.linspace(math.radians(a0), math.radians(a0 + 90), 12):
            rounded.append([cx + r * math.cos(a), cy + r * math.sin(a)])
    mask = syn.fill((syn.H, syn.W), [syn.project(R, t, np.array(rounded))]) > 0
    cal = calibration_from_mask(asset(), mask, "ID-1 card", CARD)
    assert cal["ok"] and tuple(cal["size_mm"]) == (85.6, 53.98)
    # pose from the card predicts the A4 corners within ~1.5 mm
    plane = g.calibration_from_dict(cal)
    sheet_px = syn.project(R, t, syn.sheet_world())
    back = g.pixels_to_plane(plane, sheet_px)
    origin = np.array([60, 100])  # card BL corner is the world origin of this calibration
    err = np.hypot(*(back - (syn.sheet_world() - origin)).T)
    assert err.max() < 3.0, err


def test_coin_scale_only():
    R, t = syn.look_at((0, 0, 300), (0, 0.01, 0))
    coin = syn.circle_pts(0, 0, 23.25 / 2, 240)
    mask = syn.fill((syn.H, syn.W), [syn.project(R, t, coin)]) > 0
    d = g.scale_from_circle(mask, 23.25)
    expected = 300 / syn.F  # mm per px at 300 mm
    assert abs(d["mm_per_px"] - expected) / expected < 0.02


def test_offset_px_grows_both_orientations():
    sq = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)
    for poly in (sq, sq[::-1]):
        grown = offset_px(poly, 0.5)
        assert abs(g.polygon_area(grown) - 11 * 11) < 1.0


def test_polygons_with_holes():
    m = np.zeros((100, 100), bool)
    m[10:90, 10:90] = True
    m[40:60, 40:60] = False
    p = polygons(m)
    assert len(p) == 1 and len(p[0]["holes"]) == 1


def test_object_prompt_grammar():
    s = object_prompt(1200, 900, points=[{"x": 600, "y": 450, "positive": True}, {"x": 10, "y": 10, "positive": False}], box=[100, 100, 300, 200])
    assert s.startswith("<0f>1") and "box;" in s and "-<|point" in s and "w=1200;h=900" in s


def test_edge_snap_removes_sam_halo():
    img, sheet, part, R, t = syn.scene()
    cal = calibration_from_mask(asset(), sheet, "A4", A4)
    halo = cv2.dilate(part.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0  # SAM-like 3 px border bias, hole shrinks
    raw = measure_mask(halo, cal)
    snapped = measure_mask(halo, cal, image=img)
    assert raw["size_mm"][0] - 60 > 0.8 and 10 - raw["holes_mm"][0]["d"] > 0.8
    assert snapped["edge_snap"] > 0.8
    assert abs(snapped["size_mm"][0] - 60) < 0.4 and abs(snapped["size_mm"][1] - 40) < 0.4, snapped["size_mm"]
    assert abs(snapped["holes_mm"][0]["d"] - 10) < 0.4, snapped["holes_mm"]
