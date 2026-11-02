"""Agent-facing details: tolerant program edits, English-only prompts, supports as a normal way to print,
the finish gate and its reviewer, builds that reuse the engine's kept build."""
import base64
from types import SimpleNamespace

import pytest

from formwright import db as dbmod
from formwright.agent import critic, tools
from formwright.agent.prompts import CRITIC
from formwright.agent.tools import DesignState, _apply_edits, _finish
from formwright.config import settings
from formwright.geom import GeomError
from formwright.llm.client import CostMeter
from formwright.llm.english import is_english
from formwright.memory import store as memory
from formwright.printing.profile import features, rule_diff

OPEN = "meta-models/muse-spark-open-1026"

PROGRAM = """function build(p, lib) {
  const { std } = lib;
  const body = std.box([p.w, p.d, p.h]);
  return body.subtract(std.holeZ(5, p.h, { at: [0, 0, p.h] }));
}"""


def test_edit_applies_exact_and_reindented_snippets():
    out, errors = _apply_edits(PROGRAM, [{"find": "std.box([p.w, p.d, p.h])", "replace": "std.box([p.w, p.d, p.h], { r: 2 })"}])
    assert not errors and "{ r: 2 }" in out
    # the model copied the line with other indentation and spacing
    out, errors = _apply_edits(PROGRAM, [{"find": "const body =   std.box([p.w, p.d, p.h]);\n    return body", "replace": "return std.box([1, 1, 1])"}])
    assert not errors and "return std.box([1, 1, 1])" in out and "const body" not in out


def test_edit_that_misses_points_at_the_closest_line():
    out, errors = _apply_edits(PROGRAM, [{"find": "const body = std.box([p.w, p.depth, p.h]);", "replace": "x"}])
    assert out == PROGRAM
    assert "not found" in errors[0] and "const body = std.box([p.w, p.d, p.h]);" in errors[0]
    _, errors = _apply_edits(PROGRAM + "\n// p.h\n", [{"find": "p.h", "replace": "p.height"}])
    assert "ambiguous" in errors[0]


def test_english_detection():
    assert is_english("white plastic clip, 32 mm ±0.2")
    assert not is_english("белая пластиковая клипса")
    assert not is_english("clip for Ø32 шланг")


def test_overhangs_turn_supports_on():
    checks = {"issues": [{"code": "overhang", "severity": "warn", "message": "overhang", "z": [12.0, 30.0], "value": 240}],
              "stats": {"size": [40, 40, 50], "firstLayerArea": 900.0}}
    d = {x["key"]: x for x in rule_diff({"process": {"enable_support": "0"}, "filament": {}}, features(checks, None, {}), {})}
    assert d["enable_support"]["to"] == "1" and d["support_type"]["to"] == "tree(auto)"
    assert not d["enable_support"]["required"]  # a refining model may still drop it with evidence


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def test_lessons_are_english_and_never_about_supports(fresh_db):
    for _ in range(3):
        await memory.observe_fix("floating_island", "a keel under the tail", "collect", "j1")
        await memory.observe_fix("too_thin", "Утолщил лапы до 1.2 мм", "collect", "j1")
        await memory.observe_fix("thin_wall", "walls to 1.68 mm", "collect", "j1")
    rows = await fresh_db.all("SELECT name, status FROM memory WHERE kind = 'lesson'")
    assert {r["name"]: r["status"] for r in rows} == {"thin_wall:collect": "active"}
    recalled = await memory.recall("u1", "thin_wall collect figure", "collect")
    assert [m["name"] for m in recalled["lesson"]] == ["thin_wall:collect"]


# ---------------------------------------------------------------- finish gate


class FakeCtx:
    """The parts of a JobContext the tools touch, with every event kept in order."""

    def __init__(self, project_id: str = "p_test", language: str | None = None):
        self.project = {"id": project_id, "title": "Test part", "brief": {"language": language} if language else {}}
        self.project_id = project_id
        self.user = {"id": "u_test"}
        self.job_id = "j_test"
        self.meter = CostMeter()
        self.models = SimpleNamespace(designer="muse-spark-1.3", fast="muse-spark-1.3-contributor")
        self.events: list[tuple[str, dict]] = []

    async def emit(self, type_: str, data: dict | None = None) -> None:
        self.events.append((type_, data or {}))

    async def status(self, text: str) -> None:
        self.events.append(("agent.status", {"text": text}))

    def check_cancelled(self) -> None:
        pass


