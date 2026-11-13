"""The automatic steps of an order: read the request, then start the designer or quote straight away, watch the
design job, and slice for the firm quote. A ready model (a studio or chat order) is sliced while the intake reads
it: the binding price does not wait on the model call, and Pay waits on its safety verdict instead (flow.safety).
One step per order runs at a time, one OrcaSlicer run at a time on the whole server (a slice takes 2-42 s and a
small VPS has no room for two).

Tasks live in memory: after a restart `reconcile` (called lazily from the operator's queue and the order page)
picks up every order whose step was cut short, and a step that failed stays failed until its input changes. It also
moves quotes past their valid_until to expired; a requote brings one back.
"""
from __future__ import annotations

import asyncio
import logging
import weakref
from collections.abc import Coroutine
from typing import Any

from formwright import events, quotas
from formwright.db import Database, now

from . import flow, intake as intake_mod, quote, store

log = logging.getLogger("formwright.shop")

QUOTE_VALID_S = 7 * 86400
RETRY_S = 600  # a step that failed for a passing reason (quota, slicer) is tried again after this long
WATCH_ROUNDS = 240  # x 15 s: an hour of design, questions included

_tasks: dict[str, asyncio.Task] = {}
_gates: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()


class QuoteError(Exception):
    """str(e) is what a customer may read; `detail` what the operator's problem row and the log get."""

    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.detail = detail or message


def _hooks() -> Any:
    from . import routes  # the hooks live with the router, where tests swap them

    return routes.hooks


def slice_gate() -> asyncio.Semaphore:
    """One slicer run at a time (per event loop, so each test's loop gets its own)."""
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = asyncio.Semaphore(1)
    return gate


def running(order_id: str) -> bool:
    t = _tasks.get(order_id)
    return bool(t and not t.done())


def spawn(order_id: str, step: Coroutine[Any, Any, Any]) -> bool:
    """Runs one automatic step of an order in the background; False (and nothing runs) when one is running already."""
    if running(order_id):
        step.close()
        return False

    async def guarded() -> None:
        try:
            await step
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - a background step must not die silently
            log.exception("shop step failed for order %s", order_id)
            await _step_failed(order_id, e)
        finally:
            if _tasks.get(order_id) is task:
                _tasks.pop(order_id, None)

    task = asyncio.get_running_loop().create_task(guarded())
    _tasks[order_id] = task
    return True


async def _step_failed(order_id: str, e: Exception) -> None:
    """The order's problem row, so the operator sees it and reconcile waits for RETRY_S instead of restarting it on every poll."""
    try:
        db = await store.shop_db()
        o = await store.get(db, order_id)
        if o and o["status"] in flow.OPEN:
            await problem(db, o, "step_failed", f"{type(e).__name__}: {e}")
    except Exception:  # noqa: BLE001 - the database that failed the step may fail this too
        log.exception("order %s: its failure could not be recorded", order_id)


