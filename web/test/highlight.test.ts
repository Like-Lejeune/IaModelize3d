// node --test web/test/highlight.test.ts: the firmware editor's colouring keeps every character of the source and
// tells comments, strings, numbers, keywords, types, calls and preprocessor lines apart in Arduino C++ and MicroPython.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { highlight, tokens, codeLang } = await import('../src/lib/device/highlight.ts');

const kinds = (src: string, lang: 'cpp' | 'python') => tokens(src, lang).map((t) => [t.kind, src.slice(t.start, t.end)]);
const unhtml = (h: string) => h.replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

const INO = `#include <Wire.h>
#define LED_PIN 8 // status LED
/* a comment
   over two lines */
const char* ssid = "home \\"wifi\\"";
void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  float t = 21.5f; uint32_t mask = 0xFF'00;
  if (t > 3 && ssid[0] != '\\n') digitalWrite(LED_PIN, HIGH);
}
`;

test('Arduino C++: every kind of token, and the text comes back unchanged', () => {
  const k = kinds(INO, 'cpp');
  assert.deepEqual(k[0], ['pp', '#include <Wire.h>']);
  assert.deepEqual(k[1], ['pp', '#define LED_PIN 8 ']);
  assert.deepEqual(k[2], ['com', '// status LED']);
  assert.deepEqual(k[3], ['com', '/* a comment\n   over two lines */']);
  const has = (kind: string, text: string) => assert.ok(k.some(([a, b]) => a === kind && b === text), `${kind} ${text}`);
  has('kw', 'const');
  has('type', 'char');
  has('str', '"home \\"wifi\\""');
  has('type', 'void');
  has('fn', 'setup');
  has('type', 'Serial');
  has('fn', 'begin');
  has('num', '115200');
  has('lit', 'LED_PIN');
  has('lit', 'OUTPUT');
  has('num', '21.5f');
  has('type', 'uint32_t');
  has('num', "0xFF'00");
  has('kw', 'if');
  has('str', "'\\n'");
  has('lit', 'HIGH');
  // the user's own names stay plain
  assert.ok(!k.some(([, b]) => b === 'ssid' || b === 't' || b === 'mask'));
  assert.equal(unhtml(highlight(INO, 'cpp')), INO);
  assert.match(highlight('a < b && c > d', 'cpp'), /a &lt; b &amp;&amp; c &gt; d/);
});

test('an unclosed comment or string does not swallow the wrong text', () => {
  assert.deepEqual(kinds('x = 1; /* open\nstill open', 'cpp').at(-1), ['com', '/* open\nstill open']);
  // an unclosed string stops at its line end
  assert.deepEqual(kinds('s = "oops\nint y;', 'cpp').slice(0, 2), [['str', '"oops'], ['type', 'int']]);
  assert.deepEqual(kinds('#define A(x) \\\n  ((x) + 1)\nint z;', 'cpp')[0], ['pp', '#define A(x) \\\n  ((x) + 1)']);
});

const PY = `import machine, time
from machine import Pin  # the LED
@micropython.native
def blink(n=3):
    """Blink n times.
    Twice as fast as before."""
    led = Pin(8, Pin.OUT)
    for _ in range(n):
        led.value(not led.value()); time.sleep_ms(250)
    return None
class Sensor:
    pass
print(f"done {0x1F}")
`;

test('MicroPython: comments, triple-quoted strings, decorators, defs and builtins', () => {
  const k = kinds(PY, 'python');
  const has = (kind: string, text: string) => assert.ok(k.some(([a, b]) => a === kind && b === text), `${kind} ${text}`);
  has('kw', 'import');
  has('kw', 'from');
  has('com', '# the LED');
  has('pp', '@micropython.native');
  has('kw', 'def');
  has('fn', 'blink');
  has('num', '3');
  has('str', '"""Blink n times.\n    Twice as fast as before."""');
  has('fn', 'Pin');
  has('type', 'range');
  has('kw', 'not');
  has('num', '250');
  has('lit', 'None');
  has('fn', 'Sensor');
  has('str', 'f"done {0x1F}"');
  assert.equal(unhtml(highlight(PY, 'python')), PY);
});

test('a file takes its tokenizer from its extension, then from the firmware language', () => {
  assert.equal(codeLang('main.ino'), 'cpp');
  assert.equal(codeLang('config.h', 'micropython'), 'cpp');
  assert.equal(codeLang('main.py', 'arduino'), 'python');
  assert.equal(codeLang('platformio.ini'), 'plain');
  assert.equal(codeLang('main', 'MicroPython'), 'python');
  assert.equal(codeLang('main', 'arduino'), 'cpp');
  assert.equal(highlight('a <b> & c', 'plain'), 'a &lt;b&gt; &amp; c');
});
