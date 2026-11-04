"""Defects read from the real chats on formwright.axo.kz of 2026-11-04, each kept as a case of the general mechanism that fixes it."""
from __future__ import annotations

import pytest

from formwright import device, firmware_check
from formwright.agent import device_inspect, device_tools, loop, narrate
from formwright.agent.tools import DesignState, _hand_values, _source_value, _unstrung, tools_for

XIAO_S3 = "113991114"
XIAO_C3 = "113991054"


def _keypad(**place) -> dict:
    return {"schema": "fw.device/1", "title": "Keypad", "board": {"holes": True}, "nodes": [
        {"id": "U1", "kind": "module", "module": XIAO_S3, "edge": "-y"},
        {"id": "SW1", "kind": "button"},
        {"id": "BT1", "kind": "accessory", "accessory": "lipo_1s_500", **place}],
        "nets": [{"pins": ["U1.GND", "SW1.B"], "name": "GND"}, {"pins": ["U1.D0", "SW1.A"]}]}


def test_a_cell_on_the_bat_pads_has_no_place():
    """A keypad's board went from 56 to 100 mm and the run out of steps moving a cell that stays where the case puts it."""
    norm, issues = device.normalize(_keypad(place={"x": 0, "y": 32}))
    assert not next(n for n in norm["nodes"] if n["id"] == "BT1").get("place")
    assert not [i for i in issues if i["ref"] == "BT1"]


def test_the_cell_is_not_on_the_board_in_the_inspection():
    board = {"pcb": {"outline": {"w": 36, "h": 56}},
             "components": [{"id": "SW4", "x": 26.0, "y": 28.0, "w": 7.0, "d": 9.0, "h": 5.0, "access": "press"}],
             "accessories": [{"id": "BT1", "key": "lipo_1s_500", "name": "LiPo", "kind": "battery", "mount": "inside", "x": 18.0, "y": 28.0, "w": 30.0, "d": 20.0, "h": 6.0}]}
    key = device_inspect.part_facts("SW4", board, None, None)
    assert "under" not in key and not [n for n in key.get("neighbours", []) if n.startswith("BT1")]
    cell = device_inspect.part_facts("BT1", board, None, None)
    assert "Loose in the case" in cell["note"] and "at_mm" not in cell and "error" not in cell


def test_a_module_on_the_board_still_covers_what_is_under_it():
    board = {"pcb": {"outline": {"w": 50, "h": 50}},
             "components": [{"id": "BZ1", "x": 25.0, "y": 25.0, "w": 9.0, "d": 9.0, "h": 5.0, "access": "sound"}],
             "accessories": [{"id": "DS1", "key": "oled", "name": "OLED", "kind": "display", "mount": "board", "x": 25.0, "y": 25.0, "w": 27.0, "d": 27.0, "h": 3.0, "z0": 2.5}]}
    assert device_inspect.part_facts("BZ1", board, None, None).get("under")


def _meter() -> dict:
    return {"nodes": [{"id": "U1", "kind": "module", "module": XIAO_S3, "edge": "-y"}, {"id": "J1", "kind": "header", "pins": ["RF", "GND"], "edge": "+y"}],
            "nets": [{"pins": ["U1.GND", "J1.GND"], "name": "GND"}],
            "requirements": [{"id": "R7", "text": "SMA input", "parts": ["J1"], "firmware": False}]}


def test_a_required_connector_with_a_pin_wired_to_nothing_is_an_error():
    """A 2.4 GHz meter shipped with its RF input connected to nothing, and its build's warning passed over."""
    doc = _meter()
    assert any("J1.RF is wired to nothing" in p for p in device_tools.requirement_problems(doc))
    doc["nets"].append({"pins": ["J1.RF", "U1.D0"]})
    assert not any("wired to nothing" in p for p in device_tools.requirement_problems(doc))


def test_lint_says_a_header_pin_is_open():
    norm, _ = device.normalize({**_meter(), "schema": "fw.device/1", "title": "m", "board": {}})
    assert any(w["code"] == "open_pin" and w["ref"] == "J1.RF" for w in device.lint(norm, {}))


