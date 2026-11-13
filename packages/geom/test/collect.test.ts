import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { strFromU8, unzipSync } from 'fflate';
import { Engine, loadKernel, functionEvaluator, fromBase64, makeLib, DEFAULT_PRINTER, withArena } from '../src/index.ts';
import { NAME_MIN, STICKER_COLORS, makeCollect, openRelief } from '../src/lib/collect.ts';

const engine = new Engine(await loadKernel(), functionEvaluator());
// a SAM 3.1 mask of a cat photo through vision/relief.py (heightmap at half resolution)
const CAT = JSON.parse(readFileSync(new URL('./data/cat_relief.json', import.meta.url), 'utf8')) as {
  loops_px: [number, number][][];
  crop_px: [number, number, number, number];
  heightmap: { w: number; h: number; data: number[] };
  name: string;
};

// the program /api/snap/{id}/keep saves (server/iamodelize3d/collect.py STICKER_SOURCE)
const STICKER = `
const meta = { title: 'Snap sticker', pack: 'collect' };
const params = {
  size:   { value: 50,  min: 25,  max: 90, unit: 'mm', label: 'Longest side', source: 'design' },
  puff:   { value: 4,   min: 1.5, max: 9,  unit: 'mm', label: 'Relief',       source: 'design' },
  base:   { value: 1.6, min: 1.2, max: 4,  unit: 'mm', label: 'Base',         source: 'design' },
  border: { value: 2.2, min: 1,   max: 5,  unit: 'mm', label: 'Border',       source: 'design' },
};
function build(p, lib) { return lib.collect.sticker('subject', { ...p, name: lib.inputs.values.name }); }
return { meta, params, build };`;

const PLATE = `
const meta = { title: 'Collection plate', pack: 'collect' };
const params = { size: { value: 48, min: 25, max: 80, unit: 'mm', source: 'design' }, gap: { value: 6, min: 3, max: 15, unit: 'mm', source: 'design' } };
function build(p, lib) { return lib.collect.plate(lib.inputs.values.keys, { size: p.size, gap: p.gap }); }
return { meta, params, build };`;

function inputs(keys: string[], name: string | null = CAT.name) {
  const out = { outlines: {} as any, heightmaps: {} as any, values: {} as Record<string, string | number> };
  for (const k of keys) {
    out.outlines[k] = CAT.loops_px;
    out.heightmaps[k] = CAT.heightmap;
    [out.values[`${k}_x0`], out.values[`${k}_y0`], out.values[`${k}_x1`], out.values[`${k}_y1`]] = CAT.crop_px;
    if (name !== null) out.values[`${k}_name`] = name;
  }
  return out;
}

test('a snapped cat becomes a printable 3D sticker in well under 2.5 s', () => {
  const i = inputs(['subject']);
  i.values.name = CAT.name;
  const t = performance.now();
  const r = engine.build({ source: STICKER, inputs: i, analyze: 'full' }) as any;
  const ms = performance.now() - t;
  engine.release();
  assert.ok(ms < 2500, `build took ${ms.toFixed(0)} ms`);
  assert.equal(r.checks.ok, true);
  assert.equal(r.checks.score, 100);
  // the mini-slicer finds nothing to fix (a lone small sticker only gets the short-layer-time note)
  assert.deepEqual(r.checks.issues.filter((x: any) => x.severity !== 'info').map((x: any) => x.message), []);
  const [x, y, z] = r.checks.stats.size;
  assert.ok(Math.abs(x - 55) < 3 && Math.abs(y - 44) < 3 && z > 5.5 && z < 8, `size ${r.checks.stats.size}`);
  // three colours for a filament swap at the base's top
  assert.deepEqual(r.parts.map((p: any) => [p.name, p.color]), [['base', STICKER_COLORS.base], ['figure', STICKER_COLORS.figure], ['name', STICKER_COLORS.name]]);
  const base = r.parts[0].bbox, name = r.parts[2].bbox;
  assert.ok(Math.abs(base.max[2] - 1.6) < 1e-6);
  assert.ok(name.min[2] >= 1.6 - 1e-6 && name.max[2] <= 2.4 + 1e-6);
  assert.ok(name.max[1] - name.min[1] >= NAME_MIN, `letters ${(name.max[1] - name.min[1]).toFixed(2)} mm tall`);
  assert.ok(r.checks.stats.estGrams > 2 && r.checks.stats.estGrams < 7);
});

