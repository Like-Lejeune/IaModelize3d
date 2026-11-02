"""Fakes for the shop tests: a temp database, people named by a header, and model/slicer hooks that answer with
real numbers (OrcaSlicer runs and Muse Spark intake answers recorded in tests/fixtures/shop)."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import cv2
import httpx
import numpy as np
from fastapi import Request, Response

from formwright import db as dbmod, events
from formwright.app import app
from formwright.config import settings
from formwright.db import get_db, new_id, now
from formwright.shop import autoquote, intake, routes, store

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "shop"
CALIB = json.loads((FIXTURES / "calibration.json").read_text(encoding="utf-8"))["points"]
WHEEL = next(r for r in CALIB if r["title"] == "Exact Part Replica")  # 41.19 g, 126.4 min on Orca
CASES = {c["name"]: c for c in json.loads((FIXTURES / "intake_cases.json").read_text(encoding="utf-8"))["cases"]}


def answer(case: str) -> dict[str, Any]:
    c = copy.deepcopy(CASES[case])
    return intake.combine(c["spark"], c["open"], spark_model=c["spark_model"], open_model=c["open_model"])


class FakeHooks(routes.Hooks):
    def __init__(self) -> None:
        self.qc_results: list[dict] = []
        self.slices: list[dict] = []
        self.designs: list[dict] = []
        self.answers: list[str] = []
        self.numbers: dict[str, tuple[float, float]] = {}  # project_id -> Orca (grams, minutes)
        self.slice_error: Exception | None = None
        self.slice_delay = 0.0
        self.active = self.max_active = 0

    async def current_user(self, request: Request, response: Response):
        uid = request.headers.get("x-user", "u_anon")
        db = await get_db()
        if not await db.one("SELECT id FROM users WHERE id = ?", uid):
            await db.insert("users", {"id": uid, "tier": "anon", "created_at": now()})
        return await db.one("SELECT * FROM users WHERE id = ?", uid)

    async def intake(self, user, text, photos):
        t = text.lower()
        if "gas" in t:
            return answer("gas_knob")
        if "review-me" in t:
            return answer("gas_knob_spark_ok_open_unsafe")
        return answer("voice_wheel_plate_a4")

    async def start_design(self, user, project, text, asset_ids, language=None, shown=None):
        jid = new_id("j_")
        db = await get_db()
        await db.insert("jobs", {"id": jid, "project_id": project["id"], "user_id": user["id"], "kind": "design", "status": "running",
                                 "input": {"text": text}, "created_at": now()})
        self.designs.append({"user": user["id"], "project": project["id"], "text": text, "asset_ids": asset_ids, "job": jid, "language": language,
                             "shown": shown})
        return jid

    async def slice(self, project_id, version, printer_id, material, fingerprint):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.slice_delay:
                await asyncio.sleep(self.slice_delay)
            if self.slice_error:
                raise self.slice_error
            n = len(self.slices) + 1
            self.slices.append({"project": project_id, "version": version, "preset": printer_id, "material": material, "fingerprint": fingerprint})
            g, m = self.numbers.get(project_id, (WHEEL["orca_g"], WHEEL["orca_min"]))
            return {"id": f"s_{n}", "material": material, "printer": {"id": printer_id, "name": printer_id},
                    "stats": {"grams": g, "minutes": m, "supports": True, "warnings": [], "slice_seconds": 12.2},
                    "files": {"gcode": f"/files/{project_id}/slices/s_{n}/part.gcode", "project_3mf": f"/files/{project_id}/slices/s_{n}/part.3mf"}}
        finally:
            self.active -= 1

    async def qc(self, user, order, data, filename, mime):
        return self.qc_results.pop(0)

    async def fingerprint(self, user, asset):
        return {"measured": {"holes": {"5": 4.8}}, "fingerprint": {"holeDelta": 0.2, "outerDelta": 0.05, "confidence": 0.6}}

    async def answer(self, job_id, user_id, text):
        db = await get_db()
        await db.execute("UPDATE jobs SET status = 'running' WHERE id = ? AND status = 'waiting'", job_id)
        self.answers.append(text)
        return True


async def setup(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    """A fresh database with the Axo farm and its operator u_op; nothing can reach a model."""
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir(exist_ok=True)
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings(), "open_base_url", "")
    monkeypatch.setattr(settings(), "blur_faces", False)
    await dbmod.close_db()
    db = await get_db()
    await store.ensure(db)
    hooks = FakeHooks()
    monkeypatch.setattr(routes, "hooks", hooks)

    async def fast_wait(project_id: str, timeout: float = 15.0) -> None:
        await asyncio.sleep(0.01)

    monkeypatch.setattr(events, "wait", fast_wait)
    await db.insert("users", {"id": "u_op", "tier": "pro", "created_at": now()})
    await db.insert("shop_orgs", {"id": "org_axo", "name": "Axo", "kind": "farm", "tier": "farm", "created_at": now()})
    await db.insert("shop_members", {"org_id": "org_axo", "user_id": "u_op", "role": "operator"})
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return SimpleNamespace(db=db, hooks=hooks, c=client)


async def teardown(env: SimpleNamespace) -> None:
    # design watchers outlive a test (they follow a job for up to an hour): stop them before the database goes
    tasks = [t for t in autoquote._tasks.values() if not t.done()]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    autoquote._tasks.clear()
    await env.c.aclose()
    await dbmod.close_db()


async def wait_for(env: SimpleNamespace, order_id: str, *statuses: str, idle: bool = False, timeout: float = 5.0) -> dict[str, Any]:
    """The order once it reaches one of `statuses` (and, with idle, once no step of it runs)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        o = await store.get(env.db, order_id)
        if o and o["status"] in statuses and not (idle and autoquote.running(order_id)):
            return o
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"order {order_id} stayed {o and o['status']} (problem {o and o.get('problem')})")
        await asyncio.sleep(0.01)


def jpeg(w: int = 320, h: int = 240) -> bytes:
    img = np.full((h, w, 3), 230, np.uint8)
    cv2.circle(img, (w // 2, h // 2), min(w, h) // 5, (90, 90, 95), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


async def add_program(db, project_id: str, version: int = 1, est: tuple[float, float] = (WHEEL["est_g"], WHEEL["est_min"]), ok: bool = True) -> None:
    await db.insert("programs", {"project_id": project_id, "version": version, "source": "return lib.box(10,10,10)", "params": {}, "inputs": {},
                                 "checks": {"ok": ok, "stats": {"estGrams": est[0], "estMinutes": est[1]}}, "author": "agent", "created_at": now()})
    await db.execute("UPDATE projects SET version = ? WHERE id = ?", version, project_id)


async def finish_design(env: SimpleNamespace, order_id: str, *, version: int = 1, critic: str | None = "pass") -> None:
    """What the agent leaves behind: a version, its hand-over message with the critic's verdict, the job done."""
    o = await store.get(env.db, order_id)
    await add_program(env.db, o["project_id"], version)
    if critic:
        await env.db.insert("messages", {"id": new_id("msg_"), "project_id": o["project_id"], "role": "agent", "text": "done",
                                         "data": {"version": version, "critic": {"verdict": critic}}, "created_at": now()})
    await env.db.execute("UPDATE jobs SET status = 'done', finished_at = ? WHERE project_id = ?", now(), o["project_id"])
    await events.emit(o["project_id"], "job.finished", {"status": "done"})
    # the watcher sees the job end and quotes
    await wait_for(env, order_id, "quoted", "requested", "paid", "cancelled", "refused", idle=True)
