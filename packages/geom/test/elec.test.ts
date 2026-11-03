import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { strFromU8, unzipSync, unzlibSync } from 'fflate';
import { Engine, loadKernel, functionEvaluator, fromBase64, makeLib, DEFAULT_PRINTER, withArena, displayBuffers, buildProgram, disposeBuild } from '../src/index.ts';
import { canTip, checkEnclosure } from '../src/enclosure.ts';
import type { BoardSpec } from '../src/lib/elec.ts';
import { BOARD_CASE as CASE } from './fixtures.ts'; // the case program an agent writes for a board, over lib.elec

const engine = new Engine(await loadKernel(), functionEvaluator());
const wasm = engine.wasm;
const json = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const dataset = json('../src/boards.json') as { boards: BoardSpec[]; typical: Record<string, unknown> };
const schema = json('../src/board.schema.json');
const carrier = json('./data/xiao_carrier.board.json') as BoardSpec;
const board = (id: string): BoardSpec => structuredClone(dataset.boards.find((b) => b.id === id)!);

// the same program with the edge clips as a param
const CASE_CLIPS = CASE.replace("layout: { value: 'print'", "clips: { value: 'edge', options: ['edge', 'none'], source: 'design' },\n  layout: { value: 'print'")
  .replace('buttons: p.buttons });', 'buttons: p.buttons, clips: p.clips });');

const inputs = (spec: BoardSpec) => ({ boards: { board: spec } });
const check = (spec: BoardSpec, params: Record<string, any> = {}) =>
  engine.inspect({ source: CASE, inputs: inputs(spec), params, ops: [{ op: 'enclosure' }] }).results[0] as any;
const find = (r: any, code: string, part?: string) => r.findings.find((f: any) => f.code === code && (part === undefined || f.part === part));
const errors = (r: any) => r.findings.filter((f: any) => f.severity === 'error');

// lib.elec straight from makeLib: the case report and solids, for checks on the plan itself
function plan<T>(spec: BoardSpec, opts: Record<string, unknown>, fn: (enc: any, E: any, lib: any) => T): T {
  return withArena(() => {
    const lib = makeLib(wasm, { printer: DEFAULT_PRINTER, inputs: inputs(spec) });
    const enc = lib.elec.enclosure(lib.elec.board(spec), opts);
    return fn(enc, lib.elec, lib);
  });
}
// RGBA pixels of a PNG from encodePng (one IDAT, filter 0 on every row).
function pixels(b64: string) {
  const png = fromBase64(b64);
  const dv = new DataView(png.buffer, png.byteOffset);
  const width = dv.getUint32(16);
  let o = 8;
  const idat: Uint8Array[] = [];
  while (o < png.length) {
    const len = dv.getUint32(o);
    if (String.fromCharCode(...png.subarray(o + 4, o + 8)) === 'IDAT') idat.push(png.subarray(o + 8, o + 8 + len));
    o += 12 + len;
  }
  const raw = unzlibSync(Uint8Array.from(idat.flatMap((c) => [...c])));
  const rows = raw.length / (width * 4 + 1);
  const out = new Uint8Array(width * rows * 4);
  for (let y = 0; y < rows; y++) out.set(raw.subarray(y * (width * 4 + 1) + 1, (y + 1) * (width * 4 + 1)), y * width * 4);
  return out;
}
const bluish = (rgba: Uint8Array) => {
  let n = 0;
  for (let i = 0; i < rgba.length; i += 4) if (rgba[i + 2] - rgba[i] > 40 && rgba[i + 2] > rgba[i + 1]) n++;
  return n;
};
const feature = (enc: any, type: string, id?: string) => enc.report.features.find((f: any) => f.type === type && (id === undefined || f.for === id));

test('fw.board/1: schema and dataset of 13 boards with the typical parts table', () => {
  assert.equal(schema.$id, 'fw.board/1');
  assert.equal(dataset.boards.length, 13);
  for (const k of ['usb_c', 'usb_micro_b', 'pin_header_2_54', 'tact_6x6', 'tact_3x4_smd', 'led_0603', 'jst_ph_2p']) assert.ok(dataset.typical[k], k);
  for (const b of [...dataset.boards, carrier]) {
    for (const k of schema.required) assert.ok(k in b, `${b.id}: ${k}`);
    assert.equal(b.schema, 'fw.board/1');
    for (const c of b.components) {
      for (const k of schema.$defs.component.required) assert.ok(k in c, `${b.id}.${c.id}: ${k}`);
      if (c.access === 'port') for (const k of ['edge', 'at', 'd', 'protrude']) assert.ok(k in c, `${b.id}.${c.id}: ${k}`);
      else for (const k of ['x', 'y', 'd']) assert.ok(k in c, `${b.id}.${c.id}: ${k}`);
    }
  }
});

