// Previews: PCB top and bottom (SVG), schematic (SVG), the assembled board as GLB, and SVG -> PNG.
// PNGs come from resvg compiled to wasm, because the native @resvg/resvg-js addon cannot load in the sandboxed worker
// (--permission forbids addons). The GLB board texture is rendered the same way: the bundle aliases
// @resvg/resvg-js, which circuit-json-to-gltf imports, to the Resvg class below (scripts/bundle.mjs).
// The converters are imported lazily, so the small svg-png entry in dist/ can ship without them.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import tscircuitFont from '@tscircuit/alphabet/base64font';

let wasm = null;
let wasmReady = null;
const FONT = 'TscircuitAlphabet';

function wasmBytes() {
  // dist/resvg.wasm next to the bundle; unbundled (tests) the package's own copy
  const local = new URL('./resvg.wasm', import.meta.url);
  try { return fs.readFileSync(local); } catch { /* not bundled */ }
  return fs.readFileSync(createRequire(import.meta.url).resolve('@resvg/resvg-wasm/index_bg.wasm'));
}

export async function ensureResvg() {
  wasmReady ??= (async () => {
    const m = await import('@resvg/resvg-wasm');
    await m.initWasm(wasmBytes());
    wasm = m;
  })();
  await wasmReady;
  return wasm;
}

const fontBuffer = () => Uint8Array.from(Buffer.from(tscircuitFont, 'base64'));

/** Drop-in for @resvg/resvg-js's Resvg on top of the wasm build (call ensureResvg() first). */
export class Resvg {
  constructor(svg, opts = {}) {
    if (!wasm) throw new Error('resvg wasm is not initialised');
    const { fontFiles, loadSystemFonts, ...font } = opts.font ?? {};
    this.inner = new wasm.Resvg(svg, {
      ...opts,
      font: { ...font, fontBuffers: [fontBuffer()], defaultFontFamily: FONT, sansSerifFamily: FONT, monospaceFamily: FONT, serifFamily: FONT },
    });
  }
  render() { return this.inner.render(); }
  get width() { return this.inner.width; }
  get height() { return this.inner.height; }
}

export async function svgToPng(svg, { width = 1200, background } = {}) {
  await ensureResvg();
  const r = new Resvg(svg, { fitTo: { mode: 'width', value: width }, ...(background ? { background } : {}) });
  return r.render().asPng();
}

/** fw.board/1 mm -> SVG px for a PCB view, from the board outline the SVG draws: px = a*x + e, py = d*y + f. */
export function svgMap(svg, W, H) {
  const path = svg.match(/<path[^>]*class="pcb-board"[^>]*>/)?.[0];
  const d = path?.match(/\sd="([^"]+)"/)?.[1];
  const size = svg.match(/<svg[^>]*\swidth="([\d.]+)"[^>]*\sheight="([\d.]+)"/);
  if (!d) return null;
  const nums = d.match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/gi).map(Number);
  const xs = nums.filter((_, i) => i % 2 === 0), ys = nums.filter((_, i) => i % 2 === 1);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const a = (x1 - x0) / W, dd = -(y1 - y0) / H;
  const k = (v) => Math.round(v * 10000) / 10000;
  return { matrix: [k(a), 0, 0, k(dd), k(x0), k(y1)], width: size ? Number(size[1]) : null, height: size ? Number(size[2]) : null };
}

export async function previews(cj, models = {}) {
  const { convertCircuitJsonToPcbSvg, convertCircuitJsonToSchematicSvg } = await import('circuit-to-svg');
  const { convertCircuitJsonToGltf } = await import('circuit-json-to-gltf');
  const b = cj.find((e) => e.type === 'pcb_board');
  const ms = {};
  const time = async (k, fn) => { const t = performance.now(); const r = await fn(); ms[k] = Math.round(performance.now() - t); return r; };
  const opts = { width: 960, matchBoardAspectRatio: true };
  // both copper layers in each view, as an EDA tool shows them: the active one in full colour, the other dimmed
  // behind it (top red, bottom blue)
  const top = await time('svg_top', () => convertCircuitJsonToPcbSvg(cj, { ...opts, colorOverrides: { copper: { top: 'rgb(200, 52, 52)', bottom: 'rgba(77, 127, 196, 0.42)' } } }));
  const bottom = await time('svg_bottom', () => convertCircuitJsonToPcbSvg(cj, { ...opts, colorOverrides: { copper: { top: 'rgba(200, 52, 52, 0.28)', bottom: 'rgb(77, 127, 196)' } } }));
  const schematic = await time('svg_schematic', () => convertCircuitJsonToSchematicSvg(cj));
  let glb = null, glbError = null;
  try {
    await ensureResvg();
    const { withModels, withModelFetch } = await import('./models.mjs');
    const convert = (m) => {
      const dressed = withModels(cj, m);
      return withModelFetch(dressed.objs, async () => new Uint8Array(await convertCircuitJsonToGltf(dressed.cj, { format: 'glb', boardTextureResolution: 1024 })));
    };
    glb = await time('glb', async () => {
      try {
        return await convert(models);
      } catch (e) { // a catalogue model that does not parse costs the models, not the board's picture
        glbError = `a part's 3D model failed: ${String(e?.message ?? e).slice(0, 200)}`;
        return await convert({ ...models, objs: {} });
      }
    });
  } catch (e) {
    glbError = String(e?.message ?? e).slice(0, 300);
  }
  return {
    files: { 'pcb_top.svg': top, 'pcb_bottom.svg': bottom, 'schematic.svg': schematic, ...(glb ? { 'board.glb': glb } : {}) },
    svg_map: b ? { 'pcb_top.svg': svgMap(top, b.width, b.height), 'pcb_bottom.svg': svgMap(bottom, b.width, b.height) } : {},
    // board.glb is Y-up around the board centre with x mirrored: row-major 4x4 from GLB coordinates to fw.board/1 mm
    ...(b ? { glb_map: { matrix: [[-1, 0, 0, -(b.center.x - b.width / 2)], [0, 0, 1, -(b.center.y - b.height / 2)], [0, 1, 0, b.thickness / 2], [0, 0, 0, 1]] } } : {}),
    ...(glbError ? { glb_error: glbError } : {}),
    ms,
  };
}

/** dist/svg-png.mjs: SVG on stdin -> PNG on stdout (argv: width, background). */
export async function pngMain() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  const [width, background] = process.argv.slice(2);
  const png = await svgToPng(Buffer.concat(chunks).toString('utf8'), { width: Number(width) || 1200, background: background || undefined });
  process.stdout.write(Buffer.from(png));
}
