// Signed distance fields: smooth, organic and "product design" shapes that CSG cannot
// express (blended bodies, rounded extrusions, pillows, shells). Fields are composed in
// JS and turned into a closed manifold once, with Manifold.levelSet.
//
// Convention: negative inside, all primitives centred at the origin, sizes are FULL
// extents in mm (like std.box / std.cyl). Every field carries a conservative bounding
// box so .mesh() needs no arguments.
import type { CrossSection, Manifold, Wasm } from '../kernel.ts';
import { detail } from '../kernel.ts';

type V2 = [number, number];
type V3 = [number, number, number];
type Box = { min: V3; max: V3 };
type Fn = (x: number, y: number, z: number) => number;

const INF = 1e9;
const len2 = (x: number, y: number) => Math.sqrt(x * x + y * y);
const len3 = (x: number, y: number, z: number) => Math.sqrt(x * x + y * y + z * z);
const clamp = (v: number, a: number, b: number) => (v < a ? a : v > b ? b : v);

// polynomial smooth min/max (blend radius k, bulges by at most k/4)
export const smin = (a: number, b: number, k: number) => {
  if (k <= 0) return Math.min(a, b);
  const h = Math.max(k - Math.abs(a - b), 0) / k;
  return Math.min(a, b) - h * h * k * 0.25;
};
const smax = (a: number, b: number, k: number) => -smin(-a, -b, k);

const boxOf = (min: V3, max: V3): Box => ({ min, max });
const grow = (b: Box, d: number): Box => boxOf([b.min[0] - d, b.min[1] - d, b.min[2] - d], [b.max[0] + d, b.max[1] + d, b.max[2] + d]);
const merge = (a: Box, b: Box): Box =>
  boxOf([Math.min(a.min[0], b.min[0]), Math.min(a.min[1], b.min[1]), Math.min(a.min[2], b.min[2])],
    [Math.max(a.max[0], b.max[0]), Math.max(a.max[1], b.max[1]), Math.max(a.max[2], b.max[2])]);
const meet = (a: Box, b: Box): Box =>
  boxOf([Math.max(a.min[0], b.min[0]), Math.max(a.min[1], b.min[1]), Math.max(a.min[2], b.min[2])],
    [Math.min(a.max[0], b.max[0]), Math.min(a.max[1], b.max[1]), Math.min(a.max[2], b.max[2])]);
const finite = (b: Box) => [...b.min, ...b.max].every((v) => Math.abs(v) < INF / 2);

// Rotation in degrees, applied X then Y then Z (same as Manifold.rotate).
function rotMatrix(r: V3): number[] {
  const [a, b, c] = r.map((d) => (d * Math.PI) / 180);
  const cx = Math.cos(a), sx = Math.sin(a), cy = Math.cos(b), sy = Math.sin(b), cz = Math.cos(c), sz = Math.sin(c);
  // R = Rz * Ry * Rx (row-major)
  return [
    cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx,
    sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx,
    -sy, cy * sx, cy * cx,
  ];
}
function transformBox(b: Box, f: (p: V3) => V3): Box {
  let out: Box | null = null;
  for (let i = 0; i < 8; i++) {
    const p = f([i & 1 ? b.max[0] : b.min[0], i & 2 ? b.max[1] : b.min[1], i & 4 ? b.max[2] : b.min[2]]);
    out = out ? merge(out, boxOf(p, p)) : boxOf(p, p);
  }
  return out!;
}

// Cache for 2D functions sampled by a 3D grid: every z of a column asks the same (x, y),
// so outlines with hundreds of segments cost one evaluation per column, not per point.
export function memo2(fn: (x: number, y: number) => number): (x: number, y: number) => number {
  let rows = new Map<number, Map<number, number>>();
  let size = 0;
  return (x, y) => {
    let row = rows.get(x);
    if (!row) {
      if (size > 4e6) {
        rows = new Map();
        size = 0;
      }
      row = new Map();
      rows.set(x, row);
    }
    let v = row.get(y);
    if (v === undefined) {
      v = fn(x, y);
      row.set(y, v);
      size++;
    }
    return v;
  };
}

