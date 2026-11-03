"""The feature-router registry in app.py (contract C11): every router sits before the SPA catch-all, a missing or
broken feature module is logged and skipped, and a feature's own error code reaches the client at the top level."""
from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import FastAPI

from formwright import app as appmod, db as dbmod, sessions
from formwright.app import ROUTERS, app, include_routers
from formwright.config import settings


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings(), "open_base_url", "")
    await dbmod.close_db()
    db = await dbmod.get_db()
    await db.insert("users", {"id": "u1", "tier": "anon", "created_at": dbmod.now()})
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={sessions.COOKIE: await sessions.issue("u1")}) as c:
        yield c
    await dbmod.close_db()


def _paths(route) -> list[str]:
    """A route's paths; an included router (newer FastAPI keeps it as one entry) gives all of its own."""
    inner = getattr(route, "original_router", None)
    if inner is not None:
        return [p for r in inner.routes for p in _paths(r)]
    return [route.path] if getattr(route, "path", None) else []


def test_registry_names_the_three_feature_routers():
    assert ROUTERS == ("formwright.shop.routes", "formwright.pcbapi", "formwright.deviceapi", "formwright.collect")


def test_feature_routes_come_before_the_catch_all():
    import importlib

    order = [(i, p) for i, r in enumerate(app.routes) for p in _paths(r)]
    catch_all = [i for i, p in order if p == "/{path:path}"]
    shop = [i for i, p in order if p.startswith("/api/shop/")]
    assert shop, "the shop router is not mounted"
    for name in ROUTERS:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError:
            continue  # a feature that has not landed yet: test_missing_feature_is_skipped covers it
        mine = {r.path for r in module.router.routes}
        at = [i for i, p in order if p in mine]
        assert at, f"{name} is importable but not mounted"
        if catch_all:
            assert max(at) < min(catch_all), f"{name} is mounted after the SPA catch-all"


def test_missing_feature_is_skipped(caplog, tmp_path, monkeypatch):
    (tmp_path / "fw_broken_feature.py").write_text("raise RuntimeError('half-written module')\n", encoding="utf-8")
    (tmp_path / "fw_no_router_feature.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    target = FastAPI()
    with caplog.at_level(logging.ERROR, logger="formwright"):
        mounted = include_routers(target, ("formwright.no_such_feature", "fw_broken_feature", "fw_no_router_feature", "formwright.shop.routes"))
    assert mounted == ["formwright.shop.routes"]
    text = caplog.text
    assert "formwright.no_such_feature is not there" in text and "fw_broken_feature failed to import" in text and "has no `router`" in text
    assert any(p.startswith("/api/shop/") for r in target.routes for p in _paths(r))


async def test_listings_answer_json_not_the_web_app(client):
    r = await client.get("/api/shop/listings")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json") and r.json() == []
    r = await client.get("/api/shop/tariff")
    assert r.json()["currency"] == "KZT" and set(r.json()["materials"]) >= {"PLA", "PETG"}


async def test_feature_error_codes_are_top_level(client):
    r = await client.get("/api/shop/ops/queue")
    assert r.status_code == 403 and r.json() == {"detail": "operators only", "code": "not_operator"}
    r = await client.get("/api/shop/orders/so_nope")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


async def test_collection_skips_print_plates(client):
    db = await dbmod.get_db()
    t = dbmod.now()
    for pid, brief in (("p_find", {"collect": True}), ("p_plate", {"collect": True, "plate": {"ids": ["p_find"], "size_mm": 48}})):
        await db.insert("projects", {"id": pid, "user_id": "u1", "title": pid, "pack": "collect", "brief": brief, "created_at": t, "updated_at": t})
    items = (await client.get("/api/collection")).json()
    assert [i["id"] for i in items] == ["p_find"]
    assert appmod.ROUTERS is ROUTERS
