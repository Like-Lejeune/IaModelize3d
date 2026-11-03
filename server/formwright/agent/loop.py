"""The design agent loop (Responses API, append-only history for prefix caching)."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError
from PIL import Image

from .. import storage
from ..config import settings
from ..db import get_db, now
from ..geom import GeomError
from ..knowledge.facts import lookup_standard
from ..llm.english import english, remember as remember_english
from ..llm.client import BudgetExceeded, meta
from ..memory import store as memory
from ..models import SendMessage
from .examples import EXAMPLES_TEXT, PACK_EXAMPLES
from .prompts import CLASSIFY, MESH_ENGINE, PACK_NAMES, PACKS, SYSTEM
from .runner import JobContext, add_message
from . import narrate
from . import compare
from .side import GENERATED
from .tools import DesignState, _crop_data_url, device_tools, is_mesh_doc, pcb_tools, run_tool, tools_for

log = logging.getLogger(__name__)

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "pack": {"type": "string", "enum": PACK_NAMES},
        "title": {"type": "string", "description": "2-5 word project title in the user's language"},
        "refuse": {"type": "boolean"},
        "reason": {"type": "string", "description": "one short sentence in the user's language; empty unless refused"},
        "language": {"type": "string", "description": "user's language, e.g. en, ru, kk"},
        "subject": {"type": "string", "description": "short noun phrase for the main object in the photos, in the user's language; "
                                                    "never the reference sheet or card it lies on; empty without photos"},
        "subject_en": {"type": "string", "description": "the same noun phrase in English, e.g. 'white plastic clip' (the segmenter "
                                                       "reads English only); empty without photos"},
        "photo_role": {"type": "string", "enum": ["copy", "fit", "style", "none"],
                       "description": "copy: reproduce the object shown; fit: design something that fits or attaches to it; "
                                      "style: the look inspires a new design; none: no photos"},
        "engine": {"type": "string", "enum": ["cad", "mesh"],
                   "description": "mesh: sculpt a surface (living and free-form subjects); cad: a parametric program (everything exact)"},
    },
    "required": ["pack", "title", "refuse", "reason", "language", "subject", "subject_en", "photo_role", "engine"],
}

PHOTO_KINDS = ("photo", "sketch", "print")
HEARTBEAT_S = 15.0
# what ends a run early without making its versions worthless: those get a handover instead of a bare failure
STOPS = (BudgetExceeded, APIStatusError, APIConnectionError, APITimeoutError, httpx.HTTPError, TimeoutError, GeomError)
WRAP_UP = "You are close to the {} limit. Fix only blocking problems and call finish with an honest summary."
CUT_OFF = "Your last answer was cut off at the output limit; use edit_program/mesh_edit or a shorter program."
CUT_OFF_PCB = "Your last answer was cut off at the output limit; use write_circuit with edits on the current file, or a shorter file."
CUT_OFF_DEVICE = "Your last answer was cut off at the output limit; use write_device with edits on the current device, or fewer parts."
MAX_OUTPUT = {"high": 20000, "xhigh": 28000, "max": 32000}  # tokens per designer turn by effort; 12000 for the rest
# Per pack: a circuit file is long, and in the PCB spike medium effort twice spent all 12k tokens thinking and answered nothing.
PACK_LLM: dict[str, dict[str, Any]] = {"pcb": {"effort": "low", "max_output_tokens": 24000}, "device": {"effort": "low", "max_output_tokens": 24000}}


CYRILLIC = re.compile(r"[Ѐ-ӿ]")
LATIN_WORD = re.compile(r"\b[A-Za-z]{2,}\b")
CYRILLIC_LANGS = ("ru", "kk", "uk", "be", "bg", "sr", "mk", "ky", "tg", "mn")


def _script(text: str | None) -> str | None:
    """The script a message is written in: any Cyrillic (a Russian request names its 'Pico W' in Latin letters),
    else two Latin words; None for photos only, a number or a bare 'ok'."""
    if len(CYRILLIC.findall(text or "")) >= 2:
        return "cyrillic"
    return "latin" if len(LATIN_WORD.findall(text or "")) >= 2 else None


def message_language(text: str | None, earlier: str | None) -> str:
    """The language this message is answered in: the message's own script wins over the project's language (a Russian
    message in a project started in English gets Russian), and a project in another language of the same script keeps
    it (kk, de). A message without words keeps the project's language."""
    script, earlier = _script(text), str(earlier or "").strip().lower()
    if earlier and (script is None or (script == "cyrillic") == earlier.startswith(CYRILLIC_LANGS)):
        return earlier
    return "ru" if script == "cyrillic" else "en"


LANGUAGE_NAMES = {"english": "en", "russian": "ru", "kazakh": "kk", "русский": "ru", "английский": "en", "казахский": "kk", "қазақша": "kk"}


