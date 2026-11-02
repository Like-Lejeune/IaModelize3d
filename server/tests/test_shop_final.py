"""Wave-6 shop residuals: the quantity is the order's (never a design question), the operator's 'Let through' on a request
nobody could read sets its quantity and material, a failed requote in the material the intake chose keeps Pay closed
until reconcile prices it again, and the design run opens with the customer's own words (offline: shop_fakes)."""
from __future__ import annotations

import asyncio
import copy

import pytest

from formwright.db import new_id, now
from formwright.shop import autoquote, flow, intake, routes, store

from shop_fakes import CASES, add_program, answer, setup, teardown, wait_for


@pytest.fixture
async def env(tmp_path, monkeypatch):
    e = await setup(tmp_path, monkeypatch)
    yield e
    await teardown(e)


def H(user: str) -> dict[str, str]:
    return {"x-user": user}


def _codes(timeline: list[dict]) -> list[str]:
    return [(t.get("data") or {}).get("code") for t in timeline]


# ------------------------------------------------------------------ the quantity is the order's
QUANTITY_ASKS = ["Сколько колёс нужно напечатать?", "Сколько штук нужно?", "Какое количество вам нужно?", "Нужно одно колесо или несколько?",
                 "How many wheels do you need?", "What quantity should we print?", "How many pieces?", "How many copies would you like?",
                 "Сколько колёс вам нужно?", "Сколько вы хотите заказать?", "How many should we print?"]
DESIGN_ASKS = ["Уточните диаметр колеса и диаметр/д длину оси?", "Пришлите фото на листе с линейкой?", "Какое количество зубьев у шестерни?",
               "Сколько отверстий под винты?", "How many teeth does the gear have?", "What is the wheel diameter and axle/mount type?",
               "Can you send a photo of an intact wheel?", "How many screw holes do you see on the part?",
               "How many teeth do you count on the gear?", "Сколько отверстий под винты вы видите на детали?",
               "Сколько миллиметров диаметр оси, которую вы измерили?"]


def test_quantity_questions_are_told_apart_from_design_questions():
    assert [q for q in QUANTITY_ASKS if not intake.asks_quantity(q)] == []
    assert [q for q in DESIGN_ASKS if intake.asks_quantity(q)] == []


def test_the_intake_and_the_brief_drop_quantity_questions_and_name_the_orders_quantity():
    spark = copy.deepcopy(CASES["voice_wheel_plate_a4"]["spark"])
    spark["questions"] = ["Сколько колёс нужно напечатать?", "Уточните диаметр колеса?"]
    out = intake.combine(spark, None, spark_model="spark")
    assert out["questions"] == ["Уточните диаметр колеса?"]
    brief = intake.design_brief(out, "колёсико", "FW-1001", quantity=2, material="PETG")
    assert "Quantity: 2, set on the order: never ask the customer how many they need." in brief
    assert "Уточните диаметр колеса?" in brief and "Сколько" not in brief
    # an intake stored before the filter still has the question: the brief leaves it out
    old = {**out, "questions": ["How many wheels do you need?"]}
    brief = intake.design_brief(old, "", "FW-1002")
    assert "How many" not in brief and "could not tell" not in brief and "Quantity: 4," in brief  # the intake's own reading, without an order
    # the customer's own material against the intake's pick: the designer knows both
    brief = intake.design_brief(out, "", "FW-1003", quantity=1, material="PLA")
    assert "Material: PLA (up to 70 C, wet" in brief and "the customer's choice (the intake desk would pick PETG)" in brief


async def test_the_forms_quantity_is_the_quantity_the_designer_gets(env):
    # the form says 2; the intake reads '4 pcs' from the request: the order and the brief keep the form's 2
    o = (await env.c.post("/api/shop/requests", data={"text": "колёсико нижней корзины", "quantity": "2"}, headers=H("u_ann"))).json()
    o = await wait_for(env, o["id"], "designing")
    assert o["quantity"] == 2 and o["intake"]["part"]["quantity"] == 4
    assert "Quantity: 2, set on the order" in env.hooks.designs[0]["text"]
    # left empty ('from the request'): what the request says
    o2 = (await env.c.post("/api/shop/requests", data={"text": "колёсико нижней корзины"}, headers=H("u_bob"))).json()
    o2 = await wait_for(env, o2["id"], "designing")
    assert o2["quantity"] == 4 and "Quantity: 4, set on the order" in env.hooks.designs[1]["text"]


