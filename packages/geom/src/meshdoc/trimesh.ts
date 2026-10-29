// Plain triangle meshes for the mesh engine: welded vertices, consistently oriented closed
// surfaces, kept in typed arrays between operations (no WASM objects, so states can be
// cached and replayed). Manifold is used only to enter and leave this world and for exact
// booleans; everything a sculptor does to vertices happens here.
import type { Manifold, Wasm } from '../kernel.ts';
import { solidFromArrays, weld } from '../lib/meshops.ts';

export type V3 = [number, number, number];

export interface TriMesh {
  pos: Float64Array; // xyz per vertex
  tris: Uint32Array; // 3 vertex indices per triangle, counter-clockwise from outside
}

export const fromSolid = (solid: Manifold): TriMesh => weld(solid);
export const toSolid = (wasm: Wasm, m: TriMesh): Manifold => solidFromArrays(wasm, m.pos, m.tris);
export const cloneMesh = (m: TriMesh): TriMesh => ({ pos: m.pos.slice(), tris: m.tris.slice() });
export const meshBytes = (m: TriMesh) => m.pos.byteLength + m.tris.byteLength;

export function bounds(m: TriMesh): { min: V3; max: V3 } {
  const min: V3 = [Infinity, Infinity, Infinity], max: V3 = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < m.pos.length; i += 3)
    for (let k = 0; k < 3; k++) {
      const v = m.pos[i + k];
      if (v < min[k]) min[k] = v;
      if (v > max[k]) max[k] = v;
    }
  return { min, max };
}

export function meanEdge(m: TriMesh): number {
  const { pos, tris } = m;
  let s = 0;
  const n = Math.min(tris.length / 3, 20000);
  const step = Math.max(1, Math.floor(tris.length / 3 / n));
  let c = 0;
  for (let t = 0; t < tris.length; t += 3 * step) {
    const a = tris[t] * 3, b = tris[t + 1] * 3;
    s += Math.hypot(pos[a] - pos[b], pos[a + 1] - pos[b + 1], pos[a + 2] - pos[b + 2]);
    c++;
  }
  return c ? s / c : 1;
}