def language_hint(value: Any) -> str | None:
    """SendMessage.language as the short code the brief keeps ('ru', 'en', 'kk'; 'ru-RU' -> 'ru'), or None when it is
    missing or not a language: then the message's own script decides."""
    v = str(value or "").strip().lower()
    v = LANGUAGE_NAMES.get(v, v)
    return v.split("-")[0].split("_")[0] if re.fullmatch(r"[a-z]{2,3}(?:[-_][a-z0-9]{2,8})?", v) else None


# a progress line answers the checks and the reviewer, not the person: no 'You're right' / 'Вы правы' in front of it
AGREEMENT = re.compile(
    r"^\s*(?:(?:you(?:'re|’re| are)|(?:вы|ты))\s+(?:(?:absolutely|completely|quite|totally|абсолютно|совершенно|полностью)\s+)?(?:right|правы?)"
    r"(?:\s*[,—–-]?\s*(?:that|что)\b|\s*[,;:.!—–-]+)"
    r"|(?:good|great|nice)\s+(?:catch|point|call)\s*[,;:.!—–-]+|fair\s+point\s*[,;:.!—–-]+|agreed\s*[,;:.!—–-]+"
    r"|(?:thanks|thank\s+you|спасибо)(?:\s+(?:for|за)\b[^,;:.!—–]{0,48})?\s*[,;:.!—–-]+"
    r"|(?:верно|справедливо|согласен|согласна|хорошее\s+замечание|дұрыс\s+айтасыз)\s*[,;:.!—–-]+)\s*",
    re.I)


def without_agreement(text: str) -> str:
    """The progress line without a leading 'You're right —' / 'Вы правы, что' / 'Good catch:' clause, so it starts with
    what changes; a line that says nothing else stays as it is."""
    m = AGREEMENT.match(text)
    rest = text[m.end():].lstrip() if m else ""
    return rest[0].upper() + rest[1:] if rest else text


STICKER_CALL = "lib.collect.sticker("
# the snap page's «Сделать фигурку» message and what people type for the same wish
FIGURINE = re.compile(r"figurine|miniature|statuette|\b3d\b|фигурк|миниатюр|статуэтк|объ[её]мн", re.I)


def figurine_from_sticker(latest: dict[str, Any] | None, text: str | None, fresh_photos: bool) -> bool:
    """Whether this request turns a kept snap sticker (author 'instant', a lib.collect.sticker program) into a figurine:
    the photo sent again (the snap page's «Сделать фигурку») or a request for a miniature. A plate is not a sticker."""
    if not latest or latest.get("author") != "instant" or STICKER_CALL not in (latest.get("source") or ""):
        return False
    return fresh_photos or bool(FIGURINE.search(text or ""))


def llm_options(pack: str, effort: str) -> tuple[str, int]:
    """The effort and output budget of one designer turn: the pack's own where it has them."""
    o = PACK_LLM.get(pack, {})
    effort = o.get("effort") or effort
    return effort, max(MAX_OUTPUT.get(effort, 12000), int(o.get("max_output_tokens") or 0))


def instructions_for(pack: str, engine: str) -> str:
    """Stable first: SYSTEM and the shared examples are identical for every pack, so that prefix stays cached across
    projects; then the pack's rules and its own reference example, then the mesh engine."""
    out = SYSTEM + "\n\n" + EXAMPLES_TEXT + "\n\n" + PACKS[pack]
    if pack in PACK_EXAMPLES:
        out += "\n\n" + PACK_EXAMPLES[pack]
    return out + ("\n\n" + MESH_ENGINE if engine == "mesh" else "")


async def _calibrate(ctx: JobContext, assets: list[dict[str, Any]]) -> list[str]:
    """Find the scale reference on every photo first: the intake must know a white sheet is not the object."""
    try:
        from ..vision import scene
    except ImportError:
        return []

    async def one(a: dict[str, Any]) -> str | None:
        if not a["meta"].get("calibration") and not a["meta"].get("calibration_failed"):
            try:
                cal = await scene.calibrate(ctx.meter, a)
            except Exception as e:  # noqa: BLE001 - a failed calibration is information, not a crash
                log.info("calibration of %s: %s", a["id"], e)
                cal = {"ok": False, "reason": str(e)[:200]}
            a["meta"]["calibration"] = cal
        cal = a["meta"].get("calibration") or {}
        return f"{cal.get('reference')} on asset {a['id']}" if cal.get("ok") else None

    photos = [a for a in assets if a["kind"] in PHOTO_KINDS]
    if photos:
        await ctx.status("Looking for a reference object to calibrate the photo")
    return [r for r in await asyncio.gather(*(one(a) for a in photos)) if r]


