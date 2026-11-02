"""scripts/shop_seed.py: without --projects it lists only the farm's own projects (its operators'), never the newest
household project of whoever visited; --projects still takes any project by id; each card gets an English and a
Russian name, and one real part can be named by hand with what it fits. Scratch databases only."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3

import pytest

from formwright import db as dbmod
from formwright.config import SERVER_DIR, settings
from formwright.shop import store


def _seed():
    spec = importlib.util.spec_from_file_location("shop_seed", SERVER_DIR / "scripts" / "shop_seed.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _args(**kw) -> argparse.Namespace:
    return argparse.Namespace(**{"farm": "Axo", "projects": None, "limit": 4, "public": True, "apply": True, "material": "PETG", **kw})


async def _db(tmp_path, monkeypatch, *, farm: bool = True):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir(exist_ok=True)
    await dbmod.close_db()
    db = await dbmod.get_db()
    await store.ensure(db)
    t = dbmod.now()
    for uid in ("u_op", "u_visitor"):
        await db.insert("users", {"id": uid, "tier": "anon", "created_at": t})
    # the farm's demo run, and a visitor's opened example (newer, same pack): only the first is the farm's to list
    for i, (pid, uid, title) in enumerate((("p_farm", "u_op", "Basket wheel"), ("p_visit", "u_visitor", "Shelf bag hook"))):
        await db.insert("projects", {"id": pid, "user_id": uid, "title": title, "pack": "household", "version": 1, "created_at": t + i,
                                     "updated_at": t + i})
        await db.insert("programs", {"project_id": pid, "version": 1, "source": "return lib.box(10,10,10)", "params": {}, "inputs": {},
                                     "checks": {"ok": True, "stats": {"estGrams": 3.0}}, "author": "agent", "created_at": t})
    if farm:
        await db.insert("shop_orgs", {"id": "org_axo", "name": "Axo", "kind": "farm", "tier": "farm", "created_at": t})
        await db.insert("shop_members", {"org_id": "org_axo", "user_id": "u_op", "role": "operator"})
    await dbmod.close_db()
    conn = sqlite3.connect(tmp_path / "formwright.db")
    conn.row_factory = sqlite3.Row
    return conn


async def test_default_lists_only_the_farms_projects(tmp_path, monkeypatch, capsys):
    seed = _seed()
    conn = await _db(tmp_path, monkeypatch)
    try:
        assert [p["id"] for p in seed.candidates(conn, _args())] == ["p_farm"]
        seed.listings(conn, _args())
        rows = conn.execute("SELECT project_id, owner_id, title, public, title_en, title_ru FROM shop_listings").fetchall()
        # an English title names the English card; nothing names the Russian one yet, so it shows the English name
        assert [tuple(r) for r in rows] == [("p_farm", "u_op", "Basket wheel", 1, "Basket wheel", "")]
        assert "Shelf bag hook" not in capsys.readouterr().out
        # by id, anyone's project goes in
        assert [p["id"] for p in seed.candidates(conn, _args(projects=["p_visit"]))] == ["p_visit"]
        # another farm's name: none of these operators
        assert seed.candidates(conn, _args(farm="Other farm")) == []
    finally:
        conn.close()


async def test_no_farm_yet_lists_nothing_and_says_how(tmp_path, monkeypatch, capsys):
    seed = _seed()
    conn = await _db(tmp_path, monkeypatch, farm=False)
    try:
        seed.listings(conn, _args(apply=False))
        out = capsys.readouterr().out
        assert "no operator of the farm 'Axo'" in out and "--projects" in out and "would list" not in out
        # a database the shop never ran on (no shop tables at all)
        conn.execute("DROP TABLE shop_members")
        assert seed.candidates(conn, _args()) == []
    finally:
        conn.close()


async def test_cards_get_both_names_and_what_they_fit(tmp_path, monkeypatch, capsys):
    """The names come from the intake of the order the part was born from (the open model's catalog titles), else the
    project's title on the side of its script; --title-en/--title-ru/--brand/--models/--part-numbers name one part, also
    one listed before. The catalog shows a card in the UI's language whenever a name in it exists."""
    from formwright.shop.routes import card_titles, listing_out

    seed = _seed()
    conn = await _db(tmp_path, monkeypatch)
    try:
        t = dbmod.now()
        conn.execute("INSERT INTO projects (id, user_id, title, pack, version, created_at, updated_at) VALUES ('p_ru', 'u_op', 'Настенный держатель', 'household', 1, ?, ?)", (t, t))
        conn.execute("INSERT INTO programs (project_id, version, source, params, inputs, checks, author, created_at) "
                     "VALUES ('p_ru', 1, 'x', '{}', '{}', '{\"ok\": true}', 'agent', ?)", (t,))
        intake = {"request": {"kind": "photo"}, "language": "ru", "part": {"name_user": "колёсико", "name_en": "dishwasher lower basket wheel"},
                  "classify": {"title_en": "Dishwasher lower basket wheel", "title_ru": "Колёсико нижней корзины посудомойки", "safety_critical": False}}
        conn.execute("INSERT INTO shop_orders (id, ref, user_id, project_id, status, intake, created_at, updated_at) "
                     "VALUES ('so_1', 'FW-1001', 'u_op', 'p_farm', 'delivered', ?, ?, ?)", (json.dumps(intake, ensure_ascii=False), t, t))
        seed.listings(conn, _args(limit=5))
        rows = {r["project_id"]: r for r in conn.execute("SELECT * FROM shop_listings")}
        # from the intake of the order the wheel was born from; the Russian project's own title names its Russian side
        assert (rows["p_farm"]["title_en"], rows["p_farm"]["title_ru"]) == ("Dishwasher lower basket wheel", "Колёсико нижней корзины посудомойки")
        assert (rows["p_ru"]["title_en"], rows["p_ru"]["title_ru"]) == ("", "Настенный держатель")
        # one part named by hand, though it is listed already: the names and what it fits change, the rest stays
        named = _args(projects=["p_ru"], title_en="Wall phone holder", title_ru=None, brand="", models=None, part_numbers=["PH-78"], limit=5)
        seed.listings(conn, named)
        row = conn.execute("SELECT * FROM shop_listings WHERE project_id = 'p_ru'").fetchone()
        assert (row["title_en"], row["title_ru"], row["part_numbers"], row["models"]) == ("Wall phone holder", "Настенный держатель", '["PH-78"]', "[]")
        assert conn.execute("SELECT COUNT(*) FROM shop_listings").fetchone()[0] == 2  # updated, not added
        found = conn.execute("SELECT id FROM shop_listings_fts WHERE shop_listings_fts MATCH ?", ('"phone"*',)).fetchall()
        assert [r[0] for r in found] == [row["id"]]
        # a new card with every flag
        conn.execute("INSERT INTO projects (id, user_id, title, pack, version, created_at, updated_at) VALUES ('p_knob', 'u_op', 'Knob', 'household', 1, ?, ?)", (t, t))
        conn.execute("INSERT INTO programs (project_id, version, source, params, inputs, checks, author, created_at) "
                     "VALUES ('p_knob', 1, 'x', '{}', '{}', '{\"ok\": true}', 'agent', ?)", (t,))
        seed.listings(conn, _args(projects=["p_knob"], title_en=None, title_ru="Ручка", brand="Indesit", models=["IWSC 5105"], part_numbers=None))
        knob = conn.execute("SELECT * FROM shop_listings WHERE project_id = 'p_knob'").fetchone()
        assert (knob["title_en"], knob["title_ru"], knob["brand"], knob["models"]) == ("Knob", "Ручка", "Indesit", '["IWSC 5105"]')
        assert "fits Indesit IWSC 5105" in capsys.readouterr().out
        # the catalog card: a name in the UI's language when one exists, the other one otherwise
        assert card_titles({"title": "Настенный держатель", "title_en": "", "title_ru": ""}) == ("Настенный держатель", "Настенный держатель")
        assert card_titles({"title": "Настенный держатель", "title_en": "Wall phone holder", "title_ru": ""}) == ("Wall phone holder", "Настенный держатель")
        assert card_titles({"title": "Колесо", "title_en": "", "title_ru": "Wheel"}) == ("Wheel", "Колесо")  # a name on the wrong side
        li = {**dict(knob), "models": ["IWSC 5105"], "part_numbers": [], "verified": {}}
        assert (listing_out(li, None)["title_en"], listing_out(li, None)["compatible_with"]) == ("Knob", "Indesit IWSC 5105")
    finally:
        conn.close()


def test_naming_flags_need_one_project(monkeypatch, capsys):
    seed = _seed()
    monkeypatch.setattr("sys.argv", ["shop_seed.py", "--title-en", "Wheel"])
    with pytest.raises(SystemExit):
        seed.main()
    assert "exactly one --projects" in capsys.readouterr().err


async def test_public_also_publishes_a_card_listed_before(tmp_path, monkeypatch, capsys):
    """The docstring's own wheel example on a part seeded privately before: --public puts it in the catalog too."""
    seed = _seed()
    conn = await _db(tmp_path, monkeypatch)
    try:
        seed.listings(conn, _args(projects=["p_farm"], public=False))
        assert conn.execute("SELECT public FROM shop_listings WHERE project_id = 'p_farm'").fetchone()[0] == 0
        seed.listings(conn, _args(projects=["p_farm"], public=False))
        assert "listed already (private: --public shows it in the catalog)" in capsys.readouterr().out
        named = _args(projects=["p_farm"], title_en="Dishwasher lower basket wheel", title_ru=None, brand="Bosch", models=["SMS46GI01E"],
                      part_numbers=["00611475"], public=True)
        seed.listings(conn, named)
        row = conn.execute("SELECT * FROM shop_listings WHERE project_id = 'p_farm'").fetchone()
        assert row["public"] == 1 and json.loads(row["verified"])["seeded"] is True and row["brand"] == "Bosch"
        assert "now public" in capsys.readouterr().out
        assert conn.execute("SELECT COUNT(*) FROM shop_listings").fetchone()[0] == 1
    finally:
        conn.close()
