"""What anyone can do to the shop from the outside (wave-6 security review): how many orders one visitor or one
network opens, whose test payments move everyone's ETA, who gets the workshop tariff, what a catalog buyer sees of the
card owner's private project, and a failed price-card 'Apply' that must not open Pay (offline: shop_fakes)."""
from __future__ import annotations

import sqlite3

import pytest

from formwright.db import new_id, now
from formwright.shop import autoquote, flow, routes, store

from shop_fakes import add_program, setup, teardown, wait_for
from test_shop_showcase import _operator_script


@pytest.fixture
async def env(tmp_path, monkeypatch):
    e = await setup(tmp_path, monkeypatch)
    yield e
    await teardown(e)


def H(user: str) -> dict[str, str]:
    return {"x-user": user}


async def _user(env, uid: str, tier: str = "anon", ip: str | None = None) -> None:
    await env.db.insert("users", {"id": uid, "tier": tier, "ip": ip, "created_at": now()})


async def test_one_anonymous_visitor_or_network_cannot_fill_the_farms_board(env):
    await _user(env, "u_flood", ip="203.0.113.7")
    codes = [(await env.c.post("/api/shop/requests", data={"text": f"oven handle {i}"}, headers=H("u_flood"))).status_code for i in range(6)]
    assert codes == [200] * routes.ANON_OPEN_ORDERS + [429]
    r = await env.c.post("/api/shop/requests", data={"text": "oven handle"}, headers=H("u_flood"))
    assert r.json()["code"] == "too_many_orders"
    # a new cookie from the same network: counted together, ANON_NETWORK_ORDERS a day
    for i in range(routes.ANON_NETWORK_ORDERS - routes.ANON_OPEN_ORDERS):
        await _user(env, f"u_n{i}", ip="203.0.113.7")
        assert (await env.c.post("/api/shop/requests", data={"text": "knob"}, headers=H(f"u_n{i}"))).status_code == 200
    await _user(env, "u_late", ip="203.0.113.7")
    late = await env.c.post("/api/shop/requests", data={"text": "knob"}, headers=H("u_late"))
    assert late.status_code == 429 and late.json()["code"] == "too_many_orders"
    await _user(env, "u_far", ip="198.51.100.1")  # another network still orders
    assert (await env.c.post("/api/shop/requests", data={"text": "knob"}, headers=H("u_far"))).status_code == 200
    # an anonymous order takes up to ANON_PIECES pieces; a signed-in person (and the farm) more
    big = await env.c.post("/api/shop/requests", data={"text": "clip", "quantity": "200"}, headers=H("u_anon"))
    assert big.status_code == 400 and big.json()["code"] == "too_many_pieces"
    await _user(env, "u_judge", tier="free")
    assert (await env.c.post("/api/shop/requests", data={"text": "clip", "quantity": "200"}, headers=H("u_judge"))).status_code == 200
    # a cancelled order no longer counts toward the open ones
    mine = (await env.c.get("/api/shop/orders", headers=H("u_flood"))).json()
    await env.c.post(f"/api/shop/orders/{mine[0]['id']}/cancel", headers=H("u_flood"))
    await env.db.execute("UPDATE users SET ip = NULL WHERE id = 'u_flood'")  # (the network's day is used up)
    assert (await env.c.post("/api/shop/requests", data={"text": "oven handle"}, headers=H("u_flood"))).status_code == 200


