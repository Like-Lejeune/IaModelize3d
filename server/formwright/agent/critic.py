"""Independent critic: sees the request, measured facts, photos and renders — never the code.
A model that grades its own code tends to approve it; this one cannot."""
from __future__ import annotations

import json
from typing import Any

from .. import storage
from ..config import settings
from ..db import get_db
from ..llm.client import meta
from .prompts import CRITIC
from .runner import JobContext

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
                    "text": {"type": "string"},
                    "fix_hint": {"type": "string"},
                },
                "required": ["severity", "text", "fix_hint"],
            },
        },
    },
    "required": ["verdict", "match_score", "issues"],
}

async def review(ctx: JobContext, state: Any) -> dict[str, Any]:
    db = await get_db()
    msgs = await db.all("SELECT text FROM messages WHERE project_id = ? AND role = 'user' ORDER BY created_at DESC LIMIT 3", ctx.project_id)
    photos = await db.all("SELECT * FROM assets WHERE project_id = ? AND kind IN ('photo','sketch','concept') ORDER BY created_at DESC LIMIT 3", ctx.project_id)
    stats = (state.last_build or {}).get("checks", {}).get("stats", {})
    params = {k: v for k, v in (state.params or {}).items()}
    specs = (state.last_build or {}).get("paramSpecs", {})
    lines = [
        "Request: " + " / ".join(m["text"] for m in reversed(msgs) if m["text"]),
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
    content: list[dict[str, Any]] = [{"type": "input_text", "text": "\n".join(lines)}]
    for p in photos:
        content.append({"type": "input_image", "image_url": storage.data_url(p["path"], 1024)})
    if state.last_render:
        content.append({"type": "input_text", "text": "Renders of the model (6 views):"})
        content.append({"type": "input_image", "image_url": storage.data_url(state.last_render, None)})
    if state.copies_photo:
        from .tools import _likeness

        facts, panels = await _likeness(ctx, state)
        for f, rel in zip(facts, panels):
            content.append({"type": "input_text", "text": "The model next to the object on the photo, seen from about the same angle. "
                                                          "Measured silhouette agreement: " + json.dumps(f, ensure_ascii=False)})
            content.append({"type": "input_image", "image_url": storage.data_url(rel, 1280)})
    model = settings().model_critic or ctx.models.fast
    return await meta().json(ctx.meter, model=model, system=CRITIC, content=content, schema=SCHEMA, name="critic", effort="low")