# ------------------------------------------------------------------ the operator lets an unread request through
async def _unread(env, user: str, text: str, **form: str) -> dict:
    async def down(user, text, photos):
        raise ConnectionError("the intake model is unreachable")

    env.hooks.intake = down
    o = (await env.c.post("/api/shop/requests", data={"text": text, **form}, headers=H(user))).json()
    o = await wait_for(env, o["id"], "requested", idle=True)
    assert o["intake"]["review"]["code"] == "intake_failed" and flow.safety(o) == "held" and env.hooks.designs == []
    return o


async def test_let_through_an_unread_request_with_the_quantity_and_material_the_operator_read(env):
    o = await _unread(env, "u_gul", "Сломалась ручка духовки Gorenje, нужно 2 штуки")
    bad = await env.c.post(f"/api/shop/orders/{o['id']}/review", json={"action": "approve", "material": "ABS"}, headers=H("u_op"))
    assert bad.status_code == 400 and bad.json()["code"] == "bad_material"
    r = await env.c.post(f"/api/shop/orders/{o['id']}/review", json={"action": "approve", "quantity": 2, "material": "petg"}, headers=H("u_op"))
    assert r.status_code == 200
    o = await wait_for(env, o["id"], "designing")
    assert (o["quantity"], o["material"]) == (2, "PETG")
    assert o["intake"]["part"]["quantity"] == 2 and o["intake"]["material"] == "PETG" and o["intake"]["reviewed"]["action"] == "approve"
    brief = env.hooks.designs[0]["text"]
    assert "Material: PETG." in brief and "Quantity: 2, set on the order" in brief and "intake desk would pick" not in brief
    approved = next(t for t in await store.timeline(env.db, o["id"]) if (t.get("data") or {}).get("code") == "approved")
    assert approved["data"]["params"] == {"note": "", "quantity": 2, "material": "PETG"}
    assert approved["note"] == "approved by the operator, 2 pcs, PETG"


async def test_let_through_without_fields_keeps_the_customers_form(env):
    o = await _unread(env, "u_dina", "ручка духовки", quantity="3", material="ASA")
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/review", json={"action": "approve"}, headers=H("u_op"))).status_code == 200
    o = await wait_for(env, o["id"], "designing")
    assert (o["quantity"], o["material"]) == (3, "ASA") and "Material: ASA." in env.hooks.designs[0]["text"]
    assert "Quantity: 3, set on the order" in env.hooks.designs[0]["text"]


async def test_the_operators_quantity_is_the_only_quantity_in_the_brief(env):
    # the form said 3 and its request text carries 'Quantity: 3'; the operator lets it through with 2
    o = await _unread(env, "u_ilya", "ручка духовки", quantity="3")
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/review", json={"action": "approve", "quantity": 2}, headers=H("u_op"))).status_code == 200
    o = await wait_for(env, o["id"], "designing")
    brief = env.hooks.designs[0]["text"]
    assert o["quantity"] == 2 and "Quantity: 2, set on the order" in brief and "Quantity: 3" not in brief
    assert brief.endswith("The customer's request:\nручка духовки")


