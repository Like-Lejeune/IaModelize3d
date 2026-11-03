"""Agent tools for whole devices (pack 'device'): find real parts in the LCSC catalogue, draw the device as a graph of
parts and nets (fw.device/1, formwright/device.py), build it into a placed, routed and checked board, wrap it in a
printed case (pcb_tools.make_enclosure), write its firmware and price it.

The hub (tools.py, prompts.py, loop.py) offers TOOLS (plus pcb_tools' make_enclosure, export_fab and look), hands the
calls named in NAMES to run() and asks finish_gate() before finish. The designer never writes coordinates or TSX: the
document is the design, deviceapi.build_device compiles it. Every write_device is a device version the node editor
shows at once ('device.version'); the person's own edits in the editor arrive as versions by 'user' and are loaded at
the start of the next job.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .. import catalog, device, device_store, events

log = logging.getLogger(__name__)

MAX_DOC = 60_000


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


_S = {"type": "string"}

SEARCH_PARTS = _fn(
    "search_parts",
    "Search the LCSC catalogue (what JLCPCB assembles): part number, LCSC code or keywords such as 'BME280', 'LDO 3.3V SOT-23-5', "
    "'WS2812B-2020', 'SSD1306'. Returns in-stock parts first with package, stock, price and whether it is a JLCPCB basic part "
    "(no extended-part fee). Use part_info before wiring a chip.",
    {"query": _S, "basic": {"type": "boolean", "description": "basic library only (passives, common ICs)"},
     "limit": {"type": "integer", "description": "1-12, default 6"}},
    ["query"])
PART_INFO = _fn(
    "part_info",
    "One LCSC part in full: its pins (number, name and the label you wire as '<node>.<label>'; a name that repeats such as GND "
    "is one reference for all of them), footprint size and height, stock, price breaks and datasheet link. Only parts with an "
    "EasyEDA footprint can go on the board.",
    {"lcsc": {**_S, "description": "LCSC code, e.g. C92489"}},
    ["lcsc"])
WRITE_DEVICE = _fn(
    "write_device",
    "Write the device graph (fw.device/1, see the pack rules): every part as a node and every connection as a net. It is saved "
    "as a device version the person sees in the node editor at once, checked (unknown pins, missing pull-ups, decoupling, LED "
    "resistors, USB-C CC) and not built: build_device builds it. Give the whole `doc`, or `edits` on the current one.",
    {"doc": {"type": "object", "description": "the whole document {schema:'fw.device/1', title, summary, board, nodes, nets}"},
     "edits": {"type": "array", "description": "instead of doc, in order: {op:'add', node:{...}} | {op:'remove', id} | {op:'set', id, "
                                               "fields:{...}} | {op:'connect', pins:[...], name?} | {op:'disconnect', pins:[...]}",
               "items": {"type": "object"}},
     "summary": {**_S, "description": "one line for the person: what this version changes (in the user's language)"}},
    ["summary"])
BUILD_DEVICE = _fn(
    "build_device",
    "Build the current device version into a board: parts on an edge placed facing out, the rest packed next to the pins they "
    "connect, autorouted on 2 layers, DRC and intent checked, fab files (Gerber, BOM with LCSC numbers, CPL) for a clean board. "
    "The board grows until it routes. Returns the checks with hints and a picture of the routed board.",
    {"summary": {**_S, "description": "one line for the person (in the user's language)"}},
    [])
WRITE_FIRMWARE = _fn(
    "write_firmware",
    "Write the firmware of the device for its microcontroller, with the pins exactly as wired in the device graph. Saved with the "
    "device (the person downloads it next to the fab files).",
    {"lang": {**_S, "description": "'arduino' (XIAO ESP32-C3/S3, Pico with arduino-pico) | 'micropython' (Pico, Pico W) | 'esphome'"},
     "files": {"type": "object", "description": "file name -> complete content, e.g. {'weather_station.ino': '...'}"},
     "notes": {**_S, "description": "board selection, libraries to install, how to flash, in the user's language"}},
    ["lang", "files"])
QUOTE_DEVICE = _fn(
    "quote_device",
    "What finished devices cost from the latest built board: LCSC parts, PCB, SMT assembly, the printed case, hand assembly and "
    "firmware, delivery; with the BOM lines and the timeline. Call after make_enclosure.",
    {"qty": {"type": "integer", "description": "number of devices, default 5"}},
    [])

TOOLS = [SEARCH_PARTS, PART_INFO, WRITE_DEVICE, BUILD_DEVICE, WRITE_FIRMWARE, QUOTE_DEVICE]
NAMES = {t["name"] for t in TOOLS}


def _as_obj(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return None
    return v


async def run(ctx: Any, state: Any, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    try:
        if name == "search_parts":
            return await _search(args), []
        if name == "part_info":
            return await _info(args), []
        if name == "write_device":
            return await _write(ctx, state, args), []
        if name == "build_device":
            return await _build(ctx, state, args)
        if name == "write_firmware":
            return await _firmware(ctx, state, args), []
        if name == "quote_device":
            return await _quote(ctx, state, args), []
    except catalog.CatalogError as e:
        return {"ok": False, "error": str(e)}, []
    except device.DeviceError as e:
        return {"ok": False, "error": str(e)}, []
    return {"ok": False, "error": f"unknown tool {name}"}, []


# ------------------------------------------------------------------ catalogue
def _short(c: dict[str, Any]) -> dict[str, Any]:
    p = c.get("prices") or []
    return {"lcsc": c.get("lcsc"), "mpn": c.get("mpn"), "package": c.get("package"), "stock": c.get("stock"), "basic": c.get("basic"),
            "usd": catalog.price_at(p, 10) if p else None, "description": (c.get("description") or "")[:140]}


async def _search(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("query") or "").strip()
    if not q:
        return {"ok": False, "error": "query is empty"}
    hits = await catalog.search(q, limit=max(1, min(12, int(args.get("limit") or 6))), basic=bool(args.get("basic")))
    if not hits:
        return {"ok": True, "parts": [], "note": "nothing found: try the bare part number, fewer words, or the function ('LDO 3.3V')"}
    return {"ok": True, "parts": [_short(h) for h in hits]}


async def _info(args: dict[str, Any]) -> dict[str, Any]:
    card = await catalog.info(str(args.get("lcsc") or ""))
    pins = [f"{p['num']}:{p['label']}" + (f" ({p['name']})" if p["name"] != p["label"] else "") for p in card["pins"]]
    return {"ok": True, **{k: card.get(k) for k in ("lcsc", "mpn", "brand", "package", "category", "stock", "basic", "size_mm", "height_mm",
                                                       "datasheet")},
            "description": (card.get("description") or "")[:300], "usd_at_10": catalog.price_at(card.get("prices") or [], 10),
            "pins": pins, "wire_as": sorted(set(catalog.base_label(p["label"]) for p in card["pins"]))}


# ------------------------------------------------------------------ the document
def apply_edits(doc: dict[str, Any], edits: list[Any]) -> tuple[dict[str, Any], list[str]]:
    """Graph operations on a normalized document; returns (new doc, errors). Unknown ops are reported, not guessed."""
    doc = device.clone(doc)
    errors: list[str] = []
    for i, e in enumerate(edits):
        if not isinstance(e, dict):
            errors.append(f"edit {i}: not an object")
            continue
        op = str(e.get("op") or e.get("type") or e.get("action") or "")
        # {"connect": [pins], "name": "GND"} names the op by its key
        for k in ("add", "remove", "set", "connect", "disconnect"):
            if not op and k in e:
                op, v = k, e[k]
                e = {**e, **({"node": v} if k == "add" else {"id": v} if k == "remove" else {"pins": v} if isinstance(v, list) else {})}
        if op == "add" and isinstance(e.get("node"), dict):
            doc["nodes"].append(e["node"])
        elif op == "remove" and e.get("id"):
            nid = str(e["id"])
            doc["nodes"] = [n for n in doc["nodes"] if n["id"] != nid]
            for net in doc["nets"]:
                net["pins"] = [p for p in net["pins"] if p.split(".", 1)[0] != nid]
        elif op == "set" and e.get("id") and isinstance(e.get("fields"), dict):
            node = next((n for n in doc["nodes"] if n["id"] == e["id"]), None)
            if node is None:
                errors.append(f"edit {i}: no node {e['id']}")
            else:
                node.update({k: v for k, v in e["fields"].items() if k not in ("id",)})
        elif op == "connect" and isinstance(e.get("pins"), list):
            pins = [str(p) for p in e["pins"]]
            if e.get("name"):
                # onto a named net: the pins leave whatever other net they were on
                name = str(e["name"])
                for net in doc["nets"]:
                    if net.get("name") != name:
                        net["pins"] = [p for p in net["pins"] if p not in pins]
            doc["nets"].append({"pins": pins, **({"name": str(e["name"])} if e.get("name") else {})})
        elif op == "disconnect" and isinstance(e.get("pins"), list):
            drop = {str(p) for p in e["pins"]}
            for net in doc["nets"]:
                net["pins"] = [p for p in net["pins"] if p not in drop]
        else:
            errors.append(f"edit {i}: unknown or incomplete op {op!r}")
    return doc, errors


async def current(project_id: str) -> tuple[dict[str, Any] | None, int | None]:
    row = await device_store.latest(project_id)
    return ((row or {}).get("doc"), (row or {}).get("version"))


async def _write(ctx: Any, state: Any, args: dict[str, Any]) -> dict[str, Any]:
    doc = _as_obj(args.get("doc"))
    edits = _as_obj(args.get("edits"))
    errors: list[str] = []
    if not isinstance(doc, dict) and edits:
        cur, _ = await current(ctx.project_id)
        if not cur:
            return {"ok": False, "error": "no device yet: pass the whole doc"}
        cur, _ = device.normalize(cur)
        doc, errors = apply_edits(cur, edits if isinstance(edits, list) else [])
    if not isinstance(doc, dict):
        return {"ok": False, "error": "pass the whole device document as `doc` (an object), or `edits` on the current one"}
    if len(json.dumps(doc)) > MAX_DOC:
        return {"ok": False, "error": "the document is too large: at most 40 parts and 30 nets"}
    doc.setdefault("title", ctx.project.get("title") or "Device")
    norm, issues = device.normalize(doc)
    if not norm["nodes"]:
        return {"ok": False, "error": "the device has no valid parts", "issues": issues}
    # keep the firmware and the editor's positions of nodes that survive
    cur, _ = await current(ctx.project_id)
    if cur:
        if cur.get("firmware") and not norm.get("firmware"):
            norm["firmware"] = cur["firmware"]
        ui = {n["id"]: n.get("ui") for n in cur.get("nodes") or [] if n.get("ui")}
        # a part the person placed on the board stays where they put it
        placed = {n["id"]: n.get("pcb") for n in cur.get("nodes") or [] if n.get("pcb")}
        for n in norm["nodes"]:
            if n["id"] in ui and not n.get("ui"):
                n["ui"] = ui[n["id"]]
            if n["id"] in placed and not n.get("pcb"):
                n["pcb"] = placed[n["id"]]
        if placed and not (norm["board"].get("w") and norm["board"].get("h")):
            for k in ("w", "h"):
                if (cur.get("board") or {}).get(k):
                    norm["board"][k] = cur["board"][k]
        # the person's zones and hand-drawn traces stay unless the designer wrote its own lists; traces of parts it removed go
        if "zones" not in doc and cur.get("zones"):
            norm["zones"] = [z for z in cur["zones"] if z["kind"] == "keepout" or any(n.get("name") == z["net"] for n in norm["nets"])]
            if not norm["zones"]:
                del norm["zones"]
        if "routes" not in doc and cur.get("routes"):
            ids = {n["id"] for n in norm["nodes"]}
            kept = [r for r in cur["routes"] if r["from"].split(".", 1)[0] in ids and r["to"].split(".", 1)[0] in ids]
            if kept:
                norm["routes"] = kept
    parts, more = await device.resolve(norm)
    issues += more
    lint = device.lint(norm, parts)
    version = await device_store.save(ctx.project_id, norm, author="agent", summary=str(args.get("summary") or "")[:200])
    await events.emit(ctx.project_id, "device.version", {"version": version, "author": "agent"}, ctx.job_id)
    state.device = {"version": version, "built": False}
    out: dict[str, Any] = {"ok": not issues, "version": version, "nodes": len(norm["nodes"]), "nets": len(norm["nets"])}
    if errors:
        out["edit_errors"] = errors
    if issues:
        out["issues"] = [f"{i['code']} {i['ref']}: {i['msg']}" for i in issues][:12]
    if lint:
        out["design_warnings"] = [f"{w['code']} {w['ref']}: {w['msg']}" for w in lint][:12]
    out["next"] = "fix the issues, then write_device again" if issues else "build_device"
    return out


# ------------------------------------------------------------------ build
async def _build(ctx: Any, state: Any, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .. import deviceapi, pcb_store
    from . import pcb_tools

    doc, version = await current(ctx.project_id)
    if not doc:
        return {"ok": False, "error": "no device yet: write_device first"}, []
    res = await deviceapi.build_device(ctx.project_id, doc, job_id=ctx.job_id, status=ctx.status, device_version=version)
    if res.get("pcb_version") is None:
        return {k: v for k, v in res.items() if k in ("ok", "stage", "error", "hint", "issues", "attempts")}, []
    v = res["pcb_version"]
    build = res["build"]
    row = await pcb_store.get(ctx.project_id, v)
    board = pcb_tools._board(ctx.project_id, v)
    state.pcb.update({"version": v, "source": row["source"] if row else None, "ok": bool(build.get("ok")), "made": True,
                      "intent_ok": bool((build.get("intent") or {}).get("ok", True))})
    state.device = {"version": version, "built": True, "pcb_version": v}
    pcb_tools._fact(state, v, build, board, (state.pcb.get("enclosure") or {}).get("mockup"))
    out = pcb_tools.brief(build, v, board, set((row or {}).get("artifacts") or {}))
    out["attempts"] = res.get("attempts")
    out["device_version"] = version
    if res.get("lint"):
        out["design_warnings"] = [f"{w['code']} {w['ref']}: {w['msg']}" for w in res["lint"]][:8]
    if not build.get("ok"):
        out["next"] = ("change the graph: fewer or smaller parts, another edge for a connector, or a fixed larger board (board.w/h), "
                       "then write_device and build_device again; the hints name the parts in the way")
    else:
        out["next"] = "make_enclosure, then write_firmware and quote_device"
    path = pcb_store.artifact_path(ctx.project_id, v, "pcb_top.svg")
    images = await pcb_tools._top_view(ctx, v, path.read_text(encoding="utf-8") if path else None)
    return out, images


# ------------------------------------------------------------------ firmware and quote
async def _firmware(ctx: Any, state: Any, args: dict[str, Any]) -> dict[str, Any]:
    files = _as_obj(args.get("files"))
    if not isinstance(files, dict) or not files:
        return {"ok": False, "error": "files must be an object {name: content}"}
    doc, _ = await current(ctx.project_id)
    if not doc:
        return {"ok": False, "error": "no device yet: write_device first"}
    doc = device.clone(doc)
    doc["firmware"] = {"lang": str(args.get("lang") or "arduino"), "files": {str(k): str(v) for k, v in files.items()},
                       **({"notes": str(args["notes"])} if args.get("notes") else {})}
    norm, _ = device.normalize(doc)
    version = await device_store.save(ctx.project_id, norm, author="agent", summary="firmware")
    await events.emit(ctx.project_id, "device.version", {"version": version, "author": "agent", "firmware": True}, ctx.job_id)
    state.device = {**(state.device or {}), "firmware": True}
    names = list(norm.get("firmware", {}).get("files", {}))
    return {"ok": True, "version": version, "files": names,
            "links": {n: f"/api/projects/{ctx.project_id}/device/firmware/{n}" for n in names}}


async def _quote(ctx: Any, state: Any, args: dict[str, Any]) -> dict[str, Any]:
    from fastapi import HTTPException

    from .. import deviceapi

    try:
        q = await deviceapi.quote_for(ctx.project_id, int(args.get("qty") or 5))
    except HTTPException as e:
        return {"ok": False, "error": str(e.detail)}
    state.device = {**(state.device or {}), "quoted": True}
    return {"ok": True, "qty": q["qty"], "total_usd": q["total_usd"], "total_kzt": q["total_kzt"], "per_device_usd": q["per_device_usd"],
            "groups": {g["key"]: g["usd"] for g in q["groups"]}, "eta": q["eta"], "board_mm": q["board_mm"],
            "bom_lines": len(q["bom"]), "out_of_stock": [b["mpn"] for b in q["bom"] if not b["in_stock"]]}


# ------------------------------------------------------------------ for the hub and the loop
async def finish_gate(ctx: Any, state: Any) -> list[str]:
    """The board must be built from the latest device version (and clean), the case made from it, and the firmware written."""
    from . import pcb_tools

    if state.finish_attempts > pcb_tools.BLOCK_ATTEMPTS:
        return []
    from .. import pcb_store

    doc, version = await current(ctx.project_id)
    if not doc:
        return ["no device yet: write_device, then build_device"]
    row = await pcb_store.get(ctx.project_id)
    built = None
    if row:
        path = pcb_store.artifact_path(ctx.project_id, int(row["version"]), "device.json")
        try:
            built = json.loads(path.read_text(encoding="utf-8")).get("_version") if path else None
        except (OSError, json.JSONDecodeError):
            built = None
    reasons: list[str] = []
    # the firmware alone does not change the board
    if built is None or (built != version and _board_changed(doc, built and await device_store.get(ctx.project_id, built))):
        reasons.append(f"device version {version} is not built yet: build_device")
        return reasons
    if not (doc.get("firmware") or {}).get("files"):
        reasons.append("no firmware yet: write_firmware for its microcontroller")
    reasons += await pcb_tools.finish_gate(ctx, state)
    return reasons


def _board_changed(doc: dict[str, Any], row: dict[str, Any] | None) -> bool:
    if not row:
        return True
    return device.board_key(doc) != device.board_key(row.get("doc") or {})


async def load(project_id: str, state: Any) -> None:
    from . import pcb_tools

    await pcb_tools.load(project_id, state)
    doc, version = await current(project_id)
    if doc:
        state.device = {"version": version, "firmware": bool((doc.get("firmware") or {}).get("files"))}


async def user_changes(project_id: str) -> tuple[list[str], dict[str, Any] | None]:
    """What the person changed in the node editor since the designer's last version: (lines, the latest document), or
    ([], None) when the latest version is the designer's own or there is none of theirs to compare with."""
    rows = await device_store.versions(project_id)
    if not rows or rows[-1]["author"] != "user":
        return [], None
    mine = next((r for r in reversed(rows) if r["author"] != "user"), None)
    if mine is None:
        return [], None
    old, new = await device_store.get(project_id, mine["version"]), await device_store.latest(project_id)
    if not old or not new:
        return [], None
    return device.changes(old["doc"], new["doc"]), new["doc"]


