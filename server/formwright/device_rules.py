"""Electrical design rules of a device graph (fw.device/1): the mistakes a netlist shows before any board exists, beyond
what device.lint() says (unconnected parts, LED resistors, decoupling, USB-C CC). The devices of 2026-11-03 passed lint and
the reviewer and were still broken: a LiPo on the XIAO's 5 V pin, an S8050 turned round, a 30 mA buzzer on a bare GPIO,
a buzzer whose two terminals were one reference, a WS2812 on 5 V fed 3.3 V data; later a flyback diode with its cathode on
no net, and an LDR whose rising reading the firmware took for dark (sensor_divider states the direction, data carries it
for the reviewer). check() names each finding with what to
change, for the designer: {code, ref, msg, severity: 'error'|'warning', hint}. An error means the device does not work or
gets damaged; a warning is the designer's to weigh. Errors come first.

Pin roles come from the part card: labels B/E/C, G/S/D (catalog.info), else its kind_hint / category / description, else
the usual SOT-23 pinout, said as an assumption; a chip LED's A/K from its labels (catalog.roles_of reads a numbered
symbol's diode triangle), a buzzer's supply terminal from the rail it sits on. GPIO numbers and strapping pins come from device.MODULES ('gpio',
'strapping'), else MCU_PINS below; accessories (ready-made modules on wires) from accessories.ACCESSORIES when present.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

from . import catalog, device

log = logging.getLogger(__name__)

ERROR, WARNING = "error", "warning"
GPIO_MAX_MA = 20.0   # what an ESP32 / RP2040 pin should source or sink for long; more droops it and heats the chip
VF_MIN = 1.9         # the lowest LED forward voltage (red): the worst case for its current
# what an LED of a colour drops at its low end (InGaN white / blue / true green, AlGaInP red / yellow / orange); a plain
# 'green' may be either, so it keeps VF_MIN
LED_VF = [(re.compile(r"\b(white|blue|true[ -]?green|pure[ -]?green|emerald|cyan|uv|ultra-?violet|violet|purple|pink)\b|\d{4}K\b", re.I), 2.8),
          (re.compile(r"\b(red|yellow|orange|amber)\b", re.I), 1.9)]
# until device.MODULES carries 'gpio' and 'strapping' (contract C5): XIAO pin -> GPIO, and the GPIOs read at reset
_C3 = {"D0": 2, "D1": 3, "D2": 4, "D3": 5, "SDA": 6, "SCL": 7, "TX": 21, "RX": 20, "SCK": 8, "MISO": 9, "MOSI": 10}
_S3 = {"D0": 1, "D1": 2, "D2": 3, "D3": 4, "SDA": 5, "SCL": 6, "TX": 43, "RX": 44, "SCK": 7, "MISO": 8, "MOSI": 9}
MCU_PINS: dict[str, tuple[dict[str, int], list[int]]] = {"ESP32-C3": (_C3, [2, 8, 9]), "ESP32-S3": (_S3, [0, 3, 45, 46])}
MODULE_RAIL = {"V3V3": 3.3, "V5": 5.0, "VBUS": 5.0, "VSYS": 5.0, "ADC_VREF": 3.3}
MODULE_GND = re.compile(r"^A?GND\d*$")
RAIL_V = [(re.compile(r"^(V3V3|V3V|V33|V3_3|P3V3|VCC3V3|VDD3V3|VCC_3V3)$", re.I), 3.3),
          (re.compile(r"^(V5|V5V|VBUS|VSYS|VUSB|USB5V|P5V|VCC5V|VCC_5V)$", re.I), 5.0),
          (re.compile(r"^(VBAT|VBATT|BAT|BATT|VLIPO|VCELL)$", re.I), 4.2),
          (re.compile(r"^(V1V8|V18)$", re.I), 1.8), (re.compile(r"^V9V?$", re.I), 9.0), (re.compile(r"^V12V?$", re.I), 12.0),
          (re.compile(r"^V24V?$", re.I), 24.0), (re.compile(r"^V36V?$", re.I), 36.0), (re.compile(r"^V48V?$", re.I), 48.0)]
BATTERY = re.compile(r"bat|lipo|li-?ion|li-?po|18650|lifepo|аккум|батар", re.I)
BAT_PLUS = re.compile(r"^(\+|P|VBAT|BAT|BATP|BAT_P|BAT\+|V\+|VP|VCC|VIN|PLUS|RED)$", re.I)
SUPPLY_PIN = re.compile(r"^(VDD|VCC|VIN|VDDIO|AVDD|DVDD|VDDA|VS|VP|V\+|VBAT|PWR|POWER|V5|V5V|V3V3|5V|3V3|\+)$", re.I)
NC = re.compile(r"^(NC|N_C|DNC)(_?\d+)?$", re.I)
I2C_PIN = re.compile(r"^(I2C_?)?(SDA|SCL|SDX|SCX)\d*$", re.I)
I2C_ALT = re.compile(r"^(SDI|SCK|SCLK|SDATA|SDIO)$", re.I)   # a bus pin's other names, I2C when on the module's SDA/SCL
I2C_NET = re.compile(r"^(I2C\d?_?)?(SDA|SCL)\d*$", re.I)
DIN = re.compile(r"^(DIN|DI|IN|SDI|DATA_?IN|D_IN)$", re.I)
VDD = re.compile(r"^(VDD|VCC|V\+|VP|VDD5V|V5|5V|VLED)$", re.I)
ADDRESSABLE = re.compile(r"WS281[12]|SK6812|SK6805|APA10[24]|SK9822|Built-in IC|addressable", re.I)
VRANGE = re.compile(r"(\d+(?:\.\d+)?)\s*V\s*[~～\-–]\s*(\d+(?:\.\d+)?)\s*V")
ANODE, CATHODE = re.compile(r"^(A|ANODE)\d?$", re.I), re.compile(r"^(K|CATHODE)\d?$", re.I)
# a resistance that follows light or temperature, read as one leg of a divider: which way the reading moves is what the
# firmware's thresholds must agree with (a night light that took a high reading for dark never turned on)
DIVIDER = re.compile(r"Photo ?resist|\bLDR\b|\bCdS\b|GL55\d\d|Thermistor|\bNTC\b|\bPTC\b", re.I)
THERMAL = re.compile(r"Thermistor|\bNTC\b|\bPTC\b", re.I)
# what feeds a rail: a regulator's or charger's output pin, a header pin that brings power in
REGULATOR = re.compile(r"LDO|Regulator|DC-?DC|\bBuck\b|\bBoost\b|Charger|Charge Management|Battery Management|PMIC|Power Management", re.I)
REG_OUT = re.compile(r"^(VOUT\d*|VO|OUT\d*|OUTPUT|SW|VSYS)$", re.I)
SOURCE_HEADER = re.compile(r"^(VIN|PWR|POWER|BAT|VBAT|BATP|BAT_P|P|EXT\w*|VEXT)$", re.I)
NOT_RAIL = re.compile(r"SENSE|SNS|ADC|MEAS|DIV|_FB$|REF", re.I)  # a divider tap named like a rail (VBAT_SENSE)
PROTECT = re.compile(r"\bTVS\b|Zener|\bESD\b", re.I)
SOT23 = re.compile(r"SOT-?23(?!-?[4-9])|SOT-?323|SC-?70|SOT-?416|SC-?59|TO-?236", re.I)
BUZZERS = ("buzzer", "buzzer_active", "buzzer_passive", "speaker")
LOADS = (*BUZZERS, "motor", "relay")
COILS = ("motor", "relay")
SWITCHES = ("npn", "pnp", "nmos", "pmos", "transistor")
MISUSE = ("led", "button", "rgb_led", *LOADS, *SWITCHES)  # what an I2C pin must not drive
TWO = {"resistor": ("1", "2"), "capacitor": ("1", "2"), "led": ("A", "K"), "diode": ("A", "K"), "button": ("A", "B"), "jst": ("P1", "P2")}
ROLE_RE = {r: re.compile(rf"^({r}|{w})\d*$", re.I) for r, w in
           (("B", "BASE"), ("E", "EMITTER"), ("C", "COLLECTOR"), ("G", "GATE"), ("S", "SOURCE"), ("D", "DRAIN"))}
# the standard 3-pin small-signal pinout (JEDEC TO-236): what a card with unnamed pins most likely is, said as an assumption
SOT23_ROLES = {"npn": ("B", "E", "C"), "pnp": ("B", "E", "C"), "nmos": ("G", "S", "D"), "pmos": ("G", "S", "D")}
KIND_WORD = {"npn": "NPN", "pnp": "PNP", "nmos": "N-MOSFET", "pmos": "P-MOSFET", "transistor": "transistor", "buzzer": "buzzer",
             "buzzer_active": "active buzzer", "buzzer_passive": "passive buzzer", "speaker": "speaker", "motor": "motor",
             "relay": "relay", "rgb_led": "addressable LED", "led": "LED", "diode": "diode"}


def _accessories() -> dict[str, dict[str, Any]]:
    """The accessory library (contract C1d) once it exists: key -> {name, pins, connect, supply, current_ma, ...}."""
    try:
        from . import accessories  # type: ignore[attr-defined]
    except ImportError:
        return {}
    return getattr(accessories, "ACCESSORIES", None) or {}


def _c_para(part: dict[str, Any]) -> dict[str, Any]:
    return (((part.get("raw") or {}).get("dataStr") or {}).get("head") or {}).get("c_para") or {}


def _classify(t: str) -> str | None:
    """A part's kind from the catalogue's words (category, description, part number). Drivers and controllers (motor
    drivers, LED drivers, gate drivers) are ICs, not the loads they drive; WS2811-style LED drivers are addressable LEDs."""
    if re.search(r"Photo|Opto", t, re.I):
        return "sensor"
    if ADDRESSABLE.search(t):
        return "rgb_led"
    if re.search(r"\bDrivers?\b|\bControllers?\b", t, re.I):
        return "ic"
    if re.search(r"MOSFET", t, re.I):
        n, p = re.search(r"N-?Channel|NMOS", t, re.I), re.search(r"P-?Channel|PMOS", t, re.I)
        return "nmos" if n and not p else "pmos" if p and not n else "transistor"
    if re.search(r"Bipolar|BJT|Transistor", t, re.I) or re.search(r"\b[NP]PN\b", t):
        n, p = re.search(r"\bNPN\b", t, re.I), re.search(r"\bPNP\b", t, re.I)
        return "npn" if n and not p else "pnp" if p and not n else "transistor"
    if re.search(r"Buzzer", t, re.I):
        return ("buzzer_active" if re.search(r"\bActive\b|Built-in Driv|self-?driv", t, re.I)
                else "buzzer_passive" if re.search(r"Passive|Externally Driven", t, re.I) else "buzzer")
    if re.search(r"Speaker", t, re.I):
        return "speaker"
    if re.search(r"Relay", t, re.I):
        return "relay"
    if re.search(r"\bMotors?\b", t, re.I):
        return "motor"
    if re.search(r"\bLEDs?\b|Light Emitting", t, re.I):
        return "led"
    if re.search(r"Diode|Schottky|Rectifier|Zener|\bTVS\b", t, re.I):
        return "diode"
    return None


def _kind(node: dict[str, Any], part: dict[str, Any]) -> str:
    """What a node is for the rules: its kind, and for a chip the catalogue's kind_hint, else what its card says, else its
    symbol's designator prefix (Q?, BUZZER?), else the designer's label."""
    k = node.get("kind") or ""
    if k != "chip":
        return k
    hint = str(part.get("kind_hint") or "").strip().lower()
    if hint and hint not in ("ic", "other", "unknown"):
        return hint
    got = _classify(" ".join(str(part.get(f) or "") for f in ("category", "description", "mpn")))
    if got:
        return got
    pre = str(_c_para(part).get("pre") or "").rstrip("?").upper()
    by_pre = {"Q": "transistor", "BUZ": "buzzer", "BUZZER": "buzzer", "LS": "speaker", "SP": "speaker", "LED": "led", "D": "diode", "K": "relay"}
    return by_pre.get(pre) or _classify(str(node.get("label") or "")) or hint or "ic"


def _ohms(v: Any) -> float | None:
    """'4.7k' / '4k7' / '330R' / '47' / '1M' -> ohms."""
    s = re.sub(r"(?i)\s|ohms?|Ω", "", str(v or ""))
    m = re.match(r"^(\d+(?:\.\d+)?)([RrKkMm]?)(\d*)$", s)
    if not m:
        return None
    mult = {"": 1.0, "r": 1.0, "k": 1e3, "m": 1e6}[m[2].lower()]
    num = float(f"{m[1]}.{m[3]}" if m[3] and "." not in m[1] else m[1])
    return num * mult


def _f(sev: str, code: str, ref: str, msg: str, hint: str, lint: str | None = None) -> dict[str, Any]:
    out = {"code": code, "ref": ref, "msg": msg, "severity": sev, "hint": hint}
    if lint:
        out["_lint"] = lint  # the lint code that already says this: dropped when lint does
    return out


class _G:
    """The document as the rules read it: every wired physical pin (node id, pin key) and its net; what each part is."""

    def __init__(self, doc: dict[str, Any], parts: dict[str, dict[str, Any]]):
        self.doc, self.parts, self.lib = doc, parts, _accessories()
        self.nodes = {n["id"]: n for n in doc.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
        self.nets = [n for n in doc.get("nets") or [] if isinstance(n, dict)]
        self.kind = {nid: _kind(n, self.part(nid)) for nid, n in self.nodes.items()}
        refs: dict[str, list[str]] = {}
        for net in self.nets:
            for ref in net.get("pins") or []:
                nid, _, pin = str(ref).partition(".")
                refs.setdefault(nid, []).append(pin)
        self.pins = {nid: self._pins(nid, refs.get(nid, [])) for nid in self.nodes}
        self.at: dict[tuple[str, str], int] = {}
        self.on: list[list[tuple[str, str]]] = [[] for _ in self.nets]
        for i, net in enumerate(self.nets):
            for ref in net.get("pins") or []:
                nid, _, pin = str(ref).partition(".")
                if nid in self.nodes:
                    for key in self._keys(nid, pin):
                        if (nid, key) not in self.at:
                            self.at[(nid, key)] = i
                            self.on[i].append((nid, key))
        self.modules = [nid for nid, n in self.nodes.items() if n.get("kind") == "module" and n.get("module") in device.MODULES]
        self._i2c: bool | None = None
        self._src: set[int] | None = None

    # ---- parts and pins
    def part(self, nid: str) -> dict[str, Any]:
        return self.parts.get(nid) or {}

    def acc(self, nid: str) -> dict[str, Any]:
        return self.lib.get(str(self.nodes[nid].get("accessory") or "")) or {}

    def _pins(self, nid: str, used: list[str]) -> list[dict[str, str]]:
        n, k = self.nodes[nid], self.nodes[nid].get("kind")
        if k == "chip":
            pins = [{"key": str(p.get("num")), "label": str(p.get("label") or p.get("name") or p.get("num")), "name": str(p.get("name") or "")}
                    for p in self.part(nid).get("pins") or [] if isinstance(p, dict)]
            if pins:
                return pins
            names = list(dict.fromkeys(used))  # no card: the pins the nets name
        elif k == "module":
            names = list((device.MODULES.get(n.get("module")) or {}).get("pins") or [])
        elif k == "header":
            names = list(n.get("pins") or [])
        elif k == "accessory":
            raw = [str(p) for p in self.acc(nid).get("pins") or []]
            return [{"key": device.ident(p), "label": device.ident(p), "name": p} for p in raw] or [{"key": p, "label": p, "name": p} for p in dict.fromkeys(used)]
        else:
            names = list((device.PRIMS.get(k) or {}).get("pins") or [])
        return [{"key": p, "label": p, "name": p} for p in names]

    def _keys(self, nid: str, pin: str) -> list[str]:
        """The physical pins one reference stands for: a chip's 'GND' is every pin labelled GND or GND_7 (as the compiler
        wires it), a Pico's 'GND' all eight. A chip pin written as 'P2' still finds pin 2 after the card renamed it."""
        pins, up, n = self.pins[nid], pin.upper(), self.nodes[nid]
        if n.get("kind") == "module":
            spec = device.MODULES.get(n.get("module")) or {}
            group = (spec.get("groups") or {}).get(pin)
            if group:
                return list(group)
            up = {a.upper(): t for a, t in (spec.get("aliases") or {}).items()}.get(up, up).upper()
        tests = [lambda p: p["label"].upper() == up, lambda p: bool(p["name"]) and catalog.safe_label(p["name"]).upper() == up,
                 lambda p: f"P{p['key']}".upper() == up or p["key"].upper() == up]
        if n.get("kind") == "chip":
            tests.insert(0, lambda p: catalog.base_label(p["label"]).upper() == up)
        for test in tests:
            hit = [p["key"] for p in pins if test(p)]
            if hit:
                return hit
        return [pin]

    def net(self, nid: str, key: str) -> int | None:
        return self.at.get((nid, key))

    def net_of(self, nid: str, rx: re.Pattern[str]) -> int | None:
        """The net of the first wired pin whose label or name matches."""
        return next((i for p in self.pins[nid] if (rx.match(p["label"]) or rx.match(p["name"])) and (i := self.net(nid, p["key"])) is not None), None)

    def alone(self, nid: str, key: str) -> bool:
        """A pin on no net, or on one with nothing but the part's own pins: it connects to nothing."""
        i = self.net(nid, key)
        return i is None or all(x == nid for x, _ in self.on[i])

    def ends(self, d: str) -> tuple[int | None, int | None] | None:
        """(anode net, cathode net) of a diode: the primitive, or a chip diode by its A / K pins; None for anything else."""
        if self.nodes[d].get("kind") == "diode":
            return self.net(d, "A"), self.net(d, "K")
        if self.nodes[d].get("kind") == "chip" and self.kind[d] == "diode" and any(ANODE.match(p["label"]) for p in self.pins[d]):
            return self.net_of(d, ANODE), self.net_of(d, CATHODE)
        return None

    def wired(self, nid: str) -> list[tuple[dict[str, str], int]]:
        return [(p, self.at[(nid, p["key"])]) for p in self.pins[nid] if (nid, p["key"]) in self.at]

    def terminals(self, nid: str) -> list[dict[str, str]]:
        return [p for p in self.pins[nid] if not NC.match(p["name"] or p["label"])]

    def raw(self, nid: str, key: str) -> str:
        """The pin's own label (a chip's pin key is its number)."""
        return next((p["label"] for p in self.pins[nid] if p["key"] == key), key)

    def label(self, nid: str, key: str) -> str:
        p = next((p for p in self.pins[nid] if p["key"] == key), None)
        if not p:
            return key
        lb = catalog.base_label(p["label"]) if self.nodes[nid].get("kind") == "chip" else p["label"]
        return lb + (f" ({p['name']})" if p["name"] and p["name"] not in (lb, p["label"]) and not p["name"].isdigit() else "")

    def other(self, nid: str, key: str) -> int | None:
        pair = TWO.get(self.nodes[nid].get("kind") or "")
        if not pair or key not in pair:
            return None
        return self.net(nid, pair[1] if key == pair[0] else pair[0])

    def what(self, nid: str) -> str:
        n, k, part = self.nodes[nid], self.nodes[nid].get("kind"), self.part(nid)
        if k == "chip":
            base = str(part.get("mpn") or n.get("mpn") or n.get("lcsc") or "chip")
            word = KIND_WORD.get(self.kind[nid])
            return f"{base}, {word}" if word else base
        if k == "module":
            return device.MODULES[n["module"]]["name"] if n.get("module") in device.MODULES else "module"
        if k == "accessory":
            return str(self.acc(nid).get("name") or n.get("accessory") or "accessory")
        return str(n.get("label") or k)

    def text(self, nid: str) -> str:
        part = self.part(nid)
        return " ".join(str(part.get(f) or "") for f in ("category", "description", "mpn"))

    def tech(self, nid: str) -> str | None:
        t = self.text(nid)
        return "piezo" if re.search(r"Piezo", t, re.I) else "magnetic" if re.search(r"Magnetic", t, re.I) else None

    def current_ma(self, nid: str) -> float | None:
        if self.nodes[nid].get("kind") == "accessory":
            v = self.acc(nid).get("current_ma")
        else:
            part = self.part(nid)
            v = part.get("current_ma")
            if v is None:
                found = re.findall(r"(\d+(?:\.\d+)?)\s*mA(?!h)", str(part.get("description") or ""))
                v = max(map(float, found)) if found else None
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def roles(self, nid: str) -> tuple[dict[str, list[str]] | None, bool]:
        """{role: pin keys} of a transistor and whether it is the assumed SOT-23 pinout, or (None, False) when unknown;
        ({}, False) for a dual part (G1/G2...), whose channels are not checked here."""
        want = SOT23_ROLES.get(self.kind[nid])
        if not want:
            return None, False
        found: dict[str, list[str]] = {}
        units: set[str] = set()
        for p in self.pins[nid]:
            for t in (catalog.base_label(p["label"]), p["name"]):
                r = next((r for r in want if ROLE_RE[r].match(t or "")), None)
                if r:
                    found.setdefault(r, []).append(p["key"])
                    units.add(re.sub(r"^\D+", "", t))
                    break
        if all(r in found for r in want):
            return (found if len(units) <= 1 else {}), False
        part = self.part(nid)
        pkg = " ".join(str(x or "") for x in (part.get("package"), part.get("footprint_name"), _c_para(part).get("package")))
        if [p["key"] for p in self.pins[nid]] == ["1", "2", "3"] and SOT23.search(pkg):
            return {r: [str(i + 1)] for i, r in enumerate(want)}, True
        return None, False

    def addressable(self, nid: str) -> bool:
        if self.nodes[nid].get("kind") != "chip" or not any(DIN.match(p["label"]) or DIN.match(p["name"]) for p in self.pins[nid]):
            return False
        return self.kind[nid] == "rgb_led" or bool(ADDRESSABLE.search(self.text(nid)))

    # ---- nets
    def name(self, i: int) -> str:
        return self.nets[i].get("name") or "/".join(f"{a}.{self.label(a, b)}" for a, b in self.on[i][:3])

    def gnd(self, i: int) -> bool:
        return bool(device.GROUND.match(self.nets[i].get("name") or "")) or any(
            nid in self.modules and MODULE_GND.match(p) for nid, p in self.on[i])

    def volt(self, i: int) -> float | None:
        """The voltage of a supply net: a module's rail on it, else a battery's + on it (a full LiPo), else its name."""
        vs = [MODULE_RAIL[p] for nid, p in self.on[i] if nid in self.modules and p in MODULE_RAIL]
        if vs:
            return max(vs)
        if any(self.battery_plus(nid) == key for nid, key in self.on[i]):
            return 4.2
        name = self.nets[i].get("name") or ""
        return next((v for rx, v in RAIL_V if rx.match(name)), None)

    def power(self, i: int) -> bool:
        return self.gnd(i) or self.volt(i) is not None or bool(device.POWER_NET.match(self.nets[i].get("name") or ""))

    def rail(self, i: int) -> bool:
        return self.power(i) and not self.gnd(i)

    # ---- modules
    def mod(self, m: str) -> tuple[dict[str, int], list[int], dict[str, Any]]:
        spec = device.MODULES.get(self.nodes[m].get("module")) or {}
        fb_gpio, fb_strap = MCU_PINS.get(str(spec.get("mcu")), ({}, []))
        gpio = spec.get("gpio") or fb_gpio or {p: int(p[2:]) for p in spec.get("pins") or [] if re.match(r"^GP\d+$", p)}
        strap = spec.get("strapping") if spec.get("strapping") is not None else fb_strap
        return gpio, list(strap or []), spec

    def gpios(self, i: int | None) -> list[tuple[str, str]]:
        if i is None:
            return []
        return [(m, p) for m, p in self.on[i] if m in self.modules and p in self.mod(m)[0]]

    def driven(self, i: int | None) -> list[tuple[str, str]]:
        """Module GPIOs on a net directly or through one series resistor."""
        out = self.gpios(i)
        for r, key in self.on[i] if i is not None else []:
            if self.nodes[r].get("kind") == "resistor":
                j = self.other(r, key)
                if j is not None and j != i and not self.power(j):
                    out += self.gpios(j)
        return out

    def pin_txt(self, m: str, pin: str) -> str:
        gpio, _, spec = self.mod(m)
        alias = next((a for a, t in (spec.get("aliases") or {}).items() if t == pin and re.match(r"^D\d+$", a)), None)
        bits = [b for b in (alias, f"GPIO{gpio[pin]}" if pin in gpio and not pin.startswith("GP") else None) if b]
        return f"{m}.{pin}" + (f" ({', '.join(bits)})" if bits else "")

    def free(self, m: str) -> str:
        """Unused GPIOs of a module that are not read at boot and not the I2C pins (when a bus is in use)."""
        gpio, strap, spec = self.mod(m)
        alias = {t: a for a, t in (spec.get("aliases") or {}).items() if re.match(r"^D\d+$", a)}
        out = [f"{alias[p]}/{p}" if p in alias else p for p, n in gpio.items()
               if (m, p) not in self.at and n not in strap and not (p in ("SDA", "SCL") and self.i2c_present())]
        return ", ".join(out[:8]) or "none is free: free one up"

    def i2c_present(self) -> bool:
        """Is an I2C device on the board: a chip, header or accessory pin named SDA/SCL, or a bus pin (SDI, SCK) on the
        module's SDA/SCL net."""
        if self._i2c is None:
            self._i2c = False
            for i, members in enumerate(self.on):
                bus = any(m in self.modules and p in ("SDA", "SCL") for m, p in members)
                for nid, key in members:
                    if self.nodes[nid].get("kind") in ("chip", "header", "accessory") and self.kind[nid] not in MISUSE:
                        lb = catalog.base_label(self.raw(nid, key))
                        if I2C_PIN.match(lb) or (bus and I2C_ALT.match(lb)):
                            self._i2c = True
        return self._i2c

    def i2c_net(self, i: int) -> bool:
        return bool(I2C_NET.match(self.nets[i].get("name") or "")) or any(
            (nid in self.modules and p in ("SDA", "SCL")) or (nid not in self.modules and I2C_PIN.match(catalog.base_label(self.raw(nid, p))))
            for nid, p in self.on[i])

    def beyond(self, i: int) -> list[tuple[str, str, str | None]]:
        """(part, pin, the series resistor it is reached through) for the parts on a net and, through one resistor that is
        not a pull-up or pull-down, the parts beyond it. Modules are left out."""
        out: list[tuple[str, str, str | None]] = []
        for nid, key in self.on[i]:
            if nid in self.modules:
                continue
            if self.nodes[nid].get("kind") == "resistor":
                j = self.other(nid, key)
                if j is not None and j != i and not self.power(j):
                    out += [(x, k, nid) for x, k in self.on[j] if x != nid and x not in self.modules]
            else:
                out.append((nid, key, None))
        return out

    def battery_plus(self, nid: str) -> str | None:
        """The + pin of a battery: a JST, header or accessory that is one by its id, label or library entry."""
        n = self.nodes.get(nid) or {}
        k, words = n.get("kind"), f"{nid} {n.get('label') or ''}"
        if k == "jst":
            i = self.net(nid, "P1")
            named = i is not None and re.match(r"^V?BATT?(_|$)", self.nets[i].get("name") or "", re.I)
            return "P1" if BATTERY.search(words) or named else None
        if k == "header" and BATTERY.search(words):
            return next((p["key"] for p in self.pins[nid] if BAT_PLUS.match(p["key"])), None)
        if k == "accessory":
            a = self.acc(nid)
            if a.get("kind") == "battery" or a.get("connect") == "module_bat" or BATTERY.search(f"{n.get('accessory') or ''} {a.get('name') or ''}"):
                return next((p["key"] for p in self.pins[nid] if BAT_PLUS.match(p["key"]) or BAT_PLUS.match(p["name"])), None)
        return None

    def role(self, nid: str, key: str) -> str | None:
        """B/E/C or G/S/D of a transistor's pin, when its pinout is known."""
        roles, _ = self.roles(nid) if self.kind[nid] in SWITCHES else (None, False)
        return next((r for r, keys in (roles or {}).items() if key in keys), None)

    def through(self, nid: str, near: str, far: str) -> tuple[int | None, int | None] | None:
        """(net of a transistor's `near` role, net of its `far` role), or None when its pinout is unknown."""
        roles, _ = self.roles(nid)
        if not roles or near not in roles or far not in roles:
            return None
        nets = {r: next((i for k in roles[r] if (i := self.net(nid, k)) is not None), None) for r in (near, far)}
        return nets[near], nets[far]

    def source_pin(self, nid: str, key: str) -> bool:
        """A pin that feeds the net it is on: a module's power pin or GPIO, USB-C VBUS, a JST's or a battery's +, a header
        pin that brings power in, a regulator's or charger's output."""
        k = self.nodes[nid].get("kind")
        if nid in self.modules:
            return key in ("V3V3", "V5", "VBUS", "VSYS") or key in self.mod(nid)[0]
        if k == "usb_c":
            return key == "VBUS"
        if k == "jst":
            return key == "P1"
        if k == "header":
            return bool(SOURCE_HEADER.match(key))
        if k == "accessory":
            return self.battery_plus(nid) == key
        if k == "chip" and (self.kind[nid] in ("regulator", "charger", "ldo", "dcdc", "pmic") or REGULATOR.search(self.text(nid))):
            p = next((p for p in self.pins[nid] if p["key"] == key), None)
            return bool(p and (REG_OUT.match(catalog.base_label(p["label"])) or REG_OUT.match(p["name"])
                               or (self.kind[nid] == "charger" and re.match(r"^(BAT|VBAT)$", p["label"], re.I))))
        return False

    def sourced(self) -> set[int]:
        """The nets something feeds: those with a source pin, then on through a diode (A to K) and a high-side switch
        (P-MOSFET S to D, PNP E to C) until nothing changes."""
        if self._src is None:
            src = {i for i, members in enumerate(self.on) if any(self.source_pin(x, k) for x, k in members)}
            links = [e for d in self.nodes if (e := self.ends(d))]
            links += [t for d in self.nodes if self.kind[d] in ("pmos", "pnp")
                      and (t := self.through(d, *(("S", "D") if self.kind[d] == "pmos" else ("E", "C")))) is not None]
            grew = True
            while grew:
                grew = False
                for a, b in links:
                    if a in src and b is not None and b not in src:
                        src.add(b)
                        grew = True
            self._src = src
        return self._src

    def supply_net(self, i: int) -> bool:
        """A named supply rail (device.is_supply when the compiler has it), not ground nor a divider tap named like one."""
        net, name = self.nets[i], self.nets[i].get("name") or ""
        if not name or self.gnd(i) or NOT_RAIL.search(name):
            return False
        test = getattr(device, "is_supply", None)
        try:
            return bool(test(net, self.nodes, self.parts)) if test else bool(device.POWER_NET.match(name) or self.volt(i) is not None)
        except Exception:  # noqa: BLE001 - a net it cannot read is no rail to check
            return False

    def upstream(self, i: int) -> tuple[str, set[int]]:
        """Where a load's feed side leads, and the nets on the way: 'fed' (a source), 'rail' (a named rail nothing feeds:
        supply_no_source's) or 'none'. It goes through resistors, buttons, LEDs and diodes (K to A) and high-side
        switches (P-MOSFET D to S, PNP C to E); never through ground or a low-side switch, which lead nowhere."""
        todo, seen, found = [i], {i}, "none"
        while todo:
            j = todo.pop()
            if j in self.sourced():
                return "fed", seen
            if self.supply_net(j):
                found = "rail"
                continue
            if self.gnd(j):
                continue
            for x, key in self.on[j]:
                k, kd = self.nodes[x].get("kind"), self.kind[x]
                nxt: int | None = None
                if k in ("resistor", "button"):
                    nxt = self.other(x, key)
                elif k in ("led", "diode") and key == "K":
                    nxt = self.net(x, "A")
                elif kd in ("pmos", "pnp") and self.role(x, key) == ("D" if kd == "pmos" else "C"):
                    t = self.through(x, *(("S", "D") if kd == "pmos" else ("E", "C")))
                    nxt = t[0] if t else None
                if nxt is not None and nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return found, seen

    def desc(self, nid: str, key: str) -> str:
        """A part as something on a pin's net: 'SW1 (button to GND)', 'Q1 base (S8050, NPN)', 'J1.AO (Soil sensor)'."""
        k, kd = self.nodes[nid].get("kind"), self.kind[nid]
        to_gnd = (j := self.other(nid, key)) is not None and self.gnd(j)
        if k in ("button", "capacitor", "led", "diode"):
            return f"{nid} ({'LED' if k == 'led' else k}{' to GND' if to_gnd else ''})"
        if kd in SWITCHES:
            word = {"B": "base", "G": "gate", "E": "emitter", "S": "source", "C": "collector", "D": "drain"}.get(self.role(nid, key) or "", "pin")
            return f"{nid} {word} ({self.what(nid)})"
        if k in ("header", "accessory", "chip"):
            return f"{nid}.{self.label(nid, key)} ({self.what(nid)})"
        return f"{nid} ({self.what(nid)})"


