import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Engine, loadKernel, functionEvaluator } from '../src/index.ts';
import { BAG_HOOK, VASE, BAD_SHELF } from './fixtures.ts';

const engine = new Engine(await loadKernel(), functionEvaluator());

test('bag hook builds and passes full checks', () => {
  const r = engine.build({ source: BAG_HOOK, analyze: 'full', mesh: true });
  assert.equal(r.ok, true);
  assert.ok(r.checks.stats.volume > 1000);
  const errors = r.checks.issues.filter((i: any) => i.severity === 'error');
  assert.deepEqual(errors, []);
  assert.equal(r.handles.length, 1);
});

test('params are clamped to their range', () => {
  const r = engine.build({ source: BAG_HOOK, params: { shelf_t: 999 }, analyze: 'none' });
  assert.equal(r.params.shelf_t, 40);
});

test('vase surface is a closed solid', () => {
  const r = engine.build({ source: VASE, analyze: 'fast' });
  assert.equal(r.checks.issues.filter((i: any) => i.code === 'invalid_mesh').length, 0);
  assert.ok(r.checks.stats.size[2] > 119);
});

test('bad shelf reports islands and thin features with heights', () => {
  const r = engine.build({ source: BAD_SHELF, analyze: 'full' });
  const codes = r.checks.issues.map((i: any) => i.code);
  assert.ok(codes.includes('floating_island'), codes.join(','));
  assert.ok(codes.includes('too_thin'), codes.join(','));
  const island = r.checks.issues.find((i: any) => i.code === 'floating_island');
  assert.ok(island.z[0] >= 19 && island.z[0] <= 21, JSON.stringify(island.z));
});

test('compile errors are reported with a stage', () => {
  assert.throws(() => engine.build({ source: 'return { build: 1 }' }), /build/);
});

test('render sheet and 3mf export produce bytes', () => {
  const png = engine.render({ source: BAG_HOOK, view: 'sheet', tile: 200 });
  assert.ok(png.png.length > 1000);
  const tmf = engine.export({ source: BAG_HOOK, format: '3mf', title: 'hook' });
  assert.ok(tmf.data.length > 1000);
});

test('extrude keeps its cross-section (scalar scaleTop binding bug)', async () => {
  const { makeLib, DEFAULT_PRINTER } = await import('../src/index.ts');
  const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER });
  const box = lib.CS.square([10, 10], true).extrude(40, 0, 0, 1);
  assert.ok(Math.abs(box.volume() - 4000) < 1, String(box.volume()));
  assert.ok(Math.abs(lib.std.box([10, 10, 40]).volume() - 4000) < 1);
});

test('constraint sketch solves a dimensioned bracket with a tangent', async () => {
  const { makeLib, DEFAULT_PRINTER } = await import('../src/index.ts');
  const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER });
  const s = lib.std.sketch();
  // rough guesses on purpose; relations fix the exact shape
  const a = s.point(0, 0, { fixed: true }), b = s.point(37, 3), c = s.point(41, 22), d = s.point(2, 18);
  const ab = s.line(a, b), bc = s.line(b, c), cd = s.line(c, d), da = s.line(d, a);
  s.horizontal(ab); s.vertical(bc); s.horizontal(cd); s.vertical(da);
  s.length(ab, 40); s.length(bc, 20);
  const hole = s.circle(s.point(30, 8), 3);
  s.radius(hole, 4); s.tangent(bc, hole); s.dy(a, hole.c, 10);
  const r = s.solve();
  assert.equal(r.ok, true, JSON.stringify(r));
  const [cx, cy] = s.at(c);
  assert.ok(Math.abs(cx - 40) < 1e-6 && Math.abs(cy - 20) < 1e-6, `${cx},${cy}`);
  const [hx, hy] = s.at(hole.c);
  assert.ok(Math.abs(hx - 36) < 1e-5 && Math.abs(hy - 10) < 1e-5, `${hx},${hy}`);
  const plate = s.polygon([a, b, c, d]).subtract(s.disc(hole));
  assert.ok(Math.abs(plate.area() - (800 - Math.PI * 16)) < 0.6);
});

test('thread crests are fine detail, not errors', () => {
  const src = `return { meta: {}, params: {}, build: (p, lib) => lib.std.thread({ d: 6, pitch: 1, length: 12 }) };`;
  const r = engine.build({ source: src, analyze: 'full' });
  const errors = r.checks.issues.filter((i: any) => i.severity === 'error').map((i: any) => i.message);
  assert.deepEqual(errors, []);
});
