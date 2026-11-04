"""PCB tools (agent/pcb_tools.py): builds come back as hints, every rendered build is a version, only a clean one gets
fab files, the case is made from the version's board.json, and finish waits for DRC 0, a met intent, the fab files and
a case. A fake PcbPool answers in the shape of C6; the store is the real one on a scratch database. The last tests run
the real bundle and the real geometry engine on the home page's XIAO carrier and on the designer's reference board."""
from __future__ import annotations

import copy
import json
import re
from types import SimpleNamespace

import pytest

from formwright import db as dbmod
from formwright import geom as geommod
from formwright import pcb, pcb_store, pcbapi, showcase
from formwright.agent import critic, device_tools, elec_tools, pcb_prompt, pcb_tools, tools
from formwright.agent.tools import DesignState
from formwright.config import REPO_DIR, settings
from formwright.geom import GeomPool
from formwright.llm.client import CostMeter
from formwright.llm.english import is_english
from formwright.pcb import PcbError, PcbPool

SRC = 'export const meta = { title: "Test carrier" }\nexport default () => (<board width="44mm" height="36mm"><resistor name="R1" resistance="1k" footprint="0603" pcbX={0} pcbY={0} /></board>)'
BOARD = {"schema": "fw.board/1", "id": "pcb", "name": "Test carrier", "source": {"kind": "pcb"}, "frame": "mm",
         "pcb": {"outline": {"kind": "rect", "w": 44, "h": 36}, "thickness": 1.6, "holes": []},
         "components": [{"id": "J1", "type": "usb_c", "side": "top", "access": "port", "edge": "-y", "at": 22, "w": 9, "h": 3.2},
                        {"id": "R1", "type": "passive_0603", "side": "top", "access": "none", "x": 22, "y": 18, "w": 1.6, "d": 0.8, "h": 0.55}]}
INTENT = {"ok": True, "issues": [], "checked": 5}
CLEAN = {"ok": True, "errors": [], "warnings": [{"type": "pcb_trace_warning", "message": "routed thinner than requested", "hint": "fine below 0.5 A"}],
         "suppressed": 0, "quiet": {}, "counts": {"components": 11, "nets": 11, "connections": 25, "traces": 23, "vias": 13},
         "board": BOARD, "circuit_json": [{"type": "pcb_board", "width": 44, "height": 36}], "intent": INTENT,
         "limits": {"ok": True, "issues": [], "limits": {}}, "frames": [{"progress": 1, "lines": [[0, 0, 1, 1]]}], "nets": [],
         "meta": {"title": "Test carrier"}, "ms": 3500, "timings": {}}
DECOUPLING = {"type": "pcb_autorouting_error",
              "message": "Autorouting was skipped because the 1mm maximum length for .C9 > .pin1 to .U1 > .V3V3 cannot be satisfied",
              "hint": "a 100nF capacitor between a supply net and GND counts as decoupling, so each of its traces must be <= 1 mm (now 25.50 mm). "
                      "Place it so C9.pin1 within 1 mm of U1.V3V3 at (7.62, 10.04)"}
FAILED = {**CLEAN, "ok": False, "errors": [DECOUPLING], "suppressed": 25, "counts": {**CLEAN["counts"], "traces": 0, "vias": 0}}
ON_SUPPLY = {**CLEAN, "intent": {"ok": False, "checked": 5, "issues": [{"code": "intent_gpio_on_supply", "ref": "LED1", "msg": "LED1 should be driven by D10, but it reaches V3V3 (through R3)",
                                                                       "hint": "wire LED1 (through its series resistor, if any) to .U1 > .MOSI instead of the supply"}]}}
NO_INTENT = {**CLEAN, "intent": {"ok": True, "issues": [], "checked": 0}}
EXPORT = {"files": {"gerbers.zip": b"PK\x03\x04zip", "board.glb": b"glTF....", "bom.csv": "Comment,Designator,Footprint,LCSC\n", "cpl.csv": "Designator\n",
                    "pcb_top.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>", "pcb_bottom.svg": "<svg/>", "schematic.svg": "<svg/>"},
          "layers": ["board.GTL", "board.GBL"], "svg_map": {"pcb_top.svg": {"matrix": [20, 0, 0, -20, 25, 765]}}, "glb_map": {"matrix": []},
          "bom_lines": 9, "cpl_lines": 9, "lcsc_verified": False, "rotation_checked": False, "ms": 300}
