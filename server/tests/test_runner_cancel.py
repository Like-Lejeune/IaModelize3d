"""Stop always ends a job: a second Stop cannot cut its bookkeeping short, a row a restart left
behind is closed, and a job past its deadline is stopped (questions do not count against it)."""
from __future__ import annotations

import asyncio

import pytest

from formwright import db as dbmod, events
from formwright.agent import runner
from formwright.config import settings


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def _start(db, uid: str, pid: str, work, kind: str = "design") -> runner.JobContext:
    await db.insert("users", {"id": uid, "tier": "anon", "created_at": dbmod.now()})
    t = dbmod.now()
    await db.insert("projects", {"id": pid, "user_id": uid, "title": "x", "created_at": t, "updated_at": t})
    user = await db.one("SELECT * FROM users WHERE id = ?", uid)
    ctx = await runner._create(user, {"id": pid, "user_id": uid}, kind, {"text": "a bracket"})
    runner._spawn(ctx, work)
    return ctx


async def _finished(pid: str) -> list[dict]:
    return [e for e in await events.since(pid, 0) if e["type"] == "job.finished"]


async def _sleepy(ctx):
    await asyncio.sleep(30)


@pytest.mark.parametrize("ticks", [1, 3, 8, 20, 40])
async def test_second_stop_does_not_break_the_first(fresh_db, ticks):
    ctx = await _start(fresh_db, f"u_stop{ticks}", f"p_stop{ticks}", _sleepy)
    task = runner._tasks[ctx.job_id]
    await asyncio.sleep(0)
    first = asyncio.create_task(runner.cancel_job(ctx.job_id, ctx.user["id"]))
    for _ in range(ticks):
        await asyncio.sleep(0)
    second = await runner.cancel_job(ctx.job_id, ctx.user["id"])
    task.cancel()  # anything else cancelling the task meanwhile (a shutdown, the hard stop)
    assert await first is True and second in (True, False)
    await asyncio.wait({task}, timeout=5)
    row = await fresh_db.one("SELECT status, result FROM jobs WHERE id = ?", ctx.job_id)
    assert row["status"] == "cancelled" and row["result"]["summary"] == "stopped"
    assert len(await _finished(ctx.project_id)) == 1
    assert ctx.job_id not in runner._jobs and ctx.job_id not in runner._tasks
    assert (await fresh_db.one("SELECT status FROM projects WHERE id = ?", ctx.project_id))["status"] == "idle"
    brief = (await fresh_db.one("SELECT brief FROM projects WHERE id = ?", ctx.project_id))["brief"]
    assert brief["turns"] == ["a bracket (interrupted: cancelled)"]


async def test_stop_returns_once_the_job_has_ended(fresh_db):
    ctx = await _start(fresh_db, "u_sync", "p_sync", _sleepy)
    assert await runner.cancel_job(ctx.job_id, ctx.user["id"]) is True
    assert (await fresh_db.one("SELECT status FROM jobs WHERE id = ?", ctx.job_id))["status"] == "cancelled"
    assert await runner.cancel_job(ctx.job_id, "u_someone_else") is False


async def test_stop_after_a_restart(fresh_db):
    db = fresh_db
    t = dbmod.now()
    await db.insert("projects", {"id": "p_orphan", "user_id": "u_orphan", "title": "x", "status": "working", "created_at": t, "updated_at": t})
    await db.insert("jobs", {"id": "j_orphan", "project_id": "p_orphan", "user_id": "u_orphan", "kind": "design", "status": "waiting",
                             "input": {"text": "a hook"}, "created_at": t})
    assert await runner.cancel_job("j_orphan", "u_other") is False
    assert await runner.cancel_job("j_orphan", "u_orphan") is True
    row = await db.one("SELECT status, finished_at, result FROM jobs WHERE id = 'j_orphan'")
    assert row["status"] == "cancelled" and row["finished_at"] and row["result"]["cost"]["usd"] == 0
    assert (await db.one("SELECT status, brief FROM projects WHERE id = 'p_orphan'"))["status"] == "idle"
    finished = await _finished("p_orphan")
    assert len(finished) == 1 and finished[0]["data"]["status"] == "cancelled"
    assert await runner.cancel_job("j_orphan", "u_orphan") is False  # already closed


async def test_a_job_past_its_deadline_is_stopped(fresh_db, monkeypatch):
    monkeypatch.setattr(settings(), "side_deadline_s", 1.0)
    monkeypatch.setattr(runner, "HARD_STOP_S", 0.0)
    ctx = await _start(fresh_db, "u_slow", "p_slow", _sleepy, kind="concepts")
    assert ctx.deadline - ctx.started == pytest.approx(1.0)
    await asyncio.wait_for(runner._tasks[ctx.job_id], 10)
    row = await fresh_db.one("SELECT status, result FROM jobs WHERE id = ?", ctx.job_id)
    assert row["status"] == "failed" and row["result"]["summary"] == runner.TOO_LONG
    finished = await _finished(ctx.project_id)
    assert len(finished) == 1 and finished[0]["data"]["status"] == "failed"
    assert ctx.job_id not in runner._jobs


async def test_waiting_for_an_answer_does_not_count(fresh_db, monkeypatch):
    monkeypatch.setattr(settings(), "side_deadline_s", 0.2)
    monkeypatch.setattr(runner, "HARD_STOP_S", 0.1)

    async def asks(ctx):
        answer = await ctx.ask("Which side faces the wall?", ["left", "right"], timeout=0.5)
        await asyncio.sleep(0.1)  # still inside the moved deadline
        return f"answer: {answer}"

    ctx = await _start(fresh_db, "u_ask", "p_ask", asks, kind="concepts")
    await asyncio.wait_for(runner._tasks[ctx.job_id], 10)
    row = await fresh_db.one("SELECT status, result FROM jobs WHERE id = ?", ctx.job_id)
    assert row["status"] == "done" and row["result"]["summary"] == "answer: None"
    assert ctx.deadline - ctx.started == pytest.approx(0.7, abs=0.15)


async def test_questions_wait_for_the_configured_time(fresh_db, monkeypatch):
    monkeypatch.setattr(settings(), "ask_timeout_s", 0.05)

    async def asks(ctx):
        return await ctx.ask("Metric or imperial?") or "no answer"

    ctx = await _start(fresh_db, "u_ask2", "p_ask2", asks, kind="concepts")
    await asyncio.wait_for(runner._tasks[ctx.job_id], 5)
    assert (await fresh_db.one("SELECT result FROM jobs WHERE id = ?", ctx.job_id))["result"]["summary"] == "no answer"


async def test_work_may_end_with_its_own_status(fresh_db):
    async def handover(ctx):
        ctx.final_status = "budget"
        return "Stopped at the spending cap; v2 is the latest"

    ctx = await _start(fresh_db, "u_hand", "p_hand", handover)
    await asyncio.wait_for(runner._tasks[ctx.job_id], 5)
    row = await fresh_db.one("SELECT status, result FROM jobs WHERE id = ?", ctx.job_id)
    assert row["status"] == "budget" and row["result"]["summary"].startswith("Stopped at the spending cap")
    finished = await _finished(ctx.project_id)
    assert [e["data"]["status"] for e in finished] == ["budget"]