async def _prepare_scene(ctx: JobContext, assets: list[dict[str, Any]], subject: str, language: str) -> dict[str, Any] | None:
    """Deterministic first, all at once: find and measure the subject on each photo, read calipers."""
    try:
        from ..vision import scene
    except ImportError:
        return None
    from ..models import SelectRequest
    from ..vision import spot

    # the studio may still be cutting the object out of a fresh photo: that selection is the one to measure
    await spot.settled([a["id"] for a in assets])
    db = await get_db()
    confirmed = {r["asset_id"] for r in await db.all("SELECT asset_id FROM selections WHERE project_id = ? AND role = 'target'", ctx.project_id)}

    async def photo(a: dict[str, Any]) -> None:
        if a["id"] in confirmed:
            return
        # a picked concept: Muse Image drew it, SAM cuts it out like the object on a photo
        drawn = a["kind"] == "concept"
        models = ([settings().model_image] if drawn else []) + [settings().model_sam, ctx.models.fast]
        try:
            await ctx.emit("tool.call", {"name": "measure", "kind": "measure", "models": models,
                                         "title": narrate.localize(f"Finding “{subject}” on the photo", language)})
            sel = await scene.select(ctx.user, ctx.project_id, a, SelectRequest(text=subject, role="target", name=subject))
            await ctx.emit("selection.added", {"id": sel["id"], "asset_id": sel["asset_id"], "role": sel["role"], "name": sel["name"],
                                               "mask_url": storage.url(sel.get("mask_path")), "data": sel["data"]})
            title = narrate.concept_title(language) if drawn else narrate.localize(
                narrate.result_title("measure", {"target": subject}, {**sel["data"], "name": subject}), language)
            await ctx.emit("tool.result", {"name": "measure", "kind": "measure", "ok": True, "models": models, "title": title})
        except Exception as e:  # noqa: BLE001 - not found is information, not a crash
            log.info("subject on %s: %s", a["id"], e)
            error = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
            await ctx.emit("tool.result", {"name": "measure", "kind": "measure", "ok": False, "models": models,
                                           "title": narrate.localize(narrate.result_title("measure", {}, {"ok": False, "error": error}), language)})

    async def caliper(a: dict[str, Any]) -> None:
        try:
            await scene.read_caliper(ctx.meter, a)
        except Exception as e:  # noqa: BLE001
            log.info("caliper %s: %s", a["id"], e)

    jobs = [photo(a) for a in assets if a["kind"] in ("photo", "concept") and subject]
    jobs += [caliper(a) for a in assets if a["kind"] == "caliper" and not a["meta"].get("caliper")]
    if jobs:
        await ctx.status("Measuring the photos")
        await asyncio.gather(*jobs)
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


async def _load_meshes(state: DesignState, assets: list[dict[str, Any]]) -> None:
    """Uploaded STL/OBJ files become inputs.meshes, so programs can edit them (lib.mesh.input)."""
    from ..geom import GeomError, geom

    for a in assets:
        name = (a["meta"].get("mesh") or {}).get("name")
        if a["kind"] != "mesh" or not name or name in (state.inputs.get("meshes") or {}):
            continue
        try:
            parsed = await geom().parse_mesh(storage.abs_path(a["path"]).read_bytes(), storage.abs_path(a["path"]).suffix)
        except (GeomError, OSError) as e:
            log.info("mesh %s: %s", a["id"], e)
            continue
        state.inputs.setdefault("meshes", {})[name] = {"positions": parsed["positions"], "triangles": parsed["triangles"]}


def _item_dict(item: Any) -> dict[str, Any]:
    d = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else dict(item)
    d.pop("status", None) if d.get("type") == "reasoning" else None
    return d


def _concept_subject(a: dict[str, Any]) -> str:
    """What a concept shows, from the prompt it was drawn with: its first clause is short enough for the segmenter."""
    return re.split(r"[.,;:\n]", str(a["meta"].get("prompt") or ""), maxsplit=1)[0].strip()[:60]


async def _mark_generated(a: dict[str, Any]) -> None:
    """Concepts drawn before generated images were marked: no reference search on them, and a known size."""
    patch: dict[str, Any] = {"meta": {**a["meta"], "calibration": dict(GENERATED)}}
    if not a["width"]:
        try:
            with Image.open(storage.abs_path(a["path"])) as im:
                patch["width"], patch["height"] = im.size
        except OSError as e:
            log.info("concept %s: %s", a["id"], e)
    db = await get_db()
    await db.update("assets", "id", a["id"], patch)
    a.update(patch)


def _effort(requested: str, turn: int, max_turns: int, rethink: bool) -> str:
    """The effort the person picked where the plan is made (the first turn, the one after a rejection); at most
    high for the fixes in between, which is as fast as medium; low for the last two turns."""
    if turn >= max_turns - 2 and requested != "minimal":
        return "low"
    if rethink or requested not in ("xhigh", "max"):
        return requested
    return "high"


def _closing(ctx: JobContext, turn: int, max_turns: int) -> str | None:
    """Which limit is near, if any: then the agent stops polishing and hands over."""
    m = ctx.meter
    if m.budget_usd and m.usd >= 0.7 * m.budget_usd:
        return "budget"
    if math.isfinite(ctx.deadline) and time.monotonic() - ctx.started >= 0.75 * (ctx.deadline - ctx.started):
        return "time"
    if turn >= max_turns - 3:
        return "turn"
    return None