# ------------------------------------------------------------------ the rules
def _short_part(g: _G) -> list[dict[str, Any]]:
    out = []
    for nid, n in g.nodes.items():
        k = n.get("kind")
        if k in TWO:
            a, b = (g.net(nid, p) for p in TWO[k])
            if a is not None and a == b:
                out.append(_f(ERROR, "short_part", nid, f"{nid} ({k}) has both pins ({' and '.join(TWO[k])}) on net {g.name(a)}: it is shorted out and does nothing",
                              f"Put {nid}.{TWO[k][0]} and {nid}.{TWO[k][1]} on two different nets, or remove {nid}."))
        elif k in ("chip", "accessory"):
            wired = g.wired(nid)
            names = {(p["name"] or p["label"]).upper() for p, _ in wired if not NC.match(p["name"] or p["label"])}
            nets = {i for _, i in wired}
            if len(wired) >= 2 and len(nets) == 1 and len(names) >= 2:
                i = nets.pop()
                out.append(_f(ERROR, "short_part", nid, f"every wired pin of {nid} ({g.what(nid)}: {', '.join(sorted(names))}) is on net {g.name(i)}: the part is shorted out",
                              f"Wire each of {nid}'s pins to the net it belongs on (part_info lists them); a part needs at least two different nets."))
    return out


