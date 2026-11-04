"""The designer's self-check in place of the device reviewer (device_checklists.py, device_tools.self_check, tools._finish,
the requirement checks of firmware_check.py): the checklist is English, compact, names only checks that exist and maps a
graph's parts to the kinds the design rules see; a device's first finish past the gate returns the checklist of its kinds
and is accepted once `checked` answers every kind; the reviewer runs only when settings.device_reviewer turns it on; and
the firmware is held to its requirements: the soil sensor and the leak detector of 2026-11-03 had their deep sleep
commented out, a night light promised a fade it did not do, while the devices that did both stay clean."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from formwright import device, device_checklists as dc, firmware_check as fc
from formwright.agent import device_prompt, device_review, device_tools, prompts, tools
from formwright.agent.tools import DesignState
from formwright.config import settings
from formwright.llm.english import is_english

from test_device_tools_harness import FakeCtx

SERVER = Path(__file__).resolve().parent.parent / "formwright"
FIX = Path(__file__).parent / "fixtures" / "firmware"
C3 = {"id": "U1", "kind": "module", "module": "113991054"}


def fixture(name: str) -> tuple[dict, dict, str]:
    doc = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["doc"]
    return doc, doc["firmware"]["files"], doc["firmware"]["lang"]


def codes(r: dict, code: str) -> list[dict]:
    return [i for i in r["errors"] + r["warnings"] if i["code"] == code]


@pytest.fixture
def no_gxx(monkeypatch):
    monkeypatch.setattr(fc, "gxx", lambda: None)


# ---------------------------------------------------------------- the checklist
def _known_codes() -> set[str]:
    rules = (SERVER / "device_rules.py").read_text(encoding="utf-8")
    known = set(re.findall(r'_f\((?:ERROR|WARNING), "([a-z_0-9]+)"', rules))
    known |= set(re.findall(r'_item\("([a-z_0-9]+)"', (SERVER / "firmware_check.py").read_text(encoding="utf-8")))
    known |= set(re.findall(r'"code": "([a-z_0-9]+)"', (SERVER / "device.py").read_text(encoding="utf-8")))
    # the case's findings (packages/geom enclosure check) the finish gate reads
    return known | {"light_window", "sound_grille", "sensor_window", "display_window", "cable_exit", "battery_space",
                    "button_unreachable", "button_reach"}


def test_the_checklist_is_english_compact_and_names_real_checks():
    text = dc.all_text()
    assert is_english(text) and 9_000 < len(text) < 15_000   # ~3500 tokens in the cached system prompt
    for key, (title, items) in dc.SECTIONS.items():
        assert f"## {key}: {title}" in text and items, key
        for i, (item, rule) in enumerate(items):
            assert "\n" not in item and len(item) < 240, item
            assert f"- {key}.{i + 1} {item} [{rule or 'you'}]" in text
    known = _known_codes()
    named = {c for _, items in dc.SECTIONS.values() for _, rule in items for c in re.findall(r"\b[a-z0-9]+_[a-z0-9_]+\b", rule)}
    assert named - known == set(), named - known
    # the facts the designer got wrong on 2026-11-03, said the right way round
    for want in ("D6=TX=GPIO21", "esp_deep_sleep_enable_gpio_wakeup", "GPIO0-5", "C3 D0-D2", "GPIO2/8/9", "0/3/45/46",
                 "tone()", "a 2-4 V part never on 5 V", "module_bat", "decide dark only while the lights are off", "ledcAttach",
                 "5.1k", "0x3C", "_t_cyrillic", "Warm-up", "electrolysis", "INPUT_PULLUP", "press tab"):
        assert want in text, want


def test_the_device_prompt_carries_the_checklist_after_the_method():
    pack = prompts.PACKS["device"]
    assert device_prompt.PACK_TEXT in pack and device_prompt.CHECKLIST in pack
    assert pack.index(device_prompt.PACK_TEXT) < pack.index("# Self-check")
    assert "`checked`" in device_prompt.PACK_TEXT and len(device_prompt.PACK_TEXT) < 18_000  # the concept step took ~1.3k


def test_kinds_of_follows_the_design_rules_and_the_accessories():
    doc = {"nodes": [C3, {"id": "LED1", "kind": "led"}, {"id": "R1", "kind": "resistor"}, {"id": "C1", "kind": "capacitor"},
                     {"id": "SW1", "kind": "button"}, {"id": "J1", "kind": "usb_c"}, {"id": "H1", "kind": "hole"},
                     {"id": "Q1", "kind": "chip", "lcsc": "C20917"}, {"id": "BZ1", "kind": "chip", "lcsc": "C96093"},
                     {"id": "U3", "kind": "chip", "lcsc": "C2843785", "label": "PIR AM312"},
                     {"id": "DS1", "kind": "accessory", "accessory": "oled_096_i2c"},
                     {"id": "BT1", "kind": "accessory", "accessory": "lipo_1s_500"},
                     {"id": "PIR1", "kind": "accessory", "accessory": "hc_sr501_pir"},
                     {"id": "P1", "kind": "accessory", "accessory": "soil_capacitive_v12"},
                     {"id": "M1", "kind": "accessory", "accessory": "servo_sg90"}]}
    parts = {"Q1": {"kind_hint": "nmos"}, "BZ1": {"kind_hint": "buzzer_active"}, "U3": {"kind_hint": "sensor"}}
    assert dc.kinds_of(doc, parts) == {"mcu", "led", "resistor", "capacitor", "switch", "connector", "transistor", "buzzer", "pir",
                                       "display", "battery", "probe", "motor", "case", "device"}
    assert dc.kinds_of({"nodes": []}) == {"case", "device"}
    # without a card a chip falls back to what its label says, as the rules do
    assert "transistor" in dc.kinds_of({"nodes": [{"id": "Q1", "kind": "chip", "lcsc": "C1", "label": "MOSFET low side"}]}, {})
    text = dc.for_kinds({"led", "case", "nonsense"})
    assert text.startswith("## led:") and "## case:" in text and "## mcu" not in text
    mine = dc.for_kinds({"transistor"}, only_yours=True)
    assert "transistor.5" in mine and "transistor.1 " not in mine


def test_coverage_wants_every_kind_with_a_verdict():
    kinds = ["led", "switch", "case", "device"]
    missing, bad = dc.coverage([{"kind": "led", "verdict": "ok"}, {"item": "switch.2", "verdict": "fixed", "where": "fw.ino:12"},
                                {"item": "case: openings", "verdict": "n/a"}, {"kind": "device", "verdict": "problem"}, "x"], kinds)
    assert missing == ["device"] and len(bad) == 2 and "ok, fixed or n/a" in bad[0]
    assert dc.coverage([{"kind": k, "verdict": "OK"} for k in kinds], kinds) == ([], [])


# ---------------------------------------------------------------- finish: the self-check instead of the reviewer
@pytest.fixture
def device_finish(monkeypatch):
    """A device whose gate passes: an LED, its resistor and a button on a XIAO; the parts resolve to nothing (primitives)."""
    doc = {"schema": "fw.device/1", "title": "Lamp", "requirements": [{"id": "R1", "text": "a light", "parts": ["LED1"]}],
           "nodes": [C3, {"id": "LED1", "kind": "led"}, {"id": "R1", "kind": "resistor", "value": "1k"}, {"id": "SW1", "kind": "button"}],
           "nets": [{"name": "GND", "pins": ["U1.GND", "LED1.K", "SW1.B"]}, {"pins": ["U1.D1", "R1.1"]}, {"pins": ["R1.2", "LED1.A"]},
                    {"pins": ["U1.D2", "SW1.A"]}]}
    calls = []

    async def gate(ctx, state):
        return []

    async def current(project_id):
        return doc, 4

    async def resolve(d):
        return {}, []

    async def reviewer(ctx, state, *, bar=None, summary=""):
        calls.append(summary)
        return {"verdict": "pass", "match_score": 9, "issues": [], "model": "open", "reviewer": "primary", "version": state.version}

    monkeypatch.setattr(device_tools, "finish_gate", gate)
    monkeypatch.setattr(device_tools, "current", current)
    monkeypatch.setattr(device, "resolve", resolve)
    monkeypatch.setattr(device_review, "review", reviewer)
    return calls


async def test_a_device_finish_returns_its_self_check_then_accepts_the_answers(device_finish):
    ctx, state = FakeCtx(), DesignState(pack="device", version=2)
    r = await tools._finish(ctx, state, "a lamp")
    assert r["accepted"] is False and r["reason"] == "self-check against the checklist" and not state.done
    sc = r["self_check"]
    assert sc["kinds"] == ["mcu", "led", "resistor", "switch", "case", "device"]
    assert "## led:" in sc["checklist"] and "led.1 A towards the GPIO" in sc["checklist"] and "## buzzer" not in sc["checklist"]
    assert "`checked`" in sc["how"] and state.finish_attempts == 0   # the round is no failed finish: the gate keeps its count
    # an answer that leaves kinds out goes back, naming them
    partial = [{"kind": "mcu", "verdict": "ok", "where": "U1"}, {"item": "led.2", "verdict": "fixed", "where": "R1 1k"}]
    r = await tools._finish(ctx, state, "a lamp", partial)
    assert r["accepted"] is False and r["missing"] == ["resistor", "switch", "case", "device"]
    full = partial + [{"kind": k, "verdict": "n/a" if k == "case" else "ok", "where": "x"} for k in ("resistor", "switch", "case", "device")]
    r = await tools._finish(ctx, state, "a lamp", json.dumps(full))   # a JSON string is read as the list
    # a full answer without a look at the board and the case goes back once, naming the parts to look at
    assert r["accepted"] is False and r["reason"] == "look at the board and the case first" and "(LED1, SW1)" in r["look"]
    state.self_check["looked"] = ["inspect_board", "inspect_case"]
    r = await tools._finish(ctx, state, "ok", json.dumps(full))   # "ok": the fuller summary of the first finish is kept
    assert r == {"accepted": True} and state.done and state.summary == "a lamp"
    assert [d for t, d in ctx.events if t == "device.self_check"][0]["looked"] == ["inspect_board", "inspect_case"]
    assert state.self_check["passed"] is True and len(state.self_check["checked"]) == 6
    # no reviewer by default: nothing called, no 'critic' event, narrate sees no review
    assert device_finish == [] and not [t for t, _ in ctx.events if t == "critic"] and state.critic is None
    from formwright.agent import narrate

    assert narrate.review_of(state.critic, state.version) is None and narrate.review_notes(state.critic, state.version, "ru") == ""


async def test_the_self_check_gives_way_on_the_last_turn_and_after_two_rounds(device_finish):
    ctx, state = FakeCtx(), DesignState(pack="device", version=2, turns_left=0)
    r = await tools._finish(ctx, state, "a lamp")
    assert r == {"accepted": True, "self_check": "not answered in full"} and state.done
    state = DesignState(pack="device", version=2)
    for _ in range(3):
        r = await tools._finish(ctx, state, "a lamp", [{"kind": "led", "verdict": "ok"}])
        if r["accepted"]:
            break
    assert r["accepted"] and state.self_check["rejected"] == 2


async def test_the_device_reviewer_is_back_when_the_setting_says_so(device_finish, monkeypatch):
    monkeypatch.setattr(settings(), "device_reviewer", True)
    ctx, state = FakeCtx(), DesignState(pack="device", version=2)
    state.self_check["passed"] = True
    r = await tools._finish(ctx, state, "a lamp")
    assert r["accepted"] and device_finish == ["a lamp"] and [t for t, _ in ctx.events if t == "critic"] == ["critic"]


def test_the_device_finish_tool_takes_checked():
    names = [t["name"] for t in tools.tools_for("device", photos=False, prints=False)]
    assert names.count("finish") == 1
    fin = next(t for t in tools.tools_for("device", photos=False, prints=False) if t["name"] == "finish")
    assert fin is device_tools.FINISH and "checked" in fin["parameters"]["properties"] and is_english(fin["description"])
    assert next(t for t in tools.tools_for("household", photos=False, prints=False) if t["name"] == "finish") is tools.FINISH


# ---------------------------------------------------------------- the firmware against its requirements
@pytest.mark.parametrize("name, line", [("req_soil_sleep_commented", 107), ("req_leak_sleep_commented", 0)])
async def test_sleep_promised_but_commented_out(no_gxx, name, line):
    r = await fc.check(*fixture(name))
    e = codes(r, "requirement_sleep")
    assert not r["ok"] and len(e) == 1 and e[0] in r["errors"] and "R6" in e[0]["msg"]
    assert ("commented out" in e[0]["msg"]) and (f":{line} " in e[0]["msg"] if line else "esp_sleep_enable_timer_wakeup" in e[0]["msg"])
    assert "esp_deep_sleep_enable_gpio_wakeup" in e[0]["hint"]   # a XIAO ESP32-C3: no ext0 / ext1


async def test_fade_promised_but_the_level_never_changes(no_gxx):
    r = await fc.check(*fixture("req_night_no_fade"))
    e = codes(r, "requirement_fade")
    assert len(e) == 1 and e[0] in r["errors"] and "R4" in e[0]["msg"] and "ledcAttach" in e[0]["hint"]


@pytest.mark.parametrize("name", ["req_soil_sleeps", "req_leak_sleeps", "req_night_fades", "req_night_ledc_fade", "req_dice_sleeps"])
async def test_devices_that_do_what_they_promise_stay_clean(no_gxx, name):
    r = await fc.check(*fixture(name))
    assert not [i for i in r["errors"] + r["warnings"] if i["code"].startswith("requirement")], r


def _doc(*reqs, nodes=(), nets=()) -> dict:
    return {"requirements": [{"id": f"R{i + 1}", "text": t, "parts": p, "firmware": True} for i, (t, p) in enumerate(reqs)],
            "nodes": [C3, *nodes], "nets": list(nets)}


SLEEPY = _doc(("battery powered, deep sleep between readings", ["U1"]))


async def test_sleep_must_be_reached(no_gxx):
    async def sleep(code):
        r = await fc.check(SLEEPY, {"a.ino": code}, "arduino")
        return codes(r, "requirement_sleep")

    assert not await sleep("void nap(){ esp_deep_sleep_start(); }\nvoid setup(){}\nvoid loop(){ if (millis() > 1) nap(); }\n")
    assert not await sleep("void setup(){ esp_sleep_enable_timer_wakeup(1000000ULL); esp_deep_sleep_start(); }\nvoid loop(){}\n")
    off = await sleep("void setup(){}\nvoid loop(){\n#if 0\n  esp_deep_sleep_start();\n#endif\n}\n")
    assert off and "a.ino:4 is under #if 0" in off[0]["msg"]
    assert not await sleep("void setup(){}\nvoid loop(){\n#if 0\n#else\n  esp_deep_sleep_start();\n#endif\n}\n")
    lone = await sleep("void nap(){ esp_deep_sleep_start(); }\nvoid setup(){}\nvoid loop(){}\n")
    assert lone and "in nap(), which nothing calls" in lone[0]["msg"]
    assert await sleep('void setup(){ Serial.println("esp_deep_sleep_start();"); }\nvoid loop(){}\n')
    py = await fc.check(SLEEPY, {"main.py": "import machine\nmachine.deepsleep(60000)\n"}, "micropython")
    assert not codes(py, "requirement_sleep")
    py = await fc.check(SLEEPY, {"main.py": "import machine\n# machine.deepsleep(60000)\n"}, "micropython")
    assert codes(py, "requirement_sleep") and "machine.deepsleep" in codes(py, "requirement_sleep")[0]["hint"]


def test_what_asks_for_sleep_or_a_fade():
    for t in ("Автономное питание LiPo, глубокий сон", "сон для экономии", "спящий режим", "засыпает через 30 с", "deep sleep after 30 s",
              "sleeps between readings", "battery-saving mode"):
        assert fc.asks_sleep(t), t
    for t in ("never sleeps: always on", "без сна, всегда включен", "работает не засыпая", "sleep timer turns the lamp off",
              "таймер сна на 30 минут", "measure the climate", "снаружи корпуса"):
        assert not fc.asks_sleep(t), t
    for t in ("плавное затухание", "Плавно включается", "fades in and out", "smooth dimming", "dimmable warm light"):
        assert fc.asks_fade(t), t
    for t in ("a status LED blinks", "автовыключение по таймеру", "fadeless"):
        assert not fc.asks_fade(t), t


async def test_fade_needs_a_changing_level(no_gxx):
    fade = _doc(("the light fades out", ["U1"]))

    async def fades(code):
        r = await fc.check(fade, {"a.ino": code}, "arduino")
        return not codes(r, "requirement_fade")

    assert await fades("void setup(){ ledcAttach(3, 5000, 8); }\nvoid loop(){ for (int v = 255; v >= 0; v--) { ledcWrite(3, v); delay(4); } }\n")
    assert await fades("int level = 0;\nvoid setup(){}\nvoid loop(){ int d = (millis() / 10) % 256; analogWrite(3, d); }\n")
    assert await fades("void setLevel(int b){ ledcWrite(3, b); }\nvoid setup(){}\nvoid loop(){ setLevel(10); }\n")
    assert await fades("#include <FastLED.h>\nCRGB leds[4];\nvoid setup(){}\nvoid loop(){ fadeToBlackBy(leds, 4, 20); FastLED.show(); }\n")
    assert not await fades("void setup(){ ledcAttach(3, 5000, 8); }\nvoid loop(){ ledcWrite(3, 255); delay(1000); ledcWrite(3, 0); }\n")
    assert not await fades("void setup(){}\nvoid loop(){\n  // fade out: for (v...) ledcWrite(3, v--);\n  analogWrite(3, 0);\n}\n")
    py = await fc.check(fade, {"main.py": "from machine import Pin, PWM\np = PWM(Pin(3))\nfor d in range(0, 65535, 512):\n    p.duty_u16(d)\n"},
                        "micropython")
    assert not codes(py, "requirement_fade")


async def test_a_firmware_requirement_whose_pins_the_code_never_touches(no_gxx):
    doc = _doc(("a button to snooze the alarm", ["SW1"]), ("a status light", ["LED1"]),
               nodes=[{"id": "SW1", "kind": "button"}, {"id": "LED1", "kind": "led"}, {"id": "R1", "kind": "resistor", "value": "1k"}],
               nets=[{"name": "GND", "pins": ["U1.GND", "SW1.B", "LED1.K"]}, {"pins": ["U1.D1", "SW1.A"]}, {"pins": ["U1.D2", "R1.1"]},
                     {"pins": ["R1.2", "LED1.A"]}])
    r = await fc.check(doc, {"a.ino": "#define LED D2\nvoid setup(){ pinMode(LED, OUTPUT); }\nvoid loop(){ digitalWrite(LED, HIGH); }\n"},
                       "arduino")
    w = codes(r, "requirement_pins")
    assert len(w) == 1 and w[0] in r["warnings"] and "R1" in w[0]["msg"] and "D1 (GPIO3)" in w[0]["msg"] and "SW1" in w[0]["msg"]


async def test_the_stored_check_is_redone_when_the_requirements_change(monkeypatch):
    seen = []

    async def check(doc, fw):
        seen.append(doc.get("requirements"))
        return {"ok": True, "errors": [], "warnings": [], "wiring": device_tools.wiring(doc), "asks": device_tools.asks(doc)}

    monkeypatch.setattr(device_tools, "firmware_check", check)
    doc = _doc(("a light", ["U1"]))
    fw = {"files": {"a.ino": "void setup(){}\nvoid loop(){}\n"}}
    fw["check"] = await check(doc, fw)
    state = DesignState(pack="device")
    assert await device_tools.check_now(state, doc, fw) is fw["check"] and len(seen) == 1
    doc2 = _doc(("a light", ["U1"]), ("deep sleep after a minute", ["U1"]))
    await device_tools.check_now(state, doc2, fw)
    assert len(seen) == 2 and len(seen[-1]) == 2
