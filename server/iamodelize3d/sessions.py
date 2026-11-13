"""Browser sessions. The cookie carries a random token and the database keeps only its SHA-256: the cookie is not the
user id (a Telegram user's id is easy to guess), a copy of the database signs nobody in, and deleting a user's rows
signs every browser of theirs out (judge_link.py --revoke does).

Sign-in links (logins rows: judge links, the Telegram bot) work once; `redeem` uses one up.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from .db import get_db, now

COOKIE = "fw_session"
LEGACY_COOKIE = "fw_uid"  # before sessions this cookie held the user id itself
MAX_AGE = 365 * 86400  # an anonymous person's projects live in their session: keep it a year after the last visit
TOUCH_S = 86400  # last_seen, and with it the cookie's lifetime, is renewed at most once a day
# a page load sends several requests at once, each with the old cookie: they all get a session in this window
LEGACY_GRACE_S = 600
# ids our code drew at random (db.new_id); tg_<Telegram id> is guessable, so it never counts as proof
LEGACY_ID = re.compile(r"u_(?:judge_)?[0-9a-f]{16}")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue(user_id: str) -> str:
    """A new session for this user; returns the token for the cookie."""
    token = secrets.token_urlsafe(32)
    t = now()
    db = await get_db()
    await db.execute("DELETE FROM sessions WHERE expires_at < ?", t)
    await db.insert("sessions", {"id": _digest(token), "user_id": user_id, "created_at": t, "last_seen": t, "expires_at": t + MAX_AGE})
    return token


async def user_for(token: str | None) -> tuple[dict[str, Any] | None, bool]:
    """The user a session cookie belongs to, and whether its lifetime was just renewed (send the cookie again)."""
    if not token or len(token) > 128:
        return None, False
    db = await get_db()
    t = now()
    sid = _digest(token)
    user = await db.one("SELECT u.*, s.last_seen AS session_seen FROM sessions s JOIN users u ON u.id = s.user_id "
                        "WHERE s.id = ? AND s.expires_at > ?", sid, t)
    if not user:
        return None, False
    renew = t - user.pop("session_seen") > TOUCH_S
    if renew:
        await db.execute("UPDATE sessions SET last_seen = ?, expires_at = ? WHERE id = ?", t, t + MAX_AGE, sid)
    return user, renew


async def adopt_legacy(uid: str | None) -> dict[str, Any] | None:
    """A browser signed in before sessions existed sends its user id. It may swap it for a session: only an id our
    code drew at random, only for a user who existed before sessions (users.legacy_cookie, set by the migration), and
    only within LEGACY_GRACE_S of the first swap. After that the bare id signs nobody in."""
    if not uid or not LEGACY_ID.fullmatch(uid):
        return None
    t = now()
    db = await get_db()
    rows = await db.returning("UPDATE users SET legacy_cookie = CASE WHEN legacy_cookie = 0 THEN ? ELSE legacy_cookie END "
                              "WHERE id = ? AND (legacy_cookie = 0 OR legacy_cookie > ?) RETURNING *", t, uid, t - LEGACY_GRACE_S)
    return rows[0] if rows else None


async def revoke(user_id: str) -> None:
    """Signs every browser of this user out, a pre-session cookie included."""
    db = await get_db()
    await db.execute("DELETE FROM sessions WHERE user_id = ?", user_id)
    await db.execute("UPDATE users SET legacy_cookie = NULL WHERE id = ?", user_id)


async def login_target(token: str) -> dict[str, Any] | None:
    """The user an unused, unexpired sign-in link names (its name for the confirmation page); nothing is used up."""
    db = await get_db()
    return await db.one("SELECT u.id, u.name FROM logins l JOIN users u ON u.id = l.user_id WHERE l.token = ? AND l.expires_at > ?",
                        token, now())


async def redeem(token: str) -> str | None:
    """Uses a sign-in link up and returns its user id: of two requests with one link, one signs in."""
    db = await get_db()
    rows = await db.returning("DELETE FROM logins WHERE token = ? AND expires_at > ? RETURNING user_id", token, now())
    return rows[0]["user_id"] if rows else None


def send_cookie(response: Response, request: Request, token: str | None) -> None:
    """Sets the session cookie (None: the browser's own stays) and drops a pre-session cookie."""
    if token:
        response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax", secure=request.url.scheme == "https")
    if LEGACY_COOKIE in request.cookies:
        response.delete_cookie(LEGACY_COOKIE)
