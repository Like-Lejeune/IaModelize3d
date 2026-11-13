"""Devices (fw.device/1): the node graph a whole device is designed in, and its deterministic compiler to a board.

A device is parts (nodes) and the nets between their pins. The designer (agent pack 'device') and the node editor in
the studio both edit this one document. compile() turns it into a tscircuit TSX file:
  - parts on an edge (connectors, a module's own USB) get exact positions and rotations so their mouths face out,
  - parts people see or touch may be placed by the designer (node.place, or a doc.layouts pattern such as a dice face)
    and by the person (node.pcb, which wins): fixed positions,
  - everything else gets its spot from the placer here (arrange(): greedy in connectivity order, next to the pins it
    connects, inside the real outline); tscircuit's packer is only the fallback if the placer itself breaks,
  - nets become traces (named nets through net.NAME, 5 V paths pin to pin at 0.4 mm),
  - the intent (edge of every port, the pin that drives each LED and button) is stated for the build to check,
and lists the LCSC footprints the PCB worker needs (catalog.easyeda), since the worker has no network.
deviceapi.build_device runs it through the PCB pipeline, growing the board until placement and routing succeed, and
dress_board() tells board.json what the graph knows: faces (light, sound, sensor) and the accessories fitted by hand.
The board is a rectangle, a rounded rectangle or a circle (board.shape, outline()); a curved one compiles to a polygon
outline, and the holes, the edge parts, the placement checks and the growth all go by the real outline. A placed part
running into an edge part hears the ways out with the board each gives (_ways: smallest first, growth last with its
cost), a board far larger than its parts the smaller arrangement that exists (compaction), a build that grew by how much
and why (growth_report).

Document:
  {schema: 'fw.device/1', title, summary,
   board: {w?, h?, holes: true, shape?: rect|rounded|round, r? (a rounded board's corner radius, mm; a round board is a
           circle of diameter w, h = w)},
   requirements?: [{id: 'R1', text, parts: [ids], firmware?: bool, test?: {given?, steps?, expect} (firmware_sim plays it)}],
   concept?: {uses, options: [{name, look, form, stance, mounting, board, module_edge, panel}], chosen, why} (device_concept),
   nodes: [{id: 'U1', kind, label?, value?, package?, color?, lcsc?, module?, accessory?, pins? (header labels), edge?,
            place?: {x, y, rot} (mm from the board centre, +y up, degrees), face?: light|sound|sensor|display|none,
            pcb?: {x, y, rot} (the person's), ui?: [x, y]}],
   layouts?: [{pattern: dice|row|column|grid|ring, nodes: [ids], center?: [x, y], pitch?, cols?, radius?, rot?}],
   nets:  [{name?: 'GND', pins: ['U1.GND', 'U2.GND', 'C1.2'], amps?: 2.5}],
   firmware?: {lang, files: {name: text}}}
Kinds: module (by part number, MODULES), chip (any LCSC part with an EasyEDA footprint), accessory (a ready-made module
fitted by hand, accessories.ACCESSORIES: the carrier gets its connector), resistor, capacitor, led, diode, button,
header, usb_c, jst, hole. Pin references are '<node>.<pin>'; for a chip a duplicated pin name ('GND' twice) is one
reference for all of them. A net may state amps, the current it carries: the build widens its traces by IPC-2221 and the
rules hold connectors, transistors, resistors and the board's copper to it (device_rules). A button's switch says which: a tact switch (default), or a mechanical key switch (SWITCHES:
hand-soldered, its top through a plate in the case lid, a printed keycap on it). Any node may carry model: primitives
describing its 3D look (model_prims), for a part the catalogue has no 3D model of.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import re
from typing import Any

from . import accessories as acc
from . import catalog, device_concept

log = logging.getLogger(__name__)

SCHEMA = "fw.device/1"
MAX_NODES = 40
MAX_W = 100.0
EDGES = ("-x", "+x", "-y", "+y")
EDGE_ALIASES = {"left": "-x", "right": "+x", "bottom": "-y", "top": "+y", "-x": "-x", "+x": "+x", "-y": "-y", "+y": "+y"}
# the board's outline (doc.board.shape): a rectangle, a rectangle with rounded corners (board.r), a circle of diameter w
SHAPES = ("rect", "rounded", "round")
ROUND_SEGMENTS = 72    # a round board as the polygon tscircuit and the case get: 0.06 mm inside the circle at 60 mm
CORNER_SEGMENTS = 10   # each corner arc of a rounded board
RIM_MM = 3.5           # a mounting hole's centre from the board's edge (both edges at a rectangle's corner)
# nets shown as labels in the editor rather than wires, and the ones whose path is widened
POWER_NET = re.compile(r"^(GND|AGND|V3V3|V3V|V1V8|V5|V5V|VBUS|VSYS|VBAT|VIN|VCC|VDD|V12|V9)$", re.I)
WIDE_NET = re.compile(r"^(V5|V5V|VBUS|VSYS|VBAT|VIN|V12|V9|V_?LED|V_?MOT(OR)?)$", re.I)
# a rail the designer named in its own words (VLED behind a diode, V3V3_SENSOR, PWR_5V): supply capacitors on it decouple
# the chips on it, as on V3V3. The names POWER_NET lists keep their meaning for shorts and the editor's power labels.
SUPPLY_NAME = re.compile(r"^(V(?!REF|SENSE|SNS|OUT_?SENSE)[A-Z0-9_]*|\d+V\d*|PWR\w*|\w+_(VCC|VDD|PWR|V3V3|V5))$", re.I)
SUPPLY_PIN = re.compile(r"^(VDD\w*|VCC\w*|AVDD|DVDD|VIN|VBUS|VSYS|V3V3|V5|VS|VM)$", re.I)
GROUND = re.compile(r"^(GND|AGND|VSS)$", re.I)

# development boards soldered on headers: their own USB faces the edge named in the node (default top)
MODULES: dict[str, dict[str, Any]] = {
    "113991054": {
        "name": "Seeed XIAO ESP32-C3", "mcu": "ESP32-C3", "footprint": "dip14_w15.24mm", "size": [17.8, 21.0], "depth": 10.5,
        "pins": ["D0", "D1", "D2", "D3", "SDA", "SCL", "TX", "RX", "SCK", "MISO", "MOSI", "V3V3", "GND", "V5"],
        "aliases": {"D4": "SDA", "D5": "SCL", "D6": "TX", "D7": "RX", "D8": "SCK", "D9": "MISO", "D10": "MOSI", "3V3": "V3V3", "5V": "V5"},
        "price_usd": 4.99, "wireless": ["Wi-Fi", "BLE 5"], "fw": "arduino-esp32 (board 'XIAO_ESP32C3')", "port": {"label": "USB-C", "w": 8.94, "d": 7.3, "protrude": 1.0},
        "url": "https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/",
    },
    "113991114": {
        "name": "Seeed XIAO ESP32-S3", "mcu": "ESP32-S3", "footprint": "dip14_w15.24mm", "size": [17.8, 21.0], "depth": 10.5,
        "pins": ["D0", "D1", "D2", "D3", "SDA", "SCL", "TX", "RX", "SCK", "MISO", "MOSI", "V3V3", "GND", "V5"],
        "aliases": {"D4": "SDA", "D5": "SCL", "D6": "TX", "D7": "RX", "D8": "SCK", "D9": "MISO", "D10": "MOSI", "3V3": "V3V3", "5V": "V5"},
        "price_usd": 7.49, "wireless": ["Wi-Fi", "BLE 5"], "fw": "arduino-esp32 (board 'XIAO_ESP32S3')", "port": {"label": "USB-C", "w": 8.94, "d": 7.3, "protrude": 1.0},
        "url": "https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/",
    },
    "SC0915": {
        "name": "Raspberry Pi Pico", "mcu": "RP2040", "footprint": "dip40_w17.78mm", "size": [21.0, 51.0], "depth": 25.75,
        "pins": ["GP0", "GP1", "GND3", "GP2", "GP3", "GP4", "GP5", "GND8", "GP6", "GP7", "GP8", "GP9", "GND13", "GP10", "GP11", "GP12", "GP13",
                 "GND18", "GP14", "GP15", "GP16", "GP17", "GND23", "GP18", "GP19", "GP20", "GP21", "GND28", "GP22", "RUN", "GP26", "GP27",
                 "AGND", "GP28", "ADC_VREF", "V3V3", "V3V3_EN", "GND", "VSYS", "VBUS"],
        "aliases": {"3V3": "V3V3"}, "price_usd": 4.0, "wireless": [], "fw": "MicroPython or arduino-pico", "port": {"label": "USB", "w": 8.0, "d": 5.6, "protrude": 1.3},
        "url": "https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf",
    },
    "SC0918": {
        "name": "Raspberry Pi Pico W", "mcu": "RP2040", "footprint": "dip40_w17.78mm", "size": [21.0, 51.0], "depth": 25.75,
        "pins": ["GP0", "GP1", "GND3", "GP2", "GP3", "GP4", "GP5", "GND8", "GP6", "GP7", "GP8", "GP9", "GND13", "GP10", "GP11", "GP12", "GP13",
                 "GND18", "GP14", "GP15", "GP16", "GP17", "GND23", "GP18", "GP19", "GP20", "GP21", "GND28", "GP22", "RUN", "GP26", "GP27",
                 "AGND", "GP28", "ADC_VREF", "V3V3", "V3V3_EN", "GND", "VSYS", "VBUS"],
        "aliases": {"3V3": "V3V3"}, "price_usd": 6.0, "wireless": ["Wi-Fi", "BLE"], "fw": "MicroPython or arduino-pico", "port": {"label": "USB", "w": 8.0, "d": 5.6, "protrude": 1.3},
        "url": "https://datasheets.raspberrypi.com/picow/pico-w-datasheet.pdf",
    },
}
# GND pins of a module are one reference: 'U1.GND' reaches all of a Pico's eight
for _m in MODULES.values():
    _m["groups"] = {"GND": [p for p in _m["pins"] if re.match(r"^A?GND\d*$", p) and p != "AGND"]}
# GPIO number of each pin label (what the firmware writes, contract C5), the strapping pins a boot can trip over, the ADC
# pins (ADC1 only on the ESP32s: ADC2 stops while Wi-Fi runs) and how a LiPo goes on: the XIAOs charge a cell on the
# BAT pads under the module, so a raw cell on V5 or 3V3 is never right
_XIAO_BAT = ("1S LiPo on the BAT+ / BAT- pads under the module: its own charger takes it from USB-C (about 100 mA); never "
             "wire a cell to V5 or 3V3 (USB would push 5 V into it). The pads are not on the header: solder the leads there.")
MODULES["113991054"].update({
    "gpio": {"D0": 2, "D1": 3, "D2": 4, "D3": 5, "SDA": 6, "SCL": 7, "TX": 21, "RX": 20, "SCK": 8, "MISO": 9, "MOSI": 10},
    "strapping": [2, 8, 9], "adc": ["D0", "D1", "D2"], "battery": _XIAO_BAT})
MODULES["113991114"].update({
    "gpio": {"D0": 1, "D1": 2, "D2": 3, "D3": 4, "SDA": 5, "SCL": 6, "TX": 43, "RX": 44, "SCK": 7, "MISO": 8, "MOSI": 9},
    "strapping": [0, 3, 45, 46], "adc": ["D0", "D1", "D2", "D3", "SDA", "SCL", "SCK", "MISO", "MOSI"], "battery": _XIAO_BAT})
for _k in ("SC0915", "SC0918"):
    MODULES[_k].update({"gpio": {p: int(p[2:]) for p in MODULES[_k]["pins"] if re.match(r"^GP\d+$", p)}, "strapping": [],
                        "adc": ["GP26", "GP27", "GP28"],
                        "battery": "no charger on board: a cell needs its own charger module feeding VSYS through a Schottky diode"})

# key switches a button node may be (node.switch), soldered by hand: pads and locating holes around the switch's centre, the
# cap's plan (nothing else on the board under it, keys sit `pitch` apart), the key data the case reads (mm above the PCB's
# top face: where the plate's top goes so the switch clips in, the stem's top at rest). The fab cannot place them.
SWITCHES: dict[str, dict[str, Any]] = {
    "mx": {
        "name": "MX-style mechanical key switch, 5-pin", "price_usd": 0.45, "pitch": 19.05, "cap": [18.0, 18.0], "hole": 1.5, "pad": 2.3,
        "pins": {"A": (-3.81, 2.54), "B": (2.54, 5.08)}, "npth": [(0.0, 0.0, 4.0), (-5.08, 0.0, 1.75), (5.08, 0.0, 1.75)],
        "url": "https://www.lcsc.com/search?q=mechanical%20keyboard%20switch",
        "key": {"plate_top": 5.0, "plate_t": 1.5, "cut": 14.0, "travel": 4.0, "stem_top": 11.6, "stem": "mx", "cap": [18.0, 18.0]},
        "note": "Any MX-compatible switch (Gateron, Outemu, Kailh Box, Cherry) fits: 14 mm plate cut-out, 19.05 mm pitch.",
    },
    "choc": {
        "name": "Kailh Choc v1 low-profile key switch (PG1350)", "price_usd": 0.75, "pitch": 18.0, "cap": [17.5, 16.5], "hole": 1.2, "pad": 2.0,
        "pins": {"A": (5.0, 3.8), "B": (0.0, 5.9)}, "npth": [(0.0, 0.0, 3.4), (-5.5, 0.0, 1.9), (5.5, 0.0, 1.9)],
        "url": "https://www.lcsc.com/search?q=kailh%20choc",
        "key": {"plate_top": 2.2, "plate_t": 1.2, "cut": 14.0, "travel": 3.0, "stem_top": 8.0, "stem": "choc", "cap": [17.5, 16.5]},
        "note": "Low profile, 18 x 17 mm spacing, its own keycap stem (no MX caps). Verify the heights against the switch before an order.",
    },
    # switches held by the lid, on two wires to the board: a round hole in the lid, the body under it, so the case is as deep as the body
    "arcade": {
        "name": "30 mm arcade push button", "price_usd": 1.1, "pitch": 36.0, "cap": [33.0, 33.0], "hole": 1.0, "pad": 1.7,
        "pins": {"A": (-1.27, 0.0), "B": (1.27, 0.0)}, "npth": [], "url": "https://www.lcsc.com/search?q=arcade%20button",
        "key": {"stem": "panel", "cut": 28.2, "depth": 30.0, "cap": [33.0, 33.0], "color": "#c8352f"},
        "note": "Snaps into a 28 mm hole in the lid, 30 mm deep, wired to the board's two pads. For big buttons hit in a hurry.",
    },
    "stomp": {
        "name": "12 mm momentary foot switch (PBS-24B)", "price_usd": 1.6, "pitch": 30.0, "cap": [22.0, 22.0], "hole": 1.0, "pad": 1.7,
        "pins": {"A": (-1.27, 0.0), "B": (1.27, 0.0)}, "npth": [], "url": "https://www.lcsc.com/search?q=foot%20switch",
        "key": {"stem": "panel", "cut": 12.2, "depth": 26.0, "cap": [22.0, 22.0], "color": "#b9bdc4"},
        "note": "A metal foot switch nutted through a 12 mm hole in the lid, 26 mm deep, wired to the board's two pads. For pedals: a tab in a printed lid does not survive a foot.",
    },
}
# wire terminals a header node may be (node.connector): pins in a row at their pitch, the wires entering from the board's edge.
# amps per contact, what the block is rated for
CONNECTORS: dict[str, dict[str, Any]] = {
    "terminal_5": {"name": "Screw terminal block, 5.08 mm", "pitch": 5.08, "hole": 1.3, "pad": 2.6, "amps": 16.0, "d": 7.6, "h": 10.0, "price_usd": 0.12, "color": "#2f7d4f"},
    "terminal_3": {"name": "Screw terminal block, 3.5 mm", "pitch": 3.5, "hole": 1.1, "pad": 2.0, "amps": 8.0, "d": 7.0, "h": 8.5, "price_usd": 0.1, "color": "#2f7d4f"},
}
CONNECTOR_AMPS = {"header": 3.0, "jst": 2.0, "usb_c": 3.0}  # per contact, the part's usual rating: a 2.54 mm pin, a JST PH, USB-C's VBUS
TRACE_MAX_MM = 2.0      # what the autorouter still places well; more current takes a pour (about 5 A at 1 oz)
TRACE_MIN_AMPS = 0.5    # below this the default width carries it
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
KINDS = ("module", "chip", "header", "accessory", *PRIMS)
EDGE_KINDS = ("usb_c", "header", "jst", "module", "accessory", "chip")
# what a part needs from the case above it (node.face, contract C1c) -> the access board.json gives it (C2a)
FACES = ("light", "sound", "sensor", "display", "shaft", "hole", "none")
FACE_TEXT = (  # first match wins, on the part's kind hint, mpn, category, package and description
    ("shaft", re.compile(r"rotary encoder|\bP?EC1[126]\b|\bP?EC1[126][A-Z0-9-]", re.I)),
    ("light", re.compile(r"\b(rgb_led|led)\b|WS28\d\d|SK68\d\d|APA10\d|addressable|\bRGB\b|\bLEDs?\b", re.I)),
    ("sound", re.compile(r"buzzer|speaker|sounder|piezo|transducer|\bBUZ", re.I)),
    ("sensor", re.compile(r"\bPIR\b|pyroelectric|motion sens|ambient light|light sens|illuminance|photo ?(diode|transistor|resistor)|"
                          r"\bLDR\b|\bUV\b|colou?r sens|BH1750|VEML|TSL25|LTR-?\d|\bAPDS|gas sens|air quality|\bVOC\b|\bCO2\b|"
                          r"humidity|\bSGP\d|\bSCD\d|\bCCS811|\bENS\d|\bBME\d|\bSHT\d|\bAHT\d|\bHDC\d|microphone|\bMEMS mic|\bMIC\b|AM312", re.I)),
)
# the kind hints a catalogue card carries (contract C6) that settle the face and the decoupling check without text
HINT_FACE = {"led": "light", "rgb_led": "light", "buzzer_active": "sound", "buzzer_passive": "sound", "buzzer": "sound", "speaker": "sound",
             "display": "display"}
DISCRETE_HINTS = {"npn", "pnp", "transistor", "nmos", "pmos", "diode", "tvs", "led", "rgb_led", "buzzer_active", "buzzer_passive", "buzzer",
                  "speaker", "motor", "resistor", "capacitor", "inductor", "crystal", "connector", "switch", "fuse", "button"}
DISCRETE_TEXT = re.compile(r"transistor|MOSFET|\bBJT\b|diode|zener|schottky|\bTVS\b|buzzer|speaker|piezo|\bLEDs?\b|WS28\d\d|SK68\d\d|"
                           r"connector|header|switch|button|resistor|capacitor|inductor|ferrite|crystal|oscillator|fuse|relay", re.I)
ROUND_PACKAGE = re.compile(r"TO-?(5|18|39|46)\b|_BD\d|\bDIA\d|-D\d+(\.\d+)?-|PIR", re.I)
LAYOUTS = ("dice", "row", "column", "grid", "ring")
LAYOUT_MAX = 12
REQ_MAX = 20
# a dice face's pips in the order the layout lists its nodes: centre, then the corners and the middle row by rows
DICE = ((0, 0), (-1, 1), (1, 1), (-1, 0), (1, 0), (-1, -1), (1, -1))
PASSIVE_PKG = ("0402", "0603", "0805", "1206")
# courtyard w x h at rotation 0, for the board-size estimate and the edge layout
SIZE = {"0402": (1.6, 0.9), "0603": (2.2, 1.2), "0805": (2.8, 1.6), "1206": (3.8, 2.0), "led": (2.2, 1.2), "diode": (4.5, 2.0),
        "button": (7.0, 9.0), "usb_c": (10.4, 8.4), "jst": (7.0, 6.0), "hole": (7.2, 7.2)}
# centre distance from the edge for a part whose body ends at the edge (usbcmidmount body spans -5.5..+2.9 around its origin;
# a jst*_ph courtyard reaches 2.2 mm from its pin row towards its mouth and 3.3 mm behind it)
DEPTH = {"usb_c": 5.5, "header": 2.5, "jst": 2.6}
# traces the person drew on the board: pad to pad on one net, corners in mm from the board's centre (+y up)
ROUTE_MAX = 200
ROUTE_POINTS = 64
PORT_REF = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z0-9_]+)$")
# a primitive's pads as the board names them (the TSX names an LED's pins anode/cathode, the board pin1/pin2); a
# button's pins 1-2 and 3-4 are one contact each; a USB-C receptacle's twin rows and shell go with the pin it names
PORT_NAMES = {"led": {"A": ["pin1"], "K": ["pin2"]}, "diode": {"A": ["pin1"], "K": ["pin2"]},
              "button": {"A": ["pin1", "pin2"], "B": ["pin3", "pin4"]}}
USB_PORTS = {"VBUS": ["VBUS_A", "VBUS_B"], "GND": ["GND_A", "GND_B", "SH1"], "DP": ["DP1", "DP2"], "DM": ["DN1", "DN2"]}
MODEL_PRIMS = 60       # primitives one part's model may have
MODEL_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
# areas the person drew on the board: a copper pour of a net (a rectangle, or the whole board) and a keepout (no copper)
ZONE_MAX = 24
POUR_CLEARANCE_MM = 0.3


class DeviceError(Exception):
    pass


def trace_mm(amps: float, rise_c: float = 20.0) -> float:
    """The width of an outer 1 oz (35 um) trace that carries `amps` with `rise_c` of heating (IPC-2221)."""
    if amps <= 0:
        return 0.0
    area_mil2 = (amps / (0.048 * rise_c ** 0.44)) ** (1 / 0.725)
    return round(area_mil2 / 1.378 * 0.0254, 2)


def poured(doc: dict[str, Any], net: dict[str, Any]) -> bool:
    return bool(net.get("name")) and any(z.get("kind") == "pour" and z.get("net") == net["name"] for z in doc.get("zones") or [])


def net_width(doc: dict[str, Any], net: dict[str, Any]) -> float | None:
    """The trace width a net's stated current asks for (mm), None when the default does or a pour carries it."""
    a = float(net.get("amps") or 0)
    if a < TRACE_MIN_AMPS or poured(doc, net) or GROUND.match(net.get("name") or ""):
        return None
    return min(TRACE_MAX_MM, max(0.25, trace_mm(a)))


def ident(name: str) -> str:
    s = catalog.safe_label(name)
    return s if re.match(r"^[A-Za-z_]", s) else f"N{s}"


# ------------------------------------------------------------------ the document
def blank(title: str = "Device") -> dict[str, Any]:
    return {"schema": SCHEMA, "title": title, "summary": "", "board": {"holes": True}, "nodes": [], "nets": []}


