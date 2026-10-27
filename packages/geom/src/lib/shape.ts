// Free-form modelling on top of CSG: splines, lofts through sections, sweeps along
// paths, subdivision smoothing, true 3D rounding/offsets, features that follow a curved
// surface (grooves, embossing) and space deformations.
import type { CrossSection, Manifold, Wasm } from '../kernel.ts';
import { earcut, solidFromArrays } from './meshops.ts';

type V2 = [number, number];
type V3 = [number, number, number];

const sub3 = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot3 = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross3 = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm3 = (a: V3): V3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};

// ---------- splines ----------
// Centripetal Catmull-Rom: passes through every control point, no loops or cusps.
function catmull<T extends number[]>(pts: T[], closed: boolean, samples: number): T[] {
  const n = pts.length;
  if (n < 3) return pts.slice();
  const get = (i: number) => (closed ? pts[(i + n) % n] : pts[Math.max(0, Math.min(n - 1, i))]);
  const dist = (a: number[], b: number[]) => Math.max(1e-6, Math.sqrt(Math.hypot(...a.map((v, k) => v - b[k]))));
  const out: T[] = [];
  const segs = closed ? n : n - 1;
  for (let i = 0; i < segs; i++) {
    const p0 = get(i - 1), p1 = get(i), p2 = get(i + 1), p3 = get(i + 2);
    const t0 = 0, t1 = t0 + dist(p0, p1), t2 = t1 + dist(p1, p2), t3 = t2 + dist(p2, p3);
    for (let s = 0; s < samples; s++) {
      const t = t1 + ((t2 - t1) * s) / samples;
      const lerp = (a: number[], b: number[], ta: number, tb: number) => a.map((v, k) => ((tb - t) / (tb - ta)) * v + ((t - ta) / (tb - ta)) * b[k]);
      const a1 = lerp(p0, p1, t0, t1), a2 = lerp(p1, p2, t1, t2), a3 = lerp(p2, p3, t2, t3);
      const b1 = lerp(a1, a2, t0, t2), b2 = lerp(a2, a3, t1, t3);
      out.push(lerp(b1, b2, t1, t2) as T);
    }
  }
  if (!closed) out.push(pts[n - 1]);
  return out;
}

// Outer loop of a shape as points.
function outerLoop(shape: CrossSection | V2[]): V2[] {
  if (Array.isArray(shape)) return shape;
  const polys = shape.toPolygons() as V2[][];
  if (!polys.length) throw new Error('empty section');
  let best = polys[0], bestA = -Infinity;
  for (const p of polys) {
    let a = 0;
    for (let i = 0, j = p.length - 1; i < p.length; j = i++) a += p[j][0] * p[i][1] - p[i][0] * p[j][1];
    if (Math.abs(a) > bestA) {
      bestA = Math.abs(a);
      best = p;
    }
  }
  return best;
}

