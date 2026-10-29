// Direct mesh work: build solids from vertex arrays, edit vertices (relax, inflate,
// displace, sculpt brushes) and bring in imported meshes. Topology is kept, so every
// result is still a closed manifold that the printability checks understand.
// This is also the toolbox of the mesh engine (editing a mesh instead of a program).
import type { Manifold, Wasm } from '../kernel.ts';
import { detail } from '../kernel.ts';

type V3 = [number, number, number];

export interface RawMesh {
  positions: ArrayLike<number>; // xyz per vertex
  triangles: ArrayLike<number>; // 3 vertex indices per triangle
}

// Signed volume of a triangle soup (positive when faces point outward).
export function signedVolume(pos: ArrayLike<number>, tris: ArrayLike<number>) {
  let v = 0;
  for (let t = 0; t < tris.length; t += 3) {
    const a = tris[t] * 3, b = tris[t + 1] * 3, c = tris[t + 2] * 3;
    v += pos[a] * (pos[b + 1] * pos[c + 2] - pos[b + 2] * pos[c + 1])
      - pos[a + 1] * (pos[b] * pos[c + 2] - pos[b + 2] * pos[c])
      + pos[a + 2] * (pos[b] * pos[c + 1] - pos[b + 1] * pos[c]);
  }
  return v / 6;
}

// Ear clipping for one simple polygon (any winding). Returns triangles as index triples,
// counter-clockwise. Fine for the few hundred points of a loft or sweep cap.
export function earcut(pts: [number, number][]): number[] {
  const n = pts.length;
  let area = 0;
  for (let i = 0, j = n - 1; i < n; j = i++) area += pts[j][0] * pts[i][1] - pts[i][0] * pts[j][1];
  const idx = Array.from({ length: n }, (_, i) => i);
  if (area < 0) idx.reverse();
  const cross = (a: number, b: number, c: number) =>
    (pts[b][0] - pts[a][0]) * (pts[c][1] - pts[a][1]) - (pts[b][1] - pts[a][1]) * (pts[c][0] - pts[a][0]);
  const inside = (p: number, a: number, b: number, c: number) =>
    cross(a, b, p) >= 0 && cross(b, c, p) >= 0 && cross(c, a, p) >= 0;
  const out: number[] = [];
  let guard = 0;
  while (idx.length > 3 && guard++ < n * n) {
    let clipped = false;
    for (let i = 0; i < idx.length; i++) {
      const a = idx[(i + idx.length - 1) % idx.length], b = idx[i], c = idx[(i + 1) % idx.length];
      if (cross(a, b, c) <= 1e-12) continue;
      let ear = true;
      for (const p of idx) {
        if (p === a || p === b || p === c) continue;
        if (inside(p, a, b, c)) {
          ear = false;
          break;
        }
      }
      if (!ear) continue;
      out.push(a, b, c);
      idx.splice(i, 1);
      clipped = true;
      break;
    }
    if (!clipped) {
      // degenerate leftovers (collinear points): fan them
      for (let i = 1; i < idx.length - 1; i++) out.push(idx[0], idx[i], idx[i + 1]);
      return out;
    }
  }
  if (idx.length === 3) out.push(idx[0], idx[1], idx[2]);
  return out;
}

export function solidFromArrays(wasm: Wasm, positions: ArrayLike<number>, triangles: ArrayLike<number>): Manifold {
  const { Manifold: M, Mesh } = wasm as any;
  let tris = Uint32Array.from(triangles as ArrayLike<number>);
  if (signedVolume(positions, tris) < 0) {
    tris = tris.slice();
    for (let t = 0; t < tris.length; t += 3) [tris[t + 1], tris[t + 2]] = [tris[t + 2], tris[t + 1]];
  }
  const mesh = new Mesh({ numProp: 3, vertProperties: Float32Array.from(positions as ArrayLike<number>), triVerts: tris });
  mesh.merge();
  const m = M.ofMesh(mesh);
  const status = m.status();
  if (status !== 'NoError') throw new Error(`mesh is not a closed manifold (${status}); close holes or weld vertices first`);
  return m;
}

