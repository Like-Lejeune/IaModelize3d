"""Device documents of a project (fw.device/1, see device.py): one row per saved version in device_docs. The latest row
is what the node editor shows and what the next build compiles; every PCB version built from one carries a copy as
device.json. Edits by the person in one sitting update one version (like slider edits of a program), so dragging nodes
around does not add a version per drop. Orders of finished devices live in device_orders.
"""
from __future__ import annotations

import asyncio
import json
import weakref
from typing import Any

from .db import get_db, new_id, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS device_docs (
  project_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  doc TEXT NOT NULL,
  author TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY (project_id, version)
);
CREATE TABLE IF NOT EXISTS device_orders (
  id TEXT PRIMARY KEY,
  ref TEXT NOT NULL,
  user_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  pcb_version INTEGER,
  program_version INTEGER,
  quantity INTEGER NOT NULL,
  status TEXT NOT NULL,
  quote TEXT NOT NULL,
  contact TEXT NOT NULL DEFAULT '{}',
  timeline TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS device_orders_user ON device_orders(user_id, created_at);
"""
EDIT_WINDOW_S = 20 * 60

_ready: weakref.WeakSet = weakref.WeakSet()
_lock = asyncio.Lock()


async def _db():
    db = await get_db()
    if db not in _ready:
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                await db.execute(stmt)
        _ready.add(db)
    return db


def _dump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _row(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if r is None:
        return None
    out = dict(r)
    for k in ("doc", "quote", "contact", "timeline"):
        if isinstance(out.get(k), str):
            try:
                out[k] = json.loads(out[k])
            except json.JSONDecodeError:
                pass
    return out


async def latest(project_id: str) -> dict[str, Any] | None:
    db = await _db()
    return _row(await db.one("SELECT * FROM device_docs WHERE project_id = ? ORDER BY version DESC LIMIT 1", project_id))


async def get(project_id: str, version: int) -> dict[str, Any] | None:
    db = await _db()
    return _row(await db.one("SELECT * FROM device_docs WHERE project_id = ? AND version = ?", project_id, int(version)))


async def save(project_id: str, doc: dict[str, Any], *, author: str, summary: str = "") -> int:
    """Store a normalized document as the next version; the person's edits within EDIT_WINDOW_S of their own last one
    update it instead. Returns the version."""
    db = await _db()
    t = now()
    async with _lock:
        last = await latest(project_id)
        if last and author == "user" and last["author"] == "user" and t - float(last["updated_at"]) < EDIT_WINDOW_S:
            await db.execute("UPDATE device_docs SET doc = ?, summary = ?, updated_at = ? WHERE project_id = ? AND version = ?",
                             _dump(doc), summary or last["summary"], t, project_id, last["version"])
            return int(last["version"])
        version = int((last or {}).get("version") or 0) + 1
        await db.execute("INSERT INTO device_docs (project_id, version, doc, author, summary, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         project_id, version, _dump(doc), author, summary[:200], t, t)
        return version


async def copy_all(src: str, dst: str) -> int:
    """Every device version of a project into another (a remix), same numbers; returns how many."""
    db = await _db()
    rows = await db.all("SELECT * FROM device_docs WHERE project_id = ? ORDER BY version", src)
    for r in rows:
        await db.execute("INSERT OR IGNORE INTO device_docs (project_id, version, doc, author, summary, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         dst, r["version"], r["doc"] if isinstance(r["doc"], str) else _dump(r["doc"]), r["author"], r["summary"], r["created_at"], r["updated_at"])
    return len(rows)


async def copy_one(src: str, version: int, dst: str) -> None:
    """One device version into another project under the same number (a replay, as its event comes up)."""
    db = await _db()
    r = await db.one("SELECT * FROM device_docs WHERE project_id = ? AND version = ?", src, int(version))
    if r:
        await db.execute("INSERT OR IGNORE INTO device_docs (project_id, version, doc, author, summary, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         dst, r["version"], r["doc"] if isinstance(r["doc"], str) else _dump(r["doc"]), r["author"], r["summary"], r["created_at"], r["updated_at"])


async def versions(project_id: str) -> list[dict[str, Any]]:
    db = await _db()
    return await db.all("SELECT version, author, summary, created_at, updated_at FROM device_docs WHERE project_id = ? ORDER BY version", project_id)


# ------------------------------------------------------------------ orders
async def add_order(*, user_id: str, project_id: str, pcb_version: int | None, program_version: int | None, quantity: int,
                    quote: dict[str, Any], contact: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    db = await _db()
    oid = new_id("do")
    t = now()
    n = (await db.one("SELECT COUNT(*) AS n FROM device_orders"))["n"]  # type: ignore[index]
    ref = f"FW-D{1001 + int(n)}"
    await db.execute(
        "INSERT INTO device_orders (id, ref, user_id, project_id, pcb_version, program_version, quantity, status, quote, contact, timeline, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        oid, ref, user_id, project_id, pcb_version, program_version, quantity, "placed", _dump(quote), _dump(contact), _dump(timeline), t, t)
    return await order(oid)  # type: ignore[return-value]


async def order(order_id: str) -> dict[str, Any] | None:
    db = await _db()
    return _row(await db.one("SELECT * FROM device_orders WHERE id = ?", order_id))


async def orders_of(user_id: str, project_id: str | None = None) -> list[dict[str, Any]]:
    db = await _db()
    if project_id:
        rows = await db.all("SELECT * FROM device_orders WHERE user_id = ? AND project_id = ? ORDER BY created_at DESC", user_id, project_id)
    else:
        rows = await db.all("SELECT * FROM device_orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 50", user_id)
    return [_row(r) for r in rows]  # type: ignore[misc]