def _room(ctx: JobContext, turn: int, max_turns: int) -> dict[str, Any]:
    """How much is left, next to every tool result: the model plans instead of running out mid-fix."""
    room: dict[str, Any] = {"turn": f"{turn + 1} of {max_turns}", "budget_left_usd": round(max(0.0, ctx.meter.budget_usd - ctx.meter.usd), 3)}
    if math.isfinite(ctx.deadline):
        room["seconds_left"] = max(0, round(ctx.deadline - time.monotonic()))
    return room


async def _heartbeat(ctx: JobContext, stage: str | None) -> None:
    t0 = time.monotonic()
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        try:
            await ctx.emit("job.heartbeat", {"seconds": round(time.monotonic() - t0), "stage": stage})
        except Exception as e:  # noqa: BLE001 - a missed heartbeat is not worth the job
            log.info("heartbeat: %s", e)


async def _respond(ctx: JobContext, stage: str | None, **kwargs: Any) -> Any:
    """One designer turn. The answer comes whole after up to minutes of thinking: a heartbeat says the job is alive."""
    beat = asyncio.create_task(_heartbeat(ctx, stage))
    try:
        return await meta().respond(ctx.meter, **kwargs)
    finally:
        beat.cancel()


async def _keep_language(ctx: JobContext, language: str) -> dict[str, Any]:
    """The run's language into the brief, here and in the database: the tools, the reviewer and the runner's own lines
    read it there. Returns the brief with it."""
    db = await get_db()
    ctx.project["brief"] = {**(ctx.project.get("brief") or {}), "language": language}
    fresh = (await db.one("SELECT brief FROM projects WHERE id = ?", ctx.project_id) or {}).get("brief") or {}
    await db.update("projects", "id", ctx.project_id, {"brief": {**fresh, "language": language}})
    return ctx.project["brief"]


