"""Model-facing text of the 'device' pack: how a whole device is designed as a graph of real parts (fw.device/1), the
modules and primitives, the design rules, the flow from the graph to a routed board, its case, firmware and price.
Everything here is English: models read it. EXAMPLE is a document the engine builds clean (tests/test_device.py).
"""
from __future__ import annotations

import json

from ..device import MODULES

_MODULES = "\n".join(f"  - {k}: {m['name']} ({m['mcu']}{', ' + ' + '.join(m['wireless']) if m['wireless'] else ''}), "
                     f"{m['size'][0]:g} x {m['size'][1]:g} mm, pins {' '.join(m['pins'])}"
                     + (f"; aliases {', '.join(f'{a}={t}' for a, t in m['aliases'].items())}" if m["aliases"] else "")
                     for k, m in MODULES.items())

PACK_TEXT = f"""
# Pack: a finished device (from a description to a board with real parts, its case, firmware and an order)
You design the whole device as a graph of parts and nets (fw.device/1) with write_device. You never write coordinates or TSX:
build_device compiles the graph, places the edge parts facing out, packs the rest next to the pins it connects, autoroutes 2
layers, runs DRC and the intent checks and exports the fab files; the board grows until it routes. The JS program format above
is only for the case, which make_enclosure writes for you.
Flow: decide what the device must do -> pick the microcontroller -> search_parts for every function (sensor, driver,
regulator, display connector) -> part_info for every chip you wire (its real pins) -> write_device -> build_device -> fix ->
make_enclosure -> write_firmware -> quote_device -> finish. Choose parts and pins yourself and say which in the summary; ask
only what changes the device's purpose. The person sees the graph in a node editor and may edit it: keep their changes.

## The document
{{"schema": "fw.device/1", "title": "...", "summary": "what it does", "board": {{"holes": true}}, "nodes": [...], "nets": [...]}}
Nodes (id = reference designator, label = the role in a few words):
- module: a development board on headers, its own USB-C/micro-USB facing `edge` (default "+y"); it decouples itself.
{_MODULES}
- chip: {{"id": "U2", "kind": "chip", "lcsc": "C92489", "label": "climate sensor"}}: any LCSC part with an EasyEDA footprint. Wire it by
  the labels part_info gives ('U2.SDI'); a name that repeats (GND twice) is one reference for all of them.
- resistor {{"value": "4.7k", "package": "0603"}} pins 1, 2; capacitor {{"value": "100nF"}} pins 1, 2 (1 is + for polarised);
  led {{"color": "green|red|blue|yellow|white"}} pins A, K; diode (Schottky B5819W, 1 A) pins A, K.
- button (6 x 6 mm tact switch, pressed through the case lid): pins A, B, its two contacts.
- header {{"pins": ["V3V3", "GND", "SDA", "SCL"], "edge": "-y"}}: 2.54 mm pin header; for things on wires (an I2C OLED display,
  a probe, a servo, a relay module), programming or expansion. Pins are its labels.
- usb_c {{"edge": "-y"}}: 16-pin receptacle, pins VBUS GND CC1 CC2 DP DM. Power needs CC1 and CC2 each 5.1k to GND.
- jst {{"edge": "+x"}}: JST PH 2.0 2-pin, P1 = +, P2 = -: battery or external power.
Nothing else: no coordinates, rotations or footprints. A node with `pcb` {{x, y, rot}} was placed on the board by the person:
keep it as it is (write_device keeps it when you leave it out) and never add one yourself. `routes` are traces the person
drew pad to pad ({{from: 'R3.pin2', to: 'LED1.pin1', layer, width, points}}): the build keeps them and autoroutes the rest;
leave them out of your documents (write_device keeps them) and never draw any. `zones` (copper pours, keepouts) are the
person's too: keep them. 4 M3 corner holes come with board.holes.
Optional board.w/h (mm) fixes the size (only when the person gives one; otherwise it is found).
edge: "-x" | "+x" | "-y" | "+y" (left, right, bottom, top) for usb_c, header, jst and modules; parts sharing an edge are spread along it.
Nets: [{{"name": "GND", "pins": ["U1.GND", "U2.GND", "C1.2"]}}, {{"name": "SDA", "pins": [...]}}, {{"pins": ["U1.D10", "R3.1"]}}].
Name supply and bus nets (GND, V3V3, V5, VBUS, VBAT, SDA, SCL, MOSI...); a name starts with a letter (V3V3, never 3V3). V5, VBUS,
VSYS, VBAT and VIN are routed 0.4 mm wide. A pin belongs to one net; two nets sharing a pin become one.

## Design rules (write_device warns; you decide)
- Every chip: 100nF from each supply pin to GND (plus 10uF on a regulator's input and output and on radios). The build puts
  each one at its chip's supply pin; name the chip in its label ('U2 decoupling'). Never delete a decoupling capacitor to
  clear a DRC error: fix the board instead.
- I2C: 4.7k pull-ups on SDA and SCL to 3V3, once per bus. LED: 1k from the GPIO to A, K to GND. Button: A to a GPIO (internal
  pull-up), B to GND.
- Read the supply range in part_info's description; tie configuration pins as the datasheet says (BME280: CSB to 3V3 = I2C,
  SDO to GND = address 0x76). Never leave an enable pin floating.
- Powering a module from another input: into XIAO V5 / Pico VSYS through the Schottky (A on the source), so its own USB cannot
  back-feed. The module's 3V3 supplies small sensors (up to ~200 mA); motors, LED strips and relays need their own supply.
- Prefer in-stock JLCPCB basic parts (no extended fee) and parts with stock for 50+ boards. At most 40 parts and 30 nets.
- A display, a probe or a sensor that must sit outside the case goes on a header at the edge; say what plugs in.

## Build, case, firmware, price
- build_device errors come root cause first with hints naming parts; change the graph (fewer parts, another edge for a
  connector, split a crowded edge), write_device, build again (1-3 rounds). look(what='pcb') shows the routed board.
- make_enclosure builds the snap-fit case from the routed board (windows for edge ports, press tabs over buttons, light
  windows over LEDs) and checks it; with_mockup adds a printed stand-in plate of the PCB. The case's size is case_fit.case_mm
  (assembled); size_mm is the print plate with the parts side by side, never the case's size.
- write_firmware: a complete program for the microcontroller with the exact pins of the graph (XIAO: D0-D10 as wired, SDA = D4,
  SCL = D5; Pico: GPn); libraries and how to flash in notes. Arduino for XIAO ESP32-C3/S3, MicroPython or Arduino for Pico.
  Implement every function the person asked for, no TODO stubs: Wi-Fi joins with SSID/password constants at the top and serves
  the readings on a small web page (and JSON at /api) or posts them where they said; a sleep schedule, debouncing, a fallback
  when a sensor is missing.
- quote_device: the price of N finished devices (parts, PCB, assembly, case, delivery) and the date; say it in the summary.
- finish needs the latest device version built clean (0 DRC errors, intent met), a case made from that board and firmware.
- Summary, for a non-engineer: what the device does, its parts (with LCSC numbers for chips), which pin drives what, board size,
  the case, the firmware, the price of 5 and the date, and what is unverified (part heights, rotations at the fab).
""".strip()

