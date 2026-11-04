"""Electrical design rules (device_rules.py): every rule on a small hand-written graph, and the five devices of
2026-11-03 that passed lint and the reviewer while broken. Those graphs (latest version, firmware left out), their chips'
JLCPCB cards and EasyEDA entries are fixtures (tests/fixtures/device_rules); catalog.info runs on them offline."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from formwright import catalog, device, device_rules
from formwright.agent import device_prompt

FIX = Path(__file__).parent / "fixtures" / "device_rules"
CARDS = json.loads((FIX / "cards.json").read_text(encoding="utf-8"))
GRAPHS = json.loads((FIX / "graphs.json").read_text(encoding="utf-8"))
XIAO = {"id": "U1", "kind": "module", "module": "113991054"}
PICO = {"id": "U1", "kind": "module", "module": "SC0915"}


def card(names, *, labels=None, mpn="PART", category="", description="", package="", **extra):
    """A part card as catalog.info gives it: pins {num, name, label} in number order."""
    labels = labels or list(names)
    return {"mpn": mpn, "category": category, "description": description, "package": package,
            "pins": [{"num": str(i + 1), "name": n, "label": lb} for i, (n, lb) in enumerate(zip(names, labels))], **extra}


NPN = card(["1", "2", "3"], labels=["B", "E", "C"], mpn="S8050", category="Bipolar (BJT)", description="NPN 25V 500mA SOT-23", package="SOT-23")
NPN_BARE = card(["1", "2", "3"], labels=["P1", "P2", "P3"], mpn="S8050", category="Bipolar (BJT)", description="NPN 25V 500mA SOT-23", package="SOT-23")
PNP = card(["1", "2", "3"], labels=["B", "E", "C"], mpn="S8550", category="Bipolar (BJT)", description="PNP 25V 500mA SOT-23", package="SOT-23")
NMOS = card(["G", "S", "D"], mpn="AO3400", category="MOSFETs", description="N-Channel 30V 5.8A SOT-23", package="SOT-23")
MAG_BUZZER = card(["1", "2"], labels=["P1", "P2"], mpn="MLT-9650", category="Buzzers", description="2.7kHz 30mA 3V~7V Active Buzzer (Built-in Driving Circuit) Electromagnetic")
PIEZO = card(["1", "2"], labels=["P1", "P2"], mpn="PS1240P02BT", category="Buzzers", description="3V 4kHz Passive (Externally Driven) Piezoelectric")
PIEZO_ACTIVE = card(["+", "2"], labels=["P", "P2"], mpn="HND-2319", category="Buzzers", description="3V~24V 90dB Active Buzzer (Built-in Driving Circuit) Piezoelectric")
WS2812 = card(["VDD", "DOU", "GND", "DIN"], mpn="WS2812B", category="RGB LEDs(Built-in IC)", description="3.5V~5.5V 800Kbit/s SMD5050-4P")
BME280 = card(["GND", "CSB", "SDI", "SCK", "SDO", "VDDIO", "GND", "VDD"], labels=["GND", "CSB", "SDI", "SCK", "SDO", "VDDIO", "GND_7", "VDD"],
              mpn="BME280", category="Temperature and Humidity Sensor", description="1.71V~3.6V I2C SPI")
GND_V3 = [{"name": "GND", "pins": ["U1.GND"]}, {"name": "V3V3", "pins": ["U1.V3V3"]}]


def run(nodes, nets, parts=None, **extra):
    doc, _ = device.normalize({"title": "t", "nodes": [XIAO, *nodes] if not any(n["id"] == "U1" for n in nodes) else nodes,
                               "nets": nets, **extra})
    return device_rules.check(doc, parts or {})


def codes(found, severity=None):
    return sorted({(f["code"], f["ref"]) for f in found if severity in (None, f["severity"])})


def one(found, code):
    hits = [f for f in found if f["code"] == code]
    assert len(hits) == 1, found
    return hits[0]


# ---------------------------------------------------------------- the rules one by one
def test_short_part_two_terminal_parts_and_chips():
    bz = card(["+", "-", "NC"], labels=["POS", "NEG", "NC"], mpn="MLT-5020", category="Buzzers", description="100mA Electromagnetic Passive")
    found = run([{"id": "R1", "kind": "resistor"}, {"id": "SW1", "kind": "button"}, {"id": "BZ1", "kind": "chip", "lcsc": "C94598"}],
                [{"name": "GND", "pins": ["U1.GND", "SW1.A", "SW1.B"]}, {"name": "V3V3", "pins": ["U1.V3V3", "R1.1", "R1.2", "BZ1.POS", "BZ1.NEG", "BZ1.NC"]}],
                {"BZ1": bz})
    assert {("short_part", "R1"), ("short_part", "SW1"), ("short_part", "BZ1"), ("buzzer_unwired", "BZ1")} <= set(codes(found, "error"))
    bz1 = next(f for f in found if f["code"] == "short_part" and f["ref"] == "BZ1")
    assert "every wired pin of BZ1 (MLT-5020, passive buzzer: +, -) is on net V3V3" in bz1["msg"]
    # a chip whose only wired pins are its two grounds is unwired, not shorted
    assert not run([{"id": "U2", "kind": "chip", "lcsc": "C92489"}], [{"name": "GND", "pins": ["U1.GND", "U2.GND"]}], {"U2": BME280})


def test_battery_raw_on_a_xiao_a_pico_and_through_a_diode():
    bat = {"id": "J_BAT", "kind": "jst", "label": "LiPo 3.7V", "edge": "+x"}
    f = one(run([bat], [{"name": "GND", "pins": ["U1.GND", "J_BAT.P2"]}, {"name": "VBAT", "pins": ["U1.V5", "J_BAT.P1"]}]), "battery_raw")
    assert f["severity"] == "error" and f["ref"] == "J_BAT" and "U1.V5" in f["msg"] and "BAT+ / BAT-" in f["hint"]
    f = one(run([bat], [{"name": "V3V3", "pins": ["U1.V3V3", "J_BAT.P1"]}, {"name": "GND", "pins": ["U1.GND", "J_BAT.P2"]}]), "battery_raw")
    assert "3.3 V rail" in f["msg"]
    pico = run([PICO, {"id": "J1", "kind": "jst", "label": "battery"}], [{"name": "VSYS", "pins": ["U1.VSYS", "J1.P1"]}, {"name": "GND", "pins": ["U1.GND", "J1.P2"]}])
    assert "Schottky" in one(pico, "battery_raw")["hint"]
    # through the Schottky (A on the cell): the module's 5 V cannot reach the cell
    ok = run([bat, {"id": "D1", "kind": "diode"}], [{"name": "VBAT", "pins": ["J_BAT.P1", "D1.A"]}, {"name": "V5", "pins": ["D1.K", "U1.V5"]},
                                                     {"name": "GND", "pins": ["U1.GND", "J_BAT.P2"]}])
    assert "battery_raw" not in {f["code"] for f in ok}
    # a JST that is not a battery is not one; a JST on a VBAT net is
    assert not run([{"id": "J1", "kind": "jst", "label": "solar in"}], [{"name": "V5", "pins": ["U1.V5", "J1.P1"]}, {"name": "GND", "pins": ["U1.GND", "J1.P2"]}])
    assert one(run([{"id": "J1", "kind": "jst"}], [{"name": "VBAT", "pins": ["U1.V5", "J1.P1"]}, {"name": "GND", "pins": ["U1.GND", "J1.P2"]}]), "battery_raw")


def test_battery_accessory_from_the_library(monkeypatch):
    monkeypatch.setattr(device_rules, "_accessories", lambda: {"cell": {"name": "1S LiPo", "kind": "battery", "pins": ["VBAT", "GND"],
                                                                        "connect": "module_bat", "supply": "3V3"}})
    doc = {"nodes": [XIAO, {"id": "A1", "kind": "accessory", "accessory": "cell"}],
           "nets": [{"name": "V5", "pins": ["U1.V5", "A1.VBAT"]}, {"name": "GND", "pins": ["U1.GND", "A1.GND"]}]}
    f = one(device_rules.check(doc, {}), "battery_raw")
    assert f["ref"] == "A1" and "1S LiPo" in f["msg"] and "'cell' (connect module_bat)" in f["hint"]


def test_bjt_turned_round_base_without_resistor_and_the_right_way():
    nodes = [{"id": "Q1", "kind": "chip", "lcsc": "C181158"}, {"id": "R5", "kind": "resistor", "value": "1k"},
             {"id": "BZ1", "kind": "chip", "lcsc": "C96127"}]
    good = [{"name": "GND", "pins": ["U1.GND", "Q1.E"]}, {"name": "V5", "pins": ["U1.V5", "BZ1.P1"]}, {"pins": ["BZ1.P2", "Q1.C"]},
            {"pins": ["U1.D1", "R5.1"]}, {"pins": ["R5.2", "Q1.B"]}]
    parts = {"Q1": NPN, "BZ1": MAG_BUZZER}
    assert not [f for f in run(nodes, good, parts) if f["code"] in ("bjt_reversed", "bjt_base_resistor", "gpio_overload")]
    flipped = [{"name": "GND", "pins": ["U1.GND", "Q1.C"]}, {"name": "V3V3", "pins": ["U1.V3V3", "Q1.E", "BZ1.P1"]}, {"pins": ["BZ1.P2", "U1.D2"]},
               {"pins": ["U1.D1", "R5.1"]}, {"pins": ["R5.2", "Q1.B"]}]
    f = one(run(nodes, flipped, parts), "bjt_reversed")
    assert f["severity"] == "error" and "emitter Q1.E on V3V3" in f["msg"] and "collector Q1.C on GND" in f["msg"] and "assuming" not in f["msg"]
    direct = [{"name": "GND", "pins": ["U1.GND", "Q1.E"]}, {"name": "V5", "pins": ["U1.V5", "BZ1.P1"]}, {"pins": ["BZ1.P2", "Q1.C"]}, {"pins": ["U1.D1", "Q1.B"]}]
    f = one(run(nodes, direct, parts), "bjt_base_resistor")
    assert "U1.D1 (GPIO3)" in f["msg"] and "1k" in f["hint"]
    # unnamed pins: the SOT-23 pinout is assumed and said; in another package the pinout is unknown
    bare = [{"name": "GND", "pins": ["U1.GND", "Q1.P3"]}, {"name": "V3V3", "pins": ["U1.V3V3", "Q1.P2"]}, {"pins": ["U1.D1", "R5.1"]}, {"pins": ["R5.2", "Q1.P1"]}]
    f = one(run(nodes[:2], bare, {"Q1": NPN_BARE}), "bjt_reversed")
    assert "assuming the usual SOT-23 pinout Q1.P1=B, Q1.P2=E, Q1.P3=C" in f["msg"]
    found = run(nodes[:2], bare, {"Q1": {**NPN_BARE, "package": "TO-92"}})
    assert codes(found) == [("pinout_unknown", "Q1")] and found[0]["severity"] == "warning" and "verify the pinout" in found[0]["msg"]


def test_pnp_mirrored_and_a_5v_high_side_from_a_3v3_pin():
    nodes = [{"id": "Q1", "kind": "chip", "lcsc": "C8546"}, {"id": "R1", "kind": "resistor", "value": "1k"}]
    rev = run(nodes, [{"name": "GND", "pins": ["U1.GND", "Q1.E"]}, {"pins": ["U1.D1", "R1.1"]}, {"pins": ["R1.2", "Q1.B"]}, {"name": "V3V3", "pins": ["U1.V3V3", "Q1.C"]}],
              {"Q1": PNP})
    assert one(rev, "bjt_reversed")["severity"] == "error"
    hi = run(nodes, [{"name": "V5", "pins": ["U1.V5", "Q1.E"]}, {"pins": ["U1.D1", "R1.1"]}, {"pins": ["R1.2", "Q1.B"]}, {"pins": ["Q1.C", "U1.D2"]}], {"Q1": PNP})
    assert one(hi, "high_side_level")["severity"] == "warning" and "never turns off" in one(hi, "high_side_level")["msg"]


def test_mosfet_gate_pull_down_high_side_and_reversed():
    motor = card(["+", "-"], labels=["P", "N"], mpn="1027 motor", category="Vibration Motors")
    nodes = [{"id": "Q1", "kind": "chip", "lcsc": "C344010"}, {"id": "M1", "kind": "chip", "lcsc": "C2759984"}, {"id": "R1", "kind": "resistor", "value": "100k"},
             {"id": "D1", "kind": "diode"}]
    parts = {"Q1": NMOS, "M1": motor}
    good = [{"name": "GND", "pins": ["U1.GND", "Q1.S", "R1.2"]}, {"pins": ["U1.D2", "Q1.G", "R1.1"]}, {"name": "V5", "pins": ["U1.V5", "M1.P", "D1.K"]},
            {"pins": ["M1.N", "Q1.D", "D1.A"]}]
    assert run(nodes, good, parts) == []
    floating = [{"name": "GND", "pins": ["U1.GND", "Q1.S"]}, {"pins": ["U1.D2", "Q1.G"]}, {"name": "V5", "pins": ["U1.V5", "M1.P", "D1.K"]},
                {"pins": ["M1.N", "Q1.D", "D1.A"]}]
    f = one(run(nodes[:2] + nodes[3:], floating, parts), "mosfet_gate_floating")
    assert f["severity"] == "warning" and "100k" in f["hint"]
    high = [{"name": "GND", "pins": ["U1.GND", "M1.N", "R1.2"]}, {"pins": ["U1.D2", "Q1.G", "R1.1"]}, {"name": "V5", "pins": ["U1.V5", "Q1.D"]},
            {"pins": ["Q1.S", "M1.P"]}]
    assert one(run(nodes[:3], high, parts), "mosfet_high_side")["severity"] == "warning"
    rev = [{"name": "GND", "pins": ["U1.GND", "Q1.D", "R1.2"]}, {"pins": ["U1.D2", "Q1.G", "R1.1"]}, {"name": "V5", "pins": ["U1.V5", "M1.P"]},
           {"pins": ["M1.N", "Q1.S"]}]
    assert one(run(nodes[:3], rev, parts), "mosfet_reversed")["severity"] == "error"
    # the motor is a coil: switched without a diode across it, it kicks the MOSFET
    no_diode = [{"name": "GND", "pins": ["U1.GND", "Q1.S", "R1.2"]}, {"pins": ["U1.D2", "Q1.G", "R1.1"]}, {"name": "V5", "pins": ["U1.V5", "M1.P"]},
                {"pins": ["M1.N", "Q1.D"]}]
    assert codes(run(nodes[:3], no_diode, parts)) == [("flyback_diode", "M1")]


def test_gpio_overload_buzzers_cards_and_accessories(monkeypatch):
    nets = [{"name": "GND", "pins": ["U1.GND", "BZ1.P2"]}, {"pins": ["U1.D1", "BZ1.P1"]}]
    f = one(run([{"id": "BZ1", "kind": "chip", "lcsc": "C96127"}], nets, {"BZ1": MAG_BUZZER}), "gpio_overload")
    assert f["severity"] == "error" and "30 mA" in f["msg"] and "U1.D1 (GPIO3)" in f["msg"] and "diode across it" in f["hint"]
    # a passive piezo is a small capacitor a GPIO drives with tone(); an active piezo with no stated current is a doubt
    assert not run([{"id": "BZ1", "kind": "chip", "lcsc": "C76871"}], nets, {"BZ1": PIEZO})
    act = run([{"id": "BZ1", "kind": "chip", "lcsc": "C2878"}], [{"name": "GND", "pins": ["U1.GND", "BZ1.P2"]}, {"pins": ["U1.D1", "BZ1.P"]}], {"BZ1": PIEZO_ACTIVE})
    assert one(act, "gpio_overload")["severity"] == "warning"
    # any part whose card says >= 20 mA, powered from a pin
    hungry = card(["VCC", "GND", "OUT"], mpn="RCWL-0516", description="radar", current_ma=50)
    f = one(run([{"id": "U2", "kind": "chip", "lcsc": "C1"}], [{"pins": ["U1.D2", "U2.VCC"]}, {"name": "GND", "pins": ["U1.GND", "U2.GND"]}, {"pins": ["U1.D3", "U2.OUT"]}],
                {"U2": hungry}), "gpio_overload")
    assert "50 mA" in f["msg"]
    monkeypatch.setattr(device_rules, "_accessories", lambda: {"servo": {"name": "SG90 servo", "pins": ["GND", "VCC", "SIG"], "supply": "5V", "current_ma": 250}})
    doc = {"nodes": [XIAO, {"id": "A1", "kind": "accessory", "accessory": "servo"}],
           "nets": [{"pins": ["U1.D3", "A1.VCC"]}, {"name": "GND", "pins": ["U1.GND", "A1.GND"]}, {"pins": ["U1.D2", "A1.SIG"]}]}
    assert one(device_rules.check(doc, {}), "gpio_overload")["ref"] == "A1"


def test_the_catalogue_kind_hint_and_current_settle_it_without_words():
    """catalog.info's kind_hint and current_ma (contract C6) are read first; the category and description only fill in."""
    bz = card(["1", "2"], labels=["POS", "NEG"], mpn="X1", kind_hint="buzzer_active", current_ma=35)
    f = one(run([{"id": "BZ1", "kind": "chip", "lcsc": "C1"}], [{"pins": ["U1.D1", "BZ1.NEG"]}, {"name": "V3V3", "pins": ["U1.V3V3", "BZ1.POS"]}], {"BZ1": bz}),
            "gpio_overload")
    assert f["severity"] == "error" and "35 mA" in f["msg"]
    q = card(["1", "2", "3"], labels=["B", "E", "C"], mpn="X2", kind_hint="npn")
    found = run([{"id": "Q1", "kind": "chip", "lcsc": "C2"}], [{"name": "V3V3", "pins": ["U1.V3V3", "Q1.E"]}, {"pins": ["U1.D1", "Q1.B"]}, {"name": "GND", "pins": ["U1.GND", "Q1.C"]}],
                {"Q1": q})
    assert codes(found) == [("bjt_base_resistor", "Q1"), ("bjt_reversed", "Q1")]
    # an LED driver or a motor driver is an IC, not the load it drives
    drv = card(["VCC", "GND", "IN1", "OUT1"], mpn="DRV8833", category="Motor Driver ICs", description="Brushed DC motor driver 1.5A")
    assert not run([{"id": "U2", "kind": "chip", "lcsc": "C3"}], [{"pins": ["U1.D1", "U2.IN1"]}, {"name": "V5", "pins": ["U1.V5", "U2.VCC"]}, {"name": "GND", "pins": ["U1.GND", "U2.GND"]}],
                   {"U2": drv})


