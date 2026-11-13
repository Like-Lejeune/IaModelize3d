"""The device compiler's placement and what it tells the case (device.py, accessories.py, deviceapi.bom_of; contracts C1,
C2, C5): layouts and designer placements become fixed positions, faces become board.json access, accessories put their
connector on the carrier and their body into board.json and the quote, connectors on an edge open outwards, decoupling
is asked of ICs only, and pin names saved before the catalogue renamed pins still wire. The 2026-11-03 night light and
leak sensor graphs, whose bodies were packed onto each other, build clean through the real bundle.

The catalogue is stubbed from the EasyEDA entries in tests/fixtures/easyeda; nothing goes online."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from iamodelize3d import accessories, catalog, device, pcb
from iamodelize3d.config import REPO_DIR
from iamodelize3d.deviceapi import bom_of, pad_count
from iamodelize3d.pcb import PcbPool

FIX = Path(__file__).parent / "fixtures" / "device"
RAW = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (FIX.parent / "easyeda").glob("C*.json")}
GRAPHS = {k: v for k, v in json.loads((FIX / "regressions.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}


def card_of(code: str) -> dict:
    """A part card as catalog.info gives it, from the EasyEDA entry alone (no JLCPCB card: no category)."""
    raw = RAW[code]
    pins = catalog.pins_of(raw)
    labels = catalog.labels_of(pins)
    head = raw["dataStr"]["head"]["c_para"]
    n, tht = catalog.smd_of(raw)
    return {"lcsc": code, "mpn": head.get("Manufacturer Part"), "package": head.get("package"), "stock": 1000, "basic": False,
            "prices": [{"qty": 1, "usd": 0.2}], "description": raw.get("title") or "", "category": None,
            "pins": [{"num": p["num"], "name": p["name"], "label": labels[f"pin{p['num']}"]} for p in pins],
            "size_mm": catalog.size_of(raw), "height_mm": catalog.height_of(raw), "pads": n, "tht": tht}


@pytest.fixture
def catalogue(monkeypatch):
    cards: dict[str, dict] = {}

    async def info(code):
        if code in cards:
            return copy.deepcopy(cards[code])
        if code not in RAW:
            raise catalog.CatalogError(f"{code} has no EasyEDA footprint")
        return card_of(code)

    async def easyeda(code):  # a made-up card borrows the footprint of the part it was copied from
        return RAW.get(code) or RAW.get((cards.get(code) or {}).get("footprint_of"))

    async def basic(kind, value="", package="0603", color=""):
        return {"lcsc": {"resistor": "C23162", "capacitor": "C14663", "led": "C12624", "header": "C2337"}.get(kind, "C1"), "mpn": kind,
                "basic": True, "stock": 10_000, "prices": [{"qty": 1, "usd": 0.04 if kind == "header" else 0.01}]}

    monkeypatch.setattr(catalog, "info", info)
    monkeypatch.setattr(catalog, "easyeda", easyeda)
    monkeypatch.setattr(catalog, "resolve_basic", basic)
    return cards


def dice_doc() -> dict:
    leds = [f"LED{i}" for i in range(1, 8)]
    nodes = [{"id": "U1", "kind": "module", "module": "113991054"}, {"id": "SW1", "kind": "button", "label": "roll"}]
    nodes += [{"id": f"LED{i}", "kind": "led", "color": "red"} for i in range(1, 8)]
    nodes += [{"id": f"R{i}", "kind": "resistor", "value": "1k"} for i in range(1, 8)]
    gpio = ["D0", "D1", "D2", "D3", "D8", "D9", "D10"]
    nets = [{"name": "GND", "pins": ["U1.GND", "SW1.B"] + [f"LED{i}.K" for i in range(1, 8)]}, {"pins": ["U1.D6", "SW1.A"]}]
    nets += [{"pins": [f"U1.{g}", f"R{i}.1"]} for i, g in zip(range(1, 8), gpio)]
    nets += [{"pins": [f"R{i}.2", f"LED{i}.A"]} for i in range(1, 8)]
    return {"title": "Dice", "board": {"holes": True}, "nodes": nodes, "nets": nets,
            "layouts": [{"pattern": "dice", "nodes": leds, "center": [0, -6], "pitch": 7}],
            "requirements": [{"id": "R1", "text": "seven pips show a die face", "parts": leds + ["NOPE"], "firmware": True}, "a roll button"]}


# ---------------------------------------------------------------- the document
def test_layouts_expand_to_places_in_the_dice_order():
    doc, issues = device.normalize(dice_doc())
    # a part a requirement names but the graph lacks stays named, and is called out
    assert [(i["code"], i["ref"]) for i in issues] == [("requirement_part_missing", "R1")] and "NOPE" in issues[0]["msg"]
    lay = doc["layouts"][0]
    assert lay == {"pattern": "dice", "nodes": [f"LED{i}" for i in range(1, 8)], "center": [0.0, -6.0], "pitch": 7.0, "rot": 0.0}
    at = device.places(doc)
    # centre, top-left, top-right, middle-left, middle-right, bottom-left, bottom-right
    want = [(0, -6), (-7, 1), (7, 1), (-7, -6), (7, -6), (-7, -13), (7, -13)]
    assert [(at[f"LED{i}"]["x"], at[f"LED{i}"]["y"]) for i in range(1, 8)] == want
    assert doc["requirements"] == [{"id": "R1", "text": "seven pips show a die face", "parts": [f"LED{i}" for i in range(1, 8)] + ["NOPE"], "firmware": True},
                                   {"id": "R2", "text": "a roll button", "parts": []}]
    # the other patterns, and a turned one
    row = device.layout_places({"pattern": "row", "nodes": ["A", "B", "C"], "center": [0, 0], "pitch": 5, "rot": 0})
    assert [(p["x"], p["y"]) for p in row.values()] == [(-5, 0), (0, 0), (5, 0)]
    col = device.layout_places({"pattern": "column", "nodes": ["A", "B"], "center": [1, 1], "pitch": 4, "rot": 0})
    assert [(p["x"], p["y"]) for p in col.values()] == [(1, 3), (1, -1)]
    grid = device.layout_places({"pattern": "grid", "nodes": list("ABCD"), "center": [0, 0], "pitch": 6, "rot": 0})
    assert [(p["x"], p["y"]) for p in grid.values()] == [(-3, 3), (3, 3), (-3, -3), (3, -3)]
    ring = device.layout_places({"pattern": "ring", "nodes": list("ABCD"), "center": [0, 0], "pitch": 8, "radius": 10, "rot": 0})
    assert [(p["x"], p["y"]) for p in ring.values()] == [(0, 10), (10, 0), (0, -10), (-10, 0)]  # clockwise from the top
    turned = device.layout_places({"pattern": "row", "nodes": ["A", "B"], "center": [0, 0], "pitch": 10, "rot": 90})
    assert [(p["x"], p["y"], p["rot"]) for p in turned.values()] == [(0, -5, 90), (0, 5, 90)]


def test_normalize_keeps_place_face_and_accessories_and_names_what_it_drops():
    doc, issues = device.normalize({"title": "x", "nodes": [
        {"id": "LED1", "kind": "led", "place": {"x": 3, "y": -4.25, "rot": 45}, "face": "light"},
        {"id": "LED2", "kind": "led", "place": [1, 2], "face": "loud"},
        {"id": "LED3", "kind": "led", "place": {"x": 300, "y": 0}},
        {"id": "D1", "kind": "accessory", "accessory": "OLED 0.96"},
        {"id": "P1", "kind": "accessory", "accessory": "ds18b20_probe"},
        {"id": "X1", "kind": "accessory", "accessory": "flux capacitor"}],
        "layouts": [{"pattern": "spiral", "nodes": ["LED1"]}, {"pattern": "row", "nodes": ["LED1", "GHOST"]}],
        "nets": [{"pins": ["D1.SDA", "P1.DATA"]}],
        "firmware": {"lang": "arduino", "files": {"main.ino": "void setup(){}"}, "check": {"ok": True, "tool": "arduino-cli", "errors": []}}})
    by = {n["id"]: n for n in doc["nodes"]}
    assert by["LED1"]["place"] == {"x": 3.0, "y": -4.25, "rot": 45.0} and by["LED1"]["face"] == "light"
    assert by["LED2"]["place"] == {"x": 1.0, "y": 2.0, "rot": 0.0} and "face" not in by["LED2"]
    assert "place" not in by["LED3"]
    assert by["D1"]["accessory"] == "oled_096_i2c" and "edge" not in by["D1"]  # sits on the board
    assert by["P1"]["edge"] == "-y"  # a lead leaves through a wall
    assert doc["nets"][0]["pins"] == ["D1.SDA", "P1.DQ"]  # DATA is the probe's DQ
    assert doc["layouts"] == [{"pattern": "row", "nodes": ["LED1"], "center": [0.0, 0.0], "pitch": 8.0, "rot": 0.0}]
    assert doc["firmware"]["check"]["tool"] == "arduino-cli"
    assert sorted(i["code"] for i in issues) == ["bad_face", "bad_layout", "bad_place", "unknown_accessory"]


def test_modules_say_their_gpio_numbers_and_strapping_pins():
    c3, s3, pico = device.MODULES["113991054"], device.MODULES["113991114"], device.MODULES["SC0915"]
    assert c3["gpio"] == {"D0": 2, "D1": 3, "D2": 4, "D3": 5, "SDA": 6, "SCL": 7, "TX": 21, "RX": 20, "SCK": 8, "MISO": 9, "MOSI": 10}
    assert c3["strapping"] == [2, 8, 9] and s3["strapping"] == [0, 3, 45, 46] and s3["gpio"]["TX"] == 43 and s3["gpio"]["RX"] == 44
    assert pico["gpio"]["GP22"] == 22 and "BAT" in c3["battery"] and "V5" in c3["battery"]
    out, _ = device.normalize({"title": "x", "nodes": [{"id": "U1", "kind": "module", "module": "113991054"}, {"id": "R1", "kind": "resistor"}],
                               "nets": [{"pins": ["U1.GPIO21", "R1.1"]}]})
    assert out["nets"][0]["pins"] == ["U1.TX", "R1.1"]
    lib = device.library()
    assert lib["modules"][0]["gpio"]["D0"] == 2 and {a["key"] for a in lib["accessories"]} == set(accessories.ACCESSORIES)
    assert all(a["pins"] and a["note"] for a in lib["accessories"])


# ---------------------------------------------------------------- compile
async def test_designer_places_compile_as_fixed_positions_and_the_persons_pcb_wins(catalogue):
    raw = dice_doc()
    next(n for n in raw["nodes"] if n["id"] == "SW1")["place"] = {"x": 0, "y": -22, "rot": 90}
    next(n for n in raw["nodes"] if n["id"] == "LED7")["pcb"] = {"x": 9, "y": -14, "rot": 0}
    doc, _ = device.normalize(raw)
    parts, _ = await device.resolve(doc)
    W, H = device.estimate(doc, parts)
    assert W >= 2 * (7 + 2.96 / 2) and H / 2 >= 22 + 7 / 2  # the button's fixed spot (turned: 9 x 7) lies on the board
    c = device.compile(doc, parts, (W, H))
    assert c["placed"]["LED1"] == {"pcbX": 0, "pcbY": -6, "pcbRotation": 0} and c["placed"]["LED2"] == {"pcbX": -7, "pcbY": 1, "pcbRotation": 0}
    assert c["placed"]["SW1"] == {"pcbX": 0, "pcbY": -22, "pcbRotation": 90}
    assert c["placed"]["LED7"] == {"pcbX": 9, "pcbY": -14, "pcbRotation": 0}  # the person's pcb over the layout
    assert '<led name="LED2" color="red" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C12624"] }} pcbX={-7} pcbY={1} />' in c["source"]
    assert "pcbPack" not in c["source"] and not c.get("unplaced")  # the resistors get their spots from the placer, by their LEDs
    for i in range(1, 8):
        led, r = c["placed"][f"LED{i}"], c["placed"][f"R{i}"]
        assert math.hypot(r["pcbX"] - led["pcbX"], r["pcbY"] - led["pcbY"]) < 7, (f"R{i}", r, led)


def test_faces_default_from_the_part_and_the_designer_overrides():
    node = lambda k="chip", **kw: {"id": "X", "kind": k, **kw}  # noqa: E731
    assert device.face_of(node("led")) == "light" and device.face_of(node("led", face="none")) == "none"
    assert device.face_of(node(), {"mpn": "XL-5050RGBC-2812B", "description": "XL-5050RGBC-WS2812B"}) == "light"
    assert device.face_of(node(), {"kind_hint": "rgb_led"}) == "light" and device.face_of(node(), {"kind_hint": "buzzer_active"}) == "sound"
    assert device.face_of(node(), {"mpn": "MLT-9650", "package": "BUZ-SMD_L9.6-W9.6-LS10.0-R"}) == "sound"
    assert device.face_of(node(), {"mpn": "AM312", "package": "TO-5-3_L8.2-W8.2"}) == "sensor"
    assert device.face_of(node(), {"mpn": "BH1750FVI-TR", "description": "Ambient Light Sensors"}) == "sensor"
    assert device.face_of(node(), {"mpn": "BME280", "description": "Humidity Sensors"}) == "sensor"
    assert device.face_of(node(), {"mpn": "2N7002", "category": "Transistors"}) == "none"
    assert device.face_of(node(), {"mpn": "TLC5940", "description": "LED driver"}) == "none"
    assert device.face_of({"id": "D1", "kind": "accessory", "accessory": "oled_096_i2c"}) == "display"


async def test_decoupling_is_asked_of_ics_not_of_buzzers_transistors_or_leds(catalogue):
    doc, _ = device.normalize(GRAPHS["leak_sensor_2"])
    doc["nodes"] = [n for n in doc["nodes"] if n["id"] != "C1"]
    doc["nets"] = [{**n, "pins": [p for p in n["pins"] if not p.startswith("C1.")]} for n in doc["nets"]]
    parts, _ = await device.resolve(doc)
    assert not any(w["code"] == "decoupling" for w in device.lint(doc, parts))  # BZ1 (2 pins), Q1 (2N7002)
    assert device.needs_decoupling({"kind_hint": "ic"}) and not device.needs_decoupling({"kind_hint": "nmos", "pins": [{}] * 8})
    assert not device.needs_decoupling({"pins": [{}] * 4, "description": "XL-5050RGBC-WS2812B"})
    assert device.needs_decoupling({"pins": [{}] * 8, "description": "1.71V~3.6V I2C SPI"})


async def test_supply_capacitors_hang_off_the_wide_chain_at_their_chip(catalogue):
    doc, _ = device.normalize(GRAPHS["night_light_1"])
    parts, _ = await device.resolve(doc)
    assert device.bulky(parts["U2"]) and not device.bulky(parts["LED1"]) and not device.bulky(parts["U3"])
    src = device.compile(doc, parts, device.estimate(doc, parts))["source"]
    # V5: module -> LED1 -> LED2 -> LED3 -> J1, the capacitor by its own trace to the LED it decouples
    assert '<trace from=".C4 > .pin1" to=".LED1 > .VDD" thickness="0.4mm" />' in src
    assert '<trace from=".LED3 > .VDD" to=".C4 > .pin1"' not in src
    # the PIR (a TO-5 can over three pads) with its capacitor at its supply pin, tied to its pins
    assert '<group' not in src and '<trace from=".C3 > .pin1" to=".U2 > .VCC" />' in src and '<trace from=".C3 > .pin2" to=".U2 > .GND" />' in src
    assert "maxDecouplingTraceLength={16}" in next(ln for ln in src.splitlines() if 'name="C3"' in ln)
    plan, _ = device.decoupling(doc, parts)
    small = next(c for c, *_ in plan["U3"])
    assert "maxDecouplingTraceLength={10}" in next(ln for ln in src.splitlines() if f'name="{small}"' in ln)  # a small IC's as ever


async def test_edge_connectors_open_outwards(catalogue):
    nodes = [{"id": "U1", "kind": "module", "module": "113991054"}] + [{"id": f"J{i}", "kind": "jst", "edge": e} for i, e in enumerate(device.EDGES)]
    doc, _ = device.normalize({"title": "x", "nodes": nodes, "nets": [{"name": "GND", "pins": ["U1.GND"] + [f"J{i}.2" for i in range(4)]}]})
    parts, _ = await device.resolve(doc)
    c = device.compile(doc, parts, (50, 50))
    # jst*_ph opens to +y at rotation 0 (tscircuit's insertion direction): turned towards each edge, 2.6 mm in
    assert {e: c["placed"][f"J{i}"]["pcbRotation"] for i, e in enumerate(device.EDGES)} == {"-x": 90, "+x": 270, "-y": 180, "+y": 0}
    assert c["placed"]["J1"]["pcbX"] == 25 - 2.6


def test_an_edge_connector_with_face_none_is_no_wall_port():
    doc, _ = device.normalize({"title": "x", "nodes": [{"id": "J1", "kind": "jst", "edge": "+x", "face": "none", "label": "cell"},
                                                     {"id": "J2", "kind": "jst", "edge": "-x"}], "nets": []})
    cj = [{"type": "pcb_board", "center": {"x": 0, "y": 0}, "width": 40, "height": 30},
          {"type": "source_component", "source_component_id": "s1", "name": "J1"}, {"type": "source_component", "source_component_id": "s2", "name": "J2"},
          {"type": "pcb_component", "source_component_id": "s1", "center": {"x": 17.4, "y": 0}, "rotation": 270},
          {"type": "pcb_component", "source_component_id": "s2", "center": {"x": -17.4, "y": 0}, "rotation": 90}]
    port = {"type": "jst_ph_2p", "side": "top", "access": "port", "at": 15, "w": 6.9, "h": 6, "d": 5.5, "z0": 0, "protrude": -0.4, "plug": None}
    board = {"components": [{"id": "J1", "edge": "+x", **port}, {"id": "J2", "edge": "-x", **port}]}
    device.dress_board(board, doc, {}, cj)
    j1, j2 = board["components"]
    assert j1["access"] == "none" and (j1["x"], j1["y"], j1["w"], j1["d"]) == (37.4, 15, 5.5, 6.9) and "edge" not in j1
    assert j2["access"] == "port" and j2["edge"] == "-x"


# ---------------------------------------------------------------- accessories
def oled_doc() -> dict:
    return {"title": "Thermometer", "board": {"holes": True}, "nodes": [
        {"id": "U1", "kind": "module", "module": "113991054"},
        {"id": "D1", "kind": "accessory", "accessory": "oled_096_i2c", "label": "screen"},
        {"id": "P1", "kind": "accessory", "accessory": "ds18b20_probe"},
        {"id": "B1", "kind": "accessory", "accessory": "lipo_1s_500"},
        {"id": "R1", "kind": "resistor", "value": "4.7k", "label": "DQ pull-up"},
        {"id": "J1", "kind": "jst", "edge": "+x"}],
        "nets": [{"name": "GND", "pins": ["U1.GND", "D1.GND", "P1.GND", "J1.2"]}, {"name": "V3V3", "pins": ["U1.3V3", "D1.VCC", "P1.VCC", "R1.1"]},
                 {"name": "SDA", "pins": ["U1.SDA", "D1.SDA"]}, {"name": "SCL", "pins": ["U1.SCL", "D1.SCL"]},
                 {"pins": ["U1.D0", "P1.DQ", "R1.2"]}, {"name": "VBUS", "pins": ["U1.5V", "J1.1"]}]}


async def test_accessories_put_their_connector_on_the_carrier(catalogue):
    doc, issues = device.normalize(oled_doc())
    assert issues == []
    parts, _ = await device.resolve(doc)
    assert parts["D1"]["accessory"] == "oled_096_i2c" and parts["D1"]["connector"]["lcsc"] == "C2337" and "connector" not in parts["B1"]
    assert device.lint(doc, parts) == []
    W, H = device.estimate(doc, parts)
    assert W >= 27.3 + 4 and H >= 21 + 27.8 + 8
    c = device.compile(doc, parts, (W, H))
    src = c["source"]
    # the OLED: its header row where the module's pins land, its body a courtyard the packer keeps clear, centred low
    d1 = next(ln for ln in src.splitlines() if 'name="D1"' in ln)
    assert 'pinLabels={{ pin1: "GND", pin2: "VCC", pin3: "SCL", pin4: "SDA" }}' in d1 and "<courtyardrect" in d1 and "width={27.3} height={27.8}" in d1
    body = device.accessory_places(doc, parts, W, H)["D1"]
    assert body["x"] == 0 and body["y"] - 27.8 / 2 >= -H / 2 + 1 and c["placed"]["D1"]["pcbY"] == round(body["y"] + 12.4, 2)
    assert '<pinheader name="P1" pinCount={3} pitch="2.54mm" pinLabels={["GND", "DQ", "VCC"]}' in src and c["placed"]["P1"]["pcbY"] == -(H / 2 - 2.5)
    assert 'name="B1"' not in src and ".B1 >" not in src  # a cell on the XIAO's BAT pads puts nothing on the carrier
    assert '<trace from=".D1 > .SDA" to="net.SDA" />' in src and c["intent"]["edge"]["P1"] == "-y"
    # a cell wired to the carrier's nets is called out, and left out
    bad, _ = device.normalize({**oled_doc(), "nets": oled_doc()["nets"] + [{"name": "VBUS", "pins": ["B1.BAT+"]}]})
    assert [w["code"] for w in device.lint(bad, parts)] == ["battery_wiring"]
    assert ".B1 >" not in device.compile(bad, parts, (W, H))["source"]


async def test_accessories_are_priced_hand_fitted_lines(catalogue):
    doc, _ = device.normalize(oled_doc())
    parts, _ = await device.resolve(doc)
    b = bom_of(doc, parts, 5)
    rows = {r.get("accessory") or r["refs"][0] + ":" + r["kind"]: r for r in b["bom"]}
    oled = rows["oled_096_i2c"]
    assert oled["kind"] == "accessory" and oled["name"] == accessories.ACCESSORIES["oled_096_i2c"]["name"] and oled["assembly"] == "hand"
    assert oled["qty"] == 5 and oled["unit_usd"] == 2.5 and oled["total_usd"] == 12.5 and oled["url"]
    assert rows["lipo_1s_500"]["total_usd"] == 15.0 and b["modules"] == 3
    assert b["modules_usd"] == round(5 * (2.5 + 1.6 + 3.0), 3)
    conn = rows["D1:header"]  # its header on the carrier: 4 pins cut from a 1x40 strip
    assert conn["lcsc"] == "C2337" and conn["unit_usd"] == round(0.04 * 4 / 40, 4) and conn["assembly"] == "hand"
    by_id = {n["id"]: n for n in doc["nodes"]}
    assert pad_count(by_id["D1"], parts["D1"]) == 4 and pad_count(by_id["B1"], parts["B1"]) == 2
    assert not any(r["kind"] == "accessory" for r in b["bom"] if r.get("lcsc"))


# ---------------------------------------------------------------- pin names from before the catalogue renamed them
async def test_pin_names_saved_before_the_catalogue_renamed_pins_still_wire(catalogue):
    # MLT-5020: '+' and '-' were both 'P' (one reference for both terminals); S8050: '1' '2' '3' were P1 P2 P3, now B E C
    catalogue["C94598"] = {**card_of("C96127"), "footprint_of": "C96127", "lcsc": "C94598", "mpn": "MLT-5020",
                           "pins": [{"num": "1", "name": "+", "label": "POS"}, {"num": "2", "name": "-", "label": "NEG"}]}
    catalogue["C2150"] = {**card_of("C8545"), "footprint_of": "C8545", "lcsc": "C2150", "mpn": "S8050",
                          "pins": [{"num": "1", "name": "1", "label": "B"}, {"num": "2", "name": "2", "label": "E"}, {"num": "3", "name": "3", "label": "C"}]}
    doc, _ = device.normalize({"title": "x", "nodes": [{"id": "BZ1", "kind": "chip", "lcsc": "C94598"}, {"id": "Q1", "kind": "chip", "lcsc": "C2150"},
                                                     {"id": "R1", "kind": "resistor"}],
                               "nets": [{"name": "V3V3", "pins": ["BZ1.P", "R1.2"]}, {"pins": ["Q1.P1", "R1.1"]}, {"name": "GND", "pins": ["Q1.pin2"]},
                                        {"pins": ["Q1.3", "BZ1.NEG"]}]})
    parts, issues = await device.resolve(doc)
    assert [i["code"] for i in issues] == ["legacy_pin"] and "BZ1.POS" in issues[0]["msg"] and "BZ1.NEG" in issues[0]["msg"]
    nets = [n["pins"] for n in doc["nets"]]
    assert ["BZ1.P", "R1.2"] in nets and ["Q1.B", "R1.1"] in nets and ["Q1.E"] in nets and ["Q1.C", "BZ1.NEG"] in nets
    assert device.chip_labels(parts["BZ1"], "P") == (["POS", "NEG"], "legacy")
    src = device.compile(doc, parts, (30, 30))["source"]
    assert '<trace from=".BZ1 > .POS" to="net.V3V3" />' in src and '<trace from=".BZ1 > .NEG" to="net.V3V3" />' in src  # as before
    assert '<trace from=".Q1 > .B" to=".R1 > .pin1" />' in src


async def test_numbered_led_and_buzzer_pins_wire_by_role_and_by_number(catalogue):
    """C210315 (2835 LED) is K/A and C49246934 (TMB12075 buzzer) POS/NEG since catalog.card_pins reads the symbol's
    triangle and the footprint's '+': graphs written 'LED1.P2' / 'BZ1.P1' still wire, and so do the new names the
    designer reached for first ('BZ1.NEG' once got 'no pin NEG; its pins are P1, P2')."""
    for code, kind in (("C210315", "led"), ("C49246934", "buzzer_active")):
        c = card_of(code)
        c["pins"], c["pin_note"] = catalog.card_pins(RAW[code], c, kind)
        catalogue[code] = c
    doc, _ = device.normalize({"title": "x", "nodes": [{"id": "LED1", "kind": "chip", "lcsc": "C210315"}, {"id": "BZ1", "kind": "chip", "lcsc": "C49246934"},
                                                     {"id": "R1", "kind": "resistor"}],
                               "nets": [{"name": "V5", "pins": ["LED1.P2"]}, {"pins": ["LED1.P1", "R1.1"]}, {"name": "V3V3", "pins": ["BZ1.P1"]},
                                        {"pins": ["BZ1.NEG", "R1.2"]}]})
    parts, issues = await device.resolve(doc)
    assert issues == [] and [p["label"] for p in parts["LED1"]["pins"]] == ["K", "A"] and [p["label"] for p in parts["BZ1"]["pins"]] == ["POS", "NEG"]
    nets = [n["pins"] for n in doc["nets"]]
    assert ["LED1.A"] in nets and ["LED1.K", "R1.1"] in nets and ["BZ1.POS"] in nets and ["BZ1.NEG", "R1.2"] in nets
    assert device.chip_labels(parts["LED1"], "P2") == (["A"], "name") and device.chip_labels(parts["BZ1"], "pin1") == (["POS"], "number")
    src = device.compile(doc, parts, (30, 30))["source"]
    assert '<trace from=".LED1 > .K" to=".R1 > .pin1" />' in src and '<trace from=".BZ1 > .NEG" to=".R1 > .pin2" />' in src


# ---------------------------------------------------------------- the real bundle
DIST = REPO_DIR / "packages" / "pcb" / "dist"
needs_bundle = pytest.mark.skipif(not (DIST / "pcb-worker.mjs").exists(), reason="run `npm ci --ignore-scripts && npm run bundle` in packages/pcb")


@pytest.fixture
async def real_pcb():
    old = pcb._pool
    pcb._pool = PcbPool(1)
    yield
    await pcb._pool.close()
    pcb._pool = old


@needs_bundle
@pytest.mark.parametrize("name", sorted(k for k in GRAPHS if "_r3_" not in k))
async def test_the_graphs_whose_parts_were_packed_onto_each_other_build_clean(name, catalogue, real_pcb, monkeypatch):
    """2026-11-03: a TO-5 PIR, a 9.6 mm buzzer and 5050 LEDs in a group with their capacitors were packed by their pads
    alone, onto their neighbours and over the edge; growing the board 44 -> 74 mm did not help. Through the attempt loop: the
    router may hang a net off a capacitor's far pad (night_light_2, 34 mm), which lifts that limit on the same board."""
    from iamodelize3d import deviceapi

    async def nothing(*a, **k):
        return None

    async def save(project_id, **k):
        return 1

    monkeypatch.setattr(deviceapi.events, "emit", nothing)
    monkeypatch.setattr(deviceapi.pcbapi, "emit_route", nothing)
    monkeypatch.setattr(deviceapi.pcbapi, "emit_version", nothing)
    monkeypatch.setattr(deviceapi.pcb_store, "save", save)
    doc, _ = device.normalize(GRAPHS[name])
    parts, _ = await device.resolve(doc)
    res = await deviceapi.build_device("p_test", copy.deepcopy(GRAPHS[name]))
    b = res["build"]
    assert b["ok"] and not b["errors"] and b["intent"]["ok"], (b["errors"][:3], b["intent"])
    assert res["size_mm"] == list(device.estimate(doc, parts)), res["attempts"]  # the size it asked for
    assert b["counts"]["traces"] >= 15
    board = device.dress_board(b["board"], doc, parts, b["circuit_json"])
    comps = {x["id"]: x for x in board["components"]}
    if name.startswith("night_light"):
        assert comps["U2"]["access"] == "sensor" and comps["U2"]["shape"] == "round" and comps["LED1"]["access"] == "light"
    else:
        assert comps["BZ1"]["access"] == "sound" and comps["LED1"]["access"] == "light" and comps["J_BAT"]["access"] == "port"


