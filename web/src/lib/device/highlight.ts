// Syntax colouring for the firmware editor: a small tokenizer for Arduino C/C++ and MicroPython that turns source
// text into HTML spans (class "t-<kind>"), laid under the editable textarea. It only colours: anything it does not
// know stays plain text, and the output always holds exactly the input's characters.

export type CodeLang = 'cpp' | 'python' | 'plain';
export type TokenKind = 'com' | 'str' | 'num' | 'kw' | 'type' | 'fn' | 'pp' | 'lit';

const words = (s: string) => new Set(s.split(/\s+/).filter(Boolean));

const CPP_KW = words(`
  if else for while do switch case default break continue return goto sizeof alignof typedef struct union enum class
  public private protected virtual override final static const constexpr volatile extern inline register mutable
  explicit friend namespace using template typename operator new delete this try catch throw noexcept auto
  static_cast dynamic_cast const_cast reinterpret_cast decltype static_assert PROGMEM IRAM_ATTR`);
const CPP_TYPES = words(`
  void bool char short int long float double signed unsigned wchar_t size_t ssize_t int8_t int16_t int32_t int64_t
  uint8_t uint16_t uint32_t uint64_t uintptr_t intptr_t byte word boolean String Stream Print Serial Serial1 Serial2
  Wire SPI WiFi WiFiClient WiFiServer WebServer HTTPClient Preferences File SD EEPROM esp_err_t TaskHandle_t TickType_t`);
const CPP_LIT = words(`
  true false nullptr NULL HIGH LOW INPUT OUTPUT INPUT_PULLUP INPUT_PULLDOWN LED_BUILTIN CHANGE RISING FALLING
  LSBFIRST MSBFIRST DEC HEX BIN OCT PI`);

const PY_KW = words(`
  def class if elif else for while return import from as with try except finally raise pass break continue lambda
  yield global nonlocal assert del in is not and or async await match case`);
const PY_TYPES = words(`
  int float str bytes bytearray bool list dict tuple set frozenset object type len range print enumerate zip map
  filter min max abs sum sorted reversed isinstance hasattr getattr setattr super open repr round iter next
  memoryview Exception ValueError OSError RuntimeError KeyboardInterrupt self cls`);
const PY_LIT = words('None True False');

const CPP_RE = new RegExp(
  [
    // an unclosed block comment runs to the end of the file
    String.raw`(?<com>\/\/[^\n]*|\/\*[\s\S]*?(?:\*\/|(?![\s\S])))`,
    // a preprocessor line up to a comment, with backslash continuations
    String.raw`(?<pp>^[ \t]*#(?:\\\n|[^\n/]|\/(?![/*]))*)`,
    String.raw`(?<str>"(?:[^"\\\n]|\\[\s\S])*"?|'(?:[^'\\\n]|\\[\s\S])*'?)`,
    String.raw`(?<num>\b(?:0[xX][\da-fA-F']+|0[bB][01']+|\d[\d']*(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)[uUlLfF]*\b)`,
    String.raw`(?<id>[A-Za-z_]\w*)`,
  ].join('|'),
  'gm',
);

const PY_RE = new RegExp(
  [
    String.raw`(?<com>#[^\n]*)`,
    String.raw`(?<str>(?:\b[rRbBfFuU]{1,2})?(?:"""[\s\S]*?(?:"""|(?![\s\S]))|'''[\s\S]*?(?:'''|(?![\s\S]))|"(?:[^"\\\n]|\\[\s\S])*"?|'(?:[^'\\\n]|\\[\s\S])*'?))`,
    String.raw`(?<pp>^[ \t]*@[\w.]+)`,
    String.raw`(?<num>\b(?:0[xX][\da-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|\d[\d_]*(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)[jJ]?\b)`,
    String.raw`(?<id>[A-Za-z_]\w*)`,
  ].join('|'),
  'gm',
);

/** Which tokenizer a file takes: by its extension, else by the firmware's language ("arduino", "micropython", ...). */
export function codeLang(file: string, lang = ''): CodeLang {
  const ext = /\.([^./\\]+)$/.exec(file)?.[1]?.toLowerCase() ?? '';
  if (ext === 'py') return 'python';
  if (['ino', 'c', 'cc', 'cpp', 'cxx', 'h', 'hh', 'hpp', 'hxx'].includes(ext)) return 'cpp';
  if (ext) return 'plain';
  return /python/i.test(lang) ? 'python' : 'cpp';
}

/** The source as tokens: plain text between them is left out (its kind would be null). */
export function tokens(src: string, lang: CodeLang): { kind: TokenKind; start: number; end: number }[] {
  if (lang === 'plain') return [];
  const py = lang === 'python';
  const re = new RegExp(py ? PY_RE : CPP_RE);
  const [KW, TYPES, LIT] = py ? [PY_KW, PY_TYPES, PY_LIT] : [CPP_KW, CPP_TYPES, CPP_LIT];
  const out: { kind: TokenKind; start: number; end: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(src))) {
    if (!m[0]) {
      re.lastIndex++;
      continue;
    }
    const g = m.groups ?? {};
    const start = m.index, end = start + m[0].length;
    let kind: TokenKind | null = null;
    if (g.com != null) kind = 'com';
    else if (g.pp != null) kind = 'pp';
    else if (g.str != null) kind = 'str';
    else if (g.num != null) kind = 'num';
    else if (g.id != null) {
      const w = g.id;
      if (KW.has(w)) kind = 'kw';
      else if (LIT.has(w)) kind = 'lit';
      else if (TYPES.has(w)) kind = 'type';
      // a call or a definition: the name before "("
      else if (/^\s*\(/.test(src.slice(end, end + 40))) kind = 'fn';
      // an Arduino-style constant (LED_PIN, SDA, I2C_ADDR)
      else if (!py && /^[A-Z][A-Z\d_]+$/.test(w)) kind = 'lit';
      else if (py && /^(?:def|class)$/.test(prevWord(src, start))) kind = 'fn';
    }
    if (kind) out.push({ kind, start, end });
  }
  return out;
}

function prevWord(src: string, at: number): string {
  return /(\w+)\s+$/.exec(src.slice(Math.max(0, at - 12), at))?.[1] ?? '';
}

const esc = (s: string) => s.replace(/[&<>]/g, (c) => (c === '&' ? '&amp;' : c === '<' ? '&lt;' : '&gt;'));

/** The source as escaped HTML with a span per token. */
export function highlight(src: string, lang: CodeLang): string {
  let html = '';
  let at = 0;
  for (const t of tokens(src, lang)) {
    html += esc(src.slice(at, t.start)) + `<span class="t-${t.kind}">${esc(src.slice(t.start, t.end))}</span>`;
    at = t.end;
  }
  return html + esc(src.slice(at));
}
