"""Automatic quoting: the design job's end quotes the order, a question parks it in needs_info, a restart is picked up
by the lazy reconcile, a studio model skips design, one slicer run at a time, and the instant range covers OrcaSlicer."""
from __future__ import annotations

import asyncio

import pytest

from formwright import events
from formwright.db import new_id, now
from formwright.printing.service import SliceError
from formwright.shop import autoquote, store

from shop_fakes import CALIB, WHEEL, add_program, finish_design, setup, teardown, wait_for


@pytest.fixture
async def env(tmp_path, monkeypatch):
    e = await setup(tmp_path, monkeypatch)
    yield e
    await teardown(e)


def H(user: str) -> dict[str, str]:
    return {"x-user": user}


async def _project(env, user: str, title: str = "Bracket", pack: str = "household") -> str:
    pid = new_id("p_")
    if not await env.db.one("SELECT id FROM users WHERE id = ?", user):
        await env.db.insert("users", {"id": user, "tier": "anon", "created_at": now()})
    await env.db.insert("projects", {"id": pid, "user_id": user, "title": title, "pack": pack, "created_at": now(), "updated_at": now()})
    return pid


async def test_design_end_quotes_and_a_question_parks_the_order(env):
    c = env.c
    o = (await c.post("/api/shop/requests", data={"text": "dishwasher wheel"}, headers=H("u_ann"))).json()
    await wait_for(env, o["id"], "designing")
    job = env.hooks.designs[0]["job"]
    # the agent asks: the order waits for the customer, who answers from the order page
    await env.db.execute("UPDATE jobs SET status = 'waiting' WHERE id = ?", job)
    await events.emit(o["project_id"], "ask", {"question": "Is the axle 5 or 6 mm?", "options": ["5 mm", "6 mm"]}, job)
    await wait_for(env, o["id"], "needs_info")
    page = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_ann"))).json()
    assert page["question"]["question"] == "Is the axle 5 or 6 mm?" and page["next"] == ["designing", "cancelled"]
    assert (await c.post(f"/api/shop/orders/{o['id']}/answer", json={"text": "5 mm"}, headers=H("u_bob"))).status_code == 403
    page = (await c.post(f"/api/shop/orders/{o['id']}/answer", json={"text": "5 mm"}, headers=H("u_ann"))).json()
    assert env.hooks.answers == ["5 mm"] and page["intake"]["answers"][0]["text"] == "5 mm"
    await wait_for(env, o["id"], "designing")
    await finish_design(env, o["id"])
    o = (await c.get(f"/api/shop/orders/{o['id']}", headers=H("u_ann"))).json()
    assert o["status"] == "quoted" and o["quote"]["source"] == "orca" and o["version"] == 1
    assert [t["status"] for t in o["timeline"]] == ["requested", "requested", "designing", "needs_info", "designing", "quoted"]
    # a customer asks for another material: quoted again on the slicer, still quoted
    again = (await c.post(f"/api/shop/orders/{o['id']}/quote", json={"material": "asa", "quantity": 2}, headers=H("u_ann"))).json()
    assert again["status"] == "quoted" and again["material"] == "ASA" and again["quantity"] == 2 and env.hooks.slices[-1]["material"] == "ASA"
    bad = await c.post(f"/api/shop/orders/{o['id']}/quote", json={"material": "nylon"}, headers=H("u_ann"))
    assert bad.status_code == 409 and bad.json()["code"] == "bad_material"


