"""Independent critic: sees the request, measured facts, photos and renders — never the code.
A model that grades its own code tends to approve it; this one cannot."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .. import storage
from ..config import settings
from ..db import get_db
from ..llm.client import BudgetExceeded, meta
from .prompts import CRITIC
from .runner import JobContext, model_text

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "revise"]},
        "match_score": {"type": "number", "description": "0-10, how well it matches the intent/photo"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["major", "minor"]},
                    "text": {"type": "string", "description": "the issue, in English (the designer model reads it)"},
                    "text_user": {"type": "string", "description": "the same issue in a few plain words for the person, in the request's language"},
                    "fix_hint": {"type": "string"},
                },
                "required": ["severity", "text", "text_user", "fix_hint"],
            },
        },
    },
    "required": ["verdict", "match_score", "issues"],
}
# reasoning comes out of the same budget on the open-weights reviewer: room for it and for a few issues in two languages
MAX_OUTPUT = 16000
MAJOR = ("major", "critical", "high", "blocker", "severe")

# How the renders colour the parts (packages/geom engine.ts Engine.colors): a part's own colour, else this palette by its
# index among the build's parts; helper volumes light blue, reference parts translucent blue; negative parts are not
# drawn. The sheet of views also tints overhang faces red (the printability heat).
PALETTE = ((214, 216, 222), (232, 150, 90), (110, 170, 220), (150, 200, 120), (220, 120, 160), (240, 210, 100))
HUES = ((15, "red"), (45, "orange"), (70, "yellow"), (160, "green"), (195, "cyan"), (255, "blue"), (290, "purple"), (340, "pink"), (361, "red"))
ROLE_TEXT = {"model": "printed part", "modifier": "light blue helper volume for print settings, not a printed body",
             "reference": "translucent blue reference, shown for context and never printed"}


def colour_name(rgb: tuple[int, int, int]) -> str:
    """A colour as a reviewer would name it on the render: 'light grey', 'orange', 'dark green'."""
    r, g, b = (c / 255 for c in rgb)
    hi, lo = max(r, g, b), min(r, g, b)
    light = (hi + lo) / 2
    if hi == lo or (hi - lo) / (1 - abs(2 * light - 1)) < 0.2:
        return "light grey" if light > 0.7 else "dark grey" if light < 0.3 else "grey"
    d = hi - lo
    hue = 60 * (((g - b) / d) % 6 if hi == r else (b - r) / d + 2 if hi == g else (r - g) / d + 4)
    name = next(n for top, n in HUES if hue < top)
    return ("light " if light > 0.75 else "dark " if light < 0.3 else "") + name


def _part_rgb(p: dict[str, Any], index: int) -> tuple[int, int, int]:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(p.get("color") or "").strip())
    if m:
        v = int(m.group(1), 16)
        return (v >> 16) & 255, (v >> 8) & 255, v & 255
    return PALETTE[index % len(PALETTE)]


def _mm(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def legend(state: Any) -> str:
    """What the renders show, for a model of several parts or with a reference part: each drawn part's name, role,
    colour and size, where they sit in the views and the case layout, so the reviewer never takes the lid for the base."""
    build = state.last_build or {}
    drawn = [(i, p) for i, p in enumerate(build.get("parts") or []) if p.get("role", "model") in ROLE_TEXT]
    if len(drawn) < 2 and all(p.get("role", "model") == "model" for _, p in drawn):
        return ""
    boxes: dict[str, tuple[list[float], list[float]]] = {}
    lines = []
    for i, p in drawn:
        role = p.get("role", "model")
        if role == "model":
            rgb = _part_rgb(p, i)
            hue = colour_name(rgb)
            # warm colours read brown on the shaded faces of the iso views
            colour = f"{hue} #{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}" + (", brown on shaded faces" if hue in ("orange", "yellow") else "")
        else:
            colour = ""
        box = p.get("bbox") or {}
        lo, hi = box.get("min"), box.get("max")
        size = ""
        if isinstance(lo, list) and isinstance(hi, list) and len(lo) == len(hi) == 3:
            boxes[str(p.get("name"))] = (lo, hi)
            size = ", " + " x ".join(_mm(hi[k] - lo[k]) for k in range(3)) + " mm"
        lines.append(f"- {p.get('name') or f'part {i + 1}'}: {colour + ', ' if colour else ''}{ROLE_TEXT[role]}{size}")
    out = ["Parts in the renders (name: colour, role, size):", *lines]
    names = [str(p.get("name")) for _, p in drawn]
    # side by side along x: the FRONT, TOP and ISO views show them left to right (BOTTOM and ISO BACK mirror it)
    order = sorted(boxes, key=lambda n: boxes[n][0][0])
    if len(order) == len(drawn) and all(boxes[a][1][0] <= boxes[b][0][0] + 0.5 for a, b in zip(order, order[1:])):
        out.append(f"In the FRONT, TOP and ISO views they sit left to right: {', '.join(order)}; BOTTOM and ISO BACK show them mirrored.")
    layout = (build.get("params") or state.params or {}).get("layout")
    case = {"base", "lid"} <= set(names) and "lib.elec" in (state.source or "")
    if layout == "print":
        out.append("Layout: print, the parts lie side by side as they go on the bed." + (
            " The lid is printed upside down: its outer top face lies on the bed, so the BOTTOM view shows the outside of the lid "
            "and the TOP view its inside (hooks, posts); a hole through the lid shows in both." if case else "") + (
            " The stand is a separate printed wedge the case leans in." if case and "stand" in names else ""))
    elif layout == "assembled":
        out.append("Layout: assembled, the parts sit together as in use" + (", the lid on the base." if case else ".") + (
            " The case is drawn lying flat with its stand tilted under it; in use the stand is on the desk and the case leans in it." if case and "stand" in names else ""))
    out.append("A red tint on faces marks overhangs (the printability heat), not a part's colour.")
    return "\n".join(out)


QUOTE = 1000  # characters of one question or answer the reviewer reads
EARLIER_QA = 4  # answered questions from the project's earlier runs: their requests are in the review's Request line


def _quote(text: Any) -> str:
    """The person's words verbatim, in quotes that cannot be confused with the line around them."""
    s = str(text or "").strip()
    return json.dumps(s if len(s) <= QUOTE else s[:QUOTE] + "…", ensure_ascii=False)


