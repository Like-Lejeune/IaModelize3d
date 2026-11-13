"""Live Meta API checks on synthetic images (about $0.02).
Opt-in: needs a key and FW_LIVE_TESTS=1, so the default suite stays offline.

    cd server && FW_LIVE_TESTS=1 .venv/Scripts/python -m pytest -q tests/test_vision_live.py -s
"""
from __future__ import annotations

import os

import cv2
import numpy as np
import pytest

import test_vision_synth as syn
from test_vision_pipeline import env, jpeg_with_exif  # noqa: F401 (fixture)


def _live() -> bool:
    from iamodelize3d.config import Settings

    return os.environ.get("FW_LIVE_TESTS") == "1" and bool(Settings().meta_api_key)


pytestmark = pytest.mark.skipif(not _live(), reason="live Meta API: needs META_API_KEY and FW_LIVE_TESTS=1")


def caliper_image() -> np.ndarray:
    img = np.full((900, 1400, 3), (70, 90, 110), np.uint8)
    cv2.rectangle(img, (100, 380), (1300, 470), (190, 190, 195), -1)  # beam
    cv2.rectangle(img, (420, 250), (900, 520), (60, 60, 65), -1)  # body
    cv2.rectangle(img, (470, 290), (850, 400), (170, 190, 160), -1)  # LCD
    cv2.putText(img, "18.20", (500, 380), cv2.FONT_HERSHEY_SIMPLEX, 2.8, (20, 20, 20), 7, cv2.LINE_AA)
    cv2.putText(img, "mm", (760, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 20), 2, cv2.LINE_AA)
    for x in range(140, 1290, 12):
        cv2.line(img, (x, 470), (x, 455 if x % 60 else 445), (30, 30, 30), 2)
    return img


async def test_live_calibrate_select_detect_caliper(env):  # noqa: F811
    from iamodelize3d.db import get_db
    from iamodelize3d.llm.client import CostMeter
    from iamodelize3d.models import Point, SelectRequest
    from iamodelize3d.vision import ingest, scene

    db = await get_db()
    await db.insert("users", {"id": "u1", "tier": "admin", "created_at": 0})
    user = await db.one("SELECT * FROM users WHERE id = 'u1'")
    img, sheet, part, *_ = syn.scene()
    asset = await ingest.ingest_asset("p1", "photo", "s.jpg", jpeg_with_exif(img), "image/jpeg")

    meter = CostMeter(budget_usd=0.2)
    cal = await scene.calibrate(meter, asset)
    assert cal["ok"] and cal["reference"] == "A4", cal
    assert abs(cal["mm_per_px"] - 0.258) < 0.02

    asset = await db.one("SELECT * FROM assets WHERE id = ?", asset["id"])
    cy, cx = np.argwhere(part).mean(axis=0)
    sel = await scene.select(user, "p1", asset, SelectRequest(points=[Point(x=float(cx), y=float(cy) - 60)], role="target", name="part"))
    d = sel["data"]
    print("live select:", d["size_mm"], d.get("holes_mm"), d["uncertainty_mm"])
    assert abs(d["size_mm"][0] - 60) < 1.0 and abs(d["size_mm"][1] - 40) < 1.0

    found = await scene.detect(user, asset)
    print("detect:", found)
    assert any(r["kind"] == "sheet" for r in found["references"])

    cimg = caliper_image()
    ok, buf = cv2.imencode(".jpg", cimg)
    casset = await ingest.ingest_asset("p1", "caliper", "c.jpg", buf.tobytes(), "image/jpeg")
    reading = await scene.read_caliper(meter, casset)
    print("caliper:", reading, "spent", meter.summary())
    assert reading["found"] and abs(reading["value_mm"] - 18.2) < 0.01
