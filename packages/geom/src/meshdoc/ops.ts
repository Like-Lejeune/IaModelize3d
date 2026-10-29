// Operations of the mesh engine. Each takes the current surface (or null before the first
// one) and returns the next; vertex edits work in place on a copy the runner owns.
import { detail, type Manifold, type Wasm } from '../kernel.ts';
import { makeNoise } from '../lib/forms.ts';
import { makeSdf, smin, type Field } from '../lib/sdf.ts';
import {
  adjacency,
  bounds,
  fromSolid,
  loopSubdivide,
  meanEdge,
  meshField,
  refine,
  relaxTangential,
  taubin,
  toSolid,
  vertexNormals,
  type TriMesh,
  type V3,
  type Weights,
} from './trimesh.ts';

export type Op = Record<string, any> & { op: string; id?: string; enabled?: boolean; note?: string };

export interface OpContext {
  wasm: Wasm;
  sdf: ReturnType<typeof makeSdf>;
  symmetry: 'x' | 'y' | null;
  /** Default triangle size for clay and remesh (doc.detail or chosen from the size), mm. */
  edgeFor: (box: { min: V3; max: V3 }) => number;
  importMesh: (name: string) => TriMesh;
  runProgram: (source: string, params: Record<string, any>) => TriMesh;
  runScript: (code: string, mesh: TriMesh) => TriMesh;
}

const clamp = (v: number, a: number, b: number) => (v < a ? a : v > b ? b : v);
const smooth01 = (t: number) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));
const num = (v: unknown, name: string, fallback?: number): number => {
  if (v === undefined || v === null) {
    if (fallback !== undefined) return fallback;
    throw new Error(`${name} is required`);
  }
  const n = Number(v);
  if (!Number.isFinite(n)) throw new Error(`${name} must be a number, got ${JSON.stringify(v)}`);
  return n;
};
const vec = (v: unknown, name: string, fallback?: V3): V3 => {
  if (v === undefined || v === null) {
    if (fallback) return fallback;
    throw new Error(`${name} is required ([x, y, z])`);
  }
  if (typeof v === 'number') return [v, v, v];
  if (!Array.isArray(v) || v.length !== 3) throw new Error(`${name} must be [x, y, z], got ${JSON.stringify(v)}`);
  return v.map((x, i) => num(x, `${name}[${i}]`)) as V3;
};
const axisVec = (a: unknown): V3 => (a === 'x' ? [1, 0, 0] : a === 'y' ? [0, 1, 0] : a === 'z' || a === undefined ? [0, 0, 1] : vec(a, 'axis'));
const len = (v: V3) => Math.hypot(v[0], v[1], v[2]);
const growBox = (b: { min: V3; max: V3 }, d: number) => ({ min: b.min.map((v) => v - d) as V3, max: b.max.map((v) => v + d) as V3 });
const mergeBox = (a: { min: V3; max: V3 }, b: { min: V3; max: V3 }) => ({
  min: [0, 1, 2].map((k) => Math.min(a.min[k], b.min[k])) as V3,
  max: [0, 1, 2].map((k) => Math.max(a.max[k], b.max[k])) as V3,
});

// ---------------------------------------------------------------- meshing fields
// Distance queries cost per nearby triangle, and marching tetrahedra leaves flat areas far
// denser than needed: the field is taken from a simplified copy (within edge/20 of the surface).
function fieldOf(ctx: OpContext, m: TriMesh, edge: number, band: number, maxBand = band) {
  let src = m;
  if (m.tris.length / 3 > 15000) {
    const s = toSolid(ctx.wasm, m);
    const lean = s.simplify(edge / 20);
    if (lean.numTri() < (m.tris.length / 3) * 0.8) src = fromSolid(lean);
    lean.delete();
    s.delete();
  }
  return meshField(src, band, maxBand);
}

function levelSet(ctx: OpContext, f: (x: number, y: number, z: number) => number, box: { min: V3; max: V3 }, edge: number): TriMesh {
  const size = [0, 1, 2].map((k) => box.max[k] - box.min[k]);
  if (size.some((v) => !(v > 0) || !Number.isFinite(v))) throw new Error('nothing to mesh (empty or unbounded shape)');
  const cap = 1.6e6 / detail.factor ** 3;
  const cells = (size[0] * size[1] * size[2]) / edge ** 3;
  if (cells > cap) edge *= Math.cbrt(cells / cap);
  const b = growBox(box, edge * 2);
  const m = (ctx.wasm.Manifold as any).levelSet((p: V3) => -f(p[0], p[1], p[2]), b, edge, 0, edge / 20) as Manifold;
  if (m.isEmpty()) throw new Error('the result is empty');
  const out = fromSolid(m);
  m.delete();
  return out;
}

