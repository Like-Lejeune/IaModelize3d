import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Engine, loadKernel, functionEvaluator, evalExpr, clearMeshCache } from '../src/index.ts';
import { lastRun } from '../src/meshdoc/doc.ts';
import { meshField, refine, loopSubdivide, fromSolid } from '../src/meshdoc/trimesh.ts';

const engine = new Engine(await loadKernel(), functionEvaluator());
const doc = (ops: any[], extra: any = {}) => JSON.stringify({ engine: 'mesh', meta: { title: 't' }, ...extra, ops });
const build = (source: string, params: any = {}) => engine.build({ source, params, analyze: 'fast' });
const size = (r: any) => r.checks.stats.size as number[];
const vol = (r: any) => r.checks.stats.volume as number;

const BODY = { id: 'body', op: 'clay', shapes: [{ shape: 'ellipsoid', at: [0, 0, 20], size: [30, 24, 40] }, { shape: 'sphere', at: [0, -2, 44], d: 22 }], smooth: 6 };

test('expressions: params, arithmetic, functions, no eval', () => {
  assert.equal(evalExpr('a * 2 + max(b, 3)', { a: 4, b: 1 }), 11);
  assert.equal(evalExpr('-(2 ^ 3) / 4', {}), -2);
  assert.ok(Math.abs(evalExpr('sin(30)', {}) - 0.5) < 1e-9);
  assert.throws(() => evalExpr('a; process.exit()', { a: 1 }), /cannot read|unknown|unexpected/);
  assert.throws(() => evalExpr('nope + 1', {}), /unknown name/);
});

test('clay: blended primitives become one closed body', () => {
  const r = build(doc([BODY]));
  assert.equal(r.checks.issues.filter((i: any) => i.code === 'invalid_mesh').length, 0);
  assert.equal(r.checks.stats.bodies, 1);
  const s = size(r);
  assert.ok(Math.abs(s[0] - 30) < 2 && s[2] > 50, JSON.stringify(s));
});

test('params and expressions drive op values', () => {
  const src = doc([{ op: 'clay', shapes: [{ shape: 'box', at: [0, 0, '= h / 2'], size: [20, 20, '$h'], r: 2 }] }], {
    params: { h: { value: 30, min: 10, max: 60, unit: 'mm' } },
  });
  assert.ok(Math.abs(size(build(src))[2] - 30) < 0.8);
  assert.ok(Math.abs(size(build(src, { h: 50 }))[2] - 50) < 0.8);
});

test('sculpt with symmetry moves both sides alike; strokes on the centre act once', () => {
  const ears = { op: 'sculpt', brush: 'grab', at: [8, -2, 52], radius: 6, to: [12, -2, 62] };
  const nose = { op: 'sculpt', brush: 'grab', at: [0, -12, 44], radius: 5, dir: [0, -1, 0], strength: 3 };
  const base = build(doc([BODY]));
  const r = build(doc([BODY, ears, nose], { symmetry: 'x' }));
  const b = r.checks.stats.bbox;
  assert.ok(Math.abs(b.max[0] + b.min[0]) < 0.6, `not symmetric: ${b.min[0]} .. ${b.max[0]}`);
  assert.ok(size(r)[2] > size(base)[2] + 4, 'ears did not rise');
  // nose: pulled ~3 mm forward once, not twice by its mirror image
  const dy = base.checks.stats.bbox.min[1] - b.min[1];
  assert.ok(dy > 1.5 && dy < 4.5, `nose moved ${dy}`);
});

test('clay add with a blend fuses into the body; subtract carves', () => {
  const add = build(doc([BODY, { op: 'clay', mode: 'add', blend: 4, shapes: [{ shape: 'capsule', from: [10, 0, 20], to: [24, 0, 10], d: 8 }] }]));
  assert.equal(add.checks.stats.bodies, 1);
  assert.ok(size(add)[0] > 35);
  const base = vol(build(doc([BODY])));
  const cut = build(doc([BODY, { op: 'clay', mode: 'subtract', blend: 2, shapes: [{ shape: 'sphere', at: [0, -12, 30], d: 10 }] }]));
  assert.ok(vol(cut) < base - 100, `${vol(cut)} vs ${base}`);
});

