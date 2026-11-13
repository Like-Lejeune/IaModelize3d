"""Snap & collect: a photo of something out in the world becomes a printable miniature.

The tap on the phone screen is SAM's point prompt, so the object is found without asking;
a fast model names it in the user's language and lists other objects the person might
have meant. Street photos have no scale reference, so calibration is skipped and the
agent sizes the miniature from typical dimensions.

Right after the mask comes the instant 3D sticker (relief.py): outline loops and a relief
heightmap that lib.collect turns into a printable sticker in a second or two, in the
browser for the preview and in the geometry pool when it is kept (iamodelize3d/collect.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import cv2
import numpy as np

from .. import quotas
from ..db import get_db, new_id, now
from ..llm.client import CostMeter, meta
from . import relief
from .common import abs_path, asset_image, data_url, norm_box_to_px, write_bytes
from .sam import Mask, load_mask_png, save_mask_png, segment
from .scene import _insert_selection, _unique_name, _update_meta, measure_mask

log = logging.getLogger(__name__)

NO_REFERENCE = {"ok": False, "reason": "street photo: no scale reference"}
LANGUAGES = {"ru": "Russian", "en": "English", "kk": "Kazakh"}

NAME_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "1-3 word noun phrase for the selected object, in the requested language"},
        "part_only": {"type": "boolean", "description": "true when the outline covers only a piece of a larger object (a slat of a bench, "
                                                        "a cat's ear); false when it is the whole object"},
        "box": {"type": "array", "items": {"type": "number"}, "description": "[x_min, y_min, x_max, y_max] of the whole object, 0-1000 grid"},
        "organic": {"type": "boolean", "description": "true for living or free-form shapes (animals, plants, sculptures, rocks), "
                                                       "false for built objects with flat faces (benches, lamps, buildings, vehicles)"},
        "person": {"type": "boolean", "description": "true when the outlined object is a person or part of one (face, hands); "
                                                     "a statue or a toy is not a person"},
        "objects": {
            "type": "array",
            "description": "up to 4 other distinct objects in the photo worth collecting",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "box": {"type": "array", "items": {"type": "number"}}},
                "required": ["label", "box"],
            },
        },
    },
    "required": ["label", "part_only", "box", "organic", "person", "objects"],
}


def _language(lang: str) -> str:
    return LANGUAGES.get((lang or "en").lower()[:2], "English")


def _outlined(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """The photo with the selection drawn on it: naming what is outlined beats guessing what lies under a point."""
    out = img.copy()
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, contours, -1, (60, 255, 60), max(3, round(max(img.shape[:2]) / 250)))
    return out


async def _name(meter: CostMeter, img: np.ndarray, mask: np.ndarray | None, gx: float, gy: float, lang: str, model: str) -> dict[str, Any]:
    where = ("The selected object is outlined in bright green." if mask is not None
             else f"Nothing was selected automatically; the person tapped x={gx:.0f}, y={gy:.0f} on a 0-1000 grid.")
    client = meta()
    if hasattr(client, "model_for"):
        model = client.model_for("snap_name", model)  # may go to the open-weights model
    out = await client.json(
        meter,
        model=model,
        system=(
            "A person collects real-world objects as 3D-printed miniatures: they photograph something (a bench, a statue, "
            "a cat, a lamp post) and tap it on the screen. Name the selected object. Boxes are [x_min, y_min, x_max, y_max] "
            f"on a 0-1000 grid. Write every label in {_language(lang)}, lowercase unless it is a proper name."
        ),
        content=[{"type": "input_text", "text": where},
                 {"type": "input_image", "image_url": data_url(_outlined(img, mask) if mask is not None else img, 1024)}],
        schema=NAME_SCHEMA,
        name="snap_name",
        effort="minimal",
        max_output_tokens=1500,
    )
    return out if isinstance(out, dict) else {}


def _pick(masks: list[Mask], x: float, y: float) -> Mask | None:
    """The best mask that contains the tap; SAM may also return pieces next to it."""
    xi, yi = int(round(x)), int(round(y))
    inside = [m for m in masks if 0 <= yi < m.mask.shape[0] and 0 <= xi < m.mask.shape[1] and m.mask[yi, xi]]
    pool = inside or [m for m in masks if m.score >= 0.2] or masks
    return max(pool, key=lambda m: m.score) if pool else None


def _selection_data(img: np.ndarray, mask: Mask, extra: dict[str, Any]) -> dict[str, Any]:
    data = measure_mask(mask.mask, {}, image=img)
    data.update({"bbox_px": mask.bbox_px, "confidence": round(mask.score, 4), "calibration_note": NO_REFERENCE["reason"], **extra})
    return data


async def _replace_target(project_id: str, asset_id: str, name: str, prompt: dict[str, Any], mask: Mask, data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Exactly one target selection per snap photo: the new one replaces the old ones."""
    db = await get_db()
    old = await db.all("SELECT id FROM selections WHERE project_id = ? AND asset_id = ? AND role = 'target'", project_id, asset_id)
    gone = [r["id"] for r in old]
    sid = new_id("s_")
    mask_path = save_mask_png(f"{project_id}/{sid}_mask.png", mask.mask)
    name = await _unique_name(project_id, name.strip().replace(" ", "_")[:40] or "object", exclude=tuple(gone))
    # the new one first: a failure here leaves the old target, never none
    sel = await _insert_selection(project_id, asset_id, "target", name, prompt, mask_path, data, sid)
    if gone:
        await db.execute(f"DELETE FROM selections WHERE id IN ({','.join('?' * len(gone))})", *gone)
    return sel, gone


