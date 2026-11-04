// lib.elec and check_enclosure for what a device needs from its case beyond ports and buttons (fw.board/1 C2): lid
// windows over LEDs, sensors and displays, sound grilles, a display module on a header held down by the lid, cable exits
// with a zip-tie slot, a loose LiPo under or beside the board. Synthetic boards for each, and two boards from the
// 2026-11-03 device runs (kitchen timer, leak sensor) with those fields added by hand (test/data/*.board.json).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Engine, loadKernel, functionEvaluator, makeLib, DEFAULT_PRINTER, withArena, buildProgram, disposeBuild } from '../src/index.ts';
import { checkEnclosure } from '../src/enclosure.ts';
import type { BoardAccessory, BoardComponent, BoardSpec } from '../src/lib/elec.ts';
import { BOARD_CASE as CASE } from './fixtures.ts';

const engine = new Engine(await loadKernel(), functionEvaluator());
const json = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const schema = json('../src/board.schema.json');
const inputs = (spec: BoardSpec) => ({ boards: { board: spec } });
const check = (spec: BoardSpec, params: Record<string, any> = {}) =>
  engine.inspect({ source: CASE, inputs: inputs(spec), params, ops: [{ op: 'enclosure' }] }).results[0] as any;
const find = (r: any, code: string, part?: string) => r.findings.find((f: any) => f.code === code && (part === undefined || f.part === part));
const errors = (r: any) => r.findings.filter((f: any) => f.severity === 'error').map((f: any) => `${f.code} ${f.part}: ${f.msg}`);
const feature = (enc: any, type: string, id?: string) => enc.report.features.find((f: any) => f.type === type && (id === undefined || f.for === id));
function plan<T>(spec: BoardSpec, opts: Record<string, unknown>, fn: (enc: any, E: any) => T): T {
  return withArena(() => {
    const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER, inputs: inputs(spec) });
    return fn(lib.elec.enclosure(lib.elec.board(spec), opts), lib.elec);
  });
}

// a 50 x 40 carrier with M3 holes 3.5 mm in from the corners, like the PCB pipeline's
const part = (id: string, access: BoardComponent['access'], x: number, y: number, w: number, d: number, h: number, more: Partial<BoardComponent> = {}): BoardComponent =>
  ({ id, type: 'chip', side: 'top', access, x, y, w, d, h, ...more });
function board(components: BoardComponent[], accessories: BoardAccessory[] = [], W = 50, H = 40): BoardSpec {
  const holes = [[3.5, 3.5], [W - 3.5, 3.5], [3.5, H - 3.5], [W - 3.5, H - 3.5]].map(([x, y]) => ({ x, y, d: 3.2, use: 'mount' as const }));
  return { schema: 'fw.board/1', id: 'syn', name: 'synthetic', source: { kind: 'pcb' }, frame: 'mm', pcb: { outline: { kind: 'rect', w: W, h: H }, thickness: 1.6, holes },
    components, accessories, heights: { bottom_max: 2 } };
}
const usb = (edge: '+x' | '-x' | '+y' | '-y', at: number): BoardComponent =>
  ({ id: `usb${edge}`, type: 'usb_c', side: 'top', access: 'port', edge, at, w: 8.94, h: 3.26, d: 7.35, protrude: 0.5, plug: [12.4, 6.5], plugR: 0.6 });
const OLED: BoardAccessory = { id: 'OLED1', key: 'oled_ssd1306_096', kind: 'display', mount: 'board', x: 25, y: 20, w: 27.3, d: 27.8, h: 3.7, z0: 8.5, window: [23, 12], window_dy: 1 };

