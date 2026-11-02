// Mechanisms: involute gears, print-in-place hinges, snap hooks, dovetails.
import type { CrossSection, Manifold, Wasm } from '../kernel.ts';

type V2 = [number, number];

export function makeMech(wasm: Wasm, fit: (kind: any) => number, lineWidth = 0.42) {
  const { Manifold: M, CrossSection: CS } = wasm;

  // Spur gear outline (module m, z teeth), centred at the origin.
  const gear2d = (o: { module: number; teeth: number; pressureAngle?: number; backlash?: number; bore?: number }): CrossSection => {
    const m = o.module;
    const z = o.teeth;
    const a = ((o.pressureAngle ?? 20) * Math.PI) / 180;
    const rp = (m * z) / 2;
    const rb = rp * Math.cos(a);
    const ra = rp + m;
    const rf = Math.max(rp - 1.25 * m, 0.5);
    const inv = Math.tan(a) - a;
    const half = Math.PI / (2 * z) - (o.backlash ?? 0.1) / (2 * rp);
    const flank: V2[] = [];
    const steps = 10;
    const rStart = Math.max(rb, rf);
    for (let i = 0; i <= steps; i++) {
      const r = rStart + ((ra - rStart) * i) / steps;
      const t = Math.sqrt(Math.max(0, (r / rb) ** 2 - 1));
      const x = rb * (Math.cos(t) + t * Math.sin(t));
      const y = rb * (Math.sin(t) - t * Math.cos(t));
      const ang = Math.atan2(y, x) - (half + inv);
      flank.push([r * Math.cos(ang), r * Math.sin(ang)]);
    }
    const mirrored = flank.map(([x, y]) => [x, -y] as V2).reverse();
    const tooth = new CS([[[0, 0], ...flank, ...mirrored]], 'NonZero');
    const teeth: CrossSection[] = [CS.circle(rf, Math.max(48, z * 4))];
    for (let i = 0; i < z; i++) teeth.push(tooth.rotate((360 * i) / z));
    let g = CS.union(teeth);
    if (o.bore) g = g.subtract(CS.circle(o.bore / 2, 48));
    return g;
  };

  const gear = (o: { module: number; teeth: number; thickness: number; pressureAngle?: number; backlash?: number; bore?: number; helix?: number }): Manifold => {
    const cs = gear2d(o);
    const twist = o.helix ? (o.thickness * Math.tan((o.helix * Math.PI) / 180) * 360) / (Math.PI * o.module * o.teeth) : 0;
    return cs.extrude(o.thickness, twist ? 12 : 0, twist);
  };

  // Hinge printed already assembled. Axis along X at height d/2. Returns [leafA, leafB].
  const hinge = (o: { length: number; d?: number; knuckles?: number; gap?: number; leafWidth?: number; leafThickness?: number }) => {
    const L = o.length;
    const d = o.d ?? 8;
    const n = Math.max(3, (o.knuckles ?? 5) | 1);
    const g = o.gap ?? fit('print_in_place');
    const w = o.leafWidth ?? 20;
    const t = o.leafThickness ?? Math.min(3, d / 2);
    const seg = L / n;
    const axis = (s: Manifold) => s.rotate([0, 90, 0]).translate([0, 0, d / 2]);
    const knuckle = (x0: number, x1: number) => axis(M.cylinder(x1 - x0, d / 2, d / 2, 48)).translate([x0, 0, 0]);
    const rc = d * 0.28;
    // cone pointing +X (protrusion) or recess
    const cone = (x: number, dir: 1 | -1, grow: number) => {
      const c = M.cylinder(rc + grow, rc + grow, 0.01, 32);
      const oriented = dir === 1 ? c.rotate([0, 90, 0]) : c.rotate([0, -90, 0]);
      return oriented.translate([x, 0, d / 2]);
    };
    let A: Manifold[] = [];
    let B: Manifold[] = [];
    for (let i = 0; i < n; i++) {
      const x0 = i * seg + (i > 0 ? g / 2 : 0);
      const x1 = (i + 1) * seg - (i < n - 1 ? g / 2 : 0);
      (i % 2 === 0 ? A : B).push(knuckle(x0, x1));
    }
    let a = M.union(A);
    let b = M.union(B);
    // cones from every A knuckle into its B neighbours
    for (let i = 0; i < n - 1; i++) {
      const xi = (i + 1) * seg;
      const dir: 1 | -1 = i % 2 === 0 ? 1 : -1; // A is on the left when i even
      const from = dir === 1 ? xi - g / 2 : xi + g / 2;
      a = a.add(cone(from, dir, 0));
      b = b.subtract(cone(from, dir, g));
    }
    const clearAxis = (x0: number, x1: number) => axis(M.cylinder(x1 - x0 + g, d / 2 + g, d / 2 + g, 48)).translate([x0 - g / 2, 0, 0]);
    let leafA = M.cube([L, w, t]).translate([0, -w - d / 2 + 0.01, 0]).add(M.cube([L, d / 2, t]).translate([0, -d / 2, 0]));
    let leafB = M.cube([L, w, t]).translate([0, d / 2 - 0.01, 0]).add(M.cube([L, d / 2, t]));
    for (let i = 0; i < n; i++) {
      const x0 = i * seg;
      const x1 = (i + 1) * seg;
      if (i % 2 === 0) leafB = leafB.subtract(clearAxis(x0, x1));
      else leafA = leafA.subtract(clearAxis(x0, x1));
    }
    return [a.add(leafA), b.add(leafB)];
  };

  // Cantilever snap hook in the XZ plane, extruded along Y. Hook tip at x = length.
  // The lead-in ramp stops where it is still tipMin thick (default two lines): a knife-edge tip
  // prints as a sliver the slicer drops (too_thin).
  const snapHook = (o: { length: number; thickness: number; width: number; overhang?: number; lead?: number; tipMin?: number }) => {
    const L = o.length;
    const t = o.thickness;
    const h = o.overhang ?? t * 0.8;
    const lead = o.lead ?? h * 1.5;
    const tip = Math.max(0.01, Math.min(o.tipMin ?? 2 * lineWidth, 0.6 * (t + h)));
    const xTip = L + lead * (1 - tip / (t + h));
    const profile: V2[] = [
      [0, 0], [L, 0], [xTip, 0], [xTip, tip], [L, t + h], [L - h * 0.6, t + h], [L - h * 0.6, t], [0, t],
    ];
    return new CS([profile], 'NonZero').extrude(o.width).rotate([90, 0, 0]).translate([0, o.width / 2, 0]);
  };

  const dovetail2d = (o: { width: number; depth: number; angle?: number; gap?: number }): CrossSection => {
    const a = ((o.angle ?? 15) * Math.PI) / 180;
    const g = o.gap ?? 0;
    const spread = o.depth * Math.tan(a);
    const w = o.width / 2 + g / 2;
    return new CS([[[-w, 0], [w, 0], [w + spread, o.depth + g], [-w - spread, o.depth + g]]], 'NonZero');
  };

  return { gear2d, gear, hinge, snapHook, dovetail2d };
}
