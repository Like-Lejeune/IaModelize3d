"""Agent tools. Each returns (result_json, images) — images are attached to the next
user turn because the API reads images only in user messages."""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

from .. import storage
from ..db import get_db, now
from ..geom import GeomError, geom
from ..knowledge import facts as knowledge
from ..memory import store as memory
from .runner import JobContext

log = logging.getLogger(__name__)


@dataclass
class DesignState:
    pack: str
    source: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    version: int = 0
    inputs: dict[str, Any] = field(default_factory=dict)
    last_build: dict[str, Any] | None = None
    last_render: str | None = None
    issue_codes: set[str] = field(default_factory=set)
    last_edit_summary: str = ""
    finish_attempts: int = 0
    questions: int = 0
    done: bool = False
    summary: str = ""
    memory_ids: list[str] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    printer: dict[str, Any] | None = None
    critic: dict[str, Any] | None = None
    copies_photo: bool = False  # the photo shows the object to reproduce: builds come with a likeness panel
    view_elevation: float = 15.0
    view_azimuth: float = 0.0


def fn(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or list(properties)}}


S = {"type": "string"}
N = {"type": "number"}

WRITE = fn("write_program", "Write the full program (replaces the current one). Builds it, runs the printability checks and returns what you need to judge it: "
           "size, issues with exact locations, a 6-view render and, for copies of a photo, the model next to the photo.",
           {"source": {**S, "description": "complete JavaScript program ending with return { meta, params, handles, build }"},
            "summary": {**S, "description": "one line: what this version does (user's language)"}})
EDIT = fn("edit_program", "Apply exact text replacements to the current program, then build and check it like write_program. Cheaper than rewriting.",
          {"edits": {"type": "array", "items": {"type": "object", "properties": {"find": S, "replace": S}, "required": ["find", "replace"]}},
           "summary": S})
SET_PARAMS = fn("set_params", "Change parameter values (no code change), then build and check.",
                {"values": {"type": "object", "description": "param name -> value"}, "summary": S})
INSPECT = fn("inspect_model", "Measure the current model. ops: {op:'section', z} | {op:'parts'} | {op:'gap', a, b} | {op:'ray', from:[x,y,z], to:[x,y,z]} | "
             "{op:'surface', from:'front'|'back'|'left'|'right'|'top'|'bottom', points:[[u,v],...]} (points on the skin seen from that side with "
             "their normals: front/back take (x, z), left/right take (y, z), top/bottom take (x, y); use them to place strokes and pads) | "
             "{op:'extremes'} (the outermost point in each direction: tips of ears, nose, tail)",
             {"ops": {"type": "array", "items": {"type": "object"}}})
LOOK = fn("look", "Look closely. what='model': 6 views of the model with overhang heat; add `views` for your own angles, `zoom` for a close-up "
          "of a region or a part, `cut` for a section (walls, cavities, how deep a groove is). what='compare': the model next to the object on "
          "the photo, seen from the same angle (set elevation to the photo's camera angle), with silhouette numbers. what=<asset id>: an input "
          "image at full resolution, optionally a crop [x1,y1,x2,y2] on a 0-1000 grid.",
          {"what": S, "crop": {"type": "array", "items": N}, "elevation": {**N, "description": "degrees above the horizon, for 'compare'"},
           "azimuth": {**N, "description": "degrees around the model, 0 = its front (-Y side), for 'compare'"},
           "views": {"type": "array", "description": "up to 6 angles for what='model'", "items": {"type": "object", "properties": {
               "azimuth": {**N, "description": "0 = from -Y (front), 90 = from +X (right), 180 = from +Y, 270 = from -X"},
               "elevation": {**N, "description": "degrees above the horizon (negative = from below)"}}, "required": ["azimuth", "elevation"]}},
           "zoom": {"type": "object", "description": "close-up for what='model': {part: name} or {center: [x,y,z], size: mm}",
                    "properties": {"part": S, "center": {"type": "array", "items": N}, "size": N}},
           "cut": {"type": "object", "description": "section for what='model': keeps the side below `at` on `axis` and looks at the cut face",
                   "properties": {"axis": {"type": "string", "enum": ["x", "y", "z"]}, "at": N, "keep": {"type": "string", "enum": ["below", "above"]}},
                   "required": ["axis", "at"]},
           "markers": {"type": "boolean", "description": "mesh documents: numbered dots where each op acts (hollow when hidden behind the surface)"}}, ["what"])
DIMENSIONS = fn("dimensions", "Real dimensions with their source: built-in standards first (screws M2-M8, nuts, inserts, bearings, threads, "
                "VESA, Raspberry Pi, sockets, reference objects, fits, materials), then official specs from the web when the tables have nothing.",
                {"query": S, "web": {"type": "boolean", "description": "search the web even if the tables answer"}}, ["query"])
