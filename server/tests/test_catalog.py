"""Catalogue (catalog.py): pin labels that keep a buzzer's two terminals apart and a supply's pins together, a discrete's pin
roles from its package's standard pinout, what a part is (kind_hint) and draws (current_ma), heights a case can trust, and
a search that finds parts by their function. Nothing goes online: JLCPCB answers from recorded responses
(fixtures/catalog/jlc.json, keyword -> the listing's items) through an httpx MockTransport, EasyEDA from its recorded
entries (fixtures/easyeda), and the cache lives in a temporary folder."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pytest

from iamodelize3d import catalog

FIX = Path(__file__).parent / "fixtures" / "catalog"
JLC = json.loads((FIX / "jlc.json").read_text(encoding="utf-8"))
BME = json.loads((FIX.parent / "easyeda" / "C92489.json").read_text(encoding="utf-8"))


def ee(code: str) -> dict | None:
    p = FIX.parent / "easyeda" / f"{code}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


class Jlc:
    """The JLCPCB search endpoint from the recordings: every call's keyword in `calls` (with its time in `at`), and the
    keywords in `refuse` answered 403 (as JLCPCB answers calls made back to back) `refuse[kw]` times."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.at: list[float] = []
        self.refuse: dict[str, int] = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        kw = body["keyword"]
        self.calls.append(kw)
        self.at.append(time.monotonic())
        if self.refuse.get(kw):
            self.refuse[kw] -= 1
            return httpx.Response(403, json={"status": 403, "error": "Forbidden"})
        items = JLC.get(kw, [])[: body["pageSize"]]
        return httpx.Response(200, json={"code": 200, "data": {"componentPageInfo": {"list": items or None}}})


@pytest.fixture
def jlc(monkeypatch, tmp_path):
    def _dir(name: str) -> Path:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def easyeda(code):
        return ee(catalog.norm_code(code) or "")

    fake = Jlc()
    monkeypatch.setattr(catalog, "_dir", _dir)
    monkeypatch.setattr(catalog, "_transport", httpx.MockTransport(fake))
    monkeypatch.setattr(catalog, "easyeda", easyeda)
    monkeypatch.setattr(catalog, "SEARCH_GAP", 0.0)
    monkeypatch.setattr(catalog, "RETRY_WAIT", 0.0)
    monkeypatch.setattr(catalog, "_next_call", 0.0)
    return fake


def labels(pins: list[tuple[str, str]], roles: dict[str, str] | None = None) -> list[str]:
    out = catalog.labels_of([{"num": n, "name": m} for n, m in pins], roles)
    return [out[f"pin{n}"] for n, _ in pins]


# ---------------------------------------------------------------- labels
def test_safe_label_keeps_polarity():
    assert catalog.safe_label("+") == "POS" and catalog.safe_label("-") == "NEG" and catalog.safe_label("−") == "NEG"
    assert catalog.safe_label("IN-") == "INN" and catalog.safe_label("IN+") == "INP" and catalog.safe_label("VIN+") == "VINP"
    assert catalog.safe_label("D-") == "DN" and catalog.safe_label("D+") == "DP" and catalog.safe_label("-5V") == "N5V"
    assert catalog.safe_label("3V3") == "V3V3" and catalog.safe_label("IO0/BOOT") == "IO0_BOOT" and catalog.safe_label("SPI-CS") == "SPI_CS"


def test_a_buzzers_terminals_are_two_pins_and_polarity_shows():
    """MLT-5020 C94598 names its pins '+', '-', 'NC': once both were 'P', so 'P' and 'P_2' folded into one reference and the
    - terminal could not be wired."""
    pins = catalog.pins_of(ee("C94598"))
    assert [p["name"] for p in pins] == ["+", "-", "NC"]
    assert labels([(p["num"], p["name"]) for p in pins]) == ["POS", "NEG", "NC"]
    assert {catalog.base_label(x) for x in ("POS", "NEG", "NC")} == {"POS", "NEG", "NC"}


