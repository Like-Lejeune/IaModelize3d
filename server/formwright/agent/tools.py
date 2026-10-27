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


def fn(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or list(properties)}}


S = {"type": "string"}
N = {"type": "number"}

TOOLS: list[dict[str, Any]] = [
    fn("write_program", "Write the full program (replaces the current one). Builds it, runs full printability checks and returns a render sheet.",
       {"source": {**S, "description": "complete JavaScript program ending with return { meta, params, handles, build }"},
        "summary": {**S, "description": "one line: what this version does"}}),
    fn("edit_program", "Apply exact text replacements to the current program, then build/check/render. Cheaper than rewriting.",
       {"edits": {"type": "array", "items": {"type": "object", "properties": {"find": S, "replace": S}, "required": ["find", "replace"]}},
        "summary": S}),
    fn("set_params", "Change parameter values (no code change), then build/check/render.",
       {"values": {"type": "object", "description": "param name -> value"}, "summary": S}),
    fn("inspect_model", "Measure the current model. ops: {op:'section', z} | {op:'parts'} | {op:'gap', a, b} | {op:'ray', from:[x,y,z], to:[x,y,z]}",
       {"ops": {"type": "array", "items": {"type": "object"}}}),
    fn("render_view", "Render the current model: view 'sheet' (6 views), 'iso', or 'photo' (drawn over a calibrated photo, needs asset_id).",
       {"view": {"type": "string", "enum": ["sheet", "iso", "photo"]}, "asset_id": {**S, "description": "for view='photo'"}}, ["view"]),
    fn("look_at", "Look at a project image again at higher resolution, optionally a crop given as [x1,y1,x2,y2] on a 0-1000 grid.",
       {"asset_id": S, "crop": {"type": "array", "items": N}}, ["asset_id"]),
    fn("scene", "Current measurements from photos and calipers: calibrations, selected objects with mm outlines/holes/uncertainty.", {}, []),
    fn("measure_photo", "Segment an object on a photo by a short noun phrase and measure it in mm (needs a reference object in the photo).",
       {"asset_id": S, "target": {**S, "description": "short noun phrase, e.g. 'white plastic clip'"},
        "role": {"type": "string", "enum": ["target", "mating", "reference", "context"]}, "name": S}, ["asset_id", "target"]),
    fn("read_caliper", "Read a caliper display on a photo.", {"asset_id": S}),
    fn("lookup_standard", "Look up built-in standards: screws (M2-M8: clearance, nut, insert, heads), bearings, threads (metric, BSP), references (A4, card, coins), mounts (VESA, Raspberry Pi), sockets, fits, materials.",
       {"query": S}),
    fn("search_dimensions", "Search the web for official dimensions of a real product/standard. Results are cached as facts with source URLs.",
       {"query": S}),
    fn("recall", "Search memory: the user's measured interfaces and preferences, lessons, reusable skills.", {"query": S}),
    fn("remember_interface", "Save a measured interface of the user's world for future designs (e.g. 'vacuum hose', {od: 32}).",
       {"name": S, "values": {"type": "object"}, "source": S}),
    fn("ask_user", "Ask the user one question that changes the design and cannot be measured. Give 2-4 concrete options.",
       {"question": S, "options": {"type": "array", "items": S}, "allow_text": {"type": "boolean"}}, ["question", "options"]),
    fn("fit_to_photo", "Let a numeric optimizer tune the given numeric params so the model's silhouette matches the selected object's mask on calibrated photos.",
       {"params": {"type": "array", "items": S}, "selection": {**S, "description": "selection name (default: the target)"}}, ["params"]),
    fn("propose_probe", "Offer a quick test print to resolve an uncertain fit-critical dimension (variants around the nominal value).",
       {"kind": {"type": "string", "enum": ["hole", "peg", "gap", "thread", "clip"]}, "nominal": N, "dimension": S,
        "variants": {"type": "array", "items": N}}, ["kind", "nominal", "dimension"]),
    fn("concept_images", "Generate concept images for a form (Muse Image) to agree on the look before modelling.",
       {"prompt": S, "n": {"type": "integer"}}, ["prompt"]),
    fn("load_terrain", "Load a real elevation heightmap for a place (name or lat/lon) into inputs.heightmaps.terrain.",
       {"place": S, "lat": N, "lon": N, "size_km": N}, ["size_km"]),
    fn("save_skill", "Propose a reusable, tested module for future designs. source must be a function body that ends with `return function(lib, opts) {...}`.",
       {"name": S, "source": S, "doc": S, "test_call": {**S, "description": "e.g. lib.skills.name({w: 20})"}, "expected_size": {"type": "array", "items": N}},
       ["name", "source", "doc", "test_call"]),
    fn("compare_print", "Compare a photo of the PRINTED part (on a reference sheet) with the target: the selected original outline if given, else the model's footprint. Returns deviations and suggested corrections.",
       {"asset_id": S, "target": {**S, "description": "selection name of the original part (optional)"}}, ["asset_id"]),
    fn("finish", "Finish when the model is printable and matches the intent. Runs an independent critic and full checks first.",
       {"summary": {**S, "description": "final message to the user (their language)"}}),
]