async def drain(timeout: float = 30.0) -> None:
    """Waits for every running step (tests, shutdown), `timeout` seconds in all: a hung step is left running."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while (pending := [t for t in _tasks.values() if not t.done()]) and loop.time() < deadline:
        await asyncio.wait(pending, timeout=deadline - loop.time())


# ------------------------------------------------------------------ problems the operator sees
async def problem(db: Database, o: dict[str, Any], code: str, detail: str, *, retry: bool = True, **extra: Any) -> dict[str, Any]:
    """Records why an automatic step stopped (once per cause, so the timeline is not flooded)."""
    old = o.get("problem") or {}
    p = {"code": code, "detail": detail[:300], "at": now(), "retry_at": now() + RETRY_S if retry else None, **extra}
    if old.get("code") != code or old.get("version") != extra.get("version"):
        await store.log(db, o["id"], o["status"], o["status"], "system", None, code="problem", params={"code": code, "detail": detail[:200]})
    return await store.patch(db, o["id"], {"problem": p})


def _stuck(o: dict[str, Any], version: int | None = None) -> bool:
    """A failed step that should not run again yet: same input, and not time to retry."""
    p = o.get("problem") or {}
    if not p:
        return False
    if version is not None and p.get("version") is not None and p["version"] != version:
        return False  # a new model version: worth another try
    return p.get("retry_at") is None or p["retry_at"] > now()


# ------------------------------------------------------------------ slicing and quoting
async def printer_for(db: Database, material: str, printer_id: str | None = None) -> dict[str, Any] | None:
    """The given farm printer, else one loaded with this material (idle first), else any that is not in maintenance."""
    await store.ensure(db)
    if printer_id:
        return await db.one("SELECT * FROM shop_printers WHERE id = ?", printer_id)
    return (await db.one("SELECT * FROM shop_printers WHERE material = ? AND state != 'maintenance' ORDER BY state = 'idle' DESC, name LIMIT 1", material)
            or await db.one("SELECT * FROM shop_printers WHERE state != 'maintenance' ORDER BY state = 'idle' DESC, name LIMIT 1"))


def fingerprint_of(printer: dict[str, Any] | None) -> dict[str, Any] | None:
    fp = (printer or {}).get("fingerprint")
    return fp if isinstance(fp, dict) and fp else None


async def slice_for(project_id: str, version: int, printer: dict[str, Any] | None, material: str) -> dict[str, Any]:
    """OrcaSlicer on this printer's preset with its fingerprint (the farm's A1 preset when no printer is set up)."""
    preset = (printer or {}).get("preset_id") or quote.shop_settings().farm_preset
    fp = fingerprint_of(printer)
    async with slice_gate():
        sl = await _hooks().slice(project_id, version, preset, material, fp)
    return {**sl, "shop_printer_id": (printer or {}).get("id"), "fingerprint": fp}


def same_slice(sl: dict[str, Any] | None, printer: dict[str, Any], version: int | None) -> bool:
    """The quote's slice is the file this printer would print: same printer, same fingerprint, same version."""
    sl = sl or {}
    return (bool((sl.get("files") or {}).get("gcode")) and sl.get("shop_printer_id") == printer["id"]
            and (sl.get("fingerprint") or None) == fingerprint_of(printer) and (sl.get("version") in (None, version)))


async def customer_kind(db: Database, user_id: str) -> str:
    """The workshop tariff is for a repair shop the farm has checked (its tier 'repair_shop'): one anybody makes with
    POST /orgs is 'pending' and pays the consumer price."""
    org = await store.org_of(db, user_id)
    return "repair_shop" if org and org["kind"] == "repair_shop" and org["tier"] == "repair_shop" else "consumer"


async def requote(order_id: str, *, material: str | None = None, quantity: int | None = None, delivery: str | None = None,
                  printer_id: str | None = None, manual: tuple[float, float] | None = None, actor: str = "system",
                  actor_id: str | None = None) -> dict[str, Any]:
    """A binding quote for the order's model: the pinned version for a catalog part, the project's newest otherwise.
    `manual` (grams, minutes): an operator's own numbers when this server has no slicer."""
    db = await store.shop_db()
    o = await store.get(db, order_id)
    if not o:
        raise flow.FlowError("not_found", "order not found")
    if o["status"] not in flow.OPEN and o["status"] != "expired":
        raise flow.FlowError("guard", "the order is past quoting")
    p = await db.one("SELECT version FROM projects WHERE id = ?", o["project_id"])
    version = o["version"] if o.get("listing_id") else (p or {}).get("version")
    if not version:
        raise QuoteError("no_model", "there is no model to quote yet")
    # "choose for me": a requote that names no material is in the one the intake picked (flow.material_due)
    material = (material or flow.material_due(o) or o["material"] or "PLA").upper()
    if material not in quote.MATERIALS:
        raise QuoteError("bad_material", f"we print {', '.join(quote.MATERIALS)}")
    quantity = max(1, min(200, int(quantity or o["quantity"] or 1)))
    method = delivery or (o.get("delivery") or {}).get("method") or "courier"
    printer = await printer_for(db, material, printer_id)
    listing = await store.get_listing(db, o["listing_id"]) if o.get("listing_id") else None
    kw = dict(quantity=quantity, customer=await customer_kind(db, o["user_id"]), new_part=listing is None, delivery=method,
              listing_royalty=bool(listing and listing["public"] and listing["owner_id"] != o["user_id"]),
              queue_hours=await store.queue_hours(db), printers=await store.printers_online(db))
    sl = None
    if manual:
        q = quote.manual(manual[0], manual[1], material=material, **kw)
    else:
        try:
            sl = await slice_for(o["project_id"], version, printer, material)
            q = quote.firm(sl, material=material, **kw)
        except Exception as e:  # noqa: BLE001 - SliceError, GeomError, a slice without numbers: all mean no firm quote
            raise QuoteError("slice_failed", "the slicer could not price this model; try again in a few minutes", f"{type(e).__name__}: {e}"[:300]) from e
        sl["version"] = version
    q.update({"version": version, "valid_until": now() + QUOTE_VALID_S, "quoted_at": now()})
    fields: dict[str, Any] = {"quote": q, "version": version, "material": material, "quantity": quantity,
                              "delivery": {**(o.get("delivery") or {}), "method": method}, "problem": {}}
    if sl is not None:
        fields["slice"] = sl
    said = {"grams": q["grams_each"], "minutes": q["minutes_each"], "quantity": quantity, "total": q["total"], "total_usd": q["usd"]["total"],
            "currency": q.get("currency") or "KZT",
            "by": "orca" if q["source"] == "orca" else "operator"}
    if o["status"] == "quoted":
        # the slice took seconds: a customer who paid meanwhile keeps the quote they paid for
        o = await store.patch_if(db, order_id, fields, "quoted")
        await store.log(db, order_id, "quoted", "quoted", actor, actor_id, code="requoted", params=said)
        return o
    if o["status"] == "expired":
        # a fresh slice and a new valid_until: the order can be paid again
        return await store.move(db, order_id, "quoted", actor, actor_id, code="requoted", params=said, fields=fields)
    if o["status"] == "needs_info":
        await store.move(db, order_id, "designing", "system", code="design_done")
    return await store.move(db, order_id, "quoted", "operator" if actor == "operator" else "system", actor_id, code="quoted", params=said,
                            fields=fields)