test('every dataset board gets a printable case that passes check_enclosure', () => {
  for (const spec of dataset.boards) {
    const r = engine.build({ source: CASE, inputs: inputs(spec), analyze: 'full' });
    assert.equal(r.checks.ok, true, spec.id);
    assert.ok(r.checks.score >= 90, `${spec.id}: score ${r.checks.score}`);
    const c = check(spec);
    assert.deepEqual(errors(c), [], spec.id);
    const ports = spec.components.filter((p) => p.access === 'port');
    assert.equal(Object.keys(c.clearance).length, ports.length, spec.id);
    // a 0.3 mm port fit, less at most 0.01 mm of chord in the window's corner arcs
    for (const p of ports) assert.ok(c.clearance[p.id] >= 0.285, `${spec.id}.${p.id}: ${c.clearance[p.id]}`);
    // held: on standoffs and pegs, or on ledges under edge clips
    assert.equal(find(c, 'pcb_seated')?.severity, 'info', spec.id);
    assert.equal(find(c, 'board_retained')?.severity, 'info', `${spec.id}: ${find(c, 'board_retained')?.msg}`);
    assert.ok(c.rays.length > 0 && c.rays.every((r: any) => r.from.length === 3 && r.to.length === 3 && typeof r.hit === 'boolean'), spec.id);
    for (const p of ports) assert.ok(c.rays.filter((r: any) => r.port === p.id).length <= 12, `${spec.id}.${p.id}`);
  }
});

test('Pico W: plug clearance 0.29 mm, BOOTSEL plunger 0.30 mm, snap strain under 2 %, no metal at the antenna', () => {
  const c = check(board('rpi-pico-w'));
  assert.ok(c.clearance.usb >= 0.285 && c.clearance.usb <= 0.3, String(c.clearance.usb));
  // the case as it stands with its lid on: the 21 x 51 mm board, walls round it
  assert.ok(c.size[0] > 25 && c.size[0] < 35 && c.size[1] > 55 && c.size[1] < 65 && c.size[2] > 5, String(c.size));
  const port = find(c, 'port_clear', 'usb');
  assert.equal(port.severity, 'info');
  assert.equal(port.value, c.clearance.usb);
  assert.equal(port.unit, 'mm');
  const btn = find(c, 'button_reach', 'bootsel');
  assert.ok(btn && Math.abs(btn.value - 0.3) <= 0.05, JSON.stringify(btn));
  const snap = find(c, 'snap_strain');
  assert.ok(snap.value < 2, JSON.stringify(snap));
  assert.equal(find(c, 'keepout_ok', 'antenna').severity, 'info');
  assert.equal(find(c, 'pcb_seated').severity, 'info');
  const held = find(c, 'board_retained');
  assert.equal(held.severity, 'info');
  assert.equal(held.value, 4);
  assert.match(held.msg, /4 posts over its 4 mount holes; pegs locate it/);
  assert.equal(find(c, 'light_window', 'led').value, 0);
  assert.equal(find(c, 'lid_fit').severity, 'info');
  // the usb rays leave through the +y window, none of them hit
  const usb = c.rays.filter((r: any) => r.port === 'usb');
  assert.ok(usb.length >= 9 && usb.every((r: any) => !r.hit && r.to[1] > r.from[1]));
  assert.ok(c.ms < 2000, `op took ${c.ms} ms`);
});

test('inspect ray reports millimetres, and the segment fraction as frac', () => {
  const cube = 'function build(p, lib) { return lib.M.cube([10, 10, 10]); } return { meta: {}, params: {}, build };';
  const r = engine.inspect({ source: cube, ops: [{ op: 'ray', from: [-2.5, 5, 5], to: [7.5, 5, 5] }, { op: 'ray', from: [-5, 5, 5], to: [5, 5, 5] }] }).results as any[];
  assert.equal(r[0].hits[0].distance, 2.5);
  assert.equal(r[0].hits[0].frac, 0.25);
  assert.equal(r[1].hits[0].distance, 5);
  assert.equal(r[1].hits[0].frac, 0.5);
});

