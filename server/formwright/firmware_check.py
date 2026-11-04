"""Firmware check (C3): does the firmware the designer wrote compile, and does it drive the pins the board wires?

check(doc, files, lang) -> {ok, tool, errors: [{code, file, line, msg, hint?}], warnings: [...]}; never raises, bounded to
20 s. `line` is 1-based in `file`; 0 for findings about the board rather than a line (a wired pin nothing uses).
  - Arduino (.ino/.cpp/.h): the IDE's preprocessing (the .ino files joined, the one with setup() first,
    `#include <Arduino.h>` in front, prototypes for functions defined later), then one `g++ -S -O0 -std=gnu++17` (to
    assembly in a temp dir, nothing assembled or linked) against firmware_stubs/: the arduino-esp32 3.x / arduino-pico
    core and the libraries designers reach for, declared with their real signatures so misuse fails as it does for real.
    The board's pin names come from -DFW_BOARD_*. A header with no stub becomes an empty file: the errors its
    identifiers cause are dropped and a warning says the library was not checked. Only headers by plain name are read
    (a text scan, then a preprocessor pass listing what it opened): the server's files never reach the compiler. No
    g++: tool 'static only'.
  - MicroPython (.py): ast.parse, and the pins of machine.Pin / PWM / ADC / I2C / NeoPixel ...
  - Static, both languages (they matter as much as the compile): every pin the code touches is resolved to a GPIO
    (#define, const, arrays, D0..D10, A0.., SDA/SCL/TX/RX/SCK/MISO/MOSI, GPIO_NUM_n, numbers, a function's parameter
    through its callers) and compared with what the device graph wires to that pin of the module: pin_unwired,
    pin_conflict (an LED driven on the I2C bus), i2c_pins, adc_pin, pin_unused (a wired LED or button the code never
    touches); display_charset (UTF-8 text on a display whose font is ASCII); stub (a shortcut left in a function body);
    blocking_delay (long delay() in loop() under a web server); core_api (arduino-esp32 2.x LEDC calls).
  - The requirements (doc.requirements, any language) against the code, where the device reviewer's real catches were:
    requirement_sleep (asked to sleep, but no esp_deep_sleep_start() / lightsleep() is reached: only in a comment, under
    #if 0, or in a function nothing calls), requirement_fade (asked to fade, but no ledcWrite / analogWrite /
    setBrightness / duty() gets a value that changes), both errors; requirement_pins (a firmware requirement whose parts'
    module pins the code never touches), a warning.
"""
from __future__ import annotations

import ast
import asyncio
import difflib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from bisect import bisect_left
from pathlib import Path
from typing import Any

from . import device

STUBS = Path(__file__).parent / "firmware_stubs"
STD = "gnu++17"
TOTAL_S = 20.0
GXX_S = 11.0     # the compile; the preprocessor pass before it gets PRE_S, both well inside TOTAL_S
PRE_S = 5.0
MAX_ITEMS = 20
CPP_EXT = (".ino", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".c")

# the module pin label -> GPIO map is device.MODULES[mpn]['gpio'] (C5); these until every module has one
_XIAO_C3 = {"D0": 2, "D1": 3, "D2": 4, "D3": 5, "SDA": 6, "SCL": 7, "TX": 21, "RX": 20, "SCK": 8, "MISO": 9, "MOSI": 10}
_XIAO_S3 = {"D0": 1, "D1": 2, "D2": 3, "D3": 4, "SDA": 5, "SCL": 6, "TX": 43, "RX": 44, "SCK": 7, "MISO": 8, "MOSI": 9}
_PICO = {f"GP{n}": n for n in (*range(23), 26, 27, 28)}
GPIO_FALLBACK = {"113991054": _XIAO_C3, "113991114": _XIAO_S3, "SC0915": _PICO, "SC0918": _PICO}
_ESP = ["ESP32", "ESP_PLATFORM", "ARDUINO_ARCH_ESP32"]
_PICO_NAMES = {"A0": 26, "A1": 27, "A2": 28, "A3": 29, "SDA": 4, "SCL": 5, "TX": 0, "RX": 1, "SCK": 18, "MISO": 16, "MOSI": 19, "SS": 17,
               **{f"D{n}": n for n in range(29)}}
# what the stubs are told (-D) and what the chip's pins can do; names are the Arduino variant's (pins_arduino.h)
BOARDS: dict[str, dict[str, Any]] = {
    "113991054": {"define": "FW_BOARD_XIAO_ESP32C3", "defs": [*_ESP, "ARDUINO_XIAO_ESP32C3", "CONFIG_IDF_TARGET_ESP32C3=1"],
                  "core": "arduino-esp32 3.x", "names": {"A0": 2, "A1": 3, "A2": 4, "A3": 5, "SS": 20}, "led": None,
                  "adc": range(0, 5), "adc2": (5,), "gpios": range(0, 22)},
    "113991114": {"define": "FW_BOARD_XIAO_ESP32S3", "defs": [*_ESP, "ARDUINO_XIAO_ESP32S3", "CONFIG_IDF_TARGET_ESP32S3=1"],
                  "core": "arduino-esp32 3.x", "names": {"A0": 1, "A1": 2, "A2": 3, "A3": 4, "A4": 5, "A5": 6, "A8": 7, "A9": 8, "A10": 9, "SS": 44},
                  "led": 21, "adc": range(1, 11), "adc2": range(11, 21), "gpios": (*range(0, 22), *range(26, 49))},
    "SC0915": {"define": "FW_BOARD_PICO", "defs": ["ARDUINO_ARCH_RP2040", "ARDUINO_RASPBERRY_PI_PICO"], "core": "arduino-pico",
               "names": _PICO_NAMES, "led": 25, "adc": range(26, 30), "adc2": (), "gpios": range(0, 30)},
    "SC0918": {"define": "FW_BOARD_PICO_W", "defs": ["ARDUINO_ARCH_RP2040", "ARDUINO_RASPBERRY_PI_PICO_W"], "core": "arduino-pico",
               "names": _PICO_NAMES, "led": 64, "adc": range(26, 30), "adc2": (), "gpios": range(0, 30)},
}

# headers the host compiler has (left to it); anything else without a stub is an unchecked library
_STD_C = set("assert complex ctype errno fenv float inttypes iso646 limits locale math setjmp signal stdalign stdarg stdatomic stdbool "
             "stddef stdint stdio stdlib stdnoreturn string strings tgmath time uchar wchar wctype".split())
_STD_CXX = set("algorithm any array atomic bitset cassert cctype cerrno cfloat chrono cinttypes climits clocale cmath complex "
               "condition_variable cstdarg cstdbool cstddef cstdint cstdio cstdlib cstring ctime cwchar deque exception forward_list "
               "fstream functional initializer_list iomanip ios iosfwd iostream istream iterator limits list locale map memory mutex "
               "new numeric optional ostream queue random ratio regex set sstream stack stdexcept streambuf string string_view "
               "system_error thread tuple type_traits typeindex typeinfo unordered_map unordered_set utility valarray variant vector".split())
_KEYWORDS = set("if else for while do switch case return sizeof decltype catch new delete throw operator alignof static_assert".split())
OUT = {"output", "pwm", "tone", "neopixel", "servo"}
IN = {"input", "analog", "interrupt", "touch"}
STUB_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK|stub|placeholder|not implemented|unimplemented|simplified|dummy|for now)\b|"
                     r"упрощ|заглушк|не реализ|пока что|пока без|временн|допиш|доделат", re.I)
_I2C_PIN = re.compile(r"^(I2C\d?_?)?(SDA|SCL|SDX|SCX)\d?$", re.I)
_DISPLAYS = {"Adafruit_SSD1306": "gfx", "Adafruit_SH1106G": "gfx", "Adafruit_SH1107": "gfx", "Adafruit_SH110X": "gfx",
             "Adafruit_ST7735": "gfx", "Adafruit_ST7789": "gfx", "Adafruit_ILI9341": "gfx", "Adafruit_GFX": "gfx", "TFT_eSPI": "tft",
             "TFT_eSprite": "tft", "LiquidCrystal_I2C": "lcd", "LiquidCrystal": "lcd", "U8G2": "u8g2", "U8X8": "u8g2"}
_PRINTS = ("print|println|printf|write|drawString|drawStr|drawStrX2|drawUTF8|drawUTF8X2|drawCentreString|drawCenterString|"
           "drawRightString|draw2x2String|draw1x2String|draw2x2UTF8|draw1x2UTF8|drawButtonUTF8|drawExtUTF8")
_I2C_LIBS = re.compile(r"#\s*include\s*[<\"](Wire|Adafruit_SSD1306|Adafruit_SH110X|BH1750|Adafruit_BME280|Adafruit_BMP280|"
                       r"Adafruit_AHTX0|LiquidCrystal_I2C|Adafruit_MPU6050|SparkFun\w*|Adafruit_VEML\w*)\.h[>\"]")
_HINT_CHARSET = ("Show English text on the device (Russian is fine in Serial and on the web page), or drive the display with "
                 "U8g2: u8g2.enableUTF8Print(); u8g2.setFont(u8g2_font_6x13_t_cyrillic); u8g2.print(\"...\")")


# ------------------------------------------------------------------ entry
async def check(doc: dict, files: dict[str, str], lang: str) -> dict:
    """The firmware against its device graph; never raises (a broken check is a warning, not a verdict)."""
    try:
        return await asyncio.wait_for(_check(doc if isinstance(doc, dict) else {}, files if isinstance(files, dict) else {},
                                             str(lang or "")), TOTAL_S)
    except Exception as e:  # noqa: BLE001 - the designer must always get an answer
        return {"ok": True, "tool": "none", "errors": [],
                "warnings": [_item("check_failed", "", 0, f"the firmware check itself failed ({type(e).__name__}: {e}); nothing was checked")]}


def _item(code: str, file: str, line: int | None, msg: str, hint: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "file": file, "line": int(line or 0), "msg": msg[:500]}
    if hint:
        out["hint"] = hint[:400]
    return out


_CONTROLLER = re.compile(r"(?<![A-Za-z0-9])(SSD\d{4}|SH\d{4}|ST\d{4}|ILI\d{4}|UC\d{4})")
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/|#[^\n]*", re.S)


def _display_controller(doc: dict, files: dict[str, str]) -> list[dict]:
    """The firmware drives the controller the device's display has: the controller is in the accessory's own name. An analyzer's
    1.3" SH1106 shipped driven as an SH1107, which compiles and shows garbage. A display whose name names none is not judged."""
    from . import accessories

    names = [accessories.ACCESSORIES[n["accessory"]]["name"] for n in doc.get("nodes") or []
             if isinstance(n, dict) and accessories.ACCESSORIES.get(str(n.get("accessory")), {}).get("kind") == "display"]
    have = {c for name in names for c in _CONTROLLER.findall(name)}
    if not have or not all(_CONTROLLER.search(n) for n in names):
        return []
    out = []
    for fname, text in files.items():
        for m in _CONTROLLER.finditer(_COMMENT.sub(" ", text)):
            if m.group(1) not in have:
                out.append(_item("display_controller", fname, 0, f"the code drives a {m.group(1)}, and the device's display is {', '.join(names)}",
                                 f"use the driver of the {', '.join(sorted(have))}: Adafruit_SH1106G for an SH1106, Adafruit_SSD1306 for an SSD1306, or the matching U8g2 constructor"))
                break
    return out


async def _check(doc: dict, files: dict[str, str], lang: str) -> dict:
    clean: dict[str, str] = {}
    errors: list[dict] = []
    warnings: list[dict] = []
    for name, text in files.items():
        base = os.path.basename(str(name).replace("\\", "/"))
        if not re.fullmatch(r"[\w.+-]{1,60}", base) or base.startswith(".") or not isinstance(text, str):
            warnings.append(_item("bad_name", str(name)[:60], 0, f"file {str(name)[:60]!r} is not a plain file name: not checked"))
            continue
        clean[base] = text.replace("\r\n", "\n")
    if not clean:
        return {"ok": False, "tool": "none", "errors": [_item("no_firmware", "", 0, "no firmware files to check")], "warnings": warnings}
    errors += _display_controller(doc, clean)
    py = [n for n in clean if n.endswith(".py")]
    cc = [n for n in clean if n.endswith(CPP_EXT)]
    if not py and not cc:
        (py if "python" in lang.lower() else cc).extend(clean)
    board = Board.of(doc)
    wiring = _wiring(doc, board) if board else {}
    facts = Facts()
    tools = []
    if cc:
        tools.append(await _arduino({n: clean[n] for n in cc}, board, facts, errors, warnings))
    if py:
        tools.append(_micropython({n: clean[n] for n in py}, board, facts, errors, warnings))
    if board and not facts.blind:
        _pin_checks(board, wiring, facts, errors, warnings)
    _requirement_checks(doc, {n: clean[n] for n in cc}, {n: clean[n] for n in py}, lang, board, wiring, facts, errors, warnings)
    errors = _dedupe(errors)
    warnings = _dedupe(warnings)
    return {"ok": not errors, "tool": "; ".join(tools), "errors": _cap(errors), "warnings": _cap(warnings)}