async def quote_step(order_id: str) -> None:
    """requote() in the background: a failure becomes the order's problem, not an exception."""
    db = await store.shop_db()
    try:
        await requote(order_id)
    except (QuoteError, flow.FlowError) as e:
        o = await store.get(db, order_id)
        if o and o["status"] in flow.OPEN and getattr(e, "code", "") != "conflict":
            p = await db.one("SELECT version FROM projects WHERE id = ?", o["project_id"])
            await problem(db, o, e.code, getattr(e, "detail", str(e)), retry=e.code == "slice_failed",
                          version=o["version"] if o.get("listing_id") else (p or {}).get("version"))


# ------------------------------------------------------------------ the first step after a request
def _read(intake: dict[str, Any]) -> bool:
    return isinstance(intake.get("refuse"), bool)


# the quoting step's own problems: the intake, once it reads the request, leaves them for the operator
QUOTE_PROBLEMS = ("slice_failed", "no_model", "bad_material", "guard", "design_unfinished", "design_unreviewed")


async def _read_request(db: Database, o: dict[str, Any], user: dict[str, Any]) -> dict[str, Any] | quotas.QuotaExceeded:
    """Muse Spark 1.3 reads the request (the safety gate), and its verdict goes on the order: the intake, the journal
    line, a refusal, a hold for the operator. Returns the order as it is then, or the quota error that kept the model
    from running (the caller records it, after a quote racing it has landed)."""
    order_id = o["id"]
    req = (o.get("intake") or {}).get("request") or {}
    photos = []
    for ph in req.get("photos") or []:
        a = await db.one("SELECT * FROM assets WHERE id = ?", ph.get("id"))
        if a:
            photos.append({**a, "role": ph.get("role", "part")})
    try:
        result = await _hooks().intake(user, req.get("text") or "", photos)
    except quotas.QuotaExceeded as e:
        return e
    except Exception as e:  # noqa: BLE001 - no answer means the safety gate did not run: the operator decides
        log.warning("intake failed for %s: %s: %s", o["ref"], type(e).__name__, e)
        result = intake_mod.combine(e, None)
    # what the operator wrote meanwhile (a review) stays, and so does a material the customer picked meanwhile on
    # the price card (the request's): read the order again after the model's seconds
    fresh = await store.get(db, order_id) or o
    req = (fresh.get("intake") or {}).get("request") or req
    data = {**(fresh.get("intake") or {}), **result, "request": req, "read_at": now()}
    fields: dict[str, Any] = {"intake": data}
    if (fresh.get("problem") or {}).get("code") not in QUOTE_PROBLEMS:
        fields["problem"] = {}
    # a ready model is quoted meanwhile: that quote decides the quantity and the material (_follow_material)
    if req.get("kind") != "project":
        if not req.get("quantity") and (data.get("part") or {}).get("quantity"):
            fields["quantity"] = data["part"]["quantity"]
        if not req.get("material") and data.get("material"):
            fields["material"] = data["material"]
    o = await store.patch(db, order_id, fields)
    en, ru = intake_mod.titles(data, intake_mod.title_for(data))
    said = ({"code": "intake_unread", "params": {"error": str(data["error"])[:200]}} if data.get("error") else
            {"code": "intake_read", "params": {"model": data.get("model") or "", "title": intake_mod.title_for(data), "title_en": en, "title_ru": ru,
                                          "title_fr": intake_mod.title_fr(data, en)}})
    await store.log(db, order_id, "requested", "requested", "system", None, data={"refuse": data.get("refuse"), "review": data.get("review")}, **said)
    if req.get("kind") != "project" and (title := intake_mod.title_for(data, "")):
        await db.update("projects", "id", o["project_id"], {"title": title, "updated_at": now()})
    if data.get("refuse") and o["status"] in ("requested", "designing", "quoted"):
        # quoted meanwhile too (a ready model, or a hand quote): a safety refusal takes the price off the table
        try:
            return await store.move(db, order_id, "refused", "system", code="refused_safety", params={"reason": str(data.get("reason") or "")[:300]})
        except flow.FlowError:
            return await store.get(db, order_id) or o  # cancelled in that moment: nothing left to refuse
    if data.get("review") and not data.get("reviewed") and o["status"] in flow.OPEN:
        await store.log(db, order_id, o["status"], o["status"], "system", None, code="held",
                        params={"review": data["review"].get("code"), "why": str(data["review"].get("why") or "")[:300]})
    return o