def _battery_raw(g: _G) -> list[dict[str, Any]]:
    out = []
    bat_key = next((k for k, a in g.lib.items() if a.get("connect") == "module_bat"), None)
    for nid in g.nodes:
        plus = g.battery_plus(nid)
        i = g.net(nid, plus) if plus else None
        if i is None:
            continue
        for m, pin in g.on[i]:
            if m not in g.modules or pin not in ("V5", "VBUS", "VSYS", "V3V3"):
                continue
            _, _, spec = g.mod(m)
            why = ("with USB plugged in, the module's 5 V is pushed straight into the cell (no charge control, no protection: a LiPo "
                   "swells or burns) and the cell back-feeds the USB port" if pin != "V3V3" else
                   "a full cell (4.2 V) on the 3.3 V rail over-volts the microcontroller, and the module's regulator back-feeds the cell")
            if str(spec.get("mcu", "")).startswith("ESP32"):
                hint = (f"The {spec.get('name', 'XIAO')} charges a LiPo itself: the cell goes on the BAT+ / BAT- pads under the module, "
                        f"never on {pin}. " + (f"Use the accessory '{bat_key}' (connect module_bat) instead of {nid}." if bat_key else
                                               f"Take {nid} off {pin} and say in the summary that the cell is soldered to the BAT pads."))
            elif spec.get("mcu") == "RP2040":
                hint = ("Charge the cell with a charger IC (TP4056 or MCP73831, with protection) and feed VSYS through a Schottky diode "
                        f"(the diode primitive: A on {nid}.{plus}, K on VSYS), as the Pico datasheet's battery example does; never put the cell on VBUS or 3V3.")
            else:
                hint = "Add a charger IC for the cell and a Schottky diode (A on the battery +, K on the 5 V input) so USB cannot push into it."
            out.append(_f(ERROR, "battery_raw", nid, f"{nid} ({g.what(nid)}) + is wired straight to {m}.{pin}: {why}", hint))
    return out


