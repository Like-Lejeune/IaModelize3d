"""The designer's close looks (agent/device_inspect.py): inspect_board crops the routed board to a part, a net or a region
and measures it from circuit.json and board.json, inspect_case renders the real case around a part with its opening, and
inspect_part gathers one node's card, nets, driver, placement, case opening, firmware lines and rule findings.

The board is the night light p_871b9d8d70f743d3 PCB v1 as it was built (fixtures/device_inspect: board.json, the drawings,
circuit.json without the schematic, the device it was built from, device v4 with its firmware and the case program with
its enclosure check). The SVG renderer and the geometry engine are the real ones when their bundles are there.
Set FW_INSPECT_OUT to a folder to keep the pictures."""
from __future__ import annotations

import copy
import io
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from iamodelize3d import catalog, device_store, pcb, pcb_store, storage
from iamodelize3d import db as dbmod
from iamodelize3d import geom as geommod
from iamodelize3d.agent import device_inspect as di
from iamodelize3d.agent import device_prompt, device_tools, tools
from iamodelize3d.agent.tools import DesignState
from iamodelize3d.config import REPO_DIR, settings
from iamodelize3d.geom import GeomPool
from iamodelize3d.llm.client import CostMeter

FIX = Path(__file__).parent / "fixtures" / "device_inspect"
PID = "p_inspect"
BOARD = json.loads((FIX / "board.json").read_text(encoding="utf-8"))
CJ = json.loads((FIX / "circuit.json").read_text(encoding="utf-8"))
DOC = json.loads((FIX / "device_doc.json").read_text(encoding="utf-8"))
CASE = json.loads((FIX / "case.json").read_text(encoding="utf-8"))
SVG_PNG = REPO_DIR / "packages" / "pcb" / "dist" / "svg-png.mjs"
needs_svg = pytest.mark.skipif(not SVG_PNG.exists(), reason="run `npm run bundle` in packages/pcb")
OUT = os.environ.get("FW_INSPECT_OUT")


class FakeCtx:
    def __init__(self):
        self.project = {"id": PID, "title": "Night light", "brief": {"language": "ru"}}
        self.project_id = PID
        self.user = {"id": "u_inspect"}
        self.job_id = "j_inspect"
        self.meter = CostMeter()
        self.models = SimpleNamespace(designer="muse-spark-1.3", fast="muse-spark-1.3-contributor")
        self.events: list[tuple[str, dict]] = []

    async def emit(self, type_: str, data: dict | None = None) -> None:
        self.events.append((type_, data or {}))

    async def status(self, text: str) -> None:
        self.events.append(("agent.status", {"text": text}))

    def check_cancelled(self) -> None:
        pass


@pytest.fixture
async def project(tmp_path, monkeypatch):
    """The night light's PCB v1 and device v4 in a scratch store; the catalogue answers offline."""
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    await dbmod.get_db()
    files = {n: (FIX / n).read_text(encoding="utf-8") for n in ("board.json", "pcb_top.svg", "pcb_bottom.svg", "device.json")}
    files["circuit.json"] = json.dumps(CJ)
    await pcb_store.add(PID, {"source": "// night light", "intent": None, "checks": {"ok": True, "errors": []}, "files": files})
    await device_store.save(PID, copy.deepcopy(DOC), author="agent", summary="v4")

    async def info(code):
        if code != "C78960":
            raise catalog.CatalogError(f"{code}: offline")
        return {"lcsc": "C78960", "mpn": "BH1750FVI-TR", "brand": "ROHM", "package": "WSOF-6", "category": "Ambient Light Sensors",
                "kind_hint": "sensor", "current_ma": 0.19, "stock": 5000, "basic": False, "description": "I2C ambient light sensor 2.4V~3.6V",
                "pins": [{"num": str(i), "name": n, "label": n} for i, n in enumerate(["VCC", "ADDR", "GND", "SDA", "DVI", "SCL", "EP"], 1)]}

    monkeypatch.setattr(catalog, "info", info)

    async def no_rules(doc, parts=None):
        return [{"code": "light_sensor_glare", "ref": "U2", "severity": "warning", "msg": "U2 sits 10 mm from LED2"},
                {"code": "pullup_value", "ref": "R1", "severity": "warning", "msg": "4.7k on SDA"}]

    monkeypatch.setattr(device_tools, "design_checks", no_rules)
    yield tmp_path
    await dbmod.close_db()


def _png(rel: str, name: str) -> Image.Image:
    path = storage.abs_path(rel)
    if OUT:
        Path(OUT).mkdir(parents=True, exist_ok=True)
        shutil.copy(path, Path(OUT) / name)
    return Image.open(io.BytesIO(path.read_bytes()))


