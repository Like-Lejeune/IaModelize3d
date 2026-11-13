"""The agent's own wiring around the open-weights reviewer: Muse Spark Open on Baseten gets the schema spelled out and a
low reasoning effort, an answer without the schema's keys counts as none, the critic reads loose answers in the schema's
own terms, the open intake never refuses on its own, the enclosure op reaches the designer, the result card carries
the case check, and «Сделать фигурку» on a kept snap sticker starts a fresh figurine. Offline: every model is a stub."""
from __future__ import annotations

import io
import json
import logging
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from iamodelize3d import db as dbmod, events, storage
from iamodelize3d.agent import critic, loop, tools
from iamodelize3d.agent.runner import JobContext
from iamodelize3d.agent.tools import DesignState
from iamodelize3d.config import settings
from iamodelize3d.llm import client
from iamodelize3d.llm.client import CostMeter, MetaClient
from iamodelize3d.models import SendMessage
from iamodelize3d.quotas import ModelChoice
from iamodelize3d.vision.relief import STICKER_SOURCE

OPEN = "meta-models/muse-spark-open-1026"
SPARK = "muse-spark-1.3-contributor"


@pytest.fixture
def offline(monkeypatch):
    """Endpoints nobody listens on: a stub that misses a call fails fast instead of reaching a real provider."""
    s = settings()
    monkeypatch.setattr(s, "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(s, "meta_api_key", "test")
    monkeypatch.setattr(s, "open_base_url", "http://127.0.0.1:9/open/v1")
    monkeypatch.setattr(s, "open_api_key", "test")
    monkeypatch.setattr(s, "open_model", OPEN)
    monkeypatch.setattr(s, "open_roles", "critic,classify,english")
    return s


def _open_stub(answers: list):
    """A Chat Completions endpoint that plays back (content, finish_reason) pairs, or raises an exception."""
    seen: list[dict] = []

    async def create(**kwargs):
        seen.append(kwargs)
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        text, finish = a if isinstance(a, tuple) else (a, "stop")
        msg = SimpleNamespace(content=text, reasoning_content="The request is in Russian, so text_user goes in Russian." * 20)
        resp = SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)],
                               usage=SimpleNamespace(prompt_tokens=3000, completion_tokens=9000))
        return SimpleNamespace(parse=lambda: resp, headers=None)

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=create)))), seen


# ---------------------------------------------------------------- the open-weights call


async def test_open_json_spells_out_the_schema_and_asks_for_low_effort(offline):
    mc = MetaClient()
    mc.open, seen = _open_stub(['{"verdict": "pass", "match_score": 9, "issues": []}', '{"english": "white clip"}'])
    out = await mc.json(CostMeter(), model=OPEN, system="Review.", content=[{"type": "input_text", "text": "x"}],
                        schema=critic.SCHEMA, name="critic", effort="low", max_output_tokens=critic.MAX_OUTPUT, fallback=False)
    assert out["verdict"] == "pass"
    first = seen[0]
    # Baseten takes the format but does not enforce it for Muse Spark Open: the prompt carries the schema too
    assert first["messages"][0]["content"].startswith("Review.") and '"required": ["verdict", "match_score", "issues"]' in first["messages"][0]["content"]
    assert first["response_format"]["json_schema"]["strict"] is True
    # its default effort is xhigh, and max_tokens counts the reasoning
    assert first["extra_body"] == {"reasoning_effort": "low"} and first["max_tokens"] == critic.MAX_OUTPUT
    # a short translation still leaves the reasoning room; minimal runs as low there anyway
    await mc.json(CostMeter(), model=OPEN, system="Translate.", content=[{"type": "input_text", "text": "белая клипса"}],
                  schema={"type": "object", "properties": {"english": {"type": "string"}}, "required": ["english"]},
                  name="english", effort="minimal", max_output_tokens=2000)
    assert seen[1]["max_tokens"] == client.OPEN_MIN_TOKENS and seen[1]["extra_body"] == {"reasoning_effort": "low"}


