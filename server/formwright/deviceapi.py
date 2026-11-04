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

build_device() is shared with the designer's build_device tool (agent/device_tools.py): the compiler's placer puts the free
parts on the board the estimate says, the board grows only if the router cannot join them, every attempt streams 'pcb.route'
frames, the best one is saved as a PCB version (with the document as device.json) and announced with 'pcb.version'.
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

from . import accessories, catalog, device, device_store, events, pcb_store, pcbapi

log = logging.getLogger(__name__)
router = APIRouter()

ATTEMPTS = 5
GROW = 1.1  # per side: 1.18 took a board that just failed to route from 58 x 51 to 69 x 61 mm, +42% area for a few millimetres
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
    try:
        from . import device_rules

        rules = device_rules.check(doc, parts)
    except Exception:  # noqa: BLE001 - the editor still gets its document when a rule trips over a graph
        log.exception("device rules failed for %s", project_id)
        rules = []
    return {
        "version": (row or {}).get("version"),
        "author": (row or {}).get("author"),
        "doc": doc,
        "view": device.view(doc, parts),
        "issues": issues + more,
        "lint": device.lint(doc, parts),
        "rules": rules,
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
    # a board size the person sets (or keeps after setting it) is theirs: the build keeps it, where the designer's only
    # starts the growth
    prev = ((await device_store.latest(project_id)) or {}).get("doc") or {}
    pb, nb = prev.get("board") or {}, doc["board"]
    if nb.get("w") and nb.get("h") and ((pb.get("w"), pb.get("h")) != (nb["w"], nb["h"]) or pb.get("locked")):
        nb["locked"] = True
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
    """Compile and build a device; the board grows until it routes (ATTEMPTS at most). The best attempt is saved
    as a PCB version, its board.json dressed by device.dress_board (faces, accessories). Returns {ok (DRC clean and the
    intent kept), drc_ok, intent_ok, drc {errors (root causes), cascaded (not-connected that follow), warnings},
    pcb_version, size_mm, attempts [{size_mm, errors, cascaded, ok, first?}], growth (device.growth_report: how far the
    board grew past the size asked for and why, or past the chosen concept's board; also the first line of lint, so the
    designer reads it), issues, lint, build (the pipeline's result)}."""
    from .pcb import PcbError, pool

    doc, issues = device.normalize(doc)
    parts, more = await device.resolve(doc)
    issues += more
    lint = device.lint(doc, parts)
    if not [n for n in doc["nodes"] if n["kind"] != "hole"]:
        return {"ok": False, "error": "the device has no parts yet", "issues": issues}
    W, H = device.estimate(doc, parts)
    # only the person's size is a cage: the designer's board.w/h is where the growth starts (device.estimate)
    fixed = bool(doc["board"].get("locked"))
    attempts: list[dict[str, Any]] = []
    best: tuple[int, dict[str, Any], dict[str, Any]] | None = None

    async def frame(f: dict[str, Any]) -> None:
        await pcbapi.emit_route(project_id, f, job_id)

    relaxed: dict[str, dict[str, Any]] = {}  # capacitors whose length limit the router could not meet: lifted, then a warning
    gap: float | None = None  # the placer's gap when the same board is tried with its free parts arranged another way
    rearranged = False
    for attempt in range(ATTEMPTS):
        W, H = device.room(doc, parts, (W, H))  # a grown round board's rim can still shut a part out: never one for the packer
        comp = device.compile(doc, parts, (W, H), relaxed=set(relaxed), gap=gap)
        if comp.get("unplaced"):  # the person's fixed board, or the largest there is: said in plain words, no packing errors
            return {"ok": False, "stage": "placement", "error": device.no_room(doc, (W, H), comp["unplaced"]), "issues": issues, "lint": lint,
                    "attempts": attempts, "source": comp["source"]}
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
        # errors: the root causes the build lists (what pcb.version and the designer's brief count); cascaded: the 'not
        # connected' errors that only follow from routing being skipped. A title summing both said '50 DRC errors' for
        # a board whose version said 4.
        try:  # placement errors told in the designer's terms: the placed part to move, never the module on its edge
            device.build_hints(doc, parts, (W, H), build.get("errors") or [])
        except Exception:  # noqa: BLE001 - the worker's own hints stay
            log.exception("device build hints failed for %s", project_id)
        n_err, cascaded = len(build.get("errors") or []), int(build.get("suppressed") or 0)
        attempts.append({"size_mm": [W, H], "errors": n_err, "cascaded": cascaded, "ok": bool(build.get("ok")),
                         **({"first": str(build["errors"][0].get("message") or "")[:160]} if n_err else {}),
                         **({"gap": gap} if gap is not None else {}),
                         **({"relaxed": sorted(relaxed)} if relaxed else {})})
        if best is None or (n_err, cascaded) < best[0]:
            best = ((n_err, cascaded), build, comp)
        if build.get("ok"):
            break
        # a decoupling capacitor's trace over its limit (the router took 31.9 mm round a crowded corner between two pads
        # 1.6 mm apart) never fails a device: the same board again with the limit lifted, and a warning. Growing the board
        # for it only spread the parts further (52 -> 88 x 100 mm in eight builds).
        long = device.long_caps(doc, build.get("errors") or [])
        if long and not set(long) <= set(relaxed):
            relaxed.update(long)
            continue
        # the router tripped over one spot (a via on a pad, two traces too close): the same board arranged another way, once,
        # before a larger one (device_bench: 62 x 62 mm built where growing took it to 69 x 69)
        if not rearranged and device.growable(build.get("errors") or []) and (gap := device.other_gap(doc, parts, (W, H), comp)) is not None:
            rearranged = True
            continue
        # placement errors (overlaps, a part over the edge, a packing that gave up) and routing failures want room: grow
        # and try again; anything else is the same on a larger board
        if fixed or not device.growable(build.get("errors") or []) or (W >= device.MAX_W and H >= device.MAX_W):
            break
        gap = None
        W, H = device.next_size(doc, parts, (W, H), comp, GROW)
    assert best is not None
    _, build, comp = best
    for cap, r in relaxed.items():
        if cap in comp["relaxed"]:
            build.setdefault("warnings", []).append({
                "type": "decoupling_distance_warning", "ref": cap,
                "message": f"{cap} ended {r['length']:g} mm from {r['to'] or 'its chip'}: decoupling works best within {r['max']:g} mm",
                "hint": f"place {(r['to'] or '').split('.')[0] or 'the chip'} and {cap} together, or name the chip in {cap}'s label "
                        f"(e.g. '{(r['to'] or 'U2').split('.')[0]} decoupling') so the compiler groups them; the board was built with the limit lifted"})
    # board.json learns what the graph knows: faces (light, sound, sensor) and the modules fitted by hand
    if build.get("board"):
        device.dress_board(build["board"], doc, parts, build.get("circuit_json") or [])
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
    drc_ok = bool(build.get("ok"))
    intent_ok = bool((build.get("intent") or {}).get("ok", True))
    growth = device.growth_report(doc, parts, tuple(comp["size"]), attempts)
    if growth:  # said once, where the designer reads the build's warnings
        lint = [{"code": "board_grew", "ref": "board", "msg": growth["msg"]}, *lint]
    # ok: a board that is clean AND does what the graph says (edges, the pins that drive LEDs and buttons)
    return {"ok": drc_ok and intent_ok, "drc_ok": drc_ok, "intent_ok": intent_ok, "pcb_version": version, "size_mm": comp["size"], "growth": growth,
            "drc": {"errors": len(build.get("errors") or []), "cascaded": int(build.get("suppressed") or 0),
                    "warnings": len(build.get("warnings") or [])},
            "attempts": attempts, "issues": issues, "lint": lint, "build": build, "doc": doc, "parts": parts, "export_ok": export is not None}


async def make_case(project_id: str, pcb_version: int, *, mockup: bool = True) -> int | None:
    """The snap-fit case of a PCB version as a program version (the studio builds it in the browser, as for slider edits)."""
    from .agent import elec_tools
    from .db import get_db, now

    path = pcb_store.artifact_path(project_id, pcb_version, "board.json")
    if path is None:
        return None
    board = json.loads(path.read_text(encoding="utf-8"))
    db = await get_db()
    # keep the options the designer chose for the last case (its shape, how it mounts, how it sits)
    prev = await db.one("SELECT source FROM programs WHERE project_id = ? AND source LIKE '%lib.elec%' ORDER BY version DESC LIMIT 1", project_id)
    opts = elec_tools.case_options(prev["source"]) if prev else {}
    source = elec_tools.enclosure_program("board", title=f"{str(board.get('name') or 'Device')[:60]} case", mockup=mockup, **opts)
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
        if res.get("drc_ok"):  # a clean board gets its case even when an intent check still complains
            case = await make_case(project_id, res["pcb_version"])
        b = res.get("build") or {}
        await events.emit(project_id, "device.build", {
            "state": "done", "ok": bool(res.get("ok")), "pcb_version": res.get("pcb_version"), "program_version": case,
            "size_mm": res.get("size_mm"), "attempts": res.get("attempts"), "growth": (res.get("growth") or {}).get("msg"),
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
THT_KINDS = ("button", "header", "jst", "module", "accessory")


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
    if node["kind"] == "accessory":  # its connector's pins (the module plugs or solders onto them); a cell's two BAT pads
        a = accessories.ACCESSORIES.get(node.get("accessory") or "") or {}
        return 2 if a.get("connect") == "module_bat" else len(a.get("pins") or [])
    pads = part.get("pads")
    if isinstance(pads, dict):
        pads = len(pads)
    return int(pads or {"resistor": 2, "capacitor": 2, "led": 2, "diode": 2, "usb_c": 16, "button": 4, "jst": 2,
                        "header": len(node.get("pins") or []),
                        "module": len(device.MODULES.get(node.get("module") or "", {}).get("pins") or [])}.get(node["kind"], 4))


def bom_of(doc: dict[str, Any], parts: dict[str, dict[str, Any]], q: int) -> dict[str, Any]:
    """The bill of materials for q devices: {bom: rows, parts_usd (LCSC parts), modules_usd (ready-made modules fitted by
    hand: kind 'accessory' rows with name, url, qty, unit_usd, total_usd), modules (how many), extended, joints (SMD
    per board), hand_joints (per device)}. The same LCSC part on several nodes is one line; an accessory is its own
    line, and its connector on the carrier another."""
    lines: dict[str, dict[str, Any]] = {}
    joints = 0
    hand_joints = 0
    for n in doc["nodes"]:
        k, part = n["kind"], parts.get(n["id"], {})
        if k == "hole":
            continue
        if k == "accessory":
            # a ready-made module bought finished and fitted by hand at the workshop, and its connector on the carrier
            a = accessories.ACCESSORIES[n["accessory"]]
            ln = lines.setdefault(f"accessory:{n['accessory']}", {
                "refs": [], "kind": "accessory", "accessory": n["accessory"], "lcsc": None, "mpn": a["name"], "package": None, "basic": None,
                "stock": None, "url": a.get("url"), "prices": part.get("prices") or [{"qty": 1, "usd": a["price_usd"]}], "assembly": "hand",
                "label": n.get("label") or a["name"], "pins_each": 0})
            ln["refs"].append(n["id"])
            hand_joints += pad_count(n, part)
            conn = part.get("connector")
            if conn and a["connect"] in ("header", "jst"):
                cl = lines.setdefault(f"{conn.get('lcsc')}:{n['id']}", {
                    "refs": [], "kind": "header" if a["connect"] == "header" else "jst", "lcsc": conn.get("lcsc"), "mpn": conn.get("mpn"),
                    "package": conn.get("package"), "basic": conn.get("basic"), "stock": conn.get("stock"), "url": conn.get("url"),
                    "prices": conn.get("prices") or [], "assembly": "hand", "label": f"{n['id']} connector", "pins_each": len(a["pins"])})
                cl["refs"].append(n["id"])
            continue
        key = part.get("lcsc") or (f"module:{n['module']}" if k == "module" else f"{k}:{n['id']}")
        ln = lines.setdefault(key, {"refs": [], "kind": k, "lcsc": part.get("lcsc"), "mpn": part.get("mpn"), "package": part.get("package"),
                                    "basic": part.get("basic"), "stock": part.get("stock"), "url": part.get("url"), "prices": part.get("prices") or [],
                                    "assembly": "hand" if k in THT_KINDS or part.get("tht") else "smt",
                                    "label": n.get("label") or n.get("value") or n.get("color") or "", "pins_each": len(n.get("pins") or [])})
        ln["refs"].append(n["id"])
        pads = pad_count(n, part)
        if ln["assembly"] == "smt":
            joints += pads
        else:
            hand_joints += pads
    bom = []
    parts_usd = modules_usd = 0.0
    extended = 0
    for ln in lines.values():
        per = len(ln["refs"])
        need = per * q
        unit = catalog.price_at(ln["prices"], need) if ln["prices"] else 0.0
        if ln["kind"] == "header":
            unit = unit * max(1, ln["pins_each"]) / 40  # cut from a 1x40 strip
        total = round(unit * need, 3)
        if ln["kind"] == "accessory":
            modules_usd += total
        else:
            parts_usd += total
        if ln["assembly"] == "smt" and ln["lcsc"] and ln["basic"] is False:
            extended += 1
        name = ln["mpn"] if ln["kind"] in ("accessory", "module") else " ".join(x for x in (ln["label"], ln["mpn"] or ln["kind"]) if x)
        bom.append({**{k: ln[k] for k in ("refs", "kind", "lcsc", "mpn", "package", "basic", "stock", "url", "assembly", "label")},
                    **({"accessory": ln["accessory"], "note": "ready-made module, bought finished and fitted by hand: in the order"}
                       if ln.get("accessory") else {}),
                    "name": name, "in_order": True, "qty_each": per, "qty": need, "unit_usd": round(unit, 4), "total_usd": total,
                    "in_stock": ln["stock"] is None or (ln["stock"] or 0) >= need})
    n_modules = sum(len(ln["refs"]) for ln in lines.values() if ln["kind"] == "accessory")
    # what each device arrives with, one line a BOM row: the summary says this, not what it guesses (the LiPo is in)
    in_order = [f"{', '.join(b['refs'])}: {b['qty_each']} x {b['name']}" for b in bom]
    return {"bom": bom, "in_order": in_order, "parts_usd": parts_usd, "modules_usd": modules_usd, "modules": n_modules, "extended": extended,
            "joints": joints, "hand_joints": hand_joints}


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
    bm = bom_of(doc, parts, q)
    bom, parts_usd, modules_usd, n_modules = bm["bom"], bm["parts_usd"], bm["modules_usd"], bm["modules"]
    extended, joints, hand_joints = bm["extended"], bm["joints"], bm["hand_joints"]
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
    hmax = max([float(c.get("h") or 0) + float(c.get("z0") or 0) for c in board.get("components") or []]
               + [float(a.get("h") or 0) + float(a.get("z0") or 0) for a in board.get("accessories") or [] if a.get("mount") == "board"] or [8.0])
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
    lcsc_lines = len([b for b in bom if b["kind"] != "accessory"])
    groups = [
        {"key": "parts", "usd": round(parts_usd, 2), "note": f"{lcsc_lines} BOM lines from LCSC, {extended} extended",
         "data": {"lines": lcsc_lines, "extended": extended}},
        # ready-made modules (an OLED, a probe, a cell): bought finished, fitted by hand, in the order like every other line
        *([{"key": "modules", "usd": round(modules_usd, 2), "note": f"{n_modules} ready-made modules fitted by hand",
            "data": {"count": n_modules}}] if n_modules else []),
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
        "groups": groups, "bom": bom, "in_order": bm["in_order"], "total_usd": total, "total_kzt": round(total * rate / 10) * 10, "per_device_usd": round(total / q, 2),
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
