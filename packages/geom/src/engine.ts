// One request/response API over programs, used by the server worker (Node) and the
// browser worker alike. Inputs and outputs are plain JSON (binary as base64).
import { analyze, type CheckReport } from './checks.ts';
import { to3mf, toStl } from './export.ts';
import { nelderMead, unpackMask } from './fit.ts';
import { parseMesh } from './import.ts';
import { withArena, type Wasm } from './kernel.ts';
import { DEFAULT_PRINTER, type Inputs, type PrinterProfile } from './lib/index.ts';
import { solidFromArrays } from './lib/meshops.ts';
import { fromBase64, hexColor, partsMesh, toBase64 } from './mesh.ts';
import { encodePng } from './png.ts';
import {
  buildProgram,
  disposeBuild,
  ProgramError,
  resolveParams,
  type Evaluator,
  type ParamValues,
  type Part,
  type Program,
} from './program.ts';
import { iou, orthoFit, render, renderSheet, SHEET_VIEWS, silhouette, type Camera } from './render.ts';

function partsBox(positions: ArrayLike<number>) {
  const min: [number, number, number] = [Infinity, Infinity, Infinity];
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3)
    for (let k = 0; k < 3; k++) {
      min[k] = Math.min(min[k], positions[i + k]);
      max[k] = Math.max(max[k], positions[i + k]);
    }
  return { min, max };
}

export interface BaseRequest {
  source: string;
  params?: ParamValues;
  printer?: Partial<PrinterProfile>;
  inputs?: Inputs;
  skills?: Record<string, string>; // name -> source returning function(lib, ...args)
}

export interface BuildRequest extends BaseRequest {
  analyze?: 'none' | 'fast' | 'full';
  vaseMode?: boolean;
  mesh?: boolean;
}

export interface ViewSpec {
  name?: string;
  azimuth: number; // degrees around the model, 0 = front (looking from -Y), 90 = right side (+X)
  elevation: number; // degrees above the horizon
}

export interface RenderRequest extends BaseRequest {
  view?: 'sheet' | 'iso';
  camera?: Camera; // photo camera for overlays
  tile?: number;
  heat?: boolean;
  title?: string;
  // look closer: chosen angles, a close-up region (or a part), a section cut
  views?: ViewSpec[];
  focus?: { center: [number, number, number]; size: number } | { part: string };
  cut?: { axis: 'x' | 'y' | 'z'; at: number; keep?: 'below' | 'above' };
}

export interface ParseMeshRequest {
  data: string; // base64 file bytes
  format: string; // stl | obj
}

export interface ExportRequest extends BaseRequest {
  format: 'stl' | '3mf';
  title?: string;
  objectSettings?: Record<string, string | number | boolean>;
}

export interface InspectRequest extends BaseRequest {
  ops: (
    | { op: 'section'; z: number }
    | { op: 'outline'; z?: number }
    | { op: 'parts' }
    | { op: 'gap'; a: string; b: string; search?: number }
    | { op: 'ray'; from: [number, number, number]; to: [number, number, number] }
  )[];
}

export interface FitRequest extends BaseRequest {
  free: string[];
  targets: { camera: Camera; mask: string }[]; // mask: packed bits, base64, width*height of the camera
  maxEval?: number;
}

const PALETTE: [number, number, number][] = [
  [214, 216, 222], [232, 150, 90], [110, 170, 220], [150, 200, 120], [220, 120, 160], [240, 210, 100],
];

export class Engine {
  wasm: Wasm;
  evaluator: Evaluator;
  private cache = new Map<string, Program>();

  constructor(wasm: Wasm, evaluator: Evaluator) {
    this.wasm = wasm;
    this.evaluator = evaluator;
  }

  compile(source: string): Program {
    let p = this.cache.get(source);
    if (!p) {
      try {
        p = this.evaluator.compile(source);
      } catch (e: any) {
        if (e instanceof ProgramError) throw e;
        throw new ProgramError('compile', e?.message ?? String(e));
      }
      if (this.cache.size > 64) this.cache.clear();
      this.cache.set(source, p);
    }
    return p;
  }

  private printer(req: BaseRequest): PrinterProfile {
    return { ...DEFAULT_PRINTER, ...(req.printer ?? {}) };
  }