async def design(ctx: JobContext, body: SendMessage) -> str | None:
    db = await get_db()
    project = ctx.project
    brief = project.get("brief") or {}
    all_assets = await db.all("SELECT * FROM assets WHERE project_id = ? ORDER BY created_at", ctx.project_id)
    new_assets = [a for a in all_assets if a["id"] in body.asset_ids] or ([] if brief.get("turns") else all_assets)
    # a picked Muse Image concept ("Use this look") is the object to build: cut out and matched like a photographed one
    concept = next((a for a in new_assets if a["kind"] == "concept" and a["id"] in body.asset_ids and not a["meta"].get("visual_edit")), None)
    if concept and not concept["meta"].get("calibration"):
        await _mark_generated(concept)
    # the other concepts are ideas the person did not pick
    scene_assets = [a for a in (new_assets or all_assets) if a["kind"] != "concept" or a is concept]

    # every message is answered in its own language: the caller's when it knows it (a shop order's intake: its design
    # brief is English for the model, the customer is not), else the script of the person's own words (SendMessage.shown
    # when the caller wrote the text for the model; Cyrillic -> Russian), which the intake may refine
    hint = language_hint(body.language)
    spoken = body.shown or body.text
    language = hint or message_language(spoken, brief.get("language"))
    if hint and hint != brief.get("language"):
        # known before the intake runs: a failure from here on is reported in the customer's language too
        brief = await _keep_language(ctx, hint)
    stage = {"current": None}

    async def set_stage(name: str) -> None:
        if stage["current"] != name:
            stage["current"] = name
            await ctx.emit("job.stage", {"stage": name, "label": narrate.stage_label(name, language)})

    await set_stage("understand")
    photos = [a for a in scene_assets if a["kind"] in ("photo", "sketch", "concept")]
    fresh_photos = bool(photos) and (bool(body.asset_ids) or not brief.get("turns"))
    pack = project.get("pack")
    subject, photo_role = brief.get("subject", ""), brief.get("photo_role", "none")
    cls: dict[str, Any] = {}
    # pack, safety and what the photos are for: once per project, and again when new photos arrive
    references = await _calibrate(ctx, new_assets or all_assets)
    latest = await db.one("SELECT source, author FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", ctx.project_id)
    # «Сделать фигурку» on a kept snap sticker: the figurine starts afresh (its own engine too), the sticker stays a version
    sticker = latest if figurine_from_sticker(latest, body.text, fresh_photos) else None
    if sticker:
        latest = None
    current_is_mesh = is_mesh_doc((latest or {}).get("source"))
    # the engine: an existing mesh document stays one; snapped organic objects start as one
    engine = "mesh" if current_is_mesh else brief.get("engine") or ("mesh" if (brief.get("snap") or {}).get("organic") else "cad")
    if not pack or project["title"] in ("New project", "Untitled") or fresh_photos:
        await ctx.status("Understanding the request")
        note = f"\nScale references found (not the object): {', '.join(references)}." if references else ""
        if hint:
            note += f"\nThe person's language is {hint}: write title, reason and subject in it."
        content = [{"type": "input_text", "text": (body.text or "(photos only)") + note}]
        content += [{"type": "input_image", "image_url": storage.data_url(a["path"], 768)} for a in photos[:2]]
        # intake runs on the open-weights model when one is configured for it
        intake = meta().model_for("classify", ctx.models.fast) if hasattr(meta(), "model_for") else ctx.models.fast
        cls = await meta().json(ctx.meter, model=intake, system=CLASSIFY, content=content, schema=CLASSIFY_SCHEMA,
                                name="classify", effort="minimal")
        if cls.get("refuse") and intake != ctx.models.fast:
            # the open-weights intake is never the safety veto: Muse Spark decides a refusal (and the designer's own rules
            # still hold when the open model lets something through)
            cls = await meta().json(ctx.meter, model=ctx.models.fast, system=CLASSIFY, content=content, schema=CLASSIFY_SCHEMA,
                                    name="classify", effort="minimal")
        if cls.get("refuse"):
            text = narrate.localize(f"I can't help with this one: {cls.get('reason', '')}", language if hint else cls.get("language") or language)
            await add_message(ctx.project_id, "agent", text)
            await ctx.emit("agent.message", {"text": text})
            return "refused"
        pack = pack or cls.get("pack", "household")
        # the intake read this message; photos alone tell it nothing about a project that already has a language, and the
        # caller's language wins over it
        said = str(cls.get("language") or "").strip()
        if said and not hint and (_script(spoken) or not brief.get("language")):
            language = said
        if not latest and cls.get("engine") in ("cad", "mesh"):
            engine = cls["engine"]
        # a snapped collectible: the user named and outlined the object already
        if fresh_photos and not brief.get("collect"):
            subject, photo_role = (cls.get("subject") or "").strip()[:60], cls.get("photo_role") or "none"
            remember_english(subject, cls.get("subject_en") or "")
        updates = {"pack": pack}
        if project["title"] in ("New project", "Untitled") and cls.get("title"):
            updates["title"] = cls["title"][:60]
            project["title"] = updates["title"]
        await db.update("projects", "id", ctx.project_id, updates)
    if language != brief.get("language"):
        await _keep_language(ctx, language)
    if pack not in PACKS:
        pack = "household"
    if current_is_mesh:
        engine = "mesh"
    if pack in ("enclosure", "pcb", "device"):
        engine = "cad"  # boards and cases are exact geometry
    if concept:
        subject, photo_role = _concept_subject(concept) or subject, "copy"
        # the intake looked at the picture: its English noun phrase is what the segmenter gets for the prompt's words
        remember_english(subject, cls.get("subject_en") or "")

    state = DesignState(pack=pack, copies_photo=photo_role == "copy")
    current = await db.one("SELECT * FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", ctx.project_id)
    if current and sticker:
        state.version = current["version"]
    elif current:
        state.source, state.params, state.version, state.inputs = current["source"], current["params"], current["version"], current["inputs"] or {}
    if pack == "pcb" and pcb_tools:
        await pcb_tools.load(ctx.project_id, state)
    elif pack == "device" and device_tools:
        await device_tools.load(ctx.project_id, state)

    if concept or any(a["kind"] in ("photo", "sketch", "caliper", "print", "video") for a in (new_assets or all_assets)):
        await set_stage("measure")
    async def recall() -> dict[str, list[dict[str, Any]]]:
        # lessons and skills are written in English, so the lookup is too
        return await memory.recall(ctx.user["id"], await english(ctx.meter, body.text, ctx.models.fast), pack)

    # measuring, watching the video and recalling memory do not depend on each other
    scene, video_notes, mem = await asyncio.gather(
        _prepare_scene(ctx, scene_assets, subject if fresh_photos else "", language),
        _video_notes(ctx, new_assets),
        recall(),
    )
    if scene:
        state.inputs.update(scene.get("inputs", {}))
    await _load_meshes(state, all_assets)
    state.memory_ids = [m["id"] for items in mem.values() for m in items]
    await memory.mark_used(state.memory_ids)

    # ---- context: stable instructions first, project specifics after
    instructions = instructions_for(pack, engine)
    ctx_lines = [f"# Project: {project['title']} (pack: {pack}, reply in language: {language})"]
    if brief.get("summary"):
        ctx_lines.append(f"Previous result: {brief['summary']}")
    if brief.get("turns"):
        ctx_lines.append("Earlier requests: " + " | ".join(brief["turns"][-5:]))
    for a in all_assets:
        meta_bits = {k: a["meta"].get(k) for k in ("transcript", "exif") if a["meta"].get(k)}
        if a["kind"] == "mesh" and a["meta"].get("mesh"):
            m = a["meta"]["mesh"]
            meta_bits["mesh"] = {**m, "use": f"lib.mesh.input('{m['name']}')"}
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
    targets = await compare.targets(ctx.project_id) if photo_role != "none" else []
    if photo_role != "none":
        what = {"copy": "reproduce the object shown", "fit": "design something that fits or attaches to the object shown",
                "style": "use the look of the object shown as inspiration"}
        # what an intake model read from a photo is a pointer, not a fact: the close-up shows what was actually selected
        names = ", ".join(dict.fromkeys(f"“{s['name']}”" for _, s in targets)) or f"“{subject}”"
        if any((s.get("prompt") or {}).get("by") == "user" for _, s in targets):
            found = f"The person outlined the object on the photo themselves (scene selection {names}, role 'target'): that is the object."
        elif targets:
            found = (f"The object was selected automatically as {names} (scene selection, role 'target'); check on the close-up "
                     "that it is the right object before using its outline.")
        else:
            found = "The object could not be selected automatically: look at the photos and measure it yourself."
        ctx_lines.append(f"# Photos\nTask: {what.get(photo_role, photo_role)}. {found} A reference sheet or card in a photo only gives the scale.")
        if concept:
            ctx_lines.append(f"The person picked concept image {concept['id']}, drawn by Muse Image from “{str(concept['meta'].get('prompt') or '')[:300]}”: "
                             "build a printable model of the object it shows. A generated image has no scale, so choose real-world dimensions.")
    recalled = memory.format_recall(mem)
    if recalled:
        ctx_lines.append("# Memory (relevant)\n" + recalled)
    if brief.get("printer"):
        ctx_lines.append(f"Printer: {brief['printer']}")
    if engine == "mesh":
        ctx_lines.append("# Engine: mesh. Shape this one as a mesh document (mesh_write, then mesh_edit); a CAD program only if the "
                         "object turns out to be exact geometry.")
    if sticker:
        ctx_lines.append(f"# Kept sticker\nVersion {state.version} is the flat photo sticker kept from the snap (lib.collect.sticker: a relief "
                         "of the photo, made in a second). This request is for a 3D miniature of the object: start a new "
                         f"{'mesh document (mesh_write)' if engine == 'mesh' else 'program (write_program)'} from scratch; do not edit the "
                         "sticker, it stays as its own version.")
    if pack == "pcb" and pcb_tools:
        # the circuit is what the designer edits; the case program is make_enclosure's
        ctx_lines.extend(pcb_tools.context_lines(state))
    elif pack == "device" and device_tools:
        # the device graph is what the designer edits; the board is compiled from it, the case comes from the board
        ctx_lines.extend(await device_tools.context_lines(ctx.project_id, state))
        # the person edited the device since the designer's last version: say in the chat that those edits are read
        edits, _ = await device_tools.user_changes(ctx.project_id)
        if edits:
            n = len(edits)
            text = (f"Учитываю ваши правки в устройстве: {n} {narrate._ru_form(n, ('изменение', 'изменения', 'изменений'))}."
                    if narrate._ru(language) else f"Taking your {n} edit{'s' if n != 1 else ''} to the device into account.")
            await ctx.emit("agent.status", {"text": text, "say": True})
    elif state.source and is_mesh_doc(state.source):
        ctx_lines.append(f"# Current mesh document (version {state.version}); params {json.dumps(state.params, ensure_ascii=False)}\n```json\n{state.source}\n```")
    elif state.source:
        ctx_lines.append(f"# Current program (version {state.version}); params {json.dumps(state.params, ensure_ascii=False)}\n```js\n{state.source}\n```")
    ctx_lines.append("# Request\n" + (body.text or "(see photos)"))
    content: list[dict[str, Any]] = [{"type": "input_text", "text": "\n".join(ctx_lines)}]
    for a in (new_assets or all_assets)[:6]:
        if a["kind"] in ("photo", "sketch", "caliper", "concept"):
            content.append({"type": "input_text", "text": f"asset {a['id']} ({a['kind']}):"})
            content.append({"type": "input_image", "image_url": storage.data_url(a["path"], 1280)})
    if fresh_photos:
        for a, sel in targets:
            box = (sel["data"] or {}).get("bbox_px")
            if box and a["width"] and a["height"]:
                pad = 0.08 * max(box[2] - box[0], box[3] - box[1])
                grid = [(box[0] - pad) / a["width"] * 1000, (box[1] - pad) / a["height"] * 1000,
                        (box[2] + pad) / a["width"] * 1000, (box[3] + pad) / a["height"] * 1000]
                content.append({"type": "input_text", "text": f"Close-up of {subject} on asset {a['id']}:"})
                content.append({"type": "input_image", "image_url": _crop_data_url(a["path"], grid)})
    history: list[dict[str, Any]] = [{"type": "message", "role": "user", "content": content}]

    model = ctx.models.designer
    has_photos = any(a["kind"] in ("photo", "sketch") for a in all_assets)
    has_prints = any(a["kind"] == "print" for a in all_assets)
    tools = tools_for(pack, photos=has_photos, prints=has_prints, engine=engine)
    max_turns = settings().max_iterations * 3
    final_text: str | None = None
    # why the run ended before an accepted finish: budget, failed, engine (errors), time, turns
    ending: str | None = None
    wrapped = chained = False
    rethink = True  # the first turn plans; so does the one after the reviewer sends the design back
    # the first model turn plans the design: the stage says so, not "measuring"
    await set_stage("design")
    try:
        for turn in range(max_turns):
            ctx.check_cancelled()
            if time.monotonic() > ctx.deadline and (state.last_build or state.pcb.get("made")):
                ending = "time"
                break
            effort, max_output = llm_options(pack, _effort(body.reasoning, turn, max_turns, rethink))
            rethink = False
            resp = await _respond(ctx, stage["current"], model=model, instructions=instructions, input=history, tools=tools, effort=effort,
                                  max_output_tokens=max_output, cache_key=f"fw-agent-{pack}-{engine}-{int(has_photos)}{int(has_prints)}")
            # cut off at max_output_tokens: a half-written program or call is worse than a shorter one
            cut = getattr(resp, "status", None) == "incomplete"
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
                        # after the first turn the model answers tool results (the checks, the reviewer), not the person
                        final_text = without_agreement(text.strip()) if turn else text.strip()
                        await ctx.emit("agent.status", {"text": final_text[:4000], "say": True})
                elif t == "function_call":
                    calls.append(d)
            if not calls:
                if cut and turn < max_turns - 1:
                    history.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": CUT_OFF_PCB if pack == "pcb" else CUT_OFF_DEVICE if pack == "device" else CUT_OFF}]})
                    continue
                # The review gate lives in finish(); a model that just stops talking does not skip it.
                if (state.source or state.pcb.get("made")) and not state.done and state.finish_attempts == 0 and turn < max_turns - 1:
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
                    args = None
                # cut-off arguments: running the tool with {} would answer something misleading ("source is empty")
                broken = not isinstance(args, dict)
                args = args if isinstance(args, dict) else {}
                preview = {k: (v if len(json.dumps(v, ensure_ascii=False)) < 300 else "…") for k, v in args.items()}
                kind = narrate.KIND.get(name, "other")
                await set_stage(narrate.STAGE.get(kind, stage["current"] or "design"))
                await ctx.emit("tool.call", {"id": call.get("call_id"), "name": name, "kind": kind, "model": model,
                                             "title": narrate.localize(narrate.call_title(name, args), language), "args": preview})
                critic = state.critic
                if broken:
                    result, imgs = {"ok": False, "error": "arguments were not valid JSON (likely cut off)"}, []
                else:
                    try:
                        result, imgs = await run_tool(ctx, state, name, args)
                    except BudgetExceeded:
                        raise
                    except Exception as e:  # noqa: BLE001 - report to the model, keep going
                        log.exception("tool %s failed", name)
                        result, imgs = {"ok": False, "error": f"{type(e).__name__}: {e}"[:800]}, []
                if name == "finish" and result.get("accepted") is False and state.critic is not critic:
                    rethink = True
                review = narrate.review_of(state.critic, state.version) if name == "finish" and result.get("accepted") else None
                if review:
                    # accepted is not approved: the step and its summary (first, inside the 600 characters) say how the review ended
                    result = {"accepted": True, "review": review, **result}
                images.extend(imgs)
                ok = result.get("ok", result.get("accepted", True)) is not False
                # people get a calm title without server paths; the model gets the full error below
                await ctx.emit("tool.result", {"id": call.get("call_id"), "name": name, "kind": kind, "ok": ok,
                                               "title": narrate.localize(narrate.result_title(name, args, result), language),
                                               "summary": narrate.scrub(json.dumps(result, ensure_ascii=False))[:600],
                                               "image": storage.url(imgs[0]) if imgs and not imgs[0].startswith("data:") else None,
                                               # a board scan is SAM 3.1 and the fast model reading the silkscreen, not the designer
                                               **({"models": [settings().model_sam, ctx.models.fast]}
                                                  if name == "scan_board" and "unknown asset" not in str(result.get("error", "")) else {})})
                like, panel = narrate._likeness(result), next((r for r in imgs if "_compare_" in r), None)
                if concept and not chained and like is not None and panel:
                    chained = True
                    await ctx.emit("tool.result", {"name": "compare", "kind": "compare", "ok": True, "title": narrate.concept_title(language, like),
                                                   "image": storage.url(panel), "models": [settings().model_image, settings().model_sam, model]})
                history.append({"type": "function_call_output", "call_id": call["call_id"],
                                "output": json.dumps({**_room(ctx, turn, max_turns), **result}, ensure_ascii=False)[:12000]})
            if images:
                parts: list[dict[str, Any]] = [{"type": "input_text", "text": "Images from the tools above:"}]
                for ref in images[:4]:
                    parts.append({"type": "input_image", "image_url": ref if ref.startswith("data:") else storage.data_url(ref, None if ref.endswith(".png") else 1280)})
                history.append({"type": "message", "role": "user", "content": parts})
            if cut:
                history.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": CUT_OFF_PCB if pack == "pcb" else CUT_OFF_DEVICE if pack == "device" else CUT_OFF}]})
            if state.done:
                break
            closing = None if wrapped else _closing(ctx, turn, max_turns)
            if closing:
                wrapped = True
                history.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": WRAP_UP.format(closing)}]})
        else:
            ending = "turns"
    except STOPS as e:
        # the versions made so far are still the person's (a board counts too): hand the latest one over honestly
        if not state.last_build and not state.pcb.get("made"):
            raise
        log.warning("job %s stopped at v%s: %s: %s", ctx.job_id, state.version, type(e).__name__, e)
        ending = "budget" if isinstance(e, BudgetExceeded) else "engine" if isinstance(e, GeomError) else "failed"
        ctx.final_status = "budget" if ending == "budget" else "failed"

    if state.summary:
        # the summary was written before the review: a hand-over the reviewer did not approve says so after it
        notes = narrate.review_notes(state.critic, state.version, language) if state.done else ""
        text = f"{state.summary}\n\n{notes}" if notes else state.summary
    elif state.last_build and not state.done:
        # never the last mid-work line ("removing the sharp nose…"): say where it stopped and what is there
        reviewed = (state.critic or {}).get("version") == state.version
        text = narrate.handover(ending or "unfinished", state.version, (state.last_build.get("checks") or {}).get("ok", True), reviewed, language)
    elif state.pcb.get("made") and not state.done and pcb_tools:
        text = pcb_tools.handover(ending or "unfinished", state, language)
    else:
        text = final_text or narrate.localize("I ran out of steps before finishing; the latest version is in the viewer." if state.source else "No model yet.", language)
    await add_message(ctx.project_id, "agent", text, {"version": state.version, "critic": state.critic})
    await ctx.emit("agent.message", {"text": text, "version": state.version})
    if state.source and state.last_build:
        await set_stage("done")
        card = result_card(ctx, state)
        card["next"] = [{**n, "label": narrate.localize(n["label"], language)} for n in card["next"]]
        if pack in ("pcb", "device") and pcb_tools:
            card["pcb"] = await pcb_tools.card(ctx.project_id, state)
        await ctx.emit("result", card)
    # a run that ends as budget/failed has its request kept by the runner, marked as interrupted
    turns = (brief.get("turns") or []) + ([] if ctx.final_status else [body.text[:200]])
    fresh = (await db.one("SELECT brief FROM projects WHERE id = ?", ctx.project_id) or {}).get("brief") or {}
    await db.update("projects", "id", ctx.project_id, {"brief": {**fresh, **brief, "turns": turns[-10:], "summary": text[:800], "language": language,
                                                                      "subject": subject, "photo_role": photo_role, "engine": engine}, "updated_at": now()})
    await memory.record_outcome(state.memory_ids, success=state.done)
    # skills are tested JS modules; a mesh document has none to harvest, and a PCB job's case program is generated
    if state.done and state.source and not is_mesh_doc(state.source) and pack not in ("pcb", "device") and (state.critic or {}).get("verdict") == "pass":
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
    iso = storage.url(f"{ctx.project_id}/renders/v{state.version}_iso.png")
    # the model next to the photo or concept it copies, as seen for this version (the newest view if it was looked at again)
    panels = sorted(storage.abs_path(f"{ctx.project_id}/renders").glob(f"v{state.version}_compare_*.jpg"), key=lambda p: p.stat().st_mtime)
    card: dict[str, Any] = {
        "version": state.version,
        "title": ctx.project["title"],
        "size_mm": [round(v, 1) for v in stats.get("size", [])],
        "est_grams": round(stats.get("estGrams", 0), 1),
        "est_minutes": round(stats.get("estMinutes", 0)),
        "params_with_sources": params,
        "checks": {"ok": checks.get("ok", True), "errors": errors, "warnings": sum(1 for i in issues if i["severity"] == "warn"), "score": checks.get("score")},
        "critic": state.critic or {},
        # which version the reviewer saw: older than `version` means the shipped one was not reviewed
        "reviewed_version": (state.critic or {}).get("version"),
        "cover": iso,
        "render": iso,
        "sheet": storage.url(state.last_render),
        "compare": storage.url(f"{ctx.project_id}/renders/{panels[-1].name}") if panels else None,
        "cost_usd": round(ctx.meter.usd, 4),
        "cost": ctx.meter.summary(),
        "next": nxt,
    }
    enc = checks.get("enclosure")
    if isinstance(enc, dict):
        # a case: how it sits on its board (checks.enclosure of this build), next to the printability checks
        card["enclosure"] = {k: enc.get(k) for k in ("ok", "summary", "board", "version", "findings")}
    return card


def standards_hint(query: str) -> str:
    return json.dumps(lookup_standard(query), ensure_ascii=False)
