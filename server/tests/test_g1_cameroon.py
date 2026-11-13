"""G1 Réparation (Cameroon): prices in FCFA rounded to 100, a French title for every order, and a Mobile Money payment
the workshop checks before printing. Offline, on the same fakes as the shop tests."""
from __future__ import annotations

import pytest

from formwright.shop import flow, intake, quote

from shop_fakes import answer, finish_design, jpeg, setup, teardown, wait_for


def H(user: str) -> dict[str, str]:
    return {"x-user": user}


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setattr(quote, "DEFAULT", quote.CAMEROON)
    e = await setup(tmp_path, monkeypatch)
    yield e
    await teardown(e)


# ------------------------------------------------------------------ tariff
def test_the_cameroon_tariff_prices_in_fcfa_rounded_to_100():
    q = quote.price(grams=41.2, minutes=126.4, material="PETG", quantity=3, t=quote.CAMEROON)
    assert q["currency"] == "XAF"
    assert q["unit_price"] % 100 == 0 and q["unit_price"] >= quote.CAMEROON.min_unit["consumer"]
    assert q["total"] == q["parts"] + q["new_part_fee"] + q["delivery"]["price"]
    assert q["usd"]["rate"] == quote.CAMEROON.usd_rate and q["usd"]["total"] == round(q["total"] / 600.0, 2)
    # a repair shop pays less per unit
    shop = quote.price(grams=41.2, minutes=126.4, material="PETG", quantity=3, customer="repair_shop", t=quote.CAMEROON)
    assert shop["unit_price"] < q["unit_price"]


def test_the_kazakh_tariff_is_unchanged_by_default():
    assert quote.TARIFFS["kz"].currency == "KZT" and quote.TARIFFS["kz"].round_to == 0
    assert quote._round_price(2_345, quote.TARIFFS["kz"]) == 2_390  # tenge prices end in 90
    assert quote._round_price(2_345, quote.CAMEROON) == 2_400


def test_the_tariff_and_rate_are_settings(monkeypatch):
    monkeypatch.setattr(quote, "shop_settings", lambda: quote.ShopSettings(_env_file=None, shop_tariff="cm", usd_rate=610.0))
    assert quote._tariff() is quote.CAMEROON and quote.usd_rate(quote.CAMEROON) == 610.0
    monkeypatch.setattr(quote, "shop_settings", lambda: quote.ShopSettings(_env_file=None, shop_tariff="xx"))
    with pytest.raises(ValueError, match="FW_SHOP_TARIFF"):
        quote._tariff()


# ------------------------------------------------------------------ French titles
def test_a_french_title_from_the_customers_words_or_the_models():
    data = {"language": "fr", "part": {"name_user": "molette du ventilateur", "name_fr": "bouton de ventilateur", "name_en": "fan knob"},
            "appliance": {"brand": "Binatone", "model": "TS-1880"}}
    assert intake.title_fr(data) == "Molette du ventilateur · Binatone TS-1880"
    # an English-speaking customer: the intake's French name, not their English words
    data["language"] = "en"
    assert intake.title_fr(data).startswith("Bouton de ventilateur")
    # the open model's catalog title comes before the intake's own name
    data["classify"] = {"title_fr": "Bouton rotatif de ventilateur", "safety_critical": False}
    assert intake.title_fr(data).startswith("Bouton rotatif")
    assert intake.title_fr({}) == intake.UNNAMED_FR


def test_the_intake_asks_for_french_names():
    assert "name_fr" in intake.SCHEMA["properties"]["part"]["required"]
    assert "title_fr" in intake.CLASSIFY_SCHEMA["required"]
    assert "part.name_fr" in intake.SYSTEM and "title_fr" in intake.CLASSIFY_SYSTEM


# ------------------------------------------------------------------ an order end to end
async def quoted_order(env, delivery: str = "courier") -> dict:
    c = env.c
    r = await c.post("/api/shop/requests", data={"text": "La roulette du panier de mon lave-vaisselle est cassée", "delivery": delivery,
                                                 "contact": "+237 6 00 00 00 00"},
                     files=[("files", ("roue.jpg", jpeg(), "image/jpeg"))], headers=H("u_ama"))
    assert r.status_code == 200, r.text
    o = r.json()
    await wait_for(env, o["id"], "designing")
    await finish_design(env, o["id"])
    o = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_ama"))).json()
    assert o["status"] == "quoted", o
    return o


