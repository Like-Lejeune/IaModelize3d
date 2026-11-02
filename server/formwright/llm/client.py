"""Meta Model API client: Responses API for text/vision/tools/search and SAM,
images for Muse Image, multipart for Voice Transcribe.

Every call is metered into a CostMeter (per job) so budgets are enforced before a
request is sent and usage is exact afterwards. Rate limits are respected with an
adaptive limiter fed by the x-ratelimit-* headers.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from ..config import settings
from . import pricing

log = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    pass


# a stuck provider must not park a job: no single read waits longer than this, and no call as a whole
META_TIMEOUT = httpx.Timeout(connect=10, read=150, write=60, pool=10)
RESPOND_DEADLINE_S = 240
JSON_DEADLINE_S = 90
TIMEOUT_RETRIES = 2
# Muse Spark Open on Baseten always reasons, at xhigh unless told otherwise, and max_tokens counts the reasoning: a review
# left at the default thought through its whole budget and answered nothing. Baseten runs none/minimal as low.
OPEN_EFFORT = {"minimal": "low", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "xhigh"}
OPEN_MIN_TOKENS = 8000  # the reasoning comes out of the same budget, even for a two-word translation
OPEN_MAX_IMAGES = 8  # per request on Baseten
OPEN_JSON_RULES = ("\n\nAnswer with one JSON object and nothing else: no code fence, no prose around it. Use exactly the keys of this "
                   "JSON schema, spelled as they are in English whatever language the values are in, with every required key present "
                   "and enum values copied exactly:\n")


def _retryable(status: int) -> bool:
    return status in (408, 409, 425, 429) or status >= 500


def _retry_after(headers: Any) -> float | None:
    """The provider's own wait hint: retry-after-ms first, then retry-after in seconds."""
    if not headers:
        return None
    for key, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        try:
            v = float(headers.get(key) or "")
        except ValueError:
            continue
        if v >= 0:
            return min(v * scale, 30.0)
    return None


@contextlib.asynccontextmanager
async def _deadline(seconds: float, what: str):
    """An overall limit per call; it ends as the client's own timeout error, so callers handle one kind."""
    try:
        async with asyncio.timeout(seconds):
            yield
    except TimeoutError as e:
        raise APITimeoutError(request=httpx.Request("POST", what)) from e


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def parse_json_object(text: str, required: Any = ()) -> dict[str, Any] | None:
    """The JSON object in a model's answer. Reasoning blocks (<think>...</think>), code fences and prose around
    it are skipped; the first object with every required key wins, else the first object at all."""
    text = _THINK.sub("", text or "")
    if "</think>" in text:  # the opening tag came from the chat template
        text = text.rsplit("</think>", 1)[1]
    decoder = json.JSONDecoder()
    first: dict[str, Any] | None = None
    i = text.find("{")
    while i >= 0:
        try:
            obj, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            if all(k in obj for k in required or ()):
                return obj
            if first is None:
                first = obj
        i = text.find("{", i + 1)
    return first


def _sam_purpose(prompt: str) -> str:
    """What a SAM call was for: its noun phrase, or how the person pointed at the object."""
    if "<|box" in prompt:
        return "box"
    if "<|point" in prompt:
        return "tap"
    return prompt


@dataclass
class CostMeter:
    budget_usd: float = 0.6
    usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    calls: int = 0
    by_model: dict[str, float] = field(default_factory=dict)
    # which models acted and what for: the "Meta models in this run" strip reads these
    calls_by_model: dict[str, int] = field(default_factory=dict)
    purposes_by_model: dict[str, dict[str, int]] = field(default_factory=dict)

    def check(self, estimate: float = 0.0) -> None:
        if self.usd + estimate > self.budget_usd:
            raise BudgetExceeded(f"job budget ${self.budget_usd:.2f} reached (spent ${self.usd:.3f})")

    def add(self, model: str, usd: float, tin: int = 0, tout: int = 0, tcached: int = 0, purpose: str | None = None) -> None:
        self.usd += usd
        self.tokens_in += tin
        self.tokens_out += tout
        self.tokens_cached += tcached
        self.calls += 1
        self.by_model[model] = self.by_model.get(model, 0.0) + usd
        self.calls_by_model[model] = self.calls_by_model.get(model, 0) + 1
        if purpose:
            purposes = self.purposes_by_model.setdefault(model, {})
            purpose = purpose.strip()[:60]
            purposes[purpose] = purposes.get(purpose, 0) + 1

    def summary(self) -> dict[str, Any]:
        return {
            "usd": round(self.usd, 5),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_cached": self.tokens_cached,
            "cache_ratio": round(self.tokens_cached / self.tokens_in, 3) if self.tokens_in else 0,
            "calls": self.calls,
            "by_model": {k: round(v, 5) for k, v in self.by_model.items()},
            "calls_by_model": dict(self.calls_by_model),
            "purposes_by_model": {k: dict(v) for k, v in self.purposes_by_model.items()},
        }


