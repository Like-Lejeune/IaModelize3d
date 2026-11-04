"""The virtual board (firmware_sim): each defect it exists for, broken and fixed, on small devices with no catalogue parts."""
from __future__ import annotations

import pytest

pytest.importorskip("ziglang")
pytest.importorskip("wasmtime")

from formwright import device, device_rules, firmware_sim as fs  # noqa: E402

XIAO = {"id": "U1", "kind": "module", "module": "113991054"}
CELL = {"id": "BT1", "kind": "accessory", "accessory": "lipo_1s_500"}


def _doc(nodes: list[dict], nets: list[list[str]], requirements: list[dict] | None = None) -> dict:
    doc = {"schema": "fw.device/1", "title": "t", "nodes": [XIAO, *nodes], "nets": [{"pins": n} for n in nets]}
    norm, _ = device.normalize(doc)
    if requirements:
        norm["requirements"] = requirements
    return norm


async def _sim(doc: dict, code: str) -> dict:
    res = await fs.simulate(doc, {}, {"a.ino": code}, "arduino")
    assert res["ran"], res.get("why")
    return res


def _codes(res: dict, severity: str = "error") -> set[str]:
    return {f["code"] for f in res["findings"] if f["severity"] == severity}


LEAK_NODES = [
    {"id": "PR1", "kind": "accessory", "accessory": "leak_probe", "edge": "+y"},
    {"id": "SW1", "kind": "button"},
    {"id": "LED1", "kind": "led", "color": "red"},
    {"id": "R1", "kind": "resistor", "value": "1k"},
    {"id": "R2", "kind": "resistor", "value": "100k"},
    CELL,
]
LEAK_NETS = [["U1.GND", "PR1.GND", "SW1.B", "LED1.K"], ["U1.V3V3", "R2.1"], ["U1.D1", "PR1.SENSE", "R2.2"], ["U1.D2", "SW1.A"], ["U1.D3", "R1.1"], ["R1.2", "LED1.A"]]
LEAK_BROKEN = """
void setup() {
  pinMode(D1, INPUT); pinMode(D2, INPUT_PULLUP); pinMode(D3, OUTPUT);
  if (digitalRead(D1) == LOW) {
    unsigned long t0 = millis();
    while (millis() - t0 < 60000UL && digitalRead(D1) == LOW && digitalRead(D2) == HIGH) {
      digitalWrite(D3, HIGH); delay(300); digitalWrite(D3, LOW); delay(300);
    }
  }
  esp_deep_sleep_enable_gpio_wakeup((1ULL << 3) | (1ULL << 4), ESP_GPIO_WAKEUP_GPIO_LOW);
  esp_deep_sleep_start();
}
void loop() {}
"""
LEAK_FIXED = """
RTC_DATA_ATTR bool reported = false;
void setup() {
  pinMode(D1, INPUT); pinMode(D2, INPUT_PULLUP); pinMode(D3, OUTPUT);
  bool wet = digitalRead(D1) == LOW;
  if (!wet) reported = false;
  if (wet && !reported) {
    unsigned long t0 = millis();
    while (millis() - t0 < 60000UL && digitalRead(D1) == LOW && digitalRead(D2) == HIGH) {
      digitalWrite(D3, HIGH); delay(300); digitalWrite(D3, LOW); delay(300);
    }
    reported = true;
  }
  // still wet: only the button or the timer wakes it, then it looks again
  uint64_t mask = (1ULL << 4) | (digitalRead(D1) == LOW ? 0 : (1ULL << 3));
  esp_deep_sleep_enable_gpio_wakeup(mask, ESP_GPIO_WAKEUP_GPIO_LOW);
  if (digitalRead(D1) == LOW) esp_sleep_enable_timer_wakeup(600ULL * 1000000ULL);
  esp_deep_sleep_start();
}
void loop() {}
"""


async def test_a_wake_level_still_active_is_found_and_the_fix_is_clean():
    doc = _doc(LEAK_NODES, LEAK_NETS)
    res = await _sim(doc, LEAK_BROKEN)
    assert "sim_sleep_rearms" in _codes(res)
    assert "PR1" in next(f["msg"] for f in res["findings"] if f["code"] == "sim_sleep_rearms")
    fixed = await _sim(doc, LEAK_FIXED)
    assert "sim_sleep_rearms" not in _codes(fixed), fixed["findings"]
    assert fixed["effects"]["PR1"] == ["LED1"]


SOIL_NODES = [{"id": "PR1", "kind": "accessory", "accessory": "soil_capacitive_v12", "edge": "+y"}, {"id": "LED1", "kind": "led", "color": "green"},
              {"id": "R1", "kind": "resistor", "value": "1k"}, {"id": "BT1", "kind": "accessory", "accessory": "lipo_1s_1000"}]