EXAMPLE_DOC = {
    "schema": "fw.device/1", "title": "Weather station", "summary": "Temperature, humidity and pressure on a 0.96\" OLED, status LED, button",
    "board": {"holes": True},
    "nodes": [
        {"id": "U1", "kind": "module", "module": "113991054", "label": "MCU", "edge": "+y"},
        {"id": "U2", "kind": "chip", "lcsc": "C92489", "label": "BME280 climate sensor"},
        {"id": "C1", "kind": "capacitor", "value": "100nF", "label": "U2 decoupling"},
        {"id": "R1", "kind": "resistor", "value": "4.7k", "label": "SDA pull-up"},
        {"id": "R2", "kind": "resistor", "value": "4.7k", "label": "SCL pull-up"},
        {"id": "R3", "kind": "resistor", "value": "1k", "label": "LED resistor"},
        {"id": "LED1", "kind": "led", "color": "green", "label": "status"},
        {"id": "SW1", "kind": "button", "label": "page"},
        {"id": "J2", "kind": "header", "pins": ["V3V3", "GND", "SCL", "SDA"], "edge": "-y", "label": "OLED SSD1306 I2C"},
    ],
    "nets": [
        {"name": "GND", "pins": ["U1.GND", "U2.GND", "U2.SDO", "C1.2", "LED1.K", "SW1.B", "J2.GND"]},
        {"name": "V3V3", "pins": ["U1.V3V3", "U2.VDD", "U2.VDDIO", "U2.CSB", "C1.1", "R1.1", "R2.1", "J2.V3V3"]},
        {"name": "SDA", "pins": ["U1.SDA", "U2.SDI", "R1.2", "J2.SDA"]},
        {"name": "SCL", "pins": ["U1.SCL", "U2.SCK", "R2.2", "J2.SCL"]},
        {"pins": ["U1.D10", "R3.1"]},
        {"pins": ["R3.2", "LED1.A"]},
        {"pins": ["U1.D1", "SW1.A"]},
    ],
}

EXAMPLE = ("# Reference device (built: 0 DRC errors, intent met, 36 x 35 mm): a XIAO ESP32-C3 weather station. Learn the patterns;"
           " your device picks its own parts.\n```json\n" + json.dumps(EXAMPLE_DOC, ensure_ascii=False, separators=(",", ":")) + "\n```")

CLASSIFY_HINT = ("device (a complete electronic device from a description: 'I need a weather station / plant watering controller / "
                 "a tracker / a macro keypad / a gadget that ...': real parts from the LCSC catalogue, a routed board, its 3D-printed "
                 "case and firmware, ready to order; also any request to build electronics without asking for a specific PCB file)")
