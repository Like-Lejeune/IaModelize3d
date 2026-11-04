"""Agent tools for whole devices (pack 'device'): find real parts in the LCSC catalogue, draw the device as a graph of
parts and nets (fw.device/1, formwright/device.py), build it into a placed, routed and checked board, wrap it in a
printed case (pcb_tools.make_enclosure), write its firmware and price it.

The hub (tools.py, prompts.py, loop.py) offers TOOLS (plus pcb_tools' make_enclosure, export_fab and look), hands the
calls named in NAMES to run() and asks finish_gate() before finish. The designer never writes TSX: the document is the
design, deviceapi.build_device compiles it. Every write_device is a device version the node editor shows at once
('device.version'); the person's own edits in the editor arrive as versions by 'user' and are loaded at the start of the
next job. Three checks stand between a design and finish besides the board's own: the design rules (device_rules, C4:
design_errors block, design_warnings inform), the firmware check (firmware_check, C3, kept in doc.firmware.check with the
wiring it was made for) and the opening the case gave every face part and accessory (the enclosure findings). Both
checkers are imported lazily: without them the pack works as before.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

from .. import catalog, device, device_concept, device_store, events

log = logging.getLogger(__name__)

MAX_DOC = 60_000
MAX_REQUIREMENTS = 20
FIRMWARE_CHECK_S = 40.0  # the checker answers within 20 s (C3); a hung one must not hold the job
# what the case must give a face part (board.json access, C2a) and how the enclosure check names it
OPENING = {"light": ("light_window", "opening over the light"), "sound": ("sound_grille", "sound grille"),
           "sensor": ("sensor_window", "opening for the sensor"), "display": ("display_window", "window in the lid"),
           "key": ("key_plate", "plate for the key switch")}
# findings only a case engine that knows face parts and accessories reports: without any of them, their absence says nothing
FACE_FINDINGS = {"display_window", "sound_grille", "sensor_window", "cable_exit", "battery_space", "key_plate"}
LIGHT_SKIN_MM = 0.6  # the most plastic a light still shows through (the enclosure check's own line)


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


_S = {"type": "string"}

SEARCH_PARTS = _fn(
    "search_parts",
    "Search the LCSC catalogue (what JLCPCB assembles) with a short query: a part number or LCSC code ('AM312', 'C92489'), or 2-3 "
    "words of the function ('buzzer 3V', 'LDO 3.3V SOT-23', 'NPN SOT-23'); long phrases find nothing. Returns in-stock parts first "
    "with package, stock, price and whether it is a JLCPCB basic part (no extended-part fee). Ready-made modules (OLED displays, "
    "PIR modules, soil probes, LiPo cells, servos) are accessory nodes, not catalogue parts: the note names a matching one. Use "
    "part_info before wiring a chip.",
    {"query": _S, "basic": {"type": "boolean", "description": "basic library only (passives, common ICs)"},
     "limit": {"type": "integer", "description": "1-12, default 6"}},
    ["query"])
PART_INFO = _fn(
    "part_info",
    "One LCSC part in full: its pins (number, name and the label you wire as '<node>.<label>'), footprint size and height, stock, "
    "price breaks, datasheet link, kind_hint (npn, pnp, nmos, pmos, diode, led, rgb_led, buzzer_active, buzzer_passive, sensor, "
    "ic...) and current_ma (rated or max current from the description). Repeated signal pins get distinct labels (P1, P2); a "
    "transistor's pins are B/E/C or G/S/D and a diode's A/K when the catalogue says which; a supply name that repeats (GND twice) "
    "is one reference for all of them. Only parts with an EasyEDA footprint can go on the board.",
    {"lcsc": {**_S, "description": "LCSC code, e.g. C92489"}},
    ["lcsc"])
WRITE_DEVICE = _fn(
    "write_device",
    "Write the device graph (fw.device/1, see the pack rules): the concept (uses, at least 3 options, the chosen one), "
    "requirements, every part as a node (modules, chips, primitives, "
    "accessories), every connection as a net, the front panel as node.place or layouts, node.face where the default is wrong. "
    "Saved as a device version the person sees in the node editor at once, checked and not built (build_device builds it). "
    "Returns issues (broken references), design_errors (wrong wiring, missing drivers, unsafe power, no concept: they block "
    "finish, fix them), design_warnings (yours to judge) and the chosen concept in one line. Give the whole `doc`, or `edits` "
    "on the current one (a doc without concept keeps the current one).",
    {"doc": {"type": "object", "description": "the whole document {schema:'fw.device/1', title, summary, board, concept, requirements, nodes, "
                                              "nets, layouts}"},
     "edits": {"type": "array", "description": "instead of doc, in order: {op:'add', node:{...}} | {op:'remove', id} | {op:'set', id, "
                                               "fields:{...}} (place, face too) | {op:'connect', pins:[...], name?} | {op:'disconnect', "
                                               "pins:[...]} | {op:'amps', net or pins, amps} | {op:'zones', zones:[...]} | {op:'requirements', requirements:[...]} | {op:'layouts', layouts:[...]} | "
                                               "{op:'concept', concept:{...}} | {op:'compact'} (the smaller arrangement a board_too_large "
                                               "warning names: applied, the concept's board with it)",
               "items": {"type": "object"}},
     "summary": {**_S, "description": "one line for the person: what this version changes (in the user's language)"}},
    ["summary"])
BUILD_DEVICE = _fn(
    "build_device",
    "Build the current device version into a board: parts on an edge placed facing out, placed parts where the document puts "
    "them, the rest placed by the compiler next to the pins they connect, autorouted on 2 layers, DRC and intent checked, fab files (Gerber, BOM "
    "with LCSC numbers, CPL) for a clean board. The board grows until it routes. ok only with 0 DRC errors and the intent met. "
    "Returns the checks with hints and a picture of the routed board.",
    {"summary": {**_S, "description": "one line for the person (in the user's language)"}},
    [])
WRITE_FIRMWARE = _fn(
    "write_firmware",
    "Write the firmware of the device for its microcontroller, with the pins exactly as wired in the device graph. It is checked "
    "(compiled or linted, its pins against the wiring) and saved with the device (the person downloads it next to the fab files); "
    "ok is false while the check finds errors: fix them and write_firmware again with the whole files.",
    {"lang": {**_S, "description": "'arduino' (XIAO ESP32-C3/S3, Pico with arduino-pico) | 'micropython' (Pico, Pico W) | 'esphome'"},
     "files": {"type": "object", "description": "file name -> complete content, e.g. {'weather_station.ino': '...'}"},
     "notes": {**_S, "description": "board selection, libraries to install, how to flash, in the user's language"}},
    ["lang", "files"])
QUOTE_DEVICE = _fn(
    "quote_device",
    "What finished devices cost from the latest built board: LCSC parts, accessories, PCB, SMT assembly, the printed case, hand "
    "assembly and firmware, delivery; with the BOM lines and the timeline. Call after make_enclosure.",
    {"qty": {"type": "integer", "description": "number of devices, default 5"}},
    [])

SIMULATE_DEVICE = _fn(
    "simulate_device",
    "Run the firmware on a virtual board wired as the device graph, on a virtual clock (a day takes under a second). write_firmware does "
    "the full run by itself: every input pressed in every condition, a probe that stays wet, a day left alone. With no arguments this "
    "repeats it. With `steps` it plays your own scenario and returns what happened: when each load was on, the screen, serial, boots "
    "and sleeps. Use it to check a requirement before you claim it: press start, wait, press stop, press start again.",
    {"steps": {"type": "array", "description": "what happens: {at_s: 45, press: 'SW1'} presses a button and lets go, {at_s: 60, input: 'PR1', value: 1} sets an input: 1 is water "
                                               "or motion; an analog probe takes millivolts, a light sensor lux, a thermistor degrees C. The inputs are listed in simulation.coverage",
               "items": {"type": "object", "properties": {"at_s": {"type": "number"}, "press": _S, "hold_s": {"type": "number"}, "input": _S, "value": {"type": "number"}}, "required": ["at_s"]}},
     "condition": {"type": "object", "description": "inputs that hold a value from the start, e.g. {'LDR1': 0.5} for a dark room"},
     "horizon_s": {"type": "number", "description": "how long to run, seconds of device time, up to 21600"}},
    [])

TOOLS = [SEARCH_PARTS, PART_INFO, WRITE_DEVICE, BUILD_DEVICE, WRITE_FIRMWARE, SIMULATE_DEVICE, QUOTE_DEVICE]
NAMES = {t["name"] for t in TOOLS}
# the hub's finish for a device (tools.py runs it): the gate, then the designer's own self-check in `checked`
FINISH = _fn(
    "finish",
    "Finish the device. Runs the final checks (latest version built clean, no design errors, the case with every opening, firmware "
    "that passes its check); if they pass, the first call returns self_check: the checklist items for the part kinds in your graph. "
    "Check each one, fix what is wrong, then call finish again with `checked`.",
    {"summary": {**_S, "description": "final message to the person, in their language: what the device does, parts, pins, board and "
                                       "case size, firmware, price and date, what is in the order, what is unverified"},
     "checked": {"type": "array", "description": "the self-check: at least one entry for every kind self_check lists, e.g. {kind: 'led', "
                                                 "verdict: 'ok', where: 'LED1-LED3, R1-R3 1k'} or {item: 'device.2', verdict: 'fixed', "
                                                 "where: 'soil.ino:88'}",
                 "items": {"type": "object", "properties": {"kind": _S, "item": _S, "verdict": {"type": "string", "enum": ["ok", "fixed", "n/a"]},
                                                            "where": {**_S, "description": "node / net / file:line"}}}}},
    ["summary"])
SELF_CHECK_ROUNDS = 2   # answers that leave a kind out go back this often; then the finish goes through and says so
SELF_CHECK_FULL = 9500  # characters of checklist sent whole; a larger device gets the items no rule checks


def _parse(text: str) -> tuple[Any, str | None]:
    """JSON a model passed as a string, read as forgivingly as it can be: raw newlines, a code fence, trailing commas. (value, None), or
    (None, what is wrong with it): on 2026-11-04 designers lost 20 turns to a refusal that did not say."""
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    last = ""
    for attempt in (s, re.sub(r",(\s*[}\]])", r"\1", s)):
        try:
            return json.loads(attempt, strict=False), None
        except json.JSONDecodeError as e:
            last = f"{e.msg} at character {e.pos} of {len(attempt)}: ...{attempt[max(0, e.pos - 50):e.pos + 20]}..."
    return None, last


def _as_obj(v: Any) -> Any:
    if isinstance(v, str):
        return _parse(v)[0]
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
        if name == "simulate_device":
            return await _simulate(ctx, state, args), []
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


def _accessory_for(query: str) -> str | None:
    """The accessory (C1d) a query names ('ssd1306 oled', 'PIR', 'soil probe') as "<key> (<name>)", else None."""
    try:
        from .. import accessories

        key = accessories.find(query)
        a = accessories.get(key) if key else None
    except Exception:  # noqa: BLE001 - the library is optional here
        return None
    if not a:
        return None
    # a whole word of the query in the accessory's key or name: 'LED' is in 'OLED', but an LED is not a display
    words = set(re.findall(r"[a-z0-9]+", f"{key} {a['name']}".lower()))
    return f"{key} ({a['name']})" if words & set(re.findall(r"[a-z0-9]+", query.lower())) else None


async def _search(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("query") or "").strip()
    if not q:
        return {"ok": False, "error": "query is empty"}
    hits = await catalog.search(q, limit=max(1, min(12, int(args.get("limit") or 6))), basic=bool(args.get("basic")))
    acc = _accessory_for(q)
    tip = f"a ready-made module fits this: accessory {acc}, as a node {{kind: 'accessory', accessory: '{acc.split(' ', 1)[0]}'}}" if acc else ""
    if not hits:
        return {"ok": True, "parts": [], "note": "nothing found: try the bare part number, 1-3 words, or the function ('LDO 3.3V'); "
                + (tip or "displays, PIR modules, probes, batteries and servos are accessory nodes, not catalogue parts")}
    return {"ok": True, "parts": [_short(h) for h in hits], **({"note": tip} if tip else {})}


async def _info(args: dict[str, Any]) -> dict[str, Any]:
    card = await catalog.info(str(args.get("lcsc") or ""))
    pins = [f"{p['num']}:{p['label']}" + (f" ({p['name']})" if p["name"] != p["label"] else "") for p in card["pins"]]
    return {"ok": True, **{k: card.get(k) for k in ("lcsc", "mpn", "brand", "package", "category", "stock", "basic", "size_mm", "height_mm",
                                                       "datasheet")},
            # C6: what the part is and what it draws, when the catalogue could tell
            **{k: card[k] for k in ("kind_hint", "current_ma", "pin_note") if card.get(k) is not None},
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
        for k in ("add", "remove", "set", "connect", "disconnect", "requirements", "layouts", "concept"):
            if not op and k in e:
                op, v = k, e[k]
                e = {**e, **({"node": v} if k == "add" else {"id": v} if k == "remove" else {"pins": v} if isinstance(v, list) else {})}
        if op in ("requirements", "layouts", "zones") and isinstance(e.get(op), list):
            # document-level lists are replaced whole
            doc[op] = e[op]
        elif op == "concept" and isinstance(e.get("concept"), dict):
            doc["concept"] = e["concept"]
        elif op == "add" and isinstance(e.get("node"), dict):
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
            doc["nets"].append({"pins": pins, **({"name": str(e["name"])} if e.get("name") else {}), **({"amps": e["amps"]} if e.get("amps") else {})})
        elif op == "amps" and (e.get("net") or e.get("pins")):
            # the current of a net that is there: by its name or any pin on it
            pins = {str(p) for p in e.get("pins") or []}
            hit = [net for net in doc["nets"] if (e.get("net") and net.get("name") == e["net"]) or pins & set(net["pins"])]
            if not hit:
                errors.append(f"edit {i}: no net {e.get('net') or sorted(pins)}")
            for net in hit:
                net["amps"] = e.get("amps")
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


def _is_compact(edit: Any) -> bool:
    return isinstance(edit, dict) and edit.get("op") == "compact"


async def compact(doc: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """The edit {op:'compact'}: the smaller arrangement device.compaction found, with the chosen concept's board and module
    edge moved along, so the concept and the board stay one. (doc, what it did)."""
    norm, _ = device.normalize(doc)
    parts, _ = await device.resolve(norm)
    roomy = device.compaction(norm, parts)
    if not roomy:
        return doc, "nothing smaller than this arrangement was found: the board stays as it is"
    out = roomy["doc"]
    aim = device_concept.chosen(out)
    if aim:
        aim["board"] = {**(aim.get("board") or {}), "w": roomy["size"][0], "h": roomy["size"][1]}
        edge = next((n.get("edge") for n in out["nodes"] if n.get("kind") == "module"), None)
        if edge:
            aim["module_edge"] = edge
    return out, f"{roomy['say']}: about {roomy['size'][0]:g} x {roomy['size'][1]:g} mm. Now build_device, make_enclosure, and write_firmware if pins moved"


async def _write(ctx: Any, state: Any, args: dict[str, Any]) -> dict[str, Any]:
    doc = _as_obj(args.get("doc"))
    edits = _as_obj(args.get("edits"))
    errors: list[str] = []
    compacted = ""
    if not isinstance(doc, dict) and edits:
        cur, _ = await current(ctx.project_id)
        if not cur:
            return {"ok": False, "error": "no device yet: pass the whole doc"}
        ncur, _ = device.normalize(cur)
        keep_requirements(ncur, cur)
        ops = edits if isinstance(edits, list) else []
        doc, errors = apply_edits(ncur, [e for e in ops if not _is_compact(e)])
        if any(_is_compact(e) for e in ops):
            doc, compacted = await compact(doc)
    if not isinstance(doc, dict):
        bad = next((f"`{k}` is not valid JSON: {_parse(args[k])[1]}" for k in ("doc", "edits") if isinstance(args.get(k), str) and _parse(args[k])[1]), None)
        return {"ok": False, "error": (bad + ". Send it again, or the changes alone as `edits`: a smaller call is less likely to break") if bad else "pass the whole device document as `doc` (an object), or `edits` on the current one"}
    if not edits:
        # a `doc` with only the nodes being changed replaces the device with them (a timer once lost 8 parts and every net)
        cur, _ = await current(ctx.project_id)
        old = {n.get("id") for n in (cur or {}).get("nodes") or [] if isinstance(n, dict)}
        new = {n.get("id") for n in doc.get("nodes") or [] if isinstance(n, dict)}
        nets = len((cur or {}).get("nets") or [])
        partial = new <= old and len(new) * 2 < len(old) and len(doc.get("nets") or []) * 2 < nets  # a few old parts, nothing new
        if old and (nets and not doc.get("nets") or partial):
            gone = sorted(i for i in old - new if i)
            return {"ok": False, "error": f"this doc would replace the device: it keeps {len(old & new)} of its {len(old)} parts"
                    f"{'' if doc.get('nets') else ' and none of its nets'} (gone: {', '.join(gone[:12])}). Nothing was saved. To change a few "
                    "parts send `edits` ({op:'set', id, fields}); to replace the device, send the whole new doc with its nets."}
    if len(json.dumps(doc)) > MAX_DOC:
        return {"ok": False, "error": "the document is too large: at most 40 parts and 30 nets"}
    doc.setdefault("title", ctx.project.get("title") or "Device")
    # keep the firmware and the editor's positions of nodes that survive
    cur, _ = await current(ctx.project_id)
    concept_defaults(doc, doc if doc.get("concept") is not None else cur or {})
    norm, issues = device.normalize(doc)
    if not norm["nodes"]:
        return {"ok": False, "error": "the device has no valid parts", "issues": issues}
    # what the device must do (C1e): this version's list, else the one before
    keep_requirements(norm, doc if doc.get("requirements") else cur or {})
    # how it is used and what it looks like (device_concept): this version's, else the one before
    concept_src = doc if doc.get("concept") is not None else cur or {}
    keep_concept(norm, concept_src)
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
        cb = cur.get("board") or {}
        if (placed or cb.get("locked")) and not (norm["board"].get("w") and norm["board"].get("h")):
            for k in ("w", "h"):
                if cb.get(k):
                    norm["board"][k] = cb[k]
            if cb.get("shape") and "shape" not in norm["board"]:  # hand-placed parts stand on that outline
                norm["board"].update({k: cb[k] for k in ("shape", "r") if cb.get(k)})
        # the person's own size stays a cage while the designer keeps it; writing another size means they asked for it
        if cb.get("locked") and (norm["board"].get("w"), norm["board"].get("h")) == (cb.get("w"), cb.get("h")):
            norm["board"]["locked"] = True
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
    rules = await design_checks(norm, parts)
    # what finish refuses is an error now, so the designer fixes it before building, not after the case and the firmware
    design_errors = [_line(r) for r in rules if r.get("severity") == "error"] + concept_problems(concept_src) + requirement_problems(norm)
    seen = {(r.get("code"), r.get("ref")) for r in rules}
    # a requirement naming a missing part is an error here (requirement_problems), not the rules' warning of it
    design_warnings = ([_line(r) for r in rules if r.get("severity") != "error" and r.get("code") != "unused_requirement"]
                       + [_line(w) for w in lint if (w.get("code"), w.get("ref")) not in seen])
    version = await device_store.save(ctx.project_id, norm, author="agent", summary=str(args.get("summary") or "")[:200])
    await events.emit(ctx.project_id, "device.version", {"version": version, "author": "agent"}, ctx.job_id)
    state.device = {"version": version, "built": False}
    out: dict[str, Any] = {"ok": not issues and not design_errors, "version": version, "nodes": len(norm["nodes"]), "nets": len(norm["nets"])}
    if errors:
        out["edit_errors"] = errors
    if issues:
        out["issues"] = [f"{i['code']} {i['ref']}: {i['msg']}" for i in issues][:12]
    if design_errors:
        out["design_errors"] = design_errors[:12]
    if design_warnings:
        out["design_warnings"] = design_warnings[:12]
    # told only at the finish, designers wrote them last, to match the code
    untested = [r["id"] for r in requirements_of(norm) if r.get("firmware") and not r.get("test")]
    if untested:
        out["requirements_without_test"] = f"{', '.join(untested)}: write each one's `test` now, before the firmware: the code is written to pass them"
    weak = weakened_tests(state, norm)
    if weak:
        out["tests_weakened"] = weak[:6]
    chosen = device_concept.line(norm)
    if chosen:
        out["concept"] = chosen
    if compacted:
        out["compacted"] = compacted
    fw = (cur or {}).get("firmware") or {}
    if fw.get("files") and wiring(cur or {}) != wiring(norm):
        out["firmware"] = "the wiring changed since the firmware was written: write_firmware again with the pins as wired now"
    out["next"] = ("fix the issues, then write_device again" if issues
                   else "fix the design_errors (they block finish), then write_device again" if design_errors else "build_device")
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
    pcb_tools._fact(state, v, build, board, (state.pcb.get("enclosure") or {}).get("mockup"))
    out = pcb_tools.brief(build, v, board, set((row or {}).get("artifacts") or {}))
    intent = out["intent"]
    if not intent["ok"]:
        # a board that routes with a part where the device cannot use it is not built: finish refuses it, so ok says so now
        out["ok"] = False
        if not out.get("error"):
            i = (intent.get("issues") or [{}])[0]
            out["error"] = (f"intent not met: {i.get('code')} ({i.get('ref')}): {i.get('msg')}" + (f" -> {i['hint']}" if i.get("hint") else ""))[:400]
    state.device = {"version": version, "built": True, "pcb_version": v, "ok": out["ok"]}
    out["attempts"] = res.get("attempts")
    out["device_version"] = version
    if res.get("lint"):
        out["design_warnings"] = [f"{w['code']} {w['ref']}: {w['msg']}" for w in res["lint"]][:8]
    drift = concept_warnings(doc, board or {})
    if drift:
        out["concept_warnings"] = drift
    blocks = (res.get("models") or {}).get("blocks")
    if blocks:
        out["no_3d_model"] = {"parts": blocks, "say": "the catalogue has no 3D model of these: plain blocks in the board view. Give each a model of your own (node.model) in the next write_device"}
    if not build.get("ok"):
        out["next"] = ("move or reshape, never delete a requested function, a decoupling capacitor or a driver: place the parts in the "
                       "way elsewhere, another edge for a connector, or a fixed larger board (board.w/h); then write_device and "
                       "build_device again; the hints name the parts in the way")
    elif not intent["ok"]:
        out["next"] = ("move the part the intent names (the hint says how far): another edge, its place, or a larger board.w/h; then "
                       "write_device and build_device again")
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
    keep_requirements(norm, doc)
    fw = norm.get("firmware") or {}
    check = None
    if fw.get("files"):
        status = getattr(ctx, "status", None)
        if status:
            await status("Checking the firmware")
        # kept with the version (C3), with the wiring it was checked against: finish re-checks only when that changed
        check = await firmware_check(norm, fw)
        if check is not None:
            fw["check"] = check
    sim = None
    if fw.get("files") and (check is None or check["ok"]):
        status = getattr(ctx, "status", None)
        if status:
            await status("Running the firmware on a virtual board")
        sim = await simulation(norm, fw)
        fw["sim"] = sim
        note_tests(state, norm, sim)
    version = await device_store.save(ctx.project_id, norm, author="agent", summary="firmware")
    await events.emit(ctx.project_id, "device.version", {"version": version, "author": "agent", "firmware": True}, ctx.job_id)
    state.device = {**(state.device or {}), "firmware": True, "firmware_ok": None if check is None else check["ok"]}
    names = list(fw.get("files", {}))
    # the check's verdict before the links: the step's summary is this JSON cut at 600 characters
    out: dict[str, Any] = {"ok": check is None or check["ok"], "version": version, "files": names}
    if check is None:
        out["check"] = {"ran": False, "note": "no firmware checker here: read the pins against the graph yourself"}
    else:
        out["check"] = {"ran": True, "ok": check["ok"], "tool": check["tool"], "errors": len(check["errors"]), "warnings": len(check["warnings"])}
        if not check["ok"]:
            out["error"] = (f"the firmware check found {len(check['errors']) or 1} error(s): "
                            f"{_fw_line(check['errors'][0]) if check['errors'] else 'see errors'}")[:400]
            out["errors"] = [_fw_line(e) for e in check["errors"][:12]]
        if check["warnings"]:
            out["warnings"] = [_fw_line(w) for w in check["warnings"][:8]]
    if sim is not None:
        out["simulation"] = sim_view(sim)
        if sim.get("ran") and not sim.get("ok"):
            out["ok"] = False
            errs = [f for f in sim.get("findings") or [] if f.get("severity") == "error"]
            out["error"] = f"it compiles, but running it found {len(errs)} problem(s): {_sim_line(errs[0])}"[:500] if errs else "running it found problems"
    out["links"] = {n: f"/api/projects/{ctx.project_id}/device/firmware/{n}" for n in names}
    out["next"] = ("fix them and write_firmware again with the whole files: finish needs firmware that passes the check"
                   if check is not None and not check["ok"] else
                   "fix what the simulation found (the board or the firmware), then write_firmware again: finish needs a clean run"
                   if sim is not None and sim.get("ran") and not sim.get("ok") else
                   "quote_device, then finish")
    return out


def _sim_line(f: dict[str, Any]) -> str:
    return f"{f.get('code')} {f.get('ref')}: {f.get('msg')}" + (f" Fix: {f['hint']}" if f.get("hint") else "")


def sim_key(doc: dict[str, Any], fw: dict[str, Any]) -> str:
    """What a run depends on: the circuit, the requirements that judge it, the code."""
    return hashlib.sha1(json.dumps([doc.get("nodes"), doc.get("nets"), requirements_of(doc), fw.get("files")], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


async def simulation(doc: dict[str, Any], fw: dict[str, Any]) -> dict[str, Any]:
    """The firmware on its circuit (firmware_sim), as saved with the version; {ran: False, why} when it could not run."""
    try:
        from .. import firmware_sim
    except Exception as e:  # noqa: BLE001 - the pack still works, it just says it did not simulate
        return {"ran": False, "ok": True, "why": f"no simulator here ({type(e).__name__})", "key": sim_key(doc, fw)}
    try:
        parts, _ = await device.resolve(device.clone(doc))
    except Exception as e:  # noqa: BLE001 - a catalogue outage is no verdict on the firmware
        return {"ran": False, "ok": True, "why": f"the parts could not be read ({type(e).__name__})", "key": sim_key(doc, fw)}
    res = await firmware_sim.simulate(doc, parts, fw.get("files") or {}, str(fw.get("lang") or "arduino"))
    res["key"] = sim_key(doc, fw)
    return res


def sim_view(sim: dict[str, Any]) -> dict[str, Any]:
    """A run as the designer reads it: findings first, what each input did, the power budget, what it covers."""
    if not sim.get("ran"):
        return {"ran": False, "why": sim.get("why"), "note": "not simulated: nothing here was exercised, so say so in the summary"}
    keep = ("code", "severity", "ref", "msg", "hint", "trace")
    return {"ran": True, "ok": sim.get("ok"), "findings": [{k: f[k] for k in keep if f.get(k)} for f in sim.get("findings") or []],
            "requirements": sim.get("requirements"), "effects": sim.get("effects"), "power": sim.get("power"), "coverage": sim.get("coverage")}


async def sim_now(state: Any, doc: dict[str, Any], fw: dict[str, Any]) -> dict[str, Any] | None:
    """The run for the device as it is now: the saved one when the circuit and the code are the same, else a new one."""
    key = sim_key(doc, fw)
    saved = fw.get("sim") if isinstance(fw.get("sim"), dict) else None
    if saved and saved.get("key") == key:
        return saved
    mine = getattr(state, "device", None)
    cached = mine.get("fw_sim") if isinstance(mine, dict) else None
    if cached and cached.get("key") == key:
        return cached
    sim = await simulation(doc, fw)
    if isinstance(mine, dict):
        mine["fw_sim"] = sim
    return sim


async def _simulate(ctx: Any, state: Any, args: dict[str, Any]) -> dict[str, Any]:
    doc, _ = await current(ctx.project_id)
    fw = (doc or {}).get("firmware") or {}
    if not fw.get("files"):
        return {"ok": False, "error": "no firmware yet: write_firmware first"}
    norm, _ = device.normalize(doc)
    keep_requirements(norm, doc)
    steps = _as_obj(args.get("steps"))
    condition = _as_obj(args.get("condition"))
    status = getattr(ctx, "status", None)
    if status:
        await status("Running the firmware on a virtual board")
    if not steps and not condition:
        sim = await simulation(norm, fw)
        note_tests(state, norm, sim)
        return {"ok": bool(sim.get("ok", True)), "simulation": sim_view(sim)}
    from .. import firmware_sim

    parts, _ = await device.resolve(device.clone(norm))
    res = await firmware_sim.try_scenario(norm, parts, fw.get("files") or {}, [x for x in steps or [] if isinstance(x, dict)],
                                          float(args.get("horizon_s") or 120.0), condition if isinstance(condition, dict) else {})
    return {"ok": bool(res.get("ran")), **({"error": res.get("why")} if not res.get("ran") else {}), **{k: v for k, v in res.items() if k != "why"}}


async def finish_note(ctx: Any, state: Any, summary: str) -> str:
    """The summary with the run's own line after it."""
    doc, _ = await current(ctx.project_id)
    fw = (doc or {}).get("firmware") or {}
    if not fw.get("files"):
        return summary
    norm, _ = device.normalize(doc)
    keep_requirements(norm, doc)
    note = sim_note(await sim_now(state, norm, fw), summary)
    changed = changed_tests(state, norm)
    if changed:
        note += (f" Сценарии проверки {', '.join(changed)} менялись после провала." if re.search(r"[А-Яа-яЁё]", summary or "")
                 else f" The tests of {', '.join(changed)} were changed after they failed.")
    return f"{summary.rstrip()}\n\n{note}"