async def test_a_catalog_order_is_capped_too(env):
    pid = new_id("p_")
    await _user(env, "u_seller", tier="free")
    await env.db.insert("projects", {"id": pid, "user_id": "u_seller", "title": "Wheel", "pack": "household", "created_at": now(), "updated_at": now()})
    await add_program(env.db, pid)
    li = await store.save_listing(env.db, project_id=pid, version=1, owner_id="u_seller", title="Wheel", public=True)
    r = await env.c.post(f"/api/shop/listings/{li['id']}/order", json={"quantity": 200}, headers=H("u_b"))
    assert r.status_code == 400 and r.json()["code"] == "too_many_pieces"
    for _ in range(routes.ANON_OPEN_ORDERS):
        assert (await env.c.post(f"/api/shop/listings/{li['id']}/order", json={"quantity": 2}, headers=H("u_b"))).status_code == 200
    assert (await env.c.post(f"/api/shop/listings/{li['id']}/order", json={"quantity": 2}, headers=H("u_b"))).json()["code"] == "too_many_orders"
    o = await wait_for(env, (await env.c.get("/api/shop/orders", headers=H("u_b"))).json()[0]["id"], "quoted", idle=True)
    # nor can a requote on the price card raise it
    r = await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"quantity": 200}, headers=H("u_b"))
    assert r.status_code == 400 and r.json()["code"] == "too_many_pieces"


async def test_an_anonymous_test_payment_does_not_push_back_everyones_eta(env):
    q = {"minutes_each": 120, "binding": True}
    await _user(env, "u_anon_payer")
    await _user(env, "u_known", tier="free")
    await store.create_order(env.db, user_id="u_anon_payer", project_id="p_x", status="paid", quantity=10, quote=q)
    await store.patch(env.db, (await store.queue(env.db))[0]["id"], {"payment": {"mode": "test"}})
    assert await store.queue_hours(env.db) == 0
    o = await store.create_order(env.db, user_id="u_known", project_id="p_y", status="paid", quote=q)
    await store.patch(env.db, o["id"], {"payment": {"mode": "test"}})
    assert await store.queue_hours(env.db) == 2  # a signed-in customer's order
    o = await store.create_order(env.db, user_id="u_anon_payer", project_id="p_z", status="printing", quote=q)
    assert await store.queue_hours(env.db) == 4  # the farm put this one on a printer


