"""SQLite storage. One file, WAL mode, FTS5 for memory and facts retrieval."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import aiosqlite

from .config import settings

SCHEMA = """
PRAGMA busy_timeout=30000;
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, tier TEXT NOT NULL DEFAULT 'anon', name TEXT,
  contributor_consent INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT 'Untitled', pack TEXT,
  status TEXT NOT NULL DEFAULT 'idle', public INTEGER NOT NULL DEFAULT 0, forked_from TEXT,
  version INTEGER NOT NULL DEFAULT 0, cover TEXT, brief TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, mime TEXT,
  width INTEGER, height INTEGER, meta TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS selections (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, asset_id TEXT NOT NULL, role TEXT NOT NULL, name TEXT NOT NULL,
  prompt TEXT NOT NULL DEFAULT '{}', mask_path TEXT, data TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS programs (
  project_id TEXT NOT NULL, version INTEGER NOT NULL, source TEXT NOT NULL, params TEXT NOT NULL DEFAULT '{}',
  inputs TEXT NOT NULL DEFAULT '{}', summary TEXT, checks TEXT, author TEXT NOT NULL DEFAULT 'agent',
  created_at REAL NOT NULL, PRIMARY KEY (project_id, version)
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, project_id TEXT, user_id TEXT, kind TEXT NOT NULL, status TEXT NOT NULL,
  input TEXT NOT NULL DEFAULT '{}', result TEXT, reserved_usd REAL NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0,
  tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0, tokens_cached INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, finished_at REAL
);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, job_id TEXT, type TEXT NOT NULL,
  data TEXT NOT NULL, ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_project ON events(project_id, seq);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, attribute TEXT NOT NULL, value TEXT NOT NULL, unit TEXT,
  source_kind TEXT NOT NULL, source_url TEXT, confidence REAL NOT NULL DEFAULT 0.5, user_id TEXT,
  uses INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(id UNINDEXED, subject, attribute);
CREATE TABLE IF NOT EXISTS memory (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'global', user_id TEXT,
  body TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'candidate',
  uses INTEGER NOT NULL DEFAULT 0, successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
  evidence INTEGER NOT NULL DEFAULT 0, origin_job TEXT, last_used REAL, created_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(id UNINDEXED, name, tags, text);
CREATE TABLE IF NOT EXISTS printers (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, preset TEXT NOT NULL DEFAULT '{}',
  fingerprint TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS spend (
  user_id TEXT NOT NULL, day TEXT NOT NULL, usd REAL NOT NULL DEFAULT 0, jobs INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS captures (
  token TEXT PRIMARY KEY, project_id TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS logins (
  token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at REAL NOT NULL, last_seen REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS tg_chats (
  chat_id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, user_id TEXT NOT NULL, status TEXT NOT NULL,
  external_ref TEXT, checkout_url TEXT, quote TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS replay_views (
  project_id TEXT NOT NULL, user_id TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS idempotency (
  user_id TEXT NOT NULL, scope TEXT NOT NULL, idem_key TEXT NOT NULL, ref TEXT, created_at REAL NOT NULL,
  PRIMARY KEY (user_id, scope, idem_key)
);
"""

MIGRATIONS = [
    ("users", "ip", "TEXT"),
    ("projects", "replay_of", "TEXT"),
    # home page order of curated public runs (0: not featured)
    ("projects", "featured", "INTEGER DEFAULT 0"),
    # users from before sessions, whose browsers send the bare user id: 0 until it is swapped for a session, then the
    # time of that swap (sessions.adopt_legacy); NULL for everyone else. The backfill runs once, as the column appears.
    ("users", "legacy_cookie", "REAL", "UPDATE users SET legacy_cookie = 0"),
    # the replay gallery: public is the link, listed puts the run on /replays too; hidden is an admin's word over both
    ("projects", "listed", "INTEGER DEFAULT 0"),
    ("projects", "listed_at", "REAL"),
    ("projects", "hidden", "INTEGER DEFAULT 0"),
    ("projects", "views", "INTEGER DEFAULT 0"),
]

JSON_COLUMNS = {"brief", "meta", "prompt", "data", "params", "inputs", "checks", "input", "result", "body", "preset", "fingerprint", "quote"}


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:16]


def now() -> float:
    return time.time()


def _decode(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for k, v in out.items():
        if k in JSON_COLUMNS and isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                pass
    return out


def _encode(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self._migrate()
        await self.conn.commit()

    async def _migrate(self) -> None:
        """Additive column migrations for databases created by older versions."""
        assert self.conn
        for table, column, decl, *backfill in MIGRATIONS:
            async with self.conn.execute(f"PRAGMA table_info({table})") as cur:
                cols = {r[1] for r in await cur.fetchall()}
            if column not in cols:
                await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
                for sql in backfill:
                    await self.conn.execute(sql)

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def execute(self, sql: str, *args: Any) -> int:
        assert self.conn
        cur = await self.conn.execute(sql, tuple(_encode(a) for a in args))
        await self.conn.commit()
        return cur.lastrowid or cur.rowcount

    async def one(self, sql: str, *args: Any) -> dict[str, Any] | None:
        assert self.conn
        async with self.conn.execute(sql, tuple(_encode(a) for a in args)) as cur:
            return _decode(await cur.fetchone())

    async def all(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        assert self.conn
        async with self.conn.execute(sql, tuple(_encode(a) for a in args)) as cur:
            return [_decode(r) for r in await cur.fetchall()]  # type: ignore[misc]

    async def returning(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        """A write with RETURNING, committed: the rows it changed, e.g. to use a one-time token up atomically."""
        assert self.conn
        async with self.conn.execute(sql, tuple(_encode(a) for a in args)) as cur:
            rows = [_decode(r) for r in await cur.fetchall()]
        await self.conn.commit()
        return rows  # type: ignore[return-value]

    async def insert(self, table: str, row: dict[str, Any]) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        await self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", *row.values())

    async def update(self, table: str, key: str, key_value: Any, fields: dict[str, Any]) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self.execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", *fields.values(), key_value)


_db: Database | None = None


async def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(str(settings().data_dir / "formwright.db"))
        await _db.open()
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None
