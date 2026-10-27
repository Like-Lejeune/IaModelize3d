"""Telegram bot: send photos, a voice note or text, get a printable model back.

People already send "can you make this?" photos to print shops in messengers; this
meets them there. Started inside the API process when FW_TELEGRAM_TOKEN is set.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import httpx

from .. import events
from ..config import settings
from ..db import get_db, new_id, now
from ..geom import geom
from ..models import SendMessage

log = logging.getLogger(__name__)

WELCOME = ("Send photos of the part next to a sheet of A4 paper or a bank card for scale, a voice note or text describing what you need. "
           "I'll design a printable model, check it and send you the file. /new starts a new project.")


class Bot:
    def __init__(self, token: str) -> None:
        self.api = f"https://api.telegram.org/bot{token}"
        self.file_api = f"https://api.telegram.org/file/bot{token}"
        self.http = httpx.AsyncClient(timeout=70)
        self.pending: dict[int, list[str]] = {}

    async def call(self, method: str, **params: Any) -> Any:
        r = await self.http.post(f"{self.api}/{method}", json=params)
        data = r.json()
        if not data.get("ok"):
            log.warning("telegram %s failed: %s", method, data.get("description"))
        return data.get("result")

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

    async def login_link(self, user_id: str, project_id: str) -> str:
        db = await get_db()
        token = new_id("l_") + new_id()
        await db.insert("logins", {"token": token, "user_id": user_id, "expires_at": now() + 7 * 86400})
        return f"{settings().public_url}/api/login/{token}?next=/p/{project_id}"

    # ------------------------------------------------------------ handlers
    async def on_message(self, msg: dict[str, Any]) -> None:
        chat_id = msg["chat"]["id"]
        text = msg.get("text") or msg.get("caption") or ""
        if text.startswith("/start"):
            await self.call("sendMessage", chat_id=chat_id, text=WELCOME)
            return
        user, project = await self.user_and_project(msg["from"], chat_id, fresh=text.startswith("/new"))
        if text.startswith("/new"):
            self.pending.pop(chat_id, None)
            await self.call("sendMessage", chat_id=chat_id, text="New project. Send photos or describe what you need.")
            return
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
            await self.call("sendMessage", chat_id=chat_id, text=f"Could not read that file: {e}")
            return
        if not text:
            await self.call("sendMessage", chat_id=chat_id, text="Got it. Add more photos or tell me what you need.")
            return
        await self.run_job(chat_id, user, project, text)

    async def run_job(self, chat_id: int, user: dict, project: dict, text: str) -> None:
        from .. import quotas
        from ..agent.runner import start_design_job

        assets = self.pending.pop(chat_id, [])
        try:
            job_id = await start_design_job(user, project, SendMessage(text=text, asset_ids=assets))
        except quotas.QuotaExceeded as e:
            await self.call("sendMessage", chat_id=chat_id, text=str(e))
            return
        status = await self.call("sendMessage", chat_id=chat_id, text="Working on it…")
        asyncio.create_task(self.follow(chat_id, user, project["id"], job_id, status["message_id"] if status else None))

    async def follow(self, chat_id: int, user: dict, project_id: str, job_id: str, status_id: int | None) -> None:
        db = await get_db()
        last = (await db.one("SELECT COALESCE(MAX(seq), 0) AS s FROM events WHERE project_id = ?", project_id))["s"] - 50  # type: ignore[index]
        last_status = ""
        cover = None
        while True:
            rows = await events.since(project_id, max(0, last))
            for r in rows:
                last = r["seq"]
                if r["job_id"] != job_id:
                    continue
                d = r["data"]
                if r["type"] == "agent.status" and status_id and d.get("text") and d["text"] != last_status:
                    last_status = d["text"]
                    await self.call("editMessageText", chat_id=chat_id, message_id=status_id, text=f"⏳ {last_status[:300]}")
                elif r["type"] == "program.updated":
                    cover = d.get("cover")
                elif r["type"] == "ask":
                    kb = [[{"text": o[:60], "callback_data": f"a|{job_id}|{i}"}] for i, o in enumerate(d.get("options", [])[:6])]
                    await self.call("sendMessage", chat_id=chat_id, text=d["question"], reply_markup={"inline_keyboard": kb})
                    self.questions[job_id] = d.get("options", [])
                elif r["type"] == "job.finished":
                    await self.finish(chat_id, user, project_id, d, cover)
                    return
            if not rows:
                await events.wait(project_id, 20)

    questions: dict[str, list[str]] = {}

    async def finish(self, chat_id: int, user: dict, project_id: str, d: dict, cover: str | None) -> None:
        db = await get_db()
        msg = await db.one("SELECT text FROM messages WHERE project_id = ? AND role = 'agent' ORDER BY created_at DESC LIMIT 1", project_id)
        text = (msg or {}).get("text") or d.get("summary") or "Done."
        link = await self.login_link(user["id"], project_id)
        buttons = [[{"text": "Open 3D studio", "url": link}],
                   [{"text": "Send 3MF", "callback_data": f"f|{project_id}|3mf"}, {"text": "Send STL", "callback_data": f"f|{project_id}|stl"}],
                   [{"text": "Order print (Axo)", "callback_data": f"o|{project_id}"}]]
        if cover:
            from .. import storage

            png = storage.abs_path(cover.removeprefix("/files/")).read_bytes()
            await self.send_photo(chat_id, png, text[:1000], buttons)
        else:
            await self.call("sendMessage", chat_id=chat_id, text=text[:4000], reply_markup={"inline_keyboard": buttons})

    async def on_callback(self, cb: dict[str, Any]) -> None:
        chat_id = cb["message"]["chat"]["id"]
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
            from ..integrations import axo
            from ..models import OrderRequest

            project = await db.one("SELECT * FROM projects WHERE id = ? AND user_id = ?", rest[0], user["id"])
            if project:
                r = await axo.create_order(user, project, OrderRequest())
                await self.call("sendMessage", chat_id=chat_id, text=r.get("checkout_url") or r.get("message") or str(r))

    async def run(self) -> None:
        offset = 0
        log.info("telegram bot started")
        while True:
            try:
                updates = await self.call("getUpdates", offset=offset, timeout=50, allowed_updates=["message", "callback_query"]) or []
            except (httpx.HTTPError, ValueError) as e:
                log.warning("telegram polling: %s", e)
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


async def run_bot() -> None:
    token = settings().telegram_token
    if token:
        await Bot(token).run()
