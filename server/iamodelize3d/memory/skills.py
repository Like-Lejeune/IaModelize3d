"""Skill harvesting: after an accepted design, extract at most one reusable module.

The candidate is built and size-checked right away; it becomes active only after it
helps in two more jobs (store.record_outcome), and consolidation archives it if it
stops passing its test. That is how the library grows without filling up with junk.
"""
from __future__ import annotations

import logging
from typing import Any

from ..db import get_db
from ..llm.client import CostMeter, meta
from . import store
from .sleep import test_skill

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "worth_it": {"type": "boolean", "description": "true only for a module that other designs would reuse (a clip, clamp, hinge, knob, mount pattern)"},
        "name": {"type": "string", "description": "snake_case, e.g. shelf_clamp"},
        "doc": {"type": "string", "description": "one line: what it makes and its options with units"},
        "tags": {"type": "string", "description": "space separated keywords"},
        "source": {"type": "string", "description": "JavaScript body that ends with `return function(lib, opts) { ... return manifold; }`"},
        "test_call": {"type": "string", "description": "e.g. lib.skills.shelf_clamp({board: 18})"},
        "expected_size": {"type": "array", "items": {"type": "number"}, "description": "bounding box [x,y,z] in mm of the test call"},
    },
    "required": ["worth_it", "name", "doc", "tags", "source", "test_call", "expected_size"],
}

PROMPT = """You maintain a library of reusable parametric modules for a 3D-printing design agent.
Given a finished program, decide whether it contains ONE module worth reusing in other designs.
If yes, rewrite it as a self-contained function using only `lib` (lib.std, lib.M, lib.CS, lib.forms) and an
`opts` object with sensible defaults, returning a Manifold resting on z=0. Most programs contain nothing
reusable: then worth_it=false. Never extract whole objects that are only useful once."""


async def harvest(program_source: str, pack: str, job_id: str, model: str) -> dict[str, Any] | None:
    db = await get_db()
    active = await db.all("SELECT name FROM memory WHERE kind = 'skill' AND status != 'archived'")
    meter = CostMeter(budget_usd=0.03)
    try:
        out = await meta().json(meter, model=model, system=PROMPT, name="skill",
                                content=[{"type": "input_text", "text": f"Existing modules: {', '.join(r['name'] for r in active) or 'none'}\n\n```js\n{program_source}\n```"}],
                                schema=SCHEMA, effort="low", max_output_tokens=6000)
    except Exception as e:  # noqa: BLE001 - harvesting is best effort
        log.info("skill harvest skipped: %s", e)
        return None
    if not out.get("worth_it") or not out.get("source"):
        return None
    name = out["name"]
    if any(r["name"] == name for r in active):
        return None
    candidate = {"name": name, "body": {"source": out["source"], "test": {"call": out["test_call"], "size": out.get("expected_size"), "tol": 1.0}}}
    if not await test_skill(candidate):
        log.info("skill %s failed its own test, dropped", name)
        return None
    item_id = await store.propose_skill(name, out["source"], out["doc"], candidate["body"]["test"], f"{pack} {out.get('tags', '')}", job_id)
    return {"id": item_id, "name": name, "doc": out["doc"], "cost_usd": round(meter.usd, 5)}