# ---------------------------------------------------------------- circuit.json, measured
def test_the_circuit_is_read_in_the_board_frame():
    c = di.Circuit(CJ, 58, 66)
    # U1's first pin: (-7.62, 30.12) centred -> (21.38, 63.12) from the bottom-left corner, as board.json has its hole
    d0 = next(p for p in c.ports.values() if p["ref"] == "U1.D0")
    assert (round(d0["x"], 2), round(d0["y"], 2)) == (21.38, 63.12)
    sda = c.key_of_pin("U2", ["SDA"])
    assert sda and c.name_of(sda) == "SDA" and c.key_by_name("sda") == sda
    assert {p["ref"] for p in c.ports.values() if p["key"] == sda} == {"U1.SDA", "U2.SDA", "R1.2"}
    conns = c.connections(sda)
    assert conns and all(t["length"] >= t["straight"] - 1e-6 for t in conns)
    assert sum(t["vias"] for t in c.traces) <= len(c.vias) + 1
    # a resistor's pin by its device name ('1') or its pad name ('pin1') is the same net
    assert c.key_of_pin("R1", ["1"]) == c.key_of_pin("R1", ["pin1"]) == c.key_by_name("V3V3")


def test_part_facts_name_neighbours_lights_and_edges():
    c = di.Circuit(CJ, 58, 66)
    f = di.part_facts("U2", BOARD, c, DOC)
    assert f["at_mm"] == [29.0, 31.6] and f["access"] == "sensor" and f["side"] == "top"
    assert f["nearest_edge"].startswith("+x") or f["nearest_edge"].startswith("-x") or "mm" in f["nearest_edge"]
    assert any(n.startswith("C1:") for n in f["neighbours"]), f["neighbours"]
    # the light sensor sees the three LEDs it must ignore
    lights = f["lights_within_20mm"]
    assert [x.split()[0] for x in lights] == ["LED2", "LED1", "LED3"] and lights[0] == "LED2 11.4 mm"
    # the parts under the PIR module's body are said to be under it
    pir = di.part_facts("PIR1", BOARD, c, DOC)
    assert "module" in pir["accessory"] and pir["access"] == "sensor"
    assert "under" not in pir
    assert all(not n.startswith("PIR1") for n in pir["neighbours"])


def test_a_connector_facing_inwards_is_said():
    node = {"id": "J1", "kind": "usb_c"}
    assert "out over the nearest edge" in di._facing(node, "-y", 0)
    bad = di._facing(node, "-y", 180)
    assert "faces +y" in bad and "nearest edge is -y" in bad and "rotation 0" in bad


def test_net_and_board_facts_measure_the_copper():
    assert di.Circuit(CJ, 58, 66).key_by_name("V5") is None, "the compiler wired V5 pin to pin: circuit.json has no name for it"
    c = di.Circuit(CJ, 58, 66, DOC)
    n = di.net_facts(c.key_by_name("V5"), c, BOARD)
    assert n["net"] == "V5" and n["routed_total_mm"] > 20 and len(n["pads"]) >= 5
    assert all({"from", "to", "routed_mm", "straight_mm", "layers"} <= set(x) for x in n["connections"])
    assert n["user_facing_parts"] and any(p.startswith("LED") for p in n["user_facing_parts"])
    b = di.board_facts(c, BOARD)
    assert b["board_mm"] == [58, 66] and len(b["longest"]) == 6
    assert b["longest"][0]["routed_mm"] >= b["longest"][-1]["routed_mm"]
    assert all(d["detour"] >= di.DETOUR for d in b.get("detours", []))
    r = di.region_facts((20.0, 28.0, 38.0, 46.0), c, BOARD)
    assert any(p.startswith("U2 (sensor)") for p in r["parts"]) and "SDA" in r["nets_crossing"]


# ---------------------------------------------------------------- inspect_board
@needs_svg
async def test_inspect_board_crops_a_part_with_a_grid(project):
    ctx, state = FakeCtx(), DesignState(pack="device")
    r, images = await di.run(ctx, state, "inspect_board", {"focus": "U2"})
    assert r["ok"] and r["focus"] == "part" and r["id"] == "U2" and "grid" in r["picture"], r
    img = _png(images[0], "board_U2.png")
    assert img.width == di.IMG_W and 0.5 < img.height / img.width < 2.1
    # a net by a pin, the bottom side, one layer
    r, images = await di.run(ctx, state, "inspect_board", {"focus": "U2.SDA", "side": "bottom", "layers": "copper_bottom"})
    assert r["ok"] and r["focus"] == "net" and r["net"] == "SDA" and "U2.SDA at" in " ".join(r["pads"]), r
    _png(images[0], "board_SDA_bottom.png")
    r, images = await di.run(ctx, state, "inspect_board", {"focus": "V5", "layers": "copper_top"})
    assert r["ok"] and r["net"] == "V5" and images
    _png(images[0], "board_V5.png")
    r, images = await di.run(ctx, state, "inspect_board", {"focus": {"x": 10, "y": 25, "w": 38, "h": 22}, "layers": "parts"})
    assert r["ok"] and r["focus"] == "region" and images
    _png(images[0], "board_region_parts.png")
    r, images = await di.run(ctx, state, "inspect_board", {})
    assert r["ok"] and r["focus"] == "board" and r["longest"] and images
    _png(images[0], "board_whole.png")


