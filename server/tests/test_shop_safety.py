"""A ready model's binding quote does not wait on the intake; Pay waits on its safety verdict instead. The races
(the intake refuses after the quote, the quote lands after a refusal, Pay during the intake), a request held for the
operator, a quota that held the intake up, "choose for me", quotes that expire and come back, and the intake's
language reaching the designer (offline: shop_fakes' temp DB and hooks)."""
from __future__ import annotations

import asyncio

import pytest

from iamodelize3d import quotas
from iamodelize3d.db import new_id, now
from iamodelize3d.shop import autoquote, routes, store

from shop_fakes import add_program, answer, setup, teardown, wait_for


@pytest.fixture
async def env(tmp_path, monkeypatch):
    e = await setup(tmp_path, monkeypatch)
    yield e
    await teardown(e)


def H(user: str) -> dict[str, str]:
    return {"x-user": user}


async def _studio(env, user: str = "u_lea", *, material: str | None = "PLA", text: str = "") -> dict:
    """A studio model ordered from the studio ("Get a quote"): the order as the request answers it."""
    pid = new_id("p_")
    if not await env.db.one("SELECT id FROM users WHERE id = ?", user):
        await env.db.insert("users", {"id": user, "tier": "anon", "created_at": now()})
    await env.db.insert("projects", {"id": pid, "user_id": user, "title": "Bracket", "pack": "household", "created_at": now(), "updated_at": now()})
    await add_program(env.db, pid)
    form = {"project_id": pid, "quantity": "1", **({"material": material} if material else {}), **({"text": text} if text else {})}
    r = await env.c.post("/api/shop/requests", data=form, headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def _slow_intake(env, case: str) -> asyncio.Event:
    gate = asyncio.Event()

    async def intake(user, text, photos):
        await gate.wait()
        return answer(case)

    env.hooks.intake = intake
    return gate


def _codes(timeline: list[dict]) -> list[str]:
    return [(t.get("data") or {}).get("code") for t in timeline]


async def test_the_quote_lands_while_the_intake_reads_and_pay_waits_for_it(env):
    gate = _slow_intake(env, "voice_wheel_plate_a4")
    o = await _studio(env)
    assert o["safety"] == "pending"
    o = await wait_for(env, o["id"], "quoted")  # OrcaSlicer's price, with Muse Spark 1.3 still reading
    assert o["quote"]["binding"] and not isinstance(o["intake"].get("refuse"), bool)
    page = (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_lea"))).json()
    assert page["status"] == "quoted" and page["safety"] == "pending" and page["quote"]["total"] > 0 and "paid" not in page["next"]
    # Pay during the intake
    r = await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))
    assert r.status_code == 409 and r.json()["code"] == "safety_pending"
    assert (await store.get(env.db, o["id"]))["status"] == "quoted"
    gate.set()
    await wait_for(env, o["id"], "quoted", idle=True)
    page = (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_lea"))).json()
    assert page["safety"] == "ok" and "paid" in page["next"]
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()["status"] == "paid"


async def test_the_intake_refuses_after_the_quote(env):
    gate = _slow_intake(env, "gas_knob")
    o = await _studio(env)
    await wait_for(env, o["id"], "quoted")
    gate.set()
    o = await wait_for(env, o["id"], "refused", idle=True)
    assert o["intake"]["refuse"] is True
    assert _codes(await store.timeline(env.db, o["id"]))[-1] == "refused_safety"
    r = await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))
    assert r.status_code == 409 and (await store.get(env.db, o["id"]))["status"] == "refused"


