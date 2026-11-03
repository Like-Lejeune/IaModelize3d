"""HTTP API. Run: uvicorn formwright.app:app --port 8400 (from server/)."""
from __future__ import annotations

import asyncio
import base64
import bisect
import importlib
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import events, quotas, sessions, showcase
from .agent import narrate
from .config import REPO_DIR, settings
from .db import close_db, get_db, new_id, now
from .geom import GeomError, geom
from .llm.client import BudgetExceeded
from .models import (
    AnswerRequest,
    AssetOut,
    BreedRequest,
    ConceptRequest,
    CreateProject,
    ExportRequest,
    MessageOut,
    OrderRequest,
    ParamsUpdate,
    Point,
    ProgramUpdate,
    ProgramOut,
    ProjectDetail,
    ProjectOut,
    SelectionOut,
    SelectRequest,
    SpotRequest,
    SendMessage,
    SliceRequest,
    Usage,
    VisualEditRequest,
)

log = logging.getLogger("formwright")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def recover_interrupted() -> int:
    """Jobs still 'running' or 'waiting' belonged to the previous process, whose tasks are gone: close them as failed
    and free every project left 'working' (replay copies too), so nobody watches a dead job or is blocked by one."""
    db = await get_db()
    t = now()
    stuck = await db.all("SELECT * FROM jobs WHERE status IN ('running', 'waiting')")
    for j in stuck:
        cost = (j["result"] if isinstance(j["result"], dict) else {}).get("cost") or {
            "usd": j["cost_usd"], "tokens_in": j["tokens_in"], "tokens_out": j["tokens_out"], "tokens_cached": j["tokens_cached"], "calls": 0, "by_model": {}}
        await db.update("jobs", "id", j["id"], {"status": "failed", "finished_at": t, "result": {"summary": "interrupted: the server restarted", "cost": cost}})
        if not j["project_id"]:
            continue
        if j["kind"] == "design":
            # as the runner does for a stopped job: "Continue" picks the interrupted request up again
            p = await db.one("SELECT brief FROM projects WHERE id = ?", j["project_id"])
            if p:
                brief = p["brief"] or {}
                req = j["input"] if isinstance(j["input"], dict) else {}
                turns = (brief.get("turns") or []) + [f"{str(req.get('text', ''))[:200]} (interrupted: failed)"]
                await db.update("projects", "id", j["project_id"], {"brief": {**brief, "turns": turns[-10:]}})
        await events.emit(j["project_id"], "job.finished", {"job_id": j["id"], "status": "failed", "summary": "interrupted", "cost": cost}, j["id"])
    working = await db.all("SELECT id FROM projects WHERE status = 'working'")
    await db.execute("UPDATE projects SET status = 'idle', updated_at = ? WHERE status = 'working'", t)
    if stuck or working:
        log.info("startup recovery: %d interrupted jobs failed, %d projects set idle", len(stuck), len(working))
    return len(stuck)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await get_db()
    try:
        await recover_interrupted()
    except Exception:  # noqa: BLE001 - a bad row must not keep the API from starting
        log.exception("startup recovery failed")
    async def sleep_cycle() -> None:
        from .memory.sleep import consolidate

        while True:
            await asyncio.sleep(6 * 3600)
            try:
                log.info("memory consolidation: %s", await consolidate())
            except Exception:  # noqa: BLE001 - never take the API down for housekeeping
                log.exception("memory consolidation failed")

    sleeper = asyncio.create_task(sleep_cycle())
    # example covers are built once per program; doing it now keeps the first home page visit quick
    warm = asyncio.create_task(showcase.warm())
    bot = None
    if settings().telegram_token:
        from .integrations.telegram import run_bot

        bot = asyncio.create_task(run_bot())
    yield
    sleeper.cancel()
    warm.cancel()
    if bot:
        bot.cancel()
    await geom().close()
    from . import pcb

    await pcb.close()
    await close_db()


app = FastAPI(title="Formwright", lifespan=lifespan)
FILES = settings().data_dir / "files"


async def files_allowed(request: Request, top: str, rel: str) -> str | None:
    """Whether this browser may read data/files/<rel>, whose first part <top> is a project id (or 'examples'):
    'public' for anyone, 'private' for this signed-in viewer only, None when not.
    Example covers and public projects are open; a private project's files go to its owner, the farm's operators
    (they print, check and ship every order), and for a shop order only what its page shows: the project's cover to
    whoever ordered it, a colleague's project to the repair shop, a catalog card's cover, an order's QC photo.
    A showcase order (delivered, shown to anyone without its customer's data) opens the render of the version it printed
    (not the project's cover: the customer's later versions stay theirs) and its QC photo and mask."""
    if top == "examples":
        return "public"
    db = await get_db()
    p = await db.one("SELECT id, user_id, public, cover, version FROM projects WHERE id = ?", top)
    if not p:
        return None
    if p["public"]:
        return "public"
    user, _ = await sessions.user_for(request.cookies.get(sessions.COOKIE))
    if user and user["id"] == p["user_id"]:
        return "private"
    from .shop import store

    sdb = await store.shop_db()
    if await sdb.one("SELECT 1 FROM shop_listings WHERE project_id = ? AND public = 1 AND flagged = 0 AND cover = ?", top, rel):
        return "public"
    url = f"/files/{rel}"  # a QC photo sits in the farm's own project
    shown = "showcase = 1 AND status IN ('shipped', 'delivered')"
    shows = await sdb.all(f"SELECT project_id, version FROM shop_orders WHERE project_id = ? AND {shown}", top)
    if any(rel == store.shipped_cover(o, p) for o in shows) or await sdb.one(
            f"SELECT 1 FROM shop_orders WHERE {shown} AND (json_extract(qc, '$.photo_url') = ? OR json_extract(qc, '$.mask_url') = ?)", url, url):
        return "public"
    if not user:
        return None
    role, org = await store.role(sdb, user["id"])
    if role == "operator":
        return "private"
    mine = "(user_id = ? OR (org_id IS NOT NULL AND org_id = ?))"
    orders = await sdb.all(f"SELECT user_id, org_id, project_id, version, listing_id FROM shop_orders WHERE project_id = ? AND {mine}",
                           top, user["id"], org)
    # someone else's catalog card, bought: that card's picture and the render of the version it prints, not the owner's
    # cover as it is now (a later private version)
    bought = [o for o in orders if o["listing_id"] and o["user_id"] != p["user_id"]]
    own = [o for o in orders if o not in bought]
    if own and (rel == p["cover"] or any(org and o["org_id"] == org and o["user_id"] == p["user_id"] for o in own)):
        return "private"
    if bought and (any(rel == store.shipped_cover(o, p) for o in bought) or await sdb.one(
            f"SELECT 1 FROM shop_listings WHERE id IN ({', '.join('?' * len(bought))}) AND cover = ?", *[o["listing_id"] for o in bought], rel)):
        return "private"
    qc = await sdb.one(f"SELECT 1 FROM shop_orders WHERE {mine} AND (json_extract(qc, '$.photo_url') = ? OR json_extract(qc, '$.mask_url') = ?)",
                       user["id"], org, url, url)
    return "private" if qc else None


