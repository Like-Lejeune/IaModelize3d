"""Print-and-deliver via Axo (axo.kz), an existing 3D-printing service in Kazakhstan.

Axo's code is not part of this repository; it is used as an external fulfilment API:
POST {AXO_API_URL}/partner/custom-orders  (multipart: 3mf file + JSON order)
-> {order_id, checkout_url, price_kzt, eta_days}
POST {AXO_API_URL}/partner/formwright/designs  (multipart: meta JSON, model.3mf, optional preview PNG/JPEG)
-> 201 {design_id, add_url, price_kzt}: a version as a design in the Axo shop. add_url puts it in the buyer's cart; the
   cart's "Edit" brings them back to edit_url?axo=<design_id>, and the next design sent with &replace=<that id> on
   add_url takes that cart line's place.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from PIL import Image

from .. import idempotency, storage
from ..config import settings
from ..db import get_db, new_id, now
from ..geom import geom
from ..models import OrderRequest

log = logging.getLogger(__name__)

DESIGN_ID = re.compile(r"[0-9a-f]{32}")
MODEL_LIMIT = 64 * 1024 * 1024
PREVIEW_LIMIT = 4 * 1024 * 1024
PREVIEW_MIN_PX = 256
_transport: httpx.AsyncBaseTransport | None = None  # the tests answer as Axo here


async def create_order(user: dict[str, Any], project: dict[str, Any], body: OrderRequest, version: int | None = None, *,
                       key: str | None = None) -> dict[str, Any]:
    """Sends one version of the project to Axo: `version` pins it (a shop order's version, the one that was quoted and
    checked), else the newest. `key`: the request's Idempotency-Key, so a retry answers with the first order; the header
    goes to Axo too, for a retry after a reply that was lost on the way."""
    async def first(ref: str) -> dict[str, Any] | None:
        db = await get_db()
        o = await db.one("SELECT id, checkout_url, quote FROM orders WHERE id = ?", ref)
        q = (o or {}).get("quote") or {}
        return {"status": "created", "order_id": o["id"], "checkout_url": o["checkout_url"], "price_kzt": q.get("price_kzt"), "eta_days": q.get("eta_days")} if o else None

    return await idempotency.once(user["id"], f"axo:{project['id']}", key, lambda: _create_order(user, project, body, version, key), first,
                                  ref=lambda r: r.get("order_id"))


async def _create_order(user: dict[str, Any], project: dict[str, Any], body: OrderRequest, version: int | None, key: str | None) -> dict[str, Any]:
    s = settings()
    db = await get_db()
    if version:
        prog = await db.one("SELECT * FROM programs WHERE project_id = ? AND version = ?", project["id"], version)
    else:
        prog = await db.one("SELECT * FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", project["id"])
    if not prog:
        return {"status": "error", "message": f"there is no version {version} of this model" if version else "design something first"}
    if not s.axo_api_url:
        return {"status": "not_configured", "message": "Print & delivery via Axo is available in Kazakhstan. Download the 3MF to print it yourself."}
    tmf = await geom().export(prog["source"], prog["params"], "3mf", inputs=prog["inputs"], title=project["title"])
    stats = (prog["checks"] or {}).get("stats", {})
    order = {
        "title": project["title"],
        "quantity": body.quantity,
        "material": body.material,
        "color": body.color,
        "comment": body.comment,
        "size_mm": stats.get("size"),
        "volume_mm3": stats.get("volume"),
        "source": f"{s.public_url}/r/{project['id']}",
        "external_id": f"{project['id']}:v{prog['version']}",
    }
    try:
        async with httpx.AsyncClient(timeout=60, transport=_transport) as h:
            r = await h.post(
                f"{s.axo_api_url.rstrip('/')}/partner/custom-orders",
                headers={"Authorization": f"Bearer {s.axo_api_key}", **({"Idempotency-Key": key} if key else {})},
                files={"order": (None, json.dumps(order), "application/json"), "model": ("model.3mf", base64.b64decode(tmf["data"]), "model/3mf")},
            )
    except httpx.HTTPError as e:
        # the reply may be what was lost: said so, and a retry with the same key is safe where Axo honours it
        log.warning("Axo order for %s: %s", project["id"], type(e).__name__)
        return {"status": "error", "message": "Axo is not answering. Check your orders at Axo before trying again."}
    if r.status_code >= 400:
        return {"status": "error", "message": f"Axo rejected the order ({r.status_code})"}
    data = _json(r)
    if not isinstance(data, dict):
        log.error("Axo order for %s: answer %s is not a JSON object", project["id"], r.status_code)
        return {"status": "error", "message": "Axo took the request but its answer could not be read. Check your orders at Axo before trying again."}
    oid = new_id("o_")
    await db.insert("orders", {"id": oid, "project_id": project["id"], "user_id": user["id"], "status": "created",
                               "external_ref": data.get("order_id"), "checkout_url": data.get("checkout_url"), "quote": data, "created_at": now()})
    return {"status": "created", "order_id": oid, "checkout_url": data.get("checkout_url"), "price_kzt": data.get("price_kzt"), "eta_days": data.get("eta_days")}


# ------------------------------------------------------------------ the Axo shop's cart
def _fail(status: int, code: str, message: str) -> HTTPException:
    # {detail, code} like every API error (app.http_error): the web says the code in the UI's language
    return HTTPException(status, {"detail": message, "code": code})


async def add_to_cart(project: dict[str, Any], version: int | None = None, replace: str | None = None) -> dict[str, Any]:
    """One version of the project (`version`, else the newest) as a design in the Axo shop. {url} takes the buyer to
    their cart with it; with `replace` (the design Axo sent them back to edit) it takes that cart line's place."""
    if replace is not None and not DESIGN_ID.fullmatch(replace):
        raise _fail(400, "bad_replace", "replace must be an Axo design id (32 lowercase hex characters)")
    s = settings()
    if not s.axo_api_url:
        raise _fail(503, "not_configured", "The Axo shop is not connected on this server (FW_AXO_API_URL is not set)")
    db = await get_db()
    if version:
        prog = await db.one("SELECT * FROM programs WHERE project_id = ? AND version = ?", project["id"], version)
    else:
        prog = await db.one("SELECT * FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", project["id"])
    if not prog:
        raise _fail(404 if version else 400, "no_model", f"there is no version {version} of this model" if version else "design something first")
    v = prog["version"]
    size, volume = await _measure(prog)
    exported = await geom().export(prog["source"], prog["params"], "3mf", inputs=prog["inputs"], title=project["title"])
    tmf = base64.b64decode(exported["data"])
    if len(tmf) > MODEL_LIMIT:
        raise _fail(413, "axo_too_large", "The model is too large for the Axo shop (64 MB max)")
    grams, minutes = await _sliced(project["id"], v)
    meta = {
        "external_id": f"{project['id']}:v{v}",
        "title": (str(project["title"] or "").strip()[:120].strip() or "Formwright model"),
        # the studio: its owner edits the project there (a device's /p/ link goes on to /d/), ?axo=<design id> appended by Axo
        "edit_url": f"{s.public_url.rstrip('/')}/p/{project['id']}",
        "size_mm": size,
        "volume_mm3": volume,
        "weight_g": grams,
        "print_time_min": minutes,
    }
    files: dict[str, tuple[str, bytes, str]] = {"model": ("model.3mf", tmf, "model/3mf")}
    preview = await _preview(project["id"], prog)
    if preview:
        files["preview"] = preview
    data, url = await _send_design(f"{project['id']} v{v}", meta, files, replace)
    return {"url": url, "design_id": data.get("design_id"), "price_kzt": data.get("price_kzt")}


