"""Firmware check (firmware_check.py, contract C3): the five devices of 2026-11-03 as stored (graph + firmware, fixtures in
tests/fixtures/firmware) give the verdicts they should have had, the IDE preprocessing maps errors back to the right
file and line, unknown libraries degrade to a warning, MicroPython is parsed and its pins checked, a sketch cannot make
the compiler read server files, and the check never raises. Compiles need g++ (skipped without it); the static checks
run either way."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from formwright import firmware_check as fc

FIX = Path(__file__).parent / "fixtures" / "firmware"
needs_gxx = pytest.mark.skipif(not fc.gxx(), reason="no g++ on this machine")
XIAO_C3 = {"nodes": [{"id": "U1", "kind": "module", "module": "113991054"}], "nets": []}


def fixture(name: str) -> tuple[dict, dict, str]:
    doc = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["doc"]
    return doc, doc["firmware"]["files"], doc["firmware"]["lang"]


def codes(items: list[dict], code: str) -> list[dict]:
    return [i for i in items if i["code"] == code]


@pytest.fixture
def no_gxx(monkeypatch):
    monkeypatch.setattr(fc, "gxx", lambda: None)


# ------------------------------------------------------------------ the stored devices
@needs_gxx
async def test_dice_prose_line_and_leds_on_the_i2c_bus():
    doc, files, lang = fixture("dice")
    t = time.monotonic()
    r = await fc.check(doc, files, lang)
    assert time.monotonic() - t < 20
    assert not r["ok"] and r["tool"].startswith("g++")
    comp = codes(r["errors"], "compile")
    assert comp[0]["file"] == "dice.ino" and comp[0]["line"] == 47 and "QMA6100P" in comp[0]["msg"]
    assert "outside a comment" in comp[0]["hint"]
    conflicts = {e["line"]: e["msg"] for e in codes(r["errors"], "pin_conflict")}
    assert set(conflicts) == {9, 10}   # #define PIN_LED5 6, #define PIN_LED6 7
    assert "GPIO6" in conflicts[9] and "I2C" in conflicts[9] and "LED5 is wired to TX" in conflicts[9]
    assert "GPIO7" in conflicts[10] and "LED6 is wired to RX" in conflicts[10]
    unused = " ".join(w["msg"] for w in codes(r["warnings"], "pin_unused"))
    assert "GPIO21" in unused and "GPIO20" in unused and "LED5" in unused


@needs_gxx
async def test_soil_member_function_as_flag_and_cyrillic_on_ssd1306():
    r = await fc.check(*fixture("soil"))
    assert not r["ok"]
    comp = codes(r["errors"], "compile")
    assert [(e["line"], "ssd1306_command" in e["msg"]) for e in comp] == [(81, True)]
    assert "bool" in comp[0]["hint"]
    charset = codes(r["errors"], "display_charset")
    assert any("ПОЛЕЙ МЕНЯ!" in e["msg"] and e["line"] == 86 for e in charset)
    assert "u8g2_font_6x13_t_cyrillic" in charset[0]["hint"]
    assert codes(r["warnings"], "blocking_delay") and codes(r["warnings"], "stub")
    assert not codes(r["errors"], "pin_conflict") and not codes(r["errors"], "pin_unwired")


@needs_gxx
async def test_timer_compiles_but_prints_russian_on_the_oled():
    r = await fc.check(*fixture("timer"))
    assert not codes(r["errors"], "compile")
    charset = codes(r["errors"], "display_charset")
    assert charset and charset[0]["line"] == 33 and "ГОТОВО" in charset[0]["msg"]
    assert len(charset) <= 5   # many lines on one display fold into one item
    assert any("упрощено" in w["msg"] for w in codes(r["warnings"], "stub"))
    # buttons read through a helper's parameter still count as the wired pins
    assert not codes(r["warnings"], "pin_unused")


@needs_gxx
@pytest.mark.parametrize("name", ["leak", "nightlight"])
async def test_good_devices_pass(name):
    r = await fc.check(*fixture(name))
    assert r["ok"] and r["errors"] == [], r["errors"]
    assert not codes(r["warnings"], "pin_unused")


async def test_static_checks_without_a_compiler(no_gxx):
    r = await fc.check(*fixture("dice"))
    assert r["tool"] == "static only (no g++)"
    assert {e["line"] for e in codes(r["errors"], "pin_conflict")} == {9, 10}
    assert any(e["line"] == 47 for e in codes(r["errors"], "compile"))   # the prose line, found without g++
    r = await fc.check(*fixture("soil"))
    assert codes(r["errors"], "display_charset")


# ------------------------------------------------------------------ preprocessing, compile, mapping
@needs_gxx
async def test_prototypes_and_error_lines_across_ino_files():
    main = ("#include <Wire.h>\n"
            "struct Reading { int v; };\n"
            "void setup() {\n"
            "  Serial.begin(115200);\n"
            "  show(read(), 3);\n"        # both defined later: the generated prototypes make this legal
            "}\n"
            "void loop() { later(1); }\n"
            "Reading read() { Reading r{1}; return r; }\n"
            "void show(Reading r, int times = 1) { Serial.println(r.v * times); }\n")
    second = "void later(int v) {\n  Serial.println(v)\n}\n"
    r = await fc.check(XIAO_C3, {"main.ino": main, "b_second.ino": second}, "arduino")
    comp = codes(r["errors"], "compile")
    assert [(e["file"], e["line"]) for e in comp] == [("b_second.ino", 2)]
    assert "expected ';'" in comp[0]["msg"]


@needs_gxx
async def test_compile_errors_with_hints():
    src = ("int level(int x) {\n"
           "  if (x > 0) return x * 2;\n"
           "}\n"
           "void setup() {\n"
           "  digitalWirte(D0, HIGH);\n"
           "  String s = 5;\n"
           "  pinMode(LED_BUILTIN, OUTPUT);\n"
           "  esp_sleep_enable_ext0_wakeup(GPIO_NUM_2, 0);\n"
           "}\n"
           "void loop() {}\n")
    r = await fc.check(XIAO_C3, {"t.ino": src.replace("void setup", "#include <esp_sleep.h>\nvoid setup", 1)}, "arduino")
    by_line = {e["line"]: e for e in codes(r["errors"], "compile")}
    assert "control reaches end" in by_line[3]["msg"]
    assert "digitalWrite" in by_line[6]["msg"]
    assert "String(value)" in by_line[7]["hint"]
    assert "no user LED" in by_line[8]["hint"]
    assert "esp_deep_sleep_enable_gpio_wakeup" in by_line[9]["hint"]


@needs_gxx
async def test_leak_v6_timer_wakeup_compiles_ext0_does_not_on_c3():
    """p_979fb77173044e39 v6 called the sleep API without #include <esp_sleep.h>, as arduino-esp32 allows (esp32-hal.h
    brings it): the timer wake-up and deep sleep are fine on the C3, only ext0 (an S3/ESP32 source) is an error."""
    r = await fc.check(*fixture("leak_v6"))
    comp = codes(r["errors"], "compile")
    assert [e["line"] for e in comp] == [41, 62]
    assert all("esp_sleep_enable_ext0_wakeup" in e["msg"] and "esp_deep_sleep_enable_gpio_wakeup" in e["hint"] for e in comp)
    assert "timer wake-up works" in comp[0]["hint"]
    assert not any("timer_wakeup" in e["msg"] or "esp_deep_sleep_start" in e["msg"] for e in r["errors"])


CHIP_PROBE = """#include <WiFi.h>
#include <esp_now.h>
#include <esp_task_wdt.h>
#include "driver/rtc_io.h"
RTC_DATA_ATTR int boots = 0;
hw_timer_t *timer = nullptr;
portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
volatile int ticks = 0;
void IRAM_ATTR onTimer() { portENTER_CRITICAL_ISR(&mux); ticks++; portEXIT_CRITICAL_ISR(&mux); }
void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) { (void)info; (void)data; (void)len; }
void setup() {
  Serial.begin(115200);
  if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER) boots++;
  WiFi.setSleep(false); WiFi.setSleep(WIFI_PS_MIN_MODEM); esp_wifi_set_ps(WIFI_PS_NONE); WiFi.setTxPower(WIFI_POWER_8_5dBm);
  esp_now_init(); esp_now_register_recv_cb(onRecv);
  uint32_t mv = analogReadMilliVolts(D0); uint32_t r = esp_random(); float t = temperatureRead();
  ESP_LOGI("dev", "mv=%u r=%u t=%.1f", (unsigned)mv, (unsigned)r, t); log_i("boot %d", boots);
  ledcAttach(D1, 5000, 10); ledcWrite(D1, 512); ledcFade(D1, 0, 1023, 500);
  timer = timerBegin(1000000); timerAttachInterrupt(timer, &onTimer); timerAlarm(timer, 500000, true, 0);
  rgbLedWrite(D2, 10, 0, 0);
  gpio_hold_en(GPIO_NUM_3); gpio_deep_sleep_hold_en(); esp_task_wdt_reset();
  esp_sleep_enable_timer_wakeup(30ULL * 1000000ULL); esp_sleep_enable_gpio_wakeup();