async def test_a_server_that_refuses_the_options_gets_the_plain_request(offline, monkeypatch):
    from test_llm_client import FastAsyncio, status_error

    monkeypatch.setattr(client, "asyncio", FastAsyncio())
    mc = MetaClient()
    mc.open, seen = _open_stub([status_error(400), '{"verdict": "pass"}'])
    schema = {"type": "object", "properties": {"verdict": {"type": "string"}}, "required": ["verdict"]}
    assert await mc.json(CostMeter(), model=OPEN, system="s", content=[], schema=schema, name="critic", fallback=False) == {"verdict": "pass"}
    assert "response_format" not in seen[1] and "extra_body" not in seen[1] and '"required": ["verdict"]' in seen[1]["messages"][0]["content"]


@pytest.mark.parametrize("answer", [
    # cut off while writing: only an inner issue object is whole
    ('{"verdict": "revise", "match_score": 6, "issues": [{"severity": "minor", "text": "x", "text_user": "x", "fix_hint": "y"}, {"sev', "length"),
    # keys of its own, in the request's language
    ('{"вердикт": "pass", "оценка": 9, "замечания": []}', "stop"),
    # thought through the whole budget
    ("", "length"),
])
async def test_an_answer_without_the_schemas_keys_counts_as_none_and_says_why(offline, caplog, answer):
    mc = MetaClient()
    mc.open, _ = _open_stub([answer])
    meter = CostMeter()
    with caplog.at_level(logging.WARNING, logger="iamodelize3d.llm.client"):
        out = await mc.json(meter, model=OPEN, system="s", content=[], schema=critic.SCHEMA, name="critic", fallback=False)
    assert out == {}
    line = next(r.getMessage() for r in caplog.records if "no usable critic answer" in r.getMessage())
    assert f"finish {answer[1]}" in line and "9000 output tokens" in line and "chars of reasoning" in line
    assert meter.summary()["calls_by_model"] == {OPEN: 1}  # it answered, so it is metered


async def test_the_open_request_keeps_the_last_eight_images(offline):
    mc = MetaClient()
    mc.open, seen = _open_stub(['{"verdict": "pass"}'])
    content = [{"type": "input_text", "text": "photos"}] + [{"type": "input_image", "image_url": f"data:image/png;base64,{i}"} for i in range(10)]
    await mc.json(CostMeter(), model=OPEN, system="s", content=content, schema={"required": ["verdict"]}, name="critic", fallback=False)
    parts = seen[0]["messages"][1]["content"]
    assert [p["image_url"]["url"][-1] for p in parts if p["type"] == "image_url"] == [str(i) for i in range(2, 10)]
    assert parts[0] == {"type": "text", "text": "photos"}


def test_snap_naming_is_not_an_open_role_even_without_the_setting():
    mc = MetaClient.__new__(MetaClient)
    mc.s, mc.open = SimpleNamespace(open_model=OPEN), object()  # settings without open_roles
    assert mc.model_for("snap_name", "muse-spark-1.3") == "muse-spark-1.3"
    assert mc.model_for("critic", "muse-spark-1.3") == OPEN and mc.model_for("english", "x") == OPEN


# ---------------------------------------------------------------- the critic


def test_a_loose_review_is_read_in_the_schemas_terms():
    v = critic.usable({"verdict": " Pass", "match_score": "8,5/10", "extra": 1, "issues": [
        {"severity": "Critical", "text": "the USB opening is 2 mm low", "fix_hint": "raise it 2 mm"},
        {"severity": "cosmetic", "text": "lid edge is sharp", "text_user": "острый край крышки"},
        {"severity": "major", "text": " "},
        "not an issue"]})
    assert v == {"verdict": "pass", "match_score": 8.5, "issues": [
        {"severity": "major", "text": "the USB opening is 2 mm low", "text_user": "the USB opening is 2 mm low", "fix_hint": "raise it 2 mm"},
        {"severity": "minor", "text": "lid edge is sharp", "text_user": "острый край крышки", "fix_hint": ""}]}
    assert critic.usable({"verdict": "revise", "match_score": 14, "issues": None}) == {"verdict": "revise", "match_score": 10.0, "issues": []}
    assert critic.usable({"verdict": "revise", "match_score": True})["match_score"] is None
    # no verdict in the schema's words: no review
    assert critic.usable({"verdict": "одобрено", "match_score": 9}) == {} and critic.usable({}) == {}


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