test('fw.board/1 schema: the new access kinds, window/shape and accessories', () => {
  assert.deepEqual(schema.$defs.component.properties.access.enum, ['port', 'press', 'light', 'sensor', 'display', 'sound', 'key', 'cable', 'none']);
  assert.ok(schema.$defs.component.properties.window && schema.$defs.component.properties.shape);
  assert.deepEqual(schema.$defs.accessory.properties.mount.enum, ['board', 'cable', 'inside']);
  assert.equal(schema.properties.accessories.items.$ref, '#/$defs/accessory');
});

test('sound: a hex grille of 1.5 mm holes on a 3 mm pitch over a round buzzer, all through the lid in one cut; a 3 x 3 pattern over a small one', () => {
  const spec = board([part('BZ1', 'sound', 25, 20, 12, 12, 9.5, { shape: 'round' })]);
  const quiet = board([part('BZ1', 'none', 25, 20, 12, 12, 9.5)]);
  const genus = plan(quiet, {}, (enc) => enc.lid.genus());
  plan(spec, {}, (enc) => {
    const f = feature(enc, 'sound_grille', 'BZ1');
    assert.ok(f.count >= 7 && f.count === f.holes.length && f.d === 1.5 && f.pitch === 3, JSON.stringify(f));
    // inside the buzzer's circle less a 0.5 mm margin, 3 mm apart, one on its centre (where a magnetic buzzer's port is)
    for (const [x, y] of f.holes) assert.ok(Math.hypot(x - 25, y - 20) <= 6 - 0.5 - 0.75 + 1e-6, `${x}, ${y}`);
    for (let i = 0; i < f.holes.length; i++) for (let j = i + 1; j < f.holes.length; j++)
      assert.ok(Math.hypot(f.holes[i][0] - f.holes[j][0], f.holes[i][1] - f.holes[j][1]) >= 3 - 0.01);
    assert.ok(f.holes.some(([x, y]: number[]) => x === 25 && y === 20));
    assert.equal(enc.lid.genus() - genus, f.count); // every hole goes through
  });
  const c = check(spec);
  assert.deepEqual(errors(c), []);
  const g = find(c, 'sound_grille', 'BZ1');
  assert.ok(g.severity === 'info' && g.value >= 7 && /open over it/.test(g.msg), JSON.stringify(g));
  // a 5 x 5 mm SMD buzzer: 3 x 3 holes, as close as a two-line web allows (1.5 + 0.15 compensation + 0.9)
  plan(board([part('BZ2', 'sound', 25, 20, 5, 5, 2.5)]), {}, (enc) => {
    const f = feature(enc, 'sound_grille', 'BZ2');
    assert.ok(f.count === 9 && Math.abs(f.pitch - 2.55) < 1e-9, JSON.stringify(f));
  });
  // a case built without the grille (for a board that did not say BZ1 needs sound): the check finds the buzzer muffled
  assert.equal(find(check(quiet), 'sound_grille'), undefined);
  const out = buildProgram(engine.wasm, engine.evaluator, engine.compile(CASE), { layout: 'assembled', show_board: true }, { printer: DEFAULT_PRINTER, inputs: inputs(quiet) });
  try {
    const m = find(checkEnclosure(engine.wasm, out.parts, spec), 'sound_grille', 'BZ1');
    assert.ok(m.severity === 'error' && /no sound grille over it; the buzzer is muffled/.test(m.msg), JSON.stringify(m));
  } finally {
    disposeBuild(out);
  }
});

