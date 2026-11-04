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
    res = await _sim(doc, "#include <Preferences.h>\nPreferences p; void setup(){p.begin(\"a\",false);pinMode(D3,OUTPUT);} void loop(){delay(10);}")
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
