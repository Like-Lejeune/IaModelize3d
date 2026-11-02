"""The order as a person reads it: journal notes as codes the web says in RU/EN, no exception text for customers,
titles in both languages, whether the part is shared, the owner-as-customer answer, and the Axo export of a pinned version."""
from __future__ import annotations

import base64

import httpx
import pytest

from formwright.db import new_id, now
from formwright.shop import notes, routes, store

from shop_fakes import add_program, finish_design, setup, teardown, wait_for


@pytest.fixture
async def env(tmp_path, monkeypatch):
    e = await setup(tmp_path, monkeypatch)
    yield e
    await teardown(e)


def H(user: str) -> dict[str, str]:
    return {"x-user": user}


async def _project(env, user: str, title: str = "Shelf bracket") -> str:
    pid = new_id("p_")
    if not await env.db.one("SELECT id FROM users WHERE id = ?", user):
        await env.db.insert("users", {"id": user, "tier": "anon", "created_at": now()})
    await env.db.insert("projects", {"id": pid, "user_id": user, "title": title, "pack": "household", "created_at": now(), "updated_at": now()})
    return pid


async def test_journal_comes_as_codes_and_titles_in_both_languages(env):
    c = env.c
    o = (await c.post("/api/shop/requests", data={"text": "Bosch dishwasher wheel"}, headers=H("u_ann"))).json()
    await wait_for(env, o["id"], "designing")
    await finish_design(env, o["id"])
    o = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_ann"))).json()
    codes = [(t["status"], t["code"]) for t in o["timeline"]]
    assert codes == [("requested", "created"), ("requested", "intake_read"), ("designing", "designing"), ("quoted", "quoted")]
    read = o["timeline"][1]["params"]
    assert read["model"].startswith("muse-spark-1.3") and read["title_ru"].startswith("Колёсико нижней") and read["title_en"].startswith("Dishwasher")
    quoted = o["timeline"][3]["params"]
    assert quoted["by"] == "orca" and quoted["total"] == o["quote"]["total"] and quoted["total_usd"] == o["quote"]["usd"]["total"]
    assert o["timeline"][3]["note"].endswith("by OrcaSlicer")  # the English line stays for the log
    # the UI follows its own language: the customer's own words in theirs, the open model's catalog title in the other
    assert o["title_en"] == "Dishwasher lower basket wheel with axle · BOSCH SMS46GI01E/09"
    assert o["title_ru"] == o["title"] == "Колёсико нижней корзины · BOSCH SMS46GI01E/09"
    assert o["own_listing"] is None

    await c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_ann"))
    pr = (await c.post("/api/shop/ops/printers", json={"name": "A1 #1", "material": "PETG"}, headers=H("u_op"))).json()
    await c.post(f"/api/shop/orders/{o['id']}/assign", json={"printer_id": pr["id"]}, headers=H("u_op"))
    await c.post(f"/api/shop/orders/{o['id']}/printed", headers=H("u_op"))
    env.hooks.qc_results = [{"pass": False, "error": "the measuring model is unavailable (APIConnectionError); try the photo again",
                             "error_code": "model_unavailable"}, {"pass": True, "max_mm": 0.31, "tolerance_mm": 0.6}]
    await c.post(f"/api/shop/orders/{o['id']}/qc", files={"file": ("qc.jpg", b"x", "image/jpeg")}, headers=H("u_op"))
    seen = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_ann"))).json()
    assert "APIConnectionError" not in str(seen)  # the customer never reads an exception
    assert seen["qc"]["error_code"] == "model_unavailable" and seen["qc"]["error"] == routes.QC_ERRORS["model_unavailable"]
    assert seen["timeline"][-1]["code"] == "qc_unmeasured" and seen["timeline"][-1]["note"] == "QC photo not measured"
    farm = next(x for x in (await c.get("/api/shop/ops/queue", headers=H("u_op"))).json()["orders"] if x["id"] == o["id"])
    assert "APIConnectionError" in farm["qc"]["error"]  # the farm sees why
    await c.post(f"/api/shop/orders/{o['id']}/qc", files={"file": ("qc.jpg", b"x", "image/jpeg")}, headers=H("u_op"))
    await c.post(f"/api/shop/orders/{o['id']}/ship", json={"carrier": "Kazpost", "tracking": "KZ123"}, headers=H("u_op"))
    d = (await c.post(f"/api/shop/orders/{o['id']}/delivered", headers=H("u_ann"))).json()
    assert d["own_listing"] == {"id": d["own_listing"]["id"], "public": False}  # "Your parts", not in the catalog yet
    await c.post("/api/shop/listings", json={"project_id": o["project_id"]}, headers=H("u_ann"))
    o = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_ann"))).json()
    assert o["own_listing"]["public"] is True
    tail = [(t["code"], t["params"]) for t in o["timeline"][-7:]]
    assert tail[0] == ("paid_test", {}) and tail[1][0] == "assigned" and tail[1][1]["printer"] == "A1 #1"
    assert tail[2][0] == "printed" and tail[4] == ("qc_pass", {"max": 0.31, "tol": 0.6})
    assert tail[5] == ("shipped", {"carrier": "Kazpost", "tracking": "KZ123"}) and o["timeline"][-1]["code"] is None  # delivered: no note