def _dedupe(items: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out = []
    for it in items:
        k = (it["code"], it["file"], it["line"], it["msg"])
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


def _cap(items: list[dict]) -> list[dict]:
    if len(items) <= MAX_ITEMS:
        return items
    rest = items[MAX_ITEMS - 1:]
    codes = ", ".join(sorted({i["code"] for i in rest}))
    return [*items[:MAX_ITEMS - 1], _item(rest[0]["code"], rest[0]["file"], rest[0]["line"], f"{len(rest)} more ({codes}); the first: {rest[0]['msg']}")]


# ------------------------------------------------------------------ the board and its wiring
class Board:
    """The device's microcontroller module: its pin labels and GPIOs, and the names the Arduino variant gives them."""

    def __init__(self, mpn: str, nid: str) -> None:
        m = device.MODULES.get(mpn) or {}
        b = BOARDS.get(mpn) or {}
        self.mpn, self.id, self.name, self.spec = mpn, nid, m.get("name", mpn), b
        raw = dict(m.get("gpio") or GPIO_FALLBACK.get(mpn) or {})
        # one entry per module pin (the graph's labels); any other key in the map is a name for the same GPIO
        self.gpio: dict[str, int] = {lb: g for lb, g in raw.items() if lb in (m.get("pins") or raw)}
        aliases = {a: t for a, t in (m.get("aliases") or {}).items() if t in self.gpio}
        self.names: dict[str, int] = {**raw, **{a: self.gpio[t] for a, t in aliases.items()}, **b.get("names", {})}
        if b.get("led") is not None:
            self.names["LED_BUILTIN"] = self.names["BUILTIN_LED"] = b["led"]
        self.label_of = {g: lb for lb, g in self.gpio.items()}
        self.alias_of: dict[str, list[str]] = {}
        for a, t in aliases.items():
            self.alias_of.setdefault(t, []).append(a)

    @staticmethod
    def of(doc: dict) -> Board | None:
        node = next((n for n in doc.get("nodes") or [] if isinstance(n, dict) and n.get("kind") == "module" and n.get("module")), None)
        return Board(str(node["module"]), str(node["id"])) if node else None

    def pin(self, g: int) -> str:
        """'SDA/D4 (GPIO6)', or 'GPIO12' for a GPIO the module does not bring out."""
        lb = self.label_of.get(g)
        if lb is None:
            return f"GPIO{g}"
        names = [lb, *[a for a in self.alias_of.get(lb, []) if re.fullmatch(r"D\d+", a)]]
        return f"{'/'.join(names)} (GPIO{g})" if lb != f"GP{g}" else lb

    @property
    def defaults(self) -> tuple[int | None, int | None]:
        return self.names.get("SDA"), self.names.get("SCL")


def _role(node: dict, pin: str, label: str) -> str:
    k = node.get("kind")
    if _I2C_PIN.match(pin) or (label in ("SDA", "SCL") and re.fullmatch(r"(SDI|SCK|SCLK|SDIO|SDA_?\w*|SCL_?\w*)", pin, re.I)):
        return "i2c"
    if k in ("led", "button"):
        return k
    if k in ("header", "accessory"):
        return "header"
    if k in ("jst", "usb_c", "hole"):
        return "power"
    if k == "chip":
        t = f"{node.get('label', '')} {node.get('mpn', '')} {node.get('note', '')}".lower()
        if re.search(r"ws28|sk68|neopixel|addressable|apa10|rgb", t):
            return "led"
        if re.search(r"buzz|beep|piezo|speaker|зумм|пищ|пьез|динам", t):
            return "buzzer"
        if re.search(r"transistor|mosfet|\bnpn\b|\bpnp\b|s8050|ss8050|2n2222|2n3904|2n7002|ao3400|si2302|bss138|mmbt|транзист|ключ", t):
            return "driver"
        if re.search(r"\bled\b|светодиод", t):
            return "led"
    return "io"


def _wiring(doc: dict, board: Board) -> dict[int, dict[str, Any]]:
    """Per GPIO of the module: its label, and the parts its net reaches (through one series resistor, not through a pull-up
    to a rail) with their role: led, button, buzzer, driver (a transistor), i2c, header, io."""
    nodes = {n["id"]: n for n in doc.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    nets = [n for n in doc.get("nets") or [] if isinstance(n, dict)]
    net_of: dict[str, int] = {}
    for i, net in enumerate(nets):
        for p in net.get("pins") or []:
            net_of[str(p)] = i

    def is_rail(i: int) -> bool:
        net = nets[i]
        return bool(device.POWER_NET.match(str(net.get("name") or ""))) or any(
            str(p).split(".", 1)[0] == board.id and str(p).split(".", 1)[-1] not in board.gpio for p in net.get("pins") or [])

    out: dict[int, dict[str, Any]] = {}
    for label, g in board.gpio.items():
        i = net_of.get(f"{board.id}.{label}")
        parts: list[dict[str, Any]] = []
        roles: set[str] = set()
        if i is not None and not is_rail(i):
            todo, seen = [(i, None)], {i}
            while todo:
                ni, via = todo.pop()
                if _I2C_PIN.match(str(nets[ni].get("name") or "")):
                    roles.add("i2c")
                for ref in nets[ni].get("pins") or []:
                    nid, _, pin = str(ref).partition(".")
                    node = nodes.get(nid)
                    if nid == board.id or node is None:
                        continue
                    if node.get("kind") == "capacitor":
                        continue
                    if node.get("kind") == "resistor":
                        j = net_of.get(f"{nid}.{'2' if pin == '1' else '1'}")
                        if via is None and j is not None and j not in seen and not is_rail(j):
                            seen.add(j)
                            todo.append((j, nid))
                        else:
                            roles.add("pull")
                        continue
                    role = _role(node, pin, label)
                    roles.add(role)
                    parts.append({"id": nid, "pin": pin, "role": role, "label": str(node.get("label") or "")[:40], "via": via})
        out[g] = {"label": label, "net": i, "parts": parts, "roles": roles}
    return out


def _parts(w: dict[str, Any], limit: int = 3) -> str:
    def one(p: dict[str, Any]) -> str:
        lb = f" {p['label']}" if p["label"] and p["label"] != p["id"] else ""
        return f"{p['id']}{lb}" + (f" (via {p['via']})" if p["via"] else "")
    seen: list[str] = []
    for p in w["parts"]:
        s = one(p)
        if s not in seen:
            seen.append(s)
    return ", ".join(seen[:limit]) + (" ..." if len(seen) > limit else "")


class Facts:
    """What the firmware does with pins, gathered from either language for the shared checks."""

    def __init__(self) -> None:
        self.uses: list[dict[str, Any]] = []      # {gpio, how, file, line, expr, origin: {name, file, line} | None}
        self.i2c = False                           # talks I2C at all
        self.i2c_pins: list[dict[str, Any]] = []   # explicit Wire.begin(sda, scl) / I2C(sda=, scl=) uses
        self.wifi = False
        self.mentioned: set[str] = set()           # identifiers in code, for pin_unused
        self.main = ""                             # the file findings without a line point at
        self.blind = False                         # a file could not be read: no pin verdicts from half the code


# ------------------------------------------------------------------ C++ lexing
class Src:
    """One C++ source: code with comments and string contents blanked (same offsets), its string literals and comments,
    its top-level functions."""

    def __init__(self, name: str, text: str) -> None:
        self.name, self.text = name, text
        self.code, self.strings, self.comments = _lex(text)
        self.nl = [i for i, c in enumerate(text) if c == "\n"]
        self.funcs = _functions(self.code)

    def line(self, off: int) -> int:
        return bisect_left(self.nl, off) + 1

    def func_at(self, off: int) -> dict[str, Any] | None:
        return next((f for f in self.funcs if f["body"] < off < f["end"]), None)

    def line_text(self, line: int) -> str:
        a = self.nl[line - 2] + 1 if line >= 2 and line - 2 < len(self.nl) else 0
        b = self.nl[line - 1] if line - 1 < len(self.nl) else len(self.code)
        return self.code[a:b]


def _lex(s: str) -> tuple[str, list[tuple[int, int, str]], list[tuple[int, int, str]]]:
    out = list(s)
    strings: list[tuple[int, int, str]] = []
    comments: list[tuple[int, int, str]] = []

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "/" and s.startswith("//", i):
            j = s.find("\n", i)
            j = n if j < 0 else j
            comments.append((i, j, s[i + 2:j]))
            blank(i, j)
            i = j
        elif c == "/" and s.startswith("/*", i):
            j = s.find("*/", i + 2)
            j = n if j < 0 else j + 2
            comments.append((i, j, s[i + 2:j - 2]))
            blank(i, j)
            i = j
        elif c == '"':
            k = i
            while k > 0 and (s[k - 1].isalnum() or s[k - 1] == "_"):
                k -= 1
            m = re.match(r'([^()\\\s"]{0,16})\(', s[i + 1:i + 19]) if s[k:i] in ("R", "u8R", "uR", "UR", "LR") else None
            if m:
                d = m.group(1)
                a = i + 2 + len(d)
                e = s.find(f'){d}"', a)
                e = n if e < 0 else e
                strings.append((a, e, s[a:e]))
                blank(i + 1, min(n, e + len(d) + 1))
                i = e + len(d) + 2
                continue
            j = i + 1
            while j < n and s[j] != '"' and s[j] != "\n":
                j += 2 if s[j] == "\\" else 1
            j = min(j, n)
            strings.append((i + 1, j, s[i + 1:j]))
            blank(i + 1, j)
            i = j + 1
        elif c == "'":
            if i > 0 and s[i - 1].isdigit() and i + 1 < n and s[i + 1].isalnum():
                i += 1   # 1'000 digit separator
                continue
            j = i + 1
            while j < n and s[j] != "'" and s[j] != "\n":
                j += 2 if s[j] == "\\" else 1
            blank(i + 1, min(j, n))
            i = j + 1
        else:
            i += 1
    return "".join(out), strings, comments


def _match(code: str, open_: int) -> int:
    """The offset of the bracket closing the one at open_ (len(code) when unbalanced)."""
    pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
    o, c = code[open_], pairs[code[open_]]
    d = 0
    for k in range(open_, len(code)):
        if code[k] == o:
            d += 1
        elif code[k] == c:
            d -= 1
            if d == 0:
                return k
        elif o == "<" and code[k] in ";{}":
            break
    return len(code)


def _split(s: str, angle: bool = False) -> list[str]:
    """Top-level comma-separated parts (call arguments, parameters, initialisers)."""
    if not s.strip():
        return []
    parts, d, cur = [], 0, 0
    opens, closes = ("([{<", ")]}>") if angle else ("([{", ")]}")
    for k, c in enumerate(s):
        if c in opens:
            d += 1
        elif c in closes:
            d -= 1
        elif c == "," and d == 0:
            parts.append(s[cur:k])
            cur = k + 1
    parts.append(s[cur:])
    return [p.strip() for p in parts]


def _at_line_start(code: str, i: int) -> bool:
    k = code.rfind("\n", 0, i)
    return not code[k + 1:i].strip()


def _functions(code: str) -> list[dict[str, Any]]:
    """Top-level function definitions: {name, ret, params, decl (offset of the declaration), body ({), end (after })}."""
    funcs: list[dict[str, Any]] = []
    depth, stmt, cur, i, n = 0, 0, None, 0, len(code)
    while i < n:
        c = code[i]
        if c == "#" and _at_line_start(code, i):
            e = i
            while True:
                e = code.find("\n", e)
                if e < 0:
                    e = n
                    break
                if code[e - 1:e] == "\\" or code[e - 2:e] == "\\\r":
                    e += 1
                    continue
                break
            if depth == 0:
                stmt = e
            i = e
            continue
        if c == "{":
            if depth == 0:
                cur = _header(code, stmt, i)
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                if cur:
                    cur["end"] = i + 1
                    funcs.append(cur)
                    cur = None
                stmt = i + 1
        elif c == ";" and depth == 0:
            stmt = i + 1
        i += 1
    return funcs


def _header(code: str, start: int, brace: int) -> dict[str, Any] | None:
    h = code[start:brace]
    m = re.search(r"\)\s*(?:(?:const|override|final|noexcept|volatile)\s*)*$", h)
    if not m:
        return None
    close = start + m.start()
    d, k = 0, close
    while k >= start:
        if code[k] == ")":
            d += 1
        elif code[k] == "(":
            d -= 1
            if d == 0:
                break
        k -= 1
    if k < start:
        return None
    pre = code[start:k]
    mm = re.search(r"((?:[A-Za-z_]\w*\s*::\s*)*~?[A-Za-z_]\w*)\s*$", pre)
    if not mm:
        return None
    name = re.sub(r"\s+", "", mm.group(1))
    ret = " ".join(pre[:mm.start()].split())
    if name in _KEYWORDS or "=" in ret or re.search(r"\b(class|struct|union|enum|namespace)\b", ret):
        return None
    params = [p for p in _split(code[k + 1:close], angle=True) if p and p != "void"]
    names = []
    for p in params:
        q = _split(p.replace("=", ",", 1), angle=True)[0] if "=" in p else p
        pm = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*$", q)
        names.append(pm.group(1) if pm else "")
    return {"name": name, "ret": ret, "params": params, "pnames": names, "decl": start + len(h) - len(h.lstrip()), "body": brace,
            "open": k, "close": close}


def _enclosing_call(code: str, off: int, stop: int = 0) -> str | None:
    """The function whose argument list holds `off` (innermost), or None."""
    d = 0
    for k in range(off - 1, stop - 1, -1):
        c = code[k]
        if c == ")":
            d += 1
        elif c == "(":
            if d == 0:
                m = re.search(r"([A-Za-z_]\w*)\s*$", code[max(0, k - 60):k])
                return m.group(1) if m else ""
            d -= 1
        elif c in ";{}" and d == 0:
            return None
    return None


def _in_call(code: str, off: int, name: str) -> bool:
    """Is `off` inside the arguments of a call to `name`, at any depth within its statement?"""
    k = off
    while True:
        d = 0
        found = None
        for j in range(k - 1, -1, -1):
            c = code[j]
            if c == ")":
                d += 1
            elif c == "(":
                if d == 0:
                    found = j
                    break
                d -= 1
            elif c in ";{}" and d == 0:
                return False
        if found is None:
            return False
        m = re.search(r"([A-Za-z_]\w*)\s*$", code[max(0, found - 60):found])
        if m and m.group(1) == name:
            return True
        k = found


# ------------------------------------------------------------------ C++ symbols and pin uses
_DECL = re.compile(r"(?:^|(?<=[;{}]))[ \t]*((?:(?:static|const|constexpr|volatile|unsigned|signed|inline)\s+)*"
                   r"(?:u?int(?:8|16|32|64)?_t|int|byte|short|long|char|size_t|gpio_num_t|auto|uint|word|pin_size_t)\b"
                   r"(?:\s+(?:const|int|long|unsigned))*)\s+([^;(){}][^;]*);", re.M)
_DEFINE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)(?![\w(])[ \t]*(.*?)[ \t]*$", re.M)
_ENUM = re.compile(r"\benum\s+(?:class\s+)?\w*\s*(?::\s*\w+\s*)?\{([^}]*)\}")
_RANGE_FOR = re.compile(r"\bfor\s*\(\s*(?:const\s+)?[\w:]+\s*&?\s*([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)\s*\)")


class Sketch:
    """The C++ sources of one firmware with their symbols, for resolving what a pin argument evaluates to."""

    def __init__(self, srcs: list[Src], board: Board | None) -> None:
        self.srcs, self.board = srcs, board
        self.syms: dict[str, list[dict[str, Any]]] = {}
        for s in srcs:
            for m in _DEFINE.finditer(s.code):
                if m.group(2):
                    self._add(m.group(1), m.group(2), None, s, m.start(1))
            for m in _DECL.finditer(s.code):
                body = s.code[m.start(2):m.end(2)]
                for part in _split(body):
                    pm = re.match(r"\s*[*&]?\s*([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*(?:=\s*(.+)|(\{.*\}))\s*$", part, re.S)
                    if not pm:
                        continue
                    val = (pm.group(3) or pm.group(4) or "").strip()
                    items = _split(val.strip()[1:-1]) if val.startswith("{") and val.endswith("}") else None
                    self._add(pm.group(1), None if items is not None else val, items, s, m.start(2))
            for m in _ENUM.finditer(s.code):
                for it in _split(m.group(1)):
                    em = re.match(r"([A-Za-z_]\w*)\s*=\s*(.+)$", it, re.S)
                    if em:
                        self._add(em.group(1), em.group(2), None, s, m.start(1))
            for m in _RANGE_FOR.finditer(s.code):
                self._add(m.group(1), m.group(2), None, s, m.start(1))
        # what the sketch itself declares (for telling its own names from an unchecked library's)
        self.declared = set(self.syms) | {f["name"].split("::")[-1] for s in srcs for f in s.funcs}
        for s in srcs:
            self.declared |= set(re.findall(r"\b(?:class|struct|enum|union|typedef[^;]*?|using)\s+([A-Za-z_]\w*)", s.code))
            for body in _ENUM.findall(s.code):
                self.declared |= set(re.findall(r"[A-Za-z_]\w*", body))

    def _add(self, name: str, value: str | None, items: list[str] | None, src: Src, off: int) -> None:
        f = src.func_at(off)
        self.syms.setdefault(name, []).append({"name": name, "value": value, "items": items, "src": src, "off": off,
                                               "func": f["body"] if f else None})

    def lookup(self, name: str, src: Src, off: int) -> dict[str, Any] | None:
        defs = self.syms.get(name) or []
        f = src.func_at(off)
        local = [d for d in defs if d["src"] is src and f and d["func"] == f["body"] and d["off"] < off]
        if local:
            return local[-1]
        glob = [d for d in defs if d["func"] is None]
        return (glob or defs or [None])[0]

    def eval(self, expr: str, src: Src, off: int, depth: int = 0) -> list[tuple[int, dict[str, Any] | None]]:
        """The GPIO numbers an expression can stand for, each with the named symbol it came through (or None)."""
        if depth > 6:
            return []
        e = expr.strip()
        e = re.sub(r"^\(\s*(?:const\s+)?(?:u?int\d*_t|int|byte|gpio_num_t|unsigned(?:\s+int)?|long|pin_size_t)\s*\)\s*", "", e)
        cm = re.fullmatch(r"(?:static_cast|reinterpret_cast)\s*<[^>]*>\s*\((.*)\)", e, re.S)
        if cm:
            e = cm.group(1).strip()
        while e.startswith("(") and _match(e, 0) == len(e) - 1:
            e = e[1:-1].strip()
        if m := re.fullmatch(r"(0[xX][0-9a-fA-F]+|\d+)[uUlL]*", e):
            return [(int(m.group(1), 0), None)]
        if m := re.fullmatch(r"GPIO_NUM_(\d+)", e):
            return [(int(m.group(1)), None)]
        if m := re.fullmatch(r"(?:digitalPinToInterrupt|digitalPinToGPIONumber|analogInputToDigitalPin)\s*\((.*)\)", e, re.S):
            return self.eval(m.group(1), src, off, depth + 1)
        if self.board and e in self.board.names:
            return [(self.board.names[e], None)]
        if m := re.fullmatch(r"([A-Za-z_]\w*)\s*\[\s*(.*?)\s*\]", e, re.S):
            d = self.lookup(m.group(1), src, off)
            if not d:
                return []
            items = d["items"]
            if items is None:
                return self.eval(d["value"] or "", d["src"], d["off"], depth + 1) if d["value"] and re.fullmatch(r"[A-Za-z_]\w*", d["value"]) else []
            if re.fullmatch(r"\d+", m.group(2)) and int(m.group(2)) < len(items):
                items = [items[int(m.group(2))]]
            return [v for it in items for v in self._via(it, d, depth)]
        if re.fullmatch(r"[A-Za-z_]\w*", e):
            d = self.lookup(e, src, off)
            if d:
                if d["items"] is not None:
                    return [v for it in d["items"] for v in self._via(it, d, depth)]
                return [(g, o or {"name": e, "file": d["src"].name, "line": d["src"].line(d["off"])})
                        for g, o in self.eval(d["value"] or "", d["src"], d["off"], depth + 1)]
            return self._param(e, src, off, depth)
        return []

    def _via(self, item: str, d: dict[str, Any], depth: int) -> list[tuple[int, dict[str, Any] | None]]:
        vals = self.eval(item, d["src"], d["off"], depth + 1)
        return [(g, o or {"name": f"{d['name']}[]", "file": d["src"].name, "line": d["src"].line(d["off"])}) for g, o in vals]

    def _param(self, name: str, src: Src, off: int, depth: int) -> list[tuple[int, dict[str, Any] | None]]:
        """A function's parameter: what its callers pass."""
        f = src.func_at(off)
        if not f or name not in f["pnames"] or depth > 3:
            return []
        k = f["pnames"].index(name)
        fname = f["name"].split("::")[-1]
        out: list[tuple[int, dict[str, Any] | None]] = []
        for s in self.srcs:
            for m in re.finditer(rf"(?<![\w.>:]){re.escape(fname)}\s*\(", s.code):
                if s is src and m.start() >= f["decl"] and m.start() <= f["open"]:
                    continue
                args = _split(s.code[m.end():_match(s.code, m.end() - 1)])
                if k < len(args):
                    out += [(g, o or {"name": args[k][:40], "file": s.name, "line": s.line(m.start())})
                            for g, o in self.eval(args[k], s, m.start(), depth + 1)]
        return out


# free functions taking a pin: name -> (argument index, how)
_PIN_CALLS: dict[str, tuple[int, str]] = {
    "digitalWrite": (0, "output"), "digitalRead": (0, "input"), "analogRead": (0, "analog"), "analogReadMilliVolts": (0, "analog"),
    "analogSetPinAttenuation": (0, "analog"), "analogWrite": (0, "pwm"), "tone": (0, "tone"), "noTone": (0, "tone"),
    "ledcAttach": (0, "pwm"), "ledcAttachChannel": (0, "pwm"), "ledcAttachPin": (0, "pwm"), "attachInterrupt": (0, "interrupt"),
    "attachInterruptArg": (0, "interrupt"), "pulseIn": (0, "input"), "pulseInLong": (0, "input"), "gpio_set_level": (0, "output"),
    "gpio_get_level": (0, "input"), "esp_sleep_enable_ext0_wakeup": (0, "input"), "touchRead": (0, "touch"),
    "touchAttachInterrupt": (0, "touch"), "touchAttachInterruptArg": (0, "touch"), "touchSleepWakeUpEnable": (0, "touch"),
    "rgbLedWrite": (0, "neopixel"), "neopixelWrite": (0, "neopixel"),
}
_LEDC3 = ("ledcWrite", "ledcWriteTone", "ledcWriteNote", "ledcDetach", "ledcChangeFrequency", "ledcFade", "ledcRead", "ledcOutputInvert")


def _uses(sk: Sketch, facts: Facts) -> None:
    core2 = any(re.search(r"\bledc(Setup|AttachPin)\s*\(", s.code) for s in sk.srcs)
    calls = dict(_PIN_CALLS)
    if not core2:
        calls.update({c: (0, "pwm") for c in _LEDC3})
    call_re = re.compile(r"(?<![\w.>:])(" + "|".join(sorted(calls, key=len, reverse=True)) + r"|pinMode|shiftOut|shiftIn)\s*\(")
    objtypes: dict[str, str] = {"Wire": "TwoWire", "Wire1": "TwoWire", "SPI": "SPIClass", "Serial0": "HardwareSerial",
                                "Serial1": "HardwareSerial", "Serial2": "HardwareSerial"}
    for s in sk.srcs:
        for m in re.finditer(r"\b(TwoWire|SPIClass|HardwareSerial|Servo|ESP32PWM|Adafruit_NeoPixel)\s*[*&]?\s*([A-Za-z_]\w*)\s*[;(=\[{,]", s.code):
            objtypes[m.group(2)] = m.group(1)

    def add(expr: str, how: str, s: Src, off: int) -> None:
        if not expr or re.fullmatch(r"U8X8_PIN_NONE|-1|255", expr.strip()):
            return
        for g, origin in sk.eval(expr, s, off):
            if g >= 0 and g != 255:
                facts.uses.append({"gpio": g, "how": how, "file": s.name, "line": s.line(off), "expr": " ".join(expr.split())[:40],
                                   "origin": origin})

    for s in sk.srcs:
        code = s.code
        facts.mentioned |= set(re.findall(r"[A-Za-z_]\w*", code))
        for m in call_re.finditer(code):
            name = m.group(1)
            pre = code[max(0, m.start() - 40):m.start()]
            if re.search(r"\b(void|int|bool|uint\w*|long|float|double)\s*[*&]?\s*$", pre):
                continue   # a definition or declaration of a function by that name
            args = _split(code[m.end():_match(code, m.end() - 1)])
            if not args:
                continue
            if name in ("analogRead", "digitalRead", "analogReadMilliVolts") and _in_call(code, m.start(), "randomSeed"):
                continue   # a floating pin read for a random seed
            if name == "pinMode":
                mode = args[1] if len(args) > 1 else ""
                how = "output" if "OUTPUT" in mode else "input" if "INPUT" in mode else "analog" if "ANALOG" in mode else "io"
                add(args[0], how, s, m.start())
            elif name == "shiftOut":
                add(args[0], "output", s, m.start())
                add(args[1] if len(args) > 1 else "", "output", s, m.start())
            elif name == "shiftIn":
                add(args[0], "input", s, m.start())
                add(args[1] if len(args) > 1 else "", "output", s, m.start())
            else:
                k, how = calls[name]
                if k < len(args):
                    add(args[k], how, s, m.start())
        for m in re.finditer(r"\b([A-Za-z_]\w*)\s*(?:\.|->)\s*(begin|setPins|attach|setPin|attachPin|setSDA|setSCL)\s*\(", code):
            obj, meth = m.group(1), m.group(2)
            t = objtypes.get(obj)
            args = _split(code[m.end():_match(code, m.end() - 1)])
            if t == "TwoWire" and meth in ("setSDA", "setSCL") and args:   # arduino-pico picks the pins this way
                facts.i2c = True
                before = len(facts.uses)
                add(args[0], "i2c_sda" if meth == "setSDA" else "i2c_scl", s, m.start())
                facts.i2c_pins += facts.uses[before:]
            elif t == "TwoWire":
                facts.i2c = True
                if len(args) >= 2 and (meth == "setPins" or not re.fullmatch(r"0x[0-9a-fA-F]+", args[0])):
                    before = len(facts.uses)
                    add(args[0], "i2c_sda", s, m.start())
                    add(args[1], "i2c_scl", s, m.start())
                    facts.i2c_pins += facts.uses[before:]
            elif t == "SPIClass" and meth == "begin":
                for a in args[:4]:
                    add(a, "io", s, m.start())
            elif t == "HardwareSerial" and meth == "begin" and len(args) >= 4:
                add(args[2], "io", s, m.start())
                add(args[3], "io", s, m.start())
            elif t == "HardwareSerial" and meth == "setPins" and len(args) >= 2:
                add(args[0], "io", s, m.start())
                add(args[1], "io", s, m.start())
            elif t == "Servo" and meth == "attach" and args:
                add(args[0], "servo", s, m.start())
            elif t == "ESP32PWM" and meth == "attachPin" and args:
                add(args[0], "pwm", s, m.start())
            elif t == "Adafruit_NeoPixel" and meth == "setPin" and args:
                add(args[0], "neopixel", s, m.start())
        for m in re.finditer(r"\b(Adafruit_NeoPixel|OneWire|DHT|Adafruit_SSD1306|U8G2_\w+|U8X8_\w+)\b(?:\s+[*&]?\s*[A-Za-z_]\w*)?\s*\(", code):
            t = m.group(1)
            args = _split(code[m.end():_match(code, m.end() - 1)])
            if t == "Adafruit_NeoPixel" and len(args) >= 2:
                add(args[1], "neopixel", s, m.start())
            elif t in ("OneWire", "DHT") and args:
                add(args[0], "onewire" if t == "OneWire" else "dht", s, m.start())
            elif t == "Adafruit_SSD1306" and len(args) == 4 and "Wire" in args[2]:
                add(args[3], "output", s, m.start())
            elif t.startswith(("U8G2_", "U8X8_")):
                a = args[1:] if t.startswith("U8G2_") else args
                if t.endswith("_HW_I2C") and not t.endswith("2ND_HW_I2C"):
                    facts.i2c = True
                    if len(a) >= 1:
                        add(a[0], "output", s, m.start())
                    if len(a) >= 3:
                        before = len(facts.uses)
                        add(a[2], "i2c_sda", s, m.start())
                        add(a[1], "i2c_scl", s, m.start())
                        facts.i2c_pins += facts.uses[before:]
                elif t.endswith("_SW_I2C") and len(a) >= 2:
                    facts.i2c = True
                    before = len(facts.uses)
                    add(a[1], "i2c_sda", s, m.start())
                    add(a[0], "i2c_scl", s, m.start())
                    facts.i2c_pins += facts.uses[before:]
                    if len(a) >= 3:
                        add(a[2], "output", s, m.start())
        for m in re.finditer(r"\bFastLED\s*\.\s*addLeds\s*<", code):
            targs = _split(code[m.end():_match(code, m.end() - 1)], angle=True)
            if len(targs) >= 2:
                add(targs[1], "neopixel", s, m.start())
        if _I2C_LIBS.search(s.text) or re.search(r"\bWire1?\s*\.", code):
            facts.i2c = True
        if re.search(r"#\s*include\s*[<\"](WiFi|WebServer|HTTPClient|ESPAsyncWebServer|WiFiClientSecure|PubSubClient)\.h", s.text) or \
                re.search(r"\bWiFi\s*\.", code):
            facts.wifi = True


# ------------------------------------------------------------------ Arduino: preprocessing and the compile
def _sketch_order(names: list[str], files: dict[str, str]) -> list[str]:
    inos = sorted(n for n in names if n.endswith(".ino"))
    main = next((n for n in inos if re.search(r"\bvoid\s+setup\s*\(", _lex(files[n])[0])), inos[0] if inos else None)
    return ([main] if main else []) + [n for n in inos if n != main]


def _prototypes(order: list[str], srcs: dict[str, Src]) -> tuple[str | None, int, str]:
    """Where the IDE puts the generated prototypes (the file and offset of the first function definition) and the text."""
    first = next(((n, srcs[n].funcs[0]["decl"]) for n in order if srcs[n].funcs), None)
    if not first:
        return None, 0, ""
    # types declared after that place cannot appear in a prototype there (the IDE stumbles on them; here they are skipped)
    after = "\n".join([srcs[first[0]].code[first[1]:], *(srcs[n].code for n in order[order.index(first[0]) + 1:])])
    later = set(re.findall(r"\b(?:struct|class|enum(?:\s+class)?|union|typedef[^;]*?|using)\s+([A-Za-z_]\w*)", after))
    protos: list[str] = []
    for name in order:
        s = srcs[name]
        for f in s.funcs:
            if "::" in f["name"] or not f["ret"] or re.search(r"\b(template|operator)\b", f["ret"] + f["name"]):
                continue
            params = [_split(p.replace("=", ",", 1), angle=True)[0] if "=" in p else p for p in f["params"]]
            sig = " ".join(f"{f['ret']} {f['name']}({', '.join(params)})".split())
            if any(re.search(rf"\b{re.escape(t)}\b", sig) for t in later):
                continue
            protos.append(f'#line {s.line(f["decl"])} "{name}"\n{sig};')
    return first[0], first[1], "\n".join(protos)


def _merge(order: list[str], files: dict[str, str], srcs: dict[str, Src]) -> str:
    """The .ino files as the IDE hands them to the compiler: one translation unit, #line directives back to each file."""
    at_file, at_off, protos = _prototypes(order, srcs)
    out = ["#include <Arduino.h>"]
    for name in order:
        text = files[name]
        out.append(f'#line 1 "{name}"')
        if name == at_file and protos:
            line = srcs[name].line(at_off)
            text = f'{text[:at_off]}\n{protos}\n#line {line} "{name}"\n{text[at_off:]}'
        out.append(text)
    return "\n".join(out) + "\n"


_GXX: dict[str, Any] = {}


def gxx() -> str | None:
    """The C++ compiler: FW_GXX, g++ on PATH, or Strawberry Perl's on Windows."""
    if "path" not in _GXX:
        cands = [os.environ.get("FW_GXX") or "", shutil.which("g++") or "", r"C:\Strawberry\c\bin\g++.exe" if sys.platform == "win32" else ""]
        _GXX["path"] = next((c for c in cands if c and Path(c).exists()), None)
    return _GXX["path"]


async def _run(cmd: list[str], cwd: str, timeout: float) -> tuple[int, str]:
    env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except NotImplementedError:   # an event loop without subprocesses (the selector loop on Windows)
        r = await asyncio.to_thread(subprocess.run, cmd, cwd=cwd, env=env, capture_output=True, timeout=timeout, check=False)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:   # timed out, or the whole check was cancelled: the compiler must not outlive it
        if proc.returncode is None:
            proc.kill()
            await asyncio.shield(proc.wait())
        raise
    return proc.returncode or 0, out.decode("utf-8", "replace")


async def _system_dirs(path: str) -> list[str]:
    """The compiler's own include directories (what `g++ -v` searches)."""
    if "sys" not in _GXX:
        dirs: list[str] = []
        try:
            _, out = await _run([path, "-E", "-x", "c++", "-v", os.devnull], str(STUBS), PRE_S)
            inside = False
            for ln in out.splitlines():
                if ln.startswith("#include <...> search starts here"):
                    inside = True
                elif ln.startswith("End of search list"):
                    break
                elif inside and ln.strip():
                    dirs.append(os.path.normcase(str(Path(ln.strip()).resolve())))
        except Exception:  # noqa: BLE001
            pass
        _GXX["sys"] = dirs
    return _GXX["sys"]


async def _reads_outside(path: str, cmd_tail: list[str], cwd: str, roots: list[str]) -> list[str]:
    """Run the preprocessor alone (-E -H, output discarded) and list the files it opened outside the allowed roots: the
    include guard's second line, for whatever the text scan cannot see (line splices, macros naming the header)."""
    _, out = await _run([path, "-E", "-H", "-o", os.devnull, *cmd_tail], cwd, PRE_S)
    allowed = [os.path.normcase(str(Path(r).resolve())) for r in roots] + await _system_dirs(path)
    bad = []
    for ln in out.splitlines():
        m = re.match(r"^\.+ (.+)$", ln)
        if not m:
            continue
        p = os.path.normcase(str((Path(cwd) / m.group(1).strip()).resolve()))
        if not any(p == a or p.startswith(a.rstrip("\\/") + os.sep) for a in allowed):
            bad.append(m.group(1).strip())
    return bad


async def _version(path: str) -> str:
    if "version" not in _GXX:
        try:
            _, out = await _run([path, "-dumpfullversion"], str(STUBS), 5)
            _GXX["version"] = out.strip().splitlines()[0][:20] if out.strip() else ""
        except Exception:  # noqa: BLE001
            _GXX["version"] = ""
    return _GXX["version"]


_STUB_IDENTS: set[str] = set()


def _stub_idents() -> set[str]:
    if not _STUB_IDENTS:
        for p in STUBS.rglob("*.h"):
            _STUB_IDENTS.update(re.findall(r"[A-Za-z_]\w+", p.read_text(encoding="utf-8", errors="replace")))
        _STUB_IDENTS.update(("setup", "loop", "Serial", "String", "millis", "delay"))
    return _STUB_IDENTS


def _host_header(name: str) -> bool:
    base = name[:-2] if name.endswith(".h") else name
    return (name.endswith(".h") and base in _STD_C) or (not name.endswith(".h") and "." not in name and name in _STD_CXX) or \
        name.startswith(("sys/", "bits/"))


def _unsafe_includes(srcs: Any) -> list[tuple[str, int, str]]:
    """#include lines naming anything but a plain relative header (an absolute path, '..', a macro): the compile would read
    files of the server. Directives are found in the code with comments blanked and line splices joined; digraphs count."""
    out = []
    for s in srcs:
        code = s.code
        for m in re.finditer(r"(?:^|\n)[ \t]*(?:#|%:)[ \t]*(?:\\\n[ \t]*)*(include_next|include|import|embed)\b", code):
            end = code.find("\n", m.end())
            end = len(code) if end < 0 else end
            k = len(code[m.end():end].rstrip())   # a trailing comment is blank in code
            arg = s.text[m.end():m.end() + k].strip()
            ok = re.fullmatch(r'(<|")([\w.+-]+(?:/[\w.+-]+)*)(>|")', arg)
            if not ok or ".." in arg or (ok.group(1) == "<") != (ok.group(3) == ">"):
                out.append((s.name, s.line(m.end()), arg or "(continued line)"))
    return out


def _generated(files: dict[str, str], srcs: list[Src]) -> tuple[dict[str, str], list[str]]:
    """Headers made for this sketch: the U8g2 classes and fonts it names, GFX fonts, empty files for unknown libraries."""
    gen: dict[str, str] = {}
    unknown: list[str] = []
    code = "\n".join(s.code for s in srcs)
    lines = []
    for cls in sorted(set(re.findall(r"\b(U8[GX][28X]_[A-Z0-9_]+)\b", code))):
        bm = re.search(r"_(2ND_4W_HW_SPI|2ND_HW_I2C|HW_I2C|SW_I2C|4W_SW_SPI|4W_HW_SPI|3W_SW_SPI|3W_HW_SPI|6800|8080)$", cls)
        if bm and cls not in ("U8G2_R0",):
            bus = "PARALLEL" if bm.group(1) in ("6800", "8080") else bm.group(1)
            lines.append(f"FW_{cls[:4]}_{bus}({cls})")
    for font in sorted(set(re.findall(r"\b(u8[gx]2?_font_\w+)", code))):
        lines.append(f"extern const uint8_t {font}[];")
    if lines:
        gen["fw_u8g2_gen.h"] = "#pragma once\n" + "\n".join(lines) + "\n"
    for s in srcs:
        for m in re.finditer(r'^[ \t]*#[ \t]*include[ \t]*[<"]([^>"\n]+)[>"]', s.text, re.M):
            inc = m.group(1).strip()
            if inc in files or os.path.basename(inc) in files or (STUBS / inc).exists() or _host_header(inc) or inc in gen:
                continue
            if not re.fullmatch(r"[\w.+-]+(/[\w.+-]+)*", inc) or ".." in inc:
                continue
            if fm := re.fullmatch(r"Fonts/(\w+)\.h", inc):
                gen[inc] = f"#pragma once\n#include <gfxfont.h>\nextern const GFXfont {fm.group(1)};\n"
                continue
            gen[inc] = "#pragma once\n"
            if inc not in unknown:
                unknown.append(inc)
    return gen, unknown


_DIAG = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^:\n]*?):(?P<line>\d+):(?:(?P<col>\d+):)? (?P<kind>fatal error|error|warning|note): (?P<msg>.*)$")
_CTX = re.compile(r"^(?:In file included from |\s+from )?(?P<file>(?:[A-Za-z]:)?[^:\n]*?):(?P<line>\d+)(?::\d+)?[:,]")
# g++ warnings worth passing on (the rest of -Wall is noise for a sketch)
_WARN_KEEP = re.compile(r"\[-W(format[\w=-]*|parentheses|address|overflow|div-by-zero|int-in-bool-context|misleading-indentation|"
                        r"logical-not-parentheses|bool-compare|sizeof-pointer-div|return-local-addr|tautological-compare|array-bounds|"
                        r"narrowing|maybe-uninitialized|uninitialized|implicit-fallthrough)")


