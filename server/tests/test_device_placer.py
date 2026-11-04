"""The device placer (device.arrange, room; deviceapi.build_device): every part nobody placed gets its spot from the compiler,
inside the real outline, clear of the fixed parts, the holes and each other, near the pins it connects, deterministic. tscircuit's
packer failed on boards with plenty of room (a 2290 mm² disc for 675 mm² of parts: 'No valid candidates found'), so the attempt
loop grew the board until it got lucky. The bench_* graphs of fixtures/device_shapes are those boards (scripts/device_bench.py)."""
from __future__ import annotations

import copy
import json
import math

import pytest
from test_device_compile import RAW, catalogue, needs_bundle, real_pcb  # noqa: F401 - fixtures
from test_device_shapes import GRAPHS, XIAO, doc_of, no_store, resolved  # noqa: F401 - fixtures

from formwright import db as dbmod
from formwright import device, device_store, geom as geommod, pcb, pcb_store
from formwright.agent import device_inspect as di
from formwright.agent import elec_tools as et
from formwright.agent.tools import DesignState
from formwright.config import settings
from formwright.geom import GeomPool

BENCH = sorted(k for k in GRAPHS if k.startswith("bench_"))
LED_NETS = [{"name": "GND", "pins": ["U1.GND", "LED1.K", "LED2.K", "LED3.K"]}, {"pins": ["U1.D0", "R1.1"]}, {"pins": ["R1.2", "LED1.A"]},
            {"pins": ["U1.D1", "R2.1"]}, {"pins": ["R2.2", "LED2.A"]}, {"pins": ["U1.D2", "R3.1"]}, {"pins": ["R3.2", "LED3.A"]}]
LEDS = [{"id": f"LED{i}", "kind": "led"} for i in (1, 2, 3)] + [{"id": f"R{i}", "kind": "resistor", "value": "330"} for i in (1, 2, 3)]


def everything(doc: dict, parts: dict, size: tuple, got: dict) -> list[tuple[str, tuple]]:
    return [(f["id"], f["rect"]) for f in device.fixed_parts(doc, parts, size)] + list(got["rects"].items())


def assert_sound(doc: dict, parts: dict, size: tuple, got: dict) -> None:
    """Every free courtyard inside the real outline by the rim, its gap from every other part (bar its own chip), off the holes."""
    assert not got["missing"]
    gap = got["gap"]
    o = device.outline(doc, size)
    fixed = {f["id"]: f for f in device.fixed_parts(doc, parts, size)}
    plan, _ = device.decoupling(doc, parts)
    held = {cap: chip for chip, caps in plan.items() for cap, *_ in caps}
    rects = everything(doc, parts, size, got)
    for nid, r in got["rects"].items():
        assert all(device._outside(o, x, y) <= -got["rim"] + 0.01 for x, y in device._corners(r)), (nid, r, o)
        for hx, hy in device._holes(doc, *size):
            k = device.HOLE_KEEP_MM
            assert not device._overlap(r, (hx - k, hy - k, hx + k, hy + k)), (nid, r, (hx, hy))
        for other, b in rects:
            if other == nid or held.get(nid) == other or held.get(other) == nid or (held.get(nid) and held.get(nid) == held.get(other)):
                continue
            assert not device._overlap(r, b, gap - 0.06), (nid, r, other, b)
    assert not set(got["place"]) & set(fixed)


# ---------------------------------------------------------------- where parts go
@pytest.mark.parametrize("board", [{"w": 44, "h": 38}, {"shape": "rounded", "w": 44, "h": 38, "r": 9}, {"shape": "round", "w": 48}, {"w": 40, "h": 40, "holes": False}])
def test_free_parts_land_inside_the_real_outline_clear_of_everything(board):
    doc = doc_of(board, *copy.deepcopy(LEDS), nets=copy.deepcopy(LED_NETS))
    size = device.estimate(doc, {})
    got = device.arrange(doc, {}, size)
    assert set(got["place"]) == {"LED1", "LED2", "LED3", "R1", "R2", "R3"}
    assert_sound(doc, {}, size, got)
    source = device.compile(doc, {}, size)["source"]
    assert "pcbPack" not in source and "<group" not in source and "<resistor name=\"R1\" resistance=\"330\" footprint=\"0603\" pcbX=" in source


