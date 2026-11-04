import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Engine, loadKernel, functionEvaluator, makeLib, DEFAULT_PRINTER, withArena } from '../src/index.ts';
import type { BoardSpec } from '../src/lib/elec.ts';
import { BOARD_CASE } from './fixtures.ts';

// Cases that follow a shaped PCB (a round or rounded outline: the walls hug it, mounts and hooks stay inside, the snap lid
// fits) and that stand as they are used (stance tilt and upright bring a printed stand, wall brings ears).
const engine = new Engine(await loadKernel(), functionEvaluator());
const json = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const timer = json('./data/kitchen_timer.board.json') as BoardSpec;
const leak = json('./data/leak_sensor.board.json') as BoardSpec;
const CASE = BOARD_CASE.replace("layout: { value: 'print'", `form: { value: 'soft', options: ['box', 'soft', 'round'], source: 'design' },
  mounting: { value: 'none', options: ['none', 'ears', 'strap', 'lanyard', 'stake', 'magnets', 'contacts'], source: 'design' },
  stance: { value: 'auto', options: ['auto', 'desk', 'tilt', 'upright', 'wall', 'hand'], source: 'design' },
  mount_edge: { value: 'auto', options: ['auto', '+x', '-x', '+y', '-y'], source: 'design' },
  layout: { value: 'print'`).replace('buttons: p.buttons });', 'buttons: p.buttons, form: p.form, mounting: p.mounting, stance: p.stance, mountEdge: p.mount_edge });');

// The timer's parts on another outline: moved by dx, dy, the module's USB still at its edge, the mount holes where the
// shape leaves room for them, a board's w x h as the outline's box.
function reshaped(spec: BoardSpec, points: [number, number][], W: number, H: number, dx: number, dy: number, holes: [number, number][]): BoardSpec {
  const s = structuredClone(spec);
  const o = s.pcb.outline as { w: number; h: number };
  for (const c of s.components) {
    if (c.access === 'port' && c.edge) {
      c.at = c.at! + (c.edge[1] === 'y' ? dx : dy);
      const left = c.edge === '+y' ? H - o.h - dy : c.edge === '-y' ? dy : c.edge === '+x' ? W - o.w - dx : dx;
      c.protrude = (c.protrude ?? 0) - left;
    } else if (c.x !== undefined) {
      c.x += dx;
      c.y! += dy;
    }
  }
  for (const a of s.accessories ?? []) {
    if (a.x !== undefined) a.x += dx;
    if (a.y !== undefined) a.y += dy;
  }
  const mounts = s.pcb.holes.filter((h) => (h.use ?? 'mount') === 'mount');
  mounts.forEach((h, i) => { [h.x, h.y] = holes[i]; });
  for (const h of s.pcb.holes.filter((h) => (h.use ?? 'mount') !== 'mount')) {
    h.x += dx;
    h.y += dy;
  }
  s.pcb.outline = { kind: 'poly', points, w: W, h: H };
  return s;
}
const circle = (D: number, n = 96): [number, number][] =>
  Array.from({ length: n }, (_, i) => [+(D / 2 + (D / 2) * Math.cos((2 * Math.PI * i) / n)).toFixed(3), +(D / 2 + (D / 2) * Math.sin((2 * Math.PI * i) / n)).toFixed(3)]);
function roundedRect(W: number, H: number, r: number): [number, number][] {
  const pts: [number, number][] = [];
  for (const [cx, cy, a0] of [[W - r, r, -90], [W - r, H - r, 0], [r, H - r, 90], [r, r, 180]] as [number, number, number][])
    for (let i = 0; i <= 8; i++) { const a = ((a0 + (90 * i) / 8) * Math.PI) / 180; pts.push([+(cx + r * Math.cos(a)).toFixed(3), +(cy + r * Math.sin(a)).toFixed(3)]); }
  return pts;
}
// a 90 mm disc: the module's USB at the top of the circle
const disc = reshaped(timer, circle(90), 90, 90, 10.5, 20, [[18.1, 71.9], [71.9, 71.9], [18.1, 18.1], [71.9, 18.1]]);
const rounded = reshaped(timer, roundedRect(69, 69, 10), 69, 69, 0, 0, [[6, 63], [63, 63], [6, 6], [63, 6]]);

