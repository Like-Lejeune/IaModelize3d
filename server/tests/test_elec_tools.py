"""Electronics enclosure tools (agent/elec_tools.py): boards into inputs.boards, the case check kept as
checks.enclosure of its version (C5), and the finish gate. A fake geometry pool answers op 'enclosure' in the
shape of C3; the last tests run the real engine on the case example."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from formwright import db as dbmod
from formwright import geom as geommod
from formwright.agent import elec_tools as et
from formwright.agent import tools
from formwright.agent.tools import DesignState
from formwright.config import settings
from formwright.geom import GeomError, GeomPool
from formwright.llm.client import CostMeter
from formwright.llm.english import is_english

PICO = et.dataset_board("rpi-pico-w")


class FakeCtx:
    def __init__(self, language: str = "en"):
        self.project = {"id": "p_case", "title": "Pico case", "brief": {"language": language}}
        self.project_id = "p_case"
        self.user = {"id": "u_case"}
        self.job_id = "j_case"
        self.meter = CostMeter()
        self.models = SimpleNamespace(designer="muse-spark-1.3", fast="muse-spark-1.3-contributor")
        self.events: list[tuple[str, dict]] = []

    async def emit(self, type_: str, data: dict | None = None) -> None:
        self.events.append((type_, data or {}))

    async def status(self, text: str) -> None:
        self.events.append(("agent.status", {"text": text}))

    def check_cancelled(self) -> None:
        pass


def finding(code: str, severity: str, part: str, value, unit: str | None = None, msg: str | None = None) -> dict:
    return {"code": code, "severity": severity, "part": part, "value": value, **({"unit": unit} if unit else {}), "msg": msg or f"{part}: {code}"}


CLEAN = {"op": "enclosure", "board": "board", "ms": 120, "clearance": {"usb": 0.268},
         "rays": [{"port": "usb", "from": [10.5, 52.4, 4.1], "to": [10.5, 57.0, 4.1], "hit": False}],
         "findings": [finding("port_clear", "info", "usb", 0.268, "mm"), finding("pcb_seated", "info", "pcb", 4),
                      finding("button_reach", "info", "bootsel", 0.3, "mm"), finding("snap_strain", "info", "lid", 1.67, "%"),
                      finding("keepout_ok", "info", "antenna", 565, "mm3")]}
BLOCKED = {**CLEAN, "clearance": {"usb": 0},
           "findings": [finding("port_blocked", "error", "usb", 0, "mm", "usb: the 10.6x7.6 mm plug hits the case"), *CLEAN["findings"][1:]]}


class FakePool:
    def __init__(self, answer: dict | Exception):
        self.answer = answer
        self.calls: list[dict] = []

    async def inspect(self, source, params=None, ops=None, **extra):
        self.calls.append({"source": source, "params": params, "ops": ops, **extra})
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"results": [json.loads(json.dumps(self.answer))]}


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    db = await dbmod.get_db()
    yield db
    await dbmod.close_db()


def pool(monkeypatch, answer) -> FakePool:
    p = FakePool(answer)
    monkeypatch.setattr(et, "geom", lambda: p)
    return p


async def case_state(db, version: int = 2) -> DesignState:
    inputs = {"boards": {"board": PICO}}
    await db.insert("programs", {"project_id": "p_case", "version": version, "source": et.EXAMPLE, "params": {"wall": 2}, "inputs": inputs,
                                 "summary": "case", "checks": {"ok": True, "issues": []}, "author": "agent", "created_at": 0})
    st = DesignState(pack="enclosure", source=et.EXAMPLE, version=version, inputs=inputs, params={"wall": 2},
                     last_build={"checks": {"ok": True, "issues": []}})
    st.build_args = {"params": {"wall": 2}, "inputs": inputs}
    return st


async def test_a_blocked_port_holds_finish_and_is_kept_on_the_version(fresh_db, monkeypatch):
    p = pool(monkeypatch, BLOCKED)
    ctx, state = FakeCtx(), await case_state(fresh_db)
    state.finish_attempts = 1
    reasons = await et.finish_gate(ctx, state)
    assert len(reasons) == 1 and reasons[0].startswith("port_blocked (usb)") and "port_fit" in reasons[0]
    # the check ran on the build the version was made with
    assert p.calls[0]["ops"] == [{"op": "enclosure", "board": "board"}] and p.calls[0]["params"] == {"wall": 2}
    assert p.calls[0]["inputs"]["boards"]["board"]["id"] == "rpi-pico-w"
    row = await fresh_db.one("SELECT checks FROM programs WHERE project_id = 'p_case' AND version = 2")
    enc = row["checks"]["enclosure"]
    assert row["checks"]["ok"] is True  # the printability checks are left as they were
    assert enc["ok"] is False and enc["board"] == "board" and enc["version"] == 2 and enc["clearance"] == {"usb": 0}
    assert enc["summary"] == {"usb_clearance_mm": 0, "button_gap_mm": 0.3, "snap_strain_pct": 1.67}
    assert enc["rays"] and enc["findings"][0]["code"] == "port_blocked"
    assert state.last_build["checks"]["enclosure"] == enc
    assert ("enclosure.checked", {"version": 2, "enclosure": enc}) in ctx.events
    # the reviewer gets the measured numbers as a fact
    fact = next(f for f in state.facts if f["subject"] == et.FACT_SUBJECT)
    assert fact["value"]["usb_clearance_mm"] == 0 and fact["value"]["errors"] == ["usb: the 10.6x7.6 mm plug hits the case"]
    # a second finish on the same version reuses the stored check
    assert await et.finish_gate(ctx, state) == reasons and len(p.calls) == 1


async def test_clean_findings_let_finish_through(fresh_db, monkeypatch):
    pool(monkeypatch, CLEAN)
    ctx, state = FakeCtx(), await case_state(fresh_db)
    assert await et.finish_gate(ctx, state) == []
    enc = (await fresh_db.one("SELECT checks FROM programs WHERE project_id = 'p_case' AND version = 2"))["checks"]["enclosure"]
    assert enc["ok"] is True and enc["summary"] == {"usb_clearance_mm": 0.268, "button_gap_mm": 0.3, "snap_strain_pct": 1.67}
    # what the designer reads: problems in full, passes as one line each, no rays
    r, images = await et.run(ctx, state, "check_enclosure", {})
    assert r["ok"] is True and r["errors"] == [] and r["warnings"] == [] and len(r["passed"]) == 5 and "rays" not in r and images == []


async def test_warnings_do_not_block_but_a_new_version_is_checked_again(fresh_db, monkeypatch):
    warn = {**CLEAN, "findings": [*CLEAN["findings"], finding("pcb_seated", "warn", "pcb", 2, msg="PCB: held down from above at 0")]}
    p = pool(monkeypatch, warn)
    ctx, state = FakeCtx(), await case_state(fresh_db)
    assert await et.finish_gate(ctx, state) == []
    r, _ = await et.run(ctx, state, "check_enclosure", {"board": "board"})
    assert [w["code"] for w in r["warnings"]] == ["pcb_seated"] and r["warnings"][0]["fix"]
    calls = len(p.calls)
    await fresh_db.insert("programs", {"project_id": "p_case", "version": 3, "source": et.EXAMPLE, "params": {}, "inputs": state.inputs,
                                       "summary": "v3", "checks": {}, "author": "agent", "created_at": 1})
    state.version = 3
    p.answer = BLOCKED
    assert (await et.finish_gate(ctx, state))[0].startswith("port_blocked") and len(p.calls) == calls + 1


async def test_nothing_to_check_and_the_attempt_limit(fresh_db, monkeypatch):
    p = pool(monkeypatch, BLOCKED)
    ctx = FakeCtx()
    assert await et.finish_gate(ctx, DesignState(pack="enclosure", source=et.EXAMPLE)) == []  # no board: a plain box is not checked
    assert await et.finish_gate(ctx, DesignState(pack="enclosure", inputs={"boards": {"board": PICO}})) == []  # no program yet
    state = await case_state(fresh_db)
    state.finish_attempts = et.BLOCK_ATTEMPTS + 1  # like printability errors: from then on it ships and says what is left
    assert await et.finish_gate(ctx, state) == [] and p.calls == []


async def test_an_engine_failure_is_not_the_designs_fault_but_a_broken_assembly_is(fresh_db, monkeypatch):
    ctx, state = FakeCtx(), await case_state(fresh_db)
    pool(monkeypatch, GeomError("crash", "worker exited"))
    monkeypatch.setattr(tools, "_geom_retry", lambda call: call())
    assert await et.finish_gate(ctx, state) == []
    pool(monkeypatch, GeomError("runtime", "spec.components is not iterable"))
    reasons = await et.finish_gate(ctx, state)
    assert reasons == ["the assembled case does not build (runtime): spec.components is not iterable"]
    r, _ = await et.run(ctx, state, "check_enclosure", {})
    assert r["ok"] is False and r["stage"] == "runtime"


async def test_use_board_takes_a_dataset_board_and_remembers_it(fresh_db, monkeypatch):
    ctx, state = FakeCtx(), DesignState(pack="enclosure")
    r, images = await et.run(ctx, state, "use_board", {"board_id": "Pico W"})
    assert r["ok"] and r["input"] == "inputs.boards.board" and state.inputs["boards"]["board"]["id"] == "rpi-pico-w" and images == []
    assert r["board"]["size_mm"] == [21, 51, 1] and len(r["board"]["holes"]) == 4 and "write the case program" in r["next"]
    assert {p["id"] for p in r["board"]["parts"]} == {"usb", "bootsel", "led"}  # parts with no access stay out of the brief
    mem = await fresh_db.one("SELECT * FROM memory WHERE kind = 'interface' AND user_id = 'u_case'")
    assert mem["name"] == "Raspberry Pi Pico W" and mem["body"]["values"]["holes"][0] == [4.8, 2, 2.1] and mem["body"]["source"] == "dataset"
    assert ("memory", {"items": [{"kind": "interface", "name": "Raspberry Pi Pico W"}]}) in ctx.events
    r, _ = await et.run(ctx, state, "use_board", {"board_id": "teensy 4.1"})
    assert r["ok"] is False and "rpi-pico-w" in r["error"]
    bad = {**PICO, "components": [{"id": "usb", "type": "usb_c", "side": "top", "access": "port", "w": 9, "h": 3}]}
    r, _ = await et.run(ctx, state, "use_board", {"spec": json.dumps(bad), "name": "mine"})
    assert r["ok"] is False and "missing edge" in r["error"] and "mine" not in state.inputs["boards"]


async def test_a_new_board_rebuilds_the_case_that_reads_it(fresh_db, monkeypatch):
    pool(monkeypatch, CLEAN)
    ctx, state = FakeCtx("ru"), await case_state(fresh_db)
    built = []

    async def commit_build(ctx_, state_, source, params, summary, author="agent", markers=None):
        built.append((source, params, summary, state_.inputs["boards"]["board"]["id"]))
        state_.build_args = {"params": params, "inputs": state_.inputs}
        return {"ok": True, "version": state_.version}, ["p_case/renders/v2.png"]

    monkeypatch.setattr(tools, "commit_build", commit_build)
    r, images = await et.run(ctx, state, "use_board", {"board_id": "xiao-esp32c3"})
    assert built == [(et.EXAMPLE, {"wall": 2}, "плата: Seeed Studio XIAO ESP32C3", "xiao-esp32c3")]
    assert images == ["p_case/renders/v2.png"] and r["build"]["ok"] and r["build"]["enclosure"]["ok"] is True


async def test_scan_board_attaches_the_board_and_shows_its_boxes(fresh_db, monkeypatch):
    from formwright.vision import board as vb

    await fresh_db.insert("assets", {"id": "a1", "project_id": "p_case", "kind": "photo", "path": "p_case/a1.jpg", "width": 1600, "height": 678,
                                     "meta": {}, "created_at": 0})
    seen = {}

    async def scan(meter, asset, hint=None, name="board", *, model=None, refine=True):
        seen.update({"asset": asset["id"], "hint": hint, "name": name, "model": model})
        board = {**PICO, "id": "photo-rpi-pico-w", "source": {"kind": "photo+dataset", "dataset_id": "rpi-pico-w", "asset_id": "a1"}}
        sel = {"id": "s1", "asset_id": "a1", "role": "context", "name": "board", "mask_path": None, "data": {"kind": "board_scan", "boxes": []}}
        return {"board": board, "boxes": [], "calibration": {"method": "board_holes", "residual_mm": 0.0, "pin_rows": {"rows_x": [1.6, 19.4]}},
                "deltas": [{"part": "usb", "field": "at", "dataset": 10.5, "photo": 10.57, "delta": 0.07, "source": "sam", "uncertainty_mm": 0.16, "applied": False}],
                "warnings": [], "schema_errors": [], "identified": {"board_id": "rpi-pico-w", "marking": "Raspberry Pi Pico W", "confidence": 0.99},
                "selection": sel}

    monkeypatch.setattr(vb, "scan_board", scan)
    ctx, state = FakeCtx(), DesignState(pack="enclosure")
    r, _ = await et.run(ctx, state, "scan_board", {"asset_id": "a1", "hint": "my Pico W"})
    assert seen == {"asset": "a1", "hint": "my Pico W", "name": "board", "model": "muse-spark-1.3-contributor"}
    assert r["ok"] and state.inputs["boards"]["board"]["id"] == "photo-rpi-pico-w"
    assert r["calibration"]["method"] == "board_holes" and r["deltas"][0]["photo"] == 10.57 and r["identified"]["board_id"] == "rpi-pico-w"
    sel = next(d for t, d in ctx.events if t == "selection.added")
    assert sel["id"] == "s1" and sel["data"]["kind"] == "board_scan" and sel["mask_url"] is None
    mem = await fresh_db.one("SELECT * FROM memory WHERE kind = 'interface'")
    assert mem["body"]["source"] == "photo" and mem["body"]["values"]["board"] == "rpi-pico-w"
    r, _ = await et.run(ctx, state, "scan_board", {"asset_id": "nope"})
    assert r["ok"] is False


def test_the_case_program_and_the_model_facing_text():
    assert len(et.EXAMPLE.splitlines()) <= 30 and "lib.inputs.boards.board" in et.EXAMPLE and "E.parts(enc, { layout: p.layout, ghost: p.show_board })" in et.EXAMPLE
    src = et.enclosure_program("pcb", title="Carrier 'case'\n", mockup=True, wall=2.4, mount="auto")
    assert "lib.inputs.boards.pcb" in src and "value: 2.4" in src and "value: 'auto'" in src and "pcbPlate" in src
    assert '"title": "Carrier \'case\'\\n"' in src  # the title is a JSON string, whatever it holds
    # a board built into the program: its geometry only, used when the project has no inputs.boards.board
    own = et.enclosure_program(fallback={**PICO, "name": "Pico W */ evil()\n"})
    assert "const BOARD = {" in own and "|| BOARD" in own and '"verify"' not in own and '"src"' not in own
    assert "// Pico W  evil(), for a project" in own and "BOARD" not in et.EXAMPLE
    with pytest.raises(TypeError):
        et.enclosure_program(walls=3)
    with pytest.raises(ValueError):
        et.enclosure_program("board; evil()")
    with pytest.raises(ValueError):
        et.enclosure_program(mount="glue")
    for t in et.TOOLS:
        assert is_english(t["description"]) and t["name"] in et.NAMES
    assert is_english(et.PACK_TEXT) and is_english(et.CLASSIFY_HINT) and et.PACK_TEXT.startswith("# Pack: enclosures")
    assert [t["name"] for t in et.tools(photos=True)] == ["use_board", "scan_board", "check_enclosure"]
    assert [t["name"] for t in et.tools(photos=False)] == ["use_board", "check_enclosure"]


def test_how_the_case_mounts_and_sits_reaches_the_program_and_survives_a_rebuild():
    src = et.enclosure_program(mounting="stake", mount_edge="-y", min_height=30, stance="upright", form="round")
    assert "mounting: p.mounting, mountEdge: p.mount_edge, minHeight: p.min_height, stance: p.stance" in src
    assert et.case_options(src) == {**et.DEFAULTS, "mounting": "stake", "mount_edge": "-y", "min_height": 30.0, "stance": "upright", "form": "round"}
    # a program from before these options keeps what it has; nothing unknown comes back
    assert et.case_options(et.enclosure_program(form="box").replace("mounting:", "fixing:")).get("mounting") is None
    with pytest.raises(ValueError):
        et.enclosure_program(mounting="glue")


# ---------------------------------------------------------------- the real engine


@pytest.fixture
async def real_geom():
    old = geommod._pool
    geommod._pool = GeomPool(1)
    yield geommod._pool
    await geommod._pool.close()
    geommod._pool = old


async def test_the_case_example_passes_its_own_check(fresh_db, real_geom):
    state = await case_state(fresh_db, version=1)
    built = await real_geom.build(et.EXAMPLE, {}, analyze="full", inputs=state.inputs)
    assert built["checks"]["ok"] and [i["code"] for i in built["checks"]["issues"] if i["severity"] != "info"] == []
    state.params = built["params"]
    state.build_args = {"params": built["params"], "inputs": state.inputs}
    enc = await et.check(FakeCtx(), state)
    s = enc["summary"]
    assert enc["ok"] and s["usb_clearance_mm"] == pytest.approx(0.27, abs=0.05) and s["button_gap_mm"] == pytest.approx(0.3, abs=0.05)
    assert s["snap_strain_pct"] < 2 and enc["rays"] and all(r["port"] == "usb" for r in enc["rays"])
    assert {f["code"] for f in enc["findings"]} >= {"port_clear", "button_reach", "light_window", "lid_fit", "snap_strain", "keepout_ok"}


async def test_the_mockup_plate_prints_next_to_the_case(real_geom):
    carrier = json.loads((settings().geom_dir / "test" / "data" / "xiao_carrier.board.json").read_text(encoding="utf-8"))
    src = et.enclosure_program("pcb", title="XIAO carrier case", mockup=True)
    built = await real_geom.build(src, {}, analyze="full", inputs={"boards": {"pcb": carrier}})
    assert [p["name"] for p in built["parts"]] == ["base", "lid", "pcb_mockup"] and built["checks"]["ok"]
    assert max(built["checks"]["stats"]["size"][:2]) < 180  # fits an A1 mini bed, so the A1 too
    out = await real_geom.inspect(src, built["params"], [{"op": "enclosure", "board": "pcb"}], inputs={"boards": {"pcb": carrier}})
    enc = et.enclosure_checks(out["results"][0], "pcb", carrier, 1)
    assert enc["ok"] and set(enc["clearance"]) == {"J1", "U1_usb"} and enc["summary"]["usb_clearance_mm"] == pytest.approx(0.27, abs=0.05)


async def test_the_wall_advice_in_the_pack_text_is_what_the_kernel_builds(real_geom):
    # the designer picks the wall from PACK_TEXT: 1.2 prints clean, the hooks catch firmer from 1.3
    assert "0.28 mm at 1.3 and up, 0.20 mm at 1.2" in et.PACK_TEXT
    catches = {}
    for wall in (1.2, 1.3, 2.0):
        src = et.enclosure_program(wall=wall)
        built = await real_geom.build(src, {}, analyze="full", inputs={"boards": {"board": PICO}})
        assert built["checks"]["ok"] and not [i["code"] for i in built["checks"]["issues"] if i["severity"] == "error"]
        out = await real_geom.inspect(src, built["params"], [{"op": "enclosure", "board": "board"}], inputs={"boards": {"board": PICO}})
        lid = next(f["msg"] for f in out["results"][0]["findings"] if f["code"] == "lid_fit")
        catches[wall] = lid.rsplit("catch ", 1)[1]
    assert catches == {1.2: "0.20 mm", 1.3: "0.28 mm", 2.0: "0.28 mm"}
