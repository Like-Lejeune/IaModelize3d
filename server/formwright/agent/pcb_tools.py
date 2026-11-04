"""Agent tools for printed circuit boards (pack 'pcb'): write a circuit (tscircuit TSX), have it placed-checked,
routed and checked, export the fab files and wrap the routed board in a 3D-printed case.

The hub (tools.py, prompts.py, loop.py) offers TOOLS, hands the calls named in NAMES to run(), asks finish_gate()
before finish and puts pcb_prompt.PACK_TEXT and EXAMPLE into the prompt. A build runs in the PCB worker (formwright.pcb,
a sandboxed Node process) and streams its routing frames as 'pcb.route' events. Every build that renders is saved as
a PCB version (pcb_store, announced with 'pcb.version') with its checks and previews; only a clean one (0 DRC errors)
also gets the fab files. make_enclosure puts the version's board.json into inputs.boards.board and builds
elec_tools.enclosure_program() as an ordinary program version, then checks the case against the board.
This module never imports tools.py at load time, so the hub can import it at its top.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .. import pcb, pcb_store, pcbapi, storage
from ..geom import GeomError
from ..pcb import PcbError

log = logging.getLogger(__name__)

# the worker itself failed (died or lost sync): one silent retry; a timeout is the circuit's own (too heavy or hanging)
INFRA_STAGES = ("crash", "protocol")
BLOCK_ATTEMPTS = 3  # like printability errors: the first three finishes are blocked, then it ships and the summary says what is left
BOARD = "board"  # the key under inputs.boards the case program reads
FAB = ("gerbers.zip", "bom.csv", "cpl.csv")
PREVIEWS = ("pcb_top.svg", "pcb_bottom.svg", "schematic.svg", "board.glb")
VIEWS = {"pcb": "pcb_top.svg", "pcb_bottom": "pcb_bottom.svg", "schematic": "schematic.svg"}
FACT_SUBJECT = "PCB of this design"
MAX_SOURCE = 60_000


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


_S = {"type": "string"}
VERSION = {"type": "integer", "description": "PCB version (default: the latest)"}

WRITE_CIRCUIT = _fn(
    "write_circuit",
    "Write the circuit (a tscircuit TSX file, see the pack rules) and build it: placement checks, autorouting on 2 layers, DRC and "
    "the intent checks, then the board description the case is made from. Every build that renders becomes a PCB version with a "
    "top view; a clean one (0 DRC errors) also gets its fab files. Errors come root cause first, each with a concrete hint. "
    "Give `source` (the whole file) or `edits` on the current file.",
    {"source": {**_S, "description": "the complete TSX file: export const meta = {...}; export default () => (<board ...>...</board>)"},
     "edits": {"type": "array", "description": "instead of source: snippets of the current file to replace, in order; each `find` must "
                                               "occur exactly once", "items": {"type": "object", "properties": {
                                                   "find": _S, "replace": {**_S, "description": "its replacement (empty string deletes it)"}},
                                                   "required": ["find", "replace"]}},
     "intent": {"type": "object", "description": "overrides meta.intent for this build: {edge: {J1: '-y'}, gpio: {LED1: 'D10'}, nets_max: 30}"},
     "summary": {**_S, "description": "one line for the person: what this version changes (in the user's language)"}},
    ["summary"])
CHECK_PCB = _fn(
    "check_pcb",
    "The checks of a saved PCB version again: DRC errors with hints, the intent, the limits (2 layers, 30 nets, 40 parts, "
    "100 x 100 mm), which parts are ports on which edge, and whether its fab files exist.",
    {"version": VERSION}, [])
EXPORT_FAB = _fn(
    "export_fab",
    "Download links of a clean PCB version's fab files: Gerber + drill zip (Protel names), BOM and CPL in JLCPCB's columns, plus "
    "the top and bottom views, the schematic and the 3D board (GLB).",
    {"version": VERSION}, [])
MAKE_ENCLOSURE = _fn(
    "make_enclosure",
    "Make the 3D-printed snap-fit case for a PCB version from its board.json (it becomes inputs.boards.board): lib.elec builds base "
    "and lid with windows for the edge ports, press tabs over buttons and windows over LEDs, then the case is checked against the "
    "board (plug paths, collisions, button reach, lid fit, snap strain). with_mockup (default true) adds a printed 1.6 mm stand-in "
    "of the PCB with its holes next to the case, so the real module can be tried in it before the board is made.",
    {"version": VERSION,
     "with_mockup": {"type": "boolean", "description": "print a stand-in plate of the PCB with the case (default true)"},
     "options": {"type": "object", "description": "case options: wall, floor, lid, clear (gap around the board), standoff (space under "
                                                  "it), port_fit (gap around plugs) in mm; lights 'hole'|'skin'; mount 'peg'|'auto'|'screw'. "
                                                  "wall 2.0 by default, 1.2 at least; the snap hooks hold firmer from 1.3 (catch 0.28 mm, "
                                                  "0.20 at 1.2). Choose the next three for how the device is used, not by default; for pack "
                                                  "'device' any left out come from the doc's chosen concept. form, the plan shape: 'soft' "
                                                  "(default: corners as round as the parts allow, at most 0.6 mm larger; desk gadgets, sensors), "
                                                  "'round' (a pebble or puck, up to 3 mm larger per side; a night light, a remote, a fob; on a "
                                                  "round PCB a true round puck), 'box' (small corners: a rack, a DIN rail, stacking). A rounded "
                                                  "or round PCB's case follows its outline. stance, how it sits in use: 'desk' (flat, lid up), "
                                                  "'tilt' (a printed wedge stand comes with it: leans 25 deg, lid and display to the person; a "
                                                  "timer, a clock, a meter), 'upright' (a printed stand, leans 75 deg like a picture frame; a "
                                                  "display read across the room, a lamp), 'wall' (flat on the wall, lid out; gets ears when no "
                                                  "mounting is given), 'hand' (no stand; pair it with round or a lanyard), 'auto' (follows the "
                                                  "mounting). A stand takes a wall free of ports (-y with a display, so it reads upright; "
                                                  "mount_edge picks another) and goes with mounting none or magnets. mounting, how it is held: "
                                                  "'ears' (two screw ears, a wall plate), 'strap' (slots for a strap or band: a pipe, a wrist), "
                                                  "'lanyard' (a keyring eyelet), 'stake' (a 70 mm spike into soil, it stands on it: a garden "
                                                  "sensor), 'magnets' (pockets for 10x2 mm disc magnets under the floor: a fridge, a whiteboard), "
                                                  "'contacts' (two M3 screws through the floor as feet or probe contacts: a leak puck), 'none'. "
                                                  "Ears, strap, lanyard and stake need walls free of ports (mount_edge '+x'|'-x'|'+y'|'-y' picks "
                                                  "the wall). min_height (mm): the outer height at least (a cube, a tower)"}},
    [])
# the pack's look: the board's own views next to the case model
LOOK = _fn(
    "look",
    "Look closely. what='pcb': the routed board from the top (both copper layers, pads, holes, silkscreen) | 'pcb_bottom': from "
    "below | 'schematic' (of a PCB version, the latest by default) | 'model': 6 views of the printed case after make_enclosure.",
    {"what": {"type": "string", "enum": ["pcb", "pcb_bottom", "schematic", "model"]}, "version": VERSION},
    ["what"])

TOOLS = [WRITE_CIRCUIT, CHECK_PCB, EXPORT_FAB, MAKE_ENCLOSURE]
NAMES = {t["name"] for t in TOOLS}


async def run(ctx: Any, state: Any, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if name == "write_circuit":
        return await _write(ctx, state, args)
    if name == "check_pcb":
        return await _check(ctx, state, args)
    if name == "export_fab":
        return await _export(ctx, state, args)
    if name == "make_enclosure":
        out, images = await _enclosure(ctx, state, args)
        if getattr(state, "pack", None) == "device":
            # the case held to the device's chosen concept (form, stance, mounting): warnings only
            from . import device_tools

            out = await device_tools.case_concept(ctx, state, out)
        return out, images
    return {"ok": False, "error": f"unknown tool {name}"}, []


# ------------------------------------------------------------------ helpers
def _as_obj(v: Any) -> Any:
    """Models sometimes send an object argument as a JSON string."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return None
    return v