def _transistors(g: _G) -> list[dict[str, Any]]:
    out = []
    for nid, n in g.nodes.items():
        k = g.kind[nid]
        if n.get("kind") != "chip" or k not in SWITCHES or len(g.pins[nid]) > 8 or not g.wired(nid):
            continue
        roles, assumed = g.roles(nid)
        what = g.what(nid)
        if roles == {}:
            continue
        if roles is None:
            names = ", ".join(p["label"] for p in g.pins[nid])
            out.append(_f(WARNING, "pinout_unknown", nid, f"verify the pinout: {nid} ({what}) pins have no roles ({names}), so nothing can check "
                          f"that it is wired the right way round" + ("" if k != "transistor" else ", nor whether it is NPN or PNP"),
                          f"Read part_info / the datasheet for which pin is {'B, E, C' if k in ('npn', 'pnp', 'transistor') else 'G, S, D'}, wire it so "
                          f"and say the pinout in its label (e.g. 'NPN 1=B 2=E 3=C'); or pick a part whose pins are named."))
            continue
        net = {r: next((g.net(nid, key) for key in keys if g.net(nid, key) is not None), None) for r, keys in roles.items()}
        lb = {r: f"{nid}.{g.label(nid, keys[0])}" for r, keys in roles.items()}
        assume = (f" (assuming the usual SOT-23 pinout {', '.join(f'{lb[r]}={r}' for r in roles)}: its pins have no names; check the datasheet)"
                  if assumed else "")
        nm = {r: g.name(i) for r, i in net.items() if i is not None}
        if k in ("npn", "pnp"):
            e, c, b = net.get("E"), net.get("C"), net.get("B")
            bad = []
            if k == "npn":
                if e is not None and g.rail(e):
                    bad.append(f"emitter {lb['E']} on {nm['E']}")
                if c is not None and g.gnd(c):
                    bad.append(f"collector {lb['C']} on {nm['C']}")
                fix = (f"Low-side switch: {lb['E']} (emitter) to GND, {lb['C']} (collector) to the load's - terminal, the load's + to the "
                       f"supply, {lb['B']} (base) through 1k to the GPIO.")
            else:
                if e is not None and g.gnd(e):
                    bad.append(f"emitter {lb['E']} on {nm['E']}")
                if c is not None and g.rail(c) and not (e is not None and g.rail(e)):
                    bad.append(f"collector {lb['C']} on {nm['C']}")
                fix = (f"High-side switch: {lb['E']} (emitter) to the supply, {lb['C']} (collector) to the load's + terminal, the load's - "
                       f"to GND, {lb['B']} (base) through 1k to the GPIO (low = on).")
            if bad:
                out.append(_f(ERROR, "bjt_reversed", nid, f"{nid} ({what}) is wired the wrong way round: {' and '.join(bad)}{assume}; "
                              "as wired it cannot switch the load", fix))
            prebiased = re.search(r"Digital Transistor|Pre-?Biased|built-in resistor", g.text(nid), re.I)
            if b is not None and not prebiased:
                gp = g.gpios(b)
                if gp:
                    out.append(_f(ERROR, "bjt_base_resistor", nid, f"{nid}'s base {lb['B']} is wired straight to {g.pin_txt(*gp[0])}{assume}: "
                                  "nothing limits the base current, so the pin and the transistor overheat",
                                  f"Put a 1k resistor between {gp[0][0]}.{gp[0][1]} and {lb['B']}, each on its own net."))
                elif g.rail(b):
                    out.append(_f(ERROR, "bjt_base_resistor", nid, f"{nid}'s base {lb['B']} is tied straight to {nm['B']}: it is stuck on or off, "
                                  "and with no resistor the base burns", f"Drive {lb['B']} from a GPIO through 1k."))
            if k == "pnp" and e is not None and (g.volt(e) or 0) >= 4.5 and g.driven(b):
                out.append(_f(WARNING, "high_side_level", nid, f"{nid} ({what}) switches {nm['E']} ({g.volt(e):g} V) but its base is driven "
                              f"from a 3.3 V GPIO: the pin cannot pull the base up to {g.volt(e):g} V, so {nid} never turns off",
                              "Drive the PNP's base through a small NPN (open collector), or switch the load low-side with an NPN / N-MOSFET instead."))
        else:
            s, d, gt = net.get("S"), net.get("D"), net.get("G")
            if k == "nmos":
                if d is not None and g.gnd(d) and not (s is not None and g.gnd(s)):
                    out.append(_f(ERROR, "mosfet_reversed", nid, f"{nid} ({what}) has its drain {lb['D']} on {nm['D']}{assume}: the body diode "
                                  "conducts and the load is always on", f"Swap it: {lb['S']} (source) to GND, {lb['D']} (drain) to the load's - terminal."))
                elif s is not None and not g.gnd(s):
                    out.append(_f(WARNING, "mosfet_high_side", nid, f"{nid} ({what}) has its source {lb['S']} on {nm['S']}, not GND{assume}: as a "
                                  "high-side switch a 3.3 V gate cannot turn an N-MOSFET fully on (the gate must rise above the source)",
                                  f"Low-side switch: {lb['S']} to GND, {lb['D']} to the load's - terminal, the load's + to the supply, {lb['G']} "
                                  "to the GPIO with 100k to GND; for a high-side switch use a P-MOSFET."))
            elif s is not None and g.gnd(s):
                out.append(_f(ERROR, "mosfet_reversed", nid, f"{nid} ({what}) has its source {lb['S']} on {nm['S']}{assume}: a P-MOSFET switches "
                              "the high side", f"{lb['S']} (source) to the supply, {lb['D']} (drain) to the load's +, {lb['G']} pulled up to the "
                              "source (100k) and pulled low to turn on."))
            if gt is None:
                out.append(_f(ERROR, "mosfet_gate_floating", nid, f"{nid}'s gate {lb['G']} is not connected: the MOSFET switches at random",
                              f"Drive {lb['G']} from a GPIO and add 100k from {lb['G']} to {'GND' if k == 'nmos' else 'its source'}."))
            elif k == "nmos" and g.driven(gt):
                sides = [gt] + [g.other(r, key) for r, key in g.on[gt] if g.nodes[r].get("kind") == "resistor"]
                pulled = any(g.nodes[r].get("kind") == "resistor" and (j := g.other(r, key)) is not None and g.gnd(j)
                             for i in sides if i is not None for r, key in g.on[i])
                if not pulled:
                    out.append(_f(WARNING, "mosfet_gate_floating", nid, f"{nid}'s gate {lb['G']} has no pull-down: while the microcontroller "
                                  "boots its pins float, so the load can switch on by itself", f"Add a 100k resistor from {lb['G']} to GND."))
            if k == "pmos" and s is not None and (g.volt(s) or 0) >= 4.5 and g.driven(gt):
                out.append(_f(WARNING, "high_side_level", nid, f"{nid} ({what}) switches {nm['S']} ({g.volt(s):g} V) with its gate on a 3.3 V "
                              f"GPIO: the gate never rises to the source, so {nid} never turns off",
                              "Pull the gate up to the source (100k) and pull it low through a small NPN / N-MOSFET driven by the GPIO."))
    return out


def _gpio_overload(g: _G) -> list[dict[str, Any]]:
    out = []
    for nid, n in g.nodes.items():
        k, cur = g.kind[nid], g.current_ma(nid)
        if k in LOADS and n.get("kind") in ("chip", "accessory"):
            keys = [p["key"] for p in g.terminals(nid)]
        elif cur is not None and cur >= GPIO_MAX_MA and n.get("kind") in ("chip", "accessory") and k not in (*SWITCHES, "diode"):
            keys = [p["key"] for p in g.pins[nid] if SUPPLY_PIN.match(p["label"]) or SUPPLY_PIN.match(p["name"])]
        else:
            continue
        piezo = k in BUZZERS and g.tech(nid) == "piezo" and not (cur and cur >= GPIO_MAX_MA)
        if piezo and k == "buzzer_passive":
            continue  # a piezo disc is a small capacitor: a GPIO drives it with tone()
        hit = next((gp[0] for key in keys if (gp := g.gpios(g.net(nid, key)))), None)
        if not hit:
            continue
        coil = k in COILS or g.tech(nid) == "magnetic"
        amps = f", {cur:g} mA" if cur else ""
        fix = (f"Switch it low-side: an NPN (S8050: base through 1k from {hit[0]}.{hit[1]}, emitter to GND, collector to {nid}'s - terminal) or an "
               f"N-MOSFET (AO3400 / 2N7002: gate to {hit[0]}.{hit[1]} with 100k to GND, source to GND, drain to {nid}'s - terminal); {nid}'s + "
               "to V3V3 or V5 (its rated voltage)" + (", and a diode across it (A on the - terminal, K on +) for the coil's kick." if coil else "."))
        if piezo:
            out.append(_f(WARNING, "gpio_overload", nid, f"{nid} ({g.what(nid)}) is driven straight from {g.pin_txt(*hit)}: its card gives no current, "
                          "and an active buzzer rated above 3.3 V can take more than a GPIO's ~20 mA (and is quiet at 3.3 V)",
                          "Check its current in the datasheet; if it is over 20 mA or it should be loud: " + fix))
        else:
            out.append(_f(ERROR, "gpio_overload", nid, f"{nid} ({g.what(nid)}{amps}) is driven straight from {g.pin_txt(*hit)}: a GPIO gives about "
                          f"{GPIO_MAX_MA:g} mA at most, so the pin is overloaded and the {('load' if k not in BUZZERS else 'sound')} weak or dead", fix))
    return out


def _buzzer_unwired(g: _G) -> list[dict[str, Any]]:
    out = []
    for nid in g.nodes:
        if g.kind[nid] not in BUZZERS or g.nodes[nid].get("kind") not in ("chip", "accessory"):
            continue
        terms = g.terminals(nid)
        nets = [(p, g.net(nid, p["key"])) for p in terms]
        if len(terms) < 2 or all(i is None for _, i in nets):
            continue  # an unconnected part is lint's
        lbl = {p["key"]: f"{nid}.{g.label(nid, p['key'])}" for p in terms}
        how = (f"Wire {nid}'s + to the supply and its - to a transistor's collector / drain switched by a GPIO (or, for a small "
               "piezo, + to a GPIO and - to GND).")
        loose = [p for p, _ in nets if g.alone(nid, p["key"])]
        if loose:
            out.append(_f(ERROR, "buzzer_unwired", nid, f"{nid} ({g.what(nid)}): {', '.join(lbl[p['key']] for p in loose)} is not connected to "
                          "anything, so it can never sound", how))
        elif all(g.power(i) for _, i in nets if i is not None):
            on = ", ".join(f"{lbl[p['key']]} on {g.name(i)}" for p, i in nets if i is not None)
            out.append(_f(ERROR, "buzzer_unwired", nid, f"{nid} ({g.what(nid)}) has every terminal on a supply net ({on}): nothing can switch it, "
                          "it is either always on or never", how))
    return out


def _gpio_short(g: _G) -> list[dict[str, Any]]:
    out = []
    for i in range(len(g.nets)):
        gp = g.gpios(i)
        if gp and g.power(i):
            for m, pin in gp:
                side = "ground" if g.gnd(i) else "supply"
                out.append(_f(ERROR, "gpio_short", f"{m}.{pin}", f"{g.pin_txt(m, pin)} is on the {side} net {g.name(i)}: the pin is tied to the "
                              "rail, and driving it the other way shorts the supply",
                              f"Take {m}.{pin} off {g.name(i)}: a pull-up / pull-down goes through a resistor (10k), a button between the pin and "
                              "GND, a load through a resistor or a transistor."))
        elif len(gp) >= 2:
            out.append(_f(ERROR, "gpio_short", "+".join(f"{m}.{p}" for m, p in gp), f"{' and '.join(g.pin_txt(m, p) for m, p in gp)} are on one net: "
                          "two pins driving it against each other short", "Give each pin its own net (and its own part)."))
        rails = {"GND" if MODULE_GND.match(p) else p for m, p in g.on[i] if m in g.modules and (p in MODULE_RAIL or MODULE_GND.match(p))}
        volts = {MODULE_RAIL[r] for r in rails if r != "GND"}
        if ("GND" in rails and volts) or len(volts) > 1:
            out.append(_f(ERROR, "supplies_shorted", g.name(i), f"net {g.name(i)} joins the module pins {', '.join(sorted(rails))}: the supplies are shorted",
                          "Give each rail its own net (GND, V3V3, V5); parts between them go on both nets."))
    return out