async def answered(project_id: str, job_id: str) -> list[str]:
    """The designer's questions to the person (ask_user) with the answers, oldest first: every one of this run, the
    unanswered too, and the latest answered ones of earlier runs. Read from the project's ask/answer events."""
    db = await get_db()
    rows = list(reversed(await db.all("SELECT job_id, type, data FROM events WHERE project_id = ? AND type IN ('ask', 'answer') "
                                      "ORDER BY seq DESC LIMIT 60", project_id)))
    data = [(r["job_id"], r["type"], r["data"]) for r in rows if isinstance(r["data"], dict)]
    answers = {d.get("question_id"): d.get("answer") for _, kind, d in data if kind == "answer"}
    this_run, earlier = [], []
    for job, kind, d in data:
        # a question still waiting has no answer event yet (the job waits on it, so a review never runs meanwhile)
        if kind != "ask" or not str(d.get("question") or "").strip() or d.get("question_id") not in answers:
            continue
        answer = answers[d["question_id"]]
        if job == job_id:
            this_run.append(f"- {_quote(d['question'])} Answer: {_quote(answer)}" if str(answer or "").strip()
                            else f"- {_quote(d['question'])} No answer came: the designer went on with an assumption it states.")
        elif str(answer or "").strip():
            earlier.append(f"- (for an earlier request) {_quote(d['question'])} Answer: {_quote(answer)}")
    return earlier[-EARLIER_QA:] + this_run


def usable(v: dict[str, Any]) -> dict[str, Any]:
    """The review in the schema's own terms, or {} when it has no verdict. A reviewer that only reads the schema in its
    prompt (open weights on Baseten) may write 'Pass', a score of '8/10' or a severity of its own; a severity it made up
    counts as minor, so a reviewer that strays from the schema never blocks a design."""
    verdict = str(v.get("verdict") or "").strip().lower()
    if verdict not in ("pass", "revise"):
        return {}
    score = v.get("match_score")
    if isinstance(score, str):
        m = re.match(r"\s*(\d+(?:[.,]\d+)?)", score)
        score = float(m.group(1).replace(",", ".")) if m else None
    score = min(10.0, max(0.0, float(score))) if isinstance(score, (int, float)) and not isinstance(score, bool) else None
    issues = []
    for i in v.get("issues") or []:
        if not isinstance(i, dict) or not str(i.get("text") or "").strip():
            continue
        text = str(i["text"]).strip()
        issues.append({"severity": "major" if str(i.get("severity") or "").strip().lower() in MAJOR else "minor", "text": text,
                       "text_user": str(i.get("text_user") or "").strip() or text, "fix_hint": str(i.get("fix_hint") or "").strip()})
    return {"verdict": verdict, "match_score": score, "issues": issues}


