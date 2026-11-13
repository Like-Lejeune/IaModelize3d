"""How a job's end reads: a crash shows people a calm line with an error id (the exception and paths go to the
log only), and Stop on a job that is already over answers 404, so the client drops its stale job id."""
from __future__ import annotations

import asyncio
import re

import httpx
import pytest

from iamodelize3d import db as dbmod, events, sessions
from iamodelize3d.agent import narrate, runner
from iamodelize3d.config import settings
from iamodelize3d.geom import GeomError


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def _start(db, uid: str, pid: str, work, text: str = "a bracket", brief: dict | None = None) -> runner.JobContext:
    if not await db.one("SELECT id FROM users WHERE id = ?", uid):
        await db.insert("users", {"id": uid, "tier": "anon", "created_at": dbmod.now()})
    t = dbmod.now()
    await db.insert("projects", {"id": pid, "user_id": uid, "title": "x", "brief": brief or {}, "created_at": t, "updated_at": t})
    user = await db.one("SELECT * FROM users WHERE id = ?", uid)
    ctx = await runner._create(user, {"id": pid, "user_id": uid}, "design", {"text": text})
    runner._spawn(ctx, work)
    return ctx


async def _finished(pid: str) -> dict:
    [e] = [e for e in await events.since(pid, 0) if e["type"] == "job.finished"]
    return e["data"]


@pytest.mark.parametrize("error, line", [
    (RuntimeError, runner.CRASHED[0]),
    (lambda m: httpx.ConnectError(m), narrate.HANDOVER["failed"][0]),
    (lambda m: GeomError("crash", m), narrate.HANDOVER["engine"][0]),
])
async def test_a_crash_shows_a_calm_line_and_logs_the_error(fresh_db, caplog, error, line):
    where = settings().data_dir / "files" / "p_crash" / "a_1.mp4"

    async def crashes(ctx):
        raise error(f"cannot decode {where}")

    ctx = await _start(fresh_db, "u_crash", "p_crash", crashes)
    await asyncio.wait_for(ctx.finished.wait(), 10)
    d = await _finished("p_crash")
    assert d["status"] == "failed"
    summary = d["summary"]
    assert summary.startswith(line)
    assert "cannot decode" not in summary and "a_1.mp4" not in summary and "Error:" not in summary
    eid = re.search(r"Error id: (e_[0-9a-f]{16})\.$", summary).group(1)
    row = await fresh_db.one("SELECT status, result FROM jobs WHERE id = ?", ctx.job_id)
    assert row["status"] == "failed" and row["result"]["summary"] == summary
    # the full error, path included, is in the log under the same id
    logged = [r.getMessage() for r in caplog.records if r.name == runner.log.name and eid in r.getMessage()]
    assert logged and "cannot decode" in logged[0] and "a_1.mp4" in logged[0]


@pytest.mark.parametrize("text, brief", [("кронштейн для полки", None), ("a bracket", {"language": "ru"})])
async def test_a_crash_speaks_the_persons_language(fresh_db, text, brief):
    async def crashes(ctx):
        raise KeyError("version")

    ctx = await _start(fresh_db, "u_ru", "p_ru", crashes, text=text, brief=brief)
    await asyncio.wait_for(ctx.finished.wait(), 10)
    summary = (await _finished("p_ru"))["summary"]
    assert summary.startswith(runner.CRASHED[1]) and "Код ошибки: e_" in summary and "KeyError" not in summary


@pytest.fixture
async def client(fresh_db):
    from iamodelize3d.app import app

    await fresh_db.insert("users", {"id": "u1", "tier": "anon", "created_at": dbmod.now()})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", cookies={sessions.COOKIE: await sessions.issue("u1")}) as c:
        yield c


async def _sleepy(ctx):
    await asyncio.sleep(30)


async def test_stop_on_a_job_that_is_over_is_a_404(client, fresh_db):
    ctx = await _start(fresh_db, "u1", "p_stop", _sleepy)
    r = await client.post(f"/api/jobs/{ctx.job_id}/cancel")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert (await fresh_db.one("SELECT status FROM jobs WHERE id = ?", ctx.job_id))["status"] == "cancelled"
    # pressed again (a stale tab), an unknown id, or someone else's job: nothing to stop
    for jid in (ctx.job_id, "j_nope"):
        r = await client.post(f"/api/jobs/{jid}/cancel")
        assert r.status_code == 404 and r.json()["code"] == "not_found" and r.json()["detail"]
    other = await _start(fresh_db, "u_other", "p_other", _sleepy)
    try:
        r = await client.post(f"/api/jobs/{other.job_id}/cancel")
        assert r.status_code == 404 and r.json()["code"] == "not_found"
        assert not other.cancelled.is_set()
    finally:
        await runner.cancel_job(other.job_id, "u_other")