def test_repeated_supply_pins_group_other_repeated_names_split():
    bme = catalog.labels_of(catalog.pins_of(BME))
    assert bme["pin1"] == "GND" and bme["pin7"] == "GND_7" and catalog.base_label("GND_7") == "GND"
    # a repeated name that is no supply: one label per pin, each its own reference
    assert labels([("1", "P"), ("2", "P"), ("3", "NC")]) == ["P1", "P2", "NC"]
    assert catalog.base_label("P2") == "P2" and catalog.base_label("IO_12") == "IO_12" and catalog.base_label("LED_1") == "LED_1"
    assert catalog.base_label("GND_A1") == "GND" and catalog.base_label("VDD_3") == "VDD"
    # never two pins on one label, and two names that clean up alike stay two pins
    got = labels([("1", "P"), ("2", "P"), ("3", "P1")])
    assert len(set(got)) == 3 and got[2] == "P1"
    assert len(set(labels([("1", "EN#"), ("2", "ENN")]))) == 2
    # a power MOSFET's parallel pads are one D and one S; a two-pin part never folds into one terminal
    so8 = labels([("1", "S"), ("2", "S"), ("3", "S"), ("4", "G"), ("5", "D"), ("6", "D"), ("7", "D"), ("8", "D")])
    assert [catalog.base_label(x) for x in so8] == ["S", "S", "S", "G", "D", "D", "D", "D"] and len(set(so8)) == 8
    assert len({catalog.base_label(x) for x in labels([("1", "S"), ("2", "S")])}) == 2


# ---------------------------------------------------------------- pin roles
def test_numbered_discretes_get_standard_roles_or_a_note():
    s8050 = catalog.pins_of(ee("C181158"))
    assert [p["name"] for p in s8050] == ["1", "2", "3"]
    roles, note = catalog.roles_of(s8050, "npn", ["SOT-23", "SOT-23-3_L2.9-W1.6-P1.90-LS2.8-BR"])
    assert roles == {"1": "B", "2": "E", "3": "C"} and "SOT-23" in note and "datasheet" in note
    assert catalog.roles_of(s8050, "nmos", ["SOT-23"])[0] == {"1": "G", "2": "S", "3": "D"}
    # TO-92 pinouts differ between makers: no guess, the note says so and the pins stay numbered
    roles, note = catalog.roles_of(s8050, "npn", ["TO-92", "TO-92-3_L4.9-W3.7-P1.27-L"])
    assert roles == {} and "TO-92" in note and "datasheet" in note
    assert labels([(p["num"], p["name"]) for p in s8050], roles) == ["P1", "P2", "P3"]
    # names the symbol gives are used: MMBT3904 'B', 'E', 'C'; AO3400 'G', 'S', 'D'; B5819W '-', '+'
    assert catalog.roles_of(catalog.pins_of(ee("C20526")), "npn", ["SOT-23"]) == ({"1": "B", "2": "E", "3": "C"}, None)
    assert catalog.roles_of(catalog.pins_of(ee("C181090")), "nmos", ["SOT-23"]) == ({"1": "G", "2": "S", "3": "D"}, None)
    assert catalog.roles_of(catalog.pins_of(ee("C8598")), "diode", ["SOD-123"]) == ({"1": "K", "2": "A"}, None)
    # a numbered diode from its package; a SOT-23 diode pair has no single pinout; SOT-23-6 is no SOT-23
    two = [{"num": "1", "name": "1"}, {"num": "2", "name": "2"}]
    assert catalog.roles_of(two, "diode", ["SOD-323"])[0] == {"1": "K", "2": "A"}
    assert catalog.roles_of(s8050, "diode", ["SOT-23"])[0] == {}
    assert catalog.roles_of(s8050, "npn", ["SOT-23-6"])[0] == {}