@pytest.mark.parametrize("name", BENCH)
async def test_the_bench_boards_get_a_spot_for_every_free_part_at_the_size_estimate_says(name, catalogue):
    doc, parts, _ = await resolved(GRAPHS[name])
    size = device.estimate(doc, parts)
    got = device.arrange(doc, parts, size)
    assert_sound(doc, parts, size, got)
    want = {n["id"] for n in doc["nodes"] if device.local_box(n, parts.get(n["id"])) and n["kind"] != "hole"} - {f["id"] for f in device.fixed_parts(doc, parts, size)}
    assert set(got["place"]) == want and want
    # the same document, the same board, to the character
    again, parts2, _ = await resolved(GRAPHS[name])
    assert device.arrange(again, parts2, size) == got
    assert device.compile(doc, parts, size)["source"] == device.compile(again, parts2, size)["source"]


def test_a_part_keeps_to_the_pins_it_connects_and_its_pads_face_them():
    """A resistor between the MCU and an LED by the LED, turned so that the pad on that net is the near one."""
    led = {"id": "LED1", "kind": "led", "place": {"x": 14, "y": -12}}
    doc = doc_of({"w": 50, "h": 50}, led, {"id": "R1", "kind": "resistor", "value": "330"},
                 nets=[{"name": "GND", "pins": ["U1.GND", "LED1.K"]}, {"pins": ["U1.D0", "R1.1"]}, {"pins": ["R1.2", "LED1.A"]}])
    size = device.estimate(doc, {})
    got = device.arrange(doc, {}, size)
    p = got["place"]["R1"]
    pad2 = device._turn((0.82, 0.0), p["pcbRotation"])
    assert math.hypot(p["pcbX"] + pad2[0] - (14 - 0.82), p["pcbY"] + pad2[1] + 12) < 4.0, p  # next to the anode
    pad1 = device._turn((-0.82, 0.0), p["pcbRotation"])
    assert math.hypot(p["pcbX"] + pad1[0] - (14 - 0.82), p["pcbY"] + pad1[1] + 12) > math.hypot(p["pcbX"] + pad2[0] - (14 - 0.82), p["pcbY"] + pad2[1] + 12)


async def test_a_chip_keeps_its_decoupling_capacitor_at_its_supply_pin_as_one_unit(catalogue):
    doc, parts, _ = await resolved({"title": "x", "board": {"w": 50, "h": 50}, "nodes": [dict(XIAO), {"id": "U2", "kind": "chip", "lcsc": "C92489"},
                                    {"id": "C1", "kind": "capacitor", "label": "U2 decoupling"}],
                                    "nets": [{"name": "GND", "pins": ["U1.GND", "U2.GND", "C1.2"]}, {"name": "V3V3", "pins": ["U1.3V3", "U2.VDD", "C1.1"]},
                                             {"name": "SDA", "pins": ["U1.SDA", "U2.SDA"]}]})
    plan, _ = device.decoupling(doc, parts)
    assert [c for c, *_ in plan["U2"]] == ["C1"]
    size = device.estimate(doc, parts)
    got = device.arrange(doc, parts, size)
    assert_sound(doc, parts, size, got)
    u2, c1 = got["place"]["U2"], got["place"]["C1"]
    label = plan["U2"][0][1]
    num = next(p["num"] for p in parts["U2"]["pins"] if p["label"] == label)
    px, py = device._turn(tuple(parts["U2"]["pads"][num][:2]), u2["pcbRotation"])
    assert math.hypot(c1["pcbX"] - (u2["pcbX"] + px), c1["pcbY"] - (u2["pcbY"] + py)) < 4.0, (u2, c1)
    src = device.compile(doc, parts, size)["source"]
    assert "<group" not in src and 'maxDecouplingTraceLength={10}' in src


