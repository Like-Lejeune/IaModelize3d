"""Agent tools for electronics enclosures (pack 'enclosure'): put a board into inputs.boards (from a photo or
the dataset) and check the case against it.

The hub (tools.py, prompts.py) offers TOOLS, hands the calls named in NAMES to run(), asks finish_gate()
before finish and puts PACK_TEXT, EXAMPLE and CLASSIFY_HINT into the prompts. check() runs the geometry
engine's inspect op 'enclosure' (plug rays through the port windows, collisions, button reach, lid fit,
keep-outs) and keeps the result as checks.enclosure of the version it checked, which the studio draws.
This module never imports tools.py at load time, so the hub can import it at its top.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from functools import lru_cache
from typing import Any

from ..config import settings
from ..db import get_db
from ..geom import GeomError, geom
from ..memory import store as memory

log = logging.getLogger(__name__)

INFRA_STAGES = ("crash", "timeout", "protocol")
FACT_SUBJECT = "case checked against the board"
BLOCK_ATTEMPTS = 3  # like printability errors: the first three finishes are blocked, then it ships and says so


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


@lru_cache
def _dataset() -> tuple[dict[str, Any], ...]:
    # read here rather than through vision.board, so importing the tools does not load the vision stack
    return tuple(json.loads((settings().geom_dir / "src" / "boards.json").read_text(encoding="utf-8"))["boards"])


def _dataset_ids() -> list[str]:
    return [b["id"] for b in _dataset()]


def dataset_board(board_id: str) -> dict[str, Any] | None:
    """A dataset board (boards.json) by id, as a fresh copy."""
    return next((copy.deepcopy(b) for b in _dataset() if b["id"] == board_id), None)


_S = {"type": "string"}
BOARD_NAME = {**_S, "description": "key under inputs.boards (default: board)"}

SCAN_BOARD = _fn(
    "scan_board",
    "Measure an electronics board on a photo and attach it as inputs.boards.<name> (fw.board/1 JSON) for lib.elec. Muse Spark reads "
    "the silkscreen and picks the board from the dataset; SAM 3.1 finds the mounting holes and the USB port; the scale comes from "
    "the board's own mounting holes (or an A4 sheet / bank card under it). Dataset numbers win and the photo gives deltas; heights "
    "are typical (verify). Rebuilds the current case program when it reads inputs.boards.",
    {"asset_id": _S, "hint": {**_S, "description": "what the person calls the board, e.g. 'Pico W' (optional)"}, "name": BOARD_NAME},
    ["asset_id"])
USE_BOARD = _fn(
    "use_board",
    "Attach a board without a photo as inputs.boards.<name>: a dataset id (" + ", ".join(_dataset_ids()) + ") or a complete fw.board/1 "
    "JSON from a datasheet or the person's measurements (validated against the schema). Rebuilds the current case program when it "
    "reads inputs.boards.",
    {"board_id": {**_S, "description": "dataset id or a marking such as 'Pico W'"},
     "spec": {"type": "object", "description": "a complete fw.board/1 board instead of board_id"}, "name": BOARD_NAME},
    [])
CHECK_ENCLOSURE = _fn(
    "check_enclosure",
    "Check the case against the board it must hold: plug paths through every port window (a ray grid over the plug section), board "
    "and part collisions, PCB supports, button reach (plunger gap, tongue strain), LED windows, lid fit and snap strain, antenna "
    "keep-outs. Builds the assembled layout with the board ghost. Errors block finish.",
    {"board": BOARD_NAME}, [])

TOOLS = [SCAN_BOARD, USE_BOARD, CHECK_ENCLOSURE]
NAMES = {t["name"] for t in TOOLS}


def tools(photos: bool) -> list[dict[str, Any]]:
    """The tools of this module for one job, in a stable order (prompt caching): scan_board only with a photo."""
    return [USE_BOARD] + ([SCAN_BOARD] if photos else []) + [CHECK_ENCLOSURE]


# ------------------------------------------------------------------ the case program
_PARAM_LINES = {
    "wall": "{{ value: {v}, min: 1.2, max: 4, step: 0.1, unit: 'mm', label: 'Wall', source: 'design', group: 'Shell' }}",
    "floor": "{{ value: {v}, min: 1.0, max: 4, step: 0.2, unit: 'mm', label: 'Floor', source: 'design', group: 'Shell' }}",
    "lid": "{{ value: {v}, min: 1.0, max: 3, step: 0.2, unit: 'mm', label: 'Lid', source: 'design', group: 'Shell' }}",
    "clear": "{{ value: {v}, min: 0.2, max: 2, step: 0.1, unit: 'mm', label: 'Gap around the board', source: 'design', group: 'Fit' }}",
    "standoff": "{{ value: {v}, min: 1.5, max: 12, step: 0.1, unit: 'mm', label: 'Space under the board', source: 'design', group: 'Fit' }}",
    "port_fit": "{{ value: {v}, min: 0.1, max: 1.0, step: 0.05, unit: 'mm', label: 'Gap around plugs', source: 'design', group: 'Fit' }}",
    "lights": "{{ value: {v}, options: ['hole', 'skin'], label: 'LED window', source: 'design', group: 'Access' }}",
    "mount": "{{ value: {v}, options: ['peg', 'auto', 'screw'], label: 'Board mount', source: 'design', group: 'Fit' }}",
}
DEFAULTS: dict[str, Any] = {"wall": 2.0, "floor": 1.6, "lid": 1.6, "clear": 0.5, "standoff": 2.5, "port_fit": 0.3, "lights": "hole", "mount": "peg"}
CHOICES = {"lights": ("hole", "skin"), "mount": ("peg", "auto", "screw")}
PRINT_NOTES = "Base floor-down, lid top-down; PETG for the snap hooks (PLA works), 0.2 mm layers, no supports."


def _js(v: Any) -> str:
    """A param default as JavaScript: numbers, or one of the validated option strings."""
    return f"{v:g}" if isinstance(v, float) else f"'{v}'"


_GEOMETRY_ONLY = {"src", "verify", "note", "evidence", "sources", "source", "frame", "aliases", "castellations", "headers", "uncertainty_mm"}


def _geometry(v: Any) -> Any:
    """A board JSON without its provenance (sources, verify lists, notes): what lib.elec builds from."""
    if isinstance(v, dict):
        return {k: _geometry(x) for k, x in v.items() if k not in _GEOMETRY_ONLY and not k.endswith(("_src", "_verify", "_note"))}
    if isinstance(v, list):
        return [_geometry(x) for x in v]
    return v


def enclosure_program(board: str = "board", *, title: str = "Board snap case", mockup: bool = False, fallback: dict[str, Any] | None = None,
                      **opts: Any) -> str:
    """The snap-fit case program for inputs.boards.<board> (EXAMPLE is this with the defaults). opts set the defaults of
    wall, floor, lid, clear, standoff, port_fit (mm), lights ('hole'|'skin') and mount ('peg'|'auto'|'screw'). mockup adds
    a printed stand-in of the PCB (lib.elec.pcbPlate with its mount and pin holes) next to the case in the print layout.
    fallback: a board built into the program (its geometry only) for a project that carries no inputs.boards.<board>."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", board):
        raise ValueError(f"board name must be an identifier: {board!r}")
    unknown = set(opts) - set(DEFAULTS)
    if unknown:
        raise TypeError(f"unknown case options: {', '.join(sorted(unknown))}")
    vals = {**DEFAULTS, **opts}
    for k, allowed in CHOICES.items():
        if vals[k] not in allowed:
            raise ValueError(f"{k} must be one of {allowed}")
    for k in DEFAULTS:
        if k not in CHOICES:
            vals[k] = float(vals[k])
    meta = json.dumps({"title": title, "pack": "enclosure", "printNotes": PRINT_NOTES}, ensure_ascii=True)
    ref = f"lib.inputs.boards.{board}"
    lines = [
        f"// Snap-fit case for the board in inputs.boards.{board} (fw.board/1): lib.elec builds it, check_enclosure verifies it.",
        f"const meta = {meta};",
        *([f"// {re.sub(r'[^A-Za-z0-9 .()+-]', '', str(fallback.get('name') or 'the board'))[:60]}, for a project without inputs.boards.{board}",
           f"const BOARD = {json.dumps(_geometry(fallback), ensure_ascii=True, separators=(',', ':'))};"] if fallback else []),
        "const params = {",
        *[f"  {k}: {_PARAM_LINES[k].format(v=_js(vals[k]))}," for k in DEFAULTS],
        *(["  mockup: { value: true, label: 'Printed stand-in for the PCB', source: 'design' },"] if mockup else []),
        "  layout: { value: 'print', options: ['print', 'assembled'], label: 'Layout', source: 'design' },",
        "  show_board: { value: false, label: 'Show the board', source: 'design' },",
        "};",
        "function build(p, lib) {",
        "  const E = lib.elec;",
        f"  const spec = (lib.inputs.boards && {ref}){' || BOARD' if fallback else ''};",
        f"  lib.assert(spec, 'attach the board JSON as inputs.boards.{board}');",
        "  const b = E.board(spec);",
        "  const enc = E.enclosure(b, { wall: p.wall, floor: p.floor, lid: p.lid, clear: p.clear, standoff: p.standoff,",
        "    portFit: p.port_fit, lights: p.lights, mount: p.mount });",
    ]
    if mockup:
        lines += [
            "  const parts = E.parts(enc, { layout: p.layout, ghost: p.show_board });",
            "  if (p.mockup && p.layout !== 'assembled') {",
            "    // the PCB's stand-in in front of the case: try the real module and the case before the board is made",
            "    const plate = E.pcbPlate(b), pb = plate.boundingBox(), cb = enc.base.boundingBox();",
            "    parts.push(lib.part(plate.translate([cb.min[0] - pb.min[0], cb.min[1] - 6 - pb.max[1], -pb.min[2]]), { name: 'pcb_mockup', color: '#3a7d44' }));",
            "  }",
            "  return parts;",
        ]
    else:
        lines.append("  return E.parts(enc, { layout: p.layout, ghost: p.show_board });")
    lines += ["}", "return { meta, params, build };", ""]
    return "\n".join(lines)


