"""Parts catalogue for devices: real LCSC parts and the modules Formwright knows by heart.

Two public sources, both cached under data/catalog so a part looked up once builds offline forever:
  search  - JLCPCB's parts search (the LCSC catalogue as JLCPCB assembles it): stock, price breaks, basic/extended
            library, package, datasheet. Cached 12 h per query.
  easyeda - EasyEDA's component library entry of an LCSC number: the symbol's pins (number -> name) and the footprint
            the PCB worker converts with tscircuit's easyeda converter (packages/pcb/src/build.mjs, footprint "lcsc:C123").
            Cached for good: a part number never changes its footprint.

A part card (info()) is what the designer, the node editor and the BOM read: pins with tscircuit-safe labels, footprint
size and height (the 3D model's name, e.g. "LGA-8_L2.5-W2.5-H0.9", or LCSC's Height parameter), stock and price breaks,
what kind of part it is (kind_hint: npn, buzzer_active, rgb_led, sensor, ...) and its rated current. Primitives (resistors,
capacitors, LEDs, buttons, headers, USB-C, ...) are built from offline footprint strings and get their LCSC number from
resolve_basic(): the cheapest in-stock part of JLCPCB's basic library for the value and package.

JLCPCB's search matches words against part numbers more than functions: 'piezo buzzer' finds nothing, 'SSD1306 OLED'
finds power inductors named SSD1306-220MT. search() therefore asks again with the query's strongest words (part numbers
first, then catalogue terms for the functions it names), drops hits whose category contradicts the query and ranks the
rest by how many query words they carry. JLCPCB refuses (403) calls made back to back, so calls are spaced.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)

JLC_SEARCH = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
EASYEDA = "https://easyeda.com/api/products/{code}/components?version=6.4.19.5"
EASYEDA_MODEL = "https://modules.easyeda.com/3dmodel/{uuid}"
MODEL_MAX_BYTES = 3_000_000  # a model past this (an overdrawn connector) would weigh more in board.glb than the rest of the board
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Formwright/1.0"
SEARCH_TTL = 12 * 3600
SEARCH_GAP = 1.5     # s between the starts of two JLCPCB calls: back-to-back calls get 403 for several seconds after
RETRY_WAIT = 4.0     # s before the one retry of a refused (403/429) call
SEARCH_CALLS = 3     # upstream calls one search may make: the query as typed, then up to two of its strongest words
EE_UNIT = 0.254  # EasyEDA canvas units are 10 mil
CODE_RE = re.compile(r"^C\d{1,10}$", re.I)
_locks: dict[str, asyncio.Lock] = {}
_next_call = 0.0                                   # monotonic time the next JLCPCB call may start
_transport: httpx.AsyncBaseTransport | None = None  # the tests answer JLCPCB from recorded responses here


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
        "family": it.get("secondSortName") or None,
        "description": (it.get("describe") or "")[:300],
        "stock": int(it.get("stockCount") or 0),
        "basic": it.get("componentLibraryType") == "base",
        "preferred": bool(it.get("preferredComponentFlag")),
        "prices": prices,
        "datasheet": it.get("dataManualUrl") or None,
        "image": it.get("minImage") or it.get("componentImageUrl") or None,
        "url": it.get("lcscGoodsUrl") or None,
        # LCSC's named parameters ('Height': '19.3mm', 'Driver Circuitry': 'Active Buzzer ...', 'Current - Collector(Ic)')
        "attrs": {str(a.get("attribute_name_en")): str(a.get("attribute_value_name")) for a in it.get("attributes") or []
                  if a.get("attribute_name_en") and a.get("attribute_value_name") not in (None, "", "-")},
    }


class CatalogError(Exception):
    pass


async def _turn() -> None:
    """Wait for this call's slot: JLCPCB refuses calls that start less than about a second apart, and keeps refusing for a
    few seconds after. The slot is taken before the first await, so concurrent searches queue up instead of racing."""
    global _next_call
    now = time.monotonic()
    at = max(now, _next_call)
    _next_call = at + SEARCH_GAP
    if at > now:
        await asyncio.sleep(at - now)


async def _query(kw: str, *, size: int, basic: bool, retry: bool = True) -> list[dict[str, Any]]:
    """One JLCPCB search call as cards in the catalogue's order, cached 12 h per keyword. A refused call (403/429) is tried
    once more after RETRY_WAIT when `retry`; when the catalogue does not answer, a stale cached answer beats none, and with
    none CatalogError is raised."""
    global _next_call
    key = hashlib.sha1(json.dumps(["jlc1", kw.lower(), size, basic]).encode()).hexdigest()[:20]
    path = _dir("search") / f"{key}.json"
    if path.is_file() and time.time() - path.stat().st_mtime < SEARCH_TTL:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    body: dict[str, Any] = {"keyword": kw, "currentPage": 1, "pageSize": size}
    if basic:
        body["componentLibraryType"] = "base"
    err: Exception | None = None
    for _ in range(2 if retry else 1):
        await _turn()
        try:
            async with httpx.AsyncClient(timeout=20, headers={"user-agent": UA}, transport=_transport) as h:
                r = await h.post(JLC_SEARCH, json=body)
                r.raise_for_status()
                data = r.json()
            err = None
            break
        except (httpx.HTTPError, ValueError) as e:
            err = e
            if not (isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (403, 429)):
                break
            _next_call = max(_next_call, time.monotonic() + RETRY_WAIT)  # every next call waits the refusal out
    if err is not None:
        log.warning("catalog search %r failed: %s", kw, err)
        if path.is_file():  # a stale answer beats none
            return json.loads(path.read_text(encoding="utf-8"))
        raise CatalogError(f"the parts catalogue did not answer ({type(err).__name__}); try again") from err
    items = ((data.get("data") or {}).get("componentPageInfo") or {}).get("list") or []
    # "C99..." numbers out of stock are JLCPCB's placeholder listings, not parts anyone can assemble
    cards = [_card(it) for it in items if it.get("componentCode") and not (str(it["componentCode"]).startswith("C99") and not it.get("stockCount"))]
    _cache(path, json.dumps(cards, ensure_ascii=False).encode())
    return cards


# function words a designer writes -> (the words, catalogue search terms best first, categories that fit). The terms are
# what LCSC lists the function under, often its jellybean part (AM312 is a digital PIR with the amplifier inside).
CONCEPTS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (r"oled|lcd|tft|displays?|screens?|ssd13\d\d\w*|sh11\d\d\w*|st77\d\d\w*|ili9\d{3}\w*|e-?paper|e-?ink", ("OLED",), r"display|oled|lcd"),
    (r"pir|motion|pyroelectric|presence|occupancy", ("AM312", "PIR"), r"human body|pyroelectric"),
    (r"buzzers?|beepers?|piezo\w*|sounders?", ("buzzer",), r"buzzer"),
    (r"ws28\d\d\w*|sk68\d\d\w*|neopixels?|addressable|apa10\d\w*|sk9822", ("WS2812",), r"rgb led|\bled"),
    (r"soil|moisture", ("soil moisture",), r"sensor"),
    (r"warm white|cool white|cold white|white leds?|illumination|high power leds?", ("2835",), r"\bled"),
    (r"ambient light|light sensors?|lux|illuminance|photoresistors?|ldr|photocells?", ("BH1750FVI", "GL5528"), r"light|photo"),
    (r"humidity|hygrometer|thermometer|temperature sensors?", ("AHT20",), r"humidity|temperature"),
    (r"accelerometers?|shake|imu|gyro\w*", ("LIS3DH",), r"accelerometer|gyro|imu|attitude"),
    (r"encoders?|rotary|knobs?", ("EC11",), r"encoder|rotary"),
    (r"(?:audio|headphone|3\.5 ?mm|tr[sr]) ?jacks?|jack ?3\.5", ("PJ-320", "PJ-307"), r"audio"),
    (r"6\.35 ?mm|guitar ?jacks?|1/4 ?inch", ("PJ-612", "PJ-601"), r"audio"),
    (r"midi|din-?5", ("DIN-504", "DIN-5"), r"din"),
    (r"(?:dc|barrel|power) ?jacks?", ("DC-005",), r"dc power"),
    (r"rj-?45|ethernet", ("RJ45",), r"ethernet|modular"),
    (r"xt-?30|xt-?60", ("XT30PW",), r"power connector"),
    (r"sma|antenna connectors?", ("SMA-KWE",), r"coaxial"),
    (r"npn|pnp|bjt|transistors?", ("S8050", "MMBT3904"), r"bipolar|bjt|transistor"),
    (r"mosfets?|n-?channel|nmos", ("AO3400",), r"mosfet|transistor"),
    (r"p-?channel|pmos", ("AO3401",), r"mosfet|transistor"),
    (r"chargers?|charging|li-?ion|li-?po|lipo|lithium", ("TP4056",), r"battery|charg|power management"),
    (r"ldo|regulators?", ("XC6206", "AMS1117"), r"regulator|ldo|power management"),
)
# words that say nothing (STOP) and words that do not say which category a hit belongs in (GENERIC: they still rank it)
STOP = {"a", "an", "the", "for", "with", "and", "or", "of", "to", "in", "on", "at", "by", "pcs", "type"}
GENERIC = {"sensor", "sensors", "module", "chip", "ic", "part", "board", "breakout", "high", "low", "power", "small", "mini",
           "digital", "analog", "smd", "tht", "led", "leds", "light", "capacitive", "cheap", "tiny", "3.3v", "5v", "3v3"}
# a word that matches more than its letters when ranking: a warm white LED's description says 2700K, not 'warm'; a PIR
# sensor's category says 'Human Body Sensing'
_PIR = r"pir|pyroelectric|human body"
_DISPLAY = r"display|oled|lcd"
SYNONYMS = {"warm": r"warm|\b2[5-9]\d\dk|\b3[0-5]\d\dk", "cool": r"cool|cold|\b[5-7]\d\d\dk", "cold": r"cool|cold|\b[5-7]\d\d\dk",
            "pir": _PIR, "motion": _PIR, "presence": _PIR, "occupancy": _PIR, "display": _DISPLAY, "screen": _DISPLAY,
            "addressable": r"addressable|built-in ic|ws28|sk68", "neopixel": r"neopixel|built-in ic|ws28|sk68",
            "moisture": r"moisture|humidity", "transistor": r"transistor|bjt|bipolar", "charger": r"charg|battery management",
            "beeper": r"buzzer", "sounder": r"buzzer"}
VALUE_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?(?:k|m|u|µ|n|p|meg)?(?:Ω|ohms?|r|f|v|a|ah|mah|w|hz|h|mm|%|ppm|db|k)?$|^\d+V\d+$", re.I)
PACKAGE_RE = re.compile(r"^(?:SOT|SOD|SOP|SOIC|SSOP|TSSOP|MSOP|ESOP|HSOP|QFN|DFN|VQFN|WQFN|QFP|LQFP|TQFP|BGA|LGA|TO|DO|SMA|SMB|SMC|"
                        r"DIP|SIP|SC|SON|WSON|USON|PLCC|SMD|LED)-?\d", re.I)


def _partlike(w: str) -> bool:
    """A word that reads as a part number (AM312, WS2812B, MLT-5020, 2N7002): letters and at least two digits, not a value
    (10k, 3.3V), a package (SOT-23-5) or an imperial size (0603)."""
    return (len(w) >= 4 and bool(re.search(r"[A-Za-z]", w)) and len(re.findall(r"\d", w)) >= 2 and not VALUE_RE.match(w)
            and not PACKAGE_RE.match(w))


def _reading(q: str) -> tuple[list[str], dict[str, set[int]], list[int]]:
    """(query words, word -> the CONCEPTS it belongs to, the concepts the query names)."""
    ql = q.lower()
    spans = [(m.group(0).strip(".:!?"), m.start(), m.end()) for m in re.finditer(r"[^\s,;()]+", ql)]
    words = list(dict.fromkeys(w for w, *_ in spans if len(w) >= 2 and w not in STOP))
    of: dict[str, set[int]] = {}
    named: list[int] = []
    for i, (pat, _, _) in enumerate(CONCEPTS):
        for m in re.finditer(rf"(?<![\w-])(?:{pat})(?![\w-])", ql):
            if i not in named:
                named.append(i)
            for w, a, b in spans:
                if a >= m.start() and b <= m.end():
                    of.setdefault(w, set()).add(i)
    return words, of, named


def _plan(q: str) -> list[str]:
    """The query as typed, then shorter ones from its strongest words: part numbers first, then the catalogue terms of the
    functions it names ('piezo buzzer' -> 'buzzer', 'WS2812 addressable LED' -> 'WS2812'). At most SEARCH_CALLS."""
    ql = q.lower()
    cands = [w.strip(",;()") for w in q.split() if _partlike(w.strip(",;()"))]
    for i in _reading(q)[2]:
        for t in CONCEPTS[i][1]:
            if t == "buzzer":  # 'passive buzzer' and 'active buzzer' are how LCSC tells them apart
                t = next((f"{d} buzzer" for d in ("passive", "active") if re.search(rf"\b{d}\b", ql)), t)
            cands.append(t)
    out = [q]
    for c in cands:
        if c and c.lower() not in {o.lower() for o in out}:
            out.append(c)
    return out[:SEARCH_CALLS]


def _hay(c: dict[str, Any]) -> str:
    return " ".join(str(c.get(k) or "") for k in ("lcsc", "mpn", "description", "category", "family", "package")).lower()


def _fits(c: dict[str, Any], concepts: list[int] | set[int]) -> bool:
    cat = f"{c.get('category') or ''} {c.get('family') or ''}".lower()
    return any(re.search(CONCEPTS[i][2], cat) for i in concepts)


def _relevant(q: str, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The hits a query can mean: when it names a function, a hit must be in a category that fits it, or carry another word
    of the query (a 'display connector' query keeps connectors); power inductors called SSD1306-220MT do not."""
    words, of, named = _reading(q)
    if not named:
        return cards
    rescue = [w for w in words if w not in of and w not in GENERIC]
    return [c for c in cards if _fits(c, named) or any(w in _hay(c) for w in rescue)]