test("a 'reference' part is not exported, not checked, drawn translucent and flagged for the viewer", () => {
  const spec = board('rpi-pico-w');
  const asm = { source: CASE, inputs: inputs(spec), params: { layout: 'assembled', show_board: true } };
  const r = engine.build({ ...asm, analyze: 'full' });
  const ghost = r.parts.find((p: any) => p.role === 'reference');
  assert.ok(ghost && ghost.name === 'board' && ghost.reference === true);
  const models = r.parts.filter((p: any) => p.role === 'model');
  assert.deepEqual(models.map((p: any) => p.name), ['base', 'lid']);
  // checks and stats see only the printed parts
  const printed = models.reduce((s: number, p: any) => s + p.volume, 0);
  assert.ok(Math.abs(r.checks.stats.volume - printed) < 1, `${r.checks.stats.volume} vs ${printed}`);
  // 3MF: two parts, no board; and a version saved in the assembled view still exports the print layout
  const files = unzipSync(fromBase64(engine.export({ ...asm, format: '3mf' }).data));
  const cfg = strFromU8(files['Metadata/model_settings.config']);
  assert.equal((cfg.match(/<part /g) ?? []).length, 2);
  assert.ok(!cfg.includes('value="board"'));
  const z = (params: Record<string, string | boolean>) => {
    const stl = fromBase64(engine.export({ ...asm, params, format: 'stl' }).data);
    const dv = new DataView(stl.buffer, stl.byteOffset);
    let top = 0;
    for (let f = 0; f < dv.getUint32(80, true); f++) for (let v = 0; v < 3; v++) top = Math.max(top, dv.getFloat32(84 + f * 50 + 12 + v * 12 + 8, true));
    return top;
  };
  assert.ok(Math.abs(z(asm.params) - z({})) < 1e-3);
  assert.ok(Math.abs(engine.build({ ...asm, analyze: 'none' }).parts.find((p: any) => p.name === 'lid').bbox.max[2] - z({})) > 1);
  // viewer buffers: the ghost goes to its own buffer, not into the pickable model mesh
  const out = buildProgram(wasm, engine.evaluator, engine.compile(CASE), asm.params, { printer: DEFAULT_PRINTER, inputs: asm.inputs });
  try {
    const d = displayBuffers(out.parts, DEFAULT_PRINTER, { heat: false });
    const iRef = out.parts.findIndex((p) => p.role === 'reference');
    assert.deepEqual(d.reference.map((g) => g[2]), [iRef]);
    assert.equal(d.referencePosition.length, out.parts[iRef].solid.numTri() * 9);
    assert.ok(d.groups.every((g) => g[2] !== iRef));
  } finally {
    disposeBuild(out);
  }
  // renders: in a section through the case the board shows as a blue tint over what is behind it
  const cut = { axis: 'x' as const, at: 10.5, keep: 'below' as const };
  const withBoard = bluish(pixels(engine.render({ ...asm, cut, tile: 200 }).png));
  const without = bluish(pixels(engine.render({ ...asm, params: { layout: 'assembled' }, cut, tile: 200 }).png));
  assert.ok(withBoard - without > 300, `${withBoard} vs ${without} blue pixels`);
});

test('XIAO carrier from the PCB pipeline: both USB-C windows open and the case passes', () => {
  const c = check(carrier);
  assert.deepEqual(errors(c), []);
  for (const id of ['J1', 'U1_usb']) {
    assert.equal(find(c, 'port_clear', id)?.severity, 'info', id);
    assert.ok(c.clearance[id] > 0.2, id);
  }
  for (const id of ['U1_boot', 'U1_reset', 'SW1']) assert.equal(find(c, 'button_reach', id)?.severity, 'info', id);
  plan(carrier, {}, (enc) => {
    const w = enc.report.features.filter((f: any) => f.type === 'port_window');
    assert.deepEqual(w.map((f: any) => [f.for, f.edge]), [['J1', '-y'], ['U1_usb', '+y']]);
    // the XIAO's own USB-C sits on the module, 3.7 mm over the carrier: its window is that high
    const usb = enc.board.comps.find((p: any) => p.id === 'U1_usb');
    assert.ok(Math.abs(usb.box.min[2] - (carrier.pcb.thickness + 3.7)) < 1e-9);
    // standoffs only under the 4 mount holes, not under the 22 pin holes
    assert.equal(enc.report.features.filter((f: any) => f.type === 'mount').length, 4);
  });
  // printed stand-in of the PCB: the outline at 1.6 mm with the mount and pin holes through it
  plan(carrier, {}, (enc, E) => {
    const plate = E.pcbPlate(enc.board);
    const bb = plate.boundingBox();
    assert.deepEqual([bb.max[0] - bb.min[0], bb.max[1] - bb.min[1]].map((v) => +v.toFixed(2)), [44, 36]);
    assert.ok(Math.abs(bb.max[2] - bb.min[2] - 1.6) < 1e-6);
    assert.equal(plate.genus(), carrier.pcb.holes.length);
    assert.equal(E.pcbPlate(enc.board, { holes: ['mount'] }).genus(), 4);
  });
});

test('a case built for one board does not pass for a board with its port elsewhere', () => {
  const spec = board('rpi-pico-w');
  const moved = board('rpi-pico-w');
  moved.components.find((c) => c.id === 'usb')!.at! += 3;
  const out = buildProgram(wasm, engine.evaluator, engine.compile(CASE), { layout: 'assembled', show_board: true }, { printer: DEFAULT_PRINTER, inputs: inputs(spec) });
  try {
    const c = checkEnclosure(wasm, out.parts, moved);
    const f = find(c, 'port_blocked', 'usb');
    assert.equal(f?.severity, 'error');
    assert.equal(c.clearance.usb, 0);
    assert.ok(c.rays.some((r) => r.port === 'usb' && r.hit));
  } finally {
    disposeBuild(out);
  }
});

