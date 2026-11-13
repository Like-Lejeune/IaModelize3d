"""/api/shop: intake, quotes, orders, the farm operator's queue, QC, the parts catalog and repair-shop accounts.

Mounted by app.py through its ROUTERS registry, before the SPA catch-all. People come from app.current_user and
projects through app.load_project (imported lazily: app.py imports this module). Everything model- or slicer-shaped
goes through `hooks`, so tests (and a demo without keys) can swap them. Errors are JSON {detail, code}.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from formwright import idempotency, quotas
from formwright.db import Database, get_db, new_id, now

from . import autoquote, flow, notes, quote, store
from .intake import UNNAMED, title_for, title_fr, titles

log = logging.getLogger("formwright.shop")
router = APIRouter(prefix="/api/shop", tags=["shop"])

UPLOAD_LIMIT = 60 * 1024 * 1024
Delivery = Literal["pickup", "courier", "post"]


# ------------------------------------------------------------------ hooks (real wiring; tests override)
class Hooks:
    async def current_user(self, request: Request, response: Response) -> dict[str, Any]:
        from formwright import app as _app  # lazy: app.py includes this router

        return await _app.current_user(request, response)

    async def load_project(self, project_id: str, user: dict[str, Any], write: bool = False) -> dict[str, Any]:
        from formwright import app as _app

        return await _app.load_project(project_id, user, write)

    async def intake(self, user: dict, text: str, photos: list[dict]) -> dict[str, Any]:
        """Muse Spark 1.3 fills the intake schema (safety gate + rating plate); Spark Open classifies, never decides refuse."""
        from .intake import extract

        return await extract(user, text, photos)

    async def start_design(self, user: dict, project: dict, text: str, asset_ids: list[str], language: str | None = None,
                           shown: str | None = None) -> str:
        """`text` is the English design brief; `language` (the intake's) is the one the run speaks to the customer in,
        so a Russian customer's question from the designer comes in Russian; `shown` is the run's first message as the
        customer sees it (their own words: intake.shown_line), while the model reads the brief."""
        from formwright.agent.runner import start_design_job
        from formwright.models import SendMessage

        return await start_design_job(user, project, SendMessage(text=text, asset_ids=asset_ids, language=language, shown=shown))

    async def slice(self, project_id: str, version: int, printer_id: str | None, material: str, fingerprint: dict | None) -> dict[str, Any]:
        from formwright.printing import service

        db = await get_db()
        prog = await db.one("SELECT * FROM programs WHERE project_id = ? AND version = ?", project_id, version)
        p = await db.one("SELECT title, brief FROM projects WHERE id = ?", project_id)
        if not prog or not p:
            raise ValueError(f"no version {version} of {project_id}")
        return await service.slice(None, project_id=project_id, source=prog["source"], params=prog["params"], inputs=prog["inputs"],
                                   # the stored checks of that version: a fresh 'full' analysis is what made this slow
                                   title=p["title"], printer_id=printer_id, material=material, goals=[], checks=prog["checks"] or None,
                                   brief=p["brief"], model=None, use_llm=False, fingerprint=fingerprint)

    async def qc(self, user: dict, order: dict, data: bytes, filename: str, mime: str) -> dict[str, Any]:
        from .qc import check_print

        return await check_print(user, order, data, filename, mime)

    async def fingerprint(self, user: dict, asset: dict) -> dict[str, Any]:
        """The calibration coupon on A4 -> how this printer distorts holes and outlines (printing/fingerprint.py)."""
        from formwright.llm.client import CostMeter
        from formwright.printing import fingerprint

        await quotas.check_light(user, 0.05)
        meter = CostMeter(budget_usd=0.05)
        try:
            return await fingerprint.measure(meter, user, asset)
        finally:
            await quotas.settle(user["id"], meter.usd, is_job=False)

    async def answer(self, job_id: str, user_id: str, text: str) -> bool:
        from formwright.agent.runner import deliver_answer

        return await deliver_answer(job_id, user_id, text)

    async def cancel_job(self, job_id: str, user_id: str) -> bool:
        from formwright.agent.runner import cancel_job

        return await cancel_job(job_id, user_id)


hooks = Hooks()


async def user_dep(request: Request, response: Response) -> dict[str, Any]:
    return await hooks.current_user(request, response)


def _fail(status: int, detail: str, code: str) -> HTTPException:
    return HTTPException(status, {"detail": detail, "code": code})


def _err(e: flow.FlowError | autoquote.QuoteError) -> HTTPException:
    if isinstance(e, autoquote.QuoteError):
        return _fail(409, str(e), e.code)
    status = 409 if e.code in ("bad_move", "guard", "conflict") else 403 if e.code == "forbidden" else 404
    return _fail(status, str(e), f"order_{e.code}")


def file_url(path: str | None) -> str | None:
    return f"/files/{path}" if path else None


async def _order_for(user: dict, order_id: str, *, operator_ok: bool = True) -> tuple[Database, dict, str]:
    db = await store.shop_db()
    o = await store.get(db, order_id)
    if not o:
        raise HTTPException(404, "order not found")
    role, org = await store.role(db, user["id"])
    if role == "operator" and operator_ok:
        return db, o, "operator"
    if o["user_id"] == user["id"] or (org and o.get("org_id") == org):
        return db, o, "customer"
    raise HTTPException(403, "not your order")


def _viewer(o: dict[str, Any], user: dict[str, Any], actor: str, view: str | None = None) -> str:
    """Whom an answer is presented to: an operator's own order reads as the customer's (its order page is where they
    pay and confirm it), except on the farm's board (view='ops'), where the farm's moves are."""
    return "customer" if actor == "operator" and o["user_id"] == user["id"] and view != "ops" else actor


# what a customer reads when a QC photo could not be measured (the farm sees the measuring step's own words)
QC_ERRORS = {"not_found": "the part was not found in the photo", "model_unavailable": "the measuring model is unavailable; another photo follows",
             "no_sheet": "no A4 sheet or card in the photo, so the print cannot be measured in mm", "version_gone": "this version of the model is gone"}


def _skip(s: Any) -> dict[str, Any]:
    """A file the request could not use, as {code, file, kind?, error?}; older orders kept an English line."""
    if isinstance(s, dict):
        return s
    s = str(s)
    if s.startswith("voice note not transcribed"):
        return {"code": "voice_untranscribed", "file": "voice", "error": s.partition(": ")[2]}
    file, _, why = s.partition(": ")
    if why.endswith("is not read here; send photos"):
        return {"code": "not_photo", "file": file, "kind": why.removeprefix("a ").split(" ")[0]}
    return {"code": "unreadable", "file": file, "error": why}


def _intake_for(data: dict[str, Any], operator: bool) -> dict[str, Any]:
    """The intake as this viewer reads it: a customer gets the verdict and what was read, never an exception's text."""
    out = dict(data)
    req = out.get("request")
    if isinstance(req, dict) and req.get("skipped"):
        out["request"] = {**req, "skipped": [_skip(x) if operator else notes.public(_skip(x)) for x in req["skipped"]]}
    if not operator:
        if out.get("error"):
            out["error"] = "not read"
        cls = out.get("classify")
        if isinstance(cls, dict) and cls.get("error"):
            out["classify"] = {**cls, "error": "no usable answer"}
    return out


async def present(db: Database, o: dict[str, Any], actor: str, *, timeline: bool = False) -> dict[str, Any]:
    """An order as the UI shows it: the farm's costs and raw errors hidden from customers, the moves this actor may make,
    the project, the title in both languages, whether the part is in the catalog, and the journal as codes (shop/notes.py)."""
    out = dict(o)
    q = dict(o.get("quote") or {})
    data = o.get("intake") or {}
    operator = actor == "operator"
    if not operator:
        for k in quote.INTERNAL:
            q.pop(k, None)
        sl = o.get("slice") or {}
        out["slice"] = {k: sl[k] for k in ("id", "printer", "material", "stats", "files") if k in sl}
        out["problem"] = {k: v for k, v in (o.get("problem") or {}).items() if k in ("code", "at", "retry_at")}
        rep = o.get("qc") or {}
        if rep.get("error"):
            out["qc"] = {**rep, "error": QC_ERRORS.get(rep.get("error_code") or "", "the photo could not be measured")}
    out["intake"] = _intake_for(data, operator)
    out["quote"] = q
    out["next"] = flow.next_moves(o, actor)
    out["actor"] = actor
    # Pay waits for the intake's verdict: 'pending' (being read), 'held' (for the operator), 'refused', or 'ok'
    out["safety"] = flow.safety(o) or "ok"
    # "choose for me": the material the intake picked while the price is still in another one (Pay waits for its quote)
    out["material_due"] = flow.material_due(o)
    out["showcase"] = bool(o.get("showcase"))
    p = await db.one("SELECT title, cover, version, user_id FROM projects WHERE id = ?", o["project_id"])
    out["project"] = {"id": o["project_id"], "title": (p or {}).get("title"), "cover": file_url((p or {}).get("cover")), "version": (p or {}).get("version")}
    out["title"] = (p or {}).get("title") or title_for(data)
    # a new part is named by what the intake read, a catalog part by its card; a studio part keeps the name it has
    li = await store.get_listing(db, o["listing_id"]) if o.get("listing_id") else None
    if li and not operator and (p or {}).get("user_id") != o["user_id"]:
        # someone else's catalog card: its own name and picture, never the owner's project as it is now (a title renamed
        # in private, a later private version), nor the slice's files, whose names carry that title
        out["project"] = {"id": o["project_id"], "title": li["title"], "cover": file_url(li.get("cover")), "version": li["version"]}
        out["title"] = li["title"]
        out["slice"].pop("files", None)
        q.pop("files", None)
    if li:
        both = card_titles(li)
    elif (data.get("request") or {}).get("kind") == "photo":
        both = titles(data, out["title"])
    else:
        # a studio part keeps its own name in its own script; the other language gets the intake's catalog title
        en, ru = titles(data, out["title"])
        both = (en, out["title"]) if CYRILLIC.search(out["title"] or "") else (out["title"], ru)
    out["title_en"], out["title_ru"] = both
    # the French title (the G1 front): a catalog card has none yet and shows its English one
    out["title_fr"] = both[0] if li else title_fr(data, both[0])
    out["own_listing"] = await store.own_listing(db, o["user_id"], o["project_id"])
    out["working"] = autoquote.running(o["id"])
    if out["working"] and o["status"] == "quoted":
        out["next"] = [m for m in out["next"] if m != "paid"]  # its step may still change the price (pay() refuses meanwhile)
    if o["status"] == "needs_info":
        ask = await db.one("SELECT data FROM events WHERE project_id = ? AND type = 'ask' ORDER BY seq DESC LIMIT 1", o["project_id"])
        out["question"] = (ask or {}).get("data")
    if timeline:
        out["timeline"] = [notes.entry(t, operator) for t in await store.timeline(db, o["id"])]
    return out


async def _instant(db: Database, project_id: str, version: int | None, user_id: str, *, quantity: int = 1, material: str = "PLA",
                   delivery: str = "courier", new_part: bool = True) -> dict[str, Any] | None:
    sql = "SELECT checks FROM programs WHERE project_id = ? " + ("AND version = ?" if version else "ORDER BY version DESC LIMIT 1")
    prog = await db.one(sql, *((project_id, version) if version else (project_id,)))
    stats = ((prog or {}).get("checks") or {}).get("stats") or {}
    if not stats.get("estGrams"):
        return None
    return quote.instant(stats, quantity=quantity, material=material, delivery=delivery, new_part=new_part,
                         customer=await autoquote.customer_kind(db, user_id), queue_hours=await store.queue_hours(db),
                         printers=await store.printers_online(db))


async def _priced_for(db: Database, q: dict[str, Any], user: dict) -> dict[str, Any]:
    """An instant quote as this viewer may see it: the farm's costs and margin only for its operators, as in present()."""
    if (await store.role(db, user["id"]))[0] == "operator":
        return q
    return {k: v for k, v in q.items() if k not in quote.INTERNAL}


# how much one person may have the farm work on: every order is an intake call, a slicer run and a card on the /ops board,
# and an anonymous visitor is a new cookie away, so their orders are also counted per network (users.ip)
ANON_OPEN_ORDERS = 5  # an anonymous visitor's orders still open (requested .. paid)
ANON_NETWORK_ORDERS = 10  # orders made in a day by the anonymous visitors of one network
OPEN_ORDERS = 20  # anyone signed in (a judge link, a Telegram chat, a repair shop)
ANON_PIECES = 20  # pieces in one order of an anonymous visitor (signed in: 200)
COUNTED = ("requested", "designing", "needs_info", "quoted", "paid")


async def order_cap(db: Database, user: dict[str, Any], quantity: int | None = None) -> None:
    """Refuses a new order (or a quantity) past these limits: 429 too_many_orders, 400 too_many_pieces. The farm's own
    operators have none."""
    if (await store.role(db, user["id"]))[0] == "operator":
        return
    anon = user.get("tier", "anon") == "anon"
    if anon and quantity and quantity > ANON_PIECES:
        raise _fail(400, f"up to {ANON_PIECES} pieces per order without signing in", "too_many_pieces")
    row = await db.one(f"SELECT COUNT(*) AS n FROM shop_orders WHERE user_id = ? AND status IN ({', '.join('?' * len(COUNTED))})",
                       user["id"], *COUNTED)
    if (row or {}).get("n", 0) >= (ANON_OPEN_ORDERS if anon else OPEN_ORDERS):
        raise _fail(429, "you have many orders open already: pay, finish or cancel one first", "too_many_orders")
    if anon and user.get("ip"):
        row = await db.one("SELECT COUNT(*) AS n FROM shop_orders o JOIN users u ON u.id = o.user_id WHERE u.tier = 'anon' AND u.ip = ? "
                           "AND o.created_at > ?", user["ip"], now() - 86400)
        if (row or {}).get("n", 0) >= ANON_NETWORK_ORDERS:
            raise _fail(429, "many orders came from this network today; try again tomorrow", "too_many_orders")


# ------------------------------------------------------------------ who is asking
@router.get("/me")
async def me(user=Depends(user_dep)):
    db = await store.shop_db()
    org = await store.org_of(db, user["id"])
    return {"user": {"id": user["id"], "tier": user["tier"], "name": user.get("name")}, "org": org,
            "is_operator": bool(org and org["kind"] == "farm"), "currency": quote.DEFAULT.currency, "usd_kzt": quote.shop_settings().usd_kzt,
            "usd_rate": quote.usd_rate()}


@router.get("/tariff")
async def tariff():
    """The price list's public part (materials and delivery), for the order form."""
    t = quote.DEFAULT
    return {"currency": t.currency, "usd_kzt": quote.shop_settings().usd_kzt, "usd_rate": quote.usd_rate(), "materials": list(quote.MATERIALS),
            "delivery": {k: {"price": v[0], "days": v[1], "price_usd": quote.usd(v[0])} for k, v in t.delivery.items()}}


# ------------------------------------------------------------------ intake
def _material(material: str | None) -> str | None:
    return material.upper() if material and material.upper() in quote.MATERIALS else None


async def new_part_project(db: Database, user_id: str, title: str) -> str:
    """The customer's own project a new part is designed in (its photos go here)."""
    pid = new_id("p_")
    t = now()
    await db.insert("projects", {"id": pid, "user_id": user_id, "title": (title or UNNAMED[0])[:80], "pack": "household", "created_at": t, "updated_at": t})
    return pid


async def order_project(db: Database, user: dict[str, Any], p: dict[str, Any], *, text: str = "", quantity: int | None = None,
                        material: str | None = None, delivery: str = "courier", contact: str = "", code: str = "ordered_studio") -> dict[str, Any]:
    """A model made in the studio (or in the Telegram chat) goes straight to the slicer quote, with no design step.
    The order comes back at once in 'requested' with the kernel's instant range; OrcaSlicer's quote follows."""
    if not p["version"]:
        raise _fail(409, "this project has no model yet", "no_model")
    await order_cap(db, user, quantity)
    _, org = await store.role(db, user["id"])
    mat = _material(material)
    brief = p["brief"] or {}
    said = "\n".join(x for x in (f"Order of a ready model: {p['title']}.", str(brief.get("summary") or "")[:600], text.strip()) if x)
    # the quantity is the form's (a model's description may mention other counts); the intake may still suggest the material
    req = {"kind": "project", "text": said, "quantity": quantity or 1, "material": mat, "photos": []}
    o = await store.create_order(db, user_id=user["id"], org_id=org, project_id=p["id"], version=p["version"], intake={"request": req},
                                 quantity=quantity or 1, material=mat or "PLA", delivery={"method": delivery},
                                 customer={"contact": contact.strip()[:200]}, code=code,
                                 quote=await _instant(db, p["id"], p["version"], user["id"], quantity=quantity or 1, material=mat or "PLA",
                                                      delivery=delivery) or {})
    autoquote.spawn(o["id"], autoquote.begin(o["id"]))
    return o


async def order_part(db: Database, user: dict[str, Any], project_id: str, *, photos: list[dict[str, Any]], text: str = "", appliance: str = "",
                     part_number: str = "", quantity: int | None = None, material: str | None = None, delivery: str = "courier",
                     contact: str = "", said: list[str] | None = None, skipped: list[dict[str, Any]] | None = None,
                     code: str = "created") -> dict[str, Any]:
    """A new part from what the customer sent (`photos`: assets already in `project_id`, role part or plate):
    read by the intake, then designed and quoted in the background."""
    await order_cap(db, user, quantity)
    _, org = await store.role(db, user["id"])
    mat = _material(material)
    said = said or []
    request_text = "\n".join(x for x in (text.strip(), f"Appliance: {appliance.strip()}" if appliance.strip() else "",
                                         f"Part number: {part_number.strip()}" if part_number.strip() else "",
                                         f"Quantity: {quantity}" if quantity else "", f"Voice note: {' '.join(said)}" if said else "") if x)
    # `words`: the customer's own text, apart from the labelled lines the models read (the studio shows it as theirs)
    req = {"kind": "photo", "text": request_text, "words": text.strip()[:2000], "appliance": appliance.strip()[:120],
           "part_number": part_number.strip()[:60], "quantity": quantity, "material": mat, "photos": photos,
           "transcript": " ".join(said)[:2000], "skipped": skipped or []}
    o = await store.create_order(db, user_id=user["id"], org_id=org, project_id=project_id, intake={"request": req}, quantity=quantity or 1,
                                 material=mat or "PLA", delivery={"method": delivery}, customer={"contact": contact.strip()[:200]}, code=code)
    autoquote.spawn(o["id"], autoquote.begin(o["id"]))
    return o


@router.post("/requests")
async def create_request(request: Request, text: str = Form(""), appliance: str = Form(""), part_number: str = Form(""), quantity: int | None = Form(None, ge=1, le=200),
                         material: str | None = Form(None), delivery: Delivery = Form("courier"), contact: str = Form(""),
                         project_id: str | None = Form(None), files: list[UploadFile] = File(default=[]), plate: UploadFile | None = File(None),
                         voice: UploadFile | None = File(None), user=Depends(user_dep)):
    """A new part: photos of the broken or missing part on A4, the rating plate, the appliance model or part number,
    a voice note -> the request is read (Muse Spark 1.3), then designed and quoted in the background.
    With `project_id`: a model already made in the studio goes straight to the slicer quote. An Idempotency-Key answers a
    retry with the first order."""
    db = await store.shop_db()

    async def again(order_id: str) -> dict[str, Any] | None:
        return await store.get(db, order_id)

    if project_id:
        p = await hooks.load_project(project_id, user)
        o = await idempotency.once(user["id"], "shop.request", idempotency.key_of(request), lambda: order_project(
            db, user, p, text=text, quantity=quantity, material=material, delivery=delivery, contact=contact), again)
        return await present(db, o, "customer")

    o = await idempotency.once(user["id"], "shop.request", idempotency.key_of(request), lambda: _new_request(
        db, user, text, appliance, part_number, quantity, material, delivery, contact, files, plate, voice), again)
    return await present(db, o, "customer")


async def _new_request(db: Database, user: dict[str, Any], text: str, appliance: str, part_number: str, quantity: int | None, material: str | None,
                       delivery: Delivery, contact: str, files: list[UploadFile], plate: UploadFile | None, voice: UploadFile | None) -> dict[str, Any]:
    from formwright.vision import ingest

    uploads = [(f, "part") for f in files[:6]] + ([(plate, "plate")] if plate else []) + ([(voice, "voice")] if voice else [])
    if not uploads and not (text.strip() or appliance.strip() or part_number.strip()):
        raise _fail(400, "send a photo of the part, a voice note or a few words about it", "empty_request")
    await order_cap(db, user, quantity)  # before any file is stored (order_part checks again)
    # unnamed until the intake reads it: 'Запчасть' for a request in Russian (the studio shows the project's own title)
    pid = await new_part_project(db, user["id"], part_number or appliance or UNNAMED[1 if CYRILLIC.search(text) else 0])
    photos: list[dict[str, Any]] = []
    said: list[str] = []
    skipped: list[dict[str, Any]] = []  # {code, file, kind?, error?}: the error text is for the farm only
    try:
        for f, role in uploads:
            data = await f.read(UPLOAD_LIMIT + 1)
            if len(data) > UPLOAD_LIMIT:
                raise _fail(413, "file too large (60 MB max)", "too_large")
            audio = role == "voice" or (f.content_type or "").startswith("audio")
            try:
                a = await ingest.ingest_asset(pid, "audio" if audio else "photo", f.filename or "upload", data, f.content_type or "")
            except ValueError as e:
                skipped.append({"code": "unreadable", "file": (f.filename or role)[:120], "error": str(e)[:200]})
                continue
            meta = a.get("meta") or {}
            if a["kind"] == "audio":
                if meta.get("transcript"):
                    said.append(meta["transcript"])
                elif meta.get("transcript_error"):
                    skipped.append({"code": "voice_untranscribed", "file": (f.filename or "voice")[:120], "error": str(meta["transcript_error"])[:200]})
            elif a["kind"] == "photo":
                photos.append({"id": a["id"], "role": "plate" if role == "plate" else "part"})
            else:
                skipped.append({"code": "not_photo", "file": (f.filename or role)[:120], "kind": a["kind"]})
    except Exception:  # a quota, a file too large, the model service down (the face pass needs it)
        from formwright import app as _app

        await _app._drop_snap(pid)  # removes the half-made project with its rows and files
        raise
    return await order_part(db, user, pid, photos=photos, text=text, appliance=appliance, part_number=part_number, quantity=quantity,
                            material=material, delivery=delivery, contact=contact, said=said, skipped=skipped)


@router.get("/instant-quote/{project_id}")
async def instant_quote(project_id: str, quantity: int = 1, material: str = "PLA", delivery: Delivery = "courier", user=Depends(user_dep)):
    """Right after a build: a non-binding range from the kernel's estimate (the slicer quote follows)."""
    p = await hooks.load_project(project_id, user)
    db = await store.shop_db()
    mat = material.upper() if material.upper() in quote.MATERIALS else "PLA"
    q = await _instant(db, p["id"], None, user["id"], quantity=max(1, min(200, quantity)), material=mat, delivery=delivery)
    if q is None:
        raise _fail(409, "no model with a mass estimate yet", "no_estimate")
    return await _priced_for(db, q, user)


# ------------------------------------------------------------------ customer side
@router.get("/orders")
async def my_orders(user=Depends(user_dep)):
    db = await store.shop_db()
    _, org = await store.role(db, user["id"])
    rows = await db.all("SELECT id FROM shop_orders WHERE user_id = ? OR (org_id IS NOT NULL AND org_id = ?) ORDER BY created_at DESC LIMIT 200",
                        user["id"], org or "")
    orders = [await store.get(db, r["id"]) for r in rows]
    if await autoquote.expire(db, orders):  # type: ignore[arg-type]
        orders = [await store.get(db, r["id"]) for r in rows]
    return [await present(db, o, "customer") for o in orders]  # type: ignore[arg-type]


# ------------------------------------------------------------------ a delivered order anyone may read
# what of an order the public page shows, field by field (an allow-list: whatever is added to orders later stays out)
PUBLIC_ORDER = ("id", "ref", "status", "quantity", "material", "color", "version", "attempts", "created_at", "updated_at")
PUBLIC_PART = ("name_en", "name_user", "part_number", "quantity", "condition", "failure")
PUBLIC_INTAKE = ("language", "material", "refuse", "reason", "ip_flags", "environment", "model", "tolerance_mm", "read_at")
# journal parameters that are free text (an operator's note) or point at the parcel: not on the public page
PUBLIC_DROP = {"note", "tracking"}


def _public_entry(e: dict[str, Any]) -> dict[str, Any]:
    """A journal line for the public page: its code and safe parameters, the English line rebuilt from them; a line
    without a code is someone's own words, and only its step is shown."""
    params = {k: v for k, v in (e.get("params") or {}).items() if k not in PUBLIC_DROP | notes.PRIVATE}
    return {"status": e["status"], "from": e["from"], "actor": e["actor"], "ts": e["ts"], "code": e["code"], "params": params,
            "note": notes.text(e["code"], params) if e["code"] else ""}


async def public_view(db: Database, o: dict[str, Any]) -> dict[str, Any]:
    """A showcase order as anyone reads it: the part, the journal, the price breakdown, the printer, the times, the QC
    photo with SAM 3.1's mask and the verdict. Nothing of the person: no contact, address, name, user id, chat, the
    words or photos they sent, their answers, nor the parcel's tracking number."""
    seen = await present(db, o, "customer", timeline=True)
    data = o.get("intake") or {}
    part, app = data.get("part") or {}, data.get("appliance") or {}
    cls = data.get("classify") if isinstance(data.get("classify"), dict) and not data["classify"].get("error") else None
    q = dict(seen["quote"])
    q.pop("files", None)  # the slice's files stay the farm's
    sl = o.get("slice") or {}
    printer = await db.one("SELECT name, preset_id FROM shop_printers WHERE id = ?", o["printer_id"]) if o.get("printer_id") else None
    pay = o.get("payment") or {}
    rep = dict(seen.get("qc") or {})
    p = await db.one("SELECT cover, version, public FROM projects WHERE id = ?", o["project_id"])
    li = await store.get_listing(db, o["listing_id"]) if o.get("listing_id") else None
    if not (li and li["public"] and not li["flagged"]):  # the part was shared to the catalog after this order
        li = store._dec(await db.one("SELECT * FROM shop_listings WHERE project_id = ? AND public = 1 AND flagged = 0 ORDER BY orders DESC, "
                                     "updated_at DESC LIMIT 1", o["project_id"]))
    timeline = [_public_entry(e) for e in seen["timeline"]]
    if (data.get("request") or {}).get("kind") == "project":
        # a studio project's own title is the customer's (a gift with someone's name in it): the intake's catalog name,
        # also where the journal says what the intake read
        en, ru = titles({**data, "part": {k: v for k, v in part.items() if k != "name_user"}}, UNNAMED[0])
        named = (ru if str(data.get("language") or "").startswith("ru") else en, en, ru)
        for e in timeline:
            if e["code"] == "intake_read":
                e["params"] = {**e["params"], "title": named[0], "title_en": en, "title_ru": ru}
                e["note"] = notes.text(e["code"], e["params"])
    else:
        named = (seen["title"], seen["title_en"], seen["title_ru"])
    out = {k: o.get(k) for k in PUBLIC_ORDER} | {
        "intake": {**{k: data[k] for k in PUBLIC_INTAKE if k in data},
                   # how the safety gate went: not read, held and why (the models' words), let through by the farm
                   **({"error": "not read"} if data.get("error") else {}),
                   **({"review": {k: data["review"][k] for k in ("code", "why") if k in data["review"]}} if isinstance(data.get("review"), dict) else {}),
                   **({"reviewed": {k: data["reviewed"][k] for k in ("action", "at") if k in data["reviewed"]}}
                      if isinstance(data.get("reviewed"), dict) else {}),
                   "request": {"kind": (data.get("request") or {}).get("kind") or "listing"},
                   "part": {k: part[k] for k in PUBLIC_PART if k in part},
                   "appliance": {k: app[k] for k in ("kind", "brand", "model") if k in app},
                   "classify": {k: cls[k] for k in ("category", "safety_critical", "title_en", "title_ru", "title_fr", "model") if k in cls} if cls else None},
        "quote": q,
        "payment": {k: pay[k] for k in ("mode", "amount", "currency", "amount_usd", "at") if k in pay},
        "slice": {k: sl[k] for k in ("printer", "material", "stats") if k in sl},
        "printer": dict(printer) if printer else None,
        "qc": rep,
        "shipping": {k: v for k, v in (o.get("shipping") or {}).items() if k in ("carrier", "at")},
        "delivery": {"method": (o.get("delivery") or {}).get("method") or "courier"},
        "customer": {},
        "problem": {},
        # the render of the version that was printed; how it was designed, and the card to order it again, when those are public
        "project": {"cover": file_url(store.shipped_cover(o, p)), "version": o.get("version"),
                    **({"id": o["project_id"]} if p and p["public"] else {})},
        "listing_id": li["id"] if li and li["public"] and not li["flagged"] else None,
        "title": named[0], "title_en": named[1], "title_ru": named[2], "title_fr": seen.get("title_fr") or named[1],
        "next": [], "actor": "public", "working": False, "safety": seen["safety"], "showcase": True,
        "timeline": timeline,
    }
    return out


@router.get("/showcase")
async def showcase_latest():
    """The newest delivered order the farm shows to anyone (/parts links it), or null."""
    db = await store.shop_db()
    o = await store.showcase(db)
    if not o:
        return None
    v = await public_view(db, o)
    return {"id": o["id"], "ref": o["ref"], "status": o["status"], "title": v["title"], "title_en": v["title_en"], "title_ru": v["title_ru"],
            "title_fr": v["title_fr"],
            "cover": v["project"]["cover"], "qc_pass": bool((o.get("qc") or {}).get("pass"))}


@router.get("/orders/{order_id}")
async def order_detail(order_id: str, user=Depends(user_dep)):
    try:
        db, o, actor = await _order_for(user, order_id)
    except HTTPException as e:
        # someone else's order: readable only once the farm made it a showcase, and then without the person in it
        db = await store.shop_db()
        o = await store.get(db, order_id) if e.status_code == 403 else None
        if o and o.get("showcase") and o["status"] in ("shipped", "delivered"):
            return await public_view(db, o)
        raise
    if await autoquote.reconcile(db, [o]):
        o = await store.get(db, order_id)  # type: ignore[assignment]
    return await present(db, o, _viewer(o, user, actor), timeline=True)


class QuoteRequest(BaseModel):
    material: str | None = None
    quantity: int | None = Field(default=None, ge=1, le=200)
    delivery: Delivery | None = None
    printer_id: str | None = None
    # an operator's own numbers when this server has no slicer
    grams_each: float | None = Field(default=None, gt=0, le=5000)
    minutes_each: float | None = Field(default=None, gt=0, le=10000)


View = Literal["ops"] | None  # ?view=ops: the farm's board asks, so an operator's own order still reads as the farm's


@router.post("/orders/{order_id}/quote")
async def quote_again(order_id: str, body: QuoteRequest, view: View = None, user=Depends(user_dep)):
    """Another material, quantity or delivery (the customer, on a quoted order), or a quote by the operator at any open step."""
    db, o, actor = await _order_for(user, order_id)
    if actor == "customer" and o["status"] not in ("quoted", "expired"):
        raise _fail(409, "the quote comes when the model is ready", "order_guard")
    if actor == "customer" and body.quantity and body.quantity > ANON_PIECES and user.get("tier", "anon") == "anon":
        raise _fail(400, f"up to {ANON_PIECES} pieces per order without signing in", "too_many_pieces")
    data = o.get("intake") or {}
    req = data.get("request") or {}
    pinned = None
    if (chosen := _material(body.material)) and not req.get("material") and o["status"] in flow.OPEN + ("expired",):
        # "choose for me" no more: a material picked on the price card (or by the farm) is the order's own, so the
        # intake's choice neither replaces it (_follow_material) nor keeps Pay closed (flow.material_due)
        o = await store.patch(db, order_id, {"intake": {**data, "request": {**req, "material": chosen}}})
        pinned = chosen
    manual = None
    if body.grams_each or body.minutes_each:
        if actor != "operator" or not (body.grams_each and body.minutes_each):
            raise _fail(403, "only the operator quotes by hand, with grams and minutes", "forbidden")
        manual = (body.grams_each, body.minutes_each)
    try:
        o = await autoquote.requote(order_id, material=body.material, quantity=body.quantity, delivery=body.delivery,
                                    printer_id=body.printer_id if actor == "operator" else None, manual=manual, actor=actor, actor_id=user["id"])
    except (flow.FlowError, autoquote.QuoteError) as e:
        fresh = await store.get(db, order_id) if pinned else None
        freq = ((fresh or {}).get("intake") or {}).get("request") or {}
        if fresh and freq.get("material") == pinned:
            # no quote in the material picked: the order is still "choose for me", so Pay keeps waiting for the
            # intake's material (flow.material_due) instead of opening on the quote in the old one
            await store.patch(db, order_id, {"intake": {**fresh["intake"], "request": {**freq, "material": req.get("material")}}})
        raise _err(e) from e
    return await present(db, o, _viewer(o, user, actor, view))


class PayIn(BaseModel):
    """How the customer paid. 'test': no money moves (the original demo). 'mobile_money': the customer sent the amount
    by MTN MoMo or Orange Money and gives the transaction reference, which the workshop checks against its account
    before printing (no payment API is called yet). 'on_pickup': paid in cash when the part is collected."""
    method: Literal["test", "mobile_money", "on_pickup"] = "test"
    operator: Literal["mtn", "orange", ""] = ""
    reference: str = Field(default="", max_length=60)


@router.post("/orders/{order_id}/pay")
async def pay(order_id: str, body: PayIn | None = None, user=Depends(user_dep)):
    """Test mode by default: no money moves and no card is asked for. A Mobile Money payment is declared with its
    transaction reference (checked by hand by the workshop); payment on pickup needs the pickup delivery. A real
    deployment puts a payment provider's checkout here."""
    body = body or PayIn()
    if body.method == "mobile_money" and (not body.operator or not body.reference.strip()):
        raise _fail(400, "a Mobile Money payment needs its operator and transaction reference", "payment_reference")
    db, o, _ = await _order_for(user, order_id, operator_ok=False)
    if body.method == "on_pickup" and (o.get("delivery") or {}).get("method") != "pickup":
        raise _fail(409, "payment on pickup is only for parts collected at the workshop", "payment_method")
    q = o.get("quote") or {}
    if q.get("valid_until") and q["valid_until"] < now():
        raise _fail(409, "the quote expired; quote again", "quote_expired")
    # a ready model is priced while the intake reads it: the money waits for the safety verdict (the move's guard
    # checks it again on the order as it is then)
    if o["status"] == "quoted" and (why := flow.safety(o)) in ("pending", "held"):
        raise _fail(409, flow.SAFETY_WHY[why], "safety_pending" if why == "pending" else "held")
    # the intake's verdict is in, and its step is still at work: "choose for me" slices again in the material it chose
    # (PETG for a dishwasher part), and that quote, not the first one, is what gets paid
    if o["status"] == "quoted" and autoquote.running(order_id):
        raise _fail(409, "the price is being updated", "price_updating")
    # ... and when that slice failed, the price in the first material is not the one to pay: reconcile slices it again
    if o["status"] == "quoted" and (m := flow.material_due(o)):
        raise _fail(409, f"the price in {m}, the material picked for this part, is not ready yet", "material_pending")
    try:
        payment = {"mode": body.method, "amount": q.get("total"), "currency": q.get("currency"),
                   "amount_usd": (q.get("usd") or {}).get("total"), "at": now()}
        if body.method == "mobile_money":
            payment |= {"operator": body.operator, "reference": body.reference.strip(), "verified": False}
        code, params = {"mobile_money": ("paid_mobile_money", {"operator": body.operator, "reference": body.reference.strip()}),
                        "on_pickup": ("paid_on_pickup", {})}.get(body.method, ("paid_test", {}))
        o = await store.move(db, order_id, "paid", "customer", user["id"], code=code, params=params, fields={"payment": payment})
    except flow.FlowError as e:
        raise _err(e) from e
    if o.get("listing_id"):
        await db.execute("UPDATE shop_listings SET orders = orders + 1 WHERE id = ?", o["listing_id"])
    return await present(db, o, "customer")


@router.post("/orders/{order_id}/cancel")
async def cancel(order_id: str, view: View = None, user=Depends(user_dep)):
    db, o, actor = await _order_for(user, order_id)
    was = o["status"]
    try:
        o = await store.move(db, order_id, "cancelled", actor, user["id"])
    except flow.FlowError as e:
        raise _err(e) from e
    if was in ("designing", "needs_info"):
        # the designer the order started must not go on spending the customer's quota on an order that is gone
        # (only that job: a studio project's own runs are the person's)
        for t in await store.timeline(db, order_id):
            if (jid := (t.get("data") or {}).get("job_id")):
                await hooks.cancel_job(jid, o["user_id"])
    return await present(db, o, _viewer(o, user, actor, view))


class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


async def answer_order(db: Database, o: dict[str, Any], text: str) -> dict[str, Any] | None:
    """The customer's answer to the designer's waiting question, from the order page or a Telegram button: it goes to
    the job (runner.deliver_answer) and into the order's intake. None when no question is waiting."""
    job = await db.one("SELECT id FROM jobs WHERE project_id = ? AND status = 'waiting' ORDER BY created_at DESC LIMIT 1", o["project_id"])
    if o["status"] != "needs_info" or not job or not await hooks.answer(job["id"], o["user_id"], text.strip()):
        return None
    data = o.get("intake") or {}
    return await store.patch(db, o["id"], {"intake": {**data, "answers": (data.get("answers") or []) + [{"text": text.strip(), "at": now()}]}})


@router.post("/orders/{order_id}/answer")
async def answer(order_id: str, body: AnswerIn, user=Depends(user_dep)):
    """The customer answers the agent's question from the order page (the studio's answer box does the same)."""
    db, o, _ = await _order_for(user, order_id, operator_ok=False)
    o = await answer_order(db, o, body.text)
    if not o:
        raise _fail(409, "no question is waiting", "no_question")
    return await present(db, o, "customer")


@router.post("/orders/{order_id}/delivered")
async def delivered(order_id: str, view: View = None, user=Depends(user_dep)):
    """Received: the contact details are wiped, and a new part becomes a private listing ("Your parts", reorder in one tap)."""
    db, o, actor = await _order_for(user, order_id)
    try:
        # an operator's own order, confirmed on its order page, is received by its customer (the journal says so)
        o = await store.move(db, order_id, "delivered", _viewer(o, user, actor, view), user["id"], fields={"customer": {}})
    except flow.FlowError as e:
        raise _err(e) from e
    if not o.get("listing_id") and o.get("version"):
        try:
            await share(db, o["user_id"], o["project_id"], public=False, order=o)
        except HTTPException as e:
            log.warning("no private listing for %s: %s", o["ref"], e.detail)
    return await present(db, o, _viewer(o, user, actor, view))


# ------------------------------------------------------------------ operator
async def operator_dep(user=Depends(user_dep)) -> dict[str, Any]:
    if (await store.role(await store.shop_db(), user["id"]))[0] != "operator":
        raise _fail(403, "operators only", "not_operator")
    return user


@router.get("/ops/queue")
async def ops_queue(user=Depends(operator_dep)):
    """The farm's board: upstream (being read, designed, quoted, held for review), paid, printing, QC, ready to ship."""
    db = await store.shop_db()
    up = await store.upstream(db)
    await autoquote.reconcile(db, up)
    printers = await db.all("SELECT p.*, o.ref AS order_ref FROM shop_printers p LEFT JOIN shop_orders o ON o.id = p.order_id ORDER BY p.name")
    return {"orders": [await present(db, o, "operator") for o in await store.queue(db)],
            "upstream": [await present(db, o, "operator") for o in await store.upstream(db)],
            "done": [await present(db, o, "operator") for o in await store.done(db)],
            "printers": printers, "queue_hours": await store.queue_hours(db)}


class ShowcaseIn(BaseModel):
    on: bool


@router.post("/orders/{order_id}/showcase")
async def set_showcase(order_id: str, body: ShowcaseIn, user=Depends(operator_dep)):
    """The farm shows one of its delivered orders to anyone (the journal, the price, the printer, the QC photo with
    its mask), without the customer's data: /orders/<id> for everyone, linked from /parts. Shipped or later only."""
    db = await store.shop_db()
    o = await store.get(db, order_id)
    if not o:
        raise HTTPException(404, "order not found")
    if body.on and o["status"] not in ("shipped", "delivered"):
        raise _fail(409, "only a shipped or delivered order can be shown", "not_delivered")
    o = await store.patch(db, order_id, {"showcase": int(body.on)})
    return await present(db, o, "operator")


class ReviewIn(BaseModel):
    action: Literal["approve", "refuse"]
    note: str = Field(default="", max_length=500)
    tolerance_mm: float | None = Field(default=None, gt=0, le=5)
    # a request nobody could read (the intake model was down): what the operator read in it, written into the intake
    # before the design starts (the board fills them from the customer's form)
    quantity: int | None = Field(default=None, ge=1, le=200)
    material: str | None = None


@router.post("/orders/{order_id}/review")
async def review(order_id: str, body: ReviewIn, user=Depends(operator_dep)):
    """A request the models disagreed on (or could not read) waits here: the operator lets it through or refuses it.
    A ready model may be quoted already (its Pay waits for this)."""
    db = await store.shop_db()
    o = await store.get(db, order_id)
    if not o or not (o["status"] == "requested" or (o["status"] == "quoted" and flow.safety(o) == "held")):
        raise _fail(409, "the order is not waiting for a review", "order_guard")
    if body.action == "approve" and flow.safety(o) != "held":
        # letting a request through is for what the models said: an approval before the intake answers would wave
        # through a hold nobody has seen yet (refusing stays allowed at any open step)
        raise _fail(409, "the safety check has not finished", "order_guard")
    data = {**(o.get("intake") or {}), "reviewed": {"by": user["id"], "action": body.action, "note": body.note, "at": now()}}
    if body.tolerance_mm:
        data["tolerance_mm"] = body.tolerance_mm
    if body.material and not _material(body.material):
        raise _fail(400, f"we print {', '.join(quote.MATERIALS)}", "bad_material")
    # what the operator set for a request still to be designed (a quoted one changes through its own requote)
    fields: dict[str, Any] = {}
    said: dict[str, Any] = {"note": body.note}
    if body.action == "approve" and o["status"] == "requested":
        if body.quantity:
            data["part"] = {**(data.get("part") or {}), "quantity": body.quantity}
            fields["quantity"] = said["quantity"] = body.quantity
        if (m := _material(body.material)):
            data["material"] = fields["material"] = said["material"] = m
    if body.action == "refuse":
        try:
            o = await store.move(db, order_id, "refused", "operator", user["id"], code="refused_operator", params={"note": body.note},
                                 fields={"intake": data})
        except flow.FlowError as e:
            raise _err(e) from e
    else:
        quoted = o["status"] == "quoted"
        o = await store.patch(db, order_id, {"intake": data} if quoted else {"intake": data, "problem": {}, **fields})
        await store.log(db, order_id, o["status"], o["status"], "operator", user["id"], code="approved", params=said)
        if not quoted:
            autoquote.spawn(order_id, autoquote.begin(order_id))
    return await present(db, o, "operator")


class PrinterIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    preset_id: str = Field(default_factory=lambda: quote.shop_settings().farm_preset, max_length=120)
    material: str = "PLA"
    color: str | None = Field(default=None, max_length=40)


def _preset(preset_id: str) -> str:
    from formwright.printing import presets

    if not presets.available():
        return preset_id  # no Orca profiles on this server: keep the name, slicing will say what is missing
    p = presets.printer_by(preset_id)
    if not p:
        raise _fail(400, f"no OrcaSlicer preset {preset_id!r}", "bad_preset")
    return p.id


@router.post("/ops/printers")
async def add_printer(body: PrinterIn, user=Depends(operator_dep)):
    db = await store.shop_db()
    pid = new_id("sp_")
    await db.insert("shop_printers", {"id": pid, "name": body.name, "preset_id": _preset(body.preset_id), "material": body.material.upper(),
                                      "color": body.color, "created_at": now()})
    return await db.one("SELECT * FROM shop_printers WHERE id = ?", pid)


class PrinterPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    material: str | None = None
    color: str | None = Field(default=None, max_length=40)
    state: Literal["idle", "printing", "maintenance"] | None = None


@router.post("/ops/printers/{printer_id}")
async def update_printer(printer_id: str, body: PrinterPatch, user=Depends(operator_dep)):
    db = await store.shop_db()
    if not await db.one("SELECT id FROM shop_printers WHERE id = ?", printer_id):
        raise HTTPException(404, "printer not found")
    fields = {k: (v.upper() if k == "material" else v) for k, v in body.model_dump(exclude_none=True).items()}
    if fields.get("state") == "idle":
        fields["order_id"] = None
    if fields:
        await db.update("shop_printers", "id", printer_id, fields)
    return await db.one("SELECT * FROM shop_printers WHERE id = ?", printer_id)


@router.post("/ops/printers/{printer_id}/fingerprint")
async def printer_fingerprint(printer_id: str, file: UploadFile = File(...), user=Depends(operator_dep)):
    """Photo of the printed calibration coupon (GET /api/printers/coupon.3mf) on A4: this printer's hole and outline
    compensation, kept with the printer, so two printers of the same model each get their own."""
    from formwright.vision import ingest

    from .qc import ops_project

    db = await store.shop_db()
    if not await db.one("SELECT id FROM shop_printers WHERE id = ?", printer_id):
        raise HTTPException(404, "printer not found")
    data = await file.read(UPLOAD_LIMIT + 1)
    if len(data) > UPLOAD_LIMIT:
        raise _fail(413, "file too large (60 MB max)", "too_large")
    try:
        asset = await ingest.ingest_asset(await ops_project(user), "photo", file.filename or "coupon.jpg", data, file.content_type or "image/jpeg")
        result = await hooks.fingerprint(user, asset)
    except ValueError as e:
        raise _fail(400, str(e), "fingerprint_failed") from e
    fp = {**result["fingerprint"], "measured": result.get("measured"), "asset_id": asset["id"], "at": now()}
    await db.update("shop_printers", "id", printer_id, {"fingerprint": fp})
    return await db.one("SELECT * FROM shop_printers WHERE id = ?", printer_id)


class AssignIn(BaseModel):
    printer_id: str


@router.post("/orders/{order_id}/payment-verified")
async def payment_verified(order_id: str, user=Depends(operator_dep)):
    """The workshop found the customer's Mobile Money transfer on its account: the order may go to a printer."""
    db, o, _ = await _order_for(user, order_id)
    pay = o.get("payment") or {}
    if o["status"] != "paid" or pay.get("mode") != "mobile_money":
        raise _fail(409, "no Mobile Money payment waits for a check on this order", "order_guard")
    o = await store.patch(db, order_id, {"payment": {**pay, "verified": True, "verified_at": now(), "verified_by": user["id"]}})
    await store.log(db, order_id, "paid", "paid", "operator", user["id"], code="payment_verified",
                    params={"reference": pay.get("reference") or ""})
    return await present(db, o, "operator")


@router.post("/orders/{order_id}/assign")
async def assign(order_id: str, body: AssignIn, user=Depends(operator_dep)):
    """paid -> printing on this printer. The quote's slice is used when it was made for this printer and its
    fingerprint; otherwise the pinned version is sliced again for it, and the paid price holds."""
    db = await store.shop_db()
    o = await store.get(db, order_id)
    printer = await db.one("SELECT * FROM shop_printers WHERE id = ?", body.printer_id)
    if not o or not printer:
        raise HTTPException(404, "order or printer not found")
    if o["status"] != "paid":
        raise _fail(409, f"{o['status']} -> printing is not allowed", "order_bad_move")
    if printer["state"] == "maintenance":
        raise _fail(409, "the printer is in maintenance", "printer_busy")
    said: dict[str, Any] = {"printer": printer["name"]}
    sl = o.get("slice") or {}
    if not autoquote.same_slice(sl, printer, o["version"]):
        try:
            sl = {**await autoquote.slice_for(o["project_id"], o["version"], printer, o["material"]), "version": o["version"]}
        except Exception as e:  # noqa: BLE001
            raise _fail(409, f"slicing for {printer['name']} failed: {e}"[:300], "slice_failed") from e
        said.update(resliced=True, grams=(sl.get("stats") or {}).get("grams"), quoted=(o.get("quote") or {}).get("grams_each"))
    try:
        o = await store.move(db, order_id, "printing", "operator", user["id"], code="assigned", params=said,
                             fields={"printer_id": printer["id"], "slice": sl, "attempts": (o.get("attempts") or 0) + 1})
    except flow.FlowError as e:
        raise _err(e) from e
    await db.update("shop_printers", "id", printer["id"], {"state": "printing", "order_id": order_id})
    return await present(db, o, "operator")


@router.post("/orders/{order_id}/printed")
async def printed(order_id: str, user=Depends(operator_dep)):
    db = await store.shop_db()
    try:
        o = await store.move(db, order_id, "qc", "operator", user["id"], code="printed")
    except flow.FlowError as e:
        raise _err(e) from e
    if o.get("printer_id"):
        await db.execute("UPDATE shop_printers SET state = 'idle', order_id = NULL WHERE id = ? AND order_id = ?", o["printer_id"], order_id)
    return await present(db, o, "operator")


@router.post("/orders/{order_id}/qc")
async def qc(order_id: str, file: UploadFile = File(...), user=Depends(operator_dep)):
    """Photo of the printed part on A4 -> SAM 3.1 outline in mm -> compared with the model -> pass, or back for a reprint.
    A photo that cannot be measured leaves the order in QC for another photo."""
    db = await store.shop_db()
    o = await store.get(db, order_id)
    if not o or o["status"] != "qc":
        raise _fail(409, "the order is not waiting for QC", "order_guard")
    data = await file.read(UPLOAD_LIMIT + 1)
    if len(data) > UPLOAD_LIMIT:
        raise _fail(413, "file too large (60 MB max)", "too_large")
    report = await hooks.qc(user, o, data, file.filename or "qc.jpg", file.content_type or "image/jpeg")
    try:
        # measuring takes seconds: a Reprint (or a second photo's verdict) may have moved the order meanwhile
        o = await store.patch_if(db, order_id, {"qc": report}, "qc")
        if report.get("error"):
            await store.log(db, order_id, "qc", "qc", "system", None, code="qc_unmeasured",
                            params={"error": str(report["error"])[:200], "error_code": report.get("error_code")})
        else:
            said = {"max": report.get("max_mm"), "tol": report.get("tolerance_mm")}
            await store.log(db, order_id, "qc", "qc", "system", None, code="qc_pass" if report.get("pass") else "qc_fail", params=said)
            if not report.get("pass"):
                o = await store.move(db, order_id, "paid", "system", code="reprint_qc")
    except flow.FlowError as e:
        raise _err(e) from e
    return await present(db, o, "operator")


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=500)