async def add_device_to_cart(project: dict[str, Any], qty: int, replace: str | None = None) -> dict[str, Any]:
    """The finished device as a batch of `qty` in the Axo shop: its case, the archive for the workshop and the price of the
    studio's quote without delivery, which the shop adds by the batch's parcel. {url} takes the buyer to their cart."""
    from .. import device_package

    if replace is not None and not DESIGN_ID.fullmatch(replace):
        raise _fail(400, "bad_replace", "replace must be an Axo design id (32 lowercase hex characters)")
    s = settings()
    if not s.axo_api_url:
        raise _fail(503, "not_configured", "The Axo shop is not connected on this server (FW_AXO_API_URL is not set)")
    pkg = await device_package.build(project, qty)
    prog, price = pkg.program, pkg.device["price_kzt"]
    meta = {
        "external_id": f"{project['id']}:v{prog['version']}:b{pkg.quote['pcb_version']}:q{pkg.device['qty']}",
        "title": (str(project["title"] or "").strip()[:120].strip() or "Formwright device"),
        "edit_url": f"{s.public_url.rstrip('/')}/p/{project['id']}",
        "size_mm": pkg.size_mm,
        "volume_mm3": pkg.volume_mm3,
        "weight_g": pkg.case_grams,
        "print_time_min": pkg.print_minutes,
        "device": pkg.device,
    }
    files: dict[str, tuple[str, bytes, str]] = {"model": ("model.3mf", pkg.model_3mf, "model/3mf"),
                                                "bundle": ("device.zip", pkg.zip_bytes, "application/zip")}
    preview = await _device_preview(project["id"], prog)
    if preview:
        files["preview"] = preview
    what = f"{project['id']} device x{pkg.device['qty']}"
    data, url = await _send_design(what, meta, files, replace)
    # the shop says the price back: one that does not know devices would sell this one at the price of its plastic
    if data.get("price_kzt") != price:
        log.error("Axo cart for %s: the shop answered price %r for %r: not sending the buyer there", what, data.get("price_kzt"), price)
        raise _fail(502, "axo_no_device", "The Axo shop does not take whole devices yet")
    return {"url": url, "design_id": data.get("design_id"), "price_kzt": price, "qty": pkg.device["qty"]}