async def test_inspect_board_says_what_it_cannot_find(project):
    ctx, state = FakeCtx(), DesignState(pack="device")
    r, images = await di.run(ctx, state, "inspect_board", {"focus": "NOPE"})
    assert not r["ok"] and "U2" in r["parts"] and "SDA" in r["nets"] and not images
    r, _ = await di.run(ctx, state, "inspect_board", {"focus": "U2.NOPIN"})
    assert not r["ok"] and "no such pad" in r["error"]
    r, _ = await di.run(ctx, state, "inspect_board", {"layers": "gold"})
    assert not r["ok"]
    r, _ = await di.run(ctx, state, "inspect_board", {"version": 7})
    assert not r["ok"] and "no PCB version 7" in r["error"]


async def test_inspect_board_keeps_the_facts_when_the_drawing_fails(project, monkeypatch):
    async def none(*a, **k):
        return None

    monkeypatch.setattr(pcb, "render_png_async", none)
    r, images = await di.run(FakeCtx(), DesignState(pack="device"), "inspect_board", {"focus": "LED2"})
    assert r["ok"] and r["at_mm"] == [29.0, 43.0] and not images and "could not be rendered" in r["picture"]


# ---------------------------------------------------------------- inspect_part
async def test_inspect_part_gathers_one_node(project):
    ctx, state = FakeCtx(), DesignState(pack="device")
    r = await di.run(ctx, state, "inspect_part", {"id": "u2"})
    r = r[0]
    assert r["ok"] and r["id"] == "U2" and r["card"]["mpn"] == "BH1750FVI-TR" and r["card"]["current_ma"] == 0.19
    assert any(p.startswith("SDA -> SDA: U1.SDA") for p in r["pins"]), r["pins"]
    assert "U1.SDA (GPIO6)" in r["driven_by"]
    assert r["board"]["at_mm"] == [29.0, 31.6] and r["board"]["built_from_device_version"] == 3
    assert any("Wire.begin" in ln for ln in r["firmware"]) and any("BH1750" in ln for ln in r["firmware"])
    assert r["design_rules"] == ["warning light_sensor_glare: U2 sits 10 mm from LED2"]
    assert r["case"] == "no case for this board yet: make_enclosure"
    # an LED switched by a MOSFET: the gate's pin through its resistor, and the firmware's constant for it
    r = (await di.run(ctx, state, "inspect_part", {"id": "LED1"}))[0]
    assert r["driven_by"] == ["U1.D1 (GPIO3) via R3, Q1, R6"], r["driven_by"]
    assert any("#define LED_PIN 3" in ln for ln in r["firmware"]) and any("ledcWrite(LED_PIN" in ln for ln in r["firmware"])
    r = (await di.run(ctx, state, "inspect_part", {"id": "PIR1"}))[0]
    assert r["driven_by"] == ["U1.D2 (GPIO4)"] and any("PIR_PIN" in ln for ln in r["firmware"])
    assert r["card"]["kind"] == "sensor"
    r = (await di.run(ctx, state, "inspect_part", {"id": "X9"}))[0]
    assert not r["ok"] and "U2" in r["nodes"]


def test_mcu_paths_stop_at_supplies():
    # C1 sits between V3V3 and GND: nothing drives it
    assert di.mcu_paths(DOC, "C1") == []
    assert di.mcu_paths(DOC, "U1") == []


