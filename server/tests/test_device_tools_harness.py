"""The device designer's harness (agent/device_tools.py, device_review.py, device_prompt.py, the tools.py hook): write_device
splits design errors from warnings, build_device is not ok while the intent fails and counts DRC as the board does, the
firmware check is kept with the version, the finish gate refuses on rules, requirements, firmware and missing case
openings, and the device reviewer reads the graph, the board render, the firmware and the order. The catalogue is the
BME280 fixture, the PCB worker a fake, the stores are real on a scratch database; device_rules and firmware_check are
stand-ins put where the real modules go, so these tests hold whether or not those modules exist yet."""
from __future__ import annotations

import copy
import io
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import formwright
from formwright import catalog, device, device_concept, device_store, pcb, pcb_store
from formwright import db as dbmod
from formwright.agent import critic, device_prompt, device_review, device_tools, narrate, pcb_tools, tools
from formwright.agent.tools import DesignState
from formwright.config import settings
from formwright.llm.client import CostMeter
from formwright.llm.english import is_english

FIX = Path(__file__).parent / "fixtures" / "device"
BME = json.loads((FIX / "C92489.easyeda.json").read_text(encoding="utf-8"))
PID = "p_dev"
REQS = [{"id": "R1", "text": "measure the climate", "parts": ["U2"], "firmware": True},
        {"id": "R2", "text": "status light", "parts": ["LED1"], "firmware": True}]


def doc(**extra) -> dict:
    d = copy.deepcopy(device_prompt.EXAMPLE_DOC)
    d["requirements"] = copy.deepcopy(REQS)
    d.update(extra)
    return d


BOARD = {"schema": "fw.board/1", "name": "Weather station", "pcb": {"outline": {"kind": "rect", "w": 36, "h": 35}, "thickness": 1.6},
         "components": [{"id": "U1", "type": "module", "access": "port", "edge": "+y", "x": 18, "y": 25, "w": 17.8, "d": 21, "h": 3},
                        {"id": "LED1", "type": "led", "access": "light", "x": 8, "y": 8, "w": 1.6, "d": 0.8, "h": 0.6},
                        {"id": "U2", "type": "chip", "access": "sensor", "x": 20, "y": 10, "w": 2.5, "d": 2.5, "h": 0.9}],
         "accessories": [{"id": "DS1", "key": "oled_096_i2c", "name": "OLED", "kind": "display", "mount": "board", "x": 18, "y": 12},
                         {"id": "P1", "key": "soil_capacitive_v12", "name": "soil probe", "kind": "probe", "mount": "cable", "x": 0, "y": 5}]}
INTENT_OK = {"ok": True, "issues": [], "checked": 5}
INTENT_BAD = {"ok": False, "checked": 5, "issues": [{"code": "intent_not_at_edge", "ref": "J2", "msg": "J2 should sit on the -y edge, but its body is 1.4 mm from it",
                                                      "hint": "move J2 by -1.1 mm in y"}]}
CLEAN = {"ok": True, "errors": [], "warnings": [], "suppressed": 0, "quiet": {}, "board": BOARD, "intent": INTENT_OK,
         "counts": {"components": 9, "nets": 7, "connections": 20, "traces": 18, "vias": 4},
         "circuit_json": [{"type": "pcb_board", "width": 36, "height": 35}],
         "limits": {"ok": True, "issues": []}, "frames": [], "meta": {}, "ms": 100}
PLACEMENT = {"type": "pcb_footprint_overlap_error", "ref": "SW1", "message": "SW1 overlaps U2", "hint": "move SW1 3 mm right"}
DIRTY = {**CLEAN, "ok": False, "errors": [PLACEMENT, {**PLACEMENT, "ref": "R1", "message": "R1 overlaps R2"}], "suppressed": 46,
         "counts": {**CLEAN["counts"], "traces": 0, "vias": 0}}
EXPORT = {"files": {"gerbers.zip": b"PK", "bom.csv": "c", "cpl.csv": "c", "pcb_top.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>"}}
PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeCtx:
    def __init__(self, language: str = "en"):
        self.project = {"id": PID, "title": "Weather station", "brief": {"language": language}}
        self.project_id = PID
        self.user = {"id": "u_dev"}
        self.job_id = "j_dev"
        self.meter = CostMeter()
        self.models = SimpleNamespace(designer="muse-spark-1.3", fast="muse-spark-1.3-contributor")
        self.events: list[tuple[str, dict]] = []

    async def emit(self, type_: str, data: dict | None = None) -> None:
        self.events.append((type_, data or {}))

    async def status(self, text: str) -> None:
        self.events.append(("agent.status", {"text": text}))

    def check_cancelled(self) -> None:
        pass


class FakePcb:
    def __init__(self, *builds):
        self.builds = list(builds)

    async def build(self, source, *, intent=None, on_frame=None, timeout=None, name=None, lcsc=None):
        return copy.deepcopy(self.builds.pop(0))

    async def export(self, circuit_json, *, timeout=60, models=None):
        return copy.deepcopy(EXPORT)


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


