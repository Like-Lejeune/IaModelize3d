import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Engine, loadKernel, functionEvaluator, makeLib, DEFAULT_PRINTER, withArena } from '../src/index.ts';
import type { BoardSpec } from '../src/lib/elec.ts';
import { BOARD_CASE as CASE } from './fixtures.ts';

// a macro pad: a XIAO above a row of four MX switches (packages/pcb: device 'button' nodes with switch: 'mx')
const engine = new Engine(await loadKernel(), functionEvaluator());
const pad = JSON.parse(readFileSync(new URL('./data/macropad.board.json', import.meta.url), 'utf8')) as BoardSpec;
const inputs = { boards: { board: pad } };
const check = (spec: BoardSpec = pad) => engine.inspect({ source: CASE, inputs: { boards: { board: spec } }, params: {}, ops: [{ op: 'enclosure' }] }).results[0] as any;

test('key switches get a plate at their clip height and pass the check', () => {
  const r = check();
  const keys = r.findings.filter((f: any) => f.code === 'key_plate');
  assert.equal(keys.length, 4);
  assert.deepEqual(keys.map((f: any) => f.severity), ['info', 'info', 'info', 'info']);
  assert.deepEqual(r.findings.filter((f: any) => f.severity === 'error'), []);
});

test('the plate is where the switch clips, its cut-out open, and the cap clears it at the end of the travel', () => {
  withArena(() => {
    const wasm = engine.wasm;
    const lib = makeLib(wasm, { printer: DEFAULT_PRINTER, inputs });
    const enc = lib.elec.enclosure(lib.elec.board(pad), {});
    const c = pad.components.find((x) => x.id === 'SW2')!, k = c.key!;
    const zPlate = enc.zBoard + pad.pcb.thickness + k.plate_top;
    const [x, y] = [c.x!, c.y!];
    const f = enc.report.features.find((f: any) => f.type === 'key_plate' && f.for === 'SW2') as any;
    assert.equal(f.plate_z.toFixed(2), zPlate.toFixed(2));
    // straight up through the cut-out: nothing in the lid; 1 mm beyond its edge: the plate, plate_t thick, its top at zPlate
    const up = (px: number, py: number) => enc.lid.rayCast([px, py, zPlate - 8], [px, py, zPlate + 30]);
    assert.equal(up(x, y).length, 0);
    const hit = up(x + k.cut / 2 + 1, y);
    assert.ok(hit.length >= 2);
    assert.ok(Math.abs(hit[0].position[2] - (zPlate - k.plate_t)) < 0.01);
    assert.ok(Math.abs(hit[hit.length - 1].position[2] - zPlate) < 0.01);
    // a cap as printed and as placed: its skirt stays over the plate with the switch at the bottom of its travel
    const cap = enc.keycaps.find((q: any) => q.id === 'SW2')!;
    const skirtEdge = cap.placed.boundingBox().min[2];
    const ring = cap.placed.intersect(wasm.Manifold.cube([40, 40, 40], true).translate([x, y, skirtEdge + 20])).subtract(wasm.Manifold.cylinder(40, 3, 3, 24).translate([x, y, skirtEdge - 5]));
    assert.ok(ring.boundingBox().min[2] - k.travel > zPlate);
    assert.ok(cap.print.boundingBox().min[2] > -0.001);
  });
});

test('parts under a plate and a module over a key are errors', () => {
  const crowded = structuredClone(pad);
  const sw = crowded.components.find((x) => x.id === 'SW2')!;
  crowded.components.push({ id: 'J9', type: 'part', side: 'top', access: 'none', x: sw.x! + 8, y: sw.y!, w: 2, d: 2, h: 6, normal: [0, 0, 1] } as any);
  const f = check(crowded).findings.find((f: any) => f.code === 'key_plate' && f.part === 'SW2');
  assert.equal(f.severity, 'error');
  assert.match(f.msg, /J9/);
});

test('the print layout has the caps on the bed', () => {
  const out = engine.build({ source: CASE, inputs, params: {} }) as any;
  const caps = out.parts.find((p: any) => p.name === 'keycaps');
  assert.ok(caps);
  assert.ok(Math.abs(caps.bbox.min[2]) < 0.01);
});

test('a panel switch and a knob get a round hole in the lid; the knob is printed and fits its shaft', () => {
  const spec = structuredClone(pad);
  const [a, b] = spec.components.filter((c) => c.access === 'key');
  Object.assign(a, { key: { stem: 'panel', cut: 12.2, depth: 26, cap: [22, 22] }, h: 26, w: 12.2, d: 12.2 });
  Object.assign(b, { key: { stem: 'shaft', cut: 7, shaft_d: 6, shaft_top: 20, cap: [22, 22] }, h: 8 });
  spec.components = spec.components.filter((c) => c.access !== 'key' || c === a || c === b);
  const r = check(spec);
  assert.deepEqual(r.findings.filter((f: any) => f.severity === 'error'), []);
  withArena(() => {
    const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER, inputs: { boards: { board: spec } } });
    const enc = lib.elec.enclosure(lib.elec.board(spec), {});
    // the case takes the switch's depth; the two holes are open straight through the lid
    assert.ok(enc.zTop > enc.zBoard + spec.pcb.thickness + 26);
    for (const c of [a, b]) assert.equal(enc.lid.rayCast([c.x!, c.y!, enc.zTop - 1], [c.x!, c.y!, enc.zTop + enc.lidT + 1]).length, 0);
    assert.deepEqual(enc.keycaps.map((k: any) => k.id), [b.id]);
    const knob = enc.keycaps[0];
    assert.ok(knob.placed.boundingBox().min[2] > enc.zTop + enc.lidT);
    assert.ok(knob.print.boundingBox().min[2] > -0.001);
  });
});