def _i2c_misuse(g: _G) -> list[dict[str, Any]]:
    out = []
    present = g.i2c_present()
    for m in g.modules:
        for pin in ("SDA", "SCL"):
            i = g.net(m, pin)
            if i is None:
                continue
            bad = list(dict.fromkeys(f"{x}" + (f" (through {via})" if via else "") for x, _, via in g.beyond(i) if g.kind[x] in MISUSE))
            if not bad:
                continue
            msg = f"{g.pin_txt(m, pin)} is the I2C {pin} pin but drives {', '.join(bad)}"
            if present:
                out.append(_f(ERROR, "i2c_pin_misuse", f"{m}.{pin}", msg + ", while an I2C device uses the bus on these pins: the pull-ups and the "
                              "bus traffic light / sound / trigger it, and the part loads the bus", f"Move it to a free pin ({g.free(m)}); keep "
                              f"{m}.SDA and {m}.SCL for the I2C bus only."))
            else:
                out.append(_f(WARNING, "i2c_pin_misuse", f"{m}.{pin}", msg + ": these are the module's I2C pins, so a display or sensor added "
                              "later has no bus", f"Prefer a free pin ({g.free(m)}) and keep {m}.SDA / {m}.SCL for I2C."))
    return out


def _strapping(g: _G) -> list[dict[str, Any]]:
    out = []
    for m in g.modules:
        gpio, strap, spec = g.mod(m)
        for pin, num in gpio.items():
            i = g.net(m, pin) if num in strap else None
            if i is None or g.power(i):
                continue  # a rail on it is gpio_short's
            pullers: list[str] = []
            movers: list[str] = []
            for x, key in g.on[i]:
                if x in g.modules:
                    continue
                if g.nodes[x].get("kind") == "resistor":
                    j = g.other(x, key)
                    if j is None or j == i:
                        continue
                    if g.gnd(j):
                        pullers.append(f"{x} (pull-down to GND)")
                        movers.append(x)
                    elif not g.power(j):  # a pull-up keeps the default level; a series resistor leads to what is beyond
                        beyond = [(y, ky) for y, ky in g.on[j] if y != x and y not in g.modules]
                        pullers += [f"{g.desc(y, ky)} through {x}" for y, ky in beyond]
                        movers += [y for y, _ in beyond] + [x]
                else:
                    pullers.append(g.desc(x, key))
                    movers.append(x)
            if pullers:
                out.append(_f(WARNING, "strapping_pin", f"{m}.{pin}", f"{g.pin_txt(m, pin)} is a strapping pin of the {spec.get('mcu', 'microcontroller')}, "
                              f"read at reset to choose the boot mode: {', '.join(pullers)} can hold it at the wrong level at power-up, and the "
                              "board may then wait in the bootloader instead of running the program",
                              f"Move {', '.join(dict.fromkeys(movers))} from {m}.{pin} to a free pin that is not read at boot ({g.free(m)}); a "
                              "strapping pin may only carry what leaves it at its default level at reset (a pull-up to 3V3)."))
    return out


def _ws2812(g: _G) -> list[dict[str, Any]]:
    out = []
    for nid in g.nodes:
        if not g.addressable(nid):
            continue
        vi, di = g.net_of(nid, VDD), g.net_of(nid, DIN)
        if vi is None:
            continue
        v = g.volt(vi)
        drv = g.driven(di)
        if v is not None and v >= 4.5 and drv:
            rng = VRANGE.search(g.text(nid))
            out.append(_f(WARNING, "ws2812_level", nid, f"{nid} ({g.what(nid)}) runs on {g.name(vi)} ({v:g} V) but its DIN comes straight from "
                          f"{g.pin_txt(*drv[0])} at 3.3 V: on 5 V it reads high only above 0.7 x VDD = {0.7 * v:.1f} V, so the data may be "
                          "missed (flicker, wrong colours, nothing)",
                          f"Feed {nid}'s VDD through the diode primitive (A on {g.name(vi)}, K on VDD: about 4.5 V, the threshold drops to "
                          f"what 3.3 V reaches), or put a level shifter (74AHCT1G125 or SN74LV1T34 powered from 5 V) between "
                          f"{drv[0][0]}.{drv[0][1]} and DIN" + (f"; or run it from V3V3 if its range allows ({rng[0]})." if rng else ".")))
        caps = [c for c, key in g.on[vi] if g.nodes[c].get("kind") == "capacitor" and (j := g.other(c, key)) is not None and g.gnd(j)]
        if not caps:
            out.append(_f(WARNING, "ws2812_decoupling", nid, f"{nid} ({g.what(nid)}) has no capacitor on its supply {g.name(vi)}: each LED's "
                          "current pulses then disturb the data and the other LEDs", f"Add 100nF from {nid}.VDD to GND (one per LED, at its "
                          "VDD pin) and one 10uF-100uF on the LED supply.", lint="decoupling"))
    return out


def _pullup_5v(g: _G) -> list[dict[str, Any]]:
    out = []
    if not g.modules:
        return out
    for r, n in g.nodes.items():
        if n.get("kind") != "resistor":
            continue
        a, b = g.net(r, "1"), g.net(r, "2")
        for x, y, pin in ((a, b, "2"), (b, a, "1")):
            if x is not None and y is not None and g.i2c_net(x) and (g.volt(y) or 0) >= 4.5:
                out.append(_f(ERROR, "pullup_5v", r, f"{r} pulls the I2C line {g.name(x)} up to {g.name(y)} ({g.volt(y):g} V): the "
                              f"{g.what(g.modules[0])}'s pins are 3.3 V and not 5 V tolerant",
                              f"Tie {r}.{pin} to V3V3 instead (4.7k to 3.3 V); a 5 V-only I2C part needs a level shifter (BSS138 pair or PCA9306)."))
    return out


def _led_ends(g: _G, nid: str) -> tuple[str, str] | None:
    """(anode key, cathode key) of an LED: the primitive, or a chip LED whose card labels one pin A and one K (named so by
    its symbol, or by catalog.roles_of from the symbol's diode triangle); None for anything else."""
    n = g.nodes[nid]
    if n.get("kind") == "led":
        return "A", "K"
    if n.get("kind") != "chip" or g.kind[nid] != "led":
        return None
    a = [p["key"] for p in g.pins[nid] if ANODE.match(catalog.base_label(p["label"]))]
    k = [p["key"] for p in g.pins[nid] if CATHODE.match(catalog.base_label(p["label"]))]
    return (a[0], k[0]) if len(a) == 1 and len(k) == 1 else None


def _vf(g: _G, nid: str) -> float:
    """An LED's forward voltage for its current: the card's Vf parameter (the lowest it gives), else what its colour
    usually drops (the node's color, the card's colour parameter or its description; a lens colour is no LED colour),
    else VF_MIN, the worst case."""
    part = g.part(nid)
    attrs = part.get("attrs") if isinstance(part.get("attrs"), dict) else {}
    vf = [float(x) for k, v in attrs.items() if re.search(r"forward", k, re.I) for x in re.findall(r"(\d+(?:\.\d+)?)\s*V", str(v))]
    if vf and 1.0 <= min(vf) <= 4.5:
        return min(vf)
    said = [str(g.nodes[nid].get("color") or ""), *(str(v) for k, v in attrs.items() if re.search(r"colou?r", k, re.I)
                                                    and not re.search(r"lens|temperature", k, re.I)),
            re.sub(r"\w+\s+Lens", "", str(part.get("description") or ""), flags=re.I)]
    return next((v for s in said for rx, v in LED_VF if rx.search(s)), VF_MIN)


def _led(g: _G) -> list[dict[str, Any]]:
    """An LED turned round, with nothing in series, or with a resistor that lets through too much: a GPIO in its path
    (straight or through the resistor) holds it to the pin's 20 mA; one fed from a rail and switched by a transistor to
    its rated current (the card's current_ma, else 20 mA), at the forward voltage its card or colour gives."""
    out = []
    for nid in g.nodes:
        ends = _led_ends(g, nid)
        if not ends:
            continue
        ka, kk = ends
        a, k = g.net(nid, ka), g.net(nid, kk)
        if a is None or k is None:
            continue  # lint: unconnected / single-pin net
        pa, pk = f"{nid}.{g.label(nid, ka)}", f"{nid}.{g.label(nid, kk)}"
        va, vk = g.volt(a) if g.rail(a) else None, g.volt(k) if g.rail(k) else None
        if g.gnd(a) or (vk is not None and not (va is not None and va > vk)):
            out.append(_f(ERROR, "led_reversed", nid, f"{nid} is turned round: its anode {pa} is on {g.name(a)} and its cathode {pk} on "
                          f"{g.name(k)}, so it never lights", "Swap them: A towards the GPIO or the supply (through the resistor), K towards GND."))
            continue
        if (g.gpios(a) or g.rail(a)) and (g.gpios(k) or g.gnd(k)):
            out.append(_f(WARNING, "led_current", nid, f"{nid} sits straight between {g.name(a)} and {g.name(k)} with no resistor in series: "
                          "nothing limits its current, so the LED and the pin burn", f"Put 1k in series: from the GPIO to a resistor, the "
                          f"resistor to {pa} (each on its own net).", lint="led_resistor"))
            continue
        vf = _vf(g, nid)
        rated = g.current_ma(nid) if g.nodes[nid].get("kind") == "chip" else None
        for side in (a, k):
            for r, key in g.on[side]:
                far = g.other(r, key) if g.nodes[r].get("kind") == "resistor" else None
                ohms = _ohms(g.nodes[r].get("value")) if far is not None and far not in (a, k) else None
                if not ohms:
                    continue
                drive = [v for i in (far, a) for v in ((g.volt(i) if g.rail(i) else None), (3.3 if g.gpios(i) else None)) if v]
                if not drive or max(drive) <= vf:
                    continue
                v = max(drive)
                ma = (v - vf) / ohms * 1000
                pin = any(g.gpios(i) for i in (far, a, k))
                limit = min(GPIO_MAX_MA, rated or GPIO_MAX_MA) if pin else (rated or GPIO_MAX_MA)
                if ma <= limit:
                    continue
                need = math.ceil((v - vf) / limit * 1000)
                if pin or not rated:
                    out.append(_f(WARNING, "led_current", nid, f"{nid}'s resistor {r} is {g.nodes[r].get('value')} from {v:g} V: up to {ma:.0f} mA "
                                  f"through the LED{' and the pin' if pin else ''} (keep it under {limit:g} mA; an indicator needs 1-5 mA)",
                                  f"Make {r} at least {need} ohm (330 to 1k is usual)."))
                else:
                    out.append(_f(WARNING, "led_current", nid, f"{nid}'s resistor {r} is {g.nodes[r].get('value')} from {v:g} V: about {ma:.0f} mA "
                                  f"through the LED (Vf ~{vf:g} V), over its rated {rated:g} mA, so it runs hot and fades early",
                                  f"Make {r} at least {need} ohm."))
    return out


def _supply_range(g: _G) -> list[dict[str, Any]]:
    """A chip's supply pin on a rail outside the range its description gives ('1.71V~3.6V'). A two-terminal load (a
    buzzer, a motor) has no pin named like a supply: whichever terminal sits on a rail is its supply (a 2V~4V buzzer's
    P1 on the 5 V VBUS)."""
    out = []
    for nid, n in g.nodes.items():
        if n.get("kind") != "chip":
            continue
        m = VRANGE.search(str(g.part(nid).get("description") or ""))
        lo, hi = (float(m[1]), float(m[2])) if m else (0.0, 0.0)
        if not m or not 0 < lo < hi <= 60:
            continue
        load = g.kind[nid] in (*BUZZERS, "motor") and len(g.terminals(nid)) == 2
        for p, i in g.wired(nid):
            lb = catalog.base_label(p["label"])
            v = g.volt(i) if g.rail(i) else None
            if v is None or not (load or SUPPLY_PIN.match(lb) or SUPPLY_PIN.match(p["name"])):
                continue
            pin = f"{nid}.{lb}"
            if v > hi + 0.1:
                fit = next((r for r, rv in (("V3V3", 3.3), ("V5", 5.0)) if lo <= rv <= hi), None)
                out.append(_f(ERROR, "supply_range", nid, f"{pin} is on {g.name(i)} ({v:g} V) but {nid} ({g.what(nid)}) is rated {lo:g}-{hi:g} V: it is damaged",
                              f"Supply {pin} from {fit or 'a rail in its range (add a regulator)'}" + (" instead." if fit and load else
                                                                                                         " and check its logic levels." if fit else ".")))
                break
            if v < lo - 0.05:
                fit = next((r for r, rv in (("V5", 5.0), ("V3V3", 3.3)) if lo <= rv <= hi), None)
                out.append(_f(WARNING, "supply_range", nid, f"{pin} is on {g.name(i)} ({v:g} V), below the {lo:g} V minimum of {nid} ({g.what(nid)}): "
                              "it may not start or work reliably", (f"Supply it from {fit} instead or pick a part rated for {v:g} V." if load else
                                                                    f"Supply it from {fit} (mind the logic levels) or pick a part rated for {v:g} V.")
                              if fit else f"Pick a part rated for {v:g} V."))
                break
    return out


