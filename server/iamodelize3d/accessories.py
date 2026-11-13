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
        "sim": {"type": "bus", "channel": 1, "rest": 25.0, "values": [10.0, 40.0]},
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
                "switches at 3.3 V (most are active LOW). Single Dupont leads (5 mm exit). Rated 10 A at 250 V: a load above 2 kW takes a contactor. "
                "Mains wiring stays outside this case.",
    },
    # displays beyond the OLEDs: SPI, on the board behind a window. Bodies from the usual module drawings: verify on the module
    "epaper_213": {
        "name": "2.13\" e-paper 250x122 SPI (SSD1680)", "kind": "display", "price_usd": 7.5,
        "pins": ["VCC", "GND", "SDI", "SCK", "CS", "DC", "RES", "BUSY"], "connect": "header", "mount": "board",
        "body": [59.2, 29.2, 3.0], "stack_h": 2.5, "header_offset": [-27.3, 0.0], "header_axis": "y",
        "window": [48.6, 23.8], "window_offset": [2.0, 0.0], "window_shape": "rect", "supply": "3V3", "current_ma": 8, "keeps_image": True,
        "note": "Keeps its picture with no power: right for what changes rarely on a battery. GxEPD2 library, full refresh about 2 s. Window offset: verify.",
    },
    "epaper_29": {
        "name": "2.9\" e-paper 296x128 SPI (SSD1680)", "kind": "display", "price_usd": 10.0,
        "pins": ["VCC", "GND", "SDI", "SCK", "CS", "DC", "RES", "BUSY"], "connect": "header", "mount": "board",
        "body": [79.0, 36.7, 3.0], "stack_h": 2.5, "header_offset": [-37.0, 0.0], "header_axis": "y",
        "window": [66.9, 29.1], "window_offset": [2.5, 0.0], "window_shape": "rect", "supply": "3V3", "current_ma": 8, "keeps_image": True,
        "note": "As the 2.13 inch one. GxEPD2 library, full refresh about 2 s. Window offset: verify.",
    },
    "tft_13_st7789": {
        "name": "1.3\" colour IPS TFT 240x240 SPI (ST7789)", "kind": "display", "price_usd": 3.2,
        "pins": ["GND", "VCC", "SCL", "SDA", "RES", "DC", "BLK"], "connect": "header", "mount": "board",
        "body": [27.8, 39.0, 3.2], "stack_h": 2.5, "header_offset": [0.0, 17.6], "header_axis": "x",
        "window": [23.4, 23.4], "window_offset": [0.0, -2.0], "window_shape": "rect", "supply": "3V3", "current_ma": 40,
        "note": "SPI despite the pin names (no CS on this one). Adafruit_ST7789 or TFT_eSPI. Window offset: verify.",
    },
    "tft_24_ili9341": {
        "name": "2.4\" colour TFT 320x240 SPI (ILI9341)", "kind": "display", "price_usd": 5.0,
        "pins": ["VCC", "GND", "CS", "RESET", "DC", "SDI", "SCK", "LED", "SDO"], "connect": "header", "mount": "board",
        "body": [42.7, 77.0, 4.0], "stack_h": 2.5, "header_offset": [0.0, 35.5], "header_axis": "x",
        "window": [37.0, 49.0], "window_offset": [0.0, -3.0], "window_shape": "rect", "supply": "3V3-5V", "current_ma": 80,
        "note": "Adafruit_ILI9341 or TFT_eSPI. Window offset: verify.",
    },
    # sound and storage
    "speaker_max98357": {
        "name": "I2S class-D amplifier MAX98357A with a 3 W 40 mm speaker", "kind": "module", "price_usd": 4.0,
        "pins": ["LRC", "BCLK", "DIN", "GND", "VIN"], "connect": "header", "mount": "inside",
        "body": [40.0, 40.0, 20.0], "supply": "3V3-5V", "current_ma": 600,
        "note": "Real sound where a piezo only beeps: I2S from the ESP32-S3 or C3 (ESP8266Audio or the I2S driver). VIN from 5 V for full power. Speaker sits in the case: a sound hole is yours to ask for.",
    },
    "dfplayer_mini": {
        "name": "DFPlayer Mini MP3 module with a 3 W speaker and microSD", "kind": "module", "price_usd": 3.5,
        "pins": ["VCC", "RX", "TX", "GND"], "connect": "header", "mount": "inside",
        "body": [40.0, 40.0, 20.0], "supply": "5V", "current_ma": 200,
        "sim": {"type": "bus"},
        "note": "Plays MP3 files from its card, driven over serial (DFRobotDFPlayerMini library): 1k in series with RX. For sound effects and voices.",
    },
    "microsd_spi": {
        "name": "microSD card module, SPI", "kind": "module", "price_usd": 1.0,
        "pins": ["CS", "SCK", "MOSI", "MISO", "VCC", "GND"], "connect": "header", "mount": "cable",
        "body": [42.0, 24.0, 4.0], "cable_d": 5.0, "supply": "3V3", "current_ma": 100,
        "sim": {"type": "bus"},
        "note": "Logging and recordings (SD library). The card slot must be reached: it goes on a short lead at a slot in the wall.",
    },
    "mic_inmp441": {
        "name": "INMP441 I2S MEMS microphone module", "kind": "sensor", "price_usd": 2.0,
        "pins": ["VDD", "GND", "SD", "WS", "SCK", "LR"], "connect": "header", "mount": "cable",
        "body": [14.0, 14.0, 3.0], "cable_d": 4.0, "supply": "3V3", "current_ma": 2,
        "note": "Digital microphone for sound levels and FFT over I2S; tie LR to GND. Faces a hole in the wall on its lead.",
    },
    # clocks, identity, position, radio
    "rtc_ds3231": {
        "name": "DS3231 real-time clock module with a coin cell", "kind": "module", "price_usd": 1.8,
        "pins": ["GND", "VCC", "SDA", "SCL"], "connect": "header", "mount": "cable",
        "body": [38.0, 22.0, 14.0], "cable_d": 5.0, "supply": "3V3-5V", "current_ma": 1, "i2c_addr": "0x68",
        "sim": {"type": "bus"},
        "note": "Keeps time through a power cut, within seconds a month: for alarms and schedules without Wi-Fi. RTClib. Lives inside the case on its lead.",
    },
    "rfid_rc522": {
        "name": "RC522 13.56 MHz RFID reader", "kind": "module", "price_usd": 1.6,
        "pins": ["SDA", "SCK", "MOSI", "MISO", "IRQ", "GND", "RST", "VCC"], "connect": "header", "mount": "cable",
        "body": [60.0, 40.0, 5.0], "cable_d": 5.0, "supply": "3V3", "current_ma": 30,
        "sim": {"type": "bus", "channel": 6, "event": True, "hold": 1.0},
        "note": "SPI (SDA is its CS): MFRC522 library. Reads through up to about 3 mm of plastic, so it lies flat against a wall of the case.",
    },
    "gps_neo6m": {
        "name": "NEO-6M GPS module with a ceramic antenna", "kind": "module", "price_usd": 4.5,
        "pins": ["VCC", "RX", "TX", "GND"], "connect": "header", "mount": "cable",
        "body": [36.0, 25.0, 12.0], "cable_d": 5.0, "supply": "3V3-5V", "current_ma": 50,
        "sim": {"type": "bus", "channel": 7, "rest": 1.0, "values": [0.0, 1.0]},
        "note": "Position over serial at 9600 baud (TinyGPSPlus). The antenna needs the sky: no metal over it. First fix a minute or more.",
    },
    "lora_ra02": {
        "name": "LoRa radio SX1278 (Ra-02) with an antenna on a lead", "kind": "module", "price_usd": 4.0,
        "pins": ["VCC", "GND", "SCK", "MISO", "MOSI", "NSS", "RST", "DIO0"], "connect": "header", "mount": "cable",
        "body": [17.0, 16.0, 3.5], "cable_d": 6.0, "supply": "3V3", "current_ma": 120,
        "sim": {"type": "bus", "channel": 8, "event": True, "hold": 1.0},
        "note": "Kilometres at low speed (LoRa library). Transmitting without the antenna kills it; its frequency must be legal where it is used. An answer from rescuers takes a receiver: it is no satellite beacon.",
    },
    # moving things: the module and its motor on a cable; the mechanics around them are the person's
    "stepper_tmc2209": {
        "name": "TMC2209 stepper driver with a NEMA 17 motor", "kind": "module", "price_usd": 14.0,
        "pins": ["EN", "STEP", "DIR", "VM", "GND", "VIO"], "connect": "header", "mount": "cable",
        "body": [42.3, 42.3, 40.0], "cable_d": 8.0, "supply": "3V3", "current_ma": 5,
        "sim": {"type": "bus"},
        "note": "Quiet stepping at up to about 1.7 A a phase: VM 12-24 V from its own supply on a terminal, with 100 uF across it at the driver; VIO on 3.3 V. Never unplug the motor under power. Motor mount and rails are not in the case.",
    },
    "dc_driver_drv8871": {
        "name": "DRV8871 DC motor driver module", "kind": "module", "price_usd": 4.0,
        "pins": ["IN1", "IN2", "VM", "GND"], "connect": "header", "mount": "cable",
        "body": [25.0, 20.0, 8.0], "cable_d": 6.0, "supply": "3V3", "current_ma": 10,
        "note": "One small brushed motor both ways, up to 3.6 A at 6.5-45 V, current limited: VM from its own supply on a terminal. No brushless or hub motor, no regeneration. Motor and gearbox are the person's.",
    },
    "pump_12v": {
        "name": "12 V mini diaphragm water pump", "kind": "module", "price_usd": 4.5,
        "pins": ["P", "N"], "connect": "header", "mount": "cable",
        "body": [40.0, 28.0, 60.0], "cable_d": 5.0, "supply": "12V", "current_ma": 500,
        "note": "Low-side MOSFET with a flyback diode, on a 12 V supply: state 1 A on its net. Never runs dry for long: a level or flow check belongs in the firmware.",
    },
    "solenoid_lock_12v": {
        "name": "12 V solenoid door latch", "kind": "module", "price_usd": 5.0,
        "pins": ["P", "N"], "connect": "header", "mount": "cable",
        "body": [54.0, 41.0, 28.0], "cable_d": 5.0, "supply": "12V", "current_ma": 800,
        "note": "Low-side MOSFET with a flyback diode, on a 12 V supply (1 A on its net), energised only for seconds: it overheats if held. Fitting it to a door is the person's.",
    },
    # weight and current without touching mains
    "loadcell_hx711": {
        "name": "HX711 board with a 1 kg bar load cell", "kind": "sensor", "price_usd": 3.0,
        "pins": ["VCC", "SCK", "DT", "GND"], "connect": "header", "mount": "cable",
        "body": [80.0, 13.0, 13.0], "cable_d": 5.0, "supply": "3V3-5V", "current_ma": 2,
        "sim": {"type": "bus", "channel": 4, "rest": 0.0, "values": [0.0, 500.0]},
        "note": "HX711 library; calibrate with a known weight. The bar must be bolted at one end and loaded at the other: the case does not make that yet, so say so.",
    },
    "ct_sct013": {
        "name": "SCT-013 clamp-on current transformer (non-invasive, on a lead)", "kind": "probe", "price_usd": 5.0,
        "pins": ["S", "GND"], "connect": "header", "mount": "cable",
        "body": [30.0, 30.0, 25.0], "cable_d": 4.0, "supply": "3V3", "current_ma": 0,
        "note": "Measures a mains wire from outside it, so nothing live reaches the board: clamp one conductor. The 1 V type reads directly on an ADC through a mid-rail bias of two 10k with 10 uF.",
    },
    "power_pzem004t": {
        "name": "PZEM-004T isolated energy meter with a current transformer", "kind": "module", "price_usd": 7.0,
        "pins": ["VCC", "RX", "TX", "GND"], "connect": "header", "mount": "cable",
        "body": [73.0, 40.0, 25.0], "cable_d": 5.0, "supply": "5V", "current_ma": 10,
        "sim": {"type": "bus", "channel": 5, "rest": 0.0, "values": [0.0, 1000.0]},
        "note": "Volts, amps, watts and kWh of a mains circuit over an isolated serial link (PZEM004Tv30): its mains side stays outside this case and is wired by an electrician.",
    },
    # strips and distance
    "led_strip_ws2812": {
        "name": "WS2812B LED strip, 1 m of 60 LEDs", "kind": "module", "price_usd": 5.0,
        "pins": ["VCC", "DIN", "GND"], "connect": "header", "mount": "cable",
        "body": [1000.0, 10.0, 3.0], "cable_d": 5.0, "supply": "5V", "current_ma": 1800,
        "note": "LEDs along a stair, a shelf, a board's whole length, cut to length. Up to 60 mA a LED at full white: limit brightness, and state its current on the supply net (0.5 to 3 A). 330R in DIN, 1000 uF across the supply, data above 0.7 x VDD (a level shifter, or VDD through a diode).",
    },
    "sonar_hcsr04": {
        "name": "HC-SR04 ultrasonic distance sensor", "kind": "sensor", "price_usd": 1.2,
        "pins": ["VCC", "TRIG", "ECHO", "GND"], "connect": "header", "mount": "cable",
        "body": [45.0, 20.0, 15.0], "cable_d": 5.0, "supply": "5V", "current_ma": 15,
        "note": "2 cm to 4 m. ECHO is 5 V: divide it (1k and 2k) before a 3.3 V GPIO. Its two cans look out of the case.",
    },
    "vibration_coin": {
        "name": "Coin vibration motor, 10 mm, on leads", "kind": "module", "price_usd": 0.5,
        "pins": ["P", "N"], "connect": "header", "mount": "inside",
        "body": [10.0, 10.0, 3.0], "supply": "3V3", "current_ma": 80,
        "note": "Low-side transistor with a flyback diode. Stuck to the inside of the case near the skin.",
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