def test_buzzer_unwired():
    bz = card(["+", "-"], labels=["P", "N"], mpn="MLT-5020", category="Buzzers", description="Electromagnetic Passive")
    loose = run([{"id": "BZ1", "kind": "chip", "lcsc": "C94598"}], [{"name": "V3V3", "pins": ["U1.V3V3", "BZ1.P"]}], {"BZ1": bz})
    assert "BZ1.N (-) is not connected" in one(loose, "buzzer_unwired")["msg"]
    rails = run([{"id": "BZ1", "kind": "chip", "lcsc": "C94598"}], [{"name": "V3V3", "pins": ["U1.V3V3", "BZ1.P"]}, {"name": "GND", "pins": ["U1.GND", "BZ1.N"]}],
                {"BZ1": bz})
    assert "every terminal on a supply net" in one(rails, "buzzer_unwired")["msg"]


def test_gpio_short_two_pins_and_module_rails():
    found = run([{"id": "R1", "kind": "resistor"}], [{"name": "GND", "pins": ["U1.GND", "U1.D0"]}, {"pins": ["U1.D1", "U1.D2", "R1.1"]},
                                                      {"name": "V3V3", "pins": ["U1.V3V3", "R1.2"]}])
    assert ("gpio_short", "U1.D0") in codes(found, "error") and ("gpio_short", "U1.D1+U1.D2") in codes(found, "error")
    assert "on the ground net GND" in next(f for f in found if f["ref"] == "U1.D0")["msg"]
    assert ("supplies_shorted", "U1.V3V3/U1.V5") in codes(run([], [{"pins": ["U1.V3V3", "U1.V5"]}]))


