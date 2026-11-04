"""A model service outage: what a run outlasts, what it does not, and what "Continue" still knows afterwards."""
from __future__ import annotations

import asyncio
import types

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from formwright.agent import loop
from formwright.agent.runner import kept_request
from formwright.llm.client import service_outage


def status_error(code: int) -> APIStatusError:
    req = httpx.Request("POST", "http://rig/v1/responses")
    return APIStatusError("rig", response=httpx.Response(code, request=req), body=None)


def fake_ctx() -> types.SimpleNamespace:
    async def emit(type_, data=None):
        ctx.events.append((type_, data))

    ctx = types.SimpleNamespace(job_id="j", outage=False, deadline=100.0, events=[], meter=types.SimpleNamespace(usd=0, tokens_in=0, tokens_out=0, tokens_cached=0),
                                emit=emit, _arm=lambda wait=0.0: None)
    return ctx


@pytest.fixture
def no_wait(monkeypatch):
    real = asyncio.sleep

    async def sleep(_):
        await real(0)

    monkeypatch.setattr(loop.asyncio, "sleep", sleep)

    async def keep(_):
        return None

    monkeypatch.setattr(loop, "_keep_cost", keep)


@pytest.mark.parametrize("error,cured", [
    (status_error(503), True), (status_error(500), True), (status_error(429), True),
    (status_error(400), False), (status_error(401), False),
    (APITimeoutError(request=httpx.Request("POST", "http://rig")), True),
    (APIConnectionError(request=httpx.Request("POST", "http://rig")), True),
    (httpx.ConnectError("refused"), True),
    (ValueError("a bug"), False),
])
def test_only_an_outage_is_worth_waiting_for(error, cured):
    assert service_outage(error) is cured


def test_a_short_outage_costs_the_run_nothing(no_wait):
    ctx, calls = fake_ctx(), []

    async def call():
        calls.append(1)
        if len(calls) < 3:
            raise status_error(503)
        return "answer"

    assert asyncio.run(loop._model_call(ctx, "design", call)) == "answer"
    assert len(calls) == 3
    assert sum(1 for t, d in ctx.events if t == "job.heartbeat" and d["outage"]) >= 2  # the person is told what the run waits for
    assert ctx.outage is False


def test_a_long_outage_ends_the_run(no_wait, monkeypatch):
    monkeypatch.setattr(loop, "OUTAGE_PATIENCE_S", 0.0)
    ctx = fake_ctx()

    async def call():
        raise status_error(503)

    with pytest.raises(APIStatusError):
        asyncio.run(loop._model_call(ctx, "design", call))
    assert ctx.outage is False


def test_a_refused_request_is_not_tried_again(no_wait):
    ctx, calls = fake_ctx(), []

    async def call():
        calls.append(1)
        raise status_error(400)

    with pytest.raises(APIStatusError):
        asyncio.run(loop._model_call(ctx, "design", call))
    assert len(calls) == 1


def test_continue_keeps_the_whole_request():
    text = "Сделай крючок. " + "Важные требования. " * 40 + "MARKER-END"
    brief = kept_request({"language": "ru"}, {"text": text}, "failed")
    assert "MARKER-END" in brief["interrupted"]
    assert brief["language"] == "ru"
    assert len(brief["turns"][-1]) < 240  # the short line among the turns stays short


def test_a_second_interruption_does_not_lose_the_first_request():
    once = kept_request({}, {"text": "the real request"}, "failed")
    twice = kept_request(once, {"text": "Continue from where you stopped."}, "failed")
    assert "the real request" in twice["interrupted"]
    assert "Continue from" in twice["interrupted"]
    assert kept_request(twice, {"text": "the real request"}, "failed")["interrupted"] == twice["interrupted"]