# ------------------------------------------------------------------ "choose for me" when the slicer fails in the intake's material
async def _studio(env, user: str = "u_lea", *, material: str | None = None) -> dict:
    pid = new_id("p_")
    await env.db.insert("users", {"id": user, "tier": "anon", "created_at": now()})
    await env.db.insert("projects", {"id": pid, "user_id": user, "title": "Wheel", "pack": "household", "created_at": now(), "updated_at": now()})
    await add_program(env.db, pid)
    form = {"project_id": pid, "quantity": "1", **({"material": material} if material else {})}
    r = await env.c.post("/api/shop/requests", data=form, headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def _petg_fails(env) -> dict:
    real = env.hooks.slice
    state = {"broken": True}

    async def slice_(project_id, version, printer_id, material, fingerprint):
        if material == "PETG" and state["broken"]:
            raise RuntimeError("OrcaSlicer exited with code 1")
        return await real(project_id, version, printer_id, material, fingerprint)

    env.hooks.slice = slice_
    return state


async def test_a_failed_requote_in_the_intakes_material_keeps_pay_closed_and_reconcile_retries_it(env):
    state = _petg_fails(env)
    o = await _studio(env)
    o = await wait_for(env, o["id"], "quoted", idle=True)
    # the PLA price stands, the PETG slice failed: a problem on the order, Pay closed
    assert o["quote"]["material"] == "PLA" and o["intake"]["material"] == "PETG"
    assert o["problem"]["code"] == "slice_failed" and o["problem"]["material"] == "PETG" and o["problem"]["retry_at"] > now()
    assert flow.material_due(o) == "PETG"
    page = (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_lea"))).json()
    assert page["safety"] == "ok" and page["material_due"] == "PETG" and "paid" not in page["next"] and page["problem"]["code"] == "slice_failed"
    r = await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))
    assert r.status_code == 409 and r.json()["code"] == "material_pending"
    assert "problem" in _codes(await store.timeline(env.db, o["id"]))
    # not again before its retry time; then the order page's reconcile slices it in PETG
    assert await autoquote.reconcile(env.db) == 0
    state["broken"] = False
    await store.patch(env.db, o["id"], {"problem": {**o["problem"], "retry_at": now() - 1}})
    await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_lea"))
    o = await wait_for(env, o["id"], "quoted", idle=True)
    assert o["quote"]["material"] == o["material"] == "PETG" and not o["problem"] and flow.material_due(o) is None
    paid = (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()
    assert paid["status"] == "paid" and paid["material"] == "PETG"


async def test_a_material_picked_on_the_price_card_is_the_customers_and_opens_pay(env):
    _petg_fails(env)
    o = await wait_for(env, (await _studio(env))["id"], "quoted", idle=True)
    assert flow.material_due(o) == "PETG"
    # changing only the quantity requotes in the intake's material (it fails again here: Pay stays closed)
    r = await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"quantity": 2}, headers=H("u_lea"))
    assert r.status_code == 409 and r.json()["code"] == "slice_failed"
    # the customer picks PLA themselves: no longer "choose for me", so it is the price to pay
    r = await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"material": "pla"}, headers=H("u_lea"))
    assert r.status_code == 200 and r.json()["quote"]["material"] == "PLA" and r.json()["material_due"] is None
    o = await store.get(env.db, o["id"])
    assert o["intake"]["request"]["material"] == "PLA" and "paid" in r.json()["next"]
    await autoquote.reconcile(env.db)
    await autoquote.drain(3)
    assert (await store.get(env.db, o["id"]))["quote"]["material"] == "PLA"  # the intake's PETG does not come back over it
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()["status"] == "paid"


async def test_an_expired_choose_for_me_quote_comes_back_in_the_intakes_material(env):
    state = _petg_fails(env)
    o = await wait_for(env, (await _studio(env))["id"], "quoted", idle=True)
    state["broken"] = False
    await store.patch(env.db, o["id"], {"quote": {**o["quote"], "valid_until": now() - 1}, "problem": {}})
    assert [x["status"] for x in (await env.c.get("/api/shop/orders", headers=H("u_lea"))).json()] == ["expired"]
    fresh = (await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={}, headers=H("u_lea"))).json()
    assert fresh["status"] == "quoted" and fresh["quote"]["material"] == "PETG" and fresh["material_due"] is None


