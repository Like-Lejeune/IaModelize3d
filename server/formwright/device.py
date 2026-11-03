"""Devices (fw.device/1): the node graph a whole device is designed in, and its deterministic compiler to a board.

A device is parts (nodes) and the nets between their pins. The designer (agent pack 'device') and the node editor in
the studio both edit this one document; neither writes coordinates. compile() turns it into a tscircuit TSX file:
  - parts on an edge (connectors, a module's own USB) get exact positions and rotations so their mouths face out,
  - everything else is left without coordinates, so tscircuit packs it next to the pins it connects to,
  - nets become traces (named nets through net.NAME, 5 V paths pin to pin at 0.4 mm),
  - the intent (edge of every port, the pin that drives each LED and button) is stated for the build to check,
and lists the LCSC footprints the PCB worker needs (catalog.easyeda), since the worker has no network.
build() runs it through the PCB pipeline, growing the board until placement and routing succeed.

Document:
  {schema: 'fw.device/1', title, summary,
   board: {w?, h?, holes: true},
   nodes: [{id: 'U1', kind, label?, value?, package?, color?, lcsc?, module?, pins? (header labels), edge?, ui?: [x, y]}],
   nets:  [{name?: 'GND', pins: ['U1.GND', 'U2.GND', 'C1.2']}],
   firmware?: {lang, files: {name: text}}}
Kinds: module (by part number, MODULES), chip (any LCSC part with an EasyEDA footprint), resistor, capacitor, led, diode,
button, header, usb_c, jst, hole. Pin references are '<node>.<pin>'; for a chip a duplicated pin name ('GND' twice) is
one reference for all of them.
"""
from __future__ import annotations

import asyncio
import copy
import math
import re
from typing import Any

from . import catalog

SCHEMA = "fw.device/1"
MAX_NODES = 40
MAX_W = 100.0
EDGES = ("-x", "+x", "-y", "+y")
EDGE_ALIASES = {"left": "-x", "right": "+x", "bottom": "-y", "top": "+y", "-x": "-x", "+x": "+x", "-y": "-y", "+y": "+y"}
# nets shown as labels in the editor rather than wires, and the ones whose path is widened
POWER_NET = re.compile(r"^(GND|AGND|V3V3|V3V|V1V8|V5|V5V|VBUS|VSYS|VBAT|VIN|VCC|VDD|V12|V9)$", re.I)
WIDE_NET = re.compile(r"^(V5|V5V|VBUS|VSYS|VBAT|VIN|V12|V9)$", re.I)
GROUND = re.compile(r"^(GND|AGND|VSS)$", re.I)

# development boards soldered on headers: their own USB faces the edge named in the node (default top)
MODULES: dict[str, dict[str, Any]] = {
    "113991054": {
        "name": "Seeed XIAO ESP32-C3", "mcu": "ESP32-C3", "footprint": "dip14_w15.24mm", "size": [17.8, 21.0], "depth": 10.5,
        "pins": ["D0", "D1", "D2", "D3", "SDA", "SCL", "TX", "RX", "SCK", "MISO", "MOSI", "V3V3", "GND", "V5"],
        "aliases": {"D4": "SDA", "D5": "SCL", "D6": "TX", "D7": "RX", "D8": "SCK", "D9": "MISO", "D10": "MOSI", "3V3": "V3V3", "5V": "V5"},
        "price_usd": 4.99, "wireless": ["Wi-Fi", "BLE 5"], "fw": "arduino-esp32 (board 'XIAO_ESP32C3')",
        "url": "https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/",
    },
    "113991114": {
        "name": "Seeed XIAO ESP32-S3", "mcu": "ESP32-S3", "footprint": "dip14_w15.24mm", "size": [17.8, 21.0], "depth": 10.5,
        "pins": ["D0", "D1", "D2", "D3", "SDA", "SCL", "TX", "RX", "SCK", "MISO", "MOSI", "V3V3", "GND", "V5"],
        "aliases": {"D4": "SDA", "D5": "SCL", "D6": "TX", "D7": "RX", "D8": "SCK", "D9": "MISO", "D10": "MOSI", "3V3": "V3V3", "5V": "V5"},
        "price_usd": 7.49, "wireless": ["Wi-Fi", "BLE 5"], "fw": "arduino-esp32 (board 'XIAO_ESP32S3')",
        "url": "https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/",
    },
    "SC0915": {
        "name": "Raspberry Pi Pico", "mcu": "RP2040", "footprint": "dip40_w17.78mm", "size": [21.0, 51.0], "depth": 25.75,
        "pins": ["GP0", "GP1", "GND3", "GP2", "GP3", "GP4", "GP5", "GND8", "GP6", "GP7", "GP8", "GP9", "GND13", "GP10", "GP11", "GP12", "GP13",
                 "GND18", "GP14", "GP15", "GP16", "GP17", "GND23", "GP18", "GP19", "GP20", "GP21", "GND28", "GP22", "RUN", "GP26", "GP27",
                 "AGND", "GP28", "ADC_VREF", "V3V3", "V3V3_EN", "GND", "VSYS", "VBUS"],
        "aliases": {"3V3": "V3V3"}, "price_usd": 4.0, "wireless": [], "fw": "MicroPython or arduino-pico",
        "url": "https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf",
    },
    "SC0918": {
        "name": "Raspberry Pi Pico W", "mcu": "RP2040", "footprint": "dip40_w17.78mm", "size": [21.0, 51.0], "depth": 25.75,
        "pins": ["GP0", "GP1", "GND3", "GP2", "GP3", "GP4", "GP5", "GND8", "GP6", "GP7", "GP8", "GP9", "GND13", "GP10", "GP11", "GP12", "GP13",
                 "GND18", "GP14", "GP15", "GP16", "GP17", "GND23", "GP18", "GP19", "GP20", "GP21", "GND28", "GP22", "RUN", "GP26", "GP27",
                 "AGND", "GP28", "ADC_VREF", "V3V3", "V3V3_EN", "GND", "VSYS", "VBUS"],
        "aliases": {"3V3": "V3V3"}, "price_usd": 6.0, "wireless": ["Wi-Fi", "BLE"], "fw": "MicroPython or arduino-pico",
        "url": "https://datasheets.raspberrypi.com/picow/pico-w-datasheet.pdf",
    },
}
# GND pins of a module are one reference: 'U1.GND' reaches all of a Pico's eight
for _m in MODULES.values():
    _m["groups"] = {"GND": [p for p in _m["pins"] if re.match(r"^A?GND\d*$", p) and p != "AGND"]}

USB_C_LABELS = {"pin1": "SH1", "pin2": "SH2", "pin3": "SH3", "pin4": "SH4", "pin5": "GND_A", "pin6": "VBUS_A", "pin7": "SBU2", "pin8": "CC1",
                "pin9": "DN2", "pin10": "DP1", "pin11": "DN1", "pin12": "DP2", "pin13": "SBU1", "pin14": "CC2", "pin15": "VBUS_B", "pin16": "GND_B"}
PRIMS: dict[str, dict[str, Any]] = {
    "resistor": {"prefix": "R", "pins": ["1", "2"], "tsx": {"1": "pin1", "2": "pin2"}},
    "capacitor": {"prefix": "C", "pins": ["1", "2"], "tsx": {"1": "pin1", "2": "pin2"}},
    "led": {"prefix": "LED", "pins": ["A", "K"], "tsx": {"A": "anode", "K": "cathode"}},
    "diode": {"prefix": "D", "pins": ["A", "K"], "tsx": {"A": "anode", "K": "cathode"}},
    "button": {"prefix": "SW", "pins": ["A", "B"], "tsx": {"A": "pin1", "B": "pin3"}},
    "usb_c": {"prefix": "J", "pins": ["VBUS", "GND", "CC1", "CC2", "DP", "DM"],
              "tsx": {"VBUS": "VBUS_A", "GND": "GND_A", "CC1": "CC1", "CC2": "CC2", "DP": "DP1", "DM": "DN1"}},
    "jst": {"prefix": "J", "pins": ["P1", "P2"], "tsx": {"P1": "pin1", "P2": "pin2"}},
    "hole": {"prefix": "H", "pins": [], "tsx": {}},
}
KINDS = ("module", "chip", "header", *PRIMS)
EDGE_KINDS = ("usb_c", "header", "jst", "module")
PASSIVE_PKG = ("0402", "0603", "0805", "1206")
# courtyard w x h at rotation 0, for the board-size estimate and the edge layout
SIZE = {"0402": (1.6, 0.9), "0603": (2.2, 1.2), "0805": (2.8, 1.6), "1206": (3.8, 2.0), "led": (2.2, 1.2), "diode": (4.5, 2.0),
        "button": (7.0, 9.0), "usb_c": (10.4, 8.4), "jst": (7.0, 6.0), "hole": (7.2, 7.2)}