def _accessory_supply(g: _G) -> list[dict[str, Any]]:
    out = []
    for nid, n in g.nodes.items():
        if n.get("kind") != "accessory":
            continue
        sup = str(g.acc(nid).get("supply") or "").upper().replace(" ", "")
        for p, i in g.wired(nid):
            v = g.volt(i) if g.rail(i) else None
            if v is None or not (SUPPLY_PIN.match(p["key"]) or SUPPLY_PIN.match(p["name"])):
                continue
            if sup == "3V3" and v >= 4.5:
                out.append(_f(ERROR, "accessory_supply", nid, f"{nid} ({g.what(nid)}) is a 3.3 V module but {nid}.{p['key']} is on {g.name(i)} ({v:g} V): it may be damaged",
                              f"Wire {nid}.{p['key']} to V3V3."))
            elif sup == "5V" and v < 4.5:
                out.append(_f(ERROR, "accessory_supply", nid, f"{nid} ({g.what(nid)}) needs 5 V but {nid}.{p['key']} is on {g.name(i)} ({v:g} V): it may not work",
                              f"Wire {nid}.{p['key']} to V5 (and check that its signal levels suit a 3.3 V microcontroller)."))
    return out


def _flyback(g: _G) -> list[dict[str, Any]]:
    out = []
    for nid in g.nodes:
        # an electromagnetic buzzer is a coil too (a soil sensor once dropped its diode); a piezo is not
        if g.kind[nid] not in COILS and not (g.kind[nid] in BUZZERS and g.tech(nid) == "magnetic"):
            continue
        nets = [i for p in g.terminals(nid) if (i := g.net(nid, p["key"])) is not None]
        if len(nets) != 2 or not any(g.kind[x] in SWITCHES for i in nets for x, _ in g.on[i]):
            continue
        diodes = {x for x, _ in g.on[nets[0]] if g.kind[x] == "diode"} & {x for x, _ in g.on[nets[1]] if g.kind[x] == "diode"}
        if not diodes:
            out.append(_f(WARNING, "flyback_diode", nid, f"{nid} ({g.what(nid)}) is a coil switched by a transistor with no diode across it: "
                          "its turn-off spike can kill the transistor", f"Add a diode across {nid}: A on the transistor side, K on the supply side."))
    return out


def _load_sides(g: _G, nid: str) -> tuple[int, int] | None:
    """(supply side, switched side) nets of a two-terminal load: the side on a rail, else the side with no transistor."""
    nets = [g.net(nid, p["key"]) for p in g.terminals(nid)]
    if len(nets) != 2 or None in nets or nets[0] == nets[1]:
        return None
    rails = [i for i in nets if i is not None and g.rail(i)]
    switched = [i for i in nets if i is not None and any(g.kind[x] in SWITCHES for x, _ in g.on[i])]
    supply = rails[0] if len(rails) == 1 else next((i for i in nets if i not in switched), None) if len(switched) == 1 else None
    if supply is None:
        return None
    return supply, next(i for i in nets if i != supply)  # type: ignore[misc]


# ---- what a chip cannot work without: the pins it measures on, its supply
MEASURED = re.compile(r"^(IP|IN|VIN|AIN|ADC_?IN|RS|ISENSE|SENSE|VSENSE|CS)[+\-PN]?\d*$|^(IN|VIN|AIN)\d*[+\-PN]$|^A?IN\d+$", re.I)


def _unwired_inputs(g: _G) -> list[dict[str, Any]]:
    """A chip whose measured input or supply is on no net cannot do its job, whatever the rest of its wiring says: a current sensor
    with no current through it reads a flat zero, and the firmware test passes on a made-up value. Only for a chip that is wired at all."""
    out = []
    for nid, n in g.nodes.items():
        # only a chip wired at all: one with nothing but its grounds on a net is lint's unconnected part
        if n.get("kind") != "chip" or not any(not g.gnd(i) for _p, i in g.wired(nid)):
            continue
        open_in, open_sup = [], []
        for p in g.pins[nid]:
            names = [p["name"], p["label"]]
            if NC.match(p["name"] or "") or g.net(nid, p["key"]) is not None:
                continue
            if any(MEASURED.match(x or "") for x in names):
                open_in.append(p["name"] or p["label"])
            elif any(SUPPLY_PIN.match(x or "") for x in names):
                open_sup.append(p["name"] or p["label"])
        # a pin of a pair that is wired on its twin counts as wired: IN- only is a single-ended amplifier's business
        if open_in:
            what = ", ".join(dict.fromkeys(open_in))
            out.append(_f(ERROR, "input_unwired", nid, f"{nid} ({g.what(nid)}) measures on {what}, and they are on no net: it reads nothing, and no firmware can make up for it",
                          f"Wire {what} to what it must measure. If that is mains or anything this board must not carry, take another part: a clamp-on current transformer or an isolated energy-meter module on a cable (see the accessories)."))
        if open_sup:
            what = ", ".join(dict.fromkeys(open_sup))
            out.append(_f(WARNING, "supply_unwired", nid, f"{nid} ({g.what(nid)}): its supply {what} is on no net: most chips do not run without every supply pin", f"Wire {what} to the rail in {nid}'s range, unless its datasheet says it may stay open."))
    return out


# ---- what the copper, the connectors and the parts carry
MAINS_NET = re.compile(r"^(L|N|PE|L1|N1|LINE|NEUTRAL|MAINS|AC|ACL|ACN|AC_L|AC_N|AC_IN|HOT|V220V?|V230V?|V110V?)$", re.I)
AMPS_SAID = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:А|A|амп\w*|amps?)(?![A-Za-zА-Яа-я])")
WATTS_SAID = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(кВт|kW|Вт|W)(?![A-Za-zА-Яа-я])")
POWER_TERM = re.compile(r"^(D|S|C|E|DRAIN|SOURCE|COLLECTOR|EMITTER)\d*$", re.I)
RDS = re.compile(r"RDS|on.?resistance", re.I)
PACKAGE_W = [(re.compile(r"TO-?247", re.I), 3.5), (re.compile(r"TO-?263|D2PAK", re.I), 3.0), (re.compile(r"TO-?220|TO-?252|DPAK", re.I), 2.0),
             (re.compile(r"PDFN|DFN|QFN|SOP-?8|SOIC-?8|PowerPAK|LFPAK", re.I), 1.5), (re.compile(r"SOT-?223|SOT-?89", re.I), 1.0), (re.compile(r"SOT-?23|SC-?70|SOT-?323", re.I), 0.35)]
RESISTOR_W = {"0402": 0.06, "0603": 0.1, "0805": 0.125, "1206": 0.25}


def _pack_w(g: _G, nid: str) -> float:
    """What a part's package sheds in still air on a small board without a heatsink, plus the heatsink the node states."""
    text = f"{g.part(nid).get('package') or ''} {g.part(nid).get('footprint_name') or ''}"
    base = next((w for rx, w in PACKAGE_W if rx.search(text)), 0.5)
    return base + float(g.nodes[nid].get("heatsink_w") or 0)


def _attr_ohms(part: dict[str, Any], rx: re.Pattern[str]) -> float | None:
    for k, v in (part.get("attrs") or {}).items():
        if rx.search(str(k)):
            m = re.search(r"(\d+(?:\.\d+)?)\s*(m|k)?(?:Ω|ohm)", str(v), re.I)
            if m:
                return float(m.group(1)) * {"m": 1e-3, "k": 1e3}.get((m.group(2) or "").lower(), 1.0)
    return None


def _contacts(g: _G, nid: str, i: int) -> list[str]:
    return [key for x, key in g.on[i] if x == nid]


def _connector_amps(g: _G, nid: str) -> float | None:
    n = g.nodes[nid]
    if n.get("connector"):
        return float(device.CONNECTORS[n["connector"]]["amps"])
    if n.get("kind") == "chip" and n.get("edge"):
        ma = g.part(nid).get("current_ma")
        return float(ma) / 1000 if ma else None
    if n.get("kind") in device.CONNECTOR_AMPS:
        return device.CONNECTOR_AMPS[n["kind"]]
    if n.get("kind") == "accessory" and g.acc(nid).get("connect") in ("header", "jst"):
        return device.CONNECTOR_AMPS["jst" if g.acc(nid).get("connect") == "jst" else "header"]
    return None


def _said(g: _G) -> tuple[float, float]:
    """The largest current and power the requirements name (A, W)."""
    text = " ".join(str(r.get("text") or "") for r in g.doc.get("requirements") or [] if isinstance(r, dict))
    amps = max([float(m.group(1).replace(",", ".")) for m in AMPS_SAID.finditer(text)] or [0.0])
    watts = max([float(m.group(1).replace(",", ".")) * (1000 if m.group(2).lower() in ("квт", "kw") else 1) for m in WATTS_SAID.finditer(text)] or [0.0])
    return amps, watts