def model_prims(raw: Any) -> tuple[list[dict[str, Any]], str | None]:
    """A part's own 3D look as primitives (mm, the part's origin, z = 0 on the board's top face): [{shape: box|cyl, at: [x, y,
    z] (centre in plan, z its bottom), size: [w, d, h], color: '#rrggbb', r?: a box's corner radius, axis?: 'x'|'y' (lying
    along it), taper?: the top's share of the bottom}]. What is broken is left out and said."""
    if not isinstance(raw, list):
        return [], "a list of primitives [{shape, at: [x, y, z], size: [w, d, h], color}]"
    out: list[dict[str, Any]] = []
    why: str | None = None
    for p in raw[:MODEL_PRIMS]:
        try:
            at, size = [float(v) for v in p["at"]], [float(v) for v in p["size"]]
            if len(at) != 3 or len(size) != 3 or min(size) <= 0 or max(map(abs, at + size)) > 150:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            why = "each primitive needs at [x, y, z] and size [w, d, h] in mm (positive, up to 150)"
            continue
        q: dict[str, Any] = {"shape": "cyl" if p.get("shape") == "cyl" else "box", "at": at, "size": size,
                             "color": p["color"] if MODEL_COLOR.match(str(p.get("color") or "")) else "#333333"}
        if p.get("axis") in ("x", "y"):
            q["axis"] = p["axis"]
        for k in ("r", "taper"):
            if isinstance(p.get(k), (int, float)) and 0 <= p[k] <= 50:
                q[k] = float(p[k])
        out.append(q)
    return out, why


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
    shape = str(b.get("shape") or "rect").strip().lower()
    if shape not in SHAPES:
        issues.append({"code": "board_shape", "ref": "shape", "msg": f"board.shape {b.get('shape')!r} is not one of {', '.join(SHAPES)} "
                       f"(rect; rounded: a rect with corner radius r mm; round: a circle of diameter w, h = w): kept rect"})
        shape = "rect"
    if shape != "rect":
        out["board"]["shape"] = shape
    if shape == "round" and (out["board"].get("w") or out["board"].get("h")):
        out["board"]["w"] = out["board"]["h"] = out["board"].get("w") or out["board"]["h"]  # the diameter
    if shape == "rounded" and b.get("r") is not None:
        try:
            r = float(b["r"])
            if not math.isfinite(r) or r < 0.5:
                raise ValueError
            side = min(out["board"].get("w") or MAX_W, out["board"].get("h") or MAX_W)
            out["board"]["r"] = round(min(r, side / 2), 1)
        except (TypeError, ValueError):
            issues.append({"code": "board_shape", "ref": "r", "msg": "board.r is a rounded board's corner radius in mm (0.5 up to half "
                           "its shorter side); left out, it is a sixth of the shorter side"})
    if b.get("locked") and out["board"].get("w") and out["board"].get("h"):
        # the person fixed the size (deviceapi.put_device): a cage for the build, where the designer's is a minimum
        out["board"]["locked"] = True
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
            prefix = PRIMS.get(kind, {}).get("prefix") or {"header": "J", "accessory": "A"}.get(kind, "U")
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
        if kind == "button" and raw.get("switch") not in (None, "", "tact"):
            sw = str(raw["switch"]).strip().lower()
            if sw in SWITCHES:
                node["switch"] = sw
            else:
                issues.append({"code": "unknown_switch", "ref": nid, "msg": f"switch {raw['switch']!r} is not known; use tact (default) or one of {', '.join(SWITCHES)}"})
        if kind == "header" and raw.get("connector"):
            con = str(raw["connector"]).strip().lower()
            if con in CONNECTORS:
                node["connector"] = con
            else:
                issues.append({"code": "unknown_connector", "ref": nid, "msg": f"connector {raw['connector']!r} is not known; use one of {', '.join(CONNECTORS)}, or leave it out for a 2.54 mm header"})
        for k in ("heatsink_w", "shaft_d", "shaft_h"):
            try:
                if raw.get(k) is not None and 0 < float(raw[k]) <= 500:
                    node[k] = round(float(raw[k]), 1)
            except (TypeError, ValueError):
                issues.append({"code": "bad_field", "ref": nid, "msg": f"{nid}.{k} is a number"})
        if raw.get("model") is not None:
            prims, why = model_prims(raw["model"])
            if prims:
                node["model"] = prims
            if why:
                issues.append({"code": "bad_model", "ref": nid, "msg": f"{nid}.model: {why}"})
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
        if kind == "accessory":
            key = acc.find(str(raw.get("accessory") or raw.get("key") or raw.get("module") or raw.get("label") or ""))
            if not key:
                issues.append({"code": "unknown_accessory", "ref": nid, "msg": f"accessory {raw.get('accessory')!r} is not known; use one of "
                               + ", ".join(f"{k} ({a['name']})" for k, a in acc.ACCESSORIES.items())})
                continue
            node["accessory"] = key
        e = _edge(raw.get("edge"))
        if e and kind in EDGE_KINDS and not (kind == "accessory" and acc.ACCESSORIES[node["accessory"]]["mount"] != "cable"):
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
        at = _place(raw.get("place"))
        if isinstance(at, str):
            issues.append({"code": "bad_place", "ref": nid, "msg": at})
        elif at and node.get("edge"):
            # an edge part (the module's USB, a connector) is laid out along its edge; moving it inwards breaks its port
            issues.append({"code": "place_on_edge_part", "ref": nid, "msg": f"{nid} sits on the {node['edge']} edge, so its place is "
                           f"ignored: move the parts that collide with it instead (or drop its edge)"})
        elif at and kind == "accessory" and acc.ACCESSORIES[node["accessory"]]["connect"] == "module_bat":
            pass  # a cell on the module's BAT pads is loose in the case, which puts it under the board or beside it: agent's _write says so
        elif at and kind != "hole":
            # placed by the designer (a part people see or touch): compiled as a fixed position, the person's pcb wins
            node["place"] = at
        if kind == "accessory" and acc.ACCESSORIES[node["accessory"]]["mount"] == "cable" and not (node.get("edge") or node.get("place") or node.get("pcb")):
            node["edge"] = "-y"  # a lead leaves the case through a wall: its connector sits on an edge
        face = str(raw.get("face") or "").strip().lower()
        if face in FACES:
            node["face"] = face
        elif face:
            issues.append({"code": "bad_face", "ref": nid, "msg": f"face {face!r} is not one of {', '.join(FACES)}"})
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
    # the current a net carries, as the designer states it: it stays with the net its pins ended up on
    for raw in doc.get("nets") or []:
        try:
            amps = float(raw.get("amps") or 0) if isinstance(raw, dict) else 0.0
        except (TypeError, ValueError):
            issues.append({"code": "bad_field", "ref": str(raw.get("name") or "net"), "msg": "a net's amps is a number"})
            continue
        if not math.isfinite(amps) or amps <= 0:
            continue
        refs = {str(r) for r in raw.get("pins") or []}
        for net in out["nets"]:
            if (raw.get("name") and net.get("name") == ident(raw["name"])) or refs & set(net["pins"]):
                net["amps"] = round(max(net.get("amps") or 0, min(amps, 200.0)), 2)
                break
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
    layouts: list[dict[str, Any]] = []
    for raw in (doc.get("layouts") or [])[:LAYOUT_MAX]:
        lay = _layout(raw, by_id)
        if isinstance(lay, str):
            issues.append({"code": "bad_layout", "ref": "layouts", "msg": lay})
        else:
            taken = {nid for x in layouts for nid in x["nodes"]}
            lay["nodes"] = [nid for nid in lay["nodes"] if nid not in taken]  # a node follows the first layout naming it
            if lay["nodes"]:
                layouts.append(lay)
    if layouts:
        out["layouts"] = layouts
    reqs: list[dict[str, Any]] = []
    for i, raw in enumerate((doc.get("requirements") or [])[:REQ_MAX]):
        if isinstance(raw, str):
            raw = {"text": raw}
        if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
            continue
        rid = ident(str(raw.get("id") or f"R{i + 1}"))[:12]
        req: dict[str, Any] = {"id": rid if rid not in {r["id"] for r in reqs} else f"R{i + 1}", "text": str(raw["text"]).strip()[:300],
                               "parts": list(dict.fromkeys(ident(str(p)) for p in raw.get("parts") or [] if str(p).strip()))[:12]}
        # a part the requirement names but the graph no longer has stays named: the requirement is not met without it
        for p in req["parts"]:
            if p not in by_id:
                issues.append({"code": "requirement_part_missing", "ref": req["id"],
                               "msg": f"requirement {req['id']} ({req['text'][:60]}) names {p}, which is not a part of the device"})
        if raw.get("firmware") is not None:
            req["firmware"] = bool(raw["firmware"])
        if isinstance(raw.get("test"), dict):
            req["test"] = raw["test"]
        reqs.append(req)
    if reqs:
        out["requirements"] = reqs
    concept = device_concept.clean(doc.get("concept"))  # the uses and the chosen look (device_concept): valid values only
    if concept:
        out["concept"] = concept
    if isinstance(doc.get("firmware"), dict):
        fw = doc["firmware"]
        files = {str(k)[:60]: str(v)[:40000] for k, v in (fw.get("files") or {}).items() if isinstance(v, str)}
        if files:
            out["firmware"] = {"lang": str(fw.get("lang") or "arduino")[:30], "files": dict(list(files.items())[:6]),
                               **({"notes": str(fw["notes"])[:1200]} if fw.get("notes") else {}),
                               # the firmware check's result (firmware_check.check, C3) that write_firmware stores
                               **({"check": fw["check"]} if isinstance(fw.get("check"), dict) else {})}
    return out, issues


