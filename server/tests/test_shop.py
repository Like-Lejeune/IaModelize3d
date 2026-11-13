"""IaModelize3d Parts (shop): prices, the order lifecycle, the farm board, QC, the catalog and the intake safety gate.
Offline: a temp database, the slicer answers with real OrcaSlicer numbers and the intake with real Muse Spark answers."""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

import numpy as np
import pytest

from iamodelize3d.shop import flow, intake, qc, quote, store

from shop_fakes import CALIB, CASES, WHEEL, finish_design, jpeg, setup, teardown, wait_for


@pytest.fixture
async def env(tmp_path, monkeypatch):
    e = await setup(tmp_path, monkeypatch)
    yield e
    await teardown(e)


def H(user: str) -> dict[str, str]:
    return {"x-user": user}


# ------------------------------------------------------------------ prices
def test_price_breakdown_is_consistent():
    q = quote.price(grams=10, minutes=35, material="PETG", quantity=4, customer="consumer", rate=520)
    assert q["currency"] == "KZT" and q["unit_price"] % 10 == 0
    assert q["parts"] == round(q["unit_price"] * 4, 2)
    assert q["total"] == round(q["parts"] + q["new_part_fee"] + q["delivery"]["price"], 2)
    assert q["usd"]["rate"] == 520 and q["usd"]["total"] == round(q["total"] / 520, 2)
    assert 0.55 < q["gross_margin"] < 0.9
    b2b = quote.price(grams=10, minutes=35, material="PETG", quantity=4, customer="repair_shop")
    assert b2b["total"] < q["total"] and b2b["new_part_fee"] < q["new_part_fee"]
    reorder = quote.price(grams=10, minutes=35, material="PETG", quantity=4, new_part=False, listing_royalty=True)
    assert reorder["new_part_fee"] == 0 and reorder["royalty"] == round(reorder["parts"] * 0.10, 2)


