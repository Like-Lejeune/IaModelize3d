"""The electronics steps read like work in the timeline, in English and Russian: the board scan, the board from the
dataset, the case checked against the board, the PCB with its DRC count, the fab files and the case made from it.
Results are built with the tools' own brief() functions from the shapes the real engines stored."""
import copy
import re

from formwright.agent import elec_tools as et, loop, narrate as n, pcb_tools as pt
from formwright.models import SendMessage

from test_loop_handover import FakeMeta, _events, _project, _use, call, fresh_db, offline, say  # noqa: F401 (fixtures)

ELEC = ("scan_board", "use_board", "check_enclosure", "write_circuit", "check_pcb", "export_fab", "make_enclosure")

# checks.enclosure of the Pico W case card as the geometry engine wrote it (findings trimmed to the ones the titles read)
PICO_CHECK = {
    "op": "enclosure", "board": "board", "rays": [], "clearance": {"usb": 0.268}, "ms": 900,
    "findings": [
        {"severity": "info", "code": "port_clear", "part": "usb", "value": 0.268, "unit": "mm", "msg": "usb: a 10.6x7.6 mm plug reaches the connector"},
        {"severity": "info", "code": "button_reach", "part": "bootsel", "value": 0.3, "unit": "mm", "msg": "bootsel: plunger 0.30 mm above the button"},
        {"severity": "info", "code": "snap_strain", "part": "lid", "value": 1.67, "unit": "%", "msg": "snap hooks bend 1.67 % going in"},
    ],
}
# a PCB version's stored checks (pcb-agent's live XIAO carrier run)
PCB_CHECKS = {
    "ok": True, "errors": [], "suppressed": 0, "warnings": [{"type": "source_pin_missing_trace_warning", "message": "Port pin3 on SW1 is missing a trace"}],
    "counts": {"components": 11, "nets": 11, "connections": 25, "traces": 23, "vias": 13},
    "intent": {"ok": True, "issues": [], "checked": 6}, "limits": {"ok": True, "issues": []},
    "fab": {"layers": ["board-NPTH.DRL", "board.DRL", "board.GBL", "board.GBO", "board.GBP", "board.GBS", "board.GKO", "board.GTL", "board.GTO",
                       "board.GTP", "board.GTS"], "bom_lines": 9, "cpl_lines": 11},
}
CARRIER = {"name": "XIAO ESP32-C3 carrier", "pcb": {"outline": {"w": 44, "h": 36}},
           "components": [{"id": "J1", "type": "usb_c", "access": "port", "edge": "-y"}]}
ALL_FILES = set(pt.FAB + pt.PREVIEWS)


def pico() -> dict:
    return et.dataset_board("rpi-pico-w")


def case(findings: list | None = None, version: int = 2) -> dict:
    res = copy.deepcopy(PICO_CHECK)
    res["findings"] += findings or []
    return et.brief(et.enclosure_checks(res, "board", pico(), version))


BLOCKED = [{"severity": "error", "code": "port_blocked", "part": "usb", "value": 0, "unit": "mm", "msg": "usb: the plug path is blocked"},
           {"severity": "error", "code": "lid_fit", "part": "lid", "value": 3.2, "unit": "mm3", "msg": "lid overlaps the base"}]


def test_every_electronics_tool_has_a_kind_and_a_stage():
    for name in ELEC:
        kind = n.KIND[name]
        assert kind != "other" and kind in n.STAGE, name
    assert [n.STAGE[n.KIND[t]] for t in ("scan_board", "use_board", "write_circuit", "make_enclosure", "check_enclosure", "check_pcb")] == [
        "measure", "measure", "design", "design", "check", "check"]