async def test_a_quote_that_lands_after_a_refusal_leaves_it_refused(env):
    sliced = asyncio.Event()
    real = env.hooks.slice

    async def slow_slice(*a):
        await sliced.wait()
        return await real(*a)

    env.hooks.slice = slow_slice

    async def gas(user, text, photos):
        return answer("gas_knob")

    env.hooks.intake = gas
    o = await _studio(env)
    await wait_for(env, o["id"], "refused")  # the refusal first, the slicer still at work
    sliced.set()
    await autoquote.drain(3)
    after = await store.get(env.db, o["id"])
    assert after["status"] == "refused" and not after["quote"].get("binding") and not after["problem"]
    assert "quoted" not in [t["too"] for t in await store.timeline(env.db, o["id"])]


async def test_a_held_ready_model_is_quoted_but_waits_for_the_operator(env):
    o = await _studio(env, text="review-me stove knob")
    o = await wait_for(env, o["id"], "quoted", idle=True)
    assert o["intake"]["review"]["code"] == "safety_disagreement"
    page = (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_lea"))).json()
    assert page["safety"] == "held" and "paid" not in page["next"]
    r = await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))
    assert r.status_code == 409 and r.json()["code"] == "held"
    # the board shows it held, and the operator lets it through on the quoted order itself
    board = (await env.c.get("/api/shop/ops/queue", headers=H("u_op"))).json()
    assert o["id"] in [x["id"] for x in board["upstream"]]
    ok = await env.c.post(f"/api/shop/orders/{o['id']}/review", json={"action": "approve", "note": "a clip"}, headers=H("u_op"))
    assert ok.status_code == 200 and ok.json()["status"] == "quoted" and ok.json()["safety"] == "ok"
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()["status"] == "paid"


async def test_the_operator_refuses_a_held_quoted_order(env):
    o = await _studio(env, text="review-me stove knob")
    await wait_for(env, o["id"], "quoted", idle=True)
    r = await env.c.post(f"/api/shop/orders/{o['id']}/review", json={"action": "refuse", "note": "gas"}, headers=H("u_op"))
    assert r.status_code == 200 and r.json()["status"] == "refused"
    # an order the intake let through is not waiting for a review
    o2 = await _studio(env)
    await wait_for(env, o2["id"], "quoted", idle=True)
    r = await env.c.post(f"/api/shop/orders/{o2['id']}/review", json={"action": "refuse"}, headers=H("u_op"))
    assert r.status_code == 409


async def test_a_quota_that_held_the_intake_up_is_read_later(env):
    calls = []

    async def spent(user, text, photos):
        calls.append(text)
        if len(calls) == 1:
            raise quotas.QuotaExceeded("daily limit reached", "daily_limit")
        return answer("voice_wheel_plate_a4")

    env.hooks.intake = spent
    o = await _studio(env)
    o = await wait_for(env, o["id"], "quoted", idle=True)
    # the quote landed, and the intake's problem is still there after it (the quote's fields clear problems)
    assert o["problem"]["code"] == "daily_limit" and o["quote"]["binding"]
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()["code"] == "safety_pending"
    assert await autoquote.reconcile(env.db) == 0  # not before its retry time
    await store.patch(env.db, o["id"], {"problem": {**o["problem"], "retry_at": now() - 1}})
    await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_lea"))  # the order page's reconcile reads it now
    o = await wait_for(env, o["id"], "quoted", idle=True)
    assert len(calls) == 2 and o["intake"]["refuse"] is False and not o["problem"] and len(env.hooks.slices) == 1
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()["status"] == "paid"


async def test_choose_for_me_quotes_the_intakes_material(env):
    o = await _studio(env, material=None)
    o = await wait_for(env, o["id"], "quoted", idle=True)
    # quoted in PLA while the intake read it, then in the PETG it chose for a dishwasher part
    assert [s["material"] for s in env.hooks.slices] == ["PLA", "PETG"]
    assert o["material"] == o["quote"]["material"] == "PETG" and "requoted" in _codes(await store.timeline(env.db, o["id"]))