def built_state(pack: str, version: int = 3) -> DesignState:
    return DesignState(pack=pack, source="return {}", version=version, last_build={"checks": {"issues": []}}, last_render=f"p_test/renders/v{version}.png")


def stub_review(monkeypatch, verdicts: list[dict]):
    calls = []

    async def review(ctx, state, *, bar=None):
        calls.append({"version": state.version, "bar": bar})
        return dict(verdicts.pop(0))

    monkeypatch.setattr(critic, "review", review)
    return calls


def critic_events(ctx: FakeCtx) -> list[dict]:
    return [d for t, d in ctx.events if t == "critic"]


async def test_finish_passes_a_good_review_and_tags_it(monkeypatch):
    calls = stub_review(monkeypatch, [{"verdict": "pass", "match_score": 9, "issues": [], "model": OPEN, "reviewer": "primary"}])
    ctx, state = FakeCtx(), built_state("household")
    assert await _finish(ctx, state, "done") == {"accepted": True}
    assert state.done and state.summary == "done" and calls == [{"version": 3, "bar": None}]
    # the status first, then exactly one critic event carrying the decision
    assert [t for t, _ in ctx.events] == ["agent.status", "critic"]
    ev = critic_events(ctx)[0]
    assert ev["verdict"] == "pass" and ev["version"] == 3 and ev["model"] == OPEN and ev["reviewer"] == "primary"
    assert ev["blocking"] is False and ev["forced_by"] is None and ev["render"] == "/files/p_test/renders/v3.png"
    assert state.critic["version"] == 3


async def test_a_copy_below_the_bar_is_revised_before_it_is_shown_then_a_plateau_ships(monkeypatch):
    minor = [{"severity": "minor", "text": "ears a bit short", "text_user": "ears a bit short", "fix_hint": "+2 mm"}]
    calls = stub_review(monkeypatch, [{"verdict": "pass", "match_score": 7.5, "issues": minor, "model": OPEN, "reviewer": "primary"},
                                      {"verdict": "pass", "match_score": 7.7, "issues": minor, "model": OPEN, "reviewer": "primary"}])
    ctx, state = FakeCtx(), built_state("collect")
    r = await _finish(ctx, state, "first try")
    assert r["accepted"] is False and r["match_score"] == 7.5 and "7.5/10" in r["issues"][0]["text"]
    assert calls[0]["bar"] == 8.0  # the reviewer is told the bar
    ev = critic_events(ctx)[0]
    # never 'pass' on screen for a version the gate sends back
    assert ev["verdict"] == "revise" and ev["blocking"] is True and ev["forced_by"] == "match_score<8" and ev["version"] == 3
    assert not state.done and state.critic_scores == [7.5]

    state.version = 4
    r = await _finish(ctx, state, "second try")
    assert r["accepted"] is True and "plateau" in r["note"]
    ev = critic_events(ctx)[1]
    assert ev["version"] == 4 and ev["blocking"] is False and ev["verdict"] == "revise" and "plateaued" in ev["note"]
    assert state.done and state.critic["version"] == 4


async def test_a_real_improvement_gets_another_round(monkeypatch):
    stub_review(monkeypatch, [{"verdict": "pass", "match_score": 6, "issues": []}, {"verdict": "pass", "match_score": 7, "issues": []}])
    ctx, state = FakeCtx(), built_state("copy")
    assert (await _finish(ctx, state, ""))["accepted"] is False
    state.version = 4
    assert (await _finish(ctx, state, ""))["accepted"] is False
    assert state.critic_scores == [6.0, 7.0]


