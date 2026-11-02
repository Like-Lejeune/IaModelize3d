"""Seed Formwright Parts for a demo: the Axo farm, its printer (a Bambu Lab A1 with the 0.4 mm nozzle, the OrcaSlicer
preset the farm slices with), and catalog listings made from projects that already passed the build checks.

Dry run by default: it opens the database read-only and prints what it would add. --apply writes. Nothing is deleted
and nothing already there is changed (run it twice and the second run adds nothing), except a listing's names, brand,
models and part numbers when you give them for one project, and a private listing that --public makes public.

    python scripts/shop_seed.py                                  # what it would add
    python scripts/shop_seed.py --apply                          # the farm, one A1 printer, up to 4 private listings
    python scripts/shop_seed.py --material PLA --printer-name "A1 #2" --apply
    python scripts/shop_seed.py --projects p_a p_b --apply       # listings from these projects only
    python scripts/shop_seed.py --public --apply                 # listings visible in the catalog (see below)
    python scripts/shop_seed.py --projects p_wheel --title-en "Dishwasher rack wheel, 25 mm, generic" \
        --title-ru "Колёсико корзины посудомойки, 25 мм, универсальное" --brand Bosch --public --apply

Which projects: without --projects, the newest household/copy projects owned by the farm's operators (shop_operator.py;
ship_runs.py import --user <operator> puts the demo runs there). Never anyone else's: a visitor who opened an example
owns a household project too, and it is not the farm's to put in a catalog. Someone else's project goes in by its id.

Names: each card has an English and a Russian name, so the catalog follows the UI's language. They come from the
intake of the order the part was born from, as the server names a shared part (shop.routes._listing_titles): the open
model's catalog titles, else the customer's own words in their language, else Muse Spark's English name; then the
project's own title fills the side of its script (Cyrillic -> Russian). --title-en / --title-ru win. A side nothing
names shows the other name, so an English card stays English in the Russian UI until it gets a Russian name.
A generic part (the example rack wheel) gets a name of its own and none of a real order's models or part numbers:
otherwise the catalog shows two cards of the same name, and a search for that order's model ('sms46') finds the
seeded one instead of the part a customer's order made and QC passed.

Listings: the catalog's rule is that a part is public only once a print of it passed QC. Seeded listings have no such
print, so they are private (their owners see them under "Your parts") unless --public is given; then they show in the
catalog marked verified.seeded = true with no QC badge, which is honest about what was checked: the build checks and,
where it ran, the independent critic. An A1 mini (180 mm bed) needs a smaller plate: pass --preset bambu-lab-a1-mini-0-4-nozzle.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR / "scripts"))

from judge_link import connect, default_db, env_setting, has_table, new_id  # noqa: E402
from shop_operator import FARM, ensure_tables, farm  # noqa: E402

PRESET = "bambu-lab-a1-0-4-nozzle"  # OrcaSlicer: BBL/machine/Bambu Lab A1 0.4 nozzle.json
PACKS = ("household", "copy")  # functional parts first; figurines are not spare parts


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")  # as printing/presets.py names presets


def check_preset(preset: str) -> None:
    root = Path(env_setting("FW_ORCA_PROFILES") or r"C:\Program Files\OrcaSlicer\resources\profiles")
    machines = list(root.glob("*/machine/*.json")) if root.exists() else []
    if machines and preset not in {slug(p.stem) for p in machines}:
        sys.exit(f"no OrcaSlicer machine preset {preset!r} under {root}")
    if not machines:
        print(f"note: no OrcaSlicer profiles at {root}; keeping the preset name {preset!r} unchecked")


def printer(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    if has_table(conn, "shop_printers") and conn.execute("SELECT 1 FROM shop_printers WHERE name = ?", (args.printer_name,)).fetchone():
        print(f"printer {args.printer_name!r} is there already")
        return
    if args.apply:
        conn.execute("INSERT INTO shop_printers (id, name, preset_id, fingerprint, material, color, state, created_at) VALUES (?, ?, ?, '{}', ?, ?, 'idle', ?)",
                     (new_id("sp_"), args.printer_name, args.preset, args.material.upper(), args.color, time.time()))
    print(f"{'added' if args.apply else 'would add'} printer {args.printer_name!r}: {args.preset}, {args.material.upper()}"
          + (f", {args.color}" if args.color else "") + " (calibrate it: /ops -> printer -> fingerprint photo of the coupon)")


CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def _cap(x: str) -> str:
    x = (x or "").strip()
    return x[:1].upper() + x[1:]


def titles(conn: sqlite3.Connection, p: sqlite3.Row, args: argparse.Namespace) -> tuple[str, str]:
    """The card's (English, Russian) names; '' where nothing names that side (see the docstring)."""
    en = ru = ""
    row = conn.execute("SELECT intake FROM shop_orders WHERE project_id = ? AND json_extract(intake, '$.request.kind') = 'photo' "
                       "ORDER BY created_at LIMIT 1", (p["id"],)).fetchone() if has_table(conn, "shop_orders") else None
    data = json.loads(row["intake"] or "{}") if row else {}
    part, cls = data.get("part") or {}, data.get("classify") or {}
    if cls.get("error") or (data.get("review") or {}).get("code") == "safety_disagreement":
        cls = {}  # the two models disagreed about the part: Spark's reading names it
    lang = str(data.get("language") or "")[:2].lower()
    own = part.get("name_user") or ""
    en = cls.get("title_en") or (own if lang == "en" else "") or part.get("name_en") or ""
    ru = cls.get("title_ru") or (own if lang == "ru" else "") or ""
    title = (p["title"] or "").strip()
    if CYRILLIC.search(title):
        ru = ru or title
    else:
        en = en or title
    return _cap(getattr(args, "title_en", None) or en)[:120], _cap(getattr(args, "title_ru", None) or ru)[:120]