@needs_bundle
async def test_a_dice_face_and_a_display_build_clean_and_reach_board_json(catalogue, real_pcb):
    doc, _ = device.normalize(dice_doc())
    parts, _ = await device.resolve(doc)
    c = device.compile(doc, parts, device.estimate(doc, parts))
    b = await pcb.pool().build(c["source"], intent=c["intent"], lcsc=c["lcsc"])
    assert b["ok"] and not b["errors"], b["errors"][:3]
    pc = {e["source_component_id"]: e for e in b["circuit_json"] if e["type"] == "pcb_component"}
    at = {s["name"]: pc[s["source_component_id"]]["center"] for s in b["circuit_json"] if s["type"] == "source_component"}
    assert (round(at["LED2"]["x"], 2), round(at["LED2"]["y"], 2)) == (-7, 1) and (round(at["LED7"]["x"], 2), round(at["LED7"]["y"], 2)) == (7, -13)

    doc, _ = device.normalize(oled_doc())
    parts, _ = await device.resolve(doc)
    W, H = device.estimate(doc, parts)
    c = device.compile(doc, parts, (W, H))
    b = await pcb.pool().build(c["source"], intent=c["intent"], lcsc=c["lcsc"])
    assert b["ok"] and not b["errors"] and b["intent"]["ok"], b["errors"][:3]
    assert not any("accessible_orientation" in w["type"] for w in b["warnings"])
    board = device.dress_board(b["board"], doc, parts, b["circuit_json"])
    acc = {a["id"]: a for a in board["accessories"]}
    body = device.accessory_places(doc, parts, W, H)["D1"]
    d1 = acc["D1"]
    assert d1["kind"] == "display" and d1["mount"] == "board" and d1["z0"] == 2.5 and (d1["w"], d1["d"]) == (27.3, 27.8)
    assert math.isclose(d1["x"], W / 2 + body["x"], abs_tol=0.01) and math.isclose(d1["y"], H / 2 + body["y"], abs_tol=0.01)
    assert d1["window"] == [21.74, 10.86] and len(d1["holes"]) == 4
    assert acc["P1"]["mount"] == "cable" and acc["P1"]["edge"] == "-y" and acc["P1"]["cable_d"] == 4.0
    assert acc["B1"]["mount"] == "inside" and (acc["B1"]["w"], acc["B1"]["d"]) == (30.0, 20.0)
    comps = {x["id"]: x for x in board["components"]}
    header = comps["D1"]
    assert header["type"] == "pin_header_2_54" and header["access"] == "none" and header["w"] == 10.16 and header["h"] == 2.5
    # the probe's header is plugged inside; its lead leaves by the accessory's cable exit, not a wall window of its own
    assert comps["P1"]["access"] == "none" and "edge" not in comps["P1"] and comps["P1"]["x"] == acc["P1"]["x"]
    assert comps["J1"]["access"] == "port" and comps["J1"]["edge"] == "+x"  # a JST the person plugs from outside
    # what packages/geom/src/board.schema.json admits
    schema = json.loads((REPO_DIR / "packages" / "geom" / "src" / "board.schema.json").read_text(encoding="utf-8"))
    allowed = set(schema["$defs"]["accessory"]["properties"])
    assert all(set(a) <= allowed for a in board["accessories"]), [set(a) - allowed for a in board["accessories"]]
    assert {x["access"] for x in board["components"]} <= set(schema["$defs"]["component"]["properties"]["access"]["enum"])