def _rank(q: str, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """In stock first, then by how many query words (or their SYNONYMS) a hit's part number, description and category
    carry, then the basic library; ties keep the catalogue's order (the query as typed before its fallbacks)."""
    pats = [re.compile(SYNONYMS.get(w, re.escape(w))) for w in _reading(q)[0]]
    hays = {id(c): _hay(c) for c in cards}
    return sorted(cards, key=lambda c: (int(c.get("stock") or 0) <= 0, -sum(1 for p in pats if p.search(hays[id(c)])), not c.get("basic")))


async def search(q: str, *, limit: int = 8, basic: bool = False, fallback: bool = True) -> list[dict[str, Any]]:
    """LCSC parts matching `q` (a part number, an LCSC code or keywords such as "BME280", "10kΩ 0603", "piezo buzzer"),
    in-stock first, best match next. basic=True keeps JLCPCB's basic library only (no extended-part fee at assembly).
    When the query as typed finds too little, it is asked again with its strongest words (at most SEARCH_CALLS calls in
    all); fallback=False asks once, as typed (an LCSC code, a value lookup). Few ready modules (OLED boards, probes) are
    on LCSC: a query for one finds nothing rather than something else."""
    q = " ".join(str(q or "").split())[:120]
    if not q:
        return []
    limit = max(1, min(int(limit), 30))
    found: dict[str, dict[str, Any]] = {}
    kept: list[dict[str, Any]] = []
    for i, kw in enumerate(_plan(q) if fallback else [q]):
        try:
            cards = await _query(kw, size=max(limit, 10) if i == 0 else max(limit, 20), basic=basic, retry=i == 0)
        except CatalogError:
            if i:
                break  # a fallback the catalogue refused: what the query found so far
            # the answer an earlier version of this search cached under its own key
            legacy = _dir("search") / (hashlib.sha1(json.dumps([q.lower(), limit, basic]).encode()).hexdigest()[:20] + ".json")
            if not legacy.is_file():
                raise
            cards = json.loads(legacy.read_text(encoding="utf-8"))
        for c in cards:
            found.setdefault(c["lcsc"], c)
        kept = _relevant(q, list(found.values()))
        if len(kept) >= min(limit, 3):
            break
    return _rank(q, kept)[:limit]


# ------------------------------------------------------------------ the cache on disk
MISS = object()


def _cache(path: Path, data: bytes) -> None:
    """One answer on disk, whole: a crash mid-write must not leave a file that fails every later read."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as e:  # a read-only or full disk costs the cache, not the answer
        log.warning("catalogue cache %s: %s", path.name, e)
    finally:
        tmp.unlink(missing_ok=True)


def _cached(path: Path) -> Any:
    """The JSON kept in this file, or MISS: no file, or a damaged one, which goes."""
    if not path.is_file():
        return MISS
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("catalogue cache %s is damaged, dropped: %s", path.name, e)
        path.unlink(missing_ok=True)
        return MISS


# ------------------------------------------------------------------ EasyEDA component (pins + footprint)
async def easyeda(code: str) -> dict[str, Any] | None:
    """The EasyEDA library entry of an LCSC part (symbol + packageDetail), or None when EasyEDA has none."""
    c = norm_code(code)
    if not c:
        return None
    path = _dir("easyeda") / f"{c}.json"
    if (known := _cached(path)) is not MISS:
        return known or None
    lock = _locks.setdefault(c, asyncio.Lock())
    async with lock:
        if (known := _cached(path)) is not MISS:
            return known or None
        try:
            async with httpx.AsyncClient(timeout=25, headers={"user-agent": UA}) as h:
                r = await h.get(EASYEDA.format(code=c))
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise CatalogError(f"EasyEDA did not answer for {c} ({type(e).__name__}); try again") from e
        result = data.get("result") if data.get("success") else None
        ok = isinstance(result, dict) and isinstance(result.get("packageDetail"), dict) and result.get("dataStr")
        _cache(path, json.dumps(result if ok else {}, ensure_ascii=False).encode())
        return result if ok else None


def model_uuid(raw: dict[str, Any] | None) -> str | None:
    """The uuid of the footprint's 3D model in EasyEDA's library, or None when it has none."""
    u = str(_svgnode(raw or {}).get("uuid") or "")
    return u if re.fullmatch(r"[0-9a-zA-Z]{16,64}", u) else None


def model_outline(raw: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """The footprint's 3D model outline (x0, y0, x1, y1) in the frame of pads_of, or None: what the converter takes for the
    courtyard (its SVGNODE's polygon points, EasyEDA units of 10 mil)."""
    d = (raw.get("packageDetail") or {}).get("dataStr") or {}
    head = d.get("head") or {}
    pts: list[tuple[float, float]] = []
    try:
        ox, oy = float(head["x"]), float(head["y"])
        for s in d.get("shape") or []:
            if isinstance(s, str) and s.startswith("SVGNODE~"):
                for ch in (json.loads(s.split("~", 1)[1]).get("childNodes") or []):
                    v = [float(t) for t in str(((ch or {}).get("attrs") or {}).get("points") or "").split()]
                    pts += [((v[i] - ox) * EE_UNIT, (oy - v[i + 1]) * EE_UNIT) for i in range(0, len(v) - 1, 2)]
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not pts:
        return None
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def model_place(raw: dict[str, Any], obj: str) -> dict[str, Any]:
    """Where a footprint puts its 3D model: {at: [dx, dy, dz] mm from the package's anchor (the frame of pads_of), rot: [x, y, z]
    degrees}. In plan the model's middle goes to the middle of the outline EasyEDA drew for it (c_origin is often left over from
    another drawing, a metre off), or of the pads when that outline lies off them too. In height its lowest point goes to
    SVGNODE z (a through-hole part's leads reach below the board)."""
    node = _svgnode(raw)
    num = lambda v: float(v) if re.fullmatch(r"-?\d+(?:\.\d+)?", str(v or "").strip()) else 0.0  # noqa: E731
    rot = [num(r) for r in (str(node.get("c_rotation") or "").split(",") + ["0", "0", "0"])[:3]]
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for line in obj.splitlines():
        if line.startswith("v "):
            v = line.split()
            try:
                xs.append(float(v[1]))
                ys.append(float(v[2]))
                zs.append(float(v[3]))
            except (IndexError, ValueError):
                continue
    if not xs:
        return {"at": [0.0, 0.0, 0.0], "rot": rot}
    pads = list(pads_of(raw).values())
    pad_mid = ((min(p[0] for p in pads) + max(p[0] for p in pads)) / 2, (min(p[1] for p in pads) + max(p[1] for p in pads)) / 2) if pads else (0.0, 0.0)
    reach = max([max(abs(p[0] - pad_mid[0]) + p[2] / 2, abs(p[1] - pad_mid[1]) + p[3] / 2) for p in pads] or [0.0]) + max(max(xs) - min(xs), max(ys) - min(ys))
    box = model_outline(raw)
    mid = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2) if box else pad_mid
    if math.hypot(mid[0] - pad_mid[0], mid[1] - pad_mid[1]) > reach:
        mid = pad_mid
    ox, oy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    c, s = math.cos(math.radians(rot[2])), math.sin(math.radians(rot[2]))
    return {"at": [round(mid[0] - (ox * c - oy * s), 3) + 0.0, round(mid[1] - (ox * s + oy * c), 3) + 0.0, round(num(node.get("z")) * EE_UNIT - min(zs), 3) + 0.0], "rot": rot}


def mouth_of(raw: dict[str, Any], obj: str | None = None) -> dict[str, Any] | None:
    """Which way a connector opens, read off its drawing: the side where its body (the 3D model where there is one, else the package's
    outline) stands furthest past its pads, since a plug needs the body's front clear of the solder. {dir: '+x'|'-x'|'+y'|'-y' at rotation
    0, reach: mm from the origin to that face, across: its middle along the face from the origin, w: its width there, z0, z1: its height
    over the board}, or None when the drawing does not say: pads as wide as the body all round, or nothing to read."""
    pads = list(pads_of(raw).values())
    if not pads:
        return None
    px0, px1 = min(p[0] - p[2] / 2 for p in pads), max(p[0] + p[2] / 2 for p in pads)
    py0, py1 = min(p[1] - p[3] / 2 for p in pads), max(p[1] + p[3] / 2 for p in pads)
    z0, z1 = 0.0, height_of(raw) or 5.0
    box: tuple[float, float, float, float] | None = None
    if obj:
        place = model_place(raw, obj)
        pts = [[float(v) for v in ln.split()[1:4]] for ln in obj.splitlines() if ln.startswith("v ")]
        if pts:
            a = math.radians(place["rot"][2])
            c, s_ = math.cos(a), math.sin(a)
            xs = [x * c - y * s_ + place["at"][0] for x, y, _ in pts]
            ys = [x * s_ + y * c + place["at"][1] for x, y, _ in pts]
            zs = [z + place["at"][2] for _, _, z in pts]
            box = (min(xs), min(ys), max(xs), max(ys))
            z0, z1 = max(0.0, min(zs)), max(zs)
    box = box or box_of(raw)
    if not box:
        return None
    over = {"+x": box[2] - px1, "-x": px0 - box[0], "+y": box[3] - py1, "-y": py0 - box[1]}
    side = max(over, key=lambda k: over[k])
    ranked = sorted(over.values(), reverse=True)
    if over[side] < 0.5 or ranked[0] - ranked[1] < 0.3:
        return None
    onx = side[1] == "x"
    reach = {"+x": box[2], "-x": -box[0], "+y": box[3], "-y": -box[1]}[side]
    across = (box[1] + box[3]) / 2 if onx else (box[0] + box[2]) / 2
    # its copper keeps off the rim however short its nose is
    pad = {"+x": px1, "-x": -px0, "+y": py1, "-y": -py0}[side]
    return {"dir": side, "reach": round(reach, 2), "pad": round(pad, 2), "across": round(across, 2), "w": round((box[3] - box[1]) if onx else (box[2] - box[0]), 2),
            "d": round((box[2] - box[0]) if onx else (box[3] - box[1]), 2), "z0": round(z0, 2), "z1": round(z1, 2)}


async def model_obj(raw: dict[str, Any] | None) -> tuple[str, str] | None:
    """(uuid, OBJ text) of a part's real 3D model, cached for good (an absent or oversized one as an empty file, so it is
    asked once); None without one. A model the catalogue cannot serve costs the part its look, never a build."""
    uuid = model_uuid(raw)
    if not uuid:
        return None
    path = _dir("models") / f"{uuid}.obj"
    if not path.is_file():
        lock = _locks.setdefault(f"model:{uuid}", asyncio.Lock())
        async with lock:
            if not path.is_file():
                try:
                    async with httpx.AsyncClient(timeout=25, headers={"user-agent": UA}, follow_redirects=True) as h:
                        r = await h.get(EASYEDA_MODEL.format(uuid=uuid))
                except httpx.HTTPError as e:
                    log.warning("3D model %s: %s", uuid, e)
                    return None
                # a refusal or a passing failure says nothing about the model: asked again next time
                if r.status_code >= 500 or r.status_code in (403, 408, 425, 429):
                    return None
                ok = r.status_code == 200 and len(r.content) <= MODEL_MAX_BYTES and b"\nf " in r.content
                _cache(path, r.content if ok else b"")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return (uuid, text) if text else None


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
    """A tscircuit pin label: letters, digits and _, not starting with a digit ('3V3' -> 'V3V3', 'IO0/BOOT' -> 'IO0_BOOT').
    A polarity sign stays readable: a lone '+'/'-' is POS/NEG, a trailing one P/N ('VIN+' -> 'VINP', 'IN-' -> 'INN',
    'D-' -> 'DN'), so a buzzer's '+' and '-' are two pins, not 'P' twice."""
    s = str(name).strip().replace("−", "-")
    if s in ("+", "-"):
        return "POS" if s == "+" else "NEG"
    s = re.sub(r"-$", "N", re.sub(r"^-(?=\d)", "N", s))
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s.replace("+", "P").replace("~", "N").replace("#", "N")).strip("_")
    if not s:
        return "P"
    if s[0].isdigit():
        s = ("V" if re.match(r"^\d+V\d*$", s) else "P") + s
    return s[:24]


