// Printability analysis in two speeds:
//  - fast: topology, bed fit, contact area and per-triangle overhang heat (every slider move)
//  - full: a mini-slicer that walks layers like a real slicer and reports *where*
//    islands, bridges, thin features and overhangs are, so the agent can fix them.
import type { CrossSection, Manifold, Wasm } from './kernel.ts';
import { withArena } from './kernel.ts';
import type { PrinterProfile } from './lib/index.ts';
import { RULES, hintsFor } from './rules.ts';

export type Severity = 'error' | 'warn' | 'info';

export interface Issue {
  code: string;
  severity: Severity;
  message: string;
  z?: [number, number];
  bbox?: { min: [number, number]; max: [number, number] };
  value?: number;
  limit?: number;
  hints: string[];
}

export interface CheckStats {
  volume: number;
  surfaceArea: number;
  bbox: { min: [number, number, number]; max: [number, number, number] };
  size: [number, number, number];
  triangles: number;
  bodies: number;
  firstLayerArea: number;
  layers?: number;
  estGrams: number;
  estMinutes: number;
}

export interface CheckReport {
  level: 'fast' | 'full';
  ok: boolean;
  score: number;
  issues: Issue[];
  stats: CheckStats;
  // 0..1 overhang risk per triangle, aligned with the mesh triangle order
  heat?: Float32Array;
  ms: number;
}

export interface CheckOptions {
  level?: 'fast' | 'full';
  vaseMode?: boolean;
  maxLayers?: number;
  wallLoops?: number;
  infill?: number;
}

function issue(code: string, severity: Severity, message: string, extra: Partial<Issue> = {}): Issue {
  return { code, severity, message: message || RULES[code]?.title || code, hints: hintsFor(code), ...extra };
}

export function triangleHeat(body: Manifold, printer: PrinterProfile): { heat: Float32Array; overhangArea: number; lowestZ: number } {
  const mesh = body.getMesh();
  const P = mesh.vertProperties;
  const np = mesh.numProp;
  const T = mesh.triVerts;
  const n = T.length / 3;
  const heat = new Float32Array(n);
  const lim = Math.sin((printer.maxOverhang * Math.PI) / 180);
  let area = 0;
  let lowestZ = Infinity;
  for (let i = 0; i < n; i++) {
    const a = T[i * 3] * np, b = T[i * 3 + 1] * np, c = T[i * 3 + 2] * np;
    const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2];
    const vx = P[c] - P[a], vy = P[c + 1] - P[a + 1], vz = P[c + 2] - P[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const len = Math.hypot(nx, ny, nz) || 1;
    const zmin = Math.min(P[a + 2], P[b + 2], P[c + 2]);
    const down = -nz / len;
    if (down > lim && zmin > printer.layer * 1.5) {
      heat[i] = Math.min(1, (down - lim) / (1 - lim) + 0.25);
      area += len / 2;
      lowestZ = Math.min(lowestZ, zmin);
    }
  }
  return { heat, overhangArea: area, lowestZ };
}

function contourLength(cs: CrossSection): number {
  let total = 0;
  for (const poly of cs.toPolygons()) {
    for (let i = 0; i < poly.length; i++) {
      const [x0, y0] = poly[i];
      const [x1, y1] = poly[(i + 1) % poly.length];
      total += Math.hypot(x1 - x0, y1 - y0);
    }
  }
  return total;
}

// Merges per-layer findings that overlap in XY on consecutive layers into one issue.
class RegionAccumulator {
  regions: { code: string; z0: number; z1: number; min: [number, number]; max: [number, number]; area: number; value: number }[] = [];
  add(code: string, z: number, step: number, b: { min: [number, number]; max: [number, number] }, area: number, value = 0) {
    for (const r of this.regions) {
      if (r.code !== code || z - r.z1 > step * 1.5) continue;
      if (b.min[0] > r.max[0] + 1 || b.max[0] < r.min[0] - 1 || b.min[1] > r.max[1] + 1 || b.max[1] < r.min[1] - 1) continue;
      r.z1 = z;
      r.min = [Math.min(r.min[0], b.min[0]), Math.min(r.min[1], b.min[1])];
      r.max = [Math.max(r.max[0], b.max[0]), Math.max(r.max[1], b.max[1])];
      r.area += area;
      r.value = Math.max(r.value, value);
      return;
    }
    this.regions.push({ code, z0: z, z1: z, min: [...b.min], max: [...b.max], area, value });
  }
}

