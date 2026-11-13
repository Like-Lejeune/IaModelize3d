// Stage 1: circuit TSX -> Circuit JSON. Placement checks, autorouting (2 layers) and the built-in DRC all run inside
// @tscircuit/core's render loop. The source is untrusted (the model writes it): it is transpiled with sucrase and
// evaluated in a vm context whose only host object is React, string/wasm code generation is off and `require` admits
// nothing but react. The vm timeout guards the top level only; component functions run later inside the reconciler,
// so a hang there is caught by the server pool, which kills the worker (server/iamodelize3d/pcb.py).
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

function evaluate(code, R = React) {
  const exportsObj = {};
  const module = { exports: exportsObj };
  const require = (m) => {
    if (m === 'react') return R;
    throw new Error(`imports are not allowed here (got '${m}'): write one self-contained file; <board>, <chip>, <resistor>, <trace> ... need no import`);
  };
  const ctx = vm.createContext({ React: R, exports: exportsObj, module, require }, { codeGeneration: { strings: false, wasm: false } });
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
      // the 3D model comes with the export instead (models.mjs): the worker has no network, and the converter's own size for it is
      // not the model's (it would shrink a 9 mm PIR can to 4 mm)
      const kept = parts[code]?.bare ? cj.filter((e) => !String(e.type).startsWith('pcb_courtyard')) : cj;
      cache.set(code, kept.map((e) => (e.type === 'cad_component' ? Object.fromEntries(Object.entries(e).filter(([k]) => !k.startsWith('model_') || k.endsWith('alignment'))) : e)));
    }
    return { footprintCircuitJson: cache.get(code) };
  };
}

const MARGIN_KEYS = ['pcbMarginLeft', 'pcbMarginRight', 'pcbMarginTop', 'pcbMarginBottom', 'pcbMarginX', 'pcbMarginY'];

/** [x0, y0, x1, y1] of one footprint element (pads, plated holes, courtyards), or null. */
function extentOf(e) {
  const box = (x, y, w, h) => [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
  const pts = (ps) => (ps?.length ? [Math.min(...ps.map((p) => p.x)), Math.min(...ps.map((p) => p.y)), Math.max(...ps.map((p) => p.x)), Math.max(...ps.map((p) => p.y))] : null);
  if (e.type === 'pcb_smtpad') {
    if (e.shape === 'circle') return box(e.x, e.y, 2 * e.radius, 2 * e.radius);
    if (e.shape === 'polygon') return pts(e.points);
    if (Number.isFinite(e.width) && Number.isFinite(e.height)) {
      const turned = Math.round(((e.ccw_rotation ?? e.rotation ?? 0) % 180 + 180) % 180) === 90;
      return turned ? box(e.x, e.y, e.height, e.width) : box(e.x, e.y, e.width, e.height);
    }
    return null;
  }
  if (e.type === 'pcb_plated_hole') {
    const w = e.rect_pad_width ?? e.outer_width ?? e.outer_diameter ?? e.hole_diameter;
    const h = e.rect_pad_height ?? e.outer_height ?? e.outer_diameter ?? e.hole_diameter;
    return Number.isFinite(w) && Number.isFinite(h) ? box(e.x, e.y, w, h) : null;
  }
  if (e.type === 'pcb_courtyard_rect') return box(e.center.x, e.center.y, e.width, e.height);
  if (e.type === 'pcb_courtyard_outline') return pts(e.outline);
  if (e.type === 'pcb_courtyard_polygon') return pts(e.points);
  if (e.type === 'pcb_courtyard_circle') return box(e.center.x, e.center.y, 2 * e.radius, 2 * e.radius);
  return null;
}

/**
 * How far each catalogue footprint's courtyard reaches past its pads: {C114881: {left, right, top, bottom}} (mm, rotation
 * 0). tscircuit's packer sizes a lone part by its courtyard but a group (a chip with its decoupling capacitors) by its
 * pads alone, so a TO-5 PIR, a 9.6 mm buzzer or a 5050 LED in a group was packed onto its neighbours and over the board
 * edge, however large the board grew. pcbMargin* widens the part's pads to its courtyard for the packer.
 */
export function courtyardMargins(parts = {}) {
  const out = {};
  for (const [code, p] of Object.entries(parts)) {
    if (!p?.easyeda || p.bare) continue;
    let cj;
    try { cj = convertEasyEdaJsonToCircuitJson(EasyEdaJsonSchema.parse(p.easyeda)); } catch { continue; }
    const grow = (b, x) => (b ? [Math.min(b[0], x[0]), Math.min(b[1], x[1]), Math.max(b[2], x[2]), Math.max(b[3], x[3])] : x);
    let pads = null, court = null;
    for (const e of cj) {
      const x = extentOf(e);
      if (!x || !x.every(Number.isFinite)) continue;
      if (/^pcb_(smtpad|plated_hole)$/.test(e.type)) pads = grow(pads, x);
      else if (e.type.startsWith('pcb_courtyard')) court = grow(court, x);
    }
    if (!pads || !court) continue;
    const m = { left: pads[0] - court[0], bottom: pads[1] - court[1], right: court[2] - pads[2], top: court[3] - pads[3] };
    for (const k of Object.keys(m)) m[k] = Math.max(0, r2(m[k]));
    if (Math.max(...Object.values(m)) > 0.25) out[String(code).toUpperCase()] = m;
  }
  return out;
}

/** The margins of a part turned by its pcbRotation (quarter turns, counter-clockwise), as the TSX props. */
function marginProps(m, rotation) {
  const order = ['right', 'top', 'left', 'bottom']; // counter-clockwise: what lay right lies on top after a quarter turn
  const q = Number.isFinite(Number(rotation)) ? ((Math.round(Number(rotation) / 90) % 4) + 4) % 4 : 0;
  const t = Object.fromEntries(order.map((side, i) => [order[(i + q) % 4], m[side]]));
  return { pcbMarginLeft: t.left, pcbMarginRight: t.right, pcbMarginTop: t.top, pcbMarginBottom: t.bottom };
}

/** React for the circuit's realm: <chip footprint="lcsc:C..."> gets its courtyard margins unless it states its own. */
function reactWithMargins(margins) {
  if (!Object.keys(margins).length) return React;
  const createElement = (type, props, ...children) => {
    const fp = type === 'chip' && typeof props?.footprint === 'string' ? props.footprint.match(/^lcsc:(\S+)$/i) : null;
    const m = fp ? margins[fp[1].toUpperCase()] : null;
    if (m && !MARGIN_KEYS.some((k) => props[k] != null)) props = { ...props, ...marginProps(m, props.pcbRotation) };
    return React.createElement(type, props, ...children);
  };
  return Object.freeze({ ...React, createElement });
}

/**
 * Build a circuit. onFrame({frame, total, progress, lines, w, h}) gets up to FRAME_CAP live routing frames (total is
 * that cap while routing runs); the result keeps the same number of frames spread evenly over the whole routing.
 */
export async function buildCircuit(source, { timeoutMs = 80000, onFrame, lcsc } = {}) {
  const t0 = performance.now();
  const code = compile(source);
  const { Comp, meta } = evaluate(code, reactWithMargins(courtyardMargins(lcsc)));
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