SOIL_CODE = """
void setup() {
  pinMode(D10, OUTPUT); %s
  delay(100);
  bool dry = analogRead(D1) > 2500;
  digitalWrite(D10, dry); delay(3000); digitalWrite(D10, LOW);
  %s
  esp_sleep_enable_timer_wakeup(1800ULL * 1000000ULL);
  esp_deep_sleep_start();
}
void loop() {}
"""


async def test_a_part_left_on_in_sleep_is_the_battery_life():
    always = _doc(SOIL_NODES, [["U1.GND", "PR1.GND", "LED1.K"], ["U1.V3V3", "PR1.VCC"], ["U1.D1", "PR1.AOUT"], ["U1.MOSI", "R1.1"], ["R1.2", "LED1.A"]])
    res = await _sim(always, SOIL_CODE % ("", ""))
    assert "sim_sleep_draw" in _codes(res)
    assert res["power"]["sleep_ma"] > 5 and 150 < res["power"]["idle_life_h"] < 250     # 1000 mAh at about 5 mA
    assert res["power"]["sleep_top"][0]["part"] == "PR1"
    # the probe on a GPIO, on only while it is read
    gated = _doc(SOIL_NODES, [["U1.GND", "PR1.GND", "LED1.K"], ["U1.D2", "PR1.VCC"], ["U1.D1", "PR1.AOUT"], ["U1.MOSI", "R1.1"], ["R1.2", "LED1.A"]])
    fixed = await _sim(gated, SOIL_CODE % ("pinMode(D2, OUTPUT); digitalWrite(D2, HIGH);", "digitalWrite(D2, LOW);"))
    assert "sim_sleep_draw" not in _codes(fixed)
    assert fixed["power"]["sleep_ma"] < 0.1
    assert fixed["effects"]["PR1"] == ["LED1"], fixed["findings"]        # a gated probe still reads, wet from dry


BLINK = [{"id": "LED1", "kind": "led", "color": "red"}, {"id": "R1", "kind": "resistor", "value": "1k"}]


async def test_a_reversed_led_is_dead_whatever_the_firmware_does():
    doc = _doc(BLINK, [["U1.D3", "R1.1"], ["R1.2", "LED1.K"], ["U1.GND", "LED1.A"]])
    res = await _sim(doc, "void setup(){pinMode(D3,OUTPUT);} void loop(){digitalWrite(D3,HIGH);delay(500);digitalWrite(D3,LOW);delay(500);}")
    dead = next(f for f in res["findings"] if f["code"] == "sim_output_dead")
    assert dead["ref"] == "LED1" and "no pin" in dead["msg"]


async def test_a_pin_never_made_an_output():
    doc = _doc(BLINK, [["U1.D3", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]])
    res = await _sim(doc, "void setup(){} void loop(){digitalWrite(D3,HIGH);delay(500);digitalWrite(D3,LOW);delay(500);}")
    assert "sim_output_dead" in _codes(res)
    ok = await _sim(doc, "void setup(){pinMode(D3,OUTPUT);} void loop(){digitalWrite(D3,HIGH);delay(500);digitalWrite(D3,LOW);delay(500);}")
    assert not _codes(ok), ok["findings"]


BUTTON_LED = [{"id": "SW1", "kind": "button"}, *BLINK]
BUTTON_NETS = [["U1.GND", "SW1.B", "LED1.K"], ["U1.D1", "SW1.A"], ["U1.D3", "R1.1"], ["R1.2", "LED1.A"]]
BUTTON_REQ = [{"id": "R1", "text": "button lights the LED", "parts": ["SW1", "LED1"], "firmware": True}]


async def test_a_floating_input_and_an_input_that_does_nothing():
    doc = _doc(BUTTON_LED, BUTTON_NETS, BUTTON_REQ)
    floating = await _sim(doc, "void setup(){pinMode(D1,INPUT);pinMode(D3,OUTPUT);} void loop(){digitalWrite(D3,digitalRead(D1)==LOW);delay(10);}")
    assert "sim_float_read" in _codes(floating)
    ignored = await _sim(doc, "void setup(){pinMode(D1,INPUT_PULLUP);pinMode(D3,OUTPUT);digitalWrite(D3,HIGH);} void loop(){delay(10);}")
    assert "sim_input_no_effect" in _codes(ignored)
    good = await _sim(doc, "void setup(){pinMode(D1,INPUT_PULLUP);pinMode(D3,OUTPUT);} void loop(){digitalWrite(D3,digitalRead(D1)==LOW);delay(10);}")
    assert not _codes(good), good["findings"]
    assert good["effects"]["SW1"] == ["LED1"]


