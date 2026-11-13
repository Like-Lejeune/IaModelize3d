"""A showcase order: the farm shows one delivered order to anyone (its journal, the price, the printer, the times, the
QC photo with SAM 3.1's mask), and nothing of the person who ordered it. Only operators set the flag, only on a
shipped or delivered order; /parts links the newest (offline: shop_fakes' temp DB and hooks)."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys

import pytest

from iamodelize3d.config import SERVER_DIR
from iamodelize3d.db import new_id, now
from iamodelize3d.shop import store

from shop_fakes import add_program, jpeg, setup, teardown, wait_for


@pytest.fixture
async def env(tmp_path, monkeypatch):
    e = await setup(tmp_path, monkeypatch)
    yield e
    await teardown(e)


def H(user: str) -> dict[str, str]:
    return {"x-user": user}


# what the customer gave or said, and the parcel: none of it may reach the public page
PERSONAL = ("+7 701 555 12 34", "Aigerim", "Abay", "424242", "KZ999TRACK", "my secret answer", "u_lea", "called her")


async def _shipped(env) -> dict:
    """An order of u_lea through the farm: paid, printed, a reprint with the operator's note, QC passed, shipped."""
    pid = new_id("p_")
    await env.db.insert("users", {"id": "u_lea", "tier": "free", "name": "Aigerim N.", "created_at": now()})
    await env.db.insert("projects", {"id": pid, "user_id": "u_lea", "title": "Basket wheel", "pack": "household", "cover": f"{pid}/renders/v1.png",
                                     "created_at": now(), "updated_at": now()})
    await add_program(env.db, pid)
    o = (await env.c.post("/api/shop/requests", data={"project_id": pid, "material": "PETG", "contact": "+7 701 555 12 34",
                                                      "text": "Call Aigerim, Abay ave 10, Almaty"}, headers=H("u_lea"))).json()
    o = await wait_for(env, o["id"], "quoted", idle=True)
    # what other paths keep on an order: an address, a name, a chat, the customer's answers
    await store.patch(env.db, o["id"], {"delivery": {"method": "courier", "address": "Abay ave 10, Almaty"},
                                        "customer": {"contact": "+7 701 555 12 34", "name": "Aigerim N.", "chat_id": 424242},
                                        "intake": {**o["intake"], "answers": [{"text": "my secret answer", "at": now()}],
                                                   "reviewed": {"by": "u_op", "action": "approve", "note": "called her", "at": now()}}})
    pr = (await env.c.post("/api/shop/ops/printers", json={"name": "Bambu Lab A1 · Axo #1", "material": "PETG"}, headers=H("u_op"))).json()
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()["status"] == "paid"
    await env.c.post(f"/api/shop/orders/{o['id']}/assign", json={"printer_id": pr["id"]}, headers=H("u_op"))
    await env.c.post(f"/api/shop/orders/{o['id']}/printed", headers=H("u_op"))
    await env.c.post(f"/api/shop/orders/{o['id']}/reprint", json={"note": "stringing, called her about it"}, headers=H("u_op"))
    await env.c.post(f"/api/shop/orders/{o['id']}/assign", json={"printer_id": pr["id"]}, headers=H("u_op"))
    await env.c.post(f"/api/shop/orders/{o['id']}/printed", headers=H("u_op"))
    env.hooks.qc_results = [{"pass": True, "max_mm": 0.31, "tolerance_mm": 0.6, "photo_url": "/files/p_ops/a_qc.jpg",
                             "mask_url": "/files/p_ops/a_qc_mask.png", "printed_mm": [[0, 0], [10, 0], [10, 10]],
                             "target_mm": [[0, 0], [10, 0], [10, 10]], "sheet": {"w": 210, "h": 297}}]
    qc = await env.c.post(f"/api/shop/orders/{o['id']}/qc", files={"file": ("qc.jpg", jpeg(), "image/jpeg")}, headers=H("u_op"))
    assert qc.json()["qc"]["pass"]
    # not yet shipped: no showcase
    early = await env.c.post(f"/api/shop/orders/{o['id']}/showcase", json={"on": True}, headers=H("u_op"))
    assert early.status_code == 409 and early.json()["code"] == "not_delivered"
    s = await env.c.post(f"/api/shop/orders/{o['id']}/ship", json={"carrier": "Kazpost", "tracking": "KZ999TRACK"}, headers=H("u_op"))
    assert s.json()["status"] == "shipped"
    return s.json()