export function shapeField(sdf: OpContext['sdf'], s: Record<string, any>): Field {
  const type = String(s.shape ?? s.type ?? 'sphere');
  let f: Field;
  if (type === 'sphere') f = sdf.sphere(num(s.d ?? (s.r !== undefined ? s.r * 2 : undefined), 'sphere d'));
  else if (type === 'ellipsoid') f = sdf.ellipsoid(vec(s.size, 'ellipsoid size'));
  else if (type === 'box') f = sdf.box(vec(s.size, 'box size'), { r: num(s.r, 'r', 0) });
  else if (type === 'cylinder') f = sdf.cylinder(num(s.d, 'cylinder d'), num(s.h, 'cylinder h'), { r: num(s.r, 'r', 0) });
  else if (type === 'cone') f = sdf.cone(num(s.d1, 'cone d1'), num(s.d2, 'cone d2'), num(s.h, 'cone h'));
  else if (type === 'capsule') return sdf.capsule(vec(s.from, 'capsule from'), vec(s.to, 'capsule to'), num(s.d, 'capsule d'));
  else if (type === 'torus') f = sdf.torus(num(s.D, 'torus D'), num(s.d, 'torus d'));
  else throw new Error(`unknown shape "${type}" (sphere, ellipsoid, box, cylinder, cone, capsule, torus)`);
  if (s.rotate) f = f.rotate(vec(s.rotate, 'rotate'));
  return f.translate(vec(s.at, 'at', [0, 0, 0]));
}

// The same shape on the other side of the symmetry plane (Euler angles flip with the mirror).
function mirrorShape(s: Record<string, any>, axis: number): Record<string, any> {
  const flip = (p: unknown) => (Array.isArray(p) && p.length === 3 ? p.map((v, k) => (k === axis ? -v : v)) : p);
  const out: Record<string, any> = { ...s, at: flip(s.at), from: flip(s.from), to: flip(s.to) };
  if (Array.isArray(s.rotate)) out.rotate = s.rotate.map((v: number, k: number) => (k === axis ? v : -v));
  return out;
}

function blob(ctx: OpContext, op: Op): Field {
  let shapes: Record<string, any>[] = Array.isArray(op.shapes) ? op.shapes : [op];
  if (!shapes.length) throw new Error('clay needs shapes');
  const axis = ctx.symmetry === 'x' ? 0 : ctx.symmetry === 'y' ? 1 : -1;
  if (axis >= 0 && op.mirror !== false) {
    const off = (s: Record<string, any>) => [s.at, s.from, s.to].some((p) => Array.isArray(p) && Math.abs(Number(p[axis])) > 1e-6);
    shapes = [...shapes, ...shapes.filter(off).map((s) => mirrorShape(s, axis))];
  }
  const fields = shapes.map((s) => shapeField(ctx.sdf, s));
  const k = num(op.smooth, 'smooth', 0);
  return k > 0 ? fields.slice(1).reduce((a, f) => a.smoothUnion(f, k), fields[0]) : fields.length > 1 ? fields[0].union(...fields.slice(1)) : fields[0];
}

/** Add or carve clay: smooth primitives blended into the surface, then one clean remesh. */
function clay(ctx: OpContext, op: Op, m: TriMesh | null): TriMesh {
  const b = blob(ctx, op);
  const mode = op.mode ?? (m ? 'add' : 'replace');
  if (!m || mode === 'replace') {
    const edge = num(op.detail, 'detail', ctx.edgeFor(b.box)) * detail.factor;
    return levelSet(ctx, (x, y, z) => b.f(x, y, z), b.box, edge);
  }
  const box = bounds(m);
  const edge = num(op.detail, 'detail', ctx.edgeFor(mergeBox(box, b.box))) * detail.factor;
  const k = Math.max(0, num(op.blend, 'blend', 0));
  const near = edge * 1.2;
  const mf = fieldOf(ctx, m, edge, near, k + near);
  // exact mesh distance is needed only near its surface, and up to k where the blend happens
  const md = (x: number, y: number, z: number, bv: number) => {
    let d = mf.at(x, y, z);
    if (k > 0 && Math.abs(d) >= near - 1e-9 && Math.abs(bv - d) < k + near) d = mf.at(x, y, z, k + near);
    return d;
  };
  let f: (x: number, y: number, z: number) => number;
  if (mode === 'add') f = (x, y, z) => {
    const bv = b.f(x, y, z);
    const d = md(x, y, z, bv);
    return k > 0 ? smin(d, bv, k) : Math.min(d, bv);
  };
  else if (mode === 'subtract') f = (x, y, z) => {
    const bv = -b.f(x, y, z);
    const d = md(x, y, z, bv);
    return k > 0 ? -smin(-d, -bv, k) : Math.max(d, bv);
  };
  else throw new Error(`clay mode must be add, subtract or replace, got "${mode}"`);
  return levelSet(ctx, f, mode === 'add' ? growBox(mergeBox(box, b.box), k / 4) : box, edge);
}

function remeshField(ctx: OpContext, m: TriMesh, edge: number, shape: (d: number) => number, reach: number, box = bounds(m)) {
  const mf = fieldOf(ctx, m, edge, edge * 1.2 + reach);
  return levelSet(ctx, (x, y, z) => shape(mf.at(x, y, z)), growBox(box, Math.max(0, reach)), edge);
}