@router.post("/orders/{order_id}/reprint")
async def reprint(order_id: str, body: NoteIn, user=Depends(operator_dep)):
    """The operator sees a defect the outline does not show (stringing, a broken snap): qc -> paid."""
    db = await store.shop_db()
    try:
        # the next print needs its own QC photo: the verdict on this one must not let the reprint ship (the journal keeps it)
        o = await store.move(db, order_id, "paid", "operator", user["id"], code="reprint", params={"note": body.note}, fields={"qc": {}})
    except flow.FlowError as e:
        raise _err(e) from e
    return await present(db, o, "operator")


class ShipIn(BaseModel):
    carrier: str = Field(default="", max_length=60)
    tracking: str = Field(default="", max_length=80)


@router.post("/orders/{order_id}/ship")
async def ship(order_id: str, body: ShipIn, user=Depends(operator_dep)):
    db = await store.shop_db()
    try:
        o = await store.move(db, order_id, "shipped", "operator", user["id"], data=body.model_dump(), code="shipped", params=body.model_dump(),
                             fields={"shipping": {**body.model_dump(), "at": now()}})
    except flow.FlowError as e:
        raise _err(e) from e
    return await present(db, o, "operator")


# ------------------------------------------------------------------ catalog
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def card_titles(li: dict[str, Any]) -> tuple[str, str]:
    """A card's (English, Russian) names: its own name in each language, else the first of its names written in that
    language's script, else any of them. So the English catalog shows a Cyrillic name only when no other name exists
    (a listing saved before the two names, or seeded, has its one title), and the Russian one likewise."""
    def pick(ru: bool, *names: str | None) -> str:
        names_ = [n for n in names if n]
        return next((n for n in names_ if bool(CYRILLIC.search(n)) == ru), names_[0] if names_ else "")

    return (pick(False, li.get("title_en"), li.get("title"), li.get("title_ru")),
            pick(True, li.get("title_ru"), li.get("title"), li.get("title_en")))


