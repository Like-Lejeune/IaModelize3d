"""Independent critic: sees the request, measured facts, photos and renders — never the code.
A model that grades its own code tends to approve it; this one cannot."""
from __future__ import annotations

import base64
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

CHECKLIST_ITEM = {
    "type": "object",
    "properties": {"id": {"type": "string"}, "check": {"type": "string"}, "must": {"type": "boolean"},
                   "valid": {"type": "boolean", "description": "false if the item itself contradicts the photo or request"},
                   "ok": {"type": "boolean"}, "note": {"type": "string"}},
    "required": ["id", "check", "must", "valid", "ok", "note"],
}


async def _photo_overlays(ctx: JobContext, state: Any, photos: list[dict[str, Any]]) -> list[str]:
    """For calibrated photos, the critic sees what the user sees in photo-AR."""
    if not state.source:
        return []
    try:
        from ..geom import geom
        from ..vision import overlay, scene
    except ImportError:
        return []
    out = []
    for p in photos[:2]:
        cam = scene.camera_for_render(p)
        if not cam:
            continue
        try:
            r = await geom().render(state.source, state.params, camera=cam, inputs=state.inputs)
            out.append(overlay.compose(p, base64.b64decode(r["png"])))
        except Exception:  # noqa: BLE001 - an overlay is a bonus for the reviewer, not a requirement
            continue
    return out


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
    content: list[dict[str, Any]] = [{"type": "input_text", "text": "\n".join(lines)}]
    for p in photos:
        content.append({"type": "input_image", "image_url": storage.data_url(p["path"], 1024)})
    if state.last_render:
        content.append({"type": "input_text", "text": "Renders of the model (6 views):"})
        content.append({"type": "input_image", "image_url": storage.data_url(state.last_render, None)})
    for overlay in await _photo_overlays(ctx, state, photos):
        content.append({"type": "input_text", "text": "The model drawn over the calibrated photo (orange outline = model edges). "
                                                      "Misalignment here is a real dimension error:"})
        content.append({"type": "input_image", "image_url": storage.data_url(overlay, 1280)})
    schema = SCHEMA
    checklist = (state.dossier or {}).get("checklist") or []
    if checklist:
        # the dossier written before modelling is the acceptance checklist
        items = "\n".join(
            f"- [{c.get('id')}]{' (must)' if c.get('must') else ''} {c.get('check')} (verify by {c.get('verify_by')})" for c in checklist[:12])
        content[0]["text"] += ("\nAcceptance checklist, written by an analyst from the same photo before modelling. It can be wrong: "
                               "form your own judgement from the photo first, then judge each item ok/not ok with a short note, "
                               "and mark an item valid=false when the item itself contradicts the photo or request:\n" + items)
        schema = {**SCHEMA, "properties": {**SCHEMA["properties"], "checklist": {"type": "array", "items": CHECKLIST_ITEM}},
                  "required": [*SCHEMA["required"], "checklist"]}
    model = settings().model_critic or ctx.models.fast
    return await meta().json(ctx.meter, model=model, system=CRITIC, content=content, schema=schema, name="critic", effort="low")
