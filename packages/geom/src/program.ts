// A Formwright program is plain JavaScript written by the agent (or a person):
//
//   const meta = { title: 'Bag hook', pack: 'household' };
//   const params = { shelf_t: { value: 18.2, min: 5, max: 40, unit: 'mm', source: 'caliper' } };
//   function handles(p) { return [{ type: 'linear', param: 'depth', at: [p.depth, 0, 10], axis: [1, 0, 0] }]; }
//   function build(p, lib) { return lib.std.box([p.depth, 20, p.shelf_t]); }
//   return { meta, params, handles, build };
//
// The same source runs in the browser (live sliders) and in the server worker
// (authoritative checks and export), so everything here is environment-free.
import type { Manifold, Wasm } from './kernel.ts';
import { withArena } from './kernel.ts';
import { makeLib, type LibContext } from './lib/index.ts';

export type Vec3 = [number, number, number];
export type ParamSource = 'photo' | 'caliper' | 'standard' | 'search' | 'user' | 'assumed' | 'design' | 'memory';

export interface ParamSpec {
  value: number | string | boolean;
  kind?: 'number' | 'int' | 'bool' | 'choice' | 'color' | 'seed';
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
  label?: string;
  unit?: string;
  source?: ParamSource;
  group?: string;
  hidden?: boolean;
}

export type Handle =
  | { type: 'linear'; param: string; at: Vec3; axis: Vec3; scale?: number; label?: string }
  | { type: 'radial'; param: string; center: Vec3; axis: Vec3; at: Vec3; scale?: number; label?: string }
  | { type: 'angle'; param: string; center: Vec3; axis: Vec3; at: Vec3; label?: string }
  | { type: 'point'; params: [string, string]; at: Vec3; plane: 'xy' | 'xz' | 'yz'; label?: string };

export type PartRole = 'model' | 'modifier' | 'negative' | 'support_blocker' | 'support_enforcer';

export interface Part {
  name: string;
  solid: Manifold;
  role: PartRole;
  color?: string;
  material?: string;
  settings?: Record<string, string | number | boolean>;
}

export interface ProgramMeta {
  title?: string;
  pack?: string;
  description?: string;
  keepPosition?: boolean;
  printNotes?: string;
}

export interface Program {
  meta: ProgramMeta;
  params: Record<string, ParamSpec>;
  handles?: (p: Record<string, any>) => Handle[];
  build: (p: Record<string, any>, lib: any) => unknown;
}

export type ParamValues = Record<string, number | string | boolean>;

// How untrusted source becomes a Program. Node uses `vm` with a timeout, the
// browser uses `new Function` inside a network-less worker.
export interface Evaluator {
  compile(source: string): Program;
  call<T>(fn: () => T): T;
}

export class ProgramError extends Error {
  stage: 'compile' | 'params' | 'build' | 'result';
  constructor(stage: ProgramError['stage'], message: string) {
    super(message);
    this.stage = stage;
  }
}

export function validateProgram(raw: any): Program {
  if (!raw || typeof raw !== 'object') throw new ProgramError('compile', 'program must `return { meta, params, build }`');
  if (typeof raw.build !== 'function') throw new ProgramError('compile', 'program has no build(p, lib) function');
  const params = raw.params ?? {};
  for (const [name, spec] of Object.entries<any>(params)) {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) throw new ProgramError('params', `bad param name "${name}"`);
    if (!spec || typeof spec !== 'object' || !('value' in spec)) {
      throw new ProgramError('params', `param "${name}" must be an object with a value`);
    }
  }
  return {
    meta: raw.meta ?? {},
    params,
    handles: typeof raw.handles === 'function' ? raw.handles : undefined,
    build: raw.build,
  };
}

