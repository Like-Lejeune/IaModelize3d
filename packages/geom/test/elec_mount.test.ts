import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Engine, loadKernel, functionEvaluator, makeLib, DEFAULT_PRINTER, withArena } from '../src/index.ts';
import type { BoardSpec } from '../src/lib/elec.ts';
import { BOARD_CASE } from './fixtures.ts';

// How a lib.elec case is held where it is used (mounting) and how tall it is at least (minHeight): flat features on the
// bed side of the base, on walls free of port windows, that keep the case printable without supports and pass the same
// enclosure check.
const engine = new Engine(await loadKernel(), functionEvaluator());
const json = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const dataset = json('../src/boards.json') as { boards: BoardSpec[] };
const carrier = json('./data/xiao_carrier.board.json') as BoardSpec;
const board = (id: string): BoardSpec => structuredClone(dataset.boards.find((b) => b.id === id)!);
const CASE = BOARD_CASE.replace("layout: { value: 'print'", "mounting: { value: 'none', options: ['none', 'ears', 'strap', 'lanyard', 'stake', 'magnets', 'contacts'], source: 'design' },\n  min_height: { value: 0, source: 'design' },\n  layout: { value: 'print'")
  .replace('buttons: p.buttons });', 'buttons: p.buttons, form: \'soft\', mounting: p.mounting, minHeight: p.min_height });');
const build = (spec: BoardSpec, opts: Record<string, unknown>) =>
  withArena(() => {
    const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER, inputs: { boards: { board: spec } } });
    const plain = lib.elec.enclosure(lib.elec.board(spec), { form: 'soft' });
    const enc = lib.elec.enclosure(lib.elec.board(spec), { form: 'soft', ...opts });
    const bb = enc.base.boundingBox(), pb = plain.base.boundingBox();
    return {
      note: enc.report.features.find((f: any) => f.type === 'mounting'), pose: enc.report.pose, size: enc.report.outerSize,
      grow: [pb.min[0] - bb.min[0], bb.max[0] - pb.max[0], pb.min[1] - bb.min[1], bb.max[1] - pb.max[1]],
      floorZ: bb.min[2], volume: enc.base.volume() - plain.base.volume(),
    };
  });
const check = (spec: BoardSpec, mounting: string, min_height = 0) =>
  engine.inspect({ source: CASE, inputs: { boards: { board: spec } }, params: { mounting, min_height, layout: 'assembled' }, ops: [{ op: 'enclosure' }] }).results[0] as any;
const notInfo = (r: any) => r.findings.filter((f: any) => f.severity !== 'info').map((f: any) => `${f.code}: ${f.msg}`);

for (const [name, spec] of [['pcb-xiao-carrier', carrier], ['rpi-pico-w', board('rpi-pico-w')]] as [string, BoardSpec][]) {
  test(`${name}: ears stick out of two opposite free walls, lie on the bed, and the case passes the check`, () => {
    const r = build(spec, { mounting: 'ears' });
    assert.ok(!r.note.blocked, JSON.stringify(r.note));
    assert.equal(r.note.edges.length, 2);
    assert.equal(r.floorZ, 0);
    assert.ok(Math.max(...r.grow) > 10, JSON.stringify(r.grow));
    assert.equal(r.pose.stance, 'wall');
    assert.deepEqual(notInfo(check(spec, 'ears')), []);
  });
  test(`${name}: a stake runs ~70 mm out of one free wall and the device stands on it`, () => {
    const r = build(spec, { mounting: 'stake' });
    assert.ok(!r.note.blocked, JSON.stringify(r.note));
    assert.ok(Math.max(...r.grow) > 65, JSON.stringify(r.grow));
    assert.equal(r.pose.stance, 'upright');
    assert.equal(r.pose.edge, r.note.edge);
    assert.deepEqual(notInfo(check(spec, 'stake')), []);
  });
  test(`${name}: a lanyard eyelet and strap slots both pass the check`, () => {
    for (const k of ['lanyard', 'strap']) {
      const r = build(spec, { mounting: k });
      assert.ok(!r.note.blocked, `${k}: ${JSON.stringify(r.note)}`);
      assert.ok(r.volume > 0);
      assert.deepEqual(notInfo(check(spec, k)), [], k);
    }
  });
  test(`${name}: magnet pockets thicken the floor, cut from below, and pass the check`, () => {
    const r = build(spec, { mounting: 'magnets' });
    assert.ok(!r.note.blocked, JSON.stringify(r.note));
    assert.ok(r.note.at.length >= 2);
    const thick = build(spec, { floor: 3.0 }); // the same floor without pockets has more plastic
    assert.ok(r.volume < thick.volume - 300, `${r.volume} vs ${thick.volume}`);
    assert.deepEqual(notInfo(check(spec, 'magnets')), []);
  });
}

test('minHeight raises the walls to make a cube; the parts stay where they were', () => {
  const r = build(carrier, { minHeight: 40 });
  assert.ok(Math.abs(r.size[2] - 40) < 0.01, JSON.stringify(r.size));
  assert.deepEqual(notInfo(check(carrier, 'none', 40)), []);
});