// 2D signed distance to polygon loops (even-odd fill), negative inside.
export function polygonSdf(loops: V2[][]): (x: number, y: number) => number {
  const segs: number[] = [];
  for (const loop of loops)
    for (let i = 0, j = loop.length - 1; i < loop.length; j = i++) segs.push(loop[j][0], loop[j][1], loop[i][0], loop[i][1]);
  const n = segs.length / 4;
  return memo2((x, y) => {
    let best = Infinity;
    let inside = false;
    for (let s = 0; s < n; s++) {
      const ax = segs[s * 4], ay = segs[s * 4 + 1], bx = segs[s * 4 + 2], by = segs[s * 4 + 3];
      const ex = bx - ax, ey = by - ay, wx = x - ax, wy = y - ay;
      const t = clamp((wx * ex + wy * ey) / (ex * ex + ey * ey || 1e-12), 0, 1);
      const dx = wx - ex * t, dy = wy - ey * t;
      const d = dx * dx + dy * dy;
      if (d < best) best = d;
      if (ay > y !== by > y && x < (ex * (y - ay)) / (ey || 1e-12) + ax) inside = !inside;
    }
    const d = Math.sqrt(best);
    return inside ? -d : d;
  });
}

const loopsOf = (shape: CrossSection | V2[] | V2[][]): V2[][] => {
  if (Array.isArray(shape)) return Array.isArray(shape[0]?.[0]) ? (shape as V2[][]) : [shape as V2[]];
  return (shape as CrossSection).toPolygons() as V2[][];
};
const loopsBox = (loops: V2[][]) => {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const l of loops) for (const [x, y] of l) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  return { x0, y0, x1, y1 };
};

export class Field {
  readonly f: Fn;
  readonly box: Box;
  private wasm: Wasm;
  constructor(wasm: Wasm, f: Fn, box: Box) {
    this.wasm = wasm;
    this.f = f;
    this.box = box;
  }
  private make(f: Fn, box: Box) {
    return new Field(this.wasm, f, box);
  }

  /** Distance at a point (negative inside). */
  at(p: V3) {
    return this.f(p[0], p[1], p[2]);
  }

  // ---- booleans (others may be several fields) ----
  union(...others: Field[]) {
    const fs = [this, ...others];
    return this.make((x, y, z) => {
      let d = Infinity;
      for (const s of fs) d = Math.min(d, s.f(x, y, z));
      return d;
    }, fs.map((s) => s.box).reduce(merge));
  }
  subtract(...others: Field[]) {
    const a = this.f;
    return this.make((x, y, z) => {
      let d = a(x, y, z);
      for (const s of others) d = Math.max(d, -s.f(x, y, z));
      return d;
    }, this.box);
  }
  intersect(...others: Field[]) {
    const fs = [this, ...others];
    return this.make((x, y, z) => {
      let d = -Infinity;
      for (const s of fs) d = Math.max(d, s.f(x, y, z));
      return d;
    }, fs.map((s) => s.box).reduce(meet));
  }
  /** Blend with a fillet of about k mm where the shapes meet. */
  smoothUnion(other: Field | Field[], k: number) {
    const os = Array.isArray(other) ? other : [other];
    const a = this.f;
    return this.make((x, y, z) => {
      let d = a(x, y, z);
      for (const s of os) d = smin(d, s.f(x, y, z), k);
      return d;
    }, grow([this.box, ...os.map((s) => s.box)].reduce(merge), k / 4));
  }
  /** Cut with a rounded (k mm) inner edge. */
  smoothSubtract(other: Field | Field[], k: number) {
    const os = Array.isArray(other) ? other : [other];
    const a = this.f;
    return this.make((x, y, z) => {
      let d = a(x, y, z);
      for (const s of os) d = smax(d, -s.f(x, y, z), k);
      return d;
    }, this.box);
  }
  smoothIntersect(other: Field | Field[], k: number) {
    const os = Array.isArray(other) ? other : [other];
    const a = this.f;
    return this.make((x, y, z) => {
      let d = a(x, y, z);
      for (const s of os) d = smax(d, s.f(x, y, z), k);
      return d;
    }, [this.box, ...os.map((s) => s.box)].reduce(meet));
  }

  // ---- surface operations ----
  /** Grow (d > 0) or shrink (d < 0) the surface; growing also rounds convex edges. */
  offset(d: number) {
    const a = this.f;
    return this.make((x, y, z) => a(x, y, z) - d, grow(this.box, Math.max(0, d)));
  }
  /** Hollow inward: keeps the outer surface, wall thickness t. */
  shell(t: number) {
    const a = this.f;
    return this.make((x, y, z) => {
      const d = a(x, y, z);
      return Math.max(d, -(d + t));
    }, this.box);
  }
  /** Add a displacement in mm (positive pushes the surface out). `amplitude` bounds |fn|. */
  displace(fn: (p: V3) => number, amplitude: number) {
    const a = this.f;
    return this.make((x, y, z) => a(x, y, z) - fn([x, y, z]), grow(this.box, Math.abs(amplitude)));
  }