async def test_customers_get_no_raw_errors(env):
    c = env.c

    async def broken(user, text, photos):
        raise ConnectionError("APIConnectionError: Connection error.")

    env.hooks.intake = broken
    o = (await c.post("/api/shop/requests", data={"text": "a fridge clip"}, headers=H("u_bea"))).json()
    await wait_for(env, o["id"], "requested", idle=True)
    seen = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_bea"))).json()
    assert seen["intake"]["review"]["code"] == "intake_failed" and seen["intake"]["error"] == "not read"
    # nothing named the part: the RU UI reads 'Запчасть', not the English fallback (the list and the farm's board alike)
    assert (seen["title_en"], seen["title_ru"]) == ("Spare part", "Запчасть")
    listed = next(x for x in (await c.get("/api/shop/orders", headers=H("u_bea"))).json() if x["id"] == o["id"])
    assert listed["title_ru"] == "Запчасть"
    assert [t["code"] for t in seen["timeline"]] == ["created", "intake_unread", "held"]
    assert seen["timeline"][1]["note"] == "not read" and seen["timeline"][1]["params"] == {}
    assert seen["timeline"][2]["params"]["review"] == "intake_failed"
    assert "Connection error" not in str(seen)
    farm = (await c.get("/api/shop/ops/queue", headers=H("u_op"))).json()["upstream"][0]
    assert "Connection error" in farm["intake"]["error"]
    del env.hooks.intake  # the recorded answers again

    # a slicer that fails: the order is paused with a code; its exception is the farm's to read
    pid = await _project(env, "u_bea")
    await add_program(env.db, pid)
    env.hooks.slice_error = RuntimeError("SliceError: orca-slicer exited 3")
    o = (await c.post("/api/shop/requests", data={"project_id": pid}, headers=H("u_bea"))).json()
    await wait_for(env, o["id"], "requested", idle=True)
    seen = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_bea"))).json()
    assert seen["problem"]["code"] == "slice_failed" and "detail" not in seen["problem"] and "orca-slicer" not in str(seen)
    entry = next(t for t in seen["timeline"] if t["code"] == "problem")
    assert entry["params"] == {"code": "slice_failed"} and entry["note"] == "slice_failed"
    farm = next(x for x in (await c.get("/api/shop/ops/queue", headers=H("u_op"))).json()["upstream"] if x["id"] == o["id"])
    assert "orca-slicer exited 3" in farm["problem"]["detail"]


