"""scripts/curate_demo.py --feature: a run is featured only when its last finish was approved by the reviewer and its
latest version passes its checks (--force overrides those), and a PCB run only when its latest board, built again
offline in the PCB worker, has no DRC errors such as pcb_button_short_error (no --force for that). Scratch databases."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3

import pytest

from iamodelize3d import db as dbmod, pcb_store
from iamodelize3d.config import REPO_DIR, SERVER_DIR, settings

DIST = REPO_DIR / "packages" / "pcb" / "dist"
XIAO = (REPO_DIR / "packages" / "pcb" / "test" / "fixtures" / "xiao_carrier.tsx").read_text(encoding="utf-8")
# GND on SW1 pin2: routes clean, but pin1 and pin2 are one contact, so the button's GPIO is shorted to GND
SHORT = XIAO.replace(".SW1 > .pin3", ".SW1 > .pin2")
needs_bundle = pytest.mark.skipif(not (DIST / "pcb-worker.mjs").exists(), reason="run `npm ci --ignore-scripts && npm run bundle` in packages/pcb")

PASS = {"verdict": "pass", "match_score": 9.0, "issues": [], "reviewer": "primary"}
REVISE = {"verdict": "revise", "match_score": 4.0, "issues": [{"severity": "major", "text": "LED window missing on lid"}], "reviewer": "primary"}
GONE = {"verdict": "pass", "match_score": None, "issues": [], "note": "reviewer unavailable", "reviewer": "unavailable"}
CLEAN = {"ok": True, "issues": [], "stats": {"size": [40, 20, 10]}}


def _curate():
    spec = importlib.util.spec_from_file_location("curate_demo", SERVER_DIR / "scripts" / "curate_demo.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _finish(cid: str, critic: dict | None, result: dict) -> list[tuple[str, dict]]:
    """The events of one finish call as the loop writes them: the call, the review inside it, the step's result."""
    out = [("tool.call", {"id": cid, "name": "finish", "kind": "finish", "title": "Final check before handing over"})]
    if critic:
        out.append(("critic", critic))
    ok = result.get("ok", result.get("accepted", True)) is not False
    return out + [("tool.result", {"id": cid, "name": "finish", "kind": "finish", "ok": ok, "title": "Approved" if ok else "Not yet",
                                   "summary": json.dumps(result, ensure_ascii=False)[:600]})]