def _ru(ctx: Any) -> bool:
    return str((ctx.project.get("brief") or {}).get("language") or "").lower().startswith(("ru", "kk"))


async def _retry(call):
    """One silent retry when the PCB worker itself failed; the pool starts a fresh one."""
    try:
        return await call()
    except PcbError as e:
        if e.stage not in INFRA_STAGES:
            raise
        log.warning("pcb worker %s, retrying once: %s", e.stage, e.message[:200])
        return await call()


def _failure(e: PcbError) -> dict[str, Any]:
    if e.stage in INFRA_STAGES:
        return {"ok": False, "infra": True, "stage": e.stage, "error": "the PCB engine failed twice on this build and was restarted, your "
                "circuit was not the problem. Retry once; if it fails again, simplify the circuit"}
    if e.stage == "timeout":
        return {"ok": False, "stage": "timeout", "error": e.message[:500],
                "hint": "fewer parts or nets, more room between parts or a larger board, so placement and routing finish in time"}
    return {"ok": False, "stage": e.stage, "error": e.message[:1500], **({"hint": e.hint} if e.hint else {}),
            "note": "nothing was saved: the previous version is unchanged"}


async def _row(ctx: Any, version: Any) -> tuple[dict[str, Any] | None, str | None]:
    """A saved PCB version (the latest when version is empty), or an error for the model."""
    v = None
    if version not in (None, "", "latest"):
        try:
            v = int(version)
        except (TypeError, ValueError):
            return None, f"version must be a number, got {version!r}"
    row = await pcb_store.get(ctx.project_id, v)
    if row is None:
        return None, "no PCB version yet: write_circuit first" if v is None else f"there is no PCB version {v}"
    return row, None