async def test_skipped_files_come_as_codes(env):
    o = await store.create_order(env.db, user_id="u_cy", project_id="p_cy", intake={"request": {"kind": "photo", "skipped": [
        "voice note not transcribed: APIConnectionError: x", "scan.heic: cannot decode the image", "clip.mp4: a video is not read here; send photos",
        {"code": "unreadable", "file": "a.jpg", "error": "ValueError: empty file"}]}})
    seen = await routes.present(env.db, o, "customer")
    assert seen["intake"]["request"]["skipped"] == [{"code": "voice_untranscribed", "file": "voice"}, {"code": "unreadable", "file": "scan.heic"},
                                                     {"code": "not_photo", "file": "clip.mp4", "kind": "video"}, {"code": "unreadable", "file": "a.jpg"}]
    farm = await routes.present(env.db, o, "operator")
    assert farm["intake"]["request"]["skipped"][1]["error"] == "cannot decode the image"


async def test_an_operators_own_order_answers_as_the_customers(env):
    c = env.c
    pid = await _project(env, "u_op", "Founder's bracket")
    await add_program(env.db, pid)
    o = (await c.post("/api/shop/requests", data={"project_id": pid}, headers=H("u_op"))).json()
    await wait_for(env, o["id"], "quoted", idle=True)
    again = (await c.post(f"/api/shop/orders/{o['id']}/quote", json={"quantity": 2}, headers=H("u_op"))).json()
    assert again["actor"] == "customer" and "paid" in again["next"] and "cost" not in again["quote"]
    board = (await c.post(f"/api/shop/orders/{o['id']}/quote", params={"view": "ops"}, json={}, headers=H("u_op"))).json()
    assert board["actor"] == "operator" and "cost" in board["quote"]  # from the farm's board it stays the farm's card
    assert (await c.post(f"/api/shop/orders/{o['id']}/cancel", headers=H("u_op"))).json()["actor"] == "customer"
    # someone else's order stays the farm's
    other = await _project(env, "u_dee")
    await add_program(env.db, other)
    theirs = (await c.post("/api/shop/requests", data={"project_id": other}, headers=H("u_dee"))).json()
    await wait_for(env, theirs["id"], "quoted", idle=True)
    assert (await c.post(f"/api/shop/orders/{theirs['id']}/cancel", headers=H("u_op"))).json()["actor"] == "operator"


def test_titles_follow_the_language_and_the_safety_model():
    from formwright.shop.intake import titles

    from shop_fakes import answer

    en, ru = titles(answer("voice_wheel_plate_a4"), "Spare part")
    assert en.startswith("Dishwasher lower basket wheel with axle") and ru.startswith("Колёсико нижней корзины")
    # the open model calls the part a gas knob: the two disagree, so Spark's reading names it in both languages
    en, ru = titles(answer("gas_knob_spark_ok_open_unsafe"), "Spare part")
    assert "gas" not in en.lower() and "газ" not in ru.lower() and "wheel" in en.lower()
    # nothing named it: the unnamed part reads in each language; any other fallback (an appliance, a part number) stays
    assert titles({}, "Spare part") == titles({}, "Запчасть") == ("Spare part", "Запчасть")
    assert titles({"error": "not read"}, "Bosch SMS46") == ("Bosch SMS46", "Bosch SMS46")