def _diagnostics(out: str, user: set[str]) -> tuple[list[dict], list[dict]]:
    """g++'s output as items on the sketch's own files; an error inside a stub is put on the user line that led there."""
    errors: list[dict] = []
    warnings: list[dict] = []
    ctx: tuple[str, int] | None = None
    last: dict | None = None
    cands = 0
    for raw in out.splitlines():
        line = raw.replace("\u2018", "'").replace("\u2019", "'").rstrip()
        m = _DIAG.match(line)
        if not m:
            c = _CTX.match(line)
            if c and os.path.basename(c.group("file")) in user:
                ctx = (os.path.basename(c.group("file")), int(c.group("line")))
            continue
        f, ln, kind, msg = os.path.basename(m.group("file")), int(m.group("line")), m.group("kind"), m.group("msg").strip()
        if kind == "fatal error":
            kind = "error"
        if kind == "note":
            if f in user and "required from" in msg:
                ctx = (f, ln)
            if last is not None and msg.startswith("candidate") and cands < 3:
                last["hint"] = ((last.get("hint") + "; ") if last.get("hint") else "candidates: ") + msg.split(":", 1)[-1].strip()[:140]
                cands += 1
            continue
        if f not in user:
            if ctx is None:
                continue
            f, ln = ctx
        ctx = None
        if kind == "warning":
            if _WARN_KEEP.search(msg) and "-Werror" not in msg:
                last = _item("compile_warning", f, ln, msg)
                warnings.append(last)
            else:
                last = None
            continue
        msg = msg.replace(" [-Werror=return-type]", "")
        if any(e["file"] == f and e["line"] == ln for e in errors):
            last = None   # the first error on a line says it; the rest follow from it
            continue
        last = _item("compile", f, ln, msg)
        errors.append(last)
        cands = 0 if "no matching" in msg else 3   # candidate lists help only when no overload fits
    return errors, warnings