test('light: a WS2812 5050 gets a window (its footprint + 0.6) flared 45 deg on the outside; a 0603 keeps its 2 mm hole; skin mode leaves 0.4 mm', () => {
  const spec = board([part('LED1', 'light', 20, 20, 5.4, 5, 1.6), part('LED2', 'light', 35, 20, 1.46, 2.96, 0.6, { type: 'led_0603' })]);
  plan(spec, {}, (enc) => {
    const f = feature(enc, 'light', 'LED1');
    assert.ok(f.mode === 'window' && f.w === 6 && f.d === 5.6 && f.chamfer === 0.8 && f.shape === 'rect', JSON.stringify(f));
    assert.equal(feature(enc, 'light', 'LED2').mode, 'hole 2');
    // 0.4 mm outside the window's side the flare has taken the top 0.4 mm of the lid off (0.8 - 0.4)
    const top = enc.zTop + enc.lidT, x = f.at[0] + f.w / 2 + 0.4;
    const hit = enc.lid.rayCast([x, f.at[1], top + 1], [x, f.at[1], enc.zTop - 0.5])[0];
    assert.ok(hit && Math.abs(hit.position[2] - (top - 0.4)) < 0.03, String(hit?.position));
    // and straight down the window nothing
    assert.equal(enc.lid.rayCast([f.at[0] + f.w / 2 - 0.1, f.at[1], top + 1], [f.at[0] + f.w / 2 - 0.1, f.at[1], enc.zTop - 0.5]).length, 0);
  });
  const c = check(spec);
  assert.deepEqual(errors(c), []);
  for (const id of ['LED1', 'LED2']) assert.ok(find(c, 'light_window', id).severity === 'info' && find(c, 'light_window', id).value === 0, id);
  const skin = check(spec, { lights: 'skin' });
  assert.ok(Math.abs(find(skin, 'light_window', 'LED1').value - 0.4) < 0.01 && find(skin, 'light_window', 'LED1').severity === 'info');
});

test('sensor and display windows: round over a TO-5 PIR, rectangular over a display part, shrunk off a post, blocked over one', () => {
  const spec = board([part('PIR1', 'sensor', 18, 22, 9.4, 9.4, 4.5, { shape: 'round' }), part('DS1', 'display', 36, 22, 12, 7, 3), part('L1', 'sensor', 7, 7, 4, 4, 1)]);
  plan(spec, {}, (enc) => {
    const p = feature(enc, 'sensor_window', 'PIR1');
    assert.ok(p.shape === 'round' && Math.abs(p.w - 10) < 1e-6 && p.w === p.d && !p.shrunk, JSON.stringify(p));
    const d = feature(enc, 'display_window', 'DS1');
    assert.ok(d.w === 12.6 && d.d === 7.6 && d.chamfer === 0.8, JSON.stringify(d));
    // L1's window would run into the hold-down post at (3.5, 3.5): it keeps the post's radius + 0.4 mm + the flare off it
    const l = feature(enc, 'sensor_window', 'L1');
    assert.ok(/hold-down post at 3.5, 3.5/.test(l.shrunk) && l.w * l.d < 4.6 * 4.6 && l.w * l.d >= 0.5 * 4.6 * 4.6, JSON.stringify(l));
    const post = enc.posts.find((q: any) => q.x === 3.5 && q.y === 3.5), keep = 3.5 + post.r + 0.4 + 0.8;
    assert.ok(Math.max(l.at[0] - l.w / 2, l.at[1] - l.d / 2) >= keep - 1e-6, JSON.stringify({ l, post }));
  });
  const c = check(spec);
  assert.deepEqual(errors(c), []);
  assert.equal(find(c, 'sensor_window', 'PIR1').severity, 'info');
  assert.match(find(c, 'sensor_window', 'PIR1').msg, /round sensor window 10 mm open/);
  assert.equal(find(c, 'display_window', 'DS1').severity, 'info');
  assert.equal(find(c, 'sensor_window', 'L1').severity, 'warn');
  // a light sensor right on a mount hole: no window can be had, and the check says why
  const over = check(board([part('L2', 'sensor', 3.5, 3.5, 2, 2, 0.5)]));
  const f = find(over, 'sensor_window', 'L2');
  assert.ok(f.severity === 'error' && /hold-down post/.test(f.msg), JSON.stringify(f));
});