def test_old_english_notes_read_back_as_codes():
    cases = {
        ("read by muse-spark-1.3: Колёсико · BOSCH", "requested", "requested", "system"): ("intake_read", {"model": "muse-spark-1.3", "title": "Колёсико · BOSCH"}),
        ("not read: APIConnectionError: Connection error.", "requested", "requested", "system"): ("intake_unread", {"error": "APIConnectionError: Connection error."}),
        ("held for the farm operator: Gas valve knob", "requested", "requested", "system"): ("held", {"why": "Gas valve knob"}),
        ("approved by the operator", "requested", "requested", "operator"): ("approved", {}),
        ("a clip, not gas", "requested", "requested", "operator"): ("approved", {"note": "a clip, not gas"}),
        ("3.1 g, 20.6 min each x2: 9,980 KZT ($19.19), by OrcaSlicer", "quoted", "designing", "system"):
            ("quoted", {"grams": 3.1, "minutes": 20.6, "quantity": 2, "total": 9980.0, "total_usd": 19.19, "by": "orca"}),
        ("quoted again: 3.1 g, 20.6 min each x4: 15,960 KZT ($30.69), by the operator", "quoted", "quoted", "operator"):
            ("requoted", {"grams": 3.1, "minutes": 20.6, "quantity": 4, "total": 15960.0, "total_usd": 30.69, "by": "operator"}),
        ("test payment", "paid", "quoted", "customer"): ("paid_test", {}),
        ("on Bambu Lab A1 · Axo #1", "printing", "paid", "operator"): ("assigned", {"printer": "Bambu Lab A1 · Axo #1"}),
        ("QC passed: max 0.29 mm within ±0.6 mm", "qc", "qc", "system"): ("qc_pass", {"max": "0.29", "tol": "0.6"}),
        ("slice_failed: SliceError: exit 3", "requested", "requested", "system"): ("problem", {"code": "slice_failed", "detail": "SliceError: exit 3"}),
        ("Kazpost KZ123", "shipped", "qc", "operator"): ("shipped", {"carrier": "Kazpost KZ123"}),
        ("A gas knob: a print can leak gas.", "refused", "requested", "system"): ("refused_safety", {"reason": "A gas knob: a print can leak gas."}),
        ("not a spare part", "refused", "requested", "operator"): ("refused_operator", {"note": "not a spare part"}),
    }
    for (note, to, frm, actor), want in cases.items():
        assert notes.legacy(note, to, frm, actor) == want, note
    assert notes.legacy("on second thought", "requested", "requested", "system") is None
    old = {"too": "requested", "frm": "requested", "actor": "system", "note": "not read: APIConnectionError: boom", "ts": 1.0, "data": {}}
    assert notes.entry(old, operator=False)["note"] == "not read" and notes.entry(old, operator=False)["params"] == {}
    assert notes.entry(old, operator=True)["params"]["error"] == "APIConnectionError: boom"
    # every code has its English line, with and without its parameters
    for code in set(notes.EN) - {"shipped"}:  # a pickup ships with no carrier and no line, as before
        assert notes.text(code, {})


async def test_axo_export_takes_the_pinned_version(env, monkeypatch):
    from formwright.config import settings
    from formwright.integrations import axo
    from formwright.models import OrderRequest

    pid = await _project(env, "u_eve", "Wheel")
    await add_program(env.db, pid, 1)
    await env.db.insert("programs", {"project_id": pid, "version": 2, "source": "return lib.box(20,20,20)", "params": {}, "inputs": {},
                                     "checks": {"ok": True, "stats": {}}, "author": "agent", "created_at": now()})
    exported: list[str] = []

    class FakeGeom:
        async def export(self, source, params, fmt, **kw):
            exported.append(source)
            return {"data": base64.b64encode(b"3mf").decode()}

    sent: list[dict] = []

    async def fake_post(self, url, **kw):
        sent.append(kw)
        return httpx.Response(200, json={"order_id": "AXO-1", "checkout_url": "https://axo.kz/pay/1", "price_kzt": 5990})

    monkeypatch.setattr(axo, "geom", lambda: FakeGeom())
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(settings(), "axo_api_url", "https://axo.example/api")
    project = await env.db.one("SELECT * FROM projects WHERE id = ?", pid)
    r = await axo.create_order({"id": "u_eve"}, project, OrderRequest(), version=1)
    assert r["status"] == "created" and exported == ["return lib.box(10,10,10)"]
    assert f'"external_id": "{pid}:v1"' in sent[0]["files"]["order"][1]
    await axo.create_order({"id": "u_eve"}, project, OrderRequest())
    assert exported[-1] == "return lib.box(20,20,20)"  # no version: the newest, as before
    assert (await axo.create_order({"id": "u_eve"}, project, OrderRequest(), version=7))["status"] == "error"