@pytest.fixture
def offline(monkeypatch):
    """catalog.info / easyeda / resolve_basic answer from the BME280 fixture and fixed basic parts; the board.json the fake
    worker returns is taken as it is (the compiler's own dressing of it is test_device's)."""
    monkeypatch.setattr(device, "dress_board", lambda board, *a, **k: board, raising=False)
    pins = catalog.pins_of(BME)
    labels = catalog.labels_of(pins)
    card = {"lcsc": "C92489", "mpn": "BME280", "brand": "Bosch Sensortec", "package": "LGA-8(2.5x2.5)", "stock": 3361, "basic": False,
            "category": "Humidity Sensors", "kind_hint": "sensor", "current_ma": 0.7,
            "prices": [{"qty": 1, "usd": 8.23}], "description": "1.71V~3.6V I2C SPI",
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


def plug(monkeypatch, name: str, module: types.ModuleType | None) -> None:
    """Put a stand-in where formwright.<name> goes (None: the module is missing), whether or not the real one exists."""
    monkeypatch.setitem(sys.modules, f"formwright.{name}", module)
    if module is None:
        monkeypatch.delattr(formwright, name, raising=False)
    else:
        monkeypatch.setattr(formwright, name, module, raising=False)


def rules(items) -> types.ModuleType:
    m = types.ModuleType("formwright.device_rules")
    m.check = lambda doc, parts: [dict(i) for i in items]  # type: ignore[attr-defined]
    return m


def checker(result) -> types.ModuleType:
    m = types.ModuleType("formwright.firmware_check")
    m.calls = []  # type: ignore[attr-defined]

    async def check(doc, files, lang):
        m.calls.append((sorted(files), lang))  # type: ignore[attr-defined]
        return copy.deepcopy(result)

    m.check = check  # type: ignore[attr-defined]
    return m


DRIVER = {"code": "gpio_overload", "ref": "BZ1", "severity": "error", "msg": "BZ1 draws 30 mA straight from U1.D2", "hint": "add an NPN low-side switch"}
NOTE = {"code": "pullup_value", "ref": "R1", "severity": "warning", "msg": "4.7k is fine up to 400 kHz"}
FW_BAD = {"ok": False, "tool": "arduino-cli", "errors": [{"code": "compile", "file": "main.ino", "line": 12, "msg": "'display' was not declared",
                                                          "hint": "declare it before setup()"}], "warnings": []}
FW_OK = {"ok": True, "tool": "arduino-cli", "errors": [], "warnings": [{"code": "unused", "file": "main.ino", "line": 3, "msg": "x unused"}]}


# ---------------------------------------------------------------- write_device
async def test_write_device_splits_design_errors_from_warnings(fresh_db, offline, monkeypatch):
    plug(monkeypatch, "device_rules", rules([DRIVER, NOTE]))
    ctx, state = FakeCtx(), DesignState(pack="device")
    r = await device_tools._write(ctx, state, {"doc": doc(), "summary": "first"})
    assert r["ok"] is False and r["version"] == 1 and r["next"].startswith("fix the design_errors")
    assert r["design_errors"] == ["gpio_overload BZ1: BZ1 draws 30 mA straight from U1.D2 -> add an NPN low-side switch"]
    assert r["design_warnings"] == ["pullup_value R1: 4.7k is fine up to 400 kHz"]
    saved = (await device_store.latest(PID))["doc"]
    assert saved["requirements"] == REQS, "the requirements are kept with the version"
    # an edit keeps them and can replace them; a requirement whose part is gone is a design error, never silently dropped
    plug(monkeypatch, "device_rules", rules([NOTE]))
    r = await device_tools._write(ctx, state, {"edits": [{"op": "remove", "id": "LED1"}], "summary": "no LED"})
    assert r["ok"] is False and any(e.startswith("requirement R2 (status light) names LED1, not in the device") for e in r["design_errors"])
    r = await device_tools._write(ctx, state, {"edits": [{"requirements": REQS[:1]}], "summary": "fewer"})
    assert r["ok"] is True and "design_errors" not in r and r["next"] == "build_device"
    # no rules module: the lint warnings alone, and no requirements at all is an error
    plug(monkeypatch, "device_rules", None)
    r = await device_tools._write(ctx, state, {"doc": {k: v for k, v in device_prompt.EXAMPLE_DOC.items() if k != "requirements"}, "summary": "x"})
    saved = (await device_store.latest(PID))["doc"]
    assert saved["requirements"] == REQS[:1], "a doc without requirements keeps the previous version's"
    assert r["ok"] is True


async def test_write_device_refuses_a_partial_doc(fresh_db, offline, monkeypatch):
    # the timer p_e4256911dad74fb1 sent only the nodes it moved as `doc` and lost 8 parts and every net
    plug(monkeypatch, "device_rules", None)
    ctx, state = FakeCtx(), DesignState(pack="device")
    full = doc()
    await device_tools._write(ctx, state, {"doc": full, "summary": "v1"})
    some = {**full, "nodes": full["nodes"][:3], "nets": []}
    r = await device_tools._write(ctx, state, {"doc": some, "summary": "moved"})
    assert r["ok"] is False and "would replace the device" in r["error"] and "`edits`" in r["error"]
    assert (await device_store.latest(PID))["version"] == 1, "nothing is saved"
    # a smaller doc that still brings its own nets and new parts is a redesign, and goes through
    redesign = {**full, "nodes": [*full["nodes"][:3], {"id": "LED9", "kind": "led", "label": "new"}], "nets": full["nets"]}
    r = await device_tools._write(ctx, state, {"doc": redesign, "summary": "smaller"})
    assert "error" not in r and r["version"] == 2


async def test_write_device_without_requirements_is_told_to_write_them(fresh_db, offline, monkeypatch):
    plug(monkeypatch, "device_rules", None)
    r = await device_tools._write(FakeCtx(), DesignState(pack="device"),
                                  {"doc": {k: v for k, v in device_prompt.EXAMPLE_DOC.items() if k != "requirements"}, "summary": "x"})
    assert r["ok"] is False and r["design_errors"][0].startswith("no requirements: write doc.requirements first")
    assert narrate.result_title("write_device", {}, r) == "Device v1 — 9 parts, 7 nets, design errors: 1"
    assert narrate.localize(narrate.result_title("write_device", {}, r), "ru") == "Устройство v1 — 9 деталей, 7 цепей, ошибок в схеме: 1"


def concept(chosen: str = "Shelf block") -> dict:
    return {**copy.deepcopy(device_prompt.EXAMPLE_DOC["concept"]), "chosen": chosen}


async def test_write_device_needs_a_concept_keeps_it_and_names_the_chosen_one(fresh_db, offline, monkeypatch):
    # every device came out as one box with the module on top: the first version brainstorms how it is used and looks
    plug(monkeypatch, "device_rules", None)
    ctx, state = FakeCtx(), DesignState(pack="device")
    bare = {k: v for k, v in doc().items() if k != "concept"}
    r = await device_tools._write(ctx, state, {"doc": bare, "summary": "v1"})
    assert r["ok"] is False and r["design_errors"][0].startswith("no concept: before the parts, write doc.concept = {uses:")
    assert "concept" not in r
    # malformed: two options, an unknown form, a stance missing, no chosen one
    bad = concept("Pebble")
    bad["options"] = bad["options"][:2]
    bad["options"][0] = {**bad["options"][0], "form": "cube"}
    del bad["options"][1]["stance"]
    r = await device_tools._write(ctx, state, {"doc": doc(concept=bad), "summary": "v2"})
    errs = r["design_errors"]
    assert r["ok"] is False
    assert "option 'Shelf block': form 'cube' is not one of soft, round, box" in errs
    assert "option 'Wall tile': stance 'missing' is not one of desk, tilt, upright, wall, hand, auto" in errs
    assert any(e.startswith("concept.options has 2: brainstorm at least 3 genuinely different ones") for e in errs)
    assert any(e.startswith("concept.chosen 'Pebble' names none of the options (Shelf block, Wall tile)") for e in errs)
    saved = (await device_store.latest(PID))["doc"]["concept"]
    assert "form" not in saved["options"][0] and "chosen" not in saved, "a wrong value is dropped, never guessed"
    # three options that are one device in other words
    same = concept()
    same["options"] = [{**o, **{k: same["options"][0][k] for k in ("form", "stance", "mounting", "board", "module_edge")}} for o in same["options"]]
    r = await device_tools._write(ctx, state, {"doc": doc(concept=same), "summary": "v3"})
    assert any(e.startswith("the options are not genuinely different") for e in r["design_errors"])
    # complete: ok, and the chosen option comes back in one line
    r = await device_tools._write(ctx, state, {"doc": doc(), "summary": "v4"})
    assert r["ok"] is True and "design_errors" not in r
    assert r["concept"].startswith("Shelf block: a small soft block standing on a shelf, LED and button on its lid (form soft, stance desk, "
                                   "mounting none; rect board 36 x 35 mm, module on +y; panel: status LED left")
    # a later doc without a concept keeps it, an edit can replace it
    r = await device_tools._write(ctx, state, {"doc": bare, "summary": "v5"})
    assert r["ok"] is True and (await device_store.latest(PID))["doc"]["concept"]["chosen"] == "Shelf block"
    r = await device_tools._write(ctx, state, {"edits": [{"op": "concept", "concept": concept("Window puck")}], "summary": "v6"})
    assert r["ok"] is True and r["concept"].startswith("Window puck: ")
    r = await device_tools._write(ctx, state, {"edits": [{"op": "set", "id": "LED1", "fields": {"color": "red"}}], "summary": "v7"})
    assert r["concept"].startswith("Window puck: "), "edits keep the concept"
    # the finish gate holds a device without one, like one without requirements
    assert device_tools.concept_problems({}) and device_tools.concept_problems(doc()) == []
    # the editor's normalize keeps it, and the self-check asks whether the uses are served and the chosen one was built
    assert device.normalize(doc())[0]["concept"]["chosen"] == "Shelf block"
    from formwright import device_checklists as dc
    assert "the concept's uses is served" in dc.for_kinds(["device"]) and "What was built is the chosen concept" in dc.for_kinds(["device"])


async def test_what_the_doc_leaves_out_comes_from_the_chosen_concept(fresh_db, offline, monkeypatch):
    # the night light p_c37992a561a1490e wrote a round wall puck into its concept and a board with no shape into its document
    plug(monkeypatch, "device_rules", None)
    ctx, state = FakeCtx(), DesignState(pack="device")
    bare = doc(concept=concept("Window puck"), board={"holes": True})
    for n in bare["nodes"]:
        if n["kind"] == "module":
            n.pop("edge", None)
    await device_tools._write(ctx, state, {"doc": bare, "summary": "v1"})
    saved = (await device_store.latest(PID))["doc"]
    assert saved["board"]["shape"] == "round" and saved["board"]["w"] == saved["board"]["h"] == 42
    assert next(n for n in saved["nodes"] if n["kind"] == "module")["edge"] == "-y"
    # what it says itself stays, and the person's locked board is never touched
    d = {"board": {"shape": "rect", "w": 30, "h": 20}, "nodes": [{"kind": "module", "edge": "+x"}]}
    device_tools.concept_defaults(d, {"concept": concept("Window puck")})
    assert d["board"] == {"shape": "rect", "w": 30, "h": 20} and d["nodes"][0]["edge"] == "+x"
    d = {"board": {"locked": True, "w": 30, "h": 20}}
    device_tools.concept_defaults(d, {"concept": concept("Window puck")})
    assert "shape" not in d["board"]


async def test_the_compact_edit_applies_the_arrangement_and_moves_the_concept_along(fresh_db, offline, monkeypatch):
    plug(monkeypatch, "device_rules", None)
    ctx, state = FakeCtx(), DesignState(pack="device")
    await device_tools._write(ctx, state, {"doc": doc(), "summary": "v1"})
    # nothing smaller: said, and the board stays
    monkeypatch.setattr(device, "compaction", lambda norm, parts: None)
    r = await device_tools._write(ctx, state, {"edits": [{"op": "compact"}], "summary": "v2"})
    assert r["compacted"].startswith("nothing smaller") and "errors" not in r

    def smaller(norm, parts):
        d = device.clone(norm)
        next(n for n in d["nodes"] if n["kind"] == "module")["edge"] = "-x"
        d["board"].pop("w", None)
        d["board"].pop("h", None)
        return {"msg": "m", "say": "put U1 on the -x edge", "size": [30.0, 28.0], "area": 840, "need": 300, "doc": d}

    monkeypatch.setattr(device, "compaction", smaller)
    r = await device_tools._write(ctx, state, {"edits": [{"op": "compact"}], "summary": "v3"})
    assert r["compacted"].startswith("put U1 on the -x edge: about 30 x 28 mm. Now build_device")
    saved = (await device_store.latest(PID))["doc"]
    assert next(n for n in saved["nodes"] if n["kind"] == "module")["edge"] == "-x"
    aim = device_concept.chosen(saved)
    assert aim["board"]["w"] == 30.0 and aim["board"]["h"] == 28.0 and aim["module_edge"] == "-x"
    assert saved["board"]["w"] == 30.0 and saved["board"]["h"] == 28.0, "the board follows the concept"


async def test_the_layout_is_asked_about_once_when_all_else_is_ready(fresh_db, offline, monkeypatch):
    # warnings were passed over in every run: a board far off its concept, or far larger than its parts, goes back once
    state = DesignState(pack="device")
    the_doc, room = doc(concept=concept("Window puck")), {"msg": "the board (52 x 65 mm) is 5.5 x what its parts take"}

    async def resolve(norm):
        return {}, []

    monkeypatch.setattr(device, "resolve", resolve)
    monkeypatch.setattr(device, "compaction", lambda norm, parts: room)
    state.turns_left = 3
    assert await device_tools.layout_problems(None, state, the_doc, the_doc, BOARD) == [], "no turns left to rebuild: it ships"
    state.turns_left = 10
    out = await device_tools.layout_problems(None, state, the_doc, the_doc, BOARD)
    assert any("the board is" in r and "the concept's is round" in r for r in out)
    assert any(r.startswith("board_too_large: the board (52 x 65 mm)") for r in out) and "give the reason in the summary" in out[-1]
    assert "{op:'compact'}" in out[-1] and "does not solve this" in out[-1] and not any(" mm, the concept's " in r for r in out)
    assert await device_tools.layout_problems(None, state, the_doc, the_doc, BOARD) == [], "once: then the reason is the designer's to give"
    # nothing to say: not spent, a later change can still be asked about
    state = DesignState(pack="device")
    monkeypatch.setattr(device, "compaction", lambda norm, parts: None)
    assert await device_tools.layout_problems(None, state, doc(), doc(), BOARD) == [] and "layout_asked" not in state.self_check


async def test_the_built_board_and_the_case_are_held_to_the_concept(fresh_db, offline, monkeypatch):
    from formwright.agent import elec_tools

    plug(monkeypatch, "device_rules", None)
    monkeypatch.setattr(pcb, "pool", lambda: FakePcb(CLEAN, CLEAN))

    async def render(svg, width=1200, background=None):
        return PNG

    monkeypatch.setattr(pcb, "render_png_async", render)
    ctx, state = FakeCtx(), DesignState(pack="device")
    # the concept is a round 42 mm puck with the module at the bottom; the designer insists on a 36 x 35 rectangle, module on top
    rect = {**doc()["board"], "shape": "rect"}
    await device_tools._write(ctx, state, {"doc": doc(concept=concept("Window puck"), board=rect), "summary": "v1"})
    r, _ = await device_tools._build(ctx, state, {})
    assert r["ok"] is True, "warnings, never errors"
    assert r["concept_warnings"] == [
        "concept 'Window puck': the board is rect, the concept's is round: set board.shape 'round', or change the concept (write_device "
        "with a new concept.chosen) so the two agree",
        "concept 'Window puck': the module U1 sits on +y, the concept puts it on -y: set its edge '-y', or change the concept "
        "(write_device with a new concept.chosen) so the two agree"]
    # a size far off the concept's
    tile = concept("Wall tile")
    assert any("the board is 36 x 35 mm, the concept's 30 x 45 mm" in w for w in device_concept.board_drift({**doc(concept=tile)}, BOARD))
    # the chosen option is what was built: nothing to say
    await device_tools._write(ctx, state, {"doc": doc(), "summary": "v2"})
    r, _ = await device_tools._build(ctx, state, {})
    assert "concept_warnings" not in r
    # the case: make_enclosure's result says where its options left the concept (through the dispatcher, device pack only)
    state.source = elec_tools.enclosure_program("board", title="case", form="soft", stance="desk", mounting="none")
    calls = []

    async def enclosure(ctx, state, args):
        calls.append(args)
        return {"ok": True, "version": 3}, []

    monkeypatch.setattr(pcb_tools, "_enclosure", enclosure)
    out, _ = await pcb_tools.run(ctx, state, "make_enclosure", {})
    assert "concept_warnings" not in out
    await device_tools._write(ctx, state, {"edits": [{"op": "concept", "concept": concept("Window puck")}], "summary": "v3"})
    out, _ = await pcb_tools.run(ctx, state, "make_enclosure", {})
    assert out["concept_warnings"] == [
        "concept 'Window puck': the case has form soft, stance desk, mounting none, the concept form round, stance upright, mounting "
        "magnets: make_enclosure with options {form: 'round', stance: 'upright', mounting: 'magnets'}, or change the concept "
        "(write_device with a new concept.chosen) so the two agree"]
    # a stance of auto follows the mounting and is not compared; another pack gets nothing added
    state.source = elec_tools.enclosure_program("board", title="case", form="round", stance="auto", mounting="magnets")
    out, _ = await pcb_tools.run(ctx, state, "make_enclosure", {})
    assert "concept_warnings" not in out
    out, _ = await pcb_tools.run(ctx, DesignState(pack="pcb", source=state.source), "make_enclosure", {})
    assert out == {"ok": True, "version": 3} and len(calls) == 4


# ---------------------------------------------------------------- the catalogue
async def test_search_names_the_accessory_for_a_ready_made_module(monkeypatch):
    lib = {"hc_sr501_pir": {"name": "HC-SR501 PIR motion module"}, "oled_096_i2c": {"name": "0.96\" OLED 128x64 I2C (SSD1306)"}}
    acc = types.ModuleType("formwright.accessories")
    acc.get = lib.get  # type: ignore[attr-defined]
    # as loose as a substring match: 'led' is in 'oled'
    acc.find = lambda q: next((k for k, a in lib.items() if any(w in f"{k} {a['name']}".lower() for w in q.lower().split())), None)  # type: ignore[attr-defined]
    plug(monkeypatch, "accessories", acc)
    hits: list = []

    async def search(q, limit=6, basic=False):
        return hits

    monkeypatch.setattr(catalog, "search", search)
    r = await device_tools._search({"query": "PIR motion sensor"})
    assert r["parts"] == [] and "accessory hc_sr501_pir (HC-SR501 PIR motion module)" in r["note"] and "kind: 'accessory'" in r["note"]
    hits.append({"lcsc": "C12624", "mpn": "LED", "prices": []})
    r = await device_tools._search({"query": "LED"})
    assert "note" not in r, "an LED is not an OLED display"
    plug(monkeypatch, "accessories", None)
    hits.clear()
    r = await device_tools._search({"query": "SSD1306 OLED"})
    assert "accessory nodes, not catalogue parts" in r["note"]


# ---------------------------------------------------------------- build_device
async def test_build_is_not_ok_while_the_intent_fails_and_counts_drc_as_the_board(fresh_db, offline, monkeypatch):
    plug(monkeypatch, "device_rules", None)
    fake = FakePcb(DIRTY, DIRTY, {**CLEAN, "intent": INTENT_BAD}, CLEAN)
    monkeypatch.setattr(pcb, "pool", lambda: fake)

    async def render(svg, width=1200, background=None):
        return PNG

    monkeypatch.setattr(pcb, "render_png_async", render)
    ctx, state = FakeCtx("ru"), DesignState(pack="device")
    # a fixed board never grows: the first build_device tries its free parts arranged a second way, then stops
    await device_tools._write(ctx, state, {"doc": doc(board={"holes": True, "w": 40, "h": 40, "locked": True}), "summary": "v1"})
    r, images = await device_tools._build(ctx, state, {})
    # 2 listed errors and 46 that follow from them: the board's own count (pcb.version, the card) is 2
    assert r["ok"] is False and r["drc_errors"] == 2 and r["error"].startswith("2 DRC error(s): move SW1")
    assert "follow from these" in r["suppressed"] and "never delete" in r["next"]
    row = await pcb_store.get(PID)
    assert len(row["checks"]["errors"]) == r["drc_errors"]
    assert narrate.localize(narrate.result_title("build_device", {}, r), "ru").startswith("Плата v1 — 2 ошибки DRC, 0 трасс")
    assert images == [f"{PID}/renders/pcb_v1_top.png"]
    # routed clean but a part off its edge: not ok, and the next step says to move it
    r, _ = await device_tools._build(ctx, state, {})
    assert r["ok"] is False and r["drc_errors"] == 0 and r["error"].startswith("intent not met: intent_not_at_edge (J2)")
    assert r["next"].startswith("move the part the intent names") and state.device["ok"] is False
    assert narrate.result_title("build_device", {}, r) == "PCB v2 — 0 DRC errors, 18 traces, 4 vias, intent not met: 1, 36 × 35 mm"
    r, _ = await device_tools._build(ctx, state, {})
    assert r["ok"] is True and r["next"].startswith("make_enclosure") and state.device["ok"] is True


# ---------------------------------------------------------------- write_firmware
async def test_the_firmware_check_is_kept_with_the_version_and_sent_back(fresh_db, offline, monkeypatch):
    plug(monkeypatch, "device_rules", None)
    fc = checker(FW_BAD)
    plug(monkeypatch, "firmware_check", fc)
    ctx, state = FakeCtx(), DesignState(pack="device")
    await device_tools._write(ctx, state, {"doc": doc(), "summary": "v1"})
    r = await device_tools._firmware(ctx, state, {"lang": "arduino", "files": {"main.ino": "void setup(){}\nvoid loop(){}"}})
    assert r["ok"] is False and r["version"] == 2 and r["check"] == {"ran": True, "ok": False, "tool": "arduino-cli", "errors": 1, "warnings": 0}
    assert r["error"].startswith("the firmware check found 1 error(s): main.ino:12 compile: 'display' was not declared")
    assert r["next"].startswith("fix them and write_firmware again") and fc.calls == [(["main.ino"], "arduino")]
    # the check is the saved version's, with the wiring it was made for
    fw = (await device_store.latest(PID))["doc"]["firmware"]
    assert fw["check"]["errors"][0]["line"] == 12 and fw["check"]["wiring"] == device_tools.wiring((await device_store.latest(PID))["doc"])
    assert list(r)[:4] == ["ok", "version", "files", "check"], "the verdict comes before the links (the step summary is cut at 600)"
    assert narrate.result_title("write_firmware", {}, r) == "Firmware: main.ino — check failed: 1"
    assert narrate.localize(narrate.result_title("write_firmware", {}, r), "ru") == "Прошивка: main.ino — ошибок проверки: 1"
    plug(monkeypatch, "firmware_check", checker(FW_OK))
    r = await device_tools._firmware(ctx, state, {"lang": "arduino", "files": {"main.ino": "void setup(){}"}})
    assert r["ok"] is True and r["warnings"] == ["main.ino:3 unused: x unused"] and r["next"] == "quote_device, then finish"
    assert narrate.localize(narrate.result_title("write_firmware", {}, r), "ru") == "Прошивка: main.ino — проверка пройдена"
    # no checker: saved as before, and it says it was not checked
    plug(monkeypatch, "firmware_check", None)
    r = await device_tools._firmware(ctx, state, {"lang": "arduino", "files": {"main.ino": "void setup(){}"}})
    assert r["ok"] is True and r["check"]["ran"] is False and "check" not in (await device_store.latest(PID))["doc"]["firmware"]
    assert narrate.result_title("write_firmware", {}, r) == "Firmware: main.ino — not checked"
    # rewiring after the firmware says so
    r = await device_tools._write(ctx, state, {"edits": [{"op": "connect", "pins": ["U1.D3", "SW1.A"]}], "summary": "button on D3"})
    assert r["firmware"].startswith("the wiring changed since the firmware was written")


# ---------------------------------------------------------------- the finish gate
async def built_device(ctx, state, monkeypatch, *, fw_result=FW_BAD, the_doc=None) -> None:
    monkeypatch.setattr(pcb, "pool", lambda: FakePcb(CLEAN))

    async def render(svg, width=1200, background=None):
        return PNG

    monkeypatch.setattr(pcb, "render_png_async", render)
    await device_tools._write(ctx, state, {"doc": the_doc or doc(), "summary": "v1"})
    await device_tools._build(ctx, state, {})
    plug(monkeypatch, "firmware_check", checker(fw_result))
    await device_tools._firmware(ctx, state, {"lang": "arduino", "files": {"main.ino": "void setup(){}"}})


ENCLOSURE = {"version": 1, "board": "board", "ok": True, "findings": [
    {"code": "light_window", "severity": "warn", "part": "LED1", "value": 99, "msg": "LED1: skin 99.00 mm over the LED (too thick to see it)"},
    {"code": "display_window", "severity": "info", "part": "DS1", "msg": "DS1: window 22.3 x 11.4 mm"}]}


async def test_finish_waits_for_rules_requirements_openings_and_firmware(fresh_db, offline, monkeypatch):
    plug(monkeypatch, "device_rules", rules([NOTE]))
    ctx, state = FakeCtx(), DesignState(pack="device")
    state.self_check["tests_asked"] = True     # the once-only ask for requirement tests has its own test (test_firmware_sim)
    await built_device(ctx, state, monkeypatch)

    async def board_ok(ctx, state):
        return []

    monkeypatch.setattr(pcb_tools, "finish_gate", board_ok)
    state.last_build = {"checks": {"enclosure": copy.deepcopy(ENCLOSURE)}}
    state.finish_attempts = 1
    plug(monkeypatch, "device_rules", rules([DRIVER, NOTE]))
    reasons = await device_tools.finish_gate(ctx, state)
    assert reasons[0] == "design error gpio_overload BZ1: BZ1 draws 30 mA straight from U1.D2 -> add an NPN low-side switch"
    assert not any("pullup_value" in r for r in reasons), "warnings never block"
    # the case: the LED is sealed, the sensor has no opening, the probe's cable no exit; the display has its window
    assert any(r.startswith("LED1: the light is sealed under the lid") and "lights: 'hole'" in r for r in reasons)
    assert any(r.startswith("U2 (sensor) got no opening for the sensor in the case") for r in reasons)
    assert any(r.startswith("accessory P1 (soil probe) has no cable exit") for r in reasons)
    assert not any("DS1" in r for r in reasons)
    assert "firmware: main.ino:12 compile: 'display' was not declared -> declare it before setup()" in reasons
    assert reasons[-1] == "fix the firmware and write_firmware again"
    # fixed: no rule errors, firmware passing; the requirements still name their parts
    plug(monkeypatch, "device_rules", rules([NOTE]))
    plug(monkeypatch, "firmware_check", checker(FW_OK))
    await device_tools._firmware(ctx, state, {"lang": "arduino", "files": {"main.ino": "void setup(){ /* fixed */ }"}})
    state.last_build["checks"]["enclosure"]["findings"] = [
        {"code": "light_window", "severity": "info", "part": "LED1", "value": 0, "msg": "LED1: open window"},
        {"code": "sensor_window", "severity": "info", "part": "U2", "msg": "U2: opening"},
        {"code": "display_window", "severity": "info", "part": "DS1", "msg": "DS1: window"},
        {"code": "cable_exit", "severity": "info", "part": "P1", "msg": "P1: cable exit"}]
    assert await device_tools.finish_gate(ctx, state) == []
    # past BLOCK_ATTEMPTS it ships (the reviewer says what is left)
    plug(monkeypatch, "device_rules", rules([DRIVER]))
    state.finish_attempts = pcb_tools.BLOCK_ATTEMPTS + 1
    assert await device_tools.finish_gate(ctx, state) == []


async def test_finish_rechecks_firmware_written_for_other_wiring_and_names_missing_requirement_parts(fresh_db, offline, monkeypatch):
    plug(monkeypatch, "device_rules", None)
    ctx, state = FakeCtx(), DesignState(pack="device")
    await built_device(ctx, state, monkeypatch, fw_result=FW_OK,
                       the_doc=doc(requirements=REQS + [{"id": "R3", "text": "beeps when it is too humid", "parts": ["BZ1"], "firmware": True}]))

    async def board_ok(ctx, state):
        return []

    monkeypatch.setattr(pcb_tools, "finish_gate", board_ok)
    state.finish_attempts = 1
    fc = checker(FW_BAD)
    plug(monkeypatch, "firmware_check", fc)
    reasons = await device_tools.finish_gate(ctx, state)
    # the stored check passed and was made for this wiring: not run again
    assert fc.calls == [] and reasons == [("requirement R3 (beeps when it is too humid) names BZ1, not in the device: add the part back or "
                                           "point the requirement at the part that does it; a requested function is never dropped")]
    # the person moved the LED in the editor (a version by 'user' that keeps the firmware and its old check): checked again, once
    row = await device_store.latest(PID)
    moved = copy.deepcopy(row["doc"])
    moved["requirements"] = REQS
    for net in moved["nets"]:
        net["pins"] = ["U1.D3" if p == "U1.MOSI" else p for p in net["pins"]]
    await device_store.save(PID, moved, author="user", summary="LED on D3")
    # and built it from the editor: the board's device.json is that version
    built_json = pcb_store.artifact_path(PID, 1, "device.json")
    built_json.write_text(json.dumps({**moved, "_version": (await device_store.latest(PID))["version"]}), encoding="utf-8")
    reasons = await device_tools.finish_gate(ctx, state)
    assert len(fc.calls) == 1 and "firmware: main.ino:12 compile: 'display' was not declared -> declare it before setup()" in reasons
    await device_tools.finish_gate(ctx, state)
    assert len(fc.calls) == 1, "the same files for the same wiring are checked once"


def test_openings_are_only_expected_from_a_case_engine_that_reports_them():
    old = {"findings": [{"code": "light_window", "severity": "info", "part": "LED1", "value": 0, "msg": "open"}]}
    # an engine without the new findings: the sensor and the probe say nothing yet, a light without a finding still does
    assert device_tools.opening_problems({"nodes": []}, BOARD, old) == []
    assert device_tools.opening_problems({"nodes": []}, BOARD, {"findings": []})[0].startswith("LED1 (light) got no opening over the light")
    # a face the designer set that the built board does not carry: the case cut nothing over it
    got = device_tools.opening_problems({"nodes": [{"id": "U2", "face": "sound"}]}, BOARD, old)
    assert got == [("U2 has face sound but the built board gives it access sensor, so the case cuts nothing over it: build_device and "
                    "make_enclosure again")]
    assert device_tools.opening_problems({"nodes": []}, None, old) == [] and device_tools.opening_problems({"nodes": []}, BOARD, None) == []


# ---------------------------------------------------------------- the device reviewer
class FakeDb:
    def __init__(self, rows):
        self.rows = rows

    async def all(self, sql, *args):
        return self.rows if "FROM messages" in sql else []


def png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (20, 120, 40)).save(buf, "PNG")
    path.write_bytes(buf.getvalue())