def _place(raw: Any) -> dict[str, float] | str | None:
    """A designer's placement {x, y, rot} cleaned (mm from the board's centre, +y up, rot in degrees), None when absent,
    or why it is not one."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) in (2, 3):
        raw = dict(zip(("x", "y", "rot"), raw))
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), (int, float)) and math.isfinite(raw[k]) for k in ("x", "y")):
        return "place is {x, y, rot?}: the part's centre in mm from the board's centre (+y up), rotation in degrees"
    if max(abs(raw["x"]), abs(raw["y"])) > MAX_W / 2:
        return f"place ({raw['x']:g}, {raw['y']:g}) is off any board here (|x|, |y| <= {MAX_W / 2:g} mm from the centre)"
    rot = raw.get("rot") or 0
    rot = float(rot) if isinstance(rot, (int, float)) and math.isfinite(rot) else 0.0
    return {"x": round(float(raw["x"]), 2), "y": round(float(raw["y"]), 2), "rot": round(rot % 360, 1) + 0.0}


def _layout(raw: Any, by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | str:
    """One layout cleaned ({pattern, nodes, center, pitch, cols?, radius?, rot}) or why not."""
    if not isinstance(raw, dict) or raw.get("pattern") not in LAYOUTS:
        return f"a layout is {{pattern: {' | '.join(LAYOUTS)}, nodes: [ids], center?: [x, y], pitch?: mm, cols?, radius?, rot?}}"
    nodes = [nid for nid in dict.fromkeys(ident(str(n)) for n in raw.get("nodes") or []) if nid in by_id and by_id[nid]["kind"] != "hole"]
    if not nodes:
        return f"layout {raw['pattern']}: none of its nodes {raw.get('nodes')} is a part of the device"
    if raw["pattern"] == "dice" and len(nodes) > 7:
        return "a dice layout has 7 pips at most: centre, top-left, top-right, middle-left, middle-right, bottom-left, bottom-right"
    out: dict[str, Any] = {"pattern": raw["pattern"], "nodes": nodes}
    c = raw.get("center") or raw.get("centre") or [0, 0]
    if isinstance(c, dict):
        c = [c.get("x", 0), c.get("y", 0)]
    ok = isinstance(c, (list, tuple)) and len(c) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in c)
    out["center"] = [round(float(c[0]), 2), round(float(c[1]), 2)] if ok else [0.0, 0.0]
    num = lambda k, lo, hi, d: round(min(hi, max(lo, float(raw[k]))), 2) if isinstance(raw.get(k), (int, float)) and math.isfinite(raw[k]) else d  # noqa: E731
    out["pitch"] = num("pitch", 1.0, 40.0, 8.0)
    if raw["pattern"] == "grid" and isinstance(raw.get("cols"), (int, float)):
        out["cols"] = int(min(len(nodes), max(1, raw["cols"])))
    if raw["pattern"] == "ring" and raw.get("radius") is not None:
        out["radius"] = num("radius", 2.0, 45.0, 8.0)
    out["rot"] = round(num("rot", -360.0, 360.0, 0.0) % 360, 1) + 0.0
    return out


def layout_places(lay: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Where a layout puts its nodes: {id: {x, y, rot}}. dice: the pips at ±pitch in the order centre, top-left, top-right,
    middle-left, middle-right, bottom-left, bottom-right; row left to right, column top down, grid by rows from the top
    left (cols default to a square), ring clockwise from the top (radius default: the pitch apart along the circle).
    The whole pattern turns by rot about its centre, and each part with it."""
    nodes, p, n = lay["nodes"], float(lay.get("pitch") or 8.0), len(lay["nodes"])
    pat = lay["pattern"]
    if pat == "dice":
        offs = [(dx * p, dy * p) for dx, dy in DICE[:n]]
    elif pat == "row":
        offs = [((i - (n - 1) / 2) * p, 0.0) for i in range(n)]
    elif pat == "column":
        offs = [(0.0, ((n - 1) / 2 - i) * p) for i in range(n)]
    elif pat == "grid":
        cols = int(lay.get("cols") or math.ceil(math.sqrt(n)))
        rows = math.ceil(n / cols)
        offs = [((i % cols - (cols - 1) / 2) * p, ((rows - 1) / 2 - i // cols) * p) for i in range(n)]
    else:
        r = float(lay.get("radius") or max(p, p * n / (2 * math.pi)))
        offs = [(r * math.sin(2 * math.pi * i / n), r * math.cos(2 * math.pi * i / n)) for i in range(n)]
    rot = float(lay.get("rot") or 0)
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    cx, cy = lay.get("center") or [0, 0]
    return {nid: {"x": round(cx + x * c - y * s, 2) + 0.0, "y": round(cy + x * s + y * c, 2) + 0.0, "rot": rot}
            for nid, (x, y) in zip(nodes, offs)}


def places(doc: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Every fixed position the compiler honours, {id: {x, y, rot}}: the person's pcb first, then the designer's own
    place, then what the layouts give the nodes they list that have neither."""
    out: dict[str, dict[str, float]] = {}
    for lay in doc.get("layouts") or []:
        out.update({k: v for k, v in layout_places(lay).items() if k not in out})
    for n in doc["nodes"]:
        if n.get("pcb"):
            out[n["id"]] = n["pcb"]
        elif n.get("place"):
            out[n["id"]] = n["place"]
    return {n["id"]: out[n["id"]] for n in doc["nodes"] if n["id"] in out}


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
    if k == "button" and node.get("switch"):
        return [{"A": "pin1", "B": "pin2"}[pin]] if pin in ("A", "B") else []
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
    if k == "accessory":
        return list(acc.ACCESSORIES[node["accessory"]]["pins"])
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
        alias.update({f"GPIO{g}": lb for lb, g in MODULES[node["module"]].get("gpio", {}).items()})
    if k == "accessory":
        alias.update({"VDD": "VCC", "V3V3": "VCC", "3V3": "VCC", "5V": "VCC", "V5": "VCC", "VIN": "VCC", "+": "VCC" if "VCC" in up else "VBAT",
                      "-": "GND", "OUT": "AOUT" if "AOUT" in up else "OUT", "AO": "AOUT", "DATA": "DQ" if "DQ" in up else "SIG",
                      "SIGNAL": "SIG", "S": "SIG", "BAT": "VBAT", "BAT+": "VBAT", "BAT-": "GND", "BATP": "VBAT", "BATN": "GND"})
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
                if node.get("edge"):
                    # a connector from the catalogue: which way it opens says how it sits on its edge
                    got = await catalog.model_obj(raw)
                    parts[nid]["mouth"] = catalog.mouth_of(raw, got[1] if got else None)
                    if not parts[nid]["mouth"]:
                        issues.append({"code": "no_mouth", "ref": nid, "msg": f"{nid} ({card.get('mpn')}): its drawing does not show which way it opens, so it cannot be put on an edge: "
                                       "take another part of the same kind, a right-angle one"})
                        node.pop("edge", None)
            elif k in ("resistor", "capacitor"):
                parts[nid] = await catalog.resolve_basic(k, node["value"], node["package"]) or {}
            elif k == "led":
                parts[nid] = await catalog.resolve_basic("led", color=node.get("color", "green")) or {}
            elif k == "diode":
                parts[nid] = await catalog.resolve_basic("schottky") or {}
            elif k in ("usb_c", "jst"):
                parts[nid] = await catalog.resolve_basic("usb_c" if k == "usb_c" else "jst2") or {}
            elif k == "button" and node.get("switch"):
                sw = SWITCHES[node["switch"]]
                parts[nid] = {"mpn": sw["name"], "switch": node["switch"], "prices": [{"qty": 1, "usd": sw["price_usd"]}], "stock": None, "url": sw["url"], "pads": 2}
            elif k == "header" and node.get("connector"):
                c = CONNECTORS[node["connector"]]
                parts[nid] = {"mpn": f"{c['name']}, {len(node['pins'])} pole", "connector": node["connector"], "prices": [{"qty": 1, "usd": round(c["price_usd"] * len(node["pins"]), 2)}], "stock": None}
            elif k in ("header", "button"):
                parts[nid] = await catalog.resolve_basic(k) or {}
            elif k == "module":
                m = MODULES[node["module"]]
                parts[nid] = {"mpn": m["name"], "module": True, "prices": [{"qty": 1, "usd": m["price_usd"]}], "stock": None, "url": m["url"]}
            elif k == "accessory":
                a = acc.ACCESSORIES[node["accessory"]]
                # the module itself is bought finished and fitted by hand; the carrier gets only its connector
                conn = None
                if a["connect"] == "header" or (a["connect"] == "jst" and len(a["pins"]) == 2):
                    conn = await catalog.resolve_basic("header" if a["connect"] == "header" else "jst2")
                parts[nid] = {"mpn": a["name"], "accessory": node["accessory"], "prices": [{"qty": 1, "usd": a["price_usd"]}], "stock": None,
                              "url": a.get("url"), **({"connector": conn} if conn else {})}
            else:
                parts[nid] = {}
        except catalog.CatalogError as e:
            issues.append({"code": "part_unavailable", "ref": nid, "msg": str(e)})
            parts[nid] = {"error": str(e)}

    await asyncio.gather(*(one(n) for n in doc["nodes"]))
    # chip pin references against the real pinout; a graph saved before the catalogue renamed pins ('BZ1.P', 'Q1.P1')
    # still finds them (chip_labels), and is told when an old name stood for several terminals
    by_id = {n["id"]: n for n in doc["nodes"]}
    for net in doc["nets"]:
        keep = []
        for ref in net["pins"]:
            nid, pin = ref.split(".", 1)
            node = by_id.get(nid)
            if node and node["kind"] == "chip" and parts.get(nid, {}).get("pins"):
                labels, how = chip_labels(parts[nid], pin)
                if not labels:
                    names = pins_of(node, parts[nid])
                    issues.append({"code": "bad_pin", "ref": ref, "msg": f"{ref}: {nid} ({parts[nid].get('mpn')}) has no pin {pin}; its pins are "
                                   + ", ".join(n for n in names if not n.upper().startswith("NC"))[:400]})
                    continue
                bases = list(dict.fromkeys(catalog.base_label(lb) for lb in labels))
                if len(bases) == 1:
                    ref = f"{nid}.{bases[0]}"
                else:  # an old name of several terminals (the MLT-5020's '+' and '-' were both 'P'): wired as it was
                    issues.append({"code": "legacy_pin", "ref": ref, "msg": f"{ref} is an old name that stands for {', '.join(labels)} of "
                                   f"{nid} ({parts[nid].get('mpn')}): they stay on one net as before, which joins them; wire each "
                                   f"terminal by its own label ({', '.join(f'{nid}.{lb}' for lb in labels)})"})
            keep.append(ref)
        net["pins"] = keep
    doc["nets"] = [n for n in doc["nets"] if len(n["pins"]) >= 2 or n.get("name")]
    # fixed spots that collide (a display placed into the module's band): said now, not after a wasted build
    try:
        issues += place_issues(doc, parts)
    except Exception:  # noqa: BLE001 - a geometry slip must not cost the editor its document
        log.exception("placement check failed")
    return parts, issues


def _part_text(part: dict[str, Any]) -> str:
    return " ".join(str(part.get(k) or "") for k in ("kind_hint", "mpn", "category", "package", "footprint_name", "description"))


def needs_decoupling(part: dict[str, Any]) -> bool:
    """An IC with supply pins wants its own 100nF; a transistor, diode, buzzer, LED or connector does not. The catalogue's
    kind hint settles it (C6); without one, three pins or fewer is a discrete, and the category (or the description when
    the card has none) names the rest."""
    hint = str(part.get("kind_hint") or "").lower()
    if hint:
        return hint not in DISCRETE_HINTS
    if len(part.get("pins") or []) <= 3:
        return False
    return not DISCRETE_TEXT.search(str(part.get("category") or "") or f"{part.get('description') or ''} {part.get('package') or ''}")


def face_of(node: dict[str, Any], part: dict[str, Any] | None = None) -> str:
    """What a part needs from the case above it (C1c): the node's own face, else light for LEDs and addressable LED chips,
    sound for buzzers and speakers, sensor for PIR, light/UV/colour, gas/air/humidity sensors and microphones, display for
    a display accessory, none for the rest."""
    if node.get("face") in FACES:
        return node["face"]
    k = node["kind"]
    if k == "led":
        return "light"
    if k == "accessory":
        return {"display": "display", "sensor": "sensor"}.get(acc.ACCESSORIES[node["accessory"]]["kind"], "none")
    if k != "chip":
        return "none"
    part = part or {}
    hint = str(part.get("kind_hint") or "").lower()
    if hint in HINT_FACE:
        return HINT_FACE[hint]
    text = _part_text(part)
    for face, rx in FACE_TEXT:
        if rx.search(text) and not (face == "light" and re.search(r"driver|controller|dimmer|sensor", text, re.I)
                                    and not re.search(r"WS28|SK68|APA10|addressable", text, re.I)):
            return face
    return "none"


def open_pins(node: dict[str, Any], on_net: Any) -> list[str]:
    """The pins a header declares that no net has: the designer named them, so something was meant to go there."""
    return [str(p) for p in node.get("pins") or [] if f"{node['id']}.{p}" not in on_net]


def lint(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Design checks a netlist can answer before any routing: unconnected parts, a USB-C without CC pull-downs, an LED
    without a resistor, chips without decoupling, single-pin nets; and a board far larger than its parts when a smaller
    arrangement exists (compaction()). Warnings: the designer decides."""
    out: list[dict[str, str]] = []
    by_id = {n["id"]: n for n in doc["nodes"]}
    net_of: dict[str, dict[str, Any]] = {}
    for net in doc["nets"]:
        for p in net["pins"]:
            net_of[p] = net
    for node in doc["nodes"]:
        nid, k = node["id"], node["kind"]
        mine = [p for p in net_of if p.split(".", 1)[0] == nid]
        if k == "accessory" and acc.ACCESSORIES[node["accessory"]]["connect"] == "module_bat":
            if mine:
                out.append({"code": "battery_wiring", "ref": nid, "msg": f"{nid} is a LiPo cell: it goes on the module's BAT pads, not on "
                            f"the carrier's nets ({', '.join(mine)}); take it off them, the compiler leaves those wires out"})
            continue
        if k != "hole" and not mine:
            out.append({"code": "unconnected", "ref": nid, "msg": f"{nid} is not connected to anything"})
            continue
        if k == "header":
            for pin in open_pins(node, net_of):
                out.append({"code": "open_pin", "ref": f"{nid}.{pin}", "msg": f"{nid}.{pin} is wired to nothing: whatever plugs in there reaches no part"})
        if k == "usb_c":
            for cc in ("CC1", "CC2"):
                if f"{nid}.{cc}" not in net_of:
                    out.append({"code": "usb_cc", "ref": nid, "msg": f"{nid}.{cc} needs 5.1k to GND, or a USB-C charger gives no 5 V"})
        if k == "led":
            a, kk = net_of.get(f"{nid}.A"), net_of.get(f"{nid}.K")
            pins = (a or {}).get("pins", []) + (kk or {}).get("pins", [])
            if not any(p.split(".")[0] in {n["id"] for n in doc["nodes"] if n["kind"] == "resistor"} for p in pins):
                out.append({"code": "led_resistor", "ref": nid, "msg": f"{nid} has no series resistor (1k from the GPIO to its A pin)"})
        if k == "chip" and needs_decoupling(parts.get(nid) or {}):
            supply = [p for p in mine if is_supply(net_of[p], by_id, parts)]
            caps = {n["id"] for n in doc["nodes"] if n["kind"] == "capacitor"}
            if supply and not any(q.split(".")[0] in caps for p in supply for q in net_of[p]["pins"]):
                out.append({"code": "decoupling", "ref": nid, "msg": f"{nid} has no capacitor on its supply: add 100nF from {supply[0].split('.')[1]} to GND"})
    for net in doc["nets"]:
        if len(net["pins"]) < 2:
            out.append({"code": "single_pin_net", "ref": net.get("name") or net["pins"][0], "msg": f"net {net.get('name') or net['pins'][0]} has only one pin"})
    try:
        roomy = compaction(doc, parts)
    except Exception:  # noqa: BLE001 - a geometry slip must not cost the designer its other warnings
        log.exception("compaction check failed")
        roomy = None
    if roomy:
        out.append({"code": "board_too_large", "ref": "board", "msg": roomy["msg"]})
    return out + route_problems(doc, parts)


# ------------------------------------------------------------------ geometry: size and edges
def _conn_kind(node: dict[str, Any]) -> str:
    """The kind of the part the compiler puts on the carrier for a node: an accessory's connector is a header or a JST."""
    if node["kind"] != "accessory":
        return node["kind"]
    a = acc.ACCESSORIES[node["accessory"]]
    return "jst" if a["connect"] == "jst" else "header"


def _footprint_size(node: dict[str, Any], part: dict[str, Any]) -> tuple[float, float]:
    k = node["kind"]
    if k == "button" and node.get("switch"):
        return tuple(SWITCHES[node["switch"]]["cap"])  # type: ignore[return-value]
    if k == "header" and node.get("connector"):
        c = CONNECTORS[node["connector"]]
        return (c["pitch"] * len(node.get("pins") or []) + 0.8, c["d"])
    if k in ("resistor", "capacitor"):
        return SIZE[node.get("package", "0603")]
    if k == "accessory":
        a = acc.ACCESSORIES[node["accessory"]]
        if a["connect"] == "module_bat":
            return (0.0, 0.0)
        if a["mount"] == "board":  # the module's body over its header: nothing else goes under it
            return (a["body"][0], a["body"][1])
        n = len(a["pins"])
        return (2.0 * (n - 1) + 4.0, 6.0) if a["connect"] == "jst" else (2.54 * n + 0.8, 3.5)
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
    if k == "chip" and part.get("mouth"):
        return part["mouth"]["w"], part["mouth"]["d"]
    w, h = _footprint_size(node, part)
    if k == "usb_c":
        return 10.4, 8.4
    if k == "module":
        return w, h
    return (max(w, h), min(w, h))


def _board_mounted(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in doc["nodes"] if n["kind"] == "accessory" and acc.ACCESSORIES[n["accessory"]]["mount"] == "board"]


def estimate(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> tuple[float, float]:
    """The board size the build starts from: base_size() grown by fit() until every fixed spot clears the edge parts, the
    outline and the corner holes, then by room() until the placer has a spot for every free part, a side nobody chose trimmed
    (_trim) to what that takes; the person's size (board.locked) as it is."""
    W, H = base_size(doc, parts)
    return (W, H) if doc["board"].get("locked") else _trim(doc, parts, room(doc, parts, fit(doc, parts, (W, H))))


def _floor(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> tuple[float, float, float]:
    """(W, H) below which the edge parts and the modules on the board do not fit between the corner holes, and the area the
    parts get, mm²."""
    holes = doc["board"].get("holes", True)
    corner = 8.0 if holes else 2.0
    need = {e: 0.0 for e in EDGES}
    depth = {e: 0.0 for e in EDGES}
    fixed = free = 0.0
    at = places(doc)
    stack, widest = 0.0, 0.0
    for n in doc["nodes"]:
        if n["kind"] == "hole":
            continue
        w, h = _footprint_size(n, parts.get(n["id"], {}))
        if n.get("edge") and n["id"] not in at:
            a, d = _along(n, parts.get(n["id"], {}))
            need[n["edge"]] += a + 2.0
            depth[n["edge"]] = max(depth[n["edge"]], d)
            fixed += w * h * 1.25
        elif n["kind"] == "accessory" or n["id"] in at:
            fixed += w * h * 1.2
            if n["kind"] == "accessory" and n["id"] not in at and w:
                stack += h + 4.0  # its body, and a band above it for the parts packed between it and the top edge
                widest = max(widest, w)
        else:
            free += w * h * (2.6 if n["kind"] in ("resistor", "capacitor", "led") else 3.0)
    W = max(need["-y"], need["+y"]) + 2 * corner
    H = max(need["-x"], need["+x"]) + 2 * corner
    # a side edge part spans the depth of the top/bottom ones too
    W = max(W, depth["-x"] + depth["+x"] + 10)
    H = max(H, depth["-y"] + depth["+y"] + 10)
    if stack:  # modules on the board stack up from the bottom edge parts (or the corner holes) to the top ones
        W = max(W, widest + 2 * max(depth["-x"], depth["+x"]) + 2 * PACK_GAP_MM + 2.0)  # the module is centred across
        H = max(H, depth["+y"] + stack + max(depth["-y"] + 1.0, corner if widest + 2 > W - 2 * corner else 1.5) + 2.0)
    return W, H, (fixed + free) * 1.15 + 60


def base_size(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> tuple[float, float]:
    """Board width and height (mm) to start from: edge parts must fit side by side, the free parts get about three times
    their own area, a module that sits on the board (an OLED) its body plus a margin, stacked between the top and bottom edge
    parts; room() has the last word. board.w/h when given (the designer's are a minimum for estimate(), the person's a
    cage). Whole millimetres."""
    W, H, area = _floor(doc, parts)
    side = math.sqrt(area)
    W, H = max(W, side * 0.9, 24.0), max(H, side * 0.9, 24.0)
    if W * H < area:
        f = math.sqrt(area / (W * H))
        W, H = W * f, H * f
    b = doc["board"]
    if b.get("w") and b.get("h"):
        return float(b["w"]), float(b["h"])
    W, H = float(min(MAX_W, b.get("w") or math.ceil(W))), float(min(MAX_W, b.get("h") or math.ceil(H)))
    if b.get("shape") == "round":  # a circle as roomy as the rectangle: its area at least, and its longer side across
        W = H = float(min(MAX_W, math.ceil(max(W, H, 1.13 * math.sqrt(W * H)))))
    return W, H


def accessory_places(doc: dict[str, Any], parts: dict[str, dict[str, Any]], W: float, H: float) -> dict[str, dict[str, float]]:
    """Where a module that sits on the board goes when neither the designer nor the person placed it: its body centred
    across the board, the first one just above the bottom edge parts (or above the corner holes when it is too wide to
    pass between them), the next ones stacked above it. Unrotated, so a display reads upright."""
    at = places(doc)
    holes = doc["board"].get("holes", True)
    low = max([_along(n, parts.get(n["id"], {}))[1] for n in doc["nodes"] if n.get("edge") == "-y" and n["id"] not in at] or [0.0])
    y = -H / 2 + (low + 1.0 if low else 1.5)
    out: dict[str, dict[str, float]] = {}
    o = outline(doc, (W, H))
    for n in _board_mounted(doc):
        if n["id"] in at:
            continue
        w, d = _footprint_size(n, {})
        if o["shape"] != "rect":  # a curved bottom edge: the body's lower corners inside it
            rim = _rim(o, "-y", w / 2)
            y = max(y, -(rim if rim is not None else 0.0) + 1.0)
        if holes and o["shape"] != "round" and w / 2 + 1.0 > W / 2 - 7.5:
            y = max(y, -H / 2 + 7.5)
        out[n["id"]] = {"x": 0.0, "y": round(y + d / 2, 2), "rot": 0.0}
        y += d + 2.0
    return out


def accessory_anchor(node: dict[str, Any], body: dict[str, float]) -> dict[str, float]:
    """pcbX/pcbY/pcbRotation of a board-mounted module's connector from where its body is ({x, y, rot})."""
    a = acc.ACCESSORIES[node["accessory"]]
    dx, dy = a.get("header_offset") or (0.0, 0.0)
    rot = float(body.get("rot") or 0)
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    return {"pcbX": round(body["x"] + dx * c - dy * s, 2) + 0.0, "pcbY": round(body["y"] + dx * s + dy * c, 2) + 0.0, "pcbRotation": rot}


# ------------------------------------------------------------------ the board's outline: rect, rounded, round
def outline(doc: dict[str, Any], size: tuple[float, float]) -> dict[str, Any]:
    """The board's outline on a W x H board: {shape, w, h, r}; r is a rounded board's corner radius (board.r, else a sixth
    of the shorter side) and a round board's radius (a circle of diameter W: its h is W too), 0 for a rect."""
    W, H = float(size[0]), float(size[1])
    b = doc.get("board") or {}
    shape = b.get("shape") if b.get("shape") in SHAPES else "rect"
    if shape == "round":
        return {"shape": "round", "w": W, "h": W, "r": W / 2}
    if shape == "rounded":
        return {"shape": "rounded", "w": W, "h": H, "r": min(float(b.get("r") or round(min(W, H) / 6, 1)), min(W, H) / 2)}
    return {"shape": "rect", "w": W, "h": H, "r": 0.0}


def _arc(o: dict[str, Any]) -> float:
    """The radius the checks use for the outline's curve: the polygon it is built as lies this far in at its chords."""
    n = ROUND_SEGMENTS if o["shape"] == "round" else 4 * CORNER_SEGMENTS
    return o["r"] * math.cos(math.pi / n)


def outline_points(o: dict[str, Any]) -> list[tuple[float, float]]:
    """A curved outline as the polygon the board is built with (mm from the board's centre, counter-clockwise from +x);
    [] for a rect, which stays tscircuit's width x height."""
    if o["shape"] == "round":
        R = o["r"]
        return [(round(R * math.cos(2 * math.pi * i / ROUND_SEGMENTS), 3) + 0.0, round(R * math.sin(2 * math.pi * i / ROUND_SEGMENTS), 3) + 0.0)
                for i in range(ROUND_SEGMENTS)]
    if o["shape"] != "rounded":
        return []
    r, cx, cy = o["r"], o["w"] / 2 - o["r"], o["h"] / 2 - o["r"]
    pts: list[tuple[float, float]] = []
    for qx, qy, a0 in ((1, 1, 0), (-1, 1, 90), (-1, -1, 180), (1, -1, 270)):
        for j in range(CORNER_SEGMENTS + 1):
            a = math.radians(a0 + 90 * j / CORNER_SEGMENTS)
            p = (round(qx * cx + r * math.cos(a), 3) + 0.0, round(qy * cy + r * math.sin(a), 3) + 0.0)
            if not pts or (abs(p[0] - pts[-1][0]) > 1e-3 or abs(p[1] - pts[-1][1]) > 1e-3):
                pts.append(p)
    return pts if abs(pts[0][0] - pts[-1][0]) > 1e-3 or abs(pts[0][1] - pts[-1][1]) > 1e-3 else pts[:-1]


def _rim(o: dict[str, Any], edge: str, u: float) -> float | None:
    """How far the board's edge lies from the centre along the outward normal of `edge`, at u along that edge (x for the
    ±y edges, y for ±x); None where the board does not reach u."""
    along_x = edge in ("+y", "-y")
    half_t, half_n = (o["w"] / 2, o["h"] / 2) if along_x else (o["h"] / 2, o["w"] / 2)
    u = abs(u)
    if u > half_t + 1e-9:
        return None
    if o["shape"] == "round":
        R = _arc(o)
        return math.sqrt(R * R - u * u) if u <= R else None
    if o["shape"] == "rounded":
        d = u - (half_t - o["r"])
        if d <= 0:
            return half_n
        re = _arc(o)
        return half_n - o["r"] + math.sqrt(re * re - d * d) if d <= re else None
    return half_n


def _outside(o: dict[str, Any], x: float, y: float) -> float:
    """How far a point lies outside the outline, mm (0 or less: inside)."""
    ax, ay = abs(x), abs(y)
    if o["shape"] == "round":
        return math.hypot(ax, ay) - _arc(o)
    if o["shape"] == "rounded":
        cx, cy = o["w"] / 2 - o["r"], o["h"] / 2 - o["r"]
        if ax > cx and ay > cy:
            return math.hypot(ax - cx, ay - cy) - _arc(o)
    return max(ax - o["w"] / 2, ay - o["h"] / 2)


def _corners(r: tuple[float, ...]) -> list[tuple[float, float]]:
    return [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]


def poking(o: dict[str, Any], rect: tuple[float, ...]) -> dict[str, float]:
    """How far a courtyard has to come in from each side it crosses, or lies closer than EDGE_MARGIN_MM to: {side: mm}. A
    curved stretch is charged to the side whose straight move in clears that corner soonest (a corner out at the upper
    right of a round board: in from +x or from +y, whichever is less). The outline is convex, so the four corners inside
    mean all inside."""
    m = EDGE_MARGIN_MM
    if o["shape"] == "rect":
        W, H = o["w"], o["h"]
        d = {"-x": -W / 2 - rect[0], "+x": rect[2] - W / 2, "-y": -H / 2 - rect[1], "+y": rect[3] - H / 2}
        return {k: round(v + m, 2) for k, v in d.items() if v > -m + 0.005}
    out: dict[str, float] = {}
    for x, y in _corners(rect):
        if _outside(o, x, y) <= -m + 0.005:
            continue
        best: tuple[str, float] | None = None
        for side in EDGES:
            t, n = (x, y) if side[1] == "y" else (y, x)
            n = n if side[0] == "+" else -n
            rim = _rim(o, side, t)
            if rim is not None and n > 0 and n - rim > -m + 0.005 and (best is None or n - rim + m < best[1]):
                best = (side, n - rim + m)
        if best is None:  # beyond the outline along both axes: in from the side it is furthest out at
            side = ("+x" if x > 0 else "-x") if abs(x) / o["w"] >= abs(y) / o["h"] else ("+y" if y > 0 else "-y")
            best = (side, max(abs(x) - o["w"] / 2, abs(y) - o["h"] / 2, 0.0) + _outside(o, x, y) + m)
        out[best[0]] = round(max(out.get(best[0], 0.0), best[1]), 2)
    return out


def _onto_rim(o: dict[str, Any], rect: tuple[float, ...], edge: str) -> float:
    """How far an edge part moves in from `edge` so its courtyard's outer corners lie on a curved outline rather than past
    it (its outer face becomes a chord of the circle, or of a rounded corner): 0 on a straight stretch."""
    if o["shape"] == "rect":
        return 0.0
    sign = 1 if edge[0] == "+" else -1
    t = 0.0
    for x, y in _corners(rect):
        tan, n = (x, y * sign) if edge[1] == "y" else (y, x * sign)
        rim = _rim(o, edge, tan)
        t = max(t, n - (rim if rim is not None else 0.0))
    return math.ceil(t * 100) / 100 if t > 0.005 else 0.0


def describe_outline(o: dict[str, Any]) -> str:
    if o["shape"] == "round":
        return f"{o['w']:g} mm round board"
    return f"{o['w']:g} x {o['h']:g} mm board" + (f" with {o['r']:g} mm corners" if o["shape"] == "rounded" else "")


# ------------------------------------------------------------------ placement: fixed spots, the free area, conflicts
# courtyards w x h at rotation 0 as the PCB worker's footprints draw them (measured on built boards)
COURTYARD = {"0402": (1.9, 1.0), "0603": (2.96, 1.46), "0805": (3.4, 1.9), "1206": (4.4, 2.3)}
PLACE_GAP_MM = 0.3   # between fixed courtyards: the DRC wants them apart, the router a little room
HOLE_KEEP_MM = 2.1   # a corner mounting hole's radius (3.2 mm) plus its copper clearance
EDGE_MARGIN_MM = 0.1  # a placed courtyard inside the outline: tscircuit's check is strict and a catalogue footprint's model
                      # outline carries a rounding (the MLT-5020 at x = 18 of a 48 mm board: 'outside by 0mm', a whole step lost)


def local_box(node: dict[str, Any], part: dict[str, Any] | None = None) -> tuple[float, float, float, float] | None:
    """A part's courtyard (x0, y0, x1, y1) around its origin at rotation 0, or None when it puts nothing on the carrier.
    A board-mounted accessory's origin is its body's centre (its place); a chip's comes from the catalogue box and pads."""
    k, part = node["kind"], part or {}
    centred = lambda w, h: (-w / 2, -h / 2, w / 2, h / 2)  # noqa: E731
    if k in ("resistor", "capacitor"):
        return centred(*COURTYARD.get(node.get("package") or "0603", COURTYARD["0603"]))
    if k == "led":
        return centred(*COURTYARD["0603"])
    if k == "diode":
        return centred(4.7, 2.3)
    if k == "button":
        return centred(*SWITCHES[node["switch"]]["cap"]) if node.get("switch") else centred(7.0, 9.0)
    if k == "usb_c":
        return (-5.2, -5.5, 5.2, 2.9)
    if k == "module":
        return centred(*MODULES[node["module"]]["size"])
    if k == "hole":
        return centred(7.2, 7.2)
    if k == "accessory":
        a = acc.ACCESSORIES[node["accessory"]]
        if a["connect"] == "module_bat":
            return None
        if a["mount"] == "board":
            return centred(a["body"][0], a["body"][1])
        n = len(a["pins"])
        return (-(n - 1) - 2.45, -3.3, (n - 1) + 2.45, 2.2) if a["connect"] == "jst" else centred(2.54 * n + 1.0, 3.54)
    if k == "header" and node.get("connector"):
        c = CONNECTORS[node["connector"]]
        return centred(c["pitch"] * len(node.get("pins") or []) + 1.0, c["d"] + 0.04)
    if k == "header":
        return centred(2.54 * len(node.get("pins") or []) + 1.0, 3.54)
    if k == "jst":
        return (-3.45, -3.3, 3.45, 2.2)
    if k == "chip":
        # as the worker's EasyEDA converter draws it: the 3D model's outline and the pads, else the package's box; +0.25
        pads, box = part.get("pads"), part.get("box")
        xs: list[float] = []
        ys: list[float] = []
        model = _model_outline(part.get("raw") or {})
        if model or not box:
            for x, y, w, h in (pads.values() if isinstance(pads, dict) else []):
                xs += [x - w / 2, x + w / 2]
                ys += [y - h / 2, y + h / 2]
        for b_ in (model or box,):
            if b_:
                xs += [b_[0], b_[2]]
                ys += [b_[1], b_[3]]
        if xs:
            return (min(xs) - 0.25, min(ys) - 0.25, max(xs) + 0.25, max(ys) + 0.25)
        s = part.get("size_mm") or [5.0, 5.0]
        return centred(s[0] + 0.5, s[1] + 0.5)
    return centred(3.0, 3.0)


_model_outline = catalog.model_outline


def _turned(box: tuple[float, float, float, float], x: float, y: float, rot: float) -> tuple[float, float, float, float]:
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    pts = [(px * c - py * s, px * s + py * c) for px, py in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]))]
    return (round(x + min(p[0] for p in pts), 3), round(y + min(p[1] for p in pts), 3), round(x + max(p[0] for p in pts), 3), round(y + max(p[1] for p in pts), 3))


def fixed_parts(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float]) -> list[dict[str, Any]]:
    """Every part with a fixed spot on a W x H board, with its courtyard rect (mm from the board's centre): how it got
    there ('edge': an edge part; 'place': the designer's place or layout; 'pcb': the person's; 'auto': a board-mounted
    module's default spot; 'cap': a decoupling capacitor the compiler puts beside a fixed chip, `of` that chip)."""
    W, H = size
    by_id = {n["id"]: n for n in doc["nodes"]}
    at = places(doc)
    auto = accessory_places(doc, parts, W, H)
    out: list[dict[str, Any]] = []
    for nid, p in layout_edges(doc, parts, W, H).items():
        if nid not in at:
            box = local_box(by_id[nid], parts.get(nid))
            if box:
                out.append({"id": nid, "how": "edge", "edge": by_id[nid]["edge"], "x": p["pcbX"], "y": p["pcbY"], "rect": _turned(box, p["pcbX"], p["pcbY"], p["pcbRotation"])})
    for nid, p in {**auto, **at}.items():
        n = by_id[nid]
        box = local_box(n, parts.get(nid))
        if box:
            out.append({"id": nid, "how": "pcb" if n.get("pcb") else "auto" if nid in auto and nid not in at else "place",
                        "x": p["x"], "y": p["y"], "rect": _turned(box, p["x"], p["y"], float(p.get("rot") or 0))})
    plan, _ = decoupling(doc, parts)
    packages = {n["id"]: n.get("package", "0603") for n in doc["nodes"] if n["kind"] == "capacitor"}
    for chip, caps in plan.items():
        if chip not in at:
            continue
        turn = float(at[chip].get("rot") or 0)
        c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
        for cap, sp in _cap_spots(parts[chip], caps, packages).items():
            if cap in at:
                continue
            x, y = at[chip]["x"] + sp["pcbX"] * c - sp["pcbY"] * s, at[chip]["y"] + sp["pcbX"] * s + sp["pcbY"] * c
            out.append({"id": cap, "how": "cap", "of": chip, "chip_at": (at[chip]["x"], at[chip]["y"]), "x": round(x, 2), "y": round(y, 2),
                        "rect": _turned(local_box(by_id[cap]), x, y, sp["pcbRotation"] + turn)})  # type: ignore[arg-type]
    return out


def _holes(doc: dict[str, Any], W: float, H: float) -> list[tuple[float, float]]:
    """The four mounting holes, RIM_MM in from the edge: at a rectangle's corners, on the diagonals of a round board
    (45 degrees), at a rounded board's corners pulled in along the diagonal of each corner arc."""
    if not (doc["board"].get("holes", True) and W >= 26 and H >= 26):
        return []
    o = outline(doc, (W, H))
    if o["shape"] == "round":
        kx = ky = (o["r"] - RIM_MM) / math.sqrt(2)
    elif o["shape"] == "rounded" and o["r"] > RIM_MM:
        kx, ky = (s / 2 - o["r"] + (o["r"] - RIM_MM) / math.sqrt(2) for s in (W, H))
    else:
        kx, ky = W / 2 - RIM_MM, H / 2 - RIM_MM
    return [(round(sx * kx, 2) + 0.0, round(sy * ky, 2) + 0.0) for sx, sy in ((-1, 1), (1, 1), (-1, -1), (1, -1))]


def _overlap(a: tuple[float, ...], b: tuple[float, ...], gap: float = 0.0) -> tuple[float, float] | None:
    ox, oy = min(a[2], b[2]) - max(a[0], b[0]) + gap, min(a[3], b[3]) - max(a[1], b[1]) + gap
    return (round(ox, 2), round(oy, 2)) if ox > 0.05 and oy > 0.05 else None


def _clearing(r: tuple[float, ...], b: dict[str, Any]) -> float:
    """How far a rect must go along an edge part's normal to come clear of it: a part held inside the module's band has to
    leave by its far side, more than the overlap of the two says."""
    br = b["rect"]
    return round({"+y": r[3] - br[1], "-y": br[3] - r[1], "+x": r[2] - br[0], "-x": br[2] - r[0]}[b["edge"]], 2)


def conflicts(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float]) -> list[dict[str, Any]]:
    """Where fixed parts collide on a W x H board: a placed part ('place', 'pcb', 'auto', 'cap') with an edge part,
    another placed part, the board outline or a corner hole. [{a, b?, kind: 'part'|'outline'|'hole', ox, oy, ...}]; a
    pair of edge parts is the edge layout's to sort out and is left out, as is a chip with its own capacitor."""
    W, H = size
    fx = fixed_parts(doc, parts, size)
    ol = outline(doc, size)
    out: list[dict[str, Any]] = []
    for i, a in enumerate(fx):
        if a["how"] == "edge":
            continue
        r = a["rect"]
        for side, d in poking(ol, r).items():  # the real outline: a round board's rim, a rounded board's corners
            out.append({"a": a, "kind": "outline", "side": side, "by": d})
        for hx, hy in _holes(doc, W, H):
            o = _overlap(r, (hx - HOLE_KEEP_MM, hy - HOLE_KEEP_MM, hx + HOLE_KEEP_MM, hy + HOLE_KEEP_MM))
            if o:
                out.append({"a": a, "kind": "hole", "at": (round(hx, 2), round(hy, 2)), "ox": o[0], "oy": o[1]})
        for j, b in enumerate(fx):
            if (b["how"] != "edge" and j <= i) or a.get("of") == b["id"] or b.get("of") == a["id"] or (a.get("of") and a.get("of") == b.get("of")):
                continue
            o = _overlap(r, b["rect"])
            if o:
                out.append({"a": a, "b": b, "kind": "part", "ox": o[0], "oy": o[1]})
    return out


def fit(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float]) -> tuple[float, float]:
    """The board grown until every placed part clears the edge parts, the outline and the corner holes. A place is from
    the board's centre, so growing h by d moves the +y edge (and the module on it) up by d/2. Two placed parts that
    overlap stay overlapped however large the board: conflicts() reports those. A round board grows as a circle (w = h)."""
    W, H = size
    round_ = doc["board"].get("shape") == "round"
    for _ in range(12):
        dw = dh = 0.0
        for c in conflicts(doc, parts, (W, H)):
            if c["kind"] == "outline":
                if c["side"] in ("-x", "+x"):
                    dw = max(dw, 2 * c["by"] + 2 * PLACE_GAP_MM)
                else:
                    dh = max(dh, 2 * c["by"] + 2 * PLACE_GAP_MM)
            elif c["kind"] == "hole":
                if c["ox"] <= c["oy"]:
                    dw = max(dw, 2 * c["ox"] + 2 * PLACE_GAP_MM)
                else:
                    dh = max(dh, 2 * c["oy"] + 2 * PLACE_GAP_MM)
            elif c["b"]["how"] == "edge":
                if c["b"]["edge"] in ("-y", "+y"):
                    dh = max(dh, 2 * (_clearing(c["a"]["rect"], c["b"]) + PLACE_GAP_MM))
                else:
                    dw = max(dw, 2 * (_clearing(c["a"]["rect"], c["b"]) + PLACE_GAP_MM))
        if not (dw or dh) or (W >= MAX_W and H >= MAX_W):
            break
        if round_:
            dw = dh = max(dw, dh)
        W, H = min(MAX_W, float(math.ceil(W + dw))), min(MAX_W, float(math.ceil(H + dh)))
    return W, H


def free_area(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float] | None = None) -> dict[str, Any]:
    """The rectangle left for placed parts on the board the build uses (or `size`): inside the outline, clear of what the
    edge parts take on each side. {x: [x0, x1], y: [y0, y1], board: [W, H]}, mm from the board's centre (+y up)."""
    W, H = size or estimate(doc, parts)
    x0, y0, x1, y1 = -W / 2 + 0.5, -H / 2 + 0.5, W / 2 - 0.5, H / 2 - 0.5
    for f in fixed_parts(doc, parts, (W, H)):
        r, e = f["rect"], f.get("edge")
        if f["how"] != "edge":
            continue
        if e == "+y":
            y1 = min(y1, r[1] - PLACE_GAP_MM)
        elif e == "-y":
            y0 = max(y0, r[3] + PLACE_GAP_MM)
        elif e == "+x":
            x1 = min(x1, r[0] - PLACE_GAP_MM)
        else:
            x0 = max(x0, r[2] + PLACE_GAP_MM)
    return {"x": [round(x0, 1), round(x1, 1)], "y": [round(y0, 1), round(y1, 1)], "board": [W, H]}


