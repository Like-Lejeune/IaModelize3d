"""Ready-made modules a device uses but the fab does not solder (fw.device/1 node kind 'accessory', contract C1d).

An OLED module, a soil probe on a cable, a LiPo cell: bought finished and fitted by hand at the workshop. The device
compiler puts only their connector on the carrier board (a 2.54 mm header with the accessory's pins in header order,
a JST PH for connect 'jst', nothing for 'module_bat': a LiPo's leads go to the XIAO's BAT pads under the module, whose
own charger handles it), wires '<id>.<pin>' nets to it, and lists the accessory as a priced, hand-fitted line of the
quote. deviceapi.build_device writes where each one sits into board.json `accessories` (contract C2b), so the case cuts
a display window, holds the module, gives a cable its exit or a cell its room.

Entry fields (mm, at rotation 0 the module's header row runs along x at the +y side of its body unless header_axis/
header_offset say otherwise):
  name, kind ('display'|'sensor'|'probe'|'battery'|'module'), price_usd (one unit, AliExpress/LCSC typical, 2026-11),
  pins [labels in header order], connect ('header'|'jst'|'wires'|'module_bat'), mount ('board': sits on the carrier
  over its connector; 'cable': off the board on a lead; 'inside': loose in the case), body [w, d, h],
  stack_h (board mounts: bottom of the module's PCB above the carrier's top face), header_offset [dx, dy] (the header
  row's centre from the body centre), header_axis ('x'|'y'), window [w, d] and window_offset [dx, dy] (what must be seen
  through the lid, from the body centre), window_shape ('rect'|'round'), holes [[dx, dy, d]] (its mounting holes),
  cable_d (the wall exit its lead needs: the cable, or the plug on its end when that must pass), supply ('3V3'|'5V'|
  '3V3-5V'), current_ma, capacity_mah (a cell), sim (its signal for firmware_sim: {type: 'analog'|'digital', pin, rest_mv,
  active_mv, ohm} or {type: 'contact', pin, to, ohm}), url, note.
Dimensions are the common Chinese module drawings; the ones a case depends on carry verify in their note.
"""
from __future__ import annotations

import re
from typing import Any

