"""Devices over HTTP and the build path from a device graph to a finished board, case and quote.

  GET  /api/catalog/search?q=&basic=   LCSC parts (catalog.search)
  GET  /api/catalog/part/{code}        one part with its pins (catalog.info)
  GET  /api/device/library             modules and primitives for the editor's palette
  GET  /api/projects/{id}/device       the latest device document with the editor's view and the design checks
  PUT  /api/projects/{id}/device       save the person's edit (owner only)
  POST /api/projects/{id}/device/build compile, place, route, check; then the case (background; 'device.build' events)
  GET  /api/projects/{id}/device/quote?qty=  what the finished devices cost: parts, PCB, assembly, case, delivery
  POST /api/projects/{id}/device/order       order them (device_orders)
  GET  /api/device-orders/{id}
  GET  /api/projects/{id}/device/firmware/{name}

build_device() is shared with the designer's build_device tool (agent/device_tools.py): the board grows until tscircuit
can pack and route it, every attempt streams 'pcb.route' frames, the best one is saved as a PCB version (with the
document as device.json) and announced with 'pcb.version'.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from . import catalog, device, device_store, events, pcb_store, pcbapi

log = logging.getLogger(__name__)
router = APIRouter()

ATTEMPTS = 4
GROW = 1.18
_building: dict[str, asyncio.Task] = {}


def _app():
    from formwright import app as app_module

    return app_module


async def _user(request: Request, response: Response) -> dict[str, Any]:
    return await _app().current_user(request, response)


# ------------------------------------------------------------------ catalogue
@router.get("/api/catalog/search")
async def catalog_search(q: str, basic: bool = False, limit: int = 12) -> list[dict[str, Any]]:
    try:
        return await catalog.search(q, limit=limit, basic=basic)
    except catalog.CatalogError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/api/catalog/part/{code}")
async def catalog_part(code: str) -> dict[str, Any]:
    try:
        return await catalog.info(code)
    except catalog.CatalogError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/api/device/library")
async def device_library() -> dict[str, Any]:
    return device.library()


# ------------------------------------------------------------------ the document
async def state_of(project_id: str, row: dict[str, Any] | None = None) -> dict[str, Any]:
    """The latest document, the editor's view of it and the checks; a project without one gets a blank document."""
    row = row or await device_store.latest(project_id)
    doc = (row or {}).get("doc") or device.blank()
    doc, issues = device.normalize(doc)
    parts, more = await device.resolve(doc)
    pcb_row = await pcb_store.get(project_id)
    built_from, stale = None, True
    if pcb_row and "device.json" in (pcb_row.get("artifacts") or {}):
        path = pcb_store.artifact_path(project_id, int(pcb_row["version"]), "device.json")
        try:
            built = json.loads(path.read_text(encoding="utf-8")) if path else {}
            built_from = built.get("_version")
            stale = device.board_key(device.normalize(built)[0]) != device.board_key(doc)
        except (OSError, json.JSONDecodeError, device.DeviceError):
            built_from = None
    checks = pcb_row.get("checks") or {} if pcb_row else {}
    return {
        "version": (row or {}).get("version"),
        "author": (row or {}).get("author"),
        "doc": doc,
        "view": device.view(doc, parts),
        "issues": issues + more,
        "lint": device.lint(doc, parts),
        "building": project_id in _building and not _building[project_id].done(),
        "pcb": {"version": int(pcb_row["version"]), "ok": not checks.get("errors"), "device_version": built_from, "stale": stale,
                "intent_ok": bool((checks.get("intent") or {}).get("ok", True)),
                "size_mm": (checks.get("counts") or {}).get("board_mm")} if pcb_row else None,
    }


class DeviceUpdate(BaseModel):
    doc: dict[str, Any]
    summary: str = ""


@router.get("/api/projects/{project_id}/device")
async def get_device(project_id: str, user=Depends(_user)) -> dict[str, Any]:
    await _app().load_project(project_id, user)
    return await state_of(project_id)