# ---------------------------------------------------------------- inspect_case
def test_case_facts_say_which_opening_is_over_a_part():
    rep = {"zBoard": 4.1, "zTop": 13.9, "lidT": 1.6, "outerSize": [68.05, 72.2, 18.7], "inner": {"x0": -0.5, "y0": -0.5, "x1": 58.5, "y1": 66.5},
           "features": [{"type": "light", "for": "LED2", "mode": "window", "shape": "round", "w": 4.0, "d": 4.0, "at": [29.0, 43.0]},
                        {"type": "sensor_window", "for": "PIR1", "shape": "round", "w": 23.8, "d": 23.8, "at": [29.0, 15.0]},
                        {"type": "light", "for": "LED1", "mode": "window", "shape": "round", "w": 4.0, "d": 4.0, "at": [20.0, 39.0]}]}
    f = di.case_facts("LED2", BOARD, rep, CASE["enclosure"]["findings"])
    assert f["opening"][0].startswith("round light (window) 4.0 x 4.0 mm at (29.0, 43.0) (for LED2): uncovers")
    assert f["lid_underside_above_part_mm"] == round(13.9 - (4.1 + 1.6 + 0.7), 1)
    assert f["inner_walls_mm"]["-x"] == round(26.805 + 0.5, 1) and f["case_check"] == ["info: LED2: nearest wall 3.00 mm", "info: LED2: open window"]
    # a window 3 mm off its LED: the offset is measured
    f = di.case_facts("LED1", BOARD, rep, [])
    assert "window centre 3.0, 0.0 mm from the part's centre" in f["opening"][0]
    # a part under nothing
    f = di.case_facts("R3", BOARD, rep, [])
    assert f["opening"] == ["none: the lid is closed over it"]
    assert di.case_facts(None, BOARD, rep, [])["openings"][0].startswith("LED2: round light")


@pytest.fixture
async def real_geom():
    old = geommod._pool
    geommod._pool = GeomPool(1)
    yield geommod._pool
    await geommod._pool.close()
    geommod._pool = old


def _case_state() -> DesignState:
    state = DesignState(pack="device", source=(FIX / "case.js").read_text(encoding="utf-8"), version=1, params=dict(CASE["params"]))
    state.inputs = {"boards": {"board": BOARD}}
    state.last_build = {"checks": {"enclosure": CASE["enclosure"]}}
    return state


async def test_inspect_case_needs_a_case(project):
    r, images = await di.run(FakeCtx(), DesignState(pack="device"), "inspect_case", {"focus": "LED2"})
    assert not r["ok"] and "make_enclosure" in r["error"] and not images
    r, _ = await di.run(FakeCtx(), _case_state(), "inspect_case", {"focus": "NOPE"})
    assert not r["ok"] and "LED2" in r["parts"]
    r, _ = await di.run(FakeCtx(), _case_state(), "inspect_case", {"mode": "melted"})
    assert not r["ok"]


async def test_inspect_case_renders_the_real_case_around_a_part(project, real_geom):
    ctx, state = FakeCtx(), _case_state()
    r, images = await di.run(ctx, state, "inspect_case", {"focus": "LED2"})
    assert r["ok"] and r["mode"] == "assembled" and r["pcb_version"] == 1, r
    assert r["part"]["id"] == "LED2" and r["lid_underside_above_part_mm"] > 0
    assert "LED2" in r["opening"][0] and "uncovers 100%" in r["opening"][0], r["opening"]
    assert "info: LED2: open window" in r["case_check"] and r["case_mm"][1:] == [72.2, 18.7]
    img = _png(images[0], "case_LED2_assembled.png")
    assert img.width >= 900
    r, images = await di.run(ctx, state, "inspect_case", {"focus": "U2", "mode": "lid_off", "view": "top"})
    assert r["ok"] and "sensor window" in r["opening"][0] and r["nearest_wall"]
    _png(images[0], "case_U2_lid_off_top.png")
    r, images = await di.run(ctx, state, "inspect_case", {"focus": "LED2", "mode": "section"})
    assert r["ok"] and "cut at y=43.0" in r["picture"]
    _png(images[0], "case_LED2_section.png")
    r, images = await di.run(ctx, state, "inspect_case", {"mode": "exploded"})
    assert r["ok"] and any(o.startswith("PIR1: round sensor window") for o in r["openings"]), r
    _png(images[0], "case_exploded.png")
    # nothing was saved: the case is still the same program version
    assert state.version == 1 and "inspect_case" not in state.source


# ---------------------------------------------------------------- the hub
def test_the_device_pack_offers_the_inspect_tools():
    names = [t["name"] for t in tools.tools_for("device", photos=False, prints=False)]
    assert {"inspect_board", "inspect_case", "inspect_part", "look"} <= set(names)
    assert names.index("inspect_board") < names.index("finish")
    assert "inspect_board" not in [t["name"] for t in tools.tools_for("pcb", photos=False, prints=False)]
    text = device_prompt.PACK_TEXT
    assert "inspect_board" in text and "inspect_case" in text and "inspect_part" in text


async def test_run_tool_dispatches_to_the_inspector(project):
    r, _ = await tools.run_tool(FakeCtx(), DesignState(pack="device"), "inspect_part", {"id": "Q1"})
    assert r["ok"] and r["id"] == "Q1" and any(p.startswith("G -> ") for p in r["pins"])
