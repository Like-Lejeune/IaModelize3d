// Generative and stylized forms: parametric surfaces of revolution (vases, shades),
// lattices, terrain tiles, voxel and low-poly stylization. All outputs are closed
// manifolds, so they pass straight into printability checks.
import type { CrossSection, Manifold, Wasm } from '../kernel.ts';

type V3 = [number, number, number];

export interface SurfaceOptions {
  height: number;
  // Outer radius at height z (0..height) and angle theta (radians); t = z/height.
  radius: (z: number, theta: number, t: number) => number;
  mode?: 'solid' | 'shell' | 'open'; // solid: for vase mode; shell: walls + bottom; open: tube (lamp shade)
  wall?: number;
  bottom?: number;
  segments?: number;
  rings?: number;
}

// Perlin-style gradient noise, deterministic per seed.
export function makeNoise(seed = 1) {
  const perm = new Uint8Array(512);
  let s = seed >>> 0 || 1;
  const rand = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  const p = Array.from({ length: 256 }, (_, i) => i);
  for (let i = 255; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [p[i], p[j]] = [p[j], p[i]];
  }
  for (let i = 0; i < 512; i++) perm[i] = p[i & 255];
  const fade = (t: number) => t * t * t * (t * (t * 6 - 15) + 10);
  const grad = (h: number, x: number, y: number, z: number) => {
    const u = (h & 15) < 8 ? x : y;
    const v = (h & 15) < 4 ? y : (h & 15) === 12 || (h & 15) === 14 ? x : z;
    return ((h & 1) === 0 ? u : -u) + ((h & 2) === 0 ? v : -v);
  };
  const lerp = (a: number, b: number, t: number) => a + t * (b - a);
  const noise3 = (x: number, y = 0, z = 0) => {
    const X = Math.floor(x) & 255, Y = Math.floor(y) & 255, Z = Math.floor(z) & 255;
    x -= Math.floor(x); y -= Math.floor(y); z -= Math.floor(z);
    const u = fade(x), v = fade(y), w = fade(z);
    const A = perm[X] + Y, AA = perm[A] + Z, AB = perm[A + 1] + Z;
    const B = perm[X + 1] + Y, BA = perm[B] + Z, BB = perm[B + 1] + Z;
    return lerp(
      lerp(lerp(grad(perm[AA], x, y, z), grad(perm[BA], x - 1, y, z), u),
        lerp(grad(perm[AB], x, y - 1, z), grad(perm[BB], x - 1, y - 1, z), u), v),
      lerp(lerp(grad(perm[AA + 1], x, y, z - 1), grad(perm[BA + 1], x - 1, y, z - 1), u),
        lerp(grad(perm[AB + 1], x, y - 1, z - 1), grad(perm[BB + 1], x - 1, y - 1, z - 1), u), v),
      w,
    );
  };
  const fbm = (x: number, y = 0, z = 0, octaves = 4) => {
    let amp = 0.5, f = 1, sum = 0;
    for (let i = 0; i < octaves; i++) {
      sum += amp * noise3(x * f, y * f, z * f);
      amp *= 0.5;
      f *= 2;
    }
    return sum;
  };
  return { noise3, fbm, rand };
}

