"""vision/relief.py: a SAM mask and its photo become sticker inputs (outline loops with holes + relief heightmap)."""
from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from formwright.vision import relief


def _disk_with_hole(detail_texture: bool = False) -> tuple[np.ndarray, np.ndarray]:
    img = np.full((400, 500, 3), 90, np.uint8)
    if detail_texture:
        img[::6] = 230  # stripes: the photo detail the relief may press in
    mask = np.zeros((400, 500), np.uint8)
    cv2.circle(mask, (250, 200), 150, 1, -1)
    cv2.circle(mask, (330, 200), 30, 0, -1)  # the hole sits off-centre
    return img, mask.astype(bool)


def test_a_disk_with_a_hole_gives_two_loops_and_a_dome():
    img, mask = _disk_with_hole()
    t = time.perf_counter()
    r = relief.relief(img, mask)
    ms = (time.perf_counter() - t) * 1000
    assert ms < 200, f"{ms:.0f} ms"
    assert len(r["loops_px"]) == 2
    outer = max(r["loops_px"], key=len)
    xs = [p[0] for p in outer]
    assert abs(min(xs) - 100) < 3 and abs(max(xs) - 400) < 3  # photo pixels
    x0, y0, x1, y1 = r["crop_px"]
    assert x0 < 100 < 400 < x1 and y0 < 50 < 350 < y1
    hm = r["heightmap"]
    assert max(hm["w"], hm["h"]) == relief.GRID and len(hm["data"]) == hm["w"] * hm["h"]
    a = np.array(hm["data"]).reshape(hm["h"], hm["w"])
    assert a.max() == pytest.approx(1.0, abs=0.05)  # a plain photo: the dome alone
    # the top is inside the disk, away from the rim and the hole; outside the outline nothing
    j, i = np.unravel_index(np.argmax(a), a.shape)
    px, py = x0 + (i + 0.5) / hm["w"] * (x1 - x0), y0 + (j + 0.5) / hm["h"] * (y1 - y0)
    assert np.hypot(px - 250, py - 200) < 110 and np.hypot(px - 330, py - 200) > 30
    assert a[0, 0] == 0 and a[a.shape[0] // 2, int((330 - x0) / (x1 - x0) * hm["w"])] < 0.05  # the hole stays a hole


def test_photo_detail_is_pressed_in_but_never_for_people():
    img, mask = _disk_with_hole(detail_texture=True)
    plain = np.array(relief.relief(img, mask, detail=0)["heightmap"]["data"])
    textured = np.array(relief.relief(img, mask)["heightmap"]["data"])
    assert np.abs(textured - plain).max() > 0.1
    assert textured.max() <= 1.3 + 1e-6


def test_sticker_payload_feeds_the_kernel_program():
    img, mask = _disk_with_hole()
    s = relief.sticker(img, mask, name="кот", size=40)
    assert "lib.collect.sticker('subject'" in s["source"]
    inp = s["inputs"]
    assert set(inp) == {"outlines", "heightmaps", "values"} and len(inp["outlines"]["subject"]) == 2
    assert inp["values"]["name"] == "кот" and inp["values"]["subject_x1"] > inp["values"]["subject_x0"]
    assert s["params"] == {"size": 40} and max(s["size_mm"]) == pytest.approx(40, abs=0.2)
    with pytest.raises(ValueError):
        relief.relief(img, np.zeros(mask.shape, bool))