# id -> (pack, events, latest program checks, PCB source or None)
RUNS: dict[str, tuple[str, list, dict, str | None]] = {
    "p_ok": ("household", _finish("c1", {**PASS, "version": 1}, {"accepted": True}), CLEAN, None),
    # wave 4's tag at the front of the summary
    "p_notes": ("enclosure", _finish("c1", {**REVISE, "version": 1}, {"accepted": True, "review": "notes", "unresolved": ["LED window missing"]}),
                CLEAN, None),
    # older runs: no tag; the third finish kept the reviewer's majors as 'unresolved'
    "p_unresolved": ("enclosure", _finish("c3", {**REVISE, "version": 8, "report_only": True}, {"accepted": True, "unresolved": ["LED"]}),
                     CLEAN, None),
    # older runs: no tag and no list: the review inside the last finish decides, not the one of the finish before it
    "p_gone": ("household", _finish("c1", {**REVISE, "version": 1}, {"accepted": False, "reason": "the reviewer found major problems"})
               + _finish("c2", {**GONE, "version": 2}, {"accepted": True}), CLEAN, None),
    "p_revised": ("household", _finish("c1", None, {"accepted": False, "reason": "printability errors remain"})
                  + _finish("c2", {**REVISE, "version": 2, "note": "match 4/10 plateaued (was 4): accepted as it is"}, {"accepted": True}),
                  CLEAN, None),
    "p_rejected": ("household", _finish("c1", {**REVISE, "version": 1}, {"accepted": False, "reason": "the reviewer found major problems"}),
                   CLEAN, None),
    "p_nofinish": ("household", [], CLEAN, None),
    "p_thin": ("household", _finish("c1", {**PASS, "version": 1}, {"accepted": True}),
               {"ok": False, "issues": [{"severity": "error", "code": "thin_wall"}, {"severity": "warn", "code": "overhang"}]}, None),
    "p_case": ("enclosure", _finish("c1", {**PASS, "version": 1}, {"accepted": True}),
               {**CLEAN, "enclosure": {"ok": False, "findings": [{"code": "port_blocked", "severity": "error"}, {"code": "lid_fit", "severity": "info"}]}},
               None),
    # a device has no reviewer: its finish's self-check speaks instead
    "p_device_checked": ("device", [("device.self_check", {"passed": True, "kinds": ["mcu"], "checked": []})] + _finish("c1", None, {"accepted": True}), CLEAN, None),
    "p_device_unchecked": ("device", _finish("c1", None, {"accepted": True}), CLEAN, None),
    "p_pcb_clean": ("pcb", _finish("c1", {**PASS, "version": 1}, {"accepted": True}), CLEAN, XIAO),
    "p_pcb_short": ("pcb", _finish("c1", {**PASS, "version": 1}, {"accepted": True}), CLEAN, SHORT),
    "p_pcb_none": ("pcb", _finish("c1", None, {"accepted": True}), CLEAN, None),
}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir(exist_ok=True)

    async def make() -> None:
        await dbmod.close_db()
        db = await dbmod.get_db()
        await db.execute(pcb_store.SCHEMA)
        t = dbmod.now()
        await db.insert("users", {"id": "u1", "tier": "anon", "created_at": t})
        for i, (pid, (pack, events, checks, circuit)) in enumerate(RUNS.items()):
            await db.insert("projects", {"id": pid, "user_id": "u1", "title": pid, "pack": pack, "brief": {"language": "en"}, "version": 1,
                                         "cover": f"{pid}/renders/v1_iso.png", "created_at": t + i, "updated_at": t + i})
            await db.insert("jobs", {"id": f"j_{pid}", "project_id": pid, "user_id": "u1", "kind": "design", "status": "done",
                                     "input": {"text": "a part"}, "created_at": t, "finished_at": t + 60})
            await db.insert("programs", {"project_id": pid, "version": 1, "source": "return lib.std.box([10, 10, 10])", "checks": checks,
                                         "created_at": t})
            for type_, data in events:
                await db.insert("events", {"project_id": pid, "job_id": f"j_{pid}", "type": type_, "data": data, "ts": t})
            if circuit:
                await db.insert("pcb_boards", {"project_id": pid, "version": 1, "source": circuit, "checks": {"ok": True, "errors": []},
                                               "artifacts": {}, "created_at": t})
        await dbmod.close_db()

    asyncio.run(make())
    c = sqlite3.connect(tmp_path / "iamodelize3d.db")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture
def curate(monkeypatch):
    """The script, with the PCB rebuild stubbed: a circuit with the SW1 pin2 wiring fails as today's engine says."""
    mod = _curate()
    built: list[str] = []

    def rebuild(source, intent):
        built.append(source)
        if source == SHORT:
            return {"ok": False, "errors": [{"type": "pcb_button_short_error", "ref": "SW1", "message": "SW1 pin1 and pin2 are one contact "
                                             "inside the switch (legs 6.50 mm apart), so U1.D1 and GND are shorted together"}]}
        return {"ok": True, "errors": [], "warnings": []}

    monkeypatch.setattr(mod, "rebuild_board", rebuild)
    mod.built = built
    return mod


def _featured(conn) -> dict[str, int]:
    return {r["id"]: r["featured"] for r in conn.execute("SELECT id, featured FROM projects WHERE featured > 0")}


def test_the_last_finish_says_how_the_review_ended(conn, curate):
    states = {pid: curate.last_finish(conn, pid)[0] for pid in RUNS}
    assert states["p_ok"] == "approved" and states["p_pcb_clean"] == "approved"
    assert states["p_notes"] == "notes" and states["p_unresolved"] == "notes" and states["p_revised"] == "notes"
    assert states["p_gone"] == "none" and states["p_rejected"] == "rejected" and states["p_nofinish"] == "missing"
    # a board without a case ships without a review: nothing to hold against it
    assert states["p_pcb_none"] == "approved"
    assert "reviewer: revise 4/10 on version 8" in curate.last_finish(conn, "p_unresolved")[1]
    assert curate.latest_checks(conn, "p_ok") is None
    assert curate.latest_checks(conn, "p_thin") == "its latest version v1 fails the printability checks (thin_wall)"
    assert curate.latest_checks(conn, "p_case") == "the case of v1 does not pass its board check (port_blocked)"