def _taint_filter(errors: list[dict], unknown: list[str], sk: Sketch, srcs: dict[str, Src]) -> list[dict]:
    """With unchecked headers, drop the errors their identifiers cause: names g++ cannot find that the sketch does not
    declare and that are not a typo of something known, variables of those types, and every error on a line using them."""
    if not unknown:
        return errors
    known = _stub_idents() | sk.declared
    taint: set[str] = set()
    for e in errors:
        for name in re.findall(r"'([A-Za-z_]\w*)' (?:was not declared|does not name a type|has not been declared|is not a type|"
                               r"is not a namespace|is not a class)", e["msg"]):
            if name not in known and not difflib.get_close_matches(name, known, n=1, cutoff=0.85):
                taint.add(name)
    code = "\n".join(s.code for s in srcs.values())
    for _ in range(2):
        for t in list(taint):
            taint |= set(re.findall(rf"\b{re.escape(t)}\b\s*(?:<[^;>]*>)?\s*[*&]?\s*([A-Za-z_]\w*)\s*[;(=\[{{,)]", code))
    taint -= {"if", "return", "else", "new", "const", "static"}
    keep = []
    for e in errors:
        quoted = set(re.findall(r"[A-Za-z_]\w*", " ".join(re.findall(r"'([^']*)'", e["msg"]))))
        src = srcs.get(e["file"])
        on_line = set(re.findall(r"[A-Za-z_]\w*", src.line_text(e["line"]))) if src else set()
        if not (taint & quoted or taint & on_line):
            keep.append(e)
    return keep