export function makeForms(wasm: Wasm) {
  const { Manifold: M, CrossSection: CS, Mesh } = wasm as any;

  const fromMesh = (positions: number[], tris: number[]): Manifold => {
    const mesh = new Mesh({ numProp: 3, vertProperties: new Float32Array(positions), triVerts: new Uint32Array(tris) });
    mesh.merge();
    return M.ofMesh(mesh);
  };

  // Builds a closed mesh: outer surface rings, top rim, inner surface (shell/open), bottom.
  const surface = (o: SurfaceOptions): Manifold => {
    const mode = o.mode ?? 'shell';
    const segs = o.segments ?? 180;
    const rings = o.rings ?? Math.max(24, Math.ceil(o.height / 1.0));
    const wall = o.wall ?? 1.6;
    const bottom = mode === 'open' ? 0 : o.bottom ?? 2;
    const pos: number[] = [];
    const tri: number[] = [];
    const vert = (x: number, y: number, z: number) => {
      pos.push(x, y, z);
      return pos.length / 3 - 1;
    };
    const ring = (z: number, rOf: (theta: number) => number) => {
      const ids: number[] = [];
      for (let k = 0; k < segs; k++) {
        const th = (2 * Math.PI * k) / segs;
        const r = Math.max(0.2, rOf(th));
        ids.push(vert(r * Math.cos(th), r * Math.sin(th), z));
      }
      return ids;
    };
    // quad strip between ring a (lower) and b (upper); outward = true for outer skin
    const strip = (a: number[], b: number[], outward: boolean) => {
      for (let k = 0; k < segs; k++) {
        const k2 = (k + 1) % segs;
        if (outward) tri.push(a[k], a[k2], b[k2], a[k], b[k2], b[k]);
        else tri.push(a[k], b[k2], a[k2], a[k], b[k], b[k2]);
      }
    };
    const fan = (center: number, r: number[], up: boolean) => {
      for (let k = 0; k < segs; k++) {
        const k2 = (k + 1) % segs;
        if (up) tri.push(center, r[k], r[k2]);
        else tri.push(center, r[k2], r[k]);
      }
    };
    const outer: number[][] = [];
    for (let i = 0; i <= rings; i++) {
      const z = (o.height * i) / rings;
      outer.push(ring(z, (th) => o.radius(z, th, z / o.height)));
    }
    for (let i = 0; i < rings; i++) strip(outer[i], outer[i + 1], true);
    if (mode === 'solid') {
      fan(vert(0, 0, 0), outer[0], false);
      fan(vert(0, 0, o.height), outer[rings], true);
    } else {
      // inner skin: radius - wall, from top down to `bottom` (or 0 for open tubes)
      const inner: number[][] = [];
      const z0 = bottom;
      for (let i = 0; i <= rings; i++) {
        const z = z0 + ((o.height - z0) * i) / rings;
        inner.push(ring(z, (th) => o.radius(z, th, z / o.height) - wall));
      }
      for (let i = 0; i < rings; i++) strip(inner[i], inner[i + 1], false);
      // top rim joins outer top to inner top
      strip(inner[rings], outer[rings], false);
      if (mode === 'open') {
        strip(outer[0], inner[0], false);
      } else {
        fan(vert(0, 0, 0), outer[0], false);
        fan(vert(0, 0, z0), inner[0], true);
      }
    }
    return fromMesh(pos, tri);
  };

  // Gyroid lattice clipped to `solid`. Cost grows with (size/cell)^3 * quality^3.
  const gyroid = (solid: Manifold, o: { cell?: number; wall?: number; quality?: number } = {}): Manifold => {
    const cell = o.cell ?? 12;
    const wall = o.wall ?? 1.2;
    const k = (2 * Math.PI) / cell;
    const b = solid.boundingBox();
    const sdf = ([x, y, z]: V3) => {
      const g = Math.sin(k * x) * Math.cos(k * y) + Math.sin(k * y) * Math.cos(k * z) + Math.sin(k * z) * Math.cos(k * x);
      return wall / 2 - (Math.abs(g) / k) * 0.85;
    };
    const lattice = M.levelSet(sdf, b, cell / (10 * (o.quality ?? 1)));
    return lattice.intersect(solid);
  };

  // Heightmap tile: `data` is row-major h x w (meters or any unit), scaled to sizeX/sizeY mm.
  const terrain = (
    hm: { w: number; h: number; data: ArrayLike<number> },
    o: { sizeX: number; sizeY?: number; zScale?: number; base?: number; maxHeight?: number },
  ): Manifold => {
    const { w, h, data } = hm;
    const sizeY = o.sizeY ?? (o.sizeX * (h - 1)) / (w - 1);
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < w * h; i++) {
      lo = Math.min(lo, data[i]);
      hi = Math.max(hi, data[i]);
    }
    const metersPerMm = 1; // caller passes zScale in mm per data unit
    const zScale = o.maxHeight ? o.maxHeight / Math.max(1e-6, hi - lo) : (o.zScale ?? 1) / metersPerMm;
    const base = o.base ?? 3;
    const pos: number[] = [];
    const tri: number[] = [];
    const idx = (i: number, j: number) => j * w + i;
    for (let j = 0; j < h; j++)
      for (let i = 0; i < w; i++) pos.push((i / (w - 1)) * o.sizeX, sizeY - (j / (h - 1)) * sizeY, base + (data[idx(i, j)] - lo) * zScale);
    for (let j = 0; j < h - 1; j++)
      for (let i = 0; i < w - 1; i++) {
        const a = idx(i, j), b2 = idx(i + 1, j), c = idx(i, j + 1), d = idx(i + 1, j + 1);
        tri.push(a, c, b2, b2, c, d);
      }
    // perimeter, counter-clockwise seen from above
    const perim: number[] = [];
    for (let i = 0; i < w; i++) perim.push(idx(i, h - 1));
    for (let j = h - 2; j >= 0; j--) perim.push(idx(w - 1, j));
    for (let i = w - 2; i >= 0; i--) perim.push(idx(i, 0));
    for (let j = 1; j < h - 1; j++) perim.push(idx(0, j));
    const bottomIds = perim.map((t) => {
      pos.push(pos[t * 3], pos[t * 3 + 1], 0);
      return pos.length / 3 - 1;
    });
    const n = perim.length;
    for (let k = 0; k < n; k++) {
      const k2 = (k + 1) % n;
      tri.push(perim[k], bottomIds[k], bottomIds[k2], perim[k], bottomIds[k2], perim[k2]);
    }
    pos.push(o.sizeX / 2, sizeY / 2, 0);
    const center = pos.length / 3 - 1;
    for (let k = 0; k < n; k++) tri.push(center, bottomIds[(k + 1) % n], bottomIds[k]);
    let m = fromMesh(pos, tri);
    if (m.volume() < 0) m = m.mirror([0, 0, 1]);
    return m;
  };

  const pointInPolys = (polys: [number, number][][], x: number, y: number) => {
    let inside = false;
    for (const poly of polys) {
      for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        const [xi, yi] = poly[i];
        const [xj, yj] = poly[j];
        if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
      }
    }
    return inside;
  };

  // Voxel stylization: each layer is a union of squares, extruded and stacked.
  const voxelize = (solid: Manifold, size: number): Manifold => {
    const b = solid.boundingBox();
    const layers: Manifold[] = [];
    for (let z = b.min[2] + size / 2; z < b.max[2]; z += size) {
      const polys = solid.slice(z).toPolygons() as [number, number][][];
      if (!polys.length) continue;
      const squares: CrossSection[] = [];
      for (let x = Math.floor(b.min[0] / size) * size; x < b.max[0]; x += size)
        for (let y = Math.floor(b.min[1] / size) * size; y < b.max[1]; y += size)
          if (pointInPolys(polys, x + size / 2, y + size / 2)) squares.push(CS.square([size, size], false).translate([x, y]));
      if (squares.length) layers.push(CS.union(squares).extrude(size).translate([0, 0, z - size / 2]));
    }
    return M.union(layers);
  };

  const lowpoly = (solid: Manifold, tolerance = 1.5): Manifold => solid.simplify(tolerance);

  // ---- relief elements: each points along +X, base on the x=0 plane (embedded 0.6 mm to fuse) ----
  const EMBED = 0.6;
  // Cube corner seen along its diagonal: a hexagon of three rhombi ("isometric cube" look).
  // With one face up, the two lower faces lean only ~24° from vertical, so it prints without support.
  const cubeCorner = (edge: number): Manifold => {
    const R = edge * Math.sqrt(2 / 3);
    const hMid = edge / Math.sqrt(3);
    const hApex = (2 * edge) / Math.sqrt(3);
    const at = (deg: number, r: number, x: number): V3 => [x, r * Math.cos((deg * Math.PI) / 180), r * Math.sin((deg * Math.PI) / 180)];
    const pts: V3[] = [
      [hApex, 0, 0],
      at(90, R, 0), at(210, R, 0), at(330, R, 0), // rim on the wall; the top face's corner points up
      at(30, R, hMid), at(150, R, hMid), at(270, R, hMid),
      [0, 0, -(R + hMid)], // 45° skirt under the lowest corner
      [-EMBED, 0, R], [-EMBED, 0, -(R + hMid)], [-EMBED, R, 0], [-EMBED, -R, 0],
    ];
    return M.hull(pts);
  };
  // Hexagonal pyramid; keep height <= apothem for support-free printing on vertical walls.
  const hexPyramid = (radius: number, height?: number): Manifold => {
    const h = height ?? radius * Math.cos(Math.PI / 6);
    const pts: V3[] = [[h, 0, 0]];
    for (let k = 0; k < 6; k++) {
      const a = (Math.PI / 3) * k + Math.PI / 2;
      pts.push([0, radius * Math.cos(a), radius * Math.sin(a)], [-EMBED, radius * Math.cos(a), radius * Math.sin(a)]);
    }
    return M.hull(pts);
  };
  const dome = (radius: number, height?: number): Manifold =>
    M.sphere(radius, 32).scale([(height ?? radius * 0.7) / radius, 1, 1]).trimByPlane([1, 0, 0], -EMBED);
  const stud = (d: number, height: number): Manifold =>
    M.cylinder(height + EMBED, d / 2, d / 2 * 0.6, 24).rotate([0, 90, 0]).translate([-EMBED, 0, 0]);

  // Tile a surface of revolution with relief elements on a (staggered) grid.
  // radius(z) is the outer wall radius; elements are oriented radially outward.
  const tile = (o: {
    radius: (z: number) => number;
    element: Manifold;
    rows: number;
    perRow: number;
    z0: number;
    z1: number;
    stagger?: boolean;
    twist?: number; // degrees added per row
    floor?: number; // nothing below this z (default 0: the bed), so skirts never lift the body
  }): Manifold => {
    const items: Manifold[] = [];
    const dz = o.rows > 1 ? (o.z1 - o.z0) / (o.rows - 1) : 0;
    for (let i = 0; i < o.rows; i++) {
      const z = o.z0 + i * dz;
      const r = o.radius(z);
      for (let j = 0; j < o.perRow; j++) {
        const theta = (360 * (j + (o.stagger === false ? 0 : (i % 2) * 0.5))) / o.perRow + (o.twist ?? 0) * i;
        items.push(o.element.rotate([0, 0, theta]).translate([r * Math.cos((theta * Math.PI) / 180), r * Math.sin((theta * Math.PI) / 180), z]));
      }
    }
    return M.union(items).trimByPlane([0, 0, 1], o.floor ?? 0);
  };

  return { surface, gyroid, terrain, voxelize, lowpoly, fromMesh, cubeCorner, hexPyramid, dome, stud, tile };
}