def test_the_board_scan_names_the_board_and_its_scale():
    scan = {"ok": True, "input": "inputs.boards.board", "board": et.board_brief({**pico(), "source": {"kind": "photo+dataset"}}),
            "identified": {"board_id": "rpi-pico-w", "confidence": 0.93}, "calibration": {"method": "board_holes", "uncertainty_mm": 0.04}, "deltas": []}
    assert n.call_title("scan_board", {"asset_id": "a_1", "hint": "Pico W"}) == "Scanning the board on the photo: Pico W"
    assert n.result_title("scan_board", {}, scan) == "Board read: Raspberry Pi Pico W, scale from its holes ±0.04 mm"
    unknown = {"ok": True, "board": {"name": "board", "source": "photo", "size_mm": [30.2, 20.1, 1.6]},
               "calibration": {"method": "a4", "uncertainty_mm": 0.31}, "build": {"ok": True, "version": 3}}
    assert n.result_title("scan_board", {}, unknown) == "Board measured: 30.2 × 20.1 mm, scale from the A4 sheet ±0.31 mm; case updated: v3"
    # a scan that could not measure stays a plain problem
    assert n.result_title("scan_board", {}, {"ok": False, "error": "unknown asset id"}) == "Problem: unknown asset id"


def test_a_board_from_the_dataset_or_its_own_numbers():
    assert n.call_title("use_board", {"board_id": "rpi-pico-w"}) == "Taking the board from the dataset: rpi-pico-w"
    assert n.call_title("use_board", {"spec": {"name": "My board"}}) == "Attaching the board from its own numbers: My board"
    assert n.call_title("use_board", {"spec": '{"name": "x"}'}) == "Attaching the board from its own numbers"
    out = {"ok": True, "input": "inputs.boards.board", "board": et.board_brief(pico()), "next": "write the case program"}
    assert n.result_title("use_board", {"board_id": "rpi-pico-w"}, out) == "Board from the dataset: Raspberry Pi Pico W, 21 × 51 mm"
    assert n.result_title("use_board", {"spec": {"name": "x"}}, {**out, "board": {**out["board"], "name": "My board"}}).startswith(
        "Board from its own numbers: My board")


def test_the_case_check_reads_its_numbers_and_its_problems():
    assert n.call_title("check_enclosure", {}) == "Checking the case against the board"
    assert n.result_title("check_enclosure", {}, case()) == "Raspberry Pi Pico W fits — USB 0.27 mm, all buttons reach, snaps 1.7 %"
    unnamed = {k: v for k, v in case().items() if k != "board_name"}  # a board JSON without a name
    assert n.result_title("check_enclosure", {}, unnamed) == "The board fits — USB 0.27 mm, all buttons reach, snaps 1.7 %"
    bad = case(BLOCKED)
    assert bad["ok"] is False
    assert n.result_title("check_enclosure", {}, bad) == "Raspberry Pi Pico W does not fit yet — USB plug blocked, the lid does not fit"
    many = case(BLOCKED + [{"severity": "error", "code": "board_collision", "part": "pcb", "value": 1.2, "msg": "x"},
                           {"severity": "error", "code": "snap_strain", "part": "lid", "value": 5.23, "unit": "%", "msg": "x"}])
    assert n.result_title("check_enclosure", {}, many).endswith("USB plug blocked, the lid does not fit, +2 more")
    # a side button pressable only with the lid off is said as such, not 'all buttons reach'
    side = case([{"severity": "warn", "code": "button_unreachable", "part": "btn_reset", "msg": "reset: side button"}])
    assert "RESET only with the lid off" in n.result_title("check_enclosure", {}, side)
    rattle = case([{"severity": "warn", "code": "pcb_seated", "part": "pcb", "msg": "held down at 0"}])
    assert n.result_title("check_enclosure", {}, rattle).endswith("snaps 1.7 %, notes: 1")
    assert n.localize(n.result_title("check_enclosure", {}, rattle), "ru").endswith("защёлки 1.7 %, замечаний: 1")
    # the USB check stops at 2 mm
    wide = case()
    wide["summary"]["usb_clearance_mm"] = 1.998
    assert "USB ≥ 2 mm" in n.result_title("check_enclosure", {}, wide)
    # an engine failure is a failed step, not a case that does not fit
    assert n.result_title("check_enclosure", {}, {"ok": False, "stage": "crash", "error": "worker died"}) == "Internal step failed, trying another way"