ACCESSORIES: dict[str, dict[str, Any]] = {
    "oled_096_i2c": {
        "name": "0.96\" OLED 128x64 I2C (SSD1306)", "kind": "display", "price_usd": 2.5,
        "pins": ["GND", "VCC", "SCL", "SDA"], "connect": "header", "mount": "board",
        "body": [27.3, 27.8, 3.0], "stack_h": 2.5, "header_offset": [0.0, 12.4], "header_axis": "x",
        "window": [21.74, 10.86], "window_offset": [0.0, -1.6], "window_shape": "rect",
        "holes": [[-11.65, 11.9, 2.0], [11.65, 11.9, 2.0], [-11.65, -11.9, 2.0], [11.65, -11.9, 2.0]],
        "supply": "3V3-5V", "current_ma": 20, "i2c_addr": "0x3C",
        "url": "https://www.lcsc.com/search?q=SSD1306%200.96",
        "note": "4-pin I2C SSD1306 module; check the pin order printed on yours (some are VCC GND SCL SDA). Soldered on its own "
                "male header 2.5 mm above the carrier, glass up. Address 0x3C. Adafruit_SSD1306 or U8g2; the default GFX font is "
                "ASCII only (Cyrillic needs a U8g2 font such as u8g2_font_6x13_t_cyrillic). Window offset: verify on the module.",
    },
    "oled_13_i2c": {
        "name": "1.3\" OLED 128x64 I2C (SH1106)", "kind": "display", "price_usd": 4.0,
        "pins": ["GND", "VCC", "SCL", "SDA"], "connect": "header", "mount": "board",
        "body": [35.4, 33.5, 3.2], "stack_h": 2.5, "header_offset": [0.0, 15.2], "header_axis": "x",
        "window": [29.42, 14.7], "window_offset": [0.0, -1.5], "window_shape": "rect",
        "holes": [[-15.2, 14.25, 3.0], [15.2, 14.25, 3.0], [-15.2, -14.25, 3.0], [15.2, -14.25, 3.0]],
        "supply": "3V3-5V", "current_ma": 25, "i2c_addr": "0x3C",
        "url": "https://www.lcsc.com/search?q=SH1106%201.3",
        "note": "SH1106 controller, not SSD1306: use Adafruit_SH110X or U8g2's SH1106 driver. Address 0x3C. Window offset: verify.",
    },
    "oled_091_i2c": {
        "name": "0.91\" OLED 128x32 I2C (SSD1306)", "kind": "display", "price_usd": 1.8,
        "pins": ["GND", "VCC", "SCL", "SDA"], "connect": "header", "mount": "board",
        "body": [38.0, 12.0, 2.6], "stack_h": 2.5, "header_offset": [-17.5, 0.0], "header_axis": "y",
        "window": [22.38, 5.58], "window_offset": [2.0, 0.0], "window_shape": "rect", "holes": [],
        "supply": "3V3-5V", "current_ma": 15, "i2c_addr": "0x3C",
        "url": "https://www.lcsc.com/search?q=SSD1306%200.91",
        "note": "4 pins on its short end; no mounting holes, the case holds it by its edges. 128x32: Adafruit_SSD1306(128, 32). "
                "Address 0x3C.",
    },
    "soil_capacitive_v12": {
        "name": "Capacitive soil moisture sensor v1.2", "kind": "probe", "price_usd": 1.5,
        "pins": ["GND", "VCC", "AOUT"], "connect": "header", "mount": "cable",
        "body": [98.0, 23.0, 4.0], "cable_d": 5.0, "supply": "3V3-5V", "current_ma": 5,
        "sim": {"type": "analog", "pin": "AOUT", "rest_mv": 1200, "active_mv": 2500, "ohm": 10000},
        "url": "https://www.lcsc.com/search?q=capacitive%20soil%20moisture",
        "note": "Analog out, lower when wet (about 1.2 V wet to 2.5 V dry at 3.3 V): wire AOUT to an ADC pin (XIAO ESP32-C3: D0-D2; "
                "S3: D0-D3) and calibrate dry/wet in the firmware. Comes with a 3-wire lead to single Dupont plugs: they pass "
                "a 5 mm exit one at a time.",
    },
    "ds18b20_probe": {
        "name": "DS18B20 waterproof temperature probe", "kind": "probe", "price_usd": 1.6,
        "pins": ["GND", "DQ", "VCC"], "connect": "header", "mount": "cable",
        "body": [6.0, 6.0, 50.0], "cable_d": 4.0, "supply": "3V3-5V", "current_ma": 2,
        "url": "https://www.lcsc.com/search?q=DS18B20",
        "note": "1-Wire: DQ needs a 4.7k pull-up to VCC on the carrier (a resistor from the DQ net to V3V3). Leads: red VCC, "
                "black GND, yellow DQ, bare tinned ends (crimped inside the case). OneWire + DallasTemperature libraries.",
    },
    "leak_probe": {
        "name": "Water leak probe (two stainless contacts on a 2-wire lead)", "kind": "probe", "price_usd": 1.0,
        "pins": ["SENSE", "GND"], "connect": "header", "mount": "cable",
        "body": [30.0, 15.0, 5.0], "cable_d": 3.0, "supply": "3V3", "current_ma": 1, "sim": {"type": "contact", "pin": "SENSE", "to": "GND", "ohm": 20000},
        "note": "Water bridges the two contacts: SENSE to a GPIO with a pull-up (100k to V3V3, or INPUT_PULLUP), reads LOW when wet. "
                "Lay it flat on the floor, contacts down.",
    },
    "lipo_1s_500": {
        "name": "LiPo cell 3.7 V 500 mAh (602030)", "kind": "battery", "price_usd": 3.0,
        "pins": ["VBAT", "GND"], "connect": "module_bat", "mount": "inside",
        "body": [30.0, 20.0, 6.0], "supply": "3V3", "current_ma": 0, "capacity_mah": 500,
        "note": "Soldered to the XIAO's BAT+ and BAT- pads under the module: the XIAO charges it from USB-C. Never wire a cell to V5 "
                "or 3V3 (USB would push 5 V into it). Protected cell with its own PCM.",
    },
    "lipo_1s_1000": {
        "name": "LiPo cell 3.7 V 1000 mAh (603450)", "kind": "battery", "price_usd": 5.0,
        "pins": ["VBAT", "GND"], "connect": "module_bat", "mount": "inside",
        "body": [50.0, 34.0, 6.0], "supply": "3V3", "current_ma": 0, "capacity_mah": 1000,
        "note": "As the 500 mAh cell: on the XIAO's BAT pads, charged by the XIAO (about 100 mA, so 10 h from empty).",
    },
    "servo_sg90": {
        "name": "SG90 micro servo", "kind": "module", "price_usd": 1.8,
        "pins": ["GND", "VCC", "SIG"], "connect": "header", "mount": "cable",
        "body": [23.0, 12.2, 29.0], "cable_d": 8.0, "supply": "5V", "current_ma": 250,
        "note": "Power from 5 V (V5/VBUS), up to 650 mA when stalled: a 100-470 uF bulk capacitor on V5 near its header. The 3.3 V "
                "signal drives it. Leads: brown GND, red VCC, orange SIG in one 3-pin plug "
                "(7.6 x 2.6 mm): the exit is 8 mm so the plug passes. ESP32Servo library.",
    },
    "hc_sr501_pir": {
        "name": "HC-SR501 PIR motion module", "kind": "sensor", "price_usd": 1.2,
        "pins": ["VCC", "OUT", "GND"], "connect": "header", "mount": "board",
        "body": [32.2, 24.3, 1.6], "stack_h": 8.5, "header_offset": [0.0, 0.0], "header_axis": "x",
        "window": [23.2, 23.2], "window_offset": [0.0, 0.0], "window_shape": "round",
        "holes": [[-14.5, 0.0, 2.0], [14.5, 0.0, 2.0]],
        "supply": "5V", "current_ma": 1, "sim": {"type": "digital", "pin": "OUT", "rest_mv": 0, "active_mv": 3300},
        "note": "Plugged dome up into a 3-pin socket (8.5 mm) on the carrier: its trimmers and BISS0001 hang underneath. The 23 mm "
                "Fresnel dome (12 mm tall) comes through a round hole in the lid. VCC 5 V (4.5-20 V), OUT is 3.3 V high on motion: "
                "straight to a GPIO. Trimmers set range and hold time; jumper H for retrigger.",
    },
    "relay_1ch_5v": {
        "name": "1-channel 5 V relay module (SRD-05VDC)", "kind": "module", "price_usd": 1.2,
        "pins": ["VCC", "GND", "IN"], "connect": "header", "mount": "cable",
        "body": [50.0, 26.0, 18.5], "cable_d": 5.0, "supply": "5V", "current_ma": 75,
        "note": "Coil from 5 V (about 75 mA). IN from a 3.3 V GPIO: pick a module with an optocoupler or transistor input that "
                "switches at 3.3 V (most are active LOW). Single Dupont leads (5 mm exit). Mains wiring stays outside this case.",
    },
}