async def _follow_material(db: Database, order_id: str) -> None:
    """A ready model ordered with "choose for me" is quoted in the order's material while the intake reads it; the
    material the intake chose (PETG for a dishwasher part) gets its own quote once it is known. When that slice fails,
    the order keeps a problem and Pay stays closed (flow.material_due): reconcile tries again at its retry time."""
    o = await store.get(db, order_id)
    if not o or ((o.get("intake") or {}).get("request") or {}).get("material"):
        return
    m = (o.get("intake") or {}).get("material")
    if m not in quote.MATERIALS:
        return
    if o["status"] == "requested" and m != o["material"]:
        await store.patch(db, order_id, {"material": m})  # no quote yet (the slicer failed): the next try uses it
    elif o["status"] == "quoted" and flow.material_due(o) == m:
        try:
            await requote(order_id, material=m)
        except flow.FlowError as e:  # paid, cancelled or changed meanwhile: nothing left to follow
            log.info("no %s quote for %s: %s", m, o["ref"], e)
        except QuoteError as e:
            log.warning("no %s quote for %s: %s", m, o["ref"], e)
            fresh = await store.get(db, order_id)
            if fresh and fresh["status"] == "quoted":
                await problem(db, fresh, e.code, e.detail, retry=e.code == "slice_failed", material=m)


async def follow_step(order_id: str) -> None:
    """The quote in the material the intake chose, tried again (its slice failed the first time)."""
    await _follow_material(await store.shop_db(), order_id)


async def _held_up(db: Database, order_id: str, e: quotas.QuotaExceeded) -> None:
    o = await store.get(db, order_id)
    if o and o["status"] in ("requested", "quoted"):
        await problem(db, o, getattr(e, "code", "quota"), str(e))


async def read_step(order_id: str) -> None:
    """The intake of a ready model's order that is quoted already (after a restart, or a quota that held it up): Pay
    waits on this."""
    db = await store.shop_db()
    o = await store.get(db, order_id)
    if not o or o["status"] not in ("requested", "quoted") or _read(o.get("intake") or {}):
        return
    user = await db.one("SELECT * FROM users WHERE id = ?", o["user_id"])
    if not user:
        return
    res = await _read_request(db, o, user)
    if isinstance(res, quotas.QuotaExceeded):
        await _held_up(db, order_id, res)
        return
    await _follow_material(db, order_id)


