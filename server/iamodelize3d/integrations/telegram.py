"""Telegram bot: send photos, a voice note or text, get a printable model back.

People already send "can you make this?" photos to print shops in messengers; this
meets them there. Started inside the API process when FW_TELEGRAM_TOKEN is set.

Orders go through IaModelize3d Parts (shop/routes.py), the same path as the web: "Order print" on a finished model
(no design step, the instant range at once, OrcaSlicer's price a few seconds later), and /part <what it is> for a
spare part from the photos sent before it. A question the designer asks about that part comes into the chat with its
options as buttons, as in a design job here. The bot answers in Russian or English, after the sender's Telegram language.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import httpx
from fastapi import HTTPException

from .. import events
from ..config import settings
from ..db import get_db, new_id, now
from ..geom import geom
from ..models import SendMessage

log = logging.getLogger(__name__)

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "welcome": ("Send photos of the part next to a sheet of A4 paper or a bank card for scale, a voice note or text describing what you need. "
                    "I'll design a printable model, check it and send you the file. /new starts a new project.\n"
                    "/part <what it is> orders a spare part printed by the Axo farm: send its photos on A4 first, or put /part in a photo's caption."),
        "new": "New project. Send photos or describe what you need.",
        "unreadable": "Could not read that file: {e}",
        "got_it": "Got it. Add more photos or tell me what you need.",
        "working": "Working on it…",
        "done": "Done.",
        "studio": "Open 3D studio", "3mf": "Send 3MF", "stl": "Send STL", "order": "Order print (Axo)",
        "ordered": "Order {ref}: {title}.\nEstimate {range}; OrcaSlicer prices the exact file in about 15 seconds.\nOpen the order: {link}",
        "ordered_no_range": "Order {ref}: {title}. OrcaSlicer prices the exact file in about 15 seconds.\nOpen the order: {link}",
        "part": ("Spare-part request {ref}{photos}. IaModelize3d reads it, designs the part and checks it before you pay; "
                 "the price comes from the slicer once the model is ready.\nFollow the order: {link}"),
        "photos": ", {n} photo(s)",
        "part_usage": "Write what the part is after /part, e.g. /part dishwasher basket wheel, Bosch SMS46, 4 pcs. Photos of it on an A4 sheet help most.",
        "quoted": "{ref}: {total} by OrcaSlicer ({grams}, {minutes} per piece, ×{n}). Pay and follow the order: {link}",
        "refused": "{ref}: we cannot print this part. {reason}",
        "held": "{ref} waits for the farm operator: a person checks the request first.",
        "asked": "{ref}: the designer has a question. Answer it on the order page: {link}",
        "asked_q": "{ref}: the designer asks:\n{question}\n\n{how}",
        "ask_tap_or_reply": "Tap an answer, or reply to this message in your own words. The order page takes it too: {link}",
        "ask_tap": "Tap an answer. The order page takes it too: {link}",
        "ask_reply": "Reply to this message with your answer. The order page takes it too: {link}",
        "answered": "{ref}: the designer has your answer ({answer}) and goes on.",
        "no_question": "{ref}: that question is no longer waiting. The order page shows where the order stands.",
        "stopped": "{ref} is paused: {why}. The farm operator sees it too.",
        "no_model": "There is no model to order yet: design it first.",
        "error": "That did not work: {e}",
        "q.daily_limit": "Today's limit is used up; sliders, checks and downloads still work.",
        "q.demo_budget": "The demo budget for today is used up; replays and sliders still work.",
        "q.ip_daily_cap": "Today's limit for anonymous use from this network is used up.",
        "q.job_running": "Another job is still running; try again when it finishes.",
        "q.project_busy": "The model is busy with another job; try again when it finishes.",
        "p.slice_failed": "the slicer could not price it",
        "p.no_model": "the design ended without a model",
        "p.step_failed": "an automatic step failed on our side; it is tried again shortly",
        "p.design_unreviewed": "the operator looks at the design first",
        "broke": "Something broke on our side, so I stopped here. Please try again in a minute.",
        "lost_track": "I lost the connection while following this. The latest state is here: {link}",
    },
    "ru": {
        "welcome": ("Пришлите фото детали рядом с листом A4 или банковской картой для масштаба, голосовое или текст: что нужно. "
                    "Я спроектирую модель для печати, проверю её и пришлю файл. /new — новый проект.\n"
                    "/part <что это> — заказать запчасть с печатью на ферме Axo: сначала пришлите её фото на листе A4 или напишите /part в подписи к фото."),
        "new": "Новый проект. Пришлите фото или опишите, что нужно.",
        "unreadable": "Не получилось прочитать файл: {e}",
        "got_it": "Принято. Добавьте ещё фото или напишите, что нужно.",
        "working": "Работаю…",
        "done": "Готово.",
        "studio": "Открыть 3D-студию", "3mf": "Прислать 3MF", "stl": "Прислать STL", "order": "Заказать печать (Axo)",
        "ordered": "Заказ {ref}: {title}.\nПредварительно {range}; точную цену OrcaSlicer посчитает примерно за 15 секунд.\nОткрыть заказ: {link}",
        "ordered_no_range": "Заказ {ref}: {title}. Точную цену OrcaSlicer посчитает примерно за 15 секунд.\nОткрыть заказ: {link}",
        "part": ("Заявка на запчасть {ref}{photos}. IaModelize3d прочитает её, спроектирует деталь и проверит до оплаты; "
                 "цену посчитает слайсер, когда модель будет готова.\nСледить за заказом: {link}"),
        "photos": ", фото: {n}",
        "part_usage": "Напишите после /part, что это за деталь, например: /part колёсико корзины посудомойки Bosch SMS46, 4 шт. Лучше всего помогают фото на листе A4.",
        "quoted": "{ref}: {total} по OrcaSlicer ({grams}, {minutes} на штуку, ×{n}). Оплатить и следить за заказом: {link}",
        "refused": "{ref}: эту деталь мы не печатаем. {reason}",
        "held": "{ref} ждёт оператора фермы: заявку сначала посмотрит человек.",
        "asked": "{ref}: у конструктора вопрос. Ответьте на странице заказа: {link}",
        "asked_q": "{ref}: вопрос от конструктора:\n{question}\n\n{how}",
        "ask_tap_or_reply": "Нажмите вариант ответа или ответьте на это сообщение своими словами. Ответить можно и на странице заказа: {link}",
        "ask_tap": "Нажмите вариант ответа. Ответить можно и на странице заказа: {link}",
        "ask_reply": "Ответьте на это сообщение. Ответить можно и на странице заказа: {link}",
        "answered": "{ref}: ответ передан конструктору ({answer}), работа продолжается.",
        "no_question": "{ref}: этот вопрос уже не ждёт ответа. Где сейчас заказ, видно на его странице.",
        "stopped": "{ref} на паузе: {why}. Оператор фермы это тоже видит.",
        "no_model": "Модели для заказа пока нет: сначала спроектируйте её.",
        "error": "Не получилось: {e}",
        "q.daily_limit": "Дневной лимит исчерпан; ползунки, проверки и скачивание работают.",
        "q.demo_budget": "Демо-бюджет на сегодня исчерпан; повторы и ползунки работают.",
        "q.ip_daily_cap": "Лимит анонимного использования из этой сети на сегодня исчерпан.",
        "q.job_running": "Другая задача ещё идёт; попробуйте, когда она закончится.",
        "q.project_busy": "Модель занята другой задачей; попробуйте, когда она закончится.",
        "p.slice_failed": "слайсер не смог посчитать цену",
        "p.no_model": "проектирование закончилось без модели",
        "p.step_failed": "автоматический шаг сорвался у нас; скоро он повторится",
        "p.design_unreviewed": "сначала модель посмотрит оператор",
        "broke": "У нас что-то сломалось, поэтому я остановился. Попробуйте ещё раз через минуту.",
        "lost_track": "Я потерял связь, пока следил за этим. Текущее состояние здесь: {link}",
    },
}
WELCOME = TEXT["en"]["welcome"]
FOLLOW_TRIES = 6  # failures in a row before a watcher gives up and says so; a pause of 2, 4, ... seconds after each
RU_LANGS = ("ru", "kk", "ky", "uz", "uk", "be")  # Kazakhstan and around: Russian is the shared language of the UI


def lang_of(tg_user: dict[str, Any] | None) -> str:
    return "ru" if str((tg_user or {}).get("language_code") or "").lower()[:2] in RU_LANGS else "en"


def t(lang: str, key: str, **kw: Any) -> str:
    s = TEXT.get(lang, TEXT["en"]).get(key) or TEXT["en"].get(key) or key
    return s.format(**kw) if kw else s


def kzt(v: float | None) -> str:
    return "—" if v is None else f"{float(v):,.0f}".replace(",", " ") + " ₸"


def price_range(q: dict[str, Any]) -> str | None:
    """'≈ 5 490–5 790 ₸ ($10.56–11.13)': the instant range, tenge first."""
    r = (q or {}).get("range") or {}
    lo_hi, usd = r.get("total"), r.get("total_usd")
    if not lo_hi:
        return None
    text = kzt(lo_hi[0]) if lo_hi[0] == lo_hi[1] else f"{kzt(lo_hi[0])[:-2]}–{kzt(lo_hi[1])}"
    return f"≈ {text}" + (f" (${usd[0]:.2f}–{usd[1]:.2f})" if usd else "")


def quota_text(e: Exception, lang: str) -> str:
    code = getattr(e, "code", "")
    return t(lang, f"q.{code}") if f"q.{code}" in TEXT["en"] else str(e)


def ask_keyboard(options: list[str], data: str) -> list[list[dict[str, str]]]:
    """A question's options as buttons, at most 6: a tap sends back `data|<index>` (Telegram allows 64 bytes)."""
    return [[{"text": str(o)[:60], "callback_data": f"{data}|{i}"}] for i, o in enumerate(options[:6])]