# calls one chip has and another lacks (ESP-IDF 5.x soc_caps.h): (names, the chips that have them, what to do elsewhere).
# A name the stubs declare but this chip lacks gets one of these hints; nothing else is ever called chip-specific.
_TOUCH = ("touchRead", "touchAttachInterrupt", "touchAttachInterruptArg", "touchDetachInterrupt", "touchInterruptGetLastStatus",
          "touchSleepWakeUpEnable", "touchSetCycles", "esp_sleep_enable_touchpad_wakeup", "esp_sleep_get_touchpad_wakeup_status",
          *(f"T{n}" for n in range(15)))
_RTCIO = ("rtc_gpio_init", "rtc_gpio_deinit", "rtc_gpio_get_level", "rtc_gpio_set_level", "rtc_gpio_set_direction",
          "rtc_gpio_set_direction_in_sleep", "rtc_gpio_pullup_en", "rtc_gpio_pullup_dis", "rtc_gpio_pulldown_en", "rtc_gpio_pulldown_dis",
          "rtc_gpio_hold_en", "rtc_gpio_hold_dis", "rtc_gpio_isolate", "rtc_gpio_force_hold_en_all", "rtc_gpio_force_hold_dis_all",
          "rtc_gpio_wakeup_enable", "rtc_gpio_wakeup_disable", "rtc_io_number_get")
CHIP_ONLY: list[tuple[tuple[str, ...], set[str], str]] = [
    (("esp_sleep_enable_ext0_wakeup", "esp_sleep_enable_ext1_wakeup", "esp_sleep_enable_ext1_wakeup_io", "esp_sleep_disable_ext1_wakeup_io",
      "esp_sleep_get_ext1_wakeup_status"), {"ESP32", "ESP32-S3"},
     "the {mcu} has no ext0/ext1 wake-up: esp_deep_sleep_enable_gpio_wakeup(1ULL << gpio, ESP_GPIO_WAKEUP_GPIO_LOW) wakes it from "
     "deep sleep, on GPIO0-5 (D0-D3) only; the timer wake-up works as on every ESP32"),
    (("esp_deep_sleep_enable_gpio_wakeup", "esp_sleep_get_gpio_wakeup_status"), {"ESP32-C3"},
     "the {mcu} wakes from deep sleep on a pin with esp_sleep_enable_ext0_wakeup(GPIO_NUM_x, level) or "
     "esp_sleep_enable_ext1_wakeup_io(mask, ESP_EXT1_WAKEUP_ANY_LOW)"),
    (_TOUCH, {"ESP32", "ESP32-S3"}, "the {mcu} has no capacitive touch: use a button, or a TTP223 touch module read with digitalRead()"),
    (("esp_sleep_enable_ulp_wakeup",), {"ESP32", "ESP32-S3"}, "the {mcu} has no ULP coprocessor: wake it with the timer or a GPIO"),
    (_RTCIO, {"ESP32", "ESP32-S3"}, "the {mcu} has no RTC IO: gpio_pullup_en()/gpio_pulldown_en() with gpio_hold_en() and "
     "gpio_deep_sleep_hold_en() keep a pin's level through deep sleep"),
    (("dacWrite", "dacDisable"), {"ESP32"}, "the {mcu} has no DAC: PWM (analogWrite or ledcWrite) through an RC filter"),
    (("analogSetWidth", "analogSetVRefPin", "hallRead", "adcAttachPin", "analogSetCycles", "analogSetSamples"), {"ESP32"},
     "not in arduino-esp32 3.x for the {mcu}: analogReadResolution(bits) sets the width, analogRead() needs no attach"),
]


def _chip_hint(name: str, mcu: str) -> str | None:
    if not mcu:
        return None
    for names, has, hint in CHIP_ONLY:
        if name in names and mcu not in has:
            return hint.format(mcu=mcu)
    if mcu == "RP2040" and re.match(r"(esp_|ledc|rtc_gpio|touch[A-Z]|gpio_[a-z]+_en|timerAlarm|timerBegin)", name):
        return f"an ESP32 call: the {mcu} does not have it (arduino-pico has its own API)"
    return None


_HEADERS: dict[str, Any] = {}