async def review(ctx: JobContext, state: Any, *, bar: float | None = None) -> dict[str, Any]:
    """The verdict on the current version, tagged with the model that gave it and whether that was the
    configured reviewer ('primary'), the fast model standing in ('fallback') or nobody ('unavailable', no verdict).
    bar: the match_score a pass needs (look tasks), stated to the reviewer so verdict and score agree."""
    db = await get_db()
    msgs = list(reversed(await db.all("SELECT text, data FROM messages WHERE project_id = ? AND role = 'user' ORDER BY created_at DESC LIMIT 3",
                                      ctx.project_id)))
    photos = await db.all("SELECT * FROM assets WHERE project_id = ? AND kind IN ('photo','sketch','concept') ORDER BY created_at DESC LIMIT 3", ctx.project_id)
    stats = (state.last_build or {}).get("checks", {}).get("stats", {})
    params = {k: v for k, v in (state.params or {}).items()}
    specs = (state.last_build or {}).get("paramSpecs", {})
    language = (ctx.project.get("brief") or {}).get("language")
    # a shop order's request is the brief written for the designer; the person's own words are what they typed or saw
    own = [m["text"].strip() for m in msgs if model_text(m) != m["text"] and m["text"].strip() and m["text"].strip() not in model_text(m)]
    asked = await answered(ctx.project_id, ctx.job_id)
    lines = [
        "Request: " + " / ".join(t for t in map(model_text, msgs) if t),
        *(["The person's own words: " + " / ".join(map(_quote, own))] if own else []),
        *(["Questions the designer asked the person, with the answers quoted verbatim. An answered question is settled: "
           "never report it as unanswered, unclear or still to be confirmed" + ("; a later request may still change an earlier "
           "answer." if any(a.startswith("- (for an earlier") for a in asked) else "."), *asked] if asked else []),
        *([f"Request language: {language} (write text_user in it)"] if language else []),
        f"Model size (mm): {[round(v, 1) for v in stats.get('size', [])]}",
        "Parameters (value, source): " + json.dumps({k: [v, specs.get(k, {}).get('source')] for k, v in params.items()}, ensure_ascii=False)[:1500],
    ]
    checks = (state.last_build or {}).get("checks", {})
    groups = checks.get("groups") or []
    lines.append(
        f"Measured printability: ok={checks.get('ok', True)}, first-layer contact {stats.get('firstLayerArea', 0):.0f} mm² "
        f"(the base sits flat on the bed at z=0), bodies={stats.get('bodies', 1)}, "
        f"issues: {', '.join(g['code'] + ' x' + str(g['count']) for g in groups) or 'none'}"
    )
    if state.facts:
        lines.append("Facts used: " + json.dumps(state.facts[:12], ensure_ascii=False)[:1500])
    refs = {((p.get("meta") or {}).get("calibration") or {}).get("reference") for p in photos} - {None}
    if refs:
        # a dark part on a white sheet is easily read as "a white plate with a hole"
        lines.append(f"Scale reference in the photos: {', '.join(sorted(refs))}. It only gives the scale; it is not part of the design. "
                     "The object to judge is the item lying on it or next to it.")
    if bar is not None:
        lines.append(f"This task copies a look: verdict=pass only if match_score >= {bar:g}; below that, verdict=revise and say what differs most.")
    earlier = state.critic or {}
    if earlier.get("issues") and earlier.get("version") != state.version:
        found = "; ".join(f"{n}. [{i.get('severity')}] {i.get('text', '')}" for n, i in enumerate(earlier["issues"][:6], 1))
        lines.append(f"An earlier review of v{earlier.get('version', '?')} found: {found}. Say in your issues which of them are still not fixed.")
    content: list[dict[str, Any]] = [{"type": "input_text", "text": "\n".join(lines)}]
    for p in photos:
        content.append({"type": "input_image", "image_url": storage.data_url(p["path"], 1024)})
    if state.last_render:
        parts = legend(state)
        content.append({"type": "input_text", "text": "Renders of the model (6 views):" + (f"\n{parts}" if parts else "")})
        content.append({"type": "input_image", "image_url": storage.data_url(state.last_render, None)})
    if state.copies_photo:
        from .tools import _likeness

        facts, panels = await _likeness(ctx, state)
        for f, rel in zip(facts, panels):
            content.append({"type": "input_text", "text": "The model next to the object on the photo, seen from about the same angle. "
                                                          "Measured silhouette agreement: " + json.dumps(f, ensure_ascii=False)})
            content.append({"type": "input_image", "image_url": storage.data_url(rel, 1280)})
    model = meta().model_for("critic", settings().model_critic or ctx.models.fast)
    try:
        verdict = usable(await meta().json(ctx.meter, model=model, system=CRITIC, content=content, schema=SCHEMA, name="critic", effort="low",
                                           max_output_tokens=MAX_OUTPUT, fallback=False))
        reviewer = "primary"
    except BudgetExceeded:
        raise
    except Exception as e:  # noqa: BLE001 - a reviewer that is down is replaced, not fatal
        log.warning("critic %s failed: %s: %s", model, type(e).__name__, e)
        verdict = {}
    if "verdict" not in verdict:
        # the open-weights reviewer failed or answered nothing usable: the fast model reviews once instead
        model, reviewer = ctx.models.fast, "fallback"
        try:
            verdict = usable(await meta().json(ctx.meter, model=model, system=CRITIC, content=content, schema=SCHEMA, name="critic", effort="low",
                                               max_output_tokens=MAX_OUTPUT))
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("fallback critic %s failed: %s: %s", model, type(e).__name__, e)
            verdict = {}
    if "verdict" not in verdict:
        return {"reviewer": "unavailable"}
    return {**verdict, "model": model, "reviewer": reviewer, "version": state.version}