def test_i2c_pins_driving_an_led():
    nodes = [{"id": "U2", "kind": "chip", "lcsc": "C92489"}, {"id": "R1", "kind": "resistor", "value": "4.7k"}, {"id": "R2", "kind": "resistor", "value": "4.7k"},
             {"id": "R3", "kind": "resistor", "value": "1k"}, {"id": "LED1", "kind": "led"}]
    nets = [{"name": "GND", "pins": ["U1.GND", "U2.GND", "LED1.K"]}, {"name": "V3V3", "pins": ["U1.V3V3", "U2.VDD", "R1.1", "R2.1"]},
            {"name": "SDA", "pins": ["U1.SDA", "U2.SDI", "R1.2", "R3.1"]}, {"name": "SCL", "pins": ["U1.SCL", "U2.SCK", "R2.2"]}, {"pins": ["R3.2", "LED1.A"]}]
    f = one(run(nodes, nets, {"U2": BME280}), "i2c_pin_misuse")
    assert f["severity"] == "error" and f["ref"] == "U1.SDA" and "LED1 (through R3)" in f["msg"] and "R1" not in f["msg"]
    alone = run(nodes[3:], [{"pins": ["U1.SCL", "R3.1"]}, {"pins": ["R3.2", "LED1.A"]}, {"name": "GND", "pins": ["U1.GND", "LED1.K"]}])
    assert one(alone, "i2c_pin_misuse")["severity"] == "warning"


def test_strapping_pins_from_the_module_spec(monkeypatch):
    nets = [{"pins": ["U1.D9", "SW1.A"]}, {"name": "GND", "pins": ["U1.GND", "SW1.B"]}]
    f = one(run([{"id": "SW1", "kind": "button"}], nets), "strapping_pin")
    assert f["ref"] == "U1.MISO" and "U1.MISO (D9, GPIO9)" in f["msg"] and "SW1 (button to GND)" in f["msg"] and f["hint"].startswith("Move SW1 from U1.MISO")
    assert not run([{"id": "SW1", "kind": "button"}], [{"pins": ["U1.D1", "SW1.A"]}, {"name": "GND", "pins": ["U1.GND", "SW1.B"]}])
    # a pull-up keeps the boot level
    assert not run([{"id": "R1", "kind": "resistor"}], [{"pins": ["U1.D0", "R1.1"]}, {"name": "V3V3", "pins": ["U1.V3V3", "R1.2"]}])
    # device.MODULES says which pins are strapping (contract C5); the rules' own table only fills in when it does not
    monkeypatch.setitem(device.MODULES["113991054"], "strapping", [])
    assert not run([{"id": "SW1", "kind": "button"}], nets)


