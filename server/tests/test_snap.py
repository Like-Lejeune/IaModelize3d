"""Snap & collect with SAM and the naming model stubbed: tap -> one named target selection with its instant
sticker, retakes leave nothing behind, a second snap waits behind the running job."""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import cv2
import httpx
import numpy as np
import pytest

from formwright import db as dbmod, quotas
from formwright.config import settings
from formwright.vision import ingest, snap
from formwright.vision.sam import Mask


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


def _photo() -> bytes:
    img = np.full((300, 400, 3), 200, np.uint8)
    cv2.rectangle(img, (120, 100), (280, 220), (40, 60, 90), -1)  # the "bench"
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


@pytest.fixture
def stubs(monkeypatch):
    calls: dict[str, list] = {"segment": [], "name": []}

    async def fake_segment(meter, image, *, text=None, points=None, box=None):
        calls["segment"].append({"points": points, "box": box})
        m = np.zeros(image.shape[:2], bool)
        if box:
            x1, y1, x2, y2 = (int(v) for v in box)
            m[y1:y2, x1:x2] = True
        else:
            m[100:220, 120:280] = True
        ys, xs = np.nonzero(m)
        return [Mask(id="1", bbox_px=[int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], score=0.9, mask=m)]

    async def fake_name(meter, img, mask, gx, gy, lang, model):
        calls["name"].append((gx, gy, lang, mask is not None))
        # says "a piece" only when the selection is much smaller than the bench
        part = mask is not None and mask.sum() < 1000
        return {"label": "скамейка", "part_only": part, "box": [300, 333, 700, 733], "organic": False,
                "objects": [{"label": "фонарь", "box": [0, 0, 100, 500]}, {"label": "", "box": [0, 0, 1, 1]}]}

    async def no_blur(img, user=None):
        return img, 0

    monkeypatch.setattr(snap, "segment", fake_segment)
    monkeypatch.setattr(snap, "_name", fake_name)
    monkeypatch.setattr(ingest, "_blur", no_blur)
    return calls