def test_every_build_of_a_case_says_how_it_fits_its_board():
    built = {"ok": True, "version": 3, "size_mm": [65.7, 56, 8.9], "printable": True, "issues": []}
    assert n.result_title("write_program", {}, {**built, "enclosure": case()}) == "Version 3 — 65.7 × 56 × 8.9 mm, printable; fits the board, USB 0.27 mm"
    assert n.result_title("set_params", {}, {**built, "enclosure": case(BLOCKED)}).endswith("; does not fit the board yet: USB plug blocked, the lid does not fit")
    assert n.result_title("edit_program", {}, {**built, "enclosure": {"ok": False, "stage": "crash", "error": "x"}}).endswith("; the case check did not run")
    assert n.result_title("write_program", {}, built) == "Version 3 — 65.7 × 56 × 8.9 mm, printable"


def test_a_pcb_build_reads_its_drc_count_traces_and_vias():
    assert n.call_title("write_circuit", {"source": "x", "summary": "XIAO carrier"}) == "Writing the circuit: XIAO carrier"
    assert n.call_title("write_circuit", {"edits": [{"find": "a", "replace": "b"}], "summary": "move C1"}) == "Changing the circuit: move C1"
    clean = pt.brief(PCB_CHECKS, 3, CARRIER, ALL_FILES)
    assert n.result_title("write_circuit", {}, clean) == "PCB v3 — 0 DRC errors, 23 traces, 13 vias"
    # a board saved with DRC errors is a version with numbers, not "Problem: …"
    dirty = copy.deepcopy(PCB_CHECKS)
    dirty["errors"] = [{"type": "pcb_trace_error", "ref": "C1", "message": "trace too close", "hint": "move C1 by 1 mm"}] * 3
    dirty["suppressed"] = 2
    out = pt.brief(dirty, 4, CARRIER, set(pt.PREVIEWS))
    assert out["ok"] is False and out["drc_errors"] == 3 and out["error"].startswith("3 DRC error(s)")
    # the listed errors, as the 'pcb.version' event and the result card count them; the 2 follow-ups are the suppressed line
    assert n.result_title("write_circuit", {}, out) == "PCB v4 — 3 DRC errors, 23 traces, 13 vias"
    assert n.result_title("write_circuit", {}, {k: v for k, v in out.items() if k != "drc_errors"}) == "PCB v4 — 3 DRC errors, 23 traces, 13 vias"
    assert n.result_title("write_circuit", {}, pt.brief({**PCB_CHECKS, "intent": {"ok": True, "checked": 0}}, 1, CARRIER, ALL_FILES)).endswith(
        ", no intent stated")
    unmet = {**PCB_CHECKS, "intent": {"ok": False, "checked": 6, "issues": [{"code": "intent_not_at_edge", "ref": "J1", "msg": "x"}]}}
    assert n.result_title("write_circuit", {}, pt.brief(unmet, 2, CARRIER, ALL_FILES)).endswith(", intent not met: 1")


def test_a_failed_circuit_build_says_what_happens_next():
    t = n.result_title
    assert t("write_circuit", {}, {"ok": False, "stage": "timeout", "error": "build timed out"}) == "Routing took too long, simplifying the board"
    assert t("write_circuit", {}, {"ok": False, "stage": "compile", "error": "Unexpected token '<'", "note": "nothing was saved"}) == (
        "Fixing the circuit: Unexpected token '<'")
    assert t("write_circuit", {}, {"ok": False, "error": "not found: 'pcbX={3}'", "hint": "copy `find` exactly"}) == "Edit didn't apply, retrying"
    assert t("write_circuit", {}, {"ok": False, "infra": True, "stage": "crash", "error": "the PCB engine failed"}) == "Internal step failed, trying another way"


