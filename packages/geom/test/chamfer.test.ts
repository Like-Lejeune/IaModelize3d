// std.extrude chamfers must be true 45° faces, not horizontal steps: the fast printability
// check should see no overhang on a chamfered bottom, and a chamfered top should not add any
// floor contact of its own. (A stepped chamfer reported ~hundreds of mm² of false overhang.)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Engine, loadKernel, functionEvaluator } from '../src/index.ts';

const engine = new Engine(await loadKernel(), functionEvaluator());
const overhang = (source: string) =>
  engine.build({ source, analyze: 'fast' }).checks.issues.filter((i: any) => i.code === 'overhang');

// A few outlines: a rounded rect (convex), a hollow ring (two loops), and a concave L.
const OUTLINES: Record<string, string> = {
  rect: `lib.std.rect(30, 20, { r: 3 })`,
  ring: `lib.std.circle(40).subtract(lib.std.circle(30))`,
  ell: `lib.std.poly([[0, 0], [30, 0], [30, 30], [20, 30], [20, 10], [0, 10]])`,
};

for (const [name, cs] of Object.entries(OUTLINES)) {
  test(`chamfered bottom has no overhang (${name})`, () => {
    const chamfered = overhang(`return { params: {}, build: (p, lib) => lib.std.extrude(${cs}, 10, { chamferBottom: 1 }) }`);
    assert.deepEqual(
      chamfered.map((i: any) => i.value),
      [],
      `chamferBottom should leave zero overhang, got ${JSON.stringify(chamfered)}`,
    );
    // Top chamfer faces point up, so they are never overhangs either.
    const both = overhang(`return { params: {}, build: (p, lib) => lib.std.extrude(${cs}, 10, { chamferBottom: 0.8, chamferTop: 0.8 }) }`);
    assert.deepEqual(both.map((i: any) => i.value), []);
  });
}

test('chamferBottom keeps the solid closed and resting on the bed', () => {
  const r = engine.build({
    source: `return { params: {}, build: (p, lib) => lib.std.extrude(lib.std.rect(30, 20, { r: 3 }), 10, { chamferBottom: 1 }) }`,
    analyze: 'fast',
  });
  assert.equal(r.checks.issues.filter((i: any) => i.code === 'invalid_mesh').length, 0);
  assert.ok(Math.abs(r.checks.stats.size[2] - 10) < 1e-3, JSON.stringify(r.checks.stats.size));
  // Bottom is inset by the chamfer, so the first-layer area is below the full footprint but positive.
  assert.ok(r.checks.stats.firstLayerArea > 0);
});