async def begin(order_id: str) -> None:
    """requested -> refused | held for the operator | designing (a new part) | quoted (a part that has a model).
    A ready model is quoted and read at the same time; a catalog part was read when its card was made."""
    db = await store.shop_db()
    o = await store.get(db, order_id)
    if not o or o["status"] != "requested":
        return
    user = await db.one("SELECT * FROM users WHERE id = ?", o["user_id"])
    if not user:
        return
    data = o.get("intake") or {}
    req = data.get("request") or {}
    if req.get("kind") == "project":
        if _read(data):
            await quote_step(order_id)  # read before (a restart, the operator's approval): the quote is what is left
            return
        # OrcaSlicer prices it while Muse Spark 1.3 reads it: the price is there in seconds, Pay waits for the verdict
        quoted, res = await asyncio.gather(quote_step(order_id), _read_request(db, o, user), return_exceptions=True)
        for r in (quoted, res):
            if isinstance(r, BaseException) and not isinstance(r, quotas.QuotaExceeded):
                raise r
        if isinstance(res, quotas.QuotaExceeded):
            await _held_up(db, order_id, res)  # after the quote, whose fields would clear the problem again
            return
        await _follow_material(db, order_id)
        return
    if not o.get("listing_id") and not _read(data):
        res = await _read_request(db, o, user)
        if isinstance(res, quotas.QuotaExceeded):
            await problem(db, o, getattr(res, "code", "quota"), str(res))
            return
        o, data = res, res.get("intake") or {}
        if o["status"] != "requested":
            return  # refused just now, or cancelled while the model read it: nothing to start
    if data.get("refuse"):
        await store.move(db, order_id, "refused", "system", code="refused_safety", params={"reason": str(data.get("reason") or "")[:300]})
        return
    if data.get("review") and not data.get("reviewed"):
        return  # held for the operator (the journal says so)
    if o.get("listing_id"):
        await quote_step(order_id)
        return
    project = await db.one("SELECT * FROM projects WHERE id = ?", o["project_id"])
    # the order's quantity and material (the form's, what the intake read, or what the operator set): not a design question
    brief = intake_mod.design_brief(data, req.get("text") or "", o["ref"], quantity=o["quantity"], material=o["material"])
    part_photos = [ph["id"] for ph in req.get("photos") or [] if ph.get("role", "part") == "part"]
    try:
        # the brief is English for the model; the run speaks to the customer in the language the intake read, and opens
        # with the customer's own words
        job = await _hooks().start_design(user, project, brief, part_photos, str(data.get("language") or "").strip() or None,
                                          shown=intake_mod.shown_line(data, o["ref"]))
    except quotas.QuotaExceeded as e:
        await problem(db, o, getattr(e, "code", "quota"), str(e))
        return
    try:
        await store.move(db, order_id, "designing", "system", code="designing", data={"job_id": job}, fields={"problem": {}})
    except Exception:
        # cancelled in the moment the job started, or the database failed: it must not run on, because the order still
        # says 'requested' and the next try would start a second design
        try:
            await _hooks().cancel_job(job, o["user_id"])
        except Exception:  # noqa: BLE001
            log.exception("order %s: design job %s could not be stopped", o["ref"], job)
        raise
    await watch_design(order_id, o["project_id"], job)


async def watch_design(order_id: str, project_id: str, job_id: str) -> None:
    """Follows the design job: a question makes the order needs_info, the answer brings it back, the end quotes it."""
    db = await store.shop_db()
    for _ in range(WATCH_ROUNDS):
        o = await store.get(db, order_id)
        if not o or o["status"] not in ("designing", "needs_info"):
            return  # cancelled or refused meanwhile
        j = await db.one("SELECT status FROM jobs WHERE id = ?", job_id)
        if not j or j["status"] not in ("running", "waiting"):
            break
        try:
            if j["status"] == "waiting" and o["status"] == "designing":
                await store.move(db, order_id, "needs_info", "system", code="asked")
            elif j["status"] == "running" and o["status"] == "needs_info":
                await store.move(db, order_id, "designing", "system", code="answered")
        except flow.FlowError:
            return
        await events.wait(project_id, 15)
    else:
        return  # still going after an hour: reconcile looks again later
    o = await store.get(db, order_id)
    if not o or o["status"] not in ("designing", "needs_info"):
        return
    p = await db.one("SELECT version FROM projects WHERE id = ?", project_id)
    if not (p or {}).get("version"):
        await problem(db, o, "no_model", "the design ended without a model; the operator or the customer takes it from here", retry=False, version=0)
        return
    if await _unfinished(db, o, p["version"]):
        return
    await quote_step(order_id)