async def test_a_workshop_account_gets_its_tariff_once_the_farm_checked_it(env, tmp_path, capsys):
    org = (await env.c.post("/api/shop/orgs", json={"name": "Мастерская"}, headers=H("u_shop"))).json()
    assert org["kind"] == "repair_shop" and org["tier"] == "pending"
    assert await autoquote.customer_kind(env.db, "u_shop") == "consumer"
    pid = new_id("p_")
    await env.db.insert("projects", {"id": pid, "user_id": "u_shop", "title": "Wheel", "pack": "household", "created_at": now(), "updated_at": now()})
    await add_program(env.db, pid)
    consumer = (await env.c.get(f"/api/shop/instant-quote/{pid}", params={"quantity": 4}, headers=H("u_shop"))).json()
    # the farm checks the workshop with the operator script (here on a copy of the tables)
    op = _operator_script()
    conn = sqlite3.connect(tmp_path / "ops.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    conn.execute("INSERT INTO shop_orgs (id, name, kind, tier, created_at) VALUES (?, 'Мастерская', 'repair_shop', 'pending', ?)", (org["id"], now()))
    op.workshop(conn, org["id"], True, False)  # a dry run writes nothing
    assert conn.execute("SELECT tier FROM shop_orgs").fetchone()[0] == "pending"
    op.workshop(conn, org["id"], True, True)
    assert conn.execute("SELECT tier FROM shop_orgs").fetchone()[0] == "repair_shop"
    assert "workshop tariff" in capsys.readouterr().out
    await env.db.execute("UPDATE shop_orgs SET tier = 'repair_shop' WHERE id = ?", org["id"])
    assert await autoquote.customer_kind(env.db, "u_shop") == "repair_shop"
    shop = (await env.c.get(f"/api/shop/instant-quote/{pid}", params={"quantity": 4}, headers=H("u_shop"))).json()
    assert shop["total"] < consumer["total"]


async def test_a_catalog_buyer_sees_the_card_not_the_owners_private_project(env):
    pid = new_id("p_")
    await _user(env, "u_seller", tier="free")
    await env.db.insert("projects", {"id": pid, "user_id": "u_seller", "title": "Wheel", "pack": "household", "cover": f"{pid}/renders/v1_iso.png",
                                     "created_at": now(), "updated_at": now()})
    await add_program(env.db, pid)
    li = await store.save_listing(env.db, project_id=pid, version=1, owner_id="u_seller", title="Dishwasher wheel", public=True,
                                  cover=f"{pid}/renders/v1_iso.png")
    # later, in private: a gift with someone's address in its name, and a newer version
    await add_program(env.db, pid, version=2)
    await env.db.execute("UPDATE projects SET title = ?, cover = ? WHERE id = ?", "Подарок для Айгуль (ул. Абая 12)", f"{pid}/renders/v2_iso.png", pid)
    o = (await env.c.post(f"/api/shop/listings/{li['id']}/order", json={"quantity": 1}, headers=H("u_buyer"))).json()
    o = await wait_for(env, o["id"], "quoted", idle=True)
    seen = (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_buyer"))).json()
    assert seen["title"] == "Dishwasher wheel" and seen["project"]["title"] == "Dishwasher wheel"
    assert seen["project"]["cover"] == f"/files/{pid}/renders/v1_iso.png" and seen["project"]["version"] == 1
    assert "files" not in seen["slice"] and "files" not in seen["quote"]
    assert "Айгуль" not in str(seen)
    # the farm prints it: its board has the files; the owner reordering their own card sees their project
    board = (await env.c.get("/api/shop/ops/queue", headers=H("u_op"))).json()
    card = next(x for x in board["upstream"] if x["id"] == o["id"])
    assert card["slice"]["files"]["gcode"]
    own = (await env.c.post(f"/api/shop/listings/{li['id']}/order", json={"quantity": 1}, headers=H("u_seller"))).json()
    assert own["project"]["title"].startswith("Подарок")


async def test_a_failed_apply_on_the_price_card_keeps_pay_waiting_for_the_intakes_material(env):
    """'Choose for me' quoted in PLA, the intake picks PETG and its slice fails: the card's 'Apply' with the PETG it
    pre-selects fails again, and Pay stays closed instead of opening on the PLA quote (wave-6 review-code)."""
    pid = new_id("p_")
    await _user(env, "u_lea")
    await env.db.insert("projects", {"id": pid, "user_id": "u_lea", "title": "Wheel", "pack": "household", "created_at": now(), "updated_at": now()})
    await add_program(env.db, pid)
    real = env.hooks.slice

    async def petg_fails(project_id, version, printer_id, material, fingerprint):
        if material == "PETG":
            raise RuntimeError("OrcaSlicer exited with code 1")
        return await real(project_id, version, printer_id, material, fingerprint)

    env.hooks.slice = petg_fails
    r = await env.c.post("/api/shop/requests", data={"project_id": pid, "quantity": "1"}, headers=H("u_lea"))
    o = await wait_for(env, r.json()["id"], "quoted", idle=True)
    assert flow.material_due(o) == "PETG" and o["quote"]["material"] == "PLA"
    r = await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"quantity": 1, "material": "PETG", "delivery": "courier"}, headers=H("u_lea"))
    assert r.status_code == 409 and r.json()["code"] == "slice_failed"
    o = await store.get(env.db, o["id"])
    assert o["intake"]["request"].get("material") is None and flow.material_due(o) == "PETG"
    page = (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_lea"))).json()
    assert "paid" not in page["next"] and page["material_due"] == "PETG"
    pay = await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))
    assert pay.status_code == 409 and pay.json()["code"] == "material_pending"
    # a material that does slice is the customer's own from then on
    r = await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"material": "ASA"}, headers=H("u_lea"))
    assert r.status_code == 200 and r.json()["quote"]["material"] == "ASA" and r.json()["material_due"] is None
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()["status"] == "paid"


async def test_the_operators_own_order_is_received_by_its_customer(env):
    for view, actor in ((None, "customer"), ("ops", "operator")):
        o = await store.create_order(env.db, user_id="u_op", project_id="p_x", status="shipped")
        url = f"/api/shop/orders/{o['id']}/delivered" + (f"?view={view}" if view else "")
        assert (await env.c.post(url, headers=H("u_op"))).json()["status"] == "delivered"
        assert (await store.timeline(env.db, o["id"]))[-1]["actor"] == actor