test('metal screws inside an antenna keep-out are an error; lib.elec puts pegs there by itself', () => {
  const spec = board('rpi-pico-w');
  const bare = { ...board('rpi-pico-w'), keepouts: [] };
  // mount: 'screw' on a board without the keep-out puts screws at all four holes...
  const out = buildProgram(wasm, engine.evaluator, engine.compile(CASE), { layout: 'assembled', show_board: true, mount: 'screw' }, { printer: DEFAULT_PRINTER, inputs: inputs(bare) });
  try {
    // ...two of which are in the real board's antenna keep-out
    const f = find(checkEnclosure(wasm, out.parts, spec), 'metal_in_keepout', 'antenna');
    assert.equal(f?.severity, 'error');
    assert.equal(f.value, 2);
  } finally {
    disposeBuild(out);
  }
  const c = check(spec, { mount: 'screw' });
  assert.equal(find(c, 'metal_in_keepout'), undefined);
  assert.equal(find(c, 'keepout_ok', 'antenna').severity, 'info');
});

test('enclosure op without a board, or a program without a board ghost, says so', () => {
  const none = engine.inspect({ source: CASE, inputs: { boards: { other: board('rpi-pico') } }, ops: [{ op: 'enclosure' }] }).results[0] as any;
  assert.equal(none.findings[0].severity, 'error');
  assert.match(none.findings[0].msg, /inputs\.boards\.board.*other/);
  const noGhost = CASE.replace('ghost: p.show_board', 'ghost: false');
  const r = engine.inspect({ source: noGhost, inputs: inputs(board('rpi-pico')), ops: [{ op: 'enclosure' }] }).results[0] as any;
  assert.equal(r.findings[0].severity, 'error');
  assert.match(r.findings[0].msg, /ghost/);
});

test('buttons off, side buttons and boards without holes are warnings, not silent', () => {
  const off = check(board('rpi-pico-w'), { buttons: 'none' });
  assert.equal(find(off, 'button_unreachable', 'bootsel')?.severity, 'warn');
  assert.equal(find(check(board('lolin-d1-mini-v4')), 'button_unreachable', 'btn_reset')?.severity, 'warn');
  // DevKitC without its edge clips: ledges under the ends but no room for a hold-down post
  const loose = engine.inspect({ source: CASE_CLIPS, inputs: inputs(board('esp32-devkitc-v4')), params: { clips: 'none' }, ops: [{ op: 'enclosure' }] }).results[0] as any;
  assert.equal(find(loose, 'pcb_seated')?.severity, 'warn');
  assert.equal(find(loose, 'board_retained')?.severity, 'warn');
  assert.equal(find(loose, 'board_retained').value, 0);
});

// ---------------------------------------------------------------- the six defects the checks found in the generator
test('regression 1: window corners follow the plug overmold, so a sharp plug still clears', () => {
  plan(board('rpi-pico-w'), {}, (enc) => assert.equal(feature(enc, 'port_window', 'usb').r, 0.9)); // plugR 0.6 + portFit 0.3
  const sharp = board('rpi-pico-w');
  sharp.components.find((c) => c.id === 'usb')!.plugR = 0;
  plan(sharp, {}, (enc) => assert.equal(feature(enc, 'port_window', 'usb').r, 0.3));
  // 0.3 mm round the corner, less the chord of the meshed arc (0.21 before the arcs got finer); with a
  // fixed 0.8 mm window radius it was 0.07
  const c = check(sharp);
  assert.ok(c.clearance.usb >= 0.29, String(c.clearance.usb));
});

test('regression 2: a plunger next to a tall connector is narrowed to keep off it', () => {
  plan(board('xiao-esp32c3'), {}, (enc) => {
    for (const id of ['btn_boot', 'btn_reset']) assert.ok(feature(enc, 'flex_button', id).plungerD < 2.6, id);
  });
  const c = check(board('xiao-esp32c3'));
  assert.equal(find(c, 'component_clear', 'usb')?.severity, 'info');
  for (const id of ['btn_boot', 'btn_reset']) assert.equal(find(c, 'button_reach', id)?.severity, 'info', id);
});

test('regression 3: hold-down posts stay inside the walls', () => {
  plan(board('arduino-nano'), {}, (enc) => {
    for (const f of enc.report.features.filter((f: any) => f.type === 'mount')) {
      const { x0, y0, x1, y1 } = enc.inner;
      const toWall = Math.min(f.at[0] - x0, x1 - f.at[0], f.at[1] - y0, y1 - f.at[1]);
      assert.ok(f.postD / 2 <= Math.max(0.9, toWall - 0.1), JSON.stringify(f));
    }
  });
  const fit = find(check(board('arduino-nano')), 'lid_fit');
  assert.equal(fit.severity, 'info');
  assert.ok(fit.value < 0.05);
});

