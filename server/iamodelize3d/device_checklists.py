"""Typical mistakes per part kind of a device (fw.device/1), for the designer to check its own design against: the device
reviewer of 2026-11-03 passed broken rounds at 8-9/10 (a 2-4 V buzzer on 5 V, a light sensor that switched its own light
off, an inverted LDR threshold) and raised false majors, while its real catches were requirements the firmware did not
do. So the designer reads these lists in its system prompt (all_text) and again at its first finish for the kinds its
graph has (for_kinds), and answers each kind before the finish is accepted (agent/device_tools.self_check).

Every item is one checkable line: what to look at on the graph, the board, the firmware or the case. [code] names the
check that already finds it (design rules: device_rules.py and device.lint; firmware: firmware_check.py; case: the
enclosure findings; requirement_*: the firmware's requirement checks), so the designer knows a clean result there covers
it; [you] means nothing checks it but the designer. Kinds are the section keys below: kinds_of() maps a graph's nodes to
them with the design rules' own notion of what a part is (device_rules._kind), so a chip with kind_hint 'nmos' is a
transistor here as it is there. 'case' and 'device' are always present.
"""
from __future__ import annotations

import re
from typing import Any

# key -> (what the section covers, [(item, the check that finds it or "" for the designer)])
SECTIONS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "mcu": ("module: XIAO ESP32-C3 / S3, Pico / Pico W", [
        ("Firmware pins by board name as wired (D0..D10, SDA, TX); C3 D6=TX=GPIO21 and D4=SDA=GPIO6, never D6 read as GPIO6",
         "pin_unwired, pin_conflict"),
        ("Strapping pins (C3 GPIO2/8/9 = D0/D8/D9; S3 GPIO0/3/45/46, D2=GPIO3): nothing pulls them low at reset (LED or button to GND)",
         "strapping_pin"),
        ("Analog only on ADC1: C3 D0-D2 (D3 is ADC2, dead with Wi-Fi); S3 every D pin but TX/RX; Pico GP26-28", "adc_pin"),
        ("A GPIO gives ~20 mA at most (an indicator LED 1-5 mA); buzzers, relays, motors, LED strings go through a transistor",
         "gpio_overload"),
        ("Pins are 3.3 V and not 5 V tolerant: a 5 V output or pull-up into a GPIO needs a divider or a level shifter",
         "pullup_5v (I2C only)"),
        ("V5 is USB's 5 V only: on a LiPo it is dead, so a battery device feeds its parts from V3V3", ""),
        ("Deep-sleep wake: C3 has no ext0/ext1, use esp_deep_sleep_enable_gpio_wakeup(1ULL<<n, ...) on GPIO0-5 (D0-D3); S3 ext0/ext1 "
         "on RTC GPIO0-21; timer: esp_sleep_enable_timer_wakeup(us)", "compile (ext0/ext1 on C3); the pin is yours"),
        ("A wake button keeps its pull-up in sleep: an external 10k to V3V3 is safest", ""),
        ("Outputs float until setup(): set every output off first; a MOSFET gate has 100k to GND", "mosfet_gate_floating"),
        ("arduino-esp32 3.x PWM: ledcAttach(pin, freq, bits) + ledcWrite(pin, duty); ledcSetup/ledcAttachPin are 2.x", "core_api"),
    ]),
    "led": ("LED primitive or chip LED", [
        ("A towards the GPIO or supply through its resistor, K towards GND or the driver", "led_reversed"),
        ("Resistor per colour: R = (V - Vf) / I; Vf red/yellow ~2.0 V, blue/white/true green ~3.0 V; from 3.3 V red 1k = 1.3 mA, "
         "330R = 4 mA; a white LED from 3.3 V is dim and uncertain (drive it from V5 through a transistor)", "led_current (too much); too dim is yours"),
        ("One resistor per LED, never one shared by parallel LEDs; more than one indicator per pin goes through a transistor",
         "led_resistor, gpio_overload"),
        ("Dimming and fades are PWM: ledcWrite on ESP32 (3.x), analogWrite on Pico, the duty stepped over time", "requirement_fade"),
        ("Seen through the lid: face light gets a light_window, not sealed under plastic", "light_window (case)"),
    ]),
    "rgb_led": ("addressable LED: WS2812B / SK6812", [
        ("On 5 V the data must reach 0.7 x VDD = 3.5 V: VDD through a diode, a level shifter, or a 3.3 V-rated part on V3V3",
         "ws2812_level"),
        ("330R in series with the first DIN at the LED; each DOUT to the next DIN; the last DOUT open", ""),
        ("100nF at each LED's VDD and 10uF+ on the chain", "ws2812_decoupling"),
        ("Up to ~60 mA per LED at full white: 8 LEDs ~0.5 A from V5/USB, not V3V3; cap the brightness in firmware", ""),
        ("Each LED idles at ~0.5-1 mA even when dark: on a battery switch their supply off or count it", ""),
        ("NEO_GRB + NEO_KHZ800 for WS2812B, show() after each change; setBrightness is lossy: fade by scaling the colours", ""),
    ]),
    "buzzer": ("buzzer (active or passive) or speaker", [
        ("Active buzzer sounds on DC (digitalWrite its driver); passive buzzer, piezo, speaker need tone() / ledcWriteTone, DC only "
         "clicks", ""),
        ("Rated voltage against its rail: a 2-4 V part never on 5 V, a 5 V part is weak on 3.3 V (part_info's range)", "supply_range"),
        ("Magnetic buzzers draw 20-40+ mA: low-side NPN or N-MOSFET, + to its rail, - to the collector or drain",
         "gpio_overload, buzzer_unwired"),
        ("Polarity: POS / + to the supply side, NEG / - to the switch", ""),
        ("A magnetic buzzer is a coil: a diode across it, K on its + side (a piezo needs none)", "flyback_diode, flyback_orientation"),
        ("A sound_grille over it in the lid", "sound_grille (case)"),
    ]),
    "transistor": ("NPN, PNP, N- or P-MOSFET", [
        ("Pinout from part_info (B/E/C, G/S/D); unnamed SOT-23 pins are only an assumption: check the datasheet",
         "bjt_reversed, mosfet_reversed, pinout_unknown"),
        ("NPN low side: E to GND, C to the load's -, 1k from the GPIO to B (2.6 mA base saturates ~50 mA; more: 470R or a MOSFET)",
         "bjt_base_resistor"),
        ("N-MOSFET: logic level, Rds(on) given at Vgs 2.5 V (AO3400, SI2302; 2N7002 only below ~100 mA); 100R to G, 100k G to GND",
         "mosfet_gate_floating; the part is yours"),
        ("High side: a PNP or P-MOSFET on a rail above 3.3 V needs an NPN in front (a GPIO cannot turn it off); an N-MOSFET "
         "belongs on the low side", "high_side_level, mosfet_high_side"),
        ("Current, voltage and SOT-23 heat (~0.25 W) above the load's, a motor's stall current included", ""),
        ("Firmware level as wired: HIGH turns NPN/N-MOSFET on, LOW turns PNP/P-MOSFET on", ""),
    ]),
    "diode": ("diode, Schottky, TVS / ESD", [
        ("Flyback across the coil, K on the + (supply) side, A on the transistor side; never from the switched side to GND",
         "flyback_orientation, diode_to_ground, floating_pin"),
        ("Supply OR-ing / back-feed: Schottky in series, A on the source, K on the rail; never straight across a rail and GND",
         "diode_across_rail"),
        ("Forward current and reverse voltage above the circuit's (B5819W: 1 A, 40 V)", ""),
        ("TVS / ESD from the line to GND at the connector, working voltage above the line's (5 V line: a 5 V TVS)", ""),
    ]),
    "resistor": ("resistor", [
        ("I2C pull-ups 4.7k to V3V3, one pair per bus (many display and sensor modules carry their own)", "pullup_5v (to 5 V)"),
        ("ADC divider keeps the tap under ~2.5 V on C3, ~3.1 V on S3; battery sense 2 x 220k from VBAT to an ADC1 pin with 100nF at the tap", ""),
        ("LDR / NTC with its fixed resistor: the sensor_divider warning says which way the reading moves", "sensor_divider"),
        ("Power P = V^2 / R under 0.1 W for 0603", ""),
    ]),
    "capacitor": ("capacitor", [
        ("100nF from each chip supply pin to GND, labelled with its chip; 10uF on regulator in/out, radios, LED chains",
         "decoupling, ws2812_decoupling"),
        ("Voltage rating at least 1.5-2 x its rail (ceramics lose capacity under DC bias)", ""),
        ("Polarised: pin 1 (+) on the higher net", ""),
        ("Bulk 100-470uF at servos, motors and LED strips on V5", ""),
    ]),
    "inductor": ("inductor", [
        ("Only with a switching regulator: value, saturation current above the peak, layout as its datasheet shows", ""),
    ]),
    "crystal": ("crystal", [
        ("Modules have their own crystal: none for them; a bare chip's load caps C = 2 x (CL - ~4 pF), e.g. CL 12.5 pF -> 18 pF",
         ""),
    ]),
    "regulator": ("voltage regulator", [
        ("Input range covers the source (LiPo 3.0-4.2 V, USB 4.5-5.5 V); a 3.3 V LDO from a LiPo drops out below ~3.5 V",
         "supply_range"),
        ("Its output feeds the rail; input and output capacitors as its datasheet says", "supply_no_source; the caps are yours"),
        ("Heat P = (Vin - Vout) x I: 5 V to 3.3 V at 200 mA is 0.34 W, the limit of a SOT-23", ""),
        ("EN tied (to VIN for always on), never floating; low quiescent current on a battery", ""),
        ("The module has a 3.3 V regulator: add one only for loads it cannot carry", ""),
    ]),
    "charger": ("LiPo charger IC", [
        ("A XIAO charges its BAT pads itself: no second charger", "battery_raw, battery_wiring"),
        ("PROG sets the current (TP4056 2k = 580 mA, 1.2k = 1 A; MCP73831 I = 1000 / R_kohm mA), at most 1C of the cell", ""),
        ("A protected cell or a DW01 + FS8205 pair; TP4056 TEMP to GND without an NTC", ""),
    ]),
    "sensor": ("sensor chip or board-mounted sensor module", [
        ("Supply range against its rail (most I2C sensors 1.7-3.6 V: V3V3)", "supply_range, accessory_supply"),
        ("Config pins tied (BME280 CSB to V3V3 = I2C, SDO to GND = 0x76); no two parts with one address on a bus", ""),
        ("It sees what it measures: a sensor_window for light, PIR and gas; air sensors vented and away from the module and "
         "regulator heat", "sensor_window (case); placement is yours"),
        ("A light sensor sees the device's own light: decide dark only while the lights are off, with hysteresis", ""),
        ("Thresholds follow the divider's direction (the sensor_divider warning) and its units", "sensor_divider"),
        ("Analog output on an ADC1 pin", "adc_pin"),
        ("Firmware checks begin(), falls back when it is missing, reads no faster than the datasheet allows", ""),
        ("Open-drain or interrupt outputs have a pull-up", ""),
    ]),
    "pir": ("PIR motion module: HC-SR501, AM312", [
        ("HC-SR501 needs 5 V (4.5-20 V): V5, so dead on a battery; AM312 runs on V3V3 (2.7-12 V)", "accessory_supply"),
        ("Warm-up: ignore its output for ~30-60 s after power-up", ""),
        ("OUT stays high for its hold time (HC-SR501 trimmer, jumper H retriggers; AM312 ~2 s): the firmware restarts its own "
         "timer on every HIGH", ""),
        ("The dome through a round lid hole, away from the module's antenna (Wi-Fi falsely triggers it)", "sensor_window (case)"),
        ("As a wake source: OUT on a wake-capable pin, wake on HIGH", ""),
    ]),
    "display": ("display (OLED module or chip)", [
        ("A display_window in the lid over its active area", "display_window (case)"),
        ("Controller and address: 0.96\" SSD1306, 1.3\" SH1106 (Adafruit_SH110X or U8g2), 0x3C (0x3D when re-jumpered)", ""),
        ("Text in English, or U8g2 with a _t_cyrillic font and enableUTF8Print: default fonts are ASCII", "display_charset"),
        ("Wired by the accessory's pin names (GND VCC SCL SDA; some modules swap VCC and GND)", ""),
        ("Display off before deep sleep (SSD1306_DISPLAYOFF / setPowerSave(1)), or it stays lit and drains the cell", ""),
    ]),
    "connector": ("header, JST, USB-C, connector", [
        ("A USB-C receptacle for power: CC1 and CC2 each 5.1k to GND", "usb_cc"),
        ("JST PH P1 = +, P2 = -; cheap leads swap red and black: say which in the summary", ""),
        ("Header pin order matches what plugs into it", ""),
        ("Every external connector gets a wall opening or a cable_exit; one plugged inside takes face none", "cable_exit (case)"),
        ("Nothing the request does not need; an external power input has reverse and ESD protection", ""),
    ]),
    "switch": ("button or switch", [
        ("A to a GPIO with INPUT_PULLUP, B to GND: LOW when pressed", "gpio_short"),
        ("Debounced (20-50 ms with millis), acts on the press edge, not on the held level", ""),
        ("Not on a strapping pin (C3 D0/D8/D9, S3 D2)", "strapping_pin"),
        ("A wake button on a wake-capable pin (C3 D1-D3; S3 any D pin but TX/RX)", ""),
        ("Pressed through the lid: placed under it where the case gives a press tab", "button_unreachable, button_reach (case)"),
        ("The right switch for how it is used: pressed all day (keys, a game pad) a mechanical one (switch: mx or choc), at its pitch, its plate free of parts", "key_plate (case)"),
    ]),
    "fuse": ("fuse", [
        ("Hold current above the normal draw, trips below what the source and traces stand", ""),
    ]),
    "motor": ("motor, relay, servo", [
        ("Driver rated for the stall / inrush current (2-5 x running)", "gpio_overload (no driver)"),
        ("A diode across a motor or relay coil, K on +", "flyback_diode, flyback_orientation"),
        ("Supply from V5 or its own source, never V3V3; 100-470uF bulk at it; V5 is dead on a battery", "accessory_supply"),
        ("Relay module: active-low IN? 3.3 V-compatible input; servos via ESP32Servo", ""),
        ("A cable_exit for whatever sits off the board", "cable_exit (case)"),
    ]),
    "ic": ("other chip", [
        ("Each supply pin decoupled at the pin", "decoupling"),
        ("Supply range against its rail", "supply_range"),
        ("Enable, reset and config pins tied as the datasheet says, never floating; exposed pad to GND when it says", ""),
        ("3.3 V logic levels; open-drain outputs pulled up", ""),
    ]),
    "battery": ("LiPo cell", [
        ("On a XIAO: the LiPo accessory with connect module_bat on the BAT pads; never on V5 or V3V3", "battery_raw, battery_wiring"),
        ("On a Pico: a charger IC and a Schottky into VSYS", "battery_raw"),
        ("The firmware really sleeps (esp_deep_sleep_start reached, not commented out) and wakes on its button, sensor or timer",
         "requirement_sleep"),
        ("Battery life from the duty cycle: hours = mAh / average mA, counting always-on drains (OLED, WS2812 idle, PIR, dividers)",
         ""),
        ("Battery voltage needs a divider to an ADC1 pin: the XIAO has none built in", ""),
        ("Room for the cell in the case", "battery_space (case)"),
    ]),
    "probe": ("probe on a cable: soil, DS18B20, leak", [
        ("A cable_exit sized for the lead or its plug", "cable_exit (case)"),
        ("Capacitive soil probe: AOUT on an ADC1 pin, lower when wet, dry/wet calibration constants", "adc_pin; direction is yours"),
        ("Leak contacts: SENSE with a pull-up (INPUT_PULLUP or 100k), LOW when wet; pulse the sense to limit electrolysis", ""),
        ("DS18B20: 4.7k from DQ to V3V3; -127 means not found, 85 a read at power-up", ""),
        ("A long lead into a GPIO: 100R-1k in series against ESD", ""),
    ]),
    "case": ("case (always)", [
        ("Every face part has its opening: light_window, sound_grille, sensor_window, display_window", "finish gate (openings)"),
        ("Every cable accessory a cable_exit, the USB-C a port, the cell its battery_space", "finish gate (openings)"),
        ("Light leaking inside the case reaches a light sensor: keep it apart from the LEDs", ""),
    ]),
    "device": ("device-level (always)", [
        ("Every requirement with firmware: true is done in code, not commented out, not a TODO, not behind #if 0: name file:line",
         "requirement_sleep, requirement_fade, requirement_pins; the rest is yours"),
        ("Sleep requested: the wake source is enabled, outputs off, then esp_deep_sleep_start() really runs", "requirement_sleep"),
        ("A fade requested: the duty or brightness steps over time", "requirement_fade"),
        ("Every firmware pin is the graph's pin, every wired part is used", "pin_unwired, pin_unused, pin_conflict"),
        ("Thresholds agree with the sensors' direction and units, with hysteresis", ""),
        ("A missing sensor or Wi-Fi never stops the device (timeouts, fallbacks); no long delay() under buttons or a web page",
         "blocking_delay (web only)"),
        ("Every summary claim is true (parts, LCSC numbers, pins, sizes, price, computed battery hours), nothing the code lacks", ""),
        ("Everything the request names is in the device, in its own terms (a wireless dongle, a frequency sweep, a kind of connector); what was left out or "
         "replaced was asked about, or is said first in the summary in plain words", ""),
        ("Each of the concept's uses is served: where it lives, how it is seen, heard and touched there, how it is powered", ""),
        ("What was built is the chosen concept: board shape and size, the module's edge, the panel as placed, the case's form, "
         "stance and mounting", "concept warnings of the build and the case; the panel is yours"),
    ]),
}
ALWAYS = ("case", "device")
VERDICTS = ("ok", "fixed", "n/a")