test('a press tongue keeps off a lid window, and openings keep off the snap hooks', () => {
  // the button's +y tongue would run through the display's window
  const spec = board([part('SW1', 'press', 25, 10, 6, 6, 5, { type: 'tact_6x6' }), part('DS1', 'display', 25, 21, 10, 6, 3)]);
  plan(spec, {}, (enc) => {
    const t = feature(enc, 'flex_button', 'SW1');
    assert.ok(t.dir !== '+y' && t.clearOfPosts, JSON.stringify(t));
    assert.ok(!feature(enc, 'display_window', 'DS1').shrunk);
  });
  const c = check(spec);
  assert.deepEqual(errors(c), []);
  assert.equal(find(c, 'button_reach', 'SW1').severity, 'info');
  // a sensor at the middle of a long wall, where its one snap hook would go: the hook moves along the wall off it
  const hookAt = (spec: BoardSpec) => plan(spec, {}, (enc) => enc.hooks.filter((h: any) => h.side === '+y').map((h: any) => enc.inner.x0 + (enc.inner.x1 - enc.inner.x0) * h.along));
  assert.ok(hookAt(board([part('PIR1', 'none', 18, 28, 6, 3, 2)], [], 36, 30)).some((x: number) => Math.abs(x - 18) < 1), 'the hook goes mid-wall without it');
  const wall = board([part('PIR1', 'sensor', 18, 28, 6, 3, 2)], [], 36, 30);
  plan(wall, {}, (enc) => {
    const f = feature(enc, 'sensor_window', 'PIR1');
    assert.ok(!f.shrunk && !f.blocked, JSON.stringify(f));
  });
  const xs = hookAt(wall);
  assert.ok(xs.length === 1 && Math.abs(xs[0] - 18) >= (6.6 + 1.6) / 2 + 3, String(xs));
  assert.deepEqual(errors(check(wall)), []);
});

test('a display module on a header: the case rises over it, the lid or a rim from it holds it down, the window shows its glass', () => {
  const low = board([], [OLED]);
  plan(low, {}, (enc) => {
    // the lid 0.2 mm over the module's top: it presses all round the window
    assert.ok(Math.abs(enc.zTop - (enc.zBoard + 1.6 + 8.5 + 3.7 + 0.2)) < 1e-6, String(enc.zTop));
    const f = feature(enc, 'display_window', 'OLED1');
    assert.ok(f.w === 23.6 && f.d === 12.6 && f.at[0] === 25 && f.at[1] === 21 && f.hold === 'lid' && f.press.length === 4 && !f.rim, JSON.stringify(f));
  });
  const c = check(low);
  assert.deepEqual(errors(c), []);
  const d = find(c, 'display_window', 'OLED1');
  assert.ok(d.severity === 'info' && /held down onto its header by the lid at 4 of 4 sides/.test(d.msg), JSON.stringify(d));
  assert.equal(find(c, 'component_clear', 'OLED1').severity, 'info');
  // a 16 mm buzzer beside it sets the lid higher: a rim hangs from the lid round the window down to the module
  const tall = board([part('BZ1', 'sound', 6.5, 30, 9, 9, 16, { shape: 'round' })], [{ ...OLED, x: 30 }]);
  plan(tall, {}, (enc) => {
    const f = feature(enc, 'display_window', 'OLED1');
    assert.ok(f.hold === 'rim' && Math.abs(f.rim.h - (16 + 1.2 - 12.2 - 0.2)) < 0.01, JSON.stringify(f));
    // the rim stays on the module: 0.2 mm in from its sides
    assert.ok(f.rim.rect[0] >= 30 - 27.3 / 2 + 0.2 - 1e-6 && f.rim.rect[2] <= 30 + 27.3 / 2 - 0.2 + 1e-6, JSON.stringify(f.rim));
  });
  const r = check(tall);
  assert.deepEqual(errors(r), []);
  assert.match(find(r, 'display_window', 'OLED1').msg, /by the lid rim \([\d.]+ mm\) at 4 of 4 sides/);
  // an LED and a button under the module: no hole or tongue is made for them, and the check says the module covers them
  const under = board([part('LED1', 'light', 25, 20, 1.46, 2.96, 0.6), part('SW1', 'press', 30, 15, 6, 6, 5)], [OLED]);
  plan(under, {}, (enc) => {
    assert.equal(feature(enc, 'light', 'LED1').covered, 'OLED1');
    assert.equal(feature(enc, 'flex_button', 'SW1'), undefined);
  });
  const u = check(under);
  assert.match(find(u, 'light_window', 'LED1').msg, /under OLED1/);
  assert.equal(find(u, 'button_unreachable', 'SW1').severity, 'error');
  // a part taller than the header under the module runs into it
  const hit = check(board([part('C1', 'none', 25, 20, 6, 6, 10)], [OLED]));
  assert.match(errors(hit).join('\n'), /OLED1: the module runs into C1/);
});

