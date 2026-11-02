// Standard library for programs: shapes, extrusion with printable chamfers,
// standard holes with printer compensation, text and splitting.
import type { CrossSection, Manifold, Wasm } from '../kernel.ts';
import standards from '../standards.json' with { type: 'json' };
import { layoutText } from './font.ts';
import type { LibContext } from './index.ts';

type V2 = [number, number];
type V3 = [number, number, number];
type Center = boolean | 'xy';

export function makeStd(wasm: Wasm, ctx: LibContext) {
  const { Manifold: M, CrossSection: CS } = wasm;
  const pr = ctx.printer;

  const comp = (d: number) => d + (pr.holeDelta ?? 0);
  const fit = (kind: keyof typeof standards.fits | number) =>
    (typeof kind === 'number' ? kind : (standards.fits as any)[kind] ?? 0.25) + (pr.fitDelta ?? 0);

  // ---------- 2D ----------
  const rect = (w: number, h: number, o: { r?: number; center?: boolean } = {}): CrossSection => {
    let cs = CS.square([w, h], o.center ?? true);
    if (o.r && o.r > 0) cs = cs.offset(-o.r, 'Square').offset(o.r, 'Round');
    return cs;
  };
  const circle = (d: number, segments?: number): CrossSection => CS.circle(d / 2, segments);
  const poly = (points: V2[] | V2[][]): CrossSection => {
    const loops = Array.isArray(points[0]?.[0]) ? (points as V2[][]) : [points as V2[]];
    return new CS(loops, 'NonZero');
  };
  const slot = (length: number, w: number): CrossSection =>
    CS.hull([circle(w).translate([-length / 2 + w / 2, 0]), circle(w).translate([length / 2 - w / 2, 0])]);
  const ngon = (n: number, d: number): CrossSection => CS.circle(d / 2, n);
  const fillet2d = (cs: CrossSection, convex = 0, concave = 0): CrossSection => {
    let out = cs;
    if (convex > 0) out = out.offset(-convex, 'Round').offset(convex, 'Round');
    if (concave > 0) out = out.offset(concave, 'Round').offset(-concave, 'Round');
    return out;
  };
  const teardrop2d = (d: number, o: { truncate?: boolean } = {}): CrossSection => {
    const r = d / 2;
    let cs = CS.hull([circle(d), poly([[-0.01, r * Math.SQRT2], [0.01, r * Math.SQRT2], [0, r * Math.SQRT2 + 0.01]])]);
    if (o.truncate) cs = cs.intersect(rect(d * 2, d, { center: true }).translate([0, 0]));
    return cs;
  };

  // ---------- extrusion ----------
  // A chamfer removes the material within c - d of the outline at depth d below the face: the
  // set offset(-(c - d), 'Round') leaves out, so it works for any (also concave) outline. For
  // one edge that set is convex (distance to a segment plus depth), so its cutter is a hull of
  // points: a circle of radius c around both ends on the face, the two ends at depth c. Every
  // face of it is at 45°, so a bottom chamfer has no overhang a printer or the checks would see.
  const chamferCutter = (cs: CrossSection, c: number, face: number, dir: 1 | -1): Manifold => {
    const e = 0.01; // past the face and the outline, so no cut face is coplanar with the prism
    const r = c + e;
    const zFace = face - dir * e;
    const zTip = face + dir * c;
    const k = 8;
    const ring = Array.from({ length: k }, (_, j) => [Math.cos((2 * Math.PI * j) / k), Math.sin((2 * Math.PI * j) / k)]);
    const cutters: Manifold[] = [];
    for (const loop of cs.toPolygons()) {
      for (let i = 0; i < loop.length; i++) {
        const a = loop[i];
        const b = loop[(i + 1) % loop.length];
        const pts: V3[] = [[a[0], a[1], zTip], [b[0], b[1], zTip]];
        for (const q of [a, b]) for (const [x, y] of ring) pts.push([q[0] + r * x, q[1] + r * y, zFace]);
        // The circle is a polygon; the points along the edge normal keep a straight edge's face exact.
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (len > 1e-9) {
          const nx = (-(b[1] - a[1]) / len) * r;
          const ny = ((b[0] - a[0]) / len) * r;
          for (const q of [a, b]) pts.push([q[0] + nx, q[1] + ny, zFace], [q[0] - nx, q[1] - ny, zFace]);
        }
        cutters.push(M.hull(pts));
      }
    }
    return M.union(cutters);
  };
  const extrude = (
    cs: CrossSection,
    h: number,
    o: { chamferBottom?: number; chamferTop?: number; twist?: number; scaleTop?: number | V2; center?: boolean; divisions?: number } = {},
  ): Manifold => {
    const cb = Math.max(0, Math.min(o.chamferBottom ?? 0, h / 2));
    const ct = Math.max(0, Math.min(o.chamferTop ?? 0, h / 2));
    let solid: Manifold;
    if (cb === 0 && ct === 0) {
      const div = o.divisions ?? (o.twist ? Math.max(1, Math.ceil(Math.abs(o.twist) / 5)) : 0);
      // A scalar scaleTop is mis-converted by the bindings (Y collapses to 0): always pass a pair.
      const st = o.scaleTop ?? 1;
      solid = cs.extrude(h, div, o.twist ?? 0, typeof st === 'number' ? [st, st] : st);
    } else {
      const cutters: Manifold[] = [];
      if (cb > 0) cutters.push(chamferCutter(cs, cb, 0, 1));
      if (ct > 0) cutters.push(chamferCutter(cs, ct, h, -1));
      solid = cs.extrude(h).subtract(M.union(cutters));
    }
    return o.center ? solid.translate([0, 0, -h / 2]) : solid;
  };

  // Profile points are [r, z]; revolved around the Z axis.
  const revolve = (profile: V2[] | CrossSection, degrees = 360, segments?: number): Manifold => {
    const cs = Array.isArray(profile) ? poly(profile) : profile;
    return cs.revolve(segments, degrees);
  };

  // ---------- solids ----------
  const place = (s: Manifold, size: V3, center: Center | undefined) => {
    if (center === true) return s.translate([0, 0, -size[2] / 2]);
    if (center === 'xy' || center === undefined) return s;
    return s.translate([size[0] / 2, size[1] / 2, 0]);
  };
  const box = (size: V3 | number, o: { r?: number; center?: Center; chamferBottom?: number; chamferTop?: number } = {}): Manifold => {
    const s: V3 = typeof size === 'number' ? [size, size, size] : size;
    const solid = extrude(rect(s[0], s[1], { r: o.r }), s[2], { chamferBottom: o.chamferBottom, chamferTop: o.chamferTop });
    return place(solid, s, o.center ?? 'xy');
  };
  const cyl = (d: number, h: number, o: { d2?: number; center?: boolean; segments?: number } = {}): Manifold =>
    M.cylinder(h, d / 2, (o.d2 ?? d) / 2, o.segments ?? 0, o.center ?? false);
  const tube = (od: number, id: number, h: number, o: { center?: boolean } = {}): Manifold =>
    extrude(circle(od).subtract(circle(id)), h, { center: o.center });
  const sphere = (d: number, segments?: number): Manifold => M.sphere(d / 2, segments);

  // ---------- holes and fasteners ----------
  const screw = (name: string) => {
    const s = (standards.screws as any)[name];
    if (!s) throw new Error(`unknown screw "${name}"; known: ${Object.keys(standards.screws).join(', ')}`);
    return s as (typeof standards.screws)['M3'];
  };
  // Vertical hole whose top is at `at`, going down `depth`. Compensated.
  const holeZ = (d: number, depth: number, o: { at?: V3; through?: boolean; segments?: number } = {}): Manifold => {
    const at = o.at ?? [0, 0, 0];
    const extra = o.through ? 1 : 0.01;
    return M.cylinder(depth + extra * 2, comp(d) / 2, comp(d) / 2, o.segments ?? 0).translate([at[0], at[1], at[2] - depth - extra]);
  };
  // Horizontal hole along X or Y centred at `at`; teardrop by default so it prints without support.
  const holeH = (d: number, length: number, o: { at?: V3; dir?: 'x' | 'y'; teardrop?: boolean } = {}): Manifold => {
    const at = o.at ?? [0, 0, 0];
    const cs = o.teardrop === false ? circle(comp(d)) : teardrop2d(comp(d));
    // Extruded along +Z, then rotated so the teardrop tip points to +Z.
    let s = cs.extrude(length).translate([0, 0, -length / 2]);
    s = (o.dir ?? 'x') === 'x' ? s.rotate([0, 90, 0]).rotate([90, 0, 0]).rotate([0, 0, 90]) : s.rotate([90, 0, 0]);
    // Normalize: tip of the teardrop must point up after rotation.
    return s.translate(at);
  };
  const clearanceHole = (name: string, depth: number, o: { at?: V3; fit?: 'close' | 'normal' | 'loose'; through?: boolean } = {}) =>
    holeZ(screw(name).clearance[o.fit ?? 'normal'], depth, o);
  const tapHole = (name: string, depth: number, o: { at?: V3 } = {}) => holeZ(screw(name).tap_plastic, depth, o);
  const insertHole = (name: string, o: { at?: V3; extraDepth?: number } = {}) => {
    const s = screw(name);
    return holeZ(s.insert.d, s.insert.depth + (o.extraDepth ?? 1), o);
  };
  const nutTrap = (name: string, o: { at?: V3; depth?: number; extra?: number; rotate?: number } = {}) => {
    const s = screw(name);
    const af = s.nut.af + (o.extra ?? 0.3);
    const at = o.at ?? [0, 0, 0];
    const depth = o.depth ?? s.nut.h + 0.3;
    return CS.circle(af / Math.sqrt(3), 6)
      .rotate(o.rotate ?? 0)
      .extrude(depth + 0.01)
      .translate([at[0], at[1], at[2] - depth]);
  };
  const counterbore = (name: string, o: { at?: V3; depth?: number } = {}) => {
    const s = screw(name);
    return holeZ(s.socket_head.d + 0.6, o.depth ?? s.socket_head.h + 0.3, { at: o.at });
  };
  const countersink = (name: string, o: { at?: V3 } = {}) => {
    const s = screw(name);
    const at = o.at ?? [0, 0, 0];
    const r1 = comp(s.csk_head.d) / 2;
    const r0 = comp(s.clearance.normal) / 2;
    const h = r1 - r0;
    return M.cylinder(h + 0.01, r0, r1 + 0.01).translate([at[0], at[1], at[2] - h]);
  };

  // ---------- text ----------
  const text2d = (str: string, o: { size?: number; stroke?: number; align?: 'left' | 'center' | 'right' } = {}): CrossSection => {
    const size = o.size ?? 5;
    const stroke = o.stroke ?? Math.max(0.45, size * 0.12);
    const { lines, width } = layoutText(str, size);
    const pieces: CrossSection[] = [];
    for (const line of lines) {
      for (let i = 0; i < line.length; i++) {
        pieces.push(CS.circle(stroke / 2, 12).translate(line[i]));
        if (i > 0) {
          const [x0, y0] = line[i - 1];
          const [x1, y1] = line[i];
          const len = Math.hypot(x1 - x0, y1 - y0);
          if (len < 1e-6) continue;
          const ang = (Math.atan2(y1 - y0, x1 - x0) * 180) / Math.PI;
          pieces.push(CS.square([len, stroke], false).translate([0, -stroke / 2]).rotate(ang).translate([x0, y0]));
        }
      }
    }
    const shift = o.align === 'left' ? 0 : o.align === 'right' ? -width : -width / 2;
    return CS.union(pieces).translate([shift, -size / 2]);
  };
  const text = (str: string, o: { size?: number; stroke?: number; depth?: number; align?: 'left' | 'center' | 'right' } = {}) =>
    text2d(str, o).extrude(o.depth ?? 0.6);

  // ---------- splitting ----------
  // Cuts at z = `at` (after optional rotation) and adds alignment pegs so the halves
  // glue back exactly. Returns [lower, upper], each resting on z=0.
  const splitWithPegs = (solid: Manifold, o: { at: number; pegD?: number; pegH?: number; count?: number; gap?: number }) => {
    const pegD = o.pegD ?? 5;
    const pegH = o.pegH ?? 6;
    const gap = o.gap ?? fit('snug');
    const [lower, upper] = solid.splitByPlane([0, 0, -1], -o.at);
    const section = solid.slice(o.at).offset(-pegD, 'Round');
    const centers: V2[] = [];
    for (const piece of section.decompose()) {
      const b = piece.bounds();
      centers.push([(b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2]);
      if (centers.length >= (o.count ?? 2)) break;
    }
    let low = lower;
    let up = upper;
    for (const [x, y] of centers) {
      low = low.add(M.cylinder(pegH / 2, pegD / 2, pegD / 2).translate([x, y, o.at]));
      up = up.subtract(M.cylinder(pegH / 2 + 0.4, (pegD + gap) / 2, (pegD + gap) / 2).translate([x, y, o.at - 0.01]));
    }
    // The upper half is flipped so its cut face sits on the bed.
    const flipped = up.rotate([180, 0, 0]);
    const zmin = flipped.boundingBox().min[2];
    return [low, flipped.translate([0, 0, -zmin])];
  };

  return {
    standards,
    comp,
    fit,
    rect,
    circle,
    poly,
    slot,
    ngon,
    fillet2d,
    teardrop2d,
    extrude,
    revolve,
    box,
    cyl,
    tube,
    sphere,
    screw,
    holeZ,
    holeH,
    clearanceHole,
    tapHole,
    insertHole,
    nutTrap,
    counterbore,
    countersink,
    text2d,
    text,
    splitWithPegs,
  };
}