async def test_a_hang_is_not_a_long_run():
    doc = _doc(BLINK, [["U1.D3", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]])
    res = await _sim(doc, "volatile int x=0; void setup(){pinMode(D3,OUTPUT);digitalWrite(D3,HIGH);} void loop(){ if(millis()>2000){ for(;;){x++;} } delay(1);}")
    assert "sim_hang" in _codes(res)


async def test_a_call_with_no_model_says_so_and_judges_nothing_after_it():
    doc = _doc(BLINK, [["U1.D3", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]])
    res = await _sim(doc, "#include <Ticker.h>\nTicker p; void tick(){} void setup(){p.attach(1.0f, tick);pinMode(D3,OUTPUT);} void loop(){delay(10);}")
    assert "sim_not_modelled" in _codes(res, "warning")
    assert "sim_output_dead" not in _codes(res)


async def test_rtc_memory_survives_sleep_and_ordinary_memory_does_not():
    doc = _doc(BLINK, [["U1.D3", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]])
    code = """
RTC_DATA_ATTR int kept = 0; int lost = 0;
void setup(){ Serial.begin(115200); kept++; lost++; Serial.printf("kept=%d lost=%d cause=%d\\n", kept, lost, (int)esp_sleep_get_wakeup_cause());
  pinMode(D3,OUTPUT); digitalWrite(D3,HIGH); delay(100); digitalWrite(D3,LOW);
  esp_sleep_enable_timer_wakeup(10ULL*1000000ULL); esp_deep_sleep_start(); }
void loop(){}
"""
    res = await fs.try_scenario(doc, {}, {"a.ino": code}, [], horizon=35.0)
    assert res["ran"]
    assert [s.split(": ", 1)[1] for s in res["serial"][:3]] == ["kept=1 lost=1 cause=0", "kept=2 lost=1 cause=4", "kept=3 lost=1 cause=4"]


async def test_flash_outlives_a_boot():
    doc = _doc(BLINK, [["U1.D3", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]])
    code = """
#include <Preferences.h>
#include <EEPROM.h>
Preferences p;
void setup(){ Serial.begin(115200); p.begin("a", false); int n = p.getInt("n", 0) + 1; p.putInt("n", n); p.putString("s", "x");
  EEPROM.begin(16); uint8_t e = EEPROM.read(3); EEPROM.write(3, e == 0xff ? 1 : e + 1); EEPROM.commit();
  Serial.printf("n=%d s=%s e=%d\\n", n, p.getString("s", "?").c_str(), EEPROM.read(3));
  esp_sleep_enable_timer_wakeup(10ULL*1000000ULL); esp_deep_sleep_start(); }
void loop(){}
"""
    res = await fs.try_scenario(doc, {}, {"a.ino": code}, [], horizon=25.0)
    assert res["ran"] and [x.split(": ", 1)[1] for x in res["serial"][:2]] == ["n=1 s=x e=1", "n=2 s=x e=2"], res


async def test_a_contact_that_reads_undefined_is_an_error_and_one_pull_fixes_it():
    doc = _doc(LEAK_NODES, LEAK_NETS)
    both = await _sim(doc, LEAK_FIXED.replace("pinMode(D1, INPUT);", "pinMode(D1, INPUT_PULLUP);"))
    assert next(f for f in both["findings"] if f["code"] == "sim_mid_level")["severity"] == "error"
    one = await _sim(doc, LEAK_FIXED)
    assert "sim_mid_level" not in _codes(one) | _codes(one, "warning"), one["findings"]


OLED13 = [{"id": "DS1", "kind": "accessory", "accessory": "oled_13_i2c"}, {"id": "SW1", "kind": "button"}]
OLED13_NETS = [["U1.GND", "DS1.GND", "SW1.B"], ["U1.V3V3", "DS1.VCC"], ["U1.SDA", "DS1.SDA"], ["U1.SCL", "DS1.SCL"], ["U1.D1", "SW1.A"]]


async def test_the_other_oled_family_shows_and_answers():
    code = """
#include <Adafruit_SH110X.h>
Adafruit_SH1106G d(128, 64, &Wire, -1); int n = 0; bool prev = HIGH;
void setup(){ pinMode(D1, INPUT_PULLUP); Wire.begin(); d.begin(0x3C, true); }
void loop(){ bool b = digitalRead(D1); if (b == LOW && prev == HIGH) n++; prev = b; d.clearDisplay(); d.setCursor(0, 0); d.print("n="); d.print(n); d.display(); delay(50); }
"""
    res = await _sim(_doc(OLED13, OLED13_NETS), code)
    assert not res["coverage"]["not_modelled"] and not _codes(res), res["findings"]
    assert res["effects"]["SW1"] == ["screen"]


