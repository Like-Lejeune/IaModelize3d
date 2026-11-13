"""Live checks of the demo-path Meta endpoints before recording (about $0.05): Muse Image generate and edit,
Voice Transcribe, a structured call on Muse Wonder and one on the open-weights model with an image.
Opt-in: needs a key and FW_LIVE_TESTS=1, so the default suite stays offline.

    cd server && FW_LIVE_TESTS=1 .venv/Scripts/python -m pytest -q tests/test_meta_live.py -s
"""
from __future__ import annotations

import base64
import io
import math
import os
import struct
import wave

import pytest
from PIL import Image

from iamodelize3d.config import Settings, settings
from iamodelize3d.llm.client import CostMeter, MetaClient


def _live() -> bool:
    return os.environ.get("FW_LIVE_TESTS") == "1" and bool(Settings().meta_api_key)


pytestmark = pytest.mark.skipif(not _live(), reason="live Meta API: needs META_API_KEY and FW_LIVE_TESTS=1")

COLOR = {"type": "object", "properties": {"color": {"type": "string", "description": "one English colour word"}}, "required": ["color"]}


def _png(color: tuple[int, int, int], side: int = 256) -> str:
    img = Image.new("RGB", (side, side), (245, 245, 245))
    img.paste(color, (side // 4, side // 4, 3 * side // 4, 3 * side // 4))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _wav(seconds: float = 2.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(seconds * rate))))
    return buf.getvalue()


async def test_muse_image_generates_and_edits():
    mc, meter = MetaClient(), CostMeter(budget_usd=0.1)
    out = await mc.image(meter, "a small red ceramic cube on a plain white background, product photo", size="256x256")
    assert out and out[0][:8] == b"\x89PNG\r\n\x1a\n"
    url = "data:image/png;base64," + base64.b64encode(out[0]).decode()
    edited = await mc.image(meter, "make the cube blue, keep everything else", images=[url])
    assert edited and len(edited[0]) > 1000
    assert meter.purposes_by_model[settings().model_image] == {"concept": 1, "edit": 1}


async def test_voice_transcribe_answers():
    mc, meter = MetaClient(), CostMeter(budget_usd=0.01)
    text = await mc.transcribe(meter, _wav(), languages=["English"])
    assert isinstance(text, str)
    # a tone has no words; the service still measured the audio
    assert meter.by_model[settings().model_voice] > 0


async def test_structured_call_on_muse_wonder():
    mc, meter = MetaClient(), CostMeter(budget_usd=0.05)
    s = settings()
    out = await mc.json(meter, model=s.model_designer_hard, system="Answer the question.", schema=COLOR, name="live_check",
                        content=[{"type": "input_text", "text": "What colour is a ripe tomato?"}], max_output_tokens=2000)
    assert out.get("color")
    assert meter.calls_by_model.get(s.model_designer_hard, 0) >= 1


@pytest.mark.skipif(not (Settings().open_base_url and Settings().open_model), reason="no open-weights model configured")
async def test_open_weights_answer_json_about_an_image():
    """The critic's path on Muse Spark Open: Chat Completions, a JSON schema and an image, no fallback."""
    mc, meter = MetaClient(), CostMeter(budget_usd=0.05)
    s = settings()
    out = await mc.json(meter, model=s.open_model, system="You describe images.", schema=COLOR, name="live_check", fallback=False,
                        content=[{"type": "input_text", "text": "What colour is the square in the middle?"},
                                 {"type": "input_image", "image_url": _png((220, 30, 30))}], max_output_tokens=2000)
    assert out.get("color")
    assert meter.calls_by_model == {s.open_model: 1}
