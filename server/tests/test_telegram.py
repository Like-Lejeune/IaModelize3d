"""Telegram bot flow with the network and the agent stubbed out."""
from __future__ import annotations

import pytest

from iamodelize3d import db as dbmod
from iamodelize3d.config import settings
from iamodelize3d.integrations import telegram


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
    import iamodelize3d.agent.runner as runner

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


# ------------------------------------------------------------------ orders through IaModelize3d Parts
def _chat(monkeypatch) -> tuple[list[tuple[str, dict]], list[str]]:
    """The bot's outgoing calls, and the shop steps it started (not run: no slicer or model here)."""
    from iamodelize3d.shop import autoquote

    sent: list[tuple[str, dict]] = []
    spawned: list[str] = []

    async def fake_call(self, method, **params):
        sent.append((method, params))
        return {"message_id": 1}

    async def no_follow(self, *args, **kwargs):
        return None

    def no_step(order_id, step):
        step.close()
        spawned.append(order_id)
        return True

    monkeypatch.setattr(telegram.Bot, "call", fake_call)
    monkeypatch.setattr(telegram.Bot, "follow_order", no_follow)
    monkeypatch.setattr(autoquote, "spawn", no_step)
    return sent, spawned


async def _model(db, user_id: str = "tg_9", pid: str = "p_tg") -> None:
    from iamodelize3d.db import now

    await db.insert("users", {"id": user_id, "tier": "free", "created_at": now()})
    await db.insert("projects", {"id": pid, "user_id": user_id, "title": "Shelf hook", "version": 1, "brief": {"telegram_chat": 42},
                                 "created_at": now(), "updated_at": now()})
    await db.insert("programs", {"project_id": pid, "version": 1, "source": "return lib.box(10,10,10)", "params": {}, "inputs": {},
                                 "checks": {"ok": True, "stats": {"estGrams": 12.0, "estMinutes": 30.0}}, "author": "agent", "created_at": now()})


async def test_order_button_makes_a_shop_order(fresh_db, monkeypatch):
    sent, spawned = _chat(monkeypatch)
    await _model(fresh_db)
    bot = telegram.Bot("TOKEN")
    await bot.on_callback({"id": "cb", "data": "o|p_tg", "message": {"chat": {"id": 42}}, "from": {"id": 9, "language_code": "ru"}})
    o = await fresh_db.one("SELECT * FROM shop_orders")
    assert o and o["project_id"] == "p_tg" and o["version"] == 1 and o["status"] == "requested" and spawned == [o["id"]]
    text = sent[-1][1]["text"]
    # Russian, the order's ref, the instant range in tenge with dollars, and a sign-in link that opens the order
    assert text.startswith(f"Заказ {o['ref']}: Shelf hook") and "Предварительно ≈ " in text and "₸ ($" in text
    assert "/api/login/" in text and f"?next=/orders/{o['id']}" in text
    token = text.split("/api/login/")[1].split("?")[0]
    assert await fresh_db.one("SELECT * FROM logins WHERE token = ? AND user_id = 'tg_9'", token)
    log = await fresh_db.one("SELECT note, data FROM shop_log WHERE order_id = ?", o["id"])
    assert log["data"]["code"] == "ordered_telegram" and log["note"] == "ordered from the Telegram chat"
    # someone else's project, or one with no model: no order, and the chat is told
    await bot.on_callback({"id": "cb", "data": "o|p_nope", "message": {"chat": {"id": 42}}, "from": {"id": 9}})
    assert (await fresh_db.one("SELECT COUNT(*) AS n FROM shop_orders"))["n"] == 1
    await fresh_db.execute("UPDATE projects SET version = 0 WHERE id = 'p_tg'")
    await bot.on_callback({"id": "cb", "data": "o|p_tg", "message": {"chat": {"id": 42}}, "from": {"id": 9, "language_code": "en"}})
    assert sent[-1][1]["text"] == telegram.t("en", "no_model")
    await bot.http.aclose()