CALIB_A1 = json.loads((Path(__file__).parent / "fixtures" / "shop" / "calibration_a1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("points", [CALIB, CALIB_A1["points"]], ids=["x1c", "a1"])
def test_instant_band_covers_every_calibration_point(points):
    inside = 0
    for r in points:
        for customer in ("consumer", "repair_shop"):
            band = quote.instant({"estGrams": r["est_g"], "estMinutes": r["est_min"]}, customer=customer)["range"]["total"]
            firm = quote.price(grams=r["orca_g"], minutes=r["orca_min"], customer=customer)["total"]
            inside += band[0] <= firm <= band[1]
    assert len(points) == 17 and inside == 2 * len(points)


def test_unit_economics_on_the_farms_a1():
    """The pitch numbers from the A1 slices and the tariff: tenge with dollars beside them."""
    def med(f):
        return sorted(f(r) for r in CALIB_A1["points"])[8]

    consumer = med(lambda r: quote.price(grams=r["orca_g"], minutes=r["orca_min"])["total"])
    margin = med(lambda r: quote.price(grams=r["orca_g"], minutes=r["orca_min"])["gross_margin"])
    assert consumer == 9790 and quote.usd(consumer) == 18.83 and 0.7 < margin < 0.78
    w = CALIB_A1["wheel"]
    four = quote.price(grams=w["orca_g"], minutes=w["orca_min"], material="PETG", quantity=4)
    shop = quote.price(grams=w["orca_g"], minutes=w["orca_min"], material="PETG", quantity=4, customer="repair_shop")
    assert (four["total"], shop["total"]) == (15960, 10960)


def test_moves_table():
    o = {"status": "quoted", "quote": {"binding": False}}
    with pytest.raises(flow.FlowError) as e:
        flow.check(o, "paid", "customer")
    assert e.value.code == "guard"
    with pytest.raises(flow.FlowError):
        flow.check({"status": "paid"}, "printing", "customer")
    assert "cancelled" in flow.next_moves({"status": "paid"}, "customer")
    # the operator is offered Assign on a paid order: the endpoint itself slices for the printer
    assert "printing" in flow.next_moves({"status": "paid"}, "operator")
    assert flow.next_moves({"status": "refused"}, "customer") == []


# ------------------------------------------------------------------ the whole order
async def test_full_order_lifecycle(env):
    c, hooks = env.c, env.hooks
    r = await c.post("/api/shop/requests", data={"text": "Bosch dishwasher lower basket wheel broke", "appliance": "Bosch SMS46GI01E",
                                                 "delivery": "courier", "contact": "+7 701 000 00 00"},
                     files=[("files", ("wheel.jpg", jpeg(), "image/jpeg")), ("plate", ("plate.jpg", jpeg(200, 120), "image/jpeg"))],
                     headers=H("u_alice"))
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["status"] == "requested" and o["intake"]["request"]["kind"] == "photo"
    await wait_for(env, o["id"], "designing")
    o = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_alice"))).json()
    assert o["status"] == "designing", o
    assert o["material"] == "PETG" and o["quantity"] == 4  # from the intake: no quantity on the form
    assert o["intake"]["refuse"] is False and o["intake"]["appliance"]["model"] == "SMS46GI01E/09"
    assert o["title"].startswith("Колёсико нижней корзины") and "SMS46GI01E/09" in o["title"]
    design = hooks.designs[0]
    plate_id = next(p["id"] for p in o["intake"]["request"]["photos"] if p["role"] == "plate")
    assert len(design["asset_ids"]) == 1 and plate_id not in design["asset_ids"]  # the agent measures the part, not the plate
    assert "never put the brand name" in design["text"] and "BOSCH logo" in design["text"] and "PETG" in design["text"]

    await finish_design(env, o["id"])
    o = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_alice"))).json()
    assert o["status"] == "quoted", o
    q = o["quote"]
    assert q["binding"] and q["source"] == "orca" and q["grams_each"] == round(WHEEL["orca_g"], 1) and q["currency"] == "KZT"
    assert q["usd"]["total"] == round(q["total"] / q["usd"]["rate"], 2)
    assert q["new_part_fee"] > 0 and q["eta"]["arrive_by"] >= q["eta"]["ready_by"]
    assert "cost" not in q and "gross_margin" not in q  # the farm's costs stay with the farm
    assert "paid" in o["next"]
    assert hooks.slices[-1]["preset"] == "bambu-lab-a1-0-4-nozzle"  # no farm printer yet: the A1 preset

    # someone else cannot see it; the operator cannot start an unpaid order
    assert (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_bob"))).status_code == 403
    pr = (await c.post("/api/shop/ops/printers", json={"name": "A1 #1", "preset_id": "Bambu Lab A1 0.4 nozzle", "material": "PETG"},
                       headers=H("u_op"))).json()
    assert pr["state"] == "idle"
    bad = await c.post(f"/api/shop/orders/{o['id']}/assign", json={"printer_id": pr["id"]}, headers=H("u_op"))
    assert bad.status_code == 409 and bad.json()["code"] == "order_bad_move"

    paid = (await c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_alice"))).json()
    assert paid["status"] == "paid" and paid["payment"]["mode"] == "test" and paid["payment"]["amount"] == q["total"]
    denied = await c.get("/api/shop/ops/queue", headers=H("u_alice"))
    assert denied.status_code == 403 and denied.json()["code"] == "not_operator"
    board = (await c.get("/api/shop/ops/queue", headers=H("u_op"))).json()
    # an anonymous visitor's test payment holds nobody's ETA back until the farm puts it on a printer
    assert [x["id"] for x in board["orders"]] == [o["id"]] and board["queue_hours"] == 0
    assert "cost" in board["orders"][0]["quote"] and board["orders"][0]["customer"]["contact"] == "+7 701 000 00 00"

    n = len(hooks.slices)
    a = (await c.post(f"/api/shop/orders/{o['id']}/assign", json={"printer_id": pr["id"]}, headers=H("u_op"))).json()
    assert a["status"] == "printing" and a["slice"]["files"]["gcode"].endswith(".gcode") and len(hooks.slices) == n + 1  # sliced for this printer
    board = (await c.get("/api/shop/ops/queue", headers=H("u_op"))).json()
    assert board["printers"][0]["state"] == "printing" and board["printers"][0]["order_ref"] == o["ref"]
    assert board["queue_hours"] > 0
    assert (await c.post(f"/api/shop/orders/{o['id']}/printed", headers=H("u_op"))).json()["status"] == "qc"

    hooks.qc_results = [{"pass": False, "max_mm": 1.4, "tolerance_mm": 0.6}, {"pass": False, "error": "no A4 sheet or card in the photo"},
                        {"pass": True, "max_mm": 0.31, "tolerance_mm": 0.6}]
    fail = (await c.post(f"/api/shop/orders/{o['id']}/qc", files={"file": ("qc.jpg", b"x", "image/jpeg")}, headers=H("u_op"))).json()
    assert fail["status"] == "paid" and fail["qc"]["max_mm"] == 1.4  # back in the queue for a reprint
    again = (await c.post(f"/api/shop/orders/{o['id']}/assign", json={"printer_id": pr["id"]}, headers=H("u_op"))).json()
    assert again["status"] == "printing" and len(hooks.slices) == n + 1  # the same printer's slice is reused
    await c.post(f"/api/shop/orders/{o['id']}/printed", headers=H("u_op"))
    blurry = (await c.post(f"/api/shop/orders/{o['id']}/qc", files={"file": ("qc.jpg", b"x", "image/jpeg")}, headers=H("u_op"))).json()
    assert blurry["status"] == "qc" and blurry["qc"]["error"]  # a photo that cannot be measured is not a failed print
    good = (await c.post(f"/api/shop/orders/{o['id']}/qc", files={"file": ("qc.jpg", b"x", "image/jpeg")}, headers=H("u_op"))).json()
    assert good["status"] == "qc" and good["qc"]["pass"] and good["attempts"] == 2 and "shipped" in good["next"]
    no_track = await c.post(f"/api/shop/orders/{o['id']}/ship", json={}, headers=H("u_op"))
    assert no_track.status_code == 409 and no_track.json()["code"] == "order_guard"
    s = (await c.post(f"/api/shop/orders/{o['id']}/ship", json={"carrier": "Kazpost", "tracking": "KZ123"}, headers=H("u_op"))).json()
    assert s["status"] == "shipped" and s["shipping"]["tracking"] == "KZ123"
    d = (await c.post(f"/api/shop/orders/{o['id']}/delivered", headers=H("u_alice"))).json()
    assert d["status"] == "delivered" and d["customer"] == {}  # the contact is wiped once delivered
    tl = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_alice"))).json()["timeline"]
    assert [t["status"] for t in tl] == ["requested", "requested", "designing", "quoted", "paid", "printing", "qc", "qc", "paid", "printing",
                                         "qc", "qc", "qc", "shipped", "delivered"]
    assert tl[1]["note"].startswith("read by muse-spark-1.3") and tl[3]["actor"] == "system" and tl[4]["actor"] == "customer"

    # "Your parts": a private listing appeared on delivery; publishing it needs the QC pass it has
    mine = (await c.get("/api/shop/listings", params={"mine": "true"}, headers=H("u_alice"))).json()
    assert len(mine) == 1 and not mine[0]["public"] and mine[0]["verified"]["qc_pass"] and mine[0]["verified"]["qc_max_mm"] == 0.31
    assert mine[0]["verified"]["printable"] and mine[0]["verified"]["critic"] == "pass"
    assert mine[0]["title"] == "Колёсико с осью для нижней корзины посудомойки" and mine[0]["compatible_with"] == "BOSCH SMS46GI01E/09"
    assert (await c.get("/api/shop/listings", params={"q": "sms46"})).json() == []
    li = (await c.post("/api/shop/listings", json={"project_id": o["project_id"], "title": "Lower basket wheel", "brand": "Bosch",
                                                   "models": ["SMS46GI01E"], "part_numbers": ["00611475"]}, headers=H("u_alice"))).json()
    assert li["id"] == mine[0]["id"] and li["public"] and li["mine"]
    found = (await c.get("/api/shop/listings", params={"q": "sms46"})).json()
    assert [x["id"] for x in found] == [li["id"]] and not found[0]["mine"] and "owner_id" not in found[0]
    assert (await c.get("/api/shop/listings", params={"q": "006114"})).json()[0]["id"] == li["id"]
    assert (await c.get("/api/shop/listings", params={"q": "bosch wheel"})).json()[0]["id"] == li["id"]

    # someone else finds it and orders it: no design step, no new-part fee, a royalty to the owner
    price = (await c.get(f"/api/shop/listings/{li['id']}/quote", params={"quantity": 2}, headers=H("u_bob"))).json()
    assert price["binding"] is False and price["new_part_fee"] == 0 and price["quantity"] == 2 and price["material"] == "PETG"
    assert not set(quote.INTERNAL) & set(price)  # the farm's costs stay with the farm here too
    assert "gross_margin" in (await c.get(f"/api/shop/listings/{li['id']}/quote", headers=H("u_op"))).json()
    assert (await c.get(f"/api/shop/instant-quote/{o['project_id']}", headers=H("u_bob"))).status_code == 403  # the project stays private
    re_ = (await c.post(f"/api/shop/listings/{li['id']}/order", json={"quantity": 1}, headers=H("u_bob"))).json()
    assert re_["status"] == "requested" and re_["quote"]["binding"] is False and re_["quote"]["range"]["total"][0] > 0  # instant range at once
    await wait_for(env, re_["id"], "quoted", idle=True)
    re_ = (await c.get(f"/api/shop/orders/{re_['id']}", headers=H("u_bob"))).json()
    assert re_["status"] == "quoted" and re_["quote"]["new_part_fee"] == 0 and len(hooks.designs) == 1
    assert (await store.get(env.db, re_["id"]))["quote"]["royalty"] > 0
    await c.post(f"/api/shop/orders/{re_['id']}/pay", headers=H("u_bob"))
    assert (await c.get(f"/api/shop/listings/{li['id']}", headers=H("u_bob"))).json()["orders"] == 1

    # takedown: a signed-in person's report hides it from the catalog until the operator looks at it
    await env.db.execute("INSERT INTO users (id, tier, created_at) VALUES ('u_carol', 'free', 0)")
    report = f"/api/shop/listings/{li['id']}/report"
    assert (await c.post(report, json={"reason": "logo on the part"}, headers=H("u_carol"))).json()["flagged"]
    assert (await c.get("/api/shop/listings", params={"q": "sms46"})).json() == []
    back = (await c.post(f"/api/shop/ops/listings/{li['id']}/flag", json={"flagged": False}, headers=H("u_op"))).json()
    assert back["reports"][0]["reason"] == "logo on the part"
    assert len((await c.get("/api/shop/listings", params={"q": "sms46"})).json()) == 1

    # an anonymous visitor's report is free to repeat with a fresh cookie: it queues for the operator, and hides the
    # part only once reports come from 3 networks; the same person twice counts once
    for uid, net in (("u_a1", "10.0.0.1"), ("u_a2", "10.0.0.1"), ("u_a3", "10.0.0.2"), ("u_a3", "10.0.0.2")):
        await env.db.execute("INSERT OR IGNORE INTO users (id, tier, ip, created_at) VALUES (?, 'anon', ?, 0)", uid, net)
        assert (await c.post(report, json={"reason": "mine"}, headers=H(uid))).json() == {"ok": True, "flagged": False}
    assert len((await c.get("/api/shop/listings", params={"q": "sms46"})).json()) == 1
    await env.db.execute("INSERT INTO users (id, tier, ip, created_at) VALUES ('u_a4', 'anon', '10.0.0.3', 0)")
    assert (await c.post(report, json={"reason": "mine"}, headers=H("u_a4"))).json()["flagged"]
    assert len((await store.get_listing(env.db, li["id"]))["reports"]) == 5
    # and nobody files more than REPORTS_PER_DAY a day
    from iamodelize3d.shop import routes

    await env.db.execute("INSERT INTO shop_listings (id, project_id, version, owner_id, title, public, created_at, updated_at) "
                         "VALUES ('l_other', 'p_other', 1, 'u_other', 'Other part', 1, 0, 0)")
    old, routes.REPORTS_PER_DAY = routes.REPORTS_PER_DAY, 1
    try:
        r = await c.post("/api/shop/listings/l_other/report", json={"reason": "x"}, headers=H("u_a1"))  # u_a1 reported one today
        assert r.status_code == 429 and r.json()["code"] == "too_many_reports"
        assert (await c.post("/api/shop/listings/l_other/report", json={"reason": "x"}, headers=H("u_bob"))).status_code == 200
    finally:
        routes.REPORTS_PER_DAY = old


async def test_unverified_part_cannot_be_public(env):
    r = (await env.c.post("/api/shop/requests", data={"text": "fridge shelf clip"}, headers=H("u_carol"))).json()
    await wait_for(env, r["id"], "designing")
    await finish_design(env, r["id"])
    res = await env.c.post("/api/shop/listings", json={"project_id": r["project_id"], "title": "clip"}, headers=H("u_carol"))
    assert res.status_code == 409 and res.json()["code"] == "not_verified"


async def test_safety_gate_refuses(env):
    r = (await env.c.post("/api/shop/requests", data={"text": "knob for my gas stove"}, headers=H("u_dan"))).json()
    await wait_for(env, r["id"], "refused", idle=True)
    r = (await env.c.get(f"/api/shop/orders/{r['id']}", headers=H("u_dan"))).json()
    assert r["status"] == "refused" and r["next"] == [] and env.hooks.designs == []
    assert "gas" in r["timeline"][-1]["note"].lower()


async def test_models_disagree_so_the_operator_decides(env):
    r = (await env.c.post("/api/shop/requests", data={"text": "review-me: a plastic part"}, headers=H("u_eve"))).json()
    await wait_for(env, r["id"], "requested", idle=True)
    r = (await env.c.get(f"/api/shop/orders/{r['id']}", headers=H("u_eve"))).json()
    assert r["status"] == "requested" and r["intake"]["review"]["code"] == "safety_disagreement" and env.hooks.designs == []
    board = (await env.c.get("/api/shop/ops/queue", headers=H("u_op"))).json()
    assert [x["id"] for x in board["upstream"]] == [r["id"]]
    await wait_for(env, r["id"], "requested", idle=True)
    assert env.hooks.designs == []  # the board's reconcile does not start a held order
    ok = (await env.c.post(f"/api/shop/orders/{r['id']}/review", json={"action": "approve", "note": "a clip, not gas"}, headers=H("u_op"))).json()
    assert ok["intake"]["reviewed"]["action"] == "approve"
    await wait_for(env, r["id"], "designing")
    assert len(env.hooks.designs) == 1


async def test_an_operator_pays_for_their_own_order(env):
    # the founder operates the farm and orders a part from the same account: the order page is the customer's
    c = env.c
    o = (await c.post("/api/shop/requests", data={"text": "dishwasher wheel"}, headers=H("u_op"))).json()
    await wait_for(env, o["id"], "designing")
    await finish_design(env, o["id"])
    mine = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_op"))).json()
    assert mine["status"] == "quoted" and mine["actor"] == "customer" and "paid" in mine["next"] and "cost" not in mine["quote"]
    assert (await c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_op"))).json()["status"] == "paid"
    board = (await c.get("/api/shop/ops/queue", headers=H("u_op"))).json()
    card = next(x for x in board["orders"] if x["id"] == o["id"])
    assert card["actor"] == "operator" and "printing" in card["next"] and "cost" in card["quote"]


async def test_repair_shop_price_is_lower(env):
    org = (await env.c.post("/api/shop/orgs", json={"name": "TechnoFix"}, headers=H("u_tech"))).json()
    assert org["tier"] == "pending"
    await env.db.execute("UPDATE shop_orgs SET tier = 'repair_shop' WHERE id = ?", org["id"])  # the farm checked it (shop_operator.py --workshop)
    me = (await env.c.get("/api/shop/me", headers=H("u_tech"))).json()
    assert me["org"]["id"] == org["id"] and not me["is_operator"] and me["currency"] == "KZT" and me["usd_kzt"] == 520
    r = (await env.c.post("/api/shop/requests", data={"text": "dishwasher wheel"}, headers=H("u_tech"))).json()
    assert r["org_id"] == org["id"]
    await wait_for(env, r["id"], "designing")
    await finish_design(env, r["id"])
    b2b = (await env.c.get(f"/api/shop/orders/{r['id']}", headers=H("u_tech"))).json()["quote"]
    consumer = quote.firm({"stats": {"grams": WHEEL["orca_g"], "minutes": WHEEL["orca_min"]}, "material": "PETG"}, quantity=4)
    assert b2b["total"] < consumer["total"]
    op = (await env.c.get("/api/shop/me", headers=H("u_op"))).json()
    assert op["is_operator"] and op["org"]["name"] == "Axo"


async def test_two_operators_cannot_both_move(env):
    o = await store.create_order(env.db, user_id="u_x", project_id="p_x", status="qc")
    await store.patch(env.db, o["id"], {"qc": {"pass": True}, "shipping": {"tracking": "T"}})
    res = await asyncio.gather(store.move(env.db, o["id"], "shipped", "operator"), store.move(env.db, o["id"], "paid", "operator"),
                               return_exceptions=True)
    out = [type(x).__name__ if isinstance(x, Exception) else x["status"] for x in res]
    assert sorted(out) in (["FlowError", "shipped"], ["FlowError", "paid"]), out


# ------------------------------------------------------------------ intake answers recorded from the models
@pytest.mark.parametrize("name", list(CASES))
def test_intake_fixtures(name):
    c = CASES[name]
    out = intake.combine(c["spark"], c["open"], spark_model=c["spark_model"], open_model=c["open_model"])
    exp = c["expect"]
    assert out["refuse"] is exp["refuse"]
    assert (out["review"] or {}).get("code") == exp["review"]
    if "material" in exp:
        assert out["material"] == exp["material"]
    if "quantity" in exp:
        assert out["part"]["quantity"] == exp["quantity"]
    if "brand" in exp:
        assert out["appliance"]["brand"] == exp["brand"] and out["appliance"]["model"] == exp["model"]
    if exp.get("ip_flags"):
        assert out["ip_flags"]
    if out["refuse"]:
        assert out["reason"]  # the customer is told why


def test_open_model_never_decides_refuse():
    gas = CASES["gas_knob"]
    # Spark refuses: the open model's opinion does not matter either way
    assert intake.combine(gas["spark"], {"safety_critical": False, "category": "appliance", "why": "", "title_en": "", "title_ru": ""})["refuse"]
    # Spark accepts and the open model's answer is not a classification at all: Spark's answer stands, nobody is held
    wheel = CASES["voice_wheel_plate_a4"]
    out = intake.combine(wheel["spark"], CASES["open_model_wrong_object"]["open"])
    assert out["refuse"] is False and out["review"] is None and out["classify"]["error"]
    brief = intake.design_brief(out, "колёсико", "IM-1001")
    assert "IM-1001" in brief and "dishwasher lower basket wheel" in brief and "compatible part" in brief


# ------------------------------------------------------------------ QC report (contract C10)
def _rot(points: np.ndarray, deg: float) -> np.ndarray:
    a = math.radians(deg)
    return points @ np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]]).T


def test_qc_report_shape_c10():
    # the model's footprint (mm, model frame) and the print as measured on the sheet: moved, turned, 0.3% larger
    target = np.array([[-20, -10], [20, -10], [20, 4], [14, 10], [-20, 10]], dtype=float)
    hole = np.array([[math.cos(t) * 2.5 - 10, math.sin(t) * 2.5] for t in np.linspace(0, 2 * math.pi, 40, endpoint=False)])
    printed = _rot(target * 1.003, 23) + [105, 150]
    rep = qc.build_report([target.tolist(), hole.tolist()], [printed.tolist()], tolerance_mm=0.6, photo_url="/files/p/a.jpg", mask_url="/files/p/m.png")
    for key in ("pass", "tolerance_mm", "max_mm", "mean_mm", "rms_mm", "bias_mm", "scale", "regions", "photo_url", "mask_url", "printed_mm",
                "target_mm", "sheet", "note"):
        assert key in rep, key
    assert rep["pass"] and rep["max_mm"] < 0.2 and rep["sheet"] == {"w": 210.0, "h": 297.0} and rep["note"] == "контур в плане"
    # target_mm is already on the print: every model point lies on the printed outline, on the sheet's grid
    t, p = np.array(rep["target_mm"]), np.array(rep["printed_mm"])
    assert 80 < t[:, 0].mean() < 130 and 120 < t[:, 1].mean() < 180
    dense = np.vstack([p[i] + (p[(i + 1) % len(p)] - p[i]) * s for i in range(len(p)) for s in np.linspace(0, 1, 50)])
    assert max(np.min(np.hypot(*(dense - q).T)) for q in t) < 0.2
    assert all("center_sheet" in r for r in rep["regions"])
    # a print 2 mm too long at one end fails the 0.6 mm tolerance (the best fit splits it, still over)
    bulged = target.copy()
    bulged[1:3, 0] += 2.0
    assert not qc.build_report([target.tolist()], [(_rot(bulged, 10) + [100, 100]).tolist()])["pass"]