async def question(db: Any, project_id: str) -> dict[str, Any]:
    """The designer's latest question in a project (its 'ask' event: question_id, question, options, allow_text)."""
    row = await db.one("SELECT data FROM events WHERE project_id = ? AND type = 'ask' ORDER BY seq DESC LIMIT 1", project_id)
    return (row or {}).get("data") or {}


class Bot:
    def __init__(self, token: str) -> None:
        self.api = f"https://api.telegram.org/bot{token}"
        self.file_api = f"https://api.telegram.org/file/bot{token}"
        self.http = httpx.AsyncClient(timeout=70)
        self.pending: dict[int, list[str]] = {}
        self.langs: dict[int, str] = {}  # chat -> 'ru' | 'en', from the last sender's Telegram language
        self.replies: dict[tuple[int, int], tuple[str, str]] = {}  # (chat, message) of a relayed question -> (order, question_id)
        self.tasks: set[asyncio.Task] = set()  # the watchers running: the loop only keeps weak references to tasks

    async def call(self, method: str, **params: Any) -> Any:
        r = await self.http.post(f"{self.api}/{method}", json=params)
        try:
            data = r.json()
        except ValueError:
            log.warning("telegram %s: an answer that is not JSON (%s)", method, r.status_code)
            return None
        if not data.get("ok"):
            log.warning("telegram %s failed: %s", method, data.get("description"))
        return data.get("result")

    def watch(self, step: Any) -> None:
        """A watcher in the background, held until it ends; whatever ends it is in the log."""
        task = asyncio.create_task(step)
        self.tasks.add(task)

        def done(t: asyncio.Task) -> None:
            self.tasks.discard(t)
            if not t.cancelled() and t.exception():
                log.error("telegram watcher failed", exc_info=t.exception())

        task.add_done_callback(done)

    async def lost_track(self, chat_id: int, user: dict, project_id: str, path: str | None = None) -> None:
        """A watcher gives up: the chat is told where the rest is, if it can still be told anything."""
        try:
            await self.say(chat_id, t(self.langs.get(chat_id, "en"), "lost_track", link=await self.login_link(user["id"], project_id, path)))
        except Exception as e:  # noqa: BLE001 - the failure that stopped the watcher may stop this too
            log.warning("telegram chat %s could not be told: %s: %s", chat_id, type(e).__name__, e)

    async def send_photo(self, chat_id: int, png: bytes, caption: str, buttons: list[list[dict]] | None = None) -> None:
        files = {"photo": ("model.png", png, "image/png")}
        data = {"chat_id": str(chat_id), "caption": caption[:1000]}
        if buttons:
            data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
        await self.http.post(f"{self.api}/sendPhoto", data=data, files=files)

    async def send_document(self, chat_id: int, data: bytes, filename: str, caption: str = "") -> None:
        await self.http.post(f"{self.api}/sendDocument", data={"chat_id": str(chat_id), "caption": caption}, files={"document": (filename, data)})

    async def download(self, file_id: str) -> tuple[bytes, str]:
        info = await self.call("getFile", file_id=file_id)
        path = info["file_path"]
        r = await self.http.get(f"{self.file_api}/{path}")
        return r.content, path.rsplit("/", 1)[-1]

    # ------------------------------------------------------------ state
    async def user_and_project(self, tg_user: dict[str, Any], chat_id: int, fresh: bool = False) -> tuple[dict, dict]:
        db = await get_db()
        uid = f"tg_{tg_user['id']}"
        user = await db.one("SELECT * FROM users WHERE id = ?", uid)
        if not user:
            await db.insert("users", {"id": uid, "tier": "free", "name": tg_user.get("first_name"), "created_at": now()})
            user = await db.one("SELECT * FROM users WHERE id = ?", uid)
        chat = await db.one("SELECT * FROM tg_chats WHERE chat_id = ?", chat_id)
        project = await db.one("SELECT * FROM projects WHERE id = ?", chat["project_id"]) if chat and not fresh else None
        if not project:
            pid = new_id("p_")
            await db.insert("projects", {"id": pid, "user_id": uid, "title": "New project", "brief": {"telegram_chat": chat_id}, "created_at": now(), "updated_at": now()})
            await db.execute("INSERT INTO tg_chats (chat_id, user_id, project_id) VALUES (?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET project_id = excluded.project_id",
                             chat_id, uid, pid)
            project = await db.one("SELECT * FROM projects WHERE id = ?", pid)
        return user, project  # type: ignore[return-value]

    async def login_link(self, user_id: str, project_id: str, path: str | None = None) -> str:
        """A one-time sign-in link that opens the project (or `path`, e.g. /orders/<id>) in the browser."""
        db = await get_db()
        token = new_id("l_") + new_id()
        await db.insert("logins", {"token": token, "user_id": user_id, "expires_at": now() + 7 * 86400})
        return f"{settings().public_url}/api/login/{token}?next={path or f'/p/{project_id}'}"

    async def say(self, chat_id: int, text: str, **extra: Any) -> Any:
        return await self.call("sendMessage", chat_id=chat_id, text=text[:4000], **extra)

    # ------------------------------------------------------------ handlers
    async def on_message(self, msg: dict[str, Any]) -> None:
        chat_id = msg["chat"]["id"]
        text = msg.get("text") or msg.get("caption") or ""
        lang = self.langs[chat_id] = lang_of(msg.get("from"))
        cmd = text.split(maxsplit=1)[0].split("@")[0].lower() if text.startswith("/") else ""
        if cmd == "/start":
            await self.say(chat_id, t(lang, "welcome"))
            return
        user, project = await self.user_and_project(msg["from"], chat_id, fresh=cmd == "/new")
        if cmd == "/new":
            self.pending.pop(chat_id, None)
            await self.say(chat_id, t(lang, "new"))
            return
        replied = (msg.get("reply_to_message") or {}).get("message_id")
        if replied and msg.get("text") and not cmd and (chat_id, replied) in self.replies:
            order_id, qid = self.replies[(chat_id, replied)]
            await self.answer_part(chat_id, user, order_id, qid, lang, text=msg["text"])
            return
        from .. import quotas
        from ..vision import ingest

        try:
            if msg.get("photo"):
                data, name = await self.download(msg["photo"][-1]["file_id"])
                asset = await ingest.ingest_asset(project["id"], "photo", name, data, "image/jpeg")
                self.pending.setdefault(chat_id, []).append(asset["id"])
            elif msg.get("voice") or msg.get("audio"):
                f = msg.get("voice") or msg.get("audio")
                data, name = await self.download(f["file_id"])
                asset = await ingest.ingest_asset(project["id"], "audio", name or "voice.ogg", data, f.get("mime_type", "audio/ogg"))
                self.pending.setdefault(chat_id, []).append(asset["id"])
                text = text or asset["meta"].get("transcript", "")
            elif msg.get("video") or msg.get("video_note"):
                f = msg.get("video") or msg.get("video_note")
                data, name = await self.download(f["file_id"])
                asset = await ingest.ingest_asset(project["id"], "video", name or "video.mp4", data, "video/mp4")
                self.pending.setdefault(chat_id, []).append(asset["id"])
        except ValueError as e:
            await self.say(chat_id, t(lang, "unreadable", e=e))
            return
        except quotas.QuotaExceeded as e:
            await self.say(chat_id, quota_text(e, lang))
            return
        if cmd == "/part":
            await self.start_part(chat_id, user, project, text.partition(" ")[2].strip())
            return
        if not text:
            await self.say(chat_id, t(lang, "got_it"))
            return
        await self.run_job(chat_id, user, project, text)

    async def run_job(self, chat_id: int, user: dict, project: dict, text: str) -> None:
        from .. import quotas
        from ..agent.runner import start_design_job

        assets = self.pending.pop(chat_id, [])
        try:
            job_id = await start_design_job(user, project, SendMessage(text=text, asset_ids=assets))
        except quotas.QuotaExceeded as e:
            await self.say(chat_id, quota_text(e, self.langs.get(chat_id, "en")))
            return
        status = await self.say(chat_id, t(self.langs.get(chat_id, "en"), "working"))
        self.watch(self.follow(chat_id, user, project["id"], job_id, status["message_id"] if status else None))

    async def follow(self, chat_id: int, user: dict, project_id: str, job_id: str, status_id: int | None) -> None:
        db = await get_db()
        last = (await db.one("SELECT COALESCE(MAX(seq), 0) AS s FROM events WHERE project_id = ?", project_id))["s"] - 50  # type: ignore[index]
        last_status = ""
        stage_label = ""
        cover = None
        failures = 0
        while True:
            try:
                rows = await events.since(project_id, max(0, last))
                for r in rows:
                    # an event counts as read once it is told: after a failure the same one is told again
                    if r["job_id"] == job_id:
                        d = r["data"]
                        line = None
                        if r["type"] == "job.stage":
                            stage_label = d.get("label", "")
                            line = f"⏳ {stage_label}"
                        elif r["type"] in ("tool.call", "tool.result") and d.get("title"):
                            line = f"⏳ {stage_label}\n{'→' if r['type'] == 'tool.call' else '✓'} {d['title']}"
                        if line and status_id and line != last_status:
                            last_status = line
                            await self.call("editMessageText", chat_id=chat_id, message_id=status_id, text=line[:1000])
                        if r["type"] == "program.updated":
                            cover = d.get("cover")
                        elif r["type"] == "ask":
                            kb = ask_keyboard(d.get("options", []), f"a|{job_id}")
                            await self.call("sendMessage", chat_id=chat_id, text=d["question"], reply_markup={"inline_keyboard": kb})
                            self.questions[job_id] = d.get("options", [])
                        elif r["type"] == "job.finished":
                            await self.finish(chat_id, user, project_id, d, cover)
                            return
                    last = r["seq"]
                if not rows:
                    await events.wait(project_id, 20)
                failures = 0
            except Exception as e:  # noqa: BLE001 - the job runs on: the network or a locked database must not end the telling
                failures += 1
                log.warning("telegram follow of %s (%d): %s: %s", job_id, failures, type(e).__name__, e)
                if failures >= FOLLOW_TRIES:
                    await self.lost_track(chat_id, user, project_id)
                    return
                await asyncio.sleep(2 ** failures)

    questions: dict[str, list[str]] = {}

    async def finish(self, chat_id: int, user: dict, project_id: str, d: dict, cover: str | None) -> None:
        db = await get_db()
        msg = await db.one("SELECT text FROM messages WHERE project_id = ? AND role = 'agent' ORDER BY created_at DESC LIMIT 1", project_id)
        lang = self.langs.get(chat_id, "en")
        text = (msg or {}).get("text") or d.get("summary") or t(lang, "done")
        link = await self.login_link(user["id"], project_id)
        buttons = [[{"text": t(lang, "studio"), "url": link}],
                   [{"text": t(lang, "3mf"), "callback_data": f"f|{project_id}|3mf"}, {"text": t(lang, "stl"), "callback_data": f"f|{project_id}|stl"}],
                   [{"text": t(lang, "order"), "callback_data": f"o|{project_id}"}]]
        png = None
        if cover:
            from .. import storage

            try:
                png = storage.abs_path(cover.removeprefix("/files/")).read_bytes()
            except OSError as e:  # the words and the buttons still go
                log.warning("telegram: no cover for %s: %s", project_id, e)
        if png:
            await self.send_photo(chat_id, png, text[:1000], buttons)
        else:
            await self.call("sendMessage", chat_id=chat_id, text=text[:4000], reply_markup={"inline_keyboard": buttons})

    async def on_callback(self, cb: dict[str, Any]) -> None:
        chat_id = cb["message"]["chat"]["id"]
        lang = self.langs[chat_id] = lang_of(cb.get("from"))
        kind, *rest = cb["data"].split("|")
        await self.call("answerCallbackQuery", callback_query_id=cb["id"])
        db = await get_db()
        user = await db.one("SELECT * FROM users WHERE id = ?", f"tg_{cb['from']['id']}")
        if not user:
            return
        if kind == "a":
            from ..agent.runner import deliver_answer

            job_id, idx = rest[0], int(rest[1])
            options = self.questions.get(job_id, [])
            if idx < len(options):
                await deliver_answer(job_id, user["id"], options[idx])
        elif kind == "f":
            project_id, fmt = rest
            prog = await db.one("SELECT * FROM programs p JOIN projects j ON j.id = p.project_id WHERE p.project_id = ? AND j.user_id = ? ORDER BY version DESC LIMIT 1",
                                project_id, user["id"])
            if prog:
                out = await geom().export(prog["source"], prog["params"], fmt, inputs=prog["inputs"])
                await self.send_document(chat_id, base64.b64decode(out["data"]), f"model.{fmt}")
        elif kind == "o":
            project = await db.one("SELECT * FROM projects WHERE id = ? AND user_id = ?", rest[0], user["id"])
            if project:
                await self.order_print(chat_id, user, project, lang)
        elif kind == "q":
            order_id, qid, idx = rest
            await self.answer_part(chat_id, user, order_id, qid, lang, option=int(idx))

    # ------------------------------------------------------------ orders (IaModelize3d Parts, printed by the Axo farm)
    async def _shop_failed(self, chat_id: int, e: HTTPException, lang: str) -> None:
        """A refused order said in the chat: the shop's {detail, code}."""
        detail = e.detail if isinstance(e.detail, dict) else {"detail": str(e.detail)}
        await self.say(chat_id, t(lang, "no_model") if detail.get("code") == "no_model" else t(lang, "error", e=detail.get("detail")))

    async def order_print(self, chat_id: int, user: dict, project: dict, lang: str) -> None:
        """The model designed in this chat, ordered the way the studio orders it: no design step, the instant range now,
        OrcaSlicer's binding price in a follow-up message."""
        from .. import quotas
        from ..shop import routes as shop, store

        db = await store.shop_db()
        try:
            o = await shop.order_project(db, user, project, code="ordered_telegram")
        except quotas.QuotaExceeded as e:
            await self.say(chat_id, quota_text(e, lang))
            return
        except HTTPException as e:
            await self._shop_failed(chat_id, e, lang)
            return
        link = await self.login_link(user["id"], project["id"], f"/orders/{o['id']}")
        rng = price_range(o.get("quote") or {})
        title = f"{project['title']} · {o['material']}"
        await self.say(chat_id, t(lang, "ordered", ref=o["ref"], title=title, range=rng, link=link) if rng else
                       t(lang, "ordered_no_range", ref=o["ref"], title=title, link=link))
        self.watch(self.follow_order(chat_id, user, o["id"], lang))

    async def start_part(self, chat_id: int, user: dict, project: dict, what: str) -> None:
        """/part <what it is>: a spare-part request from the photos sent before it (or with it). They move to the part's
        own project, where the agent designs it; the chat keeps its project for anything else."""
        from .. import quotas
        from ..shop import routes as shop, store
        from ..shop.intake import UNNAMED

        lang = self.langs.get(chat_id, "en")
        db = await store.shop_db()
        pending = self.pending.get(chat_id, [])
        photos = [r["id"] for r in [await db.one("SELECT id, kind FROM assets WHERE id = ? AND project_id = ?", a, project["id"]) for a in pending]
                  if r and r["kind"] == "photo"]
        if not what and not photos:
            await self.say(chat_id, t(lang, "part_usage"))
            return
        self.pending[chat_id] = [a for a in pending if a not in photos]
        pid = await shop.new_part_project(db, user["id"], what[:80] or UNNAMED[1 if lang == "ru" else 0])
        for aid in photos:
            await db.execute("UPDATE assets SET project_id = ? WHERE id = ? AND project_id = ?", pid, aid, project["id"])
        try:
            o = await shop.order_part(db, user, pid, photos=[{"id": a, "role": "part"} for a in photos], text=what, code="ordered_telegram")
        except quotas.QuotaExceeded as e:
            await self.say(chat_id, quota_text(e, lang))
            return
        except HTTPException as e:
            await self._shop_failed(chat_id, e, lang)
            return
        link = await self.login_link(user["id"], pid, f"/orders/{o['id']}")
        await self.say(chat_id, t(lang, "part", ref=o["ref"], photos=t(lang, "photos", n=len(photos)) if photos else "", link=link))
        self.watch(self.follow_order(chat_id, user, o["id"], lang))

    async def follow_order(self, chat_id: int, user: dict, order_id: str, lang: str, rounds: int = 360, every: float = 5.0) -> None:
        """Tells the chat when the order has its slicer price, or why it stopped (refused, held for the operator, a
        question from the designer, a problem). Half an hour at most; the order page has the rest.
        A ready model is priced while the intake reads it: 'pay' is said only once Pay is open (the safety verdict is
        in, no step is still changing the price, and the price is in the material the intake picked for "choose for
        me"), so a refusal or a hold that comes after the price is told too."""
        from ..shop import store

        db = await store.shop_db()
        told: set[str] = set()
        failures = 0
        project_id = None
        for _ in range(rounds):
            await asyncio.sleep(every)
            try:
                o = await store.get(db, order_id)
                if not o:
                    return
                project_id = o["project_id"]
                if await self.order_round(chat_id, user, order_id, o, lang, db, told):
                    return
                failures = 0
            except Exception as e:  # noqa: BLE001 - the order goes on: a failure here only costs this look at it
                failures += 1
                log.warning("telegram follow of order %s (%d): %s: %s", order_id, failures, type(e).__name__, e)
                if failures >= FOLLOW_TRIES:
                    if project_id:
                        await self.lost_track(chat_id, user, project_id, f"/orders/{order_id}")
                    return
                await asyncio.sleep(2 ** failures)

    async def order_round(self, chat_id: int, user: dict, order_id: str, o: dict, lang: str, db: Any, told: set[str]) -> bool:
        """One look at the order; True when there is nothing more to tell. What is told counts as told once it went out."""
        from ..shop import autoquote, flow

        status, q, data = o["status"], o.get("quote") or {}, o.get("intake") or {}
        if (status == "quoted" and q.get("binding") and flow.safety(o) is None and not autoquote.running(order_id)
                and not flow.material_due(o)):
            usd = (q.get("usd") or {}).get("total")
            await self.say(chat_id, t(lang, "quoted", ref=o["ref"], total=kzt(q.get("total")) + (f" (${usd:.2f})" if usd is not None else ""),
                                      grams=f"{q.get('grams_each')} {'г' if lang == 'ru' else 'g'}",
                                      minutes=f"{q.get('minutes_each')} {'мин' if lang == 'ru' else 'min'}", n=q.get("quantity") or o["quantity"],
                                      link=await self.login_link(user["id"], o["project_id"], f"/orders/{order_id}")))
            return True
        if status == "refused":
            await self.say(chat_id, t(lang, "refused", ref=o["ref"], reason=data.get("reason") or (data.get("reviewed") or {}).get("note") or ""))
            return True
        if status not in ("requested", "designing", "needs_info", "quoted"):
            return True  # paid, cancelled or further on: the order page has it from here
        ask = await question(db, o["project_id"]) if status == "needs_info" else None
        if ask is not None and (key := f"ask.{ask.get('question_id') or ''}") not in told:
            await self.relay_question(chat_id, user, o, ask, lang)
            told.add(key)  # each question once: a second one after the answer is told too
        elif data.get("review") and not data.get("reviewed") and "held" not in told:
            await self.say(chat_id, t(lang, "held", ref=o["ref"]))
            told.add("held")
        elif (code := (o.get("problem") or {}).get("code")) and f"p.{code}" not in told:
            why = next((t(lang, k) for k in (f"p.{code}", f"q.{code}") if k in TEXT["en"]), code)
            await self.say(chat_id, t(lang, "stopped", ref=o["ref"], why=why.rstrip(".")))
            told.add(f"p.{code}")
        return False

    async def relay_question(self, chat_id: int, user: dict, o: dict, ask: dict[str, Any], lang: str) -> None:
        """The designer's question about a /part order, in the chat: its options as buttons (as in a design job here),
        a reply to the message for an answer in the customer's own words, and the order page, which takes it too."""
        link = await self.login_link(user["id"], o["project_id"], f"/orders/{o['id']}")
        text, options, typed = str(ask.get("question") or "").strip(), list(ask.get("options") or [])[:6], ask.get("allow_text", True) is not False
        if not text or not (options or typed):
            await self.say(chat_id, t(lang, "asked", ref=o["ref"], link=link))
            return
        how = t(lang, "ask_tap_or_reply" if options and typed else "ask_tap" if options else "ask_reply", link=link)
        kb = ask_keyboard(options, f"q|{o['id']}|{ask.get('question_id') or ''}")
        sent = await self.say(chat_id, t(lang, "asked_q", ref=o["ref"], question=text[:3000], how=how),
                              **({"reply_markup": {"inline_keyboard": kb}} if kb else {}))
        if typed and sent and sent.get("message_id"):
            self.replies[(chat_id, sent["message_id"])] = (o["id"], ask.get("question_id") or "")

    async def answer_part(self, chat_id: int, user: dict, order_id: str, question_id: str, lang: str, *, text: str = "",
                          option: int | None = None) -> None:
        """A tapped option or a reply to the relayed question: the answer goes to the designer the way the order page
        sends it (shop.routes.answer_order: runner.deliver_answer, and the order's intake keeps it)."""
        from ..shop import routes as shop, store

        db = await store.shop_db()
        o = await store.get(db, order_id)
        if not o or o["user_id"] != user["id"]:
            return
        ask = await question(db, o["project_id"])
        if option is not None:
            options = ask.get("options") or []
            text = str(options[option]) if 0 <= option < len(options) else ""
        same = (ask.get("question_id") or "") == question_id
        done = await shop.answer_order(db, o, text) if same and text.strip() else None
        if done:
            self.replies = {k: v for k, v in self.replies.items() if v != (order_id, question_id)}
        await self.say(chat_id, t(lang, "answered", ref=o["ref"], answer=text.strip()[:300]) if done else t(lang, "no_question", ref=o["ref"]))

    async def run(self) -> None:
        offset = 0
        log.info("telegram bot started")
        while True:
            try:
                updates = await self.call("getUpdates", offset=offset, timeout=50, allowed_updates=["message", "callback_query"])
            except (httpx.HTTPError, ValueError) as e:
                log.warning("telegram polling: %s", e)
                await asyncio.sleep(5)
                continue
            if updates is None:  # Telegram said no (a bad token, a second bot on this token): call logged why
                await asyncio.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    if "message" in u:
                        await self.on_message(u["message"])
                    elif "callback_query" in u:
                        await self.on_callback(u["callback_query"])
                except Exception:  # noqa: BLE001 - one bad update must not stop the bot
                    log.exception("telegram update failed")
                    await self.tell_failed(u)

    async def tell_failed(self, update: dict[str, Any]) -> None:
        """A calm line instead of silence when handling someone's message failed."""
        msg = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        if chat_id is None:
            return
        try:
            await self.say(chat_id, t(self.langs.get(chat_id, "en"), "broke"))
        except Exception as e:  # noqa: BLE001
            log.warning("telegram chat %s could not be told: %s: %s", chat_id, type(e).__name__, e)


async def run_bot() -> None:
    token = settings().telegram_token
    if token:
        await Bot(token).run()
