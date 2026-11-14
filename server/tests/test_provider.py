"""The AI provider is a setting (FW_LLM_PROVIDER): Meta stays the default and keeps its own settings, OpenAI or a custom
Responses endpoint take their address and key from FW_LLM_*, and what only Meta offers (SAM, voice, images) is off
elsewhere: no measuring tools for the designer, no voice notes, a brief that asks for dimensions. No network."""
from __future__ import annotations

import pytest

from iamodelize3d import config
from iamodelize3d.agent import tools
from iamodelize3d.config import Settings
from iamodelize3d.llm import client, pricing
from iamodelize3d.llm.client import CostMeter, FeatureUnavailable, MetaClient
from iamodelize3d.shop import intake


def make(**env) -> Settings:
    return Settings(_env_file=None, **env)


@pytest.fixture
def use(monkeypatch):
    """Points every settings() call at the Settings given."""
    def apply(s: Settings) -> Settings:
        monkeypatch.setattr(config, "settings", lambda: s)
        for mod in (client, pricing, tools, intake):
            monkeypatch.setattr(mod, "settings", lambda: s)
        return s
    return apply


def test_meta_is_the_default_and_keeps_its_own_settings():
    s = make(meta_api_key="mk", meta_base_url="https://meta.example/v1")
    assert s.provider["name"] == "meta"
    assert (s.api_base_url, s.api_key) == ("https://meta.example/v1", "mk")
    assert s.can("sam") and s.can("voice") and s.can("image")
    # no key, no feature
    assert not make().can("sam")


def test_openai_takes_its_preset_address_and_the_generic_key():
    s = make(llm_provider="OpenAI", llm_api_key="sk-test", meta_api_key="mk")
    assert s.provider["name"] == "openai"
    assert (s.api_base_url, s.api_key) == ("https://api.openai.com/v1", "sk-test")
    assert not s.can("sam") and not s.can("voice") and not s.can("image")


def test_a_custom_endpoint_needs_its_address(monkeypatch, tmp_path):
    s = make(llm_provider="custom", llm_base_url="http://localhost:8000/v1/", llm_api_key="k")
    assert s.api_base_url == "http://localhost:8000/v1"
    monkeypatch.setenv("FW_LLM_PROVIDER", "custom")
    monkeypatch.setenv("FW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config.Settings, "model_config", {**config.Settings.model_config, "env_file": None})
    config.settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="FW_LLM_BASE_URL"):
            config.settings()
    finally:
        config.settings.cache_clear()


def test_an_unknown_provider_is_named():
    with pytest.raises(ValueError, match="FW_LLM_PROVIDER"):
        _ = make(llm_provider="acme").provider


def test_the_client_calls_the_configured_provider(use):
    use(make(llm_provider="openai", llm_api_key="sk-test"))
    c = MetaClient()
    assert str(c.oai.base_url).rstrip("/") == "https://api.openai.com/v1" and c.oai.api_key == "sk-test"


async def test_meta_only_features_refuse_clearly_elsewhere(use):
    use(make(llm_provider="openai", llm_api_key="sk-test"))
    c = MetaClient()
    meter = CostMeter(budget_usd=1)
    for call in (lambda: c.sam(meter, "data:image/png;base64,", "a wheel"), lambda: c.transcribe(meter, b"RIFF"),
                 lambda: c.image(meter, "a knob")):
        with pytest.raises(FeatureUnavailable, match="FW_LLM_PROVIDER=openai"):
            await call()
    assert meter.calls == 0


def test_the_designer_gets_no_measuring_tools_without_sam(use):
    names = lambda: [t["name"] for t in tools.tools_for("household", photos=True, prints=False)]  # noqa: E731
    use(make(meta_api_key="mk"))
    assert {"measure", "fit_to_photo"} <= set(names())
    use(make(llm_provider="openai", llm_api_key="sk-test"))
    assert not {"measure", "fit_to_photo"} & set(names()) and names()[-1] == "finish"