def test_connect_does_not_join_two_nets_by_accident():
    """Moving a flyback diode with connect joined the buzzer's switch to GND; the run went back to the wrong wiring and called it fine."""
    doc = {"nodes": [], "nets": [{"pins": ["U1.GND", "D1.A", "Q1.E"], "name": "GND"}, {"pins": ["Q1.C", "BZ1.NEG"]}]}
    new, errors = device_tools.apply_edits(doc, [{"op": "connect", "pins": ["Q1.C", "BZ1.NEG", "D1.A"]}])
    assert errors and "move" in errors[0] and new["nets"] == doc["nets"]
    new, errors = device_tools.apply_edits(doc, [{"op": "move", "pin": "D1.A", "to": "Q1.C"}])
    assert not errors
    assert new["nets"] == [{"pins": ["U1.GND", "Q1.E"], "name": "GND"}, {"pins": ["Q1.C", "BZ1.NEG", "D1.A"]}]


def test_connecting_new_pins_to_one_net_still_works():
    doc = {"nodes": [], "nets": [{"pins": ["R1.1", "U1.V3V3"], "name": "V3V3"}]}
    new, errors = device_tools.apply_edits(doc, [{"op": "connect", "pins": ["R1.1", "R2.1"]}])
    assert not errors and new["nets"][-1]["pins"] == ["R1.1", "R2.1"]


@pytest.mark.asyncio
async def test_open_warnings_are_named_for_an_answer(monkeypatch):
    async def rules(doc, parts=None):
        return [{"code": "flyback_diode", "ref": "BZ1", "severity": "warning", "msg": "no diode"}, {"code": "bjt_reversed", "ref": "Q1", "severity": "error", "msg": "x"},
                {"code": "unused_requirement", "ref": "R1", "severity": "warning", "msg": "y"}]

    monkeypatch.setattr(device_tools, "design_checks", rules)
    norm, _ = device.normalize(_keypad())
    keys = [w["key"] for w in await device_tools.open_warnings(norm, {})]
    assert "flyback_diode BZ1" in keys and "bjt_reversed Q1" not in keys and "unused_requirement R1" not in keys


def test_warnings_left_open_are_told_to_the_person():
    state = DesignState(pack="device")
    state.self_check["kept_warnings"] = ["strapping_pin U1.D0"]
    assert "strapping_pin U1.D0" in device_tools.kept_note(state, "Готово")
    assert "оставленные" in device_tools.kept_note(state, "Готово")
    assert device_tools.kept_note(DesignState(pack="device"), "Done") == ""


def test_a_compiler_error_never_reaches_the_person():
    text = device_tools.sim_note({"ran": False, "why": "build failed: macro_keypad.ino:11:1: error: unknown type name 'USBHIDKeyboard'\n 1 error generated.\n"}, "Готово")
    assert "USBHIDKeyboard" not in text and "error" not in text and "собрать" in text


def test_a_screen_the_device_never_had_is_no_weakened_test():
    """Told to "put that back", a connector board got an OLED so that a mistaken test could pass."""
    state = DesignState(pack="device")
    state.self_check["test_pins"] = {"R4": ["the screen"]}
    plain = {"nodes": [{"id": "LED1", "kind": "led"}], "requirements": [{"id": "R4", "text": "t", "parts": ["LED1"], "firmware": True,
                                                                          "test": {"expect": [{"at_s": 1, "output": "LED1"}]}}]}
    assert not device_tools.weakened_tests(state, plain)
    screen = {**plain, "nodes": [*plain["nodes"], {"id": "DS1", "kind": "accessory", "accessory": "oled_096_i2c"}]}
    assert device_tools.weakened_tests(state, screen)