async def test_a_showcase_order_shows_the_farms_work_and_nothing_of_the_customer(env):
    o = await _shipped(env)
    assert (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_other"))).status_code == 403  # not a showcase yet
    assert (await env.c.get("/api/shop/showcase")).json() is None
    # only the farm's operators set the flag
    for who in ("u_lea", "u_other"):
        r = await env.c.post(f"/api/shop/orders/{o['id']}/showcase", json={"on": True}, headers=H(who))
        assert r.status_code == 403 and r.json()["code"] == "not_operator"
    on = (await env.c.post(f"/api/shop/orders/{o['id']}/showcase", json={"on": True}, headers=H("u_op"))).json()
    assert on["showcase"] is True and on["actor"] == "operator"

    for who in ("u_other", "u_anon"):
        r = await env.c.get(f"/api/shop/orders/{o['id']}", headers=H(who))
        assert r.status_code == 200
        text = r.text  # the serialized answer, every field and the journal
        for x in PERSONAL:
            assert x not in text, (who, x)
        pub = r.json()
        assert pub["actor"] == "public" and pub["next"] == [] and pub["showcase"] is True
        for k in ("user_id", "org_id", "own_listing", "question", "project_id"):
            assert k not in pub, k
        assert pub["customer"] == {} and set(pub["delivery"]) == {"method"} and set(pub["shipping"]) == {"carrier", "at"}
        assert pub["intake"]["request"] == {"kind": "project"} and "answers" not in pub["intake"]
        assert pub["intake"]["reviewed"] == {"action": "approve", "at": pub["intake"]["reviewed"]["at"]}  # not who, nor their note
        # what the farm did is all there
        assert pub["quote"]["total"] == o["quote"]["total"] and pub["quote"]["binding"] and "files" not in pub["quote"]
        assert "cost" not in pub["quote"] and "gross_margin" not in pub["quote"]
        assert pub["printer"]["name"] == "Bambu Lab A1 · Axo #1" and pub["payment"]["amount"] == o["quote"]["total"]
        assert pub["qc"]["pass"] and pub["qc"]["photo_url"] == "/files/p_ops/a_qc.jpg" and pub["qc"]["mask_url"] == "/files/p_ops/a_qc_mask.png"
        codes = [e["code"] for e in pub["timeline"]]
        assert {"ordered_studio", "paid_test", "assigned", "printed", "reprint", "qc_pass", "shipped"} <= set(codes)
        assert all(e["ts"] for e in pub["timeline"]) and pub["project"]["cover"].endswith("/renders/v1.png")
        assert next(e for e in pub["timeline"] if e["code"] == "shipped")["params"] == {"carrier": "Kazpost"}

    # the customer and the farm keep their own view of it
    mine = (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_lea"))).json()
    assert mine["actor"] == "customer" and mine["customer"]["contact"] == "+7 701 555 12 34" and mine["showcase"] is True
    latest = (await env.c.get("/api/shop/showcase")).json()
    assert latest["id"] == o["id"] and latest["qc_pass"] and latest["title_en"] and "Aigerim" not in json.dumps(latest)

    off = (await env.c.post(f"/api/shop/orders/{o['id']}/showcase", json={"on": False}, headers=H("u_op"))).json()
    assert off["showcase"] is False
    assert (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_other"))).status_code == 403
    assert (await env.c.get("/api/shop/showcase")).json() is None


async def test_the_board_lists_shipped_orders_for_the_switch(env):
    o = await _shipped(env)
    board = (await env.c.get("/api/shop/ops/queue", headers=H("u_op"))).json()
    assert [x["id"] for x in board["done"]] == [o["id"]] and board["done"][0]["showcase"] is False
    assert o["id"] not in [x["id"] for x in board["orders"]]


def _operator_script():
    sys.path.insert(0, str(SERVER_DIR / "scripts"))
    spec = importlib.util.spec_from_file_location("shop_operator", SERVER_DIR / "scripts" / "shop_operator.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_the_operator_script_switches_a_showcase(tmp_path, capsys):
    op = _operator_script()
    conn = sqlite3.connect(tmp_path / "f.db")
    conn.row_factory = sqlite3.Row
    # a database from before the column: the shop's tables without showcase
    conn.executescript(store.SCHEMA.replace("showcase INTEGER NOT NULL DEFAULT 0,", ""))
    t = now()
    for oid, ref, status in (("so_1", "IM-1001", "delivered"), ("so_2", "IM-1002", "paid")):
        conn.execute("INSERT INTO shop_orders (id, ref, user_id, project_id, status, created_at, updated_at) VALUES (?, ?, 'u', 'p', ?, ?, ?)",
                     (oid, ref, status, t, t))
    op.showcase(conn, "https://fw.test", "IM-1001", True, False)  # a dry run writes nothing
    assert "showcase" not in {r[1] for r in conn.execute("PRAGMA table_info(shop_orders)")}
    op.showcase(conn, "https://fw.test", "IM-1001", True, True)
    assert conn.execute("SELECT showcase FROM shop_orders WHERE id = 'so_1'").fetchone()[0] == 1
    assert "https://fw.test/orders/so_1" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        op.showcase(conn, "https://fw.test", "so_2", True, True)  # paid, not delivered
    op.showcase(conn, "https://fw.test", "so_1", False, True)
    assert conn.execute("SELECT showcase FROM shop_orders WHERE id = 'so_1'").fetchone()[0] == 0
    conn.close()