def test_what_is_placed_stays_put_and_a_keepout_is_kept_out():
    sw = {"id": "SW1", "kind": "button", "place": {"x": 10, "y": -10}}
    pin = {"id": "LED1", "kind": "led", "pcb": {"x": -12, "y": -14, "rot": 90}}
    doc = doc_of({"w": 50, "h": 50}, sw, pin, {"id": "R1", "kind": "resistor", "value": "1k"},
                 nets=[{"name": "GND", "pins": ["U1.GND", "SW1.B", "LED1.K"]}, {"pins": ["U1.D0", "SW1.A"]}, {"pins": ["U1.D1", "R1.1"]}, {"pins": ["R1.2", "LED1.A"]}])
    size = device.estimate(doc, {})
    placed = device.compile(doc, {}, size)["placed"]
    assert placed["SW1"] == {"pcbX": 10, "pcbY": -10, "pcbRotation": 0} and placed["LED1"] == {"pcbX": -12, "pcbY": -14, "pcbRotation": 90}
    r = device.arrange(doc, {}, size)["rects"]["R1"]
    # the spot R1 likes, kept out: it goes elsewhere
    doc["zones"] = [{"kind": "keepout", "layers": ["top"], "rect": [r[0] - 1, r[1] - 1, r[2] + 1, r[3] + 1]}]
    moved = device.arrange(doc, {}, size)["rects"]["R1"]
    assert not device._overlap(moved, tuple(doc["zones"][0]["rect"]))
    # a board-mounted module's body counts, not only its header: nothing goes under it
    doc = doc_of({"w": 50, "h": 60}, {"id": "DS1", "kind": "accessory", "accessory": "oled_096_i2c"}, {"id": "R1", "kind": "resistor", "value": "4k7"},
                 nets=[{"name": "SDA", "pins": ["U1.SDA", "DS1.SDA", "R1.2"]}, {"name": "V3V3", "pins": ["U1.3V3", "DS1.VCC", "R1.1"]}, {"name": "GND", "pins": ["U1.GND", "DS1.GND"]}])
    size = device.estimate(doc, {})
    got = device.arrange(doc, {}, size)
    body = next(f["rect"] for f in device.fixed_parts(doc, {}, size) if f["id"] == "DS1")
    assert not device._overlap(got["rects"]["R1"], body, got["gap"] - 0.06)


# ---------------------------------------------------------------- no room, and when the placer breaks
def small_doc(locked: bool = False) -> dict:
    nodes = [{"id": f"SW{i}", "kind": "button"} for i in range(1, 7)]
    nets = [{"name": "GND", "pins": ["U1.GND"] + [f"SW{i}.B" for i in range(1, 7)]}]
    return doc_of({"w": 30, "h": 30, "holes": False, **({"locked": True} if locked else {})}, *nodes, nets=nets)


def test_a_board_too_small_says_so_and_room_grows_it_by_small_steps():
    doc = small_doc()
    got = device.arrange(doc, {}, (30, 30))
    assert got["missing"] and set(got["missing"]) < {f"SW{i}" for i in range(1, 7)}
    c = device.compile(doc, {}, (30, 30))
    assert c["unplaced"] == got["missing"] and "pcbPack" in c["source"]  # asked for directly it still compiles, as the fallback did
    W, H = device.estimate(doc, {})
    assert (W, H) > (30, 30) and not device.arrange(doc, {}, (W, H))["missing"]
    # the first size that has room: one step less has none
    assert device.arrange(doc, {}, (W - device.ROOM_STEP_MM, H))["missing"] or device.arrange(doc, {}, (W, H - device.ROOM_STEP_MM))["missing"]
    # a round board grows as a circle
    disc = doc_of({"shape": "round", "w": 34, "holes": False}, *[{"id": f"SW{i}", "kind": "button"} for i in range(1, 7)], nets=[{"name": "GND", "pins": ["U1.GND", "SW1.B"]}])
    D = device.estimate(disc, {})
    assert D[0] == D[1] and D[0] > 34 and not device.arrange(disc, {}, D)["missing"]


