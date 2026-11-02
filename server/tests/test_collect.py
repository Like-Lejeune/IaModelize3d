"""Snap & collect without the agent (formwright/collect.py): the sticker payload, "keep" as an instant version and the
collection plate on one bed. SAM, the namer and the geometry pool are fakes; the relief is real."""
from __future__ import annotations

import base64
import io

import cv2
import httpx
import numpy as np
import pytest

from formwright import collect, db as dbmod
from formwright.config import settings
from formwright.geom import GeomError
from formwright.vision import ingest, snap
from formwright.vision.sam import Mask

PNG = base64.b64encode(cv2.imencode(".png", np.zeros((4, 4, 3), np.uint8))[1].tobytes()).decode()


class FakePool:
    """Answers like the geom pool: a sticker is ~55 x 44 mm, a plate packs four to a row on the 256 mm bed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict]] = []

    def _size(self, source: str, params: dict, inputs: dict) -> list[float]:
        if "lib.collect.plate" in source:
            n = len(str(inputs["values"]["keys"]).split(","))
            if n > 8:
                raise GeomError("runtime", f"assertion failed: the collection does not fit one bed: {n} stickers at 48 mm need 240 x 250 mm")
            return [min(n, 4) * 57.0, ((n + 3) // 4) * 52.0, 6.4]
        return [params.get("size", 50) * 1.1, params.get("size", 50) * 0.88, 6.3]

    async def build(self, source, params=None, *, analyze="fast", mesh=False, **extra):
        self.calls.append(("build", source, params or {}, extra))
        size = self._size(source, params or {}, extra["inputs"])
        n = len(str(extra["inputs"]["values"].get("keys", "x")).split(","))
        return {"ok": True, "params": {**(params or {})}, "paramSpecs": {"size": {"value": 50}}, "handles": [],
                "parts": [{"name": "base"}, {"name": "figure"}, {"name": "name"}],
                "checks": {"ok": True, "score": 100, "issues": [{"code": "short_layer_time", "severity": "info"}],
                           "stats": {"size": size, "estGrams": 3.8 * n, "estMinutes": 8.0 * n}}}

    async def render(self, source, params=None, **extra):
        self.calls.append(("render", source, params or {}, extra))
        return {"png": PNG}


def _photo() -> bytes:
    img = np.full((300, 400, 3), 200, np.uint8)
    cv2.rectangle(img, (120, 100), (280, 220), (40, 60, 90), -1)
    cv2.line(img, (120, 150), (280, 150), (230, 230, 230), 3)  # a slat for the relief's photo detail
    return cv2.imencode(".jpg", img)[1].tobytes()


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "blur_faces", False)
    await dbmod.close_db()
    db = await dbmod.get_db()
    named = {"person": False}

    async def fake_segment(meter, image, *, text=None, points=None, box=None):
        m = np.zeros(image.shape[:2], bool)
        m[100:220, 120:280] = True
        m[150:170, 150:170] = False  # a hole between the slats
        return [Mask(id="1", bbox_px=[120, 100, 280, 220], score=0.9, mask=m)]

    async def fake_name(meter, img, mask, gx, gy, lang, model):
        return {"label": "скамейка", "part_only": False, "box": [300, 333, 700, 733], "organic": False, "person": named["person"], "objects": []}

    async def no_blur(img, user=None):
        return img, 0

    monkeypatch.setattr(snap, "segment", fake_segment)
    monkeypatch.setattr(snap, "_name", fake_name)
    monkeypatch.setattr(ingest, "_blur", no_blur)
    pool = FakePool()
    monkeypatch.setattr(collect, "geom", lambda: pool)
    from formwright.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, db, pool, named
    await dbmod.close_db()


async def _snap(c, named: bool = True) -> str:
    r = await c.post("/api/snap", files={"file": ("snap.jpg", io.BytesIO(_photo()), "image/jpeg")}, data={"x": "0.5", "y": "0.5", "lang": "ru"})
    assert r.status_code == 200, r.text
    pid = r.json()["project"]["id"]
    if named:
        assert (await c.get(f"/api/snap/{pid}/name")).json()["label"] == "скамейка"
    return pid


async def test_the_snap_has_a_sticker_the_browser_can_build(env):
    c, db, pool, _ = env
    pid = await _snap(c)
    r = await c.get(f"/api/snap/{pid}/sticker")
    assert r.status_code == 200, r.text
    s = r.json()
    assert "lib.collect.sticker('subject'" in s["source"] and s["params"] == {"size": 50}
    inp = s["inputs"]
    assert len(inp["outlines"]["subject"]) == 2  # the outline and its hole
    assert inp["values"]["name"] == "скамейка" and inp["heightmaps"]["subject"]["w"] == 180
    assert s["detail"] > 0 and max(s["size_mm"]) == pytest.approx(50, abs=0.2)
    # unchanged: the client keeps what it has
    assert (await c.get(f"/api/snap/{pid}/sticker", params={"have": s["key"]})).json() == {"key": s["key"], "same": True}
    # the server-rendered preview for slow phones
    r = await c.post(f"/api/snap/{pid}/sticker.png", json={"size": 40, "label": "лавка"})
    assert r.headers["content-type"] == "image/png"
    _, src, params, extra = pool.calls[-1]
    assert params == {"size": 40} and extra["inputs"]["values"]["name"] == "лавка" and extra["views"] == collect.COVER_VIEW


async def test_keep_saves_an_instant_version_without_the_agent(env):
    c, db, pool, _ = env
    pid = await _snap(c)
    r = await c.post(f"/api/snap/{pid}/keep", json={"label": "парковая скамейка", "size": 40})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["version"] == 1 and out["ok"] and out["score"] == 100 and out["issues"] == []
    assert out["cover"].endswith("/renders/v1_iso.png") and out["project"]["title"] == "Парковая скамейка"
    est = out["est"]
    assert est["minutes"] > 8 and est["grams_range"][0] <= est["grams"] <= est["grams_range"][1]
    assert est["price"]["currency"] == "KZT" and est["price"]["usd"]["total"] == pytest.approx(est["price"]["total"] / est["price"]["usd"]["rate"], abs=0.01)
    build = next(x for x in pool.calls if x[0] == "build")
    assert build[2] == {"size": 40} and build[3]["inputs"]["values"]["name"] == "парковая скамейка"
    prog = await db.one("SELECT * FROM programs WHERE project_id = ?", pid)
    assert prog["author"] == "instant" and "lib.collect.sticker" in prog["source"] and prog["inputs"]["outlines"]["subject"]
    p = await db.one("SELECT * FROM projects WHERE id = ?", pid)
    assert p["version"] == 1 and p["cover"] and p["brief"]["snap"]["sticker"]["version"] == 1
    ev = await db.one("SELECT data FROM events WHERE project_id = ? AND type = 'program.updated'", pid)
    assert ev["data"]["author"] == "instant" and ev["data"]["version"] == 1
    items = (await c.get("/api/collection")).json()
    assert [(i["id"], i["state"]) for i in items] == [(pid, "ready")]
    # keeping again makes the next version, not a second project
    assert (await c.post(f"/api/snap/{pid}/keep", json={"size": 60})).json()["version"] == 2


async def test_keep_waits_for_a_running_agent(env):
    c, db, pool, _ = env
    pid = await _snap(c)
    user = await db.one("SELECT * FROM users")
    await db.insert("jobs", {"id": "j1", "project_id": pid, "user_id": user["id"], "kind": "design", "status": "running", "created_at": dbmod.now()})
    r = await c.post(f"/api/snap/{pid}/keep", json={"size": 50})
    assert r.status_code == 409 and r.json()["code"] == "project_busy"
    assert not pool.calls


async def test_a_person_gets_no_photo_detail(env):
    c, db, pool, named = env
    named["person"] = True
    pid = await _snap(c)
    s = (await c.get(f"/api/snap/{pid}/sticker")).json()
    assert s["detail"] == 0 and s["key"].endswith("_p")


async def test_six_finds_go_on_one_plate(env):
    c, db, pool, _ = env
    ids = [await _snap(c) for _ in range(6)]
    assert (await c.post(f"/api/snap/{ids[0]}/keep", json={"label": "кот", "size": 50})).status_code == 200
    pool.calls.clear()
    r = await c.post("/api/collection/plate", json={"ids": ids + ["p_not_mine"], "size_mm": 48})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["count"] == 6 and out["skipped"] == ["p_not_mine"] and out["fits"] is True
    assert out["bed"] == [256, 256] and out["size_mm"][0] <= 240
    assert out["a1_mini"] is False  # 228 mm wide: the A1 mini's 180 mm bed needs fewer or smaller
    assert out["est"]["minutes"] > 6 * 8 and out["est"]["price"]["total"] > 0
    build = next(x for x in pool.calls if x[0] == "build")
    inputs = build[3]["inputs"]
    assert inputs["values"]["keys"] == "s0,s1,s2,s3,s4,s5" and set(inputs["outlines"]) == {f"s{i}" for i in range(6)}
    assert inputs["values"]["s0_name"] == "кот" and inputs["values"]["s1_name"] == "скамейка"  # the kept sticker's name
    assert build[3].get("printer", {"bed": [256, 256, 256]})["bed"][:2] == [256, 256]
    p = await db.one("SELECT * FROM projects WHERE id = ?", out["project_id"])
    assert p["pack"] == "collect" and p["version"] == 1 and [i["id"] for i in p["brief"]["plate"]["items"]] == ids
    prog = await db.one("SELECT * FROM programs WHERE project_id = ?", out["project_id"])
    assert "lib.collect.plate" in prog["source"] and prog["author"] == "instant"
    # the plate is a project of its own, not one more find
    assert out["project_id"] not in {i["id"] for i in (await c.get("/api/collection")).json()}


async def test_a_plate_too_big_for_the_bed_is_refused(env):
    c, db, pool, _ = env
    ids = [await _snap(c, named=False) for _ in range(9)]
    before = len(await db.all("SELECT id FROM projects"))
    r = await c.post("/api/collection/plate", json={"ids": ids})
    assert r.status_code == 422 and r.json()["code"] == "plate_too_big" and r.json()["fits"] is False
    assert "does not fit one bed" in r.json()["detail"]
    assert len(await db.all("SELECT id FROM projects")) == before
    r = await c.post("/api/collection/plate", json={"ids": ["p_nope"]})
    assert r.status_code == 400 and r.json()["code"] == "nothing_to_plate"
