// node --test test/  (from packages/pcb). Drives the worker the way the server does: JSON lines over stdio.
// xiao_carrier.tsx is the home page's PCB example: XIAO ESP32-C3 on headers, USB-C input, LED, button, I2C header.
// carrier.tsx is the designer's reference board (pcb_prompt.EXAMPLE): a Raspberry Pi Pico carrier, a different board.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';
import { unzipSync } from 'fflate';
import Ajv from 'ajv/dist/2020.js';
import { hintFor } from '../src/hints.mjs';

const PKG = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const XIAO = fs.readFileSync(path.join(PKG, 'test', 'fixtures', 'xiao_carrier.tsx'), 'utf8');
const PICO = fs.readFileSync(path.join(PKG, 'test', 'fixtures', 'carrier.tsx'), 'utf8');
const SCHEMA = JSON.parse(fs.readFileSync(path.join(PKG, '..', 'geom', 'src', 'board.schema.json'), 'utf8'));
const md5 = (s) => crypto.createHash('md5').update(s).digest('hex');

function worker(script, { sandbox = null } = {}) {
  const args = sandbox ? ['--permission', `--allow-fs-read=${sandbox}`, '--max-old-space-size=1536', script] : [script];
  const proc = spawn(process.execPath, args, { cwd: path.dirname(script), env: { PATH: process.env.PATH, SYSTEMROOT: process.env.SYSTEMROOT ?? '' } });
  proc.stderr.resume(); // tscircuit logs freely; an unread pipe would stall the worker
  const rl = readline.createInterface({ input: proc.stdout });
  const waiting = new Map();
  const frames = [];
  let ready;
  const started = new Promise((r) => { ready = r; });
  rl.on('line', (line) => {
    const m = JSON.parse(line);
    if (m.ready) return ready();
    if (m.frame) return frames.push(m.frame);
    waiting.get(m.id)?.(m);
  });
  let ids = 0;
  const call = async (method, params) => {
    await started;
    const id = ++ids;
    return new Promise((res) => { waiting.set(id, res); proc.stdin.write(JSON.stringify({ id, method, params }) + '\n'); });
  };
  return { call, frames, close: () => proc.kill() };
}

const ports = (board) => board.components.filter((c) => c.access === 'port').map((c) => `${c.id}:${c.edge}`).sort();

// the 5 V path as routed, per requested width: the narrowest wire segment over the width the circuit asked for
function powerWidths(cj) {
  const req = cj.filter((e) => e.type === 'source_trace' && e.min_trace_thickness);
  return req.map((s) => Math.min(...cj.filter((e) => e.type === 'pcb_trace' && e.source_trace_id === s.source_trace_id)
    .flatMap((t) => t.route.filter((p) => p.route_type === 'wire').map((p) => p.width))) / s.min_trace_thickness);
}