test('cable exit: a cable_d + 0.6 hole in its wall with a zip-tie slot behind it; the bay it needs grows the case; moved off a port, blocked with no room', () => {
  const spec = board([], [{ id: 'PROBE', key: 'soil_probe', kind: 'probe', mount: 'cable', edge: '-x', at: 20, cable_d: 3.5 }]);
  plan(spec, {}, (enc) => {
    const f = feature(enc, 'cable_exit', 'PROBE');
    assert.ok(f.edge === '-x' && f.at === 20 && Math.abs(f.d - 4.1) < 1e-9 && f.relief === 'tie slot' && !f.moved, JSON.stringify(f));
    // the tie block (4.4 mm) and 0.5 mm stand between the wall and the board
    assert.ok(enc.inner.x0 <= -(4.4 + 0.5) + 1e-9, JSON.stringify(enc.inner));
    // the hole is in the wall between the board top and 1 mm under the lid joint
    const zc = f.z + enc.zBoard;
    assert.ok(zc - f.d / 2 >= enc.zBoard + 1.6 + 0.3 - 1e-6 && zc + f.d / 2 <= enc.zTop - 1.0 + 1e-6, JSON.stringify({ zc, zTop: enc.zTop }));
    // straight along the cable from inside the block out of the wall: open at the axis and 1.9 mm off it, the slot cuts across
    const x0 = enc.inner.x0 + 6, x1 = enc.inner.x0 - enc.wall - 1;
    for (const [dy, dz] of [[0, 0], [1.9, 0], [-1.9, 0], [0, 1.9], [0, -1.9]]) assert.equal(enc.base.rayCast([x0, 20 + dy, zc + dz], [x1, 20 + dy, zc + dz]).length, 0, `${dy}, ${dz}`);
    const slot = enc.base.rayCast([enc.inner.x0 + 1.4, 20 + 3.5, enc.zTop], [enc.inner.x0 + 1.4, 20 + 3.5, zc - f.d / 2 - 1.4]);
    assert.equal(slot.length, 0); // open down to the tie's bottom
  });
  const c = check(spec);
  assert.deepEqual(errors(c), []);
  const e = find(c, 'cable_exit', 'PROBE');
  assert.ok(e.severity === 'info' && e.value === 4.1 && /zip-tie slot/.test(e.msg), JSON.stringify(e));
  // the same spot as a USB-C window on that wall: the exit moves along it
  const shared = board([usb('-x', 20)], [{ id: 'PROBE', mount: 'cable', edge: '-x', at: 20, cable_d: 3.5 }]);
  plan(shared, {}, (enc) => {
    const f = feature(enc, 'cable_exit', 'PROBE');
    assert.ok(Math.abs(f.moved) >= (12.4 + 0.6) / 2 + 0.6 + 0.6 + 4.1 / 2 + 2.4 - 0.25 - 1e-6, JSON.stringify(f));
  });
  assert.deepEqual(errors(check(shared)), []);
  // a 16 mm wide board edge taken by a USB-C window: no room
  const full = board([usb('-y', 8)], [{ id: 'PROBE', mount: 'cable', edge: '-y', at: 8, cable_d: 3.5 }], 16, 30);
  const x = find(check(full), 'cable_exit', 'PROBE');
  assert.ok(x.severity === 'error' && /no [\d.]+ mm of the -y wall is free/.test(x.msg), JSON.stringify(x));
  // a cable accessory without an edge leaves through the wall nearest its x, y
  plan(board([], [{ id: 'P2', mount: 'cable', x: 45, y: 20 }]), {}, (enc) => assert.equal(feature(enc, 'cable_exit', 'P2').edge, '+x'));
});