export function resolveParams(program: Program, overrides: ParamValues = {}): ParamValues {
  const out: ParamValues = {};
  for (const [name, spec] of Object.entries(program.params)) {
    let v: any = name in overrides ? overrides[name] : spec.value;
    const kind = spec.kind ?? (typeof spec.value === 'number' ? 'number' : typeof spec.value === 'boolean' ? 'bool' : 'choice');
    if (kind === 'number' || kind === 'int' || kind === 'seed') {
      v = Number(v);
      if (!Number.isFinite(v)) v = Number(spec.value);
      if (spec.min !== undefined) v = Math.max(spec.min, v);
      if (spec.max !== undefined) v = Math.min(spec.max, v);
      if (kind !== 'number') v = Math.round(v);
    } else if (kind === 'bool') {
      v = v === true || v === 'true' || v === 1;
    } else if (kind === 'choice' && spec.options && !spec.options.includes(String(v))) {
      v = spec.value;
    }
    out[name] = v;
  }
  return out;
}

export interface BuildOutput {
  parts: Part[];
  params: ParamValues;
  handles: Handle[];
  // Model parts only, unioned; what printability checks look at.
  body: Manifold;
}

function normalizeParts(result: unknown, wasm: Wasm): Part[] {
  const items = Array.isArray(result) ? result : [result];
  const parts: Part[] = [];
  items.forEach((item: any, i) => {
    if (!item) return;
    if (item instanceof (wasm.Manifold as any) || typeof item?.getMesh === 'function') {
      parts.push({ name: items.length > 1 ? `part${i + 1}` : 'body', solid: item, role: 'model' });
    } else if (item.solid && typeof item.solid.getMesh === 'function') {
      parts.push({
        name: String(item.name ?? `part${i + 1}`),
        solid: item.solid,
        role: item.role ?? 'model',
        color: item.color,
        material: item.material,
        settings: item.settings,
      });
    } else {
      throw new ProgramError('result', `build returned ${typeof item}; expected a Manifold or lib.part(...)`);
    }
  });
  if (!parts.some((p) => p.role === 'model')) throw new ProgramError('result', 'build produced no model parts');
  return parts;
}

// Runs build() inside an arena: everything except the returned parts is freed.
// The caller owns the returned solids and must call `disposeBuild`.
export function buildProgram(
  wasm: Wasm,
  evaluator: Evaluator,
  program: Program,
  overrides: ParamValues,
  ctx: LibContext,
): BuildOutput {
  const params = resolveParams(program, overrides);
  return withArena((keep) => {
    const lib = makeLib(wasm, ctx);
    let result: unknown;
    try {
      result = evaluator.call(() => program.build({ ...params }, lib));
    } catch (e: any) {
      throw new ProgramError('build', e?.message ?? String(e));
    }
    let parts = normalizeParts(result, wasm);
    for (const part of parts) {
      const status = part.solid.status();
      if (status !== 'NoError') throw new ProgramError('result', `part "${part.name}" is invalid: ${status}`);
    }
    const models = parts.filter((p) => p.role === 'model').map((p) => p.solid);
    let body = models.length === 1 ? models[0] : wasm.Manifold.union(models);
    if (body.isEmpty()) throw new ProgramError('result', 'model is empty (check booleans and dimensions)');
    if (!program.meta.keepPosition) {
      const minZ = body.boundingBox().min[2];
      if (Math.abs(minZ) > 1e-6) {
        parts = parts.map((p) => ({ ...p, solid: p.solid.translate([0, 0, -minZ]) }));
        body = body.translate([0, 0, -minZ]);
      }
    }
    for (const p of parts) keep(p.solid);
    keep(body);
    let handles: Handle[] = [];
    if (program.handles) {
      try {
        handles = evaluator.call(() => program.handles!({ ...params })) ?? [];
      } catch {
        handles = [];
      }
    }
    return { parts, params, handles, body };
  });
}

export function disposeBuild(out: BuildOutput) {
  const seen = new Set<unknown>();
  for (const s of [out.body, ...out.parts.map((p) => p.solid)]) {
    if (seen.has(s)) continue;
    seen.add(s);
    try {
      s.delete();
    } catch {
      /* already freed */
    }
  }
}

// Browser/worker evaluator. The worker that uses it strips network globals first.
export function functionEvaluator(): Evaluator {
  return {
    compile(source) {
      const raw = new Function(`"use strict";\n${source}\n`)();
      return validateProgram(raw);
    },
    call(fn) {
      return fn();
    },
  };
}