# pins the board joins anyway: supplies, grounds, exposed pads, shields, no-connects, a USB receptacle's twin D+/D-, the
# parallel pads of a power path (a MOSFET's D and S, a converter's SW/LX). Two pins of one such name are one reference:
# 'U1.GND' wires every GND. Any other repeated name is two terminals and gets a label per pin.
JOINED = re.compile(r"^(?:[ADPS]?GND\w*|V(?:SS|CC|DD|EE)\w*|[AD]V(?:CC|DD|SS)\w*|IOVDD|VCCIO|V(?:IN|OUT|BUS|BAT|SYS|O)|[PV]\d+V\d*"
                    r"|EP|EPAD|PAD|TAB|THERMAL\w*|EXPOSED\w*|SH|SHIELD|SHELL|MH|MP|MOUNT\w*|NC|DNC|DP|DN|DM|SW|LX|D|S|DRAIN|SOURCE)$", re.I)


def labels_of(pins: list[dict[str, str]], roles: dict[str, str] | None = None) -> dict[str, str]:
    """pinN -> unique label. A repeated supply-like name (JOINED) is one group: the second GND is GND_7 (its pin number) and
    base_label folds it back, so 'U2.GND' still means all of them. Any other repeated name, or two names that clean up
    alike ('EN#', 'ENN'), gets a label per pin ('P', 'P' -> P1, P2) that base_label leaves alone. `roles` ({pin number:
    'B'}) relabels the pins of a discrete whose symbol only numbers them."""
    roles = roles or {}
    nums = [p["num"] if p["num"].isdigit() else safe_label(p["num"]) for p in pins]
    bases = [roles.get(p["num"]) or safe_label(p["name"]) for p in pins]
    count = {b: bases.count(b) for b in bases}
    joined = {b for b in bases if count[b] > 1 and JOINED.match(b)}
    if len(pins) >= 2 and len({b if b in joined else (b, n) for b, n in zip(bases, nums)}) < 2:
        joined = set()  # a two-pin part never folds into one terminal
    used = {b for b in bases if count[b] == 1}  # a name only one pin has keeps it
    out: dict[str, str] = {}
    seen: set[str] = set()
    for base, num in zip(bases, nums):
        lb = base
        if count[base] > 1:
            if base not in joined:
                lb = f"{base}{num}" if base[-1].isalpha() and num.isdigit() else f"{base}_{num}"
            elif base in seen:
                lb = f"{base}_{num}"
            seen.add(base)
            while lb in used:  # 'P', 'P', 'P1': the generated P1 is taken
                lb += f"_{num}"
            used.add(lb)
        out[f"pin{num}"] = lb
    return out