test('a loose LiPo goes under the board on taller standoffs, or beside it when that makes the smaller case; ribs keep it, the check finds room', () => {
  const cell = (w: number, d: number, h: number): BoardAccessory => ({ id: 'BAT', key: 'lipo', kind: 'battery', mount: 'inside', w, d, h });
  const spec = board([part('U1', 'none', 25, 20, 18, 21, 4)], [cell(30, 20, 5)]);
  plan(spec, {}, (enc, E) => {
    const f = feature(enc, 'battery', 'BAT');
    assert.ok(f.placement === 'under' && Math.abs(enc.report.standoff - (2 + 5 + 0.4)) < 1e-9 && f.underPins === 0.4, JSON.stringify(f));
    assert.deepEqual(enc.cells.map((c: any) => c.id), ['BAT']);
    // clear of the standoffs by 0.3 mm and its ribs
    for (const p of enc.posts) assert.ok(Math.hypot(Math.max(f.box.min[0] - 1.5 - p.x, 0, p.x - f.box.max[0] - 1.5), Math.max(f.box.min[1] - 1.5 - p.y, 0, p.y - f.box.max[1] - 1.5)) >= 2.3, JSON.stringify(p));
    // the assembled parts show it as a reference part after the board
    const parts = E.parts(enc, { layout: 'assembled', ghost: true });
    assert.deepEqual(parts.map((p: any) => [p.name, p.role]), [['base', 'model'], ['lid', 'model'], ['board', 'reference'], ['BAT', 'reference']]);
  });
  const c = check(spec);
  assert.deepEqual(errors(c), []);
  const b = find(c, 'battery_space', 'BAT');
  assert.ok(b.severity === 'info' && Math.abs(b.value - 0.4) < 0.02 && /under the board/.test(b.msg), JSON.stringify(b));
  // too big to go under: beside, on a side without ports
  const big = board([usb('+y', 25), part('U1', 'none', 25, 20, 18, 21, 4)], [cell(45, 35, 6)]);
  plan(big, {}, (enc) => {
    const f = feature(enc, 'battery', 'BAT');
    assert.ok(f.placement === 'beside' && f.side !== '+y' && f.hold === 'lid bars', JSON.stringify(f));
    assert.ok(enc.report.standoff === 2.6, String(enc.report.standoff));
  });
  const bc = check(big);
  assert.deepEqual(errors(bc), []);
  assert.match(find(bc, 'battery_space', 'BAT').msg, /beside the board .*lid bars/);
  // asked to go beside: it does
  plan(spec, { battery: 'beside' }, (enc) => assert.equal(feature(enc, 'battery', 'BAT').placement, 'beside'));
  // no room under and a port on every side: the check says so
  const boxed = board([usb('+x', 20), usb('-x', 20), usb('+y', 25), usb('-y', 25)], [cell(60, 50, 6)]);
  const nb = find(check(boxed), 'battery_space', 'BAT');
  assert.ok(nb.severity === 'error' && /no room/.test(nb.msg), JSON.stringify(nb));
});