def _board(project_id: str, version: int) -> dict[str, Any] | None:
    path = pcb_store.artifact_path(project_id, version, "board.json")
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("board.json of %s v%s: %s", project_id, version, e)
        return None


def _ports(board: dict[str, Any] | None) -> list[str]:
    return [f"{c['id']} ({c.get('type')}) on {c.get('edge')}" for c in (board or {}).get("components", []) if c.get("access") == "port"]


def _size(board: dict[str, Any] | None) -> list[float] | None:
    o = ((board or {}).get("pcb") or {}).get("outline") or {}
    return [o["w"], o["h"]] if o.get("w") and o.get("h") else None


def brief(checks: dict[str, Any], version: int, board: dict[str, Any] | None, artifacts: set[str] | list[str]) -> dict[str, Any]:
    """A build (or a version's stored checks) for the designer: errors in full with their hints, the rest short. The count
    is the listed (root) errors, as the 'pcb.version' event and the result card count them; the follow-ups the listed ones
    cause (routing skipped, not connected) are the separate `suppressed` line, so a title never says 50 where the board has 4."""
    errors = checks.get("errors") or []
    intent = checks.get("intent") or {"ok": True, "issues": [], "checked": 0}
    limits = checks.get("limits") or {"ok": True, "issues": []}
    out: dict[str, Any] = {"ok": not errors, "version": version, "counts": checks.get("counts") or {}, "drc_errors": len(errors)}
    if _size(board):
        out["board_mm"] = _size(board)
    if errors:
        out["error"] = f"{len(errors)} DRC error(s): {errors[0].get('hint') or errors[0].get('message', '')}"[:300]
        out["errors"] = [{k: (str(e[k])[:500] if k == "message" else e[k]) for k in ("type", "ref", "message", "hint") if e.get(k)} for e in errors]
        if checks.get("suppressed"):
            out["suppressed"] = f"{checks['suppressed']} more errors that follow from these (fix the listed ones first)"
    warnings = checks.get("warnings") or []
    if warnings:
        out["warnings"] = [{k: str(w[k])[:240] for k in ("type", "message", "hint") if w.get(k)} for w in warnings[:6]]
    out["intent"] = {"ok": bool(intent.get("ok", True)), "checked": intent.get("checked", 0),
                     **({"issues": intent["issues"]} if intent.get("issues") else {})}
    if not intent.get("checked"):
        out["intent"]["note"] = ("no intent stated: add meta.intent (edge for every connector and the module's own USB, gpio for LEDs "
                                 "and buttons); finish needs it")
    if not limits.get("ok", True):
        out["limits"] = limits.get("issues") or []
    out["ports"] = _ports(board)
    have = [n for n in FAB if n in artifacts]
    out["fab"] = (f"ready: {', '.join(have)} (export_fab gives the links)" if len(have) == len(FAB)
                  else "none: fab files come only from a build with 0 DRC errors" if errors else "missing: the export failed, build again")
    if errors:
        out["next"] = "apply the hints, then write_circuit again (edits on the current file)"
    elif not out["intent"]["ok"] or not intent.get("checked"):
        out["next"] = "fix the intent: move or rewire the parts it names, or state it in meta.intent"
    else:
        out["next"] = "export_fab, then make_enclosure"
    return out