CASE_CLEAN = {"op": "enclosure", "board": "board", "ms": 90, "clearance": {"J1": 0.268, "U1_usb": 0.27}, "rays": [],
              "findings": [{"code": "port_clear", "severity": "info", "part": "J1", "value": 0.268, "unit": "mm", "msg": "J1: plug clear"}]}
PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeCtx:
    def __init__(self, language: str = "en"):
        self.project = {"id": "p_pcb", "title": "XIAO carrier", "brief": {"language": language}}
        self.project_id = "p_pcb"
        self.user = {"id": "u_pcb"}
        self.job_id = "j_pcb"
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
        self.calls: list[tuple] = []

    async def build(self, source, *, intent=None, on_frame=None, timeout=None, name=None):
        self.calls.append(("build", source, intent))
        b = self.builds.pop(0)
        if isinstance(b, Exception):
            raise b
        if on_frame:
            await on_frame({"frame": 0, "total": 24, "progress": 0.5, "lines": [[0, 0, 1, 1]], "w": 44, "h": 36})
        return copy.deepcopy(b)

    async def export(self, circuit_json, *, timeout=60):
        self.calls.append(("export",))
        return copy.deepcopy(EXPORT)


class FakeGeom:
    def __init__(self):
        self.calls: list[tuple] = []

    async def build(self, source, params=None, **extra):
        self.calls.append(("build", source, extra))
        return {"params": {"wall": 2}, "paramSpecs": {}, "parts": [{"name": "base", "role": "model"}, {"name": "lid", "role": "model"}],
                "checks": {"ok": True, "issues": [], "stats": {"size": [60, 52, 18]}}}

    async def render(self, source, params=None, **extra):
        import base64

        return {"png": base64.b64encode(b"png").decode()}

    async def inspect(self, source, params=None, ops=None, **extra):
        self.calls.append(("inspect", ops, extra))
        return {"results": [copy.deepcopy(CASE_CLEAN)]}


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    db = await dbmod.get_db()
    yield db
    await dbmod.close_db()


@pytest.fixture
def emitted(monkeypatch):
    """The project events pcbapi sends (pcb.route, pcb.version), in order."""
    out: list[tuple[str, dict]] = []

    async def emit(project_id, type_, data, job_id=None):
        out.append((type_, data))

    monkeypatch.setattr(pcbapi.events, "emit", emit)
    return out


def fake_pcb(monkeypatch, *builds) -> FakePcb:
    p = FakePcb(*builds)
    monkeypatch.setattr(pcb, "pool", lambda: p)

    async def render(svg, width=1200, background=None):
        return PNG

    monkeypatch.setattr(pcb, "render_png_async", render)
    return p


def stub_review(monkeypatch):
    async def review(ctx, state, *, bar=None):
        return {"verdict": "pass", "match_score": 9, "issues": [], "model": "open", "reviewer": "primary"}

    monkeypatch.setattr(critic, "review", review)


async def write(ctx, state, source=SRC, **kw):
    return await pcb_tools.run(ctx, state, "write_circuit", {"source": source, "summary": "board", **kw})


async def test_a_drc_error_comes_back_with_its_hint_and_blocks_finish(fresh_db, monkeypatch, emitted):
    fake_pcb(monkeypatch, FAILED)
    ctx, state = FakeCtx(), DesignState(pack="pcb")
    r, images = await write(ctx, state)
    assert r["ok"] is False and r["version"] == 1 and r["error"].startswith("1 DRC error(s): a 100nF capacitor") and r["drc_errors"] == 1
    assert r["errors"] == [DECOUPLING] and "follow from these" in r["suppressed"] and r["fab"].startswith("none")
    assert r["next"].startswith("apply the hints") and r["ports"] == ["J1 (usb_c) on -y"] and r["board_mm"] == [44, 36]
    # the routing animation and the version went out as project events (C8)
    assert [t for t, _ in emitted] == ["pcb.route", "pcb.version"]
    assert emitted[0][1]["lines"] == [[0, 0, 1, 1]] and emitted[1][1]["drc"] == {"errors": 1, "warnings": 1}
    # a board with DRC errors is shown (previews) but never offered to a fab
    row = await pcb_store.get("p_pcb")
    assert set(row["artifacts"]) >= {"pcb_top.svg", "schematic.svg", "board.glb", "board.json", "circuit.tsx"}
    assert not set(row["artifacts"]) & {"gerbers.zip", "bom.csv", "cpl.csv"} and "layers" not in row["checks"]["fab"]
    assert images == ["p_pcb/renders/pcb_v1_top.png"] and state.pcb["made"] and not state.pcb["ok"]
    r = await tools._finish(ctx, state, "done")
    assert r["accepted"] is False and r["reason"] == "the board is not ready"
    assert r["issues"][0].startswith("DRC pcb_autorouting_error: Autorouting was skipped") and "-> a 100nF capacitor" in r["issues"][0]
    r, _ = await pcb_tools.run(ctx, state, "export_fab", {})
    assert r["ok"] is False and "1 DRC error" in r["error"]