test('regression 4: window corners keep 0.2 mm off the receptacle corners', () => {
  const c = check(board('rpi-5'));
  for (const id of ['eth', 'sd', 'pwr_btn', 'usb_a1', 'usb_a2'].filter((id) => board('rpi-5').components.some((p) => p.id === id)))
    assert.equal(find(c, 'component_clear', id)?.severity, 'info', id);
  plan(board('rpi-5'), {}, (enc) => {
    for (const f of enc.report.features.filter((f: any) => f.type === 'port_window')) {
      const p = enc.board.comps.find((q: any) => q.id === f.for);
      const inset = Math.min((f.w - p.w) / 2, (f.h - p.h) / 2);
      // distance from the receptacle corner to the window's rounded corner
      const gap = f.r - Math.SQRT2 * (f.r - inset);
      assert.ok(f.r <= 0.2 + 1e-9 || gap >= 0.2 - 1e-6, `${f.for}: r ${f.r}, inset ${inset}`);
    }
  });
});

test('regression 5: snap hooks end in a blunt tip (two lines), not a knife edge', () => {
  withArena(() => {
    const lib = makeLib(wasm, { printer: DEFAULT_PRINTER });
    const o = { length: 6, thickness: 1, width: 6, overhang: 0.4, lead: 0.6 };
    const tipAt = (hk: any) => {
      const x = hk.boundingBox().max[0] - 0.005;
      const hits = hk.rayCast([x, 0, -1], [x, 0, 3]);
      return hits.length ? hits[1].position[2] - hits[0].position[2] : 0;
    };
    assert.ok(tipAt(lib.std.snapHook(o)) >= 2 * DEFAULT_PRINTER.lineWidth - 0.01);
    assert.ok(tipAt(lib.std.snapHook({ ...o, tipMin: 0 })) < 0.05);
  });
  const r = engine.build({ source: CASE, inputs: inputs(board('rpi-pico-w')), analyze: 'full' });
  assert.ok(!r.checks.issues.some((i: any) => i.code === 'too_thin'), JSON.stringify(r.checks.issues.map((i: any) => i.code)));
});

test('regression 6: hook grooves have a 45 degree roof: no overhangs in the base, the lid comes off', () => {
  for (const id of ['rpi-pico-w', 'rpi-4b']) {
    const r = engine.build({ source: CASE, inputs: inputs(board(id)), analyze: 'full' });
    assert.ok(!r.checks.issues.some((i: any) => i.code === 'overhang' && i.severity !== 'info'), `${id}: ${JSON.stringify(r.checks.issues.map((i: any) => i.code))}`);
    assert.equal(find(check(board(id)), 'lid_fit').value, 0, id);
  }
  plan(board('rpi-pico-w'), {}, (enc) => {
    // the groove's roof starts at the wall face and rises 45 degrees into it
    const hk = feature(enc, 'snap_hooks');
    assert.equal(hk.count, 4);
  });
});

// thinnest wall left behind the hook grooves: rays across the wall at each hook, over the groove's height
function wallAtHooks(enc: any) {
  let min = 99;
  for (const h of enc.hooks) {
    const onX = h.side[1] === 'x', sg = h.side[0] === '+' ? 1 : -1;
    const face = onX ? (sg > 0 ? enc.inner.x1 : enc.inner.x0) : sg > 0 ? enc.inner.y1 : enc.inner.y0;
    const a = onX ? enc.inner.y0 + (enc.inner.y1 - enc.inner.y0) * h.along : enc.inner.x0 + (enc.inner.x1 - enc.inner.x0) * h.along;
    const Lh = feature(enc, 'snap_hooks').length;
    for (let z = enc.zTop - Lh - 1.2; z < enc.zTop - Lh + 1.2; z += 0.05) {
      const p = (d: number): [number, number, number] => (onX ? [face + sg * d, a, z] : [a, face + sg * d, z]);
      const hits = enc.base.rayCast(p(-0.3), p(enc.wall + 1)) as { position: number[] }[];
      if (hits.length >= 2) min = Math.min(min, Math.abs(hits[1].position[onX ? 0 : 1] - hits[0].position[onX ? 0 : 1]));
    }
  }
  return min;
}