class FakeCtx:
    def __init__(self, language: str | None = None):
        self.project = {"id": "p_hub", "title": "Keypad case", "brief": {"language": language} if language else {}}
        self.project_id = "p_hub"
        self.user = {"id": "u_hub"}
        self.job_id = "j_hub"
        self.meter = CostMeter()
        self.models = SimpleNamespace(designer="muse-spark-1.3", fast=SPARK)
        self.events: list[tuple[str, dict]] = []

    async def emit(self, type_: str, data: dict | None = None) -> None:
        self.events.append((type_, data or {}))

    async def status(self, text: str) -> None:
        self.events.append(("agent.status", {"text": text}))

    def check_cancelled(self) -> None:
        pass


async def test_the_open_reviewer_writing_loosely_still_reviews_and_one_that_strays_hands_over(fresh_db, monkeypatch):
    answers = {OPEN: [{"verdict": "PASS", "match_score": "9/10", "issues": []}, {"вердикт": "pass"}], SPARK: [{"verdict": "pass", "match_score": 9, "issues": []}]}
    used = []

    class Meta:
        def model_for(self, role, default):
            return OPEN if role == "critic" else default

        async def json(self, meter, *, model, fallback=True, max_output_tokens=0, **kw):
            used.append((model, fallback, max_output_tokens))
            return answers[model].pop(0)

    monkeypatch.setattr(critic, "meta", lambda: Meta())
    ctx, state = FakeCtx(language="ru"), DesignState(pack="enclosure", version=1)
    v = await critic.review(ctx, state)
    assert v == {"verdict": "pass", "match_score": 9.0, "issues": [], "model": OPEN, "reviewer": "primary", "version": 1}
    assert used == [(OPEN, False, critic.MAX_OUTPUT)]
    v = await critic.review(ctx, state)
    assert v["reviewer"] == "fallback" and v["model"] == SPARK and used[1:] == [(OPEN, False, critic.MAX_OUTPUT), (SPARK, True, critic.MAX_OUTPUT)]


# ---------------------------------------------------------------- tools: the enclosure op


def test_inspect_offers_the_enclosure_op():
    op = tools.INSPECT["parameters"]["properties"]["ops"]["items"]["properties"]["op"]
    assert "enclosure" in op["enum"] and "enclosure {board?}" in tools.INSPECT["description"]


async def test_the_enclosure_op_reads_as_findings_with_the_blocking_rays(monkeypatch):
    rays = [{"port": "J1", "from": [0, 0, 1], "to": [0, -3, 1], "hit": False}] * 9 + [{"port": "J1", "from": [0, 0, 2], "to": [0, -1.2, 2], "hit": True}]
    seen = []

    class Geom:
        async def inspect(self, source, params, ops, **extra):
            seen.append(ops)
            return {"results": [{"op": "enclosure", "board": "board", "findings": [{"code": "port_blocked", "severity": "error", "part": "J1",
                                                                                   "msg": "J1: the plug hits the case", "value": 0}],
                                 "rays": rays, "clearance": {"J1": 0}, "ms": 140},
                                {"op": "parts", "parts": [{"name": "base"}]}]}

    monkeypatch.setattr(tools, "geom", lambda: Geom())
    state = DesignState(pack="enclosure", source="return {}", version=2)
    out, images = await tools.run_tool(FakeCtx(), state, "inspect_model", {"ops": [{"op": "enclosure"}, {"op": "parts"}]})
    enc, parts = out["results"]
    assert seen == [[{"op": "enclosure"}, {"op": "parts"}]] and images == []
    assert enc["rays"] == [rays[-1]] and enc["clear_rays"] == 9 and enc["clearance"] == {"J1": 0} and enc["findings"][0]["code"] == "port_blocked"
    assert parts == {"op": "parts", "parts": [{"name": "base"}]}


