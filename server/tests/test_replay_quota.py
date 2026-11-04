"""Replays copy the event log progressively; anonymous spend is capped per address."""
import asyncio

import pytest

from formwright import db as dbmod, events, quotas
from formwright.app import _replay
from formwright.config import settings


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def test_replay_copies_events_and_versions(fresh_db):
    db = fresh_db
    t = dbmod.now()
    for pid in ("p_src", "p_dst"):
        await db.insert("projects", {"id": pid, "user_id": "u1", "title": "x", "created_at": t, "updated_at": t})
    await db.insert("programs", {"project_id": "p_src", "version": 1, "source": "return {build:()=>null}", "created_at": t})
    await events.emit("p_src", "job.started", {"job_id": "j1"}, "j1")
    await events.emit("p_src", "program.updated", {"version": 1}, "j1")
    await events.emit("p_src", "job.finished", {"status": "done"}, "j1")
    await db.insert("messages", {"id": "m1", "project_id": "p_src", "role": "agent", "text": "hi", "created_at": t})
    await asyncio.wait_for(_replay("p_src", "p_dst", 20), 10)
    types = [e["type"] for e in await events.since("p_dst", 0)]
    assert types == ["job.started", "program.updated", "job.finished"]
    assert await db.one("SELECT * FROM programs WHERE project_id = 'p_dst' AND version = 1")
    assert (await db.one("SELECT text FROM messages WHERE project_id = 'p_dst'"))["text"] == "hi"


async def test_anonymous_spend_is_capped_per_ip(fresh_db, monkeypatch):
    db = fresh_db
    t = dbmod.now()
    monkeypatch.setattr(quotas, "ANON_PER_IP", 0.5)
    for i in range(3):
        await db.insert("users", {"id": f"u{i}", "tier": "anon", "ip": "1.2.3.4", "created_at": t})
    await quotas.settle("u0", 0.3)
    await quotas.settle("u1", 0.18)
    user = await db.one("SELECT * FROM users WHERE id = 'u2'")
    with pytest.raises(quotas.QuotaExceeded) as e:
        await quotas.headroom(user)
    assert e.value.code == "ip_daily_cap"


async def test_a_replay_copy_keeps_the_question_above_the_answer(fresh_db):
    # the chat is copied at the end of the replay: its times go on the replay's clock, not the moment it is copied
    db = fresh_db
    t = dbmod.now()
    for pid in ("p_src", "p_dst"):
        await db.insert("projects", {"id": pid, "user_id": "u1", "title": "x", "created_at": t, "updated_at": t})
    await db.insert("messages", {"id": "m_q", "project_id": "p_src", "role": "user", "text": "a hook", "created_at": t - 1})
    await events.emit("p_src", "user.message", {"text": "a hook"})
    await events.emit("p_src", "job.started", {"job_id": "j1"}, "j1")
    await events.emit("p_src", "job.finished", {"status": "done"}, "j1")
    await db.insert("messages", {"id": "m_a", "project_id": "p_src", "role": "agent", "text": "done", "created_at": dbmod.now() + 0.01})
    await asyncio.wait_for(_replay("p_src", "p_dst", 20), 10)
    ev = {e["type"]: e["ts"] for e in await events.since("p_dst", 0)}
    msgs = {m["role"]: m["created_at"] for m in await db.all("SELECT * FROM messages WHERE project_id = 'p_dst'")}
    assert msgs["user"] < ev["job.started"] <= ev["job.finished"] <= msgs["agent"]