@pytest.mark.asyncio
async def test_firmware_for_another_display_controller_is_an_error():
    """A 1.3 inch SH1106 driven as an SH1107 compiles and shows garbage."""
    doc = {"nodes": [{"id": "U1", "kind": "module", "module": XIAO_S3}, {"id": "DS1", "kind": "accessory", "accessory": "oled_13_i2c"}], "nets": []}
    code = "// SH1106 display\n#include <Adafruit_SH110X.h>\nAdafruit_{} d(128, 64, &Wire, -1);\nvoid setup() {{}}\nvoid loop() {{}}\n"
    assert firmware_check._display_controller(doc, {"a.ino": code.format("SH1107")})
    assert not firmware_check._display_controller(doc, {"a.ino": code.format("SH1106G")})


@pytest.mark.asyncio
async def test_usb_keyboard_on_a_c3_does_not_pass_the_check():
    """The C3 has no native USB: a keypad on it was sold as a USB keyboard."""
    doc = {"nodes": [{"id": "U1", "kind": "module", "module": XIAO_C3}], "nets": []}
    code = "#include <USB.h>\n#include <USBHIDKeyboard.h>\nUSBHIDKeyboard Keyboard;\nvoid setup() { Keyboard.begin(); USB.begin(); }\nvoid loop() {}\n"
    assert not (await firmware_check.check(doc, {"k.ino": code}, "arduino"))["ok"]


@pytest.mark.asyncio
async def test_a_bluetooth_keyboard_is_checked_on_both_chips():
    """Its library was "unchecked" and its sketch never ran: a keypad whose debounce never let a key through passed as fine."""
    code = "#include <BleKeyboard.h>\nBleKeyboard kb(\"Pad\");\nvoid setup() { kb.begin(); }\nvoid loop() { if (kb.isConnected()) { kb.press('a'); kb.releaseAll(); kb.write(KEY_MEDIA_MUTE); } delay(5); }\n"
    for module in (XIAO_C3, XIAO_S3):
        out = await firmware_check.check({"nodes": [{"id": "U1", "kind": "module", "module": module}], "nets": []}, {"k.ino": code}, "arduino")
        assert out["ok"], out["errors"]
        assert not [w for w in out["warnings"] if w["code"] == "library_unchecked"]


def test_the_continue_button_keeps_the_language_of_the_chat():
    assert loop.message_language("Continue from where you stopped.", "ru") == "ru"
    assert loop.message_language("Продолжи с того места, где остановился.", "en") == "en"
    assert loop.message_language("Make it twice as long", "ru") == "en"


def test_a_rewrite_keeps_the_sliders_unless_it_decides_otherwise():
    source = "const params = {\n  tube_len: { value: 80, min: 40, max: 200 },\n  key_len: { value: 6, min: 4 },\n  style: { value: 'round', kind: 'choice' },\n};"
    assert _source_value(source, "tube_len") == 80 and _source_value(source, "style") == "round" and _source_value(source, "nope") is None
    state = DesignState(pack="household", hand_params={"tube_len": {"was": 80, "now": 60}, "key_len": {"was": 5, "now": 11}, "gone": {"was": 1, "now": 2}})
    assert _hand_values(state, source) == {"tube_len": 60}
    assert set(state.hand_params) == {"tube_len", "gone"}  # key_len was written with a third value: this request's decision


def test_objects_sent_as_json_strings_are_parsed():
    out = _unstrung({"zoom": '{"part": "lid", "size": 30}', "views": "[1, 2]", "summary": "[см. выше]", "source": "{x}", "what": "model", "cut": "{broken"})
    assert out == {"zoom": {"part": "lid", "size": 30}, "views": [1, 2], "summary": "[см. выше]", "source": "{x}", "what": "model", "cut": "{broken"}


def test_machining_needs_no_printer():
    assert "set_process" in {t["name"] for t in tools_for("household", photos=False, prints=False)}
    assert "set_process" not in {t["name"] for t in tools_for("enclosure", photos=False, prints=False)}
    assert narrate.result_title("write_program", {}, {"version": 3, "size_mm": [1000, 60, 60], "process": "machined"}) == "Version 3 — 1000 × 60 × 60 мм".replace(" мм", " mm")