async def test_reconcile_picks_up_orders_after_a_restart(env):
    # what a restart leaves: the design job closed as failed by recover_interrupted, a model already there, no watcher
    pid = await _project(env, "u_kim")
    await add_program(env.db, pid)
    jid = new_id("j_")
    await env.db.insert("jobs", {"id": jid, "project_id": pid, "user_id": "u_kim", "kind": "design", "status": "failed", "input": {}, "created_at": now()})
    o = await store.create_order(env.db, user_id="u_kim", project_id=pid, intake={"refuse": False, "request": {"kind": "photo"}}, status="designing")
    await store.log(env.db, o["id"], "requested", "designing", "system", None, "the agent is measuring and designing", {"job_id": jid})
    # no model at all for another one: it is flagged once, not retried on every poll
    empty = await _project(env, "u_kim")
    o2 = await store.create_order(env.db, user_id="u_kim", project_id=empty, intake={"refuse": False}, status="designing")
    assert not autoquote.running(o["id"])
    for _ in range(3):
        await env.c.get("/api/shop/ops/queue", headers=H("u_op"))
    await wait_for(env, o["id"], "quoted", idle=True)
    o2 = await store.get(env.db, o2["id"])
    assert o2["status"] == "designing" and o2["problem"]["code"] == "no_model"
    assert [t["note"] for t in await store.timeline(env.db, o2["id"])].count(f"no_model: {o2['problem']['detail']}") == 1
    # once the customer finishes the model in the studio, the next poll quotes it
    await add_program(env.db, empty)
    await env.c.get(f"/api/shop/orders/{o2['id']}", headers=H("u_kim"))
    assert (await wait_for(env, o2["id"], "quoted", idle=True))["quote"]["version"] == 1


async def test_studio_model_goes_straight_to_the_slicer(env):
    pid = await _project(env, "u_lea", "Shelf bracket")
    await add_program(env.db, pid)
    r = await env.c.post("/api/shop/requests", data={"project_id": pid, "material": "petg", "quantity": "3"}, headers=H("u_lea"))
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["status"] == "requested" and o["quote"]["binding"] is False and o["quote"]["range"]["total"][0] < o["quote"]["range"]["total"][1]
    o = await wait_for(env, o["id"], "quoted", idle=True)
    assert o["material"] == "PETG" and o["quantity"] == 3 and o["version"] == 1 and env.hooks.designs == []
    # quoted and read at the same time: the journal has both, in whichever order they landed
    assert sorted(t["too"] for t in await store.timeline(env.db, o["id"])) == ["quoted", "requested", "requested"]
    assert o["intake"]["refuse"] is False
    # not your project, or a project with no model
    other = await _project(env, "u_max")
    assert (await env.c.post("/api/shop/requests", data={"project_id": other}, headers=H("u_lea"))).status_code == 403
    mine = await _project(env, "u_lea")
    r = await env.c.post("/api/shop/requests", data={"project_id": mine}, headers=H("u_lea"))
    assert r.status_code == 409 and r.json()["code"] == "no_model"


async def test_instant_range_covers_orca_on_17_calibration_points(env):
    """The instant endpoint's range (kernel estimate) against the firm quote (Orca's numbers for the same model)."""
    inside = []
    # 17 orders open at once: a signed-in person's allowance, not an anonymous visitor's (routes.order_cap)
    await env.db.insert("users", {"id": "u_cal", "tier": "pro", "created_at": now()})
    for r in CALIB:
        pid = await _project(env, "u_cal", r["title"])
        await add_program(env.db, pid, est=(r["est_g"], r["est_min"]))
        env.hooks.numbers[pid] = (r["orca_g"], r["orca_min"])
        band = (await env.c.get(f"/api/shop/instant-quote/{pid}", headers=H("u_cal"))).json()["range"]["total"]
        o = (await env.c.post("/api/shop/requests", data={"project_id": pid, "material": "PLA"}, headers=H("u_cal"))).json()
        firm = (await wait_for(env, o["id"], "quoted", idle=True))["quote"]["total"]
        inside.append(band[0] <= firm <= band[1])
    assert len(inside) == 17 and all(inside)


async def test_one_slice_at_a_time(env):
    env.hooks.slice_delay = 0.05
    ids = []
    for i in range(3):
        pid = await _project(env, "u_sam", f"Part {i}")
        await add_program(env.db, pid)
        # the studio passes the material it priced (with "choose for me" the intake's own pick is sliced as well)
        ids.append((await env.c.post("/api/shop/requests", data={"project_id": pid, "material": "PLA"}, headers=H("u_sam"))).json()["id"])
    for oid in ids:
        await wait_for(env, oid, "quoted", idle=True)
    assert env.hooks.max_active == 1 and len(env.hooks.slices) == 3