async def _send_design(what: str, meta: dict[str, Any], files: dict[str, tuple[str, bytes, str]], replace: str | None) -> tuple[dict[str, Any], str]:
    """A design to the shop's partner route: (its answer, the link that takes the buyer to the cart)."""
    s = settings()
    try:
        async with httpx.AsyncClient(timeout=60, transport=_transport) as h:
            r = await h.post(f"{s.axo_api_url.rstrip('/')}/partner/formwright/designs", headers={"Authorization": f"Bearer {s.axo_api_key}"},
                             data={"meta": json.dumps(meta)}, files=files)
    except httpx.HTTPError as e:
        # app.py answers a bare httpx error as the model service being busy: this one is Axo's
        log.warning("Axo cart for %s: %s", what, type(e).__name__)
        raise _fail(502, "axo_unavailable", "The Axo shop is not answering; try again in a minute") from e
    if r.status_code in (401, 403):
        log.error("Axo cart for %s: Axo refused FW_AXO_API_KEY (%s)", what, r.status_code)
        raise _fail(502, "axo_auth", "The Axo shop did not accept this server's key")
    if r.status_code == 413:
        raise _fail(413, "axo_too_large", "The model is too large for the Axo shop (64 MB max)")
    if r.status_code == 400:
        reason = _reason(r)
        log.warning("Axo cart for %s: rejected: %s", what, reason)
        raise _fail(422, "axo_rejected", f"The Axo shop did not take this model: {reason}")
    data = _json(r) if r.status_code in (200, 201) else None
    add_url = data.get("add_url") if isinstance(data, dict) else None
    # the browser goes there: an http(s) link only
    if not isinstance(add_url, str) or urlsplit(add_url).scheme not in ("http", "https"):
        log.warning("Axo cart for %s: answer %s without an add_url", what, r.status_code)
        raise _fail(502, "axo_unavailable", "The Axo shop is not answering; try again in a minute")
    url = add_url + (f"{'&' if '?' in add_url else '?'}replace={replace}" if replace else "")
    log.info("Axo cart: %s -> design %s%s", what, data.get("design_id"), f" in place of {replace}" if replace else "")
    return data, url


def _dims(stats: Any) -> tuple[list[float], float] | None:
    if not isinstance(stats, dict):
        return None
    size, volume = stats.get("size"), stats.get("volume")
    if isinstance(size, list) and len(size) == 3 and all(isinstance(x, (int, float)) for x in size) and isinstance(volume, (int, float)):
        return [round(float(x), 2) for x in size], round(float(volume), 1)
    return None