async def test_quotes_expire_and_a_fresh_quote_revives_the_order(env):
    o = await _studio(env)
    o = await wait_for(env, o["id"], "quoted", idle=True)
    await store.patch(env.db, o["id"], {"quote": {**o["quote"], "valid_until": now() - 1}})
    # the order list and the order page both see it expired
    listed = (await env.c.get("/api/shop/orders", headers=H("u_lea"))).json()
    assert [x["status"] for x in listed] == ["expired"]
    page = (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_lea"))).json()
    assert page["status"] == "expired" and page["next"] == ["quoted"] and page["timeline"][-1]["code"] == "expired"
    assert page["timeline"][-1]["actor"] == "system"
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).status_code == 409
    # someone else cannot revive it; its customer can, with a fresh slice and a new valid_until
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={}, headers=H("u_max"))).status_code == 403
    n = len(env.hooks.slices)
    fresh = (await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={}, headers=H("u_lea"))).json()
    assert fresh["status"] == "quoted" and fresh["quote"]["valid_until"] > now() and len(env.hooks.slices) == n + 1
    assert _codes(await store.timeline(env.db, o["id"]))[-1] == "requoted"
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()["status"] == "paid"


async def test_the_board_expires_stale_quotes_and_the_operator_revives_one(env):
    o = await _studio(env)
    o = await wait_for(env, o["id"], "quoted", idle=True)
    await store.patch(env.db, o["id"], {"quote": {**o["quote"], "valid_until": now() - 1}})
    board = (await env.c.get("/api/shop/ops/queue", headers=H("u_op"))).json()
    assert o["id"] not in [x["id"] for x in board["upstream"]] and (await store.get(env.db, o["id"]))["status"] == "expired"
    r = await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"grams_each": 12, "minutes_each": 40}, headers=H("u_op"))
    assert r.status_code == 200 and r.json()["status"] == "quoted" and r.json()["quote"]["source"] == "operator"


async def test_a_ru_customers_design_runs_in_russian(env):
    o = (await env.c.post("/api/shop/requests", data={"text": "колёсико для посудомойки"}, headers=H("u_ann"))).json()
    await wait_for(env, o["id"], "designing")
    d = env.hooks.designs[0]
    assert d["language"] == "ru" and d["text"].startswith("Spare part order")  # the brief stays English for the model


async def test_the_real_hook_passes_the_language_to_the_run(monkeypatch):
    from iamodelize3d.agent import runner

    seen = {}

    async def fake_start(user, project, body):
        seen["body"] = body
        return "j_x"

    monkeypatch.setattr(runner, "start_design_job", fake_start)
    assert await routes.Hooks().start_design({"id": "u"}, {"id": "p"}, "Spare part order IM-1001", ["a_1"], "ru") == "j_x"
    assert seen["body"].language == "ru" and seen["body"].text == "Spare part order IM-1001" and seen["body"].asset_ids == ["a_1"]


async def test_choose_for_me_keeps_pay_closed_until_the_intakes_material_is_quoted(env):
    real = env.hooks.slice

    async def slow_petg(project_id, version, printer_id, material, fingerprint):
        if material == "PETG":
            await asyncio.sleep(0.4)  # OrcaSlicer's seconds for the material the intake chose
        return await real(project_id, version, printer_id, material, fingerprint)

    env.hooks.slice = slow_petg
    o = await _studio(env, material=None)
    while True:  # the verdict is in (safety ok), the PLA quote stands, and the PETG slice is still running
        cur = await store.get(env.db, o["id"])
        if cur["status"] == "quoted" and cur["intake"].get("refuse") is False:
            break
        await asyncio.sleep(0.01)
    page = (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_lea"))).json()
    assert page["working"] and "paid" not in page["next"]
    r = await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))
    assert r.status_code == 409 and r.json()["code"] == "price_updating"
    o = await wait_for(env, o["id"], "quoted", idle=True)
    assert o["material"] == o["quote"]["material"] == "PETG"
    paid = (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()
    assert paid["status"] == "paid" and paid["material"] == "PETG"


async def test_a_stale_list_does_not_expire_a_quote_renewed_since(env):
    o = await wait_for(env, (await _studio(env))["id"], "quoted", idle=True)
    await store.patch(env.db, o["id"], {"quote": {**o["quote"], "valid_until": now() - 60}})
    stale = [await store.get(env.db, o["id"])]  # what the board or the order list read a moment ago
    r = await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"quantity": 2}, headers=H("u_lea"))
    assert r.status_code == 200 and r.json()["quote"]["valid_until"] > now() + 6 * 86400
    assert await autoquote.expire(env.db, stale) == 0
    assert (await store.get(env.db, o["id"]))["status"] == "quoted"


