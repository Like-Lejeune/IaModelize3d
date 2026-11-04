"""Model-facing text of the 'device' pack: the designer's method from a description to an order (requirements, architecture,
parts, schematic with drivers, front panel, build, case, firmware, price), the document's fields, the modules' pins and
the design rules. Everything here is English: models read it, every turn, so it stays compact. EXAMPLE_DOC is a document
the engine builds clean (tests/test_device.py builds it through the real bundle); the dice after it shows place, layouts,
accessories and grouped LEDs and is not built by the tests (its accessory key comes from the library when there is one).
"""
from __future__ import annotations

import json

from ..device import MODULES

_MODULES = "\n".join(f"  - {k}: {m['name']} ({m['mcu']}{', ' + ' + '.join(m['wireless']) if m['wireless'] else ''}), "
                     f"{m['size'][0]:g} x {m['size'][1]:g} mm, pins {' '.join(m['pins'])}"
                     + (f"; aliases {', '.join(f'{a}={t}' for a, t in m['aliases'].items())}" if m["aliases"] else "")
                     for k, m in MODULES.items())


def _accessories() -> dict:
    """The accessory library (C1d) when it is there; the pack works without it."""
    try:
        from ..accessories import ACCESSORIES
    except Exception:  # noqa: BLE001 - not landed yet, or broken: the prompt still loads
        return {}
    return ACCESSORIES if isinstance(ACCESSORIES, dict) else {}


_ACC = _accessories()
_ACC_LINES = "\n".join(f"  - {k}: {a.get('name', k)}; pins {' '.join(a.get('pins') or []) or '-'}; {a.get('connect', '?')}, mount {a.get('mount', '?')}"
                       + (f"; {a['supply']}" if a.get("supply") else "") for k, a in _ACC.items()) or "  (the library is empty here: use a header)"