QUOTE = {"qty": 5, "total_usd": 120.5, "eta": "2026-11-19", "groups": [{"key": "parts", "usd": 30}, {"key": "accessories", "usd": 12.5}],
         "bom": [{"refs": ["U2"], "kind": "chip", "mpn": "BME280", "lcsc": "C92489", "label": "climate sensor", "qty_each": 1, "assembly": "smt", "in_stock": True},
                 {"refs": ["DS1"], "kind": "accessory", "accessory": "oled_096_i2c", "name": "0.96\" OLED 128x64 I2C (SSD1306)",
                  "mpn": "0.96\" OLED 128x64 I2C (SSD1306)", "lcsc": None, "label": "display", "qty_each": 1, "assembly": "hand", "in_stock": True},
                 {"refs": ["BT1"], "kind": "accessory", "accessory": "lipo_1s_500", "name": "LiPo cell 3.7 V 500 mAh", "mpn": "LiPo cell 3.7 V 500 mAh",
                  "label": "battery", "qty_each": 1, "assembly": "hand", "in_stock": True}]}


async def test_the_device_reviewer_reads_the_board_the_firmware_and_the_order(fresh_db, offline, monkeypatch, tmp_path):
    plug(monkeypatch, "device_rules", rules([DRIVER]))
    ctx, state = FakeCtx("ru"), DesignState(pack="device", version=3)
    await built_device(ctx, state, monkeypatch, fw_result=FW_BAD)
    png(settings().data_dir / "files" / PID / "renders" / "pcb_v1_top.png")
    png(settings().data_dir / "files" / PID / "renders" / "v3.png")
    state.last_render = f"{PID}/renders/v3.png"
    state.last_build = {"checks": {"enclosure": copy.deepcopy(ENCLOSURE)}}
    monkeypatch.setattr(device_review, "get_db", _db([{"text": "Сделай метеостанцию", "data": {"brief": "Make a weather station"}}]))

    async def no_questions(project_id, job_id):
        return []

    async def quote(project_id, qty):
        return copy.deepcopy(QUOTE)

    from formwright import deviceapi

    monkeypatch.setattr(critic, "answered", no_questions)
    monkeypatch.setattr(deviceapi, "quote_for", quote)
    seen: list[dict] = []

    class Meta:
        def model_for(self, role, default):
            return "open" if role == "critic" else default

        async def json(self, meter, *, model, system, content, schema, name, effort, max_output_tokens, fallback=True):
            seen.append({"model": model, "system": system, "content": content, "name": name, "fallback": fallback})
            return {"verdict": "pass", "match_score": "8/10", "issues": [
                {"severity": "high", "text": "LED1 is sealed under the lid", "text_user": "светодиод закрыт крышкой", "fix_hint": "lights hole"}]}

    monkeypatch.setattr(device_review, "meta", lambda: Meta())
    v = await device_review.review(ctx, state, summary="Shows the climate on an OLED and beeps")
    # a major issue is a revise whatever the verdict said; the shape is the critic's
    assert v == {"verdict": "revise", "match_score": 8.0, "issues": [{"severity": "major", "text": "LED1 is sealed under the lid",
                                                                       "text_user": "светодиод закрыт крышкой", "fix_hint": "lights hole"}],
                 "model": "open", "reviewer": "primary", "version": 3}
    call = seen[0]
    assert call["fallback"] is False and call["name"] == "device_review" and is_english(call["system"])
    # the rubric: module_bat cells, sensor direction, battery life from the duty cycle, what-is-included claims, floating pins,
    # the person's requirements
    for want in ("has no nets on the carrier by design", "which way the reading moves", "estimate it from the firmware's duty cycle",
                 "what is included", "sits on no net", "never minor", "never propose dropping, weakening or rewording a requirement",
                 "sensor_divider or floating_pin"):
        assert want in call["system"], want
    text = call["content"][0]["text"]
    for want in ("Request: Make a weather station", "The person's own words: \"Сделай метеостанцию\"", "Request language: ru",
                 "Requirements (written by the designer): R1 measure the climate [parts U2, firmware]",
                 "- U2 chip C92489 BME280 (Humidity Sensors) kind sensor 0.7 mA 'BME280 climate sensor'", "- net SDA: ",
                 "[error] gpio_overload BZ1: BZ1 draws 30 mA", "Firmware check: FAILED (arduino-cli); [error] main.ino:12 compile",
                 "Board PCB v1: 0 DRC errors", "- LED1 (led) access light at (8, 8)", "[warn] light_window LED1",
                 "Openings missing: LED1: the light is sealed", "- DS1: ready-made 0.96\" OLED 128x64 I2C (SSD1306) (oled_096_i2c), fitted by hand",
                 "Ready-made modules in the order: DS1 0.96\" OLED 128x64 I2C (SSD1306); BT1 LiPo cell 3.7 V 500 mAh",
                 "every row is in the order and arrives fitted in the device", "## main.ino\n```\nvoid setup(){}",
                 "The designer's summary (check every claim): \"Shows the climate on an OLED and beeps\""):
        assert want in text, want
    kinds = [c["type"] for c in call["content"]]
    assert kinds == ["input_text", "input_text", "input_image", "input_text", "input_image"]
    assert "routed board from the top" in call["content"][1]["text"] and "Renders of the case" in call["content"][3]["text"]
    assert all(c["image_url"].startswith("data:image/") for c in call["content"] if c["type"] == "input_image")