def listing_out(li: dict[str, Any], viewer_id: str | None) -> dict[str, Any]:
    """A catalog card: "compatible with" the appliance, never the brand's part; no owner id, no reports."""
    fits = " ".join(x for x in (li.get("brand"), ", ".join(li.get("models") or [])) if x)
    return {k: li[k] for k in ("id", "project_id", "version", "title", "brand", "models", "part_numbers", "category", "material", "verified",
                               "orders", "created_at", "updated_at")} | {
        # the card in the UI's language; a listing saved before the two names (or seeded) has its one title in both
        "title_en": card_titles(li)[0], "title_ru": card_titles(li)[1],
        "public": bool(li["public"]), "cover": file_url(li.get("cover")), "compatible_with": fits or None,
        "mine": li["owner_id"] == viewer_id, "flagged": bool(li["flagged"]) if li["owner_id"] == viewer_id else False}


async def _critic(db: Database, project_id: str, version: int) -> str | None:
    """The independent critic's verdict on this version, from the agent's hand-over message."""
    for m in await db.all("SELECT data FROM messages WHERE project_id = ? AND role = 'agent' ORDER BY created_at DESC LIMIT 30", project_id):
        d = m["data"] or {}
        c = d.get("critic") or {}
        # the critic's own version when it has one (a run cut short hands over v2 with v1's review), and a stand-in
        # for a reviewer that did not answer is no verdict
        if c and c.get("version", d.get("version")) == version:
            return None if c.get("reviewer") == "unavailable" else c.get("verdict")
    return None