def _header_of(name: str) -> str | None:
    """The stub header that declares `name` at file level (a function, macro, type, enumerator, extern object), for
    'add #include <...>'; parameter and member names do not count."""
    if "index" not in _HEADERS:
        _HEADERS["index"] = {p.relative_to(STUBS).as_posix(): p.read_text(encoding="utf-8", errors="replace") for p in sorted(STUBS.rglob("*.h"))}
        owner: dict[str, str] = {}
        for h, t in _HEADERS["index"].items():
            names = set(re.findall(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)", t, re.M))
            names |= set(re.findall(r"^(?:extern\s+|static\s+|inline\s+)*[\w:<>]+[\w\s:<>*&]*?[\s*&]([A-Za-z_]\w*)\s*\(", t, re.M))
            names |= set(re.findall(r"^\s*(?:class|struct)\s+([A-Za-z_]\w*)", t, re.M)) | set(re.findall(r"\}\s*([A-Za-z_]\w*)\s*;", t))
            names |= set(re.findall(r"^extern\s+[^;(]*?([A-Za-z_]\w*)\s*(?:\[\])?\s*;", t, re.M))
            names |= set(re.findall(r"^typedef\s[^;{]*?([A-Za-z_]\w*)\s*;", t, re.M))
            for body in re.findall(r"\benum\b[^{;]*\{([^}]*)\}", t):
                names |= set(re.findall(r"(?:^|,)\s*([A-Za-z_]\w*)", body))
            for n in names:
                owner.setdefault(n, h)
        _HEADERS["owner"] = owner
    return _HEADERS["owner"].get(name)


def _reachable(text: str) -> set[str]:
    """Stub headers a source sees: Arduino.h and what it includes, plus its own #includes, transitively (any #if branch)."""
    index = _HEADERS.get("index") or {}
    todo = ["Arduino.h", *re.findall(r'^[ \t]*#[ \t]*include[ \t]*[<"]([^>"]+)[>"]', text, re.M)]
    seen: set[str] = set()
    while todo:
        h = todo.pop()
        if h in seen or h not in index:
            continue
        seen.add(h)
        base = h.rsplit("/", 1)[0] + "/" if "/" in h else ""
        for inc in re.findall(r'^[ \t]*#[ \t]*include[ \t]*[<"]([^>"]+)[>"]', index[h], re.M):
            todo += [inc, os.path.normpath(base + inc).replace("\\", "/")]
    return seen


def _hints(errors: list[dict], srcs: dict[str, Src], sk: Sketch | None, board: Board | None) -> None:
    known = (_stub_idents() | (sk.declared if sk else set()))
    for e in errors:
        msg, src = e["msg"], srcs.get(e["file"])
        text = src.line_text(e["line"]) if src else ""
        if re.search(r"[^\x00-\x7f]", text) and not e.get("hint"):
            e["hint"] = "this line has text outside a comment or string (a note without // in front?)"
        elif "invalid use of non-static member function" in msg or re.search(r"cannot convert '[\w:]+::\w+' from type '[^']*\(\w+::\*?\)", msg):
            e["hint"] = ("a member function named without calling it (no parentheses); to remember whether begin() worked, keep "
                         "your own bool: bool ok = display.begin(...);")
        elif "control reaches end of non-void function" in msg:
            e["hint"] = "return a value on every path: on the chip, falling off the end of the function crashes it"
        elif re.search(r"conversion from '[\w ]+' to '(const )?String' is ambiguous|conversion from '[\w ]+' to non-scalar type 'String'", msg):
            e["hint"] = "String's number constructors are explicit: String(value)"
        elif m := re.search(r"'([A-Za-z_]\w*)' was not declared", msg):
            name = m.group(1)
            mcu = (device.MODULES.get(board.mpn) or {}).get("mcu", board.name) if board else ""
            if name == "LED_BUILTIN" and board:
                e["hint"] = f"the {board.name} has no user LED (LED_BUILTIN): drive an LED the board wires"
            elif hint := _chip_hint(name, mcu):
                e["hint"] = hint
                e["msg"] = re.sub(r"; did you mean '[^']*'\?$", "", msg)   # g++'s nearest name is not the way on this chip
            elif (h := _header_of(name)) and h not in _reachable(src.text if src else ""):
                e["hint"] = f"declared in <{h}>: #include <{h}>"
            elif "did you mean" not in msg and (close := difflib.get_close_matches(name, known - {name}, n=1, cutoff=0.8)):
                e["hint"] = f"did you mean {close[0]}?"
        elif "stray" in msg and "in program" in msg:
            e["hint"] = "non-ASCII characters outside a string or comment"


async def _arduino(files: dict[str, str], board: Board | None, facts: Facts, errors: list, warnings: list) -> str:
    srcs = {n: Src(n, t) for n, t in files.items()}
    order = _sketch_order(list(files), files)
    facts.main = order[0] if order else next(iter(files))
    sk = Sketch(list(srcs.values()), board)
    _uses(sk, facts)
    _static_cpp(sk, board, facts, errors, warnings)
    path = gxx()
    unsafe = _unsafe_includes(srcs.values())
    if unsafe:
        # the compiler would read that file and quote its tokens back: only headers by plain name are compiled
        for s, ln, what in unsafe:
            errors.append(_item("compile", s, ln, f"#include {what[:60]}: only library headers and the sketch's own files can be included",
                                "include headers by name: #include <Wire.h>, #include \"config.h\""))
        return "static only (include outside the sketch)"
    if not path:
        for s in srcs.values():
            for ln in range(1, len(s.nl) + 2):
                t = s.line_text(ln)
                if re.search(r"[^\x00-\x7f]", t) and not t.lstrip().startswith("#"):
                    errors.append(_item("compile", s.name, ln, "text outside a comment or string",
                                        "a note without // in front? (checked without a compiler: no g++ here)"))
        return "static only (no g++)"
    gen, unknown = _generated(files, list(srcs.values()))
    for inc in unknown:
        warnings.append(_item("library_unchecked", facts.main, 0, f"library <{inc}> has no stub here: calls into it are not checked",
                              "fine if it is a real Arduino library; name it in the firmware notes"))
    with tempfile.TemporaryDirectory(prefix="fwcheck-", ignore_cleanup_errors=True) as tmp:
        sketch, genroot = Path(tmp) / "sketch", Path(tmp) / "gen"
        sketch.mkdir()
        genroot.mkdir()
        for rel, text in gen.items():
            p = genroot / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        units = []
        for n, t in files.items():
            if not n.endswith(".ino"):
                (sketch / n).write_text(t, encoding="utf-8")
                if n.endswith((".cpp", ".cc", ".cxx")):
                    units.append(n)
        if order:
            unit = f"{Path(order[0]).stem}__sketch.ino.cpp"
            (sketch / unit).write_text(_merge(order, files, srcs), encoding="utf-8")
            units.insert(0, unit)
        if not units:
            return "nothing to compile"
        b = board.spec if board else {}
        defs = ["ARDUINO=10819", *(b.get("defs") or _ESP), *([b["define"]] if b.get("define") else [])]
        if sys.platform == "win32":
            defs.append("_POSIX_THREAD_SAFE_FUNCTIONS=200112L")
        # -S (compile to assembly, no link) rather than -fsyntax-only: as fast here, and it reaches the passes that find a
        # function falling off its end, an error under arduino-esp32 (-Werror=return-type) and a crash on the chip
        common = [f"-std={STD}", "-I", str(genroot), "-I", str(STUBS), *[f"-D{d}" for d in defs]]
        cmd = [path, "-S", "-O0", "-fno-diagnostics-color", "-fno-diagnostics-show-caret", "-fmax-errors=40",
               "-Wall", "-Wno-unused", "-Wno-sign-compare", "-Wno-unknown-pragmas", "-Werror=return-type", *common, *units]
        try:
            outside = []
            for u in units:
                outside += await _reads_outside(path, [*common, u], str(sketch), [tmp, str(STUBS)])
            if outside:
                errors.append(_item("compile", facts.main, 0, f"the sketch includes {outside[0][:80]}: only library headers and the "
                                    "sketch's own files can be included", "include headers by name: #include <Wire.h>"))
                return "static only (include outside the sketch)"
            _, out = await _run(cmd, str(sketch), GXX_S)
        except (TimeoutError, subprocess.TimeoutExpired):
            warnings.append(_item("compile_timeout", facts.main, 0, f"the compile check took over {GXX_S:.0f} s and was stopped"))
            return "g++ (timed out)"
    found, warns = _diagnostics(out, set(files))
    found = _taint_filter(found, unknown, sk, srcs)
    _hints(found, srcs, sk, board)
    errors[:0] = found
    warnings.extend(warns)
    v = await _version(path)
    return f"g++ {v} compile, no link ({(b.get('core') if b else None) or 'arduino-esp32 3.x'} stubs{', ' + board.name if board else ''})"


# ------------------------------------------------------------------ Arduino: static checks
def _static_cpp(sk: Sketch, board: Board | None, facts: Facts, errors: list, warnings: list) -> None:
    code_all = "\n".join(s.code for s in sk.srcs)
    if re.search(r"\bledc(Setup|AttachPin)\s*\(", code_all) and (not board or board.spec.get("core", "").startswith("arduino-esp32")):
        s = next(s for s in sk.srcs if re.search(r"\bledc(Setup|AttachPin)\s*\(", s.code))
        m = re.search(r"\bledc(Setup|AttachPin)\s*\(", s.code)
        warnings.append(_item("core_api", s.name, s.line(m.start()), "ledcSetup()/ledcAttachPin() are arduino-esp32 2.x; core 3.x "
                              "(the current one) removed them and the sketch does not build there",
                              "ledcAttach(pin, freq, bits) then ledcWrite(pin, duty): by pin, no channels"))
    for s in sk.srcs:
        m2 = re.search(r"\btimerAlarm(?:Write|Enable|Disable)\s*\(|\btimerBegin\s*\([^;),]*,[^;),]*,", s.code)
        if m2 and (not board or board.spec.get("core", "").startswith("arduino-esp32")):
            warnings.append(_item("core_api", s.name, s.line(m2.start()), "timerBegin(num, divider, up) / timerAlarmWrite() / "
                                  "timerAlarmEnable() are arduino-esp32 2.x; core 3.x (the current one) removed them",
                                  "timerBegin(1000000) (Hz), timerAttachInterrupt(t, isr), timerAlarm(t, period_us, true, 0)"))
            break
    web = bool(re.search(r"\b(WebServer|ESP8266WebServer|AsyncWebServer|WiFiServer)\b|\.\s*handleClient\s*\(", code_all))
    for s in sk.srcs:
        for f in s.funcs:
            for c0, _c1, text in s.comments:
                if f["body"] < c0 < f["end"] and STUB_RE.search(text):
                    warnings.append(_item("stub", s.name, s.line(c0), f"a shortcut left in {f['name']}(): '{' '.join(text.split())[:90]}'",
                                          "finish it, or say in the notes what the device does not do yet"))
            if web and f["name"] == "loop":
                for m in re.finditer(r"(?<![\w.])delay\s*\(", s.code[f["body"]:f["end"]]):
                    off = f["body"] + m.start()
                    arg = s.code[f["body"] + m.end():_match(s.code, f["body"] + m.end() - 1)]
                    vals = [g for g, _ in sk.eval(arg, s, off)]
                    if vals and max(vals) >= 1000:
                        warnings.append(_item("blocking_delay", s.name, s.line(off), f"loop() waits {max(vals)} ms in delay() while the "
                                              "web server only answers between passes of loop(): the page hangs meanwhile",
                                              "time it with millis() instead of delay()"))
    _charset_cpp(sk, errors)


def _scripts(text: str) -> tuple[bool, bool, bool]:
    cyr = any("\u0400" <= ch <= "\u052f" for ch in text)
    lat = any("\u0080" <= ch <= "\u00ff" for ch in text)
    other = any(ord(ch) > 0x7f and not ("\u0400" <= ch <= "\u052f" or "\u0080" <= ch <= "\u00ff") for ch in text)
    return cyr, lat, other


def _font_covers(font: str, text: str) -> bool:
    cyr, lat, other = _scripts(text)
    f = font.lower()
    if cyr and "cyrillic" not in f:
        return False
    if lat and not (re.search(r"_[tmh][fe]$", f) or "unifont" in f):
        return False
    if other and not re.search(r"unifont|chinese|japanese|korean|symbol|emoticon|_t_\w+", f):
        return False
    return True


def _charset_cpp(sk: Sketch, errors: list) -> None:
    """Text with non-ASCII characters handed to a display that draws it byte by byte from an ASCII font."""
    objs: dict[str, tuple[str, str]] = {}
    for s in sk.srcs:
        for m in re.finditer(r"\b(Adafruit_\w+|GFXcanvas\w*|TFT_eS\w+|LiquidCrystal(?:_I2C)?|U8G2(?:_\w+)?|U8X8(?:_\w+)?)\b\s*[*&]?\s*"
                             r"([A-Za-z_]\w*)\s*[;(=,{]", s.code):
            t = m.group(1)
            fam = _DISPLAYS.get(t) or ("u8g2" if t.startswith(("U8G2", "U8X8")) else "gfx" if re.match(r"Adafruit_(SSD|SH|ST7|ILI|GFX)|GFXcanvas", t) else None)
            if fam and m.group(2) not in ("U8X8_PIN_NONE",):
                objs[m.group(2)] = (fam, t)
    if not objs:
        return
    code_all = "\n".join(s.code for s in sk.srcs)
    nonascii: set[str] = set()
    for s in sk.srcs:
        for m in re.finditer(r"\b(?:const\s+)?(?:char|String)\s*\*?\s*(?:const\s+)?([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*=", s.code):
            end = s.code.find(";", m.end())
            if any(m.end() <= a < (end if end >= 0 else len(s.code)) and re.search(r"[^\x00-\x7f]", t) for a, _b, t in s.strings):
                nonascii.add(m.group(1))
    for obj, (fam, typ) in objs.items():
        found: list[dict] = []
        utf8 = bool(re.search(rf"\b{obj}\s*(?:\.|->)\s*enableUTF8Print\s*\(", code_all))
        fonts = re.findall(rf"\b{obj}\s*(?:\.|->)\s*setFont\s*\(\s*([A-Za-z_]\w*)", code_all)
        smooth = bool(re.search(rf"\b{obj}\s*(?:\.|->)\s*loadFont\s*\(", code_all))
        for s in sk.srcs:
            for m in re.finditer(rf"\b{obj}\s*(?:\.|->)\s*({_PRINTS})\s*\(", s.code):
                meth = m.group(1)
                open_ = m.end() - 1
                close = _match(s.code, open_)
                bad = []
                for a, _b, t in s.strings:
                    if open_ < a < close and re.search(r"[^\x00-\x7f]", t):
                        wrap = _enclosing_call(s.code, a - 1, open_)
                        if wrap in (None, "", "String", "F", "PSTR", "FPSTR", meth):
                            bad.append(t)
                via = sorted(set(re.findall(r"[A-Za-z_]\w*", s.code[open_:close])) & nonascii)
                if not bad and not via:
                    continue
                q = f'"{bad[0][:40]}"' if bad else f"{via[0]} (non-ASCII text)"
                if fam == "u8g2":
                    if meth in ("drawStr", "drawStrX2", "drawString", "draw2x2String", "draw1x2String"):
                        why = f"{obj}.{meth}() draws single bytes: UTF-8 text comes out as garbage (drawUTF8() draws it)"
                    elif meth in ("print", "println", "printf", "write") and not utf8:
                        why = f"{obj}.{meth}() writes UTF-8 only after {obj}.enableUTF8Print()"
                    elif not fonts or not any(_font_covers(f, "".join(bad) or "Ж") for f in fonts):
                        why = (f"{obj}'s font ({', '.join(fonts) or 'none set'}) has no glyphs for these characters")
                    else:
                        continue
                elif fam == "tft" and smooth:
                    continue
                else:
                    kind = "a character LCD's ROM" if fam == "lcd" else "an ASCII font"
                    why = f"{typ} draws text with {kind}, so Cyrillic and other UTF-8 text comes out as garbage"
                found.append(_item("display_charset", s.name, s.line(m.start()), f"{q} on {obj}.{meth}(): {why}", _HINT_CHARSET))
        if len(found) > 5:
            rest = found[4:]
            found = [*found[:4], {**rest[0], "msg": f"{len(rest)} more lines print non-ASCII text on {obj} "
                                  f"(lines {', '.join(str(i['line']) for i in rest[:8])}): {rest[0]['msg']}"}]
        errors.extend(found)


# ------------------------------------------------------------------ MicroPython
def _micropython(files: dict[str, str], board: Board | None, facts: Facts, errors: list, warnings: list) -> str:
    facts.main = facts.main or next(iter(files))
    led = board.spec.get("led") if board else None
    for name, text in files.items():
        try:
            tree = ast.parse(text, filename=name)
        except SyntaxError as e:
            errors.append(_item("syntax", name, e.lineno or 0, f"{e.msg}", (e.text or "").strip()[:120] or None))
            facts.blind = True
            continue
        consts: dict[str, list[int]] = {}
        pins: dict[str, list[int]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                v = node.value
                if isinstance(v, ast.Constant) and isinstance(v.value, int) and not isinstance(v.value, bool):
                    consts[node.targets[0].id] = [v.value]
                elif isinstance(v, (ast.List, ast.Tuple)) and all(isinstance(x, ast.Constant) and isinstance(x.value, int) for x in v.elts):
                    consts[node.targets[0].id] = [x.value for x in v.elts]

        def val(x: ast.AST, consts: dict[str, list[int]] = consts, pins: dict[str, list[int]] = pins) -> list[int]:
            if isinstance(x, ast.Constant) and isinstance(x.value, int) and not isinstance(x.value, bool):
                return [x.value]
            if isinstance(x, ast.Constant) and x.value == "LED" and led is not None:
                return [led]
            if isinstance(x, ast.Name):
                return consts.get(x.id) or pins.get(x.id) or []
            if isinstance(x, ast.Subscript) and isinstance(x.value, ast.Name):
                return consts.get(x.value.id) or []
            if isinstance(x, ast.Call) and _fname(x) in ("Pin", "Signal") and x.args:
                return val(x.args[0])
            return []

        def use(gs: list[int], how: str, node: ast.AST, expr: str, file: str = name) -> None:
            for g in gs:
                if g != led:
                    facts.uses.append({"gpio": g, "how": how, "file": file, "line": getattr(node, "lineno", 0), "expr": expr[:40], "origin": None})

        calls = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call)), key=lambda n: (n.lineno, n.col_offset))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and \
                    isinstance(node.value, ast.Call) and _fname(node.value) == "Pin":
                pins[node.targets[0].id] = val(node.value)
        for c in calls:
            fn = _fname(c)
            kw = {k.arg: k.value for k in c.keywords if k.arg}
            expr = ast.get_source_segment(text, c) or fn
            if fn == "Pin" and c.args:
                mode = c.args[1] if len(c.args) > 1 else kw.get("mode")
                mname = mode.attr if isinstance(mode, ast.Attribute) else ""
                how = "output" if mname in ("OUT", "OPEN_DRAIN") else "input" if mname == "IN" else "io"
                use(val(c.args[0]), how, c, expr)
            elif fn == "PWM" and c.args:
                use(val(c.args[0]), "pwm", c, expr)
            elif fn == "ADC" and c.args:
                use(val(c.args[0]), "analog", c, expr)
            elif fn == "NeoPixel" and c.args:
                use(val(c.args[0]), "neopixel", c, expr)
            elif fn in ("DHT11", "DHT22") and c.args:
                use(val(c.args[0]), "dht", c, expr)
            elif fn == "OneWire" and c.args:
                use(val(c.args[0]), "onewire", c, expr)
            elif fn in ("I2C", "SoftI2C"):
                facts.i2c = True
                before = len(facts.uses)
                if "sda" in kw:
                    use(val(kw["sda"]), "i2c_sda", c, expr)
                if "scl" in kw:
                    use(val(kw["scl"]), "i2c_scl", c, expr)
                facts.i2c_pins += facts.uses[before:]
            elif fn in ("UART", "SPI", "SoftSPI"):
                for k in ("tx", "rx", "sck", "mosi", "miso"):
                    if k in kw:
                        use(val(kw[k]), "io", c, expr)
            elif fn == "text" and isinstance(c.func, ast.Attribute) and c.args and isinstance(c.args[0], ast.Constant) and \
                    isinstance(c.args[0].value, str) and re.search(r"[^\x00-\x7f]", c.args[0].value) and \
                    re.search(r"\b(ssd1306|sh1106|framebuf)\b", text):
                errors.append(_item("display_charset", name, c.lineno, f'"{c.args[0].value[:40]}" on .text(): the framebuf font is 8x8 '
                                    "ASCII, Cyrillic and other UTF-8 text comes out as garbage",
                                    "Show English text on the device (Russian is fine in print() and on the web page)"))
        if re.search(r"^\s*(?:import|from)\s+(?:network|socket)\b", text, re.M):
            facts.wifi = True
        facts.mentioned |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        funcs = [(n.lineno, n.end_lineno or n.lineno, n.name) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT and STUB_RE.search(tok.string):
                    f = next((f for f in funcs if f[0] < tok.start[0] <= f[1]), None)
                    if f:
                        warnings.append(_item("stub", name, tok.start[0], f"a shortcut left in {f[2]}(): '{tok.string.lstrip('# ')[:90]}'",
                                              "finish it, or say in the notes what the device does not do yet"))
        except (tokenize.TokenError, SyntaxError):
            pass
    return "python ast"


def _fname(c: ast.Call) -> str:
    f = c.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


# ------------------------------------------------------------------ the firmware against the graph
def _where(u: dict[str, Any]) -> tuple[str, int, str]:
    """Where to point at a pin use: the symbol that holds the number when there is one, else the call."""
    o = u.get("origin")
    if o:
        return o["file"], o["line"], o["name"]
    return u["file"], u["line"], f"pin {u['expr']}" if re.fullmatch(r"\d+", u["expr"]) else u["expr"]


def _meant(name: str, wiring: dict[int, dict[str, Any]], board: Board) -> str:
    """'; LED5 is on TX (GPIO21)' when the firmware's name for the pin names a part the board wires elsewhere."""
    for g, w in wiring.items():
        for p in w["parts"]:
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(p['id'])}(?![0-9])", name, re.I):
                return f"; {p['id']} is wired to {board.pin(g)}"
    return ""