TIMER_NODES = [{"id": "DS1", "kind": "accessory", "accessory": "oled_096_i2c"}, {"id": "SW1", "kind": "button"}]
TIMER_NETS = [["U1.GND", "DS1.GND", "SW1.B"], ["U1.V3V3", "DS1.VCC"], ["U1.SDA", "DS1.SDA"], ["U1.SCL", "DS1.SCL"], ["U1.D1", "SW1.A"]]
TIMER_CODE = """
#include <Adafruit_SSD1306.h>
Adafruit_SSD1306 d(128, 64, &Wire, -1);
long left = 300000; bool running = false, prev = HIGH; unsigned long last = 0;
void setup(){ pinMode(D1, INPUT_PULLUP); Wire.begin(); d.begin(SSD1306_SWITCHCAPVCC, 0x3C); }
void loop(){
  bool b = digitalRead(D1);
  if (b == LOW && prev == HIGH) { %s }
  prev = b;
  unsigned long now = millis();
  if (running) left -= now - last;
  last = now;
  long s = (left + 999) / 1000;
  char t[12]; snprintf(t, sizeof t, "%%02ld:%%02ld", s / 60, s %% 60);
  d.clearDisplay(); d.setCursor(0, 0); d.print(t); d.display(); delay(100);
}
"""
PAUSE_TEST = {"steps": [{"at_s": 5, "press": "SW1"}, {"at_s": 25, "press": "SW1"}, {"at_s": 40, "press": "SW1"}],
              "expect": [{"at_s": 35, "screen": "04:4"}, {"at_s": 50, "screen": "04:3"}]}
PAUSE_REQ = [{"id": "R1", "text": "stop keeps the time, start goes on from it", "parts": ["SW1", "DS1"], "firmware": True, "test": PAUSE_TEST}]


async def test_a_requirement_test_catches_a_pause_that_starts_over():
    doc = _doc(TIMER_NODES, TIMER_NETS, PAUSE_REQ)
    broken = await _sim(doc, TIMER_CODE % "running = !running; if (!running) left = 300000;")
    f = next(x for x in broken["findings"] if x["code"] == "sim_requirement_failed")
    assert f["ref"] == "R1" and "05:00" in f["msg"]
    assert broken["requirements"] == [{"id": "R1", "status": "failed", "why": broken["requirements"][0]["why"]}]
    fixed = await _sim(doc, TIMER_CODE % "running = !running;")
    assert not _codes(fixed), fixed["findings"]
    assert fixed["requirements"] == [{"id": "R1", "status": "passed"}]
    assert fixed["coverage"]["tests"] == {"passed": 1}


def test_a_test_keeps_what_it_checked_and_says_when_it_was_changed():
    from types import SimpleNamespace

    from formwright.agent import device_tools as dt

    sleep = {"expect": [{"from_s": 35, "to_s": 40, "asleep": True}]}
    doc = _doc(BUTTON_LED, BUTTON_NETS, [{"id": "R3", "text": "sleeps after 30 s", "parts": ["SW1"], "firmware": True, "test": sleep}])
    state = SimpleNamespace(self_check={})
    dt.note_tests(state, doc, {"requirements": [{"id": "R3", "status": "failed"}]})
    assert not dt.weakened_tests(state, doc) and not dt.changed_tests(state, doc)
    # later: the same thing at another moment is fine, and the person hears the test changed
    doc["requirements"][0]["test"] = {"expect": [{"from_s": 50, "to_s": 60, "asleep": True}]}
    assert not dt.weakened_tests(state, doc) and dt.changed_tests(state, doc) == ["R3"]
    # a sleep requirement that ends up checking a LED is not
    doc["requirements"][0]["test"] = {"steps": [{"at_s": 45, "press": "SW1"}], "expect": [{"from_s": 45, "to_s": 52, "output": "LED1"}]}
    assert "no longer checks the chip asleep" in dt.weakened_tests(state, doc)[0]
    # a part that left the device takes its check with it
    doc["requirements"][0]["test"] = sleep
    dt.note_tests(state, doc, {"requirements": [{"id": "R3", "status": "passed"}]})
    state.self_check["test_pins"]["R3"].append("GONE1 on")
    assert not dt.weakened_tests(state, doc)