ASK = fn("ask_user", "Ask the user one question that changes the design and cannot be measured or looked up. Give 2-4 concrete options.",
         {"question": S, "options": {"type": "array", "items": S}, "allow_text": {"type": "boolean"}}, ["question", "options"])
FINISH = fn("finish", "Finish when the model is printable and matches the intent. Runs the full checks and an independent reviewer first.",
            {"summary": {**S, "description": "final message to the user (their language)"}})
MEASURE = fn("measure", "Measure on a photo: segment an object by a short noun phrase and get its outline, holes and size in mm with uncertainty "
             "(needs a reference object such as an A4 sheet or a bank card in the photo). target='caliper' reads a caliper display.",
             {"asset_id": S, "target": {**S, "description": "short noun phrase, e.g. 'white plastic clip', or 'caliper'"},
              "role": {"type": "string", "enum": ["target", "mating", "reference", "context"]}, "name": S}, ["asset_id", "target"])
FIT = fn("fit_to_photo", "Let a numeric optimizer tune the given numeric params so the model's silhouette matches the selected object on calibrated photos.",
         {"params": {"type": "array", "items": S}, "selection": {**S, "description": "selection name (default: the target)"}}, ["params"])
REMEMBER = fn("remember_interface", "Save a measured interface of the user's world for future designs (e.g. 'vacuum hose', {od: 32}).",
              {"name": S, "values": {"type": "object"}, "source": S})
PROBE = fn("propose_probe", "Offer a quick test print to resolve an uncertain fit-critical dimension (variants around the nominal value).",
           {"kind": {"type": "string", "enum": ["hole", "peg", "gap", "thread", "clip"]}, "nominal": N, "dimension": S,
            "variants": {"type": "array", "items": N}}, ["kind", "nominal", "dimension"])
CONCEPTS = fn("concept_images", "Generate concept images for a form (Muse Image) to agree on the look before modelling.",
              {"prompt": S, "n": {"type": "integer"}}, ["prompt"])
TERRAIN = fn("load_terrain", "Load a real elevation heightmap for a place (name or lat/lon) into inputs.heightmaps.terrain.",
             {"place": S, "lat": N, "lon": N, "size_km": N}, ["size_km"])
COMPARE_PRINT = fn("compare_print", "Compare a photo of the PRINTED part (on a reference sheet) with the target: the selected original outline if given, "
                   "else the model's footprint. Returns deviations and suggested corrections.",
                   {"asset_id": S, "target": {**S, "description": "selection name of the original part (optional)"}}, ["asset_id"])

MESH_WRITE = fn("mesh_write", "Start or replace the model as a mesh document (the mesh engine: a surface shaped by clay, sculpt strokes and "
                "deformations, for organic and free-form shapes). Builds and checks it like write_program; the 6 views show numbered dots "
                "where the ops act.",
                {"doc": {"type": "object", "description": "{engine:'mesh', meta, params, symmetry, detail, ops:[{id, op, ...}]}"},
                 "summary": {**S, "description": "one line: what this version does (user's language)"}})
MESH_EDIT = fn("mesh_edit", "Change the current mesh document without rewriting it: add ops (at the end or after an op id), update fields of ops "
               "by id, remove ops, add params, set symmetry/detail. Only ops from the first change on are recomputed. The views mark the ops "
               "you added or changed.",
               {"add": {"type": "array", "items": {"type": "object"}, "description": "new ops; give each a short id"},
                "after": {**S, "description": "insert the added ops after this op id (default: at the end)"},
                "update": {"type": "array", "description": "[{id, set: {field: value}}]; a null value removes the field",
                           "items": {"type": "object", "properties": {"id": S, "set": {"type": "object"}}, "required": ["id", "set"]}},
                "remove": {"type": "array", "items": S, "description": "op ids to delete"},
                "params": {"type": "object", "description": "param specs to add or replace: {name: {value, min, max, unit, label, source}}"},
                "symmetry": {"type": "string", "enum": ["x", "y", "none"]},
                "detail": {**N, "description": "default triangle size for clay and remesh, mm"},
                "summary": S}, ["summary"])

FIT_PACKS = {"household", "copy", "adapter", "mechanisms"}
LOOK_PACKS = {"forms", "stylize", "landmark"}