async def test_telegram_waits_for_the_price_in_the_intakes_material(env, monkeypatch):
    from formwright.integrations import telegram

    sent: list[str] = []

    async def fake_call(self, method, **params):
        if method == "sendMessage":
            sent.append(params["text"])
        return {"message_id": 1}

    monkeypatch.setattr(telegram.Bot, "call", fake_call)
    state = _petg_fails(env)
    pid = new_id("p_")
    await env.db.insert("users", {"id": "tg_80", "tier": "anon", "created_at": now()})
    await env.db.insert("projects", {"id": pid, "user_id": "tg_80", "title": "Wheel", "pack": "household", "created_at": now(), "updated_at": now()})
    await add_program(env.db, pid)
    u = await env.db.one("SELECT * FROM users WHERE id = ?", "tg_80")
    bot = telegram.Bot("TOKEN")
    o = await routes.order_project(env.db, u, await env.db.one("SELECT * FROM projects WHERE id = ?", pid), code="ordered_telegram")
    follower = asyncio.create_task(bot.follow_order(42, u, o["id"], "en", rounds=600, every=0.01))
    o = await wait_for(env, o["id"], "quoted", idle=True)
    for _ in range(100):
        if sent:
            break
        await asyncio.sleep(0.01)
    # the PLA price is not told as payable: the slicer's stop is
    assert len(sent) == 1 and "Pay" not in sent[0] and "slicer" in sent[0]
    state["broken"] = False
    await store.patch(env.db, o["id"], {"problem": {**o["problem"], "retry_at": now() - 1}})
    await autoquote.reconcile(env.db, [await store.get(env.db, o["id"])])
    await asyncio.wait_for(follower, 10)
    assert len(sent) == 2 and "Pay and follow the order" in sent[1]
    assert (await store.get(env.db, o["id"]))["quote"]["material"] == "PETG"
    await bot.http.aclose()


# ------------------------------------------------------------------ the customer's own words open the run
def test_the_shown_line_is_the_customers_own_words_or_a_short_line_in_their_language():
    req = {"kind": "photo", "text": "Сломалась ручка\nAppliance: Gorenje\nQuantity: 2\nVoice note: она треснула", "words": "Сломалась ручка",
           "appliance": "Gorenje", "part_number": "", "transcript": "она треснула"}
    assert intake.shown_line({"request": req, "language": "ru"}, "FW-1004") == "Сломалась ручка\nGorenje\nона треснула"
    # an order from before 'words': the request text without the form's labelled lines
    old = {k: v for k, v in req.items() if k != "words"}
    assert intake.customer_words(old) == "Сломалась ручка\nGorenje\nона треснула"
    # photos alone: the ref and the part's name in the customer's language
    data = answer("voice_wheel_plate_a4")
    data["request"] = {"kind": "photo", "text": "", "words": "", "photos": [{"id": "a_1"}]}
    assert intake.shown_line(data, "FW-1005") == "Заказ FW-1005: Колёсико нижней корзины · BOSCH SMS46GI01E/09"
    assert intake.shown_line({"request": {"kind": "listing"}, "language": "en"}, "FW-1006") == "Order FW-1006: Spare part"


async def test_the_design_run_opens_with_the_customers_words(env):
    o = (await env.c.post("/api/shop/requests", data={"text": "колёсико нижней корзины", "appliance": "Bosch SMS46", "quantity": "2"},
                          headers=H("u_ann"))).json()
    await wait_for(env, o["id"], "designing")
    d = env.hooks.designs[0]
    assert d["shown"] == "колёсико нижней корзины\nBosch SMS46" and d["text"].startswith("Spare part order")
    assert "Quantity: 2" in d["text"] and "Quantity" not in d["shown"]


async def test_the_real_hook_passes_shown(monkeypatch):
    from formwright.agent import runner

    seen = {}

    async def fake_start(user, project, body):
        seen["body"] = body
        return "j_x"

    monkeypatch.setattr(runner, "start_design_job", fake_start)
    assert await routes.Hooks().start_design({"id": "u"}, {"id": "p"}, "Spare part order FW-1001", ["a_1"], "ru", shown="колёсико") == "j_x"
    assert seen["body"].text == "Spare part order FW-1001" and seen["body"].language == "ru"
    assert getattr(seen["body"], "shown", "колёсико") == "колёсико"  # SendMessage.shown (agent-answers' field)
