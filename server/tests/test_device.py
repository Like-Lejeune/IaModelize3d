"""Devices (device.py, device_tools.py, catalog.py): the graph is cleaned and checked, pin names resolve through module
aliases and chip pinouts, the compiler places edge parts and its placer the rest, and the reference device builds clean
through the real PCB bundle. The catalogue is stubbed: the BME280's EasyEDA entry is a fixture
(tests/fixtures/device), nothing goes online."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from iamodelize3d import catalog, device, pcb
from iamodelize3d.agent import device_prompt, device_tools
from iamodelize3d.config import REPO_DIR
from iamodelize3d.pcb import PcbPool

FIX = Path(__file__).parent / "fixtures" / "device"
BME = json.loads((FIX.parent / "easyeda" / "C92489.json").read_text(encoding="utf-8"))
DOC = device_prompt.EXAMPLE_DOC


@pytest.fixture
def offline(monkeypatch):
    """catalog.info / easyeda / resolve_basic answer from the fixture and fixed basic parts."""
    pins = catalog.pins_of(BME)
    labels = catalog.labels_of(pins)
    card = {"lcsc": "C92489", "mpn": "BME280", "brand": "Bosch Sensortec", "package": "LGA-8(2.5x2.5)", "stock": 3361, "basic": False,
            "prices": [{"qty": 1, "usd": 8.23}, {"qty": 10, "usd": 7.53}], "description": "1.71V~3.6V I2C SPI",
            "pins": [{"num": p["num"], "name": p["name"], "label": labels[f"pin{p['num']}"]} for p in pins],
            "size_mm": catalog.size_of(BME), "height_mm": catalog.height_of(BME), "pads": 8, "tht": False}

    async def info(code):
        if code != "C92489":
            raise catalog.CatalogError(f"{code} has no EasyEDA footprint")
        return copy.deepcopy(card)

    async def easyeda(code):
        return BME if code == "C92489" else None

    async def basic(kind, value="", package="0603", color=""):
        return {"lcsc": {"resistor": "C23162", "capacitor": "C14663", "led": "C12624"}.get(kind, "C1"), "mpn": kind, "basic": True,
                "stock": 10_000, "prices": [{"qty": 1, "usd": 0.01}]}

    monkeypatch.setattr(catalog, "info", info)
    monkeypatch.setattr(catalog, "easyeda", easyeda)
    monkeypatch.setattr(catalog, "resolve_basic", basic)


# ---------------------------------------------------------------- the catalogue's pure parts
def test_pinout_labels_and_sizes_from_easyeda():
    pins = catalog.pins_of(BME)
    assert [p["name"] for p in pins] == ["GND", "CSB", "SDI", "SCK", "SDO", "VDDIO", "GND", "VDD"]
    labels = catalog.labels_of(pins)
    assert labels["pin1"] == "GND" and labels["pin7"] == "GND_7" and catalog.base_label("GND_7") == "GND"
    assert catalog.height_of(BME) == 0.9  # from the 3D model "LGA-8_L2.5-W2.5-H0.9-P0.65"
    assert catalog.size_of(BME) == [2.92, 2.64]
    assert catalog.safe_label("3V3") == "V3V3" and catalog.safe_label("IO0/BOOT") == "IO0_BOOT" and catalog.safe_label("VIN+") == "VINP"
    assert catalog.value_keyword("resistor", "4k7", "0603") == "4.7kΩ 0603"
    assert catalog.price_at([{"qty": 1, "usd": 1.0}, {"qty": 10, "usd": 0.5}], 25) == 0.5


# ---------------------------------------------------------------- the document
def test_normalize_resolves_aliases_and_merges_nets():
    doc = copy.deepcopy(DOC)
    doc["nets"].append({"name": "GND", "pins": ["J2.GND"]})  # the same name twice is one net
    doc["nets"].append({"pins": ["U1.GPIO99", "R3.1"]})
    out, issues = device.normalize(doc)
    names = [n.get("name") for n in out["nets"]]
    assert names.count("GND") == 1
    v33 = next(n for n in out["nets"] if n.get("name") == "V3V3")
    assert "U1.V3V3" in v33["pins"]  # written U1.V3V3; '3V3' resolves to it too
    led = next(n for n in out["nets"] if "R3.1" in n["pins"])
    assert "U1.MOSI" in led["pins"]  # D10 is MOSI on a XIAO
    assert [i["code"] for i in issues] == ["bad_pin"] and "GPIO99" in issues[0]["msg"]


def test_shorted_supplies_are_an_issue_but_a_second_ground_is_not():
    doc = {"title": "x", "nodes": [{"id": "U1", "kind": "module", "module": "113991054"}, {"id": "C1", "kind": "capacitor"}],
           "nets": [{"name": "V3V3", "pins": ["U1.3V3", "C1.1"]}, {"name": "V5", "pins": ["U1.5V", "C1.1"]},
                    {"name": "GND", "pins": ["U1.GND"]}, {"name": "GND2", "pins": ["C1.2", "U1.GND"]}]}
    out, issues = device.normalize(doc)
    assert [i["code"] for i in issues] == ["supplies_shorted"]
    assert any(n.get("name") == "GND" and "C1.2" in n["pins"] for n in out["nets"])


def test_unknown_parts_are_issues_not_crashes():
    out, issues = device.normalize({"nodes": [{"id": "X", "kind": "flux_capacitor"}, {"id": "U9", "kind": "module", "module": "nope"},
                                              {"id": "U2", "kind": "chip"}], "nets": []})
    assert out["nodes"] == [] and {i["code"] for i in issues} == {"unknown_kind", "unknown_module", "no_lcsc"}


def test_edits_in_either_shape():
    doc, _ = device.normalize(copy.deepcopy(DOC))
    new, errors = device_tools.apply_edits(doc, [
        {"connect": ["U2.SDO", "U1.D2"]},                       # the op as its key
        {"op": "connect", "name": "GND", "pins": ["U2.SDO"]},   # onto a named net: it leaves the D2 net
        {"op": "set", "id": "R3", "fields": {"value": "2.2k"}},
        {"op": "remove", "id": "SW1"},
        {"op": "teleport"},
    ])
    out, _ = device.normalize(new)
    gnd = next(n for n in out["nets"] if n.get("name") == "GND")
    assert "U2.SDO" in gnd["pins"] and not any("U1.D2" in n["pins"] and "U2.SDO" in n["pins"] for n in out["nets"])
    assert next(n for n in out["nodes"] if n["id"] == "R3")["value"] == "2.2k"
    assert not any(n["id"] == "SW1" for n in out["nodes"]) and not any(p.startswith("SW1.") for n in out["nets"] for p in n["pins"])
    assert errors == ["edit 4: unknown or incomplete op 'teleport'"]


# ---------------------------------------------------------------- parts, checks and the compiler
async def test_compile_places_edge_parts_and_arranges_the_rest(offline):
    doc, _ = device.normalize(copy.deepcopy(DOC))
    parts, issues = await device.resolve(doc)
    assert issues == [] and device.lint(doc, parts) == []
    W, H = device.estimate(doc, parts)
    assert 30 <= W <= 45 and 30 <= H <= 45
    c = device.compile(doc, parts, (W, H))
    src = c["source"]
    assert 'footprint="lcsc:C92489"' in src and 'pin7: "GND_7"' in src
    assert c["lcsc"]["C92489"]["h"] == 0.9 and c["lcsc"]["C92489"]["easyeda"] is BME
    # the module's own USB at the top edge, the OLED header at the bottom; the sensor and the passives come from the placer
    assert c["placed"]["U1"]["pcbY"] == round(H / 2 - 10.5, 2) and c["placed"]["J2"]["pcbY"] == round(-(H / 2 - 2.5), 2)
    assert {"R1", "R2", "R3", "LED1", "SW1", "U2", "C1"} <= set(c["placed"]) and "pcbPack" not in src and "<group" not in src
    # the sensor and its decoupling capacitor are one unit: the capacitor sits at the sensor's supply pin
    u2, cap = c["placed"]["U2"], c["placed"]["C1"]
    assert abs(cap["pcbX"] - u2["pcbX"]) < 4 and abs(cap["pcbY"] - u2["pcbY"]) < 4 and "maxDecouplingTraceLength={10}" in src
    assert '<trace from=".U2 > .GND_7" to="net.GND" />' in src  # one 'U2.GND' is both GND pins
    assert c["intent"]["edge"] == {"U1": "+y", "J2": "-y"} and c["intent"]["gpio"] == {"LED1": "U1.MOSI", "SW1": "U1.D1"}


async def test_lint_names_what_a_netlist_can_tell(offline):
    doc = {"title": "x", "nodes": [{"id": "U1", "kind": "module", "module": "113991054"}, {"id": "U2", "kind": "chip", "lcsc": "C92489"},
                                   {"id": "LED1", "kind": "led"}, {"id": "J1", "kind": "usb_c", "edge": "-y"}, {"id": "SW1", "kind": "button"}],
           "nets": [{"name": "GND", "pins": ["U1.GND", "U2.GND", "LED1.K", "J1.GND"]}, {"name": "V3V3", "pins": ["U1.3V3", "U2.VDD"]},
                    {"pins": ["U1.D0", "LED1.A"]}, {"name": "VBUS", "pins": ["J1.VBUS", "U1.5V"]}, {"pins": ["U2.SDI", "U2.SDO"]}]}
    doc, _ = device.normalize(doc)
    parts, issues = await device.resolve(doc)
    codes = sorted({w["code"] for w in device.lint(doc, parts)})
    assert codes == ["decoupling", "led_resistor", "unconnected", "usb_cc"]
    bad, _ = device.normalize({"title": "x", "nodes": [{"id": "U2", "kind": "chip", "lcsc": "C92489"}], "nets": [{"pins": ["U2.MISO", "U2.SDI"]}]})
    _, issues = await device.resolve(bad)
    assert issues[0]["code"] == "bad_pin" and "SDI" in issues[0]["msg"]


def test_view_hides_unwired_nc_pins_and_groups_duplicates():
    doc, _ = device.normalize(copy.deepcopy(DOC))
    parts = {"U2": {"pins": [{"num": "1", "name": "GND", "label": "GND"}, {"num": "2", "name": "NC", "label": "NC"},
                             {"num": "3", "name": "GND", "label": "GND_3"}, {"num": "4", "name": "SDI", "label": "SDI"}], "lcsc": "C92489"}}
    v = device.view(doc, parts)["nodes"]["U2"]
    assert [(p["name"], p.get("count")) for p in v["pins"]] == [("GND", 2), ("SDI", None)]
    assert v["pins"][0]["net"] == "GND"


def test_board_key_ignores_where_nodes_are_drawn():
    a, _ = device.normalize(copy.deepcopy(DOC))
    b = copy.deepcopy(a)
    b["nodes"][0]["ui"] = [100, 200]
    b["firmware"] = {"lang": "arduino", "files": {"main.ino": "void setup(){}"}}
    assert device.board_key(a) == device.board_key(b)
    b["nodes"][1]["lcsc"] = "C1"
    assert device.board_key(a) != device.board_key(b)


def test_prompt_lists_the_modules_and_stays_english():
    from iamodelize3d.llm.english import is_english

    for mpn, m in device.MODULES.items():
        assert mpn in device_prompt.PACK_TEXT and m["name"] in device_prompt.PACK_TEXT
    assert is_english(device_prompt.PACK_TEXT) and is_english(device_prompt.EXAMPLE)


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


@pytest.fixture
def no_store(monkeypatch):
    from iamodelize3d import deviceapi

    async def nothing(*a, **k):
        return None

    async def save(project_id, **k):
        return 1

    monkeypatch.setattr(deviceapi.events, "emit", nothing)
    monkeypatch.setattr(deviceapi.pcbapi, "emit_route", nothing)
    monkeypatch.setattr(deviceapi.pcbapi, "emit_version", nothing)
    monkeypatch.setattr(deviceapi.pcb_store, "save", save)
    return deviceapi


@needs_bundle
async def test_the_reference_device_builds_clean(offline, real_pcb, no_store):
    device_growth = no_store.GROW + 0.02
    # through the attempt loop: the router trips over a spot on some arrangements (a via on a tiny LGA pad), and the loop deals with it
    res = await no_store.build_device("p_test", copy.deepcopy(DOC))
    b = res["build"]
    assert b["ok"] and not b["errors"] and b["intent"]["ok"] and b["intent"]["checked"] == 5, b["errors"][:3]
    first = res["attempts"][0]["size_mm"]
    assert res["size_mm"][0] <= first[0] * device_growth and res["size_mm"][1] <= first[1] * device_growth, res["attempts"]  # a step at most
    assert b["counts"]["traces"] >= 15
    u2 = next(x for x in b["board"]["components"] if x["id"] == "U2")
    assert u2["type"] == "chip" and u2["h"] == 0.9  # the catalogue height reaches the case
    fab = await pcb.pool().export(b["circuit_json"])
    assert "C92489" in fab["files"]["bom.csv"]


# ---------------------------------------------------------------- the person's edits
async def test_hand_placement_is_compiled_and_turns_the_decoupling_with_the_chip(offline):
    doc = copy.deepcopy(DOC)
    doc["board"] = {"holes": True, "w": 40, "h": 40}
    for n in doc["nodes"]:
        if n["id"] == "U2":
            n["pcb"] = {"x": 6, "y": -4, "rot": 90}
        if n["id"] == "R3":
            n["pcb"] = {"x": -12.5, "y": -12, "rot": 180}
    doc, _ = device.normalize(doc)
    parts, _ = await device.resolve(doc)
    plan, _ = device.decoupling(doc, parts)
    cap_free = device._cap_spots(parts["U2"], plan["U2"], {"C1": "0603"})["C1"]  # where it sits around an unturned chip at 0, 0
    c = device.compile(doc, parts, (40, 40))
    # a chip placed by hand stands on its own with its capacitors around it (no group: its frame is the board's)
    assert 'name="G_U2"' not in c["source"] and '<chip name="U2" footprint="lcsc:C92489"' in c["source"]
    assert c["placed"]["U2"] == {"pcbX": 6, "pcbY": -4, "pcbRotation": 90} and c["placed"]["R3"] == {"pcbX": -12.5, "pcbY": -12, "pcbRotation": 180}
    cap = c["placed"]["C1"]  # turned a quarter with its chip about its centre: (x, y) -> (6 - y, -4 + x)
    assert (cap["pcbX"], cap["pcbY"]) == (round(6 - cap_free["pcbY"], 2), round(-4 + cap_free["pcbX"], 2))
    assert cap["pcbRotation"] == (cap_free["pcbRotation"] + 90) % 360
    assert "maxDecouplingTraceLength={10}" in next(ln for ln in c["source"].splitlines() if 'name="C1"' in ln)


def routed_doc() -> dict:
    doc = copy.deepcopy(DOC)
    doc["board"] = {"holes": True, "w": 36, "h": 35}
    at = {"R3": {"x": 10, "y": 4, "rot": 90}, "LED1": {"x": 10, "y": -4, "rot": 0}, "U1": {"x": 0, "y": 7, "rot": 0}}
    for n in doc["nodes"]:
        if n["id"] in at:
            n["pcb"] = at[n["id"]]
    doc["routes"] = [
        {"from": "R3.pin2", "to": "LED1.pin1", "points": [{"x": 10, "y": 0}]},
        # header to module on the bottom, both ends through-hole
        {"from": "J2.GND", "to": "U1.GND", "layer": "bottom", "width": 0.4, "points": [{"x": -1.27, "y": -10}, {"x": 7.62, "y": -1}]},
        # R1 is packed (no fixed place): the trace leads from the header's end instead
        {"from": "R1.pin2", "to": "J2.SDA", "points": [{"x": 3.81, "y": -11}]},
        {"from": "R3.pin1", "to": "LED1.pin2", "points": []},  # two nets: never drawn
        {"from": "R3.pin2", "to": "LED1.pin1", "points": [{"x": 10, "y": 0}]},  # the same trace twice
        {"from": "Q9.pin1", "to": "R3.pin1"},
    ]
    return doc


async def test_hand_traces_go_in_the_frame_of_the_part_they_leave(offline):
    doc, issues = device.normalize(routed_doc())
    assert len(doc["routes"]) == 4 and [i["code"] for i in issues] == ["bad_route"]
    assert doc["routes"][0] == {"from": "R3.pin2", "to": "LED1.pin1", "layer": "top", "width": 0.25, "points": [{"x": 10.0, "y": 0.0}]}
    parts, _ = await device.resolve(doc)
    problems = device.route_problems(doc, parts)
    assert [p["code"] for p in problems] == ["route_shorts"] and "joins nets" in problems[0]["msg"]
    c = device.compile(doc, parts, (36, 36))
    src = c["source"]
    # (10, 0) is 4 mm below R3's centre; R3 is turned a quarter, so in its own frame the corner is at (-4, 0)
    assert '<trace from=".R3 > .pin2" to=".LED1 > .pin1" pcbPathRelativeTo=".R3 > .pin2" pcbPath={[{ x: -4, y: 0 }]} thickness="0.25mm" />' in src
    assert '<trace from=".R3 > .pin2" to=".LED1 > .anode" />' not in src, "the autorouter must not join them again"
    assert '<trace from=".J2 > .SDA" to=".R1 > .pin2" pcbPathRelativeTo=".J2 > .SDA"' in src
    assert 'from=".R3 > .pin1" to=".LED1 > .pin2"' not in src and src.count('pcbPathRelativeTo') == 3
    assert c["hand"] == 3 and '"hand_bottom": [".J2 > .GND to .U1 > .GND"]' in src
    # after a via the run leaves the same point on the other layer
    two = device.compile({**doc, "routes": [{**doc["routes"][0], "points": [{"x": 12, "y": 2, "via": True}]}]}, parts, (36, 36))["source"]
    assert ('{ x: -2, y: -2, via: true, fromLayer: "top", toLayer: "bottom" }, { x: -2, y: -2 }]' in two), two
    j2 = c["placed"]["J2"]  # on the bottom edge, unturned: the corners only shift by its centre
    assert (f'pcbPathRelativeTo=".J2 > .GND" pcbPath={{[{{ x: {-1.27 - j2["pcbX"]:g}, y: {-10 - j2["pcbY"]:g} }}, '
            f'{{ x: {7.62 - j2["pcbX"]:g}, y: {-1 - j2["pcbY"]:g} }}]}} thickness="0.4mm"') in src
    assert "routed R3.pin2 to LED1.pin1 by hand (top, 1 corners)" in device.changes(device.normalize(DOC)[0], doc)
    assert device.board_key(doc) != device.board_key({**doc, "routes": doc["routes"][:1]})


def test_changes_say_what_the_person_did():
    old, _ = device.normalize(copy.deepcopy(DOC))
    new = copy.deepcopy(old)
    new["nodes"] = [n for n in new["nodes"] if n["id"] != "SW1"]
    new["nets"] = [{**n, "pins": [p for p in n["pins"] if not p.startswith("SW1.")]} for n in new["nets"]]
    new["nets"] = [n for n in new["nets"] if len(n["pins"]) >= 2 or n.get("name")]
    next(n for n in new["nodes"] if n["id"] == "R3")["value"] = "2.2k"
    next(n for n in new["nodes"] if n["id"] == "U1")["pcb"] = {"x": 0, "y": 8, "rot": 0}
    new["nodes"].append({"id": "U3", "kind": "chip", "lcsc": "C52917434", "label": "RGB"})
    new["nets"].append({"pins": ["U3.DI", "U1.D2"]})
    new["firmware"] = {"lang": "arduino", "files": {"main.ino": "void loop(){}"}}
    got = device.changes(old, new)
    assert "added U3 (chip C52917434 'RGB')" in got and "removed SW1 (button 'page')" in got
    assert "R3: value 1k -> 2.2k" in got and any(g.startswith("U1: placed by hand on the board at (0, 8)") for g in got)
    assert "connected U1.D2, U3.DI" in got and "firmware file main.ino added" in got
    assert device.changes(old, old) == []


async def test_quote_counts_the_joints_of_a_resolved_chip(offline):
    from iamodelize3d.deviceapi import pad_count

    doc, _ = device.normalize(DOC)
    parts, _ = await device.resolve(doc)
    by_id = {n["id"]: n for n in doc["nodes"]}
    # the build resolves a chip with its pads' geometry; the quote counts them
    assert isinstance(parts["U2"]["pads"], dict) and pad_count(by_id["U2"], parts["U2"]) == 8
    assert pad_count(by_id["R1"], parts.get("R1", {})) == 2
    assert pad_count(by_id["J2"], {}) == 4 and pad_count(by_id["U1"], {}) == len(device.MODULES["113991054"]["pins"])


@needs_bundle
async def test_hand_traces_survive_the_build_and_the_rest_is_autorouted(offline, real_pcb):
    doc, _ = device.normalize(routed_doc())
    parts, _ = await device.resolve(doc)
    c = device.compile(doc, parts, (36, 35))
    b = await pcb.pool().build(c["source"], intent=c["intent"], lcsc=c["lcsc"])
    cj = b["circuit_json"]
    names = {e["source_trace_id"]: e.get("display_name") for e in cj if e["type"] == "source_trace"}
    hand = {names.get(t["source_trace_id"]): t for t in cj if t["type"] == "pcb_trace" and not t["pcb_trace_id"].startswith("source_")}
    path = {n: [(p["route_type"], p.get("layer"), round(p["x"], 2), round(p["y"], 2)) for p in t["route"]] for n, t in hand.items()}
    # as drawn, corner for corner, in the board's frame; the header-to-module trace on the bottom all the way
    assert path[".R3 > .pin2 to .LED1 > .pin1"][1] == ("wire", "top", 10, 0)
    assert [p[1:] for p in path[".J2 > .GND to .U1 > .GND"][1:3]] == [("bottom", -1.27, -10), ("bottom", 7.62, -1)]
    assert {p[1] for p in path[".J2 > .GND to .U1 > .GND"]} == {"bottom"}
    assert path[".J2 > .SDA to .R1 > .pin2"][1] == ("wire", "top", 3.81, -11)
    # the autorouter joined everything else and left the hand traces as they are; what they hit is the person's to fix
    assert not any(e["type"] == "pcb_autorouting_error" for e in b["errors"]) and b["counts"]["traces"] >= 15
    assert all(".R3 > .pin2 to .LED1" in e["message"] or ".J2 > .GND to .U1" in e["message"] for e in b["errors"] if e["type"] != "pcb_trace_too_long_error"), b["errors"]


async def test_the_designer_sees_hand_traces_by_their_ends(offline, monkeypatch):
    from types import SimpleNamespace

    doc, _ = device.normalize(routed_doc())

    async def latest(pid):
        return {"version": 9, "author": "user", "doc": copy.deepcopy(doc)}

    async def no_edits(pid):
        return [], None

    monkeypatch.setattr(device_tools.device_store, "latest", latest)
    monkeypatch.setattr(device_tools, "user_changes", no_edits)
    lines = await device_tools.context_lines("p", SimpleNamespace(pcb={}))
    assert '"routes"' not in lines[0], "the corners stay out of the context"
    assert lines[1].startswith("# 4 traces drawn by the person on the board") and "R3.pin2-LED1.pin1" in lines[1]


async def test_write_device_keeps_the_persons_traces(offline, monkeypatch):
    from types import SimpleNamespace

    mine, _ = device.normalize(routed_doc())
    saved: list[dict] = []

    async def latest(pid):
        return {"version": 9, "author": "user", "doc": copy.deepcopy(mine)}

    async def save(pid, doc, author="agent", summary=""):
        saved.append(doc)
        return 10

    async def emit(*a, **k):
        return None

    monkeypatch.setattr(device_tools.device_store, "latest", latest)
    monkeypatch.setattr(device_tools.device_store, "save", save)
    monkeypatch.setattr(device_tools.events, "emit", emit)
    ctx = SimpleNamespace(project_id="p", job_id="j", project={"title": "Weather station"})
    # the designer rewrites the document without routes and drops SW1: the traces of parts that stay are kept
    doc = copy.deepcopy(DOC)
    doc["nodes"] = [n for n in doc["nodes"] if n["id"] != "SW1"]
    doc["nets"] = [{**n, "pins": [p for p in n["pins"] if not p.startswith("SW1.")]} for n in doc["nets"]]
    out = await device_tools._write(ctx, SimpleNamespace(device=None), {"doc": doc})
    assert out["version"] == 10
    assert saved[0]["routes"] == mine["routes"]
    assert all(n.get("pcb") == next(m for m in mine["nodes"] if m["id"] == n["id"]).get("pcb") for n in saved[0]["nodes"])


async def test_zones_pour_a_net_and_keep_copper_out(offline):
    doc = copy.deepcopy(DOC)
    doc["zones"] = [
        {"kind": "pour", "net": "GND", "layer": "bottom"},
        {"kind": "pour", "net": "V3V3", "layer": "top", "rect": [4, -2, -4, 3]},
        {"kind": "keepout", "layers": ["top", "bottom"], "rect": [-12, -6, -8, -2]},
        {"kind": "pour", "net": "SPI"},  # no such net
        {"kind": "keepout", "layers": ["top"]},  # no rect
    ]
    doc, issues = device.normalize(doc)
    assert [i["code"] for i in issues] == ["bad_zone", "bad_zone"]
    assert doc["zones"][1] == {"kind": "pour", "net": "V3V3", "layer": "top", "rect": [-4.0, -2.0, 4.0, 3.0]}
    parts, _ = await device.resolve(doc)
    src = device.compile(doc, parts, (36, 35))["source"]
    assert '<copperpour layer="bottom" connectsTo="net.GND" clearance="0.3mm" />' in src
    assert 'connectsTo="net.V3V3" clearance="0.3mm" outline={[{ x: -4, y: -2 }, { x: 4, y: -2 }, { x: 4, y: 3 }, { x: -4, y: 3 }]}' in src
    assert '<keepout shape="rect" pcbX={-10} pcbY={-4} width={4} height={4} layers={["top", "bottom"]} />' in src
    got = device.changes(device.normalize(DOC)[0], doc)
    assert "GND copper pour on the bottom over the whole board" in got and any(g.startswith("keepout (no copper) on top and bottom") for g in got)


@needs_bundle
async def test_a_ground_pour_builds_into_the_copper(offline, real_pcb, no_store):
    doc = copy.deepcopy(DOC)
    doc["zones"] = [{"kind": "pour", "net": "GND", "layer": "bottom"}]
    b = (await no_store.build_device("p_test", doc))["build"]
    pours = [e for e in b["circuit_json"] if e["type"] == "pcb_copper_pour"]
    assert pours and pours[0]["layer"] == "bottom" and b["ok"] and not b["errors"], b["errors"][:3]


# ---------------------------------------------------------------- key switches and the board's 3D view
KEYPAD = {
    "schema": "fw.device/1", "title": "Macro pad", "board": {"holes": True, "w": 84, "h": 46},
    "nodes": [{"id": "U1", "kind": "module", "module": "113991054", "edge": "+y"},
              {"id": "U2", "kind": "chip", "lcsc": "C92489", "label": "BME280"},
              {"id": "C1", "kind": "capacitor", "value": "100nF", "label": "U2 decoupling"},
              *[{"id": f"SW{i}", "kind": "button", "switch": "mx", "label": f"key {i}"} for i in range(1, 5)]],
    "layouts": [{"pattern": "row", "nodes": ["SW1", "SW2", "SW3", "SW4"], "center": [0, -10], "pitch": 19.05}],
    "nets": [{"name": "GND", "pins": ["U1.GND", "SW1.B", "SW2.B", "SW3.B", "SW4.B", "U2.GND", "U2.SDO", "C1.2"]},
             {"name": "V3V3", "pins": ["U1.V3V3", "U2.VDD", "U2.VDDIO", "U2.CSB", "C1.1"]},
             {"name": "SDA", "pins": ["U1.SDA", "U2.SDI"]}, {"name": "SCL", "pins": ["U1.SCL", "U2.SCK"]},
             {"pins": ["U1.D0", "SW1.A"]}, {"pins": ["U1.D1", "SW2.A"]}, {"pins": ["U1.D2", "SW3.A"]}, {"pins": ["U1.D3", "SW4.A"]}],
}


def test_model_primitives_are_cleaned_and_an_unknown_switch_is_said():
    doc, issues = device.normalize({"nodes": [
        {"id": "SW1", "kind": "button", "switch": "alps"},
        {"id": "U2", "kind": "chip", "lcsc": "C92489", "model": [{"shape": "cyl", "at": [0, 0, 0], "size": [3, 3, 2], "color": "#112233"},
                                                                 {"shape": "box", "at": [0, 0], "size": [1, 1, 1]}]}]})
    assert {i["code"] for i in issues} == {"unknown_switch", "bad_model"}
    by_id = {n["id"]: n for n in doc["nodes"]}
    assert "switch" not in by_id["SW1"]
    assert [p["shape"] for p in by_id["U2"]["model"]] == ["cyl"]


@needs_bundle
async def test_key_switches_build_and_the_board_tells_the_case(offline, real_pcb):
    from iamodelize3d import deviceapi

    doc, issues = device.normalize(KEYPAD)
    assert not issues
    parts, more = await device.resolve(doc)
    assert not more and parts["SW1"]["switch"] == "mx" and deviceapi.pad_count(doc["nodes"][3], parts["SW1"]) == 2
    c = device.compile(doc, parts, (87, 46))
    b = await pcb.pool().build(c["source"], intent=c["intent"], lcsc=c["lcsc"])
    assert b["ok"] and not b["errors"], b["errors"][:3]
    device.dress_board(b["board"], doc, parts, b["circuit_json"])
    keys = [x for x in b["board"]["components"] if x.get("access") == "key"]
    assert len(keys) == 4 and all(k["key"]["cut"] == 14.0 and k["w"] == 14.0 for k in keys)
    # the centre of each switch is its peg hole, whatever the pads' box says, and the keys sit at their pitch
    pegs = {round(h["x"], 2) for h in b["board"]["pcb"]["holes"] if h.get("d") == 4}
    assert pegs == {round(k["x"], 2) for k in keys}
    xs = sorted(k["x"] for k in keys)
    assert all(abs(q - p - 19.05) < 0.02 for p, q in zip(xs, xs[1:]))


@needs_bundle
async def test_the_board_view_draws_real_models_and_the_module_as_itself(offline, real_pcb, monkeypatch):
    from iamodelize3d import deviceapi

    async def model_obj(raw):
        return ("uuid-in-test", "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    monkeypatch.setattr(catalog, "model_obj", model_obj)
    monkeypatch.setattr(catalog, "model_uuid", lambda raw: "uuid-in-test" if raw else None)
    doc, _ = device.normalize(KEYPAD)
    parts, _ = await device.resolve(doc)
    c = device.compile(doc, parts, (87, 46))
    b = await pcb.pool().build(c["source"], intent=c["intent"], lcsc=c["lcsc"])
    models = await deviceapi.part_models(doc, parts)
    assert list(models["objs"]) == ["uuid-in-test"] and models["parts"]["SW1"]["prims"]
    assert models["parts"]["U2"]["obj"] == "uuid-in-test" and len(models["parts"]["U2"]["at"]) == 3
    x = await pcb.pool().export(b["circuit_json"], models=models)
    assert x["files"]["board.glb"][:4] == b"glTF" and "glb_error" not in x
    # the module is its own footprint, no DIP model left to draw
    assert not any("dip14" in str(e.get("footprinter_string")) for e in b["circuit_json"] if e["type"] == "cad_component")


# ---------------------------------------------------------------- what DRC does not see
def _power_doc(**net):
    return {"schema": "fw.device/1", "title": "Load", "nodes": [
        {"id": "U1", "kind": "module", "module": "113991114", "edge": "+y"},
        {"id": "Q1", "kind": "chip", "lcsc": "C92489", "label": "x"},
        {"id": "J1", "kind": "header", "pins": ["LOAD", "GND"], "edge": "-y", **net.pop("header", {})},
    ], "nets": [{"pins": ["J1.LOAD", "U1.D0"], "name": "VLOAD", **net}, {"name": "GND", "pins": ["J1.GND", "U1.GND"]}]}


def test_trace_width_follows_ipc_2221():
    assert device.trace_mm(1) == pytest.approx(0.2, abs=0.05)
    assert device.trace_mm(5) == pytest.approx(1.8, abs=0.2)
    assert device.trace_mm(10) == pytest.approx(4.7, abs=0.3)


async def test_a_stated_current_is_held_to_the_contacts_and_the_copper(offline):
    from iamodelize3d import device_rules

    doc, _ = device.normalize(_power_doc(amps=10))
    assert next(n for n in doc["nets"] if n.get("name") == "VLOAD")["amps"] == 10
    codes = {f["code"]: f for f in device_rules.check(doc, (await device.resolve(doc))[0])}
    assert codes["connector_current"]["severity"] == "error" and "J1" in codes["connector_current"]["ref"]
    assert codes["trace_current"]["severity"] == "error"
    # a terminal rated for it and a pour for the net and ground answer both
    raw = _power_doc(amps=10, header={"connector": "terminal_5"})
    raw["zones"] = [{"kind": "pour", "net": "VLOAD", "layer": "top"}, {"kind": "pour", "net": "GND", "layer": "bottom"}]
    doc, issues = device.normalize(raw)
    assert not [i for i in issues if i["code"] in ("unknown_connector", "bad_zone")]
    found = {f["code"] for f in device_rules.check(doc, (await device.resolve(doc))[0])}
    assert not found & {"connector_current", "trace_current"}


async def test_named_currents_mains_and_unwired_inputs_are_errors(offline):
    from iamodelize3d import device_rules

    raw = _power_doc()
    raw["requirements"] = [{"id": "R1", "text": "тянет ток до 10 А", "parts": ["U1"]}]
    doc, _ = device.normalize(raw)
    assert "current_unstated" in {f["code"] for f in device_rules.check(doc, (await device.resolve(doc))[0])}
    raw = _power_doc()
    raw["nets"][0]["name"] = "MAINS"
    doc, _ = device.normalize(raw)
    assert "mains_on_board" in {f["code"] for f in device_rules.check(doc, (await device.resolve(doc))[0])}
    # a chip whose measured input is on no net: a current sensor that never sees a current
    doc, _ = device.normalize({"nodes": [{"id": "U1", "kind": "module", "module": "113991114"}, {"id": "U2", "kind": "chip", "lcsc": "C92489"}],
                               "nets": [{"pins": ["U2.GND", "U1.GND"], "name": "GND"}, {"pins": ["U2.VDD", "U1.V3V3"], "name": "V3V3"}]})
    parts, _ = await device.resolve(doc)
    parts["U2"]["pins"] = [{"num": "1", "name": "IP+", "label": "IPP"}, {"num": "2", "name": "IP-", "label": "IPN"}, {"num": "3", "name": "GND", "label": "GND"}, {"num": "4", "name": "VDD", "label": "VDD"}]
    found = {f["code"]: f for f in device_rules.check(doc, parts)}
    assert found["input_unwired"]["severity"] == "error" and "IP+" in found["input_unwired"]["msg"]


async def test_a_terminal_and_a_panel_switch_build_and_tell_the_case(offline, real_pcb):
    raw = {"schema": "fw.device/1", "title": "Pedal", "board": {"holes": True, "w": 60, "h": 60}, "nodes": [
        {"id": "U1", "kind": "module", "module": "113991114", "edge": "+y"},
        {"id": "SW1", "kind": "button", "switch": "stomp", "place": {"x": 0, "y": -7}},
        {"id": "J1", "kind": "header", "connector": "terminal_5", "pins": ["A", "B"], "edge": "-y"}],
        "nets": [{"name": "GND", "pins": ["U1.GND", "SW1.B", "J1.B"]}, {"pins": ["U1.D1", "SW1.A"]}, {"pins": ["U1.D2", "J1.A"]}]}
    doc, issues = device.normalize(raw)
    assert not issues
    parts, more = await device.resolve(doc)
    assert not more
    c = device.compile(doc, parts, (60, 60))
    b = await pcb.pool().build(c["source"], intent=c["intent"], lcsc=c["lcsc"])
    assert b["ok"] and not b["errors"], b["errors"][:3]
    device.dress_board(b["board"], doc, parts, b["circuit_json"])
    comps = {x["id"]: x for x in b["board"]["components"]}
    assert comps["SW1"]["access"] == "key" and comps["SW1"]["key"]["stem"] == "panel" and comps["SW1"]["h"] == 26.0
    assert comps["J1"]["access"] == "port" and comps["J1"]["edge"] == "-y" and comps["J1"]["w"] == 10.16


# ---------------------------------------------------------------- catalogue connectors on an edge
def test_a_connectors_mouth_is_where_its_body_stands_past_its_pads():
    pads = [f"PAD~RECT~{x}~{y}~4~4~11~~{i}~0~~0" for i, (x, y) in enumerate([(-10, 20), (10, 20), (-10, -5), (10, -5)], 1)]
    # the model's outline in the drawing sits towards -y of the canvas, which is +y on the board (the canvas's y runs down)
    outline = 'SVGNODE~{"attrs": {"c_rotation": "0,0,0", "z": "0"}, "childNodes": [{"attrs": {"points": "-20 -30 20 -30 20 10 -20 10"}}]}'
    raw = {"packageDetail": {"dataStr": {"head": {"x": 0, "y": 0}, "shape": [*pads, outline]}}}
    obj = "\n".join(f"v {x} {y} {z}" for x, y, z in [(-5, -3, 0), (5, -3, 0), (-5, 10, 6), (5, 10, 6)]) + "\nf 1 2 3\n"
    m = catalog.mouth_of(raw, obj)
    assert m and m["dir"] == "+y" and m["w"] == 10 and m["z1"] == 6
    # turned towards an edge, its offset along that edge turns with it
    assert device._mouth_shift({"dir": "+x", "across": 2.0}, 180, "+x") == pytest.approx(-2.0)
    # no pads, nothing to read
    assert catalog.mouth_of({"packageDetail": {"dataStr": {"head": {"x": 0, "y": 0}, "shape": []}}}, obj) is None