#if SOC_GPIO_SUPPORT_DEEPSLEEP_WAKEUP
  esp_deep_sleep_enable_gpio_wakeup(1ULL << 3, ESP_GPIO_WAKEUP_GPIO_LOW);
#else
  esp_sleep_enable_ext0_wakeup(GPIO_NUM_3, 0); esp_sleep_enable_ext1_wakeup_io(1ULL << 4, ESP_EXT1_WAKEUP_ANY_LOW);
  rtc_gpio_pullup_en(GPIO_NUM_3); touch_value_t tv = touchRead(T1); (void)tv;
  esp_sleep_enable_touchpad_wakeup(); esp_sleep_enable_ulp_wakeup();
#endif
  esp_light_sleep_start();
  esp_deep_sleep_start();
}
void loop() {}
"""


@needs_gxx
@pytest.mark.parametrize("mpn", ["113991054", "113991114"])
async def test_each_chip_compiles_what_it_has(mpn):
    doc = {"nodes": [{"id": "U1", "kind": "module", "module": mpn}], "nets": []}
    r = await fc.check(doc, {"chip.ino": CHIP_PROBE}, "arduino")
    assert not codes(r["errors"], "compile"), codes(r["errors"], "compile")
    assert not codes(r["warnings"], "core_api") and not codes(r["warnings"], "library_unchecked")


@needs_gxx
async def test_c3_lacks_touch_rtcio_ext1_ulp_with_hints():
    src = ('#include "driver/rtc_io.h"\nvoid setup() {\n  esp_sleep_enable_timer_wakeup(1000000);\n  int v = touchRead(T1);\n'
           "  rtc_gpio_pullup_en(GPIO_NUM_3);\n  esp_sleep_enable_ext1_wakeup(1ULL << 3, ESP_EXT1_WAKEUP_ANY_HIGH);\n"
           "  esp_sleep_enable_ulp_wakeup();\n  timerBegin(0, 80, true);\n  esp_deep_sleep_start();\n}\nvoid loop() {}\n")
    r = await fc.check(XIAO_C3, {"b.ino": src}, "arduino")
    by_line = {e["line"]: e for e in codes(r["errors"], "compile")}
    assert set(by_line) == {4, 5, 6, 7}
    assert "no capacitive touch" in by_line[4]["hint"] and "did you mean" not in by_line[4]["msg"]
    assert "gpio_hold_en" in by_line[5]["hint"]
    assert "esp_deep_sleep_enable_gpio_wakeup" in by_line[6]["hint"]
    assert "ULP" in by_line[7]["hint"]
    assert codes(r["warnings"], "core_api")[0]["line"] == 8   # the 2.x timer API: builds here, not on core 3.x


@needs_gxx
async def test_missing_include_hint_names_the_header():
    src = "void setup() {\n  esp_wifi_set_ps(WIFI_PS_NONE);\n  esp_now_init();\n}\nvoid loop() {}\n"
    r = await fc.check(XIAO_C3, {"w.ino": src}, "arduino")
    hints = {e["line"]: e.get("hint", "") for e in codes(r["errors"], "compile")}
    assert "#include <WiFi.h>" in hints[2] and "#include <esp_now.h>" in hints[3]


@needs_gxx
async def test_unknown_library_degrades_to_a_warning():
    src = ("#include <WiFiManager.h>\n"
           "WiFiManager wm;\n"
           "void setup() {\n"
           "  bool ok = wm.autoConnect(\"Device\");\n"
           "  if (ok) digitalWirte(D0, HIGH);\n"
           "  wm.resetSettings();\n"
           "}\n"
           "void loop() {}\n")
    r = await fc.check(XIAO_C3, {"wm.ino": src}, "arduino")
    assert [(e["line"], "digitalWirte" in e["msg"]) for e in codes(r["errors"], "compile")] == [(5, True)]
    assert any("WiFiManager.h" in w["msg"] for w in codes(r["warnings"], "library_unchecked"))


@needs_gxx
async def test_common_libraries_compile_clean():
    src = ("#include <Wire.h>\n#include <U8g2lib.h>\n#include <Adafruit_NeoPixel.h>\n#include <ArduinoJson.h>\n#include <WebServer.h>\n"
           "#include <Preferences.h>\n#include <DHT.h>\n#include <ESP32Servo.h>\n"
           "U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);\n"
           "Adafruit_NeoPixel px(1, D2, NEO_GRB + NEO_KHZ800);\nWebServer server(80);\nPreferences prefs;\nDHT dht(D3, DHT22);\nServo servo;\n"
           "void setup() {\n"
           "  Wire.begin(SDA, SCL);\n  u8g2.begin();\n  u8g2.enableUTF8Print();\n  u8g2.setFont(u8g2_font_6x13_t_cyrillic);\n"
           "  u8g2.setCursor(0, 12);\n  u8g2.print(\"Привет\");\n  u8g2.sendBuffer();\n"
           "  px.begin();\n  px.setPixelColor(0, px.Color(255, 120, 40));\n  px.show();\n"
           "  server.on(\"/\", []() { JsonDocument d; d[\"t\"] = dht.readTemperature(); String out; serializeJson(d, out);"
           " server.send(200, \"application/json\", out); });\n"
           "  server.begin();\n  prefs.begin(\"cfg\");\n  servo.attach(D10, 500, 2400);\n  ledcAttach(D1, 2000, 8);\n"
           "}\n"
           "void loop() { server.handleClient(); ledcWriteTone(D1, millis() % 2 ? 1000 : 0); }\n")
    r = await fc.check(XIAO_C3, {"lib.ino": src}, "arduino")
    assert not codes(r["errors"], "compile") and not codes(r["errors"], "display_charset"), r["errors"]


async def test_u8g2_single_byte_draw_and_missing_utf8_print(no_gxx):
    src = ("#include <U8g2lib.h>\nU8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0);\n"
           "void setup() {\n  u8g2.begin();\n  u8g2.setFont(u8g2_font_ncenB08_tr);\n"
           "  u8g2.drawStr(0, 10, \"Привет\");\n  u8g2.print(\"Мир\");\n}\nvoid loop() {}\n")
    r = await fc.check(XIAO_C3, {"o.ino": src}, "arduino")
    charset = {e["line"]: e["msg"] for e in codes(r["errors"], "display_charset")}
    assert "single bytes" in charset[6] and "enableUTF8Print" in charset[7]


# ------------------------------------------------------------------ the graph
WIRED = {"nodes": [{"id": "U1", "kind": "module", "module": "113991054"}, {"id": "R1", "kind": "resistor"}, {"id": "LED1", "kind": "led"},
                   {"id": "SW1", "kind": "button"}, {"id": "J2", "kind": "header", "pins": ["V3V3", "GND", "SCL", "SDA"]},
                   {"id": "J1", "kind": "header", "pins": ["V3V3", "GND", "AO"]}],
         "nets": [{"pins": ["U1.D0", "R1.1"]}, {"pins": ["R1.2", "LED1.A"]}, {"name": "GND", "pins": ["U1.GND", "LED1.K", "SW1.B", "J2.GND", "J1.GND"]},
                  {"pins": ["U1.D1", "SW1.A"]}, {"name": "SDA", "pins": ["U1.SDA", "J2.SDA"]}, {"name": "SCL", "pins": ["U1.SCL", "J2.SCL"]},
                  {"pins": ["U1.SCK", "J1.AO"]}]}


async def test_pins_against_the_graph(no_gxx):
    src = ("#include <Wire.h>\n"
           "const int LED_PIN = D1;\n"       # the board has the LED on D0 and a button on D1
           "#define BTN D0\n"
           "void setup() {\n"
           "  Wire.begin(D2, D3);\n"
           "  pinMode(LED_PIN, OUTPUT);\n"
           "  pinMode(BTN, INPUT_PULLUP);\n"
           "  digitalWrite(D7, HIGH);\n"
           "  int v = analogRead(SCK);\n"
           "}\n"
           "void loop() {}\n")
    r = await fc.check(WIRED, {"g.ino": src}, "arduino")
    errs = {e["code"]: e for e in r["errors"]}
    assert errs["pin_conflict"]["line"] == 2 and "button" in errs["pin_conflict"]["msg"]
    assert errs["i2c_pins"]["line"] == 5 and errs["i2c_pins"]["hint"] == "Wire.begin(SDA, SCL)"
    assert errs["pin_unwired"]["line"] == 8 and "RX" in errs["pin_unwired"]["msg"]
    assert errs["adc_pin"]["line"] == 9 and "D0 (GPIO2)" in errs["adc_pin"]["hint"]
    assert any(w["code"] == "pin_conflict" and w["line"] == 3 for w in r["warnings"])   # reads the LED's pin


async def test_micropython_syntax_and_pins():
    pico = {"nodes": [{"id": "U1", "kind": "module", "module": "SC0915"}, {"id": "LED1", "kind": "led"},
                      {"id": "U2", "kind": "chip", "label": "BME280", "lcsc": "C92489"}],
            "nets": [{"pins": ["U1.GP15", "LED1.A"]}, {"name": "SDA", "pins": ["U1.GP4", "U2.SDI"]}, {"name": "SCL", "pins": ["U1.GP5", "U2.SCK"]}]}
    py = ("from machine import Pin, PWM, I2C, ADC\nimport time\nLED = 15\nled = Pin(LED, Pin.OUT)\n"
          "i2c = I2C(0, sda=Pin(8), scl=Pin(9))\nbuzz = PWM(Pin(16))\nadc = ADC(Pin(3))\n"
          "def run():\n    # TODO: debounce\n    while True:\n        led.toggle()\n        time.sleep(0.5)\n")
    r = await fc.check(pico, {"main.py": py}, "micropython")
    assert r["tool"] == "python ast"
    errs = {e["code"]: e for e in r["errors"]}
    assert errs["i2c_pins"]["line"] == 5 and errs["i2c_pins"]["hint"] == "I2C(0, sda=Pin(4), scl=Pin(5))"
    assert errs["pin_unwired"]["line"] == 6 and errs["adc_pin"]["line"] == 7
    assert codes(r["warnings"], "stub")[0]["line"] == 9
    r = await fc.check(pico, {"main.py": "x = 1\ndef f(:\n    pass\n"}, "micropython")
    assert [(e["code"], e["line"]) for e in r["errors"]] == [("syntax", 2)]
    assert not codes(r["warnings"], "pin_unused")   # no verdict on pins from a file that does not parse
    r = await fc.check(pico, {"main.py": 'import ssd1306\noled.text("Привет", 0, 0)\n'}, "micropython")
    assert codes(r["errors"], "display_charset")[0]["line"] == 2


# ------------------------------------------------------------------ safety and robustness
async def test_includes_outside_the_sketch_are_refused():
    src = '#include <Arduino.h>\n#define P "/proc/self/environ"\n#include P\n#include "../../secret.h"\nvoid setup(){}\nvoid loop(){}\n'
    r = await fc.check(XIAO_C3, {"e.ino": src}, "arduino")
    assert not r["ok"] and r["tool"].startswith("static only")
    assert {e["line"] for e in codes(r["errors"], "compile")} == {3, 4}


@needs_gxx
async def test_preprocessor_pass_sees_files_outside(tmp_path):
    secret = tmp_path / "outside" / "secret.h"
    secret.parent.mkdir()
    secret.write_text("int secret;\n")
    sketch = tmp_path / "sketch"
    sketch.mkdir()
    (sketch / "a.cpp").write_text(f'#include "{secret.as_posix()}"\nint x;\n')
    bad = await fc._reads_outside(fc.gxx(), ["a.cpp"], str(sketch), [str(sketch), str(fc.STUBS)])
    assert len(bad) == 1 and bad[0].endswith("secret.h")
    (sketch / "b.cpp").write_text("#include <Arduino.h>\nint y;\n")
    assert await fc._reads_outside(fc.gxx(), ["-I", str(fc.STUBS), "b.cpp"], str(sketch), [str(sketch), str(fc.STUBS)]) == []


async def test_never_raises():
    r = await fc.check(None, None, None)  # type: ignore[arg-type]
    assert r["ok"] is False and r["errors"][0]["code"] == "no_firmware"
    r = await fc.check({"nodes": "x", "nets": 5}, {"a b?.ino": "x", "../ok.ino": "void setup(){}\nvoid loop(){}\n"}, "arduino")
    assert set(r) == {"ok", "tool", "errors", "warnings"} and r["ok"], r
    assert [w["code"] for w in r["warnings"]] == ["bad_name"]


# a device that is a USB keyboard: the S3 has native USB, the C3 does not, and the check says so before anything is ordered
HID_SKETCH = """#include "USB.h"
#include "USBHIDKeyboard.h"
USBHIDKeyboard Keyboard;
void setup() { pinMode(D0, INPUT_PULLUP); Keyboard.begin(); USB.begin(); }
void loop() { if (digitalRead(D0) == LOW) { Keyboard.press(KEY_LEFT_CTRL); Keyboard.write('c'); Keyboard.releaseAll(); delay(200); } }
"""


def _hid_doc(module: str) -> dict:
    return {"schema": "fw.device/1", "title": "pad", "nodes": [{"id": "U1", "kind": "module", "module": module}, {"id": "SW1", "kind": "button", "switch": "mx"}],
            "nets": [{"name": "GND", "pins": ["U1.GND", "SW1.B"]}, {"pins": ["U1.D0", "SW1.A"]}]}


async def test_usb_keyboard_compiles_on_the_s3_and_not_on_the_c3():
    ok = await fc.check(_hid_doc("113991114"), {"pad.ino": HID_SKETCH}, "arduino")
    assert not [e for e in ok["errors"] if e.get("code") == "compile"], ok["errors"]
    no = await fc.check(_hid_doc("113991054"), {"pad.ino": HID_SKETCH}, "arduino")
    assert any("no native USB" in str(e.get("msg") or e.get("message")) for e in no["errors"]), no["errors"]