  private skills(req: BaseRequest) {
    const out: Record<string, (lib: any, ...args: any[]) => unknown> = {};
    // Skills used by a saved program travel with it in inputs.skills, so the
    // browser can rebuild it without access to the memory store.
    const sources = { ...((req.inputs as any)?.skills ?? {}), ...(req.skills ?? {}) };
    for (const [name, src] of Object.entries<string>(sources)) {
      const fn = this.evaluator.compile(`const fn = (function(){ ${src} })(); return { meta: {}, params: {}, build: fn };`).build;
      out[name] = fn as any;
    }
    return out;
  }

  private run(req: BaseRequest) {
    const program = this.compile(req.source);
    const printer = this.printer(req);
    const out = buildProgram(this.wasm, this.evaluator, program, req.params ?? {}, {
      printer,
      inputs: req.inputs,
      skills: this.skills(req),
    });
    return { program, printer, out };
  }

  build(req: BuildRequest) {
    const { program, printer, out } = this.run(req);
    try {
      let checks: CheckReport | undefined;
      if ((req.analyze ?? 'fast') !== 'none') {
        checks = analyze(this.wasm, out.body, printer, { level: req.analyze === 'full' ? 'full' : 'fast', vaseMode: req.vaseMode });
      }
      const result: any = {
        ok: true,
        meta: program.meta,
        paramSpecs: program.params,
        params: out.params,
        handles: out.handles,
        parts: out.parts.map((p) => {
          const b = p.solid.boundingBox();
          return { name: p.name, role: p.role, color: p.color, settings: p.settings, material: p.material, bbox: b, volume: p.solid.volume() };
        }),
      };
      if (checks) {
        const { heat, ...rest } = checks;
        result.checks = rest;
        if (req.mesh && heat) result.heat = toBase64(new Uint8Array(heat.buffer));
      }
      if (req.mesh) {
        const m = partsMesh(out.parts);
        result.mesh = {
          positions: toBase64(new Uint8Array(m.positions.buffer)),
          indices: toBase64(new Uint8Array(m.indices.buffer)),
          triPart: toBase64(new Uint8Array(m.triPart.buffer)),
        };
      }
      return result;
    } finally {
      disposeBuild(out);
    }
  }

  private colors(parts: { color?: string; role: string }[], triPart: Uint16Array, heat?: Float32Array) {
    const c = new Uint8Array(triPart.length * 3);
    for (let f = 0; f < triPart.length; f++) {
      const part = parts[triPart[f]];
      let rgb = hexColor(part?.color, PALETTE[triPart[f] % PALETTE.length]);
      if (part?.role === 'modifier') rgb = [120, 200, 255];
      if (heat && heat[f] > 0) {
        const h = heat[f];
        rgb = [rgb[0] + (235 - rgb[0]) * h, rgb[1] * (1 - h * 0.7), rgb[2] * (1 - h * 0.8)];
      }
      c.set(rgb, f * 3);
    }
    return c;
  }

  render(req: RenderRequest) {
    const { printer, out } = this.run(req);
    try {
      const mesh = partsMesh(out.parts, ['model', 'modifier']);
      let heat: Float32Array | undefined;
      if (req.heat) {
        // heat is per triangle of the union body; recompute per part mesh instead
        const r = analyze(this.wasm, out.body, printer, { level: 'fast' });
        if (r.heat && r.heat.length === mesh.triPart.length) heat = r.heat;
      }
      const colors = this.colors(out.parts, mesh.triPart, heat);
      const box = out.body.boundingBox();
      if (req.views || req.focus || req.cut) return this.closeUp(req, out.parts, box);
      if (req.camera) {
        const r = render(mesh, req.camera, { colors, background: [0, 0, 0, 0], edgeColor: [255, 120, 40] });
        const mask = new Uint8Array(Math.ceil((r.width * r.height) / 8));
        for (let k = 0; k < r.width * r.height; k++) if (r.ids[k] >= 0) mask[k >> 3] |= 1 << (7 - (k & 7));
        return { png: toBase64(encodePng(r.rgba, r.width, r.height)), width: r.width, height: r.height, mask: toBase64(mask) };
      }
      if (req.view === 'iso') {
        const size = req.tile ?? 512;
        const cam = orthoFit([-1, 1, -0.8], { min: box.min as any, max: box.max as any }, size, size, 0.1);
        const r = render(mesh, cam, { colors, background: [246, 246, 243, 255] });
        return { png: toBase64(encodePng(r.rgba, r.width, r.height)), width: r.width, height: r.height };
      }
      const s = renderSheet(mesh, { min: box.min as any, max: box.max as any }, { tile: req.tile ?? 340, colors, title: req.title });
      return { png: toBase64(encodePng(s.rgba, s.width, s.height)), width: s.width, height: s.height };
    } finally {
      disposeBuild(out);
    }
  }