def tools_for(pack: str, *, photos: bool, prints: bool, engine: str = "cad") -> list[dict[str, Any]]:
    """Only the tools this job can use: fewer choices, fewer tokens. Order is stable per (pack, photos, prints, engine) for caching."""
    tools = [WRITE, EDIT, SET_PARAMS, INSPECT, LOOK, DIMENSIONS, ASK]
    if engine == "mesh":
        tools = [MESH_WRITE, MESH_EDIT] + tools
    if photos:
        tools += [MEASURE, FIT]
    if pack in FIT_PACKS:
        tools += [REMEMBER, PROBE]
    if pack in LOOK_PACKS:
        tools.append(CONCEPTS)
    if pack == "terrain":
        tools.append(TERRAIN)
    if prints:
        tools.append(COMPARE_PRINT)
    return tools + [FINISH]


def _skills_used(source: str) -> list[str]:
    return sorted(set(re.findall(r"lib\.skills\.([A-Za-z_][A-Za-z0-9_]*)", source)))


def _checks_brief(checks: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Grouped by kind (fewer tokens, less noise); errors keep up to 3 exact locations each."""
    if not checks:
        return []
    groups = checks.get("groups")
    if not groups:
        return [{"severity": i["severity"], "code": i["code"], "message": i["message"], "hints": i.get("hints", [])[:2]} for i in checks.get("issues", [])[:10]]
    out = []
    for g in groups[:8]:
        item: dict[str, Any] = {"severity": g["severity"], "code": g["code"], "title": g["title"], "count": g["count"], "hints": g.get("hints", [])[:2]}
        if g.get("z"):
            item["z_mm"] = [round(g["z"][0], 1), round(g["z"][1], 1)]
        if g["severity"] != "info":
            item["where"] = [i["message"] for i in checks.get("issues", []) if i["code"] == g["code"]][:3]
        out.append(item)
    return out


async def _printer(ctx: JobContext, state: DesignState) -> dict[str, Any] | None:
    if state.printer is None:
        try:
            from ..printing import fingerprint, service

            printer_id = (ctx.project.get("brief") or {}).get("printer")
            state.printer = service.printer_profile(printer_id, await fingerprint.load(ctx.user["id"], printer_id))
        except Exception:  # printing module optional
            state.printer = {}
    return state.printer or None


def is_mesh_doc(source: str | None) -> bool:
    return bool(source) and source.lstrip().startswith("{") and re.search(r'"engine"\s*:\s*"mesh"', source[:4000]) is not None


def _num(v: Any, params: dict[str, Any]) -> float | None:
    """A number, or a "$name" parameter reference (expressions are left to the engine)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str) and v.strip().startswith("$"):
        x = params.get(v.strip()[1:])
        return float(x) if isinstance(x, (int, float)) else None
    return None


def op_anchor(op: dict[str, Any], params: dict[str, Any]) -> list[float] | None:
    """Where an op acts, for markers (mirrors meshdoc/ops.ts opAnchor)."""
    shape = (op.get("shapes") or [op])[0] if op.get("op") == "clay" else None
    region = op.get("region") if isinstance(op.get("region"), dict) else {}
    strokes = op.get("strokes") or [{}]
    cands = [shape.get("at") if shape else None, shape.get("from") if shape else None, op.get("at"), (op.get("path") or [None])[0],
             strokes[0].get("at") if isinstance(strokes[0], dict) else None, (strokes[0].get("path") or [None])[0] if isinstance(strokes[0], dict) else None,
             region.get("at")]
    if region.get("min") and region.get("max"):
        cands.append([(a + b) / 2 if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None for a, b in zip(region["min"], region["max"])])
    for c in cands:
        if isinstance(c, list) and len(c) == 3:
            xyz = [_num(v, params) for v in c]
            if all(v is not None for v in xyz):
                return xyz  # type: ignore[return-value]
    return None


def mesh_markers(doc: dict[str, Any], ids: set[str] | None, params: dict[str, Any]) -> list[dict[str, Any]]:
    values = {k: (s.get("value") if isinstance(s, dict) else s) for k, s in (doc.get("params") or {}).items()} | params
    out = []
    for i, op in enumerate(doc.get("ops") or []):
        if not isinstance(op, dict) or op.get("enabled") is False or (ids is not None and op.get("id") not in ids):
            continue
        at = op_anchor(op, values)
        if at:
            out.append({"at": at, "label": f"{i + 1} {op.get('id') or op.get('op')}"[:12]})
    return out[:24]


def _ops_brief(doc: dict[str, Any]) -> list[str]:
    return [f"{i + 1}. {op.get('id', '?')}: {op.get('op')}{'' if op.get('enabled', True) else ' (off)'}{' - ' + str(op['note'])[:60] if op.get('note') else ''}"
            for i, op in enumerate(doc.get("ops") or []) if isinstance(op, dict)]


