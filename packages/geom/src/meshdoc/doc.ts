// The mesh engine's document: a list of operations on one surface, as JSON instead of a
// program. It compiles into an ordinary Program, so checks, renders, export, sliders and
// versions work the same as for CAD programs. Replays are incremental: the surface after
// earlier operations is cached, so appending a stroke or tuning the last one recomputes
// only what changed.
//
//   { "engine": "mesh", "meta": {...}, "params": {...}, "symmetry": "x", "detail": 0.6,
//     "ops": [ { "id": "body", "op": "clay", "shapes": [...], "smooth": 8 }, ... ] }
//
// Any number in an op may be a parameter ("$height") or an expression ("= height * 0.4").
import { detail, type Wasm } from '../kernel.ts';
import { hashString } from '../hash.ts';
import { makeSdf } from '../lib/sdf.ts';
import type { Evaluator, Program, ProgramMeta, ParamSpec } from '../program.ts';
import { ProgramError, buildProgram, disposeBuild, validateProgram } from '../program.ts';
import { applyOp, EXPENSIVE, OPS, SOURCES, type Op, type OpContext } from './ops.ts';
import { cloneMesh, fromSolid, meshBytes, toSolid, type TriMesh, type V3 } from './trimesh.ts';

export interface MeshDoc {
  engine: 'mesh';
  meta?: ProgramMeta & { color?: string };
  params?: Record<string, ParamSpec>;
  symmetry?: 'x' | 'y' | null;
  detail?: number;
  ops: Op[];
}

export function isMeshDoc(source: string): boolean {
  const s = source.trimStart();
  return s.startsWith('{') && /"engine"\s*:\s*"mesh"/.test(s.slice(0, 4000));
}

export function parseMeshDoc(source: string): MeshDoc {
  let doc: any;
  try {
    doc = JSON.parse(source);
  } catch (e: any) {
    throw new ProgramError('compile', `mesh document is not valid JSON: ${e?.message ?? e}`);
  }
  if (!doc || doc.engine !== 'mesh') throw new ProgramError('compile', 'mesh document needs "engine": "mesh"');
  if (!Array.isArray(doc.ops)) throw new ProgramError('compile', 'mesh document needs "ops": [...]');
  doc.ops.forEach((op: any, i: number) => {
    if (!op || typeof op !== 'object' || typeof op.op !== 'string') throw new ProgramError('compile', `op ${i + 1} must be an object with "op"`);
    if (!(OPS as readonly string[]).includes(op.op)) throw new ProgramError('compile', `op ${i + 1}: unknown op "${op.op}"; ops: ${OPS.join(', ')}`);
  });
  const ids = doc.ops.map((o: any) => o.id).filter(Boolean);
  const dup = ids.find((id: string, i: number) => ids.indexOf(id) !== i);
  if (dup) throw new ProgramError('compile', `two ops have the id "${dup}"`);
  if (doc.symmetry && !['x', 'y'].includes(doc.symmetry)) throw new ProgramError('compile', 'symmetry must be "x", "y" or null');
  return doc as MeshDoc;
}

// ---------------------------------------------------------------- expressions
// "= a * 2 + max(b, 3)": numbers, params, + - * / % ^, parentheses and a few functions.
// No eval: documents may come from anywhere.
const FUNCS: Record<string, (...a: number[]) => number> = {
  min: Math.min, max: Math.max, abs: Math.abs, sqrt: Math.sqrt, floor: Math.floor, ceil: Math.ceil, round: Math.round,
  sin: (d) => Math.sin((d * Math.PI) / 180), cos: (d) => Math.cos((d * Math.PI) / 180), tan: (d) => Math.tan((d * Math.PI) / 180),
  clamp: (v, a, b) => Math.min(b, Math.max(a, v)), lerp: (a, b, t) => a + (b - a) * t,
};

