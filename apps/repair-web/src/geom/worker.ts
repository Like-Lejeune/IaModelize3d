// Browser geometry worker for the studio: compiles and builds the agent's parametric programs locally, so a slider
// updates the model at interactive rates. Adapted from web/src/lib/geom/worker.ts (Formwright), without the
// electronics case check. Network APIs are removed before any program runs; the main thread kills this worker if a
// build hangs.
//
// Protocol (one reply per request id, `done` on the last one):
//   inputs {key, inputs}            stored once, builds refer to them by key
//   build  {..., quality, analyze}  -> {kind:'display'} viewer buffers (+ fast checks); with analyze 'full' the
//                                      printability report follows as {kind:'checks'}
//   export {..., format}            -> {bytes, mime}
import wasmUrl from "manifold-3d/manifold.wasm?url";
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
} from "@formwright/geom";

type Common = { id: number; source: string; params?: Record<string, any>; inputsKey?: string; printer?: any };
type Req =
  | { id: number; type: "inputs"; key: string; inputs: any }
  | (Common & { type: "build"; quality: "preview" | "final"; analyze: "none" | "fast" | "full"; heat: boolean; edges: boolean })
  | (Common & { type: "export"; format: "stl" | "3mf"; title?: string });

const ready = (async () => {
  const wasm = await loadKernel(() => wasmUrl);
  // programs are untrusted: no network or storage from here on
  for (const k of ["fetch", "XMLHttpRequest", "WebSocket", "EventSource", "importScripts", "indexedDB", "caches", "BroadcastChannel"]) {
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
const post = (msg: any, transfer: ArrayBuffer[] = []) => (self as any).postMessage(msg, transfer);

// dragging a slider back and forth revisits the same values: keep the last few results
const memo = new Map<string, { head: Record<string, any>; display: DisplayBuffers; checks?: any }>();
const copy = (d: DisplayBuffers): DisplayBuffers => ({ ...d, position: d.position.slice(), heat: d.heat.slice(), ghost: d.ghost.slice(), edges: d.edges.slice() });

self.onmessage = async (ev: MessageEvent<Req>) => {
  const msg = ev.data;
  const t0 = performance.now();
  try {
    if (msg.type === "inputs") {
      inputs.clear();
      inputs.set(msg.key, msg.inputs);
      memo.clear();
      post({ id: msg.id, ok: true, done: true });
      return;
    }
    const { wasm, engine } = await ready.catch((e) => {
      throw Object.assign(new Error(`geometry engine failed to load: ${e?.message ?? e}`), { fatal: true });
    });
    const inp = msg.inputsKey ? inputs.get(msg.inputsKey) : undefined;
    const printer = { ...DEFAULT_PRINTER, ...(msg.printer ?? {}) };
    if (msg.type === "export") {
      const out = engine.export({ source: msg.source, params: msg.params, inputs: inp, format: msg.format, title: msg.title });
      const bytes = fromBase64(out.data);
      post({ id: msg.id, ok: true, done: true, bytes, mime: out.mime }, [bytes.buffer as ArrayBuffer]);
      return;
    }
    const key = [msg.quality, msg.analyze, msg.heat, msg.edges, hashString(msg.source), JSON.stringify(msg.params ?? {}), msg.inputsKey].join("|");
    const hit = memo.get(key);
    if (hit) {
      const full = msg.analyze === "full";
      const display = copy(hit.display);
      post({ ...hit.head, id: msg.id, ok: true, kind: "display", done: !full, display, ms: performance.now() - t0 }, displayTransfer(display));
      if (full) post({ id: msg.id, ok: true, kind: "checks", done: true, checks: hit.checks, ms: performance.now() - t0 });
      return;
    }
    const program = engine.compile(msg.source);
    const out = buildProgram(wasm, engine.evaluator, program, msg.params ?? {}, { printer, inputs: inp, quality: msg.quality });
    try {
      const fast = msg.analyze === "none" ? undefined : (({ heat: _h, ...rest }) => rest)(analyze(wasm, out.body, printer, { level: "fast" }));
      const display = displayBuffers(out.parts, printer, { heat: msg.heat, edges: msg.edges });
      const head = {
        meta: program.meta,
        paramSpecs: program.params,
        params: out.params,
        handles: out.handles,
        quality: msg.quality,
        parts: out.parts.map((p) => {
          const b = p.solid.boundingBox();
          return { name: p.name, role: p.role, color: p.color, bbox: { min: [...b.min], max: [...b.max] }, volume: p.solid.volume() };
        }),
        checks: fast,
      };
      const kept = { head, display: copy(display) } as { head: Record<string, any>; display: DisplayBuffers; checks?: any };
      const full = msg.analyze === "full";
      post({ ...head, id: msg.id, ok: true, kind: "display", done: !full, display, ms: performance.now() - t0 }, displayTransfer(display));
      if (full) {
        const { heat: _h, ...checks } = analyze(wasm, out.body, printer, { level: "full" });
        kept.checks = checks;
        post({ id: msg.id, ok: true, kind: "checks", done: true, checks, ms: performance.now() - t0 });
      }
      memo.set(key, kept);
      while (memo.size > 12) memo.delete(memo.keys().next().value!);
    } finally {
      disposeBuild(out);
    }
  } catch (e: any) {
    post({ id: msg.id, ok: false, done: true, stage: e?.stage ?? "runtime", message: String(e?.message ?? e), fatal: !!e?.fatal });
  }
};