async def context_lines(project_id: str, state: Any) -> list[str]:
    """The current device graph for the designer, the person's own edits marked, then the board and the case."""
    from . import pcb_tools

    row = await device_store.latest(project_id)
    lines: list[str] = []
    if row:
        doc = dict(row["doc"])
        fw = doc.pop("firmware", None)
        # the hand-drawn traces as their ends only: their corners are the person's, write_device keeps them
        routes = doc.pop("routes", None) or []
        zones = doc.pop("zones", None) or []
        for n in doc.get("nodes") or []:
            n.pop("ui", None)
        lines.append(f"# Current device: version {row['version']}; write_device edits apply to it\n```json\n"
                     f"{json.dumps(doc, ensure_ascii=False, separators=(',', ':'))}\n```")
        if zones:
            lines.append("# Zones the person drew (`zones`, kept by write_device): " + "; ".join(
                f"{z['net']} pour on the {z['layer']}" + (" over the whole board" if not z.get("rect") else f" in {z['rect']}") if z["kind"] == "pour"
                else f"keepout on {'+'.join(z['layers'])} in {z['rect']}" for z in zones))
        if routes:
            lines.append(f"# {len(routes)} traces drawn by the person on the board (`routes`, kept by write_device; every part is pinned): "
                         + ", ".join(f"{r['from']}-{r['to']}" for r in routes[:40]) + (" ..." if len(routes) > 40 else ""))
        edits, _ = await user_changes(project_id)
        if edits:
            lines.append("# The person edited the device in the editor since your last version. Keep every one of these changes "
                         "unless the request says otherwise (parts with a `pcb` placement were put there by hand: never move them; "
                         "`routes` are traces they drew: keep them), "
                         "and build_device again before finishing if parts, nets or placements changed:\n"
                         + "\n".join(f"- {e}" for e in edits))
        if fw:
            hand = edits and any(e.startswith("firmware file") for e in edits)
            if hand:
                # their code is the starting point now: the designer sees it whole
                lines.append("# Firmware edited by the person (write_firmware from this text, keep their changes):\n"
                             + "\n".join(f"## {n}\n```\n{t[:12000]}\n```" for n, t in (fw.get("files") or {}).items()))
            else:
                lines.append(f"# Firmware ({fw.get('lang')}): " + ", ".join(fw.get("files") or {}) + " (write_firmware replaces it)")
    p = state.pcb
    if p.get("version"):
        lines.append(f"# Latest board: PCB version {p['version']} ({'DRC clean' if p.get('ok') else 'DRC errors'}, intent "
                     f"{'ok' if p.get('intent_ok') else 'not met'})")
    case = p.get("enclosure") or {}
    if case:
        lines.append(f"# Case: program version {case['version']} made from PCB version {case['pcb_version']}")
    return lines


def handover(ending: str, state: Any, language: str | None) -> str:
    from . import pcb_tools

    return pcb_tools.handover(ending, state, language)