def _fact(state: Any, version: int, checks: dict[str, Any], board: dict[str, Any] | None, mockup: bool | None = None) -> None:
    """What the independent reviewer should know: it sees the case renders, while the board itself goes to a fab house."""
    value: dict[str, Any] = {"version": version, "drc_errors": len(checks.get("errors") or []),
                             "intent_ok": bool((checks.get("intent") or {}).get("ok", True)), "size_mm": _size(board), "ports": _ports(board),
                             "note": "the board itself is made by a PCB fab from the exported Gerbers; the renders show the 3D-printed "
                                     "case for it (base and lid" + (", plus a printed 1.6 mm stand-in plate of the PCB to try the real "
                                                                    "module in the case)" if mockup else ")")}
    state.facts = [f for f in state.facts if f.get("subject") != FACT_SUBJECT] + [{
        "subject": FACT_SUBJECT, "attribute": (board or {}).get("name", "PCB"), "value": value, "unit": "mm",
        "source_kind": "pcb_build", "source_url": None, "confidence": 1.0}]


async def _top_view(ctx: Any, version: int, svg: str | None, name: str = "top") -> list[str]:
    """The board as a PNG for the model (and the timeline); nothing when it cannot be drawn."""
    if not svg:
        return []
    png = await pcb.render_png_async(svg, 1000, "#ffffff" if name == "schematic" else None)
    return [storage.save_bytes(ctx.project_id, "renders", f"pcb_v{version}_{name}.png", png)] if png else []


