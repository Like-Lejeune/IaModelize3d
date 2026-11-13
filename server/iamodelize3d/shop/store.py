"""Shop tables on the shared SQLite connection. Created on first use, so db.py stays untouched.

Personal data kept to the minimum a delivery needs (a phone or e-mail, an address), only on the order, and wiped
once the order is delivered.
"""
from __future__ import annotations

import json
import sqlite3
import weakref
from typing import Any

from iamodelize3d.db import Database, get_db, new_id, now

from . import flow, notes

SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_orgs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'repair_shop', tier TEXT NOT NULL DEFAULT 'repair_shop',
  contact TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS shop_members (
  org_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', PRIMARY KEY (org_id, user_id)
);
CREATE TABLE IF NOT EXISTS shop_listings (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, version INTEGER NOT NULL, owner_id TEXT NOT NULL, title TEXT NOT NULL,
  title_en TEXT NOT NULL DEFAULT '', title_ru TEXT NOT NULL DEFAULT '', brand TEXT NOT NULL DEFAULT '', models TEXT NOT NULL DEFAULT '[]', part_numbers TEXT NOT NULL DEFAULT '[]',
  category TEXT NOT NULL DEFAULT '', material TEXT NOT NULL DEFAULT 'PLA', cover TEXT, verified TEXT NOT NULL DEFAULT '{}',
  public INTEGER NOT NULL DEFAULT 0, orders INTEGER NOT NULL DEFAULT 0, flagged INTEGER NOT NULL DEFAULT 0,
  reports TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS shop_listings_owner ON shop_listings(owner_id, project_id);
CREATE VIRTUAL TABLE IF NOT EXISTS shop_listings_fts USING fts5(id UNINDEXED, title, brand, models, part_numbers);
CREATE TABLE IF NOT EXISTS shop_orders (
  id TEXT PRIMARY KEY, ref TEXT NOT NULL, user_id TEXT NOT NULL, org_id TEXT, project_id TEXT NOT NULL, version INTEGER,
  listing_id TEXT, status TEXT NOT NULL, intake TEXT NOT NULL DEFAULT '{}', quantity INTEGER NOT NULL DEFAULT 1,
  material TEXT NOT NULL DEFAULT 'PLA', color TEXT, delivery TEXT NOT NULL DEFAULT '{}', customer TEXT NOT NULL DEFAULT '{}',
  quote TEXT NOT NULL DEFAULT '{}', payment TEXT NOT NULL DEFAULT '{}', printer_id TEXT, slice TEXT NOT NULL DEFAULT '{}',
  qc TEXT NOT NULL DEFAULT '{}', shipping TEXT NOT NULL DEFAULT '{}', fulfilment TEXT NOT NULL DEFAULT 'own', external_ref TEXT,
  problem TEXT NOT NULL DEFAULT '{}', attempts INTEGER NOT NULL DEFAULT 0, showcase INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS shop_orders_ref ON shop_orders(ref);
CREATE INDEX IF NOT EXISTS shop_orders_status ON shop_orders(status, updated_at);
CREATE INDEX IF NOT EXISTS shop_orders_user ON shop_orders(user_id, created_at);
CREATE INDEX IF NOT EXISTS shop_orders_project ON shop_orders(project_id);
CREATE TABLE IF NOT EXISTS shop_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL, frm TEXT, too TEXT NOT NULL, actor TEXT NOT NULL,
  actor_id TEXT, note TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}', ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS shop_log_order ON shop_log(order_id, seq);
CREATE TABLE IF NOT EXISTS shop_printers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, preset_id TEXT NOT NULL, fingerprint TEXT NOT NULL DEFAULT '{}',
  material TEXT NOT NULL DEFAULT 'PLA', color TEXT, state TEXT NOT NULL DEFAULT 'idle', order_id TEXT, created_at REAL NOT NULL
);
"""
JSON_FIELDS = ("intake", "delivery", "customer", "quote", "payment", "slice", "qc", "shipping", "problem", "models", "part_numbers",
               "verified", "contact", "data", "reports", "fingerprint")
ORDER_COLUMNS = {"version", "listing_id", "intake", "quantity", "material", "color", "delivery", "customer", "quote", "payment",
                 "printer_id", "slice", "qc", "shipping", "fulfilment", "external_ref", "problem", "attempts", "org_id", "showcase"}

# columns added after a table first shipped: (table, column, declaration), added to older databases by ensure()
MIGRATIONS = [
    ("shop_listings", "title_en", "TEXT NOT NULL DEFAULT ''"),  # the catalog card follows the UI's language
    ("shop_listings", "title_ru", "TEXT NOT NULL DEFAULT ''"),
    ("shop_orders", "showcase", "INTEGER NOT NULL DEFAULT 0"),  # a delivered order anyone may read, without its customer's data
]

_ready: weakref.WeakSet[Database] = weakref.WeakSet()


async def ensure(db: Database) -> None:
    if db in _ready:
        return
    assert db.conn
    await db.conn.executescript(SCHEMA)
    for table, column, decl in MIGRATIONS:
        async with db.conn.execute(f"PRAGMA table_info({table})") as cur:
            if column not in {r[1] for r in await cur.fetchall()}:
                await db.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    await db.conn.commit()
    _ready.add(db)


async def shop_db() -> Database:
    db = await get_db()
    await ensure(db)
    return db


def _dec(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    for k in JSON_FIELDS:
        if isinstance(row.get(k), str):
            try:
                row[k] = json.loads(row[k])
            except json.JSONDecodeError:
                pass
    return row


async def _next_ref(db: Database) -> str:
    row = await db.one("SELECT MAX(CAST(SUBSTR(ref, 4) AS INTEGER)) AS n FROM shop_orders WHERE ref LIKE 'IM-%'")
    return f"IM-{max(1000, (row or {}).get('n') or 1000) + 1}"


async def create_order(db: Database, *, user_id: str, project_id: str, org_id: str | None = None, listing_id: str | None = None,
                       version: int | None = None, intake: dict | None = None, quantity: int = 1, material: str = "PLA",
                       delivery: dict | None = None, customer: dict | None = None, quote: dict | None = None,
                       status: str = "requested", code: str = "created", params: dict | None = None) -> dict[str, Any]:
    await ensure(db)
    oid = new_id("so_")
    t = now()
    for attempt in range(5):
        # two requests at the same moment may draw the same number: the unique index sends the second one round again
        row = {"id": oid, "ref": await _next_ref(db), "user_id": user_id, "org_id": org_id, "project_id": project_id, "version": version,
               "listing_id": listing_id, "status": status, "intake": intake or {}, "quantity": max(1, int(quantity)), "material": material,
               "delivery": delivery or {"method": "courier"}, "customer": customer or {}, "quote": quote or {}, "created_at": t, "updated_at": t}
        try:
            await db.insert("shop_orders", row)
            break
        except sqlite3.IntegrityError:
            if attempt == 4:
                raise
    await log(db, oid, None, status, "system", None, code=code, params=params)
    return await get(db, oid)  # type: ignore[return-value]


async def get(db: Database, order_id: str) -> dict[str, Any] | None:
    await ensure(db)
    return _dec(await db.one("SELECT * FROM shop_orders WHERE id = ?", order_id))


async def log(db: Database, order_id: str, frm: str | None, to: str, actor: str, actor_id: str | None, note: str = "", data: dict | None = None,
              *, code: str | None = None, params: dict | None = None) -> None:
    """One journal line. With `code` (shop/notes.py) the UI says it in its own language; `note` is then its English line."""
    if code:
        note = note or notes.text(code, params)
        data = {**(data or {}), "code": code, "params": params or {}}
    await db.execute("INSERT INTO shop_log (order_id, frm, too, actor, actor_id, note, data, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     order_id, frm, to, actor, actor_id, note[:500], data or {}, now())


async def timeline(db: Database, order_id: str) -> list[dict[str, Any]]:
    return [_dec(r) for r in await db.all("SELECT * FROM shop_log WHERE order_id = ? ORDER BY seq", order_id)]  # type: ignore[misc]


def _check_fields(fields: dict[str, Any]) -> None:
    bad = set(fields) - ORDER_COLUMNS
    if bad:
        raise ValueError(f"not an order field: {sorted(bad)}")


async def patch(db: Database, order_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    _check_fields(fields)
    await db.update("shop_orders", "id", order_id, {**fields, "updated_at": now()})
    return await get(db, order_id)  # type: ignore[return-value]


async def _set_if(db: Database, order_id: str, status: str, sets: dict[str, Any]) -> bool:
    # Database.execute returns `lastrowid or rowcount`, and lastrowid is the connection's last INSERT even after an
    # UPDATE, so a lost race would still look like a success: read rowcount from the cursor itself
    cols = ", ".join(f"{k} = ?" for k in sets)
    values = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in sets.values()]
    assert db.conn
    cur = await db.conn.execute(f"UPDATE shop_orders SET {cols} WHERE id = ? AND status = ?", (*values, order_id, status))
    await db.conn.commit()
    return cur.rowcount == 1


async def patch_if(db: Database, order_id: str, fields: dict[str, Any], status: str) -> dict[str, Any]:
    """patch() only while the order is still `status`: a slow step (a requote's slice, a QC measurement) must not
    rewrite an order that moved on meanwhile (paid, sent back for a reprint)."""
    _check_fields(fields)
    if not await _set_if(db, order_id, status, {**fields, "updated_at": now()}):
        raise flow.FlowError("conflict", "the order changed meanwhile")
    return await get(db, order_id)  # type: ignore[return-value]


async def move(db: Database, order_id: str, to: str, actor: str, actor_id: str | None = None, *, note: str = "",
               data: dict[str, Any] | None = None, fields: dict[str, Any] | None = None, code: str | None = None,
               params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validated status change. `fields` are written in the same statement (and are visible to the guard);
    `data` is what the guard reads, `code` and `params` the journal's note (see log)."""
    o = await get(db, order_id)
    if not o:
        raise flow.FlowError("not_found", "order not found")
    fields = fields or {}
    _check_fields(fields)
    flow.check({**o, **fields}, to, actor, data)
    # compare-and-set on the status, so two operators cannot both move the same order
    if not await _set_if(db, order_id, o["status"], {"status": to, "updated_at": now(), **fields}):
        raise flow.FlowError("conflict", "the order changed meanwhile")
    await log(db, order_id, o["status"], to, actor, actor_id, note, data, code=code, params=params)
    return await get(db, order_id)  # type: ignore[return-value]


async def queue(db: Database) -> list[dict[str, Any]]:
    await ensure(db)
    rows = await db.all("SELECT * FROM shop_orders WHERE status IN (?, ?, ?) ORDER BY CASE status WHEN 'qc' THEN 0 WHEN 'printing' THEN 1 ELSE 2 END, updated_at",
                        *flow.ACTIVE)
    return [_dec(r) for r in rows]  # type: ignore[misc]


async def upstream(db: Database, limit: int = 50) -> list[dict[str, Any]]:
    """Orders before payment: being read, designed, waiting for an answer or a quote, or held for the operator.
    The ones that need the farm or a step come first, newest first; quotes waiting for the customer's payment fill the
    rest, so a pile of unpaid quotes cannot push a new request off the board."""
    await ensure(db)
    rows = await db.all("SELECT * FROM shop_orders WHERE status IN ('requested', 'designing', 'needs_info', 'quoted') "
                        "ORDER BY status = 'quoted', updated_at DESC LIMIT ?", limit)
    return [_dec(r) for r in rows]  # type: ignore[misc]


async def done(db: Database, limit: int = 12) -> list[dict[str, Any]]:
    """The farm's latest shipped and delivered orders (the board's last column: where an operator picks a showcase)."""
    await ensure(db)
    rows = await db.all("SELECT * FROM shop_orders WHERE status IN ('shipped', 'delivered') ORDER BY updated_at DESC LIMIT ?", limit)
    return [_dec(r) for r in rows]  # type: ignore[misc]


async def showcase(db: Database) -> dict[str, Any] | None:
    """The newest order an operator made a showcase (it is shipped or delivered)."""
    await ensure(db)
    return _dec(await db.one("SELECT * FROM shop_orders WHERE showcase = 1 AND status IN ('shipped', 'delivered') ORDER BY updated_at DESC LIMIT 1"))


def shipped_cover(o: dict[str, Any], p: dict[str, Any] | None) -> str | None:
    """The render of the version an order printed (data/files-relative), which is what a showcase shows: the project's
    cover is its newest version, and a customer's studio project may have gone on to private versions since."""
    from iamodelize3d import storage

    v = o.get("version")
    rel = f"{o['project_id']}/renders/v{v}_iso.png"
    if v and storage.abs_path(rel).is_file():
        return rel
    return (p or {}).get("cover") if p and v and p.get("version") == v else None


async def queue_hours(db: Database) -> float:
    """Print hours already promised: paid and printing orders, from their firm quotes. An anonymous visitor's test
    payment (no money moves, and anyone can make one) counts once the farm puts it on a printer, so it cannot push
    every other customer's ETA back."""
    total = 0.0
    for o in await queue(db):
        q = o.get("quote") or {}
        if o["status"] == "paid" and (o.get("payment") or {}).get("mode") == "test" and await db.one(
                "SELECT 1 FROM users WHERE id = ? AND tier = 'anon'", o["user_id"]):
            continue
        if o["status"] in ("paid", "printing"):
            total += (q.get("minutes_each") or 0) * (o.get("quantity") or 1) / 60
    return round(total, 2)


async def printers_online(db: Database) -> int:
    await ensure(db)
    row = await db.one("SELECT COUNT(*) AS n FROM shop_printers WHERE state != 'maintenance'")
    return int((row or {}).get("n") or 0)


# ------------------------------------------------------------------ catalog
def _fts_text(listing: dict[str, Any]) -> tuple[str, str, str, str]:
    # its name in either language finds it ('колесо' and 'wheel' alike)
    names = " ".join(dict.fromkeys(x for x in (listing["title"], listing.get("title_en"), listing.get("title_ru")) if x))
    return names, listing.get("brand") or "", " ".join(listing.get("models") or []), " ".join(listing.get("part_numbers") or [])


async def get_listing(db: Database, listing_id: str) -> dict[str, Any] | None:
    await ensure(db)
    return _dec(await db.one("SELECT * FROM shop_listings WHERE id = ?", listing_id))


async def save_listing(db: Database, *, project_id: str, version: int, owner_id: str, title: str, brand: str = "", models: list[str] | None = None,
                       part_numbers: list[str] | None = None, category: str = "", material: str = "PLA", cover: str | None = None,
                       verified: dict | None = None, public: bool = False, title_en: str = "", title_ru: str = "") -> dict[str, Any]:
    """One listing per owner and project: sharing a part again updates it (and its search entry) instead of adding one.
    `title` is the owner's own (in their language); title_en and title_ru name it for the card in each UI language."""
    await ensure(db)
    fields = {"version": version, "title": title[:120], "title_en": title_en[:120], "title_ru": title_ru[:120], "brand": brand[:60], "models": [m[:60] for m in (models or [])][:10],
              "part_numbers": [n[:60] for n in (part_numbers or [])][:10], "category": category[:40], "material": material, "cover": cover,
              "verified": verified or {}, "public": int(public), "updated_at": now()}
    old = await db.one("SELECT id FROM shop_listings WHERE owner_id = ? AND project_id = ?", owner_id, project_id)
    if old:
        lid = old["id"]
        await db.update("shop_listings", "id", lid, fields)
        await db.execute("DELETE FROM shop_listings_fts WHERE id = ?", lid)
    else:
        lid = new_id("sl_")
        await db.insert("shop_listings", {"id": lid, "project_id": project_id, "owner_id": owner_id, "created_at": now(), **fields})
    await db.execute("INSERT INTO shop_listings_fts (id, title, brand, models, part_numbers) VALUES (?, ?, ?, ?, ?)", lid, *_fts_text(fields))
    return await get_listing(db, lid)  # type: ignore[return-value]


def _fts_query(q: str) -> str:
    # every token must match (prefix), quoted so part numbers like 00611475 or SMS46GI01E are literal
    toks = [t for t in "".join(c if c.isalnum() else " " for c in q).split() if t]
    return " AND ".join(f'"{t}"*' for t in toks[:8])


async def search_listings(db: Database, q: str = "", limit: int = 30) -> list[dict[str, Any]]:
    """The public catalog: shared, not taken down, best-selling first."""
    await ensure(db)
    if q.strip() and (fq := _fts_query(q)):
        rows = await db.all("SELECT l.* FROM shop_listings_fts f JOIN shop_listings l ON l.id = f.id WHERE shop_listings_fts MATCH ? "
                            "AND l.public = 1 AND l.flagged = 0 ORDER BY l.orders DESC, l.updated_at DESC LIMIT ?", fq, limit)
    else:
        rows = await db.all("SELECT * FROM shop_listings WHERE public = 1 AND flagged = 0 ORDER BY orders DESC, updated_at DESC LIMIT ?", limit)
    return [_dec(r) for r in rows]  # type: ignore[misc]


async def own_listing(db: Database, owner_id: str, project_id: str) -> dict[str, Any] | None:
    """Whether the owner's part is in the catalog: {id, public} of their listing of this project, None without one."""
    await ensure(db)
    row = await db.one("SELECT id, public FROM shop_listings WHERE owner_id = ? AND project_id = ?", owner_id, project_id)
    return {"id": row["id"], "public": bool(row["public"])} if row else None


async def my_listings(db: Database, owner_id: str, limit: int = 100) -> list[dict[str, Any]]:
    await ensure(db)
    rows = await db.all("SELECT * FROM shop_listings WHERE owner_id = ? ORDER BY updated_at DESC LIMIT ?", owner_id, limit)
    return [_dec(r) for r in rows]  # type: ignore[misc]


# ------------------------------------------------------------------ people
async def role(db: Database, user_id: str) -> tuple[str, str | None]:
    """('operator', farm org) | ('repair_shop', org) | ('consumer', None)."""
    await ensure(db)
    r = await db.one("SELECT m.role, o.id, o.kind FROM shop_members m JOIN shop_orgs o ON o.id = m.org_id WHERE m.user_id = ? "
                     "ORDER BY CASE o.kind WHEN 'farm' THEN 0 ELSE 1 END LIMIT 1", user_id)
    if not r:
        return "consumer", None
    if r["kind"] == "farm":
        return "operator", r["id"]
    return "repair_shop", r["id"]


async def org_of(db: Database, user_id: str) -> dict[str, Any] | None:
    await ensure(db)
    return _dec(await db.one("SELECT o.id, o.name, o.kind, o.tier, m.role FROM shop_members m JOIN shop_orgs o ON o.id = m.org_id "
                             "WHERE m.user_id = ? ORDER BY CASE o.kind WHEN 'farm' THEN 0 ELSE 1 END LIMIT 1", user_id))
