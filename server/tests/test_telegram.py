"""Telegram bot flow with the network and the agent stubbed out."""
from __future__ import annotations

import pytest

from formwright import db as dbmod
from formwright.config import settings
from formwright.integrations import telegram


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def test_text_message_starts_a_job_and_links_login(fresh_db, monkeypatch):
    sent: list[tuple[str, dict]] = []
    started: list[tuple[str, str]] = []

    async def fake_call(self, method, **params):
        sent.append((method, params))
        return {"message_id": 7}

    async def fake_start(user, project, body):
        started.append((user["id"], body.text))
        return "j_test"

    async def no_follow(*args, **kwargs):
        return None

    monkeypatch.setattr(telegram.Bot, "call", fake_call)
    monkeypatch.setattr(telegram.Bot, "follow", no_follow)
    import formwright.agent.runner as runner

    monkeypatch.setattr(runner, "start_design_job", fake_start)
    bot = telegram.Bot("TOKEN")
    msg = {"chat": {"id": 42}, "from": {"id": 9001, "first_name": "Aru"}, "text": "hook for an 18 mm shelf"}
    await bot.on_message(msg)
    assert started == [("tg_9001", "hook for an 18 mm shelf")]
    assert any(m == "sendMessage" for m, _ in sent)
    row = await fresh_db.one("SELECT * FROM tg_chats WHERE chat_id = 42")
    assert row and row["user_id"] == "tg_9001"
    link = await bot.login_link("tg_9001", row["project_id"])
    token = link.split("/api/login/")[1].split("?")[0]
    assert await fresh_db.one("SELECT * FROM logins WHERE token = ?", token)
    await bot.http.aclose()


async def test_new_command_switches_project(fresh_db, monkeypatch):
    async def fake_call(self, method, **params):
        return {"message_id": 1}

    monkeypatch.setattr(telegram.Bot, "call", fake_call)
    bot = telegram.Bot("TOKEN")
    base = {"chat": {"id": 5}, "from": {"id": 77}}
    await bot.on_message({**base, "text": "/new"})
    first = (await fresh_db.one("SELECT project_id FROM tg_chats WHERE chat_id = 5"))["project_id"]
    await bot.on_message({**base, "text": "/new"})
    second = (await fresh_db.one("SELECT project_id FROM tg_chats WHERE chat_id = 5"))["project_id"]
    assert first != second
    await bot.http.aclose()