export function evalExpr(src: string, vars: Record<string, unknown>): number {
  const toks = src.match(/\d*\.?\d+(?:e[+-]?\d+)?|[A-Za-z_][A-Za-z0-9_]*|[-+*/%^(),]/gi) ?? [];
  if (toks.join('').replace(/\s/g, '') !== src.replace(/\s/g, '')) throw new Error(`cannot read the expression "${src}"`);
  let i = 0;
  const peek = () => toks[i];
  const next = () => toks[i++];
  const expect = (t: string) => {
    if (next() !== t) throw new Error(`expected "${t}" in "${src}"`);
  };
  const primary = (): number => {
    const t = next();
    if (t === undefined) throw new Error(`unexpected end of "${src}"`);
    if (t === '(') {
      const v = sum();
      expect(')');
      return v;
    }
    if (t === '-') return -power();
    if (t === '+') return power();
    if (/^[\d.]/.test(t)) return Number(t);
    if (peek() === '(') {
      next();
      const args: number[] = [];
      if (peek() !== ')')
        for (;;) {
          args.push(sum());
          if (peek() === ',') next();
          else break;
        }
      expect(')');
      const f = FUNCS[t];
      if (!f) throw new Error(`unknown function ${t}`);
      return f(...args);
    }
    if (t === 'pi') return Math.PI;
    if (!(t in vars)) throw new Error(`unknown name "${t}" in "${src}"`);
    const v = Number(vars[t]);
    if (!Number.isFinite(v)) throw new Error(`"${t}" is not a number`);
    return v;
  };
  const power = (): number => {
    const b = primary();
    if (peek() === '^') {
      next();
      return b ** power();
    }
    return b;
  };
  const product = (): number => {
    let v = power();
    while (peek() === '*' || peek() === '/' || peek() === '%') {
      const op = next();
      const r = power();
      v = op === '*' ? v * r : op === '/' ? v / r : v % r;
    }
    return v;
  };
  const sum = (): number => {
    let v = product();
    while (peek() === '+' || peek() === '-') v = next() === '+' ? v + product() : v - product();
    return v;
  };
  const v = sum();
  if (i < toks.length) throw new Error(`unexpected "${toks[i]}" in "${src}"`);
  return v;
}

const TEXT_KEYS = new Set(['id', 'op', 'note', 'by', 'code', 'source', 'name', 'brush', 'shape', 'type', 'mode', 'pattern', 'falloff', 'keep', 'axis']);

/** Replace "$name" and "= expr" by numbers, everywhere in an op. */
export function resolveOp(op: Op, params: Record<string, unknown>): Op {
  const walk = (v: any, key: string): any => {
    if (typeof v === 'string' && !TEXT_KEYS.has(key)) {
      const s = v.trim();
      if (s.startsWith('$')) {
        const name = s.slice(1);
        if (!(name in params)) throw new Error(`unknown parameter "${name}"`);
        return params[name];
      }
      if (s.startsWith('=')) return evalExpr(s.slice(1), params);
      return v;
    }
    if (Array.isArray(v)) return v.map((x) => walk(x, key));
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x, k)]));
    return v;
  };
  return walk(op, '');
}

// ---------------------------------------------------------------- incremental replay
// Surfaces after ops, keyed by a hash of everything that led to them. Shared by all
// documents in this worker; least recently used states go first.
const states = new Map<string, TriMesh>();
let stateBytes = 0;
export const MESH_CACHE = { limit: 160e6 };

function keep(key: string, m: TriMesh) {
  if (states.has(key)) return;
  const c = cloneMesh(m);
  states.set(key, c);
  stateBytes += meshBytes(c);
  while (stateBytes > MESH_CACHE.limit && states.size > 1) {
    const [k, old] = states.entries().next().value!;
    states.delete(k);
    stateBytes -= meshBytes(old);
  }
}

function recall(key: string): TriMesh | null {
  const m = states.get(key);
  if (!m) return null;
  states.delete(key);
  states.set(key, m); // most recently used
  return cloneMesh(m);
}

export function clearMeshCache() {
  states.clear();
  stateBytes = 0;
}

export interface RunInfo {
  ops: number;
  replayed: number; // ops actually computed (the rest came from the cache)
  ms: number[];
}

/** What the last replay in this worker did (for tests and timing). */
export const lastRun: RunInfo = { ops: 0, replayed: 0, ms: [] };

