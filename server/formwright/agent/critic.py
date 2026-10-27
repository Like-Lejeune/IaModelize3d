"""Independent critic: sees the request, measured facts, photos and renders — never the code.
A model that grades its own code tends to approve it; this one cannot."""
from __future__ import annotations

import json
from typing import Any

from .. import storage
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
    if state.facts:
        lines.append("Facts used: " + json.dumps(state.facts[:12], ensure_ascii=False)[:1500])
    content: list[dict[str, Any]] = [{"type": "input_text", "text": "\n".join(lines)}]
    for p in photos:
        content.append({"type": "input_image", "image_url": storage.data_url(p["path"], 1024)})
    if state.last_render:
        content.append({"type": "input_text", "text": "Renders of the model (6 views):"})
        content.append({"type": "input_image", "image_url": storage.data_url(state.last_render, None)})
    return await meta().json(ctx.meter, model=ctx.models.fast, system=CRITIC, content=content, schema=SCHEMA, name="critic", effort="medium")
