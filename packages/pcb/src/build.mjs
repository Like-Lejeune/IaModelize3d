// Stage 1: circuit TSX -> Circuit JSON. Placement checks, autorouting (2 layers) and the built-in DRC all run inside
// @tscircuit/core's render loop. The source is untrusted (the model writes it): it is transpiled with sucrase and
// evaluated in a vm context whose only host object is React, string/wasm code generation is off and `require` admits
// nothing but react. The vm timeout guards the top level only; component functions run later inside the reconciler,
// so a hang there is caught by the server pool, which kills the worker (server/formwright/pcb.py).
import vm from 'node:vm';
import { transform } from 'sucrase';
import * as React from 'react';
import { Circuit } from '@tscircuit/core';
import { EasyEdaJsonSchema, convertEasyEdaJsonToCircuitJson } from 'easyeda';

export const FRAME_CAP = 24; // routing frames kept for the animation
const TOP_LEVEL_MS = 5000;

export class StageError extends Error {
  constructor(stage, message, hint) {
    super(message);
    this.stage = stage;
    if (hint) this.hint = hint;
  }
}

function compile(source) {
  try {
    return transform(source, {
      transforms: ['typescript', 'jsx', 'imports'],
      jsxPragma: 'React.createElement',
      jsxFragmentPragma: 'React.Fragment',
      production: true,
    }).code;
  } catch (e) {
    throw new StageError('compile', String(e?.message ?? e).slice(0, 1500));
  }
}

function evaluate(code) {
  const exportsObj = {};
  const module = { exports: exportsObj };
  const require = (m) => {
    if (m === 'react') return React;
    throw new Error(`imports are not allowed here (got '${m}'): write one self-contained file; <board>, <chip>, <resistor>, <trace> ... need no import`);
  };
  const ctx = vm.createContext({ React, exports: exportsObj, module, require }, { codeGeneration: { strings: false, wasm: false } });
  try {
    vm.runInContext(code, ctx, { timeout: TOP_LEVEL_MS, filename: 'circuit.tsx' });
  } catch (e) {
    const msg = String(e?.message ?? e);
    if (/timed out/i.test(msg)) throw new StageError('timeout', `the top level of the circuit ran longer than ${TOP_LEVEL_MS / 1000} s`);
    throw new StageError('runtime', msg.slice(0, 1500));
  }
  const out = module.exports ?? exportsObj;
  let Comp = out.default ?? exportsObj.default;
  if (React.isValidElement?.(Comp)) { const el = Comp; Comp = () => el; }
  if (typeof Comp !== 'function') throw new StageError('compile', 'the circuit must `export default () => (<board ...>...</board>)`');
  const meta = out.meta && typeof out.meta === 'object' ? JSON.parse(JSON.stringify(out.meta)) : {};
  return { Comp, meta };
}

// Autorouter debug drawing -> segments [x1, y1, x2, y2] in the fw.board/1 frame (bottom-left origin, mm).
function frameLines(debugGraphics, origin) {
  const out = [];
  for (const line of debugGraphics?.lines ?? []) {
    const pts = line?.points ?? [];
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i];
      if (![a?.x, a?.y, b?.x, b?.y].every(Number.isFinite)) continue;
      out.push([r2(a.x - origin[0]), r2(a.y - origin[1]), r2(b.x - origin[0]), r2(b.y - origin[1])]);
    }
  }
  return out;
}

// Keep at most `cap` frames, evenly spaced, always the last one.
export function thinFrames(frames, cap = FRAME_CAP) {
  if (frames.length <= cap) return frames;
  const out = [];
  for (let i = 0; i < cap; i++) out.push(frames[Math.round((i * (frames.length - 1)) / (cap - 1))]);
  return out;
}

/**
 * Catalogue footprints: {C92489: {easyeda: <EasyEDA component JSON the server fetched>}} -> the resolver behind
 * footprint="lcsc:C92489". The worker has no network, so a part the server did not send fails as an unknown footprint.
 */
export function lcscLibrary(parts = {}) {
  const cache = new Map();
  return async (name) => {
    const code = String(name).trim().toUpperCase();
    if (!cache.has(code)) {
      const raw = parts[code]?.easyeda;
      if (!raw) throw new StageError('compile', `footprint lcsc:${code} was not loaded: use part numbers from search_parts / part_info`);
      let cj;
      try {
        cj = convertEasyEdaJsonToCircuitJson(EasyEdaJsonSchema.parse(raw));
      } catch (e) {
        throw new StageError('compile', `the EasyEDA footprint of ${code} could not be converted: ${String(e?.message ?? e).slice(0, 300)}`);
      }
      // the 3D model links would make the GLB preview fetch them: the board view draws a plain box instead
      cache.set(code, cj.map((e) => (e.type === 'cad_component' ? Object.fromEntries(Object.entries(e).filter(([k]) => !k.startsWith('model_') || k.endsWith('alignment'))) : e)));
    }
    return { footprintCircuitJson: cache.get(code) };
  };
}

/**
 * Build a circuit. onFrame({frame, total, progress, lines, w, h}) gets up to FRAME_CAP live routing frames (total is
 * that cap while routing runs); the result keeps the same number of frames spread evenly over the whole routing.
 */
export async function buildCircuit(source, { timeoutMs = 80000, onFrame, lcsc } = {}) {
  const t0 = performance.now();
  const code = compile(source);
  const { Comp, meta } = evaluate(code);
  const tTranspile = performance.now() - t0;

  const circuit = new Circuit({ platform: { partsEngineDisabled: true, footprintLibraryMap: { lcsc: lcscLibrary(lcsc) } } });
  const all = [];
  let live = 0, lastLive = 0;
  circuit.on('autorouting:progress', (e) => {
    try {
      const b = circuit.db?.pcb_board?.list?.()[0];
      const origin = b ? [b.center.x - b.width / 2, b.center.y - b.height / 2] : [0, 0];
      const lines = frameLines(e?.debugGraphics, origin);
      if (!lines.length) return;
      const progress = Number.isFinite(e?.progress) ? r2(e.progress) : null;
      all.push({ progress, lines });
      const now = performance.now();
      if (onFrame && live < FRAME_CAP && (now - lastLive > 150 || progress === 1)) {
        lastLive = now;
        onFrame({ frame: live++, total: FRAME_CAP, progress, lines, w: b?.width ?? null, h: b?.height ?? null });
      }
    } catch { /* a drawing problem never stops the build */ }
  });
  try {
    circuit.add(React.createElement(Comp));
  } catch (e) {
    throw new StageError('runtime', String(e?.message ?? e).slice(0, 1500));
  }
  const t1 = performance.now();
  let timer;
  try {
    await Promise.race([
      circuit.renderUntilSettled(),
      new Promise((_, rej) => { timer = setTimeout(() => rej(new StageError('timeout', `placement and routing took longer than ${Math.round(timeoutMs / 1000)} s`)), timeoutMs); }),
    ]);
  } catch (e) {
    if (e instanceof StageError) throw e;
    throw new StageError('runtime', String(e?.message ?? e).slice(0, 1500));
  } finally {
    clearTimeout(timer);
  }
  const tRender = performance.now() - t1;
  const json = circuit.getCircuitJson();
  return { json, meta, frames: thinFrames(all), ms: { transpile: Math.round(tTranspile), render: Math.round(tRender) } };
}

const r2 = (v) => Math.round(v * 100) / 100;