async def test_finish_asks_once_for_the_tests_of_firmware_requirements():
    from types import SimpleNamespace

    from formwright.agent import device_tools as dt

    doc = _doc(BUTTON_LED, BUTTON_NETS, [{"id": "R1", "text": "lights", "parts": ["LED1"], "firmware": True}])
    fw = {"lang": "arduino", "files": {"a.ino": "x"}}
    fw["sim"] = {"ran": True, "ok": True, "findings": [], "requirements": [{"id": "R1", "status": "no_test"}], "key": dt.sim_key(doc, fw)}
    state = SimpleNamespace(self_check={}, device={})
    first = await dt.simulation_problems(state, doc, fw)
    assert len(first) == 1 and first[0].startswith("R1 have firmware work and no test")
    assert await dt.simulation_problems(state, doc, fw) == []


async def test_an_analog_probe_takes_its_two_states_or_millivolts():
    nodes = [{"id": "PR1", "kind": "accessory", "accessory": "soil_capacitive_v12", "edge": "+y"}]
    nets = [["U1.GND", "PR1.GND"], ["U1.V3V3", "PR1.VCC"], ["U1.D1", "PR1.AOUT"]]
    c = fs.Circuit(_doc(nodes, nets), {})
    read = lambda v: c.thevenin(3, {"PR1": v}, {})[0]  # noqa: E731
    assert read(0) == pytest.approx(1200, abs=30) and read(1) == pytest.approx(2500, abs=30) and read(1800) == pytest.approx(1800, abs=30)


async def test_a_test_that_passes_without_its_steps_proves_nothing():
    req = [{"id": "R1", "text": "shows the time", "parts": ["DS1"], "firmware": True,
            "test": {"steps": [{"at_s": 5, "press": "SW1"}], "expect": [{"from_s": 6, "to_s": 8, "output": "DS1", "on": True}]}}]
    res = await _sim(_doc(TIMER_NODES, TIMER_NETS, req), TIMER_CODE % "running = !running;")
    assert "sim_test_vacuous" in _codes(res)
    # a test of what must not happen has nothing to compare
    req[0]["test"] = {"steps": [{"at_s": 5, "press": "SW1"}], "expect": [{"from_s": 6, "to_s": 8, "not_screen": "99:99"}]}
    assert "sim_test_vacuous" not in _codes(await _sim(_doc(TIMER_NODES, TIMER_NETS, req), TIMER_CODE % "running = !running;"))


async def test_a_test_that_cannot_be_played_says_why_and_a_missing_one_is_counted():
    for bad, word in (({"steps": [{"at_s": 1, "press": "NOPE"}], "expect": [{"at_s": 2, "screen": "x"}]}, "SW1"),
                      ({"expect": [{"at_s": 2, "output": "NOPE"}]}, "DS1"), ({"steps": []}, "expect")):
        req = [{"id": "R1", "text": "t", "parts": ["DS1"], "firmware": True, "test": bad}]
        res = await _sim(_doc(TIMER_NODES, TIMER_NETS, req), TIMER_CODE % "running = !running;")
        assert word in next(f["msg"] for f in res["findings"] if f["code"] == "sim_test_invalid")
    req = [{"id": "R1", "text": "t", "parts": ["DS1"], "firmware": True}, {"id": "R2", "text": "charges", "parts": ["DS1"], "firmware": False}]
    res = await _sim(_doc(TIMER_NODES, TIMER_NETS, req), TIMER_CODE % "running = !running;")
    assert res["requirements"] == [{"id": "R1", "status": "no_test"}]


async def test_the_chip_asleep_and_a_window_of_beeps():
    req = [{"id": "R1", "text": "blinks on press, then sleeps", "parts": ["LED1"], "firmware": True,
            "test": {"steps": [{"at_s": 3, "press": "SW1"}], "expect": [{"from_s": 4, "to_s": 6, "output": "LED1", "on": True}, {"from_s": 8, "to_s": 12, "output": "LED1", "on": False},
                                                                        {"at_s": 15, "asleep": True}, {"at_s": 2, "asleep": False}]}}]
    code = """
void setup(){ pinMode(D1, INPUT_PULLUP); pinMode(D3, OUTPUT); }
void loop(){ if (digitalRead(D1) == LOW) { for (int i = 0; i < 10; i++) { digitalWrite(D3, HIGH); delay(200); digitalWrite(D3, LOW); delay(200); }
    esp_deep_sleep_enable_gpio_wakeup(1ULL << 3, ESP_GPIO_WAKEUP_GPIO_LOW); delay(3000); esp_deep_sleep_start(); } delay(10); }
"""
    res = await _sim(_doc(BUTTON_LED, BUTTON_NETS, req), code)
    assert res["requirements"] == [{"id": "R1", "status": "passed"}], res["findings"]