@router.put("/api/projects/{project_id}/device")
async def put_device(project_id: str, body: DeviceUpdate, user=Depends(_user)) -> dict[str, Any]:
    await _app().load_project(project_id, user, write=True)
    try:
        doc, _ = device.normalize(body.doc)
    except device.DeviceError as e:
        raise HTTPException(400, str(e)) from e
    if len(json.dumps(doc)) > 400_000:
        raise HTTPException(400, "the device document is too large")
    version = await device_store.save(project_id, doc, author="user", summary=body.summary or "edited in the node editor")
    await events.emit(project_id, "device.version", {"version": version, "author": "user"})
    return await state_of(project_id)


@router.get("/api/projects/{project_id}/device/versions")
async def device_versions(project_id: str, user=Depends(_user)) -> list[dict[str, Any]]:
    await _app().load_project(project_id, user)
    return await device_store.versions(project_id)


@router.get("/api/projects/{project_id}/device/firmware/{name}")
async def firmware_file(project_id: str, name: str, user=Depends(_user)):
    await _app().load_project(project_id, user)
    row = await device_store.latest(project_id)
    files = (((row or {}).get("doc") or {}).get("firmware") or {}).get("files") or {}
    if name not in files:
        raise HTTPException(404, "no such firmware file")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return PlainTextResponse(files[name], headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------ build
async def build_device(project_id: str, doc: dict[str, Any], *, job_id: str | None = None, status=None,
                       device_version: int | None = None) -> dict[str, Any]:
    """Compile and build a device; the board grows until it packs and routes (ATTEMPTS at most). The best attempt is saved
    as a PCB version. Returns {ok, pcb_version, size_mm, attempts, issues, lint, build (the pcb pipeline's result)}."""
    from .pcb import PcbError, pool

    doc, issues = device.normalize(doc)
    parts, more = await device.resolve(doc)
    issues += more
    lint = device.lint(doc, parts)
    if not [n for n in doc["nodes"] if n["kind"] != "hole"]:
        return {"ok": False, "error": "the device has no parts yet", "issues": issues}
    W, H = device.estimate(doc, parts)
    fixed = bool(doc["board"].get("w") and doc["board"].get("h"))
    attempts: list[dict[str, Any]] = []
    best: tuple[int, dict[str, Any], dict[str, Any]] | None = None

    async def frame(f: dict[str, Any]) -> None:
        await pcbapi.emit_route(project_id, f, job_id)

    for attempt in range(ATTEMPTS):
        comp = device.compile(doc, parts, (W, H))
        await events.emit(project_id, "device.build", {"state": "attempt", "attempt": attempt + 1, "size_mm": [W, H]}, job_id)
        if status:
            await status(f"Placing and routing the board ({W:g} x {H:g} mm)")
        try:
            build = await pool().build(comp["source"], intent=comp["intent"], on_frame=frame, lcsc=comp["lcsc"], name=doc["title"])
        except PcbError as e:
            if e.stage in ("crash", "protocol"):
                build = await pool().build(comp["source"], intent=comp["intent"], on_frame=frame, lcsc=comp["lcsc"], name=doc["title"])
            elif e.stage == "timeout" and not fixed and attempt < ATTEMPTS - 1:
                attempts.append({"size_mm": [W, H], "error": "timeout"})
                W, H = min(device.MAX_W, math.ceil(W * GROW)), min(device.MAX_W, math.ceil(H * GROW))
                continue
            else:
                return {"ok": False, "stage": e.stage, "error": e.message[:1200], **({"hint": e.hint} if e.hint else {}), "issues": issues,
                        "lint": lint, "attempts": attempts, "source": comp["source"]}
        n_err = len(build.get("errors") or []) + int(build.get("suppressed") or 0)
        attempts.append({"size_mm": [W, H], "errors": n_err, "ok": bool(build.get("ok"))})
        if best is None or n_err < best[0]:
            best = (n_err, build, comp)
        if build.get("ok") or fixed or (W >= device.MAX_W and H >= device.MAX_W):
            break
        W, H = min(device.MAX_W, math.ceil(W * GROW)), min(device.MAX_W, math.ceil(H * GROW))
    assert best is not None
    _, build, comp = best
    export = None
    try:
        export = await pool().export(build["circuit_json"])
    except PcbError as e:
        log.warning("device export failed for %s: %s", project_id, e)
    files: dict[str, Any] | None = None
    if export:
        from .agent.pcb_tools import FAB, PREVIEWS

        keep = FAB + PREVIEWS if build.get("ok") else PREVIEWS
        # every LCSC number in the BOM came from the catalogue (catalog.search / info), not from a model's memory
        files = {**export, "lcsc_verified": True, "files": {k: v for k, v in export["files"].items() if k in keep}}
    files = files or {"files": {}}
    files["files"]["device.json"] = json.dumps({**doc, "_version": device_version}, ensure_ascii=False, indent=1)
    version = await pcb_store.save(project_id, source=comp["source"], intent=comp["intent"], build=build, files=files)
    await pcbapi.emit_version(project_id, version, build, job_id)
    return {"ok": bool(build.get("ok")), "pcb_version": version, "size_mm": comp["size"], "attempts": attempts, "issues": issues, "lint": lint,
            "build": build, "doc": doc, "parts": parts, "export_ok": export is not None}


async def make_case(project_id: str, pcb_version: int, *, mockup: bool = True) -> int | None:
    """The snap-fit case of a PCB version as a program version (the studio builds it in the browser, as for slider edits)."""
    from .agent import elec_tools
    from .db import get_db, now

    path = pcb_store.artifact_path(project_id, pcb_version, "board.json")
    if path is None:
        return None
    board = json.loads(path.read_text(encoding="utf-8"))
    source = elec_tools.enclosure_program("board", title=f"{str(board.get('name') or 'Device')[:60]} case", mockup=mockup)
    db = await get_db()
    t = now()
    for _ in range(3):
        version = (await db.one("SELECT COALESCE(MAX(version), 0) AS v FROM programs WHERE project_id = ?", project_id))["v"] + 1  # type: ignore[index]
        try:
            await db.insert("programs", {"project_id": project_id, "version": version, "source": source, "params": {},
                                         "inputs": {"boards": {"board": board}}, "summary": f"case for PCB v{pcb_version}", "checks": None,
                                         "author": "device", "created_at": t})
            break
        except Exception:  # noqa: BLE001 - a concurrent version took the number
            continue
    else:
        return None
    await db.update("projects", "id", project_id, {"version": version, "updated_at": t})
    await events.emit(project_id, "program.updated", {"version": version, "params": {}, "checks": None, "author": "device", "source_changed": True})
    return version


async def _editor_build(project_id: str) -> None:
    row = await device_store.latest(project_id)
    if not row:
        return
    await events.emit(project_id, "device.build", {"state": "start"})
    try:
        res = await build_device(project_id, row["doc"], device_version=int(row["version"]))
        case = None
        if res.get("ok"):
            case = await make_case(project_id, res["pcb_version"])
        b = res.get("build") or {}
        await events.emit(project_id, "device.build", {
            "state": "done", "ok": bool(res.get("ok")), "pcb_version": res.get("pcb_version"), "program_version": case,
            "size_mm": res.get("size_mm"), "attempts": res.get("attempts"),
            "errors": [{k: e.get(k) for k in ("type", "message", "hint")} for e in (b.get("errors") or [])[:6]],
            "error": res.get("error"), "intent_ok": bool((b.get("intent") or {}).get("ok", True))})
    except Exception as e:  # noqa: BLE001 - the editor must hear that the build ended
        log.exception("device build of %s failed", project_id)
        await events.emit(project_id, "device.build", {"state": "done", "ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"})
    finally:
        _building.pop(project_id, None)


@router.post("/api/projects/{project_id}/device/build")
async def start_build(project_id: str, user=Depends(_user)) -> dict[str, Any]:
    await _app().load_project(project_id, user, write=True)
    if project_id in _building and not _building[project_id].done():
        return {"started": False, "building": True}
    if not await device_store.latest(project_id):
        raise HTTPException(400, "no device yet")
    _building[project_id] = asyncio.create_task(_editor_build(project_id))
    return {"started": True}


# ------------------------------------------------------------------ quote and order
# Fab and assembly prices: JLCPCB's public calculator for 2-layer FR-4 1.6 mm, HASL, green, and economic SMT assembly
# (checked 2026-11). Estimates: the binding price is the fab's own at checkout.
PCB_MIN_USD = 4.0          # 5 boards up to 100 x 100 mm
PCB_USD_PER_CM2 = 0.012    # each board beyond the minimum
SMT_SETUP_USD = 8.0
STENCIL_USD = 1.5
JOINT_USD = 0.0017
EXTENDED_FEE_USD = 3.0     # per unique extended-library part
FAB_SHIPPING_USD = 18.0    # JLCPCB -> Kazakhstan, Global Standard Direct
HAND_JOINT_USD = 0.05      # through-hole parts and modules soldered at the workshop
ASSEMBLY_USD = 3.0         # per device: soldering the module, flashing the firmware, test, packing
THT_KINDS = ("button", "header", "jst", "module")


def _case_grams(W: float, H: float, hmax: float) -> tuple[float, float]:
    """A snap case's PLA grams and print minutes from the board size, when no build of the case reports them."""
    wall, floor, c = 2.0, 1.6, 0.5
    ow, oh, oz = W + 2 * (wall + c), H + 2 * (wall + c), hmax + 2.5 + 1.6 + floor + 3.0
    cm3 = (2 * ow * oh * floor + 2 * (ow + oh) * oz * wall) / 1000 * 1.15
    grams = cm3 * 1.24
    return round(grams, 1), round(grams * 2.6 + 12, 0)


def pad_count(node: dict[str, Any], part: dict[str, Any]) -> int:
    """Solder joints of one part: a resolved chip carries its pad geometry (one entry a pad), a catalogue card the count,
    a primitive its package's."""
    pads = part.get("pads")
    if isinstance(pads, dict):
        pads = len(pads)
    return int(pads or {"resistor": 2, "capacitor": 2, "led": 2, "diode": 2, "usb_c": 16, "button": 4, "jst": 2,
                        "header": len(node.get("pins") or []),
                        "module": len(device.MODULES.get(node.get("module") or "", {}).get("pins") or [])}.get(node["kind"], 4))


async def quote_for(project_id: str, qty: int) -> dict[str, Any]:
    from .shop import quote as shop_quote

    row = await pcb_store.get(project_id)
    if row is None or "device.json" not in (row.get("artifacts") or {}):
        raise HTTPException(400, "build the device first")
    v = int(row["version"])
    doc = json.loads(pcb_store.artifact_path(project_id, v, "device.json").read_text(encoding="utf-8"))  # type: ignore[union-attr]
    doc, _ = device.normalize(doc)
    parts, _ = await device.resolve(doc)
    board = json.loads((pcb_store.artifact_path(project_id, v, "board.json") or pcb_store.artifact_path(project_id, v, "device.json")).read_text(encoding="utf-8"))  # type: ignore[union-attr]
    outline = (board.get("pcb") or {}).get("outline") or {}
    W, H = float(outline.get("w") or 40), float(outline.get("h") or 40)
    q = max(1, min(500, int(qty)))
    rate = shop_quote.shop_settings().usd_kzt

    # BOM lines: the same LCSC part on several nodes is one line
    lines: dict[str, dict[str, Any]] = {}
    joints = 0
    hand_joints = 0
    for n in doc["nodes"]:
        k, part = n["kind"], parts.get(n["id"], {})
        if k == "hole":
            continue
        key = part.get("lcsc") or (f"module:{n['module']}" if k == "module" else f"{k}:{n['id']}")
        ln = lines.setdefault(key, {"refs": [], "kind": k, "lcsc": part.get("lcsc"), "mpn": part.get("mpn"), "package": part.get("package"),
                                    "basic": part.get("basic"), "stock": part.get("stock"), "url": part.get("url"), "prices": part.get("prices") or [],
                                    "assembly": "hand" if k in THT_KINDS or part.get("tht") else "smt",
                                    "label": n.get("label") or n.get("value") or n.get("color") or ""})
        ln["refs"].append(n["id"])
        pads = pad_count(n, part)
        if ln["assembly"] == "smt":
            joints += pads
        else:
            hand_joints += pads
    bom = []
    parts_usd = 0.0
    extended = 0
    for ln in lines.values():
        per = len(ln["refs"])
        need = per * q
        unit = catalog.price_at(ln["prices"], need) if ln["prices"] else 0.0
        if ln["kind"] == "header":
            unit = unit * max(1, len(next((n.get("pins") or [] for n in doc["nodes"] if n["id"] == ln["refs"][0]), []))) / 40  # cut from a 1x40 strip
        total = round(unit * need, 3)
        parts_usd += total
        if ln["assembly"] == "smt" and ln["lcsc"] and ln["basic"] is False:
            extended += 1
        bom.append({**{k: ln[k] for k in ("refs", "kind", "lcsc", "mpn", "package", "basic", "stock", "url", "assembly", "label")},
                    "qty_each": per, "qty": need, "unit_usd": round(unit, 4), "total_usd": total,
                    "in_stock": ln["stock"] is None or (ln["stock"] or 0) >= need})
    boards = max(5, q)
    area_cm2 = W * H / 100
    pcb_usd = max(PCB_MIN_USD, boards * area_cm2 * PCB_USD_PER_CM2 + (2.0 if boards > 5 else 0))
    if W > 100 or H > 100:
        pcb_usd *= 1.5
    smt_usd = SMT_SETUP_USD + STENCIL_USD + joints * q * JOINT_USD + extended * EXTENDED_FEE_USD
    hand_usd = hand_joints * q * HAND_JOINT_USD

    # the case: the latest program made from this board, else an estimate from its size
    from .db import get_db

    db = await get_db()
    prog = await db.one("SELECT version, checks, inputs FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", project_id)
    stats = ((prog or {}).get("checks") or {}).get("stats") or {}
    hmax = max([float(c.get("h") or 0) + float(c.get("z0") or 0) for c in board.get("components") or []] or [8.0])
    if stats.get("estGrams"):
        grams, minutes = float(stats["estGrams"]) * 1.1, float(stats.get("estMinutes") or 60) * 1.44
        case_source = "kernel"
    else:
        grams, minutes = _case_grams(W, H, hmax)
        case_source = "estimate"
    case = shop_quote.price(grams=grams, minutes=minutes, quantity=q, delivery="courier", new_part=False)
    case_usd = case["usd"]["parts"]
    delivery_usd = case["usd"]["delivery"]
    assembly_usd = ASSEMBLY_USD * q
    # note: English for the designer and the API; data: the same numbers for the studio to say in its own language
    groups = [
        {"key": "parts", "usd": round(parts_usd, 2), "note": f"{len(bom)} BOM lines from LCSC, {extended} extended",
         "data": {"lines": len(bom), "extended": extended}},
        {"key": "pcb", "usd": round(pcb_usd, 2), "note": f"{boards} boards {W:g} x {H:g} mm, 2 layers, 1.6 mm FR-4",
         "data": {"boards": boards, "w": W, "h": H}},
        {"key": "smt", "usd": round(smt_usd, 2), "note": f"{joints} SMD joints per board, setup and stencil", "data": {"joints": joints}},
        {"key": "fab_shipping", "usd": FAB_SHIPPING_USD, "note": "JLCPCB to the workshop", "data": {}},
        {"key": "case", "usd": round(case_usd, 2), "note": f"{q} x {case['grams_each']:.0f} g PLA, {case_source}",
         "data": {"qty": q, "grams": round(case["grams_each"]), "source": case_source}},
        {"key": "assembly", "usd": round(assembly_usd + hand_usd, 2), "note": f"{hand_joints} hand joints per device, firmware, test",
         "data": {"joints": hand_joints}},
        {"key": "delivery", "usd": round(delivery_usd, 2), "note": "courier", "data": {}},
    ]
    total = round(sum(g["usd"] for g in groups), 2)
    today = dt.date.today()
    steps = [("pcb_fab", 5), ("pcb_ship", 7), ("case_print", 1), ("assembly", 1), ("delivery", 2)]
    timeline, day = [], 0
    for key, days in steps:
        day += days
        timeline.append({"key": key, "days": days, "by": (today + dt.timedelta(days=day)).isoformat()})
    return {
        "qty": q, "pcb_version": v, "program_version": (prog or {}).get("version"), "board_mm": [W, H], "usd_kzt": rate,
        "groups": groups, "bom": bom, "total_usd": total, "total_kzt": round(total * rate / 10) * 10, "per_device_usd": round(total / q, 2),
        "timeline": timeline, "eta": timeline[-1]["by"], "drc_ok": not (row.get("checks") or {}).get("errors"),
        "unverified": ["fab and assembly prices are estimates from JLCPCB's public calculator; the fab's checkout price is binding",
                       "part prices and stock are LCSC's at the time of this quote"],
    }


@router.get("/api/projects/{project_id}/device/quote")
async def device_quote(project_id: str, qty: int = 5, user=Depends(_user)) -> dict[str, Any]:
    await _app().load_project(project_id, user)
    try:
        return await quote_for(project_id, qty)
    except catalog.CatalogError as e:
        raise HTTPException(502, str(e)) from e


class DeviceOrder(BaseModel):
    qty: int = 5
    name: str = ""
    contact: str = ""
    city: str = ""
    note: str = ""


@router.post("/api/projects/{project_id}/device/order")
async def device_order(project_id: str, body: DeviceOrder, user=Depends(_user)) -> dict[str, Any]:
    await _app().load_project(project_id, user, write=True)
    q = await quote_for(project_id, body.qty)
    if not q["drc_ok"]:
        raise HTTPException(400, "the board still has DRC errors: build a clean version first")
    contact = {k: str(getattr(body, k))[:200] for k in ("name", "contact", "city", "note") if getattr(body, k)}
    order = await device_store.add_order(user_id=user["id"], project_id=project_id, pcb_version=q["pcb_version"],
                                         program_version=q["program_version"], quantity=q["qty"], quote=q, contact=contact,
                                         timeline=q["timeline"])
    await events.emit(project_id, "device.order", {"id": order["id"], "ref": order["ref"]})
    return _order_out(order)


def _order_out(o: dict[str, Any]) -> dict[str, Any]:
    pid, v = o["project_id"], o.get("pcb_version")
    files = {n: pcb_store.artifact_url(pid, v, n) for n in ("gerbers.zip", "bom.csv", "cpl.csv", "board.glb", "pcb_top.svg")
             if v and pcb_store.artifact_path(pid, v, n)}
    return {k: o[k] for k in ("id", "ref", "project_id", "pcb_version", "program_version", "quantity", "status", "quote", "timeline", "created_at")} | {
        "files": files}


@router.get("/api/device-orders/{order_id}")
async def get_order(order_id: str, user=Depends(_user)) -> dict[str, Any]:
    o = await device_store.order(order_id)
    if not o or o["user_id"] != user["id"]:
        raise HTTPException(404, "no such order")
    return _order_out(o)


@router.get("/api/projects/{project_id}/device/orders")
async def project_orders(project_id: str, user=Depends(_user)) -> list[dict[str, Any]]:
    await _app().load_project(project_id, user)
    return [_order_out(o) for o in await device_store.orders_of(user["id"], project_id)]