def test_a_two_pin_part_marked_on_one_pin_gets_the_other_sign():
    """HND-2319 C2878 names its pins '+' and '2'."""
    roles, note = catalog.roles_of(catalog.pins_of(ee("C2878")), "buzzer_active", ["Plugin,D=23mm"])
    assert roles == {"2": "NEG"} and "pin 2" in note
    assert catalog.roles_of([{"num": "1", "name": "2"}, {"num": "2", "name": "-"}], "diode", ["SOD-123"])[0] == {"1": "A", "2": "K"}


def test_a_numbered_led_takes_a_and_k_from_its_symbol_triangle():
    """HL-AM-2835H421W C210315 (warm white 2835) only numbers its pins: its triangle points at pin 1 (x=380), so 1=K 2=A.
    The small emission-arrow triangles are left out; a symbol with two triangles of a size, or no pin pair on the axis,
    gets nothing."""
    raw = ee("C210315")
    pins = catalog.pins_of(raw)
    roles, note = catalog.roles_of(pins, "led", ["SMD2835-2P"], raw)
    assert roles == {"1": "K", "2": "A"} and "diode triangle on the symbol" in note and "1=K, 2=A" in note
    assert labels([(p["num"], p["name"]) for p in pins], roles) == ["K", "A"]
    assert catalog.roles_of(pins, "led", ["SMD2835-2P"]) == ({}, None)  # no EasyEDA entry: numbered as before
    # B5819W C8598 names its pins '-' and '+': the triangle reads the same
    assert catalog.diode_roles(ee("C8598"), catalog.pins_of(ee("C8598"))) == {"1": "K", "2": "A"}
    # the triangle wins over the package's standard pinout for a numbered diode; reversed, it says so
    flipped = json.loads(json.dumps(raw).replace("M 405 306 L 395 300 L 405 293 Z", "M 395 306 L 405 300 L 395 293 Z"))
    assert catalog.roles_of(pins, "diode", ["SOD-123"], flipped)[0] == {"1": "A", "2": "K"}
    # a third pin off the axis does not get in the way
    third = {**raw, "dataStr": {**raw["dataStr"], "shape": raw["dataStr"]["shape"] + ["P~show~0~3~400~340~90~gge99~0^^400~340^^M 400 340 v -15~#880000"]}}
    assert catalog.diode_roles(third, pins + [{"num": "3", "name": "3"}]) == {"1": "K", "2": "A"}
    # a bicolour LED: two triangles of a size, back to back
    bicolour = {**raw, "dataStr": {**raw["dataStr"], "shape": raw["dataStr"]["shape"] + ["PT~M 395 316 L 405 310 L 395 303 Z~#880000~1~0~none~gge98~0~"]}}
    assert catalog.diode_roles(bicolour, pins) == {}
    assert catalog.diode_roles({"dataStr": {"shape": []}}, pins) == {}