def sim_note(sim: dict[str, Any] | None, summary: str) -> str:
    """What the run really covered and measured, in the summary's language: the part of the message no model wrote."""
    ru = bool(re.search(r"[А-Яа-яЁё]", summary or ""))
    if not sim or not sim.get("ran"):
        why = (sim or {}).get("why") or ""
        return ("Прошивка не запускалась в симуляции" if ru else "The firmware was not simulated") + (f" ({why})." if why else ".")
    cov, power = sim.get("coverage") or {}, sim.get("power") or {}
    hours = float(cov.get("simulated_s") or 0) / 3600.0
    bits = [(f"Прошивка прогнана на виртуальной плате: сценариев {cov.get('scenarios')}, {hours:.1f} ч виртуального времени" if ru else
             f"The firmware ran on a virtual board: {cov.get('scenarios')} scenarios, {hours:.1f} h of device time")]
    if power.get("sleep_ma") is not None:
        bits.append((f"ток во сне {power['sleep_ma']:g} мА" if ru else f"{power['sleep_ma']:g} mA asleep"))
    if power.get("idle_life_h"):
        from .. import firmware_sim

        life = firmware_sim.life_text(float(power["idle_life_h"]))
        if ru:
            life = life.replace("hours", "ч").replace("days", "дн.").replace("months", "мес.")
        bits.append((f"без использования батареи хватит примерно на {life}" if ru else f"left alone the cell lasts about {life}"))
    tests = cov.get("tests") or {}
    if tests:
        done, total = tests.get("passed", 0), sum(tests.values())
        bits.append((f"сценарии требований: прошли {done} из {total}" if ru else f"requirement tests: {done} of {total} passed"))
    errs = [f for f in sim.get("findings") or [] if f.get("severity") == "error"]
    if errs:
        bits.append((f"осталось проблем: {len(errs)} ({', '.join(str(f.get('code')) for f in errs[:3])})" if ru else f"problems left: {len(errs)} ({', '.join(str(f.get('code')) for f in errs[:3])})"))
    if cov.get("not_modelled"):
        bits.append((f"не промоделировано: {', '.join(cov['not_modelled'][:4])}" if ru else f"not modelled: {', '.join(cov['not_modelled'][:4])}"))
    bits.append(("на реальном железе не проверялось" if ru else "not tried on real hardware"))
    return "; ".join(bits) + "."


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


