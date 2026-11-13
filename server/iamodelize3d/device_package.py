"""A whole device as one package: everything the workshop needs for a batch, and what the buyer is told about it.

build() takes the board that was built, the case made from it and the firmware, refuses a device that is not finished,
and answers with a ZIP (the fab's files, the case, the firmware, a work order in Russian for the workshop) and the facts
the Axo shop sells it by: the batch's price without delivery and its parcel. GET .../device/package downloads the ZIP,
integrations/axo.add_device_to_cart sends it to the shop.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from . import device_store, pcb_store
from .config import settings

PACKAGE_LIMIT = 32 * 1024 * 1024  # what the shop takes (printit3 routes/builder/formwright.rs BUNDLE_MAX_BYTES)
INCLUDES_MAX, TEXT_MAX = 80, 200  # printit3 core/builder/formwright.rs DEVICE_MAX_*
BOARD_G_PER_CM2 = 0.3  # 1.6 mm FR-4 with its copper
PARTS_G = 6.0  # what is soldered on one board
MODULE_G = 12.0  # a ready-made module with its leads
PACKING_G, BOX_G = 25.0, 120.0  # around each device, and the shipping box
PACK_MARGIN_MM, BOX_MARGIN_MM = 10, 40
PCB_FILES = ("gerbers.zip", "bom.csv", "cpl.csv", "schematic.svg", "pcb_top.svg", "pcb_bottom.svg", "drc.json", "circuit.tsx")


@dataclass
class Package:
    zip_bytes: bytes
    model_3mf: bytes
    program: dict[str, Any]
    quote: dict[str, Any]
    size_mm: list[float]
    volume_mm3: float
    case_grams: float  # plastic of the whole batch
    print_minutes: float
    device: dict[str, Any]  # meta.device of the shop's partner route


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"detail": message, "code": code})


def parcel(qty: int, board_mm: list[float], case_size: list[float], case_grams_each: float, modules: int) -> tuple[int, list[int]]:
    """Weight in grams and box in mm of a batch, for the shop's delivery price: the devices in a block as near a cube as it
    goes, each with its padding."""
    w, h = board_mm
    each = case_grams_each + w * h / 100 * BOARD_G_PER_CM2 + PARTS_G + modules * MODULE_G / max(1, qty) + PACKING_G
    layers = max(1, math.ceil(qty ** (1 / 3)))
    per_layer = math.ceil(qty / layers)
    rows = max(1, math.floor(math.sqrt(per_layer)))
    cols = math.ceil(per_layer / rows)
    x, y, z = (math.ceil(v) + PACK_MARGIN_MM for v in case_size)
    return math.ceil(each * qty + BOX_G), [cols * x + BOX_MARGIN_MM, rows * y + BOX_MARGIN_MM, layers * z + BOX_MARGIN_MM]


def _work_order(project: dict[str, Any], q: dict[str, Any], doc: dict[str, Any], firmware: dict[str, Any], size: list[float], grams_each: float) -> str:
    """The workshop's page in the archive: what to order, what to fit, what to flash, what to check."""
    qty, (w, h) = q["qty"], q["board_mm"]
    fab = next(g for g in q["groups"] if g["key"] == "pcb")["data"]["boards"]
    smt = [b for b in q["bom"] if b["assembly"] == "smt"]
    hand = [b for b in q["bom"] if b["assembly"] != "smt"]
    out = [f"# {project['title']}: {qty} шт.", "",
           f"Проект: {settings().public_url.rstrip('/')}/d/{project['id']} (плата v{q['pcb_version']}, корпус v{q['program_version']})",
           f"Смета: ${q['total_usd']:.2f} с доставкой, разбивка в quote.json. Цены на дату сметы; цена фабрики при заказе главная.", "",
           "## 1. Плата на JLCPCB", "",
           f"Загрузить pcb/gerbers.zip: {fab} шт., {w:g} × {h:g} мм, 2 слоя, FR-4 1,6 мм.",
           f"Монтаж SMT: pcb/bom.csv и pcb/cpl.csv (позиций на плату: {len(smt)}).", "",
           "## 2. Детали, которые ставит мастерская", ""]
    out += [f"- {', '.join(b['refs'])}: {b['qty']} × {b['name']}" + (f" ({b['lcsc']})" if b.get("lcsc") else "") + (f", {b['url']}" if b.get("url") else "") for b in hand] or ["Нет."]
    out += ["", "## 3. Корпус", "",
            f"Печать case/case.3mf: {qty} шт., {grams_each:.0f} г PLA каждый, габарит {size[0]:g} × {size[1]:g} × {size[2]:g} мм. Цвет указан в заказе Axo.", "",
            "## 4. Прошивка", "",
            f"Файлы в firmware/ ({firmware.get('lang') or 'arduino'})."]
    if firmware.get("notes"):
        out += ["", str(firmware["notes"])]
    out += ["", "## 5. Что проверить на каждом устройстве", ""]
    out += [f"- {r['id']}: {r['text']}" for r in doc.get("requirements") or []] or ["Включается, прошивка стартует."]
    out += ["", "Прошивка проверялась на виртуальной плате, на железе этот проект мог ещё не собираться: первое устройство партии проверить полностью, прежде чем собирать остальные.", ""]
    return "\n".join(out)