async def test_an_intent_that_is_not_met_or_not_stated_blocks_finish(fresh_db, monkeypatch, emitted):
    fake_pcb(monkeypatch, ON_SUPPLY, NO_INTENT)
    ctx, state = FakeCtx(), DesignState(pack="pcb")
    r, _ = await write(ctx, state)
    # DRC is clean, so fab files exist, but the "status" LED sits on the supply
    assert r["ok"] is True and r["intent"]["ok"] is False and r["next"].startswith("fix the intent") and r["fab"].startswith("ready")
    r = await tools._finish(ctx, state, "")
    assert r["accepted"] is False and r["issues"] == [
        "intent_gpio_on_supply (LED1): LED1 should be driven by D10, but it reaches V3V3 (through R3) -> wire LED1 (through its series "
        "resistor, if any) to .U1 > .MOSI instead of the supply"]
    r, _ = await write(ctx, state)
    assert r["intent"]["checked"] == 0 and "no intent stated" in r["intent"]["note"]
    r = await tools._finish(ctx, state, "")
    assert r["accepted"] is False and "states no intent" in r["issues"][0]


async def test_a_clean_board_exports_gets_its_case_and_finishes(fresh_db, monkeypatch, emitted):
    p = fake_pcb(monkeypatch, CLEAN, CLEAN)
    g = FakeGeom()
    monkeypatch.setattr(tools, "geom", lambda: g)
    monkeypatch.setattr(elec_tools, "geom", lambda: g)
    stub_review(monkeypatch)
    ctx, state = FakeCtx("ru"), DesignState(pack="pcb")
    r, _ = await write(ctx, state, intent={"edge": {"J1": "-y"}})
    assert r["ok"] and r["fab"].startswith("ready: gerbers.zip, bom.csv, cpl.csv") and r["next"] == "export_fab, then make_enclosure"
    assert p.calls[0] == ("build", SRC, {"edge": {"J1": "-y"}})  # the intent argument overrides meta.intent
    r, _ = await pcb_tools.run(ctx, state, "export_fab", {})
    assert r["ok"] and r["files"]["gerbers.zip"] == "/api/projects/p_pcb/pcb/1/gerbers.zip" and r["layers"] == ["board.GTL", "board.GBL"]
    assert "pcb_top.svg" in r["files"] and len(r["unverified"]) == 2 and state.pcb["exported"] == 1
    # the counts before the links: the step summary (the JSON cut at 600 characters) keeps them for the RU rebuild (steps.ts)
    assert list(r)[:5] == ["ok", "version", "bom_lines", "cpl_lines", "layers"]
    assert '"version": 1, "bom_lines": 9, "cpl_lines": 9, "layers": ["board.GTL", "board.GBL"], "files"' in json.dumps(r, ensure_ascii=False)[:600]
    r = await tools._finish(ctx, state, "")
    assert r == {"accepted": False, "reason": "the board is not ready", "issues": ["no case for PCB v1 yet: make_enclosure"]}

    r, images = await pcb_tools.run(ctx, state, "make_enclosure", {"options": {"port_fit": 0.4}})
    assert r["ok"] and r["version"] == 1 and r["pcb_version"] == 1 and r["mockup"] is True and r["enclosure"]["ok"] is True
    # the step summary is cut at 600 characters and the brief comes last: its verdict goes up front (steps.ts reads it in RU)
    assert r["case_fit"] == tools._case_verdict(r["enclosure"]) and list(r).index("case_fit") == list(r).index("printable") + 1
    # the board's version too: the call named none, and the RU step names it from the cut summary
    assert list(r)[:3] == ["ok", "version", "pcb_version"]
    assert images == ["p_pcb/renders/v1.png"]
    row = await fresh_db.one("SELECT * FROM programs WHERE project_id = 'p_pcb' AND version = 1")
    assert "lib.inputs.boards.board" in row["source"] and "pcbPlate" in row["source"] and "value: 0.4" in row["source"]
    assert row["inputs"]["boards"]["board"]["source"]["pcb_job"] == "pcb:v1" and row["summary"] == "корпус для платы v1"
    assert row["checks"]["enclosure"]["ok"] is True  # checked against the board at once
    assert g.calls[-1][1] == [{"op": "enclosure", "board": "board"}]
    fact = next(f for f in state.facts if f["subject"] == pcb_tools.FACT_SUBJECT)
    assert fact["value"]["drc_errors"] == 0 and "stand-in plate" in fact["value"]["note"]
    assert await pcb_tools.finish_gate(ctx, state) == []
    r = await tools._finish(ctx, state, "Плата готова")
    assert r == {"accepted": True} and state.done

    # a newer board needs its own case
    state.done, state.finish_attempts = False, 0
    await write(ctx, state)
    assert await pcb_tools.finish_gate(ctx, state) == ["no case for PCB v2 yet: make_enclosure"]
    r, _ = await pcb_tools.run(ctx, state, "make_enclosure", {"options": {"walls": 3}})
    assert r["ok"] is False and "walls" in r["error"] and "port_fit" in r["hint"]