async def _listing_titles(db: Database, project_id: str, order: dict[str, Any] | None, name: str, title: str | None) -> tuple[str, str]:
    """The card's name in English and in Russian, from the intake of the request the part was born from: the open
    model's catalog title in each language (unless the two models disagreed about the part), else the customer's own
    words in theirs, else Spark's English name, else `name`. The owner's own `title` names it in its own language.
    No appliance in it: the card shows what it fits apart."""
    born = order if (((order or {}).get("intake") or {}).get("request") or {}).get("kind") == "photo" else store._dec(await db.one(
        "SELECT * FROM shop_orders WHERE project_id = ? AND json_extract(intake, '$.request.kind') = 'photo' ORDER BY created_at LIMIT 1", project_id))
    data = (born or {}).get("intake") or {}
    part, cls = data.get("part") or {}, data.get("classify") or {}
    if cls.get("error") or (data.get("review") or {}).get("code") == "safety_disagreement":
        cls = {}
    lang = str(data.get("language") or "")[:2].lower()
    own = part.get("name_user") or ""
    fallback = UNNAMED if name in UNNAMED else (name, name)

    def cap(x: str) -> str:
        x = x.strip()
        return x[:1].upper() + x[1:]

    en = cap(cls.get("title_en") or (own if lang == "en" else "") or part.get("name_en") or fallback[0])
    ru = cap(cls.get("title_ru") or (own if lang == "ru" else "") or fallback[1])
    if title and title.strip():
        en, ru = (en, cap(title)) if re.search(r"[А-Яа-яЁё]", title) else (cap(title), ru)
    return en, ru


