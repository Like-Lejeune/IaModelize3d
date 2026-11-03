// PCB worker: JSON lines on stdin -> JSON lines on stdout, the same protocol as packages/geom (id, result | error
// {stage, message, hint}, ms). While a build routes it also writes {id, frame} lines for the live animation.
// The server starts the bundle (dist/pcb-worker.mjs) with the Node permission model and read access to dist/ only:
// no file writes, no child processes, no worker threads, no addons (server/formwright/pcb.py). The permission model
// does not cover the network, so it is cut here, before any tscircuit code loads: a circuit that reaches for
// jlcpcb:/kicad: footprints or the parts engine fails loudly instead of quietly going online. A circuit that escapes
// its vm realm (React is a host object) still lands in this process, hence both layers.
import readline from 'node:readline';

function severNetwork() {
  // a plain function, so `new dgram.Socket()` throws this too rather than "not a constructor"
  const die = (what) => function () { throw new Error(`network is disabled in the PCB sandbox (${what}); use offline footprint strings`); };
  const mod = (name) => { try { return process.getBuiltinModule(name); } catch { return null; } };
  const outbound = {
    net: ['connect', 'createConnection', 'createServer'],
    tls: ['connect', 'createServer'],
    http: ['request', 'get', 'createServer'],
    https: ['request', 'get', 'createServer'],
    http2: ['connect', 'createServer', 'createSecureServer'],
    dgram: ['createSocket'],
    dns: ['lookup', 'resolve', 'resolve4', 'resolve6', 'Resolver'],
    'dns/promises': ['lookup', 'resolve', 'Resolver'],
    inspector: ['open', 'url', 'console'],
    child_process: ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork'],
    worker_threads: ['Worker'],
  };
  for (const [name, fns] of Object.entries(outbound)) {
    const m = mod(name);
    if (!m) continue;
    for (const fn of fns) if (fn in m) try { m[fn] = die(`${name}.${fn}`); } catch { /* frozen */ }
  }
  for (const [name, cls, fns] of [['net', 'Socket', ['connect']], ['tls', 'TLSSocket', ['connect']], ['net', 'Server', ['listen']],
    ['dgram', 'Socket', ['connect', 'bind', 'send']]]) {
    const C = mod(name)?.[cls];
    for (const fn of fns) if (C?.prototype && fn in C.prototype) try { C.prototype[fn] = die(`${name}.${cls}.${fn}`); } catch { /* frozen */ }
  }
  // UDP and DNS carry no stdio, so every function they export goes: `new dgram.Socket()` with its own lookup never calls
  // createSocket, and resolveTxt/reverse/resolveMx query the network as well as lookup does
  for (const name of ['dgram', 'dns', 'dns/promises']) {
    const m = mod(name);
    if (m) for (const fn of Object.keys(m)) if (typeof m[fn] === 'function') try { m[fn] = die(`${name}.${fn}`); } catch { /* frozen */ }
  }
  try { mod('module')?.syncBuiltinESMExports(); } catch { /* older node */ }
  // synchronous throws, so a circuit's top-level call fails right there instead of as an unhandled rejection
  globalThis.fetch = (u) => die(`fetch ${String(u).slice(0, 80)}`)();
  globalThis.XMLHttpRequest = function XMLHttpRequest() { die('XMLHttpRequest')(); };
  globalThis.WebSocket = function WebSocket() { die('WebSocket')(); };
  globalThis.EventSource = function EventSource() { die('EventSource')(); };
  try {
    const orig = process.binding?.bind(process);
    if (orig) process.binding = (name) => { if (/^(tcp_wrap|udp_wrap|tls_wrap|http2)$/.test(String(name))) throw new Error('network binding disabled'); return orig(name); };
  } catch { /* no process.binding */ }
}

severNetwork();
// stdout carries the protocol; tscircuit logs freely (stack traces of async effects), so all of it goes to stderr
for (const k of ['log', 'info', 'debug', 'warn', 'trace']) console[k] = (...a) => process.stderr.write(a.map(String).join(' ').slice(0, 4000) + '\n');
process.on('unhandledRejection', (e) => process.stderr.write(`unhandled rejection: ${String(e?.stack ?? e).slice(0, 2000)}\n`));

const { buildCircuit, StageError } = await import('./build.mjs');
const { boardFromCircuit } = await import('./board.mjs');
const { digest, hintFor } = await import('./hints.mjs');
const { netsOf, countsOf, checkIntent, checkLimits } = await import('./intent.mjs');
const { gerberZip, bomCsv, cplCsv } = await import('./fab.mjs');
const { previews } = await import('./preview.mjs');
const { runAllChecks } = await import('@tscircuit/checks');
const { tidyTraces } = await import('./tidy.mjs');

const write = (o) => process.stdout.write(JSON.stringify(o) + '\n');
const b64 = (u8) => ({ b64: Buffer.from(u8).toString('base64') });