def base_label(label: str) -> str:
    """'GND_7' -> 'GND' (a supply-like pin's twin folds into its group); any other label is its own group ('P2', 'IO_12')."""
    m = re.match(r"^(.*?)(?:_[A-Za-z]?\d+)+$", label)
    return m.group(1) if m and JOINED.match(m.group(1)) else label


def _svgnode(raw: dict[str, Any]) -> dict[str, Any]:
    for s in ((raw.get("packageDetail") or {}).get("dataStr") or {}).get("shape") or []:
        if isinstance(s, str) and s.startswith("SVGNODE~"):
            try:
                return json.loads(s.split("~", 1)[1]).get("attrs") or {}
            except (json.JSONDecodeError, AttributeError):
                return {}
    return {}


def _mm(v: Any) -> float | None:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*mm\b", str(v or ""))
    return float(m.group(1)) if m else None


def _attr_height(attrs: dict[str, str] | None, plan: list[float] | None) -> float | None:
    """LCSC's Height parameter. Now and then LCSC swaps Width and Height (a 5050 LED listed 'Height 5mm, Width 1.6mm'): a
    side much smaller than the footprint is then the height."""
    h = _mm((attrs or {}).get("Height"))
    if not h:
        return None
    sides = [s for s in (_mm(attrs.get("Length")), _mm(attrs.get("Width"))) if s]  # type: ignore[union-attr]
    if plan and sides and min(sides) < h and min(sides) < 0.6 * min(plan):
        return min(sides)
    return h