# ---------------------------------------------------------------- placement checked before a build (round 2)
def timer_doc(board: dict | None = None, ds1_y: float = 10, buttons: bool = True) -> dict:
    """2026-11-03 kitchen timer v1: the designer fixed 48 x 52 mm and put the OLED's body into the XIAO's band."""
    nodes = [{"id": "U1", "kind": "module", "module": "113991054"},
             {"id": "DS1", "kind": "accessory", "accessory": "oled_096_i2c", "place": {"x": 0, "y": ds1_y}}]
    if buttons:
        nodes += [{"id": f"SW{i}", "kind": "button", "place": {"x": x, "y": -16}} for i, x in ((1, -14), (2, 0), (3, 14))]
    nets = [{"name": "GND", "pins": ["U1.GND", "DS1.GND"] + ([f"SW{i}.B" for i in (1, 2, 3)] if buttons else [])},
            {"name": "V3V3", "pins": ["U1.3V3", "DS1.VCC"]}, {"name": "SDA", "pins": ["U1.SDA", "DS1.SDA"]}, {"name": "SCL", "pins": ["U1.SCL", "DS1.SCL"]}]
    nets += [{"pins": [f"U1.D{i - 1}", f"SW{i}.A"]} for i in (1, 2, 3)] if buttons else []
    return {"title": "Timer", "board": board or {"holes": True, "w": 48, "h": 52}, "nodes": nodes, "nets": nets}