def _pin_checks(board: Board, wiring: dict[int, dict[str, Any]], facts: Facts, errors: list, warnings: list) -> None:
    gpios = set(board.spec.get("gpios") or wiring)
    led = board.spec.get("led")
    by_gpio: dict[int, list[dict[str, Any]]] = {}
    for u in facts.uses:
        by_gpio.setdefault(u["gpio"], []).append(u)
    wired_list = ", ".join(f"{w['label']}: {_parts(w, 2)}" for g, w in wiring.items() if w["parts"] and "i2c" not in w["roles"])
    sda_d, scl_d = board.defaults
    for g, us in sorted(by_gpio.items()):
        w = wiring.get(g)
        drive = [u for u in us if u["how"] in OUT]
        read = [u for u in us if u["how"] in IN or u["how"] in ("io", "dht", "onewire")]
        bus = [u for u in us if u["how"].startswith("i2c")]
        first = (drive or read or bus)[0]
        f, ln, name = _where(first)
        if g == led:
            continue
        analog = [u for u in us if u["how"] == "analog"]
        if analog:
            fa, la, na = _where(analog[0])
            if board.spec.get("adc") is not None and g not in board.spec["adc"] and g not in board.spec.get("adc2", ()):
                adc = sorted(set(board.spec["adc"]) | set(board.spec.get("adc2", ())))
                errors.append(_item("adc_pin", fa, la, f"analog read of {board.pin(g)} ({na}): that pin has no ADC on the {board.name}",
                                    "ADC pins: " + ", ".join(board.pin(n) for n in adc if n in board.label_of) + " (wire the analog signal there)"))
            elif g in board.spec.get("adc2", ()) and facts.wifi:
                warnings.append(_item("adc_pin", fa, la, f"analog read of {board.pin(g)} ({na}): an ADC2 pin, which reads nothing while "
                                      "Wi-Fi is on", "use an ADC1 pin for analog sensors"))
        if w is None:
            if g in gpios or not board.spec:
                text = f"{name} is GPIO{g}, which the {board.name} does not bring out to a pin"
            else:
                text = f"{name} is GPIO{g}, which the {board.name} does not have"
            (errors if drive or bus else warnings).append(_item("pin_unwired", f, ln, text,
                                                               f"the module's pins: {', '.join(f'{lb}=GPIO{n}' for lb, n in board.gpio.items())}"))
            continue
        if not w["parts"] and "i2c" not in w["roles"]:
            if drive:
                errors.append(_item("pin_unwired", f, ln, f"{name} drives {board.pin(g)} ({first['how']}), but the board wires nothing "
                                    f"to {w['label']}{_meant(name, wiring, board)}", f"the board wires {wired_list}" if wired_list else None))
            elif read and not bus:
                warnings.append(_item("pin_unwired", f, ln, f"{name} reads {board.pin(g)}, but the board wires nothing to {w['label']} "
                                      "(a floating pin)", f"the board wires {wired_list}" if wired_list else None))
            continue
        roles = w["roles"] - {"pull"}
        if drive and "i2c" in roles:
            errors.append(_item("pin_conflict", f, ln, f"{name} drives {board.pin(g)} as an {drive[0]['how']}, but on the board "
                                f"{w['label']} is the I2C bus ({_parts(w)}){_meant(name, wiring, board)}",
                                "use the pin the board wires to that part; leave SDA/SCL to Wire"))
        elif drive and roles == {"button"}:
            errors.append(_item("pin_conflict", f, ln, f"{name} drives {board.pin(g)} as an {drive[0]['how']}, but the board wires a "
                                f"button there ({_parts(w)}){_meant(name, wiring, board)}", "read a button with pinMode(pin, INPUT_PULLUP)"))
        elif drive and roles and roles <= {"header"} and any(re.fullmatch(r"(A?OUT|DO|AO|SIG|SENSE|INT|ECHO)\d*", p["pin"], re.I) for p in w["parts"]):
            warnings.append(_item("pin_conflict", f, ln, f"{name} drives {board.pin(g)}, which the board wires to a sensor output "
                                  f"({_parts(w)}): two outputs fight"))
        elif read and not drive and roles and roles <= {"led", "buzzer", "driver"} and any(u["how"] in ("input", "interrupt") for u in read):
            warnings.append(_item("pin_conflict", f, ln, f"{name} reads {board.pin(g)}, which the board wires to {_parts(w)} "
                                  f"(an output part){_meant(name, wiring, board)}"))
        if bus and roles and not roles & {"i2c", "header", "io"}:
            errors.append(_item("i2c_pins", *_where(bus[0])[:2], f"I2C on {board.pin(g)}, but the board wires {_parts(w)} there"))
    # I2C: where the firmware puts the bus against where the board has it
    gsda = next((g for g, w in wiring.items() if "i2c" in w["roles"] and (w["label"] == "SDA" or any(re.search(r"SD", p["pin"], re.I) for p in w["parts"]))), None)
    gscl = next((g for g, w in wiring.items() if "i2c" in w["roles"] and g != gsda), None)
    if facts.i2c and (gsda is not None or gscl is not None):
        fw_sda = next((u for u in facts.i2c_pins if u["how"] == "i2c_sda"), None)
        fw_scl = next((u for u in facts.i2c_pins if u["how"] == "i2c_scl"), None)
        s_g, c_g = (fw_sda["gpio"] if fw_sda else sda_d), (fw_scl["gpio"] if fw_scl else scl_d)
        if (gsda is not None and s_g != gsda) or (gscl is not None and c_g != gscl):
            at = fw_sda or fw_scl
            f, ln = (at["file"], at["line"]) if at else (facts.main, 0)
            how = "the firmware puts" if at else "Wire's default pins put"
            i2c_parts = _parts(wiring[gsda if gsda is not None else gscl])
            if f.endswith(".py"):
                fix = f"I2C(0, sda=Pin({gsda}), scl=Pin({gscl}))"
            else:
                arg = [next((n for n in ("SDA", "SCL", board.label_of.get(x)) if n and board.names.get(n) == x), str(x)) for x in (gsda, gscl)]
                fix = f"Wire.begin({arg[0]}, {arg[1]})" if board.spec.get("core", "").startswith("arduino-esp32") else \
                    f"Wire.setSDA({gsda}); Wire.setSCL({gscl}); Wire.begin();"
            errors.append(_item("i2c_pins", f, ln, f"{how} I2C on SDA=GPIO{s_g}, SCL=GPIO{c_g}, but the board wires the I2C bus "
                                f"({i2c_parts}) to SDA={board.pin(gsda) if gsda is not None else '?'}, "
                                f"SCL={board.pin(gscl) if gscl is not None else '?'}", fix))
    elif facts.i2c_pins and gsda is None and gscl is None and any(w["parts"] for w in wiring.values()):
        warnings.append(_item("i2c_pins", facts.i2c_pins[0]["file"], facts.i2c_pins[0]["line"], "the firmware starts I2C but the board "
                              "wires no I2C device"))
    # wired parts the firmware never touches
    for g, w in wiring.items():
        if not w["parts"]:
            continue
        if "i2c" in w["roles"]:
            if not facts.i2c and g == gsda:
                warnings.append(_item("pin_unused", facts.main, 0, f"the board wires the I2C bus ({_parts(w)}) but the firmware never talks I2C"))
            continue
        names = {w["label"], *board.alias_of.get(w["label"], []), f"GPIO_NUM_{g}"} | {n for n, v in board.names.items() if v == g}
        if g in by_gpio or names & facts.mentioned:
            continue
        warnings.append(_item("pin_unused", facts.main, 0, f"the board wires {board.pin(g)} to {_parts(w)}, but the firmware never "
                              f"uses GPIO{g}", "drive or read it, or take it off the board"))


# ------------------------------------------------------------------ the requirements against the code
# what a requirement asks for, in the person's words (any language): sleep, and a fade; a negated or human 'sleep' is not one
SLEEP_ASK = re.compile(r"deep[\s-]?sleep|light[\s-]?sleep|\bsleeps?\b|\bsleeping\b|battery[\s-]?saving|\bсон\b|\bсна\b|\bсну\b|\bсном\b|"
                       r"спящ|засып|\bспит\b", re.I)
SLEEP_NOT = re.compile(r"(?:\bno|\bnot|\bnever|\bwithout|\bне|\bбез)\s+(?:[\w-]+\s+){0,2}?(?:sleep\w*|сна|сон|спит|спящ\w*|засып\w*)|"
                       r"sleep[\s-]?timer|таймер\w*\s+сна|\bсна\s+(?:ребён|ребен|малыш)\w*", re.I)
FADE_ASK = re.compile(r"плавн|затуха|разгора|\bfad(?:e|es|ed|ing)\b|\bdimm(?:ing|able|er)\b|smooth(?:ly)?\s+(?:dim|bright|on|off|turn|light)", re.I)
_SLEEP_CPP = re.compile(r"\b(esp_deep_sleep_start|esp_light_sleep_start|esp_deep_sleep|sleep_goto_\w+)\s*\(|"
                        r"\b(?:ESP|LowPower)\s*\.\s*(deepSleep\w*|lightSleep|sleep)\s*\(")