def height_of(raw: dict[str, Any], category: str = "", attrs: dict[str, str] | None = None) -> float | None:
    """Body height in mm: the larger of the 3D model's or package's name ('...-H0.9-...') and LCSC's Height parameter
    (`attrs`, from the search card). A footprint may borrow another part's 3D model: the 23 mm buzzer HND-2319 has a
    16 mm-high model but stands 19.3 mm, and the case must clear the real one. None when nothing says."""
    names = [str(_svgnode(raw).get("title") or ""), str(((raw.get("dataStr") or {}).get("head") or {}).get("c_para", {}).get("package") or "")]
    model = next((float(m.group(1)) for n in names if (m := re.search(r"-H(\d+(?:\.\d+)?)", n))), None)
    found = [h for h in (model, _attr_height(attrs, size_of(raw))) if h]
    if found:
        return round(max(found), 2)
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


# ------------------------------------------------------------------ what a part is
def kind_of(card: dict[str, Any]) -> str:
    """What the part is, from its LCSC category, description and parameters: npn | pnp | nmos | pmos | transistor (polarity
    unknown) | diode | tvs | led | rgb_led (an LED with its own driver IC: WS2812, SK6812) | buzzer_active (sounds on DC) | buzzer_passive
    (needs a tone) | buzzer | speaker | sensor | display | mcu | regulator | charger | resistor | capacitor | inductor |
    crystal | connector | switch | fuse | motor | ic (anything else). The designer, the case (what a part needs above it)
    and the design rules read it."""
    cat = f"{card.get('category') or ''} / {card.get('family') or ''}".lower()
    attrs = card.get("attrs") or {}
    text = " ".join([str(card.get("mpn") or ""), str(card.get("description") or ""), *(f"{k} {v}" for k, v in attrs.items())]).lower()
    pkg = f"{card.get('package') or ''} {card.get('footprint_name') or ''}".lower()
    if "built-in ic" in cat or (re.search(r"\b(ws28\d\d|sk68\d\d|apa10\d|sk9822)|2812b?\b", text) and "led" in cat):
        return "rgb_led"
    if re.search(r"\bleds?\b|light emitting", cat) and "driver" not in cat:
        return "led"
    if "buzzer" in cat:
        drive = (attrs.get("Driver Circuitry") or text).lower()
        return "buzzer_active" if re.search(r"\bactive\b", drive) else "buzzer_passive" if "passive" in drive else "buzzer"
    if "speaker" in cat:
        return "speaker"
    if re.search(r"bipolar|bjt|darlington|digital transistor", cat):
        npn, pnp = bool(re.search(r"\bnpn\b", text)), bool(re.search(r"\bpnp\b", text))
        return "npn" if npn and not pnp else "pnp" if pnp and not npn else "transistor"
    if "mosfet" in cat:
        n, p = bool(re.search(r"\bn-?channel", text)), bool(re.search(r"\bp-?channel", text))
        return "nmos" if n and not p else "pmos" if p and not n else "transistor"
    if "human body" in cat:  # a PIR element (TO-5 can) or a PIR controller chip (BISS0001, SOP-16): only one looks out
        return "ic" if re.search(r"\b(sop|soic|ssop|tssop|msop|dip|qfn|dfn)", pkg) else "sensor"
    if re.search(r"sensor|accelerometer|gyro|magnetometer|photoresistor|photodiode|phototransistor|hall|thermistor|microphone|\bimu\b", cat):
        return "sensor"
    if re.search(r"tvs|esd", cat):
        return "tvs"
    if re.search(r"diode|rectifier", cat):
        return "diode"
    for kind, pat in (("display", r"display|oled|lcd"), ("mcu", r"microcontroller|\bmcu\b"), ("charger", r"battery management|charger"),
                      ("regulator", r"regulator|ldo|dc-dc"), ("resistor", r"resistor|potentiometer"), ("capacitor", r"capacitor"),
                      ("inductor", r"inductor|choke|ferrite"), ("crystal", r"crystal|oscillator|resonator"), ("fuse", r"fuse"),
                      ("motor", r"vibration motor|^motors?\b"), ("switch", r"switch"),
                      ("connector", r"connector|header|terminal|socket|usb")):
        if re.search(pat, cat) and "driver" not in cat:
            return kind
    return "ic"