async def test_the_persons_board_without_room_is_said_in_plain_words_and_no_worker_runs(catalogue, no_store, monkeypatch):
    doc = small_doc(locked=True)
    assert device.estimate(doc, {}) == (30, 30)

    class NoWorker:
        async def build(self, *a, **k):
            raise AssertionError("the worker must not run: there is nothing it could do")

    monkeypatch.setattr(pcb, "pool", lambda: NoWorker())
    res = await no_store.build_device("p_test", doc)
    assert not res["ok"] and res["stage"] == "placement" and "the person fixed the board" in res["error"] and "30 x 30 mm board" in res["error"]
    assert "pack" not in res["error"].lower()


def test_the_packer_takes_over_only_when_the_placer_breaks(monkeypatch, caplog):
    doc = doc_of({"w": 44, "h": 38}, *copy.deepcopy(LEDS), nets=copy.deepcopy(LED_NETS))

    def broken(*a, **k):
        raise ValueError("a slip")

    monkeypatch.setattr(device, "arrange", broken)
    size = device.estimate(doc, {})
    assert size == (44, 38)
    c = device.compile(doc, {}, size)
    assert "pcbPack" in c["source"] and 'pcbPackGap="1.6mm"' in c["source"] and '<resistor name="R1" resistance="330" footprint="0603" />' in c["source"]
    assert "unplaced" not in c and "the device placer failed" in caplog.text


# ---------------------------------------------------------------- a part flush with the edge
async def test_a_part_flush_with_the_edge_grows_the_board_before_the_build_not_after_it(catalogue):
    """p_7a4af5e28ada4f46: the buzzer's courtyard is 12.0007 mm wide at x = 18 of a 48 mm board. poking() let 0.05 mm pass and
    rounding hid the rest; tscircuit's check is strict: 'BZ1 extends outside board boundaries by 0mm', a whole board step lost."""
    doc, parts, _ = await resolved(GRAPHS["bench_timer_rect"])
    bz = next(f for f in device.fixed_parts(doc, parts, (48, 65)) if f["id"] == "BZ1")
    assert bz["rect"][2] == pytest.approx(24.0, abs=0.01)
    assert [c["side"] for c in device.conflicts(doc, parts, (48, 65)) if c["kind"] == "outline" and c["a"]["id"] == "BZ1"] == ["+x"]
    W, H = device.estimate(doc, parts)
    assert W == 49 and not [c for c in device.conflicts(doc, parts, (W, H)) if c["kind"] == "outline"]
    # a courtyard well inside says nothing; one at the margin does, on every shape
    rect = device.outline(doc_of({"w": 50, "h": 40}), (50, 40))
    assert device.poking(rect, (-10, -10, 24.8, 10)) == {} and device.poking(rect, (-10, -10, 25.0, 10)) == {"+x": device.EDGE_MARGIN_MM}
    disc = device.outline(doc_of({"shape": "round", "w": 50}), (50, 50))
    assert device.poking(disc, (-3, 20, 3, 24.0)) == {} and set(device.poking(disc, (-3, 20, 3, 24.9))) == {"+y"}


# ---------------------------------------------------------------- what the rest of the compiler says about it
async def test_estimate_compaction_and_growth_speak_of_the_room_the_placer_needs(catalogue):
    doc, parts, _ = await resolved(GRAPHS["bench_leak_round"])
    assert device.base_size(doc, parts) == (44, 44)
    size = device.estimate(doc, parts)
    assert size[0] == size[1] > 44 and not device.arrange(doc, parts, size)["missing"]
    assert device.arrange(doc, parts, (size[0] - device.ROOM_STEP_MM, size[0] - device.ROOM_STEP_MM))["missing"]
    assert device.sized(doc, parts) == (size, device.conflicts(doc, parts, size))
    got = device.growth_report(doc, parts, size, [{"size_mm": list(size), "errors": 0, "ok": True}])
    assert f"to {device.size_text(doc, size)} before routing to give BZ1 a spot" in got["msg"], got
    # asked larger than it needs: the compaction hint names a size the placer has room on
    big, parts, _ = await resolved({**copy.deepcopy(GRAPHS["bench_timer_rect"]), "board": {"holes": True, "w": 80, "h": 90}})
    best = device.compaction(big, parts)
    assert best and not device.arrange(best["doc"], parts, tuple(best["size"]))["missing"] and device.estimate(best["doc"], parts) == tuple(best["size"])