async def test_a_scenario_of_ones_own_sees_a_sequence():
    doc = _doc(BUTTON_LED, BUTTON_NETS)
    code = "bool on=false,prev=HIGH; void setup(){pinMode(D1,INPUT_PULLUP);pinMode(D3,OUTPUT);} void loop(){bool b=digitalRead(D1); if(b==LOW&&prev==HIGH){on=!on;digitalWrite(D3,on);} prev=b; delay(20);}"
    res = await fs.try_scenario(doc, {}, {"a.ino": code}, [{"at_s": 5, "input": "SW1", "value": 1}, {"at_s": 5.2, "input": "SW1", "value": 0},
                                                           {"at_s": 15, "input": "SW1", "value": 1}, {"at_s": 15.2, "input": "SW1", "value": 0}], horizon=30)
    assert 9.5 < res["on_s"]["LED1"] < 10.5
    bad = await fs.try_scenario(doc, {}, {"a.ino": code}, [{"at_s": 5, "input": "NOPE"}])
    assert not bad["ran"] and "SW1" in bad["why"]


async def test_the_sketch_cannot_read_the_server():
    doc = _doc(BLINK, [["U1.D3", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]])
    for code in ('asm(".incbin \\"/etc/passwd\\"");\nvoid setup(){} void loop(){delay(1);}',
                 '#define A a##sm\nA(".incbin \\"x\\"");\nvoid setup(){} void loop(){delay(1);}',
                 '#include "/etc/passwd"\nvoid setup(){} void loop(){delay(1);}',
                 '#include "../secret.h"\nvoid setup(){} void loop(){delay(1);}'):
        res = await fs.simulate(doc, {}, {"a.ino": code}, "arduino")
        assert not res["ran"], code


async def test_no_simulator_is_not_a_pass():
    doc = _doc(BLINK, [["U1.D3", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]])
    res = await fs.simulate(doc, {}, {"main.py": "print(1)"}, "micropython")
    assert res["ran"] is False and res["why"]


def test_a_circuit_solves_as_ohm_says():
    doc = _doc(BLINK, [["U1.D3", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]])
    c = fs.Circuit(doc, {})
    assert abs(c.solve({}, {5: 2})["loads"]["LED1"] - (3.3 - 1.9) / 1040 * 1000) < 0.1
    assert c.solve({}, {5: 1})["loads"]["LED1"] == 0


def test_a_cell_leaves_v5_dead():
    nodes = [*BLINK, CELL]
    doc = _doc(nodes, [["U1.V5", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]])
    assert fs.Circuit(doc, {}).solve({}, {})["loads"]["LED1"] == 0
    usb = _doc(BLINK, [["U1.V5", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]])
    assert fs.Circuit(usb, {}).solve({}, {})["loads"]["LED1"] > 2


def test_an_led_of_the_colour_it_is_said_to_be():
    nodes = [{"id": "LED1", "kind": "led", "color": "green", "label": "тёплый свет 1"}, {"id": "R1", "kind": "resistor", "value": "100R"}]
    nets = [["U1.D3", "R1.1"], ["R1.2", "LED1.A"], ["U1.GND", "LED1.K"]]
    assert any(f["code"] == "led_colour" for f in device_rules.check(_doc(nodes, nets), {}))
    nodes[0]["label"] = "status"
    plain = _doc(nodes, nets, [{"id": "R1", "text": "тёплый свет с плавным включением", "parts": ["LED1"], "firmware": True}])
    assert any(f["code"] == "led_colour" for f in device_rules.check(plain, {}))
    nodes[0]["label"] = "зелёный индикатор"
    assert not any(f["code"] == "led_colour" for f in device_rules.check(_doc(nodes, nets), {}))


def test_battery_claims_are_read_from_battery_sentences_only():
    said = fs.battery_claims("Прогрев 30 с. Батареи хватит на 1–2 месяца; калибровку проверить. Свет горит 2 часа после движения. in standby 4 months")
    assert [h for _, h in said] == [1440.0, 2880.0]


# ---------------------------------------------------------------- the libraries behind the accessory library
SW = {"id": "SW1", "kind": "button"}


def _s3(doc: dict) -> dict:
    next(n for n in doc["nodes"] if n["kind"] == "module")["module"] = "113991114"
    return doc


