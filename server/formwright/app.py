"""HTTP API. Run: uvicorn formwright.app:app --port 8000 (from server/)."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import events, quotas
from .config import REPO_DIR, settings
from .db import close_db, get_db, new_id, now
from .geom import GeomError, geom
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
    ProgramOut,
    ProjectDetail,
    ProjectOut,
    SelectionOut,
    SelectRequest,
    SendMessage,
    SliceRequest,
    Usage,
    VisualEditRequest,
)

log = logging.getLogger("formwright")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await get_db()
    bot = None
    if settings().telegram_token:
        from .integrations.telegram import run_bot

        bot = asyncio.create_task(run_bot())
    yield
    if bot:
        bot.cancel()
    await geom().close()
    await close_db()


app = FastAPI(title="Formwright", lifespan=lifespan)
FILES = settings().data_dir / "files"
app.mount("/files", StaticFiles(directory=FILES), name="files")


def file_url(path: str | None) -> str | None:
    return f"/files/{path}" if path else None


# ------------------------------------------------------------------ session
async def current_user(request: Request, response: Response) -> dict[str, Any]:
    db = await get_db()
    uid = request.cookies.get("fw_uid")
    user = await db.one("SELECT * FROM users WHERE id = ?", uid) if uid else None
    if not user:
        uid = new_id("u_")
        await db.insert("users", {"id": uid, "tier": "anon", "created_at": now()})
        user = await db.one("SELECT * FROM users WHERE id = ?", uid)
        response.set_cookie("fw_uid", uid, httponly=True, samesite="lax", max_age=3600 * 24 * 365)
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


@app.get("/api/login/{token}")
async def magic_login(token: str, next: str = "/"):
    """One-time link (e.g. from the Telegram bot) that signs this browser in as that user."""
    db = await get_db()
    row = await db.one("SELECT * FROM logins WHERE token = ? AND expires_at > ?", token, now())
    if not row:
        raise HTTPException(404, "link expired")
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie("fw_uid", row["user_id"], httponly=True, samesite="lax", max_age=3600 * 24 * 365)
    return resp


@app.get("/api/me")
async def me(user=Depends(current_user)) -> Usage:
    usd, jobs = await quotas.spent_today(user["id"])
    limit = quotas.TIERS.get(user["tier"], quotas.TIERS["anon"])[0]
    return Usage(user_id=user["id"], tier=user["tier"], today_usd=round(usd, 4), limit_usd=limit, jobs_today=jobs, contributor_consent=bool(user["contributor_consent"]))


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
    rows = await db.all("SELECT * FROM projects WHERE public = 1 ORDER BY updated_at DESC LIMIT 60")
    return [project_out(p) for p in rows]


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
    return project_out(await db.one("SELECT * FROM projects WHERE id = ?", pid))  # type: ignore[arg-type]


# ------------------------------------------------------------------ assets & selection
@app.post("/api/projects/{project_id}/capture-token")
async def capture_token(project_id: str, user=Depends(current_user)):
    """Short-lived token so a phone (another session) can add photos to this project via QR."""
    await load_project(project_id, user, write=True)
    db = await get_db()
    token = secrets.token_urlsafe(18)
    await db.execute("DELETE FROM captures WHERE expires_at < ?", now())
    await db.insert("captures", {"token": token, "project_id": project_id, "expires_at": now() + 3600})
    return {"token": token, "url": f"/c/{project_id}?t={token}"}


async def _capture_allowed(request: Request, project_id: str) -> bool:
    token = request.headers.get("x-fw-capture") or request.query_params.get("capture")
    if not token:
        return False
    db = await get_db()
    row = await db.one("SELECT * FROM captures WHERE token = ? AND project_id = ? AND expires_at > ?", token, project_id, now())
    return row is not None


@app.post("/api/projects/{project_id}/assets")
async def upload_asset(project_id: str, request: Request, file: UploadFile = File(...), kind: str = Form("photo"), user=Depends(current_user)):
    if not await _capture_allowed(request, project_id):
        await load_project(project_id, user, write=True)
    data = await file.read()
    if len(data) > 60 * 1024 * 1024:
        raise HTTPException(413, "file too large (60 MB max)")
    from .vision import ingest

    try:
        asset = await ingest.ingest_asset(project_id, kind, file.filename or "upload", data, file.content_type or "")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
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
    try:
        sel = await scene.select(user, project_id, asset, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    out = selection_out(sel)
    await events.emit(project_id, "selection.added", out)
    return out


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

    try:
        job_id = await start_design_job(user, p, body)
    except quotas.QuotaExceeded as e:
        raise HTTPException(429, str(e)) from e
    return {"job_id": job_id}


@app.post("/api/jobs/{job_id}/answer")
async def answer(job_id: str, body: AnswerRequest, user=Depends(current_user)):
    from .agent.runner import deliver_answer

    if not await deliver_answer(job_id, user["id"], body.answer):
        raise HTTPException(404, "no question is waiting")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str, user=Depends(current_user)):
    from .agent.runner import cancel_job

    await cancel_job(job_id, user["id"])
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


@app.put("/api/projects/{project_id}/params")
async def save_params(project_id: str, body: ParamsUpdate, user=Depends(current_user)):
    """Slider changes: no LLM, just a new program version with other parameter values."""
    await load_project(project_id, user, write=True)
    prog = await latest_program(project_id)
    if not prog:
        raise HTTPException(400, "no program yet")
    db = await get_db()
    try:
        built = await geom().build(prog["source"], body.params, analyze="full", inputs=prog["inputs"])
    except GeomError as e:
        raise HTTPException(422, e.message) from e
    version = prog["version"] + 1
    await db.insert("programs", {"project_id": project_id, "version": version, "source": prog["source"], "params": built["params"],
                                 "inputs": prog["inputs"], "summary": "parameters changed", "checks": built.get("checks"), "author": "user", "created_at": now()})
    await db.update("projects", "id", project_id, {"version": version, "updated_at": now()})
    await events.emit(project_id, "program.updated", {"version": version, "params": built["params"], "checks": built.get("checks"), "author": "user"})
    return {"version": version, "checks": built.get("checks"), "params": built["params"]}


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
    return Response(data, media_type=out["mime"], headers={"Content-Disposition": f'attachment; filename="{name}.{body.format}"'})


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
    await quotas.reserve(user, 0.05)
    meter = CostMeter(budget_usd=0.05)
    try:
        fp = await fingerprint.measure(meter, user, asset)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        await quotas.settle(user["id"], meter.usd)
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


# ------------------------------------------------------------------ web app
WEB_BUILD = REPO_DIR / "web" / "build"
if WEB_BUILD.exists():
    app.mount("/_app", StaticFiles(directory=WEB_BUILD / "_app"), name="web-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        target = WEB_BUILD / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(WEB_BUILD / "index.html")


@app.exception_handler(GeomError)
async def geom_error(_: Request, exc: GeomError):
    return JSONResponse({"detail": exc.message, "stage": exc.stage}, status_code=422)
