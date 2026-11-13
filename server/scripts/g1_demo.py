"""G1 Réparation without any model key: the real API, database and order flow, with the model and slicer steps
played by stand-ins, so the React front (apps/repair-web) can be tried end to end on a laptop.

    cd server && .venv/bin/python scripts/g1_demo.py            # API on http://127.0.0.1:8400, data in <repo>/data-demo
    cd apps/repair-web && npm run dev                           # the front on http://localhost:5410

What is played: the intake (a French reading of the request; a request that mentions gas is refused, one that says
"vérifier" is held for the workshop), the designer (a version appears about 8 s later), the slicer (fixed grams and
minutes), the QC photo (passes at 0.3 mm). Everything else is the real code: prices in FCFA (FW_SHOP_TARIFF=cm),
the order's moves and their guards, Mobile Money checks, the journal.

GET /api/demo/operator makes the browser that opens it a workshop operator (demo only: this route exists in this
script, never in the app).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

# before formwright is imported: its settings are read once
os.environ.setdefault("FW_SHOP_TARIFF", "cm")
os.environ.setdefault("FW_DATA_DIR", str(SERVER_DIR.parent / "data-demo"))
os.environ.setdefault("FW_BLUR_FACES", "0")
os.environ.setdefault("FW_PUBLIC_URL", "http://localhost:5410")

from fastapi import Request, Response  # noqa: E402

from formwright import events  # noqa: E402
from formwright.app import app  # noqa: E402
from formwright.db import get_db, new_id, now  # noqa: E402
from formwright.shop import routes, store  # noqa: E402
from formwright.shop.intake import combine  # noqa: E402

DESIGN_SECONDS = 8.0
FARM = ("org_demo_atelier", "Atelier de démonstration")


def _intake(text: str) -> dict[str, Any]:
    t = text.lower()
    refuse = "gaz" in t or "gas" in t
    spark = {
        "customer_type": "consumer", "language": "fr",
        "appliance": {"kind": "appareil ménager", "brand": "", "model": "", "serial_or_enr": ""},
        "part": {"name_en": "replacement plastic part", "name_fr": "pièce de remplacement", "name_user": "", "part_number": "",
                 "quantity": 1, "condition": "broken", "failure": ""},
        "environment": {"max_temp_c": 40, "wet": False, "food_contact": False, "load": "light"},
        "material": "PLA", "urgency": "normal", "refuse": refuse,
        "reason": "Une pièce d'un appareil à gaz ne peut pas être imprimée : une copie qui casse ou fond peut provoquer une fuite." if refuse else "",
        "ip_flags": [], "questions": [], "notes": "demo",
    }
    if "lave-vaisselle" in t or "frigo" in t or "réfrigérateur" in t:
        spark["material"] = "PETG"
        spark["environment"]["wet"] = True
        spark["part"]["name_fr"] = "roulette de panier" if "lave-vaisselle" in t else "clip de bac"
    second = {"category": "appliance", "safety_critical": "vérifier" in t, "why": "demande marquée à vérifier",
              "title_en": "Replacement part", "title_ru": "", "title_fr": spark["part"]["name_fr"].capitalize()}
    return combine(spark, second, spark_model="demo-intake", open_model="demo-second-opinion")


class DemoHooks(routes.Hooks):
    async def intake(self, user: dict, text: str, photos: list[dict]) -> dict[str, Any]:
        await asyncio.sleep(1.5)
        return _intake(text)

    async def start_design(self, user, project, text, asset_ids, language=None, shown=None) -> str:
        jid = new_id("j_")
        db = await get_db()
        await db.insert("jobs", {"id": jid, "project_id": project["id"], "user_id": user["id"], "kind": "design", "status": "running",
                                 "input": {"text": text}, "created_at": now()})
        asyncio.get_running_loop().create_task(self._finish(project["id"]))
        return jid

    async def _finish(self, project_id: str) -> None:
        await asyncio.sleep(DESIGN_SECONDS)
        db = await get_db()
        p = await db.one("SELECT version FROM projects WHERE id = ?", project_id)
        version = int((p or {}).get("version") or 0) + 1
        await db.insert("programs", {"project_id": project_id, "version": version, "source": "return lib.box(30, 20, 8)", "params": {},
                                     "inputs": {}, "checks": {"ok": True, "stats": {"estGrams": 16.0, "estMinutes": 38.0}},
                                     "author": "agent", "created_at": now()})
        await db.execute("UPDATE projects SET version = ? WHERE id = ?", version, project_id)
        await db.insert("messages", {"id": new_id("msg_"), "project_id": project_id, "role": "agent", "text": "pièce conçue (démo)",
                                     "data": {"version": version, "critic": {"verdict": "pass"}}, "created_at": now()})
        await db.execute("UPDATE jobs SET status = 'done', finished_at = ? WHERE project_id = ? AND status = 'running'", now(), project_id)
        await events.emit(project_id, "job.finished", {"status": "done"})

    async def slice(self, project_id, version, printer_id, material, fingerprint) -> dict[str, Any]:
        await asyncio.sleep(1.0)
        sid = new_id("s_")
        return {"id": sid, "material": material, "printer": {"id": printer_id, "name": printer_id or "A1"},
                "stats": {"grams": 18.4, "minutes": 52.0, "supports": False, "warnings": [], "slice_seconds": 1.0},
                "files": {"gcode": f"/files/{project_id}/slices/{sid}/part.gcode"}}

    async def qc(self, user, order, data, filename, mime) -> dict[str, Any]:
        return {"pass": True, "max_mm": 0.3, "tolerance_mm": 0.6, "at": now()}

    async def answer(self, job_id, user_id, text) -> bool:
        db = await get_db()
        await db.execute("UPDATE jobs SET status = 'running' WHERE id = ? AND status = 'waiting'", job_id)
        return True


routes.hooks = DemoHooks()


@app.get("/api/demo/operator", include_in_schema=False)
async def become_operator(request: Request, response: Response):
    user = await routes.user_dep(request, response)
    db = await store.shop_db()
    if not await db.one("SELECT id FROM shop_orgs WHERE id = ?", FARM[0]):
        await db.insert("shop_orgs", {"id": FARM[0], "name": FARM[1], "kind": "farm", "tier": "farm", "created_at": now()})
    if not await db.one("SELECT user_id FROM shop_members WHERE org_id = ? AND user_id = ?", FARM[0], user["id"]):
        await db.insert("shop_members", {"org_id": FARM[0], "user_id": user["id"], "role": "operator"})
    return {"ok": True, "user": user["id"], "org": FARM[1]}


# the demo route must come before the SPA catch-all the app mounts last
app.router.routes.insert(0, app.router.routes.pop())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8400")))