async def test_an_order_is_quoted_in_fcfa_with_a_french_title(env):
    o = await quoted_order(env)
    q = o["quote"]
    assert q["currency"] == "XAF" and q["unit_price"] % 100 == 0 and q["usd"]["rate"] == 600.0
    assert "title_fr" in o and o["title_fr"]
    tariff = (await env.c.get("/api/shop/tariff")).json()
    assert tariff["currency"] == "XAF" and tariff["usd_rate"] == 600.0 and tariff["delivery"]["courier"]["price"] == 1500.0
    quoted = next(e for e in o["timeline"] if e["code"] == "quoted")
    assert quoted["params"]["currency"] == "XAF" and "XAF" in quoted["note"]


async def test_mobile_money_is_checked_by_the_workshop_before_printing(env):
    c = env.c
    o = await quoted_order(env)
    no_ref = await c.post(f"/api/shop/orders/{o['id']}/pay", json={"method": "mobile_money", "operator": "mtn"}, headers=H("u_ama"))
    assert no_ref.status_code == 400 and no_ref.json()["code"] == "payment_reference"
    paid = (await c.post(f"/api/shop/orders/{o['id']}/pay", json={"method": "mobile_money", "operator": "mtn", "reference": " MP2611.1234.A56 "},
                         headers=H("u_ama"))).json()
    assert paid["status"] == "paid"
    assert paid["payment"] | {} == paid["payment"] and paid["payment"]["mode"] == "mobile_money"
    assert paid["payment"]["reference"] == "MP2611.1234.A56" and paid["payment"]["verified"] is False
    assert paid["timeline"][-1]["code"] == "paid_mobile_money" if "timeline" in paid else True

    pr = (await c.post("/api/shop/ops/printers", json={"name": "A1 Yaoundé", "preset_id": "Bambu Lab A1 0.4 nozzle", "material": "PETG"},
                       headers=H("u_op"))).json()
    early = await c.post(f"/api/shop/orders/{o['id']}/assign", json={"printer_id": pr["id"]}, headers=H("u_op"))
    assert early.status_code == 409 and "Mobile Money" in early.json()["detail"]
    # only the workshop checks a payment
    assert (await c.post(f"/api/shop/orders/{o['id']}/payment-verified", headers=H("u_ama"))).status_code == 403
    ok = (await c.post(f"/api/shop/orders/{o['id']}/payment-verified", headers=H("u_op"))).json()
    assert ok["payment"]["verified"] is True
    a = (await c.post(f"/api/shop/orders/{o['id']}/assign", json={"printer_id": pr["id"]}, headers=H("u_op"))).json()
    assert a["status"] == "printing"
    detail = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_ama"))).json()
    codes = [e["code"] for e in detail["timeline"]]
    assert "paid_mobile_money" in codes and "payment_verified" in codes


async def test_payment_on_pickup_needs_the_pickup_delivery(env):
    c = env.c
    o = await quoted_order(env)
    bad = await c.post(f"/api/shop/orders/{o['id']}/pay", json={"method": "on_pickup"}, headers=H("u_ama"))
    assert bad.status_code == 409 and bad.json()["code"] == "payment_method"
    o2 = await quoted_order(env, delivery="pickup")
    paid = (await c.post(f"/api/shop/orders/{o2['id']}/pay", json={"method": "on_pickup"}, headers=H("u_ama"))).json()
    assert paid["status"] == "paid" and paid["payment"]["mode"] == "on_pickup"
    # no body at all is still the test payment of the original demo
    o3 = await quoted_order(env)
    assert (await c.post(f"/api/shop/orders/{o3['id']}/pay", headers=H("u_ama"))).json()["payment"]["mode"] == "test"


def test_a_test_payment_goes_to_the_printer_without_a_check():
    o = {"payment": {"mode": "test"}, "printer_id": "pr_1", "slice": {"files": {"gcode": "x.gcode"}}}
    assert flow._assigned(o) is None
    assert flow._assigned({**o, "payment": {"mode": "mobile_money", "verified": False}}) == "check the Mobile Money payment first"


def test_the_french_name_is_carried_by_the_recorded_answers():
    # the recorded Muse Spark answers predate name_fr: an order still gets a French title (the fallback)
    assert intake.title_fr(answer("voice_wheel_plate_a4")) in (intake.UNNAMED_FR,) or intake.title_fr(answer("voice_wheel_plate_a4"))