  // Views from any angle, a zoomed region or part, and section cuts (the cut face shows
  // walls, cavities and thickness the outside views hide).
  private closeUp(req: RenderRequest, parts: Part[], box: { min: number[]; max: number[] }) {
    let shown = parts.filter((p) => p.role === 'model' || p.role === 'modifier');
    const cut = req.cut;
    let cutDir: [number, number, number] | null = null;
    if (cut) {
      const i = 'xyz'.indexOf(cut.axis);
      const n: [number, number, number] = [0, 0, 0];
      const below = (cut.keep ?? 'below') === 'below';
      n[i] = below ? -1 : 1; // trimByPlane keeps the side the normal points to
      shown = shown.map((p) => ({ ...p, solid: p.solid.trimByPlane(n, below ? -cut.at : cut.at) })).filter((p) => !p.solid.isEmpty());
      if (!shown.length) throw new ProgramError('result', `nothing ${below ? 'below' : 'above'} ${cut.axis}=${cut.at}`);
      cutDir = n; // the kept side's cut face looks against n, so the camera looks along n
    }
    const mesh = partsMesh(shown);
    const colors = this.colors(shown, mesh.triPart);
    let frame = { min: [...box.min] as [number, number, number], max: [...box.max] as [number, number, number] };
    const focus = req.focus;
    if (focus && 'part' in focus) {
      const p = parts.find((q) => q.name === focus.part);
      if (!p) throw new ProgramError('result', `no part "${focus.part}"; parts: ${parts.map((q) => q.name).join(', ')}`);
      const b = p.solid.boundingBox();
      frame = { min: b.min as any, max: b.max as any };
    } else if (focus && 'center' in focus) {
      const h = Math.max(1, focus.size) / 2;
      frame = { min: focus.center.map((v) => v - h) as any, max: focus.center.map((v) => v + h) as any };
    }
    if (cut) {
      const b = mesh.positions.length ? partsBox(mesh.positions) : frame;
      if (!focus) frame = b;
    }
    const dirOf = (az: number, el: number): [number, number, number] => {
      const a = (az * Math.PI) / 180, e = (el * Math.PI) / 180;
      // camera on the (sin a, -cos a) side looking back at the model
      return [-Math.sin(a) * Math.cos(e), Math.cos(a) * Math.cos(e), -Math.sin(e)];
    };
    let views = (req.views ?? []).slice(0, 6).map((v) => ({ name: v.name ?? `AZ ${Math.round(v.azimuth)} EL ${Math.round(v.elevation)}`, dir: dirOf(v.azimuth, v.elevation) }));
    if (!views.length && cutDir) {
      const name = `SECTION ${cut!.axis.toUpperCase()}=${cut!.at}`;
      // straight at the cut face, plus two oblique views of it from either side
      const d = cutDir;
      const a = cut!.axis === 'z' ? [1, 0, 0] : [0, 0, 1];
      const b = [d[1] * a[2] - d[2] * a[1], d[2] * a[0] - d[0] * a[2], d[0] * a[1] - d[1] * a[0]];
      const ob = (k: number): [number, number, number] => [0, 1, 2].map((i) => d[i] + 0.55 * k * a[i] + 0.35 * b[i]) as [number, number, number];
      views = [{ name, dir: d }, { name: `${name} OBLIQUE`, dir: ob(1) }, { name: `${name} OBLIQUE 2`, dir: ob(-1) }];
    }
    if (!views.length) views = SHEET_VIEWS.slice(0, focus ? 3 : 6);
    const size = [0, 1, 2].map((i) => box.max[i] - box.min[i]);
    const s = renderSheet(mesh, frame, { tile: req.tile ?? 420, colors, views, title: req.title, size });
    return { png: toBase64(encodePng(s.rgba, s.width, s.height)), width: s.width, height: s.height };
  }

  parseMesh(req: ParseMeshRequest) {
    const m = parseMesh(fromBase64(req.data), req.format);
    let closed = true;
    let volume = 0;
    let reason = '';
    withArena(() => {
      try {
        volume = solidFromArrays(this.wasm, m.positions, m.triangles).volume();
      } catch (e: any) {
        closed = false;
        reason = e?.message ?? String(e);
      }
    });
    const b = partsBox(Float32Array.from(m.positions));
    return { ...m, stats: { vertices: m.positions.length / 3, triangles: m.triangles.length / 3, bbox: b, closed, volume, reason } };
  }

