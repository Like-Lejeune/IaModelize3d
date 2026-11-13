"""The design loop hands over honestly when budget, the API or its turns run out, never goes quiet while the
model thinks, and turns a picked Muse Image concept into a cut-out target. Offline: the model and tools are stubs."""
import asyncio
import copy
import io
import json
import time
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from openai import APIStatusError
from PIL import Image

from iamodelize3d import db as dbmod, events, storage
from iamodelize3d.agent import compare, loop, narrate, side
from iamodelize3d.agent.runner import JobContext
from iamodelize3d.config import settings
from iamodelize3d.llm.client import BudgetExceeded, CostMeter
from iamodelize3d.models import SendMessage
from iamodelize3d.quotas import ModelChoice


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


def _png(w: int = 64, h: int = 48) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.full((h, w, 3), 200, np.uint8)).save(buf, "PNG")
    return buf.getvalue()


async def _project(db, pid: str = "p1", **brief) -> JobContext:
    t = dbmod.now()
    await db.insert("projects", {"id": pid, "user_id": "u1", "title": "Shelf bracket", "pack": "household", "brief": brief, "created_at": t, "updated_at": t})
    project = await db.one("SELECT * FROM projects WHERE id = ?", pid)
    return JobContext(job_id="j1", kind="design", project=project, user={"id": "u1"}, meter=CostMeter(budget_usd=0.6),
                      models=ModelChoice(designer="muse-spark-1.3", fast="muse-spark-1.3", contributor=False))