async def test_edits_engine_failures_and_the_attempt_limit(fresh_db, monkeypatch, emitted):
    p = fake_pcb(monkeypatch, PcbError("compile", "Unexpected token (3:5)"),
                 PcbError("crash", "worker exited"), CLEAN,
                 CLEAN,
                 PcbError("crash", "worker exited"), PcbError("crash", "worker exited"))
    ctx, state = FakeCtx(), DesignState(pack="pcb")
    r, _ = await pcb_tools.run(ctx, state, "write_circuit", {"edits": [{"find": "a", "replace": "b"}], "summary": ""})
    assert r["ok"] is False and "no circuit yet" in r["error"] and not p.calls
    r, _ = await write(ctx, state)
    assert r["ok"] is False and r["stage"] == "compile" and "nothing was saved" in r["note"] and await pcb_store.get("p_pcb") is None
    # the worker died once: retried without a word, then saved
    r, _ = await write(ctx, state)
    assert r["ok"] and r["version"] == 1 and [c[0] for c in p.calls].count("build") == 3
    r, _ = await pcb_tools.run(ctx, state, "write_circuit", {"edits": [{"find": 'pcbX={0} pcbY={0}', "replace": "pcbX={5} pcbY={0}"}], "summary": "R1"})
    assert r["ok"] and r["version"] == 2 and "pcbX={5}" in p.calls[-2][1]
    r, _ = await pcb_tools.run(ctx, state, "write_circuit", {"edits": [{"find": "pcbX={99}", "replace": ""}], "summary": ""})
    assert r["ok"] is False and "not found" in r["error"]
    r, _ = await write(ctx, state)
    assert r["ok"] is False and r["infra"] is True and "not the problem" in r["error"]
    # past the attempt limit the gate lets it ship, like printability errors
    state.finish_attempts = pcb_tools.BLOCK_ATTEMPTS + 1
    assert await pcb_tools.finish_gate(ctx, state) == []
    state.finish_attempts = 1
    assert await pcb_tools.finish_gate(ctx, DesignState(pack="pcb")) != []