EXAMPLE = enclosure_program()

PACK_TEXT = """
# Pack: enclosures for electronics (a case around a board)
- The board comes first, as JSON in inputs.boards.board (fw.board/1: mm, origin at the PCB's bottom-left corner seen from the
  component side, z up from the PCB's bottom face). scan_board reads it from a photo (dataset boards need no reference: the scale
  comes from their own holes; other boards lie on an A4 sheet); use_board takes a dataset id (rpi-pico-w, xiao-esp32c3, ...) or a
  full board JSON from a datasheet. Never retype board numbers into the program: it reads lib.inputs.boards.board.
- Build with lib.elec, like the case example: const b = E.board(spec); const enc = E.enclosure(b, opts); return E.parts(enc,
  { layout: p.layout, ghost: p.show_board }). Keep the params layout ('print' default | 'assembled') and show_board (false): the
  check and the studio flip them, printing and export always use the print layout. Options: wall, floor, lid, clear (gap around
  the board), standoff (space under it), portFit (gap around plugs), mount 'peg'|'auto'|'screw' (+ screw 'M2'), lights
  'hole'|'skin', buttons 'flex'|'none', lidStyle 'hooks'|'plain', hookL/hookT/hookOver/hookW, tabLen, pressGap, chamfer, clips
  'edge'|'none' (lid clips that hold a board without mount holes down at its edges; default 'edge'). Expose
  wall, clear, standoff, port_fit, mount and lights as params. Extra features (a logo, a strap slot, feet) go on enc.base / enc.lid
  before E.parts and must stay clear of the port windows and the press tabs.
- Wall: 2.0 mm by default. Every wall from 1.2 mm prints clean, but the snap hooks hold firmer from 1.3 mm: their catch is
  0.28 mm at 1.3 and up, 0.20 mm at 1.2 (lid_fit says it). For a slim case choose 1.3; 1.2 only when every tenth counts, and
  then say the snap is weaker (or use lidStyle 'plain').
- Never put metal fasteners inside no_metal keep-outs (antennas): mount 'peg' or 'auto' keeps printed pegs there.
- Run check_enclosure after every change. Errors block finish: port_blocked -> raise port_fit or fix the port's plug/position in
  the board JSON; board_collision -> more clear, standoff or topGap; lid_fit -> fit or hook options; snap_strain over 4 % ->
  longer hooks (hookL) or less hookOver; metal_in_keepout -> peg mount. Boards without holes get edge clips from the lid by
  default (clips 'edge'); board_retained warns when the board can still tip or slide. Say the warnings honestly: board_retained,
  button_unreachable for side buttons (reachable with the lid off).
- Numbers marked verify in the board JSON (typical heights, positions scaled from drawings) are the risk: offer a peg-fit probe
  (propose_probe kind 'peg') when the hole fit matters, and name the verify fields a caliper should confirm.
- Summary: the board and where its numbers come from, USB clearance, plunger gap over the buttons, snap strain (PETG for a lid that
  opens often, PLA is near its limit), print orientation (base floor-down, lid top-down) and time.
""".strip()