def call(name: str, args: dict | str, cid: str = "c1") -> dict:
    return {"type": "function_call", "call_id": cid, "name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}


def say(text: str) -> dict:
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


class FakeMeta:
    """Plays a script: each respond() takes the next step, an exception is raised, a list becomes the output."""

    def __init__(self, script, cls=None):
        self.script = list(script)
        self.cls = cls or {}
        self.calls: list[dict] = []

    async def respond(self, meter, **kw):
        self.calls.append({**kw, "input": copy.deepcopy(kw["input"])})
        step = self.script.pop(0)
        if callable(step):
            step = await step(kw)
        if isinstance(step, BaseException):
            raise step
        status = "incomplete" if step and step[0] == "cut" else "completed"
        return SimpleNamespace(output=[s for s in step if s != "cut"], status=status)

    async def json(self, meter, **kw):
        return self.cls


def fake_tools(tool_log: list, outcome=None):
    """write/edit build a version, finish accepts (or what `outcome` says)."""

    async def run_tool(ctx, state, name, args):
        tool_log.append((name, args, state.copies_photo))
        if name in ("write_program", "edit_program"):
            state.version += 1
            state.source = "return {}"
            state.last_build = {"checks": {"ok": True, "stats": {"size": [40, 20, 10]}}, "paramSpecs": {}}
            rel = storage.save_bytes(ctx.project_id, "renders", f"v{state.version}.png", _png())
            storage.save_bytes(ctx.project_id, "renders", f"v{state.version}_iso.png", _png())
            return {"ok": True, "version": state.version, "size_mm": [40, 20, 10], "printable": True}, [rel]
        if name == "finish":
            if outcome:
                return outcome(state), []
            state.done, state.summary = True, args.get("summary", "")
            return {"accepted": True}, []
        return {"ok": True}, []

    return run_tool


async def _events(pid: str = "p1") -> list[dict]:
    return await events.since(pid, 0, 10_000)


@pytest.fixture
def offline(monkeypatch):
    """No model, memory or translation calls leave the machine."""
    async def same(meter, text, model):
        return text or ""

    monkeypatch.setattr(loop, "english", same)
    tool_log: list = []
    monkeypatch.setattr(loop, "run_tool", fake_tools(tool_log))
    return tool_log


def _use(monkeypatch, fake: FakeMeta) -> FakeMeta:
    monkeypatch.setattr(loop, "meta", lambda: fake)
    return fake


async def test_budget_after_a_build_hands_over_with_a_result_card(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db)
    _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x", "summary": "first"})], BudgetExceeded("job budget $0.60 reached")]))
    text = await loop.design(ctx, SendMessage(text="a shelf bracket"))
    assert ctx.final_status == "budget"
    evs = await _events()
    msg = next(e for e in evs if e["type"] == "agent.message")["data"]
    assert msg["text"].startswith("Stopped at the spending cap.") and "Version 1" in msg["text"] and "not reviewed" in msg["text"]
    assert text == msg["text"][:300]
    card = next(e for e in evs if e["type"] == "result")["data"]
    assert card["version"] == 1 and card["render"] == "/files/p1/renders/v1_iso.png"
    assert card["reviewed_version"] is None and card["cost"]["usd"] == 0 and "calls" in card["cost"]
    # the runner notes the request as interrupted; the loop does not add it a second time
    assert (await fresh_db.one("SELECT brief FROM projects WHERE id = 'p1'"))["brief"].get("turns", []) == []


async def test_api_error_hands_over_in_the_persons_language(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db, language="ru")
    monkeypatch.setattr(loop, "OUTAGE_PATIENCE_S", 0.0)  # the outage has outlasted the run's patience (test_outage.py)
    gateway = APIStatusError("bad gateway", response=httpx.Response(502, request=httpx.Request("POST", "https://api")), body=None)
    _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x"})], gateway]))
    await loop.design(ctx, SendMessage(text="кронштейн для полки"))
    assert ctx.final_status == "failed"
    msg = next(e for e in await _events() if e["type"] == "agent.message")["data"]["text"]
    assert msg.startswith("Сервис модели перестал отвечать") and "Последняя версия — 1" in msg


async def test_without_a_build_the_error_still_fails_the_job(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db)
    _use(monkeypatch, FakeMeta([BudgetExceeded("job budget $0.60 reached")]))
    with pytest.raises(BudgetExceeded):
        await loop.design(ctx, SendMessage(text="a shelf bracket"))


async def test_out_of_turns_gives_a_localized_handover_not_the_last_mid_work_line(fresh_db, offline, monkeypatch):
    monkeypatch.setattr(settings(), "max_iterations", 1)
    ctx = await _project(fresh_db, language="ru")
    fake = _use(monkeypatch, FakeMeta([[say("Убираю острый нос…"), call("edit_program" if i else "write_program", {"source": "x"}, f"c{i}")] for i in range(3)]))
    await loop.design(ctx, SendMessage(text="кронштейн для полки"))
    msg = next(e for e in await _events() if e["type"] == "agent.message")["data"]["text"]
    assert msg.startswith("Шаги закончились до финальной проверки.") and "Последняя версия — 3" in msg
    assert ctx.final_status is None
    # the wrap-up note went in once, as soon as the turn limit came near
    notes = [p["text"] for item in fake.calls[-1]["input"] if item.get("role") == "user" for p in item["content"]
             if p.get("type") == "input_text" and "close to the" in p.get("text", "")]
    assert notes == [loop.WRAP_UP.format("turn")]


async def test_out_of_turns_still_tells_the_person_what_was_built(fresh_db, offline, monkeypatch):
    """A keypad's and a leak alarm's runs ended in "steps ran out, send a message": nothing on what exists or what was dropped."""
    monkeypatch.setattr(settings(), "max_iterations", 1)
    ctx = await _project(fresh_db, language="ru")
    steps = [[call("edit_program" if i else "write_program", {"source": "x"}, f"c{i}")] for i in range(3)]
    fake = _use(monkeypatch, FakeMeta([*steps, [say("Кронштейн готов, полка 18 мм. Проверку не успел.")]]))
    await loop.design(ctx, SendMessage(text="кронштейн для полки"))
    msg = next(e for e in await _events() if e["type"] == "agent.message")["data"]["text"]
    assert msg.startswith("Кронштейн готов, полка 18 мм.") and "Шаги закончились" in msg
    assert fake.calls[-1]["tools"] == []  # the closing word can call nothing


async def test_stage_reads_design_while_the_first_turn_thinks_and_heartbeats_arrive(fresh_db, offline, monkeypatch):
    monkeypatch.setattr(loop, "HEARTBEAT_S", 0.02)
    ctx = await _project(fresh_db)
    t = dbmod.now()
    # a caliper reading already taken: the job goes through "measure" without any model call
    await fresh_db.insert("assets", {"id": "a_cal", "project_id": "p1", "kind": "caliper", "path": storage.save_bytes("p1", "photos", "cal.png", _png()),
                                     "meta": {"caliper": {"found": True, "value_mm": 12.0}}, "created_at": t})
    stages_at_first_turn: list[str] = []

    async def first(kw):
        stages_at_first_turn.extend(e["data"]["stage"] for e in await _events() if e["type"] == "job.stage")
        await asyncio.sleep(0.15)
        return [say("A plain bracket.")]

    _use(monkeypatch, FakeMeta([first]))
    await loop.design(ctx, SendMessage(text="a shelf bracket", asset_ids=["a_cal"]))
    assert stages_at_first_turn == ["understand", "measure", "design"]
    beats = [e["data"] for e in await _events() if e["type"] == "job.heartbeat"]
    assert len(beats) >= 2 and all(b["stage"] == "design" for b in beats)
    assert [b["seconds"] for b in beats] == sorted(b["seconds"] for b in beats)
    await asyncio.sleep(0.06)
    assert len([e for e in await _events() if e["type"] == "job.heartbeat"]) == len(beats)  # stopped with the turn


async def test_cut_off_arguments_are_not_run_and_the_model_is_told(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db)
    ctx.deadline = time.monotonic() + 600
    fake = _use(monkeypatch, FakeMeta([["cut", call("write_program", '{"source": "function build(p, lib) {')], [say("Shorter next time.")]]))
    await loop.design(ctx, SendMessage(text="a shelf bracket"))
    assert offline == []  # the tool never ran with {}
    sent = fake.calls[1]["input"]
    out = json.loads(next(i for i in sent if i.get("type") == "function_call_output")["output"])
    assert out["ok"] is False and "not valid JSON" in out["error"]
    assert out["turn"] == f"1 of {settings().max_iterations * 3}" and out["budget_left_usd"] == 0.6 and 590 <= out["seconds_left"] <= 600
    assert sent[-1]["content"][0]["text"] == loop.CUT_OFF
    res = next(e for e in await _events() if e["type"] == "tool.result")["data"]
    assert res["title"] == "The answer was cut off, retrying shorter"
    assert next(e for e in await _events() if e["type"] == "tool.call")["data"]["model"] == "muse-spark-1.3"


async def test_tool_errors_get_calm_titles_without_server_paths(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db)
    where = settings().data_dir / "files" / "p1" / "a_1.mp4"

    async def broken(ctx, state, name, args):
        raise OSError(f"cannot identify image file '{where}'")

    monkeypatch.setattr(loop, "run_tool", broken)
    fake = _use(monkeypatch, FakeMeta([[call("look", {"what": "a_1"})], [say("I could not open that video.")]]))
    await loop.design(ctx, SendMessage(text="look at the clip"))
    res = next(e for e in await _events() if e["type"] == "tool.result")["data"]
    assert res["title"] == "Internal step failed, trying another way"
    assert str(settings().data_dir) not in res["summary"] and settings().data_dir.as_posix() not in res["summary"]
    # the model still gets the whole error
    out = json.loads(next(i for i in fake.calls[1]["input"] if i.get("type") == "function_call_output")["output"])
    assert str(where) in out["error"]


def test_failure_titles():
    t = narrate.result_title
    assert t("write_program", {}, {"ok": False, "stage": "build", "error": "matar is not defined"}) == "Fixing the program: matar is not defined"
    assert t("write_program", {}, {"ok": False, "stage": "timeout", "error": "Script execution timed out after 20000ms"}).startswith("The model took too long")
    assert t("edit_program", {}, {"ok": False, "error": "IntegrityError: UNIQUE constraint failed"}) == "Internal step failed, trying another way"
    assert t("edit_program", {}, {"ok": False, "error": "not found: 'const seat_n'"}) == "Edit didn't apply, retrying"
    assert t("measure", {}, {"ok": False, "error": "nothing found there"}) == "Problem: nothing found there"
    assert narrate.localize(t("look", {}, {"ok": False, "error": "KeyError: 'png'"}), "ru") == "Внутренний шаг не удался, пробую иначе"


def test_effort_schedule():
    assert loop._effort("max", 0, 24, True) == "max"  # the first plan
    assert loop._effort("max", 3, 24, False) == "high"  # fixes in between
    assert loop._effort("xhigh", 9, 24, True) == "xhigh"  # right after a rejection
    assert loop._effort("medium", 3, 24, False) == "medium"
    assert loop._effort("max", 22, 24, True) == "low" and loop._effort("minimal", 23, 24, False) == "minimal"


async def test_rejection_by_the_reviewer_brings_back_the_full_effort(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db)
    rounds = iter([False, True])

    def outcome(state):
        accepted = next(rounds)
        state.critic = {"verdict": "pass" if accepted else "revise", "version": state.version}
        state.done = accepted
        return {"accepted": accepted}

    monkeypatch.setattr(loop, "run_tool", fake_tools([], outcome))
    fake = _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x"})], [call("finish", {"summary": "done"})],
                                       [call("edit_program", {"source": "y"})], [call("finish", {"summary": "done"})]]))
    await loop.design(ctx, SendMessage(text="a shelf bracket", reasoning="max"))
    assert [c["effort"] for c in fake.calls] == ["max", "high", "max", "high"]
    card = next(e for e in await _events() if e["type"] == "result")["data"]
    assert card["reviewed_version"] == 2 == card["version"]