test('six finds fit one Bambu Lab A1 bed (256 x 256) as one 3MF', () => {
  const keys = ['a', 'b', 'c', 'd', 'e', 'f'];
  const i = { ...inputs(keys), values: { ...inputs(keys).values, keys: keys.join(',') } };
  const printer = { ...DEFAULT_PRINTER, name: 'Bambu Lab A1 0.4 nozzle', bed: [256, 256, 256] as [number, number, number] };
  const r = engine.build({ source: PLATE, inputs: i, printer, analyze: 'full' }) as any;
  assert.equal(r.checks.ok, true);
  assert.equal(r.checks.score, 100);
  const [w, h] = r.checks.stats.size;
  assert.ok(w <= 240 && h <= 240, `plate ${w} x ${h}`);
  assert.ok(w > 180, 'six cats at 48 mm are wider than an A1 mini bed');
  // one part per colour, whatever the number of stickers
  assert.deepEqual(r.parts.map((p: any) => p.name), ['base', 'figure', 'name']);
  const tmf = engine.export({ source: PLATE, inputs: i, printer, format: '3mf', title: 'Прогулка' }) as any;
  engine.release();
  const files = unzipSync(fromBase64(tmf.data));
  const cfg = strFromU8(files['Metadata/model_settings.config']);
  assert.deepEqual([...cfg.matchAll(/key="extruder" value="(\d)"/g)].map((m) => m[1]).slice(1), ['1', '2', '3']);
});

test('a collection too big for the bed fails before any meshing', () => {
  const keys = Array.from({ length: 20 }, (_, n) => `k${n}`);
  const i = { ...inputs(keys), values: { ...inputs(keys).values, keys: keys.join(',') } };
  const t = performance.now();
  assert.throws(() => engine.build({ source: PLATE, inputs: i, params: { size: 70 }, analyze: 'none' }), /does not fit one bed/);
  assert.ok(performance.now() - t < 4000, 'the footprints alone tell');  // ~1.4 s alone, up to ~1.8 s with the whole suite in parallel
  // the same finds on an A1 mini bed with a smaller size
  const mini = { ...DEFAULT_PRINTER, bed: [180, 180, 180] as [number, number, number] };
  const two = { ...inputs(['a', 'b']), values: { ...inputs(['a', 'b']).values, keys: 'a,b' } };
  const r = engine.build({ source: PLATE, inputs: two, printer: mini, params: { size: 40 }, analyze: 'fast' }) as any;
  engine.release();
  assert.ok(r.checks.stats.size[0] <= 164 && r.checks.stats.size[1] <= 164);
});

test('names keep only letters the stroke font has', () => {
  withArena(() => {
    const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER, inputs: inputs(['subject'], null) });
    const collect = makeCollect(lib);
    assert.equal(collect.printable('  кот «Барсик» 🐱 '), 'КОТ БАРСИК');
    assert.equal(collect.printable('Қазақ ёж and a very long tail'), 'ҚАЗАҚ ЁЖ AND A V');
    // no name: no tab, no name part
    assert.deepEqual(collect.sticker('subject', { size: 30 }).map((p: any) => p.name), ['base', 'figure']);
    assert.throws(() => collect.sticker('missing'), /no relief for "missing"/);
  });
});

test('the relief opening removes what a nozzle cannot draw and keeps the rest', () => {
  const w = 21, h = 21;
  const d = new Float32Array(w * h);
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) d[j * w + i] = Math.hypot(i - 10, j - 10) <= 6 ? 0.5 : 0; // a wide plateau
  d[10 * w + 10] = 1; // a one-cell spike on it (0.25 mm)
  for (let j = 0; j < h; j++) d[j * w + 3] = 0.8; // a one-cell ridge across
  const o = openRelief(d, w, h, 0.25, 0.25, 0.6);
  assert.equal(o[10 * w + 10], 0.5);
  assert.equal(o[10 * w + 3], 0);
  assert.equal(o[10 * w + 14], 0.5);
});
