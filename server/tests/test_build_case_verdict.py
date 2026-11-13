"""A case build's step keeps its check against the board in the other UI language: the tool.result summary is the result's
JSON cut at 600 characters and the enclosure brief comes last, so tools.py puts a short verdict right after 'printable'
(steps.ts rebuilds the version step from it). The model still gets the whole brief; the server's own title is unchanged."""
from __future__ import annotations

import json
from types import SimpleNamespace

from iamodelize3d.agent import narrate, tools

PARAMS = {f"param_{i}": i * 1.5 for i in range(30)}


def build_result(enclosure: dict) -> dict:
    return {"ok": True, "version": 3, "size_mm": [65.7, 56, 8.9], "volume_mm3": 9100, "est_grams": 10.9, "printable": True, "score": 100,
            "issues": [{"code": "overhang", "severity": "warn", "msg": "a short overhang under the lid lip"}], "params": PARAMS,
            "parts": [{"name": "base", "role": "model"}, {"name": "lid", "role": "model"}], "enclosure": enclosure}


def brief(errors: list[dict], usb: float | None = 0.29) -> dict:
    return {"ok": not errors, "version": 3, "board_name": "Raspberry Pi Pico W",
            "summary": {"usb_clearance_mm": usb, "button_gap_mm": 0.3, "snap_strain_pct": 1.67},
            "clearance_mm": {"U1_usb": usb}, "errors": errors, "warnings": [], "passed": ["the board rests on 4 standoffs"] * 8}


def summary(result: dict) -> str:
    return narrate.scrub(json.dumps(result, ensure_ascii=False))[:600]  # as loop.py emits it


def test_the_verdict_lands_inside_the_cut_and_the_brief_stays():
    r = build_result(brief([]))
    title = narrate.result_title("edit_program", {}, r)
    tools._verdict_first(r)
    s = summary(r)
    assert '"enclosure"' not in s, "the brief itself is past the cut"
    assert '"case_fit": {"fits": true, "usb_clearance_mm": 0.29}' in s
    assert list(r)[:7] == ["ok", "version", "size_mm", "volume_mm3", "est_grams", "printable", "case_fit"]
    assert r["enclosure"]["passed"], "the model still reads the whole check"
    assert narrate.result_title("edit_program", {}, r) == title == "Version 3 — 65.7 × 56 × 8.9 mm, printable, notes: 1; fits the board, USB 0.29 mm"


def test_a_case_that_does_not_fit_names_its_codes():
    r = build_result(brief([{"code": "button_reach", "part": "BOOTSEL", "msg": "the tongue misses the button by 1.2 mm", "value": 1.2, "unit": "mm",
                              "fix": "change pressGap (plunger gap) or tabLen"}]))
    tools._verdict_first(r)
    assert r["case_fit"] == {"fits": False, "problems": [{"code": "button_reach", "part": "BOOTSEL", "value": 1.2}], "usb_clearance_mm": 0.29}
    assert json.loads(summary(r)[summary(r).index('{"fits"'):].split("}],", 1)[0] + "}]}")["problems"][0]["code"] == "button_reach"
    # many problems: six of them and how many more, still well inside the cut
    r = build_result(brief([{"code": "port_blocked", "part": f"J{i}", "msg": "x" * 80} for i in range(9)], usb=None))
    tools._verdict_first(r)
    assert len(r["case_fit"]["problems"]) == 6 and r["case_fit"]["more"] == 3 and "usb_clearance_mm" not in r["case_fit"]
    assert '"more": 3' in summary(r)


def test_an_engine_failure_of_the_check():
    r = build_result({"ok": False, "stage": "build", "error": "assembled case did not build"})
    tools._verdict_first(r)
    assert r["case_fit"] == {"ran": False}
    assert narrate.result_title("write_program", {}, r).endswith("; the case check did not run")


async def test_checked_puts_it_first_only_for_a_checked_case(monkeypatch):
    async def after_build(ctx, state, result):
        result["enclosure"] = brief([])

    monkeypatch.setattr(tools.elec_tools, "after_build", after_build)
    out, _ = await tools._checked(None, SimpleNamespace(pack="enclosure"), (build_result({}) | {"enclosure": None}, []))  # type: ignore[arg-type]
    assert list(out).index("case_fit") == 6 and out["case_fit"]["fits"] is True
    # other packs, and a failed build, keep the result as it was
    plain = {"ok": True, "version": 2, "printable": True}
    out, _ = await tools._checked(None, SimpleNamespace(pack="household"), (dict(plain), []))  # type: ignore[arg-type]
    assert out == plain
    out, _ = await tools._checked(None, SimpleNamespace(pack="enclosure"), ({"ok": False, "error": "x"}, []))  # type: ignore[arg-type]
    assert "case_fit" not in out


def test_the_verdict_names_the_assembled_size():
    # size_mm is the print plate; the check measured the case with its lid on
    b = brief([])
    b["summary"]["case_mm"] = [41, 40, 15.5]
    r = build_result(b)
    tools._verdict_first(r)
    assert r["case_fit"] == {"fits": True, "case_mm": [41, 40, 15.5], "usb_clearance_mm": 0.29}
    assert '"case_mm": [41, 40, 15.5]' in summary(r)

