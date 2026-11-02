"""Model calls outside jobs: they are paid from the person's daily budget without counting as jobs or waiting
for one (printer fingerprint, voice notes), a snap stopped by the limit leaves no draft, and video
understanding is counted under its own purpose. Every model is stubbed."""
from __future__ import annotations

import asyncio
import io
import wave
from types import SimpleNamespace

import cv2
import httpx
import numpy as np
import pytest

from formwright import db as dbmod, quotas, sessions
from formwright.config import settings
from formwright.llm.client import CostMeter
from formwright.vision import ingest, video


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")  # nobody listens: nothing reaches a model
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    db = await dbmod.get_db()
    t = dbmod.now()
    await db.insert("users", {"id": "u1", "tier": "anon", "created_at": t})
    await db.insert("projects", {"id": "p1", "user_id": "u1", "title": "Shelf", "created_at": t, "updated_at": t})
    yield db
    await dbmod.close_db()


@pytest.fixture
async def client(fresh_db):
    from formwright.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", cookies={sessions.COOKIE: await sessions.issue("u1")}) as c:
        yield c


def _photo() -> bytes:
    img = np.full((300, 400, 3), 200, np.uint8)
    cv2.rectangle(img, (120, 100), (280, 220), (40, 60, 90), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes((np.sin(np.linspace(0, 2 * np.pi * 440, 24000)) * 8000).astype(np.int16).tobytes())
    return buf.getvalue()


async def _spend_today(user_id: str = "u1") -> None:
    await quotas.settle(user_id, quotas.TIERS["anon"][0], is_job=False)


# ------------------------------------------------------------------ snap drafts
async def _no_draft_left(db) -> None:
    assert [p["id"] for p in await db.all("SELECT id FROM projects")] == ["p1"]
    assert not await db.all("SELECT id FROM assets")
    assert list((settings().data_dir / "files").iterdir()) == []


async def _snap(client) -> httpx.Response:
    return await client.post("/api/snap", files={"file": ("snap.jpg", io.BytesIO(_photo()), "image/jpeg")}, data={"lang": "en"})


async def test_a_snap_over_the_limit_leaves_no_draft(client, fresh_db):
    await _spend_today()
    r = await _snap(client)  # stopped by snap.snap's own check, after the photo was stored
    assert r.status_code == 429 and r.json()["code"] == "daily_limit"
    await _no_draft_left(fresh_db)


async def test_a_snap_whose_face_blur_hits_the_limit_leaves_no_draft(client, fresh_db, monkeypatch):
    from formwright.vision import privacy

    async def blur(meter, img):
        raise AssertionError("over the limit nothing may be called")

    monkeypatch.setattr(privacy, "blur_people", blur)
    monkeypatch.setattr(settings(), "meta_api_key", "test-key")
    monkeypatch.setattr(settings(), "blur_faces", True)
    await _spend_today()
    r = await _snap(client)
    assert r.status_code == 429 and r.json()["code"] == "daily_limit"
    await _no_draft_left(fresh_db)


# ------------------------------------------------------------------ printer fingerprint
async def test_measuring_a_coupon_does_not_wait_for_a_design_job(client, fresh_db, monkeypatch):
    from formwright.agent import runner
    from formwright.printing import fingerprint

    async def measure(meter, user, asset):
        meter.add("sam", 0.01, purpose="measure")
        return {"measured": {"rods": []}, "fingerprint": {"xy_scale": 1.0}}

    monkeypatch.setattr(fingerprint, "measure", measure)
    t = dbmod.now()
    await fresh_db.insert("assets", {"id": "a_coupon", "project_id": "p1", "kind": "photo", "path": "p1/a_coupon.jpg", "mime": "image/jpeg", "created_at": t})
    # a design job of the same person is running (anonymous plans run one at a time)
    await fresh_db.insert("jobs", {"id": "j_design", "project_id": "p1", "user_id": "u1", "kind": "design", "status": "running", "created_at": t})
    monkeypatch.setitem(runner._jobs, "j_design", SimpleNamespace(job_id="j_design", project_id="p1", kind="design", cancelled=asyncio.Event()))

    r = await client.post("/api/printers/bambu-a1/fingerprint", json={"asset_id": "a_coupon"})
    assert r.status_code == 200, r.text
    assert r.json()["fingerprint"] == {"xy_scale": 1.0}
    assert await quotas.spent_today("u1") == (pytest.approx(0.01), 0)  # paid for, not counted as a job
    await _spend_today()
    r = await client.post("/api/printers/bambu-a1/fingerprint", json={"asset_id": "a_coupon"})
    assert r.status_code == 429 and r.json()["code"] == "daily_limit"


# ------------------------------------------------------------------ voice notes
@pytest.fixture
def asr(monkeypatch):
    calls: list[list[str] | None] = []

    class FakeMeta:
        async def transcribe(self, meter, wav, *, keywords=None, languages=None, purpose="voice"):
            calls.append(languages)
            meter.add("muse-voice-transcribe-1.0", 0.002, purpose=purpose)
            return "shelf is 18 mm thick"

    monkeypatch.setattr(ingest, "meta", lambda: FakeMeta())
    monkeypatch.setattr(settings(), "meta_api_key", "test-key")
    return calls


async def test_a_voice_note_is_paid_by_the_projects_owner(fresh_db, asr):
    a = await ingest.ingest_asset("p1", "audio", "note.wav", _wav(), "audio/wav")
    assert a["kind"] == "audio" and a["meta"]["transcript"] == "shelf is 18 mm thick"
    assert await quotas.spent_today("u1") == (pytest.approx(0.002), 0)

    await _spend_today()
    a = await ingest.ingest_asset("p1", "audio", "late.wav", _wav(), "audio/wav")
    # over the limit the note is still kept, only without a transcript, and nothing was called
    assert a["meta"]["transcript"] == "" and "daily limit" in a["meta"]["transcript_error"]
    assert a["meta"]["transcript_code"] == "daily_limit"
    assert len(asr) == 1


async def test_a_voice_note_with_nobody_to_bill_is_still_transcribed(fresh_db, asr):
    assert await ingest._transcript(_wav()) == {"transcript": "shelf is 18 mm thick"}
    assert await quotas.spent_today("u1") == (0.0, 0)


# ------------------------------------------------------------------ video
async def test_video_understanding_is_counted_as_video(monkeypatch):
    seen: dict = {}

    class FakeMeta:
        async def respond(self, meter, **kw):
            seen.update(kw)
            return SimpleNamespace(output_text="a door hinge")

    monkeypatch.setattr(video, "meta", lambda: FakeMeta())
    monkeypatch.setattr(video, "_video_bytes", lambda asset: b"\0" * 16)
    assert await video.understand(CostMeter(budget_usd=0.1), {"kind": "video", "meta": {}}, "What is this part?") == "a door hinge"
    assert seen["purpose"] == "video"
