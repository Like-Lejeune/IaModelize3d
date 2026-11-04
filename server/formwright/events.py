"""Event log: every agent step is appended to `events` and fanned out to SSE listeners.

The same log powers live streaming (resumable by seq), demo replays, debugging
and the nightly memory consolidation.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from .db import get_db, now

_waiters: dict[str, asyncio.Condition] = {}
_listeners: dict[str, int] = defaultdict(int)


async def emit(project_id: str, type_: str, data: dict[str, Any] | None = None, job_id: str | None = None) -> int:
    db = await get_db()
    seq = await db.execute(
        "INSERT INTO events (project_id, job_id, type, data, ts) VALUES (?, ?, ?, ?, ?)",
        project_id, job_id, type_, data or {}, now(),
    )
    cond = _waiters.get(project_id)
    if cond:
        async with cond:
            cond.notify_all()
    return seq


async def since(project_id: str, after: int, limit: int = 500) -> list[dict[str, Any]]:
    db = await get_db()
    return await db.all(
        "SELECT seq, job_id, type, data, ts FROM events WHERE project_id = ? AND seq > ? ORDER BY seq LIMIT ?",
        project_id, after, limit,
    )


async def wait(project_id: str, timeout: float = 15.0) -> None:
    cond = _waiters.setdefault(project_id, asyncio.Condition())
    _listeners[project_id] += 1
    try:
        async with cond:
            try:
                await asyncio.wait_for(cond.wait(), timeout)
            except TimeoutError:
                pass
    finally:
        _listeners[project_id] -= 1
        if _listeners[project_id] <= 0:  # nobody follows this project now: a closed stream leaves nothing behind
            _listeners.pop(project_id, None)
            _waiters.pop(project_id, None)