class ProjectFiles(StaticFiles):
    """data/files behind files_allowed (it was an open mount: board, QC, rating-plate and snap photos of private
    projects went to anyone holding a URL). Starlette has already normalised the path; whatever it does not allow,
    or does not exist, is a 404 alike. A file only this viewer may read is never stored by a shared proxy, nor kept in
    the browser's cache, where it would still show after signing out (the server itself answers 404 without the cookie)."""

    async def get_response(self, path: str, scope: Any) -> Response:
        parts = Path(path).parts
        access = await files_allowed(Request(scope), parts[0], Path(*parts).as_posix()) if parts else None
        if not access:
            raise StarletteHTTPException(404)
        response = await super().get_response(path, scope)
        if access == "private":
            response.headers["Cache-Control"] = "private, no-store"
        # as pcbapi serves them: a file is what its type says, and an SVG opened on its own runs nothing
        response.headers["X-Content-Type-Options"] = "nosniff"
        if path.lower().endswith(".svg"):
            from .pcbapi import SVG_CSP

            response.headers["Content-Security-Policy"] = SVG_CSP
        return response


app.mount("/files", ProjectFiles(directory=FILES), name="files")


def file_url(path: str | None) -> str | None:
    return f"/files/{path}" if path else None


# ------------------------------------------------------------------ session
def _address(value: str) -> str:
    """'203.0.113.7', '203.0.113.7:5123', '[2001:db8::1]:443' or '2001:db8::1' -> the address alone."""
    value = value.strip().strip('"')
    if value.startswith("[") and "]" in value:
        return value[1:value.index("]")]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def client_ip(request: Request) -> str:
    """The visitor's address, for the per-address cap on anonymous use. With --proxy-headers uvicorn rewrites
    request.client from X-Forwarded-For, but trusting every sender (FORWARDED_ALLOW_IPS="*") it takes the leftmost
    entry, which the visitor writes. Proxies append the address they see, so the entry FW_PROXY_HOPS places from the
    right is one a proxy of ours wrote."""
    hops = settings().proxy_hops
    if hops < 0:
        hops = int(os.environ.get("FORWARDED_ALLOW_IPS", "").strip() == "*")
    if hops:
        chain = [h for v in request.headers.getlist("x-forwarded-for") for h in v.split(",") if h.strip()]
        if chain:
            return _address(chain[-hops] if len(chain) >= hops else chain[0])
    return request.client.host if request.client else "unknown"


async def current_user(request: Request, response: Response) -> dict[str, Any]:
    """The person behind this browser: its session, a cookie from before sessions swapped for one, or a new
    anonymous user. The cookie is a random session token (sessions.py), never the user id."""
    token = request.cookies.get(sessions.COOKIE)
    user, renew = await sessions.user_for(token)
    if not renew:
        token = None  # the browser's cookie is still good as it is
    if not user:
        user = await sessions.adopt_legacy(request.cookies.get(sessions.LEGACY_COOKIE))
        if not user:
            db = await get_db()
            uid = new_id("u_")
            await db.insert("users", {"id": uid, "tier": "anon", "ip": quotas.network(client_ip(request)), "created_at": now()})
            user = await db.one("SELECT * FROM users WHERE id = ?", uid)
        token = await sessions.issue(user["id"])  # type: ignore[index]
    sessions.send_cookie(response, request, token)
    return user  # type: ignore[return-value]


async def load_project(project_id: str, user: dict[str, Any], write: bool = False) -> dict[str, Any]:
    db = await get_db()
    p = await db.one("SELECT * FROM projects WHERE id = ?", project_id)
    if not p:
        raise HTTPException(404, "project not found")
    if p["user_id"] != user["id"] and (write or not p["public"]):
        raise HTTPException(403, "not your project")
    return p


def project_out(p: dict[str, Any]) -> dict[str, Any]:
    return ProjectOut(
        id=p["id"], title=p["title"], pack=p["pack"], status=p["status"], version=p["version"], public=bool(p["public"]),
        cover=file_url(p["cover"]), forked_from=p["forked_from"], created_at=p["created_at"], updated_at=p["updated_at"],
    ).model_dump()


def asset_out(a: dict[str, Any]) -> dict[str, Any]:
    return AssetOut(
        id=a["id"], kind=a["kind"], url=file_url(a["path"]) or "", thumb_url=file_url(a["meta"].get("thumb")),
        width=a["width"], height=a["height"], meta={k: v for k, v in a["meta"].items() if k not in ("thumb", "exif_raw")},
    ).model_dump()


def selection_out(s: dict[str, Any]) -> dict[str, Any]:
    return SelectionOut(id=s["id"], asset_id=s["asset_id"], role=s["role"], name=s["name"], mask_url=file_url(s["mask_path"]), data=s["data"]).model_dump()


async def latest_program(project_id: str) -> dict[str, Any] | None:
    db = await get_db()
    return await db.one("SELECT * FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", project_id)


LOGIN_NONCE = "fw_login"
LOGIN_CSS = (":root{color-scheme:dark;--bg:#13140f;--fg:#e4e3db;--muted:#c6c8b8;--accent:#b1d355;--on-accent:#273500}"
             "@media (prefers-color-scheme:light){:root{color-scheme:light;--bg:#fbf9f1;--fg:#1b1c17;--muted:#45483c;--accent:#4f6700;--on-accent:#fff}}"
             "body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);font-family:Archivo,system-ui,sans-serif}"
             "main{max-width:26rem;padding:2rem 16px;text-align:center}h1{font-size:1.4rem;margin:0 0 .75rem}p{line-height:1.5;color:var(--muted)}"
             "button,a{display:inline-block;margin-top:.75rem;padding:.75rem 1.75rem;border:0;border-radius:999px;background:var(--accent);"
             "color:var(--on-accent);font:inherit;font-weight:600;text-decoration:none;cursor:pointer}")


def _safe_next(next: str) -> str:
    # a path on this site only: to a browser "//host" and "/\host" are other sites
    return next if re.fullmatch(r"/(?![/\\])[^\\\s]*", next) else "/"