async def _set_subject(project: dict[str, Any], label: str, **brief: Any) -> None:
    db = await get_db()
    fresh = await db.one("SELECT title, brief FROM projects WHERE id = ?", project["id"]) or {}
    merged = {**(fresh.get("brief") or {}), "subject": label, **brief}
    updates: dict[str, Any] = {"brief": merged, "updated_at": now()}
    if label:
        updates["title"] = label[:1].upper() + label[1:60]
    await db.update("projects", "id", project["id"], updates)


def _objects(raw: list[Any], w: int, h: int) -> list[dict[str, Any]]:
    out = []
    for o in raw[:4]:
        if not isinstance(o, dict) or len(o.get("box") or []) != 4 or not str(o.get("label", "")).strip():
            continue
        x1, y1, x2, y2 = norm_box_to_px(o["box"], w, h)
        if x2 - x1 > 8 and y2 - y1 > 8:
            out.append({"label": str(o["label"]).strip()[:40], "bbox": [x1, y1, x2, y2]})
    return out


_naming: dict[str, asyncio.Task] = {}


def _fallback_label(lang: str) -> str:
    return "объект" if lang.startswith("ru") else "object"


async def snap(user: dict[str, Any], project: dict[str, Any], asset: dict[str, Any], x: float | None, y: float | None, lang: str) -> dict[str, Any]:
    """Segment the tapped object and answer as soon as the mask is there; the name follows (`named`).
    Naming takes longer than segmenting, and the highlight is what the person waits for."""
    await quotas.check_light(user, 0.02)
    asset["meta"] = (await _update_meta(asset["id"], {"calibration": NO_REFERENCE}))["meta"]
    img = asset_image(asset)
    h, w = img.shape[:2]
    px = min(max(x if x is not None else 0.5, 0.0), 1.0) * (w - 1)
    py = min(max(y if y is not None else 0.5, 0.0), 1.0) * (h - 1)
    meter = CostMeter(budget_usd=0.10)
    choice = await quotas.choose_models(user)
    point = {"x": px, "y": py, "positive": True}
    try:
        masks = await segment(meter, img, points=[point])
    except Exception as e:  # noqa: BLE001 - the name may still find the object by its box
        log.info("snap segmentation failed: %s", e)
        masks = []
    mask = _pick(masks, px, py)
    if mask is not None and not mask.mask.any():
        mask = None
    await _set_subject(project, "", language=lang[:2], snap={"asset_id": asset["id"], "tap": [round(px), round(py)]})
    out: dict[str, Any] = {"label": None, "objects": [], "selection": None, "removed": [], "sticker": None}
    if mask is not None:
        data = _selection_data(img, mask, {"tap_px": [round(px), round(py)]})
        out["selection"], out["removed"] = await _replace_target(project["id"], asset["id"], _fallback_label(lang), {"points": [point], "box": None, "text": None},
                                                                 mask, data)
        try:
            out["sticker"] = await sticker_for(project["id"], asset, out["selection"], img=img, mask=mask.mask)
        except Exception as e:  # noqa: BLE001 - the highlight still stands; the sticker is asked for again
            log.warning("snap sticker failed: %s", e)
    _naming[project["id"]] = asyncio.create_task(_finish_naming(user, project, asset, img, choice.fast, meter, point, mask, out["selection"], lang))
    return out