async def test_concepts_are_marked_as_generated(fresh_db, monkeypatch):
    ctx = await _project(fresh_db)

    class Images:
        async def image(self, meter, prompt, n=1, **kw):
            return [_png(80, 60)] * n

    monkeypatch.setattr(side, "meta", lambda: Images())
    await side.make_concepts(ctx, "owl lamp shade", 2)
    rows = await fresh_db.all("SELECT * FROM assets WHERE kind = 'concept'")
    assert len(rows) == 2 and all(r["meta"]["calibration"] == side.GENERATED and (r["width"], r["height"]) == (80, 60) for r in rows)


async def test_a_picked_concept_becomes_a_cut_out_target_with_a_silhouette_check(fresh_db, offline, monkeypatch):
    from iamodelize3d.vision import scene

    ctx = await _project(fresh_db)
    t = dbmod.now()
    rel = storage.save_bytes("p1", "concepts", "a_c1.png", _png(80, 60))
    # drawn before concepts were marked: no calibration, no size
    await fresh_db.insert("assets", {"id": "a_c1", "project_id": "p1", "kind": "concept", "path": rel, "mime": "image/png",
                                     "meta": {"prompt": "owl lamp shade, wide wings"}, "created_at": t})
    asked: list[str] = []

    async def select(user, project_id, asset, req):
        asked.append(req.text)
        assert asset["meta"]["calibration"] == side.GENERATED  # so no A4 search runs on a generated picture
        await fresh_db.insert("selections", {"id": "s1", "project_id": project_id, "asset_id": asset["id"], "role": "target", "name": "owl",
                                             "mask_path": "p1/s1_mask.png", "data": {"bbox_px": [10, 10, 60, 50]}, "created_at": t})
        return await fresh_db.one("SELECT * FROM selections WHERE id = 's1'")

    monkeypatch.setattr(scene, "select", select)
    tool_log: list = []
    base = fake_tools(tool_log)

    async def run_tool(ctx, state, name, args):
        result, imgs = await base(ctx, state, name, args)
        if name == "write_program":
            panel = storage.save_bytes("p1", "renders", f"v{state.version}_compare_a_c1.jpg", _png())
            result["likeness"] = [{"photo": "a_c1", "silhouette_iou": 0.74}]
            imgs = imgs + [panel]
        return result, imgs

    monkeypatch.setattr(loop, "run_tool", run_tool)
    cls = {"pack": "household", "title": "Owl lamp", "refuse": False, "reason": "", "language": "en", "subject": "owl",
           "subject_en": "owl figurine", "photo_role": "style", "engine": "cad"}
    _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x"})], [call("finish", {"summary": "An owl lamp shade."})]], cls))
    await loop.design(ctx, SendMessage(text="Use this look", asset_ids=["a_c1"]))

    assert asked == ["owl lamp shade"]
    assert tool_log[0][2] is True  # the build gets likeness panels like a photo copy
    asset = await fresh_db.one("SELECT * FROM assets WHERE id = 'a_c1'")
    assert (asset["width"], asset["height"]) == (80, 60)
    assert [a["id"] for a, _ in await compare.targets("p1")] == ["a_c1"]
    evs = await _events()
    measured = next(e["data"] for e in evs if e["type"] == "tool.result" and e["data"]["name"] == "measure")
    assert measured["title"] == "Muse Image drew it → SAM 3.1 cut it out"
    assert measured["models"][:2] == [settings().model_image, settings().model_sam]
    chain = next(e["data"] for e in evs if e["type"] == "tool.result" and e["data"]["name"] == "compare")
    assert chain["title"] == "Muse Image drew it → SAM 3.1 cut it out → silhouette 74%" and chain["image"].endswith("v1_compare_a_c1.jpg")
    card = next(e for e in evs if e["type"] == "result")["data"]
    assert card["compare"] == "/files/p1/renders/v1_compare_a_c1.jpg"
    brief = (await fresh_db.one("SELECT brief FROM projects WHERE id = 'p1'"))["brief"]
    assert brief["photo_role"] == "copy" and brief["subject"] == "owl lamp shade"