def _zip(project_id: str, version: int, tmf: bytes, firmware: dict[str, Any], doc: dict[str, Any], q: dict[str, Any], readme: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", readme)
        z.writestr("case/case.3mf", tmf)
        for name in PCB_FILES:
            path = pcb_store.artifact_path(project_id, version, name)
            if path:
                z.write(path, f"pcb/{name}")
        for name, text in firmware["files"].items():
            z.writestr("firmware/" + re.sub(r"[^A-Za-z0-9_.-]", "_", name), text)
        z.writestr("device.json", json.dumps(doc, ensure_ascii=False, indent=1))
        z.writestr("quote.json", json.dumps(q, ensure_ascii=False, indent=1))
    return buf.getvalue()


async def build(project: dict[str, Any], qty: int) -> Package:
    """The finished device of this project, for `qty` pieces. Raises {detail, code} when it is not finished: the board
    has errors or lacks fab files, the schematic changed after the board, no case or no firmware."""
    from . import deviceapi
    from .db import get_db
    from .geom import geom
    from .integrations import axo

    pid = project["id"]
    q = await deviceapi.quote_for(pid, qty)
    if not q["drc_ok"]:
        raise _refuse(409, "device_drc", "the board still has DRC errors: build a clean version first")
    v = q["pcb_version"]
    if not pcb_store.artifact_path(pid, v, "gerbers.zip"):
        raise _refuse(409, "no_gerbers", "this board has no fab files yet: build it again")
    state = await deviceapi.state_of(pid)
    if (state.get("pcb") or {}).get("stale"):
        raise _refuse(409, "device_stale", "the schematic changed after this board: rebuild it first")
    latest = await device_store.latest(pid)
    doc = (latest or {}).get("doc") or {}
    firmware = doc.get("firmware") or {}
    if not firmware.get("files"):
        raise _refuse(409, "no_firmware", "this device has no firmware yet")
    db = await get_db()
    prog = await db.one("SELECT * FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", pid)
    if not prog:
        raise _refuse(409, "no_case", "this device has no case yet")
    made_for = [b.get("source", {}).get("pcb_job") for b in ((prog["inputs"] or {}).get("boards") or {}).values() if isinstance(b, dict)]
    if f"pcb:v{v}" not in made_for and any(made_for):
        raise _refuse(409, "case_stale", "the case was made for an older board: make it again")
    # the plates the workshop prints: without the printed stand-in for the board that the studio offers for a trial fit
    params = {**(prog["params"] or {}), "mockup": False, "layout": "print", "show_board": False}
    built = await geom().build(prog["source"], params, analyze="fast", inputs=prog["inputs"])
    stats = (built.get("checks") or {}).get("stats") or {}
    volume = float(stats.get("volume") or 0)
    if volume <= 0:
        raise _refuse(422, "geom", "could not measure this case")
    # the size of the case itself (assembled), not of the print plate its parts lie on
    size = (((prog["checks"] or {}).get("enclosure") or {}).get("summary") or {}).get("case_mm") or stats.get("size")
    size = [round(float(x), 2) for x in size]
    exported = await geom().export(prog["source"], params, "3mf", inputs=prog["inputs"], title=project["title"])
    tmf = base64.b64decode(exported["data"])
    case = q["case"]
    zip_bytes = _zip(pid, v, tmf, firmware, doc, q, _work_order(project, q, doc, firmware, size, case["grams_each"]))
    if len(zip_bytes) > PACKAGE_LIMIT:
        raise _refuse(413, "axo_too_large", "the device's files are too large for the Axo shop (32 MB max)")
    modules = sum(b["qty"] for b in q["bom"] if b["kind"] == "accessory")
    parcel_g, parcel_mm = parcel(q["qty"], q["board_mm"], size, case["grams_each"], modules)
    device = {
        "qty": q["qty"], "price_kzt": q["cart"]["price_kzt"], "parcel_g": parcel_g, "parcel_mm": parcel_mm,
        "lines": q["cart"]["lines"], "includes": [s[:TEXT_MAX] for s in q["in_order"][:INCLUDES_MAX]], "eta": q["eta"],
        # until it leaves the workshop: the shop adds its own courier's days
        "lead_days": sum(step["days"] for step in q["timeline"] if step["key"] != "delivery"),
    }
    return Package(zip_bytes=zip_bytes, model_3mf=tmf, program=prog, quote=q, size_mm=size, volume_mm3=volume,
                   case_grams=round(case["grams_each"] * q["qty"], 1), print_minutes=round(case["minutes_each"] * q["qty"], 1), device=device)