async def test_a_body_placed_into_the_module_band_is_said_before_the_build_with_the_moves(catalogue):
    doc, _ = device.normalize(timer_doc())
    parts, issues = await device.resolve(doc)
    conflict = [i for i in issues if i["code"] == "place_conflict"]
    assert len(conflict) == 1 and conflict[0]["severity"] == "error" and conflict[0]["ref"] == "DS1" and set(conflict[0]["ids"]) == {"DS1", "U1"}
    msg = conflict[0]["msg"]
    # the module's band starts 21 mm below the top edge (y > 5 on 52 mm); the body is 27.8 mm tall around y = 10
    assert "runs into U1" in msg and "put DS1 at y <= -9.2" in msg and "board.h >= 91" in msg and "move U1" not in msg
    assert "left as it is, the build grows the board to 48 x 91 mm" in msg
    # the designer's size is a minimum: the build would clear it by growing; the person's is a cage
    assert device.estimate(doc, parts) == (48.0, 91.0)
    locked, _ = device.normalize(timer_doc({"holes": True, "w": 48, "h": 52, "locked": True}))
    assert locked["board"]["locked"] is True and device.estimate(locked, parts) == (48.0, 52.0)
    _, issues = await device.resolve(locked)
    assert "the person fixed the board at 48 x 52 mm" in next(i["msg"] for i in issues if i["code"] == "place_conflict")
    assert "locked" not in device.normalize({"title": "x", "board": {"locked": True, "w": 40}})[0]["board"]
    # moved where the message says: the band is clear, the buttons below are not (a pair of placed parts never grows apart)
    moved, _ = device.normalize(timer_doc(ds1_y=-9.2))
    _, issues = await device.resolve(moved)
    got = [i for i in issues if i["code"] == "place_conflict"]
    assert got and all("SW" in i["msg"] and "overlap" in i["msg"] and "U1" not in i["ids"] for i in got)
    clear, _ = device.normalize(timer_doc(ds1_y=-9.2, buttons=False))
    _, issues = await device.resolve(clear)
    assert not [i for i in issues if i["code"] == "place_conflict"]