async def test_check_pcb_and_look_read_a_saved_version(fresh_db, monkeypatch, emitted):
    fake_pcb(monkeypatch, FAILED, CLEAN)
    ctx, state = FakeCtx(), DesignState(pack="pcb")
    await write(ctx, state)
    await write(ctx, state)
    r, _ = await pcb_tools.run(ctx, state, "check_pcb", {"version": 1})
    assert r["ok"] is False and r["version"] == 1 and r["errors"][0]["hint"] == DECOUPLING["hint"] and r["case"].startswith("none")
    r, _ = await pcb_tools.run(ctx, state, "check_pcb", {})
    assert r["ok"] and r["version"] == 2 and r["intent"] == {"ok": True, "checked": 5}
    r, _ = await pcb_tools.run(ctx, state, "check_pcb", {"version": 7})
    assert r["ok"] is False and "no PCB version 7" in r["error"]
    r, images = await tools.run_tool(ctx, state, "look", {"what": "schematic", "version": 1})
    assert r == {"ok": True, "version": 1} and images == ["p_pcb/renders/pcb_v1_schematic.png"]
    r, images = await tools.run_tool(ctx, state, "look", {"what": "pcb"})
    assert images == ["p_pcb/renders/pcb_v2_top.png"]
    r, _ = await tools.run_tool(ctx, state, "look", {"what": "model"})
    assert r["ok"] is False and "no program yet" in r["error"]  # the case view needs make_enclosure first


async def test_a_job_picks_up_the_board_and_hands_over_without_a_case(fresh_db, monkeypatch, emitted):
    fake_pcb(monkeypatch, CLEAN)
    ctx, state = FakeCtx("ru"), DesignState(pack="pcb")
    await write(ctx, state)
    fresh = DesignState(pack="pcb")
    await pcb_tools.load("p_pcb", fresh)
    assert fresh.pcb["version"] == 1 and fresh.pcb["source"] == SRC and fresh.pcb["ok"] and "made" not in fresh.pcb
    lines = pcb_tools.context_lines(fresh)
    assert lines[0].startswith("# Current circuit: PCB version 1 (DRC clean, intent ok)") and SRC in lines[0]
    text = pcb_tools.handover("time", state, "ru")
    assert text.startswith("Время на этот запуск вышло. Последняя версия платы — 1: 0 ошибок DRC, корпуса пока нет.")
    assert pcb_tools.handover("budget", state, "en").startswith("Stopped at the spending cap. PCB version 1 is the latest: 0 DRC errors")
    card = await pcb_tools.card("p_pcb", state)
    assert card["version"] == 1 and card["drc"] == {"errors": 0, "warnings": 1} and card["files"]["gerbers.zip"].endswith("/pcb/1/gerbers.zip")


def test_the_model_facing_text_is_english():
    for t in [*pcb_tools.TOOLS, pcb_tools.LOOK]:
        assert is_english(json.dumps(t)), t["name"]
    assert pcb_tools.NAMES == {"write_circuit", "check_pcb", "export_fab", "make_enclosure"}
    assert is_english(pcb_prompt.PACK_TEXT) and is_english(pcb_prompt.EXAMPLE) and is_english(pcb_prompt.CLASSIFY_HINT)
    assert pcb_prompt.PACK_TEXT.startswith("# Pack: printed circuit boards")
    # the exact pin labels and the module numbers the engine keys on
    assert 'manufacturerPartNumber="113991054"' in pcb_prompt.PACK_TEXT and 'pin16:"GND_B"' in pcb_prompt.PACK_TEXT
    assert 'manufacturerPartNumber="SC0915"' in pcb_prompt.PACK_TEXT
    assert len(pcb_prompt.PACK_TEXT) < 7500  # about 1.6k tokens
    # the switch's legs pair up inside: the rules and both boards wire GPIO to pin1 and GND to pin3, never pin1 + pin2
    tied = 'internallyConnectedPins={[["pin1", "pin2"], ["pin3", "pin4"]]}'
    assert 'GPIO to pin1, GND to pin3' in pcb_prompt.PACK_TEXT
    for board in (pcb_prompt.EXAMPLE, showcase.XIAO_CARRIER):
        assert tied in board and '.SW1 > .pin3" to="net.GND"' in board and '.SW1 > .pin2"' not in board
        # the 5 V path runs pin to pin, where the router keeps the width
        assert 'to="net.VBUS"' not in board and board.count('thickness="0.4mm"') == 2


def test_the_reference_board_is_not_the_home_page_board():
    # a XIAO brief must be designed, not copied: the prompt's board is a Pico carrier, the card's a XIAO one
    assert "113991054" not in pcb_prompt.EXAMPLE and 'manufacturerPartNumber="SC0915"' in pcb_prompt.EXAMPLE
    assert 'manufacturerPartNumber="113991054"' in showcase.XIAO_CARRIER
    code = lambda s: [ln for ln in s.splitlines() if not ln.lstrip().startswith("//")]  # noqa: E731
    fixtures = REPO_DIR / "packages" / "pcb" / "test" / "fixtures"
    # each is the engine's own tested fixture, apart from the comments for the model
    assert code(pcb_prompt.EXAMPLE) == code((fixtures / "carrier.tsx").read_text(encoding="utf-8"))
    assert code(showcase.XIAO_CARRIER) == code((fixtures / "xiao_carrier.tsx").read_text(encoding="utf-8"))