def _current(g: _G) -> list[dict[str, Any]]:
    """The physics DRC does not see: a net is clean at any current. Each stated current (net.amps) is held to the width of copper it
    gets, every contact and part it runs through; a current or power the requirements name must be stated; a power path that leaves
    the board by a connector must state what it carries. IPC-2221 for copper, the part's own rating for the rest."""
    out = []
    amps_of = [float(n.get("amps") or 0) for n in g.nets]
    top = max(amps_of or [0.0])
    for i, net in enumerate(g.nets):
        name = net.get("name") or g.name(i)
        if MAINS_NET.match(net.get("name") or ""):
            out.append(_f(ERROR, "mains_on_board", name, f"net {name} is mains: this board has no creepage distances, no fuse and no isolation, and it would be live under the person's fingers",
                          "Keep mains off the board: a relay or energy-meter module on a cable (see the accessories) with its mains side outside this case, wired by an electrician, or a certified smart socket."))
        a = amps_of[i]
        conns = [x for x in dict.fromkeys(x for x, _ in g.on[i]) if _connector_amps(g, x) is not None]
        v = g.volt(i)
        if not a and conns and not g.gnd(i):
            through = [x for x, key in g.on[i] if g.kind[x] in SWITCHES and POWER_TERM.match(g.raw(x, key) or "")]
            if through or (v is not None and v > 5.5):
                why = f"{', '.join(dict.fromkeys(through))} switches it" if through else f"it brings {v:g} V"
                out.append(_f(ERROR, "current_unstated", name, f"net {name} leaves the board by {', '.join(conns)} and {why}, but says nothing of the current it carries, so nothing can check its copper or its contacts",
                              f"Give that net amps: the most it carries in use, e.g. {{\"pins\": [...], \"amps\": 1.5}}."))
        if a <= 0:
            continue
        for x in conns:
            pins = max(1, len(_contacts(g, x, i)))
            rating = float(_connector_amps(g, x) or 0) * pins
            if a > rating:
                out.append(_f(ERROR, "connector_current", x, f"{x} carries {a:g} A of net {name} on {pins} contact(s) rated about {rating:g} A in all: it overheats",
                              f"Use a screw terminal (header with connector: {', '.join(device.CONNECTORS)}: up to {max(c['amps'] for c in device.CONNECTORS.values()):g} A a pole), or more contacts on the net."))
        need = device.trace_mm(a)
        if need > device.TRACE_MAX_MM and not device.poured(g.doc, net):
            out.append(_f(ERROR, "trace_current", name, f"net {name} carries {a:g} A, which takes a {need:g} mm trace (IPC-2221, 1 oz, 20 C rise); traces stop at {device.TRACE_MAX_MM:g} mm",
                          f"Name the net and add a pour for it: zones [{{\"kind\": \"pour\", \"net\": \"{name}\", \"layer\": \"top\"}}] with a rect over its path; the other power net takes the other layer."))
        for x, key in g.on[i]:
            k = g.kind[x]
            if k in SWITCHES and POWER_TERM.match(g.raw(x, key) or ""):
                card = g.part(x)
                rated = float(card.get("current_ma") or 0) / 1000
                if rated and a > 0.7 * rated:
                    out.append(_f(ERROR, "part_current", x, f"{x} ({g.what(x)}) carries {a:g} A of net {name} and is rated {rated:g} A: keep it under 70 %", "A larger part from search_parts, or two in parallel."))
                rds = _attr_ohms(card, RDS)
                if rds:
                    heat, can = a * a * rds, _pack_w(g, x)
                    if heat > can:
                        out.append(_f(ERROR, "part_heat", x, f"{x} ({g.what(x)}) sheds {heat:.2f} W at {a:g} A ({rds * 1000:g} mOhm on), and its package gets rid of about {can:g} W here", "A part with a lower on-resistance or a larger package; a heatsink stated on the node (heatsink_w) goes in the summary as an extra."))
            elif k == "resistor":
                card, n = g.part(x), g.nodes[x]
                ohms = _attr_ohms(card, re.compile(r"^resistance$", re.I)) if n.get("kind") == "chip" else _ohms(n.get("value"))
                if ohms is None:
                    continue
                m = re.search(r"(\d+(?:\.\d+)?)\s*(m)?W", str((card.get("attrs") or {}).get("Power(Watts)") or ""))
                can = (float(m.group(1)) * (1e-3 if m.group(2) else 1)) if m else RESISTOR_W.get(str(n.get("package") or ""), 0.1)
                heat = a * a * ohms
                if heat > can:
                    out.append(_f(ERROR, "part_heat", x, f"{x} ({g.what(x)}) sheds {heat:.2f} W at {a:g} A through {ohms:g} Ohm, and it is rated {can:g} W", "A lower value or a power resistor from search_parts."))
    # what comes back through ground comes through its copper and the same connector
    if top and any(g.gnd(i) for i in range(len(g.nets))):
        for i, net in enumerate(g.nets):
            if not g.gnd(i):
                continue
            name = net.get("name") or g.name(i)
            if device.trace_mm(top) > device.TRACE_MAX_MM and not device.poured(g.doc, net):
                out.append(_f(ERROR, "trace_current", name, f"the {top:g} A of the power path comes back through {name}, which takes a {device.trace_mm(top):g} mm trace; traces stop at {device.TRACE_MAX_MM:g} mm",
                              f"Add a pour for it: zones [{{\"kind\": \"pour\", \"net\": \"{name}\", \"layer\": \"bottom\"}}]."))
    named_a, named_w = _said(g)
    if named_a >= 1 and top < 0.8 * named_a:
        out.append(_f(ERROR, "current_unstated", "requirements", f"a requirement names {named_a:g} A, and no net states that current (the most is {top:g} A), so the board was not checked for it",
                      "Give the net it runs through amps; the copper, the contacts and the parts are then held to it."))
    # a transistor an op-amp drives is in its linear region: all the power the requirement names is heat on the board
    linear = [x for x in g.nodes if g.kind[x] in SWITCHES and _linear(g, x)]
    if linear and named_w:
        can = sum(_pack_w(g, x) for x in linear)
        if named_w > can:
            out.append(_f(ERROR, "thermal_budget", linear[0], f"{', '.join(linear)} run in their linear region under an amplifier, so the {named_w:g} W a requirement names is heat on this board, and they get rid of about {can:g} W",
                          "State the heatsink each one is bolted to (heatsink_w on the node, with the cooling in the summary as an extra the case does not hold), or say the power this board can really take. Never just lower the requirement without saying so."))
    return out


def _linear(g: _G, x: str) -> bool:
    roles, _ = g.roles(x)
    gate = next((k for r in ("G", "B") for k in (roles.get(r) or [])), None) if roles else None
    i = g.net(x, gate) if gate else None
    if i is None:
        return False
    nets = {i}
    for y, _key in g.on[i]:  # through the series resistor between them
        if g.nodes[y].get("kind") == "resistor":
            nets |= {j for _p, j in g.wired(y)}
    return any(g.kind.get(y) == "ic" and re.search(r"op ?amp|operational|amplifier|comparator|LM358|LM324|MCP600", g.text(y), re.I) for j in nets for y, _k in g.on[j])


SOCKET = re.compile(r"Audio Connectors|Circular DIN|DC Power Connectors|Ethernet Connectors|Coaxial Connectors|Power connector|USB Connectors", re.I)
SIDEWAYS = re.compile(r"Right.?Angle|\bSMD\b", re.I)


def _sockets(g: _G) -> list[dict[str, Any]]:
    """A socket a plug goes into has to be reached: on an edge, where the wall gets its window, or upright through a hole in the lid. Left
    inside, it sits in a closed box and the summary tells the person to cut the wall themselves (a MIDI pedal on 2026-11-04)."""
    out = []
    for nid, n in g.nodes.items():
        if n.get("kind") != "chip":
            continue
        card = g.part(nid)
        if not SOCKET.search(f"{card.get('category') or ''} {card.get('family') or ''}"):
            continue
        text = f"{card.get('description') or ''} {card.get('package') or ''}"
        if n.get("face") == "hole" and SIDEWAYS.search(text):
            out.append(_f(ERROR, "socket_unreachable", nid, f"{nid} ({g.what(nid)}) opens sideways, so a hole in the lid does not reach it", f"Give {nid} an edge instead of face hole: the build turns it to open out of the wall."))
        elif not n.get("edge") and n.get("face") != "hole":
            out.append(_f(ERROR, "socket_unreachable", nid, f"{nid} ({g.what(nid)}) is a socket with no way in: it stays closed inside the case", f"Give {nid} an edge (\"edge\": \"-y\"): the build turns it to open outwards and the wall gets its window."))
    return out


def _floating(g: _G) -> list[dict[str, Any]]:
    """A two-terminal part with one end on no net (or on one with nothing else on it) does nothing: a flyback diode with
    its K left off, a pull-up wired at one end. A buzzer's loose terminal is buzzer_unwired's, which says how it is wired."""
    out = []
    for nid, n in g.nodes.items():
        k = n.get("kind")
        keys = list(TWO[k]) if k in TWO else [p["key"] for p in g.terminals(nid)] if k == "chip" else []
        if len(keys) != 2 or g.kind[nid] in BUZZERS:
            continue
        nets = [g.net(nid, key) for key in keys]
        if all(i is None for i in nets) or nets[0] == nets[1]:
            continue  # unconnected is lint's, both ends on one net short_part's
        loose = [key for key in keys if g.alone(nid, key)]
        if not loose:
            continue
        where = "; ".join(f"{nid}.{g.label(nid, key)} is " + ("on no net" if g.net(nid, key) is None else f"on net {g.name(g.net(nid, key))} with nothing else")
                          for key in loose)
        hint = f"Wire {' and '.join(f'{nid}.{g.label(nid, key)}' for key in loose)} to the net it belongs on, or remove {nid}."
        held = [key for key in keys if key not in loose]
        if g.ends(nid) is not None and held:
            # a diode on one side of a load: its loose end belongs on the load's other side
            near = g.net(nid, held[0])
            load = next((x for x, _ in g.on[near] if x != nid and g.kind[x] in LOADS), None) if near is not None else None
            sides = _load_sides(g, load) if load else None
            role = "K" if CATHODE.match(g.raw(nid, loose[0])) else "A"
            if sides and load:
                target = sides[0] if role == "K" else sides[1]
                hint = (f"{nid} is the flyback diode across {load}: wire {nid}.{role} to {g.name(target)} (the side {load}'s "
                        f"{'+ is on' if role == 'K' else '- and the transistor are on'}), or remove {nid}.")
            else:
                hint += " For a flyback diode: K to the supply the coil / buzzer + is on, A to its transistor side."
        out.append(_f(ERROR, "floating_pin", nid, f"{nid} ({g.what(nid)}) has a floating pin: {where}, so {nid} does nothing", hint))
    return out


def _flyback_orientation(g: _G) -> list[dict[str, Any]]:
    out = []
    for nid in g.nodes:
        sides = _load_sides(g, nid) if g.kind[nid] in LOADS else None
        if not sides:
            continue
        supply, switched = sides
        for d in g.nodes:
            e = g.ends(d) if d != nid else None
            if not e or set(e) != {supply, switched} or e[1] == supply:
                continue
            out.append(_f(ERROR, "flyback_orientation", d, f"{d} across {nid} ({g.what(nid)}) is turned round: its cathode K is on "
                          f"{g.name(switched)}, the switched side, and its anode A on the supply {g.name(supply)}: when the transistor turns "
                          "on, the diode shorts the supply through it, and it never catches the coil's kick",
                          f"Swap {d}: A on {g.name(switched)} (the transistor side), K on {g.name(supply)} (the side {nid}'s + is on)."))
    return out


def _sensor_divider(g: _G) -> list[dict[str, Any]]:
    """Which way an LDR's or a thermistor's reading moves, from where it sits in its divider: stated so the firmware's
    thresholds (and the reviewer reading them) agree with the board. A divider read on a pin with no ADC is an error."""
    out = []
    for nid, n in g.nodes.items():
        t = f"{g.text(nid)} {g.part(nid).get('kind_hint') or ''} {n.get('label') or ''}"
        terms = g.terminals(nid)
        if n.get("kind") != "chip" or not DIVIDER.search(t) or len(terms) != 2:
            continue
        a, b = (g.net(nid, p["key"]) for p in terms)
        if a is None or b is None or a == b:
            continue  # floating_pin / short_part
        leg = next(((r, m) for r, m in ((a, b), (b, a)) if g.power(r) and not g.power(m)), None)
        if not leg:
            continue
        rail, mid = leg
        gp = g.gpios(mid) or g.driven(mid)
        if not gp:
            continue
        m, pin = gp[0]
        gpio, _, spec = g.mod(m)
        alias = next((al for al, tg in (spec.get("aliases") or {}).items() if tg == pin and re.match(r"^D\d+$", al)), pin)
        thermal = bool(THERMAL.search(t))
        what = "temperature" if thermal else "light"
        more, less = ("warmer", "colder") if thermal else ("brighter", "darker")
        falls_with = not (thermal and re.search(r"\bPTC\b", t) and not re.search(r"\bNTC\b", t))  # an LDR / NTC drops with light / heat
        fixed = [(r, j) for r, key in g.on[mid] if g.nodes[r].get("kind") == "resistor" and (j := g.other(r, key)) is not None
                 and g.power(j) and g.gnd(j) != g.gnd(rail)]
        if not fixed:
            other = "GND" if g.rail(rail) else "V3V3"
            out.append(_f(WARNING, "sensor_divider", nid, f"{nid} ({g.what(nid)}) is between {g.name(rail)} and {g.pin_txt(m, pin)} with no fixed "
                          f"resistor to {other}: there is no divider, so the reading does not follow the {what}",
                          f"Add a resistor of about the sensor's mid value (10k for a GL55xx LDR or a 10k NTC) from {m}.{pin} to {other}."))
            continue
        r, j = fixed[0]
        rises = g.rail(rail) == falls_with  # the sensor on the supply side: its resistance falls, the pin rises
        word, other_word = ("RISES", "high") if rises else ("FALLS", "low")
        f = _f(WARNING, "sensor_divider", nid, f"{nid} ({g.what(nid)}) is between {g.name(rail)} and {g.pin_txt(m, pin)} with {r} "
               f"({g.nodes[r].get('value')}) to {g.name(j)}: the reading on {alias} {word} with {what} ({more} = {other_word}er analogRead); "
               "compare thresholds that way in the firmware",
               f"In the firmware {more} gives a {other_word}er analogRead({alias}) and {less} a {'lower' if rises else 'higher'} one: "
               f"'only when {'cold' if thermal else 'dark'}' means acting while the reading is {'below' if rises else 'above'} the threshold.")
        f["data"] = {"pin": f"{m}.{pin}", "alias": alias, "gpio": gpio.get(pin), "quantity": what, "rises": rises}
        out.append(f)
        adc = spec.get("adc")
        if adc is not None and pin not in adc and alias not in adc:
            out.append(_f(ERROR, "adc_pin", nid, f"{nid}'s divider is read on {g.pin_txt(m, pin)}, which has no usable ADC on the "
                          f"{spec.get('name', 'module')}: analogRead cannot measure it", f"Move the divider's middle ({m}.{pin}) to an ADC "
                          f"pin: {', '.join(p for p in adc if (m, p) not in g.at) or ', '.join(adc)}."))
    return out