async def share(db: Database, owner_id: str, project_id: str, *, public: bool, order: dict[str, Any] | None = None,
                title: str | None = None, brand: str | None = None, models: list[str] | None = None, part_numbers: list[str] | None = None,
                category: str | None = None) -> dict[str, Any]:
    """The listing of a part. Its version is the one a print passed QC on (else the newest); public needs that QC pass.
    What the intake read (part name, appliance, part number, category) fills the fields left empty."""
    p = await db.one("SELECT * FROM projects WHERE id = ?", project_id)
    if not p or not p["version"]:
        raise HTTPException(404, "no such project with a model")
    passed = store._dec(await db.one("SELECT * FROM shop_orders WHERE project_id = ? AND json_extract(qc, '$.pass') = 1 "
                                     "ORDER BY updated_at DESC LIMIT 1", project_id))
    if public and not passed:
        raise _fail(409, "a public listing needs one printed part that passed QC", "not_verified")
    version = (passed or {}).get("version") or (order or {}).get("version") or p["version"]
    src = order or passed or store._dec(await db.one("SELECT * FROM shop_orders WHERE project_id = ? ORDER BY created_at DESC LIMIT 1", project_id))
    data = (src or {}).get("intake") or {}
    part, app = data.get("part") or {}, data.get("appliance") or {}
    prog = await db.one("SELECT checks FROM programs WHERE project_id = ? AND version = ?", project_id, version)
    qc_rep = (passed or {}).get("qc") or {}
    verified = {"printable": ((prog or {}).get("checks") or {}).get("ok"), "critic": await _critic(db, project_id, version),
                "qc_pass": bool(passed), "qc_max_mm": qc_rep.get("max_mm"), "qc_tolerance_mm": qc_rep.get("tolerance_mm"),
                "qc_order": (passed or {}).get("ref")}
    cls = data.get("classify") or {}
    name = (title or cls.get("title_ru" if data.get("language") == "ru" else "title_en") or part.get("name_user") or part.get("name_en")
            or p["title"]).strip()
    name = name[:1].upper() + name[1:]
    en, ru = await _listing_titles(db, project_id, order, name, title)
    return await store.save_listing(
        db, project_id=project_id, version=version, owner_id=owner_id, title=name, title_en=en, title_ru=ru,
        brand=brand if brand is not None else app.get("brand") or "", models=models if models is not None else [m for m in [app.get("model")] if m],
        part_numbers=part_numbers if part_numbers is not None else [n for n in [part.get("part_number")] if n],
        category=category if category is not None else cls.get("category") or p["pack"] or "",
        material=(passed or src or {}).get("material") or "PLA", cover=p["cover"], verified=verified, public=public)