def test_the_reviewer_knows_a_module_bat_cell_has_no_nets_and_what_each_pin_is(monkeypatch):
    lib = {"lipo_1s_1000": {"name": "LiPo cell 3.7 V 1000 mAh", "kind": "battery", "connect": "module_bat", "mount": "inside", "supply": "3V3"},
           "oled_096_i2c": {"name": "OLED", "kind": "display", "connect": "header", "mount": "board", "supply": "3V3-5V", "current_ma": 20}}
    acc = types.ModuleType("formwright.accessories")
    acc.get = lib.get  # type: ignore[attr-defined]
    plug(monkeypatch, "accessories", acc)
    assert device_review.accessory_text("lipo_1s_1000") == (
        "accessory lipo_1s_1000 = LiPo cell 3.7 V 1000 mAh (battery; connect module_bat, mount inside, supply 3V3); its leads are soldered "
        "to the module's BAT+/BAT- pads, so it has no carrier nets by design (correct)")
    assert device_review.accessory_text("oled_096_i2c").endswith("(display; connect header, mount board, supply 3V3-5V, 20 mA)")
    graph = device_review.graph_text({"nodes": [{"id": "U1", "kind": "module", "module": "113991054"},
                                                {"id": "BT1", "kind": "accessory", "accessory": "lipo_1s_1000", "label": "battery"}], "nets": []}, {})
    assert "- BT1 accessory accessory lipo_1s_1000 = LiPo cell" in graph and "no carrier nets by design" in graph
    xiao = device.MODULES["113991054"]
    if xiao.get("gpio"):  # C5, the compiler's: each pin label's GPIO, so a firmware pin can be checked against the wiring
        assert "GPIO D0=2, D1=3" in graph and "strapping GPIO 2, 8, 9" in graph
    assert "GP0=0" not in device_review.module_text("SC0915"), "a Pico's GPn = n says nothing"