def test_the_pcb_check_the_fab_files_and_the_case():
    assert n.call_title("check_pcb", {"version": 3}) == "Checking PCB v3"
    assert n.call_title("check_pcb", {}) == "Checking the board"
    checked = {**pt.brief(PCB_CHECKS, 3, CARRIER, ALL_FILES), "case": "none for this version yet: make_enclosure"}
    assert n.result_title("check_pcb", {}, checked) == "PCB v3: 0 DRC errors, intent met, fab files ready"
    assert n.call_title("export_fab", {}) == "Exporting Gerber, BOM and CPL"
    fab = {"ok": True, "version": 3, "files": {}, "layers": PCB_CHECKS["fab"]["layers"], "bom_lines": 9, "cpl_lines": 1}
    assert n.result_title("export_fab", {}, fab) == "Fab files for PCB v3: Gerber zip (11 layers), BOM (9 lines), CPL (1 line)"
    blocked = {"ok": False, "version": 4, "error": "PCB v4 has 3 DRC error(s): fab files come only from a clean board. Fix them with write_circuit first"}
    assert n.result_title("export_fab", {}, blocked) == "No fab files for PCB v4 yet: it still has DRC errors"
    assert n.call_title("make_enclosure", {}) == "Making the case for the board and a printable mock-up of it"
    assert n.call_title("make_enclosure", {"version": 3, "with_mockup": False}) == "Making the case for PCB v3"
    made = {"ok": True, "version": 2, "size_mm": [104, 86.85, 15.5], "printable": True, "issues": [], "pcb_version": 3, "mockup": True, "enclosure": case()}
    assert n.result_title("make_enclosure", {}, made) == "Case v2 for PCB v3 — print plate 104 × 86.8 × 15.5 mm, printable; fits the board, USB 0.27 mm"
    # the call line named the version already
    assert n.result_title("make_enclosure", {"version": 3}, made) == "Case v2 — print plate 104 × 86.8 × 15.5 mm, printable; fits the board, USB 0.27 mm"
    assert n.result_title("make_enclosure", {}, {"ok": False, "stage": "runtime", "error": "lib.elec: no outline"}) == "The case did not build: lib.elec: no outline"
    assert n.call_title("look", {"what": "pcb"}) == "Looking at the routed board from the top"
    assert n.result_title("look", {"what": "schematic"}, {"ok": True, "version": 2}) == "PCB v2 schematic"


RU_TOKENS = {"USB", "DRC", "BOM", "CPL", "Gerber", "zip", "A4", "RESET", "Raspberry", "Pi", "Pico", "W"}


def _russian(text: str) -> str:
    ru = n.localize(text, "ru")
    left = set(re.findall(r"[A-Za-z]{2,}", ru)) - RU_TOKENS
    assert not left, f"{ru!r} keeps English: {left}"
    return ru


def test_a_top_button_the_plunger_misses_is_named_and_gets_the_plunger_hint():
    # the over-strained BOOTSEL tongue of the Pico W edit run: an error, not the side-button 'lid off' note
    strained = case([{"severity": "error", "code": "button_unreachable", "part": "bootsel", "value": 0.3, "unit": "mm",
                      "msg": "bootsel: plunger 0.30 mm above the button, tongue 9 mm free, bending strain 2.15 % (PLA limit ~2 %)"}])
    title = n.result_title("check_enclosure", {}, strained)
    assert title == "Raspberry Pi Pico W does not fit yet — BOOTSEL button out of reach"
    assert n.localize(title, "ru").endswith("BOOTSEL не нажимается")
    assert strained["errors"][-1]["fix"] == et.PLUNGER_HINT and "lid off" not in et.PLUNGER_HINT
    side = case([{"severity": "warn", "code": "button_unreachable", "part": "btn_reset", "msg": "reset: side button"}])
    assert "lid off" in side["warnings"][-1]["fix"]


