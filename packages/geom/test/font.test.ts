import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadKernel, makeLib, DEFAULT_PRINTER, withArena } from '../src/index.ts';
import { GLYPHS, layoutText } from '../src/lib/font.ts';

const wasm = await loadKernel();
const RU = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ';
const KK = 'ӘҒҚҢӨҰҮҺІ';

// strokes of a laid-out text, glyph by glyph, to compare with what the '#' fallback would give
const strokes = (text: string) => [...text.toUpperCase()].reduce((n, ch) => n + (ch === ' ' ? 0 : (GLYPHS[ch] ?? GLYPHS['#']).length), 0);

test('every Russian and Kazakh letter has its own glyph', () => {
  assert.equal(RU.length, 33);
  assert.equal(KK.length, 9);
  for (const ch of RU + KK) assert.ok(GLYPHS[ch], `no glyph for ${ch}`);
  // lowercase input is upper-cased on layout, ё and the Kazakh letters included
  for (const ch of 'ёйқңөұүһіә') assert.ok(GLYPHS[ch.toUpperCase()], `no glyph for ${ch}`);
});

test('a Cyrillic name lays out without the # fallback', () => {
  const text = 'БЕЛЫЙ КОТ ҚАЗАҚ ЁЖ';
  for (const ch of text) assert.ok(ch === ' ' || GLYPHS[ch], `${ch} would print as #`);
  const { lines, width } = layoutText(text, 6);
  assert.equal(lines.length, strokes(text));
  assert.notEqual(lines.length, strokes(text.replace(/\S/g, '#')));
  assert.ok(width > 6 * text.length * 0.6, `width ${width}`);
  // descenders (Д, Щ, Қ) and diacritics (Ё, Й) stay within a sixth of the size of the cap line
  const ys = layoutText('ДЩҚЁЙ', 6).lines.flat().map(([, y]) => y);
  assert.ok(Math.min(...ys) >= -1.01 && Math.max(...ys) <= 7.21);
});

test('std.text builds a solid from Cyrillic', () => {
  withArena(() => {
    const lib = makeLib(wasm, { printer: DEFAULT_PRINTER });
    const solid = lib.std.text('Белый кот - Қазақ ёж', { size: 5, depth: 0.8 });
    assert.equal(solid.status(), 'NoError');
    assert.ok(solid.volume() > 10, `volume ${solid.volume()}`);
    const b = solid.boundingBox();
    assert.ok(b.max[2] - b.min[2] > 0.79);
  });
});