class ListingIn(BaseModel):
    project_id: str
    title: str | None = Field(default=None, max_length=120)
    brand: str | None = Field(default=None, max_length=60)
    models: list[str] | None = None
    part_numbers: list[str] | None = None
    category: str | None = Field(default=None, max_length=40)
    public: bool = True


@router.post("/listings")
async def share_listing(body: ListingIn, user=Depends(user_dep)):
    """A verified part becomes a catalog entry other people can order: printable checks, the critic, a passed QC.
    Sharing your private listing ("Your parts") again with public=true publishes it."""
    db = await store.shop_db()
    p = await db.one("SELECT id FROM projects WHERE id = ? AND user_id = ?", body.project_id, user["id"])
    if not p:
        raise HTTPException(404, "no such project of yours")
    li = await share(db, user["id"], body.project_id, public=body.public, title=body.title, brand=body.brand, models=body.models,
                     part_numbers=body.part_numbers, category=body.category)
    return listing_out(li, user["id"])


@router.get("/listings")
async def catalog(request: Request, response: Response, q: str = "", mine: bool = False):
    """The public catalog by brand, model or part number prefix ('sms46', '006114'); mine=true: your own listings."""
    db = await store.shop_db()
    if mine:
        user = await hooks.current_user(request, response)
        return [listing_out(li, user["id"]) for li in await store.my_listings(db, user["id"])]
    return [listing_out(li, None) for li in await store.search_listings(db, q)]