CURRENT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(nA|uA|µA|mA|A)(?![A-Za-z])")
TO_MA = {"nA": 1e-6, "uA": 1e-3, "µA": 1e-3, "mA": 1.0, "A": 1000.0}
# a current parameter that is not what the part draws or carries
IDLE_CURRENT = re.compile(r"cut-?off|leakage|quiescent|standby|sleep|shutdown|reverse|surge|peak|saturation|bias|offset|static|off", re.I)


def _ma(s: str) -> float | None:
    vals = [float(m.group(1)) * TO_MA[m.group(2)] for m in CURRENT_RE.finditer(str(s or ""))]
    return max(vals) if vals else None


def current_of(card: dict[str, Any], kind: str = "") -> float | None:
    """The rated or maximum current in mA: LCSC's current parameter (a buzzer's 30 mA consumption, a BJT's Ic, a MOSFET's
    Id, an LED's test current, a diode's rectified current), leakage and quiescent currents left out; without parameters
    the largest current the description names. None when nothing says (an addressable LED's description gives only its
    driver's idle current: about 60 mA per pixel at full white is the usual budget)."""
    attrs = card.get("attrs") or {}
    vals = [v for k, val in attrs.items() if re.search(r"current", k, re.I) and not IDLE_CURRENT.search(k) and (v := _ma(val))]
    if vals:
        return round(max(vals), 3)
    if attrs or kind == "rgb_led":
        return None
    v = _ma(card.get("description") or "")
    return round(v, 3) if v else None


BJT_PACKAGE = re.compile(r"^(?:sot-?23(?:-3l?)?|sot-?323|sot-?416|sot-?523|sot-?723|sc-?70(?:-3)?|sc-?59|sc-?75|to-?236)(?![-\d])", re.I)
DIODE_PACKAGE = re.compile(r"^(?:sod-?123\w*|sod-?323\w*|sod-?523|sod-?923|sma\w?|smb\w?|smc|do-?214a[abc])(?![-\d])", re.I)
# (package family, its pattern, pin number -> role) of the discretes whose standard pinout is one for every maker
STANDARD_PINOUT = {
    "bjt": ("SOT-23 BJT", BJT_PACKAGE, {"1": "B", "2": "E", "3": "C"}),
    "mosfet": ("SOT-23 MOSFET", BJT_PACKAGE, {"1": "G", "2": "S", "3": "D"}),
    "diode": ("SOD-123/SMA diode", DIODE_PACKAGE, {"1": "K", "2": "A"}),
}
ROLE_SET = {"npn": "bjt", "pnp": "bjt", "bjt": "bjt", "nmos": "mosfet", "pmos": "mosfet", "mosfet": "mosfet", "diode": "diode", "led": "led"}
ROLE_WANT = {"bjt": "BCE", "mosfet": "DGS", "diode": "AK", "led": "AK"}
ROLE_NAME = {"B": "B", "BASE": "B", "E": "E", "EMITTER": "E", "C": "C", "COLLECTOR": "C", "G": "G", "GATE": "G", "S": "S",
             "SOURCE": "S", "D": "D", "DRAIN": "D", "A": "A", "ANODE": "A", "K": "K", "CATHODE": "K", "+": "A", "-": "K"}
BARE_PIN = re.compile(r"^(?:P|PIN)?\d+$", re.I)
BUZZER_KINDS = ("buzzer", "buzzer_active", "buzzer_passive")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")
Point = tuple[float, float]


def _sym_pins(raw: dict[str, Any]) -> dict[str, tuple[Point, Point]]:
    """Pin number -> (outer end, inner end) of the symbol's pins ('P~show~0~1~380~300~...^^...^^M 380 300 h 15~...'): the
    outer end is where a wire attaches, the inner end touches the body."""
    out: dict[str, tuple[Point, Point]] = {}
    for s in (raw.get("dataStr") or {}).get("shape") or []:
        if not isinstance(s, str) or not s.startswith("P~"):
            continue
        segs = s.split("^^")
        head = segs[0].split("~")
        try:
            num, x, y = head[3], float(head[4]), float(head[5])
        except (IndexError, ValueError):
            continue
        inner = (x, y)
        m = re.match(r"^\s*M\s*(-?[\d.]+)[\s,]+(-?[\d.]+)\s*([hv])\s*(-?[\d.]+)", segs[2].split("~")[0] if len(segs) > 2 else "")
        if m:
            x0, y0, d = float(m[1]), float(m[2]), float(m[4])
            inner = (x0 + d, y0) if m[3] == "h" else (x0, y0 + d)
        if num and num not in out:
            out[num] = ((x, y), inner)
    return out


def _triangles(raw: dict[str, Any]) -> list[tuple[float, list[Point]]]:
    """(area, vertices) of every closed three-point shape of the symbol: an absolute PT path (M, L, Z) or a PG polygon."""
    out: list[tuple[float, list[Point]]] = []
    for s in (raw.get("dataStr") or {}).get("shape") or []:
        f = s.split("~") if isinstance(s, str) else []
        if len(f) < 2 or f[0] not in ("PT", "PG") or (f[0] == "PT" and not re.fullmatch(r"[\s\d.,\-MLZ]+", f[1])):
            continue
        v = [float(x) for x in _NUM.findall(f[1])]
        p = list(zip(v[0::2], v[1::2]))
        if len(p) == 4 and p[0] == p[3]:
            p = p[:3]
        if len(v) % 2 or len(p) != 3:
            continue
        area = abs((p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[2][0] - p[0][0]) * (p[1][1] - p[0][1])) / 2
        if area > 0:
            out.append((area, p))
    return out


def diode_roles(raw: dict[str, Any] | None, pins: list[dict[str, str]]) -> dict[str, str]:
    """{pin number: 'A' | 'K'} from a diode's or LED's symbol: its largest triangle (an LED's emission arrows are small
    ones) points at the cathode; the anode is behind its base. The two pins must lie on the triangle's axis, one on each
    side, its base square to that axis (two pins only, or the one pair of several that does); {} when anything is
    unclear: no triangle, two of about the largest size (a bicolour LED, a diode pair), no such pin pair or more than one."""
    if not raw:
        return {}
    tris = sorted(_triangles(raw), key=lambda t: -t[0])
    if not tris:
        return {}
    area, tri = tris[0]
    rival = next((t for a, t in tris[1:] if a >= 0.6 * area and sorted(t) != sorted(tri)), None)
    ends = {n: e[0] for n, e in _sym_pins(raw).items() if n in {p["num"] for p in pins}}
    if rival or len(ends) < 2:
        return {}
    cx, cy = sum(q[0] for q in tri) / 3, sum(q[1] for q in tri) / 3
    found: list[dict[str, str]] = []
    nums = list(ends)
    for i, na in enumerate(nums):
        for nb in nums[i + 1:]:
            (ax, ay), (bx, by) = ends[na], ends[nb]
            L = math.hypot(bx - ax, by - ay)
            if not L:
                continue
            ux, uy = (bx - ax) / L, (by - ay) / L
            proj = sorted((q[0] - ax) * ux + (q[1] - ay) * uy for q in tri)
            off = abs((cx - ax) * uy - (cy - ay) * ux)  # the triangle's distance from the line through the two pins
            width = max(abs((q[0] - r[0]) * uy - (q[1] - r[1]) * ux) for q in tri for r in tri)
            lo, mid, hi = proj
            base_low = mid - lo < hi - mid  # two vertices low: the base is low, the tip high
            spread, tip, base = (mid - lo, hi, (lo + mid) / 2) if base_low else (hi - mid, lo, (mid + hi) / 2)
            if abs(tip - base) < 1 or spread > 0.35 * abs(tip - base) or lo < -1 or hi > L + 1:
                continue
            if len(ends) > 2 and off > max(2.0, width / 2):
                continue
            toward_b = tip > base  # the triangle points at pin b: b is the cathode
            found.append({na: "K" if not toward_b else "A", nb: "A" if not toward_b else "K"})
    return found[0] if len(found) == 1 else {}