CONCEPT = {"uses": ["by the bed", "in a hand"], "chosen": "Tilted puck", "why": "reads from the pillow",
           "options": [{"name": "Plain box", "form": "box", "stance": "desk", "mounting": "none"},
                       {"name": "Tilted puck", "form": "round", "stance": "tilt", "mounting": "magnets"}]}


async def _case(monkeypatch, pack, concept, options=None):
    """make_enclosure on a saved board, with the device doc's concept; the program's own lines say what it was built with."""
    fake_pcb(monkeypatch, CLEAN)
    g = FakeGeom()
    monkeypatch.setattr(tools, "geom", lambda: g)
    monkeypatch.setattr(elec_tools, "geom", lambda: g)

    async def current(project_id):
        return ({"schema": "fw.device/1", **({"concept": concept} if concept else {})}, 1)

    monkeypatch.setattr(device_tools, "current", current)
    ctx, state = FakeCtx(), DesignState(pack=pack)
    await write(ctx, state)
    r, _ = await pcb_tools.run(ctx, state, "make_enclosure", {"options": options or {}})
    return r, elec_tools.case_options(state.source)


async def test_a_device_case_takes_form_stance_and_mounting_from_the_chosen_concept(fresh_db, monkeypatch, emitted):
    r, opts = await _case(monkeypatch, "device", CONCEPT)
    assert r["ok"] and r["from_concept"] == {"option": "Tilted puck", "form": "round", "stance": "tilt", "mounting": "magnets"}
    assert (opts["form"], opts["stance"], opts["mounting"]) == ("round", "tilt", "magnets")
    assert "concept_warnings" not in r  # it is what the concept chose


async def test_explicit_case_options_win_over_the_concept_and_only_the_rest_is_named(fresh_db, monkeypatch, emitted):
    r, opts = await _case(monkeypatch, "device", CONCEPT, {"form": "box", "mounting": "none", "port_fit": 0.4})
    assert r["from_concept"] == {"option": "Tilted puck", "stance": "tilt"}
    assert (opts["form"], opts["stance"], opts["mounting"], opts["port_fit"]) == ("box", "tilt", "none", 0.4)
    # 'auto' asks for nothing: the concept's stance still comes
    r, opts = await _case(monkeypatch, "device", CONCEPT, {"stance": "auto", "form": "round", "mounting": "magnets"})
    assert r["from_concept"] == {"option": "Tilted puck", "stance": "tilt"} and opts["stance"] == "tilt"


async def test_no_concept_a_bad_one_or_another_pack_keep_the_plain_defaults(fresh_db, monkeypatch, emitted):
    for pack, concept in (("device", None), ("device", {"options": CONCEPT["options"]}), ("pcb", CONCEPT),
                          ("device", {**CONCEPT, "chosen": "nothing like this"})):
        r, opts = await _case(monkeypatch, pack, concept)
        assert r["ok"] and "from_concept" not in r, (pack, concept)
        assert (opts["form"], opts["stance"], opts["mounting"]) == ("soft", "auto", "none")
    # a value the case does not know is left out, the rest still comes; a stance of auto follows the mounting
    odd = {**CONCEPT, "options": [{"name": "Tilted puck", "form": "hexagon", "stance": "auto", "mounting": "ears"}]}
    r, opts = await _case(monkeypatch, "device", odd)
    assert r["from_concept"] == {"option": "Tilted puck", "mounting": "ears"}
    assert (opts["form"], opts["stance"], opts["mounting"]) == ("soft", "auto", "ears")


def test_the_tool_says_what_each_stance_form_and_mounting_looks_like():
    text = pcb_tools.MAKE_ENCLOSURE["parameters"]["properties"]["options"]["description"]
    assert is_english(pcb_tools.MAKE_ENCLOSURE["description"] + text)
    for k, choices in (("form", ("soft", "round", "box")), ("stance", ("desk", "tilt", "upright", "wall", "hand")),
                       ("mounting", ("ears", "strap", "lanyard", "stake", "magnets", "contacts"))):
        assert k + "," in text and all(f"'{c}'" in text for c in choices), k
    assert "chosen concept" in text


