"""Dimension knowledge: built-in standards, a facts table with provenance, and web search.

Every number the agent uses carries where it came from (photo, caliper, standard,
search, user, assumed) and how sure we are. Search results are stored as facts with
their source URL, so the next user asking for the same device gets them instantly.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from ..config import settings
from ..db import get_db, new_id, now
from ..llm.client import CostMeter, meta


@lru_cache
def standards() -> dict[str, Any]:
    return json.loads(settings().standards_path.read_text(encoding="utf-8"))


def lookup_standard(query: str) -> list[dict[str, Any]]:
    """Fuzzy lookup over the built-in tables: 'M3', '608', 'A4', 'VESA 100', 'E27', '1/2 BSP'."""
    q = query.strip().lower()
    hits: list[dict[str, Any]] = []
    for table, entries in standards().items():
        if table.startswith("_") or not isinstance(entries, dict):
            continue
        for key, value in entries.items():
            if key.startswith("_"):
                continue
            k = key.lower()
            if q == k or q in k or k in q or q.replace(" ", "") == k.replace(" ", ""):
                hits.append({"table": table, "key": key, "value": value, "source": "standard"})
    return hits[:12]


def _fts_query(text: str) -> str:
    words = [w for w in re.findall(r"[\w\-\.]+", text.lower()) if len(w) > 1][:8]
    return " OR ".join(f'"{w}"' for w in words) or '""'


async def find_facts(query: str, user_id: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
    db = await get_db()
    rows = await db.all(
        "SELECT f.* FROM facts_fts JOIN facts f ON f.id = facts_fts.id WHERE facts_fts MATCH ? "
        "AND (f.user_id IS NULL OR f.user_id = ?) ORDER BY f.confidence DESC, f.uses DESC LIMIT ?",
        _fts_query(query), user_id, limit,
    )
    for r in rows:
        await db.execute("UPDATE facts SET uses = uses + 1 WHERE id = ?", r["id"])
    return rows


async def add_fact(subject: str, attribute: str, value: Any, *, unit: str | None, source_kind: str, source_url: str | None = None,
                   confidence: float = 0.6, user_id: str | None = None) -> dict[str, Any]:
    db = await get_db()
    fid = new_id("f_")
    row = {"id": fid, "subject": subject, "attribute": attribute, "value": json.dumps(value), "unit": unit, "source_kind": source_kind,
           "source_url": source_url, "confidence": confidence, "user_id": user_id, "created_at": now()}
    await db.insert("facts", row)
    await db.execute("INSERT INTO facts_fts (id, subject, attribute) VALUES (?, ?, ?)", fid, subject, attribute)
    return row


FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "the object, e.g. 'Xiaomi Smart Band 8 charger'"},
                    "attribute": {"type": "string", "description": "e.g. 'width', 'hole spacing', 'thread'"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "source_url": {"type": "string"},
                    "confidence": {"type": "number", "description": "0..1, lower if sources disagree or are unofficial"},
                },
                "required": ["subject", "attribute", "value", "unit", "source_url", "confidence"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["facts", "notes"],
}


async def search_dimensions(meter: CostMeter, query: str, user_id: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Cache first, then web search + structured extraction. Returns facts with sources."""
    cached = await find_facts(query, user_id)
    if cached:
        return {"facts": cached, "from_cache": True}
    found = await meta().search(meter, f"Exact physical dimensions in millimeters (official spec sheets preferred): {query}. "
                                        "List each dimension with its source.", model=model)
    if not found["text"]:
        return {"facts": [], "from_cache": False, "notes": "no results"}
    extracted = await meta().json(
        meter,
        model=model or settings().model_fast,
        system="Extract dimensions as structured facts. Only numbers that the text states, with the URL that states them. Convert to mm.",
        content=[{"type": "input_text", "text": f"Query: {query}\n\nSearch answer:\n{found['text']}\n\nSources:\n" + "\n".join(s["url"] for s in found["sources"])}],
        schema=FACTS_SCHEMA,
        name="facts",
    )
    stored = []
    for f in extracted.get("facts", [])[:20]:
        stored.append(await add_fact(f["subject"], f["attribute"], f["value"], unit=f.get("unit") or "mm", source_kind="search",
                                     source_url=f.get("source_url"), confidence=float(f.get("confidence", 0.5))))
    return {"facts": stored, "from_cache": False, "notes": extracted.get("notes", ""), "sources": found["sources"]}
