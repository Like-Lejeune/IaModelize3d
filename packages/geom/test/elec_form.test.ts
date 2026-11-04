import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Engine, loadKernel, functionEvaluator, makeLib, DEFAULT_PRINTER, withArena } from '../src/index.ts';
import type { BoardSpec } from '../src/lib/elec.ts';
import { BOARD_CASE } from './fixtures.ts';

// The plan shapes of lib.elec cases: 'soft' and 'round' round the corners as far as the board and its parts allow, keep
// the port windows and snap hooks on straight walls, and pass the same enclosure check as the box.
const engine = new Engine(await loadKernel(), functionEvaluator());
const json = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const dataset = json('../src/boards.json') as { boards: BoardSpec[] };
const carrier = json('./data/xiao_carrier.board.json') as BoardSpec;
const board = (id: string): BoardSpec => structuredClone(dataset.boards.find((b) => b.id === id)!);
const CASE = BOARD_CASE.replace("layout: { value: 'print'", "form: { value: 'box', options: ['box', 'soft', 'round'], source: 'design' },\n  layout: { value: 'print'")
  .replace('buttons: p.buttons });', 'buttons: p.buttons, form: p.form });');
const plan = (spec: BoardSpec, opts: Record<string, unknown>) =>
  withArena(() => {
    const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER, inputs: { boards: { board: spec } } });
    const enc = lib.elec.enclosure(lib.elec.board(spec), opts);
    return { form: enc.report.features.find((f: any) => f.type === 'form'), hooks: enc.hooks.length, inner: { ...enc.report.inner } };
  });
const check = (spec: BoardSpec, form: string) =>
  engine.inspect({ source: CASE, inputs: { boards: { board: spec } }, params: { form, layout: 'assembled' }, ops: [{ op: 'enclosure' }] }).results[0] as any;
const notInfo = (r: any) => r.findings.filter((f: any) => f.severity !== 'info').map((f: any) => `${f.code}: ${f.msg}`);

test('the program wires the form param through, and the case program the PCB pack writes passes it', () => {
  assert.match(CASE, /form: p\.form/);
});

for (const [name, spec] of [['pcb-xiao-carrier', carrier], ['rpi-pico-w', board('rpi-pico-w')], ['arduino-nano', board('arduino-nano')]] as [string, BoardSpec][]) {
  test(`${name}: soft rounds the corners well past the box's 2.5 mm, grows at most 0.6 mm a side, and passes the check`, () => {
    const box = plan(spec, {}), soft = plan(spec, { form: 'soft' });
    assert.ok(soft.form.cornerR > 5, JSON.stringify(soft.form));
    for (const k of ['x0', 'y0'] as const) assert.ok(box.inner[k] - soft.inner[k] <= 0.6 + 1e-6);
    for (const k of ['x1', 'y1'] as const) assert.ok(soft.inner[k] - box.inner[k] <= 0.6 + 1e-6);
    assert.equal(soft.hooks, box.hooks);
    assert.deepEqual(notInfo(check(spec, 'soft')), []);
  });
  test(`${name}: round makes a pebble with every snap hook still in place, and passes the check`, () => {
    const box = plan(spec, {}), round = plan(spec, { form: 'round' }), soft = plan(spec, { form: 'soft' });
    assert.ok(round.form.cornerR >= soft.form.cornerR, JSON.stringify(round.form));
    assert.equal(round.hooks, box.hooks);
    assert.deepEqual(notInfo(check(spec, 'round')), []);
  });
}

test('a board held by its edges (no mount holes) keeps its walls where they are: rounder only as far as that allows', () => {
  const spec = board('xiao-esp32c3');
  const box = plan(spec, {}), soft = plan(spec, { form: 'soft' });
  assert.deepEqual(soft.inner, box.inner);
  assert.ok(soft.form.cornerR > 2.5);
  assert.deepEqual(notInfo(check(spec, 'soft')), []);
});

test('a polygon PCB outline with round corners lets the case corners follow it', () => {
  const spec = board('rpi-pico-w');
  const W = spec.pcb.outline.w, H = spec.pcb.outline.h, r = 6;
  const pts: [number, number][] = [];
  for (const [cx, cy, a0] of [[W - r, r, -90], [W - r, H - r, 0], [r, H - r, 90], [r, r, 180]] as [number, number, number][])
    for (let i = 0; i <= 8; i++) { const a = ((a0 + (90 * i) / 8) * Math.PI) / 180; pts.push([+(cx + r * Math.cos(a)).toFixed(3), +(cy + r * Math.sin(a)).toFixed(3)]); }
  const shaped = { ...spec, pcb: { ...spec.pcb, outline: { kind: 'poly' as const, points: pts, w: W, h: H } } };
  assert.ok(plan(shaped, { form: 'soft' }).form.cornerR > plan(spec, { form: 'soft' }).form.cornerR);
});
