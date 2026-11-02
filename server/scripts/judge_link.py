"""Sign-in links for judges: each link opens the live app as its own 'pro' user (more daily budget, three jobs
at once, Muse Wonder), so judges do not share the anonymous per-address cap or see each other's projects.

Dry run by default; --apply writes the users and logins rows. Standard library only:

    python scripts/judge_link.py --count 3 --apply          # three links, valid 14 days
    python scripts/judge_link.py --user u_judge_... --apply # one more link for that judge (another browser)
    python scripts/judge_link.py --list                     # judge users, their links, browsers and today's spend
    python scripts/judge_link.py --revoke --apply           # expire every judge link and sign the judges out

The link is FW_PUBLIC_URL/api/login/<token>. It works once: the page it opens has a button that signs that
browser in with a session of its own and uses the link up (link previews only see the page). Until then anyone who
has it can use it, so send it privately. In the container: docker exec formwright python scripts/judge_link.py --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent
PREFIX = "u_judge_"  # how --list and --revoke find these users
LIKE = PREFIX.replace("_", "!_") + "%"  # with ESCAPE '!': a bare "_" matches any character in LIKE
TIER = "pro"  # quotas.TIERS


def env_setting(name: str) -> str | None:
    """A setting as the server reads it: the environment first, then .env in the repo, then one folder up."""
    if os.environ.get(name):
        return os.environ[name]
    for path in (REPO_DIR / ".env", REPO_DIR.parent / ".env"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            key, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and key.strip().upper() == name:
                return value.strip().strip("'\"") or None
    return None


def default_db() -> Path:
    data = Path(env_setting("FW_DATA_DIR") or REPO_DIR / "data")
    return (data if data.is_absolute() else SERVER_DIR / data) / "formwright.db"


def connect(path: Path, write: bool) -> sqlite3.Connection:
    if not path.exists():
        sys.exit(f"no database at {path} (pass --db, or start the server once to create it)")
    conn = sqlite3.connect(path, timeout=10) if write else sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:16]  # as db.new_id does


def day(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def another(conn: sqlite3.Connection, base: str, uid: str, days: float, apply: bool) -> None:
    """One more link for an existing judge: each link signs in one browser."""
    user = conn.execute("SELECT id, name FROM users WHERE id = ? AND id LIKE ? ESCAPE '!'", (uid, LIKE)).fetchone()
    if not user:
        sys.exit(f"no judge user {uid} (see --list)")
    expires = time.time() + days * 86400
    token = new_id("l_") + new_id()
    if apply:
        conn.execute("INSERT INTO logins (token, user_id, expires_at) VALUES (?, ?, ?)", (token, uid, expires))
        print(f"{user['name'] or uid}: {base}/api/login/{token}")
    else:
        print(f"would add a link for {uid} valid until {day(expires)}\n\nadd --apply to create it and print the link")


def create(conn: sqlite3.Connection, base: str, count: int, days: float, name: str, apply: bool) -> None:
    t = time.time()
    expires = t + days * 86400
    for i in range(count):
        uid = new_id(PREFIX)
        token = new_id("l_") + new_id()
        label = name if count == 1 else f"{name} {i + 1}"
        if apply:
            conn.execute("INSERT INTO users (id, tier, name, contributor_consent, created_at) VALUES (?, ?, ?, 0, ?)", (uid, TIER, label, t))
            conn.execute("INSERT INTO logins (token, user_id, expires_at) VALUES (?, ?, ?)", (token, uid, expires))
            print(f"{label}: {base}/api/login/{token}")
        else:
            print(f"would create {TIER} user {uid} ({label}) with a link valid until {day(expires)}")
    if not apply:
        print("\nadd --apply to create them and print the links")


def show(conn: sqlite3.Connection, base: str) -> None:
    t = time.time()
    users = conn.execute("SELECT id, name FROM users WHERE id LIKE ? ESCAPE '!' ORDER BY created_at", (LIKE,)).fetchall()
    if not users:
        print("no judge users yet")
    today = time.strftime("%Y-%m-%d")  # quotas.spent_today uses the local date too
    sessions = has_table(conn, "sessions")
    for u in users:
        spent = conn.execute("SELECT usd, jobs FROM spend WHERE user_id = ? AND day = ?", (u["id"], today)).fetchone()
        links = conn.execute("SELECT token, expires_at FROM logins WHERE user_id = ? AND expires_at > ? ORDER BY expires_at", (u["id"], t)).fetchall()
        browsers = conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND expires_at > ?", (u["id"], t)).fetchone()[0] if sessions else 0
        state = f"{len(links)} unused link(s), {browsers} browser(s) signed in"
        print(f"{u['id']}  {u['name'] or '':<10} {state:<40} today ${spent['usd'] if spent else 0:.3f} in {spent['jobs'] if spent else 0} jobs")
        for link in links:
            print(f"    {base}/api/login/{link['token']}  (until {day(link['expires_at'])})")


def revoke(conn: sqlite3.Connection, apply: bool) -> None:
    t = time.time()
    rows = conn.execute("SELECT token FROM logins WHERE user_id LIKE ? ESCAPE '!' AND expires_at > ?", (LIKE, t)).fetchall()
    sessions = has_table(conn, "sessions")
    signed_in = conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id LIKE ? ESCAPE '!'", (LIKE,)).fetchone()[0] if sessions else 0
    print(f"{'expired' if apply else 'would expire'} {len(rows)} judge links and {'signed out' if apply else 'would sign out'} {signed_in} browsers"
          + ("" if apply else " (add --apply)"))
    if apply:
        conn.execute("UPDATE logins SET expires_at = ? WHERE user_id LIKE ? ESCAPE '!' AND expires_at > ?", (t, LIKE, t))
        if sessions:
            conn.execute("DELETE FROM sessions WHERE user_id LIKE ? ESCAPE '!'", (LIKE,))
        if "legacy_cookie" in {r[1] for r in conn.execute("PRAGMA table_info(users)")}:
            # a browser signed in before sessions existed could still swap its old cookie for one (sessions.adopt_legacy)
            conn.execute("UPDATE users SET legacy_cookie = NULL WHERE id LIKE ? ESCAPE '!'", (LIKE,))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None, help="formwright.db (default: FW_DATA_DIR or data/ in the repo)")
    ap.add_argument("--public-url", default=None, help="the app's public address (default: FW_PUBLIC_URL)")
    ap.add_argument("--count", type=int, default=1, help="how many judges, one user and link each")
    ap.add_argument("--days", type=float, default=14, help="how long the links work")
    ap.add_argument("--name", default="judge", help="user name shown in the database")
    ap.add_argument("--user", default=None, help="add one link for this existing judge user instead of creating users")
    ap.add_argument("--apply", action="store_true", help="write (without it nothing is written)")
    act = ap.add_mutually_exclusive_group()
    act.add_argument("--list", action="store_true", help="show judge users and their links")
    act.add_argument("--revoke", action="store_true", help="expire every judge link and sign the judges out")
    args = ap.parse_args()

    base = (args.public_url or env_setting("FW_PUBLIC_URL") or "http://localhost:5400").rstrip("/")
    if not (args.list or args.revoke) and any(h in base for h in ("localhost", "127.0.0.1", "[::1]")):
        print(f"warning: the public URL is {base}, so these links work on this computer only; set FW_PUBLIC_URL or pass --public-url\n")
    path = args.db or default_db()
    conn = connect(path, write=args.apply and not args.list)
    print(f"database: {path}\n")
    with conn:
        if args.list:
            show(conn, base)
        elif args.revoke:
            revoke(conn, args.apply)
        elif args.user:
            another(conn, base, args.user, args.days, args.apply)
        else:
            create(conn, base, max(1, args.count), args.days, args.name, args.apply)
    conn.close()


if __name__ == "__main__":
    main()