def _requirements(g: _G) -> list[dict[str, Any]]:
    out = []
    for r in g.doc.get("requirements") or []:
        if not isinstance(r, dict):
            continue
        missing = [str(p) for p in r.get("parts") or [] if str(p) not in g.nodes]
        if missing:
            rid = str(r.get("id") or "requirement")
            out.append(_f(WARNING, "unused_requirement", rid, f"{rid} ('{str(r.get('text') or '')[:80]}') names {', '.join(missing)}, which "
                          f"{'is' if len(missing) == 1 else 'are'} not in the graph: nothing meets it",
                          "Add the part that meets it, or point the requirement's parts at the ones that do."))
    return out


def _supply_no_source(g: _G) -> list[dict[str, Any]]:
    """A named rail with parts on it and nothing feeding it (a night light's V3V3 without U1.V3V3)."""
    out = []
    for i, net in enumerate(g.nets):
        if i in g.sourced() or not g.on[i] or not g.supply_net(i):
            continue
        name = net["name"]
        on = ", ".join(f"{x}.{g.label(x, k)}" for x, k in g.on[i][:8]) + (" ..." if len(g.on[i]) > 8 else "")
        v = next((v for rx, v in RAIL_V if rx.match(name)), None)
        m = g.modules[0] if g.modules else None
        pins = (device.MODULES[g.nodes[m]["module"]]["pins"] if m else [])
        pin = "V3V3" if v == 3.3 else next((p for p in ("V5", "VSYS", "VBUS") if p in pins), None) if v == 5.0 else None
        if m and pin:
            hint = f"Connect {m}.{pin} to {name} (or the regulator output that should feed it)."
        elif v == 4.2:
            hint = f"Put the battery's + on {name} (a JST's P1 or the battery accessory), or feed it from a charger's output."
        else:
            hint = f"Feed {name} from a source: a module power pin, a regulator output, or a diode from one (A on V5, K on {name})."
        out.append(_f(ERROR, "supply_no_source", name, f"net {name} has {on} on it but nothing feeds it (no module power pin, regulator or "
                      "charger output, USB-C VBUS, battery, or diode from one), so none of them gets power", hint))
    return out


def _load_unpowered(g: _G) -> list[dict[str, Any]]:
    """LEDs and loads whose feed side never reaches a source: LED anodes through their resistors to an N-MOSFET's drain
    only, a chip's VCC on a net nothing feeds. Loads sharing one dead end are one finding."""
    dead: dict[frozenset[int], list[tuple[str, list[int]]]] = {}
    for nid, n in g.nodes.items():
        k, kd = n.get("kind"), g.kind[nid]
        if k == "led":
            keys = ["A"]
        elif kd in LOADS and k in ("chip", "accessory"):
            keys = [p["key"] for p in g.terminals(nid)]
        elif k in ("chip", "accessory") and g.battery_plus(nid) is None and kd not in SWITCHES:
            keys = [p["key"] for p in g.pins[nid] if SUPPLY_PIN.match(catalog.base_label(p["label"])) or SUPPLY_PIN.match(p["name"])]
        else:
            continue
        sides = sorted({i for key in keys if (i := g.net(nid, key)) is not None and not g.gnd(i)})
        if not sides or any(g.upstream(i)[0] != "none" for i in sides):
            continue  # floating, fed, or on a rail supply_no_source names
        dead.setdefault(frozenset().union(*(g.upstream(i)[1] for i in sides)), []).append((nid, sides))
    out = []
    for seen, group in dead.items():
        ids = [nid for nid, _ in group]
        own = {i for _, sides in group for i in sides}
        end = sorted(seen - own) or sorted(own)  # the far end they all lead to, not each one's own feed net
        low = next(((x, key) for j in seen for x, key in g.on[j] if g.kind[x] in ("nmos", "npn") and g.role(x, key) in ("D", "C")), None)
        led = all(g.nodes[x].get("kind") == "led" for x in ids)
        who = ", ".join(ids)
        msg = (f"{who} {'is' if len(ids) == 1 else 'are'} never powered: {'the anode side' if led else 'the supply side'} leads only to "
               f"{', '.join(g.name(j) for j in end)}, which no supply, GPIO or regulator reaches")
        if low:
            q, key = low
            word, src = ("drain", "S") if g.kind[q] == "nmos" else ("collector", "E")
            msg += f" ({q}'s {word} is a low-side switch: it leads to GND, never to a supply)"
            feed, ret = (("the A side (through each resistor)", "K") if led else ("the + terminal", "- terminal"))
            hint = (f"Put {who} between the supply and {q}: {feed} to V3V3 or V5, the {ret} to {q}.{g.label(q, key)}, "
                    f"{q}.{src} to GND.")
        else:
            hint = f"Wire {who}'s {'anode side (through its resistor)' if led else 'supply pin'} to a supply rail or a GPIO."
        out.append(_f(ERROR, "load_unpowered", ids[0], msg, hint))
    return out


def _diode_to_ground(g: _G) -> list[dict[str, Any]]:
    """A 'flyback' diode from the switched side to GND: it conducts whenever the transistor is off, the load never stops."""
    out = []
    for d in g.nodes:
        e = g.ends(d)
        if not e or e[0] is None or e[1] is None or not g.gnd(e[1]) or g.gnd(e[0]):
            continue
        a = e[0]
        sw = [(x, key) for x, key in g.on[a] if g.kind[x] in ("npn", "nmos") and g.role(x, key) in ("C", "D")]
        load = next((x for x, _ in g.on[a] if g.kind[x] in LOADS), None)
        if not sw and not load:
            continue
        sides = _load_sides(g, load) if load else None
        on = " and ".join([f"{x}'s {'collector' if g.role(x, k) == 'C' else 'drain'}" for x, k in sw[:1]] + ([f"{load}'s low side"] if load else []))
        why = (f"whenever {sw[0][0]} is off the diode conducts, so {load or 'the load'} is always on" if sw
               else f"it carries {load}'s current to GND, so {load} is always on")
        supply = g.name(sides[0]) if sides else f"the supply {load or 'the load'}'s + is on"
        out.append(_f(ERROR, "diode_to_ground", d, f"{d} has its cathode K on {g.name(e[1])} and its anode A on {g.name(a)} ({on}): {why}",
                      f"A flyback diode goes across the load: {d}.A on {g.name(a)} (the low side{', the collector' if sw and g.role(*sw[0]) == 'C' else ''}), "
                      f"{d}.K on {supply} (the side {load or 'the load'}'s + is on), never on GND."))
    return out


def _diode_across_rail(g: _G) -> list[dict[str, Any]]:
    """A diode straight across a rail and GND: turned against the supply it never conducts (no flyback for anything);
    turned with it, it is a dead short. A TVS or Zener clamp there is what it should be."""
    out = []
    for d, n in g.nodes.items():
        e = g.ends(d)
        if not e or e[0] is None or e[1] is None:
            continue
        a, k = e
        if g.gnd(a) and g.rail(k) and not PROTECT.search(f"{g.text(d)} {n.get('label') or ''}"):
            load = next((x for x, _ in g.on[k] if g.kind[x] in LOADS), None)
            sides = _load_sides(g, load) if load else None
            hint = (f"If {d} is meant as {load}'s flyback diode, put it across {load}: {d}.A on {g.name(sides[1])} (the switched side), "
                    f"{d}.K on {g.name(sides[0])}; otherwise remove it." if sides else f"Remove {d}, or put it across the load it should protect.")
            out.append(_f(WARNING, "diode_across_rail", d, f"{d} sits straight across {g.name(k)} and {g.name(a)} (K on {g.name(k)}, A on "
                          f"{g.name(a)}): it never conducts, so it is no flyback diode for anything", hint))
        elif g.rail(a) and g.gnd(k):
            out.append(_f(ERROR, "diode_across_rail", d, f"{d} is forward-biased straight across {g.name(a)}: A on {g.name(a)}, K on "
                          f"{g.name(k)}; it shorts the supply (the regulator or USB gives out, or the diode burns)",
                          f"Remove {d}; a flyback diode goes across its load (A on the switched side, K on the load's supply)."))
    return out


LIGHT_WORDS = [("warm white", re.compile(r"тёпл|тепл|\bwarm\b", re.I)), ("white", re.compile(r"бел(ый|ая|ое|ые|ого)|\b(cool|cold)?\s?white\b", re.I)),
               ("red", re.compile(r"красн|\bred\b", re.I)), ("green", re.compile(r"зел[её]н|\bgreen\b", re.I)),
               ("blue", re.compile(r"\bсин(ий|яя|ее|ие)|голуб|\bblue\b", re.I)), ("yellow", re.compile(r"ж[её]лт|янтар|\b(yellow|amber)\b", re.I))]


def _light_of(g: _G, nid: str) -> str | None:
    """The colour a LED really is: the primitive's colour, a chip's card (a 2700-3500 K white is warm)."""
    n = g.nodes[nid]
    if n.get("kind") == "led":
        c = str(n.get("color") or "green").lower()
        return c if c in catalog.LED_SERIES else "green"   # a colour with no part is bought green (catalog.resolve_basic)
    t = g.text(nid)
    m = re.search(r"\b(\d{4})\s?K\b", t)
    if m:
        return "warm white" if int(m[1]) <= 3700 else "white"
    return next((w for w, rx in LIGHT_WORDS[2:] if rx.search(t)), "white" if re.search(r"\bwhite\b", t, re.I) else None)


def _light_said(text: str) -> str | None:
    return next((w for w, rx in LIGHT_WORDS if rx.search(text or "")), None)


def _led_colour_rule(g: _G) -> list[dict[str, Any]]:
    """A LED must be the colour its label and its requirements say: a 'warm light' with a green LED on the order is not a night light."""
    out: list[dict[str, Any]] = []
    leds = [nid for nid in g.nodes if g.kind[nid] == "led"]
    for nid in leds:
        said, real = _light_said(str(g.nodes[nid].get("label") or "")), _light_of(g, nid)
        if said and real and said != real:
            out.append(_f(ERROR, "led_colour", nid, f"{nid} is labelled '{g.nodes[nid].get('label')}', and the part in the order is {real}",
                          f"use a {said} LED: a chip from search_parts ('{said} LED'), wired A/K, or relabel it if {real} is what you mean"))
    for r in g.doc.get("requirements") or []:
        if not isinstance(r, dict):
            continue
        mine = [nid for nid in r.get("parts") or [] if nid in leds]
        said = _light_said(str(r.get("text") or ""))
        real = {_light_of(g, nid) for nid in mine}
        if mine and said and None not in real and said not in real:
            out.append(_f(ERROR, "led_colour", mine[0], f"{r.get('id')} asks for '{str(r.get('text'))[:80]}', and its LEDs ({', '.join(mine[:6])}) are {', '.join(sorted(real))}",
                          f"use a {said} LED: a chip from search_parts ('{said} LED'), wired A/K"))
    return out


RULES = (_current, _unwired_inputs, _sockets, _led_colour_rule, _short_part, _battery_raw, _transistors, _gpio_overload, _buzzer_unwired, _gpio_short, _i2c_misuse, _strapping, _ws2812,
         _pullup_5v, _led, _supply_range, _accessory_supply, _flyback, _floating, _flyback_orientation, _sensor_divider, _supply_no_source, _load_unpowered, _diode_to_ground,
         _diode_across_rail, _requirements)


def check(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Every finding of the rules on a normalized fw.device/1 document (parts = device.resolve(doc)[0]): {code, ref, msg,
    severity, hint}, errors first. Never raises: a rule that trips over an odd document is skipped and logged."""
    try:
        g = _G(doc if isinstance(doc, dict) else {}, parts if isinstance(parts, dict) else {})
    except Exception:  # the checker never fails a write
        log.exception("device rules: unreadable document")
        return []
    found: list[dict[str, Any]] = []
    for rule in RULES:
        try:
            found += rule(g)
        except Exception:  # one broken rule never hides the others
            log.exception("device rule %s failed", rule.__name__)
    try:
        linted = {(w.get("code"), w.get("ref")) for w in device.lint(doc, parts or {})}
    except Exception:  # noqa: BLE001 - without lint nothing is deduplicated
        linted = set()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for f in found:
        dup = f.pop("_lint", None)
        key = (f["code"], f["ref"], f["msg"])
        if (dup and (dup, f["ref"]) in linted) or key in seen:
            continue
        seen.add(key)
        out.append(f)
    out.sort(key=lambda f: f["severity"] != ERROR)
    return out