def test_a_numbered_buzzer_takes_pos_and_neg_from_its_polarity_mark():
    """TMB12075-3V C49246934 prints '+' on its footprint by pad 1; YX-YT9042 C781847 draws '+' in silkscreen lines (and on
    its symbol) by pin 1; with no mark, pin 1 is taken as + and the note says to check the part."""
    raw = ee("C49246934")
    pins = catalog.pins_of(raw)
    roles, note = catalog.roles_of(pins, "buzzer_active", ["Plugin"], raw)
    assert roles == {"1": "POS", "2": "NEG"} and "'+' printed on the footprint by pin 1" in note
    assert labels([(p["num"], p["name"]) for p in pins], roles) == ["POS", "NEG"]
    yx = ee("C781847")
    roles, note = catalog.roles_of(catalog.pins_of(yx), "buzzer_active", ["Plugin,D=9mm"], yx)
    assert roles == {"1": "POS", "2": "NEG"} and "silkscreen" in note
    # its symbol draws a '+' by pin 1 too; without that: the '+' moved next to pad 2, a '-' by pad 1 says the same, both
    # together disagree
    fp = raw["packageDetail"]["dataStr"]
    sym = {**raw["dataStr"], "shape": [s for s in raw["dataStr"]["shape"] if not (s.startswith("PL~") and len(s.split("~")[1].split()) == 4)]}
    assert catalog.buzzer_roles({**raw, "dataStr": sym}, pins)[0] == {"1": "POS", "2": "NEG"}

    def with_text(*texts):
        shapes = [s for s in fp["shape"] if not s.startswith("TEXT")] + list(texts)
        return {**raw, "dataStr": sym, "packageDetail": {**raw["packageDetail"], "dataStr": {**fp, "shape": shapes}}}

    plus2, minus1 = "TEXT~L~4021~2988.55~0.6~0~0~3~~5~+~M 0 0~~gge5~~0~", "TEXT~L~3987~2988.55~0.6~0~0~3~~5~-~M 0 0~~gge6~~0~"
    assert catalog.buzzer_roles(with_text(plus2), pins)[0] == {"2": "POS", "1": "NEG"}
    assert catalog.buzzer_roles(with_text(minus1), pins)[0] == {"2": "POS", "1": "NEG"}
    roles, note = catalog.buzzer_roles(with_text(plus2, "TEXT~L~3987~2988.55~0.6~0~0~3~~5~+~M 0 0~~gge7~~0~"), pins)
    assert roles == {} and "different pins" in note
    # no mark anywhere: the usual pinout, said as an assumption
    roles, note = catalog.buzzer_roles(with_text(), pins)
    assert roles == {"1": "POS", "2": "NEG"} and "no polarity mark found" in note and "check the +" in note
    # only a buzzer gets these; a named pin keeps its name
    assert catalog.roles_of(pins, "ic", ["Plugin"], raw) == ({}, None)
    assert catalog.roles_of(catalog.pins_of(ee("C2878")), "buzzer_active", ["Plugin,D=23mm"], ee("C2878"))[0] == {"2": "NEG"}


# ---------------------------------------------------------------- part cards
CARDS = [
    # code, kind_hint, current_ma, labels, height_mm, size_mm (None: not checked)
    ("C94598", "buzzer_passive", 100.0, ["POS", "NEG", "NC"], 2.5, [6.3, 5.26]),       # 3D model says H2.0, LCSC 2.5 mm
    ("C181158", "npn", 500.0, ["B", "E", "C"], 1.1, None),
    ("C2878", "buzzer_active", None, ["POS", "NEG"], 19.3, [23.04, 23.04]),           # borrows a 16 mm-high 3D model
    ("C114881", "sensor", None, ["VCC", "OUT", "GND"], 4.5, [9.35, 9.35]),            # AM312, TO-5 can
    ("C76871", "buzzer_passive", None, ["POS", "NEG"], 7.8, [13.0, 13.0]),            # 12.2 mm piezo, model H7.0; no mark: 1=+
    ("C96127", "buzzer_active", 30.0, ["POS", "NEG"], 5.5, None),                     # '+' in silkscreen by pad 1
    ("C2843785", "rgb_led", None, ["VDD", "DOU", "GND", "DIN"], 1.6, None),           # LCSC lists 'Height 5mm, Width 1.6mm'
    ("C181090", "nmos", 5800.0, ["G", "S", "D"], 1.0, None),
    ("C404323", "ic", 0.1, None, 1.5, None),                                          # BISS0001: a PIR controller, not a window
    ("C78960", "sensor", None, None, 0.8, None),
    ("C8598", "diode", 1000.0, ["K", "A"], None, None),
]


@pytest.mark.parametrize("code,kind,ma,lbls,h,size", CARDS)
async def test_part_cards(jlc, code, kind, ma, lbls, h, size):
    card = await catalog.info(code)
    assert card["kind_hint"] == kind and card["current_ma"] == ma and card["height_mm"] == h
    if lbls:
        assert [p["label"] for p in card["pins"]] == lbls
    if size:
        assert card["size_mm"] == size
    assert all(set(p) == {"num", "name", "label"} for p in card["pins"])
    assert card["attrs"] and card["family"]  # LCSC's parameters ride along
    assert jlc.calls == [code]  # a code is asked once, as typed