test('a case with every new feature prints: no too_thin, thin_wall, long_bridge or floating parts, and the browser-side build stays quick', () => {
  const spec = board([part('BZ1', 'sound', 12, 26, 12, 12, 7, { shape: 'round' }), part('LED1', 'light', 40, 8, 5.4, 5, 1.6), part('PIR1', 'sensor', 40, 30, 9.4, 9.4, 4.5, { shape: 'round' })],
    [{ ...OLED, x: 25, y: 14, w: 20, d: 12, window: [16, 8], window_dy: 0 }, { id: 'PROBE', mount: 'cable', edge: '-x', at: 20, cable_d: 3.5 }, { id: 'BAT', mount: 'inside', w: 30, d: 20, h: 4 }]);
  const t0 = performance.now();
  const r = engine.build({ source: CASE, inputs: inputs(spec), analyze: 'full' });
  const ms = performance.now() - t0;
  assert.equal(r.checks.ok, true);
  const bad = r.checks.issues.filter((i: any) => ['too_thin', 'thin_wall', 'long_bridge', 'floating_island'].includes(i.code) && i.severity !== 'info');
  assert.deepEqual(bad.map((i: any) => i.message), []);
  assert.ok(ms < 8000, `${Math.round(ms)} ms`);
  const c = check(spec);
  assert.deepEqual(errors(c), []);
  for (const code of ['sound_grille', 'light_window', 'sensor_window', 'display_window', 'cable_exit', 'battery_space']) assert.ok(find(c, code), code);
});

test('kitchen timer from the 2026-11-03 run: a round grille over the 23 mm buzzer, the OLED held by a lid rim over its socket, every button reached', () => {
  const spec = json('./data/kitchen_timer.board.json') as BoardSpec;
  const c = check(spec);
  assert.deepEqual(errors(c), []);
  assert.deepEqual(c.findings.filter((f: any) => f.severity === 'warn').map((f: any) => f.code), ['snap_strain'].filter((k) => find(c, k)?.severity === 'warn'));
  const g = find(c, 'sound_grille', 'BZ1');
  assert.ok(g.severity === 'info' && g.value >= 40, JSON.stringify(g));
  assert.match(find(c, 'display_window', 'OLED1').msg, /display window 23\.6 x 12\.6 mm open; held down onto its header by the lid rim \(4\.8 mm\) at 4 of 4 sides/);
  assert.equal(find(c, 'light_window', 'LED1').value, 0);
  for (const id of ['SW1', 'SW2', 'SW3', 'U1_btn_boot', 'U1_btn_reset']) assert.equal(find(c, 'button_reach', id)?.severity, 'info', id);
  plan(spec, {}, (enc) => {
    // the 16 mm buzzer sets the height; the features name what they are for
    assert.ok(Math.abs(enc.zTop - (enc.zBoard + 1.6 + 16 + 1.2)) < 1e-6);
    const named = enc.report.features.filter((f: any) => ['sound_grille', 'display_window', 'light'].includes(f.type)).map((f: any) => `${f.type}:${f.for}`).sort();
    assert.deepEqual(named, ['display_window:OLED1', 'light:LED1', 'sound_grille:BZ1']);
  });
});

test('leak sensor from the 2026-11-03 run: probe wires out of the -y wall past a tie slot, the LiPo under the board, a grille over the buzzer', () => {
  const spec = json('./data/leak_sensor.board.json') as BoardSpec;
  const c = check(spec);
  assert.deepEqual(errors(c), []);
  assert.match(find(c, 'cable_exit', 'PROBE').msg, /3\.6 mm cable exit in the -y wall at 26 mm/);
  assert.match(find(c, 'battery_space', 'BAT').msg, /35 x 30 x 5 mm cell under the board/);
  assert.ok(find(c, 'sound_grille', 'BZ1').value >= 5);
  assert.equal(find(c, 'port_clear', 'U1_usb').severity, 'info');
  const r = engine.build({ source: CASE, inputs: inputs(spec), analyze: 'full' });
  assert.ok(r.checks.ok && r.checks.score >= 90, String(r.checks.score));
});
