"""Idempotency-Key on the routes that create an order: a retry after a lost answer (or a second click) with the same key
gets the first order back instead of a second one. Same person, same scope, for a day; without the header nothing changes.

The key is claimed before the work starts, so two requests at once cannot both create. A request that fails gives its
claim back: the retry does the work again.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, Request

from .db import get_db, now

HEADER = "Idempotency-Key"
WINDOW_S = 86400
WAIT_S = 30.0  # how long a retry waits for the first request, still working, before it says so


def key_of(request: Request) -> str | None:
    return (request.headers.get(HEADER) or "").strip()[:128] or None


async def once(user_id: str, scope: str, key: str | None, make: Callable[[], Awaitable[dict[str, Any]]],
               again: Callable[[str], Awaitable[dict[str, Any] | None]], *, ref: Callable[[dict[str, Any]], Any] = lambda o: o["id"]) -> dict[str, Any]:
    """make() once per key; a repeat answers with again(ref of the first result). A result whose ref is empty created
    nothing (an order Axo refused): its claim goes back too."""
    if not key:
        return await make()
    db = await get_db()
    await db.execute("DELETE FROM idempotency WHERE created_at < ?", now() - WINDOW_S)
    where = "user_id = ? AND scope = ? AND idem_key = ?"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_S
    while True:
        claimed = await db.returning("INSERT INTO idempotency (user_id, scope, idem_key, created_at) VALUES (?, ?, ?, ?) "
                                     "ON CONFLICT DO NOTHING RETURNING idem_key", user_id, scope, key, now())
        if claimed:
            break
        row = await db.one(f"SELECT ref FROM idempotency WHERE {where}", user_id, scope, key)
        if row and row["ref"]:
            first = await again(row["ref"])
            if first is None:
                raise HTTPException(409, {"detail": "the order this request repeats is gone", "code": "order_gone"})
            return first
        if row and loop.time() > deadline:
            raise HTTPException(409, {"detail": "this order is still being placed; look at your orders in a moment", "code": "order_in_progress"})
        if row:
            await asyncio.sleep(0.25)
    try:
        out = await make()
        done = ref(out)
    except BaseException:
        with contextlib.suppress(Exception):
            await db.execute(f"DELETE FROM idempotency WHERE {where}", user_id, scope, key)
        raise
    if done:
        await db.execute(f"UPDATE idempotency SET ref = ? WHERE {where}", str(done), user_id, scope, key)
    else:
        await db.execute(f"DELETE FROM idempotency WHERE {where}", user_id, scope, key)
    return out