def _grow_to(mask: Mask | None, named: dict[str, Any], point: dict[str, Any], w: int, h: int) -> list[float] | None:
    """The whole object's box when the selection is only a piece of it (or nothing was found), else None."""
    box = norm_box_to_px(named["box"], w, h) if len(named.get("box") or []) == 4 else None
    if not box or (box[2] - box[0]) * (box[3] - box[1]) <= 64:
        return None
    if mask is not None:
        if not named.get("part_only") or not (box[0] <= point["x"] <= box[2] and box[1] <= point["y"] <= box[3]):
            return None
        m = mask.bbox_px  # the piece must lie inside the whole
        inter = max(0, min(m[2], box[2]) - max(m[0], box[0])) * max(0, min(m[3], box[3]) - max(m[1], box[1]))
        if inter < 0.7 * max(1, (m[2] - m[0]) * (m[3] - m[1])):
            return None
    pad = 0.03 * max(box[2] - box[0], box[3] - box[1])
    return [max(0, box[0] - pad), max(0, box[1] - pad), min(w - 1, box[2] + pad), min(h - 1, box[3] + pad)]


async def _finish_naming(user: dict[str, Any], project: dict[str, Any], asset: dict[str, Any], img: np.ndarray, model: str,
                         meter: CostMeter, point: dict[str, Any], mask: Mask | None, sel: dict[str, Any] | None, lang: str) -> dict[str, Any]:
    h, w = img.shape[:2]
    db = await get_db()
    try:
        try:
            named = await _name(meter, img, mask.mask if mask is not None else None, point["x"] / w * 1000, point["y"] / h * 1000, lang, model)
        except Exception as e:  # noqa: BLE001 - a nameless object is still collectable
            log.info("snap naming failed: %s", e)
            named = {}
        label = str(named.get("label") or "").strip()[:40] or _fallback_label(lang)
        objects = _objects(named.get("objects") or [], w, h)
        out: dict[str, Any] = {"label": label, "objects": objects, "selection": None, "removed": []}
        current = await db.one("SELECT * FROM selections WHERE project_id = ? AND asset_id = ? AND role = 'target'", project["id"], asset["id"])
        untouched = (current or {}).get("id") == (sel or {}).get("id")  # no correction by the person meanwhile
        # a tap on a detail gives just that detail; the whole object's box fixes it
        pbox = _grow_to(mask, named, point, w, h) if untouched else None
        if pbox:
            try:
                better = _pick(await segment(meter, img, points=[point], box=pbox), point["x"], point["y"])
            except Exception as e:  # noqa: BLE001 - keep the first mask
                log.info("snap box refine failed: %s", e)
                better = None
            if better is not None and better.mask.any() and (mask is None or better.area > mask.area):
                data = _selection_data(img, better, {"tap_px": [round(point["x"]), round(point["y"])]})
                out["selection"], out["removed"] = await _replace_target(project["id"], asset["id"], label,
                                                                         {"points": [point], "box": pbox, "text": None}, better, data)
        if out["selection"] is None and current:
            # name the selection after the object (unless the person picked another one meanwhile)
            name = label.replace(" ", "_")[:40]
            if (untouched or current["name"] == _fallback_label(lang)) and current["name"] != name:
                current["name"] = await _unique_name(project["id"], name)
                await db.update("selections", "id", current["id"], {"name": current["name"]})
            out["selection"] = current
        fresh = (await db.one("SELECT brief FROM projects WHERE id = ?", project["id"]) or {}).get("brief") or {}
        snap_info = {**(fresh.get("snap") or {}), "objects": objects, "organic": bool(named.get("organic")), "person": bool(named.get("person"))}
        await _set_subject(project, fresh.get("subject") or label, snap=snap_info)
        out["label"] = fresh.get("subject") or label
        return out
    finally:
        await quotas.settle(user["id"], meter.usd, is_job=False)


