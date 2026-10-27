// Flat mesh buffers shared by the viewer, the renderer and the exporters.
import type { Manifold } from './kernel.ts';
import type { Part } from './program.ts';

export interface FlatMesh {
  positions: Float32Array; // xyz per vertex
  indices: Uint32Array; // 3 per triangle
  triPart: Uint16Array; // part index per triangle
}

export function meshOf(solid: Manifold): { positions: Float32Array; indices: Uint32Array } {
  const m = solid.getMesh();
  const np = m.numProp;
  const n = m.vertProperties.length / np;
  const positions = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    positions[i * 3] = m.vertProperties[i * np];
    positions[i * 3 + 1] = m.vertProperties[i * np + 1];
    positions[i * 3 + 2] = m.vertProperties[i * np + 2];
  }
  return { positions, indices: new Uint32Array(m.triVerts) };
}

export function partsMesh(parts: Part[], roles: Part['role'][] = ['model', 'modifier', 'negative']): FlatMesh {
  const chunks = parts
    .map((p, i) => ({ i, p }))
    .filter(({ p }) => roles.includes(p.role))
    .map(({ i, p }) => ({ i, ...meshOf(p.solid) }));
  const nv = chunks.reduce((s, c) => s + c.positions.length, 0);
  const nt = chunks.reduce((s, c) => s + c.indices.length, 0);
  const positions = new Float32Array(nv);
  const indices = new Uint32Array(nt);
  const triPart = new Uint16Array(nt / 3);
  let vo = 0;
  let to = 0;
  for (const c of chunks) {
    positions.set(c.positions, vo);
    const base = vo / 3;
    for (let k = 0; k < c.indices.length; k++) indices[to + k] = c.indices[k] + base;
    triPart.fill(c.i, to / 3, (to + c.indices.length) / 3);
    vo += c.positions.length;
    to += c.indices.length;
  }
  return { positions, indices, triPart };
}

export function toBase64(bytes: Uint8Array): string {
  if (typeof Buffer !== 'undefined') return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString('base64');
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export function fromBase64(b64: string): Uint8Array {
  if (typeof Buffer !== 'undefined') return new Uint8Array(Buffer.from(b64, 'base64'));
  const s = atob(b64);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

export function hexColor(hex: string | undefined, fallback: [number, number, number]): [number, number, number] {
  if (!hex) return fallback;
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return fallback;
  const v = parseInt(m[1], 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}