const plan = (spec: BoardSpec, opts: Record<string, unknown>) =>
  withArena(() => {
    const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER, inputs: { boards: { board: spec } } });
    const enc = lib.elec.enclosure(lib.elec.board(spec), opts);
    const out = (f: string) => enc.report.features.filter((x: any) => x.type === f);
    return { form: out('form')[0], mounting: out('mounting')[0], stand: out('stand')[0], mounts: out('mount'), hooks: enc.hooks.length, inner: { ...enc.inner },
      pose: enc.report.pose, size: enc.report.outerSize, pieces: enc.base.decompose().length, hasStand: !!enc.stand };
  });
const findings = (spec: BoardSpec, params: Record<string, unknown>) =>
  (engine.inspect({ source: CASE, inputs: { boards: { board: spec } }, params: { ...params, layout: 'assembled' }, ops: [{ op: 'enclosure' }] }).results[0] as any).findings;
const notInfo = (r: any[]) => r.filter((f) => f.severity !== 'info').map((f) => `${f.code}: ${f.msg}`);
const printed = (spec: BoardSpec, params: Record<string, string | number | boolean>) => engine.build({ source: CASE, inputs: { boards: { board: spec } }, params, analyze: 'full' });
const printErrors = (r: any) => (r.checks?.issues ?? []).filter((i: any) => i.severity === 'error').map((i: any) => `${i.code}: ${i.message ?? i.msg}`);

test('a round PCB gets a round puck: walls in a circle, snap hooks round them, the check and the printability clean', () => {
  const r = plan(disc, { form: 'round' });
  const w = r.inner.x1 - r.inner.x0, h = r.inner.y1 - r.inner.y0;
  assert.ok(Math.abs(w - h) < 0.01, `not a circle: ${w} x ${h}`);
  assert.ok(r.form.cornerR - 2 > w / 2 - 0.1, JSON.stringify(r.form)); // the corner radius is half the width
  assert.ok(w - 90 < 6, `walls hug the disc: ${w}`);
  assert.equal(r.hooks, 4);
  assert.equal(r.pieces, 1);
  assert.deepEqual(notInfo(findings(disc, { form: 'round' })), []);
  const built = printed(disc, { form: 'round' });
  assert.deepEqual(printErrors(built), []);
  assert.deepEqual(built.parts.map((p: any) => p.name), ['base', 'lid']);
});

test('a soft case follows a round PCB as far as a round one does', () => {
  const soft = plan(disc, { form: 'soft' }), round = plan(disc, { form: 'round' });
  assert.ok(Math.abs(soft.form.cornerR - round.form.cornerR) < 0.5, `${soft.form.cornerR} vs ${round.form.cornerR}`);
  assert.deepEqual(notInfo(findings(disc, { form: 'soft' })), []);
});

test('the hold-down posts of a round board keep off the curved wall, its port window stays open', () => {
  for (const m of plan(disc, { form: 'round' }).mounts) assert.ok(m.postD >= 1.8, JSON.stringify(m));
  const port = findings(disc, { form: 'round' }).find((f: any) => f.code === 'port_clear');
  assert.ok(port && port.value >= 0.25, JSON.stringify(port));
});

test('a rounded-rectangle PCB rounds the case corners past a square one, and a rounded rect outline works alike', () => {
  const plain = plan(timer, { form: 'soft' }), r = plan(rounded, { form: 'soft' });
  assert.ok(r.form.cornerR > plain.form.cornerR, `${r.form.cornerR} vs ${plain.form.cornerR}`);
  assert.equal(r.hooks, plain.hooks);
  assert.deepEqual(notInfo(findings(rounded, { form: 'soft' })), []);
  assert.deepEqual(printErrors(printed(rounded, { form: 'soft' })), []);
  // the same shape as kind rect with r: the corner comes in as far
  const asRect = structuredClone(rounded);
  asRect.pcb.outline = { kind: 'rect', w: 69, h: 69, r: 10 };
  assert.ok(Math.abs(plan(asRect, { form: 'soft' }).form.cornerR - r.form.cornerR) < 0.5);
});