async def commit_build(ctx: JobContext, state: DesignState, source: str, params: dict[str, Any], summary: str, author: str = "agent",
                       markers: list[dict[str, Any]] | None = None):
    skills = await memory.active_skill_sources(_skills_used(source))
    inputs = {**state.inputs, **({"skills": skills} if skills else {})}
    printer = await _printer(ctx, state)
    extra: dict[str, Any] = {"inputs": inputs}
    if printer:
        extra["printer"] = printer
    try:
        built = await geom().build(source, params, analyze="full", **extra)
    except GeomError as e:
        await ctx.emit("tool.result", {"name": "build", "ok": False, "summary": f"{e.stage}: {e.message[:300]}"})
        return {"ok": False, "stage": e.stage, "error": e.message[:1500], "hint": "fix the program; the previous version is unchanged"}, []
    db = await get_db()
    state.version = (await db.one("SELECT COALESCE(MAX(version), 0) AS v FROM programs WHERE project_id = ?", ctx.project_id))["v"] + 1  # type: ignore[index]
    checks = built.get("checks") or {}
    sheet = await geom().render(source, built["params"], view="sheet", tile=340, heat=True, title=ctx.project["title"],
                                **({"markers": markers} if markers else {}), **extra)
    rel = storage.save_bytes(ctx.project_id, "renders", f"v{state.version}.png", base64.b64decode(sheet["png"]))
    iso = await geom().render(source, built["params"], view="iso", tile=512, **extra)
    cover = storage.save_bytes(ctx.project_id, "renders", f"v{state.version}_iso.png", base64.b64decode(iso["png"]))
    await db.insert("programs", {"project_id": ctx.project_id, "version": state.version, "source": source, "params": built["params"], "inputs": inputs,
                                 "summary": summary, "checks": checks, "author": author, "created_at": now()})
    await db.update("projects", "id", ctx.project_id, {"version": state.version, "cover": cover, "updated_at": now()})
    # lessons: a failing code that disappeared after this edit is evidence for a fix
    new_codes = {i["code"] for i in checks.get("issues", []) if i["severity"] != "info"}
    for code in state.issue_codes - new_codes:
        await memory.observe_fix(code, summary, state.pack, ctx.job_id)
    state.issue_codes = new_codes
    state.source, state.params, state.last_build, state.last_render = source, built["params"], built, rel
    event = {"version": state.version, "source": source, "inputs": inputs, "params": built["params"], "paramSpecs": built["paramSpecs"],
             "handles": built.get("handles", []), "checks": checks, "render": storage.url(rel), "cover": storage.url(cover),
             "summary": summary, "author": author}
    if len(json.dumps(inputs)) > 100_000:
        # big heightmaps stay out of the event stream; the client fetches the version instead
        event.pop("source")
        event.pop("inputs")
    await ctx.emit("program.updated", event)
    stats = checks.get("stats", {})
    result = {
        "ok": True,
        "version": state.version,
        "size_mm": [round(v, 2) for v in stats.get("size", [])],
        "volume_mm3": round(stats.get("volume", 0)),
        "est_grams": round(stats.get("estGrams", 0), 1),
        "printable": checks.get("ok", True),
        "score": checks.get("score"),
        "issues": _checks_brief(checks),
        "params": built["params"],
        "parts": [{"name": p["name"], "role": p["role"]} for p in built.get("parts", [])],
    }
    if is_mesh_doc(source):
        result["ops"] = _ops_brief(json.loads(source))
    images = [rel]
    if state.copies_photo:
        result["likeness"], panels = await _likeness(ctx, state)
        images += panels
    return result, images


def _apply_edits(source: str, edits: list[dict[str, str]]) -> tuple[str, list[str]]:
    errors = []
    for e in edits:
        find, rep = e.get("find", ""), e.get("replace", "")
        n = source.count(find) if find else 0
        if n == 0:
            errors.append(f"not found: {find[:80]!r}")
        elif n > 1:
            errors.append(f"ambiguous ({n} matches): {find[:80]!r}")
        else:
            source = source.replace(find, rep)
    return source, errors


async def _vision():
    try:
        from ..vision import scene  # noqa: F401

        return scene
    except ImportError:
        return None


async def _asset(ctx: JobContext, asset_id: str) -> dict[str, Any] | None:
    db = await get_db()
    return await db.one("SELECT * FROM assets WHERE id = ? AND project_id = ?", asset_id, ctx.project_id)