// ---------------------------------------------------------------- regions and symmetry
const falloffFn = (kind: unknown) =>
  kind === 'sharp' ? (t: number) => (t >= 1 ? 0 : (1 - t) * (1 - t)) : kind === 'flat' ? (t: number) => (t <= 0.6 ? 1 : smooth01((1 - t) / 0.4)) : (t: number) => smooth01(1 - t);

/**
 * Where an op acts, as a weight per vertex: {at, radius} (soft ball), {box: [min, max]} or
 * {min, max} (box, `falloff` mm soft edge), {plane: {normal, offset}} (the side the normal
 * points to, soft by `falloff`). No region = everywhere.
 */
function regionWeight(r: any, falloff: unknown): ((p: V3) => number) | null {
  if (!r || r === 'all' || r.all) return null;
  const soft = num(r.falloff ?? falloff, 'falloff', 0);
  if (r.at !== undefined) {
    const c = vec(r.at, 'region.at'), R = num(r.radius, 'region.radius');
    const fo = falloffFn(r.shape);
    return (p) => fo(Math.hypot(p[0] - c[0], p[1] - c[1], p[2] - c[2]) / R);
  }
  if (r.box || (r.min && r.max)) {
    const a = vec(r.box ? r.box[0] : r.min, 'region.min'), b = vec(r.box ? r.box[1] : r.max, 'region.max');
    const lo = [0, 1, 2].map((k) => Math.min(a[k], b[k])), hi = [0, 1, 2].map((k) => Math.max(a[k], b[k]));
    return (p) => {
      const dx = Math.max(lo[0] - p[0], 0, p[0] - hi[0]), dy = Math.max(lo[1] - p[1], 0, p[1] - hi[1]), dz = Math.max(lo[2] - p[2], 0, p[2] - hi[2]);
      const d = Math.hypot(dx, dy, dz);
      return d === 0 ? 1 : soft > 0 ? smooth01(1 - d / soft) : 0;
    };
  }
  if (r.plane) {
    const n = vec(r.plane.normal, 'plane.normal'), o = num(r.plane.offset, 'plane.offset', 0);
    const l = len(n) || 1;
    return (p) => {
      const d = (p[0] * n[0] + p[1] * n[1] + p[2] * n[2]) / l - o;
      return d >= 0 ? 1 : soft > 0 ? smooth01(1 + d / soft) : 0;
    };
  }
  throw new Error('region must be {at, radius}, {min, max}, {box: [min, max]} or {plane: {normal, offset}}');
}

function weights(m: TriMesh, wf: ((p: V3) => number) | null, mask: Uint8Array | null): Weights {
  if (!wf && !mask) return null;
  const nv = m.pos.length / 3;
  const w = new Float32Array(nv);
  for (let i = 0; i < nv; i++) {
    if (mask && !mask[i]) continue;
    w[i] = wf ? wf([m.pos[i * 3], m.pos[i * 3 + 1], m.pos[i * 3 + 2]]) : 1;
  }
  return w;
}

// Mirror an op's geometry (points, directions, regions) across the symmetry plane.
function mirrorOp(op: any, axis: number): any {
  const pointKeys = new Set(['at', 'to', 'from', 'center', 'min', 'max', 'offset', 'dir', 'normal', 'translate']);
  const walk = (v: any, key: string): any => {
    if (Array.isArray(v)) {
      if (pointKeys.has(key) && v.length === 3 && v.every((x) => typeof x === 'number')) {
        const out = [...v];
        out[axis] = -out[axis];
        return out;
      }
      if (key === 'path' || key === 'box') return v.map((p) => walk(p, 'at'));
      return v.map((x) => walk(x, key));
    }
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, k === 'offset' && typeof x === 'number' ? x : walk(x, k)]));
    return v;
  };
  const out = walk(op, '');
  // a mirrored rotation turns the other way around the mirrored axis
  if (op.op === 'rotate') {
    const ax = axisVec(op.axis);
    ax[axis] = -ax[axis];
    out.axis = ax;
    out.angle = typeof op.angle === 'number' ? -op.angle : op.angle;
  }
  return out;
}

// Which side of the symmetry plane an op is anchored on (its first point).
function anchor(op: any): V3 | null {
  const r = op.region ?? op;
  const p = op.at ?? op.path?.[0] ?? op.strokes?.[0]?.at ?? op.strokes?.[0]?.path?.[0] ?? r?.at ?? (r?.min && r?.max ? r.min.map((v: number, k: number) => (v + r.max[k]) / 2) : null);
  return Array.isArray(p) && p.length === 3 ? (p as V3) : null;
}

/**
 * Runs a vertex op symmetrically: the version anchored on the + side moves the + half,
 * its mirror image moves the - half. Ops straddling the plane therefore never act twice.
 */