KINDS = ("display", "sensor", "probe", "battery", "module")
CONNECTS = ("header", "jst", "wires", "module_bat")
MOUNTS = ("board", "cable", "inside")


def get(key: str) -> dict[str, Any] | None:
    return ACCESSORIES.get(str(key or "").strip().lower())


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9.]+", text.lower().replace('"', " ")) if t and t != "."}


def find(name: str) -> str | None:
    """The key of an accessory named loosely ('ssd1306 oled', 'OLED 0.96', 'DS18B20'), or None. Whole words only: 'LED'
    is no OLED, and at least half the words must be the accessory's."""
    q = str(name or "").strip().lower()
    if not q:
        return None
    if q in ACCESSORIES:
        return q
    words = _tokens(q)
    best, score = None, 0
    for k, a in ACCESSORIES.items():
        s = len(words & (_tokens(k.replace("_", " ")) | _tokens(a["name"])))
        if s > score:
            best, score = k, s
    return best if score and score * 2 >= len(words) else None


def catalogue() -> list[dict[str, Any]]:
    """What the designer and the node editor's palette see: every accessory with its pins and what it needs."""
    keep = ("name", "kind", "price_usd", "pins", "connect", "mount", "body", "supply", "current_ma", "cable_d", "window", "url", "note")
    return [{"key": k, **{f: a[f] for f in keep if a.get(f) is not None}} for k, a in ACCESSORIES.items()]
