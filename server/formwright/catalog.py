"""Parts catalogue for devices: real LCSC parts and the modules Formwright knows by heart.

Two public sources, both cached under data/catalog so a part looked up once builds offline forever:
  search  - JLCPCB's parts search (the LCSC catalogue as JLCPCB assembles it): stock, price breaks, basic/extended
            library, package, datasheet. Cached 12 h per query.
  easyeda - EasyEDA's component library entry of an LCSC number: the symbol's pins (number -> name) and the footprint
            the PCB worker converts with tscircuit's easyeda converter (packages/pcb/src/build.mjs, footprint "lcsc:C123").
            Cached for good: a part number never changes its footprint.

A part card (info()) is what the designer, the node editor and the BOM read: pins with tscircuit-safe labels, footprint
size and height (from the 3D model's name, e.g. "LGA-8_L2.5-W2.5-H0.9"), stock and price breaks. Primitives (resistors,
capacitors, LEDs, buttons, headers, USB-C, ...) are built from offline footprint strings and get their LCSC number from
resolve_basic(): the cheapest in-stock part of JLCPCB's basic library for the value and package.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)

JLC_SEARCH = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
EASYEDA = "https://easyeda.com/api/products/{code}/components?version=6.4.19.5"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Formwright/1.0"
SEARCH_TTL = 12 * 3600
EE_UNIT = 0.254  # EasyEDA canvas units are 10 mil
CODE_RE = re.compile(r"^C\d{1,10}$", re.I)
_locks: dict[str, asyncio.Lock] = {}


def _dir(name: str) -> Path:
    d = settings().data_dir / "catalog" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def norm_code(code: Any) -> str | None:
    c = str(code or "").strip().upper()
    if c.isdigit():
        c = "C" + c
    return c if CODE_RE.match(c) else None


# ------------------------------------------------------------------ JLCPCB search
def _card(it: dict[str, Any]) -> dict[str, Any]:
    prices = [{"qty": int(p.get("startNumber") or 1), "usd": float(p.get("productPrice") or 0)} for p in it.get("componentPrices") or []]
    return {
        "lcsc": it.get("componentCode"),
        "mpn": it.get("componentModelEn"),
        "brand": it.get("componentBrandEn"),
        "package": it.get("componentSpecificationEn"),
        "category": it.get("firstSortName") or it.get("componentTypeEn"),
        "description": (it.get("describe") or "")[:300],
        "stock": int(it.get("stockCount") or 0),
        "basic": it.get("componentLibraryType") == "base",
        "preferred": bool(it.get("preferredComponentFlag")),
        "prices": prices,
        "datasheet": it.get("dataManualUrl") or None,
        "image": it.get("minImage") or it.get("componentImageUrl") or None,
        "url": it.get("lcscGoodsUrl") or None,
    }


async def search(q: str, *, limit: int = 8, basic: bool = False) -> list[dict[str, Any]]:
    """LCSC parts matching `q` (a part number, an LCSC code or keywords such as "BME280", "10kΩ 0603", "LDO 3.3V SOT-23-5"),
    in-stock first. basic=True keeps JLCPCB's basic library only (no extended-part fee at assembly)."""
    q = " ".join(str(q or "").split())[:120]
    if not q:
        return []
    limit = max(1, min(int(limit), 30))
    key = hashlib.sha1(json.dumps([q.lower(), limit, basic]).encode()).hexdigest()[:20]
    path = _dir("search") / f"{key}.json"
    if path.is_file() and time.time() - path.stat().st_mtime < SEARCH_TTL:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    body: dict[str, Any] = {"keyword": q, "currentPage": 1, "pageSize": max(limit, 10)}
    if basic:
        body["componentLibraryType"] = "base"
    try:
        async with httpx.AsyncClient(timeout=20, headers={"user-agent": UA}) as h:
            r = await h.post(JLC_SEARCH, json=body)
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("catalog search %r failed: %s", q, e)
        if path.is_file():  # a stale answer beats none
            return json.loads(path.read_text(encoding="utf-8"))
        raise CatalogError(f"the parts catalogue did not answer ({type(e).__name__}); try again") from e
    items = ((data.get("data") or {}).get("componentPageInfo") or {}).get("list") or []
    # "C99..." numbers out of stock are JLCPCB's placeholder listings, not parts anyone can assemble
    cards = [_card(it) for it in items if it.get("componentCode") and not (str(it["componentCode"]).startswith("C99") and not it.get("stockCount"))]
    cards.sort(key=lambda c: (c["stock"] <= 0, not c["basic"]))
    cards = cards[:limit]
    path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    return cards


