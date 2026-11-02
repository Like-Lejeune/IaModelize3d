"""The home page's featured runs in the other UI language: a run opened from a ready example carries that example's
title (open_example names the project in the visitor's language), so /api/featured sends the example's own titles in
both languages; any other run keeps only its own title."""
from __future__ import annotations

import httpx
import pytest

from formwright import db as dbmod, sessions, showcase
from formwright.app import app
from formwright.config import settings


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    db = await dbmod.get_db()
    await db.insert("users", {"id": "u1", "tier": "anon", "ip": "10.0.0.1", "created_at": dbmod.now()})
    yield db
    await dbmod.close_db()


@pytest.fixture
async def client(fresh_db, monkeypatch):
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings(), "open_base_url", "")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={sessions.COOKIE: await sessions.issue("u1")}) as c:
        yield c


async def _run(db, pid: str, title: str, featured: int) -> None:
    t = dbmod.now()
    await db.insert("projects", {"id": pid, "user_id": "u1", "title": title, "pack": "enclosure", "public": 1, "featured": featured,
                                 "version": 2, "brief": {"summary": "Snap-fit case updated"}, "created_at": t, "updated_at": t})
    await db.insert("jobs", {"id": f"j_{pid}", "project_id": pid, "user_id": "u1", "kind": "design", "status": "done", "created_at": t,
                             "finished_at": t + 32, "result": {"cost": {"by_model": {"muse-spark-1.3": 0.01}, "calls_by_model": {"muse-spark-1.3": 3}}}})


async def test_an_example_run_carries_the_example_titles_and_others_keep_their_own(client, fresh_db):
    pico = showcase.BY_KEY["pico-w-case"]["title"]
    wheel = showcase.BY_KEY["rack-wheel"]["title"]
    await _run(fresh_db, "p_en", pico["en"], 4)  # opened from the example in the English UI, then edited by the agent
    await _run(fresh_db, "p_ru", pico["ru"], 3)  # the same example opened in Russian
    await _run(fresh_db, "p_typed", "Dishwasher Rack Wheel", 2)  # a typed request the agent named with the example's words
    await _run(fresh_db, "p_own", "Pico W case for my weather station", 1)  # renamed or typed: its own words only
    items = {i["id"]: i for i in (await client.get("/api/featured")).json()}
    assert list(items) == ["p_en", "p_ru", "p_typed", "p_own"]
    for pid in ("p_en", "p_ru"):
        assert (items[pid]["title_en"], items[pid]["title_ru"]) == (pico["en"], pico["ru"])
    assert items["p_en"]["title"] == pico["en"] and items["p_ru"]["title"] == pico["ru"], "the run's own title is unchanged"
    assert (items["p_typed"]["title_en"], items["p_typed"]["title_ru"]) == (wheel["en"], wheel["ru"])
    assert "title_en" not in items["p_own"] and "title_ru" not in items["p_own"] and items["p_own"]["title"] == "Pico W case for my weather station"


async def test_a_run_born_from_a_shop_order_reads_in_both_languages(client, fresh_db):
    """A Russian order's design run, featured: the English home page gets the intake's English catalog title, the
    Russian one the run's own title (wave-6 video dry run)."""
    from formwright.shop import store

    await _run(fresh_db, "p_order", "Колесо для нижней корзины посудомойки · Bosch", 1)
    sdb = await store.shop_db()
    t = dbmod.now()
    intake = {"request": {"kind": "photo"}, "refuse": False, "language": "ru",
              "classify": {"title_en": "Dishwasher lower basket wheel", "title_ru": "Колёсико нижней корзины посудомойки", "safety_critical": False}}
    await sdb.insert("shop_orders", {"id": "so_1", "ref": "FW-1002", "user_id": "u1", "project_id": "p_order", "status": "delivered",
                                     "intake": intake, "created_at": t, "updated_at": t})
    item = (await client.get("/api/featured")).json()[0]
    assert (item["title_en"], item["title_ru"]) == ("Dishwasher lower basket wheel", "Колесо для нижней корзины посудомойки · Bosch")
    # the two models disagreed about the part: no catalog title to trust
    await sdb.update("shop_orders", "id", "so_1", {"intake": {**intake, "review": {"code": "safety_disagreement"}}})
    assert "title_en" not in (await client.get("/api/featured")).json()[0]
