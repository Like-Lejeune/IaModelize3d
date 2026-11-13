"""Spot: the object on an uploaded photo, found the moment the photo arrives.

A photo from the gallery comes without a tap, so a fast model names the object the person
most likely means (their request text helps) and boxes it, and SAM cuts it out inside that
box. The studio shows the cut-out at once and the person can correct it with taps before
the agent starts; the agent then works from that selection instead of searching again.

Naming takes most of the time, so SAM looks at the middle of the photo meanwhile; when that
turns out to be the named object (the usual product shot), no second SAM call is needed.
The agent does not wait for any of this to start: it reads the request meanwhile and waits
for the cut-out (`settled`) only when it comes to measuring the photos.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .. import quotas
from ..db import get_db
from ..llm.client import CostMeter, meta
from ..models import Point, SelectRequest
from .common import asset_image, data_url, norm_box_to_px
from .sam import Mask, segment
from .scene import _update_meta, calibrate, select

log = logging.getLogger(__name__)

LANGUAGES = {"ru": "Russian", "en": "English", "kk": "Kazakh"}

SPOT_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean", "description": "false when the photo shows no distinct object (a landscape, a screenshot, text)"},
        "label": {"type": "string", "description": "1-3 word noun phrase for the object, in the requested language"},
        "box": {"type": "array", "items": {"type": "number"}, "description": "[x_min, y_min, x_max, y_max] of the whole object, 0-1000 grid"},
        "objects": {
            "type": "array",
            "description": "up to 4 other distinct objects on the photo the person might mean instead",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "box": {"type": "array", "items": {"type": "number"}}},
                "required": ["label", "box"],
            },
        },
    },
    "required": ["found", "label", "box", "objects"],
}


def _language(lang: str) -> str:
    return LANGUAGES.get((lang or "en").lower()[:2], "English")


async def _find(meter: CostMeter, img: Any, hint: str, lang: str, model: str) -> dict[str, Any]:
    out = await meta().json(
        meter,
        model=model,
        system=(
            "A person uploads a photo to get a 3D-printable model: a copy of an object, a part that fits it, or something in its "
            "style. Find the one object they mean: the one their request names, else the main subject of the photo. Never a "
            "scale reference (a sheet of paper, a bank card, a coin, a ruler), the table, the background or a hand holding it. "
            "Boxes are [x_min, y_min, x_max, y_max] on a 0-1000 grid, tight around the whole object. "
            f"Write every label in {_language(lang)}, lowercase unless it is a proper name."
        ),
        content=[{"type": "input_text", "text": f"Their request: {hint}" if hint else "No request text yet."},
                 {"type": "input_image", "image_url": data_url(img, 1024)}],
        schema=SPOT_SCHEMA,
        name="spot",
        effort="minimal",
        max_output_tokens=1500,
    )
    return out if isinstance(out, dict) else {}


def objects_px(raw: list[Any], w: int, h: int) -> list[dict[str, Any]]:
    out = []
    for o in raw[:4]:
        if not isinstance(o, dict) or len(o.get("box") or []) != 4 or not str(o.get("label", "")).strip():
            continue
        x1, y1, x2, y2 = norm_box_to_px(o["box"], w, h)
        if x2 - x1 > 8 and y2 - y1 > 8:
            out.append({"label": str(o["label"]).strip()[:40], "bbox": [x1, y1, x2, y2]})
    return out


def _iou(a: list[float], b: list[float]) -> float:
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _at(masks: list[Mask], x: int, y: int) -> Mask | None:
    """The best mask under the point (SAM may also return pieces next to it)."""
    return max((m for m in masks if m.mask[y, x]), key=lambda m: m.score, default=None)


async def spot(user: dict[str, Any], project_id: str, asset: dict[str, Any], hint: str | None, lang: str) -> dict[str, Any]:
    """Find, cut out and measure the object; it replaces earlier target selections on this photo.
    Returns {selection, label, objects}; selection is None when nothing was found."""
    if asset["kind"] != "photo":
        raise ValueError("only photos are searched for an object")
    await quotas.check_light(user, 0.02)
    img = asset_image(asset)
    h, w = img.shape[:2]
    meter = CostMeter(budget_usd=0.06)
    model = (await quotas.choose_models(user)).fast
    cal = (asset.get("meta") or {}).get("calibration") or {}
    middle = {"x": (w - 1) // 2, "y": (h - 1) // 2, "positive": True}
    try:
        # the reference sheet is looked for meanwhile too: the object must not be cut out as the sheet
        jobs = [_find(meter, img, (hint or "").strip()[:500], lang, model), segment(meter, img, points=[middle])]
        if not cal.get("ok") and not cal.get("reason"):
            jobs.append(calibrate(meter, asset))
        found, guess, *_ = await asyncio.gather(*jobs, return_exceptions=True)
    finally:
        await quotas.settle(user["id"], meter.usd, is_job=False)
    if isinstance(found, BaseException):
        log.info("spot naming failed: %s", found)
        found = {}
    if isinstance(guess, BaseException):
        log.info("spot guess failed: %s", guess)
        guess = []
    label = str(found.get("label") or "").strip()[:40]
    objects = objects_px(found.get("objects") or [], w, h)
    box = norm_box_to_px(found["box"], w, h) if found.get("found", True) and len(found.get("box") or []) == 4 else None
    await _update_meta(asset["id"], {"spot": {"label": label, "objects": objects}})
    if not box or (box[2] - box[0]) * (box[3] - box[1]) <= 64:
        return {"selection": None, "label": label or None, "objects": objects}
    pad = 0.03 * max(box[2] - box[0], box[3] - box[1])
    pbox = [max(0, box[0] - pad), max(0, box[1] - pad), min(w - 1, box[2] + pad), min(h - 1, box[3] + pad)]
    hit = _at(guess, middle["x"], middle["y"])
    reuse = hit is not None and _iou(hit.bbox_px, box) >= 0.7
    req = SelectRequest(points=[Point(**middle)] if reuse else [], box=None if reuse else pbox, role="target", name=label or "object", replace=True, by="auto")
    try:
        fresh = await (await get_db()).one("SELECT * FROM assets WHERE id = ?", asset["id"])  # with the calibration
        sel = await select(user, project_id, fresh or asset, req, masks=[hit] if reuse else None)
    except ValueError as e:
        log.info("spot segmentation failed: %s", e)
        return {"selection": None, "label": label or None, "objects": objects}
    return {"selection": sel, "label": label or None, "objects": objects}


_running: dict[str, asyncio.Task] = {}


def start(user: dict[str, Any], project_id: str, asset: dict[str, Any], hint: str | None, lang: str) -> asyncio.Task:
    """`spot` as a task of its own: it outlives the request, and the agent can wait for it."""
    task = asyncio.create_task(spot(user, project_id, asset, hint, lang))
    _running[asset["id"]] = task
    task.add_done_callback(lambda t: _running.pop(asset["id"], None) if _running.get(asset["id"]) is t else None)
    return task


async def settled(asset_ids: list[str], timeout: float = 45.0) -> None:
    """Until no object is being found on these photos, so the agent measures what the person sees."""
    tasks = [t for a in asset_ids if (t := _running.get(a))]
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)
