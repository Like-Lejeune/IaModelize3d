"""Snap & collect without the agent: the instant 3D sticker and the collection plate.

GET  /api/snap/{id}/sticker       the sticker payload of the current selection (vision/snap.py sticker_for); the
                                  browser builds its 3D preview from it. ?have=<key> answers {same: true} when unchanged.
POST /api/snap/{id}/sticker.png   the same sticker rendered by the geometry pool: the preview for a phone whose own
                                  build is too slow.
POST /api/snap/{id}/keep          {label, size}: the sticker built and checked in the pool (analyze full + cover render),
                                  saved as the project's next version with author 'instant'. The collection shows it
                                  as ready at once; "make a figurine" (the agent) stays available.
POST /api/collection/plate        {ids, size_mm, gap}: the chosen finds as stickers on one bed of the farm's printer
                                  (Bambu Lab A1, 256 x 256), a new project of its own with brief.plate (the collection
                                  list skips those). Slicing and ordering then go through the usual project endpoints.

Mounted by app.py through its ROUTERS registry; app is reached lazily (app.current_user, app.load_project), because
app imports this module while it is being built. Errors are JSON {detail, code}.
"""
from __future__ import annotations

import base64
import json
import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import events, storage
from .db import get_db, new_id, now
from .geom import GeomError, geom

log = logging.getLogger(__name__)
router = APIRouter(tags=["collect"])

# OrcaSlicer over the kernel's own estimate on instant stickers: Bambu Lab A1 0.4 nozzle, PLA, default process,
# 2026-10-30 (cat, bench, two more cats, and the 6-find plate: 90.1 min / 26.9 g, no supports, nothing outside).
# The kernel counts no travel or slow top layers, so stickers take about twice its minutes; a plate shares travel.
ORCA_PER_KERNEL = {
    "sticker": {"grams": (0.96, 0.92, 1.00), "minutes": (2.2, 2.0, 2.35)},
    "plate": {"grams": (0.95, 0.92, 1.00), "minutes": (1.85, 1.7, 2.3)},
}
A1_MINI = (180.0, 180.0)
PLATE_MARGIN = 8.0  # mm from the bed edge, as lib.collect.plate packs
MAX_PLATE = 30
# a flat sticker reads from above and in front, not from the low iso corner; the panel keeps its size line and 10 mm bar
COVER_VIEW = [{"name": "", "azimuth": 0, "elevation": 60}]

PLATE_SOURCE = """const meta = { title: 'Collection plate', pack: 'collect', printNotes: 'All stickers flat on one bed, no supports. Two colours: swap filament at 1.6 mm (dark bases, light reliefs).' };
const params = {
  size: { value: 48, min: 25, max: 80, unit: 'mm', label: 'Sticker size', source: 'design' },
  gap:  { value: 6,  min: 3,  max: 15, unit: 'mm', label: 'Gap',          source: 'design' },
};
function build(p, lib) { return lib.collect.plate(lib.inputs.values.keys, { size: p.size, gap: p.gap }); }
return { meta, params, build };
"""


def _app():
    from formwright import app as app_module  # lazy: app.py includes this router

    return app_module


async def _user(request: Request, response: Response) -> dict[str, Any]:
    return await _app().current_user(request, response)


def _err(status: int, detail: str, code: str, **info: Any) -> HTTPException:
    return HTTPException(status, {"detail": detail, "code": code, **info})