function symmetric(ctx: OpContext, op: Op, m: TriMesh, run: (op: any, mask: Uint8Array | null) => void) {
  const axis: number = ctx.symmetry === 'x' ? 0 : ctx.symmetry === 'y' ? 1 : -1;
  const a = anchor(op);
  // an op without a place (smoothing everything) is symmetric already
  if (axis < 0 || op.mirror === false || (!a && !op.region)) return run(op, null);
  const base = a && (a as number[])[axis] < 0 ? mirrorOp(op, axis) : op;
  const nv = m.pos.length / 3;
  const plus = new Uint8Array(nv), minus = new Uint8Array(nv);
  for (let i = 0; i < nv; i++) (m.pos[i * 3 + axis] >= 0 ? plus : minus)[i] = 1;
  run(base, plus);
  run(mirrorOp(base, axis), minus);
}

// ---------------------------------------------------------------- sculpt brushes
type Brush = 'grab' | 'draw' | 'inflate' | 'crease' | 'smooth' | 'flatten' | 'pinch';
const BRUSHES: Brush[] = ['grab', 'draw', 'inflate', 'crease', 'smooth', 'flatten', 'pinch'];

function dabsOf(s: any): { centres: V3[]; spacing: number; R: number } {
  const R = num(s.radius, 'radius');
  if (!(R > 0)) throw new Error('radius must be > 0');
  if (s.path) {
    const path = (s.path as unknown[]).map((p, i) => vec(p, `path[${i}]`));
    if (!path.length) throw new Error('path is empty');
    const spacing = R / 3;
    const centres: V3[] = [path[0]];
    for (let i = 1; i < path.length; i++) {
      const a = path[i - 1], b = path[i];
      const k = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]) / spacing));
      for (let j = 1; j <= k; j++) centres.push([a[0] + ((b[0] - a[0]) * j) / k, a[1] + ((b[1] - a[1]) * j) / k, a[2] + ((b[2] - a[2]) * j) / k]);
    }
    return { centres, spacing, R };
  }
  return { centres: [vec(s.at, 'at')], spacing: 0, R };
}