# ------------------------------------------------------------------ the placer: a spot for every part nobody placed
# between a free courtyard and any other part's, the widest that fits (device_bench, 17 documents: at 0.6 mm the router gave
# up on the round night lights, 68 -> 100 mm; at 1.0 mm 40 of 42 boards took a first or second attempt; at 1.4 mm all and in
# half the time, for a step more board where room is tight)
ARRANGE_GAPS_MM = (1.4, 1.0)
ARRANGE_RIM_MM = 1.0    # a free courtyard from the outline: a trace passes (at 0.5 mm a router's 'too close to the board edge', more vias)
ARRANGE_RIM_TIGHT_MM = 0.5  # the same when nothing else gets everything down: a step of board saved (a round leak sensor, 50 -> 48 mm)
ARRANGE_STEP_MM = 0.5   # the grid free parts sit on, from the board's centre
ARRANGE_SLACK_MM = 3.0  # how much further from the ideal spot a candidate may lie and still be weighed by its pins
BIG_MM2 = 20.0          # a unit at least this large goes first: small parts find room around a large one, not the reverse
ROOM_STEP_MM = 2.0      # room(): how much a side grows at a time


def _pin_pads(node: dict[str, Any], part: dict[str, Any], pin: str) -> list[tuple[float, float]]:
    """Where a device pin's pads lie around the part's origin at rotation 0 (as the worker's footprints draw them, measured
    on a built board); the origin itself when nothing says."""
    k = node["kind"]
    first = pin in ("1", "A", "P1")
    if k in ("resistor", "capacitor"):
        off = {"0402": 0.5, "0603": 0.82, "0805": 0.91, "1206": 1.4}.get(node.get("package") or "0603", 0.82)
        return [(-off if first else off, 0.0)]
    if k in ("led", "diode"):
        off = 0.82 if k == "led" else 1.65
        return [(-off if first else off, 0.0)]
    if k == "button" and node.get("switch"):
        return [SWITCHES[node["switch"]]["pins"].get(pin) or (0.0, 0.0)]
    if k == "button":  # its legs pair up inside: either of a pair will do
        return [(-2.25, 3.25), (-2.25, -3.25)] if first else [(2.25, -3.25), (2.25, 3.25)]
    if k == "jst":
        return [(-1.0 if first else 1.0, 0.0)]
    if k == "usb_c":
        return [(0.0, 2.55)]
    if k == "chip":
        pads, num_of = part.get("pads"), {p["label"]: p["num"] for p in part.get("pins") or []}
        got = [(pads[num_of[lb]][0], pads[num_of[lb]][1]) for lb in chip_labels(part, pin)[0] if isinstance(pads, dict) and num_of.get(lb) in pads]
        return got or [(0.0, 0.0)]
    if k == "module":
        m = MODULES[node["module"]]
        w = float(re.search(r"_w([\d.]+)mm", m["footprint"])[1])  # type: ignore[index]
        half, got = len(m["pins"]) // 2, []
        for lb in _tsx_pins(node, part, pin):
            if lb in m["pins"]:  # a DIP: down the left column from pin 1, up the right one
                i = m["pins"].index(lb)
                got.append((-w / 2, ((half - 1) / 2 - i) * 2.54) if i < half else (w / 2, (i - half - (half - 1) / 2) * 2.54))
        return got or [(0.0, 0.0)]
    names = list(node.get("pins") or []) if k == "header" else list(acc.ACCESSORIES[node["accessory"]]["pins"]) if k == "accessory" else []
    if pin not in names:
        return [(0.0, 0.0)]
    a = acc.ACCESSORIES[node["accessory"]] if k == "accessory" else {}
    t = (names.index(pin) - (len(names) - 1) / 2) * (CONNECTORS[node["connector"]]["pitch"] if node.get("connector") else 2.0 if a.get("connect") == "jst" else 2.54)
    return [(0.0, -t) if a.get("mount") == "board" and a.get("header_axis", "x") != "x" else (t, 0.0)]


def _turn(p: tuple[float, float], rot: float) -> tuple[float, float]:
    c, s = round(math.cos(math.radians(rot)), 6), round(math.sin(math.radians(rot)), 6)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def _fixed_spot(node: dict[str, Any], pin: dict[str, float]) -> dict[str, float]:
    """pcbX/pcbY/pcbRotation of a part from its place ({x, y, rot}; a board-mounted accessory's place is its body's centre)."""
    if node["kind"] == "accessory" and node.get("edge") is None and acc.ACCESSORIES[node["accessory"]]["mount"] == "board":
        return accessory_anchor(node, pin)
    rot = float(pin.get("rot") or 0)
    return {"pcbX": pin["x"], "pcbY": pin["y"], "pcbRotation": int(rot) if rot.is_integer() else rot}


def _half_chord(o: dict[str, Any], y: float, rim: float) -> float | None:
    """How far either side of the centre line a point at height y stays `rim` inside the outline; None above or below it."""
    if o["shape"] == "round":
        r = _arc(o) - rim
        return math.sqrt(r * r - y * y) if abs(y) <= r else None
    ay, half_h = abs(y), o["h"] / 2 - rim
    if ay > half_h:
        return None
    if o["shape"] == "rounded":
        d = ay - (o["h"] / 2 - o["r"])
        if d > 0:
            re_ = _arc(o) - rim
            return o["w"] / 2 - o["r"] + math.sqrt(re_ * re_ - d * d) if d <= re_ else None
    return o["w"] / 2 - rim


def _free_mask(o: dict[str, Any], box: tuple[float, ...], rim: float, step: float, nx: int, ny: int) -> list[int]:
    """Where a part's origin may lie for its box to stay inside the outline: one int per row of the grid, bit i the x index."""
    rows: list[int] = []
    for j in range(2 * ny + 1):
        y = (j - ny) * step
        c0, c1 = _half_chord(o, y + box[1], rim), _half_chord(o, y + box[3], rim)
        if c0 is None or c1 is None:
            rows.append(0)
            continue
        c = min(c0, c1)
        i0, i1 = max(0, math.ceil((-c - box[0]) / step - 1e-9) + nx), min(2 * nx, math.floor((c - box[2]) / step + 1e-9) + nx)
        rows.append(((1 << (i1 - i0 + 1)) - 1) << i0 if i1 >= i0 else 0)
    return rows


def _block(rows: list[int], box: tuple[float, ...], rect: tuple[float, ...], gap: float, step: float, nx: int, ny: int) -> None:
    """Takes out of a mask the origins from which `box` would come closer than `gap` to `rect`."""
    i0, i1 = max(0, math.floor((rect[0] - box[2] - gap) / step + 1e-9) + 1 + nx), min(2 * nx, math.ceil((rect[2] - box[0] + gap) / step - 1e-9) - 1 + nx)
    j0, j1 = max(0, math.floor((rect[1] - box[3] - gap) / step + 1e-9) + 1 + ny), min(2 * ny, math.ceil((rect[3] - box[1] + gap) / step - 1e-9) - 1 + ny)
    if i1 < i0:
        return
    keep = ~(((1 << (i1 - i0 + 1)) - 1) << i0)
    for j in range(j0, j1 + 1):
        rows[j] &= keep


def _free_units(doc: dict[str, Any], parts: dict[str, dict[str, Any]], taken: set[str]) -> list[dict[str, Any]]:
    """What the placer has to place: each part on the carrier without a spot, a chip with its decoupling capacitors as one
    rigid unit, the capacitors at its supply pins (_cap_spots). [{id, members: [(node, dx, dy, rot)]}]; the chip comes first."""
    plan, _ = decoupling(doc, parts)
    packages = {n["id"]: n.get("package", "0603") for n in doc["nodes"] if n["kind"] == "capacitor"}
    by_id = {n["id"]: n for n in doc["nodes"]}
    free = {n["id"] for n in doc["nodes"] if n["id"] not in taken and n["kind"] != "hole" and _on_carrier(n) and local_box(n, parts.get(n["id"]))
            and not (n["kind"] == "chip" and not parts.get(n["id"], {}).get("raw"))}
    held: dict[str, list[tuple[dict[str, Any], float, float, float]]] = {}
    for chip, caps in plan.items():
        if chip in free:
            for cap, sp in _cap_spots(parts[chip], caps, packages).items():
                if cap in free:
                    held.setdefault(chip, []).append((by_id[cap], sp["pcbX"], sp["pcbY"], sp["pcbRotation"]))
    inside = {m[0]["id"] for ms in held.values() for m in ms}
    return [{"id": n["id"], "members": [(n, 0.0, 0.0, 0.0), *held.get(n["id"], [])]} for n in doc["nodes"] if n["id"] in free and n["id"] not in inside]


def arrange(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float], gap: float | None = None) -> dict[str, Any]:
    """A spot for every part on the carrier nobody placed, on a W x H board: greedy in connectivity order (large units,
    then chips, then the rest, each time the one most attached to what is already down), on a grid inside the real outline,
    a gap clear of the other courtyards (`gap`, else the widest of ARRANGE_GAPS_MM that gets everything down) and clear of
    the corner holes and keepouts, each at the spot and quarter turn where its pads lie nearest the pins they connect. A
    resistor between a discrete and the MCU sits by the discrete. Fixed spots (fixed_parts) stay what they are. Deterministic:
    no randomness, ties go by rotation and the document's order.
    {place: {id: {pcbX, pcbY, pcbRotation}}, rects: {id: courtyard}, missing: [ids that found no spot], gap}."""
    got: dict[str, Any] = {}
    gaps = ARRANGE_GAPS_MM if gap is None else (gap,)
    for g, rim in [(g, ARRANGE_RIM_MM) for g in gaps] + [(gaps[-1], ARRANGE_RIM_TIGHT_MM)]:
        got = _arrange_at(doc, parts, size, g, rim)
        if not got["missing"]:
            break
    return got


def _arrange_at(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float], gap: float, rim: float) -> dict[str, Any]:
    o = outline(doc, (float(size[0]), float(size[1])))
    W, H = o["w"], o["h"]
    by_id = {n["id"]: n for n in doc["nodes"]}
    fx = fixed_parts(doc, parts, (W, H))
    spots: dict[str, dict[str, float]] = dict(layout_edges(doc, parts, W, H))
    spots.update({nid: _fixed_spot(by_id[nid], p) for nid, p in {**accessory_places(doc, parts, W, H), **places(doc)}.items()})
    spots.update({f["id"]: {"pcbX": f["x"], "pcbY": f["y"], "pcbRotation": 0} for f in fx if f["how"] == "cap"})
    # what is in the way: its rect and the gap it asks for
    k = HOLE_KEEP_MM
    blocks: list[tuple[tuple[float, ...], float]] = [(f["rect"], gap) for f in fx]
    blocks += [((x - k, y - k, x + k, y + k), PLACE_GAP_MM) for x, y in _holes(doc, W, H)]
    blocks += [(tuple(z["rect"]), PLACE_GAP_MM) for z in doc.get("zones") or [] if z["kind"] == "keepout" and "top" in z["layers"]]
    for r in doc.get("routes") or []:  # the person's traces on the top side, and their vias: a free part's copper stays off them
        layer, prev = r["layer"], None
        for q in r["points"]:
            if prev and layer == "top":
                n = max(1, math.ceil(math.hypot(q["x"] - prev["x"], q["y"] - prev["y"])))
                blocks += [((x - 0.2, y - 0.2, x + 0.2, y + 0.2), PLACE_GAP_MM) for x, y in
                           ((prev["x"] + (q["x"] - prev["x"]) * i / n, prev["y"] + (q["y"] - prev["y"]) * i / n) for i in range(n + 1))]
            if layer == "top" or q.get("via"):
                blocks.append(((q["x"] - 0.4, q["y"] - 0.4, q["x"] + 0.4, q["y"] + 0.4), PLACE_GAP_MM))
            layer, prev = ("bottom" if layer == "top" else "top") if q.get("via") else layer, q
    # one mask per distinct box, kept up to date as parts go down
    step, nx, ny = ARRANGE_STEP_MM, int(W / 2 / ARRANGE_STEP_MM), int(H / 2 / ARRANGE_STEP_MM)
    masks: dict[tuple[float, ...], list[int]] = {}

    def mask_of(box: tuple[float, ...]) -> list[int]:
        if box not in masks:
            masks[box] = _free_mask(o, box, rim, step, nx, ny)
            for rect, g in blocks:
                _block(masks[box], box, rect, g, step, nx, ny)
        return masks[box]

    # the pull of a pin towards the others on its net: rails pull less (they are everywhere), a discrete at the other end
    # more (a resistor belongs by the LED or the transistor it serves; the long run is the one to the MCU)
    def discrete(nid: str) -> bool:
        n = by_id.get(nid) or {}
        return n.get("kind") in ("led", "diode") or (n.get("kind") == "chip" and len(parts.get(nid, {}).get("pins") or []) <= 4)

    pins_of_part: dict[str, list[tuple[str, float, list[str]]]] = {}
    for net in doc["nets"]:
        base = 0.2 if GROUND.match(net.get("name") or "") else 0.5 if is_supply(net, by_id, parts) else 1.0
        for ref in net["pins"]:
            nid, others = ref.split(".", 1)[0], [p for p in net["pins"] if p != ref]
            pull = 1.5 if base == 1.0 and any(p.split(".", 1)[0] != nid and discrete(p.split(".", 1)[0]) for p in others) else base
            pins_of_part.setdefault(nid, []).append((ref.split(".", 1)[1], pull, others))

    def world(ref: str) -> list[tuple[float, float]]:
        nid, pin = ref.split(".", 1)
        s = spots.get(nid)
        if s is None or nid not in by_id or not _on_carrier(by_id[nid]):
            return []
        rot = float(s.get("pcbRotation") or 0)
        return [(s["pcbX"] + q[0], s["pcbY"] + q[1]) for q in (_turn(p, rot) for p in _pin_pads(by_id[nid], parts.get(nid, {}), pin))]

    units = _free_units(doc, parts, {f["id"] for f in fx})
    for i, u in enumerate(units):
        u["order"], u["boxes"] = i, {}
        for rot in (0, 90, 180, 270):
            rects = [(n["id"], _turned(local_box(n, parts.get(n["id"])), *_turn((dx, dy), rot), r + rot)) for n, dx, dy, r in u["members"]]  # type: ignore[arg-type]
            xs0, ys0, xs1, ys1 = zip(*(q[1] for q in rects))
            u["boxes"][rot] = ((min(xs0), min(ys0), max(xs1), max(ys1)), rects)
        b0 = u["boxes"][0][0]
        u["area"] = (b0[2] - b0[0]) * (b0[3] - b0[1])
        chip, ids = u["members"][0][0], {m[0]["id"] for m in u["members"]}
        u["tier"] = 0 if u["area"] >= BIG_MM2 else 1 if chip["kind"] == "chip" else 2
        # a chip's capacitors are held to it: only its own pins pull
        u["pins"] = [(w, _pin_pads(chip, parts.get(chip["id"], {}), pin), [p for p in others if p.split(".", 1)[0] not in ids])
                     for pin, w, others in pins_of_part.get(chip["id"], [])]

    place: dict[str, dict[str, float]] = {}
    rects_out: dict[str, tuple[float, ...]] = {}
    missing: list[str] = []
    todo = list(units)
    while todo:
        u = min(todo, key=lambda v: (v["tier"], -sum(w for w, _, peers in v["pins"] if any(world(p) for p in peers)), -v["area"], v["order"]))
        todo.remove(u)
        pulls = [(w, pads, [q for p in peers for q in world(p)]) for w, pads, peers in u["pins"]]
        pulls = [t for t in pulls if t[2]]
        total = sum(t[0] for t in pulls)
        # where the pins pull: first the middle of their peers, which says which peer of a rail is the near one
        cx = sum(w * sum(q[0] for q in qs) / len(qs) for w, _, qs in pulls) / total if total else 0.0
        cy = sum(w * sum(q[1] for q in qs) / len(qs) for w, _, qs in pulls) / total if total else 0.0
        best: tuple[float, float, float, int] | None = None
        for rot in (0, 90, 180, 270):
            rows = mask_of(u["boxes"][rot][0])
            turned = [(w, [_turn(p, rot) for p in pads], qs) for w, pads, qs in pulls]
            ax, ay = cx, cy  # the ideal spot at this turn: the weighted median of where each pin would have the part (Weiszfeld)
            if total:
                aims = []
                for w, pads, qs in turned:
                    p, q = min(((p, q) for p in pads for q in qs), key=lambda t: math.hypot(cx + t[0][0] - t[1][0], cy + t[0][1] - t[1][1]))
                    aims.append((w, q[0] - p[0], q[1] - p[1]))
                for _ in range(8):
                    pulled = [(w / max(math.hypot(ax - x, ay - y), 0.05), x, y) for w, x, y in aims]
                    norm = sum(t[0] for t in pulled)
                    ax, ay = sum(t[0] * t[1] for t in pulled) / norm, sum(t[0] * t[2] for t in pulled) / norm
            ix, iy = min(2 * nx, max(0, round(ax / step) + nx)), min(2 * ny, max(0, round(ay / step) + ny))
            fee = {0: 0.0, 180: 0.05, 90: 0.2, 270: 0.25}[rot]  # upright unless the pads say otherwise
            near = math.inf
            for j in sorted(range(2 * ny + 1), key=lambda j: (abs(j - iy), j)):
                if abs(j - iy) * step > near + ARRANGE_SLACK_MM:
                    break
                m = rows[j]
                if not m:
                    continue
                hi, lo = m >> ix, m & ((1 << (ix + 1)) - 1)  # the nearest free spot on this row, either side
                for i in dict.fromkeys(([ix + (hi & -hi).bit_length() - 1] if hi else []) + ([lo.bit_length() - 1] if lo else [])):
                    x, y = (i - nx) * step, (j - ny) * step
                    off = math.hypot(x - ax, y - ay)
                    near = min(near, off)
                    c = fee + 0.001 * off + sum(w * min(math.hypot(x + p[0] - q[0], y + p[1] - q[1]) for p in pads for q in qs) for w, pads, qs in turned)
                    if best is None or c < best[0] - 1e-9:
                        best = (c, x, y, rot)
        if best is None:
            missing += [m[0]["id"] for m in u["members"]]
            continue
        _, x, y, rot = best
        for (n, dx, dy, r), (nid, rect) in zip(u["members"], u["boxes"][rot][1]):
            ox, oy = _turn((dx, dy), rot)
            turned_rot = (r + rot) % 360
            place[nid] = spots[nid] = {"pcbX": round(x + ox, 2) + 0.0, "pcbY": round(y + oy, 2) + 0.0, "pcbRotation": int(turned_rot) if float(turned_rot).is_integer() else turned_rot}
            rects_out[nid] = (round(rect[0] + x, 3), round(rect[1] + y, 3), round(rect[2] + x, 3), round(rect[3] + y, 3))
            blocks.append((rects_out[nid], gap))
            for box, rows in masks.items():
                _block(rows, box, rects_out[nid], gap, step, nx, ny)
    return {"place": place, "rects": rects_out, "missing": missing, "gap": gap, "rim": rim}


