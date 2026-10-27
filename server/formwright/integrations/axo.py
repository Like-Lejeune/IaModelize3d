"""Print-and-deliver via Axo (axo.kz), an existing 3D-printing service in Kazakhstan.

Axo's code is not part of this repository; it is used as an external fulfilment API:
POST {AXO_API_URL}/partner/custom-orders  (multipart: 3mf file + JSON order)
-> {order_id, checkout_url, price_kzt, eta_days}
"""
from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from ..config import settings
from ..db import get_db, new_id, now
from ..geom import geom
from ..models import OrderRequest


async def create_order(user: dict[str, Any], project: dict[str, Any], body: OrderRequest) -> dict[str, Any]:
    s = settings()
    db = await get_db()
    prog = await db.one("SELECT * FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", project["id"])
    if not prog:
        return {"status": "error", "message": "design something first"}
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
    async with httpx.AsyncClient(timeout=60) as h:
        r = await h.post(
            f"{s.axo_api_url.rstrip('/')}/partner/custom-orders",
            headers={"Authorization": f"Bearer {s.axo_api_key}"},
            files={"order": (None, json.dumps(order), "application/json"), "model": ("model.3mf", base64.b64decode(tmf["data"]), "model/3mf")},
        )
    if r.status_code >= 400:
        return {"status": "error", "message": f"Axo rejected the order ({r.status_code})"}
    data = r.json()
    oid = new_id("o_")
    await db.insert("orders", {"id": oid, "project_id": project["id"], "user_id": user["id"], "status": "created",
                               "external_ref": data.get("order_id"), "checkout_url": data.get("checkout_url"), "quote": data, "created_at": now()})
    return {"status": "created", "order_id": oid, "checkout_url": data.get("checkout_url"), "price_kzt": data.get("price_kzt"), "eta_days": data.get("eta_days")}