class CatalogError(Exception):
    pass


# ------------------------------------------------------------------ EasyEDA component (pins + footprint)
async def easyeda(code: str) -> dict[str, Any] | None:
    """The EasyEDA library entry of an LCSC part (symbol + packageDetail), or None when EasyEDA has none."""
    c = norm_code(code)
    if not c:
        return None
    path = _dir("easyeda") / f"{c}.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")) or None
        except (OSError, json.JSONDecodeError):
            pass
    lock = _locks.setdefault(c, asyncio.Lock())
    async with lock:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8")) or None
        try:
            async with httpx.AsyncClient(timeout=25, headers={"user-agent": UA}) as h:
                r = await h.get(EASYEDA.format(code=c))
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise CatalogError(f"EasyEDA did not answer for {c} ({type(e).__name__}); try again") from e
        result = data.get("result") if data.get("success") else None
        ok = isinstance(result, dict) and isinstance(result.get("packageDetail"), dict) and result.get("dataStr")
        path.write_text(json.dumps(result if ok else {}, ensure_ascii=False), encoding="utf-8")
        return result if ok else None


def pins_of(raw: dict[str, Any]) -> list[dict[str, str]]:
    """Symbol pins in pin-number order: [{num: '1', name: 'GND'}, ...]. Multi-part symbols list every unit's pins."""
    shapes: list[str] = list((raw.get("dataStr") or {}).get("shape") or [])
    for sub in (raw.get("subparts") or []):
        shapes += list(((sub or {}).get("dataStr") or {}).get("shape") or [])
    out: dict[str, str] = {}
    for s in shapes:
        if not isinstance(s, str) or not s.startswith("P~"):
            continue
        segs = s.split("^^")
        head = segs[0].split("~")
        num = head[3] if len(head) > 3 else ""
        name = ""
        if len(segs) > 3:
            bits = segs[3].split("~")
            name = bits[4] if len(bits) > 4 else ""
        if num and num not in out:
            out[num] = name.strip() or num
    key = lambda n: (0, int(n)) if n.isdigit() else (1, n)  # noqa: E731
    return [{"num": n, "name": out[n]} for n in sorted(out, key=key)]


def safe_label(name: str) -> str:
    """A tscircuit pin label: letters, digits and _, not starting with a digit ('3V3' -> 'V3V3', 'IO0/BOOT' -> 'IO0_BOOT')."""
    s = re.sub(r"[^A-Za-z0-9_]+", "_", str(name).replace("+", "P").replace("~", "N").replace("#", "N")).strip("_")
    if not s:
        return "P"
    if s[0].isdigit():
        s = ("V" if re.match(r"^\d+V\d*$", s) else "P") + s
    return s[:24]


def labels_of(pins: list[dict[str, str]]) -> dict[str, str]:
    """pinN -> unique label; the second GND is GND_7 (its pin number), so a node can still say 'U2.GND' for all of them."""
    seen: dict[str, int] = {}
    out: dict[str, str] = {}
    for p in pins:
        base = safe_label(p["name"])
        seen[base] = seen.get(base, 0) + 1
        num = p["num"] if p["num"].isdigit() else safe_label(p["num"])
        out[f"pin{num}"] = base if seen[base] == 1 else f"{base}_{num}"
    return out


def base_label(label: str) -> str:
    """'GND_7' -> 'GND' (the group a duplicate belongs to); other labels are their own group."""
    m = re.match(r"^(.*)_\d+$", label)
    return m.group(1) if m else label


def _svgnode(raw: dict[str, Any]) -> dict[str, Any]:
    for s in ((raw.get("packageDetail") or {}).get("dataStr") or {}).get("shape") or []:
        if isinstance(s, str) and s.startswith("SVGNODE~"):
            try:
                return json.loads(s.split("~", 1)[1]).get("attrs") or {}
            except (json.JSONDecodeError, AttributeError):
                return {}
    return {}


def height_of(raw: dict[str, Any], category: str = "") -> float | None:
    """Body height in mm from the 3D model's or package's name ('...-H0.9-...'); None when neither says."""
    names = [str(_svgnode(raw).get("title") or ""), str(((raw.get("dataStr") or {}).get("head") or {}).get("c_para", {}).get("package") or "")]
    for n in names:
        m = re.search(r"-H(\d+(?:\.\d+)?)", n)
        if m:
            return round(float(m.group(1)), 2)
    if re.search(r"WIFI|ESP32|MODULE", " ".join(names) + " " + category, re.I):
        return 3.2
    return None