async def test_part_command_orders_from_the_chat_photos(fresh_db, monkeypatch):
    from iamodelize3d.db import new_id, now
    from iamodelize3d.shop import store
    from iamodelize3d.vision import ingest

    sent, spawned = _chat(monkeypatch)

    async def fake_download(self, file_id):
        return b"jpeg", "photo.jpg"

    async def fake_ingest(project_id, kind, filename, data, mime):
        aid = new_id("a_")
        await fresh_db.insert("assets", {"id": aid, "project_id": project_id, "kind": kind, "path": f"{project_id}/{aid}.jpg", "meta": {},
                                         "created_at": now()})
        return {"id": aid, "kind": kind, "meta": {}}

    monkeypatch.setattr(telegram.Bot, "download", fake_download)
    monkeypatch.setattr(ingest, "ingest_asset", fake_ingest)
    bot = telegram.Bot("TOKEN")
    base = {"chat": {"id": 7}, "from": {"id": 55, "language_code": "en"}}
    await bot.on_message({**base, "text": "/part"})
    assert sent[-1][1]["text"] == telegram.t("en", "part_usage") and not await fresh_db.one("SELECT id FROM shop_orders")
    await bot.on_message({**base, "photo": [{"file_id": "f1"}]})
    assert sent[-1][1]["text"] == telegram.t("en", "got_it")
    chat_project = (await fresh_db.one("SELECT project_id FROM tg_chats WHERE chat_id = 7"))["project_id"]
    # the second photo carries the command in its caption
    await bot.on_message({**base, "photo": [{"file_id": "f2"}], "caption": "/part@IaModelize3dBot dishwasher basket wheel, 4 pcs"})
    o = await store.get(fresh_db, (await fresh_db.one("SELECT id FROM shop_orders"))["id"])
    assert o and o["user_id"] == "tg_55" and o["project_id"] != chat_project and spawned == [o["id"]]
    req = o["intake"]["request"]
    assert req["kind"] == "photo" and req["text"] == "dishwasher basket wheel, 4 pcs" and len(req["photos"]) == 2
    moved = await fresh_db.all("SELECT project_id FROM assets")
    assert {r["project_id"] for r in moved} == {o["project_id"]}  # the photos went with the part
    assert bot.pending.get(7) == []
    text = sent[-1][1]["text"]
    assert text.startswith(f"Spare-part request {o['ref']}, 2 photo(s).") and f"?next=/orders/{o['id']}" in text
    await bot.http.aclose()


async def test_follow_order_tells_the_price_and_the_stops(fresh_db, monkeypatch):
    from iamodelize3d.shop import store

    sent: list[tuple[str, dict]] = []

    async def fake_call(self, method, **params):
        sent.append((method, params))
        return {"message_id": 1}

    monkeypatch.setattr(telegram.Bot, "call", fake_call)
    await _model(fresh_db)
    db = await store.shop_db()
    o = await store.create_order(db, user_id="tg_9", project_id="p_tg", version=1, quantity=2)
    await store.patch(db, o["id"], {"problem": {"code": "slice_failed", "detail": "SliceError: boom"}})
    bot = telegram.Bot("TOKEN")
    states = iter([None, {"status": "quoted", "quote": {"binding": True, "total": 9980.0, "usd": {"total": 19.19}, "grams_each": 3.1,
                                                         "minutes_each": 20.6, "quantity": 2}, "problem": {}, "intake": {"refuse": False}}, None])

    async def step(_):
        s = next(states)
        if s:
            await db.update("shop_orders", "id", o["id"], s)

    monkeypatch.setattr(telegram.asyncio, "sleep", step)
    await bot.follow_order(42, {"id": "tg_9"}, o["id"], "ru", rounds=3)
    texts = [p["text"] for _, p in sent]
    assert texts[0] == f"{o['ref']} на паузе: слайсер не смог посчитать цену. Оператор фермы это тоже видит."
    assert texts[1].startswith(f"{o['ref']}: 9 980 ₸ ($19.19) по OrcaSlicer (3.1 г, 20.6 мин на штуку, ×2).") and "next=/orders/" in texts[1]
    assert len(texts) == 2 and "SliceError" not in " ".join(texts)
    await bot.http.aclose()



