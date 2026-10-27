// Browser geometry worker: compiles and builds agent-written programs locally so
// sliders and handles update at interactive rates. Network APIs are removed before
// any program runs; the main thread kills this worker if a build hangs.
import wasmUrl from 'manifold-3d/manifold.wasm?url';
import {
  analyze,
  buildProgram,
  DEFAULT_PRINTER,
  disposeBuild,
  Engine,
  functionEvaluator,
  loadKernel,
  partsMesh,
  triangleHeat,
  fromBase64,
} from '@formwright/geom';

type Req =
  | { id: number; type: 'build'; source: string; params?: Record<string, any>; inputs?: any; printer?: any; level?: 'none' | 'fast' | 'full'; vaseMode?: boolean }
  | { id: number; type: 'export'; source: string; params?: Record<string, any>; inputs?: any; format: 'stl' | '3mf'; title?: string };

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
  return { wasm, engine: new Engine(wasm, functionEvaluator()) };
})();

self.onmessage = async (ev: MessageEvent<Req>) => {
  const msg = ev.data;
  const t0 = performance.now();
  try {
    const { wasm, engine } = await ready;
    if (msg.type === 'export') {
      const out = engine.export({ source: msg.source, params: msg.params, inputs: msg.inputs, format: msg.format, title: msg.title });
      const bytes = fromBase64(out.data);
      (self as any).postMessage({ id: msg.id, ok: true, bytes, mime: out.mime }, [bytes.buffer]);
      return;
    }
    const program = engine.compile(msg.source);
    const printer = { ...DEFAULT_PRINTER, ...(msg.printer ?? {}) };
    const out = buildProgram(wasm, engine.evaluator, program, msg.params ?? {}, { printer, inputs: msg.inputs });
    try {
      const level = msg.level ?? 'fast';
      let checks: any;
      if (level !== 'none') {
        const r = analyze(wasm, out.body, printer, { level, vaseMode: msg.vaseMode });
        const { heat: _h, ...rest } = r;
        checks = rest;
      }
      const shown = out.parts.filter((p) => p.role === 'model' || p.role === 'modifier' || p.role === 'negative');
      const mesh = partsMesh(out.parts);
      // heat per displayed part, concatenated in partsMesh order
      const heat = new Float32Array(mesh.triPart.length);
      let off = 0;
      for (const p of shown) {
        const n = p.solid.numTri();
        if (p.role === 'model') heat.set(triangleHeat(p.solid, printer).heat.subarray(0, n), off);
        off += n;
      }
      const result = {
        id: msg.id,
        ok: true,
        meta: program.meta,
        paramSpecs: program.params,
        params: out.params,
        handles: out.handles,
        parts: out.parts.map((p) => {
          const b = p.solid.boundingBox();
          return { name: p.name, role: p.role, color: p.color, settings: p.settings, bbox: { min: [...b.min], max: [...b.max] }, volume: p.solid.volume() };
        }),
        checks,
        positions: mesh.positions,
        indices: mesh.indices,
        triPart: mesh.triPart,
        heat,
        ms: performance.now() - t0,
      };
      (self as any).postMessage(result, [mesh.positions.buffer, mesh.indices.buffer, mesh.triPart.buffer, heat.buffer]);
    } finally {
      disposeBuild(out);
    }
  } catch (e: any) {
    (self as any).postMessage({ id: msg.id, ok: false, stage: e?.stage ?? 'runtime', message: String(e?.message ?? e) });
  }
};