@router.get("/listings/{listing_id}")
async def listing_detail(listing_id: str, user=Depends(user_dep)):
    db = await store.shop_db()
    li = await store.get_listing(db, listing_id)
    if not li or not ((li["public"] and not li["flagged"]) or li["owner_id"] == user["id"]):
        raise HTTPException(404, "listing not found")
    return listing_out(li, user["id"])


@router.get("/listings/{listing_id}/quote")
async def listing_quote(listing_id: str, quantity: int = 1, delivery: Delivery = "courier", user=Depends(user_dep)):
    """The instant range for a catalog part before ordering it (no new-part fee; its project itself stays private)."""
    db = await store.shop_db()
    li = await store.get_listing(db, listing_id)
    if not li or not ((li["public"] and not li["flagged"]) or li["owner_id"] == user["id"]):
        raise HTTPException(404, "listing not found")
    q = await _instant(db, li["project_id"], li["version"], user["id"], quantity=max(1, min(200, quantity)), material=li["material"],
                       delivery=delivery, new_part=False)
    if q is None:
        raise _fail(409, "no mass estimate for this part", "no_estimate")
    return await _priced_for(db, q, user)


class ListingOrder(BaseModel):
    quantity: int = Field(default=1, ge=1, le=200)
    delivery: Delivery = "courier"
    contact: str = Field(default="", max_length=200)