  // ---- placement ----
  translate(v: V3) {
    const a = this.f;
    const [tx, ty, tz] = v;
    return this.make((x, y, z) => a(x - tx, y - ty, z - tz), boxOf(
      [this.box.min[0] + tx, this.box.min[1] + ty, this.box.min[2] + tz], [this.box.max[0] + tx, this.box.max[1] + ty, this.box.max[2] + tz]));
  }
  rotate(r: V3) {
    const R = rotMatrix(r);
    const a = this.f;
    // inverse rotation = transpose
    return this.make(
      (x, y, z) => a(R[0] * x + R[3] * y + R[6] * z, R[1] * x + R[4] * y + R[7] * z, R[2] * x + R[5] * y + R[8] * z),
      transformBox(this.box, ([x, y, z]) => [R[0] * x + R[1] * y + R[2] * z, R[3] * x + R[4] * y + R[5] * z, R[6] * x + R[7] * y + R[8] * z]),
    );
  }
  /** Uniform or per-axis scale (per-axis distances are approximate but fine for meshing). */
  scale(s: number | V3) {
    const [sx, sy, sz] = typeof s === 'number' ? [s, s, s] : s;
    const k = Math.min(Math.abs(sx), Math.abs(sy), Math.abs(sz));
    const a = this.f;
    return this.make((x, y, z) => a(x / sx, y / sy, z / sz) * k, transformBox(this.box, ([x, y, z]) => [x * sx, y * sy, z * sz]));
  }
  /** Mirror the positive half onto the negative half of an axis (perfect symmetry). */
  symmetric(axis: 'x' | 'y' | 'z' = 'x') {
    const a = this.f;
    const i = 'xyz'.indexOf(axis);
    const box = boxOf([...this.box.min] as V3, [...this.box.max] as V3);
    const m = Math.max(Math.abs(box.min[i]), Math.abs(box.max[i]));
    box.min[i] = -m;
    box.max[i] = m;
    if (i === 0) return this.make((x, y, z) => a(Math.abs(x), y, z), box);
    if (i === 1) return this.make((x, y, z) => a(x, Math.abs(y), z), box);
    return this.make((x, y, z) => a(x, y, Math.abs(z)), box);
  }
  /** Twist around Z by `degPerMm` degrees per mm of height. */
  twist(degPerMm: number) {
    const a = this.f;
    const k = (degPerMm * Math.PI) / 180;
    const r = Math.max(...[this.box.min[0], this.box.max[0], this.box.min[1], this.box.max[1]].map(Math.abs)) * Math.SQRT2;
    return this.make((x, y, z) => {
      const c = Math.cos(-k * z), s = Math.sin(-k * z);
      return a(c * x - s * y, s * x + c * y, z) * 0.8;
    }, boxOf([-r, -r, this.box.min[2]], [r, r, this.box.max[2]]));
  }
  /** Arbitrary domain warp: fn maps a world point to the point to sample. Give the new bounds. */
  warp(fn: (p: V3) => V3, bounds?: Box) {
    const a = this.f;
    return this.make((x, y, z) => {
      const q = fn([x, y, z]);
      return a(q[0], q[1], q[2]) * 0.8;
    }, bounds ?? this.box);
  }
  /** Override the bounding box used for meshing. */
  bounds(min: V3, max: V3) {
    return this.make(this.f, boxOf(min, max));
  }

  /**
   * Mesh into a closed Manifold. edge: target triangle size in mm (smaller = finer, slower);
   * by default chosen from the size, capped so meshing stays within a couple of seconds.
   */
  mesh(o: { edge?: number; tolerance?: number; simplify?: number | false } = {}): Manifold {
    if (!finite(this.box)) throw new Error('sdf.mesh: unbounded field (intersect half-spaces with a finite shape, or call .bounds(min, max))');
    const size = [0, 1, 2].map((i) => this.box.max[i] - this.box.min[i]);
    if (size.some((v) => v <= 0)) throw new Error('sdf.mesh: empty field (the shapes do not overlap)');
    const diag = len3(size[0], size[1], size[2]);
    let edge = (o.edge ?? clamp(diag / 140, 0.35, 2)) * detail.factor;
    // keep the grid under ~1.6M points (a preview under a fraction of that)
    const cap = 1.6e6 / detail.factor ** 3;
    const cells = (size[0] * size[1] * size[2]) / edge ** 3;
    if (cells > cap) edge *= Math.cbrt(cells / cap);
    const b = grow(this.box, edge * 2);
    const f = this.f;
    const m = (this.wasm.Manifold as any).levelSet((p: V3) => -f(p[0], p[1], p[2]), b, edge, 0, o.tolerance ?? edge / 20) as Manifold;
    // marching tetrahedra over-tessellates flat and gently curved areas: 3-30x fewer
    // triangles for < 0.1% volume change
    return o.simplify === false ? m : m.simplify(o.simplify ?? 0.02);
  }
}