async def test_the_third_finish_is_reviewed_but_only_reports(monkeypatch):
    major = {"verdict": "revise", "match_score": 3, "model": "muse-spark-1.3-contributor", "reviewer": "fallback",
             "issues": [{"severity": "major", "text": "pose does not match", "text_user": "the pose is different", "fix_hint": "turn the head"}]}
    calls = stub_review(monkeypatch, [major, major, major])
    ctx, state = FakeCtx(), built_state("stylize")
    for v in (3, 4):
        state.version = v
        r = await _finish(ctx, state, "")
        assert r == {"accepted": False, "reason": "the reviewer found major problems", "issues": major["issues"]}
    state.version = 5
    r = await _finish(ctx, state, "shipped")
    assert r["accepted"] is True and r["unresolved"] == ["pose does not match"]
    assert [c["version"] for c in calls] == [3, 4, 5]
    ev = critic_events(ctx)[-1]
    assert ev["version"] == 5 and ev["report_only"] is True and ev["blocking"] is False and ev["reviewer"] == "fallback"
    assert state.done and state.critic["version"] == 5  # what ships is what was reviewed


async def test_finish_without_a_reviewer_still_ships_and_says_so(monkeypatch):
    stub_review(monkeypatch, [{"reviewer": "unavailable"}])
    ctx, state = FakeCtx(), built_state("household")
    assert (await _finish(ctx, state, ""))["accepted"] is True
    ev = critic_events(ctx)[0]
    assert ev["verdict"] == "pass" and ev["note"] == "reviewer unavailable" and ev["reviewer"] == "unavailable" and ev["version"] == 3


async def test_the_case_gate_runs_after_printability_and_before_the_review(monkeypatch):
    from formwright.agent import elec_tools

    calls = stub_review(monkeypatch, [{"verdict": "pass", "match_score": 9, "issues": []}])
    gate = [["port_blocked (usb): the plug hits the case -> raise port_fit"], []]

    async def finish_gate(ctx, state):
        return gate.pop(0)

    monkeypatch.setattr(elec_tools, "finish_gate", finish_gate)
    ctx, state = FakeCtx(), built_state("enclosure")
    r = await _finish(ctx, state, "")
    assert r == {"accepted": False, "reason": "the case check found errors", "issues": ["port_blocked (usb): the plug hits the case -> raise port_fit"]}
    assert not calls and not critic_events(ctx)
    assert (await _finish(ctx, state, "case"))["accepted"] is True and len(calls) == 1
    # other packs have no gate
    assert tools.pack_gate("household") is None and tools.pack_gate("pcb")[1] == "the board is not ready"


async def test_a_case_build_is_checked_against_its_board_at_once(fresh_db, monkeypatch):
    from formwright.agent import elec_tools

    checked = []

    async def after_build(ctx, state, result):
        checked.append(state.version)
        result["enclosure"] = {"ok": True}

    monkeypatch.setattr(tools, "geom", lambda: FakeGeom())
    monkeypatch.setattr(elec_tools, "after_build", after_build)
    ctx = FakeCtx()
    r, _ = await tools.run_tool(ctx, DesignState(pack="enclosure"), "write_program", {"source": "return {}", "summary": "case"})
    assert r["enclosure"] == {"ok": True} and checked == [1]
    r, _ = await tools.run_tool(ctx, DesignState(pack="household"), "write_program", {"source": "return {}", "summary": "hook"})
    assert "enclosure" not in r and checked == [1]


async def test_printability_errors_block_before_any_review(monkeypatch):
    calls = stub_review(monkeypatch, [])
    ctx, state = FakeCtx(), built_state("household")
    state.last_build = {"checks": {"issues": [{"severity": "error", "code": "non_manifold", "message": "open edges", "hints": []}]}}
    r = await _finish(ctx, state, "")
    assert r["accepted"] is False and r["reason"] == "printability errors remain" and not calls and not critic_events(ctx)


# ---------------------------------------------------------------- critic


