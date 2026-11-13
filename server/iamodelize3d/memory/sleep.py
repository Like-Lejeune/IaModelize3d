"""Consolidation ("sleep"): keep memory small and useful.

- archive items that are unused for long or fail more than they help, and lessons about checks
  that supports answer (they would teach every design to avoid supports)
- merge near-duplicate lessons/skills (by name/doc similarity), keeping the better one
- enforce hard per-kind budgets (weakest out first)
- re-run every active skill's test; a skill that no longer passes is archived
Run: python -m iamodelize3d.memory.sleep
"""
from __future__ import annotations

import asyncio
import difflib
import time
from typing import Any

from ..db import get_db
from ..geom import geom
from .store import BUDGET, TRADE_OFF_CODES


def _strength(m: dict[str, Any]) -> float:
    age_days = (time.time() - (m["last_used"] or m["created_at"])) / 86400
    return (m["successes"] + 1) / (m["failures"] + 1) * (1 + m["uses"]) / (1 + age_days / 14)


async def test_skill(item: dict[str, Any]) -> bool:
    test = item["body"].get("test") or {}
    call = test.get("call", "lib.skills.%s({})" % item["name"])
    program = f"""return {{ meta: {{}}, params: {{}}, build: (p, lib) => {call} }};"""
    try:
        r = await geom().build(program, {}, analyze="fast", skills={item["name"]: item["body"]["source"]})
    except Exception:
        return False
    size = r["checks"]["stats"]["size"]
    expect = test.get("size")
    if expect:
        return all(abs(a - b) <= test.get("tol", 0.5) for a, b in zip(size, expect))
    return r["ok"]


async def consolidate() -> dict[str, int]:
    db = await get_db()
    stats = {"archived": 0, "merged": 0, "failed_tests": 0}
    rows = await db.all("SELECT * FROM memory WHERE status != 'archived'")
    now = time.time()
    for m in rows:
        stale = (now - (m["last_used"] or m["created_at"])) > 60 * 86400 and m["kind"] in ("lesson", "skill")
        failing = m["failures"] >= 3 and m["failures"] > 2 * m["successes"]
        trade_off = m["kind"] == "lesson" and m["body"].get("code") in TRADE_OFF_CODES
        if stale or failing or trade_off:
            await db.update("memory", "id", m["id"], {"status": "archived"})
            stats["archived"] += 1
    for kind in ("lesson", "skill"):
        items = await db.all("SELECT * FROM memory WHERE kind = ? AND status != 'archived'", kind)
        items.sort(key=_strength, reverse=True)
        kept: list[dict[str, Any]] = []
        for it in items:
            text = it["body"].get("text") or it["body"].get("doc") or it["name"]
            dup = next((k for k in kept if difflib.SequenceMatcher(None, text, k["body"].get("text") or k["body"].get("doc") or k["name"]).ratio() > 0.86), None)
            if dup:
                await db.update("memory", "id", it["id"], {"status": "archived"})
                await db.execute("UPDATE memory SET evidence = evidence + ?, successes = successes + ? WHERE id = ?", it["evidence"], it["successes"], dup["id"])
                stats["merged"] += 1
                continue
            if kind == "skill" and it["status"] == "active" and not await test_skill(it):
                await db.update("memory", "id", it["id"], {"status": "archived"})
                stats["failed_tests"] += 1
                continue
            kept.append(it)
        for it in kept[BUDGET[kind]:]:
            await db.update("memory", "id", it["id"], {"status": "archived"})
            stats["archived"] += 1
    return stats


if __name__ == "__main__":
    print(asyncio.run(consolidate()))