def test_ws2812_level_and_decoupling(monkeypatch):
    nodes = [{"id": "LED1", "kind": "chip", "lcsc": "C2843785"}, {"id": "C1", "kind": "capacitor"}]
    on5 = [{"name": "V5", "pins": ["U1.V5", "LED1.VDD", "C1.1"]}, {"name": "GND", "pins": ["U1.GND", "LED1.GND", "C1.2"]}, {"pins": ["U1.D2", "LED1.DIN"]}]
    found = run(nodes, on5, {"LED1": WS2812})
    assert codes(found) == [("ws2812_level", "LED1")] and "0.7 x VDD = 3.5 V" in found[0]["msg"] and "74AHCT1G125" in found[0]["hint"]
    # VDD a diode drop below 5 V: no level problem
    dropped = [{"name": "V5", "pins": ["U1.V5", "D1.A"]}, {"name": "VLED", "pins": ["D1.K", "LED1.VDD", "C1.1"]}, {"name": "GND", "pins": ["U1.GND", "LED1.GND", "C1.2"]},
               {"pins": ["U1.D2", "LED1.DIN"]}]
    assert run([*nodes, {"id": "D1", "kind": "diode"}], dropped, {"LED1": WS2812}) == []
    bare = [{"name": "V5", "pins": ["U1.V5", "LED1.VDD"]}, {"name": "GND", "pins": ["U1.GND", "LED1.GND"]}, {"pins": ["U1.D2", "LED1.DIN"]}]
    assert codes(run(nodes[:1], bare, {"LED1": WS2812})) == [("ws2812_decoupling", "LED1"), ("ws2812_level", "LED1")]
    # what lint already says is not said twice
    real = device.lint
    monkeypatch.setattr(device, "lint", lambda d, p: real(d, p) + [{"code": "decoupling", "ref": "LED1", "msg": "x"}])
    assert codes(run(nodes[:1], bare, {"LED1": WS2812})) == [("ws2812_level", "LED1")]
    # on 3.3 V it is under its 3.5 V minimum
    low = run(nodes, [{"name": "V3V3", "pins": ["U1.V3V3", "LED1.VDD", "C1.1"]}, {"name": "GND", "pins": ["U1.GND", "LED1.GND", "C1.2"]}, {"pins": ["U1.D2", "LED1.DIN"]}],
              {"LED1": WS2812})
    assert one(low, "supply_range")["severity"] == "warning"


def test_i2c_pull_ups_to_5v():
    found = run([{"id": "U2", "kind": "chip", "lcsc": "C92489"}, {"id": "R1", "kind": "resistor", "value": "4.7k"}],
                [{"name": "GND", "pins": ["U1.GND", "U2.GND"]}, {"name": "V3V3", "pins": ["U1.V3V3", "U2.VDD"]}, {"name": "V5", "pins": ["U1.V5", "R1.1"]},
                 {"name": "SDA", "pins": ["U1.SDA", "U2.SDI", "R1.2"]}, {"name": "SCL", "pins": ["U1.SCL", "U2.SCK"]}], {"U2": BME280})
    f = one(found, "pullup_5v")
    assert f["severity"] == "error" and f["ref"] == "R1" and "R1.1 to V3V3" in f["hint"]


def test_led_current_no_series_resistor_and_turned_round():
    small = run([{"id": "R1", "kind": "resistor", "value": "22"}, {"id": "LED1", "kind": "led", "color": "red"}],
                [{"pins": ["U1.D1", "R1.1"]}, {"pins": ["R1.2", "LED1.A"]}, {"name": "GND", "pins": ["U1.GND", "LED1.K"]}])
    f = one(small, "led_current")
    assert f["severity"] == "warning" and "64 mA" in f["msg"] and "at least 70 ohm" in f["hint"]
    # a pull-up on the anode's net satisfies lint, yet nothing is in series
    pulled = run([{"id": "R1", "kind": "resistor", "value": "10k"}, {"id": "LED1", "kind": "led"}],
                 [{"pins": ["U1.D1", "LED1.A", "R1.1"]}, {"name": "V3V3", "pins": ["U1.V3V3", "R1.2"]}, {"name": "GND", "pins": ["U1.GND", "LED1.K"]}])
    assert "no resistor in series" in one(pulled, "led_current")["msg"]
    rev = run([{"id": "R1", "kind": "resistor", "value": "1k"}, {"id": "LED1", "kind": "led"}],
              [{"pins": ["U1.D1", "R1.1"]}, {"pins": ["R1.2", "LED1.K"]}, {"name": "GND", "pins": ["U1.GND", "LED1.A"]}])
    assert one(rev, "led_reversed")["severity"] == "error"
    assert not run([{"id": "R1", "kind": "resistor", "value": "4k7"}, {"id": "LED1", "kind": "led"}],
                   [{"pins": ["U1.D1", "R1.1"]}, {"pins": ["R1.2", "LED1.A"]}, {"name": "GND", "pins": ["U1.GND", "LED1.K"]}])


def test_supply_range_over_the_maximum():
    found = run([{"id": "U2", "kind": "chip", "lcsc": "C92489"}], [{"name": "GND", "pins": ["U1.GND", "U2.GND"]}, {"name": "V5", "pins": ["U1.V5", "U2.VDD"]}],
                {"U2": BME280})
    f = one(found, "supply_range")
    assert f["severity"] == "error" and "rated 1.71-3.6 V" in f["msg"] and "V3V3" in f["hint"]


def test_supply_range_of_a_two_terminal_load():
    """A buzzer or motor has no pin named like a supply: the terminal on a rail is its supply."""
    bz = card(["1", "2"], labels=["POS", "NEG"], mpn="TMB12075-3V", category="Buzzers", kind_hint="buzzer_active", current_ma=30,
              description="2.7kHz 2V~4V 30mA 3V Active Buzzer (Built-in Driving Circuit) Electromagnetic")
    nodes = [{"id": "BZ1", "kind": "chip", "lcsc": "C49246934"}, {"id": "Q1", "kind": "chip", "lcsc": "C2146"}, {"id": "R1", "kind": "resistor", "value": "1k"}]
    parts = {"BZ1": bz, "Q1": NPN}
    on5 = run(nodes, [*SWITCHED, {"name": "VBUS", "pins": ["U1.V5", "BZ1.P1"]}, {"pins": ["BZ1.P2", "Q1.C"]}], parts)
    f = one(on5, "supply_range")
    assert f["severity"] == "error" and "BZ1.POS is on VBUS (5 V)" in f["msg"] and "rated 2-4 V" in f["msg"] and f["hint"] == "Supply BZ1.POS from V3V3 instead."
    assert "supply_range" not in {x["code"] for x in run(nodes, [*SWITCHED, {"name": "V3V3", "pins": ["U1.V3V3", "BZ1.POS"]}, {"pins": ["BZ1.NEG", "Q1.C"]}], parts)}
    motor = card(["+", "-"], labels=["POS", "NEG"], mpn="1020 motor", category="Vibration Motors", description="2.5V~3.5V 80mA coin vibration motor")
    found = run([{"id": "M1", "kind": "chip", "lcsc": "C9"}, *nodes[1:]], [*SWITCHED, {"name": "V5", "pins": ["U1.V5", "M1.POS"]}, {"pins": ["M1.NEG", "Q1.C"]}],
                {"M1": motor, "Q1": NPN})
    assert one(found, "supply_range")["ref"] == "M1"


LED_CHIP = card(["1", "2"], labels=["K", "A"], mpn="RED0805", category="LED Indication - Discrete", description="Red 0805 20mA", kind_hint="led",
                current_ma=20, attrs={"Voltage - Forward(Vf)": "1.8V~2.2V"})


