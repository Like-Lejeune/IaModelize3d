"""Everything a model reads is English, whatever language the person writes in.

People's words reach other models as prompts in a few places: the segmenter's noun phrase
(SAM reads English only), image prompts, web searches, memory lookups over English lessons.
Those get translated here, once per distinct text; English text passes through untouched.
"""
from __future__ import annotations

import logging

from .client import CostMeter, meta

log = logging.getLogger(__name__)

SYSTEM = ("Translate the text into English. It becomes a prompt for another model (an image segmenter, an image generator, "
          "a web search or a keyword index). Keep numbers, units, sizes, proper names, brands and model names exactly. "
          "Keep the form: a short noun phrase stays a short noun phrase, an instruction stays an instruction. Add nothing.")
SCHEMA = {"type": "object", "properties": {"english": {"type": "string"}}, "required": ["english"]}

_known: dict[str, str] = {}


def is_english(text: str) -> bool:
    """No letters outside ASCII: English, or numbers and symbols only."""
    return not any(ch.isalpha() and not ch.isascii() for ch in text)


def remember(text: str, english: str) -> None:
    """A translation that came for free (e.g. from the intake model) saves a call later."""
    text, english = (text or "").strip(), (english or "").strip()
    if text and english and is_english(english) and not is_english(text):
        if len(_known) > 2000:
            _known.clear()
        _known[text] = english


async def english(meter: CostMeter, text: str | None, model: str) -> str:
    text = (text or "").strip()
    if not text or is_english(text):
        return text
    if text in _known:
        return _known[text]
    try:
        out = await meta().json(meter, model=meta().model_for("english", model), system=SYSTEM, content=[{"type": "input_text", "text": text[:4000]}],
                                schema=SCHEMA, name="english", effort="minimal", max_output_tokens=2000)
    except Exception as e:  # noqa: BLE001 - the original words are a worse prompt, not a failure
        log.info("translation failed: %s", e)
        return text
    result = str(out.get("english") or "").strip()
    if not result:
        return text
    remember(text, result)
    return result