CLASSIFY_HINT = "enclosure (a case, box or housing for an electronics board: Raspberry Pi, Pico, ESP32, XIAO, Arduino, a custom PCB)"


# ------------------------------------------------------------------ running the tools
async def run(ctx: Any, state: Any, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if name == "scan_board":
        return await _scan(ctx, state, args)
    if name == "use_board":
        return await _use(ctx, state, args)
    if name == "check_enclosure":
        try:
            enc = await check(ctx, state, _name(args.get("board")))
        except GeomError as e:
            return {"ok": False, "stage": e.stage, "error": e.message[:800]}, []
        return brief(enc), []
    return {"ok": False, "error": f"unknown tool {name}"}, []


def _name(v: Any) -> str:
    n = str(v or "board").strip()
    return n if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", n) else "board"


def board_brief(b: dict[str, Any]) -> dict[str, Any]:
    """What the designer needs to know about a board, without the provenance."""
    o = b["pcb"]["outline"]
    comps = b.get("components", [])
    verify = sum(len(c.get("verify") or []) for c in comps) + sum(len(h.get("verify") or []) for h in b["pcb"].get("holes", []))
    return {
        "id": b["id"], "name": b["name"], "source": b.get("source", {}).get("kind"),
        "size_mm": [o["w"], o["h"], b["pcb"]["thickness"]],
        "holes": [[h["x"], h["y"], h["d"], h.get("use", "mount")] for h in b["pcb"].get("holes", [])],
        "parts": [{k: c[k] for k in ("id", "type", "access", "edge", "at", "x", "y", "w", "h", "protrude", "plug") if k in c} for c in comps
                  if c.get("access") != "none"],
        "keepouts": [{k: ko[k] for k in ("id", "rule", "rect")} for ko in b.get("keepouts", [])],
        "heights": {k: (b.get("heights") or {}).get(k) for k in ("top_max", "bottom_max")},
        "verify_fields": verify,
    }


def _interface(b: dict[str, Any]) -> dict[str, Any]:
    """The board as a remembered interface: the numbers a later design needs."""
    o = b["pcb"]["outline"]
    return {"board": b.get("source", {}).get("dataset_id") or b["id"], "w": o["w"], "h": o["h"], "t": b["pcb"]["thickness"],
            "holes": [[h["x"], h["y"], h["d"]] for h in b["pcb"].get("holes", [])],
            "ports": {c["id"]: {"edge": c.get("edge"), "at": c.get("at"), "w": c.get("w")} for c in b.get("components", []) if c.get("access") == "port"},
            "top_max": (b.get("heights") or {}).get("top_max"), "bottom_max": (b.get("heights") or {}).get("bottom_max")}


async def _attach(ctx: Any, state: Any, name: str, board: dict[str, Any], source: str) -> tuple[dict[str, Any], list[str]]:
    """The board into inputs.boards and the person's remembered interfaces; the current case is rebuilt when it reads it."""
    state.inputs = {**(state.inputs or {}), "boards": {**((state.inputs or {}).get("boards") or {}), name: board}}
    item = await memory.remember_interface(ctx.user["id"], board["name"][:60], _interface(board), source)
    await ctx.emit("memory", {"items": [{"kind": "interface", "name": item["name"]}]})
    out: dict[str, Any] = {"ok": True, "input": f"inputs.boards.{name}", "board": board_brief(board)}
    images: list[str] = []
    if state.source and "inputs.boards" in state.source:
        from .tools import commit_build

        ru = str((ctx.project.get("brief") or {}).get("language") or "").lower().startswith(("ru", "kk"))
        built, images = await commit_build(ctx, state, state.source, state.params, f"{'плата' if ru else 'board'}: {board['name']}")
        out["build"] = built
        if built.get("ok"):
            await after_build(ctx, state, built)
    else:
        out["next"] = (f"write the case program (lib.elec, reads lib.inputs.boards.{name}), then check_enclosure" if not state.source
                       else f"the current program does not read inputs.boards.{name}: rewrite it with lib.elec")
    return out, images


async def _asset(ctx: Any, asset_id: str) -> dict[str, Any] | None:
    db = await get_db()
    return await db.one("SELECT * FROM assets WHERE id = ? AND project_id = ?", asset_id, ctx.project_id)


async def _scan(ctx: Any, state: Any, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .. import storage
    from ..vision import board as vb

    asset = await _asset(ctx, str(args.get("asset_id") or ""))
    if not asset:
        return {"ok": False, "error": "unknown asset id; give the id of a photo of this project"}, []
    name = _name(args.get("name"))
    await ctx.status("Reading the board on the photo")
    try:
        out = await vb.scan_board(ctx.meter, asset, str(args.get("hint") or "")[:200] or None, name, model=ctx.models.fast)
    except ValueError as e:
        return {"ok": False, "error": str(e)}, []
    if out.get("schema_errors"):
        return {"ok": False, "error": "the scan did not give a valid board JSON: " + "; ".join(out["schema_errors"][:5]),
                "identified": out["identified"]}, []
    sel = out.get("selection")
    if sel:
        await ctx.emit("selection.added", {"id": sel["id"], "asset_id": sel["asset_id"], "role": sel["role"], "name": sel["name"],
                                           "mask_url": storage.url(sel.get("mask_path")), "data": sel["data"]})
    attached, images = await _attach(ctx, state, name, out["board"], "photo")
    cal = out["calibration"]
    # what was read and the scale come before the long board brief: the timeline keeps only the first 600 characters
    result = {
        "ok": attached.pop("ok"),
        "identified": out["identified"],
        "calibration": {k: cal[k] for k in ("method", "residual_mm", "pattern_mm", "mm_per_px", "uncertainty_mm", "pin_rows", "measured_mm", "reference")
                        if cal.get(k) is not None},
        **attached,
        "deltas": [{k: d[k] for k in ("part", "field", "dataset", "photo", "delta", "source", "applied")} for d in out["deltas"]][:14],
        **({"warnings": out["warnings"]} if out["warnings"] else {}),
    }
    return result, images


async def _use(ctx: Any, state: Any, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from ..vision import board as vb

    name = _name(args.get("name"))
    spec = args.get("spec")
    if isinstance(spec, str):  # some models send the object as a JSON string
        try:
            spec = json.loads(spec)
        except json.JSONDecodeError:
            spec = None
    if isinstance(spec, dict) and spec:
        spec = {"schema": "fw.board/1", **spec}
        spec.setdefault("source", {"kind": "dataset"})
        spec.setdefault("frame", vb.dataset()["frame"])
        errors = vb.schema_errors(spec)
        if errors:
            return {"ok": False, "error": "invalid fw.board/1 JSON: " + "; ".join(errors[:8])}, []
        return await _attach(ctx, state, name, spec, "user")
    board = vb.find_board(str(args.get("board_id") or ""))
    if not board:
        return {"ok": False, "error": f"no dataset board {args.get('board_id')!r}; known: {', '.join(_dataset_ids())}. "
                                      "For another board give spec (fw.board/1) or scan a photo of it"}, []
    return await _attach(ctx, state, name, board, "dataset")


# ------------------------------------------------------------------ the check (C3 -> checks.enclosure, C5)
def summary(res: dict[str, Any], spec: dict[str, Any] | None) -> dict[str, Any]:
    """The three numbers the studio and the result card show: USB clearance, plunger gap, snap strain."""
    clearance = res.get("clearance") or {}
    usb = [c["id"] for c in (spec or {}).get("components", []) if c.get("access") == "port" and str(c.get("type", "")).startswith("usb")]
    vals = [clearance[i] for i in usb if isinstance(clearance.get(i), (int, float))]

    def first(code: str, pick: Any) -> float | None:
        v = [f["value"] for f in res.get("findings") or [] if f.get("code") == code and isinstance(f.get("value"), (int, float))]
        return pick(v) if v else None

    return {"usb_clearance_mm": min(vals) if vals else None, "button_gap_mm": first("button_reach", min), "snap_strain_pct": first("snap_strain", max),
            **({"case_mm": res["size"]} if isinstance(res.get("size"), list) else {})}


def enclosure_checks(res: dict[str, Any], board: str, spec: dict[str, Any] | None, version: int) -> dict[str, Any]:
    """checks.enclosure (C5) from an inspect op 'enclosure' result (C3)."""
    findings = res.get("findings") or []
    return {**res, "board": board, "ok": not any(f.get("severity") == "error" for f in findings), "summary": summary(res, spec), "version": version,
            **({"board_name": spec["name"]} if (spec or {}).get("name") else {})}


async def check(ctx: Any, state: Any, board: str = "board") -> dict[str, Any]:
    """inspect op 'enclosure' on the current version (with the params and inputs it was built with), kept as its
    checks.enclosure: the C3 result plus {board, ok, summary, version}. Raises GeomError when the engine fails."""
    from .tools import _geom_retry, _render_args

    if not state.source:
        return {"ok": False, "board": board, "error": "no program yet", "findings": [], "rays": [], "clearance": {}, "summary": summary({}, None),
                "version": state.version}
    ra = _render_args(state)
    params = ra.pop("params")
    out = await _geom_retry(lambda: geom().inspect(state.source, params, [{"op": "enclosure", "board": board}], **ra))
    res = (out.get("results") or [{}])[0]
    findings = res.get("findings") or []
    spec = ((ra.get("inputs") or {}).get("boards") or {}).get(board)
    enc = enclosure_checks(res, board, spec, state.version)
    db = await get_db()
    await db.execute("UPDATE programs SET checks = json_set(COALESCE(checks, '{}'), '$.enclosure', json(?)) WHERE project_id = ? AND version = ?",
                     json.dumps(enc), ctx.project_id, state.version)
    if state.last_build is not None:
        state.last_build.setdefault("checks", {})["enclosure"] = enc
    # the independent reviewer reads these as measured facts
    state.facts = [f for f in state.facts if f.get("subject") != FACT_SUBJECT] + [{
        "subject": FACT_SUBJECT, "attribute": (spec or {}).get("name", board), "value": {**enc["summary"], "errors": [f["msg"] for f in findings if f.get("severity") == "error"][:4],
                                                                                        "warnings": [f["msg"] for f in findings if f.get("severity") == "warn"][:4]},
        "unit": "mm / %", "source_kind": "check_enclosure", "source_url": None, "confidence": 1.0}]
    await ctx.emit("enclosure.checked", {"version": state.version, "enclosure": enc})
    return enc


def brief(enc: dict[str, Any]) -> dict[str, Any]:
    """The check for the designer: every problem in full, the passes as one line each."""
    if enc.get("error"):
        return {"ok": False, "error": enc["error"]}
    fs = enc.get("findings") or []

    def full(f: dict[str, Any]) -> dict[str, Any]:
        return {k: f[k] for k in ("code", "part", "msg", "value", "unit") if f.get(k) is not None} | ({"fix": h} if (h := hint(f)) else {})

    return {"ok": enc["ok"], "version": enc.get("version"), **({"board_name": enc["board_name"]} if enc.get("board_name") else {}),
            "summary": enc.get("summary"), "clearance_mm": enc.get("clearance"),
            "errors": [full(f) for f in fs if f.get("severity") == "error"], "warnings": [full(f) for f in fs if f.get("severity") == "warn"],
            "passed": [f["msg"] for f in fs if f.get("severity") == "info"][:16]}


HINTS = {
    "port_blocked": "raise port_fit, or fix the port's plug size and position in the board JSON",
    "board_collision": "more clear around the board, a taller standoff, or topGap for tall parts",
    "component_clear": "more clear around that part",
    "pcb_seated": "the board must rest on standoffs or ledges: build with lib.elec (E.parts) so the board ghost is there, check mount and the holes",
    "button_reach": "change pressGap (plunger gap) or tabLen",
    "button_unreachable": "a side or bottom button gets no actuator yet: say it is reachable with the lid off",
    "light_window": "lights 'hole', or a thinner skin",
    "lid_fit": "the lid and the base overlap: change fit or the hook options",
    "snap_strain": "longer hooks (hookL), less hookOver, or lidStyle 'plain'",
    "metal_in_keepout": "mount 'peg' or 'auto': no metal screws in no_metal keep-outs",
    "board_retained": "keep clips 'edge' (default) and clear at most 0.5 mm; free part of the board rim of parts so a clip fits",
}
# a top button whose plunger is there but misses it (gap, a blocked tongue, too much strain) is an error, not the side-button note
PLUNGER_HINT = "change pressGap so the plunger sits 0.1-0.8 mm over the button, keep the tongue's slots clear of the lid, or lengthen tabLen until the bending strain is under 2 %"


def hint(f: dict[str, Any]) -> str | None:
    if f.get("code") == "button_unreachable" and f.get("severity") == "error":
        return PLUNGER_HINT
    return HINTS.get(f.get("code"))  # type: ignore[arg-type]


async def after_build(ctx: Any, state: Any, result: dict[str, Any]) -> None:
    """For the hub, after a build of a case: check it at once and add the brief to the build result."""
    boards = (state.inputs or {}).get("boards") or {}
    if not boards or not state.source or "inputs.boards" not in state.source:
        return
    name = "board" if "board" in boards else next(iter(boards))
    try:
        result["enclosure"] = brief(await check(ctx, state, name))
    except GeomError as e:
        result["enclosure"] = {"ok": False, "stage": e.stage, "error": e.message[:500]}


async def finish_gate(ctx: Any, state: Any) -> list[str]:
    """Why finish must wait: the error findings of the case check on the version that would ship (checked now if
    it was not yet). Nothing to say without a board or a program, after BLOCK_ATTEMPTS finishes, or when the
    engine itself failed (that is not the design's fault)."""
    boards = (state.inputs or {}).get("boards") or {}
    if not state.source or not boards or state.finish_attempts > BLOCK_ATTEMPTS:
        return []
    name = "board" if "board" in boards else next(iter(boards))
    enc = ((state.last_build or {}).get("checks") or {}).get("enclosure")
    if not enc or enc.get("version") != state.version or enc.get("board") != name:
        try:
            enc = await check(ctx, state, name)
        except GeomError as e:
            if e.stage in INFRA_STAGES:
                log.warning("case check skipped at finish: %s %s", e.stage, e.message[:200])
                return []
            return [f"the assembled case does not build ({e.stage}): {e.message[:300]}"]
    return [f"{f['code']} ({f.get('part')}): {f.get('msg')}" + (f" -> {h}" if (h := hint(f)) else "")
            for f in enc.get("findings") or [] if f.get("severity") == "error"]