PACK_TEXT = f"""
# Pack: a finished device (from a description to a board with real parts, its case, firmware and an order)
You design the whole device as a graph of parts and nets (fw.device/1) with write_device; build_device compiles it into a
board: edge parts face out, parts you `place` go where you put them, the rest the compiler places next to the pins they connect, then
2-layer autorouting, DRC, the intent checks and fab files; the board grows until it routes. You never write TSX. The JS
program format above is only for the case, which make_enclosure writes for you. Choose parts and pins yourself and say which
in the summary; ask only what changes the device's purpose. The person sees the graph in a node editor and may edit it: keep
their changes.

## Method: every device, in this order
1. Concept and brainstorm, before any part (doc.concept). Imagine 2-4 uses: where it lives, who uses it, how it is seen,
   heard and touched there, how it is powered and charged. Then brainstorm at least three genuinely different options, each
   another form, stance, mounting, board shape or panel: a night light as a round puck on the nightstand with a ring of
   LEDs, a wedge on the wall at plug height lighting downwards, a stake in a hallway pot; a kitchen timer as a tilted desk
   wedge with the display facing the cook, a fridge-magnet puck, an egg in the hand. Choose the one that fits the uses best
   and is compact. Prefer an original shape made for its purpose to the default box, never at the cost of working. All the
   rest follows the chosen one: board.shape and w/h, the module's edge, place and layouts as its panel says, make_enclosure's
   form, stance and mounting. To change course, write a new concept.chosen; never drift from it silently.
   {{"uses": ["..."], "options": [{{"name": "...", "look": "one line", "form": "soft|round|box", "stance":
   "desk|tilt|upright|wall|hand|auto", "mounting": "none|ears|strap|lanyard|stake|magnets|contacts", "board": {{"shape":
   "rect|rounded|round", "w": mm, "h": mm}}, "module_edge": "+y|-y|+x|-x", "panel": "what is where on the lid"}}, ...],
   "chosen": "<an option's name>", "why": "..."}}
2. Requirements: doc.requirements = [{{"id": "R1", "text": "...", "parts": [node ids], "firmware": true}}], every function
   the person asked for plus the obvious ones a device of that kind needs (a night light must be seen and must sense the dark;
   a battery device must charge and sleep; a timer must be heard). Each names the parts that do it; firmware: true when code
   does it too. They are the person's: never drop, weaken or reword one to make a build pass or to match the code or a
   review; fix the board or the code instead.
3. Architecture: the module (MCU); power from its USB-C or a battery. A battery device on a XIAO takes a LiPo accessory with
   connect module_bat (the cell goes on the module's BAT pads, the module charges it from USB), never a cell on V5: USB would
   push 5 V into it. A battery device sleeps (deep sleep, wakes on its button, sensor or a timer). What the person
   touches, sees and hears sits where the concept's panel puts it: the lid is over the top of the board.
4. Parts: search_parts with short queries (a part number 'AM312', or 2-3 words 'buzzer 3V', 'NPN SOT-23'); part_info for every
   chip you wire. Ready-made modules the fab does not solder (displays, PIR modules, probes, batteries, servos) are accessory
   nodes, so the order is complete; never a bare header "for your OLED". No spare or "expansion" connector the request does
   not need: each one is a hole in the case, a row in the order and a pin the firmware never uses.
5. Schematic with explicit drivers, pull-ups and decoupling (rules below).
6. Front panel, as the concept's panel says: `place` or `layouts` for everything user-facing (dice pips, an LED row or ring, buttons, the display centred on
   the lid, a sensor at its window), `face` where the default is wrong.
7. write_device, then fix every design_errors item (they block finish; design_warnings are yours to judge; place_conflict
   names the board's free area: move the placed part there or enlarge board.w/h), then build_device.
8. Plan builds: each costs a turn and about a minute, and every tool result says the turn (turn x of N). Before the first,
   give user-facing parts room and size the board for them; after a failed one, fix every placement error it lists in one
   write_device. Fix by moving or reshaping: a larger board.w/h, another edge, other place coordinates, a smaller package.
   Never by deleting a requested function, a decoupling capacitor or a driver. If it cannot be done, say so in the summary.
9. make_enclosure with the chosen concept's form, stance and mounting, plus mount_edge (the wall without ports) and
   min_height where they fit; build_device and make_enclosure return concept_warnings where the result left the concept:
   change the design or the concept until they agree. Check that every face part and accessory got its opening in the enclosure findings (light_window,
   display_window, sound_grille, sensor_window, cable_exit, battery_space); fix what is missing. After any later rebuild,
   make_enclosure again (the case is made from the latest board).
10. write_firmware: pins exactly as wired (write it again whenever they change); a comment at each analog sensor says which
   way its reading moves for the divider as wired (an LDR from V3V3 to the pin with 10k to GND reads higher in light; the
   sensor_divider warning states it) and the thresholds follow it. A light sensor in the same box as the device's own lights
   sees them: decide dark while they are off (read before switching on, never "it got bright, switch off" while lit), or the
   light switches itself off and flickers. It must pass the firmware check. write_firmware also runs it on a virtual board wired
   as your graph (`simulation`: each input in each condition, a probe that stays wet, hours left alone); its errors block finish.
   simulate_device plays your own steps: use it for what only a sequence shows (start, stop, start again).
11. quote_device, then finish with an honest summary. Its first answer is self_check, the checklist items for your graph's
   part kinds (the self-check below): check each, fix what is wrong, then finish again with `checked`.

## The document
{{"schema": "fw.device/1", "title": "...", "summary": "what it does", "board": {{"holes": true}}, "concept": {{...}}, "requirements": [...],
"nodes": [...], "nets": [...], "layouts": [...]}}
Nodes (id = reference designator, label = the role in a few words):
- module: a development board on headers, its own USB-C facing `edge` (default "+y"); it decouples itself.
{_MODULES}
- chip: {{"id": "U2", "kind": "chip", "lcsc": "C92489", "label": "climate sensor"}}: any LCSC part with an EasyEDA footprint. Wire
  it by part_info's labels ('U2.SDI'): repeated signal pins get distinct labels (P1, P2), a transistor is B/E/C or G/S/D, a
  diode or LED A/K, a lone + / - terminal (buzzers) POS / NEG; a supply name that repeats (GND twice) is one reference for
  all of them; pin_note says when the roles come from the standard package pinout. kind_hint says what it is
  (npn, nmos, buzzer_active, rgb_led, sensor...), current_ma what it draws.
- resistor {{"value": "4.7k", "package": "0603"}} pins 1, 2; capacitor {{"value": "100nF"}} pins 1, 2 (1 is + for polarised);
  led {{"color": "green|red|blue|yellow|white"}} pins A, K: indicator colours only (the white is cold); any other light is a
  chip LED from search_parts ('warm white LED', wired A/K); diode (Schottky B5819W, 1 A) pins A, K.
- button (6 x 6 mm tact switch, pressed through the case lid): pins A, B, its two contacts.
- accessory {{"id": "DS1", "kind": "accessory", "accessory": "<key>", "label": "display", "edge"?: "-y", "place"?: {{...}}}}: a
  ready-made module, hand-fitted and priced in the order; the build puts its connector on the board, wire it by its pins
  ('DS1.SDA'); the case holds it (mount board), lets its cable out (cable) or makes room (inside). Library:
{_ACC_LINES}
- header {{"pins": ["V3V3", "GND", "SDA", "SCL"], "edge": "-y"}}: 2.54 mm pin header for programming or expansion only.
- usb_c {{"edge": "-y"}}: 16-pin receptacle, pins VBUS GND CC1 CC2 DP DM. Power needs CC1 and CC2 each 5.1k to GND.
- jst {{"edge": "+x"}}: JST PH 2.0 2-pin, P1 = +, P2 = -: external power.
Front panel (mm from the board centre, +y up):
- place {{"x": 0, "y": 8, "rot": 0}} on a node: where a part people see or touch sits (LED, button, display, sensor, buzzer).
  Give user-facing parts room (a 6 x 6 button needs 9 mm, a display its whole body); the build places everything else.
  The module on its edge takes a ~21 mm band (XIAO on +y: y above H/2 - 21 is taken); a board-mounted accessory's place is
  its body centre and nothing else sits under that body.
- layouts [{{"pattern": "dice"|"row"|"column"|"grid"|"ring", "nodes": [ids], "center": [x, y], "pitch": 8, "cols": n, "radius": mm,
  "rot": deg}}] places many at once; dice order: centre, top-left, top-right, middle-left, middle-right, bottom-left, bottom-right.
- face "light"|"sound"|"sensor"|"display"|"none": what a part needs from the lid above it. Defaults: LEDs and LED chips light,
  buzzers sound, PIR, light, gas and humidity sensors and microphones sensor, the rest none. A jst or header that is plugged
  inside the case (not from outside) takes face "none", so the case cuts no wall window for it.
- pcb {{x, y, rot}} is the person's own placement from the editor: keep it (write_device keeps it when you leave it out), never
  write one. `routes` (traces they drew) and `zones` (pours, keepouts) are theirs too: write_device keeps them, never add any.
board.w/h (mm): yours is a minimum the build grows when placed parts do not fit; the person's (board.locked) is fixed.
place_conflict from write_device blocks the build: follow its levers (a new place, or the board size it names) or use the
free area it states. Never place edge parts (the module, usb_c, jst, cable headers): their edge places them. 4 M3 corner holes come with
board.holes. edge: "-x" | "+x" | "-y" | "+y" (left, right, bottom, top) for usb_c, header, jst, modules and cable accessories.
Nets: [{{"name": "GND", "pins": ["U1.GND", "U2.GND", "C1.2"]}}, {{"pins": ["U1.D10", "R3.1"]}}]. Name supply and bus nets (GND, V3V3,
V5, VBUS, VBAT, SDA, SCL...); a name starts with a letter (V3V3, never 3V3). V5, VBUS, VSYS, VBAT and VIN are routed 0.4 mm
wide. A pin belongs to one net; two nets sharing a pin become one.

## Module pins (firmware uses these numbers)
XIAO ESP32-C3: D0=GPIO2, D1=3, D2=4, D3=5, SDA(D4)=6, SCL(D5)=7, TX(D6)=21, RX(D7)=20, SCK(D8)=8, MISO(D9)=9, MOSI(D10)=10;
deep-sleep wake only on GPIO0-5 (D0-D3). XIAO ESP32-S3: D0=1, D1=2, D2=3, D3=4, SDA=5, SCL=6, TX=43, RX=44, SCK=7, MISO=8,
MOSI=9. Pico: GPn = n. Strapping pins (C3: GPIO 2, 8, 9; S3: 0, 3, 45, 46) decide how the chip boots: nothing that pulls
them low at reset (an LED or buzzer to GND, a pressed button); use them last. Analog inputs: C3 D0-D2 (D3 is ADC2, dead
while Wi-Fi is on); S3 D0-D10 but TX and RX; Pico GP26-28.

## Design rules (write_device returns design_errors and design_warnings)
- Every chip: 100nF from each supply pin to GND (plus 10uF on a regulator's input and output and on radios and LED chains),
  labelled with its chip ('U2 decoupling'); the build puts it at the pin. Transistors, diodes, buzzers and LEDs need none.
- A GPIO drives 10 mA at most. A buzzer, relay, motor, LED string or anything from 20 mA goes through a low-side switch: NPN
  (S8050, MMBT2222: E to GND, C to the load's -, the load's + to its supply, 1k from the GPIO to B) or N-MOSFET (AO3400,
  2N7002: S to GND, D to the load, 100R from the GPIO to G, 100k G to GND); a diode across relays, motors and magnetic
  buzzers (K to the + side).
- WS2812/SK6812 on V5 needs data above 0.7 x VDD: feed its VDD from V5 through a diode (about 4.3 V, 3.3 V data then works)
  or add a level shifter; 330R in series with DIN, 100nF at each LED, 10uF on the chain. On V3V3 it runs directly if part_info's
  range allows. Its DOUT goes to the next DIN.
- I2C: 4.7k pull-ups on SDA and SCL to V3V3, once per bus. LED: 1k from the GPIO to A, K to GND. Button: A to a GPIO (internal
  pull-up), B to GND.
- Read the supply range in part_info's description; tie configuration pins as the datasheet says (BME280: CSB to V3V3 = I2C,
  SDO to GND = 0x76). Never leave an enable pin floating.
- Power: the module's 3V3 supplies small parts (up to ~200 mA); motors, LED strips and relays need their own supply. 5 V
  from another input goes into XIAO V5 / Pico VSYS through the Schottky (A on the source) so USB cannot back-feed.
- Prefer in-stock JLCPCB basic parts (no extended fee) with stock for 50+ boards. At most 40 parts and 30 nets.

## Build, case, firmware, price
- build_device: ok only with 0 DRC errors and the intent met. Errors come root cause first with hints naming parts; change the
  graph (place, another edge, a fixed larger board), write_device, build again. look(what='pcb') shows the routed board.
- make_enclosure builds the snap-fit case from the routed board (port windows, press tabs over buttons, openings over face parts,
  display windows, cable exits) and checks it; with_mockup adds a printed stand-in plate of the PCB. The case's size is
  case_fit.case_mm (assembled); size_mm is the print plate.
- Look closely, never assume: checks pass on boards people would reject (an LED beside its window, a light sensor next to the
  LEDs it must ignore, a connector facing inwards, a buzzer under the display, parts crowded into a corner with a 30 mm
  detour). After build_device, inspect_board each user-facing part (its neighbours, what sits over it, which way it faces)
  and the longest connections and detours (inspect_board without focus lists them). After make_enclosure, inspect_case
  focused on each light, display, button and sensor (assembled: what its window uncovers; lid_off or section: where it sits
  under the lid): is its opening right over it? Before saying a part works, inspect_part: its nets, the pin that drives it
  and the firmware lines that use it. Fix what you see, then look again.
- write_firmware: a complete program with the exact pins of the graph (Arduino for XIAO ESP32-C3/S3, MicroPython or Arduino
  for Pico); libraries and how to flash in notes. Every requirement with firmware: true implemented, no TODO stubs: debouncing,
  a fallback when a sensor is missing, the sleep schedule; Wi-Fi with SSID/password constants at the top when asked. Text on a
  display in English: the default Adafruit GFX and U8g2 fonts have no Cyrillic (a U8g2 font ending in _t_cyrillic has).
  Pins by their board names as wired (D0, SDA...), Wire.begin() with no arguments on the module's own I2C pins, arduino-esp32
  3.x LEDC calls (ledcAttach/ledcWrite). write_firmware compiles it against the core and checks every pin against the graph.
- quote_device: the price of N finished devices (parts, accessories, PCB, assembly, case, delivery) and the date.
- finish needs: the latest device version built clean, no design_errors, every requirement's parts in the device, the case
  made from that board with every opening, firmware that passes its check for the current wiring (a requested sleep or fade
  really in the code) and a clean simulation, and your self-check answered for every part kind (`checked`).
- Summary, for a non-engineer: what the device does, its parts (LCSC numbers for chips), which pin drives what, board and case
  size, the firmware, the price of 5 and the date, what is in the order (every accessory is in it, fitted: a LiPo comes
  soldered to the module's BAT pads) and what the person adds, what is unverified. Battery life only from simulation.power
  (idle_life_h, sleep_ma). Claim nothing the board or the code does not do.
""".strip()