// Resample a closed loop to n points, counter-clockwise, starting where the ray from the
// centroid along +u crosses it, so consecutive sections line up.
function resample(loop: V2[], n: number): V2[] {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0, j = loop.length - 1; i < loop.length; j = i++) {
    const f = loop[j][0] * loop[i][1] - loop[i][0] * loop[j][1];
    a += f;
    cx += (loop[j][0] + loop[i][0]) * f;
    cy += (loop[j][1] + loop[i][1]) * f;
  }
  let pts = a < 0 ? loop.slice().reverse() : loop.slice();
  cx /= 3 * a || 1;
  cy /= 3 * a || 1;
  // start point
  let startSeg = 0, startT = 0, bestX = -Infinity;
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i], q = pts[(i + 1) % pts.length];
    if ((p[1] - cy) * (q[1] - cy) <= 0 && p[1] !== q[1]) {
      const t = (cy - p[1]) / (q[1] - p[1]);
      const x = p[0] + (q[0] - p[0]) * t;
      if (x > cx && x > bestX) {
        bestX = x;
        startSeg = i;
        startT = t;
      }
    }
  }
  if (bestX === -Infinity) {
    startSeg = pts.reduce((bi, p, i) => (p[0] > pts[bi][0] ? i : bi), 0);
    startT = 0;
  }
  const s0 = pts[startSeg], s1 = pts[(startSeg + 1) % pts.length];
  const start: V2 = [s0[0] + (s1[0] - s0[0]) * startT, s0[1] + (s1[1] - s0[1]) * startT];
  pts = [start, ...pts.slice(startSeg + 1), ...pts.slice(0, startSeg + 1)];
  const lens = [0];
  for (let i = 1; i <= pts.length; i++) {
    const p = pts[i - 1], q = pts[i % pts.length];
    lens.push(lens[i - 1] + Math.hypot(q[0] - p[0], q[1] - p[1]));
  }
  const total = lens[pts.length];
  const out: V2[] = [];
  let k = 0;
  for (let s = 0; s < n; s++) {
    const d = (total * s) / n;
    while (lens[k + 1] < d) k++;
    const p = pts[k], q = pts[(k + 1) % pts.length];
    const t = (d - lens[k]) / (lens[k + 1] - lens[k] || 1);
    out.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]);
  }
  return out;
}

// Closed tube mesh from rings of equal size (+ caps when open).
function ringsToSolid(wasm: Wasm, rings: V3[][], ring2d: V2[] | null, closedPath: boolean): Manifold {
  const n = rings[0].length;
  const pos: number[] = [];
  for (const r of rings) for (const p of r) pos.push(p[0], p[1], p[2]);
  const tris: number[] = [];
  const R = rings.length;
  const last = closedPath ? R : R - 1;
  for (let i = 0; i < last; i++) {
    const a = i * n, b = ((i + 1) % R) * n;
    for (let k = 0; k < n; k++) {
      const k2 = (k + 1) % n;
      tris.push(a + k, a + k2, b + k2, a + k, b + k2, b + k);
    }
  }
  if (!closedPath && ring2d) {
    const cap = earcut(ring2d);
    const top = (R - 1) * n;
    for (let t = 0; t < cap.length; t += 3) {
      tris.push(cap[t], cap[t + 2], cap[t + 1]); // bottom faces back
      tris.push(top + cap[t], top + cap[t + 1], top + cap[t + 2]);
    }
  }
  return solidFromArrays(wasm, pos, tris);
}