async def test_critic_falls_back_to_the_fast_model_and_names_it(fresh_db, monkeypatch):
    used = []

    class Meta:
        def model_for(self, role, default):
            return OPEN if role == "critic" else default

        async def json(self, meter, *, model, content, fallback=True, **kw):
            used.append((model, fallback))
            if model == OPEN:
                raise RuntimeError("endpoint is cold")
            return {"verdict": "pass", "match_score": 9, "issues": []}

    monkeypatch.setattr(critic, "meta", lambda: Meta())
    ctx, state = FakeCtx(language="ru"), DesignState(pack="household", version=2)
    v = await critic.review(ctx, state)
    assert used == [(OPEN, False), ("muse-spark-1.3-contributor", True)]
    assert v["model"] == "muse-spark-1.3-contributor" and v["reviewer"] == "fallback" and v["version"] == 2

    used.clear()
    state.critic = {"version": 1, "issues": [{"severity": "major", "text": "hook too short"}]}

    async def ok(self, meter, *, model, content, fallback=True, **kw):
        used.append(content[0]["text"])
        return {"verdict": "pass", "match_score": 9, "issues": []}

    monkeypatch.setattr(Meta, "json", ok)
    v = await critic.review(ctx, state, bar=8)
    assert v["model"] == OPEN and v["reviewer"] == "primary"
    text = used[0]
    assert "Request language: ru" in text and "match_score >= 8" in text and "earlier review of v1 found: 1. [major] hook too short" in text
    assert is_english(text)


def test_critic_issues_carry_text_for_the_person():
    item = critic.SCHEMA["properties"]["issues"]["items"]
    assert "text_user" in item["properties"] and "text_user" in item["required"]
    assert "text_user" in CRITIC and is_english(CRITIC)


# ---------------------------------------------------------------- builds


class FakeGeom:
    def __init__(self, fail: list[str] | None = None):
        self.fail = list(fail or [])
        self.calls: list[tuple[str, dict, dict]] = []

    async def build(self, source, params=None, **extra):
        self.calls.append(("build", params, extra))
        if self.fail:
            raise GeomError(self.fail.pop(0), "worker exited")
        return {"params": {"w": 10, "h": 5}, "paramSpecs": {}, "parts": [], "checks": {"issues": [], "stats": {"size": [10, 10, 5]}}}

    async def render(self, source, params=None, **extra):
        self.calls.append(("render", params, extra))
        return {"png": base64.b64encode(b"png").decode()}

    async def inspect(self, source, params=None, ops=None, **extra):
        self.calls.append(("inspect", params, extra))
        return {"results": []}


async def test_renders_reuse_the_build_and_an_engine_crash_is_retried_silently(fresh_db, monkeypatch):
    fake = FakeGeom(fail=["crash"])
    monkeypatch.setattr(tools, "geom", lambda: fake)
    ctx, state = FakeCtx(), DesignState(pack="household", inputs={"outlines": {}})
    result, images = await tools.commit_build(ctx, state, "return {}", {}, "first")
    assert result["ok"] is True and result["version"] == 1 and images == ["p_test/renders/v1.png"]
    # the crash was retried without a word to the model or the timeline
    assert [c[0] for c in fake.calls] == ["build", "build", "render", "render"]
    assert not any(t == "tool.result" for t, _ in ctx.events)
    # the same params dict and inputs as the build, so the engine's kept build is hit
    inputs = fake.calls[0][2]["inputs"]
    assert all(c[1] == {} and c[2]["inputs"] == inputs for c in fake.calls)
    assert state.params == {"w": 10, "h": 5} and state.build_args["params"] == {}
    await tools.run_tool(ctx, state, "inspect_model", {"ops": [{"op": "parts"}]})
    assert fake.calls[-1][0] == "inspect" and fake.calls[-1][1] == {} and fake.calls[-1][2]["inputs"] == inputs