async def test_a_small_overlap_with_an_edge_part_is_grown_away_quietly_and_the_free_area_says_where_room_is(catalogue):
    raw = {"title": "x", "board": {"holes": True, "w": 40, "h": 44}, "nodes": [
        {"id": "U1", "kind": "module", "module": "113991054"}, {"id": "LED1", "kind": "led", "place": {"x": 0, "y": 4}},
        {"id": "R1", "kind": "resistor", "value": "1k"}],
        "nets": [{"pins": ["U1.D0", "R1.1"]}, {"pins": ["R1.2", "LED1.A"]}, {"name": "GND", "pins": ["U1.GND", "LED1.K"]}]}
    doc, _ = device.normalize(raw)
    parts, issues = await device.resolve(doc)
    assert not [i for i in issues if i["code"] == "place_conflict"]
    W, H = device.estimate(doc, parts)
    assert W == 40 and 44 < H <= 44 + 12  # the +y band rose by half of what h grew, clear of the LED
    area = device.free_area(doc, parts, (W, H))
    assert area["board"] == [W, H] and area["x"] == [-19.5, 19.5] and area["y"][1] == round(H / 2 - 21 - device.PLACE_GAP_MM, 1)
    assert area["y"][1] + 0.05 >= 4 + 1.46 / 2  # (rounded to 0.1 mm)
    # an edge part's own place is ignored (it is laid out along its edge), and said
    raw["nodes"][0]["place"] = {"x": 0, "y": 0}
    doc, issues = device.normalize(raw)
    assert "place" not in doc["nodes"][0] and [i["code"] for i in issues] == ["place_on_edge_part"]