def test_chip_led_turned_round_and_its_current():
    """A chip LED whose card labels A and K (by name, or from its symbol's triangle) is checked like the primitive: a GPIO
    in its path holds it to 20 mA; fed from a rail through a transistor it is held to its rated current, at the Vf its
    card gives or its colour drops. 'LED1.P2' still finds pin 2, now A."""
    nodes = [{"id": "LED1", "kind": "chip", "lcsc": "C1"}, {"id": "R1", "kind": "resistor", "value": "22R"}]
    pin = run(nodes, [{"pins": ["U1.D1", "R1.1"]}, {"pins": ["R1.2", "LED1.P2"]}, {"name": "GND", "pins": ["U1.GND", "LED1.P1"]}], {"LED1": LED_CHIP})
    f = one(pin, "led_current")
    assert "68 mA through the LED and the pin (keep it under 20 mA" in f["msg"] and "at least 75 ohm" in f["hint"]  # (3.3 - 1.8) / 22R
    rev = run(nodes, [{"pins": ["U1.D1", "R1.1"]}, {"pins": ["R1.2", "LED1.K"]}, {"name": "GND", "pins": ["U1.GND", "LED1.A"]}], {"LED1": LED_CHIP})
    assert one(rev, "led_reversed")["severity"] == "error" and "anode LED1.A is on GND" in one(rev, "led_reversed")["msg"]
    # a 60 mA white 2835 from V5 behind an N-MOSFET: its own rating, not the pin's 20 mA
    white = copy.deepcopy(CARDS["C210315"])
    switched = [{"pins": ["U1.D1", "R6.1"]}, {"pins": ["R6.2", "Q1.G", "R7.1"]}, {"name": "GND", "pins": ["U1.GND", "Q1.S", "R7.2"]},
                {"name": "V5", "pins": ["U1.V5", "LED1.P2"]}, {"pins": ["LED1.P1", "R1.1"]}, {"pins": ["R1.2", "Q1.D"]}]
    sw = [{"id": "Q1", "kind": "chip", "lcsc": "C181090"}, {"id": "R6", "kind": "resistor", "value": "100R"}, {"id": "R7", "kind": "resistor", "value": "100k"}]

    def led_findings(ohms, part):
        found = run([{**nodes[0], "lcsc": "C210315"}, {**nodes[1], "value": ohms}, *sw], switched, {"LED1": part, "Q1": NMOS})
        return [x for x in found if x["code"].startswith("led_")]

    assert [p["label"] for p in white["pins"]] == ["K", "A"] and led_findings("33R", white) == []  # (5 - 3.2) / 33R = 55 mA
    f = one(led_findings("10R", white), "led_current")
    assert "about 180 mA through the LED (Vf ~3.2 V), over its rated 60 mA" in f["msg"] and "at least 30 ohm" in f["hint"]
    # no Vf on the card: white drops about 2.8 V (the 'Frosted Yellow Lens' is no colour), red 1.9 V
    bare = {**white, "attrs": {}}
    assert "Vf ~2.8 V" in one(led_findings("33R", bare), "led_current")["msg"]
    assert "Vf ~1.9 V" in one(led_findings("33R", {**bare, "description": "Red 2835 60mA"}), "led_current")["msg"]
    # a chip LED whose pins have no roles is left alone
    numbered = {**white, "pins": [{"num": "1", "name": "1", "label": "P1"}, {"num": "2", "name": "2", "label": "P2"}]}
    assert led_findings("10R", numbered) == []


def test_accessory_supply(monkeypatch):
    monkeypatch.setattr(device_rules, "_accessories", lambda: {
        "pir": {"name": "HC-SR501 PIR", "pins": ["VCC", "OUT", "GND"], "supply": "5V", "current_ma": 1},
        "oled": {"name": "OLED 3V3 only", "pins": ["GND", "VCC", "SCL", "SDA"], "supply": "3V3", "current_ma": 15},
        "probe": {"name": "probe", "pins": ["GND", "VCC", "AOUT"], "supply": "3V3-5V", "current_ma": 5}})
    doc = {"nodes": [XIAO, {"id": "A1", "kind": "accessory", "accessory": "pir"}, {"id": "A2", "kind": "accessory", "accessory": "oled"},
                     {"id": "A3", "kind": "accessory", "accessory": "probe"}],
           "nets": [{"name": "V3V3", "pins": ["U1.V3V3", "A1.VCC"]}, {"name": "V5", "pins": ["U1.V5", "A2.VCC", "A3.VCC"]},
                    {"name": "GND", "pins": ["U1.GND", "A1.GND", "A2.GND", "A3.GND"]}, {"pins": ["U1.D1", "A1.OUT"]}, {"pins": ["U1.D0", "A3.AOUT"]}]}
    found = device_rules.check(doc, {})
    assert {("accessory_supply", "A1"), ("accessory_supply", "A2")} == {c for c in codes(found) if c[0] == "accessory_supply"}
    # a 5 V relay that never pulls in passed as a warning on 2026-11-04: a module off its supply does not work
    assert all(f["severity"] == "error" for f in found if f["code"] == "accessory_supply")


def test_requirements_naming_parts_that_are_not_there():
    doc, _ = device.normalize({"title": "t", "nodes": [XIAO], "nets": GND_V3})
    doc["requirements"] = [{"id": "R1", "text": "beeps when the soil is dry", "parts": ["BZ1", "U1"]}, {"id": "R2", "text": "Wi-Fi page", "parts": ["U1"], "firmware": True}]
    f = one(device_rules.check(doc, {}), "unused_requirement")
    assert f["ref"] == "R1" and "names BZ1, which is not in the graph" in f["msg"] and f["severity"] == "warning"


SWITCHED = [{"name": "GND", "pins": ["U1.GND", "Q1.E"]}, {"pins": ["U1.D1", "R1.1"]}, {"pins": ["R1.2", "Q1.B"]}]
LDR = card(["1", "2"], labels=["P1", "P2"], mpn="GL5516", category="Photoresistors", description="5kΩ~10kΩ 540nm", kind_hint="sensor")


def test_floating_pin_a_diode_left_hanging_and_a_one_ended_resistor():
    nodes = [{"id": "Q1", "kind": "chip", "lcsc": "C2146"}, {"id": "R1", "kind": "resistor", "value": "1k"}, {"id": "BZ1", "kind": "chip", "lcsc": "C96127"},
             {"id": "D1", "kind": "diode"}]
    parts = {"Q1": NPN, "BZ1": MAG_BUZZER}
    f = one(run(nodes, [*SWITCHED, {"name": "V5", "pins": ["U1.V5", "BZ1.P1"]}, {"pins": ["BZ1.P2", "Q1.C", "D1.A"]}], parts), "floating_pin")
    assert f["severity"] == "error" and f["ref"] == "D1" and "D1.K is on no net" in f["msg"] and "wire D1.K to V5" in f["hint"]
    whole = run(nodes, [*SWITCHED, {"name": "V5", "pins": ["U1.V5", "BZ1.P1", "D1.K"]}, {"pins": ["BZ1.P2", "Q1.C", "D1.A"]}], parts)
    assert not [x for x in whole if x["code"] in ("floating_pin", "flyback_orientation")]
    # a pull-up wired at one end only, and one whose other end is a net with nothing else on it
    one_end = run([{"id": "R2", "kind": "resistor"}], [{"pins": ["U1.D2", "R2.1"]}])
    assert "R2.2 is on no net" in one(one_end, "floating_pin")["msg"]
    lonely = run([{"id": "R2", "kind": "resistor"}], [{"pins": ["U1.D2", "R2.1"]}, {"name": "PULL", "pins": ["R2.2"]}])
    assert "R2.2 is on net PULL with nothing else" in one(lonely, "floating_pin")["msg"]
    # a buzzer's loose terminal is said once, by buzzer_unwired
    bz = run([{"id": "BZ1", "kind": "chip", "lcsc": "C96127"}], [{"name": "V3V3", "pins": ["U1.V3V3", "BZ1.P1"]}], {"BZ1": MAG_BUZZER})
    assert codes(bz) == [("buzzer_unwired", "BZ1")]


