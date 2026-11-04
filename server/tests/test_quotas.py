"""Quotas count only jobs that really run: a row a restart left 'running' or a job waiting for an
answer never locks a user out, two starts cannot both pass the check, and every refusal says
which limit it hit."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from formwright import db as dbmod, quotas
from formwright.agent import runner
from formwright.config import settings
from formwright.models import SendMessage


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def _user(db, uid: str, tier: str = "anon", ip: str | None = "1.2.3.4") -> dict:
    await db.insert("users", {"id": uid, "tier": tier, "ip": ip, "created_at": dbmod.now()})
    return await db.one("SELECT * FROM users WHERE id = ?", uid)


async def _job(db, jid: str, uid: str, status: str = "running", kind: str = "design", project_id: str = "p_a") -> None:
    await db.insert("jobs", {"id": jid, "project_id": project_id, "user_id": uid, "kind": kind, "status": status, "created_at": dbmod.now()})


def test_quota_exceeded_takes_a_message_alone():
    e = quotas.QuotaExceeded("out of credits")  # as telegram and older callers raise it
    assert str(e) == "out of credits" and e.code == "quota" and e.info == {}
    e = quotas.QuotaExceeded("busy", code="job_running", project_id="p_1", job_id="j_1")
    assert e.code == "job_running" and e.info == {"project_id": "p_1", "job_id": "j_1"}


async def test_orphaned_and_waiting_jobs_do_not_block(fresh_db):
    user = await _user(fresh_db, "u_orphan")
    await _job(fresh_db, "j_orphan", "u_orphan")  # a restart killed its task
    await _job(fresh_db, "j_ask", "u_orphan", status="waiting", project_id="p_b")  # waits for an answer
    # neither blocks a start, and a job has no cap but what is left today
    assert await quotas.headroom(user, live={"j_ask"}) == pytest.approx(1.0)
    assert await quotas.headroom(user, live=set()) == pytest.approx(1.0)
    await quotas.settle("u_orphan", 0.3)
    assert await quotas.headroom(user, live=set()) == pytest.approx(0.7)


async def test_a_running_job_blocks_and_names_itself(fresh_db):
    user = await _user(fresh_db, "u_busy")
    await _job(fresh_db, "j_live", "u_busy", project_id="p_live")
    with pytest.raises(quotas.QuotaExceeded) as e:
        await quotas.headroom(user, live={"j_live"})
    assert e.value.code == "job_running" and e.value.info == {"project_id": "p_live", "job_id": "j_live"}
    # a slice may run next to it
    assert await quotas.headroom(user, live={"j_live"}, concurrency=False) == pytest.approx(1.0)
    # and a running slice does not hold a design job up
    await fresh_db.execute("UPDATE jobs SET kind = 'slice' WHERE id = 'j_live'")
    assert await quotas.headroom(user, live={"j_live"}) == pytest.approx(1.0)


async def test_limits_carry_codes(fresh_db, monkeypatch):
    monkeypatch.setattr(quotas, "ANON_PER_IP", 1.5)
    other = await _user(fresh_db, "u_ip1")
    user = await _user(fresh_db, "u_ip2")
    await quotas.settle(other["id"], 1.0)
    await quotas.settle(user["id"], 0.48)
    with pytest.raises(quotas.QuotaExceeded) as e:
        await quotas.headroom(user, live=set())
    # the address cap bites first; the message no longer quotes the $1.00 plan limit
    assert e.value.code == "ip_daily_cap" and "1.00" not in str(e.value)
    no_ip = await _user(fresh_db, "u_noip", ip=None)
    await quotas.settle(no_ip["id"], 0.995)
    with pytest.raises(quotas.QuotaExceeded) as e:
        await quotas.check_light(no_ip)
    assert e.value.code == "daily_limit" and e.value.info == {"limit_usd": 1.0}
    monkeypatch.setattr(settings(), "daily_budget_usd", 1.0)
    with pytest.raises(quotas.QuotaExceeded) as e:
        await quotas.check_light(await _user(fresh_db, "u_fresh", ip="5.6.7.8"))
    assert e.value.code == "demo_budget"


async def test_calls_outside_jobs_are_not_counted_as_jobs(fresh_db):
    await quotas.settle("u_n", 0.01, is_job=False)
    await quotas.settle("u_n", 0.0, is_job=False)
    await quotas.settle("u_n", 0.2)
    usd, jobs = await quotas.spent_today("u_n")
    assert usd == pytest.approx(0.21) and jobs == 1


async def test_two_starts_at_once_run_one_job(fresh_db):
    user = await _user(fresh_db, "u_race")
    a = {"id": "p_race_a", "user_id": "u_race"}
    b = {"id": "p_race_b", "user_id": "u_race"}
    out = await asyncio.gather(runner._create(user, a, "design", {"text": "x"}), runner._create(user, b, "design", {"text": "y"}),
                               return_exceptions=True)
    ok = [o for o in out if isinstance(o, runner.JobContext)]
    refused = [o for o in out if isinstance(o, quotas.QuotaExceeded)]
    try:
        assert len(ok) == 1 and len(refused) == 1 and refused[0].code == "job_running"
        assert refused[0].info["job_id"] == ok[0].job_id
        rows = await fresh_db.all("SELECT * FROM jobs WHERE user_id = 'u_race'")
        assert len(rows) == 1 and rows[0]["status"] == "running"
    finally:
        for o in ok:
            runner._jobs.pop(o.job_id, None)


async def test_one_agent_per_project(fresh_db):
    user = await _user(fresh_db, "u_pro", tier="pro")
    p = {"id": "p_busy", "user_id": "u_pro"}
    first = await runner._create(user, p, "design", {"text": "x"})
    try:
        with pytest.raises(quotas.QuotaExceeded) as e:
            await runner._create(user, p, "design", {"text": "again"})
        assert e.value.code == "project_busy" and e.value.info == {"project_id": "p_busy", "job_id": first.job_id}
        # a slice of the same project is fine
        side = await runner._create(user, p, "slice", {}, concurrency=False)
        runner._jobs.pop(side.job_id, None)
    finally:
        runner._jobs.pop(first.job_id, None)


async def test_every_plan_picks_every_designer(fresh_db, monkeypatch):
    s = settings()
    monkeypatch.setattr(s, "model_designer_hard", "muse-wonder-1.0")
    monkeypatch.setattr(s, "model_designer", "muse-spark-1.3")
    monkeypatch.setattr(s, "model_fast", "muse-spark-1.3")
    monkeypatch.setattr(s, "open_base_url", "http://127.0.0.1:9/open/v1")
    monkeypatch.setattr(s, "open_model", "meta-models/muse-spark-open-1026")
    anon = await _user(fresh_db, "u_judge")
    opts = {o["key"]: o for o in quotas.model_options(anon)}
    assert set(opts) == {"contributor", "spark", "wonder", "spark_open"} and all(o["available"] for o in opts.values())
    assert opts["spark_open"]["id"] == "meta-models/muse-spark-open-1026"
    assert (await quotas.choose_models(anon, model="wonder")).designer == "muse-wonder-1.0"
    picked = await quotas.choose_models(anon, model="spark_open")
    # the open model designs; the quick side calls (translation, search) stay on Spark
    assert picked.designer == "meta-models/muse-spark-open-1026" and picked.fast == "muse-spark-1.3" and not picked.contributor
    # without an open endpoint it is not offered, and an old client that still sends it gets Spark
    monkeypatch.setattr(s, "open_base_url", "")
    assert "spark_open" not in {o["key"] for o in quotas.model_options(anon)}
    assert (await quotas.choose_models(anon, model="spark_open")).designer == "muse-spark-1.3"
    assert SendMessage(text="x", model="spark_open").model == "spark_open"


async def test_a_job_has_no_cap_but_what_is_left_today(fresh_db, monkeypatch):
    from formwright.agent import loop

    s = settings()
    monkeypatch.setattr(s, "daily_budget_usd", 4.0)
    gate = asyncio.Event()

    async def fake_design(ctx, body):
        await gate.wait()
        return "ok"

    monkeypatch.setattr(loop, "design", fake_design)
    user = await _user(fresh_db, "u_budget", tier="admin")
    # whatever model or reasoning the run picks, its cap is the global budget left, and a running job holds none back
    jobs = [await runner.start_design_job(user, {"id": "p_w1", "user_id": "u_budget"}, SendMessage(text="x", model="wonder", reasoning="max")),
            await runner.start_design_job(user, {"id": "p_w2", "user_id": "u_budget"}, SendMessage(text="x", model="spark", reasoning="minimal"))]
    caps = [runner._jobs[j].meter.budget_usd for j in jobs]
    gate.set()
    await asyncio.gather(*[t for j in jobs if (t := runner._tasks.get(j))])
    assert caps == [pytest.approx(4.0), pytest.approx(4.0)]
    await quotas.settle("u_budget", 1.5)
    job = await runner._create(user, {"id": "p_w3", "user_id": "u_budget"}, "design", {"text": "x"})
    try:
        assert job.meter.budget_usd == pytest.approx(2.5)
    finally:
        runner._jobs.pop(job.job_id, None)


async def test_live_jobs_skip_stopped_ones():
    ev = asyncio.Event()
    ev.set()
    runner._jobs["j_stopping"] = SimpleNamespace(cancelled=ev)  # type: ignore[assignment]
    runner._jobs["j_going"] = SimpleNamespace(cancelled=asyncio.Event())  # type: ignore[assignment]
    try:
        assert {"j_going"} <= runner.live_jobs() and "j_stopping" not in runner.live_jobs()
    finally:
        runner._jobs.pop("j_stopping", None)
        runner._jobs.pop("j_going", None)