def size_of(raw: dict[str, Any]) -> list[float] | None:
    """Footprint extent [w, h] in mm (pads and silkscreen) from the package's bounding box."""
    bb = ((raw.get("packageDetail") or {}).get("dataStr") or {}).get("BBox") or {}
    try:
        return [round(float(bb["width"]) * EE_UNIT, 2), round(float(bb["height"]) * EE_UNIT, 2)]
    except (KeyError, TypeError, ValueError):
        return None


def pads_of(raw: dict[str, Any]) -> dict[str, tuple[float, float, float, float]]:
    """Pad number -> (x, y, w, h) in mm in the frame the PCB worker's converter puts the footprint in (origin at the
    package's anchor, y up, rotation 0): where a decoupling capacitor must sit to be next to its pin."""
    d = (raw.get("packageDetail") or {}).get("dataStr") or {}
    head = d.get("head") or {}
    try:
        ox, oy = float(head.get("x") or 0), float(head.get("y") or 0)
    except (TypeError, ValueError):
        return {}
    out: dict[str, tuple[float, float, float, float]] = {}
    for s in d.get("shape") or []:
        if not isinstance(s, str) or not s.startswith("PAD~"):
            continue
        b = s.split("~")
        try:
            num, x, y, w, h = b[8], float(b[2]), float(b[3]), float(b[4]), float(b[5])
        except (IndexError, ValueError):
            continue
        rot = float(b[11]) if len(b) > 11 and b[11] not in ("", None) and b[11].replace(".", "", 1).isdigit() else 0.0
        if round(rot) % 180 == 90:
            w, h = h, w
        if num and num not in out:
            out[num] = (round((x - ox) * EE_UNIT, 3), round((oy - y) * EE_UNIT, 3), round(w * EE_UNIT, 3), round(h * EE_UNIT, 3))
    return out