# ---------------------------------------------------------------- the result card


def test_the_result_card_carries_the_case_check(fresh_db):
    enc = {"op": "enclosure", "board": "board", "ok": True, "version": 3, "rays": [{"hit": False}], "clearance": {"U1_usb": 0.268},
           "summary": {"usb_clearance_mm": 0.268, "button_gap_mm": 0.3, "snap_strain_pct": 1.67},
           "findings": [{"code": "port_clear", "severity": "info", "msg": "U1_usb: 0.27 mm clearance all round", "part": "U1_usb", "value": 0.268}]}
    state = DesignState(pack="enclosure", source="return {}", version=3, last_render="p_hub/renders/v3.png",
                        last_build={"checks": {"ok": True, "issues": [], "stats": {"size": [65.7, 56, 8.9]}, "enclosure": enc}, "paramSpecs": {}})
    card = loop.result_card(FakeCtx(), state)
    assert card["enclosure"] == {"ok": True, "summary": enc["summary"], "board": "board", "version": 3, "findings": enc["findings"]}
    state.last_build["checks"].pop("enclosure")
    assert "enclosure" not in loop.result_card(FakeCtx(), state)


# ---------------------------------------------------------------- a kept snap sticker becomes a figurine


def test_which_requests_turn_a_sticker_into_a_figurine():
    sticker = {"author": "instant", "source": STICKER_SOURCE}
    assert loop.STICKER_CALL in STICKER_SOURCE
    assert loop.figurine_from_sticker(sticker, "Сделай коллекционную миниатюру: кот, около 50 мм по длинной стороне.", False)
    assert loop.figurine_from_sticker(sticker, "Make a collectible miniature of this: bench, about 50 mm along its longest side.", False)
    assert loop.figurine_from_sticker(sticker, "сделай фигурку", False) and loop.figurine_from_sticker(sticker, "", True)
    # the sticker itself is changed, not replaced
    assert not loop.figurine_from_sticker(sticker, "сделай имя крупнее", False)
    # a figurine the agent made, a collection plate, or nothing yet
    assert not loop.figurine_from_sticker({"author": "agent", "source": STICKER_SOURCE}, "миниатюра", True)
    assert not loop.figurine_from_sticker({"author": "instant", "source": "lib.collect.plate(lib.inputs.values.keys, {})"}, "miniature", True)
    assert not loop.figurine_from_sticker(None, "miniature", True)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.full((48, 64, 3), 200, np.uint8)).save(buf, "PNG")
    return buf.getvalue()


class ScriptMeta:
    """respond() plays a script of outputs; json() answers per model."""

    def __init__(self, script, answers=None):
        self.script, self.answers = list(script), answers or {}
        self.calls: list[dict] = []
        self.json_calls: list[str] = []

    def model_for(self, role, default):
        return OPEN if role in ("classify", "critic", "english") else default

    async def respond(self, meter, **kw):
        self.calls.append(kw)
        return SimpleNamespace(output=self.script.pop(0), status="completed")

    async def json(self, meter, *, model, **kw):
        self.json_calls.append(model)
        return dict(self.answers.get(model) or {})


def _call(name: str, args: dict) -> dict:
    return {"type": "function_call", "call_id": f"c_{name}", "name": name, "arguments": json.dumps(args)}