def test_the_electronics_titles_are_all_russian_in_a_russian_run():
    scan = {"ok": True, "board": et.board_brief(pico()), "calibration": {"method": "board_holes", "uncertainty_mm": 0.04}}
    titles = [
        n.call_title("scan_board", {}), n.result_title("scan_board", {}, scan),
        n.result_title("scan_board", {}, {**scan, "board": {"name": "x", "source": "photo", "size_mm": [30, 20]}, "calibration": {"method": "card"}}),
        n.call_title("use_board", {"board_id": "Pico W"}), n.result_title("use_board", {"board_id": "Pico W"}, {"ok": True, "board": et.board_brief(pico())}),
        n.call_title("use_board", {"spec": {}}), n.call_title("check_enclosure", {}),
        n.result_title("check_enclosure", {}, case()), n.result_title("check_enclosure", {}, case(BLOCKED)),
        n.result_title("check_enclosure", {}, case([{"severity": "warn", "code": "button_unreachable", "part": "btn_reset", "msg": "x"}])),
        # every problem the check can name, one at a time
        *[n.result_title("check_enclosure", {}, case([{"severity": "error", "code": c, "part": "usb", "value": 5.0, "msg": "x"}])) for c in n.CASE_PROBLEM],
        n.call_title("write_circuit", {"source": "x"}), n.call_title("write_circuit", {"edits": [{}]}),
        n.result_title("write_circuit", {}, pt.brief(PCB_CHECKS, 3, CARRIER, ALL_FILES)),
        n.result_title("write_circuit", {}, pt.brief({**PCB_CHECKS, "intent": {"ok": False, "checked": 2, "issues": [{}]}}, 3, CARRIER, ALL_FILES)),
        n.result_title("write_circuit", {}, pt.brief({**PCB_CHECKS, "intent": {"ok": True, "checked": 0}}, 3, CARRIER, ALL_FILES)),
        n.result_title("write_circuit", {}, {"ok": False, "stage": "timeout", "error": "x"}),
        n.call_title("check_pcb", {"version": 3}), n.call_title("check_pcb", {}),
        n.result_title("check_pcb", {}, pt.brief(PCB_CHECKS, 3, CARRIER, ALL_FILES)),
        n.result_title("check_pcb", {}, pt.brief({**PCB_CHECKS, "intent": {"ok": True, "checked": 0}}, 3, CARRIER, set())),
        n.call_title("export_fab", {"version": 2}),
        n.result_title("export_fab", {}, {"ok": True, "version": 3, "layers": ["a"] * 11, "bom_lines": 9, "cpl_lines": 21}),
        n.result_title("export_fab", {}, {"ok": False, "version": 3, "error": "PCB v3 has 1 DRC error(s)"}),
        n.result_title("export_fab", {}, {"ok": False, "version": 3, "error": "PCB v3 has no gerbers.zip"}),
        n.call_title("make_enclosure", {}), n.call_title("make_enclosure", {"version": 2}),
        n.result_title("make_enclosure", {}, {"ok": True, "version": 2, "size_mm": [104, 86, 15], "pcb_version": 3, "enclosure": case(BLOCKED)}),
        n.result_title("make_enclosure", {}, {"ok": True, "version": 2, "size_mm": [104, 86, 15], "enclosure": {"ok": False, "error": "x"}}),
        n.result_title("make_enclosure", {}, {"ok": True, "version": 2, "size_mm": [104, 86, 15], "printable": False, "issues": [{"severity": "error"}]}),
        n.call_title("look", {"what": "pcb"}), n.call_title("look", {"what": "pcb_bottom"}), n.call_title("look", {"what": "schematic"}),
        n.result_title("look", {"what": "pcb"}, {"ok": True, "version": 1}), n.result_title("look", {"what": "pcb_bottom"}, {"ok": True, "version": 1}),
        n.result_title("look", {"what": "schematic"}, {"ok": True, "version": 1}),
        n.result_title("finish", {}, {"accepted": False, "reason": "the board is not ready"}),
        n.result_title("finish", {}, {"accepted": False, "reason": "the case check found errors"}),
    ]
    ru = [_russian(t) for t in titles]
    for want in ("Плата распознана: Raspberry Pi Pico W, масштаб по её отверстиям ±0.04 мм",
                 "Raspberry Pi Pico W влезает — USB 0.27 мм, все кнопки нажимаются, защёлки 1.7 %",
                 "Raspberry Pi Pico W пока не влезает — USB перекрыт, крышка не садится",
                 "Плата v3 — 0 ошибок DRC, 23 трассы, 13 переходов",
                 "Файлы для фабрики, плата v3: Gerber zip (11 слоёв), BOM (9 строк), CPL (21 строка)"):
        assert want in ru, want
    assert ru[-2:] == ["Пока нет: плата ещё не готова", "Пока нет: проверка корпуса нашла ошибки"]