async def _unfinished(db: Database, o: dict[str, Any], version: int) -> bool:
    """A design that stopped early (budget, deadline, a crash) can leave a version that fails its printability checks:
    no payable quote for it. The operator looks first and can still quote it by hand."""
    prog = await db.one("SELECT checks FROM programs WHERE project_id = ? AND version = ?", o["project_id"], version)
    if ((prog or {}).get("checks") or {}).get("ok") is False:
        await problem(db, o, "design_unfinished", f"v{version} of the design fails its printability checks", retry=False, version=version)
        return True
    if await _unreviewed(db, o["project_id"], version):
        await problem(db, o, "design_unreviewed", f"no reviewer looked at v{version} of the design", retry=False, version=version)
        return True
    return False


async def _unreviewed(db: Database, project_id: str, version: int) -> bool:
    """The agent handed this version over and no reviewer gave a verdict on it (it did not answer, or the run stopped
    before the review). Not payable by itself: the operator looks first and can still quote it by hand."""
    for m in await db.all("SELECT data FROM messages WHERE project_id = ? AND role = 'agent' ORDER BY created_at DESC LIMIT 30", project_id):
        d = m["data"] if isinstance(m["data"], dict) else {}
        c = d.get("critic") or {}
        if d.get("version") != version and c.get("version") != version:
            continue
        return c.get("reviewer") == "unavailable" or c.get("version", d.get("version")) != version or c.get("verdict") not in ("pass", "revise")
    return False


async def _design_job(db: Database, o: dict[str, Any]) -> dict[str, Any] | None:
    for t in reversed(await store.timeline(db, o["id"])):
        if (jid := (t.get("data") or {}).get("job_id")):
            return await db.one("SELECT id, status FROM jobs WHERE id = ?", jid)
    return await db.one("SELECT id, status FROM jobs WHERE project_id = ? AND kind = 'design' ORDER BY created_at DESC LIMIT 1", o["project_id"])


def _expired(o: dict[str, Any]) -> bool:
    until = (o.get("quote") or {}).get("valid_until")
    return o["status"] == "quoted" and bool(until) and until < now()


async def expire(db: Database, orders: list[dict[str, Any]]) -> int:
    """quoted -> expired for the quotes past their valid_until (a requote brings the order back); how many moved."""
    moved = 0
    for o in orders:
        if not _expired(o):
            continue
        try:
            await store.move(db, o["id"], "expired", "system", code="expired")
            moved += 1
        except flow.FlowError:
            pass  # paid or quoted again in that moment
    return moved


async def reconcile(db: Database, orders: list[dict[str, Any]] | None = None) -> int:
    """Starts the step each open order is waiting for when nothing runs it (after a restart, or a watcher that gave up),
    and expires stale quotes. Cheap when there is nothing to do: it is called on every poll of the queue and of an
    order page. Returns how many orders it moved or started a step for."""
    orders = orders if orders is not None else await store.upstream(db)
    started = await expire(db, orders)
    for o in orders:
        if running(o["id"]) or _expired(o):
            continue
        data = o.get("intake") or {}
        if o["status"] == "quoted":
            # a ready model quoted before its intake could run (a restart, a quota): Pay waits on that read
            if (data.get("request") or {}).get("kind") == "project" and not _read(data) and not _stuck(o):
                started += spawn(o["id"], read_step(o["id"]))
            elif flow.material_due(o) and not _stuck(o):
                # "choose for me" whose quote in the intake's material failed: Pay waits on it
                started += spawn(o["id"], follow_step(o["id"]))
            continue
        if o["status"] not in ("requested", "designing", "needs_info"):
            continue
        if o["status"] == "requested":
            # a held ready model is still quoted (its Pay waits for the operator); a held new part waits to be designed
            held = data.get("review") and not data.get("reviewed") and (data.get("request") or {}).get("kind") != "project"
            if held or _stuck(o):
                continue
            started += spawn(o["id"], begin(o["id"]))
            continue
        job = await _design_job(db, o)
        if job and job["status"] in ("running", "waiting"):
            started += spawn(o["id"], watch_design(o["id"], o["project_id"], job["id"]))
            continue
        p = await db.one("SELECT version FROM projects WHERE id = ?", o["project_id"])
        version = (p or {}).get("version") or 0
        if _stuck(o, version):
            continue
        if not version:
            await problem(db, o, "no_model", "the design ended without a model; the operator or the customer takes it from here", retry=False, version=0)
            continue
        if await _unfinished(db, o, version):
            continue
        started += spawn(o["id"], quote_step(o["id"]))
    return started
