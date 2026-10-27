"""The design agent loop (Responses API, append-only history for prefix caching)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from .. import storage
from ..config import settings
from ..db import get_db, now
from ..knowledge.facts import lookup_standard
from ..llm.client import meta
from ..memory import store as memory
from ..models import SendMessage
from .examples import EXAMPLES_TEXT
from .prompts import CLASSIFY, PACK_NAMES, PACKS, SYSTEM
from .runner import JobContext, add_message
from . import dossier as dossier_mod
from . import narrate
from .tools import TOOLS, DesignState, run_tool

log = logging.getLogger(__name__)

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "pack": {"type": "string", "enum": PACK_NAMES},
        "title": {"type": "string", "description": "2-5 word project title"},
        "refuse": {"type": "boolean"},
        "reason": {"type": "string"},
        "language": {"type": "string", "description": "user's language, e.g. en, ru, kk"},
    },
    "required": ["pack", "title", "refuse", "reason", "language"],
}


async def _prepare_scene(ctx: JobContext, assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Deterministic first: calibrate photos and read calipers before the LLM thinks."""
    try:
        from ..vision import scene
    except ImportError:
        return None
    for a in assets:
        try:
            if a["kind"] in ("photo", "sketch", "print") and not a["meta"].get("calibration") and not a["meta"].get("calibration_failed"):
                await ctx.status("Looking for a reference object to calibrate the photo")
                await scene.calibrate(ctx.meter, a)
            elif a["kind"] == "caliper" and not a["meta"].get("caliper"):
                await ctx.status("Reading the caliper")
                await scene.read_caliper(ctx.meter, a)
        except Exception as e:  # noqa: BLE001 - a failed calibration is information, not a crash
            log.info("scene prep for %s: %s", a["id"], e)
    try:
        return await scene.scene_summary(ctx.project_id)
    except Exception as e:  # noqa: BLE001
        log.info("scene summary: %s", e)
        return None


async def _video_notes(ctx: JobContext, assets: list[dict[str, Any]]) -> list[str]:
    notes = []
    for a in assets:
        if a["kind"] != "video":
            continue
        try:
            from ..vision import video

            await ctx.status("Watching the video")
            text = await video.understand(ctx.meter, a, "Describe the object being shown, what it is for, what is broken or wanted, "
                                                         "and every dimension or constraint mentioned aloud.")
            notes.append(f"Video {a['id']}: {text}")
        except Exception as e:  # noqa: BLE001
            log.info("video understanding failed: %s", e)
    return notes


def _item_dict(item: Any) -> dict[str, Any]:
    d = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else dict(item)
    d.pop("status", None) if d.get("type") == "reasoning" else None
    return d


