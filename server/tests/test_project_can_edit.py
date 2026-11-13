"""The project detail says whether this browser may change the project, by the rule the message route's 403 follows:
the owner may; a visitor on a public project may not, and the studio opens read-only for them with a Remix offer."""
from __future__ import annotations

import httpx
import pytest

from iamodelize3d import db as dbmod, sessions
from iamodelize3d.app import app
from iamodelize3d.config import settings


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


def client(cookies: dict[str, str] | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=cookies or {})


async def test_can_edit_follows_the_message_routes_403(fresh_db):
    t = dbmod.now()
    for uid in ("u_owner", "u_visitor"):
        await fresh_db.insert("users", {"id": uid, "tier": "anon", "created_at": t})
    await fresh_db.insert("projects", {"id": "p_pub", "user_id": "u_owner", "title": "Shared case", "public": 1, "brief": {}, "created_at": t, "updated_at": t})
    await fresh_db.insert("projects", {"id": "p_own", "user_id": "u_owner", "title": "Private", "brief": {}, "created_at": t, "updated_at": t})
    owner = {sessions.COOKIE: await sessions.issue("u_owner")}
    visitor = {sessions.COOKIE: await sessions.issue("u_visitor")}

    async with client(owner) as c:
        for pid in ("p_pub", "p_own"):
            d = (await c.get(f"/api/projects/{pid}")).json()
            assert d["can_edit"] is True, pid

    async with client(visitor) as c:
        d = (await c.get("/api/projects/p_pub")).json()
        assert d["can_edit"] is False and d["title"] == "Shared case"
        # what the flag stands for: the send is refused, and the studio offers the remix instead
        r = await c.post("/api/projects/p_pub/messages", json={"text": "make it bigger"})
        assert r.status_code == 403 and r.json()["code"] == "forbidden"
        assert (await c.patch("/api/projects/p_pub", json={"title": "mine now"})).status_code == 403
        # a private project is not shown to a visitor at all
        assert (await c.get("/api/projects/p_own")).status_code == 403

    # a browser with no session yet is a new anonymous visitor
    async with client() as c:
        assert (await c.get("/api/projects/p_pub")).json()["can_edit"] is False


async def test_send_message_takes_a_language(fresh_db):
    """CONTRACTS: SendMessage.language reaches the run (a shop order passes its intake's language); None by default."""
    from iamodelize3d.models import SendMessage

    assert SendMessage(text="x").language is None
    assert SendMessage(text="колесо", language="ru").language == "ru"
    assert SendMessage.model_validate({"text": "x", "language": "kk", "unknown": 1}).language == "kk"
