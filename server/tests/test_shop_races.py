"""Slow steps of an order against what people do meanwhile: a requote that lands after Pay, a cancel or a hand quote
during the intake, a reprint after a QC pass, a QC answer after a Reprint, a held request behind 50 unpaid quotes,
a design that stopped with a failing model, and the catalog's critic badge (offline: shop_fakes' temp DB and hooks)."""
from __future__ import annotations

import asyncio

import pytest

from iamodelize3d import events
from iamodelize3d.db import new_id, now
from iamodelize3d.shop import autoquote, routes, store

from shop_fakes import add_program, answer, jpeg, setup, teardown, wait_for


@pytest.fixture
async def env(tmp_path, monkeypatch):
    e = await setup(tmp_path, monkeypatch)
    yield e
    await teardown(e)


def H(user: str) -> dict[str, str]:
    return {"x-user": user}


async def _project(env, user: str, title: str = "Bracket") -> str:
    pid = new_id("p_")
    if not await env.db.one("SELECT id FROM users WHERE id = ?", user):
        await env.db.insert("users", {"id": user, "tier": "anon", "created_at": now()})
    await env.db.insert("projects", {"id": pid, "user_id": user, "title": title, "pack": "household", "created_at": now(), "updated_at": now()})
    return pid


async def _quoted_studio_order(env, user: str = "u_lea") -> dict:
    pid = await _project(env, user)
    await add_program(env.db, pid)
    o = (await env.c.post("/api/shop/requests", data={"project_id": pid, "quantity": "1"}, headers=H(user))).json()
    return await wait_for(env, o["id"], "quoted", idle=True)


async def _in_qc(env, o: dict) -> str:
    pr = (await env.c.post("/api/shop/ops/printers", json={"name": "A1 #1", "material": "PLA"}, headers=H("u_op"))).json()
    await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))
    await env.c.post(f"/api/shop/orders/{o['id']}/assign", json={"printer_id": pr["id"]}, headers=H("u_op"))
    await env.c.post(f"/api/shop/orders/{o['id']}/printed", headers=H("u_op"))
    return pr["id"]


async def test_a_requote_that_lands_after_pay_leaves_the_paid_order_alone(env):
    o = await _quoted_studio_order(env)
    env.hooks.slice_delay = 0.5
    rq = asyncio.create_task(env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"quantity": 5}, headers=H("u_lea")))
    await asyncio.sleep(0.15)
    paid = await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_lea"))
    r = await rq
    after = await store.get(env.db, o["id"])
    assert paid.status_code == 200 and after["status"] == "paid"
    assert r.status_code == 409 and r.json()["code"] == "order_conflict"
    assert after["quantity"] == 1 and after["quote"]["total"] == after["payment"]["amount"] == o["quote"]["total"]


async def test_cancelling_during_the_intake_starts_no_designer(env):
    gate = asyncio.Event()

    async def slow_intake(user, text, photos):
        await gate.wait()
        return answer("voice_wheel_plate_a4")

    env.hooks.intake = slow_intake
    o = (await env.c.post("/api/shop/requests", data={"text": "dishwasher wheel"}, headers=H("u_ann"))).json()
    await asyncio.sleep(0.05)
    c = await env.c.post(f"/api/shop/orders/{o['id']}/cancel", headers=H("u_ann"))
    assert c.status_code == 200 and c.json()["status"] == "cancelled"
    gate.set()
    await autoquote.drain(3)
    assert (await store.get(env.db, o["id"]))["status"] == "cancelled"
    assert env.hooks.designs == []


async def test_cancelling_a_designing_order_stops_its_design_job(env):
    o = (await env.c.post("/api/shop/requests", data={"text": "dishwasher wheel"}, headers=H("u_ann"))).json()
    await wait_for(env, o["id"], "designing")
    job = env.hooks.designs[0]["job"]
    c = await env.c.post(f"/api/shop/orders/{o['id']}/cancel", headers=H("u_ann"))
    assert c.status_code == 200 and c.json()["status"] == "cancelled"
    assert (await env.db.one("SELECT status FROM jobs WHERE id = ?", job))["status"] == "cancelled"


async def test_a_safety_refusal_wins_over_a_hand_quote_made_during_the_intake(env):
    gate = asyncio.Event()

    async def slow_intake(user, text, photos):
        await gate.wait()
        return answer("gas_knob")

    env.hooks.intake = slow_intake
    o = (await env.c.post("/api/shop/requests", data={"text": "gas stove knob"}, headers=H("u_ann"),
                          files=[("files", ("knob.jpg", jpeg(), "image/jpeg"))])).json()
    await add_program(env.db, o["project_id"])  # the farm made a model for it in the studio
    q = await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"grams_each": 10, "minutes_each": 30}, headers=H("u_op"))
    assert q.status_code == 200 and q.json()["status"] == "quoted"
    gate.set()
    await autoquote.drain(3)
    after = await store.get(env.db, o["id"])
    assert after["intake"]["refuse"] is True and after["status"] == "refused"