// Uniform grid over vertices for brush queries.
function vertexGrid(pos: Float64Array, cell: number) {
  const map = new Map<string, number[]>();
  const key = (x: number, y: number, z: number) => `${Math.floor(x / cell)},${Math.floor(y / cell)},${Math.floor(z / cell)}`;
  for (let i = 0; i < pos.length / 3; i++) {
    const k = key(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
    let b = map.get(k);
    if (!b) map.set(k, (b = []));
    b.push(i);
  }
  return (c: V3, r: number) => {
    const out: number[] = [];
    const n = Math.ceil(r / cell);
    const ci = Math.floor(c[0] / cell), cj = Math.floor(c[1] / cell), ck = Math.floor(c[2] / cell);
    for (let i = ci - n; i <= ci + n; i++)
      for (let j = cj - n; j <= cj + n; j++)
        for (let k = ck - n; k <= ck + n; k++) {
          const b = map.get(`${i},${j},${k}`);
          if (b) for (const v of b) out.push(v);
        }
    return out;
  };
}

function stroke(m: TriMesh, s: any, mask: Uint8Array | null) {
  const brush = String(s.brush ?? 'draw') as Brush;
  if (!BRUSHES.includes(brush)) throw new Error(`unknown brush "${brush}" (${BRUSHES.join(', ')})`);
  const { centres, spacing, R } = dabsOf(s);
  const fo = falloffFn(s.falloff);
  const pos = m.pos;
  const find = vertexGrid(pos, R);
  const { off, nb } = adjacency(m);
  let dir: V3 | null = s.dir ? vec(s.dir, 'dir') : null;
  let strength = num(s.strength, 'strength', brush === 'smooth' || brush === 'flatten' || brush === 'pinch' ? 0.5 : 1);
  if (brush === 'grab' && s.to) {
    const to = vec(s.to, 'to');
    dir = [to[0] - centres[0][0], to[1] - centres[0][1], to[2] - centres[0][2]];
    strength = s.strength === undefined ? len(dir) : strength;
  }
  // along a path each dab adds a share, so the centre line gets about `strength` in total
  const k = spacing ? (strength * spacing) / R : strength;
  for (const c of centres) {
    const hit = find(c, R * 1.25).filter((i) => (!mask || mask[i]) && Math.hypot(pos[i * 3] - c[0], pos[i * 3 + 1] - c[1], pos[i * 3 + 2] - c[2]) < R);
    if (!hit.length) continue;
    const w = hit.map((i) => fo(Math.hypot(pos[i * 3] - c[0], pos[i * 3 + 1] - c[1], pos[i * 3 + 2] - c[2]) / R));
    const n = vertexNormals(m);
    const an: V3 = [0, 0, 0], ap: V3 = [0, 0, 0];
    let ws = 0;
    hit.forEach((i, j) => {
      for (let a = 0; a < 3; a++) {
        an[a] += n[i * 3 + a] * w[j];
        ap[a] += pos[i * 3 + a] * w[j];
      }
      ws += w[j];
    });
    const nl = len(an) || 1;
    for (let a = 0; a < 3; a++) {
      an[a] /= nl;
      ap[a] /= ws || 1;
    }
    const old = brush === 'smooth' ? pos.slice() : pos;
    const d: V3 = [0, 0, 0];
    hit.forEach((i, j) => {
      const f = w[j] * k;
      const p: V3 = [old[i * 3], old[i * 3 + 1], old[i * 3 + 2]];
      if (brush === 'grab') {
        const g = dir ?? an;
        const l = len(g) || 1;
        for (let a = 0; a < 3; a++) d[a] = (g[a] / l) * f;
      } else if (brush === 'draw') {
        for (let a = 0; a < 3; a++) d[a] = an[a] * f;
      } else if (brush === 'inflate') {
        for (let a = 0; a < 3; a++) d[a] = n[i * 3 + a] * f;
      } else if (brush === 'crease') {
        // inward and toward the stroke centre: a sharp valley
        for (let a = 0; a < 3; a++) d[a] = -an[a] * f + (c[a] - p[a]) * 0.15 * w[j];
      } else if (brush === 'smooth') {
        const lo = off[i], hi = off[i + 1];
        for (let a = 0; a < 3; a++) {
          let sum = 0;
          for (let q = lo; q < hi; q++) sum += old[nb[q] * 3 + a];
          d[a] = (sum / Math.max(1, hi - lo) - p[a]) * Math.min(1, f);
        }
      } else if (brush === 'flatten') {
        const h = (p[0] - ap[0]) * an[0] + (p[1] - ap[1]) * an[1] + (p[2] - ap[2]) * an[2];
        for (let a = 0; a < 3; a++) d[a] = -an[a] * h * Math.min(1, f);
      } else {
        for (let a = 0; a < 3; a++) d[a] = (c[a] - p[a]) * Math.min(1, f) * 0.5;
        const h = d[0] * an[0] + d[1] * an[1] + d[2] * an[2];
        for (let a = 0; a < 3; a++) d[a] -= an[a] * h; // stay on the surface
      }
      pos[i * 3] = p[0] + d[0];
      pos[i * 3 + 1] = p[1] + d[1];
      pos[i * 3 + 2] = p[2] + d[2];
    });
  }
}

// Enough triangles under the brush for the detail it asks for.
function refineFor(m: TriMesh, strokes: any[], symmetryAxis: number): TriMesh {
  let out = m;
  for (const s of strokes) {
    const { centres, R } = dabsOf(s);
    const target = Math.max(0.12, (R / 4) * detail.factor);
    const all = symmetryAxis >= 0 ? [...centres, ...centres.map((c) => c.map((v, k) => (k === symmetryAxis ? -v : v)) as V3)] : centres;
    const lo = [0, 1, 2].map((k) => Math.min(...all.map((c) => c[k])) - R * 1.3);
    const hi = [0, 1, 2].map((k) => Math.max(...all.map((c) => c[k])) + R * 1.3);
    const near = (x: number, y: number, z: number) => {
      if (x < lo[0] || y < lo[1] || z < lo[2] || x > hi[0] || y > hi[1] || z > hi[2]) return false;
      for (const c of all) if (Math.hypot(x - c[0], y - c[1], z - c[2]) < R * 1.3) return true;
      return false;
    };
    out = refine(out, target, near, 1_200_000);
  }
  return out;
}

function sculpt(ctx: OpContext, op: Op, m: TriMesh): TriMesh {
  const strokes = Array.isArray(op.strokes) ? op.strokes.map((s: any) => ({ ...op, ...s, strokes: undefined })) : [op];
  const axis = ctx.symmetry === 'x' ? 0 : ctx.symmetry === 'y' ? 1 : -1;
  const out = refineFor(m, strokes, op.mirror === false ? -1 : axis);
  for (const s of strokes) symmetric(ctx, s, out, (v, mask) => stroke(out, v, mask));
  if (op.relax !== false) relaxTangential(out, 1);
  return out;
}

// ---------------------------------------------------------------- deformations
function rotateAbout(p: V3, c: V3, axis: V3, rad: number): V3 {
  const l = len(axis) || 1;
  const [ux, uy, uz] = axis.map((v) => v / l);
  const x = p[0] - c[0], y = p[1] - c[1], z = p[2] - c[2];
  const cs = Math.cos(rad), sn = Math.sin(rad), d = ux * x + uy * y + uz * z;
  return [
    c[0] + x * cs + (uy * z - uz * y) * sn + ux * d * (1 - cs),
    c[1] + y * cs + (uz * x - ux * z) * sn + uy * d * (1 - cs),
    c[2] + z * cs + (ux * y - uy * x) * sn + uz * d * (1 - cs),
  ];
}

function regionCentre(r: any, m: TriMesh): V3 {
  if (r?.at) return vec(r.at, 'region.at');
  if (r?.min && r?.max) return [0, 1, 2].map((k) => (r.min[k] + r.max[k]) / 2) as V3;
  if (r?.box) return [0, 1, 2].map((k) => (r.box[0][k] + r.box[1][k]) / 2) as V3;
  const b = bounds(m);
  return [0, 1, 2].map((k) => (b.min[k] + b.max[k]) / 2) as V3;
}

function deform(ctx: OpContext, op: Op, m: TriMesh): TriMesh {
  symmetric(ctx, op, m, (o, mask) => {
    const w = weights(m, regionWeight(o.region, o.falloff), mask);
    const pos = m.pos;
    const nv = pos.length / 3;
    const centre = o.center ? vec(o.center, 'center') : regionCentre(o.region, m);
    const off = o.op === 'move' ? vec(o.offset, 'offset') : null;
    const sc = o.op === 'scale' ? vec(o.factor, 'factor') : null;
    const axis = o.op === 'rotate' ? axisVec(o.axis) : null;
    const ang = o.op === 'rotate' ? (num(o.angle, 'angle') * Math.PI) / 180 : 0;
    for (let i = 0; i < nv; i++) {
      const f = w ? w[i] : 1;
      if (!f) continue;
      const p: V3 = [pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]];
      let q: V3;
      if (off) q = [p[0] + off[0] * f, p[1] + off[1] * f, p[2] + off[2] * f];
      else if (sc) q = [0, 1, 2].map((k) => centre[k] + (p[k] - centre[k]) * (1 + (sc[k] - 1) * f)) as V3;
      else q = rotateAbout(p, centre, axis!, ang * f);
      pos[i * 3] = q[0];
      pos[i * 3 + 1] = q[1];
      pos[i * 3 + 2] = q[2];
    }
  });
  return m;
}