export function makeShape(wasm: Wasm) {
  const { Manifold: M, CrossSection: CS } = wasm as any;

  /** Smooth curve through 2D points (closed by default). Use std.poly(points) for a shape. */
  const spline2d = (points: V2[], o: { closed?: boolean; samples?: number } = {}): V2[] =>
    catmull(points, o.closed ?? true, o.samples ?? 12) as V2[];
  /** Smooth 3D curve through points (open by default), for sweep/pipe paths. */
  const spline3d = (points: V3[], o: { closed?: boolean; samples?: number } = {}): V3[] =>
    catmull(points, o.closed ?? false, o.samples ?? 12) as V3[];
  /** Circular arc in 2D from a0 to a1 degrees. */
  const arc2d = (r: number, a0: number, a1: number, o: { center?: V2; segments?: number } = {}): V2[] => {
    const n = o.segments ?? Math.max(8, Math.ceil(Math.abs(a1 - a0) / 6));
    const [cx, cy] = o.center ?? [0, 0];
    return Array.from({ length: n + 1 }, (_, i) => {
      const a = ((a0 + ((a1 - a0) * i) / n) * Math.PI) / 180;
      return [cx + r * Math.cos(a), cy + r * Math.sin(a)] as V2;
    });
  };
  /** A band of width w along a 2D polyline (seams, slots along a curve, lettering strokes). */
  const stroke2d = (points: V2[], w: number, o: { closed?: boolean } = {}): CrossSection => {
    const pieces: CrossSection[] = [];
    const pts = o.closed ? [...points, points[0]] : points;
    for (let i = 1; i < pts.length; i++)
      pieces.push(CS.hull([CS.circle(w / 2, 16).translate(pts[i - 1]), CS.circle(w / 2, 16).translate(pts[i])]));
    return CS.union(pieces);
  };

  /**
   * Loft through cross-sections placed along an axis. Each section: { shape, at } where
   * shape is a CrossSection or points in the plane across the axis (axis z: x,y; axis y:
   * x,z; axis x: y,z) and `at` its position along the axis. smooth=true blends sections
   * with a spline (needs 3+), otherwise straight between them.
   */
  const loft = (
    sections: { shape: CrossSection | V2[]; at: number }[],
    o: { axis?: 'x' | 'y' | 'z'; points?: number; smooth?: boolean; steps?: number } = {},
  ): Manifold => {
    if (sections.length < 2) throw new Error('loft needs at least 2 sections');
    const secs = sections.slice().sort((a, b) => a.at - b.at);
    const n = o.points ?? 96;
    const rings2 = secs.map((s) => resample(outerLoop(s.shape), n));
    const ats = secs.map((s) => s.at);
    const smooth = (o.smooth ?? true) && secs.length >= 3;
    const steps = smooth ? o.steps ?? 8 : 1;
    const out: { ring: V2[]; at: number }[] = [];
    for (let i = 0; i < secs.length - 1; i++) {
      const h = ats[i + 1] - ats[i];
      for (let s = 0; s < steps; s++) {
        const t = s / steps;
        if (!smooth) {
          out.push({ ring: rings2[i].map((p, k) => [p[0] + (rings2[i + 1][k][0] - p[0]) * t, p[1] + (rings2[i + 1][k][1] - p[1]) * t]), at: ats[i] + h * t });
          continue;
        }
        // cubic Hermite in `at` with Catmull-Rom tangents: monotone along the axis
        const tan = (j: number, k: number, c: 0 | 1) => {
          const a = Math.max(0, j - 1), b = Math.min(secs.length - 1, j + 1);
          return (rings2[b][k][c] - rings2[a][k][c]) / (ats[b] - ats[a] || 1);
        };
        const h00 = 2 * t ** 3 - 3 * t * t + 1, h10 = t ** 3 - 2 * t * t + t, h01 = -2 * t ** 3 + 3 * t * t, h11 = t ** 3 - t * t;
        out.push({
          ring: rings2[i].map((p, k) => [0, 1].map((c) => h00 * p[c] + h10 * h * tan(i, k, c as 0) + h01 * rings2[i + 1][k][c] + h11 * h * tan(i + 1, k, c as 0)) as V2),
          at: ats[i] + h * t,
        });
      }
    }
    out.push({ ring: rings2[secs.length - 1], at: ats[secs.length - 1] });
    const axis = o.axis ?? 'z';
    const place = (p: V2, at: number): V3 => (axis === 'z' ? [p[0], p[1], at] : axis === 'y' ? [p[0], at, p[1]] : [at, p[0], p[1]]);
    return ringsToSolid(wasm, out.map((r) => r.ring.map((p) => place(p, r.at))), rings2[0], false);
  };

  /**
   * Sweep a 2D profile along a 3D path (rotation-minimising frames, no flips). The profile's
   * (u, v) map to the path's normal/binormal. scale: number or t => factor (t = 0..1),
   * twist: total degrees. Keep the path's bend radius larger than the profile.
   */
  const sweep = (
    profile: CrossSection | V2[],
    path: V3[],
    o: { closed?: boolean; points?: number; scale?: number | ((t: number) => number); twist?: number; up?: V3 } = {},
  ): Manifold => {
    const closed = o.closed ?? false;
    const P = path.slice();
    if (closed && Math.hypot(...sub3(P[0], P[P.length - 1])) < 1e-6) P.pop();
    if (P.length < 2) throw new Error('sweep path needs at least 2 points');
    const N = P.length;
    const T: V3[] = P.map((_, i) => {
      const a = closed ? P[(i - 1 + N) % N] : P[Math.max(0, i - 1)];
      const b = closed ? P[(i + 1) % N] : P[Math.min(N - 1, i + 1)];
      return norm3(sub3(b, a));
    });
    // initial normal: perpendicular to the first tangent, biased toward `up`
    const up = o.up ?? (Math.abs(T[0][2]) < 0.9 ? [0, 0, 1] : [1, 0, 0]);
    let nrm = norm3(cross3(cross3(T[0], up as V3), T[0]));
    const normals: V3[] = [nrm];
    for (let i = 0; i < N - 1; i++) {
      // double reflection (Wang et al. 2008)
      const v1 = sub3(P[i + 1], P[i]);
      const c1 = dot3(v1, v1) || 1e-12;
      const rL = sub3(nrm, v1.map((x) => (x * 2 * dot3(v1, nrm)) / c1) as V3);
      const tL = sub3(T[i], v1.map((x) => (x * 2 * dot3(v1, T[i])) / c1) as V3);
      const v2 = sub3(T[i + 1], tL);
      const c2 = dot3(v2, v2) || 1e-12;
      nrm = norm3(sub3(rL, v2.map((x) => (x * 2 * dot3(v2, rL)) / c2) as V3));
      normals.push(nrm);
    }
    let fix = 0;
    if (closed) {
      // spread the closing mismatch so the ends meet
      const b0 = cross3(T[0], normals[0]);
      const nEnd = normals[N - 1];
      fix = Math.atan2(dot3(nEnd, b0), dot3(nEnd, normals[0]));
    }
    const prof = resample(outerLoop(profile), o.points ?? 48);
    const rings: V3[][] = [];
    for (let i = 0; i < N; i++) {
      const t = closed ? i / N : i / (N - 1);
      const s = typeof o.scale === 'function' ? o.scale(t) : o.scale ?? 1;
      const ang = ((o.twist ?? 0) * Math.PI) / 180 * t - fix * t;
      const c = Math.cos(ang), sn = Math.sin(ang);
      const n0 = normals[i], b0 = cross3(T[i], n0);
      const nn: V3 = [n0[0] * c + b0[0] * sn, n0[1] * c + b0[1] * sn, n0[2] * c + b0[2] * sn];
      const bb: V3 = cross3(T[i], nn);
      rings.push(prof.map(([u, v]) => [P[i][0] + (nn[0] * u + bb[0] * v) * s, P[i][1] + (nn[1] * u + bb[1] * v) * s, P[i][2] + (nn[2] * u + bb[2] * v) * s]));
    }
    return ringsToSolid(wasm, rings, prof, closed);
  };
  /** Round tube of diameter d along a path (handles, wires, rails, rings when closed). */
  const pipe = (path: V3[], d: number, o: { closed?: boolean; segments?: number } = {}) =>
    sweep(CS.circle(d / 2, o.segments ?? 32), path, { closed: o.closed, points: o.segments ?? 32 });

  /**
   * Subdivision smoothing for faceted organic meshes (low-poly hulls, coarse lofts, sculpts):
   * edges sharper than `angle` degrees stay crisp, the rest become G1-smooth; `smoothness`
   * (0..1) also softens the sharp ones. Large flat faces of 1-2 triangles bulge outward, so
   * check the size after; to round the edges of boxy parts use r options or round3d instead.
   * tolerance: max distance to the ideal surface (mm).
   */
  const smooth = (solid: Manifold, o: { angle?: number; smoothness?: number; tolerance?: number; edge?: number } = {}) => {
    const s = solid.smoothOut(o.angle ?? 60, o.smoothness ?? 0);
    return o.edge ? s.refineToLength(o.edge) : s.refineToTolerance(o.tolerance ?? 0.05);
  };
  const ball = (r: number) => M.sphere(r, Math.max(12, Math.min(32, Math.round(r * 6))));
  /** Grow (d > 0) or shrink (d < 0) a solid by d mm in every direction (Minkowski). */
  const offset3d = (solid: Manifold, d: number) =>
    d === 0 ? solid : d > 0 ? solid.minkowskiSum(ball(d)) : solid.minkowskiDifference(ball(-d));
  /**
   * True 3D rounding of every convex (outer) edge with radius r, size kept. Concave inner
   * fillets this way take tens of seconds, so make those with fillet2d before extruding or
   * with sdf smoothUnion / smoothSubtract. Round simple bodies before adding detail.
   */
  const round3d = (solid: Manifold, r: number) => solid.minkowskiDifference(ball(r)).minkowskiSum(ball(r));
  /** Hollow a solid: walls of thickness t following the outside. */
  const shell3d = (solid: Manifold, t: number) => solid.subtract(offset3d(solid, -t));

  // ---------- surface-following features ----------
  type Dir = 'z' | '-z' | 'x' | '-x' | 'y' | '-y';
  const dirVec = (d: Dir): V3 => ({ z: [0, 0, 1], '-z': [0, 0, -1], x: [1, 0, 0], '-x': [-1, 0, 0], y: [0, 1, 0], '-y': [0, -1, 0] } as Record<Dir, V3>)[d];
  // 2D shape seen from `dir`, extruded through the whole solid along it.
  const prism = (solid: Manifold, shape: CrossSection, dir: Dir) => {
    const b = solid.boundingBox();
    const ax = dir.replace('-', '');
    const lo = ax === 'z' ? b.min[2] : ax === 'x' ? b.min[0] : b.min[1];
    const hi = ax === 'z' ? b.max[2] : ax === 'x' ? b.max[0] : b.max[1];
    // shape coordinates: z -> (x, y); x -> (y, z); y -> (x, z). Only proper rotations
    // (a plain axis swap would mirror the mesh inside out).
    if (ax === 'z') return shape.extrude(hi - lo + 2).translate([0, 0, lo - 1]);
    if (ax === 'x')
      return shape.extrude(hi - lo + 2).translate([0, 0, lo - 1]).warp((v: number[]) => {
        const [u, w, h] = v;
        v[0] = h; v[1] = u; v[2] = w;
      });
    return shape.extrude(hi - lo + 2).translate([0, 0, -(hi + 1)]).warp((v: number[]) => {
      const [u, w, h] = v;
      v[0] = u; v[1] = -h; v[2] = w;
    });
  };
  // A plate that follows the surface facing `dir` over the shape's area: from `lo` to `hi`
  // mm along the outward direction, measured from the surface. Sampled with rays on a grid,
  // so it stays clean on steep and nearly vertical walls (a shifted copy of the solid
  // leaves slivers there).
  const surfacePlate = (solid: Manifold, shape: CrossSection, dir: Dir, lo: number, hi: number, step?: number) => {
    const ax = 'xyz'.indexOf(dir.replace('-', ''));
    const sgn = dir.startsWith('-') ? -1 : 1;
    // shape coordinates (u, v) -> world axes, as documented: z: (x, y); x: (y, z); y: (x, z)
    const [iu, iv] = ax === 2 ? [0, 1] : ax === 0 ? [1, 2] : [0, 2];
    const sb = shape.bounds();
    const bb = solid.boundingBox();
    const span = Math.max(sb.max[0] - sb.min[0], sb.max[1] - sb.min[1]);
    let h = step ?? Math.min(0.4, Math.max(0.15, span / 300));
    const pad = 2 * h;
    const u0 = sb.min[0] - pad, v0 = sb.min[1] - pad;
    let nu = Math.ceil((sb.max[0] - sb.min[0] + 2 * pad) / h) + 1;
    let nv = Math.ceil((sb.max[1] - sb.min[1] + 2 * pad) / h) + 1;
    if (nu * nv > 60000) {
      h *= Math.sqrt((nu * nv) / 60000);
      nu = Math.ceil((sb.max[0] - sb.min[0] + 2 * pad) / h) + 1;
      nv = Math.ceil((sb.max[1] - sb.min[1] + 2 * pad) / h) + 1;
    }
    const far = sgn > 0 ? bb.max[ax] + 1 : bb.min[ax] - 1;
    const near = sgn > 0 ? bb.min[ax] - 1 : bb.max[ax] + 1;
    const pos: number[] = [];
    const at = (u: number, v: number, w: number) => {
      const p = [0, 0, 0];
      p[iu] = u;
      p[iv] = v;
      p[ax] = w;
      pos.push(p[0], p[1], p[2]);
    };
    const surf = new Float64Array(nu * nv).fill(NaN);
    const queue: number[] = [];
    for (let j = 0; j < nv; j++)
      for (let i = 0; i < nu; i++) {
        const a: V3 = [0, 0, 0], b: V3 = [0, 0, 0];
        a[iu] = b[iu] = u0 + i * h;
        a[iv] = b[iv] = v0 + j * h;
        a[ax] = far;
        b[ax] = near;
        const hit = solid.rayCast(a, b);
        if (hit.length) {
          surf[j * nu + i] = hit[0].position[ax];
          queue.push(j * nu + i);
        }
      }
    if (!queue.length) throw new Error(`the shape is not over the solid seen from ${dir}`);
    // off the body: continue the nearest surface height, so the plate has no cliffs
    for (let q = 0; q < queue.length; q++) {
      const k = queue[q], i = k % nu, j = Math.floor(k / nu);
      for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const i2 = i + di, j2 = j + dj;
        if (i2 < 0 || j2 < 0 || i2 >= nu || j2 >= nv) continue;
        const k2 = j2 * nu + i2;
        if (Number.isNaN(surf[k2])) {
          surf[k2] = surf[k];
          queue.push(k2);
        }
      }
    }
    const inner = Array.from(surf, (c) => c + sgn * lo);
    const outer = Array.from(surf, (c) => c + sgn * hi);
    for (let k = 0; k < nu * nv; k++) at(u0 + (k % nu) * h, v0 + Math.floor(k / nu) * h, outer[k]);
    for (let k = 0; k < nu * nv; k++) at(u0 + (k % nu) * h, v0 + Math.floor(k / nu) * h, inner[k]);
    const tris: number[] = [];
    const id = (i: number, j: number) => j * nu + i;
    const off = nu * nv;
    for (let j = 0; j < nv - 1; j++)
      for (let i = 0; i < nu - 1; i++) {
        const a = id(i, j), b = id(i + 1, j), c = id(i, j + 1), d = id(i + 1, j + 1);
        tris.push(a, b, d, a, d, c);
        tris.push(off + a, off + d, off + b, off + a, off + c, off + d);
      }
    const ring: number[] = [];
    for (let i = 0; i < nu; i++) ring.push(id(i, 0));
    for (let j = 1; j < nv; j++) ring.push(id(nu - 1, j));
    for (let i = nu - 2; i >= 0; i--) ring.push(id(i, nv - 1));
    for (let j = nv - 2; j > 0; j--) ring.push(id(0, j));
    for (let k = 0; k < ring.length; k++) {
      const a = ring[k], b = ring[(k + 1) % ring.length];
      tris.push(a, off + a, off + b, a, off + b, b);
    }
    return solidFromArrays(wasm, pos, tris).intersect(prism(solid, shape, dir));
  };
  /**
   * Cut a groove of constant depth that follows the curved surface facing `dir` (default:
   * the top). shape: the groove seen from that side (e.g. std.stroke2d(points, 1.2)).
   * Seams between buttons, panel lines, engraved text on a dome.
   */
  const groove = (solid: Manifold, shape: CrossSection, depth: number, o: { dir?: Dir; step?: number } = {}) =>
    solid.subtract(surfacePlate(solid, shape, o.dir ?? 'z', -depth, 1.5, o.step));
  /** Raise a shape by `height` on the curved surface facing `dir` (logos, grips, ribs, side buttons). */
  const emboss = (solid: Manifold, shape: CrossSection, height: number, o: { dir?: Dir; step?: number } = {}) =>
    solid.add(surfacePlate(solid, shape, o.dir ?? 'z', -0.3, height, o.step));
  /** The part of a separate piece that sits on the surface: a plate following it (pads, button caps). */
  const onSurface = (solid: Manifold, shape: CrossSection, thickness: number, o: { dir?: Dir; gap?: number; step?: number } = {}) =>
    surfacePlate(solid, shape, o.dir ?? 'z', o.gap ?? 0, (o.gap ?? 0) + thickness, o.step);
  /** Height of the top surface at (x, y), or null if the solid is not there. */
  const surfaceZ = (solid: Manifold, x: number, y: number, o: { from?: 'top' | 'bottom' } = {}) => {
    const b = solid.boundingBox();
    const top = o.from !== 'bottom';
    const hits = solid.rayCast([x, y, top ? b.max[2] + 1 : b.min[2] - 1], [x, y, top ? b.min[2] - 1 : b.max[2] + 1]);
    return hits.length ? hits[0].position[2] : null;
  };

  // ---------- deformations (refined first so straight edges can curve) ----------
  const refined = (solid: Manifold, edge?: number) => {
    const b = solid.boundingBox();
    const diag = Math.hypot(b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]);
    return solid.refineToLength(edge ?? Math.max(0.5, diag / 80));
  };
  /** Bend along X around the Y axis: the X range becomes an arc of `angle` degrees (upward for positive). */
  const bend = (solid: Manifold, angle: number, o: { edge?: number } = {}) => {
    const b = solid.boundingBox();
    const L = b.max[0] - b.min[0];
    if (Math.abs(angle) < 1e-6 || L <= 0) return solid;
    const th = (angle * Math.PI) / 180;
    const R = L / th;
    const x0 = (b.min[0] + b.max[0]) / 2;
    return refined(solid, o.edge).warp((v: number[]) => {
      const a = (v[0] - x0) / R;
      const r = R - v[2];
      v[0] = x0 + r * Math.sin(a);
      v[2] = R - r * Math.cos(a);
    });
  };
  /** Scale XY linearly from 1 at the bottom to `scaleTop` at the top. */
  const taper = (solid: Manifold, scaleTop: number | V2, o: { edge?: number } = {}) => {
    const b = solid.boundingBox();
    const [sx, sy] = typeof scaleTop === 'number' ? [scaleTop, scaleTop] : scaleTop;
    const h = b.max[2] - b.min[2] || 1;
    return refined(solid, o.edge).warp((v: number[]) => {
      const t = (v[2] - b.min[2]) / h;
      v[0] *= 1 + (sx - 1) * t;
      v[1] *= 1 + (sy - 1) * t;
    });
  };
  /** Twist around Z by `angle` degrees over the height. */
  const twist = (solid: Manifold, angle: number, o: { edge?: number } = {}) => {
    const b = solid.boundingBox();
    const h = b.max[2] - b.min[2] || 1;
    return refined(solid, o.edge).warp((v: number[]) => {
      const a = (((v[2] - b.min[2]) / h) * angle * Math.PI) / 180;
      const c = Math.cos(a), s = Math.sin(a);
      const x = v[0];
      v[0] = c * x - s * v[1];
      v[1] = s * x + c * v[1];
    });
  };

  return {
    spline2d, spline3d, arc2d, stroke2d, loft, sweep, pipe,
    smooth, offset3d, round3d, shell3d,
    groove, emboss, onSurface, surfaceZ,
    bend, taper, twist,
  };
}