def box_of(raw: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """The package's outline box (x0, y0, x1, y1) in mm in the same frame as pads_of."""
    d = (raw.get("packageDetail") or {}).get("dataStr") or {}
    head, bb = d.get("head") or {}, d.get("BBox") or {}
    try:
        ox, oy = float(head["x"]), float(head["y"])
        x0, ytop = (float(bb["x"]) - ox) * EE_UNIT, (oy - float(bb["y"])) * EE_UNIT
        return (round(x0, 3), round(ytop - float(bb["height"]) * EE_UNIT, 3), round(x0 + float(bb["width"]) * EE_UNIT, 3), round(ytop, 3))
    except (KeyError, TypeError, ValueError):
        return None


def smd_of(raw: dict[str, Any]) -> tuple[int, bool]:
    """(pad count, any through-hole pad) of the footprint: solder joints for the assembly price."""
    pads, tht = 0, False
    for s in ((raw.get("packageDetail") or {}).get("dataStr") or {}).get("shape") or []:
        if isinstance(s, str) and s.startswith("PAD~"):
            pads += 1
            bits = s.split("~")
            try:
                if float(bits[9] or 0) > 0:  # hole radius
                    tht = True
            except (IndexError, ValueError):
                pass
    return pads, tht


async def info(code: str) -> dict[str, Any]:
    """Everything about one LCSC part: the catalogue card (stock, prices) and its pins, footprint size and height.
    Raises CatalogError when the code is unknown or EasyEDA has no footprint for it."""
    c = norm_code(code)
    if not c:
        raise CatalogError(f"{code!r} is not an LCSC part number (C followed by digits, e.g. C92489)")
    raw, hits = await asyncio.gather(easyeda(c), search(c, limit=5))
    card = next((h for h in hits if (h.get("lcsc") or "").upper() == c), None)
    if raw is None:
        raise CatalogError(f"{c} has no EasyEDA footprint" + (f" ({card['mpn']})" if card else "") + ": pick another part")
    head = ((raw.get("dataStr") or {}).get("head") or {}).get("c_para") or {}
    pins = pins_of(raw)
    labels = labels_of(pins)
    pads, tht = smd_of(raw)
    out = {
        **(card or {"lcsc": c, "mpn": head.get("Manufacturer Part") or raw.get("title"), "brand": head.get("Manufacturer"), "package": head.get("package"),
                    "category": None, "description": raw.get("description") or "", "stock": int(((raw.get("lcsc") or {}).get("stock")) or 0),
                    "basic": head.get("JLCPCB Part Class") == "Basic Part", "preferred": False,
                    "prices": [{"qty": 1, "usd": float((raw.get("lcsc") or {}).get("price") or 0)}], "datasheet": None, "image": None,
                    "url": (raw.get("lcsc") or {}).get("url")}),
        "lcsc": c,
        "footprint_name": head.get("package"),
        "pins": [{"num": p["num"], "name": p["name"], "label": labels[f"pin{p['num'] if p['num'].isdigit() else safe_label(p['num'])}"]} for p in pins],
        "size_mm": size_of(raw),
        "height_mm": height_of(raw, (card or {}).get("category") or ""),
        "pads": pads,
        "tht": tht,
    }
    return out


def price_at(prices: list[dict[str, Any]], qty: int) -> float:
    """Unit price in USD at a quantity, from the price breaks."""
    best = 0.0
    for p in sorted(prices or [], key=lambda p: p.get("qty") or 1):
        if (p.get("qty") or 1) <= max(1, qty):
            best = float(p.get("usd") or 0)
    return best or (float(prices[0]["usd"]) if prices else 0.0)


# ------------------------------------------------------------------ basic parts for primitives
LED_SERIES = {"red": "KT-0603R", "green": "KT-0603G", "yellow": "KT-0603Y", "blue": "KT-0603B", "white": "KT-0603W", "orange": "KT-0603O"}
# offline footprint -> the package name JLCPCB lists
PACKAGE = {"0402": "0402", "0603": "0603", "0805": "0805", "1206": "1206"}
FIXED = {
    # parts every board uses, looked up once by number (stock and price still come live from search)
    "usb_c": "C165948",      # TYPE-C-31-M-12, 16-pin power-only receptacle (footprint usbcmidmount)
    "schottky": "C8598",     # B5819W, SOD-123, 1 A 40 V
    "jst2": "C173752",       # S2B-PH-K-S, JST PH 2.0 mm 2-pin, through-hole
    "header": "C2337",       # 2.54 mm 1x40 pin header, cut to length
    "button": "C110153",     # K2-1102DP-C4SW-04, 6 x 6 x 5 mm tact switch, through-hole (footprint pushbutton)
}


def value_keyword(kind: str, value: str, package: str) -> str:
    v = str(value or "").strip().replace(" ", "")
    if kind == "resistor":
        v = re.sub(r"(?i)(ohm|Ω|r)$", "", v)
        m = re.match(r"^(\d+(?:\.\d+)?)([kKmM]?)(\d*)$", v)
        if m and m.group(3):  # 4k7 -> 4.7k
            v = f"{m.group(1)}.{m.group(3)}{m.group(2)}"
        v = v.replace("K", "k")
        return f"{v}Ω {package}"
    if kind == "capacitor":
        v = re.sub(r"(?i)f$", "", v)
        v = v.replace("u", "u").replace("µ", "u")
        return f"{v}F {package}"
    return f"{v} {package}"


async def resolve_basic(kind: str, value: str = "", package: str = "0603", color: str = "") -> dict[str, Any] | None:
    """The LCSC part for a primitive: resistor/capacitor by value and package from the basic library, an LED by colour
    (KT-0603 series), the fixed parts (usb_c, schottky, jst2, header) by number. None when the catalogue has nothing fitting."""
    try:
        if kind in FIXED:
            hits = await search(FIXED[kind], limit=3)
            return next((h for h in hits if h["lcsc"] == FIXED[kind]), None)
        if kind == "led":
            series = LED_SERIES.get((color or "green").lower(), "KT-0603G")
            hits = await search(series, limit=6)
            hit = next((h for h in hits if (h.get("mpn") or "").upper() == series), None)
            return hit or next((h for h in hits if h["stock"] > 0), None)
        if kind in ("resistor", "capacitor"):
            pkg = PACKAGE.get(package, "0603")
            hits = await search(value_keyword(kind, value, pkg), limit=8, basic=True)
            fit = [h for h in hits if (h.get("package") or "") == pkg and h["stock"] > 0]
            return fit[0] if fit else None
    except CatalogError as e:
        log.warning("resolve_basic %s %s: %s", kind, value, e)
    return None