# centre distance from the edge for a part whose body ends at the edge (usbcmidmount body spans -5.5..+2.9 around its origin)
DEPTH = {"usb_c": 5.5, "header": 2.5, "jst": 3.6}
# traces the person drew on the board: pad to pad on one net, corners in mm from the board's centre (+y up)
ROUTE_MAX = 200
ROUTE_POINTS = 64
PORT_REF = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z0-9_]+)$")
# a primitive's pads as the board names them (the TSX names an LED's pins anode/cathode, the board pin1/pin2); a
# button's pins 1-2 and 3-4 are one contact each; a USB-C receptacle's twin rows and shell go with the pin it names
PORT_NAMES = {"led": {"A": ["pin1"], "K": ["pin2"]}, "diode": {"A": ["pin1"], "K": ["pin2"]},
              "button": {"A": ["pin1", "pin2"], "B": ["pin3", "pin4"]}}
USB_PORTS = {"VBUS": ["VBUS_A", "VBUS_B"], "GND": ["GND_A", "GND_B", "SH1"], "DP": ["DP1", "DP2"], "DM": ["DN1", "DN2"]}
# areas the person drew on the board: a copper pour of a net (a rectangle, or the whole board) and a keepout (no copper)
ZONE_MAX = 24
POUR_CLEARANCE_MM = 0.3


class DeviceError(Exception):
    pass


def ident(name: str) -> str:
    s = catalog.safe_label(name)
    return s if re.match(r"^[A-Za-z_]", s) else f"N{s}"


# ------------------------------------------------------------------ the document
def blank(title: str = "Device") -> dict[str, Any]:
    return {"schema": SCHEMA, "title": title, "summary": "", "board": {"holes": True}, "nodes": [], "nets": []}


def _edge(v: Any) -> str | None:
    return EDGE_ALIASES.get(str(v or "").strip().lower()) if v else None