# ------------------------------------------------------------------ the checks a device must pass
def _data(d: Any) -> str:
    """A rule finding's data (C4) in a few words: a sensor's reading direction as the firmware must read it, else compact."""
    if not isinstance(d, dict) or not d:
        return ""
    if "rises" in d and d.get("pin"):
        gpio = f", GPIO{d['gpio']}" if d.get("gpio") is not None else ""
        return (f" [{d['pin']} ({d.get('alias') or d['pin']}{gpio}): the reading {'rises' if d['rises'] else 'falls'} with more "
                f"{d.get('quantity') or 'signal'}]")
    return " [" + json.dumps(d, ensure_ascii=False, separators=(",", ":"))[:200] + "]"


def _line(i: dict[str, Any]) -> str:
    return (f"{i.get('code')} {i.get('ref') or ''}: {i.get('msg')}".replace(" :", ":") + _data(i.get("data"))
            + (f" -> {i['hint']}" if i.get("hint") else ""))


def _fw_line(e: dict[str, Any]) -> str:
    where = ":".join(str(x) for x in (e.get("file"), e.get("line")) if x not in (None, ""))
    return f"{where + ' ' if where else ''}{e.get('code') or 'error'}: {e.get('msg')}" + (f" -> {e['hint']}" if e.get("hint") else "")