def test_rule_data_reaches_the_designer_with_the_direction():
    f = {"code": "sensor_divider", "ref": "R5", "severity": "warning", "msg": "R5 (LDR) is between V3V3 and U1.D1",
         "data": {"pin": "U1.D1", "alias": "D1", "gpio": 3, "quantity": "light", "rises": True}}
    assert device_tools._line(f) == ("sensor_divider R5: R5 (LDR) is between V3V3 and U1.D1 [U1.D1 (D1, GPIO3): the reading rises with "
                                     "more light]")
    assert device_tools._line({**f, "data": {"limit_ma": 20}, "hint": "x"}).endswith('[{"limit_ma":20}] -> x')


async def test_a_device_that_runs_out_of_turns_says_where_the_device_stands(fresh_db, offline, monkeypatch):
    plug(monkeypatch, "device_rules", None)
    ctx, state = FakeCtx("ru"), DesignState(pack="device", version=2)
    await built_device(ctx, state, monkeypatch, fw_result=FW_BAD)
    state.critic = {"verdict": "revise", "version": 2, "issues": [
        {"severity": "major", "text": "R4 calibration not implemented", "text_user": "кнопка калибровки не сохраняет пороги"},
        {"severity": "minor", "text": "cosmetic", "text_user": "мелочь"}]}
    text = await device_tools.handover(PID, "turns", state, "ru")
    # the device's own version, its board, case and firmware: never the case program's version
    assert text == ("Шаги закончились до финальной проверки. Устройство — версия 2: из неё собрана плата v1, 0 ошибок DRC, корпуса под неё "
                    "пока нет, прошивка пока не проходит проверку. Осталось: сделать корпус под последнюю плату; исправить прошивку, чтобы "
                    "она прошла проверку; замечания ревьюера: кнопка калибровки не сохраняет пороги. Напишите сообщение, чтобы продолжить.")
    assert (await device_tools.handover(PID, "time", state, "en")).startswith(
        "Time is up for this run. Device version 2: PCB v1 is built from it with 0 DRC errors, no case for it yet, the firmware does not "
        "pass its check yet. Left: make the case for the latest board;")
    # a device with no board and no firmware yet
    await device_store.save("p_new", device.normalize(doc())[0], author="agent")
    fresh = DesignState(pack="device")
    assert await device_tools.handover("p_new", "time", fresh, "en") == (
        "Time is up for this run. Device version 1: no board is built yet, no firmware yet. Left: build the board from it; write the "
        "firmware. Send a message to continue.")


