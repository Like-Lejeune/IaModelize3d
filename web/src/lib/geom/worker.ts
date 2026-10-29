// Browser geometry worker: compiles and builds agent-written programs locally so
// sliders and handles update at interactive rates. Network APIs are removed before
// any program runs; the main thread kills this worker if a build hangs.
//
// Protocol (one reply per request id, a `done` flag on the last one):
//   inputs  {key, inputs}       stored once, builds refer to them by key
//   build   {..., quality, analyze, heat, edges}
//           -> {kind:'display'} viewer buffers (+ fast checks); with analyze 'full'
//              the full mini-slicer report follows as {kind:'checks'}
//   export  {..., format}       -> {bytes, mime}
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
  type DisplayBuffers,
} from '@formwright/geom';

type Common = { id: number; source: string; params?: Record<string, any>; inputsKey?: string; printer?: any };
type Req =
  | { id: number; type: 'inputs'; key: string; inputs: any }
  | (Common & { type: 'build'; quality: 'preview' | 'final'; analyze: 'none' | 'fast' | 'full'; heat: boolean; edges: boolean; vaseMode?: boolean })
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
type Cached = { head: Record<string, any>; display: DisplayBuffers; checks?: any; bytes: number };
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
    const { wasm, engine } = await ready;
    const inp = msg.inputsKey ? inputs.get(msg.inputsKey) : undefined;
    if (msg.type === 'export') {
      const out = engine.export({ source: msg.source, params: msg.params, inputs: inp, format: msg.format, title: msg.title });
      const bytes = fromBase64(out.data);
      post({ id: msg.id, ok: true, done: true, bytes, mime: out.mime }, [bytes.buffer as ArrayBuffer]);
      return;
    }
    const key = [msg.quality, msg.analyze, msg.heat, msg.edges, msg.vaseMode, hashString(msg.source), JSON.stringify(msg.params ?? {}), msg.inputsKey, JSON.stringify(msg.printer ?? {})].join('|');
    const hit = memo.get(key);
    if (hit) {
      memo.delete(key);
      memo.set(key, hit);
      const full = msg.analyze === 'full';
      sendDisplay(msg.id, hit.head, copy(hit.display), !full, performance.now() - t0);
      if (full) post({ id: msg.id, ok: true, kind: 'checks', done: true, checks: hit.checks, ms: performance.now() - t0 });
      return;
    }
    const program = engine.compile(msg.source);
    const printer = { ...DEFAULT_PRINTER, ...(msg.printer ?? {}) };
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
          return { name: p.name, role: p.role, color: p.color, settings: p.settings, bbox: { min: [...b.min], max: [...b.max] }, volume: p.solid.volume() };
        }),
        checks: fast,
      };
      const cached: Cached = { head, display: copy(display), bytes: display.position.byteLength * 1.5 + display.edges.byteLength };
      const full = msg.analyze === 'full';
      sendDisplay(msg.id, head, display, !full, performance.now() - t0);
      if (full) {
        const { heat: _h, ...checks } = analyze(wasm, out.body, printer, { level: 'full', vaseMode: msg.vaseMode });
        cached.checks = checks;
        post({ id: msg.id, ok: true, kind: 'checks', done: true, checks, ms: performance.now() - t0 });
      }
      remember(key, cached);
    } finally {
      disposeBuild(out);
    }
  } catch (e: any) {
    post({ id: msg.id, ok: false, done: true, stage: e?.stage ?? 'runtime', message: String(e?.message ?? e) });
  }
};