async def test_the_operator_cannot_approve_before_the_intake_has_answered(env):
    gate = _slow_intake(env, "gas_knob_spark_ok_open_unsafe")
    o = await _studio(env)
    assert o["safety"] == "pending"
    r = await env.c.post(f"/api/shop/orders/{o['id']}/review", json={"action": "approve"}, headers=H("u_op"))
    assert r.status_code == 409 and r.json()["code"] == "order_guard"
    gate.set()
    o = await wait_for(env, o["id"], "quoted", idle=True)
    # the open model's hold comes after: it is the operator's to see, and Pay waits for it
    assert o["intake"]["review"]["code"] == "safety_disagreement" and "reviewed" not in o["intake"]
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))).json()["code"] == "held"


async def _telegram_order(env, monkeypatch, case: str, user: str) -> tuple:
    from iamodelize3d.integrations import telegram

    sent: list[str] = []

    async def fake_call(self, method, **params):
        if method == "sendMessage":
            sent.append(params["text"])
        return {"message_id": 1}

    monkeypatch.setattr(telegram.Bot, "call", fake_call)
    gate = _slow_intake(env, case)
    pid = new_id("p_")
    await env.db.insert("users", {"id": user, "tier": "anon", "created_at": now()})
    await env.db.insert("projects", {"id": pid, "user_id": user, "title": "Knob", "pack": "household", "created_at": now(), "updated_at": now()})
    await add_program(env.db, pid)
    u = await env.db.one("SELECT * FROM users WHERE id = ?", user)
    bot = telegram.Bot("TOKEN")
    o = await routes.order_project(env.db, u, await env.db.one("SELECT * FROM projects WHERE id = ?", pid), code="ordered_telegram")
    follower = asyncio.create_task(bot.follow_order(42, u, o["id"], "en", rounds=400, every=0.01))
    await wait_for(env, o["id"], "quoted")  # the price lands while the intake still reads
    await asyncio.sleep(0.1)
    return bot, o, follower, gate, sent


async def test_telegram_tells_a_refusal_that_comes_after_the_price(env, monkeypatch):
    bot, o, follower, gate, sent = await _telegram_order(env, monkeypatch, "gas_knob", "tg_77")
    assert sent == []  # no 'pay' while Pay is closed
    gate.set()
    await wait_for(env, o["id"], "refused", idle=True)
    await asyncio.wait_for(follower, 10)
    assert len(sent) == 1 and "we cannot print this part" in sent[0]
    await bot.http.aclose()


async def test_telegram_tells_a_hold_and_then_the_price_once_the_operator_lets_it_through(env, monkeypatch):
    bot, o, follower, gate, sent = await _telegram_order(env, monkeypatch, "gas_knob_spark_ok_open_unsafe", "tg_78")
    gate.set()
    await wait_for(env, o["id"], "quoted", idle=True)
    for _ in range(100):
        if sent:
            break
        await asyncio.sleep(0.01)
    assert len(sent) == 1 and "waits for the farm operator" in sent[0]
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/review", json={"action": "approve"}, headers=H("u_op"))).status_code == 200
    await asyncio.wait_for(follower, 10)
    assert len(sent) == 2 and "Pay and follow the order" in sent[1]
    await bot.http.aclose()