async def test_card_notes_say_where_roles_came_from(jlc):
    s8050 = await catalog.info("C181158")
    assert "standard SOT-23 BJT pinout" in s8050["pin_note"] and [p["name"] for p in s8050["pins"]] == ["1", "2", "3"]
    assert (await catalog.info("C181090"))["pin_note"] is None
    assert "pin 2" in (await catalog.info("C2878"))["pin_note"]


async def test_a_part_jlcpcb_does_not_list_is_read_from_easyeda(jlc):
    """No search card for MMBT3904 C20526: the EasyEDA entry's tag is the category, its symbol names B/E/C."""
    card = await catalog.info("C20526")
    assert card["category"] == "Bipolar Transistors - BJT" and card["kind_hint"] == "transistor" and card["attrs"] == {}
    assert [p["label"] for p in card["pins"]] == ["B", "E", "C"] and card["pin_note"] is None


def test_kind_and_current_from_search_cards():
    cards = {c["lcsc"]: c for kw in ("buzzer", "WS2812", "PIR", "SSD1306", "2835") for c in map(catalog._card, JLC[kw])}
    assert catalog.kind_of(cards["C2877"]) == "buzzer_active" and catalog.current_of(cards["C2877"]) == 10.0  # from its description
    assert catalog.kind_of(cards["C94598"]) == "buzzer_passive"
    assert catalog.kind_of(cards["C114587"]) == "rgb_led" and catalog.current_of(cards["C114587"], "rgb_led") is None  # 0.6 mA is idle
    assert catalog.kind_of(cards["C2887901"]) == "sensor" and catalog.kind_of(cards["C2940631"]) == "pmos"
    assert catalog.kind_of(cards["C5127225"]) == "inductor" and catalog.kind_of(cards["C73541"]) == "led"
    assert catalog.current_of(cards["C73541"]) == 150.0
    led_driver = {"category": "LED Drivers", "family": "LED Drivers", "description": "125mA Buck"}
    assert catalog.kind_of(led_driver) == "ic"
    assert catalog.current_of({"attrs": {"Current - Collector Cutoff": "100nA", "Current - Collector(Ic)": "500mA"}}) == 500.0
    assert catalog.current_of({"attrs": {"Quiescent Current": "10nA"}}) is None


# ---------------------------------------------------------------- search
async def test_an_oled_query_finds_displays_not_inductors(jlc):
    """'SSD1306 OLED' used to answer SSD1306-220MT power inductors."""
    hits = await catalog.search("SSD1306 OLED", limit=6)
    assert hits and all(h["category"] == "OLED Display" for h in hits)
    assert hits[0]["lcsc"] == "C5248081" and "SSD1306" in hits[0]["description"]  # the panel with an SSD1306 on it first
    assert jlc.calls == ["SSD1306 OLED", "SSD1306", "OLED"]  # at most three calls


async def test_functional_queries_find_parts(jlc):
    pir = await catalog.search("PIR motion sensor", limit=6)
    codes = [h["lcsc"] for h in pir]
    assert codes[0] == "C114881" and "C2887901" in codes  # AM312 first, the PIR223D elements next
    assert all(h["category"] == "Human Body Sensing Sensor" for h in pir)  # not TPIRLML MOSFETs or SPIRR inductors
    assert jlc.calls == ["PIR motion sensor", "AM312", "PIR"]

    buz = await catalog.search("piezo buzzer", limit=6)
    assert all(h["category"] == "Buzzers" for h in buz) and "Piezoelectric" in buz[0]["description"]

    ws = await catalog.search("WS2812 addressable LED", limit=6)
    assert ws and all(h["category"] == "RGB LEDs(Built-in IC)" for h in ws)

    warm = await catalog.search("LED warm white high power", limit=4)
    assert all(h["category"] == "LED Indication - Discrete" for h in warm)
    assert all(("2700K" in h["description"]) or ("3000K" in h["description"]) for h in warm)

    soil = await catalog.search("capacitive soil moisture sensor", limit=6)
    assert [h["mpn"] for h in soil] == ["CHT-T-R"]  # the one soil probe LCSC has, nothing else


