import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Engine, loadKernel, functionEvaluator, RULES } from '../src/index.ts';

const engine = new Engine(await loadKernel(), functionEvaluator());
const program = (build: string, meta = '{}') => `return { meta: ${meta}, params: {}, build: (p, lib) => ${build} };`;
const codes = (r: any) => r.checks.issues.map((i: any) => i.code);

test('a hollow shade on a thin ring is a wide base, not a tip-over risk', () => {
  // Ø120 x 150 mm with 1.6 mm walls: the first layer is only ~600 mm² but 120 mm across
  const tube = program('lib.M.cylinder(150, 60, 60, 192).subtract(lib.M.cylinder(152, 58.4, 58.4, 192).translate([0, 0, -1]))');
  const r = engine.build({ source: tube, analyze: 'fast' });
  assert.ok(r.checks.stats.firstLayerArea < 700, String(r.checks.stats.firstLayerArea));
  assert.ok(!codes(r).includes('tip_over'), codes(r).join(','));
});

test('a tall narrow rod may tip over', () => {
  const r = engine.build({ source: program('lib.std.box([10, 10, 80])'), analyze: 'fast' });
  assert.ok(codes(r).includes('tip_over'), codes(r).join(','));
  // a thin plate standing on its edge tips across its thickness, whatever its area
  const plate = engine.build({ source: program('lib.std.box([100, 5, 60])'), analyze: 'fast' });
  assert.ok(codes(plate).includes('tip_over'), codes(plate).join(','));
});

test('a keepPosition body lifted off z = 0 is checked from its own base', () => {
  const r = engine.build({ source: program('lib.std.box([30, 30, 20]).translate([0, 0, 5])', '{ keepPosition: true }'), analyze: 'full' });
  assert.ok(Math.abs(r.checks.stats.bbox.min[2] - 5) < 1e-6);
  assert.ok(Math.abs(r.checks.stats.firstLayerArea - 900) < 1, String(r.checks.stats.firstLayerArea));
  assert.deepEqual(codes(r), []);
  // its bottom rests on the bed: no overhang heat there either
  const fast = engine.build({ source: program('lib.std.box([30, 30, 20]).translate([0, 0, 5])', '{ keepPosition: true }'), analyze: 'fast' });
  assert.ok(!codes(fast).includes('overhang') && !codes(fast).includes('small_contact'), codes(fast).join(','));
});

test('layers are print layers; the mini-slicer reports how densely it sampled', () => {
  const tall = engine.build({ source: program('lib.std.box([40, 40, 150])'), analyze: 'full' });
  assert.equal(tall.checks.stats.layers, 750);
  assert.equal(tall.checks.stats.slicesChecked, 320);
  assert.ok(Math.abs(tall.checks.stats.sliceStep - 150 / 320) < 1e-9);
  const low = engine.build({ source: program('lib.std.box([40, 40, 22])'), analyze: 'full' });
  assert.equal(low.checks.stats.layers, 110);
  assert.equal(low.checks.stats.slicesChecked, 110);
  assert.equal(low.checks.stats.sliceStep, 0.2);
  // fast checks know the layer count too, but sample nothing
  const fast = engine.build({ source: program('lib.std.box([40, 40, 22])'), analyze: 'fast' });
  assert.equal(fast.checks.stats.layers, 110);
  assert.equal(fast.checks.stats.slicesChecked, undefined);
});

test('the rulebook marks every code no check emits', () => {
  const src = readFileSync(new URL('../src/checks.ts', import.meta.url), 'utf8');
  for (const [code, rule] of Object.entries(RULES)) {
    assert.equal(src.includes(`'${code}'`), !rule.notImplemented, `${code}: notImplemented=${!!rule.notImplemented}`);
  }
  assert.deepEqual(Object.keys(RULES).filter((c) => RULES[c].notImplemented).sort(),
    ['elephant_foot', 'fit_clearance', 'horizontal_hole', 'load_across_layers', 'small_text']);
});

test('a speck where a relief grazes the slice plane is no floating island; a real island that starts as a speck is', () => {
  // cat2 at puff 3.5 (snap sticker): one slice holds a 0.0005 mm² speck that used to score it 94
  const cat = JSON.parse(readFileSync(new URL('./data/cat2_relief.json', import.meta.url), 'utf8'));
  const inputs = { outlines: { subject: cat.loops_px }, heightmaps: { subject: cat.heightmap }, values: { name: cat.name } as Record<string, string | number> };
  [inputs.values.subject_x0, inputs.values.subject_y0, inputs.values.subject_x1, inputs.values.subject_y1] = cat.crop_px;
  const sticker = `return { meta: { pack: 'collect' }, params: { puff: { value: 3.5, min: 1.5, max: 9 } }, build: (p, lib) => lib.collect.sticker('subject', { puff: p.puff, name: lib.inputs.values.name }) };`;
  const r = engine.build({ source: sticker, inputs, analyze: 'full' });
  engine.release();
  assert.ok(!codes(r).includes('floating_island'), JSON.stringify(r.checks.issues.map((i: any) => i.message)));
  assert.equal(r.checks.score, 100);
  // a 0.2 mm crumb floating next to a pillar (one slice, 0.04 mm²) is dropped like the slicer drops it...
  const crumb = program('lib.M.union([lib.std.box([20, 20, 2]), lib.std.box([4, 4, 12]), lib.M.cube([0.2, 0.2, 0.2]).translate([6, 6, 6.1])])');
  assert.ok(!codes(engine.build({ source: crumb, analyze: 'full' })).includes('floating_island'));
  // ...a 2 mm cube there is an island...
  const cube = program('lib.M.union([lib.std.box([20, 20, 2]), lib.std.box([4, 4, 12]), lib.M.cube([2, 2, 2]).translate([6, 6, 6.1])])');
  assert.ok(codes(engine.build({ source: cube, analyze: 'full' })).includes('floating_island'));
  // ...and so is a cone hanging point-down in mid-air, whose first slices are specks
  const cone = program('lib.M.union([lib.std.box([20, 20, 2]), lib.std.box([4, 4, 14]), lib.M.cylinder(5, 0, 4, 48).translate([10, 10, 6.03])])');
  const c = engine.build({ source: cone, analyze: 'full' });
  const island = c.checks.issues.find((i: any) => i.code === 'floating_island');
  assert.ok(island && island.z[0] < 6.03 + 1, JSON.stringify(c.checks.issues.map((i: any) => i.message)));
});