for (const mounting of ['ears', 'strap', 'lanyard', 'stake', 'magnets', 'contacts'])
  test(`a round puck takes ${mounting}: built on the curved wall in one piece, the check clean`, () => {
    const r = plan(disc, { form: 'round', mounting });
    assert.ok(!r.mounting.blocked, JSON.stringify(r.mounting));
    assert.equal(r.pieces, 1);
    assert.deepEqual(notInfo(findings(disc, { form: 'round', mounting })), []);
  });

test('magnet pockets stay inside a round floor', () => {
  const r = plan(disc, { form: 'round', mounting: 'magnets' });
  const R = (r.inner.x1 - r.inner.x0) / 2;
  for (const [x, y] of r.mounting.at) assert.ok(Math.hypot(x - 45, y - 45) + 5.15 + 1 <= R, JSON.stringify(r.mounting));
});

for (const [stance, angle] of [['tilt', 25], ['upright', 75]] as [string, number][])
  test(`stance ${stance}: a printed stand the case leans in at ${angle} deg, on the wall free of ports; the display reads upright`, () => {
    const r = plan(timer, { form: 'soft', stance });
    assert.equal(r.hasStand, true);
    assert.deepEqual(r.pose, { stance, edge: '-y', angle });
    assert.deepEqual(notInfo(findings(timer, { stance })), []);
    const built = printed(timer, { stance });
    assert.deepEqual(printErrors(built), []);
    const stand = built.parts.find((p: any) => p.name === 'stand');
    assert.ok(stand && stand.volume > 1000, JSON.stringify(built.parts.map((p: any) => p.name)));
    assert.equal(+stand.bbox.min[2].toFixed(3), 0); // on the bed
    // assembled: the stand's slope and ledge touch neither the base nor the lid
    const fit = findings(timer, { stance }).find((f: any) => f.code === 'lid_fit');
    assert.ok(fit.value <= 0.05, JSON.stringify(fit));
  });

test('a stand on a round puck and on a board with its ports on one wall', () => {
  assert.deepEqual(notInfo(findings(disc, { form: 'round', stance: 'tilt' })), []);
  assert.deepEqual(printErrors(printed(disc, { form: 'round', stance: 'tilt' })), []);
  const r = plan(leak, { stance: 'upright' }); // USB on +y and the probe on -y: it stands on a side
  assert.ok(r.pose!.edge === '-x' || r.pose!.edge === '+x', JSON.stringify(r.pose));
});

test('stance wall gets ears when no mounting is named; desk and hand build nothing; a stake stands alone', () => {
  const wall = plan(timer, { stance: 'wall' });
  assert.equal(wall.mounting.kind, 'ears');
  assert.equal(wall.mounting.fromStance, true);
  assert.equal(wall.pose!.stance, 'wall');
  assert.deepEqual(notInfo(findings(timer, { stance: 'wall' })), []);
  for (const stance of ['desk', 'hand']) {
    const r = plan(timer, { stance });
    assert.equal(r.hasStand, false);
    assert.equal(r.mounting.kind, 'none');
  }
  const stake = plan(timer, { mounting: 'stake' });
  assert.equal(stake.hasStand, false);
  assert.equal(stake.pose!.stance, 'upright');
  assert.deepEqual(notInfo(findings(timer, { mounting: 'stake' })), []);
});

test('what cannot be built is said: a stand with ears, and a stand with every wall taken', () => {
  const ears = notInfo(findings(timer, { stance: 'tilt', mounting: 'ears' }));
  assert.equal(ears.length, 1);
  assert.match(ears[0], /^mounting: stand: ears and a stand exclude each other/);
  const shut = structuredClone(timer);
  for (const edge of ['-y', '-x', '+x'] as const)
    shut.components.push({ id: `J${edge}`, type: 'usb_c', side: 'top', access: 'port', edge, at: 34.5, w: 8.94, d: 7.3, h: 3.2 } as any);
  const warned = notInfo(findings(shut, { stance: 'upright' })).filter((m) => m.startsWith('mounting:'));
  assert.deepEqual(warned, ['mounting: stand: every wall has a port window or a cable exit: nothing to stand on']);
});
