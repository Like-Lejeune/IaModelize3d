"""What happens when something fails: orders are not doubled, a missing price is not zero, nothing raw reaches people, and
what could not run is said to have not run."""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from formwright import catalog, events, idempotency, storage
from formwright.agent import critic, narrate
from formwright.agent.tools import DesignState, _finish
from formwright.db import close_db, get_db
from formwright.deviceapi import bom_of
from formwright.geom import CRASHED, GeomError, _Worker


@pytest.fixture
async def db(tmp_path, monkeypatch):
    from formwright.config import settings

    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir(exist_ok=True)
    await close_db()
    yield await get_db()
    await close_db()


async def test_a_retry_with_the_same_key_gets_the_first_order(db):
    made: list[str] = []

    async def make():
        made.append("o")
        return {"id": f"o{len(made)}"}

    async def again(ref):
        return {"id": ref, "again": True}

    first = await idempotency.once("u", "s", "k", make, again)
    second = await idempotency.once("u", "s", "k", make, again)
    assert first == {"id": "o1"} and second == {"id": "o1", "again": True} and len(made) == 1
    assert (await idempotency.once("u", "s", "other", make, again))["id"] == "o2"  # another key is another order
    assert (await idempotency.once("u2", "s", "k", make, again))["id"] == "o3"  # and so is another person's
    assert (await idempotency.once("u", "s", None, make, again))["id"] == "o4"  # no header: as before
    assert (await idempotency.once("u", "s", None, make, again))["id"] == "o5"


async def test_two_requests_at_once_make_one_order(db):
    made: list[int] = []

    async def make():
        made.append(1)
        await asyncio.sleep(0.05)
        return {"id": "o1"}

    async def again(ref):
        return {"id": ref}

    out = await asyncio.gather(*(idempotency.once("u", "s", "k", make, again) for _ in range(3)))
    assert len(made) == 1 and [o["id"] for o in out] == ["o1"] * 3


async def test_a_failed_request_gives_its_key_back(db):
    tries = []

    async def make():
        tries.append(1)
        if len(tries) == 1:
            raise RuntimeError("no")
        return {"id": "o1"}

    async def again(ref):
        return {"id": ref}

    with pytest.raises(RuntimeError):
        await idempotency.once("u", "s", "k", make, again)
    assert (await idempotency.once("u", "s", "k", make, again))["id"] == "o1"

    async def refused():
        return {"status": "error"}

    await idempotency.once("u", "s", "k2", refused, again, ref=lambda r: r.get("order_id"))
    assert (await db.one("SELECT COUNT(*) AS n FROM idempotency WHERE idem_key = 'k2'"))["n"] == 0


def test_a_part_the_catalogue_did_not_answer_for_has_no_price_and_no_stock():
    doc = {"nodes": [{"id": "R1", "kind": "resistor"}, {"id": "R2", "kind": "resistor"}]}
    parts = {"R1": {"error": "the parts catalogue did not answer"}, "R2": {"lcsc": "C1", "prices": [{"qty": 1, "usd": 0.01}], "stock": 100}}
    rows = {b["refs"][0]: b for b in bom_of(doc, parts, 1)["bom"]}
    assert rows["R1"]["unpriced"] is True and rows["R1"]["in_stock"] is False
    assert "unpriced" not in rows["R2"] and rows["R2"]["in_stock"] is True


async def test_a_damaged_catalogue_file_is_a_miss_and_goes(tmp_path):
    path = tmp_path / "C1.json"
    path.write_text('{"half', encoding="utf-8")
    assert catalog._cached(path) is catalog.MISS and not path.exists()
    catalog._cache(path, b'{"a": 1}')
    assert catalog._cached(path) == {"a": 1} and [p.name for p in tmp_path.iterdir()] == ["C1.json"]


def test_a_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / "x.bin"
    storage.write_atomic(path, b"one")

    def boom(*_):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        storage.write_atomic(path, b"two")
    assert path.read_bytes() == b"one" and [p.name for p in tmp_path.iterdir()] == ["x.bin"]


async def test_nobody_left_listening_leaves_no_waiter_behind():
    await events.wait("p_gone", 0.01)
    assert "p_gone" not in events._waiters and "p_gone" not in events._listeners


class _Script(_Worker):
    """A worker that runs a Python script instead of node."""

    def __init__(self, script: str) -> None:
        super().__init__()
        self.script = script