export function makeSdf(wasm: Wasm) {
  const F = (f: Fn, box: Box) => new Field(wasm, f, box);
  const half = (s: V3) => s.map((v) => v / 2) as V3;

  const sphere = (d: number) => {
    const r = d / 2;
    return F((x, y, z) => len3(x, y, z) - r, boxOf([-r, -r, -r], [r, r, r]));
  };
  /** Ellipsoid with full sizes [x, y, z]. */
  const ellipsoid = (size: V3) => {
    const [a, b, c] = half(size);
    return F((x, y, z) => {
      const k0 = len3(x / a, y / b, z / c);
      const k1 = len3(x / (a * a), y / (b * b), z / (c * c));
      return k1 < 1e-12 ? -Math.min(a, b, c) : (k0 * (k0 - 1)) / k1;
    }, boxOf([-a, -b, -c], [a, b, c]));
  };
  /** Box with full sizes, optional edge radius r. */
  const box = (size: V3 | number, o: { r?: number } = {}) => {
    const s: V3 = typeof size === 'number' ? [size, size, size] : size;
    const [hx, hy, hz] = half(s);
    const r = clamp(o.r ?? 0, 0, Math.min(hx, hy, hz));
    return F((x, y, z) => {
      const qx = Math.abs(x) - hx + r, qy = Math.abs(y) - hy + r, qz = Math.abs(z) - hz + r;
      return len3(Math.max(qx, 0), Math.max(qy, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qy, qz), 0) - r;
    }, boxOf([-hx, -hy, -hz], [hx, hy, hz]));
  };
  /** Cylinder along Z, diameter d, height h, optional edge radius r. */
  const cylinder = (d: number, h: number, o: { r?: number } = {}) => {
    const R = d / 2, H = h / 2;
    const r = clamp(o.r ?? 0, 0, Math.min(R, H));
    return F((x, y, z) => {
      const qx = len2(x, y) - R + r, qz = Math.abs(z) - H + r;
      return len2(Math.max(qx, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qz), 0) - r;
    }, boxOf([-R, -R, -H], [R, R, H]));
  };
  /** Cone frustum along Z: bottom diameter d1, top d2, height h. */
  const cone = (d1: number, d2: number, h: number) => {
    const r1 = d1 / 2, r2 = d2 / 2, H = h / 2;
    const R = Math.max(r1, r2);
    return F((x, y, z) => {
      const q = len2(x, y);
      const k1x = r2, k1y = H, k2x = r2 - r1, k2y = 2 * H;
      const cax = q - Math.min(q, z < 0 ? r1 : r2), cay = Math.abs(z) - H;
      const t = clamp(((k1x - q) * k2x + (k1y - z) * k2y) / (k2x * k2x + k2y * k2y), 0, 1);
      const cbx = q - k1x + k2x * t, cby = z - k1y + k2y * t;
      const s = cbx < 0 && cay < 0 ? -1 : 1;
      return s * Math.sqrt(Math.min(cax * cax + cay * cay, cbx * cbx + cby * cby));
    }, boxOf([-R, -R, -H], [R, R, H]));
  };
  /** Capsule (rounded rod) from a to b, diameter d. */
  const capsule = (a: V3, b: V3, d: number) => {
    const r = d / 2;
    const ex = b[0] - a[0], ey = b[1] - a[1], ez = b[2] - a[2];
    const ee = ex * ex + ey * ey + ez * ez || 1e-12;
    return F((x, y, z) => {
      const wx = x - a[0], wy = y - a[1], wz = z - a[2];
      const t = clamp((wx * ex + wy * ey + wz * ez) / ee, 0, 1);
      return len3(wx - ex * t, wy - ey * t, wz - ez * t) - r;
    }, grow(merge(boxOf(a, a), boxOf(b, b)), r));
  };
  /** Torus in the XY plane: ring diameter D (centre line), tube diameter d. */
  const torus = (D: number, d: number) => {
    const R = D / 2, r = d / 2;
    return F((x, y, z) => len2(len2(x, y) - R, z) - r, boxOf([-R - r, -R - r, -r], [R + r, R + r, r]));
  };
  /** Half-space n·p <= offset (unbounded: intersect it with a finite shape). */
  const halfspace = (normal: V3, offset = 0) => {
    const l = len3(...normal) || 1;
    const [nx, ny, nz] = normal.map((v) => v / l);
    return F((x, y, z) => nx * x + ny * y + nz * z - offset, boxOf([-INF, -INF, -INF], [INF, INF, INF]));
  };
  /**
   * Extrusion of a 2D outline (CrossSection or point loops), centred in Z, height h.
   * r rounds the top and bottom edges (pillow-like); the outline keeps its size.
   */
  const extrude = (shape: CrossSection | V2[] | V2[][], h: number, o: { r?: number } = {}) => {
    const loops = loopsOf(shape);
    const d2 = polygonSdf(loops);
    const { x0, y0, x1, y1 } = loopsBox(loops);
    const H = h / 2;
    const r = clamp(o.r ?? 0, 0, H);
    return F((x, y, z) => {
      const wx = d2(x, y) + r, wy = Math.abs(z) - H + r;
      return Math.min(Math.max(wx, wy), 0) + len2(Math.max(wx, 0), Math.max(wy, 0)) - r;
    }, boxOf([x0, y0, -H], [x1, y1, H]));
  };
  /** Revolve a profile given in (r, z) around Z (r >= 0). */
  const revolve = (profile: CrossSection | V2[] | V2[][]) => {
    const loops = loopsOf(profile);
    const d2 = polygonSdf(loops);
    const { y0, x1, y1 } = loopsBox(loops);
    return F((x, y, z) => d2(len2(x, y), z), boxOf([-x1, -x1, y0], [x1, x1, y1]));
  };
  /**
   * Solid between z=0 and a top surface z = top(x, y) inside a plan outline: mice, soap,
   * handles, palm rests. r rounds where the top meets the side walls.
   */
  const heightfield = (shape: CrossSection | V2[] | V2[][], topFn: (x: number, y: number) => number, o: { r?: number; maxHeight?: number } = {}) => {
    const top = memo2(topFn);
    const loops = loopsOf(shape);
    const d2 = polygonSdf(loops);
    const { x0, y0, x1, y1 } = loopsBox(loops);
    let zmax = o.maxHeight ?? 0;
    if (!o.maxHeight)
      for (let i = 0; i <= 24; i++)
        for (let j = 0; j <= 24; j++) zmax = Math.max(zmax, top(x0 + ((x1 - x0) * i) / 24, y0 + ((y1 - y0) * j) / 24));
    const r = Math.max(0, o.r ?? 0);
    return F((x, y, z) => {
      const side = d2(x, y);
      // vertical distance overestimates on slopes: scale down to stay conservative
      const lid = (z - top(x, y)) * 0.7;
      return Math.max(smax(side, lid, r), -z);
    }, boxOf([x0, y0, 0], [x1, y1, zmax * 1.05 + 1]));
  };
  /**
   * A soft product body over a plan outline: full height h(x, y) inside, falling to the outline along a
   * quarter circle `edge` mm wide (by distance from the outline, so it follows any plan shape without
   * creases). Mice, remotes, soap, pebbles, grips. height: number or (x, y) => mm; r softens the foot.
   */
  const pillow = (shape: CrossSection | V2[] | V2[][], height: number | ((x: number, y: number) => number), o: { edge?: number; r?: number } = {}) => {
    const loops = loopsOf(shape);
    const d2 = polygonSdf(loops);
    const { x0, y0, x1, y1 } = loopsBox(loops);
    const edge = Math.max(0.5, o.edge ?? Math.min(x1 - x0, y1 - y0) * 0.35);
    const h = typeof height === 'number' ? () => height : height;
    let zmax = 0;
    for (let i = 0; i <= 24; i++)
      for (let j = 0; j <= 24; j++) zmax = Math.max(zmax, h(x0 + ((x1 - x0) * i) / 24, y0 + ((y1 - y0) * j) / 24));
    return heightfield(shape, (x, y) => {
      const t = Math.min(1, Math.max(0, -d2(x, y) / edge));
      return h(x, y) * Math.sqrt(1 - (1 - t) * (1 - t));
    }, { r: o.r ?? 0, maxHeight: zmax });
  };
  /** Union of many fields with a common blend radius. */
  const blend = (fields: Field[], k: number) => fields.slice(1).reduce((acc, f) => acc.smoothUnion(f, k), fields[0]);
  const union = (fields: Field[]) => fields[0].union(...fields.slice(1));
  /** Wrap any distance function (negative inside) with explicit bounds. */
  const custom = (fn: (p: V3) => number, min: V3, max: V3) => F((x, y, z) => fn([x, y, z]), boxOf(min, max));

  return { sphere, ellipsoid, box, cylinder, cone, capsule, torus, halfspace, extrude, revolve, heightfield, pillow, blend, union, custom, smin };
}