test('regression 7: a 1.2 mm wall keeps two lines behind the hook grooves and window chamfers, on every board', () => {
  for (const spec of dataset.boards) {
    const r = engine.build({ source: CASE, inputs: inputs(spec), params: { wall: 1.2 }, analyze: 'full' });
    assert.equal(r.checks.ok, true, spec.id);
    const thin = r.checks.issues.filter((i: any) => ['thin_wall', 'too_thin', 'overhang'].includes(i.code) && i.severity !== 'info');
    assert.deepEqual(thin.map((i: any) => i.message), [], spec.id);
    const c = check(spec, { wall: 1.2 });
    assert.deepEqual(errors(c), [], spec.id);
    assert.equal(find(c, 'lid_fit').value, 0, spec.id);
  }
  // Pico W: a 0.3 mm groove leaves 0.9 mm of wall; the bump shrinks to a 0.2 mm catch, 0.1 mm off the groove floor
  plan(board('rpi-pico-w'), { wall: 1.2 }, (enc) => {
    const hk = feature(enc, 'snap_hooks');
    assert.equal(hk.count, 4);
    assert.ok(Math.abs(hk.groove - 0.3) < 1e-6 && Math.abs(hk.overhang - hk.fit - 0.2) < 1e-6, JSON.stringify(hk));
    assert.ok(Math.abs(wallAtHooks(enc) - 0.91) < 0.02, String(wallAtHooks(enc)));
    for (const f of enc.report.features.filter((f: any) => f.type === 'port_window')) assert.ok(Math.abs(f.chamfer - 0.3) < 1e-6, JSON.stringify(f));
    assert.ok(!enc.report.features.some((f: any) => f.type === 'warning'));
  });
  const snap = find(check(board('rpi-pico-w'), { wall: 1.2 }), 'snap_strain');
  assert.ok(snap.severity === 'info' && snap.value < 1.67, JSON.stringify(snap));
  // the default 2 mm wall is untouched: 0.7 mm groove, 0.4 mm bump, 0.6 mm window chamfer
  plan(board('rpi-pico-w'), {}, (enc) => {
    const hk = feature(enc, 'snap_hooks');
    assert.ok(Math.abs(hk.groove - 0.7) < 1e-6 && hk.overhang === 0.4, JSON.stringify(hk));
    assert.ok(Math.abs(wallAtHooks(enc) - 1.31) < 0.02, String(wallAtHooks(enc)));
    assert.equal(feature(enc, 'port_window', 'usb').chamfer, 0.6);
  });
  // a wall too thin for any catch says so in lid_fit instead of passing silently
  plan(board('rpi-pico-w'), { wall: 1.0 }, (enc) => {
    const w = enc.report.features.find((f: any) => f.type === 'warning');
    assert.match(w?.text ?? '', /1 mm wall leaves the snap hooks a 0\.00 mm catch: use a wall of 1\.2 mm or more/);
  });
  const thinCase = CASE.replace('wall: { value: 2.0, min: 1.2', 'wall: { value: 2.0, min: 0.8'); // the param range stops at 1.2
  const lid = find(engine.inspect({ source: thinCase, inputs: inputs(board('rpi-pico-w')), params: { wall: 1.0 }, ops: [{ op: 'enclosure' }] }).results[0], 'lid_fit');
  assert.ok(lid.severity === 'warn' && /0\.00 mm catch/.test(lid.msg), JSON.stringify(lid));
});

test('regression 8: a port window reaches past the receptacle mouth, so a plug taller than the room under the lid gets in at any clear', () => {
  // the Zero 2 W's 8 mm mini-HDMI plug stands 1.2 mm above the lid underside, and the hook band puts its -y wall about
  // 1.9 mm + clear off the board: a window cut 2 mm past the inner wall face left a lid sliver in the plug's path from
  // clear 0.7 (HDMI) and 1.2 (the micro-USBs) on (elec_clear*.test.ts sweeps every board)
  for (const clear of [0.7, 1.2, 2.0]) {
    const c = check(board('rpi-zero-2-w'), { clear });
    assert.deepEqual(errors(c), [], `clear ${clear}`);
    for (const id of ['hdmi', 'usb', 'pwr']) assert.ok(find(c, 'port_clear', id) && c.clearance[id] >= 0.285, `${id} at clear ${clear}: ${c.clearance[id]}`);
  }
  plan(board('rpi-zero-2-w'), { clear: 2.0 }, (enc) => {
    const f = feature(enc, 'port_window', 'hdmi');
    const [x, y, z] = enc.at(enc.board.comps.find((p: any) => p.id === 'hdmi').mouth);
    // the plug body enters from the outer wall face to the mouth (y = -0.5)
    assert.ok(Math.abs(f.plugReachMm - (enc.wall - enc.inner.y0 + y)) < 0.01, JSON.stringify(f));
    // the lid's notch over it runs the port fit (0.3 mm) past the mouth into the case, and no farther
    const lidAt = (dy: number) => enc.lid.rayCast([x, y + dy, enc.zTop - 1], [x, y + dy, z + f.h / 2 - 0.05]).length;
    assert.equal(lidAt(0.2), 0);
    assert.ok(lidAt(0.5) > 0);
  });
  // a receptacle set back from the board edge takes the plug that much farther in (the carrier's J1: protrude -0.02 on -y)
  plan(carrier, {}, (enc) => {
    const f = feature(enc, 'port_window', 'J1');
    assert.ok(Math.abs(f.plugReachMm - (enc.wall - enc.inner.y0 + 0.02)) < 0.01, JSON.stringify(f));
  });
});