test('xiao carrier: routed with 0 errors and 0 warnings, fw.board/1 with 3 edge ports, intent kept, fab files for JLC', { timeout: 180000 }, async () => {
  const w = worker(path.join(PKG, 'src', 'worker.mjs'));
  try {
    const t0 = Date.now();
    const r = await w.call('build', { source: XIAO });
    assert.ok(!r.error, JSON.stringify(r.error));
    const b = r.result;
    assert.equal(b.ok, true, JSON.stringify(b.errors));
    assert.deepEqual(b.errors, []);
    // the home page card lists its engine notes next to DRC 0: there are none (button legs, power trace width)
    assert.deepEqual(b.warnings, []);
    const widths = powerWidths(b.circuit_json);
    assert.ok(widths.length === 2 && widths.every((k) => k >= 0.999), `power path width / requested: ${widths}`);
    assert.ok(b.counts.traces >= 20, `traces ${b.counts.traces}`);
    assert.equal(b.counts.components, 11);
    assert.ok(Date.now() - t0 < 60000);
    assert.ok(b.frames.length >= 1 && b.frames.length <= 24 && w.frames.length >= 1, 'routing frames');
    assert.ok(b.frames.at(-1).lines.every((l) => l.length === 4));

    const ajv = new Ajv({ allErrors: true, strict: false });
    const valid = ajv.compile(SCHEMA);
    assert.ok(valid(b.board), JSON.stringify(valid.errors));
    assert.deepEqual(ports(b.board), ['J1:-y', 'J2:+x', 'U1_usb:+y']);
    const own = b.board.components.find((c) => c.id === 'U1_usb');
    assert.equal(own.z0, 3.7); // the XIAO's own USB-C sits on the module, above the carrier
    assert.equal(b.board.pcb.holes.filter((h) => h.use === 'mount').length, 4);
    assert.equal(b.board.source.kind, 'pcb');
    assert.deepEqual(b.intent, { ok: true, issues: [], checked: 6 });
    assert.equal(b.limits.ok, true);

    const e = await w.call('export', { circuit_json: b.circuit_json });
    assert.ok(!e.error, JSON.stringify(e.error));
    const files = e.result.files;
    const zip = unzipSync(Buffer.from(files['gerbers.zip'].b64, 'base64'));
    const names = Object.keys(zip).sort();
    const protel = names.filter((n) => /\.(GTL|GBL|GTO|GBO|GTS|GBS|GTP|GBP|GKO)$/.test(n));
    assert.equal(protel.length, 9, names.join(' '));
    assert.deepEqual(names.filter((n) => /DRL$/.test(n)), ['board-NPTH.DRL', 'board.DRL']);
    assert.ok(!names.some((n) => /Fab/i.test(n)));
    assert.match(files['bom.csv'], /^Comment,Designator,Footprint,LCSC,lcsc_verified\n/);
    assert.match(files['bom.csv'], /5\.1k,"R1,R2",res0603,C23186,false/);
    assert.match(files['cpl.csv'], /^Designator,Mid X,Mid Y,Layer,Rotation\n/);
    assert.match(files['cpl.csv'], /\nJ2,19\.500mm,4\.000mm,Top,90\n/);
    assert.equal(Buffer.from(files['board.glb'].b64, 'base64').subarray(0, 4).toString(), 'glTF');
    assert.match(files['pcb_top.svg'], /^<svg/);
    assert.equal(e.result.svg_map['pcb_top.svg'].matrix.length, 6);
  } finally {
    w.close();
  }
});

test('reference board: a Pico carrier, 0 errors and 0 warnings, the Pico expanded as a module with its own USB port', { timeout: 180000 }, async () => {
  const w = worker(path.join(PKG, 'src', 'worker.mjs'));
  try {
    const r = await w.call('build', { source: PICO });
    assert.ok(!r.error, JSON.stringify(r.error));
    const b = r.result;
    assert.equal(b.ok, true, JSON.stringify(b.errors));
    assert.deepEqual(b.warnings, []);
    assert.deepEqual(b.intent, { ok: true, issues: [], checked: 6 });
    assert.equal(b.limits.ok, true);
    assert.ok(b.counts.traces >= 20 && b.counts.components === 11, JSON.stringify(b.counts));
    assert.ok(powerWidths(b.circuit_json).every((k) => k >= 0.999));
    const valid = new Ajv({ allErrors: true, strict: false }).compile(SCHEMA);
    assert.ok(valid(b.board), JSON.stringify(valid.errors));
    // not the home page's board: another module, other edges
    assert.deepEqual(ports(b.board), ['J1:+x', 'J2:-y', 'U1_usb:+y']);
    const own = Object.fromEntries(b.board.components.filter((c) => c.id.startsWith('U1')).map((c) => [c.id, c]));
    assert.equal(own.U1.type, 'rpi_pico');
    assert.equal(own.U1_usb.type, 'usb_micro_b');
    assert.equal(own.U1_usb.z0, 3.5); // its 1 mm PCB on 2.5 mm headers, the plug on top of it
    assert.equal(own.U1_bootsel.access, 'press');
    assert.equal(own.U1_led.access, 'light');
    // the module's aliases answer too
    const alias = (await w.call('build', { source: PICO.replace('gpio: { LED1: "GP15", SW1: "GP14" }', 'gpio: { LED1: "GPIO15", SW1: "U1.GPIO14" }') })).result;
    assert.deepEqual(alias.intent, { ok: true, issues: [], checked: 6 });
  } finally {
    w.close();
  }
});