def _crosses(segs: list[tuple[Point, Point]]) -> list[Point]:
    """Centres of the '+' signs drawn as two short lines, one level and one upright, crossing at their middles."""
    level = [s for s in segs if abs(s[0][1] - s[1][1]) < 0.01 and 1.5 <= abs(s[0][0] - s[1][0]) <= 15]
    upright = [s for s in segs if abs(s[0][0] - s[1][0]) < 0.01 and 1.5 <= abs(s[0][1] - s[1][1]) <= 15]
    out: list[Point] = []
    for h in level:
        for v in upright:
            lh, lv = abs(h[0][0] - h[1][0]), abs(v[0][1] - v[1][1])
            mh = ((h[0][0] + h[1][0]) / 2, h[0][1])
            mv = (v[0][0], (v[0][1] + v[1][1]) / 2)
            if 0.5 <= lh / lv <= 2 and math.hypot(mh[0] - mv[0], mh[1] - mv[1]) <= 0.25 * min(lh, lv):
                out.append(mh)
    return out


def _segments(shapes: list[Any], kind: str, layer: str | None = None) -> list[tuple[Point, Point]]:
    """Two-point lines of the symbol ('PL~x1 y1 x2 y2~...') or of the footprint's top silkscreen ('TRACK~w~3~net~x1 y1 x2 y2~...')."""
    out: list[tuple[Point, Point]] = []
    for s in shapes:
        f = s.split("~") if isinstance(s, str) else []
        if not f or f[0] != kind or (layer is not None and (len(f) < 3 or f[2] != layer)):
            continue
        v = [float(x) for x in _NUM.findall(f[1] if kind == "PL" else f[4] if len(f) > 4 else "")]
        if len(v) == 4:
            out.append(((v[0], v[1]), (v[2], v[3])))
    return out


def _nearest(mark: Point, at: dict[str, Point]) -> str | None:
    """The one of two points clearly nearest the mark (under 0.6 of the other's distance), else None."""
    if len(at) != 2:
        return None
    (na, a), (nb, b) = at.items()
    da, db = math.hypot(mark[0] - a[0], mark[1] - a[1]), math.hypot(mark[0] - b[0], mark[1] - b[1])
    return na if da < 0.6 * db else nb if db < 0.6 * da else None


def buzzer_roles(raw: dict[str, Any] | None, pins: list[dict[str, str]]) -> tuple[dict[str, str], str]:
    """({pin number: 'POS' | 'NEG'}, note) of a two-pin buzzer whose symbol only numbers its pins, from a polarity mark:
    a '+' or '-' text on the footprint (TMB12075 C49246934 prints '+' by pad 1), a '+' drawn in silkscreen lines on the
    footprint or in lines on the symbol (YX-YT9042 C781847, by pin 1), the pin or pad it is clearly nearest. Marks that
    disagree give no roles; no mark gives pin 1 = + (the usual buzzer pinout), said as an assumption."""
    nums = [p["num"] for p in pins]
    pk = ((raw or {}).get("packageDetail") or {}).get("dataStr") or {}
    fshapes = [s for s in pk.get("shape") or [] if isinstance(s, str)]
    pads: dict[str, Point] = {}
    for s in fshapes:
        b = s.split("~")
        if b[0] == "PAD" and len(b) > 8 and b[8] in nums and b[8] not in pads:
            try:
                pads[b[8]] = (float(b[2]), float(b[3]))
            except ValueError:
                pass
    plus: list[tuple[str, str]] = []  # (the pin the + is by, where the mark is)
    for s in fshapes:
        b = s.split("~")
        if b[0] == "TEXT" and len(b) > 10 and b[10].strip().replace("−", "-") in ("+", "-"):
            try:
                near = _nearest((float(b[2]), float(b[3])), pads)
            except ValueError:
                continue
            if near:
                plus.append((near if b[10].strip() == "+" else next(n for n in nums if n != near), "a '" + b[10].strip() + "' printed on the footprint"))
    plus += [(n, "a '+' drawn on the footprint's silkscreen") for c in _crosses(_segments(fshapes, "TRACK", "3")) if (n := _nearest(c, pads))]
    inner = {n: e[1] for n, e in _sym_pins(raw or {}).items() if n in nums}
    sym = [s for s in ((raw or {}).get("dataStr") or {}).get("shape") or [] if isinstance(s, str)]
    plus += [(n, "a '+' drawn on the symbol") for c in _crosses(_segments(sym, "PL")) if (n := _nearest(c, inner))]
    by = {n for n, _ in plus}
    if len(by) > 1:
        return {}, ("the symbol and footprint mark + by different pins (" + "; ".join(f"{w} by pin {n}" for n, w in plus) + "): read the "
                    "datasheet for which pin is + and wire by number")
    if by:
        p = by.pop()
        n = next(x for x in nums if x != p)
        return {p: "POS", n: "NEG"}, (f"pin {p}=POS, pin {n}=NEG come from {plus[0][1]} by pin {p} (the symbol only numbers its pins): "
                                     "check the + marked on the part")
    a, b = sorted(nums, key=lambda x: (0, int(x)) if x.isdigit() else (1, x))
    return {a: "POS", b: "NEG"}, (f"no polarity mark found on the symbol or footprint: pin {a} is taken as + (POS) and pin {b} as - (NEG), "
                                  "the usual buzzer pinout; check the + marked on the part before wiring")


