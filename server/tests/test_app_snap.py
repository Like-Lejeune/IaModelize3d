"""POST /api/snap answers with the instant sticker made right after the mask, so the page needs no second request."""
from __future__ import annotations

import io

import cv2
import httpx
import numpy as np
import pytest

from formwright import db as dbmod
from formwright.config import settings
from formwright.vision import ingest, snap


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    from formwright.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dbmod.close_db()


async def test_the_snap_answer_carries_the_sticker(client, monkeypatch):
    sticker = {"key": "s_1_d", "selection_id": None, "source": "lib.collect.sticker('subject')", "size_mm": [50, 32, 4]}

    async def no_blur(img, user=None):
        return img, 0

    async def fake_snap(user, project, asset, x, y, lang):
        return {"label": "скамейка", "objects": [], "selection": None, "removed": [], "sticker": sticker}

    monkeypatch.setattr(ingest, "_blur", no_blur)
    monkeypatch.setattr(snap, "snap", fake_snap)
    ok, buf = cv2.imencode(".jpg", np.full((120, 160, 3), 200, np.uint8))
    r = await client.post("/api/snap", files={"file": ("snap.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")}, data={"x": "0.5", "y": "0.5", "lang": "ru"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["sticker"] == sticker and out["label"] == "скамейка" and out["project"]["pack"] == "collect"

    async def no_sticker(user, project, asset, x, y, lang):
        return {"label": None, "objects": [], "selection": None, "removed": [], "sticker": None}

    monkeypatch.setattr(snap, "snap", no_sticker)
    r = await client.post("/api/snap", files={"file": ("snap.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")}, data={"lang": "en"})
    assert r.status_code == 200 and r.json()["sticker"] is None  # the page then asks GET .../sticker, as before
