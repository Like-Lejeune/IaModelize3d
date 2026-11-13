"""Farm operators for IaModelize3d Parts: the Axo farm's people who work the /ops board (assign printers, QC, ship).

An operator is a member of the farm organisation (shop_orgs kind 'farm'). Each run can create one, or make an existing
user one, and print a sign-in link the way judge_link.py does (it opens /ops after the button is pressed).
Dry run by default; --apply writes.

    python scripts/shop_operator.py --name "Roman" --apply          # a new operator user and a link, valid 14 days
    python scripts/shop_operator.py --user u_0123456789abcdef --apply # make your own account an operator (id from /api/me)
    python scripts/shop_operator.py --user u_op_... --link --apply    # one more link for an operator (another browser)
    python scripts/shop_operator.py --list                            # the farm, its operators, their unused links
    python scripts/shop_operator.py --remove u_op_... --apply         # no longer an operator (the user stays)
    python scripts/shop_operator.py --showcase IM-1001 --apply        # anyone may read this delivered order (/parts links it)
    python scripts/shop_operator.py --showcase IM-1001 --off --apply  # back to its customer and the farm only
    python scripts/shop_operator.py --workshop org_... --apply        # a repair shop the farm checked: the workshop tariff
    python scripts/shop_operator.py --workshop org_... --off --apply  # back to the consumer price

A showcase order (shipped or delivered) is readable by anyone at /orders/<id>, without the customer's data: the part,
the journal, the price, the printer, the times and the QC photo with its mask. The /ops board has the same switch.

A repair shop's account (POST /api/shop/orgs) starts 'pending': its people share their orders, and they pay the
consumer price until the farm has checked the workshop and set it here (--list shows the pending ones).

The link is FW_PUBLIC_URL/api/login/<token>?next=/ops and works once. Send it privately.
In the container: docker exec iamodelize3d python scripts/shop_operator.py --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR / "scripts"))

from judge_link import connect, day, default_db, env_setting, has_table, new_id  # noqa: E402

FARM = "Axo"  # the founder's own farm, which prints and ships every order
PREFIX = "u_op_"
TIER = "pro"  # QC photos and calibration coupons are model calls on the operator's own daily budget


def ensure_tables(conn: sqlite3.Connection) -> None:
    """The shop's tables as the server creates them (iamodelize3d.shop.store.SCHEMA), for a database the shop never ran on,
    and the columns added since (store.MIGRATIONS) for one it ran on before them."""
    from iamodelize3d.shop.store import MIGRATIONS, SCHEMA

    if not has_table(conn, "shop_orgs"):
        conn.executescript(SCHEMA)
    for table, column, decl in MIGRATIONS:
        if has_table(conn, table) and column not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def farm(conn: sqlite3.Connection, name: str, apply: bool) -> str | None:
    row = conn.execute("SELECT id FROM shop_orgs WHERE kind = 'farm' AND name = ?", (name,)).fetchone() if has_table(conn, "shop_orgs") else None
    if row:
        return row["id"]
    if not apply:
        print(f"would create the farm organisation {name!r}")
        return None
    oid = new_id("org_")
    conn.execute("INSERT INTO shop_orgs (id, name, kind, tier, contact, created_at) VALUES (?, ?, 'farm', 'farm', '{}', ?)", (oid, name, time.time()))
    print(f"farm organisation {name!r}: {oid}")
    return oid


def link(conn: sqlite3.Connection, base: str, uid: str, days: float, apply: bool) -> None:
    token = new_id("l_") + new_id()
    if apply:
        conn.execute("INSERT INTO logins (token, user_id, expires_at) VALUES (?, ?, ?)", (token, uid, time.time() + days * 86400))
        print(f"sign-in link for {uid}: {base}/api/login/{token}?next=/ops")
    else:
        print(f"would add a sign-in link for {uid}, valid {days:g} days")


def make(conn: sqlite3.Connection, base: str, args: argparse.Namespace) -> None:
    if args.apply:
        ensure_tables(conn)
    org = farm(conn, args.farm, args.apply)
    uid = args.user
    if uid:
        if not conn.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone():
            sys.exit(f"no user {uid} (open the app once in that browser; /api/me shows the id)")
    elif args.apply:
        uid = new_id(PREFIX)
        conn.execute("INSERT INTO users (id, tier, name, contributor_consent, created_at) VALUES (?, ?, ?, 0, ?)", (uid, TIER, args.name, time.time()))
        print(f"operator user {args.name!r}: {uid}")
    else:
        print(f"would create the {TIER} user {args.name!r} ({PREFIX}...)")
    member = org and uid and conn.execute("SELECT 1 FROM shop_members WHERE org_id = ? AND user_id = ?", (org, uid)).fetchone()
    if args.apply and not member:
        conn.execute("INSERT INTO shop_members (org_id, user_id, role) VALUES (?, ?, 'operator')", (org, uid))
        print(f"{uid} operates the {args.farm} farm")
    elif not args.apply and not member:
        print(f"would make {uid or 'that user'} an operator of the {args.farm} farm")
    if not args.user or args.link:
        link(conn, base, uid or PREFIX + "...", args.days, args.apply)
    if not args.apply:
        print("\nadd --apply to write")


def show(conn: sqlite3.Connection, base: str) -> None:
    if not has_table(conn, "shop_orgs"):
        print("no shop tables yet (the server creates them on the first shop request; --apply here does too)")
        return
    t = time.time()
    for org in conn.execute("SELECT * FROM shop_orgs WHERE kind = 'farm' ORDER BY created_at").fetchall():
        print(f"farm {org['name']!r} ({org['id']})")
        for m in conn.execute("SELECT u.id, u.name, u.tier FROM shop_members m JOIN users u ON u.id = m.user_id WHERE m.org_id = ?", (org["id"],)):
            links = conn.execute("SELECT token, expires_at FROM logins WHERE user_id = ? AND expires_at > ?", (m["id"], t)).fetchall()
            print(f"  {m['id']}  {m['name'] or '':<12} {m['tier']:<6} {len(links)} unused link(s)")
            for li in links:
                print(f"      {base}/api/login/{li['token']}?next=/ops  (until {day(li['expires_at'])})")
    printers = conn.execute("SELECT name, preset_id, material, state FROM shop_printers ORDER BY name").fetchall()
    for p in printers:
        print(f"  printer {p['name']}: {p['preset_id']}, {p['material']}, {p['state']}")
    for org in conn.execute("SELECT id, name, tier FROM shop_orgs WHERE kind = 'repair_shop' ORDER BY created_at").fetchall():
        print(f"workshop {org['name']!r} ({org['id']}): {'workshop tariff' if org['tier'] == 'repair_shop' else org['tier'] + ', consumer price'}")


def remove(conn: sqlite3.Connection, uid: str, apply: bool) -> None:
    rows = conn.execute("SELECT o.name FROM shop_members m JOIN shop_orgs o ON o.id = m.org_id WHERE m.user_id = ? AND o.kind = 'farm'", (uid,)).fetchall()
    if not rows:
        sys.exit(f"{uid} is not an operator")
    print(f"{'removed' if apply else 'would remove'} {uid} from {', '.join(r['name'] for r in rows)}" + ("" if apply else " (add --apply)"))
    if apply:
        conn.execute("DELETE FROM shop_members WHERE user_id = ? AND org_id IN (SELECT id FROM shop_orgs WHERE kind = 'farm')", (uid,))


def showcase(conn: sqlite3.Connection, base: str, order: str, on: bool, apply: bool) -> None:
    row = conn.execute("SELECT id, ref, status FROM shop_orders WHERE id = ? OR ref = ?", (order, order)).fetchone()         if has_table(conn, "shop_orders") else None
    if not row:
        sys.exit(f"no order {order} (an id so_... or a ref IM-...)")
    if on and row["status"] not in ("shipped", "delivered"):
        sys.exit(f"{row['ref']} is {row['status']}: only a shipped or delivered order can be shown")
    if apply:
        ensure_tables(conn)  # the showcase column, on a database from before it
        conn.execute("UPDATE shop_orders SET showcase = ?, updated_at = ? WHERE id = ?", (int(on), time.time(), row["id"]))
    what = f"anyone may read it at {base}/orders/{row['id']} (no customer data)" if on else "only its customer and the farm see it"
    print(f"{row['ref']}: {what}" + ("" if apply else " (add --apply)"))


def workshop(conn: sqlite3.Connection, org: str, on: bool, apply: bool) -> None:
    has = has_table(conn, "shop_orgs")
    row = conn.execute("SELECT id, name, tier FROM shop_orgs WHERE id = ? AND kind = 'repair_shop'", (org,)).fetchone() if has else None
    if not row:
        sys.exit(f"no repair shop {org} (--list shows them)")
    if apply:
        conn.execute("UPDATE shop_orgs SET tier = ? WHERE id = ?", ("repair_shop" if on else "pending", row["id"]))
    what = "gets the workshop tariff" if on else "pays the consumer price"
    print(f"{row['name']!r} ({row['id']}) {what}" + ("" if apply else " (add --apply)"))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None, help="iamodelize3d.db (default: FW_DATA_DIR or data/ in the repo)")
    ap.add_argument("--public-url", default=None, help="the app's public address (default: FW_PUBLIC_URL)")
    ap.add_argument("--farm", default=FARM, help="the farm organisation's name")
    ap.add_argument("--name", default="operator", help="name of a new operator user")
    ap.add_argument("--user", default=None, help="make this existing user an operator instead of creating one")
    ap.add_argument("--link", action="store_true", help="with --user: print a sign-in link for them too")
    ap.add_argument("--days", type=float, default=14, help="how long a link works")
    ap.add_argument("--apply", action="store_true", help="write (without it nothing is written)")
    act = ap.add_mutually_exclusive_group()
    act.add_argument("--list", action="store_true", help="show the farm, its operators and printers")
    act.add_argument("--remove", metavar="USER", default=None, help="take the operator role away from this user")
    act.add_argument("--showcase", metavar="ORDER", default=None, help="show this shipped or delivered order to anyone (id or IM- ref)")
    act.add_argument("--workshop", metavar="ORG", default=None, help="the workshop tariff for this repair shop, once the farm checked it")
    ap.add_argument("--off", action="store_true", help="with --showcase: stop showing it; with --workshop: back to the consumer price")
    args = ap.parse_args()

    base = (args.public_url or env_setting("FW_PUBLIC_URL") or "http://localhost:5400").rstrip("/")
    path = args.db or default_db()
    conn = connect(path, write=args.apply and not args.list)
    print(f"database: {path}\n")
    with conn:
        if args.list:
            show(conn, base)
        elif args.remove:
            remove(conn, args.remove, args.apply)
        elif args.showcase:
            showcase(conn, base, args.showcase, not args.off, args.apply)
        elif args.workshop:
            workshop(conn, args.workshop, not args.off, args.apply)
        else:
            make(conn, base, args)
    conn.close()


if __name__ == "__main__":
    main()