// ---------------------------------------------------------------- textures
function pattern(kind: string, seed: number, octaves: number) {
  const nz = makeNoise(seed);
  if (kind === 'noise') return (x: number, y: number, z: number) => nz.fbm(x, y, z, octaves) * 2;
  if (kind === 'ridges') return (x: number, y: number, z: number) => {
    const v = 1 - Math.abs(nz.fbm(x, y, z, octaves) * 2);
    return v * v * 2 - 1;
  };
  if (kind === 'cells') {
    // Worley F1: one feature point per unit cell; raised cells with grooves between (stones, scales)
    const h = (i: number, j: number, k: number, s: number) => {
      let n = (i * 374761393 + j * 668265263 + k * 2147483647 + s * 1274126177 + seed * 97) | 0;
      n = Math.imul(n ^ (n >>> 13), 1274126177);
      return ((n ^ (n >>> 16)) >>> 0) / 4294967296;
    };
    return (x: number, y: number, z: number) => {
      const ci = Math.floor(x), cj = Math.floor(y), ck = Math.floor(z);
      let f1 = 9, f2 = 9;
      for (let i = ci - 1; i <= ci + 1; i++)
        for (let j = cj - 1; j <= cj + 1; j++)
          for (let k = ck - 1; k <= ck + 1; k++) {
            const d = Math.hypot(i + h(i, j, k, 1) - x, j + h(i, j, k, 2) - y, k + h(i, j, k, 3) - z);
            if (d < f1) {
              f2 = f1;
              f1 = d;
            } else if (d < f2) f2 = d;
          }
      return clamp((f2 - f1) * 4, 0, 1) * 2 - 1;
    };
  }
  if (kind === 'stripes') return (x: number, _y: number, z: number) => Math.sin(2 * Math.PI * z + nz.noise3(x, z, 0) * 0.5);
  throw new Error(`unknown pattern "${kind}" (noise, ridges, cells, stripes)`);
}

function displace(ctx: OpContext, op: Op, m: TriMesh): TriMesh {
  const scale = num(op.scale, 'scale', 4);
  const amp = num(op.amplitude, 'amplitude', 0.5);
  const wf = regionWeight(op.region, op.falloff);
  const fine = Math.max(0.15, num(op.detail, 'detail', scale / 4) * detail.factor);
  const out = refine(m, fine, wf ? (x, y, z) => wf([x, y, z]) > 0 : null, 1_500_000);
  const axis = op.axis ? axisVec(op.axis) : null;
  const pat = pattern(String(op.pattern ?? 'noise'), Math.round(num(op.seed, 'seed', 1)), Math.round(num(op.octaves, 'octaves', 4)));
  const n = vertexNormals(out);
  const w = weights(out, wf, null);
  const pos = out.pos;
  for (let i = 0; i < pos.length / 3; i++) {
    const f = w ? w[i] : 1;
    if (!f) continue;
    let x = pos[i * 3] / scale, y = pos[i * 3 + 1] / scale, z = pos[i * 3 + 2] / scale;
    if (axis) z = (pos[i * 3] * axis[0] + pos[i * 3 + 1] * axis[1] + pos[i * 3 + 2] * axis[2]) / (len(axis) * scale);
    const d = pat(x, y, z) * amp * f;
    pos[i * 3] += n[i * 3] * d;
    pos[i * 3 + 1] += n[i * 3 + 1] * d;
    pos[i * 3 + 2] += n[i * 3 + 2] * d;
  }
  return out;
}

// ---------------------------------------------------------------- exact (Manifold) steps
function viaSolid(ctx: OpContext, m: TriMesh, fn: (s: Manifold) => Manifold): TriMesh {
  const s = toSolid(ctx.wasm, m);
  const r = fn(s);
  if (r.isEmpty()) throw new Error('the result is empty');
  return fromSolid(r);
}

