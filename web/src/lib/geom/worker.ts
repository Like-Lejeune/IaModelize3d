// Browser geometry worker: compiles and builds agent-written programs locally so
// sliders and handles update at interactive rates. Network APIs are removed before
// any program runs; the main thread kills this worker if a build hangs.
//
// Protocol (one reply per request id, a `done` flag on the last one):
//   inputs    {key, inputs}       stored once, builds refer to them by key
//   build     {..., quality, analyze, heat, edges, enclosure?}
//             -> {kind:'display'} viewer buffers (+ fast checks); with analyze 'full'
//                the full mini-slicer report follows as {kind:'checks'}. A case program's
//                full build with enclosure {board, spec?} also checks the case against that
//                board (the assembled layout, checkEnclosure) and sends it with the report.
//   enclosure {..., board, spec?} -> {kind:'enclosure', enclosure}: that check alone
//   export    {..., format}       -> {bytes, mime}
// Parts carry their meta in the head; a board ghost (a 'reference' part from lib.elec) also gets
// `pose`, where the board's own frame sits in the build, found exactly as checkEnclosure finds it.
import wasmUrl from 'manifold-3d/manifold.wasm?url';
import {
  analyze,
  buildProgram,
  DEFAULT_PRINTER,
  disposeBuild,
  displayBuffers,
  displayTransfer,
  Engine,
  functionEvaluator,
  fromBase64,
  hashString,
  loadKernel,
  withArena,
  type DisplayBuffers,
  type Part,
  type Wasm,
} from '@formwright/geom';
import { checkEnclosure, type EnclosureCheck } from '@formwright/geom/enclosure.ts';
import { boardGhost, boardModel, type BoardSpec } from '@formwright/geom/lib/elec.ts';

type Common = { id: number; source: string; params?: Record<string, any>; inputsKey?: string; printer?: any };
/** Which board to check a case against: a name under inputs.boards, or a board the program carries itself (spec). */
type CaseBoard = { board: string; spec?: BoardSpec };
type Req =
  | { id: number; type: 'inputs'; key: string; inputs: any }
  | (Common & { type: 'build'; quality: 'preview' | 'final'; analyze: 'none' | 'fast' | 'full'; heat: boolean; edges: boolean; vaseMode?: boolean; enclosure?: CaseBoard })
  | (Common & CaseBoard & { type: 'enclosure' })
  | (Common & { type: 'export'; format: 'stl' | '3mf'; title?: string });

