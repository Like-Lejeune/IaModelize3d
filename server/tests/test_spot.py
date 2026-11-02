"""The studio's object search (spot) and the agent share work: one calibration per photo, and
the agent waits for a cut-out still in progress instead of making its own. Spots stop at the daily cap."""
from __future__ import annotations

import asyncio

import pytest

from formwright import db as dbmod, quotas
from formwright.config import settings
from formwright.vision import scene, spot


async def test_one_automatic_calibration_for_concurrent_callers(monkeypatch):
    calls = []

    async def slow(meter, asset, reference=None, *, mask=None, box=None):
        calls.append(asset["id"])
        await asyncio.sleep(0.05)
        return {"ok": True, "reference": "A4"}

    monkeypatch.setattr(scene, "_calibrate", slow)
    a = {"id": "a_1", "kind": "photo", "meta": {}}
    first, second = await asyncio.gather(scene.calibrate(None, a), scene.calibrate(None, dict(a)))
    assert calls == ["a_1"] and first == second == {"ok": True, "reference": "A4"}
    assert first is not second  # each caller gets its own copy
    await scene.calibrate(None, a)  # a later call searches again
    await scene.calibrate(None, a, "A4")  # a named reference is never shared
    assert calls == ["a_1", "a_1", "a_1"]


async def test_agent_waits_for_spot_in_progress(monkeypatch):
    done = asyncio.Event()

    async def slow(user, project_id, asset, hint, lang):
        await asyncio.sleep(0.05)
        done.set()
        return {"selection": None, "label": None, "objects": []}

    monkeypatch.setattr(spot, "spot", slow)
    task = spot.start({}, "p_1", {"id": "a_2"}, None, "en")
    await spot.settled(["a_2", "a_other"])
    assert done.is_set() and task.done()
    await asyncio.sleep(0)
    assert "a_2" not in spot._running
    await spot.settled(["a_2"])  # nothing running: returns at once


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def test_spot_stops_at_the_daily_cap(fresh_db, monkeypatch):
    called = []

    async def no_model(*args, **kwargs):
        called.append(args)
        return {}

    monkeypatch.setattr(spot, "_find", no_model)
    monkeypatch.setattr(spot, "segment", no_model)
    await fresh_db.insert("users", {"id": "u1", "tier": "anon", "ip": "1.2.3.4", "created_at": dbmod.now()})
    user = await fresh_db.one("SELECT * FROM users WHERE id = 'u1'")
    asset = {"id": "a_1", "kind": "photo", "path": "p_1/a_1.jpg", "meta": {}}
    await quotas.settle("u1", 0.995, is_job=False)
    with pytest.raises(quotas.QuotaExceeded) as e:
        await spot.spot(user, "p_1", asset, None, "en")
    assert e.value.code == "daily_limit" and not called
    # the same address spent its share through other anonymous sessions
    await fresh_db.insert("users", {"id": "u2", "tier": "anon", "ip": "1.2.3.4", "created_at": dbmod.now()})
    monkeypatch.setattr(quotas, "ANON_PER_IP", 1.5)
    await quotas.settle("u2", 0.6, is_job=False)
    with pytest.raises(quotas.QuotaExceeded) as e:
        await spot.spot(await fresh_db.one("SELECT * FROM users WHERE id = 'u2'"), "p_1", asset, None, "en")
    assert e.value.code == "ip_daily_cap" and not called