test('remesh keeps the volume; hollow leaves a wall; base flattens the bottom', () => {
  const base = vol(build(doc([BODY])));
  const re = vol(build(doc([BODY, { op: 'remesh', detail: 0.8 }])));
  assert.ok(Math.abs(re - base) / base < 0.03, `${re} vs ${base}`);
  const hol = build(doc([BODY, { op: 'hollow', wall: 2, drain: 5 }]));
  assert.ok(vol(hol) < base * 0.6, `${vol(hol)} vs ${base}`);
  const flat = build(doc([BODY, { op: 'base', depth: 3 }]));
  assert.ok(flat.checks.stats.firstLayerArea > 150, String(flat.checks.stats.firstLayerArea));
});

test('mirror, boolean, transform fit, subdivide and displace stay closed', () => {
  const lop = { op: 'sculpt', brush: 'grab', at: [10, 0, 20], radius: 6, dir: [1, 0, 0], strength: 4 };
  const m = build(doc([BODY, lop, { op: 'mirror', axis: 'x', keep: '+' }]));
  const b = m.checks.stats.bbox;
  assert.ok(Math.abs(b.max[0] + b.min[0]) < 0.3);
  const hole = build(doc([BODY, { op: 'base', depth: 2 }, { op: 'boolean', mode: 'subtract', shape: { shape: 'cylinder', d: 8, h: 6, at: [0, 0, 0] } }]));
  assert.ok(vol(hole) < vol(build(doc([BODY, { op: 'base', depth: 2 }]))));
  const fit = build(doc([BODY, { op: 'transform', fit: { height: 80 } }]));
  assert.ok(Math.abs(size(fit)[2] - 80) < 0.5);
  const sub = build(doc([BODY, { op: 'subdivide', levels: 1 }, { op: 'displace', pattern: 'cells', scale: 6, amplitude: 0.6, region: { plane: { normal: [0, 0, 1], offset: 30 } } }]));
  assert.equal(sub.checks.issues.filter((i: any) => i.code === 'invalid_mesh').length, 0);
});

test('appending an op replays only that op', () => {
  clearMeshCache();
  const ops = [BODY, { op: 'smooth', iterations: 3 }];
  build(doc(ops));
  build(doc([...ops, { op: 'sculpt', brush: 'inflate', at: [0, -10, 25], radius: 6, strength: 1 }]));
  assert.equal(lastRun.replayed, 1, JSON.stringify(lastRun));
  // tuning the last op: again one step
  build(doc([...ops, { op: 'sculpt', brush: 'inflate', at: [0, -10, 25], radius: 6, strength: 2 }]));
  assert.equal(lastRun.replayed, 1, JSON.stringify(lastRun));
});

test('errors name the op that failed', () => {
  assert.throws(() => build(doc([{ op: 'smooth' }])), /first op must be clay/);
  assert.throws(() => build(doc([BODY, { id: 'nose', op: 'sculpt', brush: 'twist', at: [0, 0, 0], radius: 3 }])), /op 2 \(nose\).*unknown brush/);
  assert.throws(() => build(doc([BODY, { op: 'move', offset: [0, 0, '$nope'] }])), /unknown parameter/);
});

test('mesh field: winding sign, union of overlapping shells', () => {
  const M: any = engine.wasm.Manifold;
  const a = fromSolid(M.sphere(10, 48));
  const f = meshField(a, 1.5);
  assert.ok(f.at(0, 0, 0) < 0 && f.at(0, 0, 12) > 0);
  assert.ok(Math.abs(f.at(0, 0, 9) + 1) < 0.1, String(f.at(0, 0, 9)));
  // a second sphere overlapping the first: its inside is inside, not a hole
  const b = fromSolid(M.sphere(10, 48).translate([12, 0, 0]));
  const both = { pos: Float64Array.from([...a.pos, ...b.pos]), tris: Uint32Array.from([...a.tris, ...Array.from(b.tris, (t) => t + a.pos.length / 3)]) };
  assert.ok(meshField(both, 1.5).inside(6, 0, 0));
  const fine = refine(a, 0.5);
  assert.ok(fine.tris.length > a.tris.length * 3);
  assert.equal(loopSubdivide(a).tris.length, a.tris.length * 4);
});