const ready = (async () => {
  const wasm = await loadKernel(() => wasmUrl);
  // Programs are untrusted: no network or storage from here on.
  for (const k of ['fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'importScripts', 'indexedDB', 'caches', 'BroadcastChannel']) {
    try {
      Object.defineProperty(self, k, { value: undefined, configurable: false, writable: false });
    } catch {
      /* not defined here */
    }
  }
  const engine = new Engine(wasm, functionEvaluator());
  engine.keepBuilds = 1;
  return { wasm, engine };
})();

const inputs = new Map<string, any>();

// Dragging a slider back and forth revisits the same values: keep the last results.
type Cached = { head: Record<string, any>; display: DisplayBuffers; checks?: any; enclosure?: any; bytes: number };
const memo = new Map<string, Cached>();
const MEMO_BYTES = 160e6;
let memoBytes = 0;

const copy = (d: DisplayBuffers): DisplayBuffers => ({ ...d, position: d.position.slice(), heat: d.heat.slice(), ghost: d.ghost.slice(), edges: d.edges.slice() });

function remember(key: string, c: Cached) {
  memo.set(key, c);
  memoBytes += c.bytes;
  while (memoBytes > MEMO_BYTES && memo.size > 1) {
    const [k, old] = memo.entries().next().value!;
    memo.delete(k);
    memoBytes -= old.bytes;
  }
}

const post = (msg: any, transfer: ArrayBuffer[] = []) => (self as any).postMessage(msg, transfer);

function sendDisplay(id: number, head: Record<string, any>, display: DisplayBuffers, done: boolean, ms: number) {
  post({ ...head, id, ok: true, kind: 'display', done, display, ms }, displayTransfer(display));
}

// ---- a case around its board
type V3 = [number, number, number];

/** The board spec a ghost was made from: the inputs board with its id, or the one the request brought along. */
function specOf(inp: any, id: unknown, extra?: BoardSpec): BoardSpec | null {
  const boards = Object.values((inp?.boards ?? {}) as Record<string, BoardSpec>);
  return boards.find((b) => b?.id === id) ?? (extra && extra.id === id ? extra : null);
}

// the ghost's own box depends on the board alone: once per spec object (inputs keep theirs between builds)
const ghostMins = new WeakMap<object, Map<boolean, V3>>();
function ghostMin(wasm: Wasm, spec: BoardSpec, bottomPins: boolean): V3 {
  let m = ghostMins.get(spec);
  if (!m) ghostMins.set(spec, (m = new Map()));
  let v = m.get(bottomPins);
  if (!v) {
    v = withArena(() => [...boardGhost(wasm, boardModel(wasm, spec), { bottomPins }).boundingBox().min] as V3);
    m.set(bottomPins, v);
  }
  return v;
}

/** Part meta as plain data (programs may put anything there), plus the pose of a board ghost. */
function metaOf(wasm: Wasm, p: Part, min: V3, inp: any, extra?: BoardSpec): Record<string, any> | undefined {
  if (!p.meta) return undefined;
  let meta: Record<string, any>;
  try {
    meta = JSON.parse(JSON.stringify(p.meta));
  } catch {
    return undefined;
  }
  if (p.role === 'reference' && meta.board) {
    const spec = specOf(inp, meta.board, extra);
    if (spec) {
      try {
        const own = ghostMin(wasm, spec, !!meta.bottomPins);
        meta.pose = [0, 1, 2].map((i) => +(min[i] - own[i]).toFixed(4));
      } catch {
        /* the viewer estimates the pose from the box */
      }
    }
  }
  return meta;
}

/** The three numbers the studio shows (agent/elec_tools.py summary): USB clearance, plunger gap, snap strain. */
function summary(check: EnclosureCheck, spec: BoardSpec) {
  const usb = spec.components.filter((c) => c.access === 'port' && String(c.type ?? '').startsWith('usb')).map((c) => c.id);
  const vals = usb.map((i) => check.clearance[i]).filter((v) => typeof v === 'number');
  const of = (code: string) => check.findings.filter((f) => f.code === code && typeof f.value === 'number').map((f) => f.value as number);
  const gaps = of('button_reach'), strains = of('snap_strain');
  return {
    usb_clearance_mm: vals.length ? Math.min(...vals) : null,
    button_gap_mm: gaps.length ? Math.min(...gaps) : null,
    snap_strain_pct: strains.length ? Math.max(...strains) : null,
  };
}

/**
 * check_enclosure in the browser: the case rebuilt closed around its board ghost and checked against the
 * board JSON, as the server's inspect op 'enclosure' does. Returns checks.enclosure (C5) without the version.
 */
function caseCheck(wasm: Wasm, engine: Engine, msg: Common & CaseBoard, inp: any, printer: any) {
  const t0 = performance.now();
  const spec = (inp?.boards?.[msg.board] as BoardSpec | undefined) ?? msg.spec;
  if (!spec) {
    const known = Object.keys(inp?.boards ?? {});
    return { error: `no board JSON at inputs.boards.${msg.board}${known.length ? `; boards: ${known.join(', ')}` : ''}`, board: msg.board };
  }
  const program = engine.compile(msg.source);
  const out = buildProgram(wasm, engine.evaluator, program, { ...(msg.params ?? {}), layout: 'assembled', show_board: true }, { printer, inputs: inp, quality: 'final' });
  try {
    const check = checkEnclosure(wasm, out.parts, spec);
    return {
      op: 'enclosure', board: msg.board, ...check, ms: Math.round(performance.now() - t0),
      ok: !check.findings.some((f) => f.severity === 'error'), summary: summary(check, spec),
    };
  } finally {
    disposeBuild(out);
  }
}

self.onmessage = async (ev: MessageEvent<Req>) => {
  const msg = ev.data;
  const t0 = performance.now();
  try {
    if (msg.type === 'inputs') {
      inputs.set(msg.key, msg.inputs);
      // only the newest inputs are ever asked for again
      for (const k of [...inputs.keys()]) if (k !== msg.key) inputs.delete(k);
      memo.clear();
      memoBytes = 0;
      post({ id: msg.id, ok: true, done: true });
      return;
    }
    const { wasm, engine } = await ready.catch((e) => {
      // a kernel that failed to load stays failed in this worker: the main thread replaces it
      throw Object.assign(new Error(`geometry engine failed to load: ${e?.message ?? e}`), { fatal: true });
    });
    const inp = msg.inputsKey ? inputs.get(msg.inputsKey) : undefined;
    const printer = { ...DEFAULT_PRINTER, ...(msg.printer ?? {}) };
    if (msg.type === 'export') {
      const out = engine.export({ source: msg.source, params: msg.params, inputs: inp, format: msg.format, title: msg.title });
      const bytes = fromBase64(out.data);
      post({ id: msg.id, ok: true, done: true, bytes, mime: out.mime }, [bytes.buffer as ArrayBuffer]);
      return;
    }
    if (msg.type === 'enclosure') {
      post({ id: msg.id, ok: true, done: true, kind: 'enclosure', enclosure: caseCheck(wasm, engine, msg, inp, printer), ms: performance.now() - t0 });
      return;
    }
    const enc = msg.analyze === 'full' ? msg.enclosure : undefined;
    const encKey = enc ? `${enc.board}:${enc.spec ? hashString(JSON.stringify(enc.spec)) : ''}` : '';
    const key = [msg.quality, msg.analyze, msg.heat, msg.edges, msg.vaseMode, hashString(msg.source), JSON.stringify(msg.params ?? {}), msg.inputsKey, JSON.stringify(msg.printer ?? {}), encKey].join('|');
    const hit = memo.get(key);
    if (hit) {
      memo.delete(key);
      memo.set(key, hit);
      const full = msg.analyze === 'full';
      sendDisplay(msg.id, hit.head, copy(hit.display), !full, performance.now() - t0);
      if (full) post({ id: msg.id, ok: true, kind: 'checks', done: true, checks: hit.checks, ...(enc ? { enclosure: hit.enclosure } : {}), ms: performance.now() - t0 });
      return;
    }
    const program = engine.compile(msg.source);
    const out = buildProgram(wasm, engine.evaluator, program, msg.params ?? {}, { printer, inputs: inp, quality: msg.quality });
    try {
      const fast = msg.analyze === 'none' ? undefined : (({ heat: _h, ...rest }) => rest)(analyze(wasm, out.body, printer, { level: 'fast', vaseMode: msg.vaseMode }));
      const display = displayBuffers(out.parts, printer, { heat: msg.heat, edges: msg.edges });
      const head = {
        meta: program.meta,
        paramSpecs: program.params,
        params: out.params,
        handles: out.handles,
        quality: msg.quality,
        parts: out.parts.map((p) => {
          const b = p.solid.boundingBox();
          const meta = metaOf(wasm, p, [...b.min] as V3, inp, enc?.spec);
          return { name: p.name, role: p.role, color: p.color, settings: p.settings, bbox: { min: [...b.min], max: [...b.max] }, volume: p.solid.volume(), ...(meta ? { meta } : {}) };
        }),
        checks: fast,
      };
      const cached: Cached = { head, display: copy(display), bytes: display.position.byteLength * 1.5 + display.edges.byteLength };
      const full = msg.analyze === 'full';
      sendDisplay(msg.id, head, display, !full, performance.now() - t0);
      if (full) {
        const { heat: _h, ...checks } = analyze(wasm, out.body, printer, { level: 'full', vaseMode: msg.vaseMode });
        cached.checks = checks;
        if (enc) {
          // a failed assembled build is no reason to lose the printability report
          try {
            cached.enclosure = caseCheck(wasm, engine, { ...msg, ...enc }, inp, printer);
          } catch (e: any) {
            cached.enclosure = { error: `${e?.stage ?? 'runtime'}: ${String(e?.message ?? e)}`, board: enc.board };
          }
        }
        post({ id: msg.id, ok: true, kind: 'checks', done: true, checks, ...(enc ? { enclosure: cached.enclosure } : {}), ms: performance.now() - t0 });
      }
      remember(key, cached);
    } finally {
      disposeBuild(out);
    }
  } catch (e: any) {
    post({ id: msg.id, ok: false, done: true, stage: e?.stage ?? 'runtime', message: String(e?.message ?? e), fatal: !!e?.fatal });
  }
};