export function vertexNormals(m: TriMesh): Float64Array {
  const { pos, tris } = m;
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

/** Vertex neighbours in CSR form: nb[off[i] .. off[i+1]) are the neighbours of vertex i. */
export function adjacency(m: TriMesh): { off: Int32Array; nb: Int32Array } {
  const nv = m.pos.length / 3;
  const { tris } = m;
  // In a closed oriented surface every edge a->b appears once as a half-edge, so the
  // outgoing half-edges of a vertex list each neighbour exactly once.
  const deg = new Int32Array(nv + 1);
  for (let t = 0; t < tris.length; t++) deg[tris[t] + 1]++;
  for (let i = 0; i < nv; i++) deg[i + 1] += deg[i];
  const nb = new Int32Array(deg[nv]);
  const fill = deg.slice(0, nv);
  for (let t = 0; t < tris.length; t += 3)
    for (let e = 0; e < 3; e++) nb[fill[tris[t + e]]++] = tris[t + ((e + 1) % 3)];
  return { off: deg, nb };
}

/** Per-vertex weights in 0..1 (null = every vertex fully). */
export type Weights = Float32Array | null;

/** Taubin smoothing: removes facets and noise without shrinking the shape. */
export function taubin(m: TriMesh, iterations: number, strength = 0.5, w: Weights = null) {
  const { off, nb } = adjacency(m);
  const pos = m.pos;
  const nv = pos.length / 3;
  const lam = Math.min(0.9, Math.max(0.01, strength)), mu = -lam - 0.03;
  const next = new Float64Array(pos.length);
  const step = (k: number) => {
    for (let i = 0; i < nv; i++) {
      const f = k * (w ? w[i] : 1);
      const a = off[i], b = off[i + 1];
      if (!f || a === b) {
        next[i * 3] = pos[i * 3];
        next[i * 3 + 1] = pos[i * 3 + 1];
        next[i * 3 + 2] = pos[i * 3 + 2];
        continue;
      }
      let x = 0, y = 0, z = 0;
      for (let j = a; j < b; j++) {
        const q = nb[j] * 3;
        x += pos[q];
        y += pos[q + 1];
        z += pos[q + 2];
      }
      const c = b - a;
      next[i * 3] = pos[i * 3] + f * (x / c - pos[i * 3]);
      next[i * 3 + 1] = pos[i * 3 + 1] + f * (y / c - pos[i * 3 + 1]);
      next[i * 3 + 2] = pos[i * 3 + 2] + f * (z / c - pos[i * 3 + 2]);
    }
    pos.set(next);
  };
  for (let it = 0; it < iterations; it++) {
    step(lam);
    step(mu);
  }
}

/** Tangential relaxation: evens out triangle sizes along the surface, keeps the form. */
export function relaxTangential(m: TriMesh, iterations: number, w: Weights = null) {
  const { off, nb } = adjacency(m);
  const pos = m.pos;
  const nv = pos.length / 3;
  for (let it = 0; it < iterations; it++) {
    const n = vertexNormals(m);
    const next = pos.slice();
    for (let i = 0; i < nv; i++) {
      const f = 0.5 * (w ? w[i] : 1);
      const a = off[i], b = off[i + 1];
      if (!f || a === b) continue;
      let x = 0, y = 0, z = 0;
      for (let j = a; j < b; j++) {
        const q = nb[j] * 3;
        x += pos[q];
        y += pos[q + 1];
        z += pos[q + 2];
      }
      const c = b - a;
      let dx = x / c - pos[i * 3], dy = y / c - pos[i * 3 + 1], dz = z / c - pos[i * 3 + 2];
      const h = dx * n[i * 3] + dy * n[i * 3 + 1] + dz * n[i * 3 + 2];
      dx -= h * n[i * 3];
      dy -= h * n[i * 3 + 1];
      dz -= h * n[i * 3 + 2];
      next[i * 3] += f * dx;
      next[i * 3 + 1] += f * dy;
      next[i * 3 + 2] += f * dz;
    }
    pos.set(next);
  }
}

/**
 * Split edges longer than `maxEdge` (only edges touching selected vertices when `select`
 * is given) until none is left: red-green refinement, so neighbours of split triangles are
 * split too and the surface stays closed without T-junctions. Linear midpoints; smooth
 * afterwards if the new vertices should round off.
 */
export function refine(m: TriMesh, maxEdge: number, select: ((x: number, y: number, z: number) => boolean) | null = null, maxTriangles = 1_500_000): TriMesh {
  let pos = m.pos, tris = m.tris;
  const L2 = maxEdge * maxEdge;
  for (let pass = 0; pass < 10; pass++) {
    const nv = pos.length / 3;
    const mids = new Map<number, number>();
    const extra: number[] = [];
    const len2 = (a: number, b: number) => {
      const dx = pos[a * 3] - pos[b * 3], dy = pos[a * 3 + 1] - pos[b * 3 + 1], dz = pos[a * 3 + 2] - pos[b * 3 + 2];
      return dx * dx + dy * dy + dz * dz;
    };
    const midOf = (a: number, b: number, mark: boolean) => {
      const key = a < b ? a * nv + b : b * nv + a;
      let v = mids.get(key);
      if (v === undefined && mark) {
        v = nv + extra.length / 3;
        extra.push((pos[a * 3] + pos[b * 3]) / 2, (pos[a * 3 + 1] + pos[b * 3 + 1]) / 2, (pos[a * 3 + 2] + pos[b * 3 + 2]) / 2);
        mids.set(key, v);
      }
      return v ?? -1;
    };
    const chosen = select ? new Uint8Array(nv) : null;
    if (chosen) for (let v = 0; v < nv; v++) chosen[v] = select!(pos[v * 3], pos[v * 3 + 1], pos[v * 3 + 2]) ? 1 : 0;
    for (let t = 0; t < tris.length; t += 3)
      for (let e = 0; e < 3; e++) {
        const a = tris[t + e], b = tris[t + ((e + 1) % 3)];
        if ((!chosen || chosen[a] || chosen[b]) && len2(a, b) > L2) midOf(a, b, true);
      }
    if (!mids.size) break;
    const out: number[] = [];
    for (let t = 0; t < tris.length; t += 3) {
      const v = [tris[t], tris[t + 1], tris[t + 2]];
      const s = [midOf(v[0], v[1], false), midOf(v[1], v[2], false), midOf(v[2], v[0], false)];
      const n = (s[0] >= 0 ? 1 : 0) + (s[1] >= 0 ? 1 : 0) + (s[2] >= 0 ? 1 : 0);
      if (n === 0) out.push(v[0], v[1], v[2]);
      else if (n === 3) out.push(v[0], s[0], s[2], s[0], v[1], s[1], s[2], s[1], v[2], s[0], s[1], s[2]);
      else {
        // rotate so the pattern starts at a split edge: edge 0 split (and edge 1 when two are)
        let r = 0;
        if (n === 1) r = s.findIndex((x) => x >= 0);
        else r = s[0] >= 0 && s[1] >= 0 ? 0 : s[1] >= 0 && s[2] >= 0 ? 1 : 2;
        const a = v[r], b = v[(r + 1) % 3], c = v[(r + 2) % 3];
        const mab = s[r], mbc = s[(r + 1) % 3];
        if (n === 1) out.push(a, mab, c, mab, b, c);
        else {
          out.push(mab, b, mbc);
          // quad a, mab, mbc, c: cut along the shorter diagonal
          if (diag(pos, extra, nv, a, mbc) <= diag(pos, extra, nv, mab, c)) out.push(a, mab, mbc, a, mbc, c);
          else out.push(a, mab, c, mab, mbc, c);
        }
      }
    }
    const np = new Float64Array(pos.length + extra.length);
    np.set(pos);
    np.set(extra, pos.length);
    pos = np;
    tris = Uint32Array.from(out);
    if (tris.length / 3 > maxTriangles) break;
  }
  return { pos, tris };
}

function diag(pos: Float64Array, extra: number[], nv: number, a: number, b: number) {
  const p = (i: number, k: number) => (i < nv ? pos[i * 3 + k] : extra[(i - nv) * 3 + k]);
  return Math.hypot(p(a, 0) - p(b, 0), p(a, 1) - p(b, 1), p(a, 2) - p(b, 2));
}

/** One level of Loop subdivision: 4x the triangles, a smooth limit surface. */
export function loopSubdivide(m: TriMesh): TriMesh {
  const { pos, tris } = m;
  const nv = pos.length / 3;
  const { off, nb } = adjacency(m);
  // edge -> new vertex, with both opposite vertices for the 3/8-1/8 rule
  const edgeVert = new Map<number, number>();
  const opp: number[] = [];
  const ends: number[] = [];
  const key = (a: number, b: number) => (a < b ? a * nv + b : b * nv + a);
  for (let t = 0; t < tris.length; t += 3)
    for (let e = 0; e < 3; e++) {
      const a = tris[t + e], b = tris[t + ((e + 1) % 3)], c = tris[t + ((e + 2) % 3)];
      const k = key(a, b);
      const v = edgeVert.get(k);
      if (v === undefined) {
        edgeVert.set(k, ends.length / 2);
        ends.push(a, b);
        opp.push(c, -1);
      } else opp[v * 2 + 1] = c;
    }
  const ne = ends.length / 2;
  const out = new Float64Array((nv + ne) * 3);
  for (let i = 0; i < nv; i++) {
    const n = off[i + 1] - off[i];
    const beta = n === 3 ? 3 / 16 : 3 / (8 * Math.max(n, 1));
    let x = 0, y = 0, z = 0;
    for (let j = off[i]; j < off[i + 1]; j++) {
      x += pos[nb[j] * 3];
      y += pos[nb[j] * 3 + 1];
      z += pos[nb[j] * 3 + 2];
    }
    const k = 1 - n * beta;
    out[i * 3] = k * pos[i * 3] + beta * x;
    out[i * 3 + 1] = k * pos[i * 3 + 1] + beta * y;
    out[i * 3 + 2] = k * pos[i * 3 + 2] + beta * z;
  }
  for (let e = 0; e < ne; e++) {
    const a = ends[e * 2] * 3, b = ends[e * 2 + 1] * 3, c = opp[e * 2], d = opp[e * 2 + 1];
    for (let k = 0; k < 3; k++)
      out[(nv + e) * 3 + k] = d >= 0 ? 0.375 * (pos[a + k] + pos[b + k]) + 0.125 * (pos[c * 3 + k] + pos[d * 3 + k]) : 0.5 * (pos[a + k] + pos[b + k]);
  }
  const nt = new Uint32Array(tris.length * 4);
  for (let t = 0, o = 0; t < tris.length; t += 3) {
    const a = tris[t], b = tris[t + 1], c = tris[t + 2];
    const ab = nv + edgeVert.get(key(a, b))!, bc = nv + edgeVert.get(key(b, c))!, ca = nv + edgeVert.get(key(c, a))!;
    nt.set([a, ab, ca, ab, b, bc, ca, bc, c, ab, bc, ca], o);
    o += 12;
  }
  return { pos: out, tris: nt };
}

// ---------------------------------------------------------------- distance to a mesh
// Closest point on triangle (Ericson, Real-Time Collision Detection 5.1.5), squared distance.
function triDist2(px: number, py: number, pz: number, P: Float64Array, a: number, b: number, c: number): number {
  const ax = P[a], ay = P[a + 1], az = P[a + 2];
  const abx = P[b] - ax, aby = P[b + 1] - ay, abz = P[b + 2] - az;
  const acx = P[c] - ax, acy = P[c + 1] - ay, acz = P[c + 2] - az;
  const apx = px - ax, apy = py - ay, apz = pz - az;
  const d1 = abx * apx + aby * apy + abz * apz, d2 = acx * apx + acy * apy + acz * apz;
  let qx: number, qy: number, qz: number;
  if (d1 <= 0 && d2 <= 0) {
    qx = ax; qy = ay; qz = az;
  } else {
    const bpx = px - P[b], bpy = py - P[b + 1], bpz = pz - P[b + 2];
    const d3 = abx * bpx + aby * bpy + abz * bpz, d4 = acx * bpx + acy * bpy + acz * bpz;
    if (d3 >= 0 && d4 <= d3) {
      qx = P[b]; qy = P[b + 1]; qz = P[b + 2];
    } else {
      const vc = d1 * d4 - d3 * d2;
      if (vc <= 0 && d1 >= 0 && d3 <= 0) {
        const v = d1 / (d1 - d3);
        qx = ax + v * abx; qy = ay + v * aby; qz = az + v * abz;
      } else {
        const cpx = px - P[c], cpy = py - P[c + 1], cpz = pz - P[c + 2];
        const d5 = abx * cpx + aby * cpy + abz * cpz, d6 = acx * cpx + acy * cpy + acz * cpz;
        if (d6 >= 0 && d5 <= d6) {
          qx = P[c]; qy = P[c + 1]; qz = P[c + 2];
        } else {
          const vb = d5 * d2 - d1 * d6;
          if (vb <= 0 && d2 >= 0 && d6 <= 0) {
            const w = d2 / (d2 - d6);
            qx = ax + w * acx; qy = ay + w * acy; qz = az + w * acz;
          } else {
            const va = d3 * d6 - d5 * d4;
            if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) {
              const w = (d4 - d3) / (d4 - d3 + (d5 - d6));
              qx = P[b] + w * (P[c] - P[b]); qy = P[b + 1] + w * (P[c + 1] - P[b + 1]); qz = P[b + 2] + w * (P[c + 2] - P[b + 2]);
            } else {
              const denom = 1 / (va + vb + vc);
              const v = vb * denom, w = vc * denom;
              qx = ax + abx * v + acx * w; qy = ay + aby * v + acy * w; qz = az + abz * v + acz * w;
            }
          }
        }
      }
    }
  }
  const dx = px - qx, dy = py - qy, dz = pz - qz;
  return dx * dx + dy * dy + dz * dz;
}