_WAKE_CPP = re.compile(r"\b(esp_sleep_enable_\w+|esp_deep_sleep_enable_gpio_wakeup)\s*\(")
_SLEEP_PY = ("deepsleep", "lightsleep")
# a call that sets a light's level -> the index of that argument (-2: any argument; -1: the call fades by itself)
_LEVEL_CPP = {"ledcWrite": 1, "analogWrite": 1, "setBrightness": 0, "setPixelColor": 1, "fill": 0, "Color": -2, "ColorHSV": -2,
              "gamma32": 0, "ledcFade": -1, "ledcFadeWithInterrupt": -1, "fadeToBlackBy": -1, "fadeLightBy": -1, "nscale8": -1,
              "nscale8_video": -1, "fadeUsingColor": -1, "blend": -1, "nblend": -1}
_LEVEL_RE = re.compile(r"(?<![\w])(" + "|".join(sorted(_LEVEL_CPP, key=len, reverse=True)) + r")\s*\(")
_TIME = re.compile(r"\b(millis|micros|esp_timer_get_time|sin|cos|sinf|cosf|exp|random|beatsin\w*|triwave8|quadwave8|cubicwave8)\s*\(")


def _requirements(doc: dict) -> list[dict[str, Any]]:
    out = []
    for i, r in enumerate(doc.get("requirements") if isinstance(doc.get("requirements"), list) else []):
        r = {"text": r} if isinstance(r, str) else r
        if isinstance(r, dict) and str(r.get("text") or "").strip():
            out.append({"id": str(r.get("id") or f"R{i + 1}")[:12], "text": " ".join(str(r["text"]).split())[:300],
                        "parts": [str(p) for p in r.get("parts") or [] if str(p).strip()] if isinstance(r.get("parts"), list) else [],
                        "firmware": r.get("firmware")})
    return out


def asks_sleep(text: str) -> bool:
    """Does a requirement's text ask the device to sleep (deep sleep, 'глубокий сон', battery-saving)? Not 'never sleeps',
    'без сна' or a lamp's sleep timer."""
    return bool(SLEEP_ASK.search(SLEEP_NOT.sub(" ", text or "")))


def asks_fade(text: str) -> bool:
    """Does it ask for a fade or smooth dimming ('плавное затухание', 'fades in', 'dimming')?"""
    return bool(FADE_ASK.search(text or ""))


def _inactive(code: str) -> str:
    """The code with what `#if 0` / `#if false` leaves out blanked (offsets kept). Any other condition counts as compiled:
    a branch the check cannot evaluate never makes a finding."""
    out = list(code)
    stack: list[str] = []   # per open #if: 'off' (the 0 branch), 'on' (its #else), 'any' (a condition not evaluated here)
    pos = 0
    for line in code.split("\n"):
        d = re.match(r"\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)", line)
        if d:
            kw, rest = d.group(1), d.group(2).strip()
            if kw.startswith("if"):
                stack.append("off" if kw == "if" and re.fullmatch(r"\(?\s*(0|false)\s*\)?", rest) else "any")
            elif kw == "else" and stack and stack[-1] == "off":
                stack[-1] = "on"
            elif kw == "elif" and stack and stack[-1] == "off":
                stack[-1] = "any"
            elif kw == "endif" and stack:
                stack.pop()
        elif "off" in stack:
            for k in range(pos, pos + len(line)):
                out[k] = " "
        pos += len(line) + 1
    return "".join(out)


def _reached_funcs(srcs: list[Src], codes: dict[str, str]) -> set[str]:
    """Names of the functions setup() and loop() reach through calls, callbacks and ISRs (a name used outside any function,
    in an initialiser, counts as reached too)."""
    funcs = [(s, f) for s in srcs for f in s.funcs]
    names = {f["name"].split("::")[-1] for _, f in funcs}
    outside = []
    for s in srcs:
        code, last = codes[s.name], 0
        for f in s.funcs:
            outside.append(code[last:f["decl"]])
            last = f["end"]
        outside.append(code[last:])
    top = " ".join(outside)
    seen: set[str] = set()
    todo = ["setup", "loop", "app_main"] + [n for n in names if re.search(rf"(?<![\w.]){re.escape(n)}\b", top)]
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        for s, f in funcs:
            if f["name"].split("::")[-1] == n:
                body = codes[s.name][f["body"]:f["end"]]
                todo += [m for m in names - seen if re.search(rf"(?<!\w){re.escape(m)}\b", body)]
    return seen


def _sleep_cpp(srcs: list[Src], codes: dict[str, str]) -> tuple[bool, str]:
    """(the code reaches a sleep call, why a sleep call that is there does not count: commented out, under #if 0, in a
    function nothing calls)."""
    reach = _reached_funcs(srcs, codes)
    unreached = ""
    for s in srcs:
        for m in _SLEEP_CPP.finditer(codes[s.name]):
            f = s.func_at(m.start())
            name = f["name"].split("::")[-1] if f else None
            if f is None or name in reach:
                return True, ""
            unreached = unreached or f"{m.group(1) or m.group(2)}() at {s.name}:{s.line(m.start())} is in {name}(), which nothing calls"
    if unreached:
        return False, unreached
    for s in srcs:
        for m in _SLEEP_CPP.finditer(s.text):
            if any(a <= m.start() < b for a, b, _ in s.comments):
                why = "commented out"
            elif _SLEEP_CPP.match(s.code, m.start()):
                why = "under #if 0"
            else:
                continue  # inside a string
            return False, f"{m.group(1) or m.group(2)}() at {s.name}:{s.line(m.start())} is {why}, so it never runs"
    for s in srcs:
        for m in _WAKE_CPP.finditer(s.text):
            if any(a <= m.start() < b for a, b, _ in s.comments):
                return False, f"only a wake source, {m.group(1)}() at {s.name}:{s.line(m.start())}, and it is commented out"
    return False, ""


def _varying_cpp(codes: dict[str, str]) -> set[str]:
    """Identifiers whose value changes as the program runs: stepped (++, --, +=, x = x ...), and what is computed from
    them or from the clock (one assignment deeper each pass)."""
    allc = "\n".join(codes.values())
    var = set(re.findall(r"\b([A-Za-z_]\w*)\s*(?:\+\+|--|[-+*/%]=)", allc)) | set(re.findall(r"(?:\+\+|--)\s*([A-Za-z_]\w*)", allc))
    assigns = [(m.group(1), m.group(2)) for m in re.finditer(r"\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*=(?!=)([^;]*)", allc)]
    var |= {n for n, e in assigns if re.search(rf"\b{re.escape(n)}\b", e)}
    for _ in range(3):
        more = {n for n, e in assigns if n not in var and (_TIME.search(e) or set(re.findall(r"[A-Za-z_]\w*", e)) & var)}
        if not more:
            break
        var |= more
    return var


def _fades_cpp(srcs: list[Src], codes: dict[str, str]) -> bool:
    """Some light level gets a value that changes: a stepped variable, the clock, or a function's parameter (its callers
    pass the steps); or a call that fades by itself (ledcFade, FastLED's fadeToBlackBy)."""
    var = _varying_cpp(codes)
    for s in srcs:
        code = codes[s.name]
        for m in _LEVEL_RE.finditer(code):
            k = _LEVEL_CPP[m.group(1)]
            if k == -1:
                return True
            args = _split(code[m.end():_match(code, m.end() - 1)])
            vals = args if k == -2 else args[k:k + 1]
            f = s.func_at(m.start())
            params = set(f["pnames"]) if f else set()
            for a in vals:
                ids = set(re.findall(r"[A-Za-z_]\w*", a))
                if _TIME.search(a) or ids & var or ids & params:
                    return True
    return False


def _py_facts(files: dict[str, str]) -> tuple[bool, bool, bool]:
    """(every file parsed, it calls deepsleep / lightsleep, it sets a PWM duty or a pixel from a changing value)."""
    sleeps = fades = False
    for name, text in files.items():
        try:
            tree = ast.parse(text, filename=name)
        except SyntaxError:
            return False, False, False
        var: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.For, ast.comprehension)) and isinstance(n.target, ast.Name):
                var.add(n.target.id)
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                var.add(n.target.id)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                var |= {a.arg for a in n.args.args}
        assigns = [(t.id, n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]

        def changes(e: ast.AST, var: set[str] = var) -> bool:
            return any(isinstance(x, ast.Name) and x.id in var for x in ast.walk(e)) or any(
                isinstance(x, ast.Call) and _fname(x) in ("ticks_ms", "ticks_us", "time", "sin", "cos") for x in ast.walk(e))
        for _ in range(3):
            more = {n for n, v in assigns if n not in var and changes(v)}
            if not more:
                break
            var |= more
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and _fname(n) in _SLEEP_PY:
                sleeps = True
            elif isinstance(n, ast.Call) and _fname(n) in ("duty", "duty_u16", "duty_ns") and n.args and changes(n.args[0]):
                fades = True
            elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Subscript) for t in n.targets) and changes(n.value) and "NeoPixel" in text:
                fades = True
    return True, sleeps, fades


def _sleep_hint(board: Board | None, py: bool) -> str:
    if py:
        return "machine.lightsleep(ms) or machine.deepsleep(ms) once the work is done, the wake pin set up before"
    mcu = (device.MODULES.get(board.mpn) or {}).get("mcu") if board else None
    wake = ("esp_deep_sleep_enable_gpio_wakeup(1ULL << 3, ESP_GPIO_WAKEUP_GPIO_LOW) (GPIO0-5 only)" if mcu == "ESP32-C3" else
            "esp_sleep_enable_ext0_wakeup(GPIO_NUM_3, 0)" if mcu == "ESP32-S3" else "the wake source")
    return f"switch the outputs off, enable {wake} and/or esp_sleep_enable_timer_wakeup(us), then call esp_deep_sleep_start() from loop()"


def _requirement_checks(doc: dict, cc: dict[str, str], py: dict[str, str], lang: str, board: Board | None,
                        wiring: dict[int, dict[str, Any]], facts: Facts, errors: list, warnings: list) -> None:
    """Each requirement against what the code really does: a requested sleep is reached, a requested fade changes a level,
    and a firmware requirement's parts are driven or read at all."""
    reqs = _requirements(doc)
    if not reqs:
        return
    yaml = {n: t for n, t in {**cc, **py}.items() if n.endswith((".yaml", ".yml")) or "esphome" in lang.lower()}
    srcs = [Src(n, t) for n, t in cc.items() if n not in yaml]
    codes = {s.name: _inactive(s.code) for s in srcs}
    parsed, py_sleep, py_fade = _py_facts({n: t for n, t in py.items() if n not in yaml}) if py else (True, False, False)
    if not parsed:
        return  # the syntax error is the finding
    main = facts.main or next(iter({**cc, **py}), "")
    want_sleep = [r for r in reqs if asks_sleep(r["text"])]
    if want_sleep:
        ok, why = _sleep_cpp(srcs, codes) if srcs else (False, "")
        ok = ok or py_sleep or any(re.search(r"^\s*deep_sleep\s*:", t, re.M) for t in yaml.values())
        if not ok:
            r = want_sleep[0]
            errors.append(_item("requirement_sleep", main, 0, f"requirement {r['id']} ('{r['text'][:90]}') asks the device to sleep, but the "
                                "firmware never goes to sleep: " + (why or "no esp_deep_sleep_start / esp_light_sleep_start / deepsleep call"),
                                _sleep_hint(board, bool(py) and not srcs)))
    want_fade = [r for r in reqs if asks_fade(r["text"])]
    if want_fade and not yaml and not (srcs and _fades_cpp(srcs, codes)) and not py_fade:
        r = want_fade[0]
        errors.append(_item("requirement_fade", main, 0, f"requirement {r['id']} ('{r['text'][:90]}') asks for a fade, but no light level "
                            "in the firmware changes over time: every ledcWrite / analogWrite / setBrightness / duty gets a fixed value",
                            "step the level in a loop or by millis(): for (int v = 255; v >= 0; v--) { ledcWrite(PIN, v); delay(4); } "
                            "(arduino-esp32 3.x: ledcAttach(PIN, 5000, 8) first), or scale the pixel colours by a changing level"))
    if not board or facts.blind:
        return
    by_gpio = {u["gpio"] for u in facts.uses}
    for r in reqs:
        if r.get("firmware") is not True or not r["parts"]:
            continue
        mine = {g: w for g, w in wiring.items() if any(p["id"] in r["parts"] for p in w["parts"])}
        if not mine:
            continue
        used = False
        for g, w in mine.items():
            names = {w["label"], *board.alias_of.get(w["label"], []), f"GPIO_NUM_{g}"} | {n for n, v in board.names.items() if v == g}
            if g in by_gpio or names & facts.mentioned or ("i2c" in w["roles"] and facts.i2c):
                used = True
                break
        if not used:
            pins = ", ".join(board.pin(g) for g in mine)
            warnings.append(_item("requirement_pins", main, 0, f"requirement {r['id']} ('{r['text'][:90]}') is firmware work, but the firmware "
                                  f"never touches {pins}, where its parts ({', '.join(r['parts'][:6])}) are wired",
                                  "implement it on those pins, or say in the summary that the code does not do it"))
