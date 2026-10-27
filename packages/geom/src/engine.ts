// One request/response API over programs, used by the server worker (Node) and the
// browser worker alike. Inputs and outputs are plain JSON (binary as base64).
import { analyze, type CheckReport } from './checks.ts';
import { to3mf, toStl } from './export.ts';
import { nelderMead, unpackMask } from './fit.ts';
import type { Wasm } from './kernel.ts';
import { DEFAULT_PRINTER, type Inputs, type PrinterProfile } from './lib/index.ts';
import { fromBase64, hexColor, partsMesh, toBase64 } from './mesh.ts';
import { encodePng } from './png.ts';
import {
  buildProgram,
  disposeBuild,
  ProgramError,
  resolveParams,
  type Evaluator,
  type ParamValues,
  type Program,
} from './program.ts';
import { iou, orthoFit, render, renderSheet, silhouette, type Camera } from './render.ts';

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

export interface RenderRequest extends BaseRequest {
  view?: 'sheet' | 'iso';
  camera?: Camera; // photo camera for overlays
  tile?: number;
  heat?: boolean;
  title?: string;
}

export interface ExportRequest extends BaseRequest {
  format: 'stl' | '3mf';
  title?: string;
  objectSettings?: Record<string, string | number | boolean>;
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
    for (const [name, src] of Object.entries(req.skills ?? {})) {
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