def test_a_magnetic_buzzer_switched_by_a_transistor_wants_its_diode():
    # the soil sensor p_6b596fac7f1e4fd3 dropped D1 from across its FMB09A03 and nothing said so
    nodes = [{"id": "Q1", "kind": "chip", "lcsc": "C2146"}, {"id": "R1", "kind": "resistor", "value": "1k"}, {"id": "BZ1", "kind": "chip", "lcsc": "C96127"}]
    nets = [*SWITCHED, {"name": "V3V3", "pins": ["U1.V3V3", "BZ1.P1"]}, {"pins": ["BZ1.P2", "Q1.C"]}]
    f = one(run(nodes, nets, {"Q1": NPN, "BZ1": MAG_BUZZER}), "flyback_diode")
    assert f["severity"] == "warning" and f["ref"] == "BZ1"
    assert not [x for x in run(nodes, nets, {"Q1": NPN, "BZ1": PIEZO_ACTIVE}) if x["code"] == "flyback_diode"], "a piezo is no coil"


def test_flyback_diode_turned_round():
    motor = card(["+", "-"], labels=["P", "N"], mpn="1027 motor", category="Vibration Motors")
    nodes = [{"id": "Q1", "kind": "chip", "lcsc": "C2146"}, {"id": "R1", "kind": "resistor", "value": "1k"}, {"id": "M1", "kind": "chip", "lcsc": "C9"},
             {"id": "D1", "kind": "diode"}]
    rev = run(nodes, [*SWITCHED, {"name": "V5", "pins": ["U1.V5", "M1.P", "D1.A"]}, {"pins": ["M1.N", "Q1.C", "D1.K"]}], {"Q1": NPN, "M1": motor})
    f = one(rev, "flyback_orientation")
    assert f["severity"] == "error" and f["ref"] == "D1" and "shorts the supply" in f["msg"] and "K on V5" in f["hint"]
    assert not run(nodes, [*SWITCHED, {"name": "V5", "pins": ["U1.V5", "M1.P", "D1.K"]}, {"pins": ["M1.N", "Q1.C", "D1.A"]}], {"Q1": NPN, "M1": motor})


def test_sensor_divider_says_which_way_the_reading_moves(monkeypatch):
    monkeypatch.setitem(device.MODULES["113991054"], "adc", ["D0", "D1", "D2"])
    nodes = [{"id": "ALS1", "kind": "chip", "lcsc": "C10077"}, {"id": "R_ALS", "kind": "resistor", "value": "10k"}]
    top = run(nodes, [{"name": "V3V3", "pins": ["U1.V3V3", "ALS1.P1"]}, {"pins": ["U1.D1", "ALS1.P2", "R_ALS.1"]}, {"name": "GND", "pins": ["U1.GND", "R_ALS.2"]}],
              {"ALS1": LDR})
    f = one(top, "sensor_divider")
    assert "the reading on D1 RISES with light" in f["msg"] and f["data"]["rises"] is True and "below the threshold" in f["hint"]
    bottom = run(nodes, [{"name": "V3V3", "pins": ["U1.V3V3", "R_ALS.1"]}, {"pins": ["U1.D1", "ALS1.P2", "R_ALS.2"]}, {"name": "GND", "pins": ["U1.GND", "ALS1.P1"]}],
                 {"ALS1": LDR})
    assert "FALLS with light" in one(bottom, "sensor_divider")["msg"] and one(bottom, "sensor_divider")["data"]["rises"] is False
    ntc = card(["1", "2"], labels=["P1", "P2"], mpn="NCP18XH103", category="NTC Thermistors", description="10kΩ ±1% B=3380")
    warm = run([{"id": "TH1", "kind": "chip", "lcsc": "C77131"}, nodes[1]],
               [{"name": "V3V3", "pins": ["U1.V3V3", "TH1.P1"]}, {"pins": ["U1.D0", "TH1.P2", "R_ALS.1"]}, {"name": "GND", "pins": ["U1.GND", "R_ALS.2"]}], {"TH1": ntc})
    assert "RISES with temperature" in one(warm, "sensor_divider")["msg"]
    alone = run(nodes[:1], [{"name": "V3V3", "pins": ["U1.V3V3", "ALS1.P1"]}, {"pins": ["U1.D1", "ALS1.P2"]}], {"ALS1": LDR})
    assert "no fixed resistor to GND" in one(alone, "sensor_divider")["msg"]
    # D3 is the XIAO ESP32-C3's ADC2 pin, unusable with Wi-Fi on: not in the module's ADC list
    d3 = run(nodes, [{"name": "V3V3", "pins": ["U1.V3V3", "ALS1.P1"]}, {"pins": ["U1.D3", "ALS1.P2", "R_ALS.1"]}, {"name": "GND", "pins": ["U1.GND", "R_ALS.2"]}],
             {"ALS1": LDR})
    assert one(d3, "adc_pin")["severity"] == "error" and one(d3, "adc_pin")["hint"].endswith("to an ADC pin: D0, D1, D2.")


PMOS = card(["G", "S", "D"], mpn="AO3401", category="MOSFETs", description="P-Channel 30V 4A SOT-23", package="SOT-23")
LDO = card(["GND", "VOUT", "VIN"], mpn="AMS1117-3.3", category="Linear Voltage Regulators (LDO)", description="1A 3.3V SOT-223")


def test_supply_no_source_a_rail_nothing_feeds():
    nodes = [{"id": "U2", "kind": "chip", "lcsc": "C92489"}, {"id": "C1", "kind": "capacitor"}]
    bare = [{"name": "GND", "pins": ["U1.GND", "U2.GND", "C1.2"]}, {"name": "V3V3", "pins": ["U2.VDD", "C1.1"]}]
    f = one(run(nodes, bare, {"U2": BME280}), "supply_no_source")
    assert f["severity"] == "error" and f["ref"] == "V3V3" and "U2.VDD, C1.1" in f["msg"] and f["hint"].startswith("Connect U1.V3V3 to V3V3")
    assert not run(nodes, [bare[0], {"name": "V3V3", "pins": ["U1.V3V3", "U2.VDD", "U2.VDDIO", "C1.1"]}], {"U2": BME280})
    # a regulator's output, a diode from a source and a battery's + feed a rail; a divider tap named like one is no rail
    reg = run([*nodes, {"id": "U3", "kind": "chip", "lcsc": "C6186"}],
              [{"name": "GND", "pins": ["U1.GND", "U2.GND", "C1.2", "U3.GND"]}, {"name": "V5", "pins": ["U1.V5", "U3.VIN"]}, {"name": "V3V3", "pins": ["U3.VOUT", "U2.VDD", "C1.1"]}],
              {"U2": BME280, "U3": LDO})
    assert "supply_no_source" not in {x["code"] for x in reg}
    vled = [{"name": "GND", "pins": ["U1.GND", "C1.2"]}, {"name": "V5", "pins": ["U1.V5", "D1.A"]}, {"name": "VLED", "pins": ["D1.K", "C1.1"]}]
    assert not run([nodes[1], {"id": "D1", "kind": "diode"}], vled)
    f = one(run([nodes[1]], [vled[0], {"name": "VLED", "pins": ["C1.1"]}]), "supply_no_source")
    assert "a diode from one (A on V5, K on VLED)" in f["hint"]
    assert not run([{"id": "J1", "kind": "jst", "label": "LiPo"}, nodes[1]], [{"name": "GND", "pins": ["U1.GND", "J1.P2", "C1.2"]}, {"name": "VBAT", "pins": ["J1.P1", "C1.1"]}])
    tap = run([{"id": "R1", "kind": "resistor"}, {"id": "R2", "kind": "resistor"}],
              [{"name": "V3V3", "pins": ["U1.V3V3", "R1.1"]}, {"name": "VBAT_SENSE", "pins": ["R1.2", "R2.1", "U1.D0"]}, {"name": "GND", "pins": ["U1.GND", "R2.2"]}])
    assert "supply_no_source" not in {x["code"] for x in tap}