// tscircuit starts every pcbPath on the top layer; a hand trace that leaves a through-hole pad on the bottom (both its
// ends there) is listed in meta.hand_bottom: its first run moves to the bottom, and what the render said about that
// copper goes (the checks after this run on the real layers)
function handBottom(json, names) {
  if (!Array.isArray(names) || !names.length) return;
  const want = new Set(names);
  const display = new Map(json.filter((e) => e.type === 'source_trace').map((e) => [e.source_trace_id, e.display_name]));
  const moved = new Set();
  for (const t of json) {
    if (t.type !== 'pcb_trace' || /^source_/.test(t.pcb_trace_id ?? '') || !want.has(display.get(t.source_trace_id))) continue;
    for (const p of t.route) {
      if (p.route_type === 'via') break;
      p.layer = 'bottom';
    }
    moved.add(display.get(t.source_trace_id));
  }
  for (let i = json.length - 1; i >= 0; i--) {
    const e = json[i];
    if (/_error$/.test(e.type ?? '') && [...moved].some((n) => String(e.message ?? '').includes(n))) json.splice(i, 1);
  }
}

async function build(params, id) {
  const t0 = performance.now();
  const { json, meta, frames, ms } = await buildCircuit(String(params.source ?? ''), {
    timeoutMs: params.timeoutMs ?? 80000,
    onFrame: params.frames === false ? undefined : (frame) => write({ id, frame }),
    lcsc: params.lcsc ?? {},
  });
  const t1 = performance.now();
  handBottom(json, meta.hand_bottom);
  let drc = [];
  let tidy = null;
  try {
    // straight runs and 45° corners where the checks allow them (tidy.mjs); its last check is the board's DRC
    if (params.tidy !== false && json.some((e) => e.type === 'pcb_trace')) {
      tidy = await tidyTraces(json, (cj) => runAllChecks(cj));
      drc = tidy.drc;
    } else drc = await runAllChecks(json);
  } catch (e) { drc = [{ type: 'drc_crash_warning', message: String(e?.message ?? e).slice(0, 300) }]; }
  ms.drc = Math.round(performance.now() - t1);
  const nets = netsOf(json);
  const { errors, warnings, suppressed, quiet } = digest(json, drc, nets);
  const counts = countsOf(json, nets);
  let board = null;
  try {
    board = boardFromCircuit(json, { id: params.board_id ?? 'pcb', name: params.name ?? meta.title ?? 'PCB', lcsc: params.lcsc ?? {} });
  } catch (e) {
    warnings.push({ type: 'board_json_warning', message: `no board description: ${String(e?.message ?? e).slice(0, 300)}` });
  }
  const intent = checkIntent(json, board, nets, counts, params.intent ?? meta.intent ?? null);
  const limits = checkLimits(json, counts);
  return {
    ok: errors.length === 0, errors, warnings, suppressed, quiet, counts, board, intent, limits, frames, meta,
    nets: nets.nets.map((n) => ({ ports: n.ports, ...(n.names.length ? { names: n.names } : {}) })),
    circuit_json: json, ms: Math.round(performance.now() - t0), timings: ms,
    ...(tidy ? { tidy: { tidied: tidy.tidied, reverted: tidy.reverted, segments: tidy.segments } } : {}),
  };
}

async function exportFab(params) {
  const t0 = performance.now();
  const cj = params.circuit_json;
  if (!Array.isArray(cj)) throw new StageError('protocol', 'export needs circuit_json');
  const { zip, layers } = gerberZip(cj, params.base ?? 'board');
  const bom = await bomCsv(cj);
  const cpl = cplCsv(cj);
  const pv = await previews(cj);
  const files = { 'gerbers.zip': b64(zip), 'bom.csv': bom.csv, 'cpl.csv': cpl.csv };
  for (const [k, v] of Object.entries(pv.files)) files[k] = typeof v === 'string' ? v : b64(v);
  return {
    files, layers, svg_map: pv.svg_map, glb_map: pv.glb_map, bom_lines: bom.lines, cpl_lines: cpl.lines, lcsc_verified: false, rotation_checked: cpl.rotation_checked,
    ...(pv.glb_error ? { glb_error: pv.glb_error } : {}), ms: Math.round(performance.now() - t0), timings: pv.ms,
  };
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
write({ ready: true });
for await (const line of rl) {
  if (!line.trim()) continue;
  let msg;
  try { msg = JSON.parse(line); } catch { write({ id: null, error: { stage: 'protocol', message: 'bad json' } }); continue; }
  const t0 = Date.now();
  try {
    let result;
    if (msg.method === 'build') result = await build(msg.params ?? {}, msg.id);
    else if (msg.method === 'export') result = await exportFab(msg.params ?? {});
    else if (msg.method === 'ping') result = { pong: true };
    else throw new StageError('protocol', `unknown method ${msg.method}`);
    write({ id: msg.id, result, ms: Date.now() - t0 });
  } catch (e) {
    const message = String(e?.message ?? e).slice(0, 2000);
    const hint = e?.hint ?? hintFor(null, message);
    write({ id: msg.id, error: { stage: e?.stage ?? 'runtime', message, ...(hint ? { hint } : {}) }, ms: Date.now() - t0 });
  }
}