function solidShape(ctx: OpContext, s: Record<string, any>): Manifold {
  const M = ctx.wasm.Manifold as any;
  const type = String(s.shape ?? s.type ?? 'box');
  let solid: Manifold;
  if (type === 'box') solid = M.cube(vec(s.size, 'box size'), true);
  else if (type === 'cylinder') solid = M.cylinder(num(s.h, 'cylinder h'), num(s.d, 'cylinder d') / 2, num(s.d2 ?? s.d, 'cylinder d2') / 2, 0, true);
  else if (type === 'sphere') solid = M.sphere(num(s.d, 'sphere d') / 2);
  else {
    const f = shapeField(ctx.sdf, s);
    return f.mesh({ simplify: false });
  }
  if (s.rotate) solid = solid.rotate(vec(s.rotate, 'rotate'));
  return solid.translate(vec(s.at, 'at', [0, 0, 0]));
}

function transform(op: Op, m: TriMesh): TriMesh {
  const pos = m.pos;
  if (op.scale !== undefined) {
    const s = vec(op.scale, 'scale');
    for (let i = 0; i < pos.length; i++) pos[i] *= s[i % 3];
    if (s[0] * s[1] * s[2] < 0) for (let t = 0; t < m.tris.length; t += 3) [m.tris[t + 1], m.tris[t + 2]] = [m.tris[t + 2], m.tris[t + 1]];
  }
  if (op.fit) {
    const b = bounds(m);
    const size = [0, 1, 2].map((k) => b.max[k] - b.min[k]);
    const f = op.fit;
    const k = f.height !== undefined ? num(f.height, 'fit.height') / size[2] : f.width !== undefined ? num(f.width, 'fit.width') / size[0]
      : f.depth !== undefined ? num(f.depth, 'fit.depth') / size[1] : num(f.longest, 'fit.longest') / Math.max(...size);
    for (let i = 0; i < pos.length; i++) pos[i] *= k;
  }
  if (op.rotate !== undefined) {
    const r = vec(op.rotate, 'rotate');
    for (const [k, a] of [[0, r[0]], [1, r[1]], [2, r[2]]] as [number, number][]) {
      if (!a) continue;
      const axis: V3 = [0, 0, 0];
      axis[k] = 1;
      for (let i = 0; i < pos.length; i += 3) {
        const q = rotateAbout([pos[i], pos[i + 1], pos[i + 2]], [0, 0, 0], axis, (a * Math.PI) / 180);
        pos[i] = q[0];
        pos[i + 1] = q[1];
        pos[i + 2] = q[2];
      }
    }
  }
  if (op.translate !== undefined) {
    const t = vec(op.translate, 'translate');
    for (let i = 0; i < pos.length; i++) pos[i] += t[i % 3];
  }
  return m;
}

// ---------------------------------------------------------------- dispatch
export const OPS = [
  'clay', 'import', 'program', 'sculpt', 'move', 'scale', 'rotate', 'smooth', 'relax', 'inflate', 'displace', 'remesh', 'subdivide',
  'refine', 'decimate', 'mirror', 'cut', 'base', 'boolean', 'transform', 'hollow', 'offset', 'script',
] as const;

/** Ops that create a new surface from nothing (allowed as the first op). */
export const SOURCES = new Set(['clay', 'import', 'program']);
/** Ops worth a cached state after them (slow to recompute). */
export const EXPENSIVE = new Set(['clay', 'import', 'program', 'remesh', 'subdivide', 'displace', 'hollow', 'offset', 'boolean', 'mirror', 'decimate', 'script']);