class _Limiter:
    """Slows down before the provider says 429, using remaining-quota headers."""

    def __init__(self) -> None:
        self.until: dict[str, float] = {}
        self.sem: dict[str, asyncio.Semaphore] = {}

    def gate(self, model: str) -> asyncio.Semaphore:
        if model not in self.sem:
            self.sem[model] = asyncio.Semaphore(4 if "contributor" in model or "image" in model else 16)
        return self.sem[model]

    async def before(self, model: str) -> None:
        delay = self.until.get(model, 0) - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

    def observe(self, model: str, headers: httpx.Headers | None) -> None:
        if not headers:
            return
        try:
            rem_req = int(headers.get("x-ratelimit-remaining-requests", "1000"))
            rem_tok = int(headers.get("x-ratelimit-remaining-tokens", "1000000"))
        except ValueError:
            return
        if rem_req < 5 or rem_tok < 20000:
            self.until[model] = time.monotonic() + 2.0


_limiter = _Limiter()


def _usage(resp: Any) -> tuple[int, int, int]:
    u = getattr(resp, "usage", None)
    if not u:
        return 0, 0, 0
    tin = getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", 0) or 0
    tout = getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", 0) or 0
    det = getattr(u, "input_tokens_details", None) or getattr(u, "prompt_tokens_details", None)
    cached = getattr(det, "cached_tokens", 0) if det else 0
    return int(tin), int(tout), int(cached or 0)