  export(req: ExportRequest) {
    const { out } = this.run(req);
    try {
      if (req.format === 'stl') return { data: toBase64(toStl(out.body)), mime: 'model/stl' };
      const data = to3mf(out.parts, { title: req.title, objectSettings: req.objectSettings });
      return { data: toBase64(data), mime: 'model/3mf' };
    } finally {
      disposeBuild(out);
    }
  }

  // Measuring tools for the agent: sections, per-part boxes, gaps between parts.
  inspect(req: InspectRequest) {
    const { out } = this.run(req);
    try {
      const results: unknown[] = [];
      for (const op of req.ops.slice(0, 20)) {
        if (op.op === 'section') {
          const cs = out.body.slice(op.z);
          const pieces = cs.decompose().map((p) => {
            const b = p.bounds();
            return { area: +p.area().toFixed(2), min: b.min.map((v) => +v.toFixed(2)), max: b.max.map((v) => +v.toFixed(2)), contours: p.numContour() };
          });
          results.push({ op: 'section', z: op.z, area: +cs.area().toFixed(2), pieces: pieces.slice(0, 12) });
        } else if (op.op === 'outline') {
          const cs = (op.z === undefined ? out.body.project() : out.body.slice(op.z)).simplify(0.02);
          results.push({ op: 'outline', z: op.z ?? null, polygons: cs.toPolygons().map((p) => p.map(([x, y]) => [+x.toFixed(3), +y.toFixed(3)])) });
        } else if (op.op === 'parts') {
          results.push({
            op: 'parts',
            parts: out.parts.map((p) => {
              const b = p.solid.boundingBox();
              return { name: p.name, role: p.role, min: b.min.map((v) => +v.toFixed(2)), max: b.max.map((v) => +v.toFixed(2)), volume: +p.solid.volume().toFixed(1) };
            }),
          });
        } else if (op.op === 'gap') {
          const a = out.parts.find((p) => p.name === op.a)?.solid;
          const b = out.parts.find((p) => p.name === op.b)?.solid;
          results.push({ op: 'gap', a: op.a, b: op.b, gap: a && b ? +a.minGap(b, op.search ?? 5).toFixed(3) : null });
        } else if (op.op === 'ray') {
          const hits = out.body.rayCast(op.from as any, op.to as any);
          results.push({ op: 'ray', hits: hits.slice(0, 8).map((h: any) => ({ distance: +h.distance.toFixed(3), position: h.position.map((v: number) => +v.toFixed(2)) })) });
        }
      }
      return { results };
    } finally {
      disposeBuild(out);
    }
  }

  fit(req: FitRequest) {
    const program = this.compile(req.source);
    const printer = this.printer(req);
    const base = resolveParams(program, req.params ?? {});
    const free = req.free.filter((k) => typeof base[k] === 'number' && program.params[k]);
    const ranges = free.map((k) => {
      const s = program.params[k];
      const v = Number(base[k]);
      return [s.min ?? v * 0.5, s.max ?? v * 1.5] as [number, number];
    });
    const targets = req.targets.map((t) => ({ camera: t.camera, mask: unpackMask(fromBase64(t.mask), t.camera.width, t.camera.height) }));
    const toParams = (x: number[]) => {
      const p: ParamValues = { ...base };
      free.forEach((k, i) => (p[k] = ranges[i][0] + x[i] * (ranges[i][1] - ranges[i][0])));
      return p;
    };
    const skills = this.skills(req);
    const score = (x: number[]) => {
      let out;
      try {
        out = buildProgram(this.wasm, this.evaluator, program, toParams(x), { printer, inputs: req.inputs, skills });
      } catch {
        return 1;
      }
      try {
        const mesh = partsMesh(out.parts, ['model']);
        let s = 0;
        for (const t of targets) s += 1 - iou(silhouette(mesh, t.camera), t.mask);
        return s / targets.length;
      } finally {
        disposeBuild(out);
      }
    };
    const x0 = free.map((k, i) => (Number(base[k]) - ranges[i][0]) / Math.max(1e-9, ranges[i][1] - ranges[i][0]));
    const before = 1 - score(x0);
    const r = nelderMead(score, x0, { maxEval: req.maxEval ?? 120 });
    const params = toParams(r.x);
    return { params: Object.fromEntries(free.map((k) => [k, Math.round(Number(params[k]) * 100) / 100])), iouBefore: before, iouAfter: 1 - r.score, evaluations: r.evaluations };
  }
}

export { orthoFit, type Camera };