/**
 * Signed distance to a closed mesh (negative inside), for remeshing and blending.
 * Distance is exact up to `band` mm and clamped beyond it; a query may ask for a wider band,
 * up to `maxBand`. Inside/outside comes from the winding number along a vertical ray, so
 * overlapping shells count as their union and small sculpting folds do not punch holes.
 */
export function meshField(m: TriMesh, band: number, maxBand = band) {
  const { pos: P, tris: T } = m;
  const nt = T.length / 3;
  const { min, max } = bounds(m);
  // dense grid of triangles, cells a little wider than an edge
  let h = Math.max(meanEdge(m) * 1.25, band / 2, 1e-3);
  let dims = [0, 1, 2].map((k) => Math.max(1, Math.ceil((max[k] - min[k]) / h) + 1));
  while (dims[0] * dims[1] * dims[2] > 6e6) {
    h *= 1.25;
    dims = [0, 1, 2].map((k) => Math.max(1, Math.ceil((max[k] - min[k]) / h) + 1));
  }
  const [dx, dy, dz] = dims;
  const ncell = dx * dy * dz;
  const cl = (v: number, k: number) => Math.min(dims[k] - 1, Math.max(0, Math.floor((v - min[k]) / h)));
  const triBox = new Float64Array(nt * 6);
  const span = new Int32Array(nt * 6);
  const count = new Int32Array(ncell + 1);
  for (let t = 0; t < nt; t++) {
    const a = T[t * 3] * 3, b = T[t * 3 + 1] * 3, c = T[t * 3 + 2] * 3;
    for (let k = 0; k < 3; k++) {
      triBox[t * 6 + k] = Math.min(P[a + k], P[b + k], P[c + k]);
      triBox[t * 6 + 3 + k] = Math.max(P[a + k], P[b + k], P[c + k]);
      span[t * 6 + k * 2] = cl(triBox[t * 6 + k], k);
      span[t * 6 + k * 2 + 1] = cl(triBox[t * 6 + 3 + k], k);
    }
    for (let k = span[t * 6 + 4]; k <= span[t * 6 + 5]; k++)
      for (let j = span[t * 6 + 2]; j <= span[t * 6 + 3]; j++)
        for (let i = span[t * 6]; i <= span[t * 6 + 1]; i++) count[(k * dy + j) * dx + i + 1]++;
  }
  for (let c = 0; c < ncell; c++) count[c + 1] += count[c];
  const cellTris = new Int32Array(count[ncell]);
  const fill = count.slice(0, ncell);
  for (let t = 0; t < nt; t++)
    for (let k = span[t * 6 + 4]; k <= span[t * 6 + 5]; k++)
      for (let j = span[t * 6 + 2]; j <= span[t * 6 + 3]; j++)
        for (let i = span[t * 6]; i <= span[t * 6 + 1]; i++) cellTris[fill[(k * dy + j) * dx + i]++] = t;
  // Chebyshev distance (in cells) to the nearest occupied cell, as far as maxBand needs:
  // samples far from the surface skip the triangle search entirely
  const reach = Math.min(250, Math.ceil(maxBand / h) + 2);
  const far = new Uint8Array(ncell).fill(255);
  let frontier: number[] = [];
  for (let c = 0; c < ncell; c++)
    if (count[c + 1] > count[c]) {
      far[c] = 0;
      frontier.push(c);
    }
  for (let r = 1; r <= reach && frontier.length; r++) {
    const next: number[] = [];
    for (const c of frontier) {
      const i = c % dx, j = Math.floor(c / dx) % dy, k = Math.floor(c / (dx * dy));
      for (let kk = Math.max(0, k - 1); kk <= Math.min(dz - 1, k + 1); kk++)
        for (let jj = Math.max(0, j - 1); jj <= Math.min(dy - 1, j + 1); jj++)
          for (let ii = Math.max(0, i - 1); ii <= Math.min(dx - 1, i + 1); ii++) {
            const n = (kk * dy + jj) * dx + ii;
            if (far[n] > r) {
              far[n] = r;
              next.push(n);
            }
          }
    }
    frontier = next;
  }
  const stamp = new Int32Array(nt);
  let query = 0;
  const scanCell = (c: number, x: number, y: number, z: number, best: number) => {
    for (let q = count[c]; q < count[c + 1]; q++) {
      const t = cellTris[q];
      if (stamp[t] === query) continue;
      stamp[t] = query;
      const o = t * 6;
      const ex = Math.max(triBox[o] - x, 0, x - triBox[o + 3]);
      const ey = Math.max(triBox[o + 1] - y, 0, y - triBox[o + 4]);
      const ez = Math.max(triBox[o + 2] - z, 0, z - triBox[o + 5]);
      if (ex * ex + ey * ey + ez * ez >= best) continue;
      const d = triDist2(x, y, z, P, T[t * 3] * 3, T[t * 3 + 1] * 3, T[t * 3 + 2] * 3);
      if (d < best) best = d;
    }
    return best;
  };
  const unsigned = (x: number, y: number, z: number, B: number) => {
    const fi = Math.floor((x - min[0]) / h), fj = Math.floor((y - min[1]) / h), fk = Math.floor((z - min[2]) / h);
    const ci = Math.min(dx - 1, Math.max(0, fi)), cj = Math.min(dy - 1, Math.max(0, fj)), ck = Math.min(dz - 1, Math.max(0, fk));
    // off the grid, the distance to it adds to the lower bound
    const gap = Math.max(Math.abs(fi - ci), Math.abs(fj - cj), Math.abs(fk - ck));
    const cheb = far[(ck * dy + cj) * dx + ci] + gap;
    if ((cheb - 1) * h >= B) return B;
    query++;
    let best = B * B;
    const R = Math.ceil(B / h) + 1;
    // how far the point is from the walls of its own cell: ring r starts that far plus r - 1 cells out
    const lx = x - (min[0] + ci * h), ly = y - (min[1] + cj * h), lz = z - (min[2] + ck * h);
    const wall = Math.max(0, Math.min(lx, h - lx, ly, h - ly, lz, h - lz));
    for (let r = Math.max(0, cheb - 1); r <= R; r++) {
      if (r > 0 && ((r - 1) * h + wall) ** 2 >= best) break;
      for (let k = ck - r; k <= ck + r; k++) {
        if (k < 0 || k >= dz) continue;
        const shellK = k === ck - r || k === ck + r;
        for (let j = cj - r; j <= cj + r; j++) {
          if (j < 0 || j >= dy) continue;
          // inside the shell only the two end cells of a row belong to ring r
          const step = shellK || j === cj - r || j === cj + r ? 1 : Math.max(1, 2 * r);
          for (let i = ci - r; i <= ci + r; i += step) {
            if (i < 0 || i >= dx) continue;
            best = scanCell((k * dy + j) * dx + i, x, y, z, best);
          }
        }
      }
    }
    return Math.sqrt(best);
  };
  // XY grid of triangles for the vertical winding rays
  const g = Math.max(h, (max[0] - min[0] + max[1] - min[1]) / 400);
  const gx = Math.max(1, Math.ceil((max[0] - min[0]) / g) + 1), gy = Math.max(1, Math.ceil((max[1] - min[1]) / g) + 1);
  const cols = new Map<number, number[]>();
  for (let t = 0; t < nt; t++) {
    const i0 = Math.floor((triBox[t * 6] - min[0]) / g), i1 = Math.floor((triBox[t * 6 + 3] - min[0]) / g);
    const j0 = Math.floor((triBox[t * 6 + 1] - min[1]) / g), j1 = Math.floor((triBox[t * 6 + 4] - min[1]) / g);
    for (let i = i0; i <= i1; i++)
      for (let j = j0; j <= j1; j++) {
        const key = j * gx + i;
        let c = cols.get(key);
        if (!c) cols.set(key, (c = []));
        c.push(t);
      }
  }
  // per column: crossing heights (sorted) and the winding number above each
  const extent = Math.max(max[0] - min[0], max[1] - min[1], 1);
  const jx = extent * 1.37e-7, jy = extent * 2.71e-7; // keeps rays off shared edges and vertices
  let columns = new Map<number, Map<number, { z: Float64Array; w: Int32Array }>>();
  let cached = 0;
  const column = (x0: number, y0: number) => {
    let row = columns.get(x0);
    if (!row) {
      if (cached > 400000) {
        columns = new Map();
        cached = 0;
      }
      columns.set(x0, (row = new Map()));
    }
    let c = row.get(y0);
    if (c) return c;
    const x = x0 + jx, y = y0 + jy;
    const hits: [number, number][] = [];
    const i = Math.floor((x - min[0]) / g), j = Math.floor((y - min[1]) / g);
    const cand = i >= 0 && j >= 0 && i < gx && j < gy ? cols.get(j * gx + i) : undefined;
    for (const t of cand ?? []) {
      const o = t * 6;
      if (x < triBox[o] || x > triBox[o + 3] || y < triBox[o + 1] || y > triBox[o + 4]) continue;
      const a = T[t * 3] * 3, b = T[t * 3 + 1] * 3, cc = T[t * 3 + 2] * 3;
      const e0 = (P[b] - P[a]) * (y - P[a + 1]) - (P[b + 1] - P[a + 1]) * (x - P[a]);
      const e1 = (P[cc] - P[b]) * (y - P[b + 1]) - (P[cc + 1] - P[b + 1]) * (x - P[b]);
      const e2 = (P[a] - P[cc]) * (y - P[cc + 1]) - (P[a + 1] - P[cc + 1]) * (x - P[cc]);
      const up = e0 > 0 && e1 > 0 && e2 > 0, down = e0 < 0 && e1 < 0 && e2 < 0;
      if (!up && !down) continue;
      const s = e0 + e1 + e2; // twice the projected area, signed
      const z = (e1 * P[a + 2] + e2 * P[b + 2] + e0 * P[cc + 2]) / s;
      hits.push([z, up ? 1 : -1]); // counter-clockwise from above: the normal points up, the ray leaves here
    }
    hits.sort((p, q) => p[0] - q[0]);
    const z = Float64Array.from(hits, (hh) => hh[0]);
    const w = new Int32Array(hits.length + 1);
    for (let k = hits.length - 1; k >= 0; k--) w[k] = w[k + 1] + hits[k][1];
    c = { z, w };
    row.set(y0, c);
    cached++;
    return c;
  };
  const inside = (x: number, y: number, z: number) => {
    const c = column(x, y);
    let lo = 0, hi = c.z.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (c.z[mid] <= z) lo = mid + 1;
      else hi = mid;
    }
    return c.w[lo] > 0; // net crossings leaving upward above the point
  };
  return {
    box: { min, max },
    band,
    /** Signed distance, exact within `B` mm (default: the field's band; at most maxBand). */
    at(x: number, y: number, z: number, B = band) {
      const d = unsigned(x, y, z, Math.min(B, maxBand));
      return inside(x, y, z) ? -d : d;
    },
    inside,
    unsigned,
  };
}
