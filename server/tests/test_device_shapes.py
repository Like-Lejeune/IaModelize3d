"""Board shapes and compaction (device.py, deviceapi.build_device; the outline in packages/pcb board.mjs): doc.board.shape
rect|rounded|round compiles to a tscircuit outline, the holes, the edge parts, the placement checks and the board's growth
follow the real outline, and board.json carries the polygon. A placed part running into the module lists the ways out with
the board each gives, smallest first and growth last with its cost; a board far larger than its parts says which smaller
arrangement exists. The boards of 2026-11-04 (58 x 81, 62 x 87 mm: the module on +y, an OLED under it, buttons under that)
are fixtures/device_shapes; a round night light and the timer with its module on a side edge build through the real bundle."""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

import pytest
from test_device_compile import RAW, catalogue, dice_doc, needs_bundle, real_pcb, timer_doc  # noqa: F401 - fixtures

from formwright import device, pcb
from formwright.config import REPO_DIR

FIX = Path(__file__).parent / "fixtures" / "device_shapes"
GRAPHS = {k: v for k, v in json.loads((FIX / "graphs.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
XIAO = {"id": "U1", "kind": "module", "module": "113991054"}


def doc_of(board: dict, *nodes: dict, nets: list | None = None) -> dict:
    return device.normalize({"title": "x", "board": board, "nodes": [dict(XIAO), *nodes],
                             "nets": nets or [{"name": "GND", "pins": ["U1.GND"]}]})[0]


def corners_inside(o: dict, rect: tuple, tol: float = 0.02) -> bool:
    return all(device._outside(o, x, y) <= tol for x, y in device._corners(rect))


def rect_of(doc: dict, size: tuple, nid: str) -> tuple:
    return next(f["rect"] for f in device.fixed_parts(doc, {}, size) if f["id"] == nid)


async def resolved(raw: dict) -> tuple[dict, dict, list]:
    doc, issues = device.normalize(copy.deepcopy(raw))
    parts, more = await device.resolve(doc)
    return doc, parts, issues + more


# ---------------------------------------------------------------- the outline
def test_normalize_keeps_shape_and_radius_and_names_the_allowed_values():
    d, issues = device.normalize({"title": "x", "board": {"shape": "round", "w": 60, "h": 40}, "nodes": [], "nets": []})
    assert d["board"] == {"holes": True, "w": 60.0, "h": 60.0, "shape": "round"} and not issues
    assert device.normalize({"title": "x", "board": {"shape": "ROUND", "h": 50}})[0]["board"]["w"] == 50
    d, issues = device.normalize({"title": "x", "board": {"shape": "oval", "w": 40, "h": 30}})
    assert "shape" not in d["board"] and issues[0]["code"] == "board_shape" and "rect, rounded, round" in issues[0]["msg"]
    d, issues = device.normalize({"title": "x", "board": {"shape": "rounded", "w": 40, "h": 30, "r": 100}})
    assert d["board"]["r"] == 15 and not issues
    d, issues = device.normalize({"title": "x", "board": {"shape": "rounded", "w": 40, "h": 30, "r": "soft"}})
    assert "r" not in d["board"] and issues[0]["ref"] == "r"
    assert device.outline(d, (40, 30))["r"] == 5  # a sixth of the shorter side
    # what a rect board always was: no new keys, so a saved board's key and its built version stay what they were
    assert device.normalize({"title": "x", "board": {"w": 40, "h": 30}})[0]["board"] == {"holes": True, "w": 40.0, "h": 30.0}
    assert "board shape round" in device.changes({"board": {}}, {"board": {"shape": "round"}})


def test_compile_gives_the_board_its_outline():
    src = device.compile(doc_of({"shape": "round", "w": 60}), {}, (60, 60))["source"]
    head = next(ln for ln in src.splitlines() if "<board " in ln)
    assert "outline={[" in head and 'width="' not in head
    pts = re.findall(r"\{ x: (-?[\d.]+), y: (-?[\d.]+) \}", head)
    assert len(pts) == device.ROUND_SEGMENTS and pts[0] == ("30", "0")
    assert all(math.isclose(math.hypot(float(x), float(y)), 30, abs_tol=0.01) for x, y in pts)

    doc = doc_of({"shape": "rounded", "w": 50, "h": 40, "r": 8})
    head = next(ln for ln in device.compile(doc, {}, (50, 40))["source"].splitlines() if "<board " in ln)
    pts = [(float(x), float(y)) for x, y in re.findall(r"\{ x: (-?[\d.]+), y: (-?[\d.]+) \}", head)]
    assert len(pts) == 4 * (device.CORNER_SEGMENTS + 1) and max(p[0] for p in pts) == 25 and max(p[1] for p in pts) == 20
    assert max(abs(x) + abs(y) for x, y in pts) < 25 + 20 - 3  # the corners are cut

    head = next(ln for ln in device.compile(doc_of({"w": 40, "h": 30}), {}, (40, 30))["source"].splitlines() if "<board " in ln)
    assert 'width="40mm" height="30mm"' in head and "outline" not in head


@pytest.mark.parametrize("board,size", [({"shape": "round", "w": 60}, (60, 60)), ({"shape": "rounded", "w": 50, "h": 40, "r": 8}, (50, 40)),
                                        ({"shape": "rounded", "w": 50, "h": 40, "r": 2}, (50, 40)), ({"w": 50, "h": 40}, (50, 40))])
def test_mounting_holes_sit_inside_the_outline(board, size):
    doc = doc_of(board)
    o = device.outline(doc, size)
    holes = device._holes(doc, *size)
    assert len(holes) == 4
    for x, y in holes:
        assert device._outside(o, x, y) == pytest.approx(-device.RIM_MM, abs=0.05)  # as far in from the edge as at a rect's corner
    src = device.compile(doc, {}, size)["source"]
    assert all(f"pcbX={{{x:g}}} pcbY={{{y:g}}}" in src for x, y in holes)
    if board.get("shape") == "round":
        assert all(abs(x) == abs(y) for x, y in holes)  # on the diagonals
    assert not device._holes(doc_of({**board, "holes": False}), *size)


def test_edge_parts_sit_on_the_rim_with_their_bodies_inside():
    W = H = 60.0
    doc = doc_of({"shape": "round", "w": 60}, {"id": "J1", "kind": "usb_c", "edge": "-y"}, {"id": "J2", "kind": "jst", "edge": "+x"})
    o = device.outline(doc, (W, H))
    for nid in ("U1", "J1", "J2"):
        r = rect_of(doc, (W, H), nid)
        assert corners_inside(o, r), (nid, r)
        # its outer corners are at the rim, not far short of it (a JST stops 0.4 mm short of any edge)
        assert max(device._outside(o, x, y) for x, y in device._corners(r)) > -0.5, (nid, r)
    r = rect_of(doc, (W, H), "U1")
    assert r[0] == pytest.approx(-8.9, abs=0.01) and r[2] == pytest.approx(8.9, abs=0.01)
    assert 28.5 < r[3] < 28.7  # the chord at x = 8.9, 1.4 mm under the top of the circle

    # two parts on one side: along the side up to the holes on the diagonals, each on its own chord
    doc = doc_of({"shape": "round", "w": 60}, {"id": "J1", "kind": "usb_c", "edge": "-y"}, {"id": "J2", "kind": "jst", "edge": "-y"})
    a, b = rect_of(doc, (W, H), "J1"), rect_of(doc, (W, H), "J2")
    assert corners_inside(o, a) and corners_inside(o, b) and not device._overlap(a, b)
    keep = device.HOLE_KEEP_MM
    for x, y in device._holes(doc, W, H):
        assert not device._overlap(a, (x - keep, y - keep, x + keep, y + keep)) and not device._overlap(b, (x - keep, y - keep, x + keep, y + keep))

    # a rounded board's straight stretch takes them where a rect would; a rect is untouched
    doc = doc_of({"shape": "rounded", "w": 60, "h": 50})
    assert rect_of(doc, (60, 50), "U1")[3] == 25
    assert device.layout_edges(doc_of({"w": 60, "h": 50}), {}, 60, 50)["U1"] == {"pcbX": 0.0, "pcbY": 14.5, "pcbRotation": 0}


def test_placed_parts_are_tested_against_the_real_outline():
    # inside the 60 x 60 mm bounding box, outside the circle
    sw = {"id": "SW1", "kind": "button", "place": {"x": 22, "y": -22}}
    doc = doc_of({"shape": "round", "w": 60, "holes": False}, sw, nets=[{"name": "GND", "pins": ["U1.GND", "SW1.B"]}])
    out = [c for c in device.conflicts(doc, {}, (60, 60)) if c["kind"] == "outline"]
    assert out and out[0]["a"]["id"] == "SW1" and out[0]["by"] > 3
    W, H = device.estimate(doc, {})
    assert W == H > 60 and device._outside(device.outline(doc, (W, H)), 25.5, -26.5) <= 0  # grown as a circle, until it is inside

    locked = device.normalize({**doc, "board": {**doc["board"], "locked": True}})[0]
    msg = next(i["msg"] for i in device.place_issues(locked, {}) if i["ids"] == ["SW1"])
    assert "past the round board's rim" in msg and "board.w >=" in msg and "60 mm round board" in msg and "within 30 mm of the centre" in msg

    # the same part clear of the rim: nothing to say, where a rect with corners is what it fits
    doc = doc_of({"shape": "round", "w": 60, "holes": False}, {"id": "SW1", "kind": "button", "place": {"x": 14, "y": -14}})
    assert not device.conflicts(doc, {}, (60, 60)) and device.estimate(doc, {}) == (60, 60)

    # a rounded board's corner is cut: past the arc, though inside the rectangle
    led = {"id": "LED1", "kind": "led", "place": {"x": 21, "y": -16}}
    assert not device.conflicts(doc_of({"w": 50, "h": 40, "holes": False}, led), {}, (50, 40))
    got = device.conflicts(doc_of({"shape": "rounded", "w": 50, "h": 40, "r": 12, "holes": False}, led), {}, (50, 40))
    assert got and got[0]["kind"] == "outline"

    # a module that sits on the board by default keeps its body's corners inside the circle
    doc = doc_of({"shape": "round", "w": 70}, {"id": "DS1", "kind": "accessory", "accessory": "oled_096_i2c"})
    body = device.accessory_places(doc, {}, 70, 70)["DS1"]
    assert corners_inside(device.outline(doc, (70, 70)), (body["x"] - 13.65, body["y"] - 13.9, body["x"] + 13.65, body["y"] + 13.9))


# ---------------------------------------------------------------- the ways out
async def test_a_conflict_lists_the_ways_out_smallest_board_first_and_growth_last_with_its_cost(catalogue):
    """p_ca81339b063a4319 v1: the message said 'put DS1 at y <= -6.2, or board.h >= 99' and the designer took 58 x 81."""
    doc, parts, issues = await resolved(GRAPHS["timer_v1"])
    msg = next(i["msg"] for i in issues if i["code"] == "place_conflict" and set(i["ids"]) == {"DS1", "U1"})
    assert "move U1" not in msg
    assert ("Ways out, smallest board first: (1) put U1 on the -x edge and DS1 at x >= 8.9 and SW1 at y <= -13.7: 57 x 58 mm; "
            "(2) put DS1 at y <= -6.2: 52 x 58 mm, but DS1 then overlaps SW1, SW2, SW3; "
            "(3) last, board.h >= 99 (the +y edge moves out by half of what it grows): grows the board to 52 x 99 mm, +71% area") in msg
    # the first way is what it says: every move applied, the board the build sizes is that one, nothing left in the way
    node = lambda nid: next(n for n in doc["nodes"] if n["id"] == nid)  # noqa: E731
    node("U1")["edge"] = "-x"
    node("DS1")["place"]["x"] = 8.95
    node("SW1")["place"]["y"] = -13.7
    assert device.sized(doc, parts) == ((57.0, 58.0), [])


async def test_a_ring_layout_gets_the_module_edge_alternative_and_a_turn_is_listed_when_it_fits_better(catalogue):
    leds = [f"LED{i}" for i in range(1, 5)]
    doc, parts, issues = await resolved({"title": "x", "board": {"holes": True, "w": 58, "h": 58}, "nodes": [dict(XIAO)]
                                         + [{"id": n, "kind": "chip", "lcsc": "C2843785"} for n in leds] + [{"id": "SW1", "kind": "button", "place": {"x": 0, "y": -20}}],
                                         "layouts": [{"pattern": "ring", "nodes": leds, "center": [0, 5], "radius": 14}],
                                         "nets": [{"name": "GND", "pins": ["U1.GND", "SW1.B"] + [f"{n}.GND" for n in leds]}]})
    msg = next(i["msg"] for i in issues if i["code"] == "place_conflict" and "U1" in i["ids"])
    assert re.search(r"\(1\) put U1 on the -x edge and its center at x >= [\d.]+: 58 x 58 mm; \(2\) put its center at y <= -9\.8: 58 x 58 mm, "
                     r"but the ring layout then overlaps SW1; \(3\) last, board\.h >= 88: grows the board to 58 x 88 mm, \+52% area", msg), msg
    # without the button in the way the plain move is as small, and the module stays put
    doc, parts, issues = await resolved({"title": "x", "board": {"holes": True, "w": 58, "h": 58}, "nodes": [dict(XIAO)]
                                         + [{"id": n, "kind": "chip", "lcsc": "C2843785"} for n in leds],
                                         "layouts": [{"pattern": "ring", "nodes": leds, "center": [0, 5], "radius": 14}],
                                         "nets": [{"name": "GND", "pins": ["U1.GND"] + [f"{n}.GND" for n in leds]}]})
    msg = next(i["msg"] for i in issues if i["code"] == "place_conflict" and "U1" in i["ids"])
    assert "(1) put its center at y <= -9.8: 58 x 58 mm; (2) last, board.h >= 88" in msg and "on the -x edge" not in msg, msg
    # a long header across the module's band: down it lands on the button, across it does not fit; turned, it stands beside
    raw = {"title": "x", "board": {"holes": True, "w": 50, "h": 60}, "nodes": [
        dict(XIAO), {"id": "J1", "kind": "header", "pins": [f"P{i}" for i in range(1, 9)], "place": {"x": 13, "y": 22}},
        {"id": "SW1", "kind": "button", "place": {"x": 3, "y": 4}}],
        "nets": [{"name": "GND", "pins": ["U1.GND", "J1.P1", "SW1.B"]}]}
    doc, parts, issues = await resolved(raw)
    msg = next(i["msg"] for i in issues if i["code"] == "place_conflict" and "U1" in i["ids"])
    assert "turn J1 by 90 degrees (rot 90): 50 x 67 mm" in msg and "J1 then overlaps SW1" in msg, msg  # EDGE_MARGIN_MM: 66 had it flush
    assert msg.index("turn J1") < msg.index("put J1 at y") < msg.index("last, board.h >= 91")


# ---------------------------------------------------------------- a board far larger than its parts
async def test_the_timer_is_told_its_smaller_arrangement_and_the_dice_is_not(catalogue):
    doc, parts, _ = await resolved(GRAPHS["timer"])
    assert device.estimate(doc, parts) == (58, 81)
    got = [w for w in device.lint(doc, parts) if w["code"] == "board_too_large"]
    assert len(got) == 1 and got[0]["ref"] == "board"
    msg = got[0]["msg"]
    assert re.match(r"the board \(58 x 81 mm, 4698 mm²\) is 3\.\d x what its parts take \(\d+ mm²\), and a smaller arrangement exists: "
                    r"put U1 on the -x edge and DS1 at x >= 10\.4: about 55 x 50 mm \(41% less area\), with board\.w/h lowered to it or left out; "
                    r"write_device edits \[\{op:'compact'\}\] applies it$", msg), msg
    # what it says is so: applied, that is the board, and nothing more to say about it
    best = device.compaction(doc, parts)
    assert best["size"] == [55, 50]  # 49 had the buttons' courtyards flush with the edge (EDGE_MARGIN_MM)
    next(n for n in doc["nodes"] if n["id"] == "U1")["edge"] = "-x"
    next(n for n in doc["nodes"] if n["id"] == "DS1")["place"]["x"] = 10.45
    doc["board"].pop("w"), doc["board"].pop("h")
    assert device.sized(doc, parts) == ((55.0, 50.0), [])
    assert not [w for w in device.lint(doc, parts) if w["code"] == "board_too_large"]

    # the soil sensor too; the person's own size stays theirs; a pattern's spacing is what it is for
    doc, parts, _ = await resolved(GRAPHS["soil"])
    assert "put U1 on the -x edge" in device.compaction(doc, parts)["msg"]
    locked, _ = device.normalize({**GRAPHS["soil"], "board": {"holes": True, "w": 62, "h": 87, "locked": True}})
    assert device.compaction(locked, parts) is None
    doc, parts, _ = await resolved(dice_doc())
    assert device.footprint_area(doc, parts) > 2 * 7 * 2.96 * 1.46  # the die's box, not seven LEDs
    assert device.compaction(doc, parts) is None
    doc, parts, _ = await resolved(GRAPHS["night_light"])  # 60 x 72 mm: a ring that wide is its look
    assert device.compaction(doc, parts) is None


async def test_placed_parts_on_each_other_speak_first_and_the_ratio_alone_says_nothing(catalogue):
    doc, parts, _ = await resolved(timer_doc(ds1_y=-9.2))
    assert any(c["kind"] == "part" for c in device.conflicts(doc, parts, device.estimate(doc, parts)))
    assert device.compaction(doc, parts) is None
    # parts the packer places need their room: a board of small parts has a high ratio and nothing smaller than base_size
    raw = {"title": "x", "board": {"holes": True}, "nodes": [dict(XIAO)] + [{"id": f"R{i}", "kind": "resistor", "value": "1k"} for i in range(1, 7)],
           "nets": [{"name": "GND", "pins": ["U1.GND"] + [f"R{i}.1" for i in range(1, 7)]}]}
    doc, parts, _ = await resolved(raw)
    assert device.compaction(doc, parts) is None
    # the estimate's margin on a small board is no finding: 36 x 40 -> 31 x 36 mm saves 324 mm²
    doc, parts, _ = await resolved({"title": "x", "nodes": [dict(XIAO), {"id": "J1", "kind": "usb_c", "edge": "-y"}, {"id": "SW1", "kind": "button"},
                                                            {"id": "U2", "kind": "chip", "lcsc": "C92489"}, {"id": "LED1", "kind": "led"}],
                                    "nets": [{"name": "GND", "pins": ["U1.GND", "U2.GND", "LED1.K", "J1.GND"]}]})
    assert device.board_area(doc, device.estimate(doc, parts)) > device.COMPACT_RATIO * device.footprint_area(doc, parts)
    assert device.compaction(doc, parts) is None


def test_growth_is_said_with_its_cost_and_its_cause():
    doc = device.normalize(timer_doc(buttons=False))[0]
    assert device.estimate(doc, {}) == (48, 91)
    got = device.growth_report(doc, {}, (48, 91), [{"size_mm": [48, 91], "errors": 0, "ok": True}])
    assert got["from"] == [48, 52] and got["to"] == [48, 91] and got["pct"] == 75
    assert got["msg"] == ("the build grew the board from 48 x 52 mm to 48 x 91 mm (+75% area): to 48 x 91 mm before routing to clear "
                          "DS1 into U1 on the +y edge")
    got = device.growth_report(doc, {}, (57, 108), [{"size_mm": [48, 91], "errors": 2, "ok": False, "first": "Unable to pack all PCB components"},
                                                    {"size_mm": [57, 108], "errors": 0, "ok": True}])
    assert "to 57 x 108 mm after 48 x 91 mm failed (Unable to pack all PCB components)" in got["msg"] and "(+147% area)" in got["msg"]
    # asked for and built: nothing to say
    clear = device.normalize(timer_doc(ds1_y=-9.2, buttons=False))[0]
    assert device.growth_report(clear, {}, (48, 52), [{"size_mm": [48, 52], "errors": 0, "ok": True}]) is None
    # past the chosen concept's board by more than a fifth, even when the designer's own size was never exceeded
    concept = {"chosen": "Puck", "options": [{"name": "Puck", "board": {"shape": "round", "w": 50, "h": 50}}]}
    got = device.growth_report({**clear, "concept": concept}, {}, (48, 52), [{"size_mm": [48, 52], "errors": 0, "ok": True}])
    assert got["concept"] == {"name": "Puck", "size": [50, 50], "pct": 27}
    assert got["msg"] == "it is past the board of the chosen concept 'Puck' (50 mm round) by 27% of its area: rearrange it (the hints say how) or change the concept"
    concept["options"][0]["board"] = {"shape": "rect", "w": 46, "h": 50}
    assert device.growth_report({**clear, "concept": concept}, {}, (48, 52), [{"size_mm": [48, 52], "errors": 0, "ok": True}]) is None


# ---------------------------------------------------------------- through the real bundle
def round_night_light() -> dict:
    """The night light of p_506b3c2ec8ec4b09 as a puck: the XIAO on the rim, the ring of WS2812s around the PIR."""
    d = copy.deepcopy(GRAPHS["night_light"])
    d["board"] = {"holes": True, "shape": "round", "w": 60}
    d["layouts"] = [{"pattern": "ring", "nodes": ["LED1", "LED2", "LED3", "LED4"], "center": [0, -9], "radius": 14, "rot": 45}]
    for n in d["nodes"]:
        if n["id"] == "U2":
            n["place"] = {"x": 0, "y": -9, "rot": 0}
        if n["id"] == "SW1":
            n["place"] = {"x": -21, "y": 6, "rot": 0}
    return d


@pytest.fixture
def no_store(monkeypatch):
    from formwright import deviceapi

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
async def test_a_round_night_light_builds_clean_and_board_json_carries_the_circle(catalogue, real_pcb, no_store):
    res = await no_store.build_device("p_test", round_night_light())
    assert res["ok"] and res["size_mm"] == [60, 60] and not res["build"]["errors"], (res["attempts"], res["build"]["errors"][:2])
    assert res["growth"] is None
    board = res["build"]["board"]
    ol = board["pcb"]["outline"]
    assert ol["kind"] == "poly" and ol["shape"] == "round" and ol["r"] == 30 and (ol["w"], ol["h"]) == (60, 60) and len(ol["points"]) == device.ROUND_SEGMENTS
    assert all(math.isclose(math.hypot(x - 30, y - 30), 30, abs_tol=0.02) for x, y in ol["points"])
    mounts = [h for h in board["pcb"]["holes"] if h["use"] == "mount"]
    assert len(mounts) == 4 and all(math.hypot(h["x"] - 30, h["y"] - 30) == pytest.approx(26.5, abs=0.02) for h in mounts)
    # every part inside the circle, the module's own USB-C still a port at the rim
    comps = {c["id"]: c for c in board["components"]}
    for c in board["components"]:
        if c.get("access") != "port":
            for sx in (-1, 1):
                for sy in (-1, 1):
                    assert math.hypot(c["x"] + sx * c["w"] / 2 - 30, c["y"] + sy * c["d"] / 2 - 30) <= 30.05, c["id"]
    usb = comps["U1_usb"]
    assert usb["access"] == "port" and usb["edge"] == "+y" and usb["at"] == 30 and -1 < usb["protrude"] < 0
    assert comps["LED1"]["access"] == "light" and comps["U2"]["access"] == "sensor"
    # what the case reads, and the schema it is written to
    schema = json.loads((REPO_DIR / "packages" / "geom" / "src" / "board.schema.json").read_text(encoding="utf-8"))
    poly = schema["properties"]["pcb"]["properties"]["outline"]["oneOf"][1]
    assert set(poly["required"]) <= set(ol) and poly["properties"]["kind"]["const"] == ol["kind"]


@needs_bundle
async def test_edge_parts_off_the_middle_of_a_round_rim_stay_ports_and_a_rounded_board_builds(catalogue):
    # board.mjs measures an edge part's gap from the outline, not the bounding box: off the middle the rim drops away
    doc = doc_of({"shape": "round", "w": 50, "holes": False}, {"id": "J1", "kind": "usb_c", "edge": "-y"}, {"id": "J2", "kind": "jst", "edge": "-y"},
                 nets=[{"name": "GND", "pins": ["U1.GND", "J1.GND", "J2.P2"]}, {"name": "V5", "pins": ["U1.V5", "J1.VBUS"]}, {"pins": ["U1.D0", "J2.P1"]}])
    parts, _ = await device.resolve(doc)
    c = device.compile(doc, parts, (50, 50))
    old, pcb._pool = pcb._pool, pcb.PcbPool(1)
    try:
        b = await pcb.pool().build(c["source"], intent=c["intent"], lcsc=c["lcsc"])
        assert b["intent"]["ok"], b["intent"]
        comps = {x["id"]: x for x in b["board"]["components"]}
        assert comps["J1"]["access"] == "port" and comps["J1"]["edge"] == "-y" and comps["J2"]["access"] == "port" and comps["J2"]["edge"] == "-y"
        assert abs(comps["J1"]["at"] - 25) > 5 and abs(comps["J2"]["at"] - 25) > 5

        doc = doc_of({"shape": "rounded", "w": 40, "h": 50, "r": 8}, {"id": "J1", "kind": "usb_c", "edge": "-y"},
                     nets=[{"name": "GND", "pins": ["U1.GND", "J1.GND"]}, {"name": "V5", "pins": ["U1.V5", "J1.VBUS"]}])
        parts, _ = await device.resolve(doc)
        c = device.compile(doc, parts, (40, 50))
        b = await pcb.pool().build(c["source"], intent=c["intent"], lcsc=c["lcsc"])
        assert b["ok"] and not b["errors"], b["errors"][:3]
        board = device.dress_board(b["board"], doc, parts, b["circuit_json"])
        ol = board["pcb"]["outline"]
        assert ol["kind"] == "poly" and ol["shape"] == "rounded" and ol["r"] == 8 and (ol["w"], ol["h"]) == (40, 50)
    finally:
        await pcb._pool.close()
        pcb._pool = old


@needs_bundle
async def test_the_timer_with_its_module_on_a_side_edge_builds_smaller(catalogue, real_pcb, no_store):
    """The arrangement the compactness warning names, on the real parts: 58 x 81 mm becomes 55 x 50 mm, DRC clean."""
    d = copy.deepcopy(GRAPHS["timer"])
    d["board"] = {"holes": True}
    for n in d["nodes"]:
        if n["id"] == "U1":
            n["edge"] = "-x"
        if n["id"] == "DS1":
            n["place"]["x"] = 10.45
    res = await no_store.build_device("p_test", d)
    assert res["ok"] and not res["build"]["errors"], (res["attempts"], res["build"]["errors"][:2])
    assert res["size_mm"] == [55, 50]
    assert next(c for c in res["build"]["board"]["components"] if c["id"] == "U1_usb")["edge"] == "-x"
    # it grew a little past the first estimate to clear the holes, and said so where the designer reads
    assert res["growth"]["from"] == [49, 49] and res["growth"]["to"] == [55, 50]
    assert res["lint"][0]["code"] == "board_grew" and "SW1 on a mounting hole" in res["lint"][0]["msg"]