def _login_page(lang: str, text: str, action: str, status: int = 200) -> HTMLResponse:
    title = escape(narrate.login_text("title", lang))
    page = (f'<!doctype html><html lang="{narrate.login_text("lang", lang)}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">'
            f"<title>{title}</title><style>{LOGIN_CSS}</style></head><body><main><h1>{title}</h1><p>{escape(text)}</p>{action}</main></body></html>")
    # the token is in this page's URL: keep it out of caches and of the Referer of anything the page leads to
    return HTMLResponse(page, status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def _login_gone(lang: str) -> HTMLResponse:
    return _login_page(lang, narrate.login_text("gone", lang), f'<a href="/">{escape(narrate.login_text("home", lang))}</a>', status=404)


def _login_lang(request: Request) -> str:
    return request.headers.get("accept-language", "").split(",")[0].strip()


@app.get("/api/login/{token}", include_in_schema=False)
async def magic_login(token: str, request: Request, next: str = "/"):
    """A sign-in link (scripts/judge_link.py, the Telegram bot) works once. Opening it only shows a button: link
    previews and mail scanners open the URL too and must not use it up. The button posts back a nonce that a cookie
    set here also carries; a form on another site cannot send that cookie, so nobody signs a visitor into their account."""
    lang = _login_lang(request)
    target = await sessions.login_target(token)
    if not target:
        return _login_gone(lang)
    path = f"/api/login/{quote(token, safe='')}"
    nonce = secrets.token_urlsafe(16)
    text = narrate.login_text("as", lang, name=target["name"]) if target["name"] else narrate.login_text("plain", lang)
    form = (f'<form method="post" action="{escape(path)}?next={escape(quote(_safe_next(next)))}">'
            f'<input type="hidden" name="nonce" value="{nonce}"><button type="submit">{escape(narrate.login_text("go", lang))}</button></form>')
    resp = _login_page(lang, text, form)
    resp.set_cookie(LOGIN_NONCE, nonce, max_age=1800, httponly=True, samesite="lax", path=path, secure=request.url.scheme == "https")
    return resp


@app.post("/api/login/{token}", include_in_schema=False)
async def magic_login_confirm(token: str, request: Request, next: str = "/", nonce: str = Form("")):
    """The button on that page: uses the link up and signs this browser in with a session of its own."""
    path = f"/api/login/{quote(token, safe='')}"
    sent = request.cookies.get(LOGIN_NONCE, "")
    if not (sent and nonce and secrets.compare_digest(sent.encode(), nonce.encode())):
        # not posted from our page (a form on another site), or the page sat open too long: show it again
        return RedirectResponse(f"{path}?next={quote(_safe_next(next))}", status_code=303)
    uid = await sessions.redeem(token)
    if not uid:
        return _login_gone(_login_lang(request))
    resp = RedirectResponse(_safe_next(next), status_code=303)
    sessions.send_cookie(resp, request, await sessions.issue(uid))
    resp.delete_cookie(LOGIN_NONCE, path=path)
    return resp


@app.get("/api/me")
async def me(user=Depends(current_user)) -> Usage:
    usd, jobs = await quotas.spent_today(user["id"])
    limit = quotas.TIERS.get(user["tier"], quotas.TIERS["anon"])[0]
    return Usage(user_id=user["id"], tier=user["tier"], today_usd=round(usd, 4), limit_usd=limit, jobs_today=jobs,
                 contributor_consent=bool(user["contributor_consent"]), models=quotas.model_options(user))


@app.post("/api/me/consent")
async def consent(body: dict[str, bool], user=Depends(current_user)):
    db = await get_db()
    await db.update("users", "id", user["id"], {"contributor_consent": 1 if body.get("contributor") else 0})
    return {"ok": True}


# ------------------------------------------------------------------ projects
@app.post("/api/projects")
async def create_project(body: CreateProject, user=Depends(current_user)):
    db = await get_db()
    pid = new_id("p_")
    t = now()
    await db.insert("projects", {"id": pid, "user_id": user["id"], "title": body.title or "New project", "pack": body.pack, "created_at": t, "updated_at": t})
    return project_out(await db.one("SELECT * FROM projects WHERE id = ?", pid))  # type: ignore[arg-type]


@app.get("/api/projects")
async def list_projects(user=Depends(current_user)):
    db = await get_db()
    rows = await db.all("SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC LIMIT 100", user["id"])
    return [project_out(p) for p in rows]


@app.get("/api/gallery")
async def gallery():
    db = await get_db()
    rows = await db.all("SELECT * FROM projects WHERE public = 1 AND replay_of IS NULL ORDER BY updated_at DESC LIMIT 60")
    return [project_out(p) for p in rows]


@app.get("/api/featured")
async def featured():
    """Real agent runs picked for the home page (projects.featured, set by scripts/curate_demo.py): watching one
    replays its event log, so it costs nothing. Empty when nothing is featured."""
    db = await get_db()
    rows = await db.all("SELECT * FROM projects WHERE public = 1 AND featured > 0 AND replay_of IS NULL ORDER BY featured DESC, updated_at DESC LIMIT 6")
    out = []
    for p in rows:
        jobs = await db.all("SELECT kind, status, result, created_at, finished_at FROM jobs WHERE project_id = ? ORDER BY created_at", p["id"])
        design = [j for j in jobs if j["kind"] == "design" and j["finished_at"]]
        first = next((j for j in design if j["status"] == "done"), design[0] if design else None)
        costs = [c for j in jobs if isinstance(j["result"], dict) and (c := j["result"].get("cost"))]
        # calls per model when every job counted them (older jobs kept only USD per model); the two units never mix
        key = "calls_by_model" if costs and all("calls_by_model" in c for c in costs) else "by_model"
        models: dict[str, float] = {}
        for c in costs:
            for m, v in (c.get(key) or {}).items():
                models[m] = models.get(m, 0) + v
        # a run opened from a ready example still has that example's title in the language it was opened in (open_example
        # names it, the agent renames only 'New project'): the home page shows the example's own title in the UI's language.
        # Matched by the words (any case), so a title the person changed stays theirs
        said = str(p["title"] or "").strip().casefold()
        ex = next((e for e in showcase.EXAMPLES if said in {v.casefold() for v in e["title"].values()}), None)
        out.append({
            "id": p["id"], "title": p["title"], "cover": file_url(p["cover"]), "pack": p["pack"], "versions": p["version"],
            **({"title_en": ex["title"]["en"], "title_ru": ex["title"]["ru"]} if ex else await _order_titles(p)),
            "summary": str((p["brief"] or {}).get("summary") or "")[:200],
            "duration_s": round(first["finished_at"] - first["created_at"]) if first else None,
            "models": {m: round(v, 5) for m, v in models.items()} if key == "by_model" else models,
        })
    return out


async def _order_titles(p: dict[str, Any]) -> dict[str, str]:
    """A run born from a shop order (the designer of a new part): the project keeps its title on its own script's side,
    and the other language gets the intake's catalog title, as the order page names it. {} for any other run."""
    from .shop import store

    sdb = await store.shop_db()
    o = store._dec(await sdb.one("SELECT intake FROM shop_orders WHERE project_id = ? AND json_extract(intake, '$.request.kind') = 'photo' "
                                 "ORDER BY created_at LIMIT 1", p["id"]))
    data = (o or {}).get("intake") or {}
    cls = data.get("classify") if isinstance(data.get("classify"), dict) else {}
    if not o or cls.get("error") or (data.get("review") or {}).get("code") == "safety_disagreement" or not (cls.get("title_en") and cls.get("title_ru")):
        return {}
    title = str(p["title"] or "")
    ru = bool(re.search(r"[А-Яа-яЁё]", title))
    return {"title_en": cls["title_en"] if ru else title, "title_ru": title if ru else cls["title_ru"]}


@app.get("/api/examples")
async def list_examples():
    out = []
    for ex in showcase.EXAMPLES:
        ready = await showcase.prepared(ex)
        if ready:
            # kind 'part': a spare part with its fit checked (the home page marks it)
            out.append({k: ex[k] for k in ("key", "pack", "title", "caption", "prompt")} | {"cover": file_url(ready["cover"]),
                                                                                         "kind": "part" if ex.get("fit") else "model"})
    return out


@app.post("/api/examples/{key}")
async def open_example(key: str, body: dict[str, Any], user=Depends(current_user)):
    """A ready example as the visitor's own project: the model opens at once, no agent run and no cost."""
    from .agent.runner import add_message

    ex = showcase.BY_KEY.get(key)
    ready = await showcase.prepared(ex) if ex else None
    if not ex or not ready:
        raise HTTPException(404, "no such example")
    lang = "ru" if body.get("lang") == "ru" else "en"
    db = await get_db()
    pid = new_id("p_")
    t = now()
    await db.insert("projects", {"id": pid, "user_id": user["id"], "title": ex["title"][lang], "pack": ex["pack"], "version": 1, "cover": ready["cover"],
                                 "brief": {"turns": [ex["prompt"][lang]], "summary": f"Ready example: {ex['title']['en']}", "language": lang,
                                           **({"material": ex["material"]} if ex.get("material") else {})},
                                 "created_at": t, "updated_at": t})
    await db.insert("programs", {"project_id": pid, "version": 1, "source": ex["source"], "params": ready["params"],
                                 "inputs": ready.get("inputs") or ex.get("inputs") or {},
                                 "summary": ex["title"][lang], "checks": ready["checks"], "author": "example", "created_at": t})
    if ready.get("pcb"):
        # the routed board the case was made from, as the project's PCB version 1 (files copied from the example's cache)
        await showcase.add_pcb(pid, ready)
    intro = showcase.intro(ex, ready, lang)
    await add_message(pid, "user", ex["prompt"][lang])
    await add_message(pid, "agent", intro)
    await events.emit(pid, "agent.message", {"text": intro})
    return project_out(await db.one("SELECT * FROM projects WHERE id = ?", pid))  # type: ignore[arg-type]


@app.get("/api/projects/{project_id}")
async def project_detail(project_id: str, user=Depends(current_user)) -> ProjectDetail:
    p = await load_project(project_id, user)
    db = await get_db()
    assets = await db.all("SELECT * FROM assets WHERE project_id = ? ORDER BY created_at", project_id)
    sels = await db.all("SELECT * FROM selections WHERE project_id = ? ORDER BY created_at", project_id)
    msgs = await db.all("SELECT * FROM messages WHERE project_id = ? ORDER BY created_at", project_id)
    prog = await latest_program(project_id)
    last = await db.one("SELECT COALESCE(MAX(seq), 0) AS s FROM events WHERE project_id = ?", project_id)
    job = await db.one("SELECT id, kind, status, cost_usd FROM jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1", project_id)
    return ProjectDetail(
        **project_out(p),
        assets=[AssetOut(**asset_out(a)) for a in assets],
        selections=[SelectionOut(**selection_out(s)) for s in sels],
        program=ProgramOut(**{k: prog[k] for k in ("version", "source", "params", "inputs", "summary", "checks", "author", "created_at")}) if prog else None,
        messages=[MessageOut(id=m["id"], role=m["role"], text=m["text"], data=m["data"], created_at=m["created_at"]) for m in msgs],
        last_seq=last["s"] if last else 0,
        job=job,
        printer=p["brief"].get("printer") if isinstance(p["brief"], dict) and isinstance(p["brief"].get("printer"), str) else None,
        material=p["brief"].get("material") if isinstance(p["brief"], dict) and isinstance(p["brief"].get("material"), str) else None,
        # load_project(write=True)'s rule, the one send_message answers 403 by
        can_edit=p["user_id"] == user["id"],
    )


@app.patch("/api/projects/{project_id}")
async def update_project(project_id: str, body: dict[str, Any], user=Depends(current_user)):
    await load_project(project_id, user, write=True)
    fields = {k: v for k, v in body.items() if k in ("title", "pack")}
    if "public" in body:
        fields["public"] = 1 if body["public"] else 0
    db = await get_db()
    await db.update("projects", "id", project_id, {**fields, "updated_at": now()})
    return project_out(await db.one("SELECT * FROM projects WHERE id = ?", project_id))  # type: ignore[arg-type]


REPLAY_SKIP = {"cost"}


async def _replay(src_id: str, dst_id: str, speed: float) -> None:
    """Re-emit a finished project's event log into a new project: watch how it was made, no tokens spent."""
    db = await get_db()
    rows = await db.all("SELECT * FROM events WHERE project_id = ? ORDER BY seq", src_id)
    prev_ts = rows[0]["ts"] if rows else now()
    clock: list[tuple[float, float]] = []  # (the original's time, the replay's time) of each event

    def replayed(ts: float) -> float:
        # a moment of the original run on the replay's clock, so the copied chat sorts among the replayed events
        i = bisect.bisect_right([o for o, _ in clock], ts) - 1
        if i < 0:
            return (clock[0][1] - min(max(clock[0][0] - ts, 0) / speed, 2.5)) if clock else now()
        return clock[i][1] + min(max(ts - clock[i][0], 0) / speed, 2.5)

    try:
        for r in rows:
            await asyncio.sleep(min(max(r["ts"] - prev_ts, 0) / speed, 2.5))
            prev_ts = r["ts"]
            clock.append((r["ts"], now()))
            if r["type"] in REPLAY_SKIP:
                continue
            if r["type"] == "program.updated":
                v = r["data"].get("version")
                prog = await db.one("SELECT * FROM programs WHERE project_id = ? AND version = ?", src_id, v)
                if prog and not await db.one("SELECT 1 AS x FROM programs WHERE project_id = ? AND version = ?", dst_id, v):
                    await db.insert("programs", {**{k: prog[k] for k in ("version", "source", "params", "inputs", "summary", "checks", "author")},
                                                 "project_id": dst_id, "created_at": now()})
                    await db.update("projects", "id", dst_id, {"version": v, "updated_at": now()})
            # boards and device graphs come along as their events come up, so the replay's tabs fill as the original's did
            if r["type"] == "pcb.version" and r["data"].get("version"):
                from . import pcb_store

                if not await pcb_store.get(dst_id, int(r["data"]["version"])):
                    await pcb_store.copy(src_id, int(r["data"]["version"]), dst_id)
            if r["type"] == "device.version" and r["data"].get("version"):
                from . import device_store

                await device_store.copy_one(src_id, int(r["data"]["version"]), dst_id)
            await events.emit(dst_id, r["type"], {**r["data"], "replay": True}, r["job_id"])
        for m in await db.all("SELECT * FROM messages WHERE project_id = ? ORDER BY created_at", src_id):
            await db.insert("messages", {"id": new_id("msg_"), "project_id": dst_id, "role": m["role"], "text": m["text"], "data": m["data"],
                                         "created_at": replayed(m["created_at"])})
    finally:
        await db.update("projects", "id", dst_id, {"status": "idle", "updated_at": now()})


@app.post("/api/projects/{project_id}/replay")
async def replay(project_id: str, speed: float = 4.0, user=Depends(current_user)):
    """A copy of a public (or own) project whose timeline plays back the original agent run."""
    src = await load_project(project_id, user)
    db = await get_db()
    pid = new_id("p_")
    t = now()
    await db.insert("projects", {"id": pid, "user_id": user["id"], "title": src["title"], "pack": src["pack"], "replay_of": project_id,
                                 "status": "working", "cover": src["cover"], "created_at": t, "updated_at": t})
    asyncio.create_task(_replay(project_id, pid, max(1.0, min(speed, 20.0))))
    return project_out(await db.one("SELECT * FROM projects WHERE id = ?", pid))  # type: ignore[arg-type]


@app.post("/api/projects/{project_id}/fork")
async def fork_project(project_id: str, user=Depends(current_user)):
    src = await load_project(project_id, user)
    prog = await latest_program(project_id)
    db = await get_db()
    pid = new_id("p_")
    t = now()
    await db.insert("projects", {"id": pid, "user_id": user["id"], "title": f"{src['title']} (remix)", "pack": src["pack"], "forked_from": project_id,
                                 "version": 1 if prog else 0, "cover": src["cover"], "created_at": t, "updated_at": t})
    if prog:
        await db.insert("programs", {"project_id": pid, "version": 1, "source": prog["source"], "params": prog["params"], "inputs": prog["inputs"],
                                     "summary": prog["summary"], "checks": prog["checks"], "author": "fork", "created_at": t})
    # a device keeps its graph and its boards (same numbers, so the case still names the board it was made for)
    from . import device_store, pcb_store

    if src["pack"] in ("device", "pcb"):
        await device_store.copy_all(project_id, pid)
        for v in await pcb_store.versions(project_id):
            await pcb_store.copy(project_id, int(v["version"]), pid)
    return project_out(await db.one("SELECT * FROM projects WHERE id = ?", pid))  # type: ignore[arg-type]


# ------------------------------------------------------------------ assets & selection
ASSET_LIMIT = 60 * 1024 * 1024
SNAP_LIMIT = 30 * 1024 * 1024


class BodyLimit:
    """Refuses a body larger than any endpoint accepts by its Content-Length, before the multipart form is parsed."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            length = dict(scope["headers"]).get(b"content-length", b"")
            if length.isdigit() and int(length) > ASSET_LIMIT + 1024 * 1024:
                await error_response(413, "file too large (60 MB max)", "too_large")(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(BodyLimit)


def public_base() -> str | None:
    """FW_PUBLIC_URL without the trailing slash, when other devices can reach it (not a localhost address)."""
    url = settings().public_url.rstrip("/")
    host = urlsplit(url).hostname or ""
    return None if not host or host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost") else url


@app.post("/api/projects/{project_id}/capture-token")
async def capture_token(project_id: str, user=Depends(current_user)):
    """Short-lived token so a phone (another session) can add photos to this project via QR."""
    await load_project(project_id, user, write=True)
    db = await get_db()
    token = secrets.token_urlsafe(18)
    await db.execute("DELETE FROM captures WHERE expires_at < ?", now())
    await db.insert("captures", {"token": token, "project_id": project_id, "expires_at": now() + 3600})
    # absolute when the app has a public address: the QR code then works from any phone, not only on this network
    return {"token": token, "url": f"{public_base() or ''}/c/{project_id}?t={token}"}


async def _capture_allowed(request: Request, project_id: str) -> bool:
    token = request.headers.get("x-fw-capture") or request.query_params.get("capture")
    if not token:
        return False
    db = await get_db()
    row = await db.one("SELECT * FROM captures WHERE token = ? AND project_id = ? AND expires_at > ?", token, project_id, now())
    return row is not None


@app.post("/api/projects/{project_id}/assets")
async def upload_asset(project_id: str, request: Request, file: UploadFile = File(...), kind: str = Form("photo"), user=Depends(current_user)):
    phone = await _capture_allowed(request, project_id)
    if not phone:
        await load_project(project_id, user, write=True)
    data = await file.read(ASSET_LIMIT + 1)
    if len(data) > ASSET_LIMIT:
        raise HTTPException(413, "file too large (60 MB max)")
    from .vision import ingest

    try:
        asset = await ingest.ingest_asset(project_id, kind, file.filename or "upload", data, file.content_type or "")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if phone:
        # sent from the QR page: the studio on the desktop puts it straight into the message being written
        asset["meta"] = {**asset["meta"], "via": "phone"}
        db = await get_db()
        await db.update("assets", "id", asset["id"], {"meta": asset["meta"]})
    await events.emit(project_id, "asset.added", asset_out(asset))
    return asset_out(asset)


@app.post("/api/projects/{project_id}/assets/{asset_id}/detect")
async def detect_objects(project_id: str, asset_id: str, user=Depends(current_user)):
    await load_project(project_id, user, write=True)
    from .vision import scene

    db = await get_db()
    asset = await db.one("SELECT * FROM assets WHERE id = ? AND project_id = ?", asset_id, project_id)
    if not asset:
        raise HTTPException(404, "asset not found")
    try:
        return await scene.detect(user, asset)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/projects/{project_id}/assets/{asset_id}/select")
async def select_object(project_id: str, asset_id: str, body: SelectRequest, user=Depends(current_user)):
    await load_project(project_id, user, write=True)
    from .vision import scene

    db = await get_db()
    asset = await db.one("SELECT * FROM assets WHERE id = ? AND project_id = ?", asset_id, project_id)
    if not asset:
        raise HTTPException(404, "asset not found")
    body.by = "user"
    try:
        sel = await scene.select(user, project_id, asset, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    for sid in sel.get("replaced") or []:
        await events.emit(project_id, "selection.removed", {"id": sid})
    out = selection_out(sel)
    await events.emit(project_id, "selection.added", out)
    return out


@app.post("/api/projects/{project_id}/assets/{asset_id}/spot")
async def spot_object(project_id: str, asset_id: str, body: SpotRequest, user=Depends(current_user)):
    """The object on a freshly uploaded photo, cut out before the agent starts (the person may correct it)."""
    await load_project(project_id, user, write=True)
    from .vision import spot

    db = await get_db()
    asset = await db.one("SELECT * FROM assets WHERE id = ? AND project_id = ?", asset_id, project_id)
    if not asset:
        raise HTTPException(404, "asset not found")
    try:
        r = await asyncio.shield(spot.start(user, project_id, asset, body.hint, body.lang))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    out = selection_out(r["selection"]) if r["selection"] else None
    for sid in (r["selection"] or {}).get("replaced") or []:
        await events.emit(project_id, "selection.removed", {"id": sid})
    if out:
        await events.emit(project_id, "selection.added", out)
    return {"selection": out, "label": r["label"], "objects": r["objects"]}


@app.delete("/api/projects/{project_id}/selections/{selection_id}")
async def delete_selection(project_id: str, selection_id: str, user=Depends(current_user)):
    await load_project(project_id, user, write=True)
    db = await get_db()
    await db.execute("DELETE FROM selections WHERE id = ? AND project_id = ?", selection_id, project_id)
    await events.emit(project_id, "selection.removed", {"id": selection_id})
    return {"ok": True}


# ------------------------------------------------------------------ agent
@app.post("/api/projects/{project_id}/messages")
async def send_message(project_id: str, body: SendMessage, user=Depends(current_user)):
    p = await load_project(project_id, user, write=True)
    from .agent.runner import start_design_job

    # `shown` is for the server's own callers (a shop order's brief): from the browser, the words shown are the words sent
    body = body.model_copy(update={"shown": None})
    # quotas.QuotaExceeded becomes a 429 with its code (quota_error below)
    return {"job_id": await start_design_job(user, p, body)}


@app.post("/api/jobs/{job_id}/answer")
async def answer(job_id: str, body: AnswerRequest, user=Depends(current_user)):
    from .agent.runner import deliver_answer

    if not await deliver_answer(job_id, user["id"], body.answer):
        raise HTTPException(404, "no question is waiting")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str, user=Depends(current_user)):
    from .agent.runner import cancel_job

    if not await cancel_job(job_id, user["id"]):
        # already over, unknown or someone else's: a 404 tells the client to drop its stale job id
        raise HTTPException(404, "no running job to stop")
    return {"ok": True}


@app.get("/api/projects/{project_id}/events")
async def stream_events(project_id: str, request: Request, after: int = 0, user=Depends(current_user)):
    await load_project(project_id, user)
    last = int(request.headers.get("last-event-id", after) or after)

    async def gen():
        nonlocal last
        yield "retry: 2000\n\n"
        while True:
            if await request.is_disconnected():
                return
            rows = await events.since(project_id, last)
            for r in rows:
                last = r["seq"]
                yield f"id: {r['seq']}\nevent: {r['type']}\ndata: {json.dumps({**r, 'data': r['data']}, ensure_ascii=False)}\n\n"
            if not rows:
                await events.wait(project_id, 15)
                yield ": ping\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ program
@app.get("/api/projects/{project_id}/program/{version}")
async def get_program(project_id: str, version: int, user=Depends(current_user)):
    await load_project(project_id, user)
    db = await get_db()
    prog = await db.one("SELECT * FROM programs WHERE project_id = ? AND version = ?", project_id, version)
    if not prog:
        raise HTTPException(404, "no such version")
    return prog


@app.get("/api/projects/{project_id}/versions")
async def versions(project_id: str, user=Depends(current_user)):
    await load_project(project_id, user)
    db = await get_db()
    return await db.all("SELECT version, summary, author, created_at FROM programs WHERE project_id = ? ORDER BY version", project_id)


USER_EDIT_WINDOW_S = 30 * 60


def _client_checks(checks: dict[str, Any] | None) -> dict[str, Any] | None:
    """The browser's report is informational (the agent and export rebuild on their own); keep it small."""
    if not isinstance(checks, dict) or len(json.dumps(checks)) > 300_000:
        return None
    return {**checks, "by": "client"}


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    if len(params) > 300:
        raise HTTPException(400, "too many parameters")
    out = {}
    for k, v in params.items():
        if not isinstance(k, str) or len(k) > 64 or not isinstance(v, (int, float, str, bool)) or (isinstance(v, str) and len(v) > 200):
            raise HTTPException(400, f"bad parameter {k!r}")
        out[k] = v
    return out


async def _save_user_version(project_id: str, prog: dict[str, Any], source: str, params: dict[str, Any], checks: dict[str, Any] | None,
                             summary: str, client: str | None) -> int:
    """User edits in one sitting update one version instead of adding one per slider release."""
    db = await get_db()
    t = now()
    if prog["author"] == "user" and prog["summary"] == summary and t - prog["created_at"] < USER_EDIT_WINDOW_S:
        version = prog["version"]
        await db.execute("UPDATE programs SET source = ?, params = ?, checks = ? WHERE project_id = ? AND version = ?",
                         source, params, checks, project_id, version)
    else:
        for attempt in range(3):
            # an agent step may commit a version at the same moment: take the next free number at the last moment
            version = (await db.one("SELECT COALESCE(MAX(version), 0) AS v FROM programs WHERE project_id = ?", project_id))["v"] + 1  # type: ignore[index]
            try:
                await db.insert("programs", {"project_id": project_id, "version": version, "source": source, "params": params,
                                             "inputs": prog["inputs"], "summary": summary, "checks": checks, "author": "user", "created_at": t})
                break
            except sqlite3.IntegrityError:
                if attempt == 2:
                    raise
    await db.update("projects", "id", project_id, {"version": version, "updated_at": t})
    event: dict[str, Any] = {"version": version, "params": params, "checks": checks, "author": "user", "client": client}
    if source != prog["source"]:
        event["source_changed"] = True
    await events.emit(project_id, "program.updated", event)
    return version


@app.put("/api/projects/{project_id}/params")
async def save_params(project_id: str, body: ParamsUpdate, user=Depends(current_user)):
    """Slider changes. The browser built and checked the model already, so nothing is rebuilt here:
    the agent's next step, export and slicing build the stored version themselves."""
    await load_project(project_id, user, write=True)
    prog = await latest_program(project_id)
    if not prog:
        raise HTTPException(400, "no program yet")
    params = _clean_params(body.params)
    version = await _save_user_version(project_id, prog, prog["source"], params, _client_checks(body.checks), "parameters changed", body.client)
    return {"version": version, "params": params}


@app.put("/api/projects/{project_id}/program")
async def save_program(project_id: str, body: ProgramUpdate, user=Depends(current_user)):
    """A program edited in the studio (operations of a mesh document, strokes sculpted by hand)."""
    await load_project(project_id, user, write=True)
    prog = await latest_program(project_id)
    if not prog:
        raise HTTPException(400, "no program yet")
    params = _clean_params(body.params)
    version = await _save_user_version(project_id, prog, body.source, params, _client_checks(body.checks), body.summary, body.client)
    return {"version": version, "params": params}


@app.post("/api/projects/{project_id}/export")
async def export(project_id: str, body: ExportRequest, user=Depends(current_user)):
    p = await load_project(project_id, user)
    prog = await latest_program(project_id)
    if not prog:
        raise HTTPException(400, "no program yet")
    try:
        out = await geom().export(prog["source"], body.params or prog["params"], body.format, inputs=prog["inputs"], title=p["title"])
    except GeomError as e:
        raise HTTPException(422, e.message) from e
    data = base64.b64decode(out["data"])
    name = "".join(c if c.isalnum() else "_" for c in p["title"])[:40] or "model"
    # headers are latin-1: the title (often Cyrillic) goes in the RFC 5987 form, with a plain fallback
    disposition = f"attachment; filename=\"model.{body.format}\"; filename*=UTF-8''{quote(name, safe='')}.{body.format}"
    return Response(data, media_type=out["mime"], headers={"Content-Disposition": disposition})


@app.post("/api/projects/{project_id}/render")
async def render_now(project_id: str, body: dict[str, Any], user=Depends(current_user)):
    await load_project(project_id, user)
    prog = await latest_program(project_id)
    if not prog:
        raise HTTPException(400, "no program yet")
    out = await geom().render(prog["source"], body.get("params") or prog["params"], view=body.get("view", "iso"), heat=bool(body.get("heat")), inputs=prog["inputs"])
    return Response(base64.b64decode(out["png"]), media_type="image/png")


# ------------------------------------------------------------------ printing
@app.get("/api/printers")
async def printers():
    from .printing import service

    return service.list_printers()


@app.get("/api/printers/coupon.3mf")
async def fingerprint_coupon():
    """Calibration coupon: print it, photograph it on an A4 sheet, POST the photo to /fingerprint."""
    from .printing import fingerprint

    out = await geom().export(fingerprint.coupon_source(), {}, "3mf", title="Formwright printer fingerprint")
    return Response(base64.b64decode(out["data"]), media_type=out["mime"], headers={"Content-Disposition": 'attachment; filename="fingerprint_coupon.3mf"'})


@app.post("/api/printers/{printer_id}/fingerprint")
async def measure_fingerprint(printer_id: str, body: dict[str, str], user=Depends(current_user)):
    from .llm.client import CostMeter
    from .printing import fingerprint

    db = await get_db()
    asset = await db.one("SELECT a.* FROM assets a JOIN projects p ON p.id = a.project_id WHERE a.id = ? AND p.user_id = ?", body.get("asset_id"), user["id"])
    if not asset:
        raise HTTPException(404, "asset not found")
    # a few model calls, not a job: it may run next to a design job and does not count as one
    await quotas.check_light(user, 0.05)
    meter = CostMeter(budget_usd=0.05)
    try:
        fp = await fingerprint.measure(meter, user, asset)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        await quotas.settle(user["id"], meter.usd, is_job=False)
    await fingerprint.save(user["id"], printer_id, fp)
    return fp


@app.post("/api/projects/{project_id}/slice")
async def slice_project(project_id: str, body: SliceRequest, user=Depends(current_user)):
    p = await load_project(project_id, user, write=True)
    from .agent.runner import start_side_job

    return {"job_id": await start_side_job(user, p, "slice", body.model_dump())}


@app.post("/api/projects/{project_id}/probe")
async def probe(project_id: str, body: dict[str, Any], user=Depends(current_user)):
    p = await load_project(project_id, user, write=True)
    from .agent.runner import start_side_job

    return {"job_id": await start_side_job(user, p, "probe", body)}


@app.post("/api/projects/{project_id}/concepts")
async def concepts(project_id: str, body: ConceptRequest, user=Depends(current_user)):
    p = await load_project(project_id, user, write=True)
    from .agent.runner import start_side_job

    return {"job_id": await start_side_job(user, p, "concepts", body.model_dump())}


@app.post("/api/projects/{project_id}/breed")
async def breed(project_id: str, body: BreedRequest, user=Depends(current_user)):
    p = await load_project(project_id, user, write=True)
    from .agent.runner import start_side_job

    return {"job_id": await start_side_job(user, p, "breed", body.model_dump())}


@app.post("/api/projects/{project_id}/visual-edit")
async def visual_edit(project_id: str, body: VisualEditRequest, user=Depends(current_user)):
    p = await load_project(project_id, user, write=True)
    from .agent.runner import start_side_job

    return {"job_id": await start_side_job(user, p, "visual_edit", body.model_dump())}


@app.post("/api/projects/{project_id}/order")
async def order(project_id: str, body: OrderRequest, user=Depends(current_user)):
    p = await load_project(project_id, user, write=True)
    from .integrations import axo

    return await axo.create_order(user, p, body)


# ------------------------------------------------------------------ memory
@app.get("/api/memory")
async def my_memory(user=Depends(current_user)):
    db = await get_db()
    mine = await db.all("SELECT id, kind, name, tags, status, uses, successes, body FROM memory WHERE user_id = ? AND status != 'archived' ORDER BY last_used DESC", user["id"])
    skills = await db.all("SELECT id, kind, name, tags, status, uses, successes FROM memory WHERE scope = 'global' AND status = 'active' ORDER BY successes DESC LIMIT 100")
    return {"mine": mine, "global": skills}


@app.delete("/api/memory/{item_id}")
async def forget(item_id: str, user=Depends(current_user)):
    db = await get_db()
    await db.execute("DELETE FROM memory WHERE id = ? AND user_id = ?", item_id, user["id"])
    return {"ok": True}


# ------------------------------------------------------------------ snap & collect
class SnapReselect(BaseModel):
    points: list[Point] = []
    box: list[float] | None = None
    label: str | None = None


class SnapConfirm(BaseModel):
    text: str
    label: str | None = None
    model: Literal["contributor", "spark", "wonder", "spark_open"] | None = None
    reasoning: Literal["minimal", "low", "medium", "high", "xhigh", "max"] = "medium"


async def _snap_project(project_id: str, user: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from .vision import snap

    p = await load_project(project_id, user, write=True)
    db = await get_db()
    asset = await db.one("SELECT * FROM assets WHERE id = ? AND project_id = ?", snap.snap_asset_id(p) or "", project_id)
    if p["pack"] != "collect" or not asset:
        raise HTTPException(400, "not a snap project")
    return p, asset


@app.post("/api/snap")
async def snap_photo(file: UploadFile = File(...), x: float | None = Form(None), y: float | None = Form(None), lang: str = Form("en"),
                     user=Depends(current_user)):
    """Phone camera shot of an object out in the world: a new collectible project with the tapped object selected and named."""
    from .vision import ingest, snap

    data = await file.read(SNAP_LIMIT + 1)
    if len(data) > SNAP_LIMIT:
        raise HTTPException(413, "photo too large (30 MB max)")
    db = await get_db()
    pid = new_id("p_")
    t = now()
    await db.insert("projects", {"id": pid, "user_id": user["id"], "title": "New project", "pack": "collect",
                                 "brief": {"collect": True, "photo_role": "copy", "language": lang[:2]}, "created_at": t, "updated_at": t})
    try:
        asset = await ingest.ingest_asset(pid, "photo", file.filename or "snap.jpg", data, file.content_type or "image/jpeg")
    except ValueError as e:
        await _drop_snap(pid)
        raise HTTPException(400, str(e)) from e
    except quotas.QuotaExceeded:
        await _drop_snap(pid)  # the face blur hit today's limit: no empty draft is left behind
        raise
    p = await db.one("SELECT * FROM projects WHERE id = ?", pid)
    try:
        r = await snap.snap(user, p, asset, x, y, lang)  # type: ignore[arg-type]
    except quotas.QuotaExceeded:
        await _drop_snap(pid)
        raise
    await events.emit(pid, "asset.added", asset_out(asset))
    if r["selection"]:
        await events.emit(pid, "selection.added", selection_out(r["selection"]))
    return {"project": project_out(await db.one("SELECT * FROM projects WHERE id = ?", pid)), "asset": asset_out(asset),  # type: ignore[arg-type]
            "selection": selection_out(r["selection"]) if r["selection"] else None, "label": r["label"], "objects": r["objects"],
            "sticker": r.get("sticker")}


@app.get("/api/snap/{project_id}/name")
async def snap_name(project_id: str, user=Depends(current_user)):
    """What the snapped object is, and other objects on the photo (arrives after the highlight)."""
    from .vision import snap

    p, _ = await _snap_project(project_id, user)
    r = await snap.named(p, (p["brief"] or {}).get("language", "en"))
    for sid in r.get("removed") or []:
        await events.emit(project_id, "selection.removed", {"id": sid})
    if r.get("removed"):
        await events.emit(project_id, "selection.added", selection_out(r["selection"]))
    return {"label": r["label"], "objects": r["objects"], "selection": selection_out(r["selection"]) if r.get("selection") else None}


@app.post("/api/snap/{project_id}/select")
async def snap_reselect(project_id: str, body: SnapReselect, user=Depends(current_user)):
    from .vision import snap

    p, asset = await _snap_project(project_id, user)
    try:
        r = await snap.reselect(user, p, asset, [pt.model_dump() for pt in body.points], body.box, body.label)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    for sid in r["removed"]:
        await events.emit(project_id, "selection.removed", {"id": sid})
    out = selection_out(r["selection"])
    await events.emit(project_id, "selection.added", out)
    return {"selection": out, "label": r["label"]}


@app.post("/api/snap/{project_id}/confirm")
async def snap_confirm(project_id: str, body: SnapConfirm, user=Depends(current_user)):
    """Start modelling now, or queue it behind the job that is still running."""
    from .vision import snap

    p, asset = await _snap_project(project_id, user)
    label = (body.label or "").strip()[:40]
    if label and label != (p["brief"] or {}).get("subject"):
        db = await get_db()
        p["brief"] = {**(p["brief"] or {}), "subject": label}
        p["title"] = label[:1].upper() + label[1:]
        await db.update("projects", "id", project_id, {"brief": p["brief"], "title": p["title"], "updated_at": now()})
    msg = SendMessage(text=body.text.strip()[:2000] or label, asset_ids=[asset["id"]], model=body.model, reasoning=body.reasoning)
    return await snap.start_or_queue(user, p, msg)


@app.delete("/api/snap/{project_id}")
async def snap_discard(project_id: str, user=Depends(current_user)):
    """Retake: a snap that never reached the agent leaves nothing behind."""
    p, _ = await _snap_project(project_id, user)
    db = await get_db()
    if p["version"] or await db.one("SELECT id FROM jobs WHERE project_id = ? LIMIT 1", project_id):
        raise HTTPException(400, "this snap is already being modelled")
    await _drop_snap(project_id)
    return {"ok": True}


async def _drop_snap(project_id: str) -> None:
    """Removes a snap draft with its rows and files (Retake, or a snap that failed before anyone saw it)."""
    db = await get_db()
    for table in ("selections", "assets", "events", "messages"):
        await db.execute(f"DELETE FROM {table} WHERE project_id = ?", project_id)
    await db.execute("DELETE FROM projects WHERE id = ?", project_id)
    shutil.rmtree(settings().data_dir / "files" / project_id, ignore_errors=True)


@app.get("/api/collection")
async def collection(user=Depends(current_user)):
    """The person's collected objects, newest first, with what each one is waiting for."""
    from .vision import snap

    db = await get_db()
    rows = await db.all("SELECT * FROM projects WHERE user_id = ? AND pack = 'collect' ORDER BY created_at DESC LIMIT 200", user["id"])
    items = []
    for p in rows:
        brief = p["brief"] or {}
        if brief.get("plate"):
            continue  # a print plate made from collected objects (collect.py), not one of them
        job = await db.one("SELECT status FROM jobs WHERE project_id = ? AND kind = 'design' ORDER BY created_at DESC LIMIT 1", p["id"])
        asset = await db.one("SELECT * FROM assets WHERE id = ?", snap.snap_asset_id(p) or "")
        sel = await db.one("SELECT mask_path, data FROM selections WHERE project_id = ? AND asset_id = ? AND role = 'target' ORDER BY created_at DESC LIMIT 1",
                           p["id"], (asset or {}).get("id", ""))
        if job and job["status"] in ("running", "waiting"):
            state = "modelling"
        elif brief.get("queued"):
            state = "queued"
        elif p["version"]:
            state = "ready"
        elif job or brief.get("queue_error"):
            state = "failed"
        else:
            state = "draft"
        items.append({
            "id": p["id"], "title": p["title"], "subject": brief.get("subject"), "cover": file_url(p["cover"]), "state": state,
            "version": p["version"], "created_at": p["created_at"], "updated_at": p["updated_at"], "error": brief.get("queue_error"),
            "photo": file_url((asset or {}).get("meta", {}).get("thumb") or (asset or {}).get("path")),
            "width": (asset or {}).get("width"), "height": (asset or {}).get("height"),
            "mask_url": file_url((sel or {}).get("mask_path")), "bbox": ((sel or {}).get("data") or {}).get("bbox_px"),
        })
    if any(i["state"] == "queued" for i in items):
        snap.ensure_drain(user["id"])  # the queue lives in memory; a restart picks it up here
    return items


# ------------------------------------------------------------------ feature routers
# Each module exports `router` (an APIRouter) and reaches this file lazily (`from formwright import app as _app`, then
# _app.current_user and _app.load_project). Mounted here, before the SPA catch-all, so /api/... never falls through
# to index.html. A module that is missing or fails to import is logged and skipped: the rest of the API still starts.
ROUTERS = ("formwright.shop.routes", "formwright.pcbapi", "formwright.deviceapi", "formwright.collect")


def include_routers(target: FastAPI, names: tuple[str, ...] = ROUTERS) -> list[str]:
    mounted = []
    for name in names:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as e:
            if e.name and name.startswith(e.name):
                log.error("feature router %s is not there, skipped", name)
            else:
                log.exception("feature router %s failed to import, skipped", name)
            continue
        except Exception:  # noqa: BLE001 - one broken feature must not take the whole API down
            log.exception("feature router %s failed to import, skipped", name)
            continue
        router = getattr(module, "router", None)
        if router is None:
            log.error("feature module %s has no `router`, skipped", name)
            continue
        target.include_router(router)
        mounted.append(name)
    return mounted


include_routers(app)


# ------------------------------------------------------------------ web app
WEB_BUILD = REPO_DIR / "web" / "build"
if settings().web_dev_port:
    # vite runs next to the API: a page opened on this port goes to the live app, not to an old web/build
    @app.get("/{path:path}", include_in_schema=False)
    async def spa_dev(path: str, request: Request):
        if path.startswith(("api/", "files/")):
            raise HTTPException(404)  # vite proxies these here, sending them back would loop
        return RedirectResponse(str(request.url.replace(port=settings().web_dev_port)), status_code=307)

elif WEB_BUILD.exists():
    app.mount("/_app", StaticFiles(directory=WEB_BUILD / "_app"), name="web-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request):
        if path.startswith(("api/", "files/")):
            raise HTTPException(404)
        root = WEB_BUILD.resolve()
        target = _spa_file(root, path)
        if target != root / "index.html":
            return FileResponse(target)
        return HTMLResponse(await share_page(_index_html(), path, public_base() or str(request.base_url).rstrip("/")))


def _spa_file(root: Path, path: str) -> Path:
    """The build file a path names, or index.html: %2e%2e, backslashes and absolute paths never leave the build folder."""
    index = root / "index.html"
    if not path:
        return index
    try:
        target = (root / path).resolve()
    except (OSError, ValueError):
        return index
    return target if target.is_relative_to(root) and target.is_file() else index


_index: dict[str, Any] = {}


def _index_html() -> str:
    """The built index.html, read again only when a new build replaces it."""
    path = WEB_BUILD / "index.html"
    stamp = path.stat().st_mtime_ns
    if _index.get("stamp") != stamp:
        _index.update(stamp=stamp, html=path.read_text(encoding="utf-8"))
    return _index["html"]


def _set_meta(page: str, key: str, value: str) -> str:
    """Fill one <meta property|name="key" content="..."> tag of app.html."""
    return re.sub(rf'(<meta (?:property|name)="{re.escape(key)}" content=")[^"]*"', lambda m: f'{m.group(1)}{escape(value)}"', page, count=1)


async def share_page(page: str, path: str, base: str) -> str:
    """Link previews (X, chats) read the meta tags without running the app: the image has to be absolute, and a
    shared public project (/r/<id>, /p/<id>) shows its own title, summary and cover."""
    page = _set_meta(page, "og:image", f"{base}/og.png")
    m = re.fullmatch(r"[rp]/([\w-]+)/?", path)
    if not m:
        return page
    db = await get_db()
    p = await db.one("SELECT title, cover, brief FROM projects WHERE id = ? AND public = 1", m.group(1))
    if not p:
        return page
    page = _set_meta(page, "og:title", p["title"])
    page = page.replace("<title>Formwright</title>", f"<title>{escape(p['title'])} · Formwright</title>", 1)
    summary = str((p["brief"] or {}).get("summary") or "").strip()[:200]
    if summary:
        page = _set_meta(_set_meta(page, "og:description", summary), "description", summary)
    if p["cover"]:
        page = _set_meta(page, "og:image", base + quote(file_url(p["cover"]) or ""))
    return page


# ------------------------------------------------------------------ errors
# every error is JSON {detail, code, ...}: the web app turns the code into a localized next step
HTTP_CODES = {400: "bad_request", 403: "forbidden", 404: "not_found", 405: "not_allowed", 409: "conflict", 413: "too_large", 422: "invalid", 429: "quota"}


def error_response(status: int, detail: Any, code: str, headers: dict[str, str] | None = None, **info: Any) -> JSONResponse:
    return JSONResponse({"detail": detail, "code": code, **info}, status_code=status, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and isinstance(exc.detail.get("code"), str):
        # HTTPException(409, {"detail": ..., "code": "order_guard"}) from a feature router: its own code, not the status's
        info = {k: v for k, v in exc.detail.items() if k not in ("detail", "code")}
        return error_response(exc.status_code, exc.detail.get("detail"), exc.detail["code"], headers=getattr(exc, "headers", None), **info)
    return error_response(exc.status_code, exc.detail, HTTP_CODES.get(exc.status_code, "error"), headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, exc: RequestValidationError):
    return error_response(422, jsonable_encoder(exc.errors()), "invalid")


@app.exception_handler(GeomError)
async def geom_error(_: Request, exc: GeomError):
    return error_response(422, exc.message, "geom", stage=exc.stage)


@app.exception_handler(quotas.QuotaExceeded)
async def quota_error(_: Request, exc: quotas.QuotaExceeded):
    # code and info (e.g. the blocking job's project_id and job_id for 'job_running') come from quotas.reserve
    return error_response(429, str(exc), getattr(exc, "code", "quota"), **getattr(exc, "info", {}))


@app.exception_handler(BudgetExceeded)
async def budget_error(_: Request, exc: BudgetExceeded):
    return error_response(429, str(exc), "budget")


async def model_busy(request: Request, exc: Exception):
    log.warning("model service error on %s %s: %s: %s", request.method, request.url.path, type(exc).__name__, exc)
    return error_response(503, "the model service is busy or unreachable; try again in a minute", "model_busy")


for _exc in (APIStatusError, APIConnectionError, APITimeoutError, httpx.HTTPError):
    app.add_exception_handler(_exc, model_busy)


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception):
    eid = new_id("e_")
    log.error("internal error %s on %s %s", eid, request.method, request.url.path, exc_info=exc)
    return error_response(500, "internal error", "internal", id=eid)