# ---------------------------------------------------------------- through the real bundle
@needs_bundle
@pytest.mark.parametrize("name", ["bench_leak_round", "bench_dice_rounded", "bench_timer_rect"])
async def test_the_boards_that_grew_for_the_packer_build_clean_at_the_size_they_ask_for(name, catalogue, real_pcb, no_store):
    res = await no_store.build_device("p_test", copy.deepcopy(GRAPHS[name]))
    doc, parts, _ = await resolved(GRAPHS[name])
    want = device.estimate(doc, parts)
    assert res["drc_ok"] and not res["build"]["errors"], (res["attempts"], res["build"]["errors"][:2])
    assert tuple(res["size_mm"]) == want and len({tuple(a["size_mm"]) for a in res["attempts"]}) == 1, res["attempts"]
    assert not any("pack" in str(a.get("first") or "").lower() for a in res["attempts"])


@pytest.fixture
async def store(tmp_path, monkeypatch):
    """A scratch store, so that the build's PCB version is what inspect_board reads."""
    from formwright import deviceapi

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    await dbmod.get_db()
    monkeypatch.setattr(deviceapi.events, "emit", nothing)
    monkeypatch.setattr(deviceapi.pcbapi, "emit_route", nothing)
    monkeypatch.setattr(deviceapi.pcbapi, "emit_version", nothing)
    yield deviceapi
    await dbmod.close_db()


class Ctx:
    def __init__(self, project_id: str):
        self.project_id, self.project = project_id, {"id": project_id, "title": "x", "brief": {"language": "en"}}
        self.user, self.job_id, self.events = {"id": "u"}, "j", []

    async def emit(self, *a, **k) -> None:
        pass

    async def status(self, text: str) -> None:
        pass

    def check_cancelled(self) -> None:
        pass


@needs_bundle
@pytest.mark.parametrize("name,free,shape", [("bench_leak_round", "R1", "round"), ("bench_timer_rect", "Q1", "rect")])
async def test_inspect_board_and_the_case_work_on_a_board_the_placer_built(name, free, shape, catalogue, real_pcb, store):
    pid = f"p_{name}"
    res = await store.build_device(pid, copy.deepcopy(GRAPHS[name]))
    assert res["drc_ok"], res["attempts"]
    await device_store.save(pid, res["doc"], author="agent", summary="v")
    r, images = await di.run(Ctx(pid), DesignState(pack="device"), "inspect_board", {"focus": free})
    assert r["ok"] and r["focus"] == "part" and r["id"] == free and images, r
    r, images = await di.run(Ctx(pid), DesignState(pack="device"), "inspect_board", {})
    assert r["ok"] and r["focus"] == "board", r
    board = json.loads(pcb_store.artifact_path(pid, res["pcb_version"], "board.json").read_text(encoding="utf-8"))
    assert {c["id"] for c in board["components"]} >= {free, "U1"}
    if shape == "round":
        assert board["pcb"]["outline"]["shape"] == "round"
    src = et.enclosure_program("board", title="case", mockup=False)
    old, geommod._pool = geommod._pool, GeomPool(1)
    try:
        built = await geommod._pool.build(src, {}, analyze="full", inputs={"boards": {"board": board}})
        assert built["checks"]["ok"] and not [i["code"] for i in built["checks"]["issues"] if i["severity"] == "error"], built["checks"]["issues"]
        out = await geommod._pool.inspect(src, built["params"], [{"op": "enclosure", "board": "board"}], inputs={"boards": {"board": board}})
        enc = et.enclosure_checks(out["results"][0], "board", board, 1)
        assert enc["findings"] and not [f for f in enc["findings"] if f.get("severity") == "error" and f["code"] in ("board_fit", "lid_fit")], enc["findings"]
    finally:
        await geommod._pool.close()
        geommod._pool = old