test('regression 9: a press tongue as thick as a 2.6 mm lid or more is lengthened, so the button stays reachable', () => {
  // strain = 1.5 * lid * (gap + travel) / L^2: a fixed 10 mm tongue bent 2.15 % at lid 2.6 and 2.48 % at lid 3.0
  // (button_unreachable on every board with a top button); elec_lid.test.ts sweeps the whole lid range
  plan(board('rpi-pico-w'), {}, (enc) => {
    const f = feature(enc, 'flex_button', 'bootsel');
    assert.ok(f.len === 10 && f.strain === 0.0132, JSON.stringify(f)); // the default 1.6 mm lid is untouched
  });
  plan(board('rpi-pico-w'), { lid: 3.0 }, (enc) => {
    const f = feature(enc, 'flex_button', 'bootsel');
    assert.ok(f.len === 11.8 && f.strain === 0.0178 && f.clearOfPosts, JSON.stringify(f));
  });
  // the gap it is sized for is the plunger gap asked for: 0.7 mm at the default lid takes 11.3 mm (2.28 % at 10 mm)
  plan(board('rpi-pico-w'), { pressGap: 0.7 }, (enc) => assert.equal(feature(enc, 'flex_button', 'bootsel').len, 11.3));
  // a tabLen in the program is kept as it is
  plan(board('rpi-pico-w'), { lid: 3.0, tabLen: 14 }, (enc) => {
    const f = feature(enc, 'flex_button', 'bootsel');
    assert.ok(f.len === 14 && f.strain === 0.0126, JSON.stringify(f));
  });
  const btn = find(engine.inspect({ source: CASE.replace('standoff: p.standoff,', 'standoff: p.standoff, lid: 3.0,'), inputs: inputs(board('rpi-pico-w')), ops: [{ op: 'enclosure' }] }).results[0], 'button_reach', 'bootsel');
  assert.ok(btn?.severity === 'info' && /tongue 11\.8 mm free, bending strain 1\.78 %/.test(btn.msg), JSON.stringify(btn));
  // the Nano's +y tongue would reach a snap hook's root from lid 2.6 on: it turns where there is room
  plan(board('arduino-nano'), { lid: 3.0 }, (enc) => {
    const f = feature(enc, 'flex_button', 'btn_reset');
    assert.ok(f.len === 11.8 && f.clearOfPosts && f.dir[1] === 'x', JSON.stringify(f));
  });
});

test('regression 10: a lid skin under two layers over a port window is opened through the lid top', () => {
  // ray straight down through the lid, from above it to just under the window top, at the window's middle and near its
  // sides, from the outer wall face to the receptacle mouth
  const lidOver = (enc: any, id: string) => {
    const f = feature(enc, 'port_window', id), c = enc.board.comps.find((p: any) => p.id === id);
    const [mx, my, mz] = enc.at(c.mouth), top = mz + f.h / 2, onX = f.edge[1] === 'x', sg = f.edge[0] === '+' ? 1 : -1;
    const face = (onX ? (sg > 0 ? enc.inner.x1 : enc.inner.x0) : sg > 0 ? enc.inner.y1 : enc.inner.y0) + sg * enc.wall;
    let hits = 0;
    for (const d of [0.7, enc.wall, Math.abs(face - (onX ? mx : my))]) // into the case from the outer face
      for (const s of [0, -1, 1].map((k) => k * (f.w / 2 - f.r - 0.05))) {
        const p = onX ? [face - sg * d, my + s] : [mx + s, face - sg * d];
        hits += enc.lid.rayCast([p[0], p[1], enc.zTop + enc.lidT + 1], [p[0], p[1], top - 0.05]).length;
      }
    return { f, hits };
  };
  // the Zero 2 W's mini-HDMI left 0.10 mm, the DevKitC's micro-USB 0.35 mm
  plan(board('rpi-zero-2-w'), {}, (enc) => {
    const { f, hits } = lidOver(enc, 'hdmi');
    assert.ok(f.openedSkin === 0.1 && hits === 0, JSON.stringify({ f, hits }));
    for (const id of ['usb', 'pwr']) assert.equal(feature(enc, 'port_window', id).openedSkin, undefined, id); // 0.60 mm stays
  });
  plan(board('esp32-devkitc-v4'), {}, (enc) => {
    const { f, hits } = lidOver(enc, 'usb');
    assert.ok(f.openedSkin === 0.35 && hits === 0, JSON.stringify({ f, hits }));
  });
  // two layers or more stay a lid over the window: the Nano's 0.45 mm
  plan(board('arduino-nano'), {}, (enc) => {
    const { f, hits } = lidOver(enc, 'usb');
    assert.ok(f.openedSkin === undefined && hits > 0, JSON.stringify({ f, hits }));
  });
  // the Pico W's window ends at the lid top at the default lid and is left as it was (USB 0.29 mm in its own test);
  // under a 1.8 mm lid it leaves 0.20 mm and opens
  plan(board('rpi-pico-w'), {}, (enc) => assert.equal(feature(enc, 'port_window', 'usb').openedSkin, undefined));
  plan(board('rpi-pico-w'), { lid: 1.8 }, (enc) => {
    const { f, hits } = lidOver(enc, 'usb');
    assert.ok(f.openedSkin === 0.2 && hits === 0, JSON.stringify({ f, hits }));
  });
  // the opened windows still fit their plugs by the port fit, and the cases pass
  for (const id of ['rpi-zero-2-w', 'esp32-devkitc-v4']) {
    const c = check(board(id));
    assert.deepEqual(errors(c), [], id);
    for (const p of board(id).components.filter((p) => p.access === 'port')) assert.ok(c.clearance[p.id] >= 0.285, `${id}.${p.id}: ${c.clearance[p.id]}`);
  }
});