async def test_a_layout_that_puts_its_parts_on_each_other_is_one_message_with_the_pitch(catalogue):
    leds = [f"LED{i}" for i in range(1, 5)]
    doc, _ = device.normalize({"title": "x", "board": {"holes": True}, "nodes": [{"id": "U1", "kind": "module", "module": "113991054"}]
                               + [{"id": n, "kind": "chip", "lcsc": "C2843785"} for n in leds],
                               "layouts": [{"pattern": "row", "nodes": leds, "center": [0, -8], "pitch": 5}],
                               "nets": [{"name": "GND", "pins": ["U1.GND"] + [f"{n}.GND" for n in leds]}]})
    parts, issues = await device.resolve(doc)
    got = [i for i in issues if i["code"] == "place_conflict"]
    assert len(got) == 1 and got[0]["msg"].startswith("the row layout of LED1, LED2, LED3, LED4 (center (0, -8), pitch 5) puts its parts on each other")
    box = device.local_box(doc["nodes"][1], parts["LED1"])  # the 5050's model outline and pads, as the worker draws its courtyard
    assert (round(box[2] - box[0], 2), round(box[3] - box[1], 2)) == (5.5, 7.0)
    assert f"a pitch >= {5 + (5.5 - 5) + device.PLACE_GAP_MM:.1f} mm" in got[0]["msg"]


