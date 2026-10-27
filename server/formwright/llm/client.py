"""Meta Model API client: Responses API for text/vision/tools/search and SAM,
images for Muse Image, multipart for Voice Transcribe.

Every call is metered into a CostMeter (per job) so budgets are enforced before a
request is sent and usage is exact afterwards. Rate limits are respected with an
adaptive limiter fed by the x-ratelimit-* headers.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
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


@dataclass
class CostMeter:
    budget_usd: float = 0.6
    usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    calls: int = 0
    by_model: dict[str, float] = field(default_factory=dict)

    def check(self, estimate: float = 0.0) -> None:
        if self.usd + estimate > self.budget_usd:
            raise BudgetExceeded(f"job budget ${self.budget_usd:.2f} reached (spent ${self.usd:.3f})")

    def add(self, model: str, usd: float, tin: int = 0, tout: int = 0, tcached: int = 0) -> None:
        self.usd += usd
        self.tokens_in += tin
        self.tokens_out += tout
        self.tokens_cached += tcached
        self.calls += 1
        self.by_model[model] = self.by_model.get(model, 0.0) + usd

    def summary(self) -> dict[str, Any]:
        return {
            "usd": round(self.usd, 5),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_cached": self.tokens_cached,
            "cache_ratio": round(self.tokens_cached / self.tokens_in, 3) if self.tokens_in else 0,
            "calls": self.calls,
            "by_model": {k: round(v, 5) for k, v in self.by_model.items()},
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
        self.oai = AsyncOpenAI(base_url=s.meta_base_url, api_key=s.meta_api_key or "missing", max_retries=0, timeout=300)
        self.open = (
            AsyncOpenAI(base_url=s.open_base_url, api_key=s.open_api_key or "none", max_retries=0, timeout=300)
            if s.open_base_url
            else None
        )

    async def _retry(self, model: str, fn, attempts: int = 5):
        delay = 0.5
        for i in range(attempts):
            await _limiter.before(model)
            async with _limiter.gate(model):
                try:
                    raw = await fn()
                    _limiter.observe(model, getattr(raw, "headers", None))
                    return raw.parse() if hasattr(raw, "parse") else raw
                except APIStatusError as e:
                    retryable = e.status_code in (429, 500, 503)
                    if not retryable or i == attempts - 1:
                        raise
                    ra = e.response.headers.get("retry-after") if e.response is not None else None
                    wait = float(ra) if ra and ra.replace(".", "").isdigit() else delay
                    log.warning("meta api %s on %s, retry in %.1fs", e.status_code, model, wait)
                    await asyncio.sleep(wait + random.random() * 0.3)
                    delay = min(delay * 2, 20)
                except (httpx.TimeoutException, httpx.TransportError, APIConnectionError, APITimeoutError):
                    if i == attempts - 1:
                        raise
                    await asyncio.sleep(delay)
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
            kwargs["reasoning"] = {"effort": effort}
            kwargs["include"] = ["reasoning.encrypted_content"] + (include or [])
        elif include:
            kwargs["include"] = include
        if cache_key and not is_open:
            kwargs["prompt_cache_key"] = cache_key
        resp = await self._retry(model, lambda: client.responses.with_raw_response.create(**kwargs))  # type: ignore[union-attr]
        tin, tout, cached = _usage(resp)
        searches = sum(1 for o in (resp.output or []) if getattr(o, "type", "") == "web_search_call")
        usd = pricing.token_cost(model, tin, cached, tout) + searches * pricing.WEB_SEARCH_PER_CALL
        meter.add(model, usd, tin, tout, cached)
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
    ) -> dict[str, Any]:
        """One-shot structured call (critic, intake, classification).
        Reasoning tokens count against max_output_tokens; a truncated answer is retried with less reasoning."""
        if self.open is not None and model == self.s.open_model:
            return await self._open_json(meter, model=model, system=system, content=content, schema=schema, name=name, max_output_tokens=max_output_tokens)
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
            )
            text = resp.output_text or ""
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                start, end = text.find("{"), text.rfind("}")
                if start >= 0:
                    try:
                        return json.loads(text[start : end + 1])
                    except json.JSONDecodeError:
                        pass
            log.warning("structured call %s unparsable (status %s, %d chars), retrying", name, getattr(resp, "status", "?"), len(text))
        return {}

    async def _open_json(self, meter: CostMeter, *, model: str, system: str, content: list[dict[str, Any]], schema: dict[str, Any],
                         name: str, max_output_tokens: int) -> dict[str, Any]:
        """Self-hosted open weights (Muse Glimmer / Spark Open behind vLLM, SGLang or llama.cpp):
        Chat Completions with a JSON schema is the common denominator of those servers."""
        parts: list[dict[str, Any]] = []
        for c in content:
            if c.get("type") == "input_text":
                parts.append({"type": "text", "text": c["text"]})
            elif c.get("type") == "input_image":
                parts.append({"type": "image_url", "image_url": {"url": c["image_url"]}})
        resp = await self._retry(model, lambda: self.open.chat.completions.with_raw_response.create(  # type: ignore[union-attr]
            model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": parts}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema}}, max_tokens=max_output_tokens,
        ))
        tin, tout, cached = _usage(resp)
        meter.add(model, 0.0, tin, tout, cached)
        text = resp.choices[0].message.content or "{}"
        start, end = text.find("{"), text.rfind("}")
        try:
            return json.loads(text[start : end + 1]) if start >= 0 else {}
        except json.JSONDecodeError:
            return {}

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
    async def sam(self, meter: CostMeter, image_data_url: str, prompt: str, *, include_confidence: bool = True) -> str:
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
        meter.add(self.s.model_sam, pricing.SAM_PER_IMAGE)
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
        meter.add(self.s.model_sam, cost)
        return resp.output_text or ""

    async def upload(self, data: bytes, filename: str, mime: str) -> str:
        f = await self.oai.files.create(purpose="user_data", file=(filename, data, mime), expires_after={"anchor": "created_at", "seconds": 86400})
        return f.id

    # ---------------------------------------------------------------- images
    async def image(self, meter: CostMeter, prompt: str, *, images: list[str] | None = None, n: int = 1, size: str | None = None) -> list[bytes]:
        meter.check(pricing.IMAGE_PER_IMAGE * n)
        if images:
            body: dict[str, Any] = {"model": self.s.model_image, "prompt": prompt, "n": n, "images": [{"image_url": u} for u in images], "output_format": "png"}
            if size:
                body["size"] = size
            async with httpx.AsyncClient(timeout=300) as h:
                r = await h.post(f"{self.s.meta_base_url}/images/edits", json=body, headers={"Authorization": f"Bearer {self.s.meta_api_key}"})
                r.raise_for_status()
                data = r.json()["data"]
        else:
            kwargs: dict[str, Any] = {"model": self.s.model_image, "prompt": prompt, "n": n, "extra_body": {"output_format": "png"}}
            if size:
                kwargs["size"] = size
            resp = await self._retry(self.s.model_image, lambda: self.oai.images.with_raw_response.generate(**kwargs))
            data = [{"b64_json": d.b64_json} for d in resp.data]
        out = [base64.b64decode(d["b64_json"]) for d in data if d.get("b64_json")]
        meter.add(self.s.model_image, pricing.IMAGE_PER_IMAGE * len(out))
        return out

    # ---------------------------------------------------------------- voice
    async def transcribe(self, meter: CostMeter, wav: bytes, *, keywords: list[str] | None = None, languages: list[str] | None = None) -> str:
        req = {"model": self.s.model_voice, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
        if keywords:
            req["keywords"] = keywords
        if languages:
            req["languageBias"] = languages
        async with httpx.AsyncClient(timeout=300) as h:
            r = await h.post(
                f"{self.s.meta_base_url}/asr/transcribe",
                headers={"Authorization": f"Bearer {self.s.meta_api_key}", "Accept": "application/json"},
                files={"request": (None, json.dumps(req), "application/json"), "audio": ("audio.wav", wav, "audio/wav")},
            )
            r.raise_for_status()
            data = r.json()
        seconds = (data.get("audioDurationMs") or 0) / 1000
        meter.add(self.s.model_voice, seconds * pricing.VOICE_PER_SECOND)
        return data.get("transcript", "")


_client: MetaClient | None = None


def meta() -> MetaClient:
    global _client
    if _client is None:
        _client = MetaClient()
    return _client