def _crop_data_url(rel: str, crop: list[float] | None) -> str:
    if not crop:
        return storage.data_url(rel, 1600)
    img = Image.open(storage.abs_path(rel)).convert("RGB")
    w, h = img.size
    x1, y1, x2, y2 = [max(0.0, min(1000.0, float(v))) for v in crop[:4]]
    box = (int(x1 / 1000 * w), int(y1 / 1000 * h), max(int(x2 / 1000 * w), int(x1 / 1000 * w) + 8), max(int(y2 / 1000 * h), int(y1 / 1000 * h) + 8))
    part = img.crop(box)
    part.thumbnail((1600, 1600))
    buf = io.BytesIO()
    part.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

async def _likeness(ctx: JobContext, state: DesignState) -> tuple[list[dict[str, Any]], list[str]]:
    """The model next to each photographed object it copies (copy tasks only)."""
    from . import compare

    facts, images = [], []
    for asset, sel in await compare.targets(ctx.project_id):
        try:
            r = await compare.panel(ctx.project_id, state, asset, sel, state.view_elevation, state.view_azimuth)
        except Exception as e:  # noqa: BLE001 - feedback is a bonus, never a failure of the build
            log.info("likeness panel failed: %s", e)
            continue
        if r:
            facts.append(r[0])
            images.append(r[1])
    return facts, images