async def test_capacitors_on_a_rail_named_by_the_designer_sit_at_each_placed_chip(catalogue):
    """Night light p_c05072e060b04ac5: four WS2812B in a row on 'VLED' (behind a diode) had their 100nF packed 25 mm away."""
    leds = [f"LED{i}" for i in range(1, 5)]
    caps = [f"C{i}" for i in range(1, 5)]
    doc, _ = device.normalize({"title": "x", "board": {"holes": True}, "nodes": [{"id": "U1", "kind": "module", "module": "113991054"},
                               {"id": "D1", "kind": "diode"}] + [{"id": n, "kind": "chip", "lcsc": "C2843785"} for n in leds]
                               + [{"id": c, "kind": "capacitor", "label": f"{n} decoupling"} for c, n in zip(caps, leds)],
                               "layouts": [{"pattern": "row", "nodes": leds, "center": [0, -10], "pitch": 10}],
                               "nets": [{"name": "V5", "pins": ["U1.5V", "D1.A"]},
                                        {"name": "VLED", "pins": ["D1.K"] + [f"{n}.VDD" for n in leds] + [f"{c}.1" for c in caps]},
                                        {"name": "GND", "pins": ["U1.GND"] + [f"{n}.GND" for n in leds] + [f"{c}.2" for c in caps]}]})
    parts, _ = await device.resolve(doc)
    plan, bulk = device.decoupling(doc, parts)
    assert {chip: [c for c, *_ in cs] for chip, cs in plan.items()} == dict(zip(leds, [[c] for c in caps])) and not bulk
    placed = device.compile(doc, parts, device.estimate(doc, parts))["placed"]
    for led, cap in zip(leds, caps):
        assert abs(placed[cap]["pcbX"] - placed[led]["pcbX"]) < 6 and abs(placed[cap]["pcbY"] - placed[led]["pcbY"]) < 6
    assert device.is_supply({"name": "VLED"}) and device.is_supply({"name": "PWR_5V"}) and not device.is_supply({"name": "VSENSE"})
    assert device.WIDE_NET.match("VLED") and not device.is_supply({"name": "GND"})