def _arranged(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float], gap: float | None = None) -> dict[str, Any] | None:
    """arrange(), or None when it broke: a slip in the placer must not kill a build, tscircuit's packer takes over."""
    try:
        return arrange(doc, parts, size, gap)
    except Exception:  # noqa: BLE001
        log.exception("the device placer failed on %s at %s", doc.get("title"), size)
        return None


def room(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float]) -> tuple[float, float]:
    """The board from `size` up, ROOM_STEP_MM at a time, shorter side first, until arrange() has a spot for every free part
    (a round board as a circle; MAX_W is the end of it). The person's size stays as it is."""
    W, H = float(size[0]), float(size[1])
    round_ = doc["board"].get("shape") == "round"
    while not doc["board"].get("locked"):
        got = _arranged(doc, parts, (W, H))
        if got is None or not got["missing"] or (W >= MAX_W and H >= MAX_W):
            break
        if round_:
            W = H = min(MAX_W, W + ROOM_STEP_MM)
        elif W <= H:
            W = min(MAX_W, W + ROOM_STEP_MM)
        else:
            H = min(MAX_W, H + ROOM_STEP_MM)
    return W, H


def _trim(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float]) -> tuple[float, float]:
    """A side nobody chose (no board.w or board.h: the designer's is a minimum) comes in a millimetre at a time while the
    fixed spots stay clear and the placer still gets everything down at its widest gap: what the board needs, not what an
    estimate of its area said. Never below what the edge parts take between the corner holes (_floor), what keeps the holes
    (_holes), or 24 mm."""
    b, (W, H) = doc["board"], size
    low = 26.0 if b.get("holes", True) else 24.0
    low_w, low_h = (max(low, math.ceil(v)) for v in _floor(doc, parts)[:2])
    wide = max(ARRANGE_GAPS_MM)

    def fine(s: tuple[float, float]) -> bool:
        if any(c["kind"] != "part" or c["b"]["how"] == "edge" for c in conflicts(doc, parts, s)):  # placed on placed: no size clears that
            return False
        got = _arranged(doc, parts, s)
        return got is not None and not got["missing"] and got["gap"] == wide and got["rim"] == ARRANGE_RIM_MM

    if b.get("shape") == "round":
        while not b.get("w") and W - 1 >= max(low_w, low_h) and fine((W - 1, W - 1)):
            W = H = W - 1
        return W, H
    can_w, can_h = not b.get("w"), not b.get("h")
    while can_w or can_h:
        if can_w and (W >= H or not can_h):  # the longer side first, while both may move
            if W - 1 >= low_w and fine((W - 1, H)):
                W -= 1
            else:
                can_w = False
        elif H - 1 >= low_h and fine((W, H - 1)):
            H -= 1
        else:
            can_h = False
    return W, H


def other_gap(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float], comp: dict[str, Any]) -> float | None:
    """A gap that arranges this board's free parts differently from the build `comp` that failed: the router is deterministic and
    trips over one spot (a via on a pad, two traces 0.08 mm apart), where another arrangement of the same board passes. None
    when there is no other."""
    if not comp.get("free"):
        return None
    for g in sorted({max(ARRANGE_GAPS_MM) + 0.6, *ARRANGE_GAPS_MM}, reverse=True):
        got = _arranged(doc, parts, size, g)
        if g != comp.get("gap") and got and not got["missing"] and any(comp["placed"].get(nid) != p for nid, p in got["place"].items()):
            return g
    return None


def next_size(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float], comp: dict[str, Any], grow: float) -> tuple[float, float]:
    """The board to try after this one failed to route: `grow` per side, or less when its free parts sat at the narrow gap and
    a step or two more gives them the wide one (the same parts, far easier to route)."""
    W, H = float(size[0]), float(size[1])
    big = (min(MAX_W, float(math.ceil(W * grow))), min(MAX_W, float(math.ceil(H * grow))))
    if comp.get("free") and comp.get("gap") != max(ARRANGE_GAPS_MM):
        while W + 1 <= big[0] or H + 1 <= big[1]:
            W, H = min(big[0], W + ROOM_STEP_MM), min(big[1], H + ROOM_STEP_MM)
            got = _arranged(doc, parts, (W, H), max(ARRANGE_GAPS_MM))
            if got and not got["missing"]:
                return W, H
    return big


def no_room(doc: dict[str, Any], size: tuple[float, float], ids: list[str]) -> str:
    """What the build says when the placer found no spot and the board cannot grow."""
    why = "the person fixed the board" if doc["board"].get("locked") else "it is the largest board there is"
    return (f"no room on the {describe_outline(outline(doc, size))} for {', '.join(ids)} ({why}): each part needs its courtyard, "
            f"{min(ARRANGE_GAPS_MM):g} mm from the next and {ARRANGE_RIM_TIGHT_MM:g} mm from the edge; make the board larger, or move placed parts together")


def _who(f: dict[str, Any]) -> str:
    r = f["rect"]
    what = {"cap": f"the capacitor the compiler puts beside {f.get('of')}", "edge": f"on the {f.get('edge')} edge",
            "auto": "at its default spot", "pcb": "placed by the person"}.get(f["how"], "")
    return f"{f['id']} ({r[2] - r[0]:.1f}x{r[3] - r[1]:.1f} mm at ({f['x']:g}, {f['y']:g}){', ' + what if what else ''})"


GROW_SAFE_MM = 12.0  # how much the build grows a board by itself to clear placed parts (or a quarter of its side)


def board_area(doc: dict[str, Any], size: tuple[float, float]) -> float:
    """The board's own area, mm² (a round board's disc, a rounded one without its corners)."""
    o = outline(doc, size)
    if o["shape"] == "round":
        return math.pi * o["r"] ** 2
    return o["w"] * o["h"] - (4 - math.pi) * o["r"] ** 2


def size_text(doc: dict[str, Any], size: tuple[float, float]) -> str:
    return f"{size[0]:g} mm round" if doc["board"].get("shape") == "round" else f"{size[0]:g} x {size[1]:g} mm"


def sized(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> tuple[tuple[float, float], list[dict[str, Any]]]:
    """The board the build would start from for a document (estimate()) and the conflicts left on it: placed parts on
    each other, which no growth clears (and anything still in the way of a board at MAX_W)."""
    size = estimate(doc, parts)
    return size, conflicts(doc, parts, size)


def _node(doc: dict[str, Any], nid: str) -> dict[str, Any]:
    return next(n for n in doc["nodes"] if n["id"] == nid)


def _members(doc: dict[str, Any], spec: tuple[str, Any]) -> set[str]:
    return set(doc["layouts"][spec[1]]["nodes"]) if spec[0] == "layout" else {spec[1]}


def _spot(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float], spec: tuple[str, Any],
          dx: float = 0.0, dy: float = 0.0, turn: float = 0.0) -> None:
    """Moves a mover in (a copy of) the document: a layout's centre (and its turn), a part's pcb (the person's), else its
    place; a part with neither (a layout member, a module at its default spot) gets a place where it was."""
    if spec[0] == "layout":
        lay = doc["layouts"][spec[1]]
        lay["center"] = [round(lay["center"][0] + dx, 2) + 0.0, round(lay["center"][1] + dy, 2) + 0.0]
        lay["rot"] = round((float(lay.get("rot") or 0) + turn) % 360, 1) + 0.0
        return
    node = _node(doc, spec[1])
    key = "pcb" if node.get("pcb") else "place"
    p = node.get(key) or places(doc).get(node["id"]) or accessory_places(doc, parts, *size).get(node["id"])
    if p is None:
        raise KeyError(spec[1])
    rot = (float(p.get("rot") or 0) + turn) % 360
    node[key] = {"x": round(p["x"] + dx, 2) + 0.0, "y": round(p["y"] + dy, 2) + 0.0,
                 "rot": int(round(rot / 90)) * 90 % 360 if key == "pcb" else round(rot, 1) + 0.0}


def _clear_of(doc: dict[str, Any], parts: dict[str, dict[str, Any]], spec: tuple[str, Any], b_id: str, name: str) -> str:
    """Shifts the mover off edge part b_id along that edge's normal, on the board the variant starts from (base_size;
    growing it only takes the edge part further out), and says where it went (' and DS1 at x >= 9.0'), '' when clear."""
    size = base_size(doc, parts)
    fx = fixed_parts(doc, parts, size)
    ids = _members(doc, spec)
    mine = [f["rect"] for f in fx if (f.get("of") or f["id"]) in ids and f["how"] != "edge"]
    eb = next((f for f in fx if f["id"] == b_id and f["how"] == "edge"), None)
    if not mine or eb is None:
        return ""
    m = (min(r[0] for r in mine), min(r[1] for r in mine), max(r[2] for r in mine), max(r[3] for r in mine))
    if not _overlap(m, eb["rect"]):
        return ""
    r, g = eb["rect"], PLACE_GAP_MM
    dx, dy = {"+y": (0.0, r[1] - g - m[3]), "-y": (0.0, r[3] + g - m[1]), "+x": (r[0] - g - m[2], 0.0), "-x": (r[2] + g - m[0], 0.0)}[eb["edge"]]
    _spot(doc, parts, size, spec, dx=dx, dy=dy)
    at = doc["layouts"][spec[1]]["center"] if spec[0] == "layout" else (places(doc)[spec[1]]["x"], places(doc)[spec[1]]["y"])
    axis, v = ("x", at[0]) if dx else ("y", at[1])
    return f" and {name} at {axis} {'>=' if (dx or dy) > 0 else '<='} {v:.1f}"


def _clear_rest(doc: dict[str, Any], parts: dict[str, dict[str, Any]], skip: set[str], b_id: str) -> str:
    """The other placed parts an edge part lands on after moving to another edge: each shifted off it the shortest way
    that does not push it out past that edge (a layout as a whole). Says where they went (' and SW1 at y <= -13.7')."""
    said = ""
    done = set(skip)
    for _ in range(8):
        size = base_size(doc, parts)
        fx = fixed_parts(doc, parts, size)
        eb = next((f for f in fx if f["id"] == b_id and f["how"] == "edge"), None)
        hit = next((f for f in fx if eb and f["how"] != "edge" and (f.get("of") or f["id"]) not in done and _overlap(f["rect"], eb["rect"])), None)
        if not eb or not hit:
            return said
        owner = hit.get("of") or hit["id"]
        idx = next((i for i, lay in enumerate(doc.get("layouts") or []) if owner in lay["nodes"]), None)
        spec: tuple[str, Any] = ("layout", idx) if idx is not None else ("node", owner)
        ids = _members(doc, spec)
        done |= ids
        mine = [f["rect"] for f in fx if (f.get("of") or f["id"]) in ids and f["how"] != "edge"]
        m = (min(r[0] for r in mine), min(r[1] for r in mine), max(r[2] for r in mine), max(r[3] for r in mine))
        r, g = eb["rect"], PLACE_GAP_MM
        ways = {"+x": (r[2] + g - m[0], 0.0), "-x": (r[0] - g - m[2], 0.0), "+y": (0.0, r[3] + g - m[1]), "-y": (0.0, r[1] - g - m[3])}
        ways.pop(eb["edge"], None)  # out past the edge the part sits on
        dx, dy = min(ways.values(), key=lambda d: abs(d[0]) + abs(d[1]))
        _spot(doc, parts, size, spec, dx=dx, dy=dy)
        at = doc["layouts"][idx]["center"] if idx is not None else (places(doc)[owner]["x"], places(doc)[owner]["y"])
        axis, v = ("x", at[0]) if dx else ("y", at[1])
        name = f"the {doc['layouts'][idx]['pattern']} layout's center" if idx is not None else owner
        said += f" and {name} at {axis} {'>=' if (dx or dy) > 0 else '<='} {v:.1f}"
    return said


def _ways(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float], spec: tuple[str, Any], who: str,
          b: dict[str, Any], moves: list[tuple[str, dict[str, float]]], grow: tuple[str, tuple[float, float]]) -> str:
    """The ways out of a placed part (or a layout) running into edge part b, each with the board the build would then size,
    smallest first: the plain moves (`moves`: what to say, the shift), b on another edge with the mover shifted clear of
    it there, the mover turned by 90 degrees; the last two only when clean and smaller than the other ways. Growing the
    board (`grow`: the lever and the size it gives) comes last, with its cost in area against `size`."""
    ids = _members(doc, spec)
    name = spec[1] if spec[0] == "node" else "its center"
    owner = spec[1] if spec[0] == "node" else f"the {doc['layouts'][spec[1]]['pattern']} layout"

    def run(say: str, kind: str, edit: Any) -> dict[str, Any] | None:
        d = clone(doc)
        try:
            more = edit(d) or ""
        except (KeyError, ValueError, IndexError, StopIteration):
            return None
        s, conf = sized(d, parts)
        left: list[str] = []
        for c in conf:
            if c["kind"] != "part":
                continue
            x, y = c["a"].get("of") or c["a"]["id"], c["b"].get("of") or c["b"]["id"]
            for p, q in ((x, y), (y, x)):
                if p in ids and q not in ids and q not in left:
                    left.append(q)
        return {"say": say + more, "kind": kind, "doc": d, "size": s, "area": board_area(d, s), "left": left}

    alts = [v for v in (run(say, "move", lambda d, k=k: _spot(d, parts, size, spec, **k)) for say, k in moves) if v]
    for e2 in EDGES:
        if e2 != b["edge"]:
            def to_edge(d: dict[str, Any], e2: str = e2) -> str:
                _node(d, b["id"])["edge"] = e2
                return _clear_of(d, parts, spec, b["id"], name) + _clear_rest(d, parts, ids, b["id"])
            v = run(f"put {b['id']} on the {e2} edge", "edge", to_edge)
            if v:
                alts.append(v)
    if spec[0] == "node":
        box = local_box(_node(doc, spec[1]), parts.get(spec[1]))
        turnable = bool(box) and abs((box[2] - box[0]) - (box[3] - box[1])) >= 2.0  # type: ignore[index]
        rot = float((places(doc).get(spec[1]) or {}).get("rot") or 0)
        node = _node(doc, spec[1])
        note = (" (the display then reads in portrait: turn the picture in the firmware)"
                if node["kind"] == "accessory" and acc.ACCESSORIES[node["accessory"]]["kind"] == "display" else "")
    else:
        lay = doc["layouts"][spec[1]]
        turnable, rot, note = lay["pattern"] in ("row", "column", "grid") and len(lay["nodes"]) > 1, float(lay.get("rot") or 0), ""
    if turnable:
        def turned(d: dict[str, Any]) -> str:
            _spot(d, parts, size, spec, turn=90)
            return _clear_of(d, parts, spec, b["id"], name)
        v = run(f"turn {who} by 90 degrees (rot {(rot + 90) % 360:g}){note}", "turn", turned)
        if v:
            alts.append(v)
    gsize = grow[1]
    if doc["board"].get("shape") == "round":
        gsize = (max(gsize), max(gsize))
    g_area = board_area(doc, gsize)
    keep = [a for a in alts if a["kind"] == "move"]
    best = min([a["area"] for a in keep if not a["left"]] + [g_area])
    for kind in ("edge", "turn"):
        clean = sorted((a for a in alts if a["kind"] == kind and not a["left"]), key=lambda a: a["area"])
        if clean and clean[0]["area"] < best - 1.0:
            keep.append(clean[0])
    keep.sort(key=lambda a: (bool(a["left"]), a["area"]))
    said = [f"({i}) {a['say']}: {size_text(a['doc'], a['size'])}" + (f", but {owner} then overlaps {', '.join(a['left'][:4])}" if a["left"] else "")
            for i, a in enumerate(keep, 1)]
    pct = round(100 * (g_area / board_area(doc, size) - 1))
    said.append(f"({len(keep) + 1}) last, {grow[0]}: grows the board to {size_text(doc, gsize)}, {pct:+d}% area")
    return "Ways out, smallest board first: " + "; ".join(said)


def place_issues(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float] | None = None) -> list[dict[str, Any]]:
    """What the build would fail on, or blow the board up for, because of a fixed spot: said before any build, with the
    designer's levers (the place that clears it, or the board size that does). Code place_conflict, severity error.
    A board the build may size grows by itself when that takes up to GROW_SAFE_MM (or a quarter) per side, and what
    that clears is not reported; two placed parts on each other are, as is anything on the person's fixed board. With
    `size`: the conflicts on that board as built. Each issue lists the parts it is about in `ids`."""
    locked = bool(doc["board"].get("locked"))
    big = False
    if size is None:
        base = base_size(doc, parts)
        grown = base if locked else fit(doc, parts, base)
        big = not locked and any(g > b0 + max(GROW_SAFE_MM, b0 * 0.25) for g, b0 in zip(grown, base))
        size = base if (locked or big) else grown
    W, H = size
    area = free_area(doc, parts, size)
    o = outline(doc, size)
    round_ = o["shape"] == "round"
    room = f"room for placed parts on a {describe_outline(o)}: x {area['x'][0]:g}..{area['x'][1]:g}, y {area['y'][0]:g}..{area['y'][1]:g}"
    if o["shape"] != "rect":
        room += (f", every courtyard corner within {o['r']:g} mm of the centre" if round_
                 else f", clear of the corner arcs")
    if big:
        room += f"; left as it is, the build grows the board to {size_text(doc, grown)}"
    if locked:
        room += f" (the person fixed the board at {W:g} x {H:g} mm)"
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    layout_of = {nid: lay for lay in doc.get("layouts") or [] for nid in lay["nodes"]}
    by_layout: dict[tuple[int, str], dict[str, Any]] = {}  # a layout's parts against one obstacle: one message
    for c in conflicts(doc, parts, size):
        a, b = c["a"], c.get("b")
        mover = a["of"] if a["how"] == "cap" else a["id"]
        lay = layout_of.get(mover) if a["how"] in ("place", "cap") else None
        if lay and b and (b["how"] == "edge" or (b["of"] if b["how"] == "cap" else b["id"]) in lay["nodes"]):
            inside = b["how"] != "edge"
            k2 = (id(lay), "itself" if inside else b["id"])
            m = by_layout.setdefault(k2, {"lay": lay, "b": b, "inside": inside, "ox": 0.0, "oy": 0.0, "clear": 0.0})
            m["ox"], m["oy"] = max(m["ox"], c["ox"]), max(m["oy"], c["oy"])
            if not inside:
                m["clear"] = max(m["clear"], _clearing(a["rect"], b))
            continue
        key = (mover, (b or {}).get("of") or (b or {}).get("id") or c["kind"])
        if key in seen:
            continue
        seen.add(key)
        r, g = a["rect"], PLACE_GAP_MM
        ax, ay = a.get("chip_at") or (a["x"], a["y"])
        who = mover + (f" (its capacitor {a['id']})" if a["how"] == "cap" else "")
        if c["kind"] == "outline":
            sd, d = c["side"], c["by"] + g
            move = {"+y": f"y <= {ay - d:.1f}", "-y": f"y >= {ay + d:.1f}", "+x": f"x <= {ax - d:.1f}", "-x": f"x >= {ax + d:.1f}"}[sd]
            axis = "h" if sd[1] == "y" and not round_ else "w"
            where = f"round board's rim on its {sd} side" if round_ else f"board's {sd} edge" + (" (a rounded corner)" if o["shape"] == "rounded" else "")
            msg = f"{_who(a)} reaches {c['by']:g} mm past the {where}: put {who} at {move}, or board.{axis} >= {math.ceil((H if axis == 'h' else W) + 2 * d)}"
        elif c["kind"] == "hole":
            hx, hy = c["at"]
            msg = (f"{_who(a)} runs into the mounting hole at ({hx:g}, {hy:g}): move {who} {c['ox'] + g:.1f} mm in x or {c['oy'] + g:.1f} mm "
                   f"in y away from the corner, or board.holes false")
        elif b["how"] == "edge":
            e, ox, oy = b["edge"], _clearing(a["rect"], b) + g, _clearing(a["rect"], b) + g
            br = b["rect"]
            spec = ("node", mover)
            moves: list[tuple[str, dict[str, float]]] = []
            if e in ("+y", "-y"):
                ny = ay - oy if e == "+y" else ay + oy
                moves.append((f"put {who} at y {'<=' if e == '+y' else '>='} {ny:.1f}", {"dy": ny - ay}))
                left, right = ax - (r[2] - br[0] + g), ax + (br[2] - r[0] + g)
                if left - (ax - r[0]) >= area["x"][0] - 0.01:
                    moves.append((f"put {who} at x <= {left:.1f}", {"dx": left - ax}))
                if right + (r[2] - ax) <= area["x"][1] + 0.01:
                    moves.append((f"put {who} at x >= {right:.1f}", {"dx": right - ax}))
                grow = (f"board.{'w' if round_ else 'h'} >= {math.ceil(H + 2 * oy)} (the {e} edge moves out by half of what it grows)",
                        (W, math.ceil(H + 2 * oy)))
            else:
                nx = ax - ox if e == "+x" else ax + ox
                moves.append((f"put {who} at x {'<=' if e == '+x' else '>='} {nx:.1f}", {"dx": nx - ax}))
                grow = (f"board.w >= {math.ceil(W + 2 * ox)} (the {e} edge moves out by half of what w grows)", (math.ceil(W + 2 * ox), H))
            msg = f"{_who(a)} runs into {_who(b)}, which stays on its edge. " + _ways(doc, parts, size, spec, who, b, moves, grow)
        else:
            ox, oy = c["ox"] + g, c["oy"] + g
            other = b["of"] if b["how"] == "cap" else b["id"]
            bx, by = b.get("chip_at") or (b["x"], b["y"])
            msg = (f"{_who(a)} and {_who(b)} overlap: move {who} {ox:.1f} mm in x (x = {ax + math.copysign(ox, (ax - bx) or 1):.1f}) "
                   f"or {oy:.1f} mm in y (y = {ay + math.copysign(oy, (ay - by) or 1):.1f}), or {other} the other way")
            lay = next((x for x in doc.get("layouts") or [] if mover in x["nodes"] and other in x["nodes"]), None)
            if lay:
                msg += f"; in their {lay['pattern']} layout, a pitch >= {lay['pitch'] + min(ox, oy):.1f} mm"
        ids = [mover] + ([b["of"] if b["how"] == "cap" else b["id"]] if b else [])
        out.append({"code": "place_conflict", "ref": mover, "severity": "error", "msg": f"{msg}. {room}", "ids": ids})
    missing = (_arranged(doc, parts, size) or {}).get("missing") or [] if locked else []
    if missing:
        out.append({"code": "place_conflict", "ref": missing[0], "severity": "error", "msg": f"{no_room(doc, size, missing)}. {room}", "ids": missing})
    for m in by_layout.values():
        lay, b, g = m["lay"], m["b"], PLACE_GAP_MM
        cx, cy = lay["center"]
        names = f"the {lay['pattern']} layout of {', '.join(lay['nodes'])} (center ({cx:g}, {cy:g}), pitch {lay['pitch']:g})"
        if m["inside"]:
            msg = f"{names} puts its parts on each other: a pitch >= {lay['pitch'] + min(m['ox'], m['oy']) + g:.1f} mm"
        else:
            spec = ("layout", (doc.get("layouts") or []).index(lay))
            who = f"the {lay['pattern']} layout"
            if b["edge"] in ("+y", "-y"):
                oy = m["clear"] + g
                ny = cy - oy if b["edge"] == "+y" else cy + oy
                moves = [(f"put its center at y {'<=' if b['edge'] == '+y' else '>='} {ny:.1f}", {"dy": ny - cy})]
                grow = (f"board.{'w' if round_ else 'h'} >= {math.ceil(H + 2 * oy)}", (W, math.ceil(H + 2 * oy)))
            else:
                ox = m["clear"] + g
                nx = cx - ox if b["edge"] == "+x" else cx + ox
                moves = [(f"put its center at x {'<=' if b['edge'] == '+x' else '>='} {nx:.1f}", {"dx": nx - cx})]
                grow = (f"board.w >= {math.ceil(W + 2 * ox)}", (math.ceil(W + 2 * ox), H))
            msg = f"{names} runs into {_who(b)}, which stays on its edge. " + _ways(doc, parts, size, spec, who, b, moves, grow)
        out.append({"code": "place_conflict", "ref": lay["nodes"][0], "severity": "error", "msg": f"{msg}. {room}",
                    "ids": list(lay["nodes"]) + ([] if m["inside"] else [b["id"]])})
    return out