def _checklist() -> str:
    """The typical mistakes per part kind (device_checklists), after the method in the pack's prompt; the pack works without."""
    try:
        from ..device_checklists import all_text
    except Exception:  # noqa: BLE001 - broken: the prompt still loads
        return ""
    return all_text()


CHECKLIST = _checklist()

EXAMPLE_DOC = {
    "schema": "fw.device/1", "title": "Weather station",
    "summary": "Temperature, humidity and pressure on a Wi-Fi web page, status LED, a page button, an I2C header for one more sensor",
    "board": {"holes": True},
    "concept": {
        "uses": ["on a living-room shelf, powered from a USB charger: a glance at the LED, the readings on a phone",
                 "in a bedroom at night: is the air too dry, one press flips the page to the last 24 hours"],
        "options": [
            {"name": "Shelf block", "look": "a small soft block standing on a shelf, LED and button on its lid", "form": "soft",
             "stance": "desk", "mounting": "none", "board": {"shape": "rect", "w": 36, "h": 35}, "module_edge": "+y",
             "panel": "status LED left, page button right, the sensor at the bottom edge away from the module's heat"},
            {"name": "Wall tile", "look": "a flat tile on two screws at eye height, the cable leaving at the bottom", "form": "box",
             "stance": "wall", "mounting": "ears", "board": {"shape": "rect", "w": 30, "h": 45}, "module_edge": "-y",
             "panel": "LED at the top, button under it, the sensor vent at the top, far from the module"},
            {"name": "Window puck", "look": "a round puck held by magnets on a metal window frame", "form": "round",
             "stance": "upright", "mounting": "magnets", "board": {"shape": "round", "w": 42, "h": 42}, "module_edge": "-y",
             "panel": "LED in the centre, button beside it, the sensor at the top of the circle"}],
        "chosen": "Shelf block",
        "why": "It stands wherever a charger reaches, keeps the LED and button in reach and is the smallest of the three.",
    },
    "requirements": [
        {"id": "R1", "text": "measure temperature, humidity and pressure", "parts": ["U2"], "firmware": True},
        {"id": "R2", "text": "serve the readings on a web page over Wi-Fi", "parts": ["U1"], "firmware": True},
        {"id": "R3", "text": "a status LED blinks on every reading", "parts": ["LED1"], "firmware": True},
        {"id": "R4", "text": "a button flips the web page between the current values and the last 24 hours", "parts": ["SW1"], "firmware": True},
    ],
    "nodes": [
        {"id": "U1", "kind": "module", "module": "113991054", "label": "MCU", "edge": "+y"},
        {"id": "U2", "kind": "chip", "lcsc": "C92489", "label": "BME280 climate sensor"},
        {"id": "C1", "kind": "capacitor", "value": "100nF", "label": "U2 decoupling"},
        {"id": "R1", "kind": "resistor", "value": "4.7k", "label": "SDA pull-up"},
        {"id": "R2", "kind": "resistor", "value": "4.7k", "label": "SCL pull-up"},
        {"id": "R3", "kind": "resistor", "value": "1k", "label": "LED resistor"},
        {"id": "LED1", "kind": "led", "color": "green", "label": "status"},
        {"id": "SW1", "kind": "button", "label": "page"},
        {"id": "J2", "kind": "header", "pins": ["V3V3", "GND", "SCL", "SDA"], "edge": "-y", "label": "I2C expansion"},
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


def _dice() -> dict:
    """A front-panel device: seven pips in the dice pattern on four GPIOs (the pairs that always light together share one),
    the roll button beside the module on a wake-capable pin, a LiPo on the module's BAT pads when the library has one."""
    lipo = next((k for k, a in _ACC.items() if isinstance(a, dict) and a.get("connect") == "module_bat"), None)
    leds = [f"LED{i}" for i in range(1, 8)]
    return {
        "schema": "fw.device/1", "title": "Electronic dice", "summary": "Press the button: the pips roll and stop on 1-6",
        "board": {"holes": True, "w": 46, "h": 50},
        "requirements": [
            {"id": "R1", "text": "seven pips in the dice pattern, seen through the lid", "parts": leds, "firmware": True},
            {"id": "R2", "text": "a button on the lid rolls the dice", "parts": ["SW1"], "firmware": True},
            {"id": "R3", "text": ("runs on a LiPo charged from the module's USB-C, deep sleep after 30 s, the button wakes it" if lipo
                                  else "powered from the module's USB-C"), "parts": ["U1", "BT1"] if lipo else ["U1"], "firmware": True},
        ],
        "nodes": [{"id": "U1", "kind": "module", "module": "113991054", "label": "MCU", "edge": "-y"},
                  *[{"id": f"LED{i}", "kind": "led", "color": "red", "label": f"pip {i}"} for i in range(1, 8)],
                  *[{"id": f"R{i}", "kind": "resistor", "value": "1k", "label": f"LED{i} resistor"} for i in range(1, 8)],
                  {"id": "SW1", "kind": "button", "label": "roll", "place": {"x": 14, "y": -12}},
                  *([{"id": "BT1", "kind": "accessory", "accessory": lipo, "label": "battery"}] if lipo else [])],
        "layouts": [{"pattern": "dice", "nodes": leds, "center": [0, 9], "pitch": 8}],
        "nets": [{"name": "GND", "pins": ["U1.GND", *[f"LED{i}.K" for i in range(1, 8)], "SW1.B"]},
                 {"pins": ["U1.D2", "R1.1"]},             # centre
                 {"pins": ["U1.D3", "R2.1", "R7.1"]},     # top-left and bottom-right
                 {"pins": ["U1.D10", "R3.1", "R6.1"]},    # top-right and bottom-left
                 {"pins": ["U1.RX", "R4.1", "R5.1"]},     # middle-left and middle-right
                 *[{"pins": [f"R{i}.2", f"LED{i}.A"]} for i in range(1, 8)],
                 {"pins": ["U1.D1", "SW1.A"]}],
    }


EXAMPLE = ("# Reference device (built: 0 DRC errors, intent met, 36 x 35 mm): a XIAO ESP32-C3 weather station. Learn the patterns;"
           " your device picks its own parts.\n```json\n" + json.dumps(EXAMPLE_DOC, ensure_ascii=False, separators=(",", ":")) + "\n```\n"
           "# A front panel (built: 0 DRC errors, intent met, 46 x 50 mm): an electronic dice. The layout puts the pips in the dice "
           "pattern above the module at the bottom edge, the button sits beside the module, pairs that always light together share a "
           "GPIO (each LED keeps its resistor), no LED or button is on a strapping pin, and the button is on D1 (GPIO3) so it can wake "
           "the module.\n```json\n" + json.dumps(_dice(), ensure_ascii=False, separators=(",", ":")) + "\n```")

CLASSIFY_HINT = ("device (a complete electronic device from a description: 'I need a weather station / plant watering controller / "
                 "a tracker / a macro keypad / a gadget that ...': real parts from the LCSC catalogue, a routed board, its 3D-printed "
                 "case and firmware, ready to order; also any request to build electronics without asking for a specific PCB file)")