async def test_a_reprint_after_a_qc_pass_needs_its_own_qc(env):
    o = await _quoted_studio_order(env)
    printer = await _in_qc(env, o)
    env.hooks.qc_results = [{"pass": True, "max_mm": 0.3, "tolerance_mm": 0.6}]
    good = (await env.c.post(f"/api/shop/orders/{o['id']}/qc", files={"file": ("qc.jpg", jpeg(), "image/jpeg")}, headers=H("u_op"))).json()
    assert good["qc"]["pass"]
    back = (await env.c.post(f"/api/shop/orders/{o['id']}/reprint", json={"note": "stringing"}, headers=H("u_op"))).json()
    assert back["status"] == "paid" and not back["qc"].get("pass")
    await env.c.post(f"/api/shop/orders/{o['id']}/assign", json={"printer_id": printer}, headers=H("u_op"))
    q = (await env.c.post(f"/api/shop/orders/{o['id']}/printed", headers=H("u_op"))).json()
    assert q["status"] == "qc" and "shipped" not in q["next"]
    s = await env.c.post(f"/api/shop/orders/{o['id']}/ship", json={"carrier": "Kazpost", "tracking": "KZ1"}, headers=H("u_op"))
    assert s.status_code == 409
    # the journal still has the first print's pass
    assert "qc_pass" in [(t.get("data") or {}).get("code") for t in await store.timeline(env.db, o["id"])]


async def test_a_qc_answer_after_a_reprint_is_a_conflict_not_a_500(env):
    o = await _quoted_studio_order(env)
    await _in_qc(env, o)
    gate = asyncio.Event()

    async def slow_qc(user, order, data, filename, mime):
        await gate.wait()
        return {"pass": False, "max_mm": 1.4, "tolerance_mm": 0.6}

    env.hooks.qc = slow_qc
    t = asyncio.create_task(env.c.post(f"/api/shop/orders/{o['id']}/qc", files={"file": ("qc.jpg", jpeg(), "image/jpeg")}, headers=H("u_op")))
    await asyncio.sleep(0.1)
    rp = await env.c.post(f"/api/shop/orders/{o['id']}/reprint", json={"note": "warped"}, headers=H("u_op"))
    gate.set()
    r = await t
    assert rp.status_code == 200 and r.status_code == 409 and r.json()["code"] == "order_conflict"
    after = await store.get(env.db, o["id"])
    assert after["status"] == "paid" and not after["qc"]


async def test_a_held_request_shows_on_the_board_behind_many_unpaid_quotes(env, monkeypatch):
    real = store.upstream
    monkeypatch.setattr(store, "upstream", lambda db, limit=5: real(db, limit))  # 5 slots stand in for 50
    for i in range(5):
        await _quoted_studio_order(env, f"u_{i:02d}")
    held = (await env.c.post("/api/shop/requests", data={"text": "review-me stove knob"}, headers=H("u_new"))).json()
    o = await wait_for(env, held["id"], "requested", idle=True)
    assert o["intake"].get("review")
    board = (await env.c.get("/api/shop/ops/queue", headers=H("u_op"))).json()
    assert held["id"] in [x["id"] for x in board["upstream"]]


async def test_a_design_that_stopped_with_a_failing_model_is_not_quoted(env):
    o = (await env.c.post("/api/shop/requests", data={"text": "dishwasher wheel"}, headers=H("u_ann"))).json()
    await wait_for(env, o["id"], "designing")
    await add_program(env.db, o["project_id"], 1, ok=False)
    await env.db.execute("UPDATE jobs SET status = 'budget', finished_at = ? WHERE project_id = ?", now(), o["project_id"])
    await events.emit(o["project_id"], "job.finished", {"status": "budget"})
    await autoquote.drain(3)
    after = await store.get(env.db, o["id"])
    assert after["status"] == "designing" and after["problem"]["code"] == "design_unfinished" and env.hooks.slices == []
    # reconcile leaves it to the operator, who can still quote it by hand
    assert await autoquote.reconcile(env.db) == 0
    q = await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={}, headers=H("u_op"))
    assert q.status_code == 200 and q.json()["status"] == "quoted"


async def _handed_over(env, pid: str, data: dict, n: int) -> None:
    await env.db.insert("messages", {"id": new_id("msg_"), "project_id": pid, "role": "agent", "text": "done", "data": data, "created_at": now() + n})


async def test_the_critic_badge_needs_a_real_review_of_that_version(env):
    pid = await _project(env, "u_kim", "Clip")
    await add_program(env.db, pid, 1)
    await add_program(env.db, pid, 2)
    # a run cut short after v2 carries v1's review
    await _handed_over(env, pid, {"version": 2, "critic": {"verdict": "pass", "version": 1}}, 1)
    assert (await routes.share(env.db, "u_kim", pid, public=False))["verified"]["critic"] is None
    # the stand-in tools._finish writes when the reviewer did not answer
    await _handed_over(env, pid, {"version": 2, "critic": {"verdict": "pass", "note": "reviewer unavailable", "reviewer": "unavailable", "version": 2}}, 2)
    assert (await routes.share(env.db, "u_kim", pid, public=False))["verified"]["critic"] is None
    await _handed_over(env, pid, {"version": 2, "critic": {"verdict": "pass", "version": 2}}, 3)
    assert (await routes.share(env.db, "u_kim", pid, public=False))["verified"]["critic"] == "pass"
