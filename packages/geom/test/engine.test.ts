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