@router.post("/listings/{listing_id}/order")
async def order_listing(listing_id: str, body: ListingOrder, request: Request, user=Depends(user_dep)):
    """Reorder, or buy someone's verified part: no design step and no new-part fee; the pinned version is sliced and
    quoted in the background, with the instant range in the answer right away. An Idempotency-Key answers a retry with
    the first order."""
    db = await store.shop_db()
    li = await store.get_listing(db, listing_id)
    if not li or not ((li["public"] and not li["flagged"]) or li["owner_id"] == user["id"]):
        raise HTTPException(404, "listing not found")

    async def place() -> dict[str, Any]:
        await order_cap(db, user, body.quantity)
        _, org = await store.role(db, user["id"])
        en, ru = card_titles(li)
        req = {"kind": "listing", "text": f"Reorder of a catalog part: {en}", "quantity": body.quantity, "photos": []}
        data = {"request": req, "refuse": False, "review": None, "part": {"name_en": en, "quantity": body.quantity},
                "appliance": {"brand": li["brand"], "model": ", ".join(li["models"] or [])}}
        o = await store.create_order(db, user_id=user["id"], org_id=org, project_id=li["project_id"], version=li["version"], listing_id=listing_id,
                                     intake=data, quantity=body.quantity, material=li["material"], delivery={"method": body.delivery},
                                     customer={"contact": body.contact.strip()}, code="ordered_catalog",
                                     params={"title": li["title"], "title_en": en, "title_ru": ru},
                                     quote=await _instant(db, li["project_id"], li["version"], user["id"], quantity=body.quantity, material=li["material"],
                                                          delivery=body.delivery, new_part=False) or {})
        autoquote.spawn(o["id"], autoquote.begin(o["id"]))
        return o

    async def again(order_id: str) -> dict[str, Any] | None:
        return await store.get(db, order_id)

    o = await idempotency.once(user["id"], f"shop.listing:{listing_id}", idempotency.key_of(request), place, again)
    return await present(db, o, "customer")


class ReportIn(BaseModel):
    reason: str = Field(default="", max_length=500)


REPORT_NETWORKS = 3  # anonymous reporters, from this many networks, hide a listing before the operator looks at it
REPORTS_PER_DAY = 10  # one person's reports, over all listings


@router.post("/listings/{listing_id}/report")
async def report_listing(listing_id: str, body: ReportIn, user=Depends(user_dep)):
    """Takedown request (a trademark on the part, a design right, a safety worry). A signed-in person's report hides
    it from the catalog at once, until the farm operator looks at it. An anonymous visitor costs nothing to make again,
    so their reports queue for the operator and hide the part only once they come from REPORT_NETWORKS networks.
    One report per person and listing, REPORTS_PER_DAY a day."""
    db = await store.shop_db()
    li = await store.get_listing(db, listing_id)
    if not li or not li["public"]:
        raise HTTPException(404, "listing not found")
    reports = li.get("reports") or []
    if any(r.get("by") == user["id"] for r in reports):
        return {"ok": True, "flagged": bool(li["flagged"])}
    day = await db.one("SELECT COUNT(*) AS n FROM shop_listings, json_each(shop_listings.reports) r "
                       "WHERE json_extract(r.value, '$.by') = ? AND json_extract(r.value, '$.at') > ?", user["id"], now() - 86400)
    if day and day["n"] >= REPORTS_PER_DAY:
        raise _fail(429, "too many reports today; the farm is looking at the ones you sent", "too_many_reports")
    anon = user.get("tier", "anon") == "anon"
    reports = reports + [{"by": user["id"], "reason": body.reason.strip(), "at": now(), "anon": anon, "net": user.get("ip")}]
    nets = {r.get("net") for r in reports if r.get("anon")}  # an unknown address is one network
    flagged = bool(li["flagged"]) or not anon or len(nets) >= REPORT_NETWORKS
    await db.update("shop_listings", "id", listing_id, {"reports": reports[-50:], "flagged": int(flagged), "updated_at": now()})
    return {"ok": True, "flagged": flagged}


class FlagIn(BaseModel):
    flagged: bool


@router.post("/ops/listings/{listing_id}/flag")
async def flag_listing(listing_id: str, body: FlagIn, user=Depends(operator_dep)):
    db = await store.shop_db()
    if not await store.get_listing(db, listing_id):
        raise HTTPException(404, "listing not found")
    await db.update("shop_listings", "id", listing_id, {"flagged": int(body.flagged), "updated_at": now()})
    li = await store.get_listing(db, listing_id)
    return {**listing_out(li, None), "flagged": bool(li["flagged"]), "reports": li.get("reports")}  # type: ignore[index]


# ------------------------------------------------------------------ repair shops
class OrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact: str = Field(default="", max_length=200)


@router.post("/orgs")
async def create_org(body: OrgIn, user=Depends(user_dep)):
    """A repair shop's account: its people see each other's orders. The workshop tariff waits until the farm has
    checked the workshop (tier 'pending' until scripts/shop_operator.py --workshop sets 'repair_shop')."""
    db = await store.shop_db()
    if await store.org_of(db, user["id"]):
        raise _fail(409, "you are in an organisation already", "org_exists")
    oid = new_id("org_")
    await db.insert("shop_orgs", {"id": oid, "name": body.name.strip(), "kind": "repair_shop", "tier": "pending", "contact": {"text": body.contact.strip()},
                                  "created_at": now()})
    await db.insert("shop_members", {"org_id": oid, "user_id": user["id"], "role": "owner"})
    return await store.org_of(db, user["id"])