async def _snap_project(project_id: str, user: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The person's own snap project with its photo and current target selection."""
    from .vision import snap

    p = await _app().load_project(project_id, user, write=True)
    db = await get_db()
    asset = await db.one("SELECT * FROM assets WHERE id = ? AND project_id = ?", snap.snap_asset_id(p) or "", project_id)
    if p["pack"] != "collect" or not asset or (p["brief"] or {}).get("plate"):
        raise _err(400, "not a snap project", "not_snap")
    sel = await _target(project_id, asset["id"])
    if not sel:
        raise _err(400, "nothing is selected on this snap yet: tap the object", "no_selection")
    return p, asset, sel


async def _target(project_id: str, asset_id: str) -> dict[str, Any] | None:
    db = await get_db()
    return await db.one("SELECT * FROM selections WHERE project_id = ? AND asset_id = ? AND role = 'target' AND mask_path IS NOT NULL "
                        "ORDER BY created_at DESC LIMIT 1", project_id, asset_id)


def _printer() -> dict[str, Any] | None:
    """The farm printer's profile (shop farm preset, Bambu Lab A1 0.4), or None for the kernel's default 256 mm bed."""
    try:
        from .printing import service
        from .shop.quote import shop_settings

        return service.printer_profile(shop_settings().farm_preset)
    except Exception as e:  # noqa: BLE001 - presets or the shop may be missing on a bare server
        log.info("no farm printer profile: %s", e)
        return None


def estimate(stats: dict[str, Any], kind: str = "sticker") -> dict[str, Any]:
    """Grams and minutes as Orca would slice them (calibrated from the kernel's estimate), with a price for the farm."""
    f = ORCA_PER_KERNEL[kind]
    g, m = float(stats.get("estGrams") or 0), float(stats.get("estMinutes") or 0)
    out: dict[str, Any] = {
        "grams": round(g * f["grams"][0], 1), "minutes": round(m * f["minutes"][0]),
        "grams_range": [round(g * f["grams"][1], 1), round(g * f["grams"][2], 1)],
        "minutes_range": [round(m * f["minutes"][1]), round(m * f["minutes"][2])],
        "source": "kernel, calibrated on OrcaSlicer (Bambu Lab A1 0.4, PLA)",
    }
    try:
        from .shop import quote

        q = quote.price(grams=out["grams"], minutes=out["minutes"], material="PLA", new_part=False, delivery="courier")
        out["price"] = {"currency": q["currency"], "print": q["parts"], "delivery": q["delivery"]["price"], "total": q["total"],
                        "usd": {"rate": q["usd"]["rate"], "print": q["usd"]["parts"], "delivery": q["usd"]["delivery"], "total": q["usd"]["total"]},
                        "binding": False}
    except Exception as e:  # noqa: BLE001 - the price is a nice-to-have next to grams and minutes
        log.info("no instant price: %s", e)
    return out


def _fits(size: list[float], bed: tuple[float, float]) -> bool:
    w, h = size[0], size[1]
    return (w <= bed[0] and h <= bed[1]) or (w <= bed[1] and h <= bed[0])


async def _next_version(project_id: str) -> int:
    db = await get_db()
    row = await db.one("SELECT COALESCE(MAX(version), 0) AS v FROM programs WHERE project_id = ?", project_id)
    return int((row or {}).get("v") or 0) + 1


async def _save_version(project: dict[str, Any], source: str, params: dict[str, Any], inputs: dict[str, Any], summary: str,
                        built: dict[str, Any], iso_png: bytes) -> tuple[int, str]:
    """A new program version (author 'instant') with its cover, announced like an agent's build."""
    db = await get_db()
    pid = project["id"]
    checks = built.get("checks") or {}
    for attempt in range(3):
        version = await _next_version(pid)
        cover = storage.save_bytes(pid, "renders", f"v{version}_iso.png", iso_png)
        try:
            await db.insert("programs", {"project_id": pid, "version": version, "source": source, "params": built.get("params") or params,
                                         "inputs": inputs, "summary": summary, "checks": checks, "author": "instant", "created_at": now()})
            break
        except sqlite3.IntegrityError:
            if attempt == 2:
                raise
    await db.update("projects", "id", pid, {"version": version, "cover": cover, "updated_at": now()})
    event = {"version": version, "source": source, "inputs": inputs, "params": built.get("params") or params, "paramSpecs": built.get("paramSpecs"),
             "handles": built.get("handles", []), "checks": checks, "render": storage.url(cover), "cover": storage.url(cover),
             "summary": summary, "author": "instant"}
    if len(json.dumps(inputs)) > 100_000:
        # big heightmaps stay out of the event stream; the client fetches the version instead
        event.pop("source")
        event.pop("inputs")
    await events.emit(pid, "program.updated", event)
    return version, cover


# ------------------------------------------------------------------ the sticker of one snap
@router.get("/api/snap/{project_id}/sticker")
async def snap_sticker(project_id: str, have: str | None = None, user=Depends(_user)):
    """The current selection's sticker: {key, selection_id, source, inputs, params, size_mm, detail}."""
    from .vision import snap

    _, asset, sel = await _snap_project(project_id, user)
    try:
        s = await snap.sticker_for(project_id, asset, sel)
    except ValueError as e:
        raise _err(400, str(e), "no_sticker") from e
    if have and have == s["key"]:
        return {"key": s["key"], "same": True}
    return s


class StickerRender(BaseModel):
    size: float = Field(50, ge=25, le=90)
    label: str | None = Field(None, max_length=40)


@router.post("/api/snap/{project_id}/sticker.png")
async def snap_sticker_png(project_id: str, body: StickerRender, user=Depends(_user)):
    """The sticker rendered on the server (from above and in front): the preview for a phone that builds too slowly itself."""
    from .vision import snap

    _, asset, sel = await _snap_project(project_id, user)
    s = await snap.sticker_for(project_id, asset, sel)
    if body.label is not None:
        s["inputs"]["values"]["name"] = body.label.strip()
    out = await geom().render(s["source"], {"size": body.size}, views=COVER_VIEW, tile=480, inputs=s["inputs"])
    return Response(base64.b64decode(out["png"]), media_type="image/png", headers={"Cache-Control": "no-store"})


class Keep(BaseModel):
    label: str | None = Field(None, max_length=40)
    size: float = Field(50, ge=25, le=90)


@router.post("/api/snap/{project_id}/keep")
async def snap_keep(project_id: str, body: Keep, user=Depends(_user)):
    """Into the collection as an instant 3D sticker: built and checked in the pool, saved as a version, no agent."""
    from .vision import snap

    p, asset, sel = await _snap_project(project_id, user)
    db = await get_db()
    if await db.one("SELECT id FROM jobs WHERE project_id = ? AND status IN ('running', 'waiting') LIMIT 1", project_id):
        raise _err(409, "the agent is modelling this find; wait for it or open the project", "project_busy", project_id=project_id)
    label = (body.label or "").strip()[:40]
    brief = dict(p["brief"] or {})
    if label and label != brief.get("subject"):
        brief["subject"] = label
        p["title"] = label[:1].upper() + label[1:]
        await db.update("projects", "id", project_id, {"brief": brief, "title": p["title"], "updated_at": now()})
    s = await snap.sticker_for(project_id, asset, sel)
    source, inputs = s["source"], s["inputs"]
    inputs["values"]["name"] = label or str(brief.get("subject") or "")
    params = {"size": round(float(body.size), 1)}
    try:
        built = await geom().build(source, params, analyze="full", inputs=inputs)
        iso = await geom().render(source, params, views=COVER_VIEW, tile=512, inputs=inputs)
    except GeomError as e:
        raise _err(422, e.message[:500], "geom", stage=e.stage) from e
    checks = built.get("checks") or {}
    size_mm = [round(v, 1) for v in (checks.get("stats") or {}).get("size", [])]
    summary = f"Instant 3D sticker, {params['size']:g} mm along the longest side ({' x '.join(f'{v:g}' for v in size_mm)} mm)"
    version, cover = await _save_version(p, source, params, inputs, summary, built, base64.b64decode(iso["png"]))
    fresh = (await db.one("SELECT brief FROM projects WHERE id = ?", project_id) or {}).get("brief") or {}
    sticker_info = {"version": version, "size": params["size"], "selection_id": sel["id"], "key": s["key"]}
    await db.update("projects", "id", project_id, {"brief": {**fresh, "snap": {**(fresh.get("snap") or {}), "sticker": sticker_info}}})
    return {"version": version, "cover": storage.url(cover), "size_mm": size_mm, "ok": checks.get("ok", True), "score": checks.get("score"),
            "issues": [i.get("code") for i in checks.get("issues", []) if i.get("severity") != "info"],
            "est": estimate(checks.get("stats") or {}, "sticker"),
            "project": _app().project_out(await db.one("SELECT * FROM projects WHERE id = ?", project_id))}


# ------------------------------------------------------------------ the collection plate
class Plate(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=MAX_PLATE)
    size_mm: float = Field(48, ge=25, le=80)
    gap: float = Field(6, ge=3, le=15)


async def _plate_item(p: dict[str, Any], key: str) -> dict[str, Any] | None:
    """One find's sticker inputs under `key`: its kept sticker version, else a sticker of its snap selection."""
    from .vision import snap

    db = await get_db()
    brief = p["brief"] or {}
    name = str(brief.get("subject") or p["title"] or "")
    kept = (brief.get("snap") or {}).get("sticker") or {}
    if kept.get("version"):
        prog = await db.one("SELECT inputs FROM programs WHERE project_id = ? AND version = ?", p["id"], kept["version"])
        inp = (prog or {}).get("inputs") or {}
        if inp.get("outlines", {}).get("subject") and inp.get("heightmaps", {}).get("subject"):
            v = inp.get("values") or {}
            values = {f"{key}_{c}": v.get(f"subject_{c}") for c in ("x0", "y0", "x1", "y1") if v.get(f"subject_{c}") is not None}
            return {"outlines": {key: inp["outlines"]["subject"]}, "heightmaps": {key: inp["heightmaps"]["subject"]},
                    "values": {**values, f"{key}_name": str(v.get("name") or name)}}
    asset = await db.one("SELECT * FROM assets WHERE id = ? AND project_id = ?", snap.snap_asset_id(p) or "", p["id"])
    sel = await _target(p["id"], asset["id"]) if asset else None
    if not sel:
        return None
    s = await snap.sticker_for(p["id"], asset, sel)
    return {"outlines": {key: s["inputs"]["outlines"]["subject"]}, "heightmaps": {key: s["inputs"]["heightmaps"]["subject"]},
            "values": {**{f"{key}_{c}": s["inputs"]["values"][f"subject_{c}"] for c in ("x0", "y0", "x1", "y1")}, f"{key}_name": name}}


@router.post("/api/collection/plate")
async def collection_plate(body: Plate, user=Depends(_user)):
    """The chosen finds on one print bed: a new project whose program is lib.collect.plate over their stickers."""
    db = await get_db()
    ids = list(dict.fromkeys(body.ids))
    rows = {r["id"]: r for r in await db.all(f"SELECT * FROM projects WHERE user_id = ? AND pack = 'collect' AND id IN ({','.join('?' * len(ids))})",
                                              user["id"], *ids)}
    inputs: dict[str, Any] = {"outlines": {}, "heightmaps": {}, "values": {}}
    items, skipped = [], []
    for pid in ids:
        p = rows.get(pid)
        one = await _plate_item(p, f"s{len(items)}") if p and not (p["brief"] or {}).get("plate") else None
        if one is None:
            skipped.append(pid)
            continue
        for k in inputs:
            inputs[k].update(one[k])
        items.append({"id": pid, "key": f"s{len(items)}", "title": p["title"]})  # type: ignore[index]
    if not items:
        raise _err(400, "none of these finds has a selection to make a sticker of", "nothing_to_plate", skipped=skipped)
    inputs["values"]["keys"] = ",".join(i["key"] for i in items)
    params = {"size": round(body.size_mm, 1), "gap": round(body.gap, 1)}
    printer = _printer()
    extra: dict[str, Any] = {"inputs": inputs, **({"printer": printer} if printer else {})}
    bed = (float((printer or {}).get("bed", [256, 256])[0]), float((printer or {}).get("bed", [256, 256])[1]))
    try:
        built = await geom().build(PLATE_SOURCE, params, analyze="full", **extra)
        iso = await geom().render(PLATE_SOURCE, params, views=COVER_VIEW, tile=640, **extra)
    except GeomError as e:
        if "does not fit one bed" in e.message:
            raise _err(422, e.message.removeprefix("assertion failed: ")[:400], "plate_too_big", fits=False, bed=list(bed), count=len(items)) from e
        raise _err(422, e.message[:500], "geom", stage=e.stage) from e
    checks = built.get("checks") or {}
    size_mm = [round(v, 1) for v in (checks.get("stats") or {}).get("size", [])]
    lang = next((str((rows[i["id"]]["brief"] or {}).get("language") or "") for i in items), "en")
    n = len(items)
    title = f"Стол коллекции · {n} шт." if lang == "ru" else f"Collection plate · {n} finds"
    t = now()
    pid = new_id("p_")
    brief = {"collect": True, "language": lang or "en", "printer": (printer or {}).get("name"),
             "plate": {"items": items, "from": "collection", "size_mm": params["size"], "gap": params["gap"], "bed": list(bed), "skipped": skipped}}
    await db.insert("projects", {"id": pid, "user_id": user["id"], "title": title, "pack": "collect", "brief": brief, "created_at": t, "updated_at": t})
    project = await db.one("SELECT * FROM projects WHERE id = ?", pid)
    summary = f"Collection plate: {n} instant stickers at {params['size']:g} mm on one {bed[0]:g} x {bed[1]:g} mm bed ({' x '.join(f'{v:g}' for v in size_mm)} mm)"
    await _save_version(project, PLATE_SOURCE, params, inputs, summary, built, base64.b64decode(iso["png"]))  # type: ignore[arg-type]
    return {
        "project_id": pid,
        "project": _app().project_out(await db.one("SELECT * FROM projects WHERE id = ?", pid)),
        "fits": _fits(size_mm, (bed[0] - 2 * PLATE_MARGIN + 1e-6, bed[1] - 2 * PLATE_MARGIN + 1e-6)),
        "bed": list(bed),
        "printer": (printer or {}).get("name"),
        # the smaller Bambu Lab A1 mini takes 180 x 180: the person learns it before slicing for one
        "a1_mini": _fits(size_mm, (A1_MINI[0] - 2 * PLATE_MARGIN, A1_MINI[1] - 2 * PLATE_MARGIN)),
        "size_mm": size_mm,
        "count": n,
        "skipped": skipped,
        "ok": checks.get("ok", True),
        "score": checks.get("score"),
        "est": estimate(checks.get("stats") or {}, "plate"),
    }