def _fts(conn: sqlite3.Connection, lid: str, names: list[str], brand: str, models: list[str], numbers: list[str]) -> None:
    # as store._fts_text: its name in either language finds it
    conn.execute("DELETE FROM shop_listings_fts WHERE id = ?", (lid,))
    conn.execute("INSERT INTO shop_listings_fts (id, title, brand, models, part_numbers) VALUES (?, ?, ?, ?, ?)",
                 (lid, " ".join(dict.fromkeys(n for n in names if n)), brand, " ".join(models), " ".join(numbers)))


def _named(args: argparse.Namespace) -> bool:
    return any(getattr(args, k, None) is not None for k in ("title_en", "title_ru", "brand", "models", "part_numbers"))


def _critic(conn: sqlite3.Connection, pid: str, version: int) -> str | None:
    for m in conn.execute("SELECT data FROM messages WHERE project_id = ? AND role = 'agent' ORDER BY created_at DESC LIMIT 30", (pid,)):
        d = json.loads(m["data"] or "{}")
        c = d.get("critic") or {}
        # as shop.routes._critic: the critic's own version first, and an unanswered review is no verdict
        if c and c.get("version", d.get("version")) == version:
            return None if c.get("reviewer") == "unavailable" else c.get("verdict")
    return None


def candidates(conn: sqlite3.Connection, args: argparse.Namespace) -> list[sqlite3.Row]:
    if args.projects:
        marks = ",".join("?" * len(args.projects))
        return conn.execute(f"SELECT * FROM projects WHERE id IN ({marks}) AND version > 0", args.projects).fetchall()
    if not (has_table(conn, "shop_members") and has_table(conn, "shop_orgs")):
        return []
    # the farm's own projects only (its operators'), never the newest projects of any visitor
    marks = ",".join("?" * len(PACKS))
    return conn.execute(f"SELECT * FROM projects WHERE version > 0 AND replay_of IS NULL AND pack IN ({marks}) AND user_id IN "
                        "(SELECT m.user_id FROM shop_members m JOIN shop_orgs o ON o.id = m.org_id WHERE o.kind = 'farm' AND o.name = ?) "
                        "ORDER BY updated_at DESC LIMIT 200", (*PACKS, args.farm)).fetchall()