// ---------------------------------------------------------------- boards without mount holes
test('boards without mount holes sit on ledges under edge clips from the lid, and the check says how they are held', () => {
  for (const id of ['xiao-esp32c3', 'xiao-esp32s3', 'esp32-devkitc-v4']) {
    const spec = board(id);
    const c = check(spec);
    assert.deepEqual(errors(c), [], id);
    plan(spec, {}, (enc) => {
      const clips = enc.report.features.filter((f: any) => f.type === 'clip');
      assert.ok(clips.length >= 4, `${id}: ${clips.length} clips`);
      assert.equal(enc.clips.length, clips.length);
      // on both long sides with a fence (the hook band leaves room), at the ends a plain lip
      const long = enc.board.H >= enc.board.W ? ['-x', '+x'] : ['-y', '+y'];
      for (const e of long) assert.ok(clips.some((f: any) => f.edge === e && f.fence >= 1), `${id}: fence on ${e}`);
      for (const f of clips) {
        assert.ok(f.lip >= 0.6 && f.lip <= 1, JSON.stringify(f));
        // every press point on the PCB and off every part on it
        for (const [x, y] of f.press) {
          assert.ok(x > 0 && x < enc.board.W && y > 0 && y < enc.board.H, JSON.stringify(f));
          const near = (p: any) => p.side !== 'bottom' && x > p.box.min[0] - 0.3 && x < p.box.max[0] + 0.3 && y > p.box.min[1] - 0.3 && y < p.box.max[1] + 0.3;
          assert.ok(!enc.board.comps.some(near), `${id}: ${JSON.stringify(f)}`);
        }
      }
      const seated = find(c, 'pcb_seated'), held = find(c, 'board_retained');
      assert.equal(seated.severity, 'info', seated.msg);
      assert.equal(held.severity, 'info', held.msg);
      assert.equal(held.value, clips.length, held.msg);
      const [, x, y] = held.msg.match(/slides ([\d.]+) mm along x and ([\d.]+) mm along y/);
      assert.ok(+x <= 1.2 && +y <= 1.2, held.msg);
    });
  }
  // the XIAO: the fences keep it within 0.25 mm of its place across, the end walls within the 0.5 mm clear
  assert.match(find(check(board('xiao-esp32c3')), 'board_retained').msg, /slides 0\.50 mm along x and 1\.00 mm along y/);
});

test('board_retained warns when a holeless board is not held: no clips, too much clear, or a case for a wider board', () => {
  const run = (params: Record<string, string | number | boolean>) =>
    engine.inspect({ source: CASE_CLIPS, inputs: inputs(board('xiao-esp32c3')), params, ops: [{ op: 'enclosure' }] }).results[0] as any;
  const none = run({ clips: 'none' });
  assert.equal(find(none, 'board_retained').severity, 'warn');
  assert.match(find(none, 'board_retained').msg, /nothing holds it down/);
  assert.match(find(none, 'pcb_seated').msg, /no holes and no edge clips/);
  // 1 mm clear leaves no room for a fence at the ends: it slides 2 mm along y
  const wide = find(run({ clear: 1.0 }), 'board_retained');
  assert.equal(wide.severity, 'warn');
  assert.match(wide.msg, /slides [\d.]+ mm along x and 2\.00 mm along y/);
  // the clips of a case built for the real XIAO press on air over a board 1.5 mm narrower
  const narrow = board('xiao-esp32c3');
  narrow.pcb.outline.w -= 1.5;
  const out = buildProgram(wasm, engine.evaluator, engine.compile(CASE), { layout: 'assembled', show_board: true }, { printer: DEFAULT_PRINTER, inputs: inputs(board('xiao-esp32c3')) });
  try {
    assert.equal(find(checkEnclosure(wasm, out.parts, narrow), 'board_retained').value, find(check(board('xiao-esp32c3')), 'board_retained').value - 1);
  } finally {
    disposeBuild(out);
  }
});

test('a board tips up about a line with every hold-down on one side and every support on the other', () => {
  const ledges: [number, number][] = [[1, 1], [9, 1], [1, 29], [9, 29]]; // a 10 x 30 board on two end ledges
  assert.equal(canTip([], ledges), true); // nothing over it: it lifts off
  assert.equal(canTip([[0.4, 15], [9.6, 15]], ledges), false); // clips mid-way on both long sides
  assert.equal(canTip([[0.4, 3], [9.6, 3]], [[1, 1], [9, 1]]), true); // held and supported at one end only: it pivots, the far end drops
  assert.equal(canTip([[0.4, 3], [0.4, 27]], ledges), true); // held along one long side only: the other side lifts
  assert.equal(canTip([[5, 15]], [[5, 15]]), true); // all in one spot: it spins about it
});