def test_load_unpowered_leds_behind_a_low_side_switch_only():
    nodes = [{"id": "Q1", "kind": "chip", "lcsc": "C181090"}, {"id": "R7", "kind": "resistor", "value": "100R"}, {"id": "R8", "kind": "resistor", "value": "100k"},
             {"id": "R3", "kind": "resistor", "value": "47R"}, {"id": "R4", "kind": "resistor", "value": "47R"}, {"id": "LED1", "kind": "led"}, {"id": "LED2", "kind": "led"}]
    gate = [{"pins": ["U1.D10", "R7.1"]}, {"pins": ["R7.2", "Q1.G", "R8.1"]}]
    wrong = [*gate, {"name": "GND", "pins": ["U1.GND", "Q1.S", "R8.2", "LED1.K", "LED2.K"]}, {"pins": ["Q1.D", "R3.2", "R4.2"]},
             {"pins": ["R3.1", "LED1.A"]}, {"pins": ["R4.1", "LED2.A"]}]
    f = one(run(nodes, wrong, {"Q1": NMOS}), "load_unpowered")
    assert f["ref"] == "LED1" and "LED1, LED2 are never powered" in f["msg"] and "Q1's drain is a low-side switch" in f["msg"]
    assert "the A side (through each resistor) to V3V3 or V5, the K to Q1.D, Q1.S to GND" in f["hint"]
    right = [*gate, {"name": "GND", "pins": ["U1.GND", "Q1.S", "R8.2"]}, {"name": "V5", "pins": ["U1.V5", "R3.1", "R4.1"]},
             {"pins": ["R3.2", "LED1.A"]}, {"pins": ["R4.2", "LED2.A"]}, {"pins": ["LED1.K", "LED2.K", "Q1.D"]}]
    assert "load_unpowered" not in {x["code"] for x in run(nodes, right, {"Q1": NMOS})}
    # through a P-MOSFET high-side switch from V5 the LEDs are fed
    high = [*gate, {"name": "GND", "pins": ["U1.GND", "R8.2", "LED1.K", "LED2.K"]}, {"name": "V5", "pins": ["U1.V5", "Q1.S"]}, {"pins": ["Q1.D", "R3.2", "R4.2"]},
            {"pins": ["R3.1", "LED1.A"]}, {"pins": ["R4.1", "LED2.A"]}]
    assert "load_unpowered" not in {x["code"] for x in run(nodes, high, {"Q1": PMOS})}
    # a chip whose VDD is on a net nothing feeds
    lone = run([{"id": "U2", "kind": "chip", "lcsc": "C92489"}, {"id": "C1", "kind": "capacitor"}],
               [{"name": "GND", "pins": ["U1.GND", "U2.GND", "C1.2"]}, {"pins": ["U2.VDD", "C1.1"]}], {"U2": BME280})
    assert one(lone, "load_unpowered")["ref"] == "U2"


def test_diode_to_ground_and_across_the_rail():
    nodes = [{"id": "Q1", "kind": "chip", "lcsc": "C2146"}, {"id": "R1", "kind": "resistor", "value": "1k"}, {"id": "BZ1", "kind": "chip", "lcsc": "C96127"},
             {"id": "D1", "kind": "diode"}]
    parts = {"Q1": NPN, "BZ1": MAG_BUZZER}
    grounded = run(nodes, [*SWITCHED[1:], {"name": "GND", "pins": ["U1.GND", "Q1.E", "D1.K"]}, {"name": "V5", "pins": ["U1.V5", "BZ1.P1"]},
                           {"pins": ["BZ1.P2", "Q1.C", "D1.A"]}], parts)
    f = one(grounded, "diode_to_ground")
    assert f["severity"] == "error" and "whenever Q1 is off the diode conducts, so BZ1 is always on" in f["msg"] and "D1.K on V5" in f["hint"]
    across = run(nodes, [*SWITCHED, {"name": "V5", "pins": ["U1.V5", "BZ1.P1", "D1.K"]}, {"pins": ["BZ1.P2", "Q1.C"]}, {"name": "GND", "pins": ["D1.A"]}], parts)
    f = one(across, "diode_across_rail")
    assert f["severity"] == "warning" and "never conducts" in f["msg"] and "put it across BZ1: D1.A on BZ1.P2/Q1.C (the switched side), D1.K on V5" in f["hint"]
    short = run([{"id": "D1", "kind": "diode"}], [{"name": "V3V3", "pins": ["U1.V3V3", "D1.A"]}, {"name": "GND", "pins": ["U1.GND", "D1.K"]}])
    assert one(short, "diode_across_rail")["severity"] == "error" and "shorts the supply" in one(short, "diode_across_rail")["msg"]
    # a TVS clamp across the rail is what it should be
    tvs = card(["A", "K"], mpn="SMBJ5.0A", category="TVS", description="5V TVS diode")
    assert not run([{"id": "D2", "kind": "chip", "lcsc": "C5"}], [{"name": "V5", "pins": ["U1.V5", "D2.K"]}, {"name": "GND", "pins": ["U1.GND", "D2.A"]}], {"D2": tvs})


def test_never_raises_on_odd_documents():
    assert device_rules.check(None, None) == [] and device_rules.check({"nodes": "x", "nets": 3}, {}) == []
    odd = {"nodes": [{"id": "U9", "kind": "module", "module": "nope"}, {"id": "Q1", "kind": "chip"}, {"kind": "led"}],
           "nets": [{"pins": ["Q1.X", "U9.D0", "nobody.P1", 7]}, "junk"]}
    assert isinstance(device_rules.check(odd, {"Q1": {"error": "no footprint"}}), list)


# ---------------------------------------------------------------- the devices that shipped broken
def raw(code):
    return json.loads((FIX.parent / "easyeda" / f"{code}.json").read_text(encoding="utf-8"))


def stored(doc):
    """The rules on a stored graph with its chips' cards as the designer saw them: the JLCPCB card, the pins of the cached
    EasyEDA entry (catalog.pins_of) labelled as catalog.info labelled them then (first runs, commit 18c5201: '+' was P, '-'
    P_2; the round-2 runs' parts carry the newer labels POS/NEG, B/E/C and kind_hint / current_ma), and the entry itself.
    Nothing goes online and nothing is resolved again, so a later relabelling does not change what the designer wired."""
    doc, _ = device.normalize(copy.deepcopy(doc))
    parts = {}
    for n in doc["nodes"]:
        if n["kind"] == "chip":
            entry = raw(n["lcsc"])
            assert [(p["num"], p["name"]) for p in CARDS[n["lcsc"]]["pins"]] == [(p["num"], p["name"]) for p in catalog.pins_of(entry)]
            parts[n["id"]] = {**copy.deepcopy(CARDS[n["lcsc"]]), "raw": entry}
    return device_rules.check(doc, parts)


def test_soil_sensor_buzzer_unwired_and_s8050_turned_round():
    found = stored(GRAPHS["soil_moisture"]["doc"])
    errors = codes(found, "error")
    assert ("buzzer_unwired", "BZ1") in errors and ("bjt_reversed", "Q1") in errors
    q1 = next(f for f in found if f["code"] == "bjt_reversed")
    assert "emitter Q1.P2 on V3V3" in q1["msg"] or "emitter Q1.E on V3V3" in q1["msg"]
    assert "on GND" in q1["msg"].split("collector", 1)[1]