def _skills_used(source: str) -> list[str]:
    return sorted(set(re.findall(r"lib\.skills\.([A-Za-z_][A-Za-z0-9_]*)", source)))


def _checks_brief(checks: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not checks:
        return []
    out = []
    for i in checks.get("issues", [])[:10]:
        out.append({"severity": i["severity"], "code": i["code"], "message": i["message"], "hints": i.get("hints", [])[:2]})
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


async def commit_build(ctx: JobContext, state: DesignState, source: str, params: dict[str, Any], summary: str, author: str = "agent"):
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
    sheet = await geom().render(source, built["params"], view="sheet", tile=340, heat=True, title=ctx.project["title"], **extra)
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
    return result, [rel]


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


async def run_tool(ctx: JobContext, state: DesignState, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Returns (result for the model, image refs). Image refs are relative file paths or data URLs."""
    ctx.check_cancelled()
    if name == "write_program":
        state.params = {}
        return await commit_build(ctx, state, args["source"], {}, args.get("summary", ""))
    if name == "edit_program":
        if not state.source:
            return {"ok": False, "error": "no program yet; use write_program"}, []
        new, errors = _apply_edits(state.source, args.get("edits", []))
        if errors:
            return {"ok": False, "error": "; ".join(errors), "hint": "copy `find` exactly from the current program"}, []
        return await commit_build(ctx, state, new, state.params, args.get("summary", ""))
    if name == "set_params":
        if not state.source:
            return {"ok": False, "error": "no program yet"}, []
        return await commit_build(ctx, state, state.source, {**state.params, **(args.get("values") or {})}, args.get("summary", "params"))
    if name == "inspect_model":
        if not state.source:
            return {"ok": False, "error": "no program yet"}, []
        return await geom().inspect(state.source, state.params, args.get("ops", []), inputs=state.inputs), []
    if name == "render_view":
        if not state.source:
            return {"ok": False, "error": "no program yet"}, []
        view = args.get("view", "sheet")
        if view == "photo":
            scene = await _vision()
            asset = await _asset(ctx, args.get("asset_id", ""))
            cam = scene.camera_for_render(asset) if scene and asset else None
            if not cam:
                return {"ok": False, "error": "photo is not calibrated (no reference object found)"}, []
            r = await geom().render(state.source, state.params, camera=cam, inputs=state.inputs)
            from ..vision import overlay

            rel = overlay.compose(asset, base64.b64decode(r["png"]))
            await ctx.emit("scene", {"asset_id": asset["id"], "overlay": storage.url(rel)})
            return {"ok": True, "note": "model drawn over the photo with an orange outline"}, [rel]
        r = await geom().render(state.source, state.params, view=view, heat=True, inputs=state.inputs)
        rel = storage.save_bytes(ctx.project_id, "renders", f"v{state.version}_{view}.png", base64.b64decode(r["png"]))
        return {"ok": True}, [rel]
    if name == "look_at":
        asset = await _asset(ctx, args.get("asset_id", ""))
        if not asset:
            return {"ok": False, "error": "unknown asset"}, []
        return {"ok": True}, [_crop_data_url(asset["path"], args.get("crop"))]
    if name == "scene":
        scene = await _vision()
        if not scene:
            return {"ok": False, "error": "vision module unavailable"}, []
        summary = await scene.scene_summary(ctx.project_id)
        state.inputs.update(summary.get("inputs", {}))
        return summary, []
    if name == "measure_photo":
        scene = await _vision()
        asset = await _asset(ctx, args.get("asset_id", ""))
        if not scene or not asset:
            return {"ok": False, "error": "vision unavailable or unknown asset"}, []
        from ..models import SelectRequest

        sel = await scene.select(ctx.user, ctx.project_id, asset, SelectRequest(text=args["target"], role=args.get("role", "target"), name=args.get("name")))
        await ctx.emit("selection.added", {"id": sel["id"], "asset_id": sel["asset_id"], "role": sel["role"], "name": sel["name"],
                                           "mask_url": storage.url(sel.get("mask_path")), "data": sel["data"]})
        summary = await scene.scene_summary(ctx.project_id)
        state.inputs.update(summary.get("inputs", {}))
        d = sel["data"]
        return {k: d.get(k) for k in ("name", "calibrated", "size_mm", "holes_mm", "uncertainty_mm", "confidence", "area_px")} | {"name": sel["name"]}, []
    if name == "read_caliper":
        scene = await _vision()
        asset = await _asset(ctx, args.get("asset_id", ""))
        if not scene or not asset:
            return {"ok": False, "error": "vision unavailable or unknown asset"}, []
        return await scene.read_caliper(ctx.meter, asset), []
    if name == "lookup_standard":
        return {"results": knowledge.lookup_standard(args.get("query", ""))}, []
    if name == "search_dimensions":
        await ctx.status(f"Searching: {args.get('query', '')}")
        r = await knowledge.search_dimensions(ctx.meter, args.get("query", ""), ctx.user["id"], ctx.models.fast)
        items = [{k: f.get(k) for k in ("subject", "attribute", "value", "unit", "source_kind", "source_url", "confidence")} for f in r["facts"]]
        for it in items:
            if isinstance(it["value"], str):
                try:
                    it["value"] = json.loads(it["value"])
                except json.JSONDecodeError:
                    pass
        state.facts.extend(items)
        await ctx.emit("facts", {"items": items})
        return {"facts": items, "from_cache": r.get("from_cache", False), "notes": r.get("notes", "")}, []
    if name == "recall":
        mem = await memory.recall(ctx.user["id"], args.get("query", ""), state.pack)
        ids = [m["id"] for items in mem.values() for m in items]
        state.memory_ids.extend(ids)
        await memory.mark_used(ids)
        if ids:
            await ctx.emit("memory", {"items": [{"kind": m["kind"], "name": m["name"]} for items in mem.values() for m in items]})
        return {"memory": memory.format_recall(mem) or "nothing relevant"}, []
    if name == "remember_interface":
        item = await memory.remember_interface(ctx.user["id"], args["name"], args.get("values") or {}, args.get("source", "agent"))
        await ctx.emit("memory", {"items": [{"kind": "interface", "name": item["name"]}]})
        return {"ok": True}, []
    if name == "ask_user":
        state.questions += 1
        if state.questions > 4:
            return {"answer": None, "note": "question limit reached; proceed with your best assumption and state it"}, []
        answer = await ctx.ask(args["question"], args.get("options") or [], bool(args.get("allow_text", True)))
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
    if name == "save_skill":
        test = {"call": args.get("test_call"), "size": args.get("expected_size"), "tol": 0.6}
        item_id = await memory.propose_skill(args["name"], args["source"], args["doc"], test, state.pack, ctx.job_id)
        return {"ok": True, "id": item_id, "status": "candidate (becomes active after it passes its test and helps twice)"}, []
    if name == "compare_print":
        return await _compare_print(ctx, state, args)
    if name == "finish":
        return await _finish(ctx, state, args.get("summary", "")), []
    return {"ok": False, "error": f"unknown tool {name}"}, []


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