def test_an_approved_run_is_featured(conn, curate, capsys):
    curate.feature(conn, ["p_ok"], apply=True)
    assert _featured(conn) == {"p_ok": 1} and "set public=1 featured=1  p_ok" in capsys.readouterr().out
    assert curate.built == []  # no PCB rebuild for a run without boards


@pytest.mark.parametrize("pid,why", [
    ("p_notes", "handed over with the reviewer's notes still open (reviewer: revise 4/10 on version 1)"),
    ("p_unresolved", "handed over with the reviewer's notes still open"),
    ("p_gone", "handed over without a review: the reviewer did not answer"),
    ("p_revised", "handed over with the reviewer's notes still open (reviewer: revise 4/10 on version 2)"),
    ("p_rejected", "its last finish was turned down: Not yet"),
    ("p_nofinish", "no finish step"),
    ("p_thin", "fails the printability checks (thin_wall)"),
    ("p_case", "does not pass its board check (port_blocked)"),
])
def test_a_run_the_reviewer_did_not_approve_is_refused_unless_forced(conn, curate, capsys, pid, why):
    with pytest.raises(SystemExit) as e:
        curate.feature(conn, ["p_ok", pid], apply=True)
    out = capsys.readouterr().out
    assert f"refused  {pid}  " in out and why in out and "refused  p_ok" not in out
    assert "nothing changed" in str(e.value) and "--force" in str(e.value)
    # nothing is written, not even for the run that passed
    assert _featured(conn) == {}
    curate.feature(conn, [pid], apply=True, force=True)
    assert f"forced  {pid}  " in capsys.readouterr().out and _featured(conn) == {pid: 1}


def test_a_dry_run_says_the_same_and_writes_nothing(conn, curate, capsys):
    with pytest.raises(SystemExit):
        curate.feature(conn, ["p_notes"], apply=False)
    assert "refused  p_notes" in capsys.readouterr().out
    curate.feature(conn, ["p_ok"], apply=False)
    assert "would set public=1 featured=1  p_ok" in capsys.readouterr().out and _featured(conn) == {}


def test_a_board_with_drc_errors_today_is_refused_even_with_force(conn, curate, capsys):
    curate.feature(conn, ["p_pcb_clean"], apply=True)
    assert _featured(conn) == {"p_pcb_clean": 1} and curate.built == [XIAO]
    assert "PCB v1: 0 DRC errors today" in capsys.readouterr().out
    for force in (False, True):
        with pytest.raises(SystemExit):
            curate.feature(conn, ["p_pcb_short"], apply=True, force=force)
        out = capsys.readouterr().out
        # the stored checks said 0 errors when it was made; the engine of today finds the short
        assert ("refused  p_pcb_short  its latest board, PCB v1, has 1 DRC error(s) with today's engine; it stored 0 when it was made: "
                "pcb_button_short_error SW1: SW1 pin1 and pin2 are one contact") in out
    assert _featured(conn) == {"p_pcb_clean": 1}
    # a PCB run without a board, and a board that cannot be rebuilt here (--force lifts only the latter)
    with pytest.raises(SystemExit):
        curate.feature(conn, ["p_pcb_none"], apply=True, force=True)
    assert "refused  p_pcb_none  it has no PCB version" in capsys.readouterr().out

    def broken(source, intent):
        raise RuntimeError("no node here")

    curate.rebuild_board = broken
    with pytest.raises(SystemExit):
        curate.feature(conn, ["p_pcb_short"], apply=True)
    assert "could not be rebuilt here (RuntimeError: no node here)" in capsys.readouterr().out
    curate.feature(conn, ["p_pcb_short"], apply=True, force=True)
    assert _featured(conn)["p_pcb_short"] == 2


@needs_bundle
def test_the_rebuild_runs_the_real_pcb_worker_offline(conn, capsys):
    curate = _curate()
    assert curate.rebuild_board(XIAO, None)["errors"] == []
    errors = curate.rebuild_board(SHORT, None)["errors"]
    assert any(e["type"] == "pcb_button_short_error" and e.get("ref") == "SW1" for e in errors)
    with pytest.raises(SystemExit):
        curate.feature(conn, ["p_pcb_short"], apply=True, force=True)
    assert "pcb_button_short_error SW1" in capsys.readouterr().out and _featured(conn) == {}