async def test_an_epaper_frame_is_seen_on_screen_and_takes_its_seconds():
    doc = _doc([SW, {"id": "DS1", "kind": "accessory", "accessory": "epaper_29", "edge": "+x"}],
               [["U1.GND", "SW1.B", "DS1.GND"], ["U1.V3V3", "DS1.VCC"], ["U1.D1", "SW1.A"], ["U1.MOSI", "DS1.SDI"], ["U1.SCK", "DS1.SCK"], ["U1.D2", "DS1.CS"], ["U1.D3", "DS1.DC"], ["U1.D0", "DS1.RES"], ["U1.TX", "DS1.BUSY"]],
               [{"id": "R1", "text": "кнопка рисует", "parts": ["SW1", "DS1"], "firmware": True,
                 "test": {"steps": [{"at_s": 3, "press": "SW1"}], "expect": [{"at_s": 8, "screen": "HELLO"}]}}])
    code = """#include <GxEPD2_BW.h>
#include <Fonts/FreeMonoBold9pt7b.h>
GxEPD2_BW<GxEPD2_290_T94_V2, GxEPD2_290_T94_V2::HEIGHT> display(GxEPD2_290_T94_V2(D2, D3, D0, TX));
void setup() { pinMode(D1, INPUT_PULLUP); display.init(115200); display.setRotation(1); display.setFont(&FreeMonoBold9pt7b); }
void loop() {
  if (digitalRead(D1) == LOW) {
    display.setFullWindow();
    display.firstPage();
    do { display.fillScreen(GxEPD_WHITE); display.setCursor(5, 20); display.print("HELLO"); } while (display.nextPage());
    display.hibernate();
    delay(500);
  }
  delay(20);
}
"""
    res = await _sim(doc, code)
    assert res["ran"], res.get("why")
    assert not (res.get("coverage") or {}).get("not_modelled"), res["coverage"]
    assert [r["status"] for r in res["requirements"]] == ["passed"], res["requirements"]


async def test_a_ds18b20_reads_what_the_run_gives_it():
    doc = _doc([{"id": "PR1", "kind": "accessory", "accessory": "ds18b20_probe"}, {"id": "LED1", "kind": "led"}, {"id": "R1", "kind": "resistor", "value": "1k"}, {"id": "R2", "kind": "resistor", "value": "4.7k"}],
               [["U1.GND", "PR1.GND", "LED1.K"], ["U1.V3V3", "PR1.VCC", "R2.1"], ["U1.D1", "PR1.DQ", "R2.2"], ["U1.D2", "R1.1"], ["R1.2", "LED1.A"]],
               [{"id": "R1", "text": "греет ниже 20 C", "parts": ["PR1", "LED1"], "firmware": True,
                 "test": {"given": {"PR1": 10}, "expect": [{"from_s": 3, "to_s": 8, "output": "LED1", "on": True}]}},
                {"id": "R2", "text": "не греет выше 30 C", "parts": ["PR1", "LED1"], "firmware": True,
                 "test": {"given": {"PR1": 40}, "expect": [{"from_s": 3, "to_s": 8, "output": "LED1", "on": False}]}}])
    code = """#include <OneWire.h>
#include <DallasTemperature.h>
OneWire bus(D1);
DallasTemperature sensors(&bus);
void setup() { pinMode(D2, OUTPUT); sensors.begin(); }
void loop() { sensors.requestTemperatures(); digitalWrite(D2, sensors.getTempCByIndex(0) < 20 ? HIGH : LOW); delay(200); }
"""
    res = await _sim(doc, code)
    assert res["ran"], res.get("why")
    assert [r["status"] for r in res["requirements"]] == ["passed", "passed"], res["requirements"]


async def test_a_usb_key_counts_as_the_buttons_effect_and_files_read_back():
    doc = _s3(_doc([SW], [["U1.GND", "SW1.B"], ["U1.D1", "SW1.A"]]))
    code = """#include "USB.h"
#include "USBHIDKeyboard.h"
#include <SD.h>
USBHIDKeyboard Keyboard;
void setup() {
  pinMode(D1, INPUT_PULLUP); Keyboard.begin(); USB.begin(); Serial.begin(115200); SD.begin(D2);
  File f = SD.open("/a.txt", FILE_WRITE); f.print("hello"); f.close();
  f = SD.open("/a.txt"); Serial.println(f.readString()); f.close();
}
void loop() { if (digitalRead(D1) == LOW) { Keyboard.press(KEY_LEFT_CTRL); Keyboard.write('c'); Keyboard.releaseAll(); delay(200); } delay(10); }
"""
    res = await _sim(doc, code)
    assert res["ran"], res.get("why")
    assert "sim_input_no_effect" not in _codes(res, "warning") | _codes(res), res["findings"]
    assert not (res.get("coverage") or {}).get("not_modelled"), res["coverage"]