async def test_a_part_orders_question_comes_into_the_chat(fresh_db, monkeypatch):
    """/part order in needs_info: the designer's question with its options as buttons; a tap or a reply to the message
    answers it through the shop (deliver_answer, kept in the order's intake); a stale button is told so."""
    from iamodelize3d import events
    from iamodelize3d.db import now
    from iamodelize3d.shop import routes as shop, store

    sent: list[tuple[str, dict]] = []

    async def fake_call(self, method, **params):
        sent.append((method, params))
        return {"message_id": 100 + len(sent)}

    delivered: list[tuple[str, str, str]] = []

    async def fake_answer(job_id, user_id, text):  # runner.deliver_answer: the waiting job takes it and runs on
        delivered.append((job_id, user_id, text))
        await fresh_db.execute("UPDATE jobs SET status = 'running' WHERE id = ? AND status = 'waiting'", job_id)
        return True

    async def no_sleep(_):
        return None

    monkeypatch.setattr(telegram.Bot, "call", fake_call)
    monkeypatch.setattr(shop.hooks, "answer", fake_answer)
    monkeypatch.setattr(telegram.asyncio, "sleep", no_sleep)
    await fresh_db.insert("users", {"id": "tg_55", "tier": "free", "created_at": now()})
    pid = await shop.new_part_project(fresh_db, "tg_55", "")
    db = await store.shop_db()
    o = await store.create_order(db, user_id="tg_55", project_id=pid, status="needs_info", intake={"request": {"kind": "photo", "text": "wheel"}})
    await fresh_db.insert("jobs", {"id": "j_1", "project_id": pid, "user_id": "tg_55", "kind": "design", "status": "waiting", "input": {},
                                   "created_at": now()})
    await events.emit(pid, "ask", {"job_id": "j_1", "question_id": "q_1", "question": "Is the axle 4 mm or 5 mm?",
                                   "options": ["4 mm", "5 mm"], "allow_text": True}, "j_1")
    bot = telegram.Bot("TOKEN")
    await bot.follow_order(7, {"id": "tg_55"}, o["id"], "ru", rounds=3)
    asks = [p for m, p in sent if m == "sendMessage"]
    assert len(asks) == 1  # once per question, however long it waits
    text = asks[0]["text"]
    assert text.startswith(f"{o['ref']}: вопрос от конструктора:\nIs the axle 4 mm or 5 mm?\n\nНажмите вариант ответа") and f"next=/orders/{o['id']}" in text
    kb = asks[0]["reply_markup"]["inline_keyboard"]
    assert [b[0]["text"] for b in kb] == ["4 mm", "5 mm"] and kb[1][0]["callback_data"] == f"q|{o['id']}|q_1|1"
    assert all(len(b[0]["callback_data"].encode()) <= 64 for b in kb)
    # a tap answers it
    cb = {"id": "cb", "message": {"chat": {"id": 7}}, "from": {"id": 55, "language_code": "ru"}}
    await bot.on_callback({**cb, "data": kb[1][0]["callback_data"]})
    assert delivered == [("j_1", "tg_55", "5 mm")]
    assert [a["text"] for a in (await store.get(db, o["id"]))["intake"]["answers"]] == ["5 mm"]
    assert sent[-1][1]["text"] == telegram.t("ru", "answered", ref=o["ref"], answer="5 mm")
    await bot.on_callback({**cb, "data": kb[0][0]["callback_data"]})  # tapped again: nothing waits any more
    assert len(delivered) == 1 and sent[-1][1]["text"] == telegram.t("ru", "no_question", ref=o["ref"])

    # a second question with no options: a reply to its message answers it; the first question's buttons are stale
    await fresh_db.execute("UPDATE jobs SET status = 'waiting' WHERE id = 'j_1'")
    await events.emit(pid, "ask", {"job_id": "j_1", "question_id": "q_2", "question": "How wide is the slot?", "options": [], "allow_text": True}, "j_1")
    await bot.follow_order(7, {"id": "tg_55"}, o["id"], "en", rounds=1)
    ask2, ask2_id = sent[-1][1], 100 + len(sent)
    assert ask2["text"].startswith(f"{o['ref']}: the designer asks:\nHow wide is the slot?\n\nReply to this message") and "reply_markup" not in ask2
    await bot.on_callback({**cb, "data": kb[0][0]["callback_data"]})
    assert len(delivered) == 1  # the stale button did not answer the new question
    msg = {"chat": {"id": 7}, "from": {"id": 55, "language_code": "en"}, "reply_to_message": {"message_id": ask2_id},
           "text": "about 4.2 mm"}
    await bot.on_message(msg)
    assert delivered[-1] == ("j_1", "tg_55", "about 4.2 mm") and sent[-1][1]["text"].startswith(f"{o['ref']}: the designer has your answer")
    assert not bot.replies  # answered: that message takes no more answers
    # someone else's tap on the order's button answers nothing and tells them nothing
    await fresh_db.execute("UPDATE jobs SET status = 'waiting' WHERE id = 'j_1'")
    await events.emit(pid, "ask", {"job_id": "j_1", "question_id": "q_3", "question": "Glossy?", "options": ["yes"]}, "j_1")
    await fresh_db.insert("users", {"id": "tg_66", "tier": "free", "created_at": now()})
    n = len(sent)
    await bot.on_callback({"id": "cb", "data": f"q|{o['id']}|q_3|0", "message": {"chat": {"id": 8}}, "from": {"id": 66}})
    assert len(delivered) == 2 and [m for m, _ in sent[n:]] == ["answerCallbackQuery"]
    await bot.on_callback({**cb, "data": f"q|{o['id']}|q_3|0"})
    assert delivered[-1] == ("j_1", "tg_55", "yes")
    await bot.http.aclose()


def test_quota_and_language():
    from iamodelize3d.quotas import QuotaExceeded

    assert telegram.lang_of({"language_code": "kk"}) == "ru" and telegram.lang_of({"language_code": "de"}) == "en" and telegram.lang_of(None) == "en"
    assert telegram.quota_text(QuotaExceeded("daily limit $0.50 reached", code="daily_limit"), "ru").startswith("Дневной лимит")
    assert telegram.quota_text(QuotaExceeded("something new", code="other"), "ru") == "something new"
    assert telegram.price_range({"range": {"total": [5490, 12590], "total_usd": [10.56, 24.21]}}) == "≈ 5 490–12 590 ₸ ($10.56–24.21)"
    assert set(telegram.TEXT["ru"]) == set(telegram.TEXT["en"])