async def test_a_stop_while_learning_a_lesson_never_hides_the_saved_version(fresh_db, monkeypatch):
    """The lesson after a fix needs a model call (the translation); the version is out before it starts."""
    import asyncio

    started, release, learned = asyncio.Event(), asyncio.Event(), []

    async def english(meter, text, model):
        started.set()
        await release.wait()  # a slow model call; the job may be stopped meanwhile
        return "thicker walls"

    async def observe_fix(code, fix, pack, job_id):
        learned.append((code, fix, pack))

    monkeypatch.setattr(tools, "geom", lambda: FakeGeom())
    monkeypatch.setattr(tools, "english", english)
    monkeypatch.setattr(tools.memory, "observe_fix", observe_fix)
    ctx, state = FakeCtx(), DesignState(pack="household", issue_codes={"thin_wall"})
    result, _ = await asyncio.wait_for(tools.commit_build(ctx, state, "return {}", {}, "стенки толще"), 5)
    # the build returned at once: the version is announced and kept in the state while the lesson is still pending
    assert result["ok"] and state.version == 1 and state.last_build is not None and state.issue_codes == set()
    assert [t for t, _ in ctx.events] == ["program.updated"] and ctx.events[0][1]["version"] == 1
    await asyncio.wait_for(started.wait(), 5)
    task = next(iter(tools._tasks))
    task.cancel()  # a Stop that takes the lesson down with it costs only the lesson
    with pytest.raises(asyncio.CancelledError):
        await task
    assert learned == [] and (await fresh_db.one("SELECT version FROM programs WHERE project_id = 'p_test'"))["version"] == 1

    # left alone, the lesson is learned in English
    release.set()
    state.issue_codes = {"thin_wall"}
    await tools.commit_build(ctx, state, "return {}", {}, "стенки толще")
    await asyncio.gather(*list(tools._tasks))
    assert learned == [("thin_wall", "thicker walls", "household")] and not tools._tasks


async def test_an_engine_that_fails_twice_is_not_blamed_on_the_program(fresh_db, monkeypatch):
    monkeypatch.setattr(tools, "geom", lambda: FakeGeom(fail=["protocol", "protocol"]))
    ctx, state = FakeCtx(), DesignState(pack="household")
    result, _ = await tools.commit_build(ctx, state, "return {}", {}, "")
    assert result["ok"] is False and result["infra"] is True and "not the problem" in result["error"]
    monkeypatch.setattr(tools, "geom", lambda: FakeGeom(fail=["runtime"]))
    result, _ = await tools.commit_build(ctx, state, "return {}", {}, "")
    assert result["ok"] is False and "infra" not in result and result["hint"].startswith("fix the program")


async def test_dimensions_search_the_web_when_the_tables_only_half_answer(monkeypatch):
    searched = []

    async def search(meter, query, user_id=None, model=None, force_web=False):
        searched.append((query, force_web))
        return {"facts": [], "from_cache": False}

    monkeypatch.setattr(tools.knowledge, "search_dimensions", search)
    ctx, state = FakeCtx(), DesignState(pack="household")
    out, _ = await tools.run_tool(ctx, state, "dimensions", {"query": "M3 screw"})
    assert out["standards"] and not searched
    out, _ = await tools.run_tool(ctx, state, "dimensions", {"query": "VESA"})
    assert out["standards"] and {h["match"] for h in out["standards"]} == {"partial"} and searched == [("VESA", False)]
    await tools.run_tool(ctx, state, "dimensions", {"query": "M3 screw", "web": True})
    assert searched[-1] == ("M3 screw", True)


async def test_likeness_panels_reuse_the_build(fresh_db, monkeypatch):
    from formwright.agent import compare

    fake = FakeGeom()
    seen = []

    async def targets(project_id):
        return [({"id": "a_photo"}, {"id": "s1"})]

    async def panel(project_id, state, asset, sel, elevation=15.0, azimuth=0.0, *, printer=None, inputs=None):
        seen.append({"params": state.params, "printer": printer, "inputs": inputs})
        return {"photo": asset["id"], "silhouette_iou": 0.8}, "p_test/renders/v1_compare.jpg"

    monkeypatch.setattr(tools, "geom", lambda: fake)
    monkeypatch.setattr(compare, "targets", targets)
    monkeypatch.setattr(compare, "panel", panel)
    ctx, state = FakeCtx(), DesignState(pack="copy", copies_photo=True, printer={"nozzle": 0.4})
    result, images = await tools.commit_build(ctx, state, "return {}", {}, "first")
    build = fake.calls[0]
    assert result["likeness"] == [{"photo": "a_photo", "silhouette_iou": 0.8}] and images[-1] == "p_test/renders/v1_compare.jpg"
    assert seen == [{"params": build[1], "printer": build[2]["printer"], "inputs": build[2]["inputs"]}]
    assert state.params == {"w": 10, "h": 5}  # the state keeps the resolved values