async def test_no_slicer_leaves_the_quote_to_the_operator(env):
    env.hooks.slice_error = SliceError("OrcaSlicer is not installed on this server (set FW_ORCA_BIN)")
    pid = await _project(env, "u_ola")
    await add_program(env.db, pid)
    o = (await env.c.post("/api/shop/requests", data={"project_id": pid}, headers=H("u_ola"))).json()
    o = await wait_for(env, o["id"], "requested", idle=True)
    assert o["problem"]["code"] == "slice_failed" and "OrcaSlicer" in o["problem"]["detail"]
    page = (await env.c.get(f"/api/shop/orders/{o['id']}", headers=H("u_ola"))).json()
    assert "paid" not in page["next"] and page["quote"]["binding"] is False  # only the instant range: nothing to pay yet
    assert not autoquote.running(o["id"])  # not retried on every poll
    # a customer cannot quote by hand; the operator can, with numbers from their own slicer
    assert (await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"grams_each": 40, "minutes_each": 120}, headers=H("u_ola"))).status_code == 409
    q = (await env.c.post(f"/api/shop/orders/{o['id']}/quote", json={"grams_each": 40, "minutes_each": 120}, headers=H("u_op"))).json()
    assert q["status"] == "quoted" and q["quote"]["source"] == "operator" and q["quote"]["binding"] and q["problem"] == {}
    # an expired quote cannot be paid
    await store.patch(env.db, o["id"], {"quote": {**q["quote"], "valid_until": now() - 1}})
    r = await env.c.post(f"/api/shop/orders/{o['id']}/pay", headers=H("u_ola"))
    assert r.status_code == 409 and r.json()["code"] == "quote_expired"


async def test_farm_printer_fingerprint_is_its_own(env):
    a = (await env.c.post("/api/shop/ops/printers", json={"name": "A1 #1", "material": "PLA"}, headers=H("u_op"))).json()
    b = (await env.c.post("/api/shop/ops/printers", json={"name": "A1 #2", "material": "PLA"}, headers=H("u_op"))).json()
    assert a["preset_id"] == b["preset_id"] == "bambu-lab-a1-0-4-nozzle"
    bad = await env.c.post("/api/shop/ops/printers", json={"name": "X", "preset_id": "no such printer"}, headers=H("u_op"))
    assert bad.status_code == 400 and bad.json()["code"] == "bad_preset"
    from shop_fakes import jpeg

    fp = (await env.c.post(f"/api/shop/ops/printers/{a['id']}/fingerprint", files={"file": ("coupon.jpg", jpeg(), "image/jpeg")}, headers=H("u_op"))).json()
    assert fp["fingerprint"]["holeDelta"] == 0.2
    assert (await env.db.one("SELECT fingerprint FROM shop_printers WHERE id = ?", b["id"]))["fingerprint"] == {}
    # a quote sliced on printer A carries A's fingerprint to the slicer
    pid = await _project(env, "u_pia")
    await add_program(env.db, pid)
    o = (await env.c.post("/api/shop/requests", data={"project_id": pid}, headers=H("u_pia"))).json()
    await wait_for(env, o["id"], "quoted", idle=True)
    assert env.hooks.slices[-1]["fingerprint"]["holeDelta"] == 0.2
    maint = (await env.c.post(f"/api/shop/ops/printers/{a['id']}", json={"state": "maintenance"}, headers=H("u_op"))).json()
    assert maint["state"] == "maintenance"
    assert WHEEL["orca_g"] > 0


async def test_drain_gives_up_on_a_hung_step():
    # the timeout bounds the whole wait: a step that never ends no longer keeps drain (and a shutdown) waiting forever
    hung = asyncio.Event()
    assert autoquote.spawn("o_hung", hung.wait())
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    try:
        await asyncio.wait_for(autoquote.drain(0.3), 5)
        assert loop.time() - t0 < 2
    finally:
        hung.set()
        await autoquote.drain(2)