def requirements_of(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """doc.requirements (C1e) cleaned: {id, text, parts, firmware?, test?}, at most MAX_REQUIREMENTS. Unlike normalize, a part
    id that is not a node stays: a requirement whose part was deleted must say so, not quietly lose it."""
    out: list[dict[str, Any]] = []
    for i, r in enumerate(doc.get("requirements") if isinstance(doc.get("requirements"), list) else []):
        r = {"text": r} if isinstance(r, str) else r
        if not isinstance(r, dict) or not str(r.get("text") or "").strip():
            continue
        parts = list(dict.fromkeys(device.ident(str(p)) for p in (r.get("parts") if isinstance(r.get("parts"), list) else []) if str(p).strip()))
        out.append({"id": device.ident(str(r.get("id") or f"R{i + 1}"))[:12], "text": str(r["text"]).strip()[:300], "parts": parts[:40],
                    **({"firmware": bool(r["firmware"])} if r.get("firmware") is not None else {}),
                    **({"test": r["test"]} if isinstance(r.get("test"), dict) else {})})
    return out[:MAX_REQUIREMENTS]


def keep_requirements(norm: dict[str, Any], raw: dict[str, Any]) -> None:
    """The requirements of `raw` onto its normalized copy, every part they name kept (normalize drops the ones that are no
    node, and with them the sign that a requested function lost its part)."""
    reqs = requirements_of(raw)
    if reqs:
        norm["requirements"] = reqs


def keep_concept(norm: dict[str, Any], raw: dict[str, Any]) -> None:
    """The concept of `raw` (this version's, or the one before when the designer left it out) onto the normalized copy."""
    concept = device_concept.clean(raw.get("concept"))
    if concept:
        norm["concept"] = concept


def concept_problems(doc: dict[str, Any]) -> list[str]:
    """What the concept lacks (device_concept.problems): none written, fewer than three options, no chosen one, unknown values."""
    return device_concept.problems(doc.get("concept"))


def concept_defaults(doc: dict[str, Any], src: dict[str, Any]) -> None:
    """What a document leaves out comes from the chosen option: the board's shape and size, the module's edge. A designer
    wrote a round wall puck into its concept and a board with no shape into its document, in three runs of five."""
    aim = device_concept.chosen(src)
    board = doc.setdefault("board", {})
    if not aim or not isinstance(board, dict) or board.get("locked"):
        return
    want = aim.get("board") if isinstance(aim.get("board"), dict) else {}
    if not board.get("shape") and want.get("shape") in ("rounded", "round"):
        board["shape"] = want["shape"]
    if not (board.get("w") or board.get("h")) and want.get("w") and want.get("h"):
        board.update({"w": want["w"], "h": want["h"]})
    if aim.get("module_edge"):
        for n in doc.get("nodes") or []:
            if isinstance(n, dict) and n.get("kind") == "module" and not n.get("edge"):
                n["edge"] = aim["module_edge"]


def concept_warnings(doc: dict[str, Any], board: dict[str, Any] | None = None, case: dict[str, Any] | None = None) -> list[str]:
    """Where the built board (board.json) or the case's options left the chosen option: warnings, never errors."""
    try:
        return device_concept.board_drift(doc, board) if board is not None else device_concept.case_drift(doc, case)
    except Exception:  # noqa: BLE001 - a comparison that trips over a board is ours, never the design's
        log.exception("concept drift failed")
        return []


async def case_concept(ctx: Any, state: Any, out: dict[str, Any]) -> dict[str, Any]:
    """make_enclosure's result with the chosen concept's form, stance and mounting held against the case it made."""
    from . import elec_tools

    doc, _ = await current(ctx.project_id)
    if not doc or not out.get("ok") or "lib.elec" not in str(getattr(state, "source", "") or ""):
        return out
    warn = concept_warnings(doc, case=elec_tools.case_options(state.source))
    return {**out, "concept_warnings": warn} if warn else out


def requirement_problems(doc: dict[str, Any]) -> list[str]:
    """What the requirements say is missing: none written, or a part a requirement names that the device has not."""
    reqs = requirements_of(doc)
    if not reqs:
        return [("no requirements: write doc.requirements first, every function the person asked for and the ones a device of this "
                 "kind needs, each with the parts that do it")]
    ids = {n.get("id") for n in doc.get("nodes") or []}
    out = []
    for r in reqs:
        gone = [p for p in r["parts"] if p not in ids]
        if gone:
            out.append(f"requirement {r['id']} ({r['text'][:80]}) names {', '.join(gone)}, not in the device: add the part back or point the "
                       "requirement at the part that does it; a requested function is never dropped")
        elif not r["parts"] and not r.get("firmware"):
            out.append(f"requirement {r['id']} ({r['text'][:80]}) names no part: say which parts do it")
    return out


def wiring(doc: dict[str, Any]) -> str:
    """What firmware depends on: the parts and which pins share a net (not names, placements or the board)."""
    nodes = sorted([n.get("id"), n.get("kind"), n.get("lcsc") or n.get("module") or n.get("accessory") or "", list(n.get("pins") or [])]
                   for n in doc.get("nodes") or [])
    nets = sorted(sorted(net.get("pins") or []) for net in doc.get("nets") or [])
    return hashlib.sha1(json.dumps([nodes, nets], sort_keys=True).encode()).hexdigest()[:16]


RULES_NOT_RUN = {"code": "rules_not_run", "severity": "warn", "ref": "device", "ran": False,
                 "msg": "the design rule check failed on our side and did not run: nothing here says the design passes it"}


async def design_checks(doc: dict[str, Any], parts: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """device_rules.check (C4) on a normalized document and its resolved parts; when they cannot run, one RULES_NOT_RUN
    warning instead of an empty list, which would read as a clean design."""
    try:
        from .. import device_rules
    except Exception:  # noqa: BLE001 - not landed yet, or broken: the pack still works
        return []
    try:
        if parts is None:
            doc = device.clone(doc)
            parts, _ = await device.resolve(doc)
        items = device_rules.check(doc, parts)
    except Exception:  # noqa: BLE001 - a rule that crashes is a bug of ours, never the design's
        log.exception("device_rules.check failed")
        return [dict(RULES_NOT_RUN)]
    return [i for i in items or [] if isinstance(i, dict) and i.get("msg")]


async def firmware_check(doc: dict[str, Any], fw: dict[str, Any]) -> dict[str, Any] | None:
    """firmware_check.check (C3) on these files for this document, with the wiring it saw; None when there is no checker or it
    failed (that is not the firmware's fault)."""
    try:
        from .. import firmware_check as fc
    except Exception:  # noqa: BLE001
        return None
    files = {str(k): str(v) for k, v in (fw.get("files") or {}).items()}
    try:
        res = await asyncio.wait_for(fc.check(doc, files, str(fw.get("lang") or "arduino")), FIRMWARE_CHECK_S)
    except Exception as e:  # noqa: BLE001 - it never raises by contract; a timeout or a bug is skipped, not blocking
        log.warning("firmware check failed: %s: %s", type(e).__name__, e)
        return None
    if not isinstance(res, dict):
        return None
    keep = ("code", "file", "line", "msg", "hint")
    errors = [{k: e[k] for k in keep if e.get(k) not in (None, "")} for e in res.get("errors") or [] if isinstance(e, dict)][:20]
    warnings = [{k: w[k] for k in keep if w.get(k) not in (None, "")} for w in res.get("warnings") or [] if isinstance(w, dict)][:20]
    return {"ok": bool(res.get("ok", not errors)) and not errors, "tool": str(res.get("tool") or "")[:60], "errors": errors,
            "warnings": warnings, "wiring": wiring(doc), "asks": asks(doc)}


def asks(doc: dict[str, Any]) -> str:
    """What the firmware's requirement checks depend on: the requirements' texts, parts and firmware flags."""
    return hashlib.sha1(json.dumps(requirements_of(doc), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


async def check_now(state: Any, doc: dict[str, Any], fw: dict[str, Any]) -> dict[str, Any] | None:
    """The firmware's check for the device as it is now: the stored one when it was made for this wiring and these
    requirements, else the same files checked again (once per job state: the finish gate and the reviewer share it); None
    without a checker."""
    check = fw.get("check") if isinstance(fw.get("check"), dict) else None
    if check is not None and check.get("wiring") == wiring(doc) and check.get("asks") == asks(doc):
        return check
    key = wiring(doc) + asks(doc) + hashlib.sha1(json.dumps(fw.get("files"), sort_keys=True).encode()).hexdigest()[:8]
    mine = getattr(state, "device", None)
    cached = mine.get("fw_check") if isinstance(mine, dict) else None
    if cached and cached.get("key") == key:
        return cached["check"]
    check = await firmware_check(doc, fw)
    if isinstance(mine, dict):
        mine["fw_check"] = {"key": key, "check": check}
    return check


async def firmware_problems(state: Any, doc: dict[str, Any], fw: dict[str, Any] | None) -> list[str]:
    """Firmware that is missing, fails its check, or was checked against other wiring and fails it now."""
    fw = fw or {}
    if not fw.get("files"):
        return ["no firmware yet: write_firmware for its microcontroller"]
    check = await check_now(state, doc, fw)
    if check is None or (check.get("ok", True) and not check.get("errors")):
        return []
    errors = check.get("errors") or [{"msg": "the firmware check failed"}]
    return [f"firmware: {_fw_line(e)}" for e in errors[:5]] + (
        [f"and {len(errors) - 5} more firmware errors"] if len(errors) > 5 else []) + ["fix the firmware and write_firmware again"]


async def simulation_problems(state: Any, doc: dict[str, Any], fw: dict[str, Any] | None) -> list[str]:
    """What running the firmware found, for the device as it is now."""
    fw = fw or {}
    if not fw.get("files"):
        return []
    sim = await sim_now(state, doc, fw)
    errs = [f for f in (sim or {}).get("findings") or [] if f.get("severity") == "error"]
    mine = state.self_check if isinstance(getattr(state, "self_check", None), dict) else {}
    note_tests(state, doc, sim)
    out = weakened_tests(state, doc) + [f"simulation: {_sim_line(f)}" for f in errs[:5]] + (
        ["fix it and write_firmware again (simulate_device replays it with your own steps)"] if errs else [])
    untested = [x["id"] for x in (sim or {}).get("requirements") or [] if x.get("status") == "no_test"]
    if untested and not errs and not mine.get("tests_asked"):
        mine["tests_asked"] = True
        out.append(f"{', '.join(untested)} have firmware work and no test. Add `test` to each with write_device edits [{{op:'requirements', requirements:[...]}}] (the whole "
                   "list, texts unchanged): the steps a person takes and what must follow, for what only a sequence shows. The next finish plays them.")
    return out


def note_tests(state: Any, doc: dict[str, Any], sim: dict[str, Any] | None) -> None:
    """What each test checked the first time it was played, and the version of it that failed. In five runs of 2026-11-04 designers
    answered a failed test by rewriting it: a sleep requirement ended up checking that a LED lights."""
    from .. import firmware_sim

    mine = state.self_check if isinstance(getattr(state, "self_check", None), dict) else None
    if mine is None or not sim:
        return
    pins, failed = mine.setdefault("test_pins", {}), mine.setdefault("failed_tests", {})
    by_id = {r["id"]: r for r in requirements_of(doc)}
    for x in sim.get("requirements") or []:
        r = by_id.get(x.get("id"))
        if not r or x.get("status") not in ("passed", "failed", "vacuous"):
            continue
        pins.setdefault(r["id"], sorted(firmware_sim.test_targets(r.get("test"))))
        if x["status"] == "failed":
            failed.setdefault(r["id"], json.dumps(r.get("test"), sort_keys=True, ensure_ascii=False))


def weakened_tests(state: Any, doc: dict[str, Any]) -> list[str]:
    """A test may move in time, or be fixed where it was wrong, but it keeps what it checked (unless that part left the device)."""
    from .. import firmware_sim

    pins = (state.self_check if isinstance(getattr(state, "self_check", None), dict) else {}).get("test_pins") or {}
    nodes = {n.get("id") for n in doc.get("nodes") or []}
    out = []
    for r in requirements_of(doc):
        now = firmware_sim.test_targets(r.get("test"))
        lost = [t for t in pins.get(r["id"]) or [] if t not in now and (not t.endswith((" on", " off")) or t.rsplit(" ", 1)[0] in nodes)]
        if lost:
            out.append(f"the test of {r['id']} no longer checks {', '.join(lost)}, as it did when it was first played. A test may move in time but keeps what it checks: "
                       "put that back and fix the device so it passes")
    return out


def changed_tests(state: Any, doc: dict[str, Any]) -> list[str]:
    """Requirements whose test differs from the one that failed: a test may be wrong, and the person hears when it was changed."""
    failed = (state.self_check if isinstance(getattr(state, "self_check", None), dict) else {}).get("failed_tests") or {}
    by_id = {r["id"]: r for r in requirements_of(doc)}
    return [rid for rid, was in failed.items() if json.dumps((by_id.get(rid) or {}).get("test"), sort_keys=True, ensure_ascii=False) != was]


def opening_problems(doc: dict[str, Any], board: dict[str, Any] | None, enc: dict[str, Any] | None) -> list[str]:
    """Face parts and accessories (C2) the case left without their opening: a light under the lid, a display with no window,
    a buzzer with no grille. Error findings are the case gate's own; this adds what has no finding at all, and a light a
    whole lid thick. Findings the case engine does not know yet (FACE_FINDINGS) are only expected once it reports some."""
    if not board or not isinstance(enc, dict) or "findings" not in enc:
        return []
    fs = [f for f in enc.get("findings") or [] if isinstance(f, dict)]
    found = {(f.get("code"), str(f.get("part"))): f for f in fs}
    knows = bool({f.get("code") for f in fs} & FACE_FINDINGS)
    comps = {str(c.get("id")): c for c in board.get("components") or [] if isinstance(c, dict)}
    out = []
    for n in doc.get("nodes") or []:
        c, face = comps.get(str(n.get("id"))), n.get("face")
        # an accessory's board entry is its connector: its window is the accessory's own, checked below
        if n.get("kind") != "accessory" and face in OPENING and c is not None and c.get("access") != face:
            out.append(f"{n['id']} has face {face} but the built board gives it access {c.get('access')}, so the case cuts nothing over it: "
                       "build_device and make_enclosure again")
    for cid, c in comps.items():
        if c.get("access") not in OPENING or c.get("side") == "bottom":
            continue
        code, what = OPENING[c["access"]]
        f = found.get((code, cid))
        if f is None and (code == "light_window" or knows):
            out.append(f"{cid} ({c['access']}) got no {what} in the case: make_enclosure again; if it stays, move it from under the "
                       "case's posts and hooks")
        elif f is not None and code == "light_window" and f.get("severity") == "warn" and isinstance(f.get("value"), (int, float)) \
                and f["value"] > LIGHT_SKIN_MM:
            out.append(f"{cid}: the light is sealed under the lid ({f.get('msg')}): make_enclosure with options {{lights: 'hole'}}")
    for a in board.get("accessories") or []:
        if not isinstance(a, dict) or not knows:
            continue
        code = ("display_window" if a.get("kind") == "display" else "cable_exit" if a.get("mount") == "cable"
                else "battery_space" if a.get("kind") == "battery" or a.get("mount") == "inside"
                else "sensor_window" if a.get("kind") == "sensor" and a.get("mount") == "board" else None)
        if code and (code, str(a.get("id"))) not in found:
            out.append(f"accessory {a.get('id')} ({a.get('name') or a.get('key')}) has no {code.replace('_', ' ')} in the case: make_enclosure again")
    return out


# ------------------------------------------------------------------ for the hub and the loop
async def finish_gate(ctx: Any, state: Any) -> list[str]:
    """Why finish must wait: the board built from the latest device version (clean, intent met), no design errors, every
    requirement's parts in the device, the case made from that board with an opening for every face part and accessory,
    and firmware that passes its check for the current wiring. Nothing after BLOCK_ATTEMPTS finishes: then it ships and the
    summary says what is left."""
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
    norm, _ = device.normalize(doc)
    keep_requirements(norm, doc)
    rules = await design_checks(norm)
    if any(i.get("code") == RULES_NOT_RUN["code"] for i in rules):
        state.unchecked.append("design_rules")
    reasons += [f"design error {_line(i)}" for i in rules if i.get("severity") == "error"][:8]
    reasons += concept_problems(doc)
    reasons += requirement_problems(norm)
    board_reasons = await pcb_tools.finish_gate(ctx, state)
    reasons += board_reasons
    if not board_reasons and row:
        # the case gate just checked the case of this board: the same check says which openings it cut
        enc = ((state.last_build or {}).get("checks") or {}).get("enclosure")
        reasons += opening_problems(norm, pcb_tools._board(ctx.project_id, int(row["version"])), enc)
    reasons += await firmware_problems(state, norm, doc.get("firmware"))
    if not reasons:
        reasons += await simulation_problems(state, norm, doc.get("firmware"))
    if not reasons and row:
        reasons += await layout_problems(ctx, state, doc, norm, pcb_tools._board(ctx.project_id, int(row["version"])))
    return reasons


async def layout_problems(ctx: Any, state: Any, doc: dict[str, Any], norm: dict[str, Any], board: dict[str, Any] | None) -> list[str]:
    """Once, when all else is ready: the built board against the chosen concept, and a board far larger than its parts. As
    warnings the designer passed over them in every run (a night light 5.5 x its parts, a round puck built as a rectangle).
    The next finish goes through, so a reason to keep the board stays the designer's to give."""
    left = getattr(state, "turns_left", None)
    if state.self_check.get("layout_asked") or (left is not None and left < LAYOUT_TURNS):
        return []
    out = list(concept_warnings(doc, board=board or {}))
    try:
        parts, _ = await device.resolve(norm)
        roomy = device.compaction(norm, parts)
    except Exception:  # noqa: BLE001 - a geometry slip must not hold the device back
        log.exception("layout check failed")
        roomy = None
    if roomy:
        # told "or change the concept", two designers of five wrote their oversized board into the concept and called it done
        out = [w for w in out if " mm, the concept's " not in w]
        out.append(f"board_too_large: {roomy['msg']}")
    if out:
        state.self_check["layout_asked"] = True
        out.append("Make the board what the concept says and as small as its parts allow"
                   + (": write_device with edits [{op:'compact'}] applies the arrangement above, then build_device, make_enclosure, and "
                      "write_firmware if pins moved. Writing the larger size into the concept does not solve this" if roomy else
                      " (write_device, build_device, make_enclosure, write_firmware if pins moved)")
                   + ". If there is a real reason to keep it, finish again and give the reason in the summary.")
    return out


def _board_changed(doc: dict[str, Any], row: dict[str, Any] | None) -> bool:
    if not row:
        return True
    return device.board_key(doc) != device.board_key(row.get("doc") or {})


LAYOUT_TURNS = 6  # a rebuild takes write_device, build_device, make_enclosure, maybe firmware, then finish twice
SELF_CHECK_HOW = ("Before this finish is accepted, check the device against these items for the part kinds it has: on the graph, the "
                  "board, the firmware (file:line) and the case. Fix every problem first (write_device, build_device, make_enclosure, "
                  "write_firmware as needed). Then call finish again with the summary and `checked`: at least one entry per kind "
                  "listed, {kind, verdict: ok|fixed|n/a, where: node / net / file:line}, or per item ({item: 'led.2', ...}). Check by "
                  "looking, not from memory: inspect_part for a part's pins, nets and firmware lines; inspect_board and inspect_case "
                  "(lid_off or section) focused on the parts people see, touch or that sense.")
LOOKS = ("inspect_board", "inspect_case")


def _can_look() -> bool:
    try:
        from . import device_inspect  # noqa: F401 - the tools exist only when it imports
    except Exception:  # noqa: BLE001
        return False
    return True


async def _claim_problem(state: Any, doc: dict[str, Any], norm: dict[str, Any]) -> dict[str, Any] | None:
    """Once: a battery life in the summary far from what the run measured. The summary is what the person believes."""
    mine = state.self_check
    fw = doc.get("firmware") or {}
    text = str(mine.get("summary") or "")
    if mine.get("claim_asked") or not fw.get("files") or not text:
        return None
    from .. import firmware_sim

    sim = await sim_now(state, norm, fw)
    life = ((sim or {}).get("power") or {}).get("idle_life_h")
    if not life:
        return None
    wrong = [w for w, h in firmware_sim.battery_claims(text) if h > 2.5 * float(life)]
    if not wrong:
        return None
    mine["claim_asked"] = True
    return {"accepted": False, "reason": "the summary promises more than the run measured",
            "issues": [f"the summary says '{wrong[0]}' about the battery; the simulation measured {firmware_sim.life_text(float(life))} left alone "
                       f"({sim['power'].get('idle_avg_ma')} mA on average). Use that number, or fix what draws the current, and finish again."]}


async def self_check(ctx: Any, state: Any, checked: Any) -> dict[str, Any] | None:
    """The designer's own check against device_checklists, in place of the device reviewer: once the gate passes, a finish
    without `checked` gets the checklist of the kinds in its graph (plus the case and device-level items) and is not
    accepted; one whose `checked` answers every kind with ok / fixed / n/a is. Neither counts as a finish attempt (the
    gate keeps its own count). None: go on with the finish (passed, nothing to check, no turn left to answer it, or
    sent back SELF_CHECK_ROUNDS times already)."""
    from .. import device_checklists as dc

    mine = state.self_check if isinstance(getattr(state, "self_check", None), dict) else {}
    checked = _as_obj(checked)
    if mine.get("passed"):
        return None
    doc, _ = await current(ctx.project_id)
    if not doc:
        return None
    norm, _ = device.normalize(doc)
    try:
        parts, _ = await device.resolve(norm)
    except Exception:  # noqa: BLE001 - the chips' kinds fall back to their labels
        parts = {}
    claim = await _claim_problem(state, doc, norm)
    if claim:
        state.finish_attempts -= 1
        return claim
    kinds = dc.ordered(dc.kinds_of(norm, parts))
    missing, bad = dc.coverage(checked, kinds) if checked else (kinds, [])
    mine["kinds"] = kinds
    left = getattr(state, "turns_left", None)
    # in ~20 runs the designer never looked at what it built: the self-check counts once it has, at the latest board and case
    unseen = [t for t in LOOKS if t not in (mine.get("looked") or [])]
    faces = [n["id"] for n in norm["nodes"] if n.get("kind") in ("led", "button", "accessory") or n.get("place") or n.get("face")
             or str((parts.get(n["id"]) or {}).get("kind_hint") or "") in ("sensor", "display", "led", "rgb_led", "buzzer_active", "buzzer_passive", "buzzer")]
    if checked and not missing and not bad:
        if unseen and (left is None or left >= 3) and not mine.get("look_asked") and _can_look():
            mine["look_asked"] = True
            state.finish_attempts -= 1
            return {"accepted": False, "reason": "look at the board and the case first",
                    "look": f"Call {' and '.join(unseen)} before this finish: inspect_board focus on the parts people see, touch or that "
                            f"sense ({', '.join(faces[:10]) or 'the user-facing parts'}) and on the longest trace; inspect_case mode lid_off "
                            "or section focus on each of them. Fix what you see, then finish again with `checked` (and the summary)."}
        mine.update({"passed": True, "checked": checked[:60]})
        return None
    if (left is not None and left < 1) or (checked and mine.get("rejected", 0) >= SELF_CHECK_ROUNDS):
        mine["passed"] = "skipped"
        return None
    if checked:
        mine["rejected"] = mine.get("rejected", 0) + 1
    mine["asked"] = mine.get("asked", 0) + 1
    state.finish_attempts -= 1
    text = dc.for_kinds(kinds)
    if len(text) > SELF_CHECK_FULL:
        text = dc.for_kinds(kinds, only_yours=True)
    out: dict[str, Any] = {"accepted": False, "reason": "the self-check leaves part kinds out" if checked else "self-check against the checklist",
                           "self_check": {"kinds": kinds, "checklist": text, "how": SELF_CHECK_HOW}}
    if checked:
        out["missing"] = missing
        if bad:
            out["invalid"] = bad[:8]
    return out


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
                chk = fw.get("check") if isinstance(fw.get("check"), dict) else None
                checked = ("not checked" if chk is None else "checked for other wiring: write_firmware again" if chk.get("wiring") != wiring(doc)
                           else "passes its check" if chk.get("ok") else f"fails its check: {'; '.join(_fw_line(e) for e in (chk.get('errors') or [])[:3])}")
                lines.append(f"# Firmware ({fw.get('lang')}): " + ", ".join(fw.get("files") or {}) + f", {checked} (write_firmware replaces it)")
    p = state.pcb
    if p.get("version"):
        lines.append(f"# Latest board: PCB version {p['version']} ({'DRC clean' if p.get('ok') else 'DRC errors'}, intent "
                     f"{'ok' if p.get('intent_ok') else 'not met'})")
    case = p.get("enclosure") or {}
    if case:
        lines.append(f"# Case: program version {case['version']} made from PCB version {case['pcb_version']}")
    # the soil sensor of 2026-11-03 spent its run on four failed builds: the plan comes before the first one
    lines.append("# Plan the turns: the concept, requirements and every part first, then one write_device with the front panel placed and a board "
                 "that fits it, and only then build_device (a build is a turn and about a minute). Keep turns for the case, the "
                 "firmware, the price and the self-check round at finish.")
    return lines


async def handover(project_id: str, ending: str, state: Any, language: str | None) -> str:
    """For a run that stopped before an accepted finish: where the device stands (its version, the board built from it,
    the case, the firmware's check) and what is left, in the person's language. Read from the stores, never from the case
    program's version, which is all the generic hand-over knows. Runs no check: the stored firmware check, or the one
    this job made."""
    from .. import pcb_store
    from . import narrate, pcb_tools

    doc, version = await current(project_id)
    f: dict[str, Any] = {"device": version, "left": []}
    if doc:
        row = await pcb_store.get(project_id)
        left = f["left"]
        if row:
            v, checks = int(row["version"]), row.get("checks") or {}
            path = pcb_store.artifact_path(project_id, v, "device.json")
            try:
                built = json.loads(path.read_text(encoding="utf-8")).get("_version") if path else None
            except (OSError, json.JSONDecodeError):
                built = None
            same = built is not None and (built == version or not _board_changed(doc, await device_store.get(project_id, built)))
            f.update({"pcb": v, "built": same, "drc": len(checks.get("errors") or []),
                      "intent_ok": bool((checks.get("intent") or {}).get("ok", True)), "case": pcb_tools.case_for(state) == v})
            left += (["build"] if not same else ["drc"] if f["drc"] else ["intent"] if not f["intent_ok"] else []) + ([] if f["case"] or not same else ["case"])
        else:
            left.append("build")
        fw = doc.get("firmware") or {}
        if fw.get("files"):
            norm, _ = device.normalize(doc)
            chk = fw.get("check") if isinstance(fw.get("check"), dict) else None
            cached = ((state.device or {}).get("fw_check") or {}).get("check") if isinstance(getattr(state, "device", None), dict) else None
            stale = chk is not None and chk.get("wiring") != wiring(norm)
            chk = cached if stale and cached else chk
            f["firmware"] = ("unchecked" if chk is None else "stale" if chk.get("wiring") != wiring(norm)
                             else "passed" if chk.get("ok") else "failed")
            left += {"failed": ["firmware_failed"], "stale": ["firmware_stale"]}.get(f["firmware"], [])
        else:
            left.append("firmware")
    critic = state.critic or {}
    if critic.get("verdict") == "revise":
        f["notes"] = [i.get("text_user") or i.get("text") for i in critic.get("issues") or [] if i.get("severity") == "major"]
    return narrate.device_handover(ending, f, language)