// Unique vertices of a solid (property seams merged) and triangles over them.
export function weld(solid: Manifold): { pos: Float64Array; tris: Uint32Array } {
  const m = solid.getMesh();
  const np = m.numProp;
  const nv = m.vertProperties.length / np;
  const canon = new Int32Array(nv);
  for (let i = 0; i < nv; i++) canon[i] = i;
  const from = m.mergeFromVert ?? [], to = m.mergeToVert ?? [];
  for (let k = 0; k < from.length; k++) canon[from[k]] = to[k];
  const remap = new Int32Array(nv).fill(-1);
  const pos: number[] = [];
  for (let i = 0; i < nv; i++) {
    const c = canon[i];
    if (remap[c] < 0) {
      remap[c] = pos.length / 3;
      pos.push(m.vertProperties[c * np], m.vertProperties[c * np + 1], m.vertProperties[c * np + 2]);
    }
    remap[i] = remap[c];
  }
  const tris = new Uint32Array(m.triVerts.length);
  for (let k = 0; k < tris.length; k++) tris[k] = remap[m.triVerts[k]];
  return { pos: Float64Array.from(pos), tris };
}

function vertexNormals(pos: Float64Array, tris: Uint32Array): Float64Array {
  const n = new Float64Array(pos.length);
  for (let t = 0; t < tris.length; t += 3) {
    const a = tris[t] * 3, b = tris[t + 1] * 3, c = tris[t + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
    const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx; // area-weighted
    for (const v of [a, b, c]) {
      n[v] += nx;
      n[v + 1] += ny;
      n[v + 2] += nz;
    }
  }
  for (let i = 0; i < n.length; i += 3) {
    const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1;
    n[i] /= l;
    n[i + 1] /= l;
    n[i + 2] /= l;
  }
  return n;
}

function neighbours(nv: number, tris: Uint32Array): number[][] {
  const adj: Set<number>[] = Array.from({ length: nv }, () => new Set<number>());
  for (let t = 0; t < tris.length; t += 3) {
    const a = tris[t], b = tris[t + 1], c = tris[t + 2];
    adj[a].add(b).add(c);
    adj[b].add(a).add(c);
    adj[c].add(a).add(b);
  }
  return adj.map((s) => [...s]);
}

const smooth01 = (t: number) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));

export interface Stroke {
  brush: 'grab' | 'inflate' | 'smooth' | 'flatten' | 'pinch' | 'crease';
  at?: V3; // brush centre
  path?: V3[]; // or a path: the brush is applied along it every radius/3
  radius: number;
  strength?: number; // mm for grab/inflate/crease, 0..1 for smooth/flatten/pinch
  dir?: V3; // grab direction (unit or not; strength scales it)
}