def test_the_device_pack_gets_more_turns():
    from formwright.agent import loop

    assert loop.PACK_TURNS.get("device", 0) >= 6 and not loop.PACK_TURNS.get("household")


def _db(rows):
    async def get():
        return FakeDb(rows)

    return get


async def test_finish_of_a_device_goes_to_the_device_reviewer(monkeypatch):
    calls = []

    async def gate(ctx, state):
        return []

    async def device_reviewer(ctx, state, *, bar=None, summary=""):
        calls.append(summary)
        return {"verdict": "revise", "match_score": 4, "issues": [{"severity": "major", "text": "the buzzer has no driver", "text_user": "x", "fix_hint": "NPN"}],
                "model": "open", "reviewer": "primary", "version": state.version}

    async def generic(ctx, state, *, bar=None):
        raise AssertionError("the case-only critic must not review a device")

    monkeypatch.setattr(tools.device_tools, "finish_gate", gate)
    monkeypatch.setattr(device_review, "review", device_reviewer)
    monkeypatch.setattr(critic, "review", generic)
    # the reviewer is off by default since 2026-11-03 (the designer's self-check replaces it); the setting brings it back
    monkeypatch.setattr(settings(), "device_reviewer", True)
    ctx, state = FakeCtx(), DesignState(pack="device", version=2)
    state.self_check["passed"] = True
    r = await tools._finish(ctx, state, "a weather station")
    # no case program in the state: a device is reviewed all the same
    assert r == {"accepted": False, "reason": "the reviewer found major problems", "issues": [
        {"severity": "major", "text": "the buzzer has no driver", "text_user": "x", "fix_hint": "NPN"}]}
    assert calls == ["a weather station"] and state.critic["blocking"] is True and not state.done
    assert [t for t, _ in ctx.events if t == "critic"] == ["critic"]


# ---------------------------------------------------------------- the prompt
def test_the_method_and_the_front_panel_example_are_in_the_prompt():
    text = device_prompt.PACK_TEXT
    for want in ("Concept and brainstorm", "Requirements:", "concept_warnings", "module_bat", "never a cell on V5", "design_errors",
                 "Never by deleting a requested function", "sound_grille", "D0=GPIO2", "Strapping pins", "layouts", "accessory", "face", "firmware check", "honest summary"):
        assert want in text, want
    assert "never add one yourself" not in text and is_english(text) and len(text) < 26_000
    ex = device_prompt.EXAMPLE
    assert '"pattern":"dice"' in ex and '"place":{"x":14,"y":-12}' in ex and is_english(ex)
    dice = json.loads(ex.split("```json\n")[2].split("\n```")[0])
    assert [r["id"] for r in dice["requirements"]] == ["R1", "R2", "R3"]
    # four GPIOs for seven pips, none of them a strapping pin of the XIAO ESP32-C3 (D0 = GPIO2, D8, D9)
    drives = {p for n in dice["nets"] for p in n["pins"] if p.startswith("U1.") and p != "U1.GND"}
    assert drives == {"U1.D1", "U1.D2", "U1.D3", "U1.D10", "U1.RX"}