async def test_clock_tag_radio_scale_energy_and_stepper_compile_and_run():
    doc = _s3(_doc([SW], [["U1.GND", "SW1.B"], ["U1.D1", "SW1.A"]]))
    code = """#include <RTClib.h>
#include <MFRC522.h>
#include <TinyGPS++.h>
#include <LoRa.h>
#include <HX711.h>
#include <PZEM004Tv30.h>
#include <DFRobotDFPlayerMini.h>
#include <AccelStepper.h>
#include <TFT_eSPI.h>
#include <Adafruit_ST7789.h>
RTC_DS3231 rtc; MFRC522 rfid(D2, D3); TinyGPSPlus gps; HX711 scale; PZEM004Tv30 pzem(Serial1, D6, D7);
DFRobotDFPlayerMini mp3; AccelStepper motor(AccelStepper::DRIVER, D8, D9); TFT_eSPI tft; Adafruit_ST7789 st(D2, D3, D0);
void setup() {
  Serial.begin(115200); pinMode(D1, INPUT_PULLUP); rtc.begin(); rtc.adjust(DateTime(2026, 11, 4, 12, 0, 0)); rfid.PCD_Init();
  LoRa.setPins(D2, D3, D0); LoRa.begin(433E6); scale.begin(D2, D3); scale.set_scale(420.f); scale.tare(); mp3.begin(Serial1); motor.setMaxSpeed(500); motor.moveTo(10);
  tft.init(); st.init(240, 240); tft.fillScreen(TFT_BLACK); tft.drawString("OK", 0, 0, 2);
  Serial.println(rtc.now().hour()); Serial.println(gps.location.isValid() ? gps.location.lat() : 0.0); Serial.println(pzem.power()); Serial.println(scale.get_units(3));
}
void loop() {
  motor.run();
  if (digitalRead(D1) == LOW) { LoRa.beginPacket(); LoRa.print("call"); LoRa.endPacket(); mp3.play(1); delay(300); }
  if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) rfid.PICC_HaltA();
  delay(5);
}
"""
    res = await _sim(doc, code)
    assert res["ran"], res.get("why")
    assert not (res.get("coverage") or {}).get("not_modelled"), res["coverage"]
    assert "sim_input_no_effect" not in _codes(res, "warning") | _codes(res), res["findings"]


async def test_every_library_the_stubs_declare_links_in_the_simulator():
    doc = _s3(_doc([SW], [["U1.GND", "SW1.B"], ["U1.D1", "SW1.A"]]))
    code = """#include <SPI.h>
#include <SD.h>
#include <ESP32Servo.h>
#include <U8g2lib.h>
#include <LiquidCrystal_I2C.h>
#include <FastLED.h>
#include <DHT.h>
#include <Adafruit_MCP4725.h>
#include <Adafruit_INA219.h>
#include <Adafruit_ADS1X15.h>
#include <Adafruit_AHTX0.h>
#include <Adafruit_BMP280.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_LIS3DH.h>
Servo sv; U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0); LiquidCrystal_I2C lcd(0x27, 16, 2); CRGB leds[3]; DHT dht(D2, DHT22);
Adafruit_MCP4725 dac; Adafruit_INA219 ina; Adafruit_ADS1115 ads; Adafruit_AHTX0 aht; Adafruit_BMP280 bmp; Adafruit_MPU6050 mpu; Adafruit_LIS3DH lis;
int n = 0;
void setup() {
  Serial.begin(115200); pinMode(D1, INPUT_PULLUP); SPI.begin(D8, D9, D10, D3); SD.begin(D3);
  sv.setPeriodHertz(50); sv.attach(D6, 500, 2400); sv.write(45);
  u8g2.begin(); u8g2.clearBuffer(); u8g2.setFont(u8g2_font_6x13_t_cyrillic); u8g2.drawUTF8(0, 12, "OK"); u8g2.sendBuffer();
  lcd.init(); lcd.backlight(); lcd.setCursor(0, 1); lcd.print("LCD");
  FastLED.addLeds<WS2812B, D0, GRB>(leds, 3); leds[0] = CRGB::Red; FastLED.show();
  dht.begin(); Serial.println(dht.readTemperature()); dac.begin(); ina.begin(); ads.begin(); Serial.println(ina.getCurrent_mA());
  sensors_event_t h, t, a, g; aht.begin(); aht.getEvent(&h, &t); bmp.begin(); Serial.println(bmp.readPressure()); mpu.begin(); mpu.getEvent(&a, &g, &t); lis.begin(); lis.read();
}
void loop() {
  if (digitalRead(D1) == LOW) { dac.setVoltage(++n * 100, false); sv.write(n % 2 ? 0 : 90); delay(200); }
  delay(5);
}
"""
    res = await _sim(doc, code)
    assert res["ran"], res.get("why")
    assert not (res.get("coverage") or {}).get("not_modelled"), res["coverage"]
    assert "sim_input_no_effect" not in _codes(res, "warning") | _codes(res), res["findings"]