export function makeMeshOps(wasm: Wasm, inputs: { meshes?: Record<string, RawMesh> } = {}) {
  const rebuild = (pos: Float64Array, tris: Uint32Array) => solidFromArrays(wasm, pos, tris);
  const fine = (solid: Manifold, edge?: number) => (edge && edge > 0 ? solid.refineToLength(edge * detail.factor) : solid);

  /** A solid from vertex and triangle arrays (orientation is fixed automatically). */
  const fromArrays = (positions: ArrayLike<number>, triangles: ArrayLike<number>) => solidFromArrays(wasm, positions, triangles);

  /** An imported mesh attached to the project (inputs.meshes[name]). */
  const input = (name: string) => {
    const m = inputs.meshes?.[name];
    if (!m) throw new Error(`no imported mesh "${name}"; available: ${Object.keys(inputs.meshes ?? {}).join(', ') || 'none'}`);
    return solidFromArrays(wasm, m.positions, m.triangles);
  };

  /** Taubin smoothing (does not shrink): softens facets and noise. weight(p) in 0..1 limits where. */
  const relax = (solid: Manifold, o: { iterations?: number; strength?: number; edge?: number; weight?: (p: V3) => number } = {}) => {
    const { pos, tris } = weld(fine(solid, o.edge));
    const adj = neighbours(pos.length / 3, tris);
    const lam = Math.min(0.9, o.strength ?? 0.5), mu = -lam - 0.03;
    const w = o.weight ? Array.from({ length: pos.length / 3 }, (_, i) => o.weight!([pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]])) : null;
    const step = (k: number) => {
      const next = pos.slice();
      for (let i = 0; i < adj.length; i++) {
        const nb = adj[i];
        if (!nb.length) continue;
        let x = 0, y = 0, z = 0;
        for (const j of nb) {
          x += pos[j * 3];
          y += pos[j * 3 + 1];
          z += pos[j * 3 + 2];
        }
        const f = k * (w ? w[i] : 1);
        next[i * 3] += f * (x / nb.length - pos[i * 3]);
        next[i * 3 + 1] += f * (y / nb.length - pos[i * 3 + 1]);
        next[i * 3 + 2] += f * (z / nb.length - pos[i * 3 + 2]);
      }
      pos.set(next);
    };
    for (let it = 0; it < (o.iterations ?? 10); it++) {
      step(lam);
      step(mu);
    }
    return rebuild(pos, tris);
  };

  /**
   * Move every vertex along its normal by fn(p, n) mm (positive = outward). Refine first
   * (edge) so there are enough vertices for the detail you want: knurl, leather, noise.
   */
  const displace = (solid: Manifold, fn: number | ((p: V3, n: V3) => number), o: { edge?: number } = {}) => {
    const { pos, tris } = weld(fine(solid, o.edge));
    const n = vertexNormals(pos, tris);
    for (let i = 0; i < pos.length; i += 3) {
      const d = typeof fn === 'number' ? fn : fn([pos[i], pos[i + 1], pos[i + 2]], [n[i], n[i + 1], n[i + 2]]);
      pos[i] += n[i] * d;
      pos[i + 1] += n[i + 1] * d;
      pos[i + 2] += n[i + 2] * d;
    }
    return rebuild(pos, tris);
  };
  const inflate = (solid: Manifold, d: number, o: { edge?: number } = {}) => displace(solid, d, o);

  /**
   * Sculpt with brushes, like a sculpting app but scripted. Each stroke has a centre (or
   * a path), radius and strength; falloff is smooth. Brushes:
   *   grab (move along dir by strength mm), inflate (along normals, mm), crease (inward line, mm),
   *   smooth (0..1), flatten (toward the local tangent plane, 0..1), pinch (toward the centre, 0..1).
   */
  const sculpt = (solid: Manifold, strokes: Stroke[], o: { edge?: number } = {}) => {
    const minR = Math.min(...strokes.map((s) => s.radius));
    const { pos, tris } = weld(fine(solid, o.edge ?? Math.max(0.3, minR / 6)));
    const nv = pos.length / 3;
    const adj = neighbours(nv, tris);
    for (const s of strokes) {
      const centres: V3[] = [];
      if (s.path && s.path.length) {
        centres.push(s.path[0]);
        for (let i = 1; i < s.path.length; i++) {
          const a = s.path[i - 1], b = s.path[i];
          const L = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
          const k = Math.max(1, Math.ceil(L / (s.radius / 3)));
          for (let j = 1; j <= k; j++) centres.push([a[0] + ((b[0] - a[0]) * j) / k, a[1] + ((b[1] - a[1]) * j) / k, a[2] + ((b[2] - a[2]) * j) / k]);
        }
      } else if (s.at) centres.push(s.at);
      const dabs = Math.max(1, centres.length);
      for (const c of centres) {
        const r2 = s.radius * s.radius;
        const hit: number[] = [];
        const w: number[] = [];
        for (let i = 0; i < nv; i++) {
          const dx = pos[i * 3] - c[0], dy = pos[i * 3 + 1] - c[1], dz = pos[i * 3 + 2] - c[2];
          const d2 = dx * dx + dy * dy + dz * dz;
          if (d2 < r2) {
            hit.push(i);
            w.push(smooth01(1 - Math.sqrt(d2) / s.radius));
          }
        }
        if (!hit.length) continue;
        const n = vertexNormals(pos, tris);
        // per-dab strength so a path stroke totals about `strength`
        const k = (s.strength ?? (s.brush === 'grab' || s.brush === 'inflate' || s.brush === 'crease' ? 1 : 0.5)) / (s.path ? Math.max(1, dabs / 3) : 1);
        let an: V3 = [0, 0, 0];
        let ap: V3 = [0, 0, 0];
        let ws = 0;
        hit.forEach((i, j) => {
          for (let a = 0; a < 3; a++) {
            an[a] += n[i * 3 + a] * w[j];
            ap[a] += pos[i * 3 + a] * w[j];
          }
          ws += w[j];
        });
        const nl = Math.hypot(...an) || 1;
        an = an.map((v) => v / nl) as V3;
        ap = ap.map((v) => v / ws) as V3;
        const old = pos.slice();
        hit.forEach((i, j) => {
          const f = w[j] * k;
          const p = [old[i * 3], old[i * 3 + 1], old[i * 3 + 2]];
          let d: number[] = [0, 0, 0];
          if (s.brush === 'grab') {
            const dir = s.dir ?? an;
            const l = Math.hypot(...dir) || 1;
            d = dir.map((v) => (v / l) * f);
          } else if (s.brush === 'inflate') {
            d = [n[i * 3] * f, n[i * 3 + 1] * f, n[i * 3 + 2] * f];
          } else if (s.brush === 'crease') {
            // pull inward and toward the stroke centre: a sharp valley
            d = [-an[0] * f, -an[1] * f, -an[2] * f];
            for (let a = 0; a < 3; a++) d[a] += (c[a] - p[a]) * 0.15 * w[j];
          } else if (s.brush === 'smooth') {
            const nb = adj[i];
            for (const q of nb) for (let a = 0; a < 3; a++) d[a] += old[q * 3 + a] / nb.length;
            d = d.map((v, a) => (v - p[a]) * Math.min(1, f));
          } else if (s.brush === 'flatten') {
            const h = (p[0] - ap[0]) * an[0] + (p[1] - ap[1]) * an[1] + (p[2] - ap[2]) * an[2];
            d = an.map((v) => -v * h * Math.min(1, f));
          } else if (s.brush === 'pinch') {
            d = p.map((v, a) => (c[a] - v) * Math.min(1, f) * 0.5);
            const h = d[0] * an[0] + d[1] * an[1] + d[2] * an[2];
            d = d.map((v, a) => v - an[a] * h); // stay on the surface
          }
          pos[i * 3] = p[0] + d[0];
          pos[i * 3 + 1] = p[1] + d[1];
          pos[i * 3 + 2] = p[2] + d[2];
        });
      }
    }
    return rebuild(pos, tris);
  };

  /** Split triangles until edges are at most `edge` mm (more vertices for sculpting/displacing). */
  const subdivide = (solid: Manifold, edge: number) => solid.refineToLength(edge);
  /** Remove vertices while staying within `tolerance` mm of the surface. */
  const decimate = (solid: Manifold, tolerance = 0.05) => solid.simplify(tolerance);
  const info = (solid: Manifold) => ({
    vertices: solid.numVert(),
    triangles: solid.numTri(),
    genus: solid.genus(),
    volume: solid.volume(),
    area: solid.surfaceArea(),
  });
  /** Vertex positions and triangles of a solid (welded), for custom per-vertex edits. */
  const arrays = (solid: Manifold) => {
    const { pos, tris } = weld(solid);
    return { positions: Array.from(pos), triangles: Array.from(tris) };
  };

  return { fromArrays, input, relax, displace, inflate, sculpt, subdivide, decimate, info, arrays };
}