async def _start(self) -> None:
    pipe = asyncio.subprocess.PIPE
    self.proc = await asyncio.create_subprocess_exec(sys.executable, "-c", self.script, stdin=pipe, stdout=pipe, stderr=pipe)
    self._drain = asyncio.create_task(self._read_stderr(self.proc))
    await asyncio.wait_for(self.proc.stdout.readline(), 10)


async def test_a_crashed_worker_tells_nobody_its_stderr(monkeypatch, caplog):
    monkeypatch.setattr(_Script, "start", _start)
    w = _Script("import sys\nprint('ready', flush=True)\nsys.stdin.readline()\nsys.stderr.write('C:/secret/path boom')\nsys.exit(1)\n")
    with pytest.raises(GeomError) as e:
        await w.call("build", {}, 10)
    assert e.value.stage == "crash" and e.value.message == CRASHED and "secret" not in str(e.value)
    assert w.proc is None


async def test_a_call_waiting_for_a_busy_worker_times_out(monkeypatch):
    monkeypatch.setattr(_Script, "start", _start)
    w = _Script("print('ready', flush=True)\n")
    await w.lock.acquire()
    with pytest.raises(GeomError) as e:
        await w.call("build", {}, 0.05)
    w.lock.release()
    assert e.value.stage == "timeout" and "busy" in e.value.message and not w.lock.locked()


def _ctx():
    async def emit(*_a, **_k):
        return None

    async def status(*_a, **_k):
        return None

    return SimpleNamespace(project={"brief": {"language": "ru"}}, project_id="p", job_id="j", emit=emit, status=status)


async def test_an_unavailable_reviewer_is_no_pass_and_is_said(monkeypatch):
    async def nobody(ctx, state, bar=None):
        return {"reviewer": "unavailable"}

    monkeypatch.setattr(critic, "review", nobody)
    state = DesignState(pack="household", source="x", version=3, last_build={"checks": {"issues": []}}, last_render="r.png")
    assert (await _finish(_ctx(), state, "готово"))["accepted"] is True
    assert state.critic["verdict"] == "unavailable" and state.critic["version"] == 3
    assert narrate.review_of(state.critic, 3) == "none"
    assert narrate.result_title("finish", {}, {"accepted": True, "review": "none"}).startswith("Handed over without")


async def test_a_check_that_could_not_run_is_no_approval(monkeypatch):
    from formwright.agent import elec_tools

    async def crashed(ctx, state):
        state.unchecked.append("case_check")
        return []

    async def passed(ctx, state, bar=None):
        return {"verdict": "pass", "match_score": 9, "issues": []}

    monkeypatch.setattr(elec_tools, "finish_gate", crashed)
    monkeypatch.setattr(critic, "review", passed)
    state = DesignState(pack="enclosure", source="x", version=3, last_build={"checks": {"issues": []}}, last_render="r.png")
    out = await _finish(_ctx(), state, "готово")
    assert out["accepted"] is True and out["unchecked"] == ["case_check"] and "проверка корпуса" in state.summary
    assert narrate.result_title("finish", {}, out) == "Handed over; a check could not run"


async def test_rules_that_crash_say_they_did_not_run(monkeypatch):
    from formwright import device_rules
    from formwright.agent import device_tools

    def boom(*_):
        raise RuntimeError("bug")

    monkeypatch.setattr(device_rules, "check", boom)
    items = await device_tools.design_checks({"nodes": []}, {})
    assert [i["code"] for i in items] == ["rules_not_run"] and items[0]["severity"] != "error"


async def test_a_pass_with_a_major_issue_is_a_revise_and_a_missing_picture_does_not_stop_the_review(db, monkeypatch):
    seen = {}

    class Model:
        def model_for(self, role, default):
            return default

        async def json(self, meter, **kw):
            seen.update(kw)
            return {"verdict": "pass", "match_score": 7, "issues": [{"severity": "major", "text": "the hook is upside down"}]}

    async def no_legend(*_):
        return []

    monkeypatch.setattr(critic, "meta", lambda: Model())
    ctx = SimpleNamespace(project={"brief": {}}, project_id="p", job_id="j", meter=None, models=SimpleNamespace(fast="m"))
    state = DesignState(pack="household", source="x", version=2, last_build={"checks": {}}, last_render="gone/v2.png")
    state.copies_photo = False
    v = await critic.review(ctx, state)
    assert v["verdict"] == "revise" and v["version"] == 2
    texts = [c["text"] for c in seen["content"] if c["type"] == "input_text"]
    assert not [c for c in seen["content"] if c["type"] == "input_image"] and "could not be shown" in texts[-1]