def normalize(doc: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """A cleaned copy of a device document and what had to be dropped or fixed ({code, ref, msg}). Never raises on content:
    a broken node or pin reference becomes an issue, so the editor and the designer always get a document back."""
    issues: list[dict[str, str]] = []
    if not isinstance(doc, dict):
        raise DeviceError("a device document is an object {schema, title, nodes, nets}")
    out = blank(str(doc.get("title") or "Device")[:80])
    out["summary"] = str(doc.get("summary") or "")[:600]
    b = doc.get("board") if isinstance(doc.get("board"), dict) else {}
    out["board"] = {"holes": b.get("holes", True) is not False}
    for k in ("w", "h"):
        try:
            if b.get(k) is not None:
                out["board"][k] = round(min(MAX_W, max(10.0, float(b[k]))), 1)
        except (TypeError, ValueError):
            issues.append({"code": "board_size", "ref": k, "msg": f"board.{k} must be a number in mm"})
    seen: set[str] = set()
    for raw in doc.get("nodes") or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in KINDS:
            issues.append({"code": "unknown_kind", "ref": str(raw.get("id")), "msg": f"kind {kind!r} is not one of {', '.join(KINDS)}"})
            continue
        nid = ident(str(raw.get("id") or ""))
        if not raw.get("id") or nid in seen:
            prefix = PRIMS.get(kind, {}).get("prefix") or ("J" if kind == "header" else "U")
            n = 1
            while f"{prefix}{n}" in seen:
                n += 1
            if raw.get("id"):
                issues.append({"code": "duplicate_id", "ref": nid, "msg": f"two nodes are called {nid}: the second is now {prefix}{n}"})
            nid = f"{prefix}{n}"
        seen.add(nid)
        node: dict[str, Any] = {"id": nid, "kind": kind}
        for k in ("label", "note"):
            if raw.get(k):
                node[k] = str(raw[k])[:80 if k == "label" else 300]
        if kind in ("resistor", "capacitor"):
            node["value"] = str(raw.get("value") or ("10k" if kind == "resistor" else "100nF")).strip()[:16]
            pkg = str(raw.get("package") or "0603")
            node["package"] = pkg if pkg in PASSIVE_PKG else "0603"
        if kind == "led":
            node["color"] = str(raw.get("color") or "green").lower()[:12]
        if kind == "module":
            mpn = str(raw.get("module") or raw.get("mpn") or "").strip()
            if mpn not in MODULES:
                by_name = next((k for k, m in MODULES.items() if mpn and mpn.lower() in m["name"].lower()), None)
                if not by_name:
                    issues.append({"code": "unknown_module", "ref": nid, "msg": f"module {mpn!r} is not known; use one of "
                                   + ", ".join(f"{k} ({m['name']})" for k, m in MODULES.items())})
                    continue
                mpn = by_name
            node["module"] = mpn
        if kind == "chip":
            code = catalog.norm_code(raw.get("lcsc"))
            if not code:
                issues.append({"code": "no_lcsc", "ref": nid, "msg": "a chip needs its LCSC number (lcsc: 'C92489'): find it with search_parts"})
                continue
            node["lcsc"] = code
            for k in ("mpn", "package"):
                if raw.get(k):
                    node[k] = str(raw[k])[:60]
        if kind == "header":
            pins = [ident(p) for p in (raw.get("pins") or []) if str(p).strip()][:20]
            if len(pins) < 1:
                pins = ["P1", "P2", "P3", "P4"][: max(1, min(20, int(raw.get("count") or 4)))]
            # pin labels of a header must be unique
            uniq: list[str] = []
            for p in pins:
                q, i = p, 2
                while q in uniq:
                    q, i = f"{p}_{i}", i + 1
                uniq.append(q)
            node["pins"] = uniq
        e = _edge(raw.get("edge"))
        if e and kind in EDGE_KINDS:
            node["edge"] = e
        elif kind == "module":
            node["edge"] = "+y"
        ui = raw.get("ui")
        if isinstance(ui, (list, tuple)) and len(ui) == 2 and all(isinstance(v, (int, float)) for v in ui):
            node["ui"] = [round(float(ui[0]), 1), round(float(ui[1]), 1)]
        pin = raw.get("pcb")
        if isinstance(pin, dict) and all(isinstance(pin.get(k), (int, float)) for k in ("x", "y")):
            # placed by hand on the board: centre in mm from the board's centre, +y up, rotation in quarter turns
            node["pcb"] = {"x": round(float(pin["x"]), 2), "y": round(float(pin["y"]), 2),
                           "rot": int(round(float(pin.get("rot") or 0) / 90)) * 90 % 360}
        out["nodes"].append(node)
    if len(out["nodes"]) > MAX_NODES:
        issues.append({"code": "too_many_parts", "ref": "", "msg": f"{len(out['nodes'])} parts: a board here holds at most {MAX_NODES}"})
        out["nodes"] = out["nodes"][:MAX_NODES]

    # nets: every pin reference checked, nets sharing a pin merged, names cleaned
    by_id = {n["id"]: n for n in out["nodes"]}
    groups: list[tuple[str | None, list[str]]] = []
    for raw in doc.get("nets") or []:
        if not isinstance(raw, dict):
            continue
        name = ident(raw["name"]) if raw.get("name") else None
        pins: list[str] = []
        for ref in raw.get("pins") or []:
            r = resolve_ref(by_id, str(ref))
            if isinstance(r, str):
                if r not in pins:
                    pins.append(r)
            else:
                issues.append({"code": "bad_pin", "ref": str(ref)[:40], "msg": r["msg"]})
        if pins:
            groups.append((name, pins))
    out["nets"] = _merge(groups, issues)
    routes: list[dict[str, Any]] = []
    for raw in (doc.get("routes") or [])[:ROUTE_MAX]:
        r = _route(raw, by_id)
        if r is None:
            issues.append({"code": "bad_route", "ref": str((raw or {}).get("from") if isinstance(raw, dict) else raw)[:40],
                           "msg": "a hand trace is {from: 'R1.pin1', to: 'U1.D10', layer, width, points: [{x, y, via?}]} between two parts of the device"})
        elif r not in routes:
            routes.append(r)
    if routes:
        out["routes"] = routes
    zones: list[dict[str, Any]] = []
    for raw in (doc.get("zones") or [])[:ZONE_MAX]:
        z = _zone(raw, out["nets"])
        if isinstance(z, str):
            issues.append({"code": "bad_zone", "ref": "zones", "msg": z})
        elif z not in zones:
            zones.append(z)
    if zones:
        out["zones"] = zones
    if isinstance(doc.get("firmware"), dict):
        fw = doc["firmware"]
        files = {str(k)[:60]: str(v)[:40000] for k, v in (fw.get("files") or {}).items() if isinstance(v, str)}
        if files:
            out["firmware"] = {"lang": str(fw.get("lang") or "arduino")[:30], "files": dict(list(files.items())[:6]),
                               **({"notes": str(fw["notes"])[:1200]} if fw.get("notes") else {})}
    return out, issues


def _route(raw: Any, by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """One hand trace cleaned, or None: both ends a pad of a part ('R3.pin1', as the board names it), the layer it leaves
    `from` on, its width, the corners in order (a via switches the layer)."""
    if not isinstance(raw, dict):
        return None
    ends = []
    for k in ("from", "to"):
        m = PORT_REF.match(str(raw.get(k) or "").strip())
        if not m or m[1] not in by_id:
            return None
        ends.append(f"{m[1]}.{m[2]}")
    if ends[0] == ends[1]:
        return None
    pts: list[dict[str, Any]] = []
    for q in (raw.get("points") or [])[:ROUTE_POINTS]:
        if isinstance(q, dict) and all(isinstance(q.get(k), (int, float)) and math.isfinite(q[k]) and abs(q[k]) <= MAX_W for k in ("x", "y")):
            pts.append({"x": round(float(q["x"]), 3), "y": round(float(q["y"]), 3), **({"via": True} if q.get("via") else {})})
    try:
        width = round(min(2.0, max(0.15, float(raw.get("width") or 0.25))), 2)
    except (TypeError, ValueError):
        width = 0.25
    return {"from": ends[0], "to": ends[1], "layer": "bottom" if raw.get("layer") == "bottom" else "top", "width": width, "points": pts}


def _zone(raw: Any, nets: list[dict[str, Any]]) -> dict[str, Any] | str:
    """One zone cleaned, or why not: {kind: 'pour', net, layer, rect?} (no rect: the whole board) or
    {kind: 'keepout', layers, rect}; rect is [x0, y0, x1, y1] in mm from the board's centre."""
    if not isinstance(raw, dict) or raw.get("kind") not in ("pour", "keepout"):
        return "a zone is {kind: 'pour', net: 'GND', layer: 'bottom', rect?: [x0, y0, x1, y1]} or {kind: 'keepout', layers: ['top'], rect}"
    rect = raw.get("rect")
    if rect is not None:
        if not (isinstance(rect, (list, tuple)) and len(rect) == 4 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in rect)):
            return "zone.rect is [x0, y0, x1, y1] in mm"
        x0, y0, x1, y1 = (round(float(v), 2) for v in rect)
        rect = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        if rect[2] - rect[0] < 0.5 or rect[3] - rect[1] < 0.5:
            return "a zone is at least 0.5 x 0.5 mm"
    if raw["kind"] == "pour":
        name = ident(str(raw.get("net") or "GND"))
        net = next((n for n in nets if n.get("name") == name), None)
        if net is None:
            return f"pour on {name}: the device has no net called {name}"
        if WIDE_NET.match(name):
            return f"pour on {name}: a supply routed wide (V5, VBUS, VBAT ...) cannot be poured yet; pour GND or V3V3"
        return {"kind": "pour", "net": name, "layer": "top" if raw.get("layer") == "top" else "bottom", **({"rect": rect} if rect else {})}
    if not rect:
        return "a keepout needs its rect"
    layers = [lay for lay in ("top", "bottom") if lay in (raw.get("layers") or [raw.get("layer") or "top"])] or ["top"]
    return {"kind": "keepout", "layers": layers, "rect": rect}


def ports_of(node: dict[str, Any], part: dict[str, Any], pin: str) -> list[str]:
    """The board's pad names one device pin stands for (what circuit.json and the hand traces call them)."""
    k = node["kind"]
    if k in PORT_NAMES:
        return PORT_NAMES[k].get(pin, [])
    if k == "usb_c":
        return USB_PORTS.get(pin) or [PRIMS["usb_c"]["tsx"][pin]]
    return _tsx_pins(node, part, pin)


def port_nets(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Every wired pad ('U2.GND_7') and the index of its net in doc['nets']."""
    by_id = {n["id"]: n for n in doc["nodes"]}
    out: dict[str, int] = {}
    for i, net in enumerate(doc["nets"]):
        for ref in net["pins"]:
            nid, pin = ref.split(".", 1)
            if nid in by_id:
                for port in ports_of(by_id[nid], parts.get(nid, {}), pin):
                    out[f"{nid}.{port}"] = i
    return out


def route_problems(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Hand traces the build leaves out: an end on no net, or two nets joined (the copper would short them)."""
    nets = port_nets(doc, parts)
    out: list[dict[str, str]] = []
    for r in doc.get("routes") or []:
        a, b = nets.get(r["from"]), nets.get(r["to"])
        ref = f"{r['from']}-{r['to']}"
        if a is None or b is None:
            off = r["from"] if a is None else r["to"]
            out.append({"code": "route_off_net", "ref": ref, "msg": f"hand trace {ref}: {off} is on no net now; the trace is left out"})
        elif a != b:
            na, nb = (doc["nets"][a].get("name") or "unnamed", doc["nets"][b].get("name") or "unnamed")
            out.append({"code": "route_shorts", "ref": ref, "msg": f"hand trace {ref} joins nets {na} and {nb}: left out, it would short them"})
    return out


def pins_of(node: dict[str, Any], part: dict[str, Any] | None = None) -> list[str]:
    """The pin names a node offers (what '<id>.<pin>' may say)."""
    k = node["kind"]
    if k in PRIMS:
        return list(PRIMS[k]["pins"])
    if k == "header":
        return list(node.get("pins") or [])
    if k == "module":
        return list(MODULES[node["module"]]["pins"])
    if k == "chip":
        labels = [p["label"] for p in (part or {}).get("pins") or []]
        return list(dict.fromkeys(catalog.base_label(lb) for lb in labels)) if labels else list(node.get("pin_names") or [])
    return []


def resolve_ref(by_id: dict[str, dict[str, Any]], ref: str) -> str | dict[str, str]:
    """'U1.D10' -> 'U1.MOSI' (a module alias), 'R1.pin1' -> 'R1.1', 'LED1.anode' -> 'LED1.A'; an error dict otherwise. Chip pins
    are checked later, against the part card (resolve())."""
    if "." not in ref:
        return {"msg": f"{ref!r} is not '<node>.<pin>'"}
    nid, pin = ref.split(".", 1)
    nid, pin = nid.strip(), pin.strip()
    node = by_id.get(nid) or by_id.get(ident(nid))
    if node is None:
        return {"msg": f"{ref}: there is no node {nid}"}
    k = node["kind"]
    if k == "chip":
        return f"{node['id']}.{catalog.safe_label(pin)}"
    names = pins_of(node)
    up = {p.upper(): p for p in names}
    p = pin.upper()
    alias = {"PIN1": "1", "PIN2": "2", "ANODE": "A", "CATHODE": "K", "+": "1" if k in ("resistor", "capacitor") else "A", "-": "2" if k in ("resistor", "capacitor") else "K"}
    if k == "usb_c":
        alias.update({"D+": "DP", "D-": "DM", "DN": "DM", "VBUS_A": "VBUS", "5V": "VBUS", "V5": "VBUS"})
    if k == "jst":
        alias.update({"+": "P1", "-": "P2", "PIN1": "P1", "PIN2": "P2", "1": "P1", "2": "P2", "VBAT": "P1", "GND": "P2"})
    if k == "button":
        alias.update({"1": "A", "2": "B", "PIN1": "A", "PIN3": "B"})
    if k == "module":
        alias.update({a.upper(): t for a, t in MODULES[node["module"]]["aliases"].items()})
        alias.update({f"GPIO{n[2:]}": n for n in names if n.startswith("GP") and n[2:].isdigit()})
    if p in up:
        return f"{node['id']}.{up[p]}"
    if p in alias and alias[p].upper() in up:
        return f"{node['id']}.{up[alias[p].upper()]}"
    return {"msg": f"{ref}: {node['id']} ({k}) has no pin {pin}; its pins are {', '.join(names[:40])}"}


def _merge(groups: list[tuple[str | None, list[str]]], issues: list[dict[str, str]]) -> list[dict[str, Any]]:
    parent = list(range(len(groups)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for i, (name, pins) in enumerate(groups):
        # the same name twice is one net too
        for p in pins + ([f"net:{name}"] if name else []):
            if p in owner:
                parent[find(i)] = find(owner[p])
            else:
                owner[p] = i
    merged: dict[int, dict[str, Any]] = {}
    for i, (name, pins) in enumerate(groups):
        r = find(i)
        m = merged.setdefault(r, {"names": [], "pins": []})
        if name and name not in m["names"]:
            m["names"].append(name)
        m["pins"] += [p for p in pins if p not in m["pins"]]
    out: list[dict[str, Any]] = []
    for m in merged.values():
        # two supplies on one net is a short; a ground called twice (GND, GND2) or a signal joined to its rail is just one net
        rails = {n.upper() for n in m["names"] if POWER_NET.match(n) and not GROUND.match(n)}
        if len(rails) > 1:
            issues.append({"code": "supplies_shorted", "ref": "+".join(m["names"]), "msg": f"nets {', '.join(m['names'])} share a pin, so these "
                           f"supplies are shorted: take the pin off one of them"})
        if any(GROUND.match(n) for n in m["names"]):
            m["names"].sort(key=lambda n: not GROUND.match(n))
        net: dict[str, Any] = {"pins": m["pins"]}
        if m["names"]:
            net["name"] = m["names"][0]
        out.append(net)
    # one name per net
    used: set[str] = set()
    for net in out:
        if net.get("name") in used:
            net.pop("name")
        if net.get("name"):
            used.add(net["name"])
    return out


# ------------------------------------------------------------------ parts: catalogue lookups
async def resolve(doc: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Per node: what it is made of {lcsc, mpn, package, prices, stock, basic, size, h, pins, pads, tht, raw (chips)}.
    Chips come from catalog.info (EasyEDA footprint + JLCPCB stock), primitives from resolve_basic."""
    issues: list[dict[str, str]] = []
    parts: dict[str, dict[str, Any]] = {}

    async def one(node: dict[str, Any]) -> None:
        k, nid = node["kind"], node["id"]
        try:
            if k == "chip":
                card, raw = await asyncio.gather(catalog.info(node["lcsc"]), catalog.easyeda(node["lcsc"]))
                parts[nid] = {**card, "raw": raw, "pads": catalog.pads_of(raw), "box": catalog.box_of(raw)}
            elif k in ("resistor", "capacitor"):
                parts[nid] = await catalog.resolve_basic(k, node["value"], node["package"]) or {}
            elif k == "led":
                parts[nid] = await catalog.resolve_basic("led", color=node.get("color", "green")) or {}
            elif k == "diode":
                parts[nid] = await catalog.resolve_basic("schottky") or {}
            elif k in ("usb_c", "jst"):
                parts[nid] = await catalog.resolve_basic("usb_c" if k == "usb_c" else "jst2") or {}
            elif k in ("header", "button"):
                parts[nid] = await catalog.resolve_basic(k) or {}
            elif k == "module":
                m = MODULES[node["module"]]
                parts[nid] = {"mpn": m["name"], "module": True, "prices": [{"qty": 1, "usd": m["price_usd"]}], "stock": None, "url": m["url"]}
            else:
                parts[nid] = {}
        except catalog.CatalogError as e:
            issues.append({"code": "part_unavailable", "ref": nid, "msg": str(e)})
            parts[nid] = {"error": str(e)}

    await asyncio.gather(*(one(n) for n in doc["nodes"]))
    # chip pin references against the real pinout
    by_id = {n["id"]: n for n in doc["nodes"]}
    for net in doc["nets"]:
        keep = []
        for ref in net["pins"]:
            nid, pin = ref.split(".", 1)
            node = by_id.get(nid)
            if node and node["kind"] == "chip" and parts.get(nid, {}).get("pins"):
                names = pins_of(node, parts[nid])
                match = next((n for n in names if n.upper() == pin.upper()), None)
                if match is None:
                    issues.append({"code": "bad_pin", "ref": ref, "msg": f"{ref}: {nid} ({parts[nid].get('mpn')}) has no pin {pin}; its pins are "
                                   + ", ".join(n for n in names if not n.upper().startswith("NC"))[:400]})
                    continue
                ref = f"{nid}.{match}"
            keep.append(ref)
        net["pins"] = keep
    doc["nets"] = [n for n in doc["nets"] if len(n["pins"]) >= 2 or n.get("name")]
    return parts, issues


def lint(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Design checks a netlist can answer before any routing: unconnected parts, a USB-C without CC pull-downs, an LED
    without a resistor, chips without decoupling, single-pin nets. Warnings: the designer decides."""
    out: list[dict[str, str]] = []
    net_of: dict[str, dict[str, Any]] = {}
    for net in doc["nets"]:
        for p in net["pins"]:
            net_of[p] = net
    for node in doc["nodes"]:
        nid, k = node["id"], node["kind"]
        mine = [p for p in net_of if p.split(".", 1)[0] == nid]
        if k != "hole" and not mine:
            out.append({"code": "unconnected", "ref": nid, "msg": f"{nid} is not connected to anything"})
            continue
        if k == "usb_c":
            for cc in ("CC1", "CC2"):
                if f"{nid}.{cc}" not in net_of:
                    out.append({"code": "usb_cc", "ref": nid, "msg": f"{nid}.{cc} needs 5.1k to GND, or a USB-C charger gives no 5 V"})
        if k == "led":
            a, kk = net_of.get(f"{nid}.A"), net_of.get(f"{nid}.K")
            pins = (a or {}).get("pins", []) + (kk or {}).get("pins", [])
            if not any(p.split(".")[0] in {n["id"] for n in doc["nodes"] if n["kind"] == "resistor"} for p in pins):
                out.append({"code": "led_resistor", "ref": nid, "msg": f"{nid} has no series resistor (1k from the GPIO to its A pin)"})
        if k == "chip":
            supply = [p for p in mine if POWER_NET.match((net_of[p].get("name") or "")) and not GROUND.match(net_of[p].get("name") or "")]
            caps = {n["id"] for n in doc["nodes"] if n["kind"] == "capacitor"}
            if supply and not any(q.split(".")[0] in caps for p in supply for q in net_of[p]["pins"]):
                out.append({"code": "decoupling", "ref": nid, "msg": f"{nid} has no capacitor on its supply: add 100nF from {supply[0].split('.')[1]} to GND"})
    for net in doc["nets"]:
        if len(net["pins"]) < 2:
            out.append({"code": "single_pin_net", "ref": net.get("name") or net["pins"][0], "msg": f"net {net.get('name') or net['pins'][0]} has only one pin"})
    return out + route_problems(doc, parts)


# ------------------------------------------------------------------ geometry: size and edges
def _footprint_size(node: dict[str, Any], part: dict[str, Any]) -> tuple[float, float]:
    k = node["kind"]
    if k in ("resistor", "capacitor"):
        return SIZE[node.get("package", "0603")]
    if k == "header":
        n = len(node.get("pins") or [])
        return (2.54 * n + 0.8, 3.5)
    if k == "module":
        w, h = MODULES[node["module"]]["size"]
        return (w, h)
    if k == "chip":
        s = part.get("size_mm") or [5.0, 5.0]
        return (s[0] + 1.0, s[1] + 1.0)
    return SIZE.get(k, (3.0, 3.0))


def _along(node: dict[str, Any], part: dict[str, Any]) -> tuple[float, float]:
    """(length along its edge, depth into the board) of an edge part."""
    k = node["kind"]
    w, h = _footprint_size(node, part)
    if k == "usb_c":
        return 10.4, 8.4
    if k == "module":
        return w, h
    return (max(w, h), min(w, h))


def estimate(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> tuple[float, float]:
    """Board width and height (mm) with room to pack and route: edge parts must fit side by side, the free parts get about
    three times their own area. Rounded up to whole millimetres."""
    holes = doc["board"].get("holes", True)
    corner = 8.0 if holes else 2.0
    need = {e: 0.0 for e in EDGES}
    depth = {e: 0.0 for e in EDGES}
    fixed = free = 0.0
    for n in doc["nodes"]:
        if n["kind"] == "hole":
            continue
        w, h = _footprint_size(n, parts.get(n["id"], {}))
        if n.get("edge"):
            a, d = _along(n, parts.get(n["id"], {}))
            need[n["edge"]] += a + 2.0
            depth[n["edge"]] = max(depth[n["edge"]], d)
            fixed += w * h * 1.25
        else:
            free += w * h * (2.6 if n["kind"] in ("resistor", "capacitor", "led") else 3.0)
    area = (fixed + free) * 1.15 + 60
    W = max(need["-y"], need["+y"]) + 2 * corner
    H = max(need["-x"], need["+x"]) + 2 * corner
    # a side edge part spans the depth of the top/bottom ones too
    W = max(W, depth["-x"] + depth["+x"] + 10)
    H = max(H, depth["-y"] + depth["+y"] + 10)
    side = math.sqrt(area)
    W, H = max(W, side * 0.9, 24.0), max(H, side * 0.9, 24.0)
    if W * H < area:
        f = math.sqrt(area / (W * H))
        W, H = W * f, H * f
    b = doc["board"]
    return float(min(MAX_W, b.get("w") or math.ceil(W))), float(min(MAX_W, b.get("h") or math.ceil(H)))


def _placement(node: dict[str, Any], part: dict[str, Any], W: float, H: float, slot: float) -> dict[str, float]:
    """pcbX/pcbY/pcbRotation of an edge part whose slot centre lies `slot` mm along its edge (from the edge's middle)."""
    k, e = node["kind"], node["edge"]
    if k == "module":
        d = MODULES[node["module"]]["depth"]
        rot = {"+y": 0, "-x": 90, "-y": 180, "+x": 270}[e]
    else:
        d = DEPTH.get(k, 3.0)
        if k == "usb_c":
            rot = {"-y": 0, "+x": 90, "+y": 180, "-x": 270}[e]
        else:
            rot = 0 if e in ("-y", "+y") else 90
    if e == "+y":
        x, y = slot, H / 2 - d
    elif e == "-y":
        x, y = slot, -(H / 2 - d)
    elif e == "+x":
        x, y = W / 2 - d, slot
    else:
        x, y = -(W / 2 - d), slot
    return {"pcbX": round(x, 2), "pcbY": round(y, 2), "pcbRotation": rot}


def layout_edges(doc: dict[str, Any], parts: dict[str, dict[str, Any]], W: float, H: float) -> dict[str, dict[str, float]]:
    """Edge parts spread evenly along their edge, clear of the corner holes."""
    holes = doc["board"].get("holes", True)
    corner = 7.5 if holes else 1.5
    out: dict[str, dict[str, float]] = {}
    for e in EDGES:
        on = [n for n in doc["nodes"] if n.get("edge") == e]
        if not on:
            continue
        L = W if e in ("-y", "+y") else H
        lens = [_along(n, parts.get(n["id"], {}))[0] for n in on]
        usable = L - 2 * corner
        gap = max(1.0, (usable - sum(lens)) / (len(on) + 1))
        pos = -usable / 2 + gap
        for n, ln in zip(on, lens):
            centre = pos + ln / 2
            if len(on) == 1:
                centre = 0.0
            out[n["id"]] = _placement(n, parts.get(n["id"], {}), W, H, centre)
            pos += ln + gap
    return out


# ------------------------------------------------------------------ compile to tscircuit
def _attr(v: Any) -> str:
    if isinstance(v, (int, float)):
        return "{" + (str(int(v)) if float(v).is_integer() else str(round(float(v), 2))) + "}"
    return '"' + str(v).replace('"', "'") + '"'


def _spn(part: dict[str, Any]) -> str:
    return f' supplierPartNumbers={{{{ jlcpcb: ["{part["lcsc"]}"] }}}}' if part.get("lcsc") else ""


def _pos(p: dict[str, float] | None) -> str:
    if not p:
        return ""
    s = f" pcbX={_attr(p['pcbX'])} pcbY={_attr(p['pcbY'])}"
    return s + (f" pcbRotation={_attr(p['pcbRotation'])}" if p.get("pcbRotation") else "")


def _tsx_pins(node: dict[str, Any], part: dict[str, Any], pin: str) -> list[str]:
    """The TSX pin labels one device pin stands for: a chip's 'GND' is every pin called GND, a Pico's 'GND' all eight."""
    k = node["kind"]
    if k in PRIMS:
        return [PRIMS[k]["tsx"][pin]]
    if k == "module":
        return MODULES[node["module"]]["groups"].get(pin) or [pin]
    if k == "chip":
        labels = [p["label"] for p in part.get("pins") or []]
        group = [lb for lb in labels if catalog.base_label(lb) == pin]
        return group or [pin]
    return [pin]


# (pin offset from the centre, courtyard half width, courtyard half length) of a chip capacitor at rotation 0
CAP_GEOM = {"0402": (0.5, 0.45, 0.8), "0603": (0.8, 0.6, 1.1), "0805": (0.95, 0.8, 1.4), "1206": (1.4, 1.0, 1.9)}
PACK_GAP_MM = 1.6           # between packed parts: room for traces, so the router does not squeeze past pads
DECOUPLING_MAX_MM = 10.0   # placed at its supply pin by the compiler; the ground pin may sit across a small package
CAP_GAP = 0.6               # between the chip's outline and the capacitor's courtyard
BULK_MAX_MM = 12.0          # a supply capacitor with no chip to sit by (a module decouples itself): anywhere near
HAND_MAX_MM = 150.0         # a capacitor routed by hand: the person's lengths (no limit would mean tscircuit's own 1 mm)


def decoupling(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> tuple[dict[str, list[tuple[str, str, str]]], set[str]]:
    """Which chip each supply-to-ground capacitor serves: {chip: [(cap, chip pin label, cap pin on the supply)]}, and the
    supply capacitors no chip with a known footprint takes (bulk). A capacitor whose role names a chip ('U2 decoupling')
    goes to that chip; otherwise to the chip on its supply with the fewest capacitors so far."""
    net_of: dict[str, dict[str, Any]] = {}
    for net in doc["nets"]:
        for p in net["pins"]:
            net_of[p] = net
    by_id = {n["id"]: n for n in doc["nodes"]}
    plan: dict[str, list[tuple[str, str, str]]] = {}
    bulk: set[str] = set()
    for n in doc["nodes"]:
        if n["kind"] != "capacitor":
            continue
        a, b = net_of.get(f"{n['id']}.1"), net_of.get(f"{n['id']}.2")
        names = [(x or {}).get("name") or "" for x in (a, b)]
        if GROUND.match(names[1]) and POWER_NET.match(names[0]) and not GROUND.match(names[0]):
            supply, cap_pin = a, "1"
        elif GROUND.match(names[0]) and POWER_NET.match(names[1]) and not GROUND.match(names[1]):
            supply, cap_pin = b, "2"
        else:
            continue
        cands: list[tuple[str, str]] = []
        for ref in supply["pins"]:  # type: ignore[index]
            cid, pin = ref.split(".", 1)
            part = parts.get(cid, {})
            if by_id.get(cid, {}).get("kind") == "chip" and part.get("pads") and part.get("pins"):
                label = next((p["label"] for p in part["pins"] if catalog.base_label(p["label"]) == pin), None)
                if label:
                    cands.append((cid, label))
        if not cands:
            bulk.add(n["id"])
            continue
        named = [c for c in cands if re.search(rf"\b{re.escape(c[0])}\b", n.get("label") or "")]
        cid, label = (named or sorted(cands, key=lambda c: len(plan.get(c[0], []))))[0]
        plan.setdefault(cid, []).append((n["id"], label, cap_pin))
    return plan, bulk


def _cap_spots(part: dict[str, Any], caps: list[tuple[str, str, str]], packages: dict[str, str]) -> dict[str, dict[str, float]]:
    """pcbX/pcbY/pcbRotation of each capacitor in its chip's group (the chip at 0, 0, unrotated): just outside the chip's
    outline on the side its supply pad is nearest to, the supply pin level with the pad, the other pin towards ground."""
    pads, pins = part["pads"], part["pins"]
    num_of = {p["label"]: p["num"] for p in pins}
    # the chip's extent: its pads, and its outline where EasyEDA gives one
    x0 = min(x - w / 2 for x, y, w, h in pads.values())
    x1 = max(x + w / 2 for x, y, w, h in pads.values())
    y0 = min(y - h / 2 for x, y, w, h in pads.values())
    y1 = max(y + h / 2 for x, y, w, h in pads.values())
    box = part.get("box")
    if box:
        x0, y0, x1, y1 = min(x0, box[0]), min(y0, box[1]), max(x1, box[2]), max(y1, box[3])
    grounds = [pads[p["num"]] for p in pins if GROUND.match(catalog.base_label(p["label"])) and p["num"] in pads]
    out: dict[str, dict[str, float]] = {}
    stack: dict[str, float] = {}
    for cap, label, cap_pin in caps:
        pad = pads.get(num_of.get(label, ""))
        if pad is None:
            continue
        px, py = pad[0], pad[1]
        off, hw, hl = CAP_GEOM.get(packages.get(cap, "0603"), CAP_GEOM["0603"])
        side = min((("-x", px - x0), ("+x", x1 - px), ("-y", py - y0), ("+y", y1 - py)), key=lambda t: t[1])[0]
        g = min(grounds, key=lambda q: abs(q[0] - px) + abs(q[1] - py)) if grounds else None
        depth = stack.get(side, 0.0)
        stack[side] = depth + 2 * hw + 0.4
        if side in ("-x", "+x"):
            cx = (x0 - CAP_GAP - hw - depth) if side == "-x" else (x1 + CAP_GAP + hw + depth)
            t = -1 if (g and g[1] < py) else 1  # the ground pin goes towards the nearest ground pad
            cy = py + t * off
            rot = 270 if t < 0 else 90  # rotation 270 puts pin 1 at +y, 90 at -y
        else:
            cy = (y0 - CAP_GAP - hw - depth) if side == "-y" else (y1 + CAP_GAP + hw + depth)
            t = -1 if (g and g[0] < px) else 1
            cx = px + t * off
            rot = 0 if t > 0 else 180  # rotation 0 puts pin 1 at -x, 180 at +x
        if cap_pin == "2":  # the supply is on pin 2: turn it round
            rot = (rot + 180) % 360
        out[cap] = {"pcbX": round(cx, 2), "pcbY": round(cy, 2), "pcbRotation": rot}
    return out


def compile(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float]) -> dict[str, Any]:
    """The TSX file, the LCSC footprints it needs ({code: {easyeda, h}}) and the intent; the board is W x H mm. A chip
    and its decoupling capacitors are one group, capacitors placed at its supply pins, so the packer moves them together
    and the capacitors stay next to the pins they decouple."""
    W, H = size
    by_id = {n["id"]: n for n in doc["nodes"]}
    place = layout_edges(doc, parts, W, H)
    plan, bulk = decoupling(doc, parts)
    packages = {n["id"]: n.get("package", "0603") for n in doc["nodes"] if n["kind"] == "capacitor"}
    pins = {n["id"]: n["pcb"] for n in doc["nodes"] if n.get("pcb")}
    in_group: dict[str, str] = {}
    decoupled: set[str] = set()
    for chip, caps in plan.items():
        spots = _cap_spots(parts[chip], caps, packages)
        at = pins.get(chip)
        turn = (at or {}).get("rot", 0)
        c, s_ = round(math.cos(math.radians(turn))), round(math.sin(math.radians(turn)))
        ox, oy = (at["x"], at["y"]) if at else (0, 0)
        for cap, *_ in caps:
            decoupled.add(cap)
            if cap in spots and cap not in pins:
                sp = spots[cap]
                # the chip turned by hand: its capacitors turn with it around the chip's centre
                x, y = sp["pcbX"], sp["pcbY"]
                place[cap] = {"pcbX": round(ox + x * c - y * s_, 2), "pcbY": round(oy + x * s_ + y * c, 2), "pcbRotation": (sp["pcbRotation"] + turn) % 360}
                if not at:
                    in_group[cap] = chip
        if not at:
            # packed: the chip and its capacitors move as one group
            place[chip] = {"pcbX": 0, "pcbY": 0, "pcbRotation": 0}
            in_group[chip] = chip
    for nid, pin in pins.items():
        place[nid] = {"pcbX": pin["x"], "pcbY": pin["y"], "pcbRotation": pin["rot"]}
    grouped: dict[str, list[str]] = {}
    lines: list[str] = []
    lcsc: dict[str, dict[str, Any]] = {}
    # a capacitor the person routed by hand: its trace lengths are theirs (the limits steer the autorouter)
    routed = {e.split(".", 1)[0] for r in doc.get("routes") or [] for e in (r["from"], r["to"])}
    for n in doc["nodes"]:
        nid, k, part = n["id"], n["kind"], parts.get(n["id"], {})
        pos = _pos(place.get(nid))
        mark = len(lines)
        if k == "resistor":
            lines.append(f'<resistor name="{nid}" resistance={_attr(n["value"])} footprint="{n["package"]}"{_spn(part)}{pos} />')
        elif k == "capacitor":
            limit = HAND_MAX_MM if nid in routed else DECOUPLING_MAX_MM if nid in decoupled else BULK_MAX_MM if nid in bulk else None
            extra = f" maxDecouplingTraceLength={{{limit:g}}}" if limit else ""
            lines.append(f'<capacitor name="{nid}" capacitance={_attr(n["value"])} footprint="{n["package"]}"{_spn(part)}{pos}{extra} />')
        elif k == "led":
            lines.append(f'<led name="{nid}" color={_attr(n.get("color", "green"))} footprint="0603"{_spn(part)}{pos} />')
        elif k == "diode":
            lines.append(f'<diode name="{nid}" footprint="sod123" manufacturerPartNumber="B5819W"{_spn(part)}{pos} />')
        elif k == "button":
            lines.append(f'<pushbutton name="{nid}" footprint="pushbutton" internallyConnectedPins={{[["pin1","pin2"],["pin3","pin4"]]}}{_spn(part)}{pos} />')
        elif k == "header":
            labels = ", ".join(f'"{p}"' for p in n["pins"])
            lines.append(f'<pinheader name="{nid}" pinCount={{{len(n["pins"])}}} pitch="2.54mm" pinLabels={{[{labels}]}}{_spn(part)}{pos} />')
        elif k == "usb_c":
            labels = ", ".join(f'{p}: "{lb}"' for p, lb in USB_C_LABELS.items())
            lines.append(f'<chip name="{nid}" footprint="usbcmidmount" manufacturerPartNumber="TYPE-C-31-M-12"{_spn(part)}{pos} pinLabels={{{{ {labels} }}}} />')
        elif k == "jst":
            lines.append(f'<chip name="{nid}" footprint="jst2_ph" manufacturerPartNumber="S2B-PH-K-S"{_spn(part)}{pos} pinLabels={{{{ pin1: "pin1", pin2: "pin2" }}}} />')
        elif k == "module":
            m = MODULES[n["module"]]
            labels = ", ".join(f'pin{i + 1}: "{p}"' for i, p in enumerate(m["pins"]))
            lines.append(f'<chip name="{nid}" footprint="{m["footprint"]}" manufacturerPartNumber="{n["module"]}"{pos} pinLabels={{{{ {labels} }}}} />')
        elif k == "chip":
            if not part.get("raw"):
                continue
            labels = ", ".join(f'pin{p["num"] if p["num"].isdigit() else catalog.safe_label(p["num"])}: "{p["label"]}"' for p in part["pins"])
            mpn = str(part.get("mpn") or n.get("mpn") or n["lcsc"]).replace('"', "'")
            lines.append(f'<chip name="{nid}" footprint="lcsc:{n["lcsc"]}" manufacturerPartNumber="{mpn}"{_spn(part)}{pos} pinLabels={{{{ {labels} }}}} />')
            lcsc[n["lcsc"]] = {"easyeda": part["raw"], "h": part.get("height_mm"), "type": "chip"}
        if nid in in_group and len(lines) > mark:
            grouped.setdefault(in_group[nid], []).append(lines.pop())
    for chip, members in grouped.items():
        # the chip first, so the group reads as the chip with its capacitors
        members.sort(key=lambda ln: f'name="{chip}"' not in ln)
        lines.append(f'<group name="G_{chip}">\n      ' + "\n      ".join(members) + "\n    </group>")
    holes = []
    if doc["board"].get("holes", True) and W >= 26 and H >= 26:
        for i, (sx, sy) in enumerate(((-1, 1), (1, 1), (-1, -1), (1, -1))):
            holes.append(f'<hole name="H{i + 1}" diameter="3.2mm" pcbX={_attr(round(sx * (W / 2 - 3.5), 2))} pcbY={_attr(round(sy * (H / 2 - 3.5), 2))} />')

    hand, joined, bottom = _hand_traces(doc, parts, place, in_group)
    # pads one hand trace already joins are one island: the autorouter only joins the islands. A pad has one key
    # whatever the TSX calls it (an LED's anode is its pin1) and a button's or a USB-C receptacle's twin pads share one
    same: dict[str, str] = {}
    for n in doc["nodes"]:
        twins = {"led": {"anode": "pin1", "cathode": "pin2"}, "diode": {"anode": "pin1", "cathode": "pin2"},
                 "button": {"pin2": "pin1", "pin4": "pin3"},
                 "usb_c": {"VBUS_B": "VBUS_A", "DP2": "DP1", "DN2": "DN1", "GND_B": "GND_A", "SH1": "GND_A"}}.get(n["kind"], {})
        same.update({_sel(f"{n['id']}.{a}"): _sel(f"{n['id']}.{b}") for a, b in twins.items()})
    island: dict[str, str] = {}

    def root(e: str) -> str:
        e = same.get(e, e)
        while island.get(e, e) != e:
            e = island[e]
        return e

    for a, b in joined:
        island[root(a)] = root(b)
    traces: list[str] = []
    auto = 0
    for net in doc["nets"]:
        ends: list[str] = []
        for ref in net["pins"]:
            nid, pin = ref.split(".", 1)
            node = by_id.get(nid)
            if node is None or (node["kind"] == "chip" and not parts.get(nid, {}).get("raw")):
                continue
            ends += [f".{nid} > .{lb}" for lb in _tsx_pins(node, parts.get(nid, {}), pin)]
        # a USB-C receptacle's twin pins and shell go with the pin the device names
        for ref in net["pins"]:
            nid, pin = ref.split(".", 1)
            if by_id.get(nid, {}).get("kind") == "usb_c":
                if pin == "VBUS":
                    traces.append(f'<trace from=".{nid} > .VBUS_B" to=".{nid} > .VBUS_A" />')
                if pin == "GND":
                    ends += [f".{nid} > .GND_B", f".{nid} > .SH1"]
                # USB 2.0 data: both rows of the reversible plug carry the same pair
                if pin == "DP":
                    traces.append(f'<trace from=".{nid} > .DP2" to=".{nid} > .DP1" />')
                if pin == "DM":
                    traces.append(f'<trace from=".{nid} > .DN2" to=".{nid} > .DN1" />')
        ends = list(dict.fromkeys(ends))
        if len(ends) < 2:
            continue
        name = net.get("name")
        if name and WIDE_NET.match(name):
            # the supply path pin to pin, so its width is kept (a width on a trace to a net is dropped)
            reps = list(dict.fromkeys(root(e) for e in ends))
            for a, b in zip(reps, reps[1:]):
                traces.append(f'<trace from="{a}" to="{b}" thickness="0.4mm" />')
        elif not name and len(ends) == 2:
            if root(ends[0]) != root(ends[1]):
                traces.append(f'<trace from="{ends[0]}" to="{ends[1]}" />')
        else:
            if not name:
                auto += 1
                name = f"N{auto}"
            traces += [f'<trace from="{e}" to="net.{ident(name)}" />' for e in ends]

    intent = intent_of(doc, parts)
    meta = {"title": doc["title"][:60], "intent": intent, "device": True, **({"hand_bottom": bottom} if bottom else {})}
    import json as _json

    zones: list[str] = []
    for z in doc.get("zones") or []:
        if z["kind"] == "pour":
            # pour after routing: the solver keeps its clearance from every other net's copper and ties its own pads in
            r = z.get("rect")
            outline = (f" outline={{[{{ x: {r[0]:g}, y: {r[1]:g} }}, {{ x: {r[2]:g}, y: {r[1]:g} }}, {{ x: {r[2]:g}, y: {r[3]:g} }}, "
                       f"{{ x: {r[0]:g}, y: {r[3]:g} }}]}}") if r else ""
            zones.append(f'<copperpour layer="{z["layer"]}" connectsTo="net.{z["net"]}" clearance="{POUR_CLEARANCE_MM:g}mm"{outline} />')
        else:
            r = z["rect"]
            layers = ", ".join(f'"{lay}"' for lay in z["layers"])
            zones.append(f'<keepout shape="rect" pcbX={_attr(round((r[0] + r[2]) / 2, 2))} pcbY={_attr(round((r[1] + r[3]) / 2, 2))} '
                         f'width={_attr(round(r[2] - r[0], 2))} height={_attr(round(r[3] - r[1], 2))} layers={{[{layers}]}} />')
    body = "\n    ".join(lines + holes + zones + hand + traces)
    source = (f"// Compiled from the device graph (fw.device/1) by Formwright: parts on an edge are placed, the rest is packed by\n"
              f"// tscircuit next to the pins it connects, then autorouted on 2 layers.\n"
              f"export const meta = {_json.dumps(meta, ensure_ascii=False)}\n\n"
              f"export default () => (\n"
              f'  <board width="{W:g}mm" height="{H:g}mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm"'
              f' pcbPackGap="{PACK_GAP_MM:g}mm">\n'
              f"    {body}\n  </board>\n)\n")
    return {"source": source, "lcsc": lcsc, "intent": intent, "size": [W, H], "placed": place, "hand": len(hand)}


def _sel(ref: str) -> str:
    nid, port = ref.split(".", 1)
    return f".{nid} > .{port}"


def _hand_traces(doc: dict[str, Any], parts: dict[str, dict[str, Any]], place: dict[str, dict[str, float]],
                 in_group: dict[str, str]) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """The person's traces as TSX: (lines, the pad pairs they join as selectors, the traces that leave on the bottom).
    tscircuit reads a pcbPath in the frame of the part at `from` (its centre, turned with it), so the corners go in
    turned back into that frame; a trace whose start part has no fixed place (packed) is left out. tscircuit starts every
    path on the top layer: the worker moves the first run of a trace listed in meta.hand_bottom to the bottom."""
    nets = port_nets(doc, parts)
    lines: list[str] = []
    joined: list[tuple[str, str]] = []
    bottom: list[str] = []
    for r in doc.get("routes") or []:
        if nets.get(r["from"]) is None or nets.get(r["from"]) != nets.get(r["to"]):
            continue  # route_problems says why
        end = r["layer"]
        for q in r["points"]:
            if q.get("via"):
                end = "bottom" if end == "top" else "top"
        # either end may lead: one that leaves on the top first, then one whose part has a fixed place
        ways = [(r["from"], r["to"], r["points"], r["layer"]), (r["to"], r["from"], r["points"][::-1], end)]
        ways.sort(key=lambda w: w[3] != "top")
        way = next((w for w in ways if place.get(w[0].split(".", 1)[0]) and w[0].split(".", 1)[0] not in in_group), None)
        if way is None:
            continue
        a, b, corners, layer = way
        at = place[a.split(".", 1)[0]]
        th = math.radians(at.get("pcbRotation") or 0)
        c, s_ = math.cos(th), math.sin(th)
        start = layer
        pts: list[str] = []
        for q in corners:
            dx, dy = q["x"] - at["pcbX"], q["y"] - at["pcbY"]
            x, y = round(dx * c + dy * s_, 3) + 0.0, round(-dx * s_ + dy * c, 3) + 0.0  # + 0.0: never "-0"
            pts.append(f"{{ x: {x:g}, y: {y:g} }}")
            if q.get("via"):
                nxt = "bottom" if layer == "top" else "top"
                # the via, then the same point on the new layer, as the autorouter writes it (the run leaves from there)
                pts.append(f'{{ x: {x:g}, y: {y:g}, via: true, fromLayer: "{layer}", toLayer: "{nxt}" }}')
                pts.append(f"{{ x: {x:g}, y: {y:g} }}")
                layer = nxt
        sa, sb = _sel(a), _sel(b)
        lines.append(f'<trace from="{sa}" to="{sb}" pcbPathRelativeTo="{sa}" pcbPath={{[{", ".join(pts)}]}} thickness="{r["width"]:g}mm" />')
        joined.append((sa, sb))
        if start == "bottom":
            bottom.append(f"{sa} to {sb}")
    return lines, joined, bottom


def intent_of(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Edges of every port part, and the module pin that drives each LED (directly or through one resistor) and button."""
    edge = {n["id"]: n["edge"] for n in doc["nodes"] if n.get("edge")}
    net_of: dict[str, dict[str, Any]] = {}
    for net in doc["nets"]:
        for p in net["pins"]:
            net_of[p] = net
    kinds = {n["id"]: n["kind"] for n in doc["nodes"]}
    modules = {n["id"] for n in doc["nodes"] if n["kind"] == "module"}
    gpio: dict[str, str] = {}

    def module_pin(net: dict[str, Any] | None) -> str | None:
        for p in (net or {}).get("pins", []):
            nid, pin = p.split(".", 1)
            if nid in modules and not POWER_NET.match(pin) and not pin.startswith("GND"):
                return p
        return None

    for n in doc["nodes"]:
        if n["kind"] == "led":
            for side in ("A", "K"):
                net = net_of.get(f"{n['id']}.{side}")
                hit = module_pin(net)
                if not hit and net:
                    for p in net["pins"]:
                        rid, rpin = p.split(".", 1)
                        if kinds.get(rid) == "resistor":
                            hit = module_pin(net_of.get(f"{rid}.{'2' if rpin == '1' else '1'}"))
                            if hit:
                                break
                if hit:
                    gpio[n["id"]] = hit
                    break
        if n["kind"] == "button":
            for side in ("A", "B"):
                hit = module_pin(net_of.get(f"{n['id']}.{side}"))
                if hit:
                    gpio[n["id"]] = hit
                    break
    out: dict[str, Any] = {"nets_max": 30}
    if edge:
        out["edge"] = edge
    if gpio:
        out["gpio"] = gpio
    return out


# ------------------------------------------------------------------ the editor's view of a document
def view(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Per node what the editor draws: its pins (with the net each is on), title line, part card bits and price."""
    net_of: dict[str, str] = {}
    for i, net in enumerate(doc["nets"]):
        for p in net["pins"]:
            net_of[p] = net.get("name") or f"n{i}"
    nodes = {}
    for n in doc["nodes"]:
        part = parts.get(n["id"], {})
        pins = pins_of(n, part)
        if n["kind"] == "chip":
            counts: dict[str, int] = {}
            for p in part.get("pins") or []:
                b = catalog.base_label(p["label"])
                counts[b] = counts.get(b, 0) + 1
        else:
            counts = {}
        nodes[n["id"]] = {
            "pins": [{"name": p, "net": net_of.get(f"{n['id']}.{p}"), **({"count": counts[p]} if counts.get(p, 1) > 1 else {})}
                     for p in pins if not (n["kind"] == "chip" and p.upper().startswith("NC") and f"{n['id']}.{p}" not in net_of)],
            "part": {k: part.get(k) for k in ("lcsc", "mpn", "brand", "package", "category", "description", "stock", "basic", "datasheet", "image",
                                              "url", "size_mm", "height_mm", "error") if part.get(k) is not None},
            "price_usd": catalog.price_at(part.get("prices") or [], 10) if part.get("prices") else None,
        }
        if n["kind"] == "module":
            m = MODULES[n["module"]]
            nodes[n["id"]]["part"].update({"mpn": m["name"], "mcu": m["mcu"], "wireless": m["wireless"], "url": m["url"]})
    plan, _ = decoupling(doc, parts)
    return {"nodes": nodes, "power": [net.get("name") for net in doc["nets"] if net.get("name") and POWER_NET.match(net["name"])],
            # a chip and the capacitors placed at its pins move together on the board
            "groups": {chip: [cap for cap, *_ in caps] for chip, caps in plan.items()}}


def library() -> dict[str, Any]:
    """What the editor's palette offers besides catalogue search: modules and primitives with their pins."""
    return {
        "modules": [{"module": k, "name": m["name"], "mcu": m["mcu"], "pins": m["pins"], "wireless": m["wireless"], "price_usd": m["price_usd"],
                     "size_mm": m["size"]} for k, m in MODULES.items()],
        "primitives": [{"kind": k, "prefix": v["prefix"], "pins": v["pins"]} for k, v in PRIMS.items()] + [{"kind": "header", "prefix": "J", "pins": ["P1", "P2", "P3", "P4"]}],
    }


def clone(doc: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(doc)


def changes(old: dict[str, Any], new: dict[str, Any], limit: int = 24) -> list[str]:
    """What the person changed between two documents, one short English line each: parts added, removed or edited,
    connections made or undone, placements fixed on the board, board settings, firmware files."""
    out: list[str] = []
    a = {n["id"]: n for n in old.get("nodes") or []}
    b = {n["id"]: n for n in new.get("nodes") or []}
    what = lambda n: (n.get("lcsc") or n.get("module") or n.get("value") or n.get("color") or "") + (f" '{n['label']}'" if n.get("label") else "")  # noqa: E731
    for nid in b.keys() - a.keys():
        out.append(f"added {nid} ({b[nid]['kind']} {what(b[nid])})".replace("  ", " "))
    for nid in a.keys() - b.keys():
        out.append(f"removed {nid} ({a[nid]['kind']} {what(a[nid])})".replace("  ", " "))
    for nid in sorted(a.keys() & b.keys()):
        for k in ("lcsc", "module", "value", "package", "color", "pins", "edge", "label"):
            if a[nid].get(k) != b[nid].get(k):
                out.append(f"{nid}: {k} {a[nid].get(k) or '-'} -> {b[nid].get(k) or '-'}")
        pa, pb = a[nid].get("pcb"), b[nid].get("pcb")
        if pa != pb:
            out.append(f"{nid}: placed by hand on the board at ({pb['x']:g}, {pb['y']:g}) mm, rotation {pb['rot']}" if pb
                       else f"{nid}: hand placement removed (placed automatically again)")
    key = lambda net: frozenset(net.get("pins") or [])  # noqa: E731
    na = {key(n): n.get("name") for n in old.get("nets") or []}
    nb = {key(n): n.get("name") for n in new.get("nets") or []}
    for pins in nb.keys() - na.keys():
        out.append(f"connected {', '.join(sorted(pins))}" + (f" (net {nb[pins]})" if nb[pins] else ""))
    for pins in na.keys() - nb.keys():
        out.append(f"net no longer as it was: {', '.join(sorted(pins))}" + (f" ({na[pins]})" if na[pins] else ""))
    for pins in nb.keys() & na.keys():
        if nb[pins] != na[pins]:
            out.append(f"net {na[pins] or 'unnamed'} renamed to {nb[pins] or 'unnamed'}")
    za = [z for z in old.get("zones") or []]
    zb = [z for z in new.get("zones") or []]
    for z in zb:
        if z not in za:
            where = "the whole board" if not z.get("rect") else f"{z['rect'][2] - z['rect'][0]:g} x {z['rect'][3] - z['rect'][1]:g} mm"
            out.append(f"{z['net']} copper pour on the {z['layer']} over {where}" if z["kind"] == "pour"
                       else f"keepout (no copper) on {' and '.join(z['layers'])}, {where} at ({z['rect'][0]:g}, {z['rect'][1]:g})")
    for z in za:
        if z not in zb:
            out.append(f"{z['kind']} zone removed")
    ra = {(r["from"], r["to"]): r for r in old.get("routes") or []}
    rb = {(r["from"], r["to"]): r for r in new.get("routes") or []}
    for k in rb.keys() - ra.keys():
        out.append(f"routed {k[0]} to {k[1]} by hand ({rb[k]['layer']}, {len(rb[k]['points'])} corners)")
    for k in ra.keys() - rb.keys():
        out.append(f"hand trace {k[0]} to {k[1]} removed")
    for k in ra.keys() & rb.keys():
        if ra[k] != rb[k]:
            out.append(f"hand trace {k[0]} to {k[1]} redrawn")
    ba, bb = old.get("board") or {}, new.get("board") or {}
    if (ba.get("w"), ba.get("h")) != (bb.get("w"), bb.get("h")):
        out.append(f"board size fixed at {bb['w']:g} x {bb['h']:g} mm" if bb.get("w") and bb.get("h") else "board size left to the build again")
    if ba.get("holes", True) != bb.get("holes", True):
        out.append("mounting holes " + ("on" if bb.get("holes", True) else "off"))
    fa = ((old.get("firmware") or {}).get("files") or {})
    fb = ((new.get("firmware") or {}).get("files") or {})
    for name in sorted(fa.keys() | fb.keys()):
        if fa.get(name) != fb.get(name):
            out.append(f"firmware file {name} " + ("added" if name not in fa else "deleted" if name not in fb else "edited by hand"))
    if len(out) > limit:
        out = out[:limit] + [f"and {len(out) - limit} more changes"]
    return out


def board_key(doc: dict[str, Any]) -> str:
    """What the board depends on (parts, nets, board settings), not where the editor drew the nodes or the firmware."""
    import json as _json

    return _json.dumps({"nodes": [{k: v for k, v in n.items() if k not in ("ui", "label", "note")} for n in doc.get("nodes") or []],
                        "nets": doc.get("nets") or [], "board": doc.get("board") or {}, "routes": doc.get("routes") or [], "zones": doc.get("zones") or []}, sort_keys=True)
