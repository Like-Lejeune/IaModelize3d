// Display-ready buffers for the browser viewer, made in the geometry worker so the main
// thread only wraps them: non-indexed positions per part (flat shading, exact per-triangle
// overhang heat), translucent helper volumes, and feature edges.
import type { PrinterProfile } from './lib/index.ts';
import { weld } from './lib/meshops.ts';
import { triangleHeat } from './checks.ts';
import type { Part } from './program.ts';

export interface DisplayBuffers {
  // model parts, concatenated in part order; groups[i] = [firstVertex, vertexCount, partIndex]
  position: Float32Array;
  heat: Uint8Array; // 0..255 per vertex (the same value for the 3 vertices of a triangle)
  groups: [number, number, number][];
  // modifier / negative volumes, drawn translucent
  ghost: Float32Array;
  // feature edges as line segments (6 floats each); empty when skipped
  edges: Float32Array;
  triangles: number;
}

const EDGE_COS = Math.cos((28 * Math.PI) / 180);

function expand(solid: Part['solid'], pos: Float32Array, at: number) {
  const m = solid.getMesh();
  const np = m.numProp, P = m.vertProperties, T = m.triVerts;
  for (let k = 0; k < T.length; k++) {
    const v = T[k] * np;
    pos[at++] = P[v];
    pos[at++] = P[v + 1];
    pos[at++] = P[v + 2];
  }
  return at;
}

// Edges where the surface folds by more than 28°, from the welded mesh so seams in
// manifold's property vertices do not show up as edges.
function featureEdges(solid: Part['solid'], out: number[]) {
  const { pos, tris } = weld(solid);
  const nv = pos.length / 3;
  const nt = tris.length / 3;
  const fn = new Float64Array(nt * 3);
  for (let t = 0; t < nt; t++) {
    const a = tris[t * 3] * 3, b = tris[t * 3 + 1] * 3, c = tris[t * 3 + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
    const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const l = Math.hypot(nx, ny, nz) || 1;
    fn[t * 3] = nx / l;
    fn[t * 3 + 1] = ny / l;
    fn[t * 3 + 2] = nz / l;
  }
  const first = new Map<number, number>();
  for (let t = 0; t < nt; t++)
    for (let e = 0; e < 3; e++) {
      const i = tris[t * 3 + e], j = tris[t * 3 + ((e + 1) % 3)];
      const key = i < j ? i * nv + j : j * nv + i;
      const o = first.get(key);
      if (o === undefined) {
        first.set(key, t);
        continue;
      }
      first.delete(key);
      const d = fn[t * 3] * fn[o * 3] + fn[t * 3 + 1] * fn[o * 3 + 1] + fn[t * 3 + 2] * fn[o * 3 + 2];
      if (d < EDGE_COS) out.push(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2], pos[j * 3], pos[j * 3 + 1], pos[j * 3 + 2]);
    }
}

export function displayBuffers(parts: Part[], printer: PrinterProfile, o: { heat?: boolean; edges?: boolean; maxEdgeTriangles?: number } = {}): DisplayBuffers {
  const models = parts.map((p, i) => ({ p, i })).filter(({ p }) => p.role === 'model');
  const ghosts = parts.filter((p) => p.role === 'modifier' || p.role === 'negative');
  const nModel = models.reduce((s, { p }) => s + p.solid.numTri(), 0);
  const nGhost = ghosts.reduce((s, p) => s + p.solid.numTri(), 0);
  const position = new Float32Array(nModel * 9);
  const heat = new Uint8Array(nModel * 3);
  const groups: [number, number, number][] = [];
  let at = 0;
  for (const { p, i } of models) {
    const start = at / 3;
    at = expand(p.solid, position, at);
    groups.push([start, at / 3 - start, i]);
    if (o.heat !== false) {
      const h = triangleHeat(p.solid, printer).heat;
      for (let t = 0; t < h.length; t++) {
        const v = Math.round(h[t] * 255);
        if (v) heat.fill(v, start + t * 3, start + t * 3 + 3);
      }
    }
  }
  const ghost = new Float32Array(nGhost * 9);
  let g = 0;
  for (const p of ghosts) g = expand(p.solid, ghost, g);
  const lines: number[] = [];
  if (o.edges && nModel <= (o.maxEdgeTriangles ?? 400_000)) for (const { p } of models) featureEdges(p.solid, lines);
  return { position, heat, groups, ghost, edges: Float32Array.from(lines), triangles: nModel };
}

export function displayTransfer(d: DisplayBuffers): ArrayBuffer[] {
  return [d.position.buffer, d.heat.buffer, d.ghost.buffer, d.edges.buffer] as ArrayBuffer[];
}