export function applyOp(ctx: OpContext, op: Op, m: TriMesh | null): TriMesh {
  const kind = op.op;
  if (!m && !SOURCES.has(kind)) throw new Error(`there is no surface yet: start with clay, import or program, not ${kind}`);
  switch (kind) {
    case 'clay':
      return clay(ctx, op, m);
    case 'import':
      return ctx.importMesh(String(op.name));
    case 'program':
      return ctx.runProgram(String(op.source ?? ''), op.params ?? {});
    case 'sculpt':
      return sculpt(ctx, op, m!);
    case 'move':
    case 'scale':
    case 'rotate':
      return deform(ctx, op, m!);
    case 'smooth':
    case 'relax':
    case 'inflate': {
      symmetric(ctx, op, m!, (o, mask) => {
        const w = weights(m!, regionWeight(o.region, o.falloff), mask);
        if (kind === 'smooth') taubin(m!, Math.round(num(o.iterations, 'iterations', 5)), num(o.strength, 'strength', 0.5), w);
        else if (kind === 'relax') relaxTangential(m!, Math.round(num(o.iterations, 'iterations', 5)), w);
        else {
          const n = vertexNormals(m!);
          const d = num(o.amount, 'amount');
          for (let i = 0; i < m!.pos.length / 3; i++) {
            const f = (w ? w[i] : 1) * d;
            m!.pos[i * 3] += n[i * 3] * f;
            m!.pos[i * 3 + 1] += n[i * 3 + 1] * f;
            m!.pos[i * 3 + 2] += n[i * 3 + 2] * f;
          }
        }
      });
      return m!;
    }
    case 'displace':
      return displace(ctx, op, m!);
    case 'remesh': {
      const edge = num(op.detail, 'detail', ctx.edgeFor(bounds(m!))) * detail.factor;
      return remeshField(ctx, m!, edge, (d) => d, 0);
    }
    case 'offset': {
      const d = num(op.distance, 'distance');
      const edge = num(op.detail, 'detail', ctx.edgeFor(bounds(m!))) * detail.factor;
      return remeshField(ctx, m!, edge, (v) => v - d, Math.abs(d));
    }
    case 'hollow': {
      const wall = num(op.wall, 'wall', 2);
      if (wall < 0.8) throw new Error('wall must be at least 0.8 mm to print');
      // the outside stays exactly as it is; only the hidden cavity is meshed, coarsely
      const box = bounds(m!);
      const edge = Math.max(num(op.detail, 'detail', ctx.edgeFor(box)) * 2, wall * 0.6) * detail.factor;
      const mf = fieldOf(ctx, m!, edge, wall + edge * 1.5);
      const inner = { min: box.min.map((v) => v + wall) as V3, max: box.max.map((v) => v - wall) as V3 };
      let cavity: TriMesh;
      try {
        cavity = levelSet(ctx, (x, y, z) => mf.at(x, y, z) + wall, inner, edge);
      } catch {
        throw new Error(`the model is nowhere thicker than two walls (${wall * 2} mm): nothing to hollow`);
      }
      let out = viaSolid(ctx, m!, (s) => s.subtract(toSolid(ctx.wasm, cavity)));
      if (op.drain) {
        const b = bounds(out);
        const dd = num(op.drain, 'drain');
        const c = [(b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2];
        out = viaSolid(ctx, out, (s) => s.subtract((ctx.wasm.Manifold as any).cylinder(wall * 2 + 2, dd / 2, dd / 2, 0, false).translate([c[0], c[1], b.min[2] - 1])));
      }
      return out;
    }
    case 'subdivide': {
      let out = m!;
      const levels = Math.round(num(op.levels, 'levels', 1));
      for (let i = 0; i < Math.min(3, levels); i++) {
        if (out.tris.length / 3 > 600_000) break;
        if (op.smooth === false) out = refine(out, meanEdge(out) * 0.55, null);
        else out = loopSubdivide(out);
      }
      return out;
    }
    case 'refine': {
      const wf = regionWeight(op.region, op.falloff);
      const edge = Math.max(0.1, num(op.edge, 'edge') * detail.factor);
      return refine(m!, edge, wf ? (x, y, z) => wf([x, y, z]) > 0 : null);
    }
    case 'decimate':
      return viaSolid(ctx, m!, (s) => s.simplify(num(op.tolerance, 'tolerance', 0.05)));
    case 'mirror': {
      const axis = 'xyz'.indexOf(String(op.axis ?? ctx.symmetry ?? 'x'));
      if (axis < 0) throw new Error('axis must be x, y or z');
      const n: V3 = [0, 0, 0];
      n[axis] = op.keep === '-' ? -1 : 1;
      return viaSolid(ctx, m!, (s) => {
        const half = s.trimByPlane(n, 0);
        const flip: V3 = [0, 0, 0];
        flip[axis] = 1;
        return half.add(half.mirror(flip));
      });
    }
    case 'cut': {
      const p = op.plane ?? op;
      return viaSolid(ctx, m!, (s) => s.trimByPlane(vec(p.normal, 'plane.normal'), num(p.offset, 'plane.offset', 0)));
    }
    case 'base': {
      const b = bounds(m!);
      const z = op.z !== undefined ? num(op.z, 'z') : b.min[2] + num(op.depth, 'depth', 1);
      return viaSolid(ctx, m!, (s) => s.trimByPlane([0, 0, 1], z));
    }
    case 'boolean': {
      const mode = String(op.mode ?? 'subtract');
      const shapes: Record<string, any>[] = Array.isArray(op.shapes) ? op.shapes : [op.shape ?? op];
      return viaSolid(ctx, m!, (s) => {
        let r = s;
        for (const sh of shapes) {
          const t = solidShape(ctx, sh);
          r = mode === 'add' ? r.add(t) : mode === 'intersect' ? r.intersect(t) : r.subtract(t);
        }
        return r;
      });
    }
    case 'transform':
      return transform(op, m!);
    case 'script':
      return ctx.runScript(String(op.code ?? ''), m!);
    default:
      throw new Error(`unknown op "${kind}"; ops: ${OPS.join(', ')}`);
  }
}

/** Where an op acts, for markers on renders and for the editor. */
export function opAnchor(op: Op): V3 | null {
  if (op.op === 'clay') {
    const s = Array.isArray(op.shapes) ? op.shapes[0] : op;
    if (s?.at) return s.at;
    if (s?.from) return s.from;
    return null;
  }
  return anchor(op);
}