async def _design(db, monkeypatch, *, source: str, author: str, text: str, title: str = "Кот", meta: ScriptMeta | None = None):
    t = dbmod.now()
    await db.insert("projects", {"id": "p_snap", "user_id": "u1", "title": title, "pack": "collect", "version": 1,
                                 "brief": {"collect": True, "language": "ru", "snap": {"sticker": {"version": 1}}}, "created_at": t, "updated_at": t})
    await db.insert("programs", {"project_id": "p_snap", "version": 1, "source": source, "params": {"size": 50}, "inputs": {"values": {"name": "кот"}},
                                 "summary": "sticker", "checks": {"ok": True}, "author": author, "created_at": t})
    project = await db.one("SELECT * FROM projects WHERE id = 'p_snap'")
    ctx = JobContext(job_id="j1", kind="design", project=project, user={"id": "u1"}, meter=CostMeter(budget_usd=0.6),
                     models=ModelChoice(designer="muse-spark-1.3", fast="muse-spark-1.3", contributor=False))
    built = []

    async def run_tool(ctx, state, name, args):
        built.append((name, state.source))
        if name == "write_program":
            state.version, state.source = 2, args["source"]
            state.last_build = {"checks": {"ok": True, "stats": {"size": [50, 30, 40]}}, "paramSpecs": {}}
            state.last_render = storage.save_bytes(ctx.project_id, "renders", "v2.png", _png())
            storage.save_bytes(ctx.project_id, "renders", "v2_iso.png", _png())
            return {"ok": True, "version": 2}, []
        state.done, state.summary = True, args.get("summary", "")
        return {"accepted": True}, []

    async def same(meter, text, model):
        return text or ""

    meta = meta or ScriptMeta([[_call("write_program", {"source": "return {}", "summary": "фигурка"})], [_call("finish", {"summary": "готово"})]])
    monkeypatch.setattr(loop, "meta", lambda: meta)
    monkeypatch.setattr(loop, "run_tool", run_tool)
    monkeypatch.setattr(loop, "english", same)
    await loop.design(ctx, SendMessage(text=text))
    return meta, built


async def test_a_figurine_from_a_kept_sticker_starts_afresh(fresh_db, monkeypatch):
    meta, built = await _design(fresh_db, monkeypatch, source=STICKER_SOURCE, author="instant",
                                text="Сделай коллекционную миниатюру: кот, около 50 мм по длинной стороне.")
    first = meta.calls[0]["input"][0]["content"][0]["text"]
    assert "# Kept sticker" in first and "Version 1 is the flat photo sticker" in first and "write_program" in first
    assert "# Current program" not in first and "lib.collect.sticker" not in first.split("# Kept sticker")[0]
    # the designer starts with no program to edit; the new version follows the sticker
    assert built[0] == ("write_program", None)


async def test_other_requests_on_a_sticker_or_a_plate_edit_what_is_there(fresh_db, monkeypatch):
    meta, built = await _design(fresh_db, monkeypatch, source=STICKER_SOURCE, author="instant", text="сделай имя крупнее")
    first = meta.calls[0]["input"][0]["content"][0]["text"]
    assert "# Current program (version 1)" in first and "# Kept sticker" not in first and built[0] == ("write_program", STICKER_SOURCE)


async def test_the_open_intake_never_refuses_on_its_own(fresh_db, monkeypatch):
    cls = {"pack": "collect", "title": "Кот", "refuse": False, "reason": "", "language": "ru", "subject": "", "subject_en": "", "photo_role": "none", "engine": "mesh"}
    meta = ScriptMeta([[], [_call("finish", {"summary": "готово"})]], {OPEN: {**cls, "refuse": True, "reason": "опасно"}, "muse-spark-1.3": cls})
    await _design(fresh_db, monkeypatch, source=STICKER_SOURCE, author="agent", text="кот на скамейке", title="New project", meta=meta)
    # Muse Spark had the last word, and the job went on to the designer
    assert meta.json_calls == [OPEN, "muse-spark-1.3"] and len(meta.calls) == 2
    assert not any(e["type"] == "agent.message" and "can't help" in e["data"]["text"] for e in await events.since("p_snap", 0, 1000))

    # both refuse: refused
    await fresh_db.execute("DELETE FROM programs")
    await fresh_db.execute("DELETE FROM projects")
    meta = ScriptMeta([], {OPEN: {**cls, "refuse": True, "reason": "опасно"}, "muse-spark-1.3": {**cls, "refuse": True, "reason": "опасно"}})
    await _design(fresh_db, monkeypatch, source=STICKER_SOURCE, author="agent", text="кот", title="New project", meta=meta)
    assert meta.json_calls == [OPEN, "muse-spark-1.3"] and not meta.calls
