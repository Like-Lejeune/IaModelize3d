"""What a visitor's uploads and messages may carry onto a page others read (wave-6 security review): a phone video's
location tags, a refused upload's bytes left on disk, a day's uploads, and the words a studio message shows."""
from __future__ import annotations

import subprocess

import httpx
import pytest

from iamodelize3d import db as dbmod, quotas, sessions
from iamodelize3d.app import app
from iamodelize3d.config import settings
from iamodelize3d.vision import ingest
from iamodelize3d.vision.common import abs_path


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings(), "open_base_url", "")
    monkeypatch.setattr(settings(), "blur_faces", False)
    (tmp_path / "files").mkdir(exist_ok=True)
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def _project(db, pid: str, uid: str, tier: str = "anon", ip: str | None = None) -> None:
    t = dbmod.now()
    if not await db.one("SELECT 1 FROM users WHERE id = ?", uid):
        await db.insert("users", {"id": uid, "tier": tier, "ip": ip, "created_at": t})
    await db.insert("projects", {"id": pid, "user_id": uid, "title": pid, "created_at": t, "updated_at": t})


def _phone_video(path) -> bytes:
    """One second of video with what a phone writes into it: where, with what, when."""
    ff = ingest.ffmpeg_bin()
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10", "-c:v", "mpeg4",
                    "-metadata", "location=+43.2389+076.8897/", "-metadata", "model=iPhone 15 Pro", "-metadata", "make=Apple",
                    "-metadata", "creation_time=2026-10-29T10:00:00Z", str(path)], check=True, capture_output=True, timeout=60)
    return path.read_bytes()


async def test_a_stored_video_keeps_no_location_or_camera_tags(fresh_db, tmp_path):
    if not ingest.ffmpeg_bin():
        pytest.skip("ffmpeg not installed")
    await _project(fresh_db, "p_v", "u_a")
    data = _phone_video(tmp_path / "IMG_0042.MOV")
    assert b"+43.2389+076.8897" in data and b"iPhone 15 Pro" in data
    v = await ingest.ingest_asset("p_v", "video", "IMG_0042.MOV", data, "video/quicktime")
    stored = abs_path(v["path"]).read_bytes()
    assert v["kind"] == "video" and v["meta"]["frames"] == 10 and v["path"].endswith(".mov")
    for tag in (b"+43.2389+076.8897", b"iPhone 15 Pro", b"Apple", b"2026-10-29"):
        assert tag not in stored, tag


async def test_a_refused_video_leaves_nothing_on_disk(fresh_db):
    if not ingest.ffmpeg_bin():
        pytest.skip("ffmpeg not installed")
    await _project(fresh_db, "p_e", "u_e")
    for _ in range(3):
        with pytest.raises(ValueError):
            await ingest.ingest_asset("p_e", "video", "clip.mp4", b"\x00garbage" * 4096, "video/mp4")
    folder = settings().data_dir / "files" / "p_e"
    assert not folder.exists() or not any(folder.iterdir())


async def test_a_days_uploads_are_capped_per_person_and_per_network(fresh_db, monkeypatch):
    import cv2
    import numpy as np

    photo = cv2.imencode(".png", np.full((64, 64, 3), 200, np.uint8))[1].tobytes()
    monkeypatch.setattr(ingest, "UPLOAD_MB_DAY", {"anon": len(photo) * 2.5 / 1e6})
    monkeypatch.setattr(ingest, "UPLOAD_MB_NETWORK", len(photo) * 3.5 / 1e6)
    await _project(fresh_db, "p_1", "u_1", ip="203.0.113.7")
    for _ in range(2):
        await ingest.ingest_asset("p_1", "photo", "a.png", photo, "image/png")
    with pytest.raises(quotas.QuotaExceeded) as e:
        await ingest.ingest_asset("p_1", "photo", "a.png", photo, "image/png")
    assert e.value.code == "upload_quota"
    # a fresh cookie on the same network: its share is what is left of the network's
    await _project(fresh_db, "p_2", "u_2", ip="203.0.113.7")
    await ingest.ingest_asset("p_2", "photo", "a.png", photo, "image/png")
    with pytest.raises(quotas.QuotaExceeded):
        await ingest.ingest_asset("p_2", "photo", "a.png", photo, "image/png")
    await _project(fresh_db, "p_3", "u_3", tier="free", ip="203.0.113.7")  # signed in: their own, larger allowance
    for _ in range(3):
        await ingest.ingest_asset("p_3", "photo", "a.png", photo, "image/png")
    # through the API it is a 429 with its code
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 cookies={sessions.COOKIE: await sessions.issue("u_1")}) as c:
        r = await c.post("/api/projects/p_1/assets", files={"file": ("a.png", photo, "image/png")}, data={"kind": "photo"})
    assert r.status_code == 429 and r.json()["code"] == "upload_quota"


async def test_a_studio_message_shows_the_words_that_were_sent(fresh_db, monkeypatch):
    """SendMessage.shown is for the server's own callers (a shop order's English brief): a browser cannot make its
    project show words the model never read."""
    from iamodelize3d.agent import runner

    await _project(fresh_db, "p_s", "u_s")
    seen = []

    async def start(user, project, body):
        seen.append(body)
        return "j_1"

    monkeypatch.setattr(runner, "start_design_job", start)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 cookies={sessions.COOKIE: await sessions.issue("u_s")}) as c:
        r = await c.post("/api/projects/p_s/messages", json={"text": "make a hook", "shown": "a kind word about the founder"})
    assert r.status_code == 200 and seen[0].text == "make a hook" and seen[0].shown is None