test('hints: decoupling cap, overlap and intent violations come back as concrete moves', { timeout: 180000 }, async () => {
  const w = worker(path.join(PKG, 'src', 'worker.mjs'));
  try {
    // a 100nF cap from 3V3 to GND far from the module pins: tscircuit skips routing for the whole board
    const decoupling = XIAO.replace('{/* M3 mounting holes */}', '<capacitor name="C1" capacitance="100nF" footprint="0603" pcbX={-15} pcbY={5} />\n    <trace from=".C1 > .pin1" to=".U1 > .V3V3" />\n    <trace from=".C1 > .pin2" to="net.GND" />\n    {/* M3 mounting holes */}');
    let r = (await w.call('build', { source: decoupling })).result;
    assert.equal(r.ok, false);
    assert.equal(r.errors[0].type, 'pcb_autorouting_error');
    assert.match(r.errors[0].hint, /decoupling.*C1\.pin\d within 1 mm of U1\.(V3V3|GND)/);
    assert.ok(r.suppressed > 10, `cascade collapsed: ${r.suppressed}`);
    assert.ok(r.errors.length < 4);

    const overlap = XIAO.replace('pcbX={-6} pcbY={-7.5}', 'pcbX={-3} pcbY={-12}');
    r = (await w.call('build', { source: overlap })).result;
    const o = r.errors.find((x) => x.type === 'pcb_footprint_overlap_error');
    assert.ok(o, JSON.stringify(r.errors.map((x) => x.type)));
    assert.match(o.hint, /move R1 by [-+][\d.]+ mm in [xy] \(pcb[XY] -?[\d.]+ -> -?[\d.]+\)/);

    // DRC-clean but wrong: the "status" LED hangs on 3V3 and the I2C header sits inside the board
    const wrong = XIAO.replace('<trace from=".U1 > .MOSI" to=".R3 > .pin1" />', '<trace from=".U1 > .V3V3" to=".R3 > .pin1" />')
      .replace('pcbX={19.5} pcbY={4} pcbRotation={90}', 'pcbX={15.5} pcbY={6} pcbRotation={90}')
      .replace('pcbX={14.5} pcbY={5}', 'pcbX={10} pcbY={5}').replace('pcbX={14.5} pcbY={0}', 'pcbX={10} pcbY={0}');
    r = (await w.call('build', { source: wrong })).result;
    assert.equal(r.intent.ok, false);
    const codes = Object.fromEntries(r.intent.issues.map((i) => [i.ref, i]));
    assert.equal(codes.LED1?.code, 'intent_gpio_on_supply', JSON.stringify(r.intent));
    assert.equal(codes.J2?.code, 'intent_not_at_edge');
    assert.match(codes.J2.hint, /move J2 by \+[\d.]+ mm in x \(pcbX 15\.5 -> /);

    const kicad = XIAO.replace('footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23186"] }} pcbX={-6}', 'footprint="kicad:Resistor_SMD/R_0603_1608Metric" pcbX={-6}');
    r = (await w.call('build', { source: kicad })).result;
    assert.equal(r.errors[0].type, 'external_footprint_load_error');
    assert.match(r.errors[0].hint, /offline footprint strings/);

    // GPIO on pin1 and GND on pin2 routes clean and passes DRC, but those legs are one contact: the GPIO is shorted to GND,
    // whether the pairs are declared or not
    const tied = ' internallyConnectedPins={[["pin1", "pin2"], ["pin3", "pin4"]]}';
    assert.ok(XIAO.includes(tied));
    for (const short of [XIAO.replace('.SW1 > .pin3', '.SW1 > .pin2'), XIAO.replace('.SW1 > .pin3', '.SW1 > .pin2').replace(tied, '')]) {
      r = (await w.call('build', { source: short })).result;
      assert.equal(r.ok, false);
      const s = r.errors.find((x) => x.type === 'pcb_button_short_error');
      assert.ok(s, JSON.stringify(r.errors));
      assert.equal(s.ref, 'SW1');
      assert.match(s.message, /SW1 pin1 and pin2 are one contact .*U1\.D1 and GND are shorted/);
      assert.match(s.hint, /move GND from pin2 to pin3 .*<trace from="\.SW1 > \.pin3" to="net\.GND" \/>/);
      assert.ok(r.warnings.some((x) => x.type === 'source_pin_missing_trace_warning' && /internallyConnectedPins/.test(x.hint)));
    }

    const err = await w.call('build', { source: 'export default () => (<board width="10mm" height="10mm"><resistor name="R1" resistance="1k" footprint="0603" />' });
    assert.equal(err.error.stage, 'compile');
  } finally {
    w.close();
  }
});

test('warning hints: a squeezed power trace gets room, a style note is left alone, an open pin is wired', () => {
  assert.match(hintFor('pcb_trace_warning', 'Trace [.D1 > .cathode to .U1 > .V5] is routed thinner than requested (requested: 0.4mm, actual: 0.3mm).'), /move the parts beside its path/);
  assert.match(hintFor('pcb_trace_style_warning', '.LED1 > .cathode to net.GND has a 6.42 mm segment on top at 278.51°, 8.51° from the nearest allowed direction (270°). Prefer a multiple of 45° for segments longer than 5 mm (tolerance 4°).'), /^cosmetic/);
  assert.match(hintFor('source_pin_missing_trace_warning', 'Port pin2 on R7 is missing a trace'), /connect R7\.pin2/);
});

test('edge intent: a plain part at its edge passes; one inside still gets a move', { timeout: 120000 }, async () => {
  // a Pico placed as a plain dip40: no port rule, so it never becomes a port and only has to sit at the edge
  const pico = (y) => `export const meta = { intent: { edge: { U1: '+y' } } }
export default () => (<board width="30mm" height="60mm"><chip name="U1" footprint="dip40_w17.78mm" pcbX={0} pcbY={${y}} /></board>)`;
  const w = worker(path.join(PKG, 'src', 'worker.mjs'));
  try {
    let r = (await w.call('build', { source: pico(0) })).result;
    const away = r.intent.issues.find((i) => i.ref === 'U1');
    assert.equal(away?.code, 'intent_not_at_edge', JSON.stringify(r.intent));
    // the hint leaves the body 0.3 mm inside the edge; 0.2 mm further puts it 0.1 mm from it
    const to = Number(away.hint.match(/pcbY -?[\d.]+ -> (-?[\d.]+)/)[1]);
    for (const y of [to, to + 0.2]) {
      r = (await w.call('build', { source: pico(y) })).result;
      assert.equal(r.intent.ok, true, `pcbY ${y}: ${JSON.stringify(r.intent.issues)}`);
      assert.equal(r.intent.checked, 1);
    }
  } finally {
    w.close();
  }
});

test('bundle from an empty folder under --permission: same board, same circuit JSON, sandbox holds', { timeout: 240000 }, async () => {
  const dist = path.join(PKG, 'dist');
  if (!fs.existsSync(path.join(dist, 'pcb-worker.mjs'))) execFileSync(process.execPath, [path.join(PKG, 'scripts', 'bundle.mjs')], { stdio: 'inherit' });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fw-pcb-'));
  for (const f of fs.readdirSync(dist)) fs.copyFileSync(path.join(dist, f), path.join(dir, f));
  const a = worker(path.join(PKG, 'src', 'worker.mjs'));
  const b = worker(path.join(dir, 'pcb-worker.mjs'), { sandbox: dir });
  try {
    const [ra, rb] = [(await a.call('build', { source: XIAO })).result, (await b.call('build', { source: XIAO })).result];
    assert.ok(rb, 'bundled build');
    assert.deepEqual(rb.counts, ra.counts);
    assert.deepEqual(ports(rb.board), ports(ra.board));
    // two independent processes route the same board byte for byte
    assert.equal(md5(JSON.stringify(rb.circuit_json)), md5(JSON.stringify(ra.circuit_json)));
    const e = await b.call('export', { circuit_json: rb.circuit_json });
    assert.ok(!e.error, JSON.stringify(e.error));
    assert.ok(e.result.files['board.glb'], `GLB in the sandbox: ${e.result.glb_error}`);

    const escape = (body) => `const host = React.createElement.constructor('return globalThis')();\n${body}\nexport default () => (<board width="10mm" height="10mm" />)`;
    let r = await b.call('build', { source: escape("host.fetch('https://example.com')") });
    assert.match(r.error?.message ?? '', /network is disabled/);
    r = await b.call('build', { source: escape("host.process.getBuiltinModule('net').connect(80, 'example.com')") });
    assert.match(r.error?.message ?? '', /network is disabled/);
    r = await b.call('build', { source: escape(`host.process.getBuiltinModule('fs').readFileSync(${JSON.stringify(path.join(PKG, 'package.json'))})`) });
    assert.match(r.error?.message ?? '', /allow-fs-read|ERR_ACCESS_DENIED|restricted/i);
    r = await b.call('build', { source: escape(`host.process.getBuiltinModule('fs').writeFileSync(${JSON.stringify(path.join(dir, 'x.txt'))}, 'x')`) });
    assert.match(r.error?.message ?? '', /allow-fs-write|ERR_ACCESS_DENIED|restricted/i);
    assert.ok(!fs.existsSync(path.join(dir, 'x.txt')));
    r = await b.call('build', { source: 'while (true) {}\nexport default () => (<board width="10mm" height="10mm" />)' });
    assert.equal(r.error?.stage, 'timeout');
  } finally {
    a.close();
    b.close();
    setTimeout(() => fs.rmSync(dir, { recursive: true, force: true }), 500).unref();
  }
});