async def _measure(prog: dict[str, Any]) -> tuple[list[float], float]:
    """Bounding box and solid volume: the version's own checks, else a quick build (no full analysis, no slicer)."""
    got = _dims(prog["checks"].get("stats") if isinstance(prog["checks"], dict) else None)
    if got:
        return got
    built = await geom().build(prog["source"], prog["params"], analyze="fast", inputs=prog["inputs"])
    got = _dims((built.get("checks") or {}).get("stats"))
    if not got:
        raise _fail(422, "geom", "Could not measure this model")
    return got


async def _sliced(project_id: str, version: int) -> tuple[float | None, float | None]:
    """OrcaSlicer's grams and minutes when a Formwright Parts quote sliced exactly this version (autoquote stamps the
    slice with it); (None, None) otherwise, and Axo estimates from the volume. Never slices here: that takes up to a minute."""
    from ..shop import store

    try:
        db = await store.shop_db()
        rows = await db.all("SELECT slice FROM shop_orders WHERE project_id = ? AND version = ? ORDER BY updated_at DESC", project_id, version)
    except Exception:  # noqa: BLE001 - the numbers are optional
        log.warning("Axo cart: the shop's slices of %s are unreadable", project_id, exc_info=True)
        return None, None
    for row in rows:
        sl = (store._dec(row) or {}).get("slice")
        stats = sl.get("stats") if isinstance(sl, dict) and sl.get("version") == version else None
        grams, minutes = (stats or {}).get("grams"), (stats or {}).get("minutes")
        if isinstance(grams, (int, float)) and isinstance(minutes, (int, float)) and grams > 0 and minutes > 0:
            return round(float(grams), 2), round(float(minutes), 1)
    return None, None


async def _preview(project_id: str, prog: dict[str, Any]) -> tuple[str, bytes, str] | None:
    """The version's iso render (the agent saves one with every version it builds), else one rendered now from the
    same program; None when there is no picture Axo takes (PNG or JPEG, 256 px or more, 4 MB at most)."""
    path = storage.abs_path(f"{project_id}/renders/v{prog['version']}_iso.png")
    if path.is_file():
        data = path.read_bytes()
    else:
        try:
            out = await geom().render(prog["source"], prog["params"], view="iso", tile=512, inputs=prog["inputs"])
            data = base64.b64decode(out["png"])
        except Exception as e:  # noqa: BLE001 - the picture is optional
            log.info("Axo cart: no preview of %s v%s (%s)", project_id, prog["version"], type(e).__name__)
            return None
    kind = "png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "jpeg" if data.startswith(b"\xff\xd8\xff") else None
    if not kind or len(data) > PREVIEW_LIMIT:
        return None
    try:
        width, height = Image.open(io.BytesIO(data)).size
    except OSError:
        return None
    if min(width, height) < PREVIEW_MIN_PX:
        return None
    return ("preview.png" if kind == "png" else "preview.jpg", data, f"image/{kind}")


async def _device_preview(project_id: str, prog: dict[str, Any]) -> tuple[str, bytes, str] | None:
    """The device as it comes, the case closed around its board; else the version's usual picture."""
    try:
        params = {**(prog["params"] or {}), "layout": "assembled", "show_board": True}
        out = await geom().render(prog["source"], params, view="iso", tile=768, inputs=prog["inputs"])
        data = base64.b64decode(out["png"])
    except Exception as e:  # noqa: BLE001 - the picture is optional
        log.info("Axo cart: no assembled picture of %s v%s (%s)", project_id, prog["version"], type(e).__name__)
        return await _preview(project_id, prog)
    return ("preview.png", data, "image/png") if len(data) <= PREVIEW_LIMIT else await _preview(project_id, prog)


def _json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def _reason(r: httpx.Response) -> str:
    """Axo's 400 says {"error": {...}}: its message, short."""
    data = _json(r)
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        err = err.get("message") or err.get("detail") or err.get("code")
    return str(err)[:200] if err else f"HTTP {r.status_code}"