async def named(project: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    """The name of the snapped object (waits for the naming call if it is still running)."""
    task = _naming.get(project["id"])
    if task is not None:
        try:
            return await asyncio.wait_for(asyncio.shield(task), 45)
        finally:
            if task.done():
                _naming.pop(project["id"], None)
    db = await get_db()
    p = await db.one("SELECT brief FROM projects WHERE id = ?", project["id"]) or {}
    brief = p.get("brief") or {}
    sel = await db.one("SELECT * FROM selections WHERE project_id = ? AND role = 'target' ORDER BY created_at DESC LIMIT 1", project["id"])
    return {"label": brief.get("subject") or _fallback_label(lang), "objects": (brief.get("snap") or {}).get("objects") or [], "selection": sel, "removed": []}


async def reselect(user: dict[str, Any], project: dict[str, Any], asset: dict[str, Any], points: list[dict[str, Any]],
                   box: list[float] | None, label: str | None) -> dict[str, Any]:
    """Refine the selection with more taps (positive/negative) or switch to another object by its box."""
    if not points and not box:
        raise ValueError("tap the object or pick one of the suggestions")
    await quotas.check_light(user, 0.01)
    img = asset_image(asset)
    meter = CostMeter(budget_usd=0.05)
    try:
        masks = await segment(meter, img, points=points or None, box=box)
    finally:
        await quotas.settle(user["id"], meter.usd, is_job=False)
    first = next((p for p in points if p.get("positive", True)), None)
    mask = _pick(masks, first["x"], first["y"]) if first else (max(masks, key=lambda m: m.score) if masks else None)
    if mask is None or not mask.mask.any():
        raise ValueError("nothing found there; tap the middle of the object")
    db = await get_db()
    current = await db.one("SELECT name FROM selections WHERE project_id = ? AND asset_id = ? AND role = 'target'", project["id"], asset["id"])
    brief = (await db.one("SELECT brief FROM projects WHERE id = ?", project["id"]) or {}).get("brief") or {}
    label = (label or "").strip()[:40]
    name = label or (current or {}).get("name") or brief.get("subject") or "object"
    data = _selection_data(img, mask, {})
    sel, removed = await _replace_target(project["id"], asset["id"], name, {"points": points, "box": box, "text": None}, mask, data)
    if label:
        await _set_subject(project, label)
    return {"selection": sel, "removed": removed, "label": label or brief.get("subject") or name}


# ------------------------------------------------------------------ the instant 3D sticker
def sticker_detail(brief: dict[str, Any] | None, asset: dict[str, Any]) -> float:
    """Photo detail of the relief: none for a person, and none while a photo with blurred faces is still unnamed."""
    snap_info = (brief or {}).get("snap") or {}
    if "person" in snap_info:
        return 0.0 if snap_info["person"] else relief.DETAIL
    meta_info = asset.get("meta") or {}
    # a photo the face pass could not look at may have faces in it
    return 0.0 if meta_info.get("faces_blurred") or meta_info.get("blur_skipped") else relief.DETAIL


async def sticker_for(project_id: str, asset: dict[str, Any], sel: dict[str, Any], *, img: np.ndarray | None = None,
                      mask: np.ndarray | None = None) -> dict[str, Any]:
    """The sticker payload (relief.sticker) of the current target selection, named after the subject.
    Kept on disk next to the mask until the selection changes: ~0.1 s to make, ~130 KB to send."""
    db = await get_db()
    brief = (await db.one("SELECT brief FROM projects WHERE id = ?", project_id) or {}).get("brief") or {}
    detail = sticker_detail(brief, asset)
    key = f"{sel['id']}_{'d' if detail else 'p'}"
    rel = f"{project_id}/sticker/{key}.json"
    path = abs_path(rel)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        if img is None:
            img = asset_image(asset)
        if mask is None:
            if not sel.get("mask_path"):
                raise ValueError("the selection has no mask")
            mask = load_mask_png(sel["mask_path"])
        payload = await asyncio.to_thread(relief.sticker, img, mask, detail=detail)
        for old in path.parent.glob("*.json") if path.parent.exists() else []:
            old.unlink(missing_ok=True)  # an earlier selection's sticker
        write_bytes(rel, json.dumps(payload, separators=(",", ":")).encode())
    payload["inputs"]["values"]["name"] = str(brief.get("subject") or "")
    return {**payload, "key": key, "selection_id": sel["id"]}


# ------------------------------------------------------------------ starting the agent
def snap_asset_id(project: dict[str, Any]) -> str | None:
    return ((project.get("brief") or {}).get("snap") or {}).get("asset_id")


async def running_jobs(user_id: str) -> int:
    """Jobs that hold the next snap back: a row a restart left 'running' or a job waiting for an answer does not."""
    return len(quotas.blocking(await quotas.active_jobs(user_id)))


def concurrent_limit(user: dict[str, Any]) -> int:
    return quotas.TIERS.get(user["tier"], quotas.TIERS["anon"])[1]


async def start_or_queue(user: dict[str, Any], project: dict[str, Any], body: Any) -> dict[str, Any]:
    """Collecting means snapping the next object while the last one is still being modelled: when the
    plan allows no more parallel jobs, the request waits in the project's brief and starts later."""
    from ..agent.runner import start_design_job

    db = await get_db()
    if await running_jobs(user["id"]) >= concurrent_limit(user):
        brief = (await db.one("SELECT brief FROM projects WHERE id = ?", project["id"]) or {}).get("brief") or {}
        await db.update("projects", "id", project["id"], {"brief": {**brief, "queued": {**body.model_dump(), "at": now()}}, "updated_at": now()})
        ensure_drain(user["id"])
        return {"queued": True, "job_id": None}
    job_id = await start_design_job(user, project, body)
    return {"queued": False, "job_id": job_id}


_drainers: dict[str, asyncio.Task] = {}


def ensure_drain(user_id: str) -> None:
    task = _drainers.get(user_id)
    if task is None or task.done():
        _drainers[user_id] = asyncio.create_task(_drain(user_id))


async def queued_projects(user_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    return await db.all("SELECT * FROM projects WHERE user_id = ? AND pack = 'collect' AND json_extract(brief, '$.queued') IS NOT NULL "
                        "ORDER BY json_extract(brief, '$.queued.at')", user_id)


async def _drain(user_id: str) -> None:
    from ..agent.runner import start_design_job
    from ..models import SendMessage

    db = await get_db()
    while True:
        await asyncio.sleep(3)
        try:
            waiting = await queued_projects(user_id)
            if not waiting:
                return
            user = await db.one("SELECT * FROM users WHERE id = ?", user_id)
            if not user or await running_jobs(user_id) >= concurrent_limit(user):
                continue
            project = waiting[0]
            brief = dict(project["brief"] or {})
            queued = brief.pop("queued") or {}
            req = {k: v for k, v in queued.items() if k != "at"}
            await db.update("projects", "id", project["id"], {"brief": brief})
            project["brief"] = brief
            try:
                await start_design_job(user, project, SendMessage(**req))
            except quotas.QuotaExceeded as e:
                if e.code in ("job_running", "project_busy"):
                    # another job started meanwhile: back in the queue
                    await db.update("projects", "id", project["id"], {"brief": {**brief, "queued": queued}})
                    continue
                # out of budget for today: every waiting snap would fail the same way
                for p in waiting:
                    b = {k: v for k, v in (p["brief"] or {}).items() if k != "queued"}
                    await db.update("projects", "id", p["id"], {"brief": {**b, "queue_error": str(e)[:200]}})
                return
        except Exception:  # noqa: BLE001 - the queue must survive a bad item
            log.exception("snap queue for %s", user_id)
            await asyncio.sleep(10)