def test_the_brief_asks_for_dimensions_without_sam(use):
    data = {"part": {"name_en": "knob"}, "material": "PLA"}
    use(make(meta_api_key="mk"))
    assert "Measure the part from the photo on the A4 sheet" in intake.design_brief(data, "", "IM-1")
    use(make(llm_provider="openai", llm_api_key="sk-test"))
    brief = intake.design_brief(data, "", "IM-1")
    assert "No measuring tool" in brief and "ask the customer" in brief


def test_another_providers_tokens_are_priced_from_the_settings(use):
    use(make(llm_provider="openai", llm_api_key="k", llm_price_in_per_m=2.0, llm_price_out_per_m=8.0))
    assert pricing.token_cost("some-model", 1_000_000, 0, 1_000_000) == pytest.approx(10.0)
    # cached input falls back to the input price when no cached price is set
    assert pricing.token_cost("some-model", 1_000_000, 1_000_000, 0) == pytest.approx(2.0)
    # Meta's own models keep their table price
    assert pricing.token_cost("muse-spark-1.3", 1_000_000, 0, 0) == pytest.approx(1.25)


def test_efforts_meta_does_not_know_are_lowered_elsewhere():
    meta = make(meta_api_key="mk")
    openai = make(llm_provider="openai", llm_api_key="k")
    assert client.provider_effort(meta, "max") == "max"
    assert client.provider_effort(openai, "max") == "high"
    assert client.provider_effort(openai, "xhigh") == "high"
    assert client.provider_effort(openai, "low") == "low"
    assert client.provider_effort(make(llm_provider="openai", llm_max_effort="xhigh"), "max") == "xhigh"
    # a model that does not reason gets no reasoning settings at all
    assert client.provider_effort(make(llm_provider="openai", llm_reasoning=False), "medium") is None


def test_one_model_name_fills_every_role_left_on_meta(monkeypatch, tmp_path):
    monkeypatch.setattr(config.Settings, "model_config", {**config.Settings.model_config, "env_file": None})
    for k, v in {"FW_LLM_PROVIDER": "openai", "FW_LLM_MODEL": "gpt-x", "FW_MODEL_FAST": "gpt-x-mini", "FW_DATA_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)
    config.settings.cache_clear()
    try:
        s = config.settings()
        assert (s.model_designer, s.model_designer_hard, s.model_fast, s.model_free) == ("gpt-x", "gpt-x", "gpt-x-mini", "gpt-x")
    finally:
        config.settings.cache_clear()


async def test_a_model_that_refuses_reasoning_is_called_again_without_it(use):
    import httpx
    from openai import AsyncOpenAI

    s = use(make(llm_provider="custom", llm_base_url="http://fake/v1", llm_api_key="k"))
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        seen.append(body)
        if "reasoning" in body:
            return httpx.Response(400, json={"error": {"message": "reasoning.effort is not supported with this model", "type": "invalid_request_error"}})
        return httpx.Response(200, json={"id": "r", "object": "response", "created_at": 0, "model": body["model"], "status": "completed",
                                         "output": [{"type": "message", "id": "m", "role": "assistant", "status": "completed",
                                                     "content": [{"type": "output_text", "text": "ok", "annotations": []}]}],
                                         "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
                                         "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                                                   "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}})

    c = MetaClient()
    c.oai = AsyncOpenAI(base_url=s.api_base_url, api_key="k", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    msg = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}]
    client._NO_REASONING.clear()
    r = await c.respond(CostMeter(), model="plain", input=msg, effort="max")
    assert r.output_text == "ok"
    assert seen[0]["reasoning"]["effort"] == "high" and "reasoning" not in seen[1] and "include" not in seen[1]
    # remembered: the next call goes without reasoning at once
    await c.respond(CostMeter(), model="plain", input=msg, effort="max")
    assert len(seen) == 3 and "reasoning" not in seen[2]
    client._NO_REASONING.clear()
