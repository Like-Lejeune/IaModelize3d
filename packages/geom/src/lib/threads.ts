// Threads as twisted extrusions: a helical solid is invariant under screw motion,
// so its cross-section at height z is the z=0 section rotated by 360*z/lead.
// Extruding that section with the matching twist reproduces the thread exactly.
import type { Manifold, Wasm } from '../kernel.ts';

export interface ThreadOptions {
  d: number; // major diameter of the external thread
  pitch: number;
  length: number;
  internal?: boolean; // returns a cutter for a nut/cap (enlarged by clearance)
  clearance?: number; // diametral, internal only
  starts?: number;
  depth?: number; // radial thread depth, default ISO 0.6134 * pitch
  crest?: number; // flat fraction of pitch at the crest
  root?: number; // flat fraction of pitch at the root
  segments?: number;
  chamfer?: boolean;
  leftHand?: boolean;
}

export function makeThreads(wasm: Wasm) {
  const { Manifold: M, CrossSection: CS } = wasm;

  const thread = (o: ThreadOptions): Manifold => {
    const starts = Math.max(1, Math.round(o.starts ?? 1));
    const lead = o.pitch * starts;
    const depth = o.depth ?? 0.6134 * o.pitch;
    const grow = o.internal ? (o.clearance ?? 0.3) / 2 : 0;
    const rMaj = o.d / 2 + grow;
    const rMin = rMaj - depth;
    const crest = o.crest ?? 0.125;
    const root = o.root ?? 0.25;
    const flank = (1 - crest - root) / 2;
    const profile = (s: number) => {
      // s in [0,1): root flat, rising flank, crest flat, falling flank
      if (s < root / 2) return rMin;
      if (s < root / 2 + flank) return rMin + ((s - root / 2) / flank) * depth;
      if (s < root / 2 + flank + crest) return rMaj;
      if (s < root / 2 + 2 * flank + crest) return rMaj - ((s - root / 2 - flank - crest) / flank) * depth;
      return rMin;
    };
    const n = o.segments ?? Math.max(96, Math.ceil(rMaj * 12));
    const pts: [number, number][] = [];
    for (let k = 0; k < n; k++) {
      const theta = (2 * Math.PI * k) / n;
      let s = ((-theta / (2 * Math.PI)) * starts) % 1;
      if (s < 0) s += 1;
      const r = profile(s);
      pts.push([r * Math.cos(theta), r * Math.sin(theta)]);
    }
    const length = o.internal ? o.length + o.pitch * 2 : o.length;
    const twist = (360 * length) / lead;
    const section = new CS([pts], 'NonZero');
    let solid = section.extrude(length, Math.ceil(Math.abs(twist) / 6), o.leftHand ? -twist : twist);
    if (o.internal) solid = solid.translate([0, 0, -o.pitch]);
    if (!o.internal && (o.chamfer ?? true)) {
      const c = depth;
      const envelope = M.union([
        M.cylinder(c, rMin, rMaj + 0.01),
        M.cylinder(o.length - 2 * c, rMaj + 0.01, rMaj + 0.01).translate([0, 0, c]),
        M.cylinder(c, rMaj + 0.01, rMin).translate([0, 0, o.length - c]),
      ]);
      solid = solid.intersect(envelope);
    }
    return solid;
  };

  // Metric shortcut: thread('M20', 15) uses the coarse pitch table.
  const metric = (d: number, pitch: number, length: number, extra: Partial<ThreadOptions> = {}) =>
    thread({ d, pitch, length, ...extra });

  return { thread, metric };
}