# the design rules' kind of a part -> its section
_SECTION_OF = {
    "npn": "transistor", "pnp": "transistor", "nmos": "transistor", "pmos": "transistor", "transistor": "transistor",
    "diode": "diode", "tvs": "diode", "led": "led", "rgb_led": "rgb_led",
    "buzzer": "buzzer", "buzzer_active": "buzzer", "buzzer_passive": "buzzer", "speaker": "buzzer",
    "sensor": "sensor", "display": "display", "mcu": "ic", "regulator": "regulator", "charger": "charger",
    "resistor": "resistor", "capacitor": "capacitor", "inductor": "inductor", "crystal": "crystal", "connector": "connector",
    "switch": "switch", "fuse": "fuse", "motor": "motor", "relay": "motor", "ic": "ic",
    # the graph's own primitives
    "module": "mcu", "button": "switch", "header": "connector", "jst": "connector", "usb_c": "connector",
}
PIR = re.compile(r"pir|motion|sr501|am312|sr602", re.I)
COIL = re.compile(r"servo|relay|motor", re.I)


def _item_id(key: str, i: int) -> str:
    return f"{key}.{i + 1}"


def _yours(rule: str) -> bool:
    return not rule or "yours" in rule or "(if fitted)" in rule


def _section(key: str, only_yours: bool = False) -> str:
    title, items = SECTIONS[key]
    lines = [f"## {key}: {title}"]
    for i, (text, rule) in enumerate(items):
        if not only_yours or _yours(rule):
            lines.append(f"- {_item_id(key, i)} {text} [{rule or 'you'}]")
    return "\n".join(lines)