# ------------------------------------------------------------------ how large the board is, against what is on it
COMPACT_RATIO = 2.5   # a board this many times its parts' footprints is worth a look for a smaller arrangement
COMPACT_GAIN = 0.8    # what counts as smaller: at most this share of the board's area,
COMPACT_SAVED = 600.0  # and at least this much off it, mm²: 36 x 40 -> 31 x 36 mm is the estimate's margin, no finding
OVER_CONCEPT = 1.2    # a build past this share of the chosen concept's board says so


def footprint_area(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> float:
    """What the parts take on the board, mm²: each courtyard on the carrier (a module over the board by its body); a
    layout as the box around its parts, because a pattern's spacing is what it is for (a die's pips, a ring of LEDs)."""
    at = places(doc)
    layouts = doc.get("layouts") or []
    in_layout = {nid for lay in layouts for nid in lay["nodes"]}
    by_id = {n["id"]: n for n in doc["nodes"]}
    total = 0.0
    for n in doc["nodes"]:
        box = local_box(n, parts.get(n["id"])) if n["kind"] != "hole" and n["id"] not in in_layout else None
        if box:
            total += (box[2] - box[0]) * (box[3] - box[1])
    for lay in layouts:
        rects = [_turned(b_, at[nid]["x"], at[nid]["y"], float(at[nid].get("rot") or 0)) for nid in lay["nodes"]
                 if nid in at and (b_ := local_box(by_id[nid], parts.get(nid)))]
        if rects:
            total += (max(r[2] for r in rects) - min(r[0] for r in rects)) * (max(r[3] for r in rects) - min(r[1] for r in rects))
    return total


def compaction(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """A board more than COMPACT_RATIO x its parts' footprints when a concrete arrangement takes at most COMPACT_GAIN of its
    area and saves COMPACT_SAVED: the same parts on the size they need (the designer's board.w/h may be the generous part), a long edge part (the
    module) on another edge with the placed parts shifted off it, a large placed body turned by 90 degrees. Each is sized
    as the build sizes a board (estimate()) and free of overlaps. None on the person's fixed board, while placed parts
    overlap (place_issues speaks first), or when nothing smaller exists. {msg, say, size, area, need, doc: the arrangement}."""
    if doc["board"].get("locked") or not doc["nodes"]:
        return None
    size, conf = sized(doc, parts)
    if any(c["kind"] == "part" for c in conf):
        return None
    area, need = board_area(doc, size), footprint_area(doc, parts)
    if need <= 0 or area <= COMPACT_RATIO * need:
        return None
    free = clone(doc)
    free["board"].pop("w", None)
    free["board"].pop("h", None)
    cands: list[tuple[str, dict[str, Any]]] = [("the same layout on the size it needs", free)]
    at = places(doc)
    in_layout = {nid for lay in doc.get("layouts") or [] for nid in lay["nodes"]}
    for n in doc["nodes"]:
        if n.get("edge") and n["id"] not in at and _along(n, parts.get(n["id"], {}))[0] >= 10.0:
            for e2 in EDGES:
                if e2 != n["edge"]:
                    d = clone(free)
                    _node(d, n["id"])["edge"] = e2
                    cands.append((f"put {n['id']} on the {e2} edge{_clear_rest(d, parts, set(), n['id'])}", d))
                    # the largest placed body it now lands on goes beside it, along the edge's normal, not the shortest way
                    # (an OLED up past the top of the board is shorter to say and far from smaller)
                    d = clone(free)
                    _node(d, n["id"])["edge"] = e2
                    fx = fixed_parts(d, parts, base_size(d, parts))
                    eb = next((f for f in fx if f["id"] == n["id"]), None)
                    hit = [f for f in fx if eb and f["how"] in ("place", "pcb", "auto") and f["id"] not in in_layout and _overlap(f["rect"], eb["rect"])]
                    if hit:
                        big = max(hit, key=lambda f: (f["rect"][2] - f["rect"][0]) * (f["rect"][3] - f["rect"][1]))["id"]
                        said = _clear_of(d, parts, ("node", big), n["id"], big)
                        cands.append((f"put {n['id']} on the {e2} edge{said}{_clear_rest(d, parts, {big}, n['id'])}", d))
    for n in doc["nodes"]:
        box = local_box(n, parts.get(n["id"])) if n["id"] in at and n["id"] not in in_layout else None
        if box and (box[2] - box[0]) * (box[3] - box[1]) >= 100.0 and abs((box[2] - box[0]) - (box[3] - box[1])) >= 2.0:
            d = clone(free)
            _spot(d, parts, size, ("node", n["id"]), turn=90)
            cands.append((f"turn {n['id']} by 90 degrees", d))
    best: tuple[float, str, tuple[float, float], dict[str, Any]] | None = None
    for say, d in cands:
        s, left = sized(d, parts)
        a = board_area(d, s)
        if not any(c["kind"] == "part" for c in left) and (best is None or a < best[0]):
            best = (a, say, s, d)
    if best is None or best[0] > COMPACT_GAIN * area or area - best[0] < COMPACT_SAVED:
        return None
    a, say, s, smaller = best
    set_wh = ", with board.w/h lowered to it or left out" if doc["board"].get("w") or doc["board"].get("h") else ""
    chosen = device_concept.chosen(doc)
    msg = (f"the board ({size_text(doc, size)}, {area:.0f} mm²) is {area / need:.1f} x what its parts take ({need:.0f} mm²), and a smaller "
           f"arrangement exists: {say}: about {size_text(doc, s)} ({round(100 * (1 - a / area))}% less area){set_wh}"
           + (" (and the concept's board with it)" if chosen and chosen.get("board") else "") + "; write_device edits [{op:'compact'}] applies it")
    return {"msg": msg, "say": say, "size": list(s), "area": round(a), "need": round(need), "doc": smaller}


def growth_report(doc: dict[str, Any], parts: dict[str, dict[str, Any]], final: tuple[float, float],
                  attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """What the build's own growth did to the board, in one message: from the size it was asked for (base_size) to the one
    it built, by how much and why (the placed parts fit() cleared before routing, the attempts that failed on a smaller
    board), and how far past the chosen concept's board if more than OVER_CONCEPT of its area. None when neither happened.
    {from, to, pct, why, msg, concept?: {name, size, pct}}."""
    base = base_size(doc, parts)
    final = (float(final[0]), float(final[1]))
    area, start = board_area(doc, final), board_area(doc, base)
    why: list[str] = []
    grew = area > start + 0.5
    est = estimate(doc, parts)
    fitted = base if doc["board"].get("locked") else fit(doc, parts, base)
    if fitted != base:
        names: list[str] = []
        for c in conflicts(doc, parts, base):
            a = c["a"].get("of") or c["a"]["id"]
            if c["kind"] == "outline":
                names.append(f"{a} past the {c['side']} edge")
            elif c["kind"] == "hole":
                names.append(f"{a} on a mounting hole")
            elif c["b"]["how"] == "edge":
                names.append(f"{a} into {c['b']['id']} on the {c['b']['edge']} edge")
        why.append(f"to {size_text(doc, fitted)} before routing to clear {', '.join(list(dict.fromkeys(names))[:4]) or 'its placed parts'}")
    if board_area(doc, est) > board_area(doc, fitted) + 0.5:
        left = (_arranged(doc, parts, fitted) or {}).get("missing") or []
        why.append(f"to {size_text(doc, est)} before routing to give {', '.join(left[:4]) or 'the free parts'} a spot")
    for prev, nxt in zip(attempts, attempts[1:]):
        if prev.get("size_mm") != nxt.get("size_mm"):
            s = str(prev.get("first") or prev.get("error") or "placement or routing failed")[:100]
            why.append(f"to {size_text(doc, tuple(nxt['size_mm']))} after {prev['size_mm'][0]:g} x {prev['size_mm'][1]:g} mm failed ({s})")
    out: dict[str, Any] = {"from": list(base), "to": list(final), "pct": round(100 * (area / start - 1)), "why": why}
    msg = f"the build grew the board from {size_text(doc, base)} to {size_text(doc, final)} ({out['pct']:+d}% area): {'; '.join(why)}" if grew else ""
    o = device_concept.chosen(doc)
    want = (o or {}).get("board") or {}
    if want.get("w") and want.get("h"):
        like = {"board": {k: v for k, v in want.items() if k in ("shape", "r")}}
        aim = board_area(like, (float(want["w"]), float(want["h"])))
        if area > OVER_CONCEPT * aim:
            pct = round(100 * (area / aim - 1))
            out["concept"] = {"name": o["name"], "size": [want["w"], want["h"]], "pct": pct}  # type: ignore[index]
            msg += ("; " if msg else "") + (f"it is past the board of the chosen concept {o['name']!r} ({size_text(like, (want['w'], want['h']))}) by {pct}% "  # type: ignore[index]
                                            f"of its area: rearrange it (the hints say how) or change the concept")
    if not msg:
        return None
    out["msg"] = msg
    return out


# errors a larger board can clear (parts packed onto each other or off the edge, routing that found no way); the rest
# (a capacitor trace over its length limit, a connector turned inwards, a shorted switch) only spreads parts apart
GROWABLE = re.compile(r"overlap|outside|packing|placement|autorouting|not_connected|trace_missing|clearance|pcb_trace_error|not_on_board", re.I)


def growable(errors: list[dict[str, Any]]) -> bool:
    return any(GROWABLE.search(str(e.get("type") or "")) for e in errors)


def long_caps(doc: dict[str, Any], errors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The capacitors behind trace-too-long errors ({cap: {length, max, to}}): the worker lists the pads such a trace runs
    between and the connections it carries; `to` is the other end of the capacitor's own connection (its chip's pin).
    Empty when any error is something else."""
    kinds = {n["id"]: n["kind"] for n in doc["nodes"]}
    out: dict[str, dict[str, Any]] = {}
    for e in errors:
        if e.get("type") != "pcb_trace_too_long_error":
            return {}
        refs = [x.lstrip(".") for t in e.get("traces") or [] for x in re.findall(r"\.(\w+) > \.(\w+)", t) for x in [f"{x[0]}.{x[1]}"]]
        caps = [r.split(".")[0] for r in refs + list(e.get("ends") or []) if kinds.get(r.split(".")[0]) == "capacitor"]
        if not caps:
            return {}
        for cap in dict.fromkeys(caps):
            to = next((r for r in refs if not r.startswith(cap + ".") and kinds.get(r.split(".")[0]) != "capacitor"), None)
            cur = out.get(cap)
            if cur is None or (e.get("length") or 0) > cur["length"]:
                out[cap] = {"length": float(e.get("length") or 0), "max": float(e.get("max") or DECOUPLING_MAX_MM), "to": to}
    return out


OVERLAP_MSG = re.compile(r"^(\S+) overlaps (\S+):|Courtyard of (\S+) overlaps with courtyard of (\S+)")


def build_hints(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float], errors: list[dict[str, Any]]) -> None:
    """Hints for a device build's placement errors in the designer's terms (changes `errors` in place): an overlap with
    a part placed by the designer names that part and its new place, never an edge part it cannot move (the worker's
    rule, 'move the smaller one', said 'move U1' to a designer whose OLED sat in the module's band); a part the packer
    pushed into an edge part, or a packing that gave up and dropped the free parts at the board's centre, says the board
    had no room and where the room is."""
    fixed = {f["id"]: f for f in fixed_parts(doc, parts, size)}
    issues = place_issues(doc, parts, size)
    area = free_area(doc, parts, size)
    room = f"room for placed parts: x {area['x'][0]:g}..{area['x'][1]:g}, y {area['y'][0]:g}..{area['y'][1]:g} on this {size[0]:g} x {size[1]:g} mm board"
    grows = "the build grows the board on its next attempt" if not doc["board"].get("locked") else "the person fixed the board size"
    for e in errors:
        msg = str(e.get("message") or "")
        if "Unable to pack all PCB components" in msg:
            e["hint"] = (f"the parts without a fixed spot did not fit around the fixed ones, so the packer left them at the board's "
                         f"centre (the overlaps there follow from this): move placed parts closer to the edges or together; {room}; {grows}")
            continue
        m = OVERLAP_MSG.search(msg)
        if not m:
            continue
        x, y = (m[1], m[2]) if m[1] else (m[3], m[4])
        hit = next((i for i in issues if {x, y} <= set(i["ids"])), None)
        if hit:
            e["hint"] = hit["msg"]
            continue
        fx, fy = fixed.get(x), fixed.get(y)
        edge = next((f for f in (fx, fy) if f and f["how"] == "edge"), None)
        if edge is None:
            continue
        other = y if edge["id"] == x else x
        f = fixed.get(other)
        if f and f["how"] != "edge":
            e["hint"] = f"{other} is placed into {edge['id']}, which stays on its {edge['edge']} edge: place {other} clear of it; {room}"
        else:
            e["hint"] = f"{other} was packed against {edge['id']} (on its {edge['edge']} edge) for want of room; {grows}, or make room ({room})"


# the side a connector's mouth faces at rotation 0, as tscircuit infers it (pcb_connector_not_in_accessible_orientation):
# usbcmidmount opens to -y, jst*_ph to +y; the rotation that turns it to each edge
FACING_ROT = {"usb_c": {"-y": 0, "+x": 90, "+y": 180, "-x": 270}, "jst": {"+y": 0, "-x": 90, "-y": 180, "+x": 270}}


MOUTH_COPPER_MM = 0.5  # a connector's pads from the rim, when its nose would leave them closer


def _mouth_shift(m: dict[str, Any], rot: float, edge: str) -> float:
    """How far a connector's mouth lies from its origin along the edge it is on, turned by rot."""
    x, y = _turn((0.0, m["across"]) if m["dir"][1] == "x" else (m["across"], 0.0), rot)
    return x if edge[1] == "y" else y


def _placement(node: dict[str, Any], part: dict[str, Any], W: float, H: float, slot: float) -> dict[str, float]:
    """pcbX/pcbY/pcbRotation of an edge part whose slot centre lies `slot` mm along its edge (from the edge's middle)."""
    k, e = _conn_kind(node), node["edge"]
    if node["kind"] == "chip" and part.get("mouth"):
        # turned so its mouth is on the edge, its face flush with the board's rim
        m, angle = part["mouth"], {"+x": 0, "+y": 90, "-x": 180, "-y": 270}
        rot = (angle[e] - angle[m["dir"]]) % 360
        d, slot = max(m["reach"], m["pad"] + MOUTH_COPPER_MM) + EDGE_MARGIN_MM, slot - _mouth_shift(m, rot, e)
    elif k == "module":
        d = MODULES[node["module"]]["depth"]
        rot = {"+y": 0, "-x": 90, "-y": 180, "+x": 270}[e]
    else:
        d = CONNECTORS[node["connector"]]["d"] / 2 if node.get("connector") else DEPTH.get(k, 3.0)
        if k in FACING_ROT:
            rot = FACING_ROT[k][e]
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
    """Edge parts spread evenly along their edge, clear of the corner holes; on a curved outline they span only the
    stretch the holes leave (a round board: its side up to the 45 degree holes) and each sits in by the chord its outer
    corners need (_onto_rim), its body inside the rim and its mouth at it."""
    holes = doc["board"].get("holes", True)
    corner = 7.5 if holes else 1.5
    o = outline(doc, (W, H))
    out: dict[str, dict[str, float]] = {}
    for e in EDGES:
        on = [n for n in doc["nodes"] if n.get("edge") == e]
        if not on:
            continue
        L = W if e in ("-y", "+y") else H
        lens = [_along(n, parts.get(n["id"], {}))[0] for n in on]
        if o["shape"] == "round":  # up to the mounting holes on the diagonals, else up to the diagonals themselves
            usable = 2 * ((o["r"] - RIM_MM) / math.sqrt(2) - HOLE_KEEP_MM - 0.5) if holes else 2 * (o["r"] / math.sqrt(2) - 1.5)
        else:
            usable = L - 2 * max(corner, o["r"] * 0.6)
        gap = max(1.0, (usable - sum(lens)) / (len(on) + 1))
        pos = -usable / 2 + gap
        for n, ln in zip(on, lens):
            centre = pos + ln / 2
            if len(on) == 1:
                centre = 0.0
            p = _placement(n, parts.get(n["id"], {}), W, H, centre)
            box = local_box(n, parts.get(n["id"])) if o["shape"] != "rect" else None
            if box:
                t = _onto_rim(o, _turned(box, p["pcbX"], p["pcbY"], p["pcbRotation"]), e)
                if t:
                    sign = 1 if e[0] == "+" else -1
                    p[("pcbY" if e[1] == "y" else "pcbX")] = round(p["pcbY" if e[1] == "y" else "pcbX"] - sign * t, 2)
            out[n["id"]] = p
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


def _on_carrier(node: dict[str, Any]) -> bool:
    """Whether the node puts anything on the carrier board (a LiPo for a XIAO goes on the module's own BAT pads)."""
    return not (node["kind"] == "accessory" and acc.ACCESSORIES[node["accessory"]]["connect"] == "module_bat")


def _accessory_tsx(node: dict[str, Any], part: dict[str, Any], pos: str) -> str | None:
    """The carrier's side of an accessory: a 2.54 mm header with its pins in header order (a JST PH for connect 'jst'),
    nothing for a cell on the module's BAT pads. A module that sits on the board (an OLED) gets its header as a footprint
    of its own whose courtyard is the module's body, so no part is packed under it (traces may pass) and the silkscreen
    shows where it goes; the part sits at the header row's centre, the body off to one side of it."""
    a = acc.ACCESSORIES[node["accessory"]]
    nid, pins = node["id"], a["pins"]
    conn = part.get("connector") or {}
    mpn = a["name"].replace('"', "in")
    if a["connect"] == "module_bat":
        return None
    labels = ", ".join(f'pin{i + 1}: "{p}"' for i, p in enumerate(pins))
    if a["mount"] == "board":
        n, (bw, bd, _) = len(pins), a["body"]
        dx, dy = a.get("header_offset") or (0.0, 0.0)
        along_x = a.get("header_axis", "x") == "x"
        holes = []
        for i in range(n):
            t = round((i - (n - 1) / 2) * 2.54, 3) + 0.0
            x, y = (t, 0.0) if along_x else (0.0, -t)
            holes.append(f'<platedhole portHints={{["pin{i + 1}"]}} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={{{x:g}}} pcbY={{{y:g}}} />')
        cx, cy = round(-dx, 3) + 0.0, round(-dy, 3) + 0.0
        fp = (f"<footprint>{''.join(holes)}<courtyardrect pcbX={{{cx:g}}} pcbY={{{cy:g}}} width={{{bw:g}}} height={{{bd:g}}} />"
              f"<silkscreenrect pcbX={{{cx:g}}} pcbY={{{cy:g}}} width={{{bw:g}}} height={{{bd:g}}} /></footprint>")
        return f'<chip name="{nid}" manufacturerPartNumber="{mpn}"{_spn(conn)}{pos} pinLabels={{{{ {labels} }}}} footprint={{{fp}}} />'
    if a["connect"] == "jst":
        return f'<chip name="{nid}" footprint="jst{len(pins)}_ph" manufacturerPartNumber="S{len(pins)}B-PH-K-S"{_spn(conn)}{pos} pinLabels={{{{ {labels} }}}} />'
    quoted = ", ".join(f'"{p}"' for p in pins)
    return f'<pinheader name="{nid}" pinCount={{{len(pins)}}} pitch="2.54mm" pinLabels={{[{quoted}]}}{_spn(conn)}{pos} />'


def _module_footprint(m: dict[str, Any]) -> str:
    """A module's pin rows as a footprint that draws the module: its real outline and its USB connector in the silkscreen.
    The holes are where the DIP string (m['footprint']) has them, 1 mm so a 0.64 mm square header pin goes in (its diagonal is 0.9), the courtyard theirs alone: the module's body stands above
    the board on its headers, and what may sit under it is the placer's business (place_issues, by its real size)."""
    w = float(re.search(r"_w([\d.]+)mm", m["footprint"])[1])  # type: ignore[index]
    half = len(m["pins"]) // 2
    holes = []
    for i in range(len(m["pins"])):
        x, y = (-w / 2, ((half - 1) / 2 - i) * 2.54) if i < half else (w / 2, (i - half - (half - 1) / 2) * 2.54)
        holes.append(f'<platedhole portHints={{["pin{i + 1}"]}} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={{{x:g}}} pcbY={{{y:g}}} />')
    mw, mh = m["size"]
    p = m["port"]
    py = mh / 2 + p["protrude"] - p["d"] / 2
    return (f"<footprint>{''.join(holes)}<courtyardrect pcbX={{0}} pcbY={{0}} width={{{w + 1.7:g}}} height={{{(half - 1) * 2.54 + 1.7:g}}} />"
            f"<silkscreenrect pcbX={{0}} pcbY={{0}} width={{{mw:g}}} height={{{mh:g}}} />"
            f"<silkscreenrect pcbX={{0}} pcbY={{{py:g}}} width={{{p['w']:g}}} height={{{p['d']:g}}} /></footprint>")


def _switch_tsx(node: dict[str, Any], part: dict[str, Any], pos: str) -> str:
    """A mechanical key switch: its two pins, its locating holes, the cap's plan as its courtyard."""
    sw = SWITCHES[node["switch"]]
    holes = "".join(f'<platedhole portHints={{["pin{i + 1}"]}} shape="circle" holeDiameter="{sw["hole"]:g}mm" outerDiameter="{sw["pad"]:g}mm" pcbX={{{sw["pins"][p][0]:g}}} pcbY={{{sw["pins"][p][1]:g}}} />'
                    for i, p in enumerate(("A", "B")))
    pegs = "".join(f'<hole diameter="{d:g}mm" pcbX={{{x:g}}} pcbY={{{y:g}}} />' for x, y, d in sw["npth"])
    cw, cd = sw["cap"]
    fp = (f"<footprint>{holes}{pegs}<courtyardrect pcbX={{0}} pcbY={{0}} width={{{cw:g}}} height={{{cd:g}}} />"
          f"<silkscreenrect pcbX={{0}} pcbY={{0}} width={{{sw['key']['cut']:g}}} height={{{sw['key']['cut']:g}}} /></footprint>")
    mpn = sw["name"].replace('"', "'")
    return f'<chip name="{node["id"]}" manufacturerPartNumber="{mpn}"{pos} pinLabels={{{{ pin1: "A", pin2: "B" }}}} footprint={{{fp}}} />'


def _terminal_tsx(node: dict[str, Any], part: dict[str, Any], pos: str) -> str:
    """A wire terminal block: its poles in a row across the part's origin, the body as its courtyard."""
    c = CONNECTORS[node["connector"]]
    n = len(node["pins"])
    holes = "".join(f'<platedhole portHints={{["pin{i + 1}"]}} shape="circle" holeDiameter="{c["hole"]:g}mm" outerDiameter="{c["pad"]:g}mm" '
                    f'pcbX={{{round((i - (n - 1) / 2) * c["pitch"], 3) + 0.0:g}}} pcbY={{0}} />' for i in range(n))
    w = c["pitch"] * n
    fp = (f'<footprint>{holes}<courtyardrect pcbX={{0}} pcbY={{0}} width={{{w:g}}} height={{{c["d"]:g}}} />'
          f'<silkscreenrect pcbX={{0}} pcbY={{0}} width={{{w:g}}} height={{{c["d"]:g}}} /></footprint>')
    labels = ", ".join(f'"{p}"' for p in node["pins"])
    return f'<pinheader name="{node["id"]}" pinCount={{{n}}} pitch="{c["pitch"]:g}mm" manufacturerPartNumber="{c["name"]}"{pos} pinLabels={{[{labels}]}} footprint={{{fp}}} />'


def connector_model(node: dict[str, Any]) -> list[dict[str, Any]]:
    """A terminal block in the board's 3D view: its body and a screw over each pole."""
    c, n = CONNECTORS[node["connector"]], len(node["pins"])
    prims = [{"shape": "box", "at": [0, 0, 0], "size": [c["pitch"] * n, c["d"], c["h"]], "r": 0.3, "color": c["color"]}]
    prims += [{"shape": "cyl", "at": [round((i - (n - 1) / 2) * c["pitch"], 3), 0, c["h"]], "size": [3.0, 3.0, 0.15], "color": "#c9ccd1"} for i in range(n)]
    return prims


def switch_model(sw: dict[str, Any]) -> list[dict[str, Any]]:
    """A key switch in the board's 3D view (models.mjs primitives): the housing up to the plate, its flange and top, the stem."""
    if sw["key"]["stem"] == "panel":
        kk = sw["key"]
        return [{"shape": "cyl", "at": [0, 0, 1.0], "size": [kk["cut"] - 1, kk["cut"] - 1, kk["depth"] - 1], "color": "#2a2a2c"},
                {"shape": "cyl", "at": [0, 0, kk["depth"]], "size": [kk["cap"][0] - 1, kk["cap"][1] - 1, 3.0], "color": kk["color"]}]
    k, c = sw["key"], sw["key"]["cut"]
    top = k["stem_top"] - (3.6 if k["stem"] == "mx" else 3.0)
    prims = [{"shape": "box", "at": [0, 0, 0], "size": [c, c, k["plate_top"]], "r": 0.5, "color": "#2a2a2c"},
             {"shape": "box", "at": [0, 0, k["plate_top"]], "size": [c + 1.6, c + 1.6, 0.8], "r": 0.8, "color": "#36363a"},
             {"shape": "box", "at": [0, 0, k["plate_top"] + 0.8], "size": [c - 1, c - 1, top - k["plate_top"] - 0.8], "r": 0.8, "color": "#3e3e44", "taper": 0.8}]
    if k["stem"] == "mx":
        prims += [{"shape": "box", "at": [0, 0, top], "size": [4.0, 1.2, 3.6], "color": "#c8352f"}, {"shape": "box", "at": [0, 0, top], "size": [1.2, 4.0, 3.6], "color": "#c8352f"}]
    else:
        prims += [{"shape": "box", "at": [x, 0, top], "size": [1.2, 3.0, 3.0], "color": "#c8352f"} for x in (-2.85, 2.85)]
    return prims


def accessory_model(a: dict[str, Any]) -> list[dict[str, Any]]:
    """A board-mounted accessory in the board's 3D view: its header, its board at its stack height, the glass or the window.
    The part's origin is the header row; the body lies off it by header_offset."""
    bw, bd, bh = a["body"]
    dx, dy = a.get("header_offset") or (0.0, 0.0)
    cx, cy = -dx, -dy
    z = float(a.get("stack_h") or 0)
    n, along_x = len(a["pins"]), a.get("header_axis", "x") == "x"
    plastic = [2.54 * n, 2.5] if along_x else [2.5, 2.54 * n]
    prims = [{"shape": "box", "at": [0, 0, 0], "size": [*plastic, max(z, 0.5)], "color": "#1a1a1a"},
             {"shape": "box", "at": [cx, cy, z], "size": [bw, bd, 1.2], "r": 0.6, "color": "#1b3a7a"}]
    if a.get("window"):
        wx, wy = a.get("window_offset") or (0.0, 0.0)
        prims.append({"shape": "box", "at": [cx + wx, cy + wy, z + 1.2], "size": [a["window"][0] + 1.5, a["window"][1] + 2.0, max(bh - 1.2, 0.4)], "color": "#0c0c10"})
    return prims


def model_plan(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """What the worker needs to draw each part it cannot draw by itself (models.mjs): {ref: {prims} | {h}}. The designer's
    node.model wins, then what the graph knows. A catalogue part's own OBJ goes by its uuid (catalog.model_obj), this
    only says how high its block is should it have none."""
    plan: dict[str, dict[str, Any]] = {}
    for n in doc["nodes"]:
        nid, k = n["id"], n["kind"]
        if n.get("model"):
            plan[nid] = {"prims": n["model"]}
        elif k == "button" and n.get("switch"):
            plan[nid] = {"prims": switch_model(SWITCHES[n["switch"]])}
        elif k == "header" and n.get("connector"):
            plan[nid] = {"prims": connector_model(n)}
        elif k == "accessory" and acc.ACCESSORIES[n["accessory"]].get("mount") == "board" and _on_carrier(n):
            plan[nid] = {"prims": accessory_model(acc.ACCESSORIES[n["accessory"]])}
        elif k == "chip":
            plan[nid] = {"h": (parts.get(nid) or {}).get("height_mm") or 2.0}
    return plan


def _tsx_pins(node: dict[str, Any], part: dict[str, Any], pin: str) -> list[str]:
    """The TSX pin labels one device pin stands for: a chip's 'GND' is every pin called GND, a Pico's 'GND' all eight."""
    k = node["kind"]
    if k == "button" and node.get("switch"):
        return [{"A": "pin1", "B": "pin2"}[pin]]
    if k in PRIMS:
        return [PRIMS[k]["tsx"][pin]]
    if k == "module":
        return MODULES[node["module"]]["groups"].get(pin) or [pin]
    if k == "chip":
        return chip_labels(part, pin)[0] or [pin]
    return [pin]


def _old_label(name: str) -> str:
    """catalog.safe_label as it was before 2026-11-03 ('+' and '-' both 'P', a bare '1' 'P1'): what saved graphs say."""
    s = re.sub(r"[^A-Za-z0-9_]+", "_", str(name).replace("+", "P").replace("~", "N").replace("#", "N")).strip("_")
    if not s:
        return "P"
    if s[0].isdigit():
        s = ("V" if re.match(r"^\d+V\d*$", s) else "P") + s
    return s[:24]


def chip_labels(part: dict[str, Any], pin: str) -> tuple[list[str], str]:
    """The TSX labels a chip pin reference stands for, and how it matched: 'label' (its label, or the group a duplicated
    supply name folds into: 'GND' is GND and GND_7), 'name' (the symbol's pin name), 'number' ('P2' / 'pin2' / '2' by pin
    number), 'legacy' (the name the catalogue gave before it renamed pins; may stand for several). ([], '') when none.
    The same order as device_rules."""
    pins, up = part.get("pins") or [], str(pin).upper()
    tests = (("label", lambda p: p["label"].upper() == up or catalog.base_label(p["label"]).upper() == up),
             ("name", lambda p: bool(p.get("name")) and catalog.safe_label(p["name"]).upper() == up),
             ("number", lambda p: up in (f"P{p['num']}".upper(), f"PIN{p['num']}".upper(), str(p["num"]).upper())),
             ("legacy", lambda p: bool(p.get("name")) and _old_label(p["name"]).upper() == up))
    for how, test in tests:
        hit = [p["label"] for p in pins if test(p)]
        if hit:
            return hit, how
    return [], ""


# (pin offset from the centre, courtyard half width, courtyard half length) of a chip capacitor at rotation 0
CAP_GEOM = {"0402": (0.5, 0.45, 0.8), "0603": (0.8, 0.6, 1.1), "0805": (0.95, 0.8, 1.4), "1206": (1.4, 1.0, 1.9)}
PACK_GAP_MM = 1.6           # between packed parts: room for traces, so the router does not squeeze past pads
DECOUPLING_MAX_MM = 10.0   # placed at its supply pin by the compiler; the ground pin may sit across a small package
CAP_GAP = 0.6               # between the chip's outline and the capacitor's courtyard
BULK_MAX_MM = 25.0          # a supply capacitor with no chip to sit by (a module decouples itself): anywhere near; a
                            # limit the packed board cannot meet skips routing altogether (12 mm did on a 58 mm board)
HAND_MAX_MM = 150.0         # a capacitor routed by hand: the person's lengths (no limit would mean tscircuit's own 1 mm)
TIED_MAX_MM = 16.0          # a capacitor of a bulky part: packed beside its body, tied to its pin by a direct trace


def bulky(part: dict[str, Any]) -> bool:
    """A body far larger than its pads (a TO-5 PIR, a 9.6 mm buzzer with two pads 9 mm apart): tscircuit's packer sees a
    group by its pads alone and drops small parts between them, so such a part is packed on its own, by its courtyard,
    and its capacitors are tied to its pins by direct traces instead of a group."""
    pads, box = part.get("pads"), part.get("box")
    if not isinstance(pads, dict) or not pads or not box:
        return False
    x0 = min(x - w / 2 for x, y, w, h in pads.values())
    x1 = max(x + w / 2 for x, y, w, h in pads.values())
    y0 = min(y - h / 2 for x, y, w, h in pads.values())
    y1 = max(y + h / 2 for x, y, w, h in pads.values())
    margin = max(x0 - box[0], box[2] - x1, y0 - box[1], box[3] - y1)
    return (box[2] - box[0]) * (box[3] - box[1]) > 2.0 * (x1 - x0) * (y1 - y0) + 4.0 or margin > 2.5


def is_supply(net: dict[str, Any], by_id: dict[str, dict[str, Any]] | None = None, parts: dict[str, dict[str, Any]] | None = None) -> bool:
    """Whether a net is a supply rail: a power name (V3V3, VLED behind a diode, PWR_5V), or no name but a chip's or
    module's supply pin on it (VDD, VCC, VIN). Ground is never one."""
    name = net.get("name") or ""
    if GROUND.match(name):
        return False
    if name:
        return bool(POWER_NET.match(name) or SUPPLY_NAME.match(name))
    for ref in net.get("pins") or []:
        nid, pin = ref.split(".", 1)
        node = (by_id or {}).get(nid) or {}
        if node.get("kind") in ("chip", "module") and SUPPLY_PIN.match(catalog.base_label(pin)):
            return True
    return False


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
        if GROUND.match(names[1]) and a and is_supply(a, by_id, parts):
            supply, cap_pin = a, "1"
        elif GROUND.match(names[0]) and b and is_supply(b, by_id, parts):
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


def _ties(doc: dict[str, Any], parts: dict[str, dict[str, Any]], plan: dict[str, list[tuple[str, str, str]]],
          bulk: set[str]) -> dict[str, str]:
    """Capacitor pads wired straight to a pad rather than to their net ({'.C1 > .pin1': '.U2 > .VDD'}): a decoupling
    capacitor to its chip's supply pin and the chip's ground pin nearest it, a bulk capacitor to the supply and ground
    pins of the part that feeds its net (the module, else the first part on it). The router then joins them pad to pad
    (a ground pin left to the net's spanning tree went 11 mm round a 5050 LED and broke the 10 mm decoupling limit), and
    the two-pin traces pull the packer together where no group holds the capacitor."""
    tied: dict[str, str] = {}
    for chip, caps in plan.items():
        for cap, label, cap_pin in caps:
            tied[f".{cap} > .pin{cap_pin}"] = f".{chip} > .{label}"
            g = _nearest_ground(parts[chip], label)
            if g:
                tied[f".{cap} > .pin{'2' if cap_pin == '1' else '1'}"] = f".{chip} > .{g}"
    by_id = {n["id"]: n for n in doc["nodes"]}
    net_of = {p: net for net in doc["nets"] for p in net["pins"]}
    for cap in bulk:
        a, b = net_of.get(f"{cap}.1"), net_of.get(f"{cap}.2")
        if not a or not b:
            continue
        sup_pin = "2" if GROUND.match(a.get("name") or "") else "1"
        sup, gnd = (a, b) if sup_pin == "1" else (b, a)
        feeds = [p for p in sup["pins"] if by_id.get(p.split(".")[0], {}).get("kind") not in (None, "capacitor") and _on_carrier(by_id[p.split(".")[0]])]
        # the packer cannot pull a part towards a fixed one (a module on its edge is an obstacle to it, not a network), so
        # a bulk capacitor fed from one stays on its nets and finds the nearest pad there
        if not feeds or any(by_id[p.split(".")[0]]["kind"] == "module" or by_id[p.split(".")[0]].get("edge") for p in feeds[:1]):
            continue
        nid, pin = feeds[0].split(".", 1)
        tied[f".{cap} > .pin{sup_pin}"] = f".{nid} > .{_tsx_pins(by_id[nid], parts.get(nid, {}), pin)[0]}"
        g = next((p.split(".", 1)[1] for p in gnd["pins"] if p.split(".")[0] == nid), None)
        if g:
            tied[f".{cap} > .pin{'2' if sup_pin == '1' else '1'}"] = f".{nid} > .{_tsx_pins(by_id[nid], parts.get(nid, {}), g)[0]}"
    return tied


def _nearest_ground(part: dict[str, Any], label: str) -> str | None:
    """The chip's ground pin label nearest its pin `label` (by pad position), or None."""
    pads, pins = part.get("pads") or {}, part.get("pins") or []
    num_of = {p["label"]: p["num"] for p in pins}
    at = pads.get(num_of.get(label, "")) if isinstance(pads, dict) else None
    grounds = [p for p in pins if GROUND.match(catalog.base_label(p["label"])) and isinstance(pads, dict) and p["num"] in pads]
    if not at or not grounds:
        return None
    return min(grounds, key=lambda p: abs(pads[p["num"]][0] - at[0]) + abs(pads[p["num"]][1] - at[1]))["label"]


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


def compile(doc: dict[str, Any], parts: dict[str, dict[str, Any]], size: tuple[float, float], *, relaxed: set[str] | frozenset[str] = frozenset(),
            gap: float | None = None) -> dict[str, Any]:
    """The TSX file, the LCSC footprints it needs ({code: {easyeda, h}}) and the intent; the board is W x H mm. Fixed
    positions: the person's pcb, the designer's place and layouts (places()), a module that sits on the board at its default
    spot (accessory_places()); an accessory's place is its body's centre, its connector goes where the module's header
    lands. The rest comes from the placer (arrange()), a chip and its decoupling capacitors as one unit, the capacitors at
    its supply pins; `unplaced` lists what found no spot (the build grows the board, or says so). Only then, or if the
    placer broke, tscircuit packs them: a chip and its capacitors as one group. `relaxed`: capacitors whose trace length
    limit the build lifts after the router could not meet it (deviceapi.build_device; a warning, not a failed board). `gap`:
    the placer's gap between free parts, when the build asks for another arrangement of the same board."""
    W, H = size
    if doc["board"].get("shape") == "round":
        H = W
    by_id = {n["id"]: n for n in doc["nodes"]}
    place = layout_edges(doc, parts, W, H)
    plan, bulk = decoupling(doc, parts)
    packages = {n["id"]: n.get("package", "0603") for n in doc["nodes"] if n["kind"] == "capacitor"}
    pins = {**accessory_places(doc, parts, W, H), **places(doc)}
    # every part nobody placed gets its spot from the placer; tscircuit packs them only if it broke or found no room
    got = _arranged(doc, parts, (W, H), gap)
    unplaced = list((got or {}).get("missing") or [])
    arranged = got["place"] if got is not None and not unplaced else None
    in_group: dict[str, str] = {}
    decoupled: set[str] = set()
    # a capacitor's pins wired straight to its chip's supply and nearest ground pin rather than to the nets: the router
    # then joins them pad to pad (a ground pin left to the net's spanning tree went 11 mm round a 5050 LED and broke the
    # 10 mm decoupling limit), and for a bulky part packed on its own, a two-pin trace is what pulls the packer together
    tied = _ties(doc, parts, plan, bulk)  # capacitor pad selector -> the pad it is wired to directly
    bulky_caps: set[str] = set()
    for chip, caps in plan.items():
        at = pins.get(chip)
        if not at and bulky(parts[chip]):
            bulky_caps |= {cap for cap, *_ in caps}
            continue
        if not at and arranged is not None:
            decoupled |= {cap for cap, *_ in caps}
            continue
        spots = _cap_spots(parts[chip], caps, packages)
        turn = float((at or {}).get("rot") or 0)
        c, s_ = round(math.cos(math.radians(turn)), 6), round(math.sin(math.radians(turn)), 6)
        ox, oy = (at["x"], at["y"]) if at else (0, 0)
        for cap, *_ in caps:
            decoupled.add(cap)
            if cap in spots and cap not in pins:
                sp = spots[cap]
                # the chip turned by hand: its capacitors turn with it around the chip's centre
                x, y = sp["pcbX"], sp["pcbY"]
                rot = (sp["pcbRotation"] + turn) % 360
                place[cap] = {"pcbX": round(ox + x * c - y * s_, 2), "pcbY": round(oy + x * s_ + y * c, 2),
                              "pcbRotation": int(rot) if float(rot).is_integer() else round(rot, 1)}
                if not at:
                    in_group[cap] = chip
        if not at:
            # packed: the chip and its capacitors move as one group
            place[chip] = {"pcbX": 0, "pcbY": 0, "pcbRotation": 0}
            in_group[chip] = chip
    for nid, pin in pins.items():
        place[nid] = _fixed_spot(by_id[nid], pin)
    if arranged:
        place.update(arranged)
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
            limit = (HAND_MAX_MM if nid in routed or nid in relaxed else TIED_MAX_MM if nid in bulky_caps else DECOUPLING_MAX_MM if nid in decoupled
                     else BULK_MAX_MM)  # no limit would mean tscircuit's own 1 mm, and a failed build for a capacitor labelled for a buzzer
            extra = f" maxDecouplingTraceLength={{{limit:g}}}" if limit else ""
            lines.append(f'<capacitor name="{nid}" capacitance={_attr(n["value"])} footprint="{n["package"]}"{_spn(part)}{pos}{extra} />')
        elif k == "led":
            lines.append(f'<led name="{nid}" color={_attr(n.get("color", "green"))} footprint="0603"{_spn(part)}{pos} />')
        elif k == "diode":
            lines.append(f'<diode name="{nid}" footprint="sod123" manufacturerPartNumber="B5819W"{_spn(part)}{pos} />')
        elif k == "button" and n.get("switch"):
            lines.append(_switch_tsx(n, part, pos))
        elif k == "button":
            lines.append(f'<pushbutton name="{nid}" footprint="pushbutton" internallyConnectedPins={{[["pin1","pin2"],["pin3","pin4"]]}}{_spn(part)}{pos} />')
        elif k == "header" and n.get("connector"):
            lines.append(_terminal_tsx(n, part, pos))
        elif k == "header":
            labels = ", ".join(f'"{p}"' for p in n["pins"])
            lines.append(f'<pinheader name="{nid}" pinCount={{{len(n["pins"])}}} pitch="2.54mm" pinLabels={{[{labels}]}}{_spn(part)}{pos} />')
        elif k == "usb_c":
            labels = ", ".join(f'{p}: "{lb}"' for p, lb in USB_C_LABELS.items())
            lines.append(f'<chip name="{nid}" footprint="usbcmidmount" manufacturerPartNumber="TYPE-C-31-M-12"{_spn(part)}{pos} pinLabels={{{{ {labels} }}}} />')
        elif k == "jst":
            lines.append(f'<chip name="{nid}" footprint="jst2_ph" manufacturerPartNumber="S2B-PH-K-S"{_spn(part)}{pos} pinLabels={{{{ pin1: "pin1", pin2: "pin2" }}}} />')
        elif k == "accessory":
            line = _accessory_tsx(n, part, pos)
            if line:
                lines.append(line)
        elif k == "module":
            m = MODULES[n["module"]]
            labels = ", ".join(f'pin{i + 1}: "{p}"' for i, p in enumerate(m["pins"]))
            lines.append(f'<chip name="{nid}" manufacturerPartNumber="{n["module"]}"{pos} pinLabels={{{{ {labels} }}}} footprint={{{_module_footprint(m)}}} />')
        elif k == "chip":
            if not part.get("raw"):
                continue
            labels = ", ".join(f'pin{p["num"] if p["num"].isdigit() else catalog.safe_label(p["num"])}: "{p["label"]}"' for p in part["pins"])
            mpn = str(part.get("mpn") or n.get("mpn") or n["lcsc"]).replace('"', "'")
            lines.append(f'<chip name="{nid}" footprint="lcsc:{n["lcsc"]}" manufacturerPartNumber="{mpn}"{_spn(part)}{pos} pinLabels={{{{ {labels} }}}} />')
            # a connector on an edge goes by its pads and its model (mouth_of): its drawn courtyard is no measure of the part
            lcsc[n["lcsc"]] = {"easyeda": part["raw"], "h": part.get("height_mm"), "type": "chip", **({"bare": True} if part.get("mouth") and n.get("edge") else {})}
        if nid in in_group and len(lines) > mark:
            grouped.setdefault(in_group[nid], []).append(lines.pop())
    for chip, members in grouped.items():
        # the chip first, so the group reads as the chip with its capacitors
        members.sort(key=lambda ln: f'name="{chip}"' not in ln)
        lines.append(f'<group name="G_{chip}">\n      ' + "\n      ".join(members) + "\n    </group>")
    holes = [f'<hole name="H{i + 1}" diameter="3.2mm" pcbX={_attr(hx)} pcbY={_attr(hy)} />' for i, (hx, hy) in enumerate(_holes(doc, W, H))]

    # a hand trace leads from a part with a fixed spot, as ever: one the placer put down has no spot of the person's
    hand, joined, bottom = _hand_traces(doc, parts, place, {**in_group, **{nid: nid for nid in arranged or {}}})
    # pads one hand trace already joins are one island: the autorouter only joins the islands. A pad has one key
    # whatever the TSX calls it (an LED's anode is its pin1) and a button's or a USB-C receptacle's twin pads share one
    same: dict[str, str] = {}
    for n in doc["nodes"]:
        twins = {"led": {"anode": "pin1", "cathode": "pin2"}, "diode": {"anode": "pin1", "cathode": "pin2"},
                 "button": {} if n.get("switch") else {"pin2": "pin1", "pin4": "pin3"},
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
            if node is None or (node["kind"] == "chip" and not parts.get(nid, {}).get("raw")) or not _on_carrier(node):
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
        width = net_width(doc, net)
        thick = f"{max(width or 0.0, 0.4):g}mm" if width and width >= 0.4 else "0.4mm"
        if (name and WIDE_NET.match(name) and not GROUND.match(name)) or width:
            # the supply path pin to pin, so its width is kept (a width on a trace to a net is dropped). A capacitor hangs
            # off the chain by one trace to the pin it serves (its chip's supply pin, else the first part on the net):
            # its traces carry the decoupling length limit, and as a link of the chain it would have to sit within 10 mm
            # of whichever parts came before and after it in the list
            reps = list(dict.fromkeys(root(e) for e in ends))
            is_cap = lambda e: by_id.get(e[1:].split(" > ", 1)[0], {}).get("kind") == "capacitor"  # noqa: E731
            chain = [e for e in reps if not is_cap(e)] or reps[:1]
            for a, b in zip(chain, chain[1:]):
                traces.append(f'<trace from="{a}" to="{b}" thickness="{thick}" />')
            for e in reps:
                if e not in chain:
                    anchor = root(tied[e]) if e in tied and root(tied[e]) in chain else chain[0]
                    traces.append(f'<trace from="{e}" to="{anchor}" thickness="{thick}" />')
        elif not name and len(ends) == 2:
            if root(ends[0]) != root(ends[1]):
                traces.append(f'<trace from="{ends[0]}" to="{ends[1]}" />')
        else:
            if not name:
                auto += 1
                name = f"N{auto}"
            # a bulky part's capacitor goes to its pin, not to the net: a two-pin trace is what pulls the packer together
            traces += [f'<trace from="{e}" to="{tied[e]}" />' if e in tied and tied[e] in ends else f'<trace from="{e}" to="net.{ident(name)}" />'
                       for e in ends]

    intent = intent_of(doc, parts)
    meta = {"title": doc["title"][:60], "intent": intent, "device": True, **({"hand_bottom": bottom} if bottom else {})}
    import json as _json

    zones: list[str] = []
    for z in doc.get("zones") or []:
        if z["kind"] == "pour":
            # pour after routing: the solver keeps its clearance from every other net's copper and ties its own pads in
            r = z.get("rect")
            poured = (f" outline={{[{{ x: {r[0]:g}, y: {r[1]:g} }}, {{ x: {r[2]:g}, y: {r[1]:g} }}, {{ x: {r[2]:g}, y: {r[3]:g} }}, "
                       f"{{ x: {r[0]:g}, y: {r[3]:g} }}]}}") if r else ""
            zones.append(f'<copperpour layer="{z["layer"]}" connectsTo="net.{z["net"]}" clearance="{POUR_CLEARANCE_MM:g}mm"{poured} />')
        else:
            r = z["rect"]
            layers = ", ".join(f'"{lay}"' for lay in z["layers"])
            zones.append(f'<keepout shape="rect" pcbX={_attr(round((r[0] + r[2]) / 2, 2))} pcbY={_attr(round((r[1] + r[3]) / 2, 2))} '
                         f'width={_attr(round(r[2] - r[0], 2))} height={_attr(round(r[3] - r[1], 2))} layers={{[{layers}]}} />')
    body = "\n    ".join(lines + holes + zones + hand + traces)
    # a curved outline goes as the polygon: tscircuit sizes the board from it, checks parts against it (pcb_component_outside_
    # board_error, copper to the edge), and board.json carries it as {kind: 'poly'} for the case
    shape = outline(doc, (W, H))
    pts = outline_points(shape)
    extent = ('outline={[' + ", ".join(f"{{ x: {x:g}, y: {y:g} }}" for x, y in pts) + ']}') if pts else f'width="{W:g}mm" height="{H:g}mm"'
    source = (f"// Compiled from the device graph (fw.device/1) by IaModelize3d: parts on an edge and the designer's are where they\n"
              f"// were put, the rest next to the pins it connects, then autorouted on 2 layers.\n"
              f"export const meta = {_json.dumps(meta, ensure_ascii=False)}\n\n"
              f"export default () => (\n"
              f'  <board {extent} thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm"'
              # pcbPack, the fallback: tscircuit packs a board only when two or more of its parts are free, so with every other
              # part placed (a dice face, a display) the one resistor left would sit at the board's centre, on top of them
              + ('>\n' if arranged is not None else f' pcbPackGap="{PACK_GAP_MM:g}mm" pcbPack>\n') +
              f"    {body}\n  </board>\n)\n")
    return {"source": source, "lcsc": lcsc, "intent": intent, "size": [W, H], "placed": place, "hand": len(hand), "relaxed": sorted(relaxed),
            **({"unplaced": unplaced} if unplaced else {}), **({"gap": got["gap"], "free": len(arranged)} if arranged is not None else {})}


def dress_board(board: dict[str, Any], doc: dict[str, Any], parts: dict[str, dict[str, Any]], cj: list[dict[str, Any]]) -> dict[str, Any]:
    """board.json (fw.board/1) told what the device graph knows and the circuit cannot (contract C2): each part's face
    becomes its access ('light' for an LED chip such as a WS2812, 'sound' over a buzzer, 'sensor' over a PIR or a light
    sensor; shape 'round' for a round can), a board-mounted module's connector becomes the header it is (its body goes
    to the accessories), a cable accessory's connector and an edge connector with face 'none' (a cell's JST) are parts
    inside rather than wall ports, and `accessories` lists every module fitted by hand: where its body sits in the board frame
    (origin bottom-left, mm), its size, window, holes, the edge a cable leaves by. Changes `board` in place."""
    if not board or not cj:
        return board
    pb = next((e for e in cj if e.get("type") == "pcb_board"), None)
    if not pb:
        return board
    W, H = float(pb["width"]), float(pb["height"])
    ox, oy = pb["center"]["x"] - W / 2, pb["center"]["y"] - H / 2
    src = {e["source_component_id"]: e.get("name") for e in cj if e.get("type") == "source_component"}
    pcs = {src.get(e.get("source_component_id")): e for e in cj if e.get("type") == "pcb_component"}
    comps = {c["id"]: c for c in board.get("components") or []}
    r2 = lambda v: round(float(v), 2) + 0.0  # noqa: E731
    out_acc: list[dict[str, Any]] = []
    # the polygon the worker read off the circuit, told what it stands for (the case and device_concept read the shape)
    shape, ol = outline(doc, (W, H)), (board.get("pcb") or {}).get("outline")
    if shape["shape"] != "rect" and isinstance(ol, dict):
        ol.update({"shape": shape["shape"], "r": r2(shape["r"])})
    def inside(c: dict[str, Any], x: float, y: float, note: str) -> None:
        """An edge connector nobody plugs from outside (a cell's JST, a probe's header): a part, not a wall window."""
        across = c["edge"] in ("+y", "-y")
        c.update({"access": "none", "x": r2(x), "y": r2(y), "w": c["w"] if across else c["d"], "d": c["d"] if across else c["w"],
                  "normal": [0, 0, 1], "note": note})
        for k in ("edge", "at", "protrude", "plug", "plugR"):
            c.pop(k, None)

    for n in doc["nodes"]:
        nid, c, part = n["id"], comps.get(n["id"]), parts.get(n["id"]) or {}
        if n["kind"] == "button" and n.get("switch"):
            if c is not None and pcs.get(nid):
                # the footprint's origin is the switch's centre: the board's box of it follows its pads
                sw, o = SWITCHES[n["switch"]], pcs[nid].get("footprint_origin") or pcs[nid]["center"]
                k = sw["key"]
                panel = k["stem"] == "panel"
                c.update({"type": f"key_{n['switch']}", "access": "key", "x": r2(o["x"] - ox), "y": r2(o["y"] - oy), "w": k["cut"], "d": k["cut"],
                          "h": r2(k["depth"] if panel else k["plate_top"] - k["plate_t"]), "key": k, "normal": [0, 0, 1], "verify": []})
                c.pop("note", None)
            continue
        if n["kind"] == "header" and n.get("connector"):
            edge = n.get("edge")
            if c is not None and pcs.get(nid):
                con, o = CONNECTORS[n["connector"]], pcs[nid].get("footprint_origin") or pcs[nid]["center"]
                w, x, y = con["pitch"] * len(n["pins"]), o["x"] - ox, o["y"] - oy
                if edge in EDGES and n.get("face") != "none":
                    # the wires come in through the wall: a window as wide as the block, as high as its entries
                    c.update({"type": n["connector"], "access": "port", "edge": edge, "at": r2(x if edge[1] == "y" else y), "w": r2(w), "h": con["h"], "d": con["d"], "z0": 0.0, "protrude": 0.0,
                              "plug": [r2(w), min(con["h"], 7.0)], "verify": []})
                    for f in ("x", "y", "normal", "note"):
                        c.pop(f, None)
                else:
                    c.update({"type": n["connector"], "access": "none", "x": r2(x), "y": r2(y), "w": r2(w), "d": con["d"], "h": con["h"], "verify": []})
                    c.pop("note", None)
            continue
        if n["kind"] == "chip" and part.get("mouth") and n.get("edge") in EDGES and n.get("face") != "none" and c is not None and pcs.get(nid):
            # a plug comes in through the wall: a window as wide as the body, from the board up to its top
            m, o, edge = part["mouth"], pcs[nid].get("footprint_origin") or pcs[nid]["center"], n["edge"]
            along = (o["x"] - ox if edge[1] == "y" else o["y"] - oy) + _mouth_shift(m, float(pcs[nid].get("rotation") or 0) % 360, edge)
            h = m["z1"] - m["z0"]
            c.update({"type": "connector", "access": "port", "edge": edge, "at": r2(along), "w": r2(m["w"]), "h": r2(h), "d": r2(m["d"]), "z0": r2(m["z0"]),
                      "protrude": 0.0,
                      "plug": [r2(max(m["w"], 8.0)), r2(max(h, 8.0))], "verify": []})
            for f in ("x", "y", "normal", "note"):
                c.pop(f, None)
            continue
        if face_of(n, part) in ("shaft", "hole") and c is not None and pcs.get(nid):
            # a knob's shaft through the lid: an encoder's or a potentiometer's body stays under it, a printed knob goes on top
            o = pcs[nid].get("footprint_origin") or pcs[nid]["center"]
            top = float(n.get("shaft_h") or part.get("height_mm") or 20.0)
            sd = float(n.get("shaft_d") or 6.0)
            c.update({"access": "key", "x": r2(o["x"] - ox), "y": r2(o["y"] - oy), "h": r2(min(top, 9.0)), "normal": [0, 0, 1],
                      "key": {"stem": "shaft", "cut": r2(sd + 1.0), "shaft_d": sd, "shaft_top": r2(top), "cap": [22.0, 22.0] if face_of(n, part) == "shaft" else [sd + 3.0, sd + 3.0],
                              "knob": face_of(n, part) == "shaft"}, "verify": []})
            c.pop("note", None)
            continue
        if n["kind"] != "accessory":
            if c is not None and c.get("access") == "port" and n.get("face") == "none" and pcs.get(nid):
                inside(c, pcs[nid]["center"]["x"] - ox, pcs[nid]["center"]["y"] - oy, "plugged inside the case (face none)")
            if c is None or c.get("access") == "port":
                continue
            face = face_of(n, part)
            if face != "none":
                c["access"] = face
                if ROUND_PACKAGE.search(_part_text(part)):
                    c["shape"] = "round"
            elif n.get("face") == "none" and c.get("access") == "light":
                c["access"] = "none"  # an LED the designer keeps inside the case
            continue
        a = acc.ACCESSORIES[n["accessory"]]
        entry: dict[str, Any] = {"id": nid, "key": n["accessory"], "name": a["name"], "kind": a["kind"], "mount": a["mount"]}
        pc = pcs.get(nid)
        rot = float((pc or {}).get("rotation") or 0) % 360
        c_, s_ = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        turn = lambda dx, dy: (dx * c_ - dy * s_, dx * s_ + dy * c_)  # noqa: E731
        bw, bd, bh = a["body"]
        swap = round(rot) % 180 == 90
        if a["mount"] == "board" and pc and c is not None:
            hx, hy = pc["center"]["x"] - ox, pc["center"]["y"] - oy  # the header row's centre
            ddx, ddy = turn(*[-v for v in (a.get("header_offset") or (0.0, 0.0))])
            bx, by = hx + ddx, hy + ddy
            n_pins = len(a["pins"])
            row, across = 2.54 * n_pins, 2.54
            along_x = (a.get("header_axis", "x") == "x") != swap
            # the board component is the header strip under the module; the module's body is an accessory
            c.update({"type": "pin_header_2_54", "access": "none", "x": r2(hx), "y": r2(hy), "w": r2(row if along_x else across),
                      "d": r2(across if along_x else row), "h": a.get("stack_h", 2.5), "note": f"header under {a['name']}"})
            c.pop("verify", None)
            entry.update({"x": r2(bx), "y": r2(by), "w": r2(bd if swap else bw), "d": r2(bw if swap else bd), "h": bh, "z0": a.get("stack_h", 2.5)})
            if a.get("window"):
                ww, wd = a["window"]
                wx, wy = turn(*(a.get("window_offset") or (0.0, 0.0)))
                entry.update({"window": [r2(wd if swap else ww), r2(ww if swap else wd)], "window_dx": r2(wx), "window_dy": r2(wy)})
                if a.get("window_shape") == "round":
                    entry["shape"] = "round"
            if a.get("holes"):
                entry["holes"] = [{"x": r2(bx + turn(hx_, hy_)[0]), "y": r2(by + turn(hx_, hy_)[1]), "d": d} for hx_, hy_, d in a["holes"]]
        elif a["mount"] == "cable" and pc:
            hx, hy = pc["center"]["x"] - ox, pc["center"]["y"] - oy
            entry.update({"x": r2(hx), "y": r2(hy), "w": bw, "d": bd, "h": bh, "cable_d": a.get("cable_d", 3.0)})
            if c is not None and c.get("access") == "port":
                entry.update({"edge": c["edge"], "at": c["at"]})
                # the lead leaves by the accessory's cable exit; its header inside is plugged once, not through a wall
                inside(c, hx, hy, f"connector of {a['name']}: its lead leaves by the cable exit")
            elif n.get("edge"):
                entry["edge"] = n["edge"]
                entry["at"] = r2(hy if n["edge"] in ("+x", "-x") else hx)
        else:  # loose in the case (a LiPo): it needs room, the case decides where
            entry.update({"x": r2(W / 2), "y": r2(H / 2), "w": bw, "d": bd, "h": bh})
        out_acc.append(entry)
    if out_acc:
        board["accessories"] = out_acc
    return board


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
    # a catalogue connector has no port until dress_board reads its mouth: its place on the edge is the compiler's own
    edge = {n["id"]: n["edge"] for n in doc["nodes"] if n.get("edge") and n["kind"] != "chip"}
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
                                              "url", "size_mm", "height_mm", "error", "tht") if part.get(k) is not None},
            "price_usd": catalog.price_at(part.get("prices") or [], 10) if part.get("prices") else None,
        }
        if n["kind"] == "module":
            m = MODULES[n["module"]]
            nodes[n["id"]]["part"].update({"mpn": m["name"], "mcu": m["mcu"], "wireless": m["wireless"], "url": m["url"]})
        if n["kind"] == "accessory":
            a = acc.ACCESSORIES[n["accessory"]]
            nodes[n["id"]]["part"].update({"accessory": n["accessory"], "kind": a["kind"], "mount": a["mount"], "note": a["note"]})
            conn = part.get("connector")
            if conn and a["connect"] in ("header", "jst"):
                unit = catalog.price_at(conn.get("prices") or [], 10) if conn.get("prices") else None
                # a header is cut from a 1x40 strip, as bom_of prices it
                price = unit * max(1, len(a["pins"])) / 40 if unit is not None and a["connect"] == "header" else unit
                nodes[n["id"]]["part"]["connector"] = {**{k: conn.get(k) for k in ("lcsc", "mpn", "package", "basic", "stock", "url")}, "price_usd": price}
        nodes[n["id"]]["face"] = face_of(n, part)
    plan, _ = decoupling(doc, parts)
    return {"nodes": nodes, "power": [net.get("name") for net in doc["nets"] if net.get("name") and POWER_NET.match(net["name"])],
            # a chip and the capacitors placed at its pins move together on the board
            "groups": {chip: [cap for cap, *_ in caps] for chip, caps in plan.items() if not bulky(parts.get(chip) or {})}}


def library() -> dict[str, Any]:
    """What the editor's palette offers besides catalogue search: modules and primitives with their pins."""
    return {
        "modules": [{"module": k, "name": m["name"], "mcu": m["mcu"], "pins": m["pins"], "wireless": m["wireless"], "price_usd": m["price_usd"],
                     "size_mm": m["size"], "gpio": m["gpio"], "strapping": m["strapping"], "battery": m["battery"]} for k, m in MODULES.items()],
        "primitives": [{"kind": k, "prefix": v["prefix"], "pins": v["pins"]} for k, v in PRIMS.items()] + [{"kind": "header", "prefix": "J", "pins": ["P1", "P2", "P3", "P4"]}],
        # ready-made modules fitted by hand: node {kind: 'accessory', accessory: key}; the carrier gets their connector
        "accessories": acc.catalogue(),
        "faces": list(FACES),
        "layouts": list(LAYOUTS),
        # what a button node may be besides a tact switch: node {kind: 'button', switch: key}
        "switches": [{"switch": k, "name": v["name"], "price_usd": v["price_usd"], "pitch": v["pitch"], "note": v["note"]} for k, v in SWITCHES.items()],
        # what a header node may be besides 2.54 mm pins: node {kind: 'header', connector: key, pins: [...]}
        "connectors": [{"connector": k, "name": v["name"], "amps": v["amps"], "pitch": v["pitch"]} for k, v in CONNECTORS.items()],
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
        for k in ("lcsc", "module", "accessory", "switch", "value", "package", "color", "pins", "edge", "face", "label"):
            if a[nid].get(k) != b[nid].get(k):
                out.append(f"{nid}: {k} {a[nid].get(k) or '-'} -> {b[nid].get(k) or '-'}")
        pa, pb = a[nid].get("pcb"), b[nid].get("pcb")
        if pa != pb:
            out.append(f"{nid}: placed by hand on the board at ({pb['x']:g}, {pb['y']:g}) mm, rotation {pb['rot']}" if pb
                       else f"{nid}: hand placement removed (placed automatically again)")
        qa, qb = a[nid].get("place"), b[nid].get("place")
        if qa != qb:
            out.append(f"{nid}: placed at ({qb['x']:g}, {qb['y']:g}) mm, rotation {qb['rot']:g}" if qb else f"{nid}: place removed")
    if (old.get("layouts") or []) != (new.get("layouts") or []):
        out.append("layouts: " + ("; ".join(f"{x['pattern']} of {', '.join(x['nodes'])}" for x in new.get("layouts") or []) or "removed"))
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
    if (ba.get("shape") or "rect", ba.get("r")) != (bb.get("shape") or "rect", bb.get("r")):
        out.append(f"board shape {bb.get('shape') or 'rect'}" + (f", corner radius {bb['r']:g} mm" if bb.get("r") else ""))
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
                        "nets": doc.get("nets") or [], "board": doc.get("board") or {}, "routes": doc.get("routes") or [], "zones": doc.get("zones") or [],
                        "layouts": doc.get("layouts") or []}, sort_keys=True)