def test_russian_counts_decline_their_noun():
    assert [n.localize(f"PCB v1 — {k} DRC errors, {k} traces, {k} vias", "ru") for k in (1, 2, 5, 11, 21, 22, 112)] == [
        f"Плата v1 — {k} {e}, {k} {t}, {k} {v}" for k, e, t, v in (
            (1, "ошибка DRC", "трасса", "переход"), (2, "ошибки DRC", "трассы", "перехода"), (5, "ошибок DRC", "трасс", "переходов"),
            (11, "ошибок DRC", "трасс", "переходов"), (21, "ошибка DRC", "трасса", "переход"), (22, "ошибки DRC", "трассы", "перехода"),
            (112, "ошибок DRC", "трасс", "переходов"))]
    # English stays English
    assert n.localize("PCB v1 — 2 DRC errors", "en") == "PCB v1 — 2 DRC errors"


def test_the_existing_titles_are_unchanged():
    t = n.result_title
    assert n.localize(t("write_program", {}, {"ok": True, "version": 2, "size_mm": [70.5, 45.4, 3], "printable": True, "issues": []}), "ru") == (
        "Версия 2 — 70.5 × 45.4 × 3 мм, печатается")
    assert n.localize(t("finish", {}, {"accepted": False, "reason": "printability errors remain"}), "ru") == "Пока нет: остались ошибки печатаемости"
    assert n.call_title("look", {"what": "a_1"}) == "Taking a closer look at the photo"
    assert t("look", {"what": "model"}, {"ok": True}) == "Done"


async def _run(ctx, monkeypatch, name: str, args: dict, result: dict, text: str = "a carrier board for the XIAO") -> list[dict]:
    async def tool(ctx, state, tool_name, tool_args):
        return result, []

    monkeypatch.setattr(loop, "run_tool", tool)
    _use(monkeypatch, FakeMeta([[call(name, args)], [say("Done here.")]]))
    await loop.design(ctx, SendMessage(text=text))
    return await _events()


async def test_the_loop_sends_the_pcb_step_with_its_kind_and_titles(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db)
    evs = await _run(ctx, monkeypatch, "write_circuit", {"source": "x", "summary": "XIAO carrier"}, pt.brief(PCB_CHECKS, 1, CARRIER, ALL_FILES))
    sent = next(e["data"] for e in evs if e["type"] == "tool.call")
    assert sent["kind"] == "build" and sent["title"] == "Writing the circuit: XIAO carrier" and sent["model"] == "muse-spark-1.3"
    res = next(e["data"] for e in evs if e["type"] == "tool.result")
    assert res["kind"] == "build" and res["ok"] is True and res["title"] == "PCB v1 — 0 DRC errors, 23 traces, 13 vias"
    assert [e["data"]["stage"] for e in evs if e["type"] == "job.stage"][:2] == ["understand", "design"]


async def test_a_russian_run_gets_russian_electronics_steps(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db, language="ru")
    evs = await _run(ctx, monkeypatch, "check_enclosure", {}, case(BLOCKED), text="корпус для Pico W")
    sent = next(e["data"] for e in evs if e["type"] == "tool.call")
    assert sent["kind"] == "inspect" and sent["title"] == "Сверяю корпус с платой"
    res = next(e["data"] for e in evs if e["type"] == "tool.result")
    assert res["ok"] is False and res["title"] == "Raspberry Pi Pico W пока не влезает — USB перекрыт, крышка не садится"
    assert any(e["type"] == "job.stage" and e["data"]["stage"] == "check" and e["data"]["label"] == "Сверяю с реальностью" for e in evs)