def ordered(kinds: Any) -> list[str]:
    """The known kinds among `kinds`, in the checklist's order."""
    want = {str(k) for k in kinds or ()}
    return [k for k in SECTIONS if k in want]


def for_kinds(kinds: Any, only_yours: bool = False) -> str:
    """The checklist sections of these kinds (section keys, see kinds_of), in the checklist's order; only_yours keeps the
    items no rule checks (a clean result covers the others), for a device with many kinds."""
    return "\n".join(_section(k, only_yours) for k in ordered(kinds))


HEADER = ("# Self-check: typical mistakes per part kind\n"
          "Check your design against these on the graph, board, firmware and case. [code]: that rule or check finds it (clean = "
          "covered); [you]: only you check it. finish returns the items for your graph's kinds: answer each kind there.")


def all_text() -> str:
    """Every section, for the designer's system prompt."""
    return HEADER + "\n" + for_kinds(SECTIONS)


def _accessory_kind(node: dict[str, Any]) -> str | None:
    try:
        from . import accessories

        a = accessories.ACCESSORIES.get(str(node.get("accessory") or "")) or {}
    except Exception:  # noqa: BLE001 - the library is optional here
        a = {}
    key = f"{node.get('accessory') or ''} {a.get('name') or ''}"
    kind = a.get("kind")
    if kind == "sensor" and PIR.search(key):
        return "pir"
    if kind in ("display", "battery", "probe", "sensor"):
        return str(kind)
    if COIL.search(key):
        return "motor"
    return "ic" if a else None