async def _look(ctx: JobContext, state: DesignState, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    what = str(args.get("what", "model")).strip()
    if what in ("model", "compare") and not state.source:
        return {"ok": False, "error": "no program yet"}, []
    if what == "model":
        extra: dict[str, Any] = {}
        if args.get("views"):
            extra["views"] = [{"azimuth": float(v.get("azimuth", 0)), "elevation": float(v.get("elevation", 0))} for v in args["views"][:6] if isinstance(v, dict)]
        zoom = args.get("zoom") or {}
        if zoom.get("part"):
            extra["focus"] = {"part": str(zoom["part"])}
        elif zoom.get("center") and zoom.get("size"):
            extra["focus"] = {"center": [float(v) for v in zoom["center"][:3]], "size": float(zoom["size"])}
        if args.get("cut"):
            c = args["cut"]
            extra["cut"] = {"axis": c.get("axis", "z"), "at": float(c.get("at", 0)), "keep": c.get("keep", "below")}
        if args.get("markers") and is_mesh_doc(state.source):
            extra["markers"] = mesh_markers(json.loads(state.source), None, state.params)
        try:
            r = await geom().render(state.source, state.params, view="sheet", heat=not extra, inputs=state.inputs, **extra)
        except GeomError as e:
            return {"ok": False, "error": e.message[:500]}, []
        name = f"v{state.version}_look{'_' + '_'.join(sorted(extra)) if extra else ''}.png"
        return {"ok": True}, [storage.save_bytes(ctx.project_id, "renders", name, base64.b64decode(r["png"]))]
    if what == "compare":
        if args.get("elevation") is not None:
            state.view_elevation = max(-10.0, min(80.0, float(args["elevation"])))
        if args.get("azimuth") is not None:
            state.view_azimuth = float(args["azimuth"]) % 360
        facts, images = await _likeness(ctx, state)
        if not images:
            return {"ok": False, "error": "no object selected on a photo; measure it first"}, []
        return {"ok": True, "likeness": facts, "note": "later builds use this angle"}, images
    asset = await _asset(ctx, what)
    if not asset:
        return {"ok": False, "error": "what must be 'model', 'compare' or an asset id"}, []
    return {"ok": True}, [_crop_data_url(asset["path"], args.get("crop"))]


async def run_tool(ctx: JobContext, state: DesignState, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Returns (result for the model, image refs). Image refs are relative file paths or data URLs."""
    ctx.check_cancelled()
    if name == "write_program":
        if not str(args.get("source") or "").strip():
            return {"ok": False, "error": "source is empty: pass the complete program"}, []
        state.params = {}
        return await commit_build(ctx, state, args["source"], {}, args.get("summary", ""))
    if name == "edit_program":
        if not state.source:
            return {"ok": False, "error": "no program yet; use write_program"}, []
        new, errors = _apply_edits(state.source, args.get("edits", []))
        if errors:
            return {"ok": False, "error": "; ".join(errors), "hint": "copy `find` exactly from the current program"}, []
        return await commit_build(ctx, state, new, state.params, args.get("summary", ""))
    if name == "mesh_write":
        return await _mesh_write(ctx, state, args)
    if name == "mesh_edit":
        return await _mesh_edit(ctx, state, args)
    if name == "set_params":
        if not state.source:
            return {"ok": False, "error": "no program yet"}, []
        values = args.get("values") or {}
        if isinstance(values, str):  # some models send the object as a JSON string
            try:
                values = json.loads(values)
            except json.JSONDecodeError:
                values = None
        if not isinstance(values, dict):
            return {"ok": False, "error": "values must be an object: {param name: value}"}, []
        return await commit_build(ctx, state, state.source, {**state.params, **values}, args.get("summary", "params"))
    if name == "inspect_model":
        if not state.source:
            return {"ok": False, "error": "no program yet"}, []
        return await geom().inspect(state.source, state.params, args.get("ops", []), inputs=state.inputs), []
    if name == "look":
        return await _look(ctx, state, args)
    if name == "measure":
        scene = await _vision()
        asset = await _asset(ctx, args.get("asset_id", ""))
        if not scene or not asset:
            return {"ok": False, "error": "vision unavailable or unknown asset"}, []
        if args.get("target", "").strip().lower() == "caliper":
            return await scene.read_caliper(ctx.meter, asset), []
        from ..models import SelectRequest

        sel = await scene.select(ctx.user, ctx.project_id, asset, SelectRequest(text=args["target"], role=args.get("role", "target"), name=args.get("name")))
        await ctx.emit("selection.added", {"id": sel["id"], "asset_id": sel["asset_id"], "role": sel["role"], "name": sel["name"],
                                           "mask_url": storage.url(sel.get("mask_path")), "data": sel["data"]})
        summary = await scene.scene_summary(ctx.project_id)
        state.inputs.update(summary.get("inputs", {}))
        d = sel["data"]
        return {k: d.get(k) for k in ("calibrated", "size_mm", "holes_mm", "uncertainty_mm", "confidence", "calibration_note") if d.get(k) is not None} | {"name": sel["name"]}, []
    if name == "dimensions":
        query = args.get("query", "")
        out: dict[str, Any] = {"standards": knowledge.lookup_standard(query)}
        if args.get("web") or not out["standards"]:
            await ctx.status(f"Searching: {query}")
            r = await knowledge.search_dimensions(ctx.meter, query, ctx.user["id"], ctx.models.fast)
            items = [{k: f.get(k) for k in ("subject", "attribute", "value", "unit", "source_kind", "source_url", "confidence")} for f in r["facts"]]
            for it in items:
                if isinstance(it["value"], str):
                    try:
                        it["value"] = json.loads(it["value"])
                    except json.JSONDecodeError:
                        pass
            state.facts.extend(items)
            if items:
                await ctx.emit("facts", {"items": items})
            out.update({"web": items, "notes": r.get("notes", "")})
        return out, []
    if name == "remember_interface":
        item = await memory.remember_interface(ctx.user["id"], args["name"], args.get("values") or {}, args.get("source", "agent"))
        await ctx.emit("memory", {"items": [{"kind": "interface", "name": item["name"]}]})
        return {"ok": True}, []
    if name == "ask_user":
        state.questions += 1
        if state.questions > 4:
            return {"answer": None, "note": "question limit reached; proceed with your best assumption and state it"}, []
        # models sometimes send {label, value} objects instead of strings; people read labels
        options = [o if isinstance(o, str) else str(o.get("label") or o.get("value") or "") if isinstance(o, dict) else str(o)
                   for o in args.get("options") or []]
        answer = await ctx.ask(args["question"], [o for o in options if o][:4], bool(args.get("allow_text", True)))
        return {"answer": answer} if answer is not None else {"answer": None, "note": "no answer; proceed with a stated assumption"}, []
    if name == "fit_to_photo":
        return await _fit_to_photo(ctx, state, args)
    if name == "propose_probe":
        from . import side

        return await side.make_probe(ctx, args), []
    if name == "concept_images":
        from . import side

        rels = await side.make_concepts(ctx, args.get("prompt", ""), int(args.get("n", 3) or 3))
        return {"ok": True, "count": len(rels), "note": "concepts shown to the user; ask which one to follow"}, rels
    if name == "load_terrain":
        from ..packs import terrain

        await ctx.status("Loading elevation data")
        hm = await terrain.load(ctx.meter, place=args.get("place"), lat=args.get("lat"), lon=args.get("lon"), size_km=float(args.get("size_km", 5)), model=ctx.models.fast)
        state.inputs.setdefault("heightmaps", {})["terrain"] = {k: hm[k] for k in ("w", "h", "data")}
        return {k: v for k, v in hm.items() if k != "data"}, []
    if name == "compare_print":
        return await _compare_print(ctx, state, args)
    if name == "finish":
        return await _finish(ctx, state, args.get("summary", "")), []
    return {"ok": False, "error": f"unknown tool {name}"}, []


def _as_obj(v: Any) -> Any:
    """Models sometimes send an object argument as a JSON string."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return None
    return v


def _name_ops(ops: list[Any], taken: set[str]) -> list[dict[str, Any]]:
    out = []
    for op in ops:
        if not isinstance(op, dict) or not isinstance(op.get("op"), str):
            raise ValueError(f"every op needs an \"op\" field: {json.dumps(op)[:120]}")
        op = dict(op)
        base = str(op.get("id") or op["op"])[:24]
        name, i = base, 2
        while name in taken:
            name, i = f"{base}{i}", i + 1
        op["id"] = name
        taken.add(name)
        out.append(op)
    return out


async def _mesh_write(ctx: JobContext, state: DesignState, args: dict[str, Any]):
    doc = _as_obj(args.get("doc"))
    if not isinstance(doc, dict) or not isinstance(doc.get("ops"), list) or not doc["ops"]:
        return {"ok": False, "error": "doc must be an object with a non-empty ops list"}, []
    doc = {"engine": "mesh", **{k: v for k, v in doc.items() if k != "engine"}}
    try:
        doc["ops"] = _name_ops(doc["ops"], set())
    except ValueError as e:
        return {"ok": False, "error": str(e)}, []
    state.params = {}
    return await commit_build(ctx, state, json.dumps(doc, ensure_ascii=False), {}, args.get("summary", ""),
                              markers=mesh_markers(doc, None, {}))


async def _mesh_edit(ctx: JobContext, state: DesignState, args: dict[str, Any]):
    if not is_mesh_doc(state.source):
        return {"ok": False, "error": "the current model is not a mesh document; start one with mesh_write"}, []
    if not any(args.get(k) not in (None, [], {}, "") for k in ("add", "update", "remove", "params", "symmetry", "detail")):
        return {"ok": False, "error": "nothing to change: give add, update or remove (or params, symmetry, detail)"}, []
    doc = json.loads(state.source or "{}")
    ops: list[dict[str, Any]] = doc.get("ops") or []
    ids = [o.get("id") for o in ops]
    touched: set[str] = set()
    errors = []
    for rid in args.get("remove") or []:
        if rid in ids:
            ops = [o for o in ops if o.get("id") != rid]
            ids = [o.get("id") for o in ops]
        else:
            errors.append(f"no op {rid!r} to remove")
    for u in _as_obj(args.get("update")) or []:
        if not isinstance(u, dict):
            continue
        op = next((o for o in ops if o.get("id") == u.get("id")), None)
        changes = _as_obj(u.get("set"))
        if op is None or not isinstance(changes, dict):
            errors.append(f"no op {u.get('id')!r} to update" if op is None else f"update {u.get('id')!r}: set must be an object")
            continue
        for k, v in changes.items():
            if k in ("id",):
                continue
            if v is None:
                op.pop(k, None)
            else:
                op[k] = v
        touched.add(op["id"])
    add = _as_obj(args.get("add")) or []
    if add:
        try:
            new = _name_ops(add, {i for i in ids if i})
        except ValueError as e:
            return {"ok": False, "error": str(e)}, []
        after = args.get("after")
        at = len(ops)
        if after:
            pos = next((i for i, o in enumerate(ops) if o.get("id") == after), None)
            if pos is None:
                errors.append(f"no op {after!r} to insert after; added at the end")
            else:
                at = pos + 1
        ops[at:at] = new
        touched |= {o["id"] for o in new}
    if errors and not touched and not args.get("remove"):
        return {"ok": False, "error": "; ".join(errors), "ops": _ops_brief(doc)}, []
    specs = _as_obj(args.get("params"))
    if isinstance(specs, dict):
        doc["params"] = {**(doc.get("params") or {}), **{k: v for k, v in specs.items() if isinstance(v, dict) and "value" in v}}
    if args.get("symmetry"):
        doc["symmetry"] = None if args["symmetry"] == "none" else args["symmetry"]
    if args.get("detail") is not None:
        doc["detail"] = float(args["detail"])
    doc["ops"] = ops
    source = json.dumps(doc, ensure_ascii=False)
    result, images = await commit_build(ctx, state, source, state.params, args.get("summary", ""),
                                        markers=mesh_markers(doc, touched or None, state.params))
    if errors:
        result["warnings"] = errors
    return result, images


async def _finish(ctx: JobContext, state: DesignState, summary: str) -> dict[str, Any]:
    from .critic import review

    state.finish_attempts += 1
    if state.source and state.last_build:
        errors = [i for i in (state.last_build.get("checks") or {}).get("issues", []) if i["severity"] == "error"]
        if errors and state.finish_attempts <= 3:
            return {"accepted": False, "reason": "printability errors remain", "issues": _checks_brief({"issues": errors})}
        if state.finish_attempts <= 2:
            await ctx.status("Independent review of the design")
            verdict = await review(ctx, state)
            if "verdict" not in verdict:
                verdict = {"verdict": "pass", "match_score": None, "issues": [], "note": "reviewer unavailable"}
            state.critic = verdict
            await ctx.emit("critic", {**verdict, "render": storage.url(state.last_render)})
            major = [i for i in verdict.get("issues", []) if i.get("severity") == "major"]
            # copying a look needs a real match, not "close enough"
            look_pack = state.pack in ("copy", "forms", "landmark", "stylize")
            score = verdict.get("match_score")
            if look_pack and isinstance(score, (int, float)) and score < 8 and not major:
                major = [{"severity": "major", "text": f"Match with the reference is only {score}/10.", "fix_hint": "; ".join(
                    i.get("text", "") for i in verdict.get("issues", []))[:500]}]
                verdict["verdict"] = "revise"
            if verdict.get("verdict") == "revise" and major:
                return {"accepted": False, "reason": "the reviewer found major problems", "issues": major}
    state.done = True
    state.summary = summary
    return {"accepted": True}


async def _compare_print(ctx: JobContext, state: DesignState, args: dict[str, Any]):
    """Closes the loop digital -> physical -> digital: measure the print, compare with the intent."""
    from ..models import SelectRequest
    from ..printing.compare import compare_outlines

    scene = await _vision()
    asset = await _asset(ctx, args.get("asset_id", ""))
    if not scene or not asset:
        return {"ok": False, "error": "vision unavailable or unknown asset"}, []
    sel = await scene.select(ctx.user, ctx.project_id, asset, SelectRequest(text="3D printed plastic part", role="context", name="printed"))
    printed = sel["data"].get("outline_mm")
    if not printed:
        return {"ok": False, "error": "the photo has no reference sheet/card, so the print cannot be measured in mm"}, []
    target = (state.inputs.get("outlines") or {}).get(args.get("target") or "")
    source = "original photo outline"
    if not target:
        if not state.source:
            return {"ok": False, "error": "no target: give the original selection name or design a model first"}, []
        out = await geom().inspect(state.source, state.params, [{"op": "outline"}], inputs=state.inputs)
        target = out["results"][0]["polygons"]
        source = "model footprint"
    report = compare_outlines(target, printed)
    report["compared_with"] = source
    await ctx.emit("tool.result", {"name": "compare_print", "ok": True, "summary": json.dumps({k: report.get(k) for k in ("max_mm", "mean_mm", "suggestions")}, ensure_ascii=False)[:600]})
    return report, []


async def _fit_to_photo(ctx: JobContext, state: DesignState, args: dict[str, Any]):
    if not state.source:
        return {"ok": False, "error": "no program yet"}, []
    scene = await _vision()
    if not scene:
        return {"ok": False, "error": "vision unavailable"}, []
    db = await get_db()
    sel_name = args.get("selection")
    sels = await db.all("SELECT * FROM selections WHERE project_id = ? AND role = 'target'" + (" AND name = ?" if sel_name else ""),
                        *([ctx.project_id, sel_name] if sel_name else [ctx.project_id]))
    targets = []
    for sel in sels[:3]:
        asset = await _asset(ctx, sel["asset_id"])
        cam = scene.camera_for_render(asset) if asset else None
        if not cam or not sel.get("mask_path"):
            continue
        mask = np.array(Image.open(storage.abs_path(sel["mask_path"])).convert("L")) > 127
        k = 480 / max(cam["width"], cam["height"])
        w, h = max(1, int(cam["width"] * k)), max(1, int(cam["height"] * k))
        small = np.array(Image.fromarray(mask.astype(np.uint8) * 255).resize((w, h), Image.NEAREST)) > 127
        cam_s = {**cam, "width": w, "height": h, "fx": cam["fx"] * k, "fy": cam["fy"] * k, "cx": cam["cx"] * k, "cy": cam["cy"] * k}
        targets.append({"camera": cam_s, "mask": base64.b64encode(np.packbits(small.flatten()).tobytes()).decode()})
    if not targets:
        return {"ok": False, "error": "no calibrated photo with a selected target mask"}, []
    await ctx.status("Fitting parameters to the photo silhouette")
    r = await geom().fit(state.source, state.params, free=args.get("params", []), targets=targets, inputs=state.inputs, maxEval=140)
    result, images = await commit_build(ctx, state, state.source, {**state.params, **r["params"]}, f"fitted {', '.join(r['params'])} to photo")
    result["fit"] = {"iou_before": round(r["iouBefore"], 3), "iou_after": round(r["iouAfter"], 3), "params": r["params"]}
    return result, images