export function analyze(wasm: Wasm, body: Manifold, printer: PrinterProfile, opts: CheckOptions = {}): CheckReport {
  const t0 = Date.now();
  const level = opts.level ?? 'fast';
  return withArena(() => {
    const issues: Issue[] = [];
    const status = body.status();
    const box = body.boundingBox();
    const size: [number, number, number] = [box.max[0] - box.min[0], box.max[1] - box.min[1], box.max[2] - box.min[2]];
    const volume = body.volume();
    const surfaceArea = body.surfaceArea();
    const bodies = body.decompose().length;
    if (status !== 'NoError') issues.push(issue('invalid_mesh', 'error', `mesh status ${status}`));
    if (body.isEmpty() || volume <= 0) issues.push(issue('empty', 'error', ''));
    if (bodies > 1) issues.push(issue('multiple_bodies', 'info', `${bodies} separate bodies`, { value: bodies }));

    const [bx, by, bz] = printer.bed;
    const fitsFlat = (size[0] <= bx && size[1] <= by) || (size[0] <= by && size[1] <= bx);
    if (!fitsFlat || size[2] > bz) {
      issues.push(issue('exceeds_bed', 'error', `size ${size.map((v) => v.toFixed(1)).join(' x ')} mm vs bed ${bx} x ${by} x ${bz}`, { value: Math.max(...size) }));
    }

    const first = body.slice(Math.min(printer.layer / 2, size[2] / 2));
    const firstLayerArea = first.area();
    if (firstLayerArea < 30 && volume > 200) {
      issues.push(issue('small_contact', 'warn', `first layer only ${firstLayerArea.toFixed(1)} mm²`, { value: firstLayerArea, limit: 30 }));
    }
    const footprint = Math.sqrt(Math.max(firstLayerArea, 1e-6));
    if (size[2] / footprint > 6 && size[2] > 40) {
      issues.push(issue('tip_over', 'warn', `height/base ratio ${(size[2] / footprint).toFixed(1)}`, { value: size[2] / footprint, limit: 6 }));
    }

    const { heat, overhangArea, lowestZ } = triangleHeat(body, printer);
    if (level === 'fast' && overhangArea > 20) {
      issues.push(issue('overhang', 'warn', `${overhangArea.toFixed(0)} mm² of surface steeper than ${printer.maxOverhang}°`, { value: overhangArea, z: [lowestZ, lowestZ] }));
    }

    const walls = opts.wallLoops ?? 2;
    const infill = opts.infill ?? 0.15;
    const shell = Math.min(volume, surfaceArea * printer.lineWidth * walls);
    const extruded = shell + Math.max(0, volume - shell) * infill;
    const density = 1.24;
    const estGrams = (extruded * density) / 1000;
    const estMinutes = extruded / 8 / 60 + size[2] / printer.layer * 0.05;

    let layers: number | undefined;
    if (level === 'full' && status === 'NoError' && volume > 0) {
      const maxLayers = opts.maxLayers ?? 320;
      const step = Math.max(printer.layer, size[2] / maxLayers);
      const reach = step * Math.tan((printer.maxOverhang * Math.PI) / 180);
      const lw = printer.lineWidth;
      const minArea = Math.max(0.6, 4 * lw * lw);
      const acc = new RegionAccumulator();
      let prev: CrossSection | null = null;
      let sawEmptyAfterSolid = false;
      layers = 0;
      for (let z = box.min[2] + step / 2; z < box.max[2]; z += step) {
        layers++;
        const cs = body.slice(z);
        if (cs.isEmpty()) {
          if (prev) sawEmptyAfterSolid = true;
          prev = null;
          continue;
        }
        if (sawEmptyAfterSolid) {
          const b = cs.bounds();
          acc.add('floating_island', z, step, { min: b.min as [number, number], max: b.max as [number, number] }, cs.area());
          sawEmptyAfterSolid = false;
        }
        // features the slicer cannot fill
        const area = cs.area();
        const single = cs.offset(-lw / 2, 'Round').offset(lw / 2, 'Round');
        const lost1 = cs.subtract(single.offset(0.02, 'Round'));
        for (const piece of lost1.decompose()) {
          if (piece.area() < minArea / 2) continue;
          const b = piece.bounds();
          const bb = { min: b.min as [number, number], max: b.max as [number, number] };
          // A sliver attached to printed material (thread crests, sharp tips) only gets rounded;
          // a feature with nothing printable left disappears from the print.
          const attached = !piece.offset(lw * 0.6, 'Round').intersect(single).isEmpty();
          acc.add(attached ? 'fine_detail' : 'too_thin', z, step, bb, piece.area());
        }
        const double = cs.offset(-lw, 'Round').offset(lw, 'Round');
        const lost2 = cs.subtract(double.offset(0.02, 'Round')).subtract(lost1);
        for (const piece of lost2.decompose()) {
          if (piece.area() < minArea) continue;
          const b = piece.bounds();
          acc.add('thin_wall', z, step, { min: b.min as [number, number], max: b.max as [number, number] }, piece.area());
        }
        if (prev && z > printer.layer * 2) {
          const supported = prev.offset(reach + 0.01, 'Round');
          for (const comp of cs.decompose()) {
            const b = comp.bounds();
            const bb = { min: b.min as [number, number], max: b.max as [number, number] };
            if (comp.intersect(prev).area() < 1e-3) {
              acc.add('floating_island', z, step, bb, comp.area());
              continue;
            }
            const unsupported = comp.subtract(supported);
            for (const u of unsupported.decompose()) {
              const ua = u.area();
              if (ua < minArea) continue;
              const ub = u.bounds();
              const ubb = { min: ub.min as [number, number], max: ub.max as [number, number] };
              const anchors = u.offset(lw * 2, 'Round').intersect(prev).decompose().length;
              if (anchors >= 2) {
                const span = Math.min(ub.max[0] - ub.min[0], ub.max[1] - ub.min[1]);
                if (span > printer.maxBridge) acc.add('long_bridge', z, step, ubb, ua, span);
              } else {
                acc.add('overhang', z, step, ubb, ua);
              }
            }
          }
        }
        if (opts.vaseMode && (cs.decompose().length !== 1 || cs.numContour() !== 1) && z > printer.layer * 3) {
          const b = cs.bounds();
          acc.add('vase_incompatible', z, step, { min: b.min as [number, number], max: b.max as [number, number] }, area);
        }
        const speed = printer.speed ?? 120;
        const layerTime = (contourLength(cs) * walls) / speed + area / (lw * speed * 1.5);
        if (layerTime < printer.minLayerTime && z > 2 && z < box.max[2] - step) {
          const b = cs.bounds();
          acc.add('short_layer_time', z, step, { min: b.min as [number, number], max: b.max as [number, number] }, area, layerTime);
        }
        prev = cs;
      }
      const severityOf: Record<string, Severity> = {
        floating_island: 'error',
        too_thin: 'error',
        fine_detail: 'info',
        thin_wall: 'warn',
        overhang: 'warn',
        long_bridge: 'warn',
        vase_incompatible: 'error',
        short_layer_time: 'info',
      };
      const ranked = acc.regions
        .filter((r) => !(r.code === 'overhang' && r.area < minArea * 3) && !(r.code === 'fine_detail' && r.area < minArea * 20))
        .sort((a, b) => (severityOf[a.code] === 'error' ? 0 : 1) - (severityOf[b.code] === 'error' ? 0 : 1) || b.area - a.area)
        .slice(0, 12);
      for (const r of ranked) {
        const where = `z ${r.z0.toFixed(1)}–${r.z1.toFixed(1)} mm, x ${r.min[0].toFixed(0)}..${r.max[0].toFixed(0)}, y ${r.min[1].toFixed(0)}..${r.max[1].toFixed(0)}`;
        const detail = r.code === 'long_bridge' ? `span ${r.value.toFixed(1)} mm > ${printer.maxBridge}` : `${r.area.toFixed(1)} mm²`;
        issues.push(
          issue(r.code, severityOf[r.code] ?? 'warn', `${RULES[r.code]?.title ?? r.code}: ${where} (${detail})`, {
            z: [r.z0, r.z1],
            bbox: { min: r.min, max: r.max },
            value: r.code === 'long_bridge' ? r.value : r.area,
            limit: r.code === 'long_bridge' ? printer.maxBridge : undefined,
          }),
        );
      }
    }

    const penalty = issues.reduce((s, i) => s + (i.severity === 'error' ? 30 : i.severity === 'warn' ? 8 : 1), 0);
    return {
      level,
      ok: !issues.some((i) => i.severity === 'error'),
      score: Math.max(0, 100 - penalty),
      issues,
      stats: {
        volume,
        surfaceArea,
        bbox: { min: box.min as [number, number, number], max: box.max as [number, number, number] },
        size,
        triangles: body.numTri(),
        bodies,
        firstLayerArea,
        layers,
        estGrams,
        estMinutes,
      },
      heat,
      ms: Date.now() - t0,
    };
  });
}