def _part_kind(node: dict[str, Any], part: dict[str, Any]) -> str:
    """What the design rules call this node (device_rules._kind: its kind, a chip's kind_hint, its card, its label)."""
    try:
        from .device_rules import _kind

        return _kind(node, part)
    except Exception:  # noqa: BLE001 - without the rules: the catalogue's own word, else the node's kind
        if node.get("kind") == "chip":
            from . import catalog

            return str(part.get("kind_hint") or (catalog.kind_of(part) if part else "ic"))
        return str(node.get("kind") or "")


def kinds_of(doc: dict[str, Any], parts: dict[str, dict[str, Any]] | None = None) -> set[str]:
    """The checklist kinds a device has: one per section its nodes fall into (parts = device.resolve(doc)[0], for the
    chips' kinds), plus 'case' and 'device'."""
    out = set(ALWAYS)
    parts = parts if isinstance(parts, dict) else {}
    for n in (doc or {}).get("nodes") or []:
        if not isinstance(n, dict):
            continue
        if n.get("kind") == "accessory":
            k = _accessory_kind(n)
        else:
            k = _SECTION_OF.get(_part_kind(n, parts.get(str(n.get("id"))) or {}))
            if n.get("kind") == "chip" and k == "sensor" and PIR.search(f"{n.get('label') or ''} {(parts.get(str(n.get('id'))) or {}).get('mpn') or ''}"):
                k = "pir"
        if k:
            out.add(k)
    return out


def coverage(checked: Any, kinds: Any) -> tuple[list[str], list[str]]:
    """(kinds the `checked` answers do not cover, answers that are not usable): an answer covers its `kind`, or the kind of
    its `item` ('led.2', or text starting with the kind), when its verdict is ok, fixed or n/a."""
    bad: list[str] = []
    covered: set[str] = set()
    for i, c in enumerate(checked if isinstance(checked, list) else []):
        if not isinstance(c, dict):
            bad.append(f"checked[{i}] is not an object")
            continue
        verdict = str(c.get("verdict") or "").strip().lower()
        if verdict not in VERDICTS:
            bad.append(f"checked[{i}] verdict {verdict or 'missing'!r}: ok, fixed or n/a (fix a problem first, then say fixed)")
            continue
        for v in (c.get("kind"), c.get("item")):
            m = re.match(r"\s*([a-z_]+)", str(v or "").lower())
            if m and m.group(1) in SECTIONS:
                covered.add(m.group(1))
    return [k for k in ordered(kinds) if k not in covered], bad