async def design(ctx: JobContext, body: SendMessage) -> str | None:
    db = await get_db()
    project = ctx.project
    brief = project.get("brief") or {}
    all_assets = await db.all("SELECT * FROM assets WHERE project_id = ? ORDER BY created_at", ctx.project_id)
    new_assets = [a for a in all_assets if a["id"] in body.asset_ids] or ([] if brief.get("turns") else all_assets)

    # until the classifier answers, guess from the script (Cyrillic -> Russian)
    language = brief.get("language") or ("ru" if re.search(r"[А-Яа-яЁё]", body.text or "") else "en")
    stage = {"current": None}

    async def set_stage(name: str) -> None:
        if stage["current"] != name:
            stage["current"] = name
            await ctx.emit("job.stage", {"stage": name, "label": narrate.stage_label(name, language)})

    await set_stage("understand")
    # pack + safety, once per project
    pack = project.get("pack")
    if not pack or project["title"] in ("New project", "Untitled"):
        await ctx.status("Understanding the request")
        cls = await meta().json(ctx.meter, model=ctx.models.fast, system=CLASSIFY,
                                content=[{"type": "input_text", "text": body.text or "(photos only)"}], schema=CLASSIFY_SCHEMA, name="classify", effort="minimal")
        if cls.get("refuse"):
            text = f"I can't help with this one: {cls.get('reason', '')}"
            await add_message(ctx.project_id, "agent", text)
            await ctx.emit("agent.message", {"text": text})
            return "refused"
        pack = pack or cls.get("pack", "household")
        language = cls.get("language") or language
        updates = {"pack": pack}
        if project["title"] in ("New project", "Untitled") and cls.get("title"):
            updates["title"] = cls["title"][:60]
            project["title"] = updates["title"]
        await db.update("projects", "id", ctx.project_id, updates)
    if pack not in PACKS:
        pack = "household"

    state = DesignState(pack=pack)
    current = await db.one("SELECT * FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", ctx.project_id)
    if current:
        state.source, state.params, state.version, state.inputs = current["source"], current["params"], current["version"], current["inputs"] or {}

    if any(a["kind"] in ("photo", "sketch", "caliper", "print", "video") for a in (new_assets or all_assets)):
        await set_stage("measure")
    scene = await _prepare_scene(ctx, new_assets or all_assets)
    if scene:
        state.inputs.update(scene.get("inputs", {}))
    video_notes = await _video_notes(ctx, new_assets)
    depth = dossier_mod.depth_for(pack, new_assets or all_assets, body.dossier or settings().dossier)
    if depth != "off" and not (state.source and depth == "short"):
        # follow-up edits of an existing model skip the short dossier; photos always get one
        await set_stage("measure" if depth == "full" else "understand")
        try:
            state.dossier = await dossier_mod.build(ctx, pack=pack, request=body.text, assets=new_assets or all_assets, scene=scene,
                                                    depth=depth, language=language)
        except Exception:  # noqa: BLE001 - analysis improves the design but must never block it
            log.exception("dossier failed")
        if state.dossier:
            await ctx.emit("dossier", state.dossier)
            await ctx.emit("tool.result", {"name": "dossier", "kind": "scene", "ok": True, "title": dossier_mod.summary_title(state.dossier, language),
                                           "summary": json.dumps({k: state.dossier.get(k) for k in ("motif", "size", "measured")}, ensure_ascii=False)[:600]})
    mem = await memory.recall(ctx.user["id"], body.text, pack)
    state.memory_ids = [m["id"] for items in mem.values() for m in items]
    await memory.mark_used(state.memory_ids)

    # ---- context: stable instructions first, project specifics after
    # SYSTEM + examples are identical for every pack, so that prefix stays cached across projects
    instructions = SYSTEM + "\n\n" + EXAMPLES_TEXT + "\n\n" + PACKS[pack]
    ctx_lines = [f"# Project: {project['title']} (pack: {pack}, reply in language: {language})"]
    if brief.get("summary"):
        ctx_lines.append(f"Previous result: {brief['summary']}")
    if brief.get("turns"):
        ctx_lines.append("Earlier requests: " + " | ".join(brief["turns"][-5:]))
    for a in all_assets:
        meta_bits = {k: a["meta"].get(k) for k in ("transcript", "exif") if a["meta"].get(k)}
        if a["meta"].get("calibration"):
            c = a["meta"]["calibration"]
            meta_bits["calibrated_with"] = c.get("reference")
            meta_bits["mm_per_px"] = c.get("mm_per_px")
        ctx_lines.append(f"- asset {a['id']} kind={a['kind']} {a['width']}x{a['height']} {json.dumps(meta_bits, ensure_ascii=False)[:400]}")
    if scene:
        ctx_lines.append("# Scene (measured)\n" + json.dumps({k: v for k, v in scene.items() if k != "inputs"}, ensure_ascii=False)[:6000])
        if scene.get("inputs", {}).get("outlines"):
            ctx_lines.append("Program inputs available: inputs.outlines." + ", inputs.outlines.".join(scene["inputs"]["outlines"]))
    ctx_lines.extend(video_notes)
    if state.dossier:
        ctx_lines.append(dossier_mod.for_designer(state.dossier))
        ctx_lines.append("Use the dossier: start from its measured proportions, counts and most likely motif hypothesis, resolve its "
                         "unknowns as it says, and aim to pass its checklist. It is the analyst's reading of the photo, not ground "
                         "truth: where the photo clearly shows otherwise, follow the photo.")
    recalled = memory.format_recall(mem)
    if recalled:
        ctx_lines.append("# Memory (relevant)\n" + recalled)
    if brief.get("printer"):
        ctx_lines.append(f"Printer: {brief['printer']}")
    if state.source:
        ctx_lines.append(f"# Current program (version {state.version}); params {json.dumps(state.params, ensure_ascii=False)}\n```js\n{state.source}\n```")
    ctx_lines.append("# Request\n" + (body.text or "(see photos)"))
    content: list[dict[str, Any]] = [{"type": "input_text", "text": "\n".join(ctx_lines)}]
    for a in (new_assets or all_assets)[:6]:
        if a["kind"] in ("photo", "sketch", "caliper", "concept"):
            content.append({"type": "input_text", "text": f"asset {a['id']} ({a['kind']}):"})
            content.append({"type": "input_image", "image_url": storage.data_url(a["path"], 1280)})
    history: list[dict[str, Any]] = [{"type": "message", "role": "user", "content": content}]

    model = ctx.models.designer
    max_turns = settings().max_iterations * 3
    final_text: str | None = None
    for turn in range(max_turns):
        ctx.check_cancelled()
        effort = "medium" if turn < max_turns - 2 else "low"
        resp = await meta().respond(ctx.meter, model=model, instructions=instructions, input=history, tools=TOOLS, effort=effort,
                                    max_output_tokens=12000, cache_key=f"fw-agent-{pack}")
        calls = []
        for item in resp.output or []:
            d = _item_dict(item)
            history.append(d)
            t = d.get("type")
            if t == "reasoning":
                summary = " ".join(s.get("text", "") for s in d.get("summary", []) if isinstance(s, dict))
                if summary:
                    await ctx.emit("agent.thinking", {"text": summary[:2000]})
            elif t == "message":
                text = " ".join(c.get("text", "") for c in d.get("content", []) if isinstance(c, dict))
                if text.strip():
                    final_text = text.strip()
                    await ctx.emit("agent.status", {"text": final_text[:400]})
            elif t == "function_call":
                calls.append(d)
        if not calls:
            # The review gate lives in finish(); a model that just stops talking does not skip it.
            if state.source and not state.done and state.finish_attempts == 0 and turn < max_turns - 1:
                history.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text":
                                "Call finish with your summary; it runs the independent review and the final checks."}]})
                continue
            break
        images: list[str] = []
        for call in calls:
            name = call.get("name", "")
            try:
                args = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            preview = {k: (v if len(json.dumps(v, ensure_ascii=False)) < 300 else "…") for k, v in args.items()}
            kind = narrate.KIND.get(name, "other")
            await set_stage(narrate.STAGE.get(kind, stage["current"] or "design"))
            await ctx.emit("tool.call", {"id": call.get("call_id"), "name": name, "kind": kind, "title": narrate.localize(narrate.call_title(name, args), language), "args": preview})
            try:
                result, imgs = await run_tool(ctx, state, name, args)
            except Exception as e:  # noqa: BLE001 - report to the model, keep going
                log.exception("tool %s failed", name)
                result, imgs = {"ok": False, "error": f"{type(e).__name__}: {e}"[:800]}, []
            images.extend(imgs)
            ok = result.get("ok", result.get("accepted", True)) is not False
            await ctx.emit("tool.result", {"id": call.get("call_id"), "name": name, "kind": kind, "ok": ok,
                                           "title": narrate.localize(narrate.result_title(name, args, result), language),
                                           "summary": json.dumps(result, ensure_ascii=False)[:600],
                                           "image": storage.url(imgs[0]) if imgs and not imgs[0].startswith("data:") else None})
            history.append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(result, ensure_ascii=False)[:12000]})
        if images:
            parts: list[dict[str, Any]] = [{"type": "input_text", "text": "Images from the tools above:"}]
            for ref in images[:4]:
                parts.append({"type": "input_image", "image_url": ref if ref.startswith("data:") else storage.data_url(ref, None if ref.endswith(".png") else 1280)})
            history.append({"type": "message", "role": "user", "content": parts})
        if state.done:
            break
        if turn == max_turns - 3 and not state.done:
            history.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text":
                            "You are close to the turn limit. Fix only blocking problems and call finish with an honest summary."}]})

    text = state.summary or final_text or ("I ran out of steps before finishing; the latest version is in the viewer." if state.source else "No model yet.")
    await add_message(ctx.project_id, "agent", text, {"version": state.version, "critic": state.critic})
    await ctx.emit("agent.message", {"text": text, "version": state.version})
    if state.source and state.last_build:
        await set_stage("done")
        card = result_card(ctx, state)
        card["next"] = [{**n, "label": narrate.localize(n["label"], language)} for n in card["next"]]
        await ctx.emit("result", card)
    turns = (brief.get("turns") or []) + [body.text[:200]]
    await db.update("projects", "id", ctx.project_id, {"brief": {**brief, "turns": turns[-10:], "summary": text[:800], "language": language}, "updated_at": now()})
    await memory.record_outcome(state.memory_ids, success=state.done)
    if state.done and state.source and (state.critic or {}).get("verdict") == "pass":
        asyncio.create_task(_harvest_skill(ctx, state.source, pack))
    return text[:300]


