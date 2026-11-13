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


# Short and numeric keys ('1', '608', 'A5', 'M3') name a standard only next to a word of its table:
# '1' is a BSP thread in "1 inch pipe thread", not in "garden hose 1/2 inch"; 'A5' is paper, not a Samsung A52.
_CONTEXT = {
    "screws": ("screw", "screws", "bolt", "bolts", "nut", "nuts", "insert", "inserts", "hole", "holes", "washer", "thread", "socket", "metric"),
    "metric_coarse_pitch": ("thread", "threads", "pitch", "tap", "bolt", "screw", "nut", "metric"),
    "pipe_threads_bsp": ("bsp", "bspp", "bspt", "pipe", "pipes", "thread", "threads", "fitting", "fittings"),
    "bearings": ("bearing", "bearings", "skateboard", "skate"),
    "references": ("paper", "sheet", "sheets", "page", "format", "iso"),
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().replace("_", " ")).rstrip(".,;:!?")


def _has(text: str, key: str) -> bool:
    """`key` as whole tokens of `text`: 'm3' is in 'm3 insert' but not in 'm3.5', '1' not in '1/2', 'a5' not in 'a52'."""
    return re.search(rf"(?<![\w./-]){re.escape(key)}(?![\w./])", text) is not None


def lookup_standard(query: str) -> list[dict[str, Any]]:
    """Lookup over the built-in tables: 'M3', '608', 'A4', 'VESA 100', 'E27', '1/2 BSP'.
    match 'exact': the query names the key; 'partial': the query is only part of a key ('vesa' -> 'VESA 100')."""
    q = _norm(query)
    words = set(re.findall(r"[a-z]+", q))
    exact: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    for table, entries in standards().items():
        if table.startswith("_") or not isinstance(entries, dict):
            continue
        context = _CONTEXT.get(table, (table.rstrip("s"), table))
        for key, value in entries.items():
            if key.startswith("_"):
                continue
            k = _norm(key)
            hit = {"table": table, "key": key, "value": value, "source": "standard"}
            if q == k or q.replace(" ", "") == k.replace(" ", ""):
                exact.append({**hit, "match": "exact"})
            elif _has(q, k):
                short = len(k) <= 2 or re.fullmatch(r"[\d/. ]+", k) is not None
                if not short or words & set(context):
                    exact.append({**hit, "match": "exact"})
            elif len(q) >= 3 and _has(k, q):
                partial.append({**hit, "match": "partial"})
    return (exact + partial)[:12]


# words that say which dimension or what for, not which thing: they never pick a cached fact
GENERIC = frozenset("""
dimension dimensions size sizes standard standards official spec specs specification specifications exact exactly datasheet
length width height thickness depth diameter radius weight mass outer inner outside inside od id overall total external internal
mm cm m inch inches in millimeter millimeters millimetres camera position hole holes spacing distance pitch measurement measurements
the a an of for and or with to on at by from its what is are how big large small typical approximate approx real actual
case cover holder mount stand bracket adapter compatible phone smartphone device product item object
""".split())


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w]+", text.lower())


def subject_tokens(query: str) -> list[str]:
    """The words of a query that name the thing (brand, model, numbers): 'iPhone 15 Pro thickness' -> iphone, 15, pro."""
    out: list[str] = []
    for w in _tokens(query):
        if w not in GENERIC and w not in out and (len(w) > 1 or w.isdigit()):
            out.append(w)
    return out[:8]


def _fts_query(tokens: list[str]) -> str:
    return "subject : (" + " AND ".join(f'"{w}"' for w in tokens) + ")"


async def find_facts(query: str, user_id: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
    """Cached facts about the same thing: every naming word of the query is in the fact's subject, so an
    'iPhone 15 Pro' never gets a Realme's numbers and 'park bench dimensions' does not get a soda can."""
    tokens = subject_tokens(query)
    if not tokens:
        return []
    db = await get_db()
    rows = await db.all(
        "SELECT f.* FROM facts_fts JOIN facts f ON f.id = facts_fts.id WHERE facts_fts MATCH ? "
        "AND (f.user_id IS NULL OR f.user_id = ?) ORDER BY f.confidence DESC, f.uses DESC LIMIT ?",
        _fts_query(tokens), user_id, limit * 3,
    )
    accepted = [r for r in rows if set(tokens) <= set(_tokens(r["subject"] or ""))][:limit]
    for r in accepted:
        await db.execute("UPDATE facts SET uses = uses + 1 WHERE id = ?", r["id"])
    return accepted


async def add_fact(subject: str, attribute: str, value: Any, *, unit: str | None, source_kind: str, source_url: str | None = None,
                   confidence: float = 0.6, user_id: str | None = None) -> dict[str, Any]:
    db = await get_db()
    fid = new_id("f_")
    # every later run reads the shared cache, and its page links the source: a web address only
    source_url = source_url if source_url and re.match(r"https?://[^\s/]+", source_url, re.I) else None
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


async def search_dimensions(meter: CostMeter, query: str, user_id: str | None = None, model: str | None = None,
                            force_web: bool = False) -> dict[str, Any]:
    """Cache first (unless force_web), then web search + structured extraction. Returns facts with sources."""
    cached = [] if force_web else await find_facts(query, user_id)
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