def test_leak_sensor_lipo_on_v5_and_30ma_buzzer_on_a_pin():
    found = stored(GRAPHS["leak_sensor"]["doc"])
    assert {("battery_raw", "J_BAT"), ("gpio_overload", "BZ1")} <= set(codes(found, "error"))
    assert "U1.V5" in one(found, "battery_raw")["msg"] and "30 mA" in one(found, "gpio_overload")["msg"]


def test_night_light_ws2812_on_5v_with_3v3_data():
    found = stored(GRAPHS["night_light"]["doc"])
    assert one(found, "ws2812_level")["ref"] == "LED1" and not codes(found, "error")


def test_dice_button_and_buzzer_on_strapping_pins():
    found = stored(GRAPHS["dice"]["doc"])
    straps = {f["ref"] for f in found if f["code"] == "strapping_pin"}
    assert {"U1.SCK", "U1.MISO"} <= straps and not codes(found, "error")


def test_kitchen_timer_active_buzzer_on_a_pin_is_a_doubt():
    found = stored(GRAPHS["kitchen_timer"]["doc"])
    assert one(found, "gpio_overload")["severity"] == "warning" and not codes(found, "error")


def test_leak_sensor_2_flyback_diode_with_its_cathode_on_no_net():
    found = stored(GRAPHS["leak_sensor_2"]["doc"])
    assert codes(found, "error") == [("floating_pin", "D1")]
    f = one(found, "floating_pin")
    assert "D1.K is on no net" in f["msg"] and "wire D1.K to V3V3 (the side BZ1's + is on)" in f["hint"]


def test_night_light_2_ldr_reading_rises_with_light():
    found = stored(GRAPHS["night_light_2"]["doc"])
    f = one(found, "sensor_divider")
    assert f["ref"] == "ALS1" and "between V3V3 and U1.D1 (GPIO3) with R_ALS (10k) to GND" in f["msg"] and "RISES with light" in f["msg"]
    assert f["data"] == {"pin": "U1.D1", "alias": "D1", "gpio": 3, "quantity": "light", "rises": True}
    assert not codes(found, "error")


def test_night_light_3_leds_behind_q1_and_a_v3v3_nothing_feeds():
    # these graphs also name a warm light and order another colour: led_colour has its own test (test_firmware_sim)
    v1 = [f for f in stored(GRAPHS["night_light_3_v1"]["doc"]) if f["code"] != "led_colour"]
    assert [c for c in codes(v1, "error") if c[0] != "accessory_supply"] == [("load_unpowered", "LED1")] and "LED1, LED2, LED3, LED4 are never powered" in one(v1, "load_unpowered")["msg"]
    v2 = [f for f in stored(GRAPHS["night_light_3_v2"]["doc"]) if f["code"] != "led_colour"]
    assert [c for c in codes(v2, "error") if c[0] != "accessory_supply"] == [("load_unpowered", "LED1"), ("supply_no_source", "V3V3")]
    f = one(v2, "supply_no_source")
    assert "U2.VCC, U2.DVI, C1.1, C2.1, R1.1, R2.1" in f["msg"] and f["hint"].startswith("Connect U1.V3V3 to V3V3")
    assert not codes([f for f in stored(GRAPHS["night_light_3_fixed"]["doc"]) if f["code"] != "led_colour"], "error")


def test_timer_3_flyback_diode_to_ground():
    found = stored(GRAPHS["timer_3_v5"]["doc"])
    assert codes(found, "error") == [("diode_to_ground", "D1")] and "BZ1 is always on" in one(found, "diode_to_ground")["msg"]
    assert not codes(stored(GRAPHS["timer_3_fixed"]["doc"]), "error")


def test_leak_3_diode_across_the_3v3_rail():
    found = stored(GRAPHS["leak_3_v4"]["doc"])
    f = one(found, "diode_across_rail")
    assert f["severity"] == "warning" and "K on V3V3, A on GND" in f["msg"] and "put it across BZ1" in f["hint"] and not codes(found, "error")
    assert not codes(stored(GRAPHS["leak_3_fixed"]["doc"]), "error")


def test_the_reference_device_passes():
    assert stored(device_prompt.EXAMPLE_DOC) == []


# ---------------------------------------------------------------- the round-4 devices, on the cards as catalog.info gives them now
def fresh(doc):
    """The rules on a stored graph with its chips' cards relabelled as catalog.info labels them now (catalog.card_pins on
    the cached EasyEDA entry): the designer wired 'LED1.P2' and 'BZ1.P1' against numbered pins, which are A/K and POS/NEG
    since the symbol's triangle and the buzzer's '+' mark are read."""
    doc, _ = device.normalize(copy.deepcopy(doc))
    parts = {}
    for n in doc["nodes"]:
        if n["kind"] == "chip":
            entry, c = raw(n["lcsc"]), copy.deepcopy(CARDS[n["lcsc"]])
            c["pins"], c["pin_note"] = catalog.card_pins(entry, c, c.get("kind_hint") or catalog.kind_of(c))
            parts[n["id"]] = {**c, "raw": entry}
    return device_rules.check(doc, parts), parts


def test_night_light_4_warm_white_2835_leds_behind_q1_are_fine():
    """3 x C210315 from V5 (their P2, now A) through 33R each to an AO3400's drain: not turned round, and judged against
    their rated 60 mA at the card's 3.2 V Vf (about 55 mA), not a GPIO's 20 mA."""
    found, parts = fresh(GRAPHS["night_light_4"]["doc"])
    assert [p["label"] for p in parts["LED1"]["pins"]] == ["K", "A"] and "diode triangle" in parts["LED1"]["pin_note"]
    assert found == []


def test_leak_4_a_2v_4v_buzzer_on_the_5v_rail():
    found, parts = fresh(GRAPHS["leak_4"]["doc"])
    assert [p["label"] for p in parts["BZ1"]["pins"]] == ["POS", "NEG"]
    # and nothing across it: the electromagnetic buzzer's flyback diode is missing too
    assert sorted(codes(found)) == [("flyback_diode", "BZ1"), ("supply_range", "BZ1")]
    f = one(found, "supply_range")
    assert f["severity"] == "error" and "BZ1.POS is on VBUS (5 V)" in f["msg"] and "rated 2-4 V" in f["msg"] and "V3V3" in f["hint"]


def test_round_4_timer_soil_and_dice_stay_clean():
    """The same buzzer on V3V3 (timer), the YX-YT9042 behind an S8050 (soil), the dice: nothing to say."""
    for key in ("timer_4", "soil_4", "dice_4"):
        assert fresh(GRAPHS[key]["doc"])[0] == [], key


def test_a_socket_must_be_reachable():
    jack = card(["1", "2", "3"], labels=["P1", "P2", "P3"], mpn="PJ-320A", category="Audio Connectors", description="3.5mm Headphone Jack Right-Angle")
    wires = [{"name": "GND", "pins": ["U1.GND", "J1.P1"]}]
    inside = run([{"id": "J1", "kind": "chip", "lcsc": "C2884926"}], wires, {"J1": jack})
    assert ("socket_unreachable", "J1") in codes(inside, "error")
    lid = run([{"id": "J1", "kind": "chip", "lcsc": "C2884926", "face": "hole"}], wires, {"J1": jack})
    assert "opens sideways" in one(lid, "socket_unreachable")["msg"]
    assert ("socket_unreachable", "J1") not in codes(run([{"id": "J1", "kind": "chip", "lcsc": "C2884926", "edge": "-y"}], wires, {"J1": jack}))