def test_a_finish_that_ran_no_review_keeps_the_versions_open_notes(conn, curate, capsys):
    """A follow-up run that built nothing and called finish: no review ran inside it, so the latest version's own
    review (revise 4/10) decides, not the quiet finish."""
    t = dbmod.now()
    for type_, data in _finish("c9", None, {"accepted": True}):
        conn.execute("INSERT INTO events (project_id, job_id, type, data, ts) VALUES ('p_notes', 'j_p_notes', ?, ?, ?)", (type_, json.dumps(data), t))
    state, why = curate.last_finish(conn, "p_notes")
    assert state == "notes" and "revise 4/10 on version 1" in why
    with pytest.raises(SystemExit):
        curate.feature(conn, ["p_notes"], apply=True)
    assert "refused  p_notes" in capsys.readouterr().out and _featured(conn) == {}
    # the same quiet finish on a run whose latest version was never reviewed
    for type_, data in _finish("c9", None, {"accepted": True}):
        conn.execute("INSERT INTO events (project_id, job_id, type, data, ts) VALUES ('p_ok', 'j_p_ok', ?, ?, ?)", (type_, json.dumps(data), t))
    conn.execute("INSERT INTO programs (project_id, version, source, checks, created_at) VALUES ('p_ok', 2, 'x', ?, ?)", (json.dumps(CLEAN), t))
    assert curate.last_finish(conn, "p_ok")[0] == "none"


def test_a_board_todays_engine_cannot_build_is_refused_even_with_force(conn, curate, capsys):
    from iamodelize3d.pcb import PcbError

    def rejects(source, intent):
        raise PcbError("compile", "Unexpected token (2:5)")

    curate.rebuild_board = rejects
    with pytest.raises(SystemExit):
        curate.feature(conn, ["p_pcb_clean"], apply=True, force=True)
    out = capsys.readouterr().out
    assert "refused  p_pcb_clean  its PCB v1 does not build with today's engine: compile: Unexpected token" in out and _featured(conn) == {}

    def slow(source, intent):
        raise PcbError("timeout", "no answer in 120 s")

    curate.rebuild_board = slow  # the worker, not the circuit: --force may still lift it
    curate.feature(conn, ["p_pcb_clean"], apply=True, force=True)
    assert "forced  p_pcb_clean  its PCB v1 could not be rebuilt here (PcbError: timeout" in capsys.readouterr().out


def test_a_device_passes_on_its_self_check_alone(tmp_path):
    curate = _curate()
    conn = sqlite3.connect(tmp_path / "d.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE projects (id TEXT, pack TEXT)")
    conn.execute("CREATE TABLE programs (project_id TEXT, version INTEGER)")
    conn.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY, project_id TEXT, type TEXT, data TEXT)")
    for pid in ("p_device_checked", "p_device_unchecked"):
        conn.execute("INSERT INTO projects VALUES (?, 'device')", (pid,))
        for typ, data in RUNS[pid][1]:
            conn.execute("INSERT INTO events (project_id, type, data) VALUES (?, ?, ?)", (pid, typ, json.dumps(data)))
    assert curate.last_finish(conn, "p_device_checked")[0] == "approved"
    assert curate.last_finish(conn, "p_device_unchecked")[0] == "none"


def test_a_run_is_taken_down_from_the_server_and_put_back(tmp_path):
    curate = _curate()
    conn = sqlite3.connect(tmp_path / "d.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE projects (id TEXT, title TEXT, public INT, listed INT, featured INT, hidden INT)")
    conn.execute("INSERT INTO projects VALUES ('p1', 't', 1, 1, 2, 0)")
    curate.take_down(conn, ["p1"], apply=False)
    assert conn.execute("SELECT hidden FROM projects").fetchone()[0] == 0
    curate.take_down(conn, ["p1"], apply=True)
    assert tuple(conn.execute("SELECT public, listed, featured, hidden FROM projects").fetchone()) == (0, 0, 0, 1)
    curate.take_down(conn, ["p1"], apply=True, hidden=False)
    assert tuple(conn.execute("SELECT public, hidden FROM projects").fetchone()) == (0, 0)