async def test_catalog_cards_carry_both_titles(env):
    c = env.c
    o = (await c.post("/api/shop/requests", data={"text": "Bosch dishwasher wheel"}, headers=H("u_ann"))).json()
    await wait_for(env, o["id"], "designing")
    await finish_design(env, o["id"])
    await store.patch(env.db, o["id"], {"qc": {"pass": True, "max_mm": 0.3, "tolerance_mm": 0.6}})
    li = (await c.post("/api/shop/listings", json={"project_id": o["project_id"]}, headers=H("u_ann"))).json()
    # the open model's catalog title in each language (the customer wrote Russian); what it fits stays apart
    assert li["title"] == li["title_ru"] == "Колёсико с осью для нижней корзины посудомойки"
    assert li["title_en"] == "Dishwasher lower basket wheel with axle" and li["compatible_with"] == "BOSCH SMS46GI01E/09"
    assert [x["id"] for x in (await c.get("/api/shop/listings", params={"q": "dishwasher axle"})).json()] == [li["id"]]  # either name finds it
    # the owner's own title names it in its language; the other keeps the catalog title
    li = (await c.post("/api/shop/listings", json={"project_id": o["project_id"], "title": "lower basket wheel"}, headers=H("u_ann"))).json()
    assert (li["title"], li["title_en"], li["title_ru"]) == ("Lower basket wheel", "Lower basket wheel", "Колёсико с осью для нижней корзины посудомойки")

    # an order from the card is named by the card in both languages, and so is its first journal line
    bought = (await c.post(f"/api/shop/listings/{li['id']}/order", json={"quantity": 1}, headers=H("u_bob"))).json()
    assert (bought["title_en"], bought["title_ru"]) == ("Lower basket wheel", "Колёсико с осью для нижней корзины посудомойки")
    seen = (await c.get(f"/api/shop/orders/{bought['id']}", headers=H("u_bob"))).json()
    first = seen["timeline"][0]
    assert first["code"] == "ordered_catalog" and first["params"]["title_ru"] == "Колёсико с осью для нижней корзины посудомойки"
    assert first["params"]["title_en"] == "Lower basket wheel"

    # a listing saved before the two names (or seeded) has its one title in both
    await env.db.execute("INSERT INTO shop_listings (id, project_id, version, owner_id, title, public, created_at, updated_at) "
                         "VALUES ('l_old', 'p_old', 1, 'u_old', 'Shelf bag hook', 1, 0, 0)")
    old = (await c.get("/api/shop/listings/l_old", headers=H("u_bob"))).json()
    assert old["title_en"] == old["title_ru"] == "Shelf bag hook"


async def test_older_databases_get_the_listing_title_columns(tmp_path):
    from formwright.db import Database

    db = Database(str(tmp_path / "old.db"))
    await db.open()
    try:
        assert db.conn
        # the wave-2 table, as databases made before the two titles have it
        await db.conn.executescript("""CREATE TABLE shop_listings (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL, version INTEGER NOT NULL, owner_id TEXT NOT NULL, title TEXT NOT NULL,
          brand TEXT NOT NULL DEFAULT '', models TEXT NOT NULL DEFAULT '[]', part_numbers TEXT NOT NULL DEFAULT '[]',
          category TEXT NOT NULL DEFAULT '', material TEXT NOT NULL DEFAULT 'PLA', cover TEXT, verified TEXT NOT NULL DEFAULT '{}',
          public INTEGER NOT NULL DEFAULT 0, orders INTEGER NOT NULL DEFAULT 0, flagged INTEGER NOT NULL DEFAULT 0,
          reports TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL, updated_at REAL NOT NULL);
          INSERT INTO shop_listings (id, project_id, version, owner_id, title, created_at, updated_at) VALUES ('l_1', 'p_1', 1, 'u_1', 'Hook', 0, 0);""")
        await store.ensure(db)
        li = await store.get_listing(db, "l_1")
        assert li["title"] == "Hook" and li["title_en"] == "" and li["title_ru"] == ""
        assert routes.listing_out(li, None)["title_ru"] == "Hook"
        saved = await store.save_listing(db, project_id="p_2", version=1, owner_id="u_1", title="Крючок", title_en="Hook", title_ru="Крючок")
        assert (saved["title_en"], saved["title_ru"]) == ("Hook", "Крючок")
    finally:
        await db.close()