# ---------------------------------------------------------------- the real bundle and engine

DIST = REPO_DIR / "packages" / "pcb" / "dist"
needs_bundle = pytest.mark.skipif(not (DIST / "pcb-worker.mjs").exists(), reason="run `npm ci --ignore-scripts && npm run bundle` in packages/pcb")


@pytest.fixture
async def real_engines():
    old_g, old_p = geommod._pool, pcb._pool
    geommod._pool, pcb._pool = GeomPool(1), PcbPool(1)
    yield
    await geommod._pool.close()
    await pcb._pool.close()
    geommod._pool, pcb._pool = old_g, old_p


@needs_bundle
async def test_the_carrier_example_goes_from_circuit_to_checked_case(fresh_db, real_engines, emitted):
    ctx, state = FakeCtx(), DesignState(pack="pcb")
    r, images = await write(ctx, state, source=showcase.XIAO_CARRIER)
    assert r["ok"] and r["intent"]["ok"] and r["intent"]["checked"] == 6 and r["counts"]["traces"] >= 20, r
    assert "warnings" not in r  # nothing for the card's engine notes
    assert sorted(r["ports"]) == ["J1 (usb_c) on -y", "J2 (pin_header_2_54) on +x", "U1_usb (usb_c) on +y"]
    png = settings().data_dir / "files" / images[0]
    assert png.read_bytes()[:4] == b"\x89PNG"
    assert sum(1 for t, _ in emitted if t == "pcb.route") >= 1
    r, _ = await pcb_tools.run(ctx, state, "export_fab", {})
    assert r["ok"] and pcb_store.artifact_path("p_pcb", 1, "gerbers.zip").read_bytes()[:2] == b"PK"
    # all the real layer files and both line counts inside the step summary's cut, ahead of the long links
    cut = json.dumps(r, ensure_ascii=False)[:600]
    assert len(r["layers"]) >= 9 and f'"bom_lines": {r["bom_lines"]}, "cpl_lines": {r["cpl_lines"]}, "layers": {json.dumps(r["layers"])}' in cut
    r, images = await pcb_tools.run(ctx, state, "make_enclosure", {})
    assert r["ok"] and r["printable"] and r["enclosure"]["ok"], r.get("enclosure")
    assert [p["name"] for p in r["parts"]] == ["base", "lid", "pcb_mockup"]
    # both USB-C ports and the I2C header at the edge get a window (the header is a port, pcb-engine deviation 3)
    assert set(r["enclosure"]["clearance_mm"]) == {"J1", "J2", "U1_usb"}
    # the case as it stands assembled, not the print plate of size_mm
    W, H = r["case_fit"]["case_mm"][:2]
    assert W < r["size_mm"][0] and H < r["size_mm"][1], r["case_fit"]
    assert re.search(r'"case_fit": \{"fits": true, "case_mm": \[[\d., ]+\], "usb_clearance_mm": 0\.29', json.dumps(r, ensure_ascii=False)[:600])
    assert json.dumps(r, ensure_ascii=False).startswith('{"ok": true, "version": 1, "pcb_version": 1, ')
    assert await pcb_tools.finish_gate(ctx, state) == []


@needs_bundle
async def test_the_reference_board_routes_clean_and_its_pico_gets_a_case(fresh_db, real_engines, emitted):
    ctx, state = FakeCtx(), DesignState(pack="pcb")
    r, _ = await write(ctx, state, source=pcb_prompt.EXAMPLE)
    assert r["ok"] and "warnings" not in r and r["intent"] == {"ok": True, "checked": 6} and r["counts"]["traces"] >= 20, r
    # the Pico is a module: its own micro-USB is a port at the top edge, next to the USB-C input and the header
    assert sorted(r["ports"]) == ["J1 (usb_c) on +x", "J2 (pin_header_2_54) on -y", "U1_usb (usb_micro_b) on +y"]
    r, _ = await pcb_tools.run(ctx, state, "make_enclosure", {})
    assert r["ok"] and r["printable"] and r["enclosure"]["ok"], r.get("enclosure")
    assert set(r["enclosure"]["clearance_mm"]) == {"J1", "J2", "U1_usb"}