# ------------------------------------------------------------------ write_circuit
async def _write(ctx: Any, state: Any, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    source = str(args.get("source") or "")
    edits = _as_obj(args.get("edits"))
    if not source.strip() and edits:
        current = state.pcb.get("source")
        if not current:
            return {"ok": False, "error": "no circuit yet: pass the whole file as source"}, []
        from .tools import _apply_edits

        source, errors = _apply_edits(current, [e for e in edits if isinstance(e, dict)] if isinstance(edits, list) else [])
        if errors:
            return {"ok": False, "error": "; ".join(errors), "hint": "copy `find` exactly from the current circuit"}, []
    if not source.strip():
        return {"ok": False, "error": "source is empty: pass the complete TSX file, or edits on the current one"}, []
    if len(source) > MAX_SOURCE:
        return {"ok": False, "error": f"the file is {len(source)} characters: keep a carrier board under {MAX_SOURCE}"}, []
    intent = _as_obj(args.get("intent"))
    intent = intent if isinstance(intent, dict) and intent else None

    async def frame(f: dict[str, Any]) -> None:
        await pcbapi.emit_route(ctx.project_id, f, ctx.job_id)

    await ctx.status("Placing and routing the board")
    try:
        build = await _retry(lambda: pcb.pool().build(source, intent=intent, on_frame=frame))
    except PcbError as e:
        return _failure(e), []
    # previews for every build that rendered, fab files only for a clean one
    export, export_error = None, None
    try:
        export = await _retry(lambda: pcb.pool().export(build["circuit_json"]))
    except PcbError as e:
        export_error = f"{e.stage}: {e.message[:300]}"
        log.warning("pcb export failed for %s: %s", ctx.project_id, export_error)
    files = None
    if export and build.get("ok"):
        files = {**export, "files": {k: v for k, v in export["files"].items() if k in FAB + PREVIEWS}}
    elif export:
        # a board with DRC errors is shown, never offered to a fab: no Gerbers, BOM or CPL, and no fab notes
        files = {"files": {k: v for k, v in export["files"].items() if k in PREVIEWS}, "svg_map": export.get("svg_map"), "glb_map": export.get("glb_map")}
    version = await pcb_store.save(ctx.project_id, source=source, intent=intent, build=build, files=files)
    await pcbapi.emit_version(ctx.project_id, version, build, ctx.job_id)
    board = build.get("board")
    state.pcb.update({"version": version, "source": source, "ok": bool(build.get("ok")), "made": True,
                      "intent_ok": bool((build.get("intent") or {}).get("ok", True))})
    _fact(state, version, build, board, (state.pcb.get("enclosure") or {}).get("mockup"))
    result = brief(build, version, board, set((files or {}).get("files") or {}))
    if export_error:
        result["export_error"] = export_error
    if args.get("summary"):
        result["summary"] = str(args["summary"])[:200]
    return result, await _top_view(ctx, version, ((export or {}).get("files") or {}).get("pcb_top.svg"))


# ------------------------------------------------------------------ check_pcb / export_fab / look
async def _check(ctx: Any, state: Any, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    row, error = await _row(ctx, args.get("version"))
    if row is None:
        return {"ok": False, "error": error}, []
    v = int(row["version"])
    out = brief(row.get("checks") or {}, v, _board(ctx.project_id, v), set(row.get("artifacts") or {}))
    case = state.pcb.get("enclosure") or {}
    out["case"] = (f"program version {case['version']}, made from this board" if case.get("pcb_version") == v
                   else "none for this version yet: make_enclosure")
    return out, []


async def _export(ctx: Any, state: Any, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    row, error = await _row(ctx, args.get("version"))
    if row is None:
        return {"ok": False, "error": error}, []
    v, checks = int(row["version"]), row.get("checks") or {}
    errors = checks.get("errors") or []
    if errors:
        return {"ok": False, "version": v, "error": f"PCB v{v} has {len(errors)} DRC error(s): fab files come only from a clean board. "
                                                   "Fix them with write_circuit first"}, []
    arts = set(row.get("artifacts") or {})
    missing = [n for n in FAB if n not in arts]
    if missing:
        return {"ok": False, "version": v, "error": f"PCB v{v} has no {', '.join(missing)}: the export failed on that build; run "
                                                   "write_circuit again with the same file"}, []
    fab = checks.get("fab") or {}
    state.pcb["exported"] = v
    # the counts before the links: the step's summary is this JSON cut at 600 characters, and the studio rebuilds the step
    # in the other UI language from it (steps.ts)
    return {"ok": True, "version": v, "bom_lines": fab.get("bom_lines"), "cpl_lines": fab.get("cpl_lines"), "layers": fab.get("layers"),
            "files": {n: pcb_store.artifact_url(ctx.project_id, v, n) for n in FAB + PREVIEWS if n in arts},
            "unverified": ["LCSC part numbers are as written in the circuit, not checked against the catalogue",
                           "CPL rotations are not yet checked against JLCPCB's placement preview"]}, []


async def look(ctx: Any, state: Any, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """look(what='pcb' | 'pcb_bottom' | 'schematic'): a saved version's own drawing as an image."""
    what = str(args.get("what") or "pcb")
    row, error = await _row(ctx, args.get("version"))
    if row is None:
        return {"ok": False, "error": error}, []
    v = int(row["version"])
    path = pcb_store.artifact_path(ctx.project_id, v, VIEWS.get(what, "pcb_top.svg"))
    if path is None:
        return {"ok": False, "error": f"PCB v{v} has no {what} drawing (its export failed)"}, []
    images = await _top_view(ctx, v, path.read_text(encoding="utf-8"), {"pcb": "top", "pcb_bottom": "bottom"}.get(what, "schematic"))
    if not images:
        return {"ok": False, "error": "the drawing could not be rendered"}, []
    return {"ok": True, "version": v}, images


# ------------------------------------------------------------------ make_enclosure
CONCEPT_KEYS = ("form", "stance", "mounting")


async def concept_case(project_id: str) -> tuple[str | None, dict[str, str]]:
    """The chosen option of the latest device doc's concept: its name and the valid form, stance and mounting it names."""
    try:
        from .. import device_concept
        from . import device_tools, elec_tools
    except ImportError as e:
        log.info("no concept for the case of %s: %s", project_id, e)
        return None, {}
    doc, _ = await device_tools.current(project_id)
    pick = device_concept.chosen(doc)
    if not pick:
        return None, {}
    vals = {k: str(pick.get(k) or "").strip().lower() for k in CONCEPT_KEYS}
    return str(pick.get("name") or "") or None, {k: v for k, v in vals.items() if v in elec_tools.CHOICES[k] and v != "auto"}


async def _enclosure(ctx: Any, state: Any, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    try:
        from . import elec_tools
    except ImportError as e:
        return {"ok": False, "error": f"the case tools are not available here ({e})"}, []
    row, error = await _row(ctx, args.get("version"))
    if row is None:
        return {"ok": False, "error": error}, []
    v = int(row["version"])
    board = _board(ctx.project_id, v)
    if board is None:
        return {"ok": False, "error": f"PCB v{v} has no board description (board.json); build the circuit again"}, []
    opts = _as_obj(args.get("options")) or {}
    if not isinstance(opts, dict):
        return {"ok": False, "error": "options must be an object, e.g. {port_fit: 0.4}"}, []
    # a device's case takes what the call leaves out from the concept it was designed to
    option, chosen = await concept_case(ctx.project_id) if getattr(state, "pack", None) == "device" else (None, {})
    from_concept = {k: v for k, v in chosen.items() if opts.get(k) in (None, "", "auto")}
    opts = {**opts, **from_concept}
    mockup = True if args.get("with_mockup") is None else bool(args.get("with_mockup"))
    try:
        source = elec_tools.enclosure_program(BOARD, title=f"{str(board.get('name') or 'PCB')[:60]} case", mockup=mockup, **opts)
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": f"options: {e}", "hint": "known options: " + ", ".join(elec_tools.DEFAULTS)}, []
    from .tools import _verdict_first, commit_build

    state.inputs = {**(state.inputs or {}), "boards": {**((state.inputs or {}).get("boards") or {}), BOARD: board}}
    state.params = {}
    built, images = await commit_build(ctx, state, source, {}, f"корпус для платы v{v}" if _ru(ctx) else f"case for PCB v{v}")
    if not built.get("ok"):
        return built, images
    state.pcb["enclosure"] = {"version": state.version, "pcb_version": v, "mockup": mockup}
    checks = row.get("checks") or {}
    _fact(state, v, checks, board, mockup)
    try:
        enc = elec_tools.brief(await elec_tools.check(ctx, state, BOARD))
    except GeomError as e:
        enc = {"ok": False, "stage": e.stage, "error": e.message[:500]}
    # the board's version right after the case's own, and the brief's verdict right after 'printable': both inside the step
    # summary's cut, so the step reads the same in the other UI language
    out = {**{k: built[k] for k in ("ok", "version") if k in built}, "pcb_version": v, **built, "mockup": mockup, "enclosure": enc}
    if from_concept:
        out["from_concept"] = {"option": option, **from_concept}
    _verdict_first(out)
    if checks.get("errors"):
        out["warning"] = f"PCB v{v} still has DRC errors: the board may still change, and the case with it"
    return out, images


# ------------------------------------------------------------------ the finish gate
def case_for(state: Any) -> int | None:
    """The PCB version the current case program was made from, if the current program is that case."""
    board = ((state.inputs or {}).get("boards") or {}).get(BOARD) or {}
    job = str((board.get("source") or {}).get("pcb_job") or "")
    if not state.source or "lib.elec" not in state.source or not job.startswith("pcb:v"):
        return None
    try:
        return int(job[5:])
    except ValueError:
        return None


async def finish_gate(ctx: Any, state: Any) -> list[str]:
    """Why finish must wait: the latest PCB version needs 0 DRC errors, a stated and met intent, its fab files and a case
    made from it without case errors. Nothing to say after BLOCK_ATTEMPTS finishes: then it ships and says what is left."""
    if state.finish_attempts > BLOCK_ATTEMPTS:
        return []
    row = await pcb_store.get(ctx.project_id)
    if row is None:
        return ["no board yet: write_circuit first"]
    v, checks = int(row["version"]), row.get("checks") or {}
    errors = checks.get("errors") or []
    reasons = [f"DRC {e.get('type')}{' (' + str(e['ref']) + ')' if e.get('ref') else ''}: {str(e.get('message', ''))[:200]}"
               + (f" -> {e['hint']}" if e.get("hint") else "") for e in errors[:6]]
    if len(errors) > 6:
        reasons.append(f"and {len(errors) - 6} more DRC errors on PCB v{v}")
    intent = checks.get("intent") or {}
    if not intent.get("checked"):
        reasons.append("the circuit states no intent: add meta.intent (edge for every connector and the module's own USB, gpio for "
                       "LEDs and buttons) and build again")
    reasons += [f"{i.get('code')} ({i.get('ref')}): {i.get('msg')}" + (f" -> {i['hint']}" if i.get("hint") else "") for i in intent.get("issues") or []]
    reasons += [f"{i.get('code')}: {i.get('msg')}" for i in (checks.get("limits") or {}).get("issues") or []]
    if reasons:
        return reasons
    missing = [n for n in FAB if n not in set(row.get("artifacts") or {})]
    if missing:
        return [f"PCB v{v} has no {', '.join(missing)}: the export failed on that build; write_circuit again"]
    if case_for(state) != v:
        return [f"no case for PCB v{v} yet: make_enclosure"]
    from . import elec_tools

    return await elec_tools.finish_gate(ctx, state)


# ------------------------------------------------------------------ for the loop
async def load(project_id: str, state: Any) -> None:
    """At the start of a job: the latest PCB version and whether the current program is its case."""
    row = await pcb_store.get(project_id)
    if row is None:
        return
    checks = row.get("checks") or {}
    state.pcb.update({"version": int(row["version"]), "source": row.get("source"), "ok": not checks.get("errors"),
                      "intent_ok": bool((checks.get("intent") or {}).get("ok", True))})
    made_from = case_for(state)
    if made_from is not None:
        state.pcb["enclosure"] = {"version": state.version, "pcb_version": made_from,
                                  "mockup": "pcbPlate" in (state.source or "")}


def context_lines(state: Any) -> list[str]:
    """The current circuit for the designer (in place of the case program, which make_enclosure writes)."""
    p = state.pcb
    lines = []
    if p.get("version"):
        status = f"DRC {'clean' if p.get('ok') else 'errors'}, intent {'ok' if p.get('intent_ok') else 'not met'}"
        lines.append(f"# Current circuit: PCB version {p['version']} ({status}); write_circuit edits apply to it\n```tsx\n{p.get('source') or ''}\n```")
    case = p.get("enclosure") or {}
    if case:
        lines.append(f"# Current case: program version {case['version']}, made by make_enclosure from PCB version {case['pcb_version']}"
                     f"{' with the mock-up plate' if case.get('mockup') else ''}; change it with make_enclosure options")
    return lines


def handover(ending: str, state: Any, language: str | None) -> str:
    """For a run that stopped before finish with boards but no case: where the person stands."""
    p = state.pcb
    v, clean = p.get("version"), p.get("ok")
    ru = str(language or "").lower().startswith(("ru", "kk"))
    if ru:
        why = {"budget": "Остановился на лимите расходов.", "time": "Время на этот запуск вышло.", "failed": "Сервис модели перестал отвечать."}.get(
            ending, "Я остановился до финальной проверки.")
        return (f"{why} Последняя версия платы — {v}: {'0 ошибок DRC' if clean else 'есть ошибки DRC'}, корпуса пока нет. "
                "Напишите сообщение, чтобы продолжить.")
    why = {"budget": "Stopped at the spending cap.", "time": "Time is up for this run.", "failed": "The model service stopped answering."}.get(
        ending, "I stopped before the final review.")
    return (f"{why} PCB version {v} is the latest: {'0 DRC errors' if clean else 'it still has DRC errors'}, no case yet. "
            "Send a message to continue.")


async def card(project_id: str, state: Any) -> dict[str, Any] | None:
    """The board in the result card: version, counts, checks and its files."""
    row = await pcb_store.get(project_id)
    if row is None:
        return None
    v, checks = int(row["version"]), row.get("checks") or {}
    arts = set(row.get("artifacts") or {})
    return {"version": v, "counts": checks.get("counts") or {},
            "drc": {"errors": len(checks.get("errors") or []), "warnings": len(checks.get("warnings") or [])},
            "intent_ok": bool((checks.get("intent") or {}).get("ok", True)),
            "case_version": state.version if case_for(state) == v else None,
            "files": {n: pcb_store.artifact_url(project_id, v, n) for n in FAB + PREVIEWS if n in arts}}