async def _harvest_skill(ctx: JobContext, source: str, pack: str) -> None:
    from ..memory.skills import harvest

    r = await harvest(source, pack, ctx.job_id, ctx.models.fast)
    if r:
        await ctx.emit("memory", {"items": [{"kind": "skill", "name": r["name"], "status": "candidate", "doc": r["doc"]}]})


def result_card(ctx: JobContext, state: DesignState) -> dict[str, Any]:
    """Everything the person needs at a glance when the agent hands over."""
    build = state.last_build or {}
    checks = build.get("checks") or {}
    stats = checks.get("stats") or {}
    issues = checks.get("issues") or []
    specs = build.get("paramSpecs") or {}
    params = [
        {"name": k, "label": s.get("label") or k, "value": state.params.get(k, s.get("value")), "unit": s.get("unit"), "source": s.get("source", "design")}
        for k, s in specs.items() if not s.get("hidden")
    ]
    errors = sum(1 for i in issues if i["severity"] == "error")
    nxt = [{"action": "download", "label": "Download 3MF"}, {"action": "slice", "label": "Prepare print settings"}]
    if any(p["source"] in ("photo", "assumed") for p in params):
        nxt.append({"action": "probe", "label": "Print a 5-minute test piece"})
    nxt += [{"action": "order", "label": "Order a print"}, {"action": "share", "label": "Share as a recipe"}]
    return {
        "version": state.version,
        "title": ctx.project["title"],
        "size_mm": [round(v, 1) for v in stats.get("size", [])],
        "est_grams": round(stats.get("estGrams", 0), 1),
        "est_minutes": round(stats.get("estMinutes", 0)),
        "params_with_sources": params,
        "checks": {"ok": checks.get("ok", True), "errors": errors, "warnings": sum(1 for i in issues if i["severity"] == "warn"), "score": checks.get("score")},
        "critic": state.critic or {},
        "cover": f"/files/{ctx.project_id}/renders/v{state.version}_iso.png",
        "render": f"/files/{state.last_render}" if state.last_render else None,
        "cost_usd": round(ctx.meter.usd, 4),
        "next": nxt,
    }


def standards_hint(query: str) -> str:
    return json.dumps(lookup_standard(query), ensure_ascii=False)