export function runMeshDoc(doc: MeshDoc, params: Record<string, unknown>, ctx: OpContext, inputsKey: string, info: RunInfo = lastRun): TriMesh {
  const ops = doc.ops.filter((o) => o.enabled !== false);
  const resolved: Op[] = [];
  ops.forEach((op, i) => {
    try {
      resolved.push(resolveOp(op, params));
    } catch (e: any) {
      throw new ProgramError('build', `op ${i + 1} (${op.id ?? op.op}): ${e?.message ?? e}`);
    }
  });
  if (!resolved.length) throw new ProgramError('build', 'the mesh document has no enabled ops');
  if (!SOURCES.has(resolved[0].op)) throw new ProgramError('build', `the first op must be clay, import or program, not ${resolved[0].op}`);
  // chain of keys: each state depends on everything before it
  const keys: string[] = [];
  let prev = hashString(`${doc.symmetry ?? ''}|${doc.detail ?? ''}|${detail.factor}|${inputsKey}`);
  for (const op of resolved) {
    const { note: _n, by: _b, id: _i, ...shape } = op;
    prev = hashString(prev + JSON.stringify(shape));
    keys.push(prev);
  }
  let start = keys.length;
  let mesh: TriMesh | null = null;
  while (start > 0) {
    mesh = recall(keys[start - 1]);
    if (mesh) break;
    start--;
  }
  info.ops = resolved.length;
  info.replayed = resolved.length - start;
  info.ms = [];
  for (let i = start; i < resolved.length; i++) {
    const t0 = Date.now();
    try {
      mesh = applyOp(ctx, resolved[i], mesh);
    } catch (e: any) {
      throw new ProgramError('build', `op ${i + 1} (${resolved[i].id ?? resolved[i].op}): ${e?.message ?? e}`);
    }
    info.ms.push(Date.now() - t0);
    // cache after slow ops, right before the last op (tuning it replays one step) and at the end
    if (EXPENSIVE.has(resolved[i].op) || i >= resolved.length - 2 || i === start) keep(keys[i], mesh);
  }
  return mesh!;
}

// ---------------------------------------------------------------- as a Program
function autoEdge(box: { min: V3; max: V3 }) {
  const diag = Math.hypot(box.max[0] - box.min[0], box.max[1] - box.min[1], box.max[2] - box.min[2]);
  return Math.min(2, Math.max(0.35, diag / 140));
}

export function compileMeshDoc(source: string, wasm: Wasm, evaluator: Evaluator): Program {
  const doc = parseMeshDoc(source);
  const sdf = makeSdf(wasm);
  const program: Program = {
    meta: { ...(doc.meta ?? {}) },
    params: doc.params ?? {},
    build: (p: Record<string, any>, lib: any) => {
      const inputs = lib.inputs ?? {};
      const ctx: OpContext = {
        wasm,
        sdf,
        symmetry: doc.symmetry ?? null,
        edgeFor: (box) => (doc.detail ? Number(doc.detail) : autoEdge(box)),
        importMesh: (name) => {
          const m = inputs.meshes?.[name];
          if (!m) throw new Error(`no imported mesh "${name}"; available: ${Object.keys(inputs.meshes ?? {}).join(', ') || 'none'}`);
          return fromSolid(lib.mesh.fromArrays(m.positions, m.triangles));
        },
        runProgram: (src, params) => {
          const prog = validateProgram(evaluator.compile(src));
          const out = buildProgram(wasm, evaluator, prog, params, { printer: lib.printer, inputs, quality: lib.quality });
          try {
            return fromSolid(out.body);
          } finally {
            disposeBuild(out);
          }
        },
        runScript: (code, m) => {
          const fn = evaluator.compile(`return { meta: {}, params: {}, build: (${code}) };`).build as any;
          const mesh = { pos: m.pos, tris: m.tris };
          const r = evaluator.call(() => fn(mesh, lib, p));
          const out = r && typeof r === 'object' && 'pos' in r ? (r as TriMesh) : mesh;
          if (!(out.pos instanceof Float64Array)) out.pos = Float64Array.from(out.pos as ArrayLike<number>);
          if (!(out.tris instanceof Uint32Array)) out.tris = Uint32Array.from(out.tris as ArrayLike<number>);
          return out;
        },
      };
      const inputsKey = inputs.meshes ? Object.keys(inputs.meshes).sort().map((k) => `${k}:${inputs.meshes[k].positions?.length}`).join(',') : '';
      const mesh = runMeshDoc(doc, p, ctx, inputsKey);
      const solid = toSolid(wasm, mesh);
      return doc.meta?.color ? lib.part(solid, { name: 'body', color: doc.meta.color }) : solid;
    },
  };
  return program;
}