class MetaClient:
    def __init__(self) -> None:
        s = settings()
        self.s = s
        self.oai = AsyncOpenAI(base_url=s.meta_base_url, api_key=s.meta_api_key or "missing", max_retries=0, timeout=META_TIMEOUT)
        # open weights answer one-shot reviews: a cold or stuck endpoint gets a short leash, then Spark takes over
        self.open_timeout = float(getattr(s, "open_timeout_s", 60.0) or 60.0)
        self.open = (
            AsyncOpenAI(base_url=s.open_base_url, api_key=s.open_api_key or "none", max_retries=0,
                        timeout=httpx.Timeout(self.open_timeout, connect=10))
            if s.open_base_url
            else None
        )

    def model_for(self, role: str, default: str) -> str:
        """The open-weights model for the roles routed to it (settings.open_roles), else the default."""
        if self.open is None or not self.s.open_model:
            return default
        roles = getattr(self.s, "open_roles", "critic,classify,english")
        if isinstance(roles, str):
            roles = roles.split(",")
        return self.s.open_model if role in {r.strip() for r in roles} else default

    async def _retry(self, model: str, fn, attempts: int = 5):
        """Retries rate limits, gateway and server errors and dropped connections; timeouts at most twice.
        The backoff sleeps outside the model's concurrency gate, so a waiting call holds no slot."""
        delay = 0.5
        timeouts = 0
        for i in range(attempts):
            await _limiter.before(model)
            try:
                async with _limiter.gate(model):
                    raw = await fn()
            except (APIStatusError, httpx.HTTPStatusError) as e:
                status = e.status_code if isinstance(e, APIStatusError) else e.response.status_code
                if not _retryable(status) or i == attempts - 1:
                    raise
                wait = _retry_after(e.response.headers if e.response is not None else None)
                wait = delay if wait is None else wait
                log.warning("meta api %s on %s, retry in %.1fs", status, model, wait)
            except (httpx.TimeoutException, APITimeoutError):
                timeouts += 1
                if timeouts > TIMEOUT_RETRIES or i == attempts - 1:
                    raise
                wait = delay
                log.warning("meta api timeout on %s, retry in %.1fs", model, wait)
            except (httpx.TransportError, APIConnectionError):
                if i == attempts - 1:
                    raise
                wait = delay
            else:
                _limiter.observe(model, getattr(raw, "headers", None))
                return raw.parse() if hasattr(raw, "parse") else raw
            await asyncio.sleep(wait + random.random() * 0.3)
            delay = min(delay * 2, 20)

    # ---------------------------------------------------------------- text
    async def respond(
        self,
        meter: CostMeter,
        *,
        model: str,
        input: list[dict[str, Any]],
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        text_format: dict[str, Any] | None = None,
        effort: str | None = None,
        max_output_tokens: int = 8000,
        cache_key: str | None = None,
        include: list[str] | None = None,
        purpose: str | None = "designer",
    ) -> Any:
        """Responses API call. Input is the full append-only history (store=false)."""
        meter.check(0.002)
        is_open = model == self.s.open_model and self.open is not None
        client = self.open if is_open else self.oai
        kwargs: dict[str, Any] = {"model": model, "input": input, "max_output_tokens": max_output_tokens, "store": False}
        if instructions:
            kwargs["instructions"] = instructions
        if tools:
            kwargs["tools"] = tools
        if text_format:
            kwargs["text"] = {"format": text_format}
        if effort and not is_open:
            # summaries make the agent's thinking visible in the timeline
            kwargs["reasoning"] = {"effort": effort, "summary": "auto"}
            kwargs["include"] = ["reasoning.encrypted_content"] + (include or [])
        elif include:
            kwargs["include"] = include
        if cache_key and not is_open:
            kwargs["prompt_cache_key"] = cache_key
        if effort in ("xhigh", "max") and not is_open:
            # the deepest reasoning answers in one piece after a long silence: give that read more room
            kwargs["timeout"] = httpx.Timeout(connect=10, read=RESPOND_DEADLINE_S - 10, write=60, pool=10)
        async with _deadline(RESPOND_DEADLINE_S, f"{model}/responses"):
            resp = await self._retry(model, lambda: client.responses.with_raw_response.create(**kwargs))  # type: ignore[union-attr]
        tin, tout, cached = _usage(resp)
        searches = sum(1 for o in (resp.output or []) if getattr(o, "type", "") == "web_search_call")
        usd = pricing.token_cost(model, tin, cached, tout) + searches * pricing.WEB_SEARCH_PER_CALL
        meter.add(model, usd, tin, tout, cached, purpose=purpose)
        return resp

    async def json(
        self,
        meter: CostMeter,
        *,
        model: str,
        system: str,
        content: list[dict[str, Any]],
        schema: dict[str, Any],
        name: str = "result",
        effort: str | None = "low",
        max_output_tokens: int = 10000,
        purpose: str | None = None,
        fallback: bool = True,
        deadline: float = JSON_DEADLINE_S,
    ) -> dict[str, Any]:
        """One-shot structured call (critic, intake, classification).
        Reasoning tokens count against max_output_tokens; a truncated answer is retried with less reasoning.
        An open-weights model that fails or answers nothing usable hands over to Spark (settings.model_fast),
        unless fallback=False: then the caller decides. `deadline`: seconds for the whole call, retries included."""
        purpose = purpose or name
        if self.open is not None and model == self.s.open_model:
            try:
                async with _deadline(deadline, f"{model}/chat/completions"):
                    out = await self._open_json(meter, model=model, system=system, content=content, schema=schema, name=name,
                                                max_output_tokens=max_output_tokens, purpose=purpose, effort=effort)
            except BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001 - an open endpoint that is down or cold is not the job's failure
                if not fallback:
                    raise
                log.warning("open model %s failed on %s (%s: %s), falling back to %s", model, name, type(e).__name__, e, self.s.model_fast)
                out = {}
            if out or not fallback:
                return out
            model = self.s.model_fast
        async with _deadline(deadline, f"{model}/responses"):
            for attempt_effort in (effort, "minimal"):
                resp = await self.respond(
                    meter,
                    model=model,
                    instructions=system,
                    input=[{"type": "message", "role": "user", "content": content}],
                    text_format={"type": "json_schema", "name": name, "schema": schema},
                    effort=attempt_effort,
                    max_output_tokens=max_output_tokens,
                    cache_key=f"fw-{name}",
                    purpose=purpose,
                )
                text = resp.output_text or ""
                out = parse_json_object(text, schema.get("required"))
                if out is not None:
                    return out
                log.warning("structured call %s unparsable (status %s, %d chars), retrying", name, getattr(resp, "status", "?"), len(text))
        return {}

    async def _open_json(self, meter: CostMeter, *, model: str, system: str, content: list[dict[str, Any]], schema: dict[str, Any],
                         name: str, max_output_tokens: int, purpose: str | None = None, effort: str | None = None) -> dict[str, Any]:
        """Self-hosted open weights (Muse Glimmer / Spark Open behind vLLM, SGLang, llama.cpp or Baseten):
        Chat Completions is the common denominator of those servers. Baseten takes a json_schema response format for
        Muse Spark Open but does not enforce it, so the schema is spelled out in the prompt as well; the reasoning effort
        is sent explicitly (its default is xhigh); an answer without every required key counts as no answer."""
        meter.check(0.0)
        parts: list[dict[str, Any]] = []
        for c in content:
            if c.get("type") == "input_text":
                parts.append({"type": "text", "text": c["text"]})
            elif c.get("type") == "input_image":
                parts.append({"type": "image_url", "image_url": {"url": c["image_url"]}})
        # the provider's cap on images: the last ones (renders, the model over the photo) matter most, early photos go first
        images = [i for i, p in enumerate(parts) if p["type"] == "image_url"]
        if len(images) > OPEN_MAX_IMAGES:
            drop = set(images[:len(images) - OPEN_MAX_IMAGES])
            parts = [p for i, p in enumerate(parts) if i not in drop]
        required = schema.get("required") or ()
        prompt = system + OPEN_JSON_RULES + json.dumps(schema, ensure_ascii=False)

        def call(with_options: bool):
            kwargs: dict[str, Any] = {"model": model, "max_tokens": max(max_output_tokens, OPEN_MIN_TOKENS),
                                      "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": parts}]}
            if with_options:
                kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}
                kwargs["extra_body"] = {"reasoning_effort": OPEN_EFFORT.get(effort or "low", "low")}
            return lambda: self.open.chat.completions.with_raw_response.create(**kwargs)  # type: ignore[union-attr]

        try:
            resp = await self._retry(model, call(True), attempts=2)
        except APIStatusError as e:
            if e.status_code != 400:
                raise
            # a server without json_schema or reasoning_effort: the schema in the prompt is enough
            log.info("open model %s refused the request options for %s (%s), retrying without them", model, name, e.status_code)
            resp = await self._retry(model, call(False), attempts=2)
        tin, tout, cached = _usage(resp)
        meter.add(model, pricing.token_cost(model, tin, cached, tout), tin, tout, cached, purpose=purpose or name)
        # reasoning servers put their thinking in message.reasoning_content (not read) or inline as <think> blocks
        choice = resp.choices[0]
        text = choice.message.content or ""
        out = parse_json_object(text, required)
        missing = [k for k in required if k not in (out or {})]
        if out is None or missing:
            # why, so the next unusable answer explains itself: cut off while reasoning, keys of its own, or prose
            thought = getattr(choice.message, "reasoning_content", None) or getattr(choice.message, "reasoning", None) or ""
            log.warning("open model %s: no usable %s answer (finish %s, %d output tokens, %d chars of reasoning, missing %s): %r", model, name,
                        getattr(choice, "finish_reason", None), tout, len(str(thought)), missing or "every key", text[:2000])
            return {}
        return out

    async def search(self, meter: CostMeter, query: str, *, model: str | None = None, country: str | None = None) -> dict[str, Any]:
        """Web search grounding: returns answer text + cited sources."""
        tool: dict[str, Any] = {"type": "web_search", "search_context_size": "medium"}
        if country:
            tool["user_location"] = {"type": "approximate", "country": country}
        resp = await self.respond(
            meter,
            model=model or self.s.model_fast,
            input=[{"type": "message", "role": "user", "content": [{"type": "input_text", "text": query}]}],
            tools=[tool],
            include=["web_search_call.results"],
            effort="low",
            max_output_tokens=3000,
            purpose="search",
        )
        sources = []
        for item in resp.output or []:
            if getattr(item, "type", "") == "message":
                for c in getattr(item, "content", []) or []:
                    for a in getattr(c, "annotations", []) or []:
                        if getattr(a, "type", "") == "url_citation":
                            sources.append({"url": a.url, "title": getattr(a, "title", "")})
        return {"text": resp.output_text or "", "sources": sources}

    # ---------------------------------------------------------------- SAM
    async def sam(self, meter: CostMeter, image_data_url: str, prompt: str, *, include_confidence: bool = True, purpose: str | None = None) -> str:
        """Returns SAM's raw token text (decode with vision.sam)."""
        meter.check(pricing.SAM_PER_IMAGE)
        kwargs = {
            "model": self.s.model_sam,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_data_url},
            ]}],
            "metadata": {"mask_encoding": "one_bit", "include_confidence": "true" if include_confidence else "false"},
            "store": False,
        }
        resp = await self._retry(self.s.model_sam, lambda: self.oai.responses.with_raw_response.create(**kwargs))
        meter.add(self.s.model_sam, pricing.SAM_PER_IMAGE, purpose=purpose or _sam_purpose(prompt))
        return resp.output_text or ""

    async def sam_video(self, meter: CostMeter, file_id: str, prompt: str, frames_estimate: int) -> str:
        cost = max(frames_estimate, pricing.SAM_MIN_FRAMES) * pricing.SAM_PER_FRAME
        meter.check(cost)
        kwargs = {
            "model": self.s.model_sam,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_video", "file_id": file_id},
            ]}],
            "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
            "store": False,
        }
        resp = await self._retry(self.s.model_sam, lambda: self.oai.responses.with_raw_response.create(**kwargs))
        meter.add(self.s.model_sam, cost, purpose=_sam_purpose(prompt))
        return resp.output_text or ""

    async def upload(self, data: bytes, filename: str, mime: str) -> str:
        f = await self.oai.files.create(purpose="user_data", file=(filename, data, mime), expires_after={"anchor": "created_at", "seconds": 86400})
        return f.id

    # ---------------------------------------------------------------- images
    async def image(self, meter: CostMeter, prompt: str, *, images: list[str] | None = None, n: int = 1, size: str | None = None,
                    purpose: str | None = None) -> list[bytes]:
        meter.check(pricing.IMAGE_PER_IMAGE * n)
        if images:
            body: dict[str, Any] = {"model": self.s.model_image, "prompt": prompt, "n": n, "images": [{"image_url": u} for u in images], "output_format": "png"}
            if size:
                body["size"] = size

            async def edit() -> dict[str, Any]:
                async with httpx.AsyncClient(timeout=META_TIMEOUT) as h:
                    r = await h.post(f"{self.s.meta_base_url}/images/edits", json=body, headers={"Authorization": f"Bearer {self.s.meta_api_key}"})
                    r.raise_for_status()
                    return r.json()

            data = (await self._retry(self.s.model_image, edit))["data"]
        else:
            kwargs: dict[str, Any] = {"model": self.s.model_image, "prompt": prompt, "n": n, "extra_body": {"output_format": "png"}}
            if size:
                kwargs["size"] = size
            resp = await self._retry(self.s.model_image, lambda: self.oai.images.with_raw_response.generate(**kwargs))
            data = [{"b64_json": d.b64_json} for d in resp.data]
        out = [base64.b64decode(d["b64_json"]) for d in data if d.get("b64_json")]
        purpose = purpose or ("edit" if images else "concept")
        for _ in out:
            meter.add(self.s.model_image, pricing.IMAGE_PER_IMAGE, purpose=purpose)
        return out

    # ---------------------------------------------------------------- voice
    async def transcribe(self, meter: CostMeter, wav: bytes, *, keywords: list[str] | None = None, languages: list[str] | None = None,
                         purpose: str | None = "voice") -> str:
        req = {"model": self.s.model_voice, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
        if keywords:
            req["keywords"] = keywords
        if languages:
            req["languageBias"] = languages

        async def post() -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=META_TIMEOUT) as h:
                r = await h.post(
                    f"{self.s.meta_base_url}/asr/transcribe",
                    headers={"Authorization": f"Bearer {self.s.meta_api_key}", "Accept": "application/json"},
                    files={"request": (None, json.dumps(req), "application/json"), "audio": ("audio.wav", wav, "audio/wav")},
                )
                r.raise_for_status()
                return r.json()

        data = await self._retry(self.s.model_voice, post)
        seconds = (data.get("audioDurationMs") or 0) / 1000
        meter.add(self.s.model_voice, seconds * pricing.VOICE_PER_SECOND, purpose=purpose)
        return data.get("transcript", "")


_client: MetaClient | None = None


def meta() -> MetaClient:
    global _client
    if _client is None:
        _client = MetaClient()
    return _client