def listings(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    added = 0
    named = _named(args)
    brand = (getattr(args, "brand", None) or "")[:60]
    models = [m[:60] for m in getattr(args, "models", None) or []][:10]
    numbers = [n[:60] for n in getattr(args, "part_numbers", None) or []][:10]
    for p in candidates(conn, args):
        if added >= args.limit:
            break
        prog = conn.execute("SELECT checks FROM programs WHERE project_id = ? AND version = ?", (p["id"], p["version"])).fetchone()
        checks = json.loads((prog or {"checks": None})["checks"] or "{}")
        if not checks.get("ok"):
            print(f"  skip {p['id']} {p['title']!r}: version {p['version']} did not pass the build checks")
            continue
        en, ru = titles(conn, p, args)
        old = conn.execute("SELECT * FROM shop_listings WHERE owner_id = ? AND project_id = ?", (p["user_id"], p["id"])).fetchone() \
            if has_table(conn, "shop_listings") else None
        if old:
            added += 1  # counts toward --limit, so a second run adds nothing
            publish = args.public and not old["public"]
            if not named and not publish:
                print(f"  {p['id']} {p['title']!r}: listed already" + ("" if old["public"] else " (private: --public shows it in the catalog)"))
                continue
            # the names given for this one project: they replace the card's (what is not given stays)
            given = {"title_en": en, "title_ru": ru, "brand": brand, "models": json.dumps(models), "part_numbers": json.dumps(numbers)}
            fields = {k: v for k, v in given.items() if getattr(args, k, None) is not None}
            if publish:
                # into the catalog as a new seeded one is: marked seeded unless a print of it passed QC
                verified = json.loads(old["verified"] or "{}")
                fields.update(public=1, verified=json.dumps(verified if verified.get("qc_pass") else {**verified, "seeded": True}))
            if args.apply:
                conn.execute(f"UPDATE shop_listings SET {', '.join(f'{k} = ?' for k in fields)}, updated_at = ? WHERE id = ?",
                             (*fields.values(), time.time(), old["id"]))
                row = conn.execute("SELECT * FROM shop_listings WHERE id = ?", (old["id"],)).fetchone()
                _fts(conn, old["id"], [row["title"], row["title_en"], row["title_ru"]], row["brand"], json.loads(row["models"] or "[]"),
                     json.loads(row["part_numbers"] or "[]"))
            print(f"  {'updated' if args.apply else 'would update'} {old['id']} {p['title']!r}: "
                  + ", ".join("now public" if k == "public" else f"{k} {v!r}" for k, v in fields.items() if k != "verified"))
            continue
        verified = {"printable": True, "critic": _critic(conn, p["id"], p["version"]), "qc_pass": False, "qc_max_mm": None, "seeded": True}
        if args.apply:
            lid, t = new_id("sl_"), time.time()
            conn.execute("INSERT INTO shop_listings (id, project_id, version, owner_id, title, title_en, title_ru, brand, models, part_numbers, category, "
                         "material, cover, verified, public, orders, flagged, reports, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, '[]', ?, ?)",
                         (lid, p["id"], p["version"], p["user_id"], p["title"], en, ru, brand, json.dumps(models), json.dumps(numbers),
                          p["pack"] or "", args.material.upper(), p["cover"], json.dumps(verified), int(args.public), t, t))
            _fts(conn, lid, [p["title"], en, ru], brand, models, numbers)
        stats = checks.get("stats") or {}
        print(f"  {'listed' if args.apply else 'would list'} {p['id']} {p['title']!r} v{p['version']} ({p['pack']}, ~{stats.get('estGrams', 0):.0f} g, "
              f"critic {verified['critic'] or '-'}), {'public' if args.public else 'private'}; en {en or '-'!r}, ru {ru or '-'!r}"
              + (f", fits {' '.join(x for x in (brand, ', '.join(models)) if x)}" if brand or models else "")
              + (f", № {', '.join(numbers)}" if numbers else ""))
        added += 1
    if not added:
        print("  no project to list (none with a version that passed the build checks)" if args.projects else
              f"  no project to list: no operator of the farm {args.farm!r} owns a household/copy project that passed the build checks.\n"
              "  Make an operator (shop_operator.py), import the demo runs as theirs (ship_runs.py import --user <id>), or pass --projects")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None, help="formwright.db (default: FW_DATA_DIR or data/ in the repo)")
    ap.add_argument("--farm", default=FARM, help="the farm organisation's name")
    ap.add_argument("--printer-name", default="Bambu Lab A1 · Axo #1")
    ap.add_argument("--preset", default=PRESET, help="OrcaSlicer machine preset id (slug of its name)")
    ap.add_argument("--material", default="PETG", help="filament loaded now (PETG: the dishwasher and fridge parts)")
    ap.add_argument("--color", default=None)
    ap.add_argument("--projects", nargs="*", default=None,
                    help="list these projects, whoever owns them (default: recent household/copy projects of the farm's operators)")
    ap.add_argument("--limit", type=int, default=4, help="at most this many listings")
    ap.add_argument("--public", action="store_true", help="show the listings in the catalog (marked seeded, no QC badge)")
    # what one real spare part's card says (with exactly one --projects): its two names and what it fits
    ap.add_argument("--title-en", default=None, help="the card's English name (with one --projects)")
    ap.add_argument("--title-ru", default=None, help="the card's Russian name (with one --projects)")
    ap.add_argument("--brand", default=None, help="the appliance brand it fits, e.g. Bosch (with one --projects; never printed on the part)")
    ap.add_argument("--models", nargs="*", default=None, help="appliance models it fits, e.g. SMS46GI01E (with one --projects)")
    ap.add_argument("--part-numbers", nargs="*", default=None, help="OEM part numbers it replaces (with one --projects)")
    ap.add_argument("--no-listings", action="store_true", help="only the farm and the printer")
    ap.add_argument("--apply", action="store_true", help="write (without it nothing is written)")
    args = ap.parse_args()
    if _named(args) and len(args.projects or []) != 1:
        ap.error("--title-en, --title-ru, --brand, --models and --part-numbers name one part: give exactly one --projects")

    check_preset(args.preset)
    path = args.db or default_db()
    conn = connect(path, write=args.apply)
    print(f"database: {path}\n")
    with conn:
        if args.apply:
            ensure_tables(conn)
        org = farm(conn, args.farm, args.apply)
        if org:
            print(f"farm {args.farm!r}: {org}")
        printer(conn, args)
        if not args.no_listings:
            print("listings:")
            listings(conn, args)
    conn.close()
    if not args.apply:
        print("\nadd --apply to write")
    else:
        print("\nan operator for the board: python scripts/shop_operator.py --apply")


if __name__ == "__main__":
    main()
