"""The project detail carries brief.printer, so the studio's print panel opens on the printer the agent checked for."""
from __future__ import annotations

import httpx
import pytest

from formwright import db as dbmod, sessions
from formwright.app import app
from formwright.config import settings


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings(), "open_base_url", "")
    (tmp_path / "files").mkdir(exist_ok=True)
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def test_the_detail_names_the_briefs_printer(fresh_db):
    t = dbmod.now()
    await fresh_db.insert("users", {"id": "u_a", "tier": "anon", "created_at": t})
    for pid, brief in (("p_set", {"printer": "bambu-lab-a1-mini-0-4-nozzle"}), ("p_none", {}), ("p_odd", {"printer": {"id": "x"}})):
        await fresh_db.insert("projects", {"id": pid, "user_id": "u_a", "title": pid, "brief": brief, "created_at": t, "updated_at": t})
    cookies = {sessions.COOKIE: await sessions.issue("u_a")}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=cookies) as c:
        assert (await c.get("/api/projects/p_set")).json()["printer"] == "bambu-lab-a1-mini-0-4-nozzle"
        assert (await c.get("/api/projects/p_none")).json()["printer"] is None
        assert (await c.get("/api/projects/p_odd")).json()["printer"] is None
