"""The Meta client offline: provider blips are retried without holding a slot, open weights answer through
think blocks and hand over to Spark, and every call is counted per model and purpose. No network."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest

from formwright.config import settings
from formwright.llm import client, pricing
from formwright.llm.client import CostMeter, MetaClient, parse_json_object

OPEN = "meta-models/muse-spark-open-1026"


class FastAsyncio:
    """asyncio for the client module with instant backoff sleeps that record what the gate looked like."""

    def __init__(self, model: str = ""):
        self.model = model
        self.waits: list[float] = []
        self.slots: list[int] = []

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        if self.model:
            self.slots.append(client._limiter.gate(self.model)._value)
        await asyncio.sleep(0)


def status_error(code: int, headers: dict[str, str] | None = None) -> openai.APIStatusError:
    resp = httpx.Response(code, headers=headers or {}, request=httpx.Request("POST", "http://test.invalid/v1/responses"))
    return openai.APIStatusError(f"status {code}", response=resp, body=None)


@pytest.fixture
def offline(monkeypatch):
    """Endpoints nobody listens on: a stub that misses a call fails fast instead of reaching a real provider."""
    s = settings()
    monkeypatch.setattr(s, "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(s, "meta_api_key", "test")
    monkeypatch.setattr(s, "open_base_url", "http://127.0.0.1:9/open/v1")
    monkeypatch.setattr(s, "open_api_key", "test")
    monkeypatch.setattr(s, "open_model", OPEN)
    monkeypatch.setattr(s, "open_roles", "critic,classify,english,snap_name")
    # a local .env may meter the open model; these tests assume the self-hosted default (billed by GPU time)
    monkeypatch.setattr(s, "open_price_in_per_m", 0.0)
    monkeypatch.setattr(s, "open_price_out_per_m", 0.0)
    return s


async def test_502_is_retried_and_the_gate_is_free_during_the_backoff(offline, monkeypatch):
    model = "muse-spark-1.3-contributor-retry-test"
    fake = FastAsyncio(model)
    monkeypatch.setattr(client, "asyncio", fake)
    full = client._limiter.gate(model)._value
    calls = []

    async def call():
        calls.append(1)
        if len(calls) == 1:
            raise status_error(502)
        return {"ok": True}

    assert await MetaClient()._retry(model, call) == {"ok": True}
    assert len(calls) == 2 and fake.slots == [full]


@pytest.mark.parametrize("code", [408, 409, 425, 429, 500, 502, 503, 504, 529])
async def test_transient_statuses_are_retried(offline, monkeypatch, code):
    monkeypatch.setattr(client, "asyncio", FastAsyncio())
    calls = []

    async def call():
        calls.append(1)
        if len(calls) < 3:
            raise status_error(code)
        return "done"

    assert await MetaClient()._retry("m", call) == "done" and len(calls) == 3


async def test_client_errors_fail_at_once(offline, monkeypatch):
    monkeypatch.setattr(client, "asyncio", FastAsyncio())
    calls = []

    async def call():
        calls.append(1)
        raise status_error(400)

    with pytest.raises(openai.APIStatusError):
        await MetaClient()._retry("m", call)
    assert len(calls) == 1


async def test_retry_after_ms_is_honoured(offline, monkeypatch):
    fake = FastAsyncio()
    monkeypatch.setattr(client, "asyncio", fake)
    n = []

    async def call():
        n.append(1)
        if len(n) == 1:
            raise status_error(429, {"retry-after-ms": "1500"})
        if len(n) == 2:
            raise status_error(503, {"retry-after": "2"})
        return 1

    await MetaClient()._retry("m", call)
    assert fake.waits[0] == pytest.approx(1.5, abs=0.31) and fake.waits[1] == pytest.approx(2.0, abs=0.31)


async def test_timeouts_are_retried_at_most_twice(offline, monkeypatch):
    monkeypatch.setattr(client, "asyncio", FastAsyncio())
    calls = []

    async def call():
        calls.append(1)
        raise openai.APITimeoutError(request=httpx.Request("POST", "http://test.invalid"))

    with pytest.raises(openai.APITimeoutError):
        await MetaClient()._retry("m", call, attempts=5)
    assert len(calls) == 3


async def test_direct_http_errors_are_retried(offline, monkeypatch):
    """/images/edits and /asr/transcribe go through the same retry."""
    monkeypatch.setattr(client, "asyncio", FastAsyncio())
    calls = []

    async def call():
        calls.append(1)
        if len(calls) == 1:
            r = httpx.Response(504, request=httpx.Request("POST", "http://test.invalid/images/edits"))
            raise httpx.HTTPStatusError("gateway timeout", request=r.request, response=r)
        return {"data": []}

    assert await MetaClient()._retry("muse-image-1.0", call) == {"data": []}


async def test_a_call_past_its_deadline_ends_as_a_timeout_error():
    with pytest.raises(openai.APITimeoutError):
        async with client._deadline(0.05, "test"):
            await asyncio.sleep(1)


def test_json_survives_think_blocks_fences_and_prose():
    schema_keys = ["verdict", "match_score", "issues"]
    text = ('<think>The user wants {"verdict": "revise"} maybe... let me check {x}</think>\n'
            'Here is my review:\n```json\n{"verdict": "pass", "match_score": 8.5, "issues": [{"severity": "minor", "text": "a {brace}"}]}\n```')
    out = parse_json_object(text, schema_keys)
    assert out == {"verdict": "pass", "match_score": 8.5, "issues": [{"severity": "minor", "text": "a {brace}"}]}
    # the opening tag came from the chat template
    assert parse_json_object('reasoning {"a": 1} more</think>{"verdict": "pass", "match_score": 9, "issues": []}', schema_keys)["match_score"] == 9
    # a nested object with the keys wins over an outer one without them
    assert parse_json_object('{"wrapper": 1} {"english": "clip"}', ["english"]) == {"english": "clip"}
    assert parse_json_object("no json here", ["a"]) is None
    assert parse_json_object('{"a": 1}', ["b"]) == {"a": 1}


def _open_stub(answers: list):
    """A Chat Completions endpoint that plays back answers (str content or an exception)."""
    seen: list[dict] = []

    async def create(**kwargs):
        seen.append(kwargs)
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        msg = SimpleNamespace(content=a, reasoning_content="thinking {not json}")
        resp = SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200))
        return SimpleNamespace(parse=lambda: resp, headers=None)

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=create)))), seen


SCHEMA = {"type": "object", "properties": {"verdict": {"type": "string"}}, "required": ["verdict"]}


async def test_open_json_reads_the_answer_and_meters_it(offline, monkeypatch):
    monkeypatch.setattr(offline, "open_price_in_per_m", 0.5)
    monkeypatch.setattr(offline, "open_price_out_per_m", 1.0)
    mc = MetaClient()
    mc.open, seen = _open_stub(['<think>hmm {"verdict": "revise"</think>{"verdict": "pass"}'])
    meter = CostMeter()
    out = await mc.json(meter, model=OPEN, system="Review.", content=[{"type": "input_text", "text": "x"},
                        {"type": "input_image", "image_url": "data:image/png;base64,AA=="}], schema=SCHEMA, name="critic")
    assert out == {"verdict": "pass"}
    assert seen[0]["response_format"]["type"] == "json_schema"
    assert seen[0]["messages"][1]["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
    s = meter.summary()
    assert s["calls_by_model"] == {OPEN: 1} and s["purposes_by_model"] == {OPEN: {"critic": 1}}
    assert s["usd"] == pytest.approx((1000 * 0.5 + 200 * 1.0) / 1e6)


async def test_open_json_without_schema_support_asks_in_words(offline, monkeypatch):
    monkeypatch.setattr(client, "asyncio", FastAsyncio())
    mc = MetaClient()
    mc.open, seen = _open_stub([status_error(400), '{"verdict": "pass"}'])
    out = await mc.json(CostMeter(), model=OPEN, system="Review.", content=[{"type": "input_text", "text": "x"}], schema=SCHEMA, name="critic")
    assert out == {"verdict": "pass"}
    assert "response_format" not in seen[1] and '"required": ["verdict"]' in seen[1]["messages"][0]["content"]


async def test_open_failures_fall_back_to_spark(offline, monkeypatch):
    monkeypatch.setattr(client, "asyncio", FastAsyncio())
    mc = MetaClient()
    used = []

    async def respond(meter, **kw):
        used.append((kw["model"], kw["purpose"]))
        return SimpleNamespace(output_text='{"verdict": "pass"}', status="completed")

    monkeypatch.setattr(mc, "respond", respond)
    # the endpoint is down (two attempts), then it answers prose only
    mc.open, _ = _open_stub([status_error(503), status_error(503)])
    assert await mc.json(CostMeter(), model=OPEN, system="s", content=[], schema=SCHEMA, name="classify") == {"verdict": "pass"}
    mc.open, _ = _open_stub(["I think it passes."])
    assert await mc.json(CostMeter(), model=OPEN, system="s", content=[], schema=SCHEMA, name="classify") == {"verdict": "pass"}
    assert used == [(settings().model_fast, "classify")] * 2
    # the critic decides itself
    mc.open, _ = _open_stub(["no json"])
    assert await mc.json(CostMeter(), model=OPEN, system="s", content=[], schema=SCHEMA, name="critic", fallback=False) == {}
    mc.open, _ = _open_stub([status_error(401)])
    with pytest.raises(openai.APIStatusError):
        await mc.json(CostMeter(), model=OPEN, system="s", content=[], schema=SCHEMA, name="critic", fallback=False)


def test_model_for_routes_only_the_open_roles(offline, monkeypatch):
    mc = MetaClient()
    assert mc.model_for("critic", "muse-spark-1.3") == OPEN
    assert mc.model_for("english", "muse-spark-1.3") == OPEN
    assert mc.model_for("designer", "muse-spark-1.3") == "muse-spark-1.3"
    monkeypatch.setattr(offline, "open_roles", "critic")
    assert MetaClient().model_for("classify", "fast") == "fast"
    monkeypatch.setattr(offline, "open_base_url", "")
    assert MetaClient().model_for("critic", "fast") == "fast"


def test_meter_counts_calls_per_model_and_purpose():
    m = CostMeter()
    m.add("muse-spark-1.3", 0.01, 100, 10, purpose="designer")
    m.add("muse-spark-1.3", 0.002, purpose="classify")
    m.add("sam-3.1", 0.0025, purpose="white plastic clip")
    m.add("sam-3.1", 0.0025)
    s = m.summary()
    assert s["calls"] == 4 and s["by_model"]["sam-3.1"] == 0.005
    assert s["calls_by_model"] == {"muse-spark-1.3": 2, "sam-3.1": 2}
    assert s["purposes_by_model"] == {"muse-spark-1.3": {"designer": 1, "classify": 1}, "sam-3.1": {"white plastic clip": 1}}
    assert client._sam_purpose("<0f>1<|point;x=5;y=5;w=100;h=100|>") == "tap"
    assert client._sam_purpose("<0f>1<|box;x1=1;y1=2;x2=29;y2=39;w=100;h=100|>") == "box"


def test_open_model_price_row(offline, monkeypatch):
    assert pricing.token_cost(OPEN, 1_000_000, 0, 0) == 0.0  # self-hosted: billed by GPU time
    monkeypatch.setattr(offline, "open_price_in_per_m", 0.3)
    monkeypatch.setattr(offline, "open_price_out_per_m", 1.2)
    assert pricing.token_cost(OPEN, 1_000_000, 0, 1_000_000) == pytest.approx(1.5)
    assert pricing.token_cost("muse-spark-1.3", 1_000_000, 0, 0) == pytest.approx(1.25)
    assert pricing.token_cost("unknown-model", 1_000_000, 0, 0) == 0.0