@pytest.fixture
async def client(fresh_db):
    from formwright.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _snap(client) -> dict:
    r = await client.post("/api/snap", files={"file": ("snap.jpg", io.BytesIO(_photo()), "image/jpeg")}, data={"x": "0.5", "y": "0.53", "lang": "ru"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_snap_names_and_selects_the_tapped_object(client, stubs, fresh_db):
    out = await _snap(client)
    # the highlight comes first, the name right after
    assert out["project"]["pack"] == "collect" and out["label"] is None
    sel = out["selection"]
    assert sel["role"] == "target" and sel["data"]["outline_px"]
    named = (await client.get(f"/api/snap/{out['project']['id']}/name")).json()
    assert named["label"] == "скамейка" and named["selection"]["name"] == "скамейка" and named["selection"]["id"] == sel["id"]
    assert [o["label"] for o in named["objects"]] == ["фонарь"]
    assert (await client.get(f"/api/projects/{out['project']['id']}")).json()["title"] == "Скамейка"
    assert (await client.get(f"/api/snap/{out['project']['id']}/name")).json()["label"] == "скамейка"  # answered from the brief later
    # the tap became SAM's positive point, at stored-image pixels
    pt = stubs["segment"][0]["points"][0]
    assert pt["positive"] and abs(pt["x"] - 0.5 * 399) < 1 and abs(pt["y"] - 0.53 * 299) < 1
    p = await fresh_db.one("SELECT * FROM projects WHERE id = ?", out["project"]["id"])
    assert p["brief"]["collect"] and p["brief"]["subject"] == "скамейка" and p["brief"]["photo_role"] == "copy"
    a = await fresh_db.one("SELECT * FROM assets WHERE id = ?", out["asset"]["id"])
    assert a["meta"]["calibration"]["ok"] is False  # no A4 search on street photos

    # refining keeps exactly one target selection, under the same name
    r = await client.post(f"/api/snap/{out['project']['id']}/select", json={"points": [{"x": 200, "y": 160, "positive": True}, {"x": 130, "y": 110, "positive": False}]})
    assert r.status_code == 200, r.text
    sels = await fresh_db.all("SELECT * FROM selections WHERE project_id = ?", out["project"]["id"])
    assert len(sels) == 1 and sels[0]["name"] == "скамейка" and sels[0]["id"] == r.json()["selection"]["id"]
    # another suggested object switches the name too
    r = await client.post(f"/api/snap/{out['project']['id']}/select", json={"box": [0, 0, 40, 150], "label": "фонарь"})
    assert r.json()["label"] == "фонарь"
    sels = await fresh_db.all("SELECT * FROM selections WHERE project_id = ?", out["project"]["id"])
    assert [s["name"] for s in sels] == ["фонарь"]


async def test_the_mask_comes_with_an_instant_sticker(client, stubs, fresh_db):
    out = await _snap(client)
    pid = out["project"]["id"]
    # made right after the mask and kept next to it, so the 3D preview needs no second pass over the photo
    cached = list((settings().data_dir / "files" / pid / "sticker").glob("*.json"))
    assert [f.name for f in cached] == [f"{out['selection']['id']}_d.json"]
    user = await fresh_db.one("SELECT * FROM users")
    p = await fresh_db.one("SELECT * FROM projects WHERE id = ?", pid)
    asset = await fresh_db.one("SELECT * FROM assets WHERE id = ?", out["asset"]["id"])
    r = await snap.snap(user, p, asset, 0.5, 0.53, "ru")
    s = r["sticker"]
    assert s["selection_id"] == r["selection"]["id"] and "lib.collect.sticker('subject'" in s["source"]
    assert s["inputs"]["outlines"]["subject"] and s["inputs"]["heightmaps"]["subject"]["data"] and s["detail"] > 0
    assert max(s["size_mm"]) == pytest.approx(50, abs=0.2)
    assert await snap.named(p, "ru")
    # the earlier selection's sticker is gone; the namer's verdict (no person) is kept for the next one
    assert [f.name for f in (settings().data_dir / "files" / pid / "sticker").glob("*.json")] == [f"{r['selection']['id']}_d.json"]
    assert (await fresh_db.one("SELECT brief FROM projects WHERE id = ?", pid))["brief"]["snap"]["person"] is False


async def test_people_on_a_photo_get_no_photo_detail_until_named(fresh_db):
    a = {"meta": {"faces_blurred": 2}}
    assert snap.sticker_detail({}, a) == 0
    assert snap.sticker_detail({"snap": {"person": False}}, a) == snap.relief.DETAIL
    assert snap.sticker_detail({"snap": {"person": True}}, {"meta": {}}) == 0
    assert snap.sticker_detail(None, {"meta": {}}) == snap.relief.DETAIL


async def test_retake_removes_the_draft(client, stubs, fresh_db):
    out = await _snap(client)
    pid = out["project"]["id"]
    assert (await client.delete(f"/api/snap/{pid}")).json() == {"ok": True}
    assert not await fresh_db.one("SELECT id FROM projects WHERE id = ?", pid)
    assert not (settings().data_dir / "files" / pid).exists()
    assert (await client.get("/api/collection")).json() == []


async def test_second_snap_waits_behind_the_running_job(client, stubs, fresh_db, monkeypatch):
    import formwright.agent.runner as runner

    started: list[str] = []

    async def fake_start(user, project, body):
        started.append(project["id"])
        jid = f"j{len(started)}"
        await fresh_db.insert("jobs", {"id": jid, "project_id": project["id"], "user_id": user["id"], "kind": "design",
                                       "status": "running", "created_at": dbmod.now()})
        # quotas count only jobs with a task behind them
        monkeypatch.setitem(runner._jobs, jid, SimpleNamespace(job_id=jid, project_id=project["id"], kind="design", cancelled=asyncio.Event()))
        return jid

    monkeypatch.setattr(runner, "start_design_job", fake_start)
    a, b = await _snap(client), await _snap(client)
    r1 = await client.post(f"/api/snap/{a['project']['id']}/confirm", json={"text": "миниатюра", "label": "скамейка"})
    r2 = await client.post(f"/api/snap/{b['project']['id']}/confirm", json={"text": "миниатюра"})
    assert r1.json()["queued"] is False and r2.json()["queued"] is True
    states = {i["id"]: i["state"] for i in (await client.get("/api/collection")).json()}
    assert states == {a["project"]["id"]: "modelling", b["project"]["id"]: "queued"}
    # the first job ends: the queued one starts
    await fresh_db.execute("UPDATE jobs SET status = 'done' WHERE id = 'j1'")
    for _ in range(50):
        if len(started) == 2:
            break
        await asyncio.sleep(0.2)
    assert started == [a["project"]["id"], b["project"]["id"]]
    p = await fresh_db.one("SELECT brief FROM projects WHERE id = ?", b["project"]["id"])
    assert "queued" not in p["brief"]


async def test_tap_on_a_detail_grows_to_the_named_object(client, stubs, fresh_db, monkeypatch):
    async def detail_segment(meter, image, *, text=None, points=None, box=None):
        m = np.zeros(image.shape[:2], bool)
        if box:
            x1, y1, x2, y2 = (int(v) for v in box)
            m[y1:y2, x1:x2] = True
        else:
            x, y = int(points[0]["x"]), int(points[0]["y"])
            m[y - 5:y + 5, x - 5:x + 5] = True  # SAM picked just the slat under the finger
        ys, xs = np.nonzero(m)
        return [Mask(id="1", bbox_px=[int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], score=0.9, mask=m)]

    monkeypatch.setattr(snap, "segment", detail_segment)
    out = await _snap(client)
    named = (await client.get(f"/api/snap/{out['project']['id']}/name")).json()
    assert named["selection"]["id"] != out["selection"]["id"]
    assert named["selection"]["data"]["bbox_px"][2] - named["selection"]["data"]["bbox_px"][0] > 150
    sels = await fresh_db.all("SELECT * FROM selections WHERE project_id = ?", out["project"]["id"])
    assert len(sels) == 1 and sels[0]["name"] == "скамейка"


async def test_a_whole_other_object_is_not_grown_into(client, stubs, fresh_db, monkeypatch):
    # the namer's box is a neighbour (a bowl in front of a TV stand): the small mask stays as it is
    async def small_segment(meter, image, *, text=None, points=None, box=None):
        m = np.zeros(image.shape[:2], bool)
        x, y = int(points[0]["x"]), int(points[0]["y"])
        m[y - 5:y + 5, x - 5:x + 5] = True
        return [Mask(id="1", bbox_px=[x - 5, y - 5, x + 5, y + 5], score=0.9, mask=m)]

    async def other_name(meter, img, mask, gx, gy, lang, model):
        return {"label": "миска", "part_only": False, "box": [0, 0, 1000, 1000], "organic": False, "objects": []}

    monkeypatch.setattr(snap, "segment", small_segment)
    monkeypatch.setattr(snap, "_name", other_name)
    out = await _snap(client)
    named = (await client.get(f"/api/snap/{out['project']['id']}/name")).json()
    assert named["selection"]["id"] == out["selection"]["id"] and named["label"] == "миска"


async def test_a_job_left_over_from_a_restart_does_not_queue_snaps(client, stubs, fresh_db, monkeypatch):
    import formwright.agent.runner as runner

    started: list[str] = []

    async def fake_start(user, project, body):
        started.append(project["id"])
        return "j_new"

    monkeypatch.setattr(runner, "start_design_job", fake_start)
    a = await _snap(client)
    user = await fresh_db.one("SELECT * FROM users")
    for jid, status in (("j_orphan", "running"), ("j_ask", "waiting")):
        await fresh_db.insert("jobs", {"id": jid, "project_id": "p_old", "user_id": user["id"], "kind": "design", "status": status, "created_at": dbmod.now()})
    # the waiting one is live (a question is open), the running one has no task behind it
    monkeypatch.setitem(runner._jobs, "j_ask", SimpleNamespace(job_id="j_ask", project_id="p_old", kind="design", cancelled=asyncio.Event()))
    r = await client.post(f"/api/snap/{a['project']['id']}/confirm", json={"text": "миниатюра"})
    assert r.json()["queued"] is False and started == [a["project"]["id"]]


async def test_snaps_stop_at_the_daily_cap(client, stubs, fresh_db):
    out = await _snap(client)
    user = await fresh_db.one("SELECT * FROM users")
    p = await fresh_db.one("SELECT * FROM projects WHERE id = ?", out["project"]["id"])
    asset = await fresh_db.one("SELECT * FROM assets WHERE id = ?", out["asset"]["id"])
    await quotas.settle(user["id"], quotas.TIERS["anon"][0], is_job=False)
    assert (await quotas.spent_today(user["id"]))[1] == 0  # calls outside jobs are not counted as jobs
    calls = len(stubs["segment"])
    with pytest.raises(quotas.QuotaExceeded) as e:
        await snap.snap(user, p, asset, 0.5, 0.5, "ru")
    assert e.value.code == "daily_limit"
    with pytest.raises(quotas.QuotaExceeded):
        await snap.reselect(user, p, asset, [{"x": 200, "y": 160, "positive": True}], None, None)
    assert len(stubs["segment"]) == calls  # SAM was not called


async def test_a_huge_photo_is_refused_cleanly(client, stubs, fresh_db, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10_000)  # the test photo now counts as a decompression bomb
    r = await client.post("/api/snap", files={"file": ("snap.jpg", io.BytesIO(_photo()), "image/jpeg")}, data={"lang": "en"})
    assert r.status_code == 400 and r.json()["detail"] == "photo is too large"
    assert not await fresh_db.all("SELECT id FROM projects")


async def test_face_blur_is_paid_from_the_daily_budget(fresh_db, monkeypatch):
    from formwright.vision import privacy

    blurred = []

    async def fake_blur(meter, img):
        blurred.append(img.shape)
        meter.usd += 0.004
        return img, 1

    monkeypatch.setattr(privacy, "blur_people", fake_blur)
    monkeypatch.setattr(settings(), "meta_api_key", "test-key")
    monkeypatch.setattr(settings(), "blur_faces", True)
    t = dbmod.now()
    await fresh_db.insert("users", {"id": "u_blur", "tier": "anon", "created_at": t})
    await fresh_db.insert("projects", {"id": "p_blur", "user_id": "u_blur", "title": "x", "created_at": t, "updated_at": t})
    a = await ingest.ingest_asset("p_blur", "photo", "a.jpg", _photo(), "image/jpeg")
    assert a["meta"]["faces_blurred"] == 1 and blurred
    assert await quotas.spent_today("u_blur") == (pytest.approx(0.004), 0)
    await quotas.settle("u_blur", 1.0, is_job=False)
    with pytest.raises(quotas.QuotaExceeded):
        await ingest.ingest_asset("p_blur", "photo", "b.jpg", _photo(), "image/jpeg")
    assert len(blurred) == 1
    monkeypatch.setattr(settings(), "blur_faces", False)  # FW_BLUR_FACES=0 in .env now takes effect
    await ingest.ingest_asset("p_blur", "photo", "c.jpg", _photo(), "image/jpeg")
    assert len(blurred) == 1


async def test_a_failed_transcription_is_reported(monkeypatch):
    async def broken(wav):
        raise RuntimeError("asr 502")

    monkeypatch.setattr(ingest, "transcribe", broken)
    assert await ingest._transcript(b"RIFF") == {"transcript": "", "transcript_error": "asr 502"}


async def test_a_queued_snap_survives_losing_a_start_race(client, stubs, fresh_db, monkeypatch):
    import formwright.agent.runner as runner

    started: list[str] = []

    async def fake_start(user, project, body):
        if not started:
            started.append("raced")
            raise quotas.QuotaExceeded("another job is still running", code="job_running", project_id="p_x", job_id="j_x")
        started.append(project["id"])
        return "j_new"

    monkeypatch.setattr(runner, "start_design_job", fake_start)
    b = await _snap(client)
    user = await fresh_db.one("SELECT * FROM users")
    await fresh_db.insert("jobs", {"id": "j_live", "project_id": "p_other", "user_id": user["id"], "kind": "design", "status": "running",
                                   "created_at": dbmod.now()})
    monkeypatch.setitem(runner._jobs, "j_live", SimpleNamespace(job_id="j_live", project_id="p_other", kind="design", cancelled=asyncio.Event()))
    r = await client.post(f"/api/snap/{b['project']['id']}/confirm", json={"text": "миниатюра"})
    assert r.json()["queued"] is True
    await fresh_db.execute("UPDATE jobs SET status = 'done' WHERE id = 'j_live'")
    for _ in range(60):
        if len(started) == 2:
            break
        await asyncio.sleep(0.2)
    assert started == ["raced", b["project"]["id"]]
    brief = (await fresh_db.one("SELECT brief FROM projects WHERE id = ?", b["project"]["id"]))["brief"]
    assert "queued" not in brief and "queue_error" not in brief
