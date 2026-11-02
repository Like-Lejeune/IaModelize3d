"""Agent memory without endless growth.

Kinds: `interface` (user's measured things: "vacuum hose 32 mm"), `pref` (user preferences),
`lesson` (a check that kept failing + the fix that worked), `skill` (a tested program module).

Rules: only verified things get in (lessons need repeated evidence, skills need tests and
two successful uses), only used things stay (stats per item, consolidation archives the
rest, hard budgets per kind), and only relevant things reach the prompt (top-k by FTS).
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..db import get_db, new_id, now
from ..llm.english import is_english

BUDGET = {"skill": 60, "lesson": 40, "interface": 200, "pref": 30}
PROMPT_K = {"skill": 3, "lesson": 4, "interface": 6, "pref": 4}
LESSON_EVIDENCE = 3
SKILL_SUCCESSES = 2
# Checks that supports answer: getting rid of them is a design choice, not a fix worth teaching
# (lessons like "a keel instead of the leg" would push every later design away from supports).
TRADE_OFF_CODES = ("overhang", "floating_island", "long_bridge")


def _fts(text: str) -> str:
    words = [w for w in re.findall(r"[\w\-]+", text.lower()) if len(w) > 2][:10]
    return " OR ".join(f'"{w}"' for w in words) or '""'


async def _index(item_id: str, name: str, tags: str, text: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM memory_fts WHERE id = ?", item_id)
    await db.execute("INSERT INTO memory_fts (id, name, tags, text) VALUES (?, ?, ?, ?)", item_id, name, tags, text)


async def recall(user_id: str, query: str, pack: str | None = None) -> dict[str, list[dict[str, Any]]]:
    db = await get_db()
    out: dict[str, list[dict[str, Any]]] = {}
    q = _fts(f"{query} {pack or ''}")
    for kind, k in PROMPT_K.items():
        scope_sql = "(m.user_id = ?)" if kind in ("interface", "pref") else "(m.scope = 'global' OR m.user_id = ?)"
        status_sql = "m.status = 'active'" if kind in ("skill", "lesson") else "m.status != 'archived'"
        if kind == "lesson":
            status_sql += f" AND json_extract(m.body, '$.code') NOT IN ({', '.join(repr(c) for c in TRADE_OFF_CODES)})"
        rows = await db.all(
            f"SELECT m.* FROM memory_fts JOIN memory m ON m.id = memory_fts.id WHERE memory_fts MATCH ? AND m.kind = ? "
            f"AND {scope_sql} AND {status_sql} ORDER BY m.successes DESC, m.uses DESC LIMIT ?",
            q, kind, user_id, k,
        )
        if kind == "lesson":
            # the prompt is English; lessons recorded before that rule are left out until rewritten
            rows = [r for r in rows if is_english(r["body"].get("text") or "")]
        if kind == "pref" and not rows:
            rows = await db.all("SELECT * FROM memory WHERE kind = 'pref' AND user_id = ? AND status != 'archived' LIMIT ?", user_id, k)
        out[kind] = rows
    return out


def format_recall(mem: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    for it in mem.get("interface", []):
        lines.append(f"- [my interface] {it['name']}: {json.dumps(it['body'].get('values'), ensure_ascii=False)} (source {it['body'].get('source')})")
    for it in mem.get("pref", []):
        lines.append(f"- [preference] {it['body'].get('text')}")
    for it in mem.get("lesson", []):
        lines.append(f"- [lesson, worked {it['successes']}x] {it['body'].get('text')}")
    for it in mem.get("skill", []):
        lines.append(f"- [skill lib.skills.{it['name']}] {it['body'].get('doc')}")
    return "\n".join(lines)


async def mark_used(item_ids: list[str]) -> None:
    db = await get_db()
    for i in item_ids:
        await db.execute("UPDATE memory SET uses = uses + 1, last_used = ? WHERE id = ?", now(), i)


async def record_outcome(item_ids: list[str], success: bool) -> None:
    db = await get_db()
    col = "successes" if success else "failures"
    for i in item_ids:
        await db.execute(f"UPDATE memory SET {col} = {col} + 1 WHERE id = ?", i)
    if success:
        # candidates that keep working become active
        await db.execute(
            "UPDATE memory SET status = 'active' WHERE status = 'candidate' AND kind = 'skill' AND successes >= ?", SKILL_SUCCESSES
        )


async def remember_interface(user_id: str, name: str, values: dict[str, Any], source: str) -> dict[str, Any]:
    db = await get_db()
    existing = await db.one("SELECT * FROM memory WHERE kind = 'interface' AND user_id = ? AND name = ?", user_id, name)
    body = {"values": values, "source": source}
    if existing:
        await db.update("memory", "id", existing["id"], {"body": body, "last_used": now()})
        item_id = existing["id"]
    else:
        item_id = new_id("m_")
        await db.insert("memory", {"id": item_id, "kind": "interface", "name": name, "scope": "user", "user_id": user_id,
                                   "body": body, "tags": "interface", "status": "active", "created_at": now(), "last_used": now()})
    await _index(item_id, name, "interface", json.dumps(values, ensure_ascii=False))
    return {"id": item_id, "name": name, **body}


async def remember_pref(user_id: str, text: str) -> None:
    db = await get_db()
    item_id = new_id("m_")
    await db.insert("memory", {"id": item_id, "kind": "pref", "name": text[:60], "scope": "user", "user_id": user_id,
                               "body": {"text": text}, "tags": "preference", "status": "active", "created_at": now()})
    await _index(item_id, text[:60], "preference", text)


async def observe_fix(code: str, fix_text: str, pack: str | None, job_id: str) -> None:
    """A check failed and the next edit fixed it. Repeated evidence turns it into a lesson.
    `fix_text` must be English: lessons go into every later prompt."""
    if code in TRADE_OFF_CODES or not fix_text.strip() or not is_english(fix_text):
        return
    db = await get_db()
    name = f"{code}:{pack or 'any'}"
    text = f"When '{code}' fails in {pack or 'any'} designs: {fix_text[:200]}"
    row = await db.one("SELECT * FROM memory WHERE kind = 'lesson' AND name = ?", name)
    if row:
        fixes = [f for f in row["body"].get("fixes", []) if is_english(f)][-4:] + [fix_text[:200]]
        status = "active" if row["evidence"] + 1 >= LESSON_EVIDENCE else row["status"]
        body = {**row["body"], "fixes": fixes}
        if not is_english(body.get("text") or ""):
            body["text"] = text
            await _index(row["id"], name, f"{code} {pack or ''}", text)
        await db.update("memory", "id", row["id"], {"evidence": row["evidence"] + 1, "status": status, "body": body})
        return
    item_id = new_id("m_")
    await db.insert("memory", {"id": item_id, "kind": "lesson", "name": name, "scope": "global", "body": {"text": text, "code": code, "fixes": [fix_text[:200]]},
                               "tags": f"{code} {pack or ''}", "status": "candidate", "evidence": 1, "origin_job": job_id, "created_at": now()})
    await _index(item_id, name, f"{code} {pack or ''}", text)


async def propose_skill(name: str, source: str, doc: str, test: dict[str, Any], tags: str, job_id: str) -> str:
    """Candidate skill: `source` is a function body `function(lib, opts) {...}` returned by `return fn;`."""
    db = await get_db()
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)[:40]
    existing = await db.one("SELECT id FROM memory WHERE kind = 'skill' AND name = ?", name)
    if existing:
        return existing["id"]
    item_id = new_id("m_")
    await db.insert("memory", {"id": item_id, "kind": "skill", "name": name, "scope": "global", "body": {"source": source, "doc": doc, "test": test},
                               "tags": tags, "status": "candidate", "origin_job": job_id, "created_at": now()})
    await _index(item_id, name, tags, doc)
    return item_id


async def active_skill_sources(names: list[str]) -> dict[str, str]:
    if not names:
        return {}
    db = await get_db()
    marks = ",".join("?" for _ in names)
    rows = await db.all(f"SELECT name, body FROM memory WHERE kind = 'skill' AND status != 'archived' AND name IN ({marks})", *names)
    return {r["name"]: r["body"]["source"] for r in rows}