def roles_of(pins: list[dict[str, str]], kind: str, packages: list[str], raw: dict[str, Any] | None = None) -> tuple[dict[str, str], str | None]:
    """({pin number: role label}, a note for the card) of a discrete: a transistor's B/E/C or G/S/D, a diode's or LED's A/K,
    a buzzer's POS/NEG. Names the symbol gives (B, Emitter, Gate, Anode, a diode's '+'/'-') are used as they are. A symbol
    that only numbers its pins (S8050 C181158: '1', '2', '3') gets the roles of the package's standard pinout (SOT-23:
    1=B 2=E 3=C, 1=G 2=S 3=D; SOD-123/SMA: 1=K 2=A) and a note to check the datasheet; TO-92 and other packages whose
    pinout differs between makers get no roles, only the note. A numbered diode or LED takes A/K from its symbol's
    triangle first (`raw`, the EasyEDA entry: diode_roles; the 2835 LED C210315 is 1=K 2=A), a numbered two-pin buzzer
    POS/NEG from its polarity mark (buzzer_roles). A two-pin part whose symbol marks one pin '+' or '-' gets the other
    sign on the other pin."""
    names = [str(p["name"]).strip().replace("−", "-") for p in pins]
    bare = [bool(BARE_PIN.match(n)) or n == p["num"] for n, p in zip(names, pins)]
    group = ROLE_SET.get(kind)
    signs = [i for i, n in enumerate(names) if n in ("+", "-")]
    if len(pins) == 2 and len(signs) == 1 and bare[1 - signs[0]]:
        i, j = signs[0], 1 - signs[0]
        plus = names[i] == "+"
        note = f"the symbol marks only pin {pins[i]['num']} ({names[i]}): pin {pins[j]['num']} is taken as the {'-' if plus else '+'} terminal"
        if group in ("diode", "led"):
            return {pins[i]["num"]: "A" if plus else "K", pins[j]["num"]: "K" if plus else "A"}, note
        if not group:
            return {pins[j]["num"]: "NEG" if plus else "POS"}, note
    if kind in BUZZER_KINDS and len(pins) == 2 and all(bare):
        return buzzer_roles(raw, pins)
    if not group:
        return {}, None
    named = {p["num"]: ROLE_NAME.get(n.upper()) for n, p in zip(names, pins)}
    if len(pins) == len(ROLE_WANT[group]) and "".join(sorted(r or "?" for r in named.values())) == ROLE_WANT[group]:
        return {k: v for k, v in named.items() if v}, None
    if group in ("diode", "led") and all(bare) and (tri := diode_roles(raw, pins)):
        spelled = ", ".join(f"{n}={tri[n]}" for n in sorted(tri, key=lambda x: (0, int(x)) if x.isdigit() else (1, x)))
        return tri, f"pin roles {spelled} come from the diode triangle on the symbol (the symbol only numbers its pins): check the polarity mark on the part"
    if group == "led" or not all(bare):
        return {}, None  # the symbol's names mean something: they stay
    fam, pat, roles = STANDARD_PINOUT[group]
    pkg = next((x for x in packages if x), "") or "unknown"
    if len(pins) == len(roles) and {p["num"] for p in pins} == set(roles) and any(x and pat.match(x) for x in packages):
        spelled = ", ".join(f"{n}={r}" for n, r in roles.items())
        return dict(roles), f"pin roles {spelled} come from the standard {fam} pinout (the symbol only numbers its pins): verify in the datasheet"
    return {}, (f"the symbol only numbers its pins and the {pkg} package has no pinout every maker shares (TO-92 transistors "
                f"differ, SOT-23 diode pairs come in several configurations): read the datasheet for which pin is which and wire by number")


def card_pins(raw: dict[str, Any], card: dict[str, Any], kind: str) -> tuple[list[dict[str, str]], str | None]:
    """The card's pins [{num, name, label}] and pin_note: the symbol's pins (pins_of) labelled by labels_of with the roles
    roles_of finds for a part of this kind (kind_of of the card) and its package."""
    pins = pins_of(raw)
    # a transistor of unknown polarity still has a BJT's or a MOSFET's pins
    rk = kind if kind != "transistor" else "mosfet" if "mosfet" in f"{card.get('category')} {card.get('description')}".lower() else "bjt"
    head = ((raw.get("dataStr") or {}).get("head") or {}).get("c_para") or {}
    roles, note = roles_of(pins, rk, [str(card.get("package") or ""), str(head.get("package") or "")], raw)
    labels = labels_of(pins, roles)
    return [{"num": p["num"], "name": p["name"], "label": labels[f"pin{p['num'] if p['num'].isdigit() else safe_label(p['num'])}"]} for p in pins], note


async def info(code: str) -> dict[str, Any]:
    """Everything about one LCSC part: the catalogue card (stock, prices, LCSC's parameters as attrs) and its pins
    [{num, name, label}], footprint size and height, kind_hint (kind_of), current_ma (current_of) and pin_note (how the
    pin roles were found, or that they were not). Raises CatalogError when the code is unknown or EasyEDA has no footprint
    for it."""
    c = norm_code(code)
    if not c:
        raise CatalogError(f"{code!r} is not an LCSC part number (C followed by digits, e.g. C92489)")
    raw, hits = await asyncio.gather(easyeda(c), search(c, limit=5, fallback=False))
    card = next((h for h in hits if (h.get("lcsc") or "").upper() == c), None)
    if raw is None:
        raise CatalogError(f"{c} has no EasyEDA footprint" + (f" ({card['mpn']})" if card else "") + ": pick another part")
    head = ((raw.get("dataStr") or {}).get("head") or {}).get("c_para") or {}
    out = {
        **(card or {"lcsc": c, "mpn": head.get("Manufacturer Part") or raw.get("title"), "brand": head.get("Manufacturer"), "package": head.get("package"),
                    "category": next(iter(raw.get("tags") or []), None), "family": None, "description": raw.get("description") or "",
                    "stock": int(((raw.get("lcsc") or {}).get("stock")) or 0), "basic": head.get("JLCPCB Part Class") == "Basic Part",
                    "preferred": False, "prices": [{"qty": 1, "usd": float((raw.get("lcsc") or {}).get("price") or 0)}], "datasheet": None,
                    "image": None, "url": (raw.get("lcsc") or {}).get("url"), "attrs": {}}),
        "lcsc": c,
        "footprint_name": head.get("package"),
    }
    kind = kind_of(out)
    pins, note = card_pins(raw, out, kind)
    pads, tht = smd_of(raw)
    out.update({
        "pins": pins,
        "size_mm": size_of(raw),
        "height_mm": height_of(raw, out.get("category") or "", out.get("attrs")),
        "pads": pads,
        "tht": tht,
        "kind_hint": kind,
        "current_ma": current_of(out, kind),
        "pin_note": note,
    })
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
            hits = await search(FIXED[kind], limit=3, fallback=False)
            return next((h for h in hits if h["lcsc"] == FIXED[kind]), None)
        if kind == "led":
            series = LED_SERIES.get((color or "green").lower(), "KT-0603G")
            hits = await search(series, limit=6, fallback=False)
            hit = next((h for h in hits if (h.get("mpn") or "").upper() == series), None)
            return hit or next((h for h in hits if h["stock"] > 0), None)
        if kind in ("resistor", "capacitor"):
            pkg = PACKAGE.get(package, "0603")
            hits = await search(value_keyword(kind, value, pkg), limit=8, basic=True, fallback=False)
            fit = [h for h in hits if (h.get("package") or "") == pkg and h["stock"] > 0]
            return fit[0] if fit else None
    except CatalogError as e:
        log.warning("resolve_basic %s %s: %s", kind, value, e)
    return None