async def test_enough_hits_ask_once_and_answers_are_cached(jlc):
    hits = await catalog.search("buzzer", limit=6)
    assert len(hits) == 6 and jlc.calls == ["buzzer"]
    assert [h["lcsc"] for h in await catalog.search("buzzer", limit=6)] == [h["lcsc"] for h in hits] and jlc.calls == ["buzzer"]
    # an exact lookup never falls back
    jlc.calls.clear()
    assert await catalog.search("piezo buzzer", fallback=False) == [] and jlc.calls == ["piezo buzzer"]


async def test_a_refused_call_is_retried_and_a_refused_fallback_ends_the_search(jlc):
    jlc.refuse = {"PIR motion sensor": 1, "PIR": 5}
    hits = await catalog.search("PIR motion sensor", limit=6)
    assert jlc.calls == ["PIR motion sensor", "PIR motion sensor", "AM312", "PIR"]  # the fallback is not retried
    assert [h["lcsc"] for h in hits] == ["C114881"]
    jlc.refuse = {"AM312 PIR": 5}
    with pytest.raises(catalog.CatalogError, match="did not answer"):
        await catalog.search("AM312 PIR")


async def test_a_stale_answer_beats_none(jlc, tmp_path):
    await catalog.search("buzzer", limit=6)
    for f in (tmp_path / "search").iterdir():
        os.utime(f, (time.time() - 2 * catalog.SEARCH_TTL,) * 2)
    jlc.refuse = {"buzzer": 5}
    assert len(await catalog.search("buzzer", limit=6)) == 6
    # an answer an earlier version cached under the query's own key (old cards: no attrs)
    old = [catalog._card(it) for it in JLC["SSD1306"]]
    for c in old:
        c.pop("attrs")
    key = __import__("hashlib").sha1(json.dumps(["ssd1306 oled", 8, False]).encode()).hexdigest()[:20]
    (tmp_path / "search" / f"{key}.json").write_text(json.dumps(old), encoding="utf-8")
    jlc.refuse = {"SSD1306 OLED": 5, "SSD1306": 5}
    assert await catalog.search("SSD1306 OLED") == []  # the inductors it found then are still not displays


async def test_calls_are_spaced(jlc, monkeypatch):
    monkeypatch.setattr(catalog, "SEARCH_GAP", 0.1)
    await catalog.search("SSD1306 OLED", limit=6)
    # Windows' timer can wake asyncio.sleep up to ~16 ms early
    assert len(jlc.at) == 3 and min(b - a for a, b in zip(jlc.at, jlc.at[1:])) >= 0.08


def test_query_plans():
    assert catalog._plan("piezo buzzer") == ["piezo buzzer", "buzzer"]
    assert catalog._plan("passive piezo buzzer 3V") == ["passive piezo buzzer 3V", "passive buzzer"]
    assert catalog._plan("WS2812 addressable LED") == ["WS2812 addressable LED", "WS2812"]
    assert catalog._plan("AM312") == ["AM312"]  # a part number is its own best word
    assert catalog._plan("LDO 3.3V SOT-23-5 0603") == ["LDO 3.3V SOT-23-5 0603", "XC6206", "AMS1117"]  # no value or package
    assert catalog._plan("NPN transistor SOT-23") == ["NPN transistor SOT-23", "S8050", "MMBT3904"]
    assert catalog._plan("BME280 breakout 10k") == ["BME280 breakout 10k", "BME280"]