async def test_build_errors_name_the_placed_part_and_the_room_never_the_module(catalogue):
    doc, _ = device.normalize(timer_doc({"holes": True, "w": 48, "h": 52, "locked": True}, buttons=False))
    parts, _ = await device.resolve(doc)
    errors = [{"type": "pcb_footprint_overlap_error", "message": "U1 overlaps DS1: 16 footprint overlaps, 1 courtyard conflict. Move the components apart.",
               "hint": "move U1 by -15.84 mm in y (pcbY 15.5 -> -0.34)"},
              {"type": "pcb_packing_error", "message": "Unable to pack all PCB components within the layout bounds: No valid candidates found"},
              {"type": "pcb_trace_error", "message": "something else", "hint": "as it was"}]
    device.build_hints(doc, parts, (48, 52), errors)
    assert errors[0]["hint"].startswith("DS1 (27.3x27.8 mm at (0, 10)) runs into U1") and "put DS1 at y <= -9.2" in errors[0]["hint"]
    assert "left them at the board's centre" in errors[1]["hint"] and "the person fixed the board size" in errors[1]["hint"]
    assert errors[2]["hint"] == "as it was"


async def test_the_quote_says_what_each_device_arrives_with(catalogue):
    doc, _ = device.normalize(oled_doc())
    parts, _ = await device.resolve(doc)
    b = bom_of(doc, parts, 2)
    assert "B1: 1 x LiPo cell 3.7 V 500 mAh (602030)" in b["in_order"] and "U1: 1 x Seeed XIAO ESP32-C3" in b["in_order"]
    assert all(r["in_order"] and r["name"] for r in b["bom"])
    assert next(r for r in b["bom"] if r.get("accessory") == "lipo_1s_500")["note"].endswith("in the order")


# ---------------------------------------------------------------- a decoupling limit never fails a device (round 3)
@needs_bundle
@pytest.mark.parametrize("name", ["night_light_r3_2", "night_light_r3_4"])
async def test_a_capacitor_trace_over_its_limit_is_a_warning_and_never_grows_the_board(name, catalogue, real_pcb, monkeypatch):
    """p_e09652612ee046f8: the router took 31.9 mm between two capacitor pads 1.6 mm apart beside U2, so every build failed
    on 'PCB trace is 31.90mm long, exceeding the 10mm maximum' (hint null) and the board grew 52 -> 88 x 100 mm."""
    from iamodelize3d import deviceapi

    async def nothing(*a, **k):
        return None

    async def save(project_id, **k):
        return 1

    monkeypatch.setattr(deviceapi.events, "emit", nothing)
    monkeypatch.setattr(deviceapi.pcbapi, "emit_route", nothing)
    monkeypatch.setattr(deviceapi.pcbapi, "emit_version", nothing)
    monkeypatch.setattr(deviceapi.pcb_store, "save", save)
    res = await deviceapi.build_device("p_test", copy.deepcopy(GRAPHS[name]))
    assert res["drc_ok"] and not res["build"]["errors"], (res["attempts"], res["build"]["errors"][:2])
    first = res["attempts"][0]["size_mm"]
    assert all(a["size_mm"] == first for a in res["attempts"]), res["attempts"]  # the same board, never grown for it
    warned = [w for w in res["build"]["warnings"] if w["type"] == "decoupling_distance_warning"]
    relaxed = set(res["attempts"][-1].get("relaxed") or [])
    assert {w["ref"] for w in warned} == relaxed and all("decoupling works best within 10 mm" in w["message"] for w in warned)
    assert all("place U2 and" in w["hint"] for w in warned)


def test_only_placement_and_routing_errors_grow_the_board_and_long_traces_name_their_capacitors():
    assert device.growable([{"type": "pcb_courtyard_overlap_error"}]) and device.growable([{"type": "pcb_packing_error"}])
    assert device.growable([{"type": "pcb_autorouting_error"}]) and not device.growable([{"type": "pcb_trace_too_long_error"}])
    assert not device.growable([{"type": "pcb_connector_not_in_accessible_orientation_warning"}, {"type": "pcb_button_short_error"}])
    doc = {"nodes": [{"id": "C1", "kind": "capacitor"}, {"id": "C2", "kind": "capacitor"}, {"id": "U2", "kind": "chip"}]}
    err = {"type": "pcb_trace_too_long_error", "message": "PCB trace is 31.90mm long, exceeding the 10mm maximum", "ends": ["C1.pin2", "C2.pin2"],
           "traces": [".C1 > .pin2 to .U2 > .GND", ".C2 > .pin2 to .U2 > .GND"], "length": 31.9, "max": 10}
    assert device.long_caps(doc, [err]) == {"C1": {"length": 31.9, "max": 10.0, "to": "U2.GND"}, "C2": {"length": 31.9, "max": 10.0, "to": "U2.GND"}}
    assert device.long_caps(doc, [err, {"type": "pcb_courtyard_overlap_error"}]) == {}  # only when nothing else failed

