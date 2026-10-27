// Mesh import (binary/ASCII STL, OBJ): vertices are welded so the result can become a
// closed manifold for programs (inputs.meshes) and the mesh engine.
import type { RawMesh } from './lib/meshops.ts';

export interface ImportedMesh extends RawMesh {
  positions: number[];
  triangles: number[];
}

function welded(soup: number[], eps = 1e-5): ImportedMesh {
  const key = (x: number, y: number, z: number) => `${Math.round(x / eps)},${Math.round(y / eps)},${Math.round(z / eps)}`;
  const ids = new Map<string, number>();
  const positions: number[] = [];
  const triangles: number[] = [];
  for (let i = 0; i < soup.length; i += 9) {
    const tri: number[] = [];
    for (let v = 0; v < 3; v++) {
      const x = soup[i + v * 3], y = soup[i + v * 3 + 1], z = soup[i + v * 3 + 2];
      const k = key(x, y, z);
      let id = ids.get(k);
      if (id === undefined) {
        id = positions.length / 3;
        ids.set(k, id);
        positions.push(x, y, z);
      }
      tri.push(id);
    }
    if (tri[0] !== tri[1] && tri[1] !== tri[2] && tri[0] !== tri[2]) triangles.push(...tri);
  }
  return { positions, triangles };
}

function parseStl(bytes: Uint8Array): ImportedMesh {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const n = bytes.byteLength >= 84 ? view.getUint32(80, true) : 0;
  const soup: number[] = [];
  if (n > 0 && 84 + n * 50 === bytes.byteLength) {
    for (let t = 0; t < n; t++) {
      const o = 84 + t * 50 + 12; // skip the facet normal
      for (let k = 0; k < 9; k++) soup.push(view.getFloat32(o + k * 4, true));
    }
    return welded(soup);
  }
  const text = new TextDecoder().decode(bytes);
  for (const m of text.matchAll(/vertex\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)/g)) soup.push(+m[1], +m[2], +m[3]);
  if (!soup.length || soup.length % 9) throw new Error('not a valid STL file');
  return welded(soup);
}

function parseObj(bytes: Uint8Array): ImportedMesh {
  const verts: number[] = [];
  const soup: number[] = [];
  for (const raw of new TextDecoder().decode(bytes).split('\n')) {
    const line = raw.trim();
    if (line.startsWith('v ')) {
      const [, x, y, z] = line.split(/\s+/);
      verts.push(+x, +y, +z);
    } else if (line.startsWith('f ')) {
      const idx = line.split(/\s+/).slice(1).map((s) => {
        const i = parseInt(s.split('/')[0], 10);
        return i < 0 ? verts.length / 3 + i : i - 1;
      });
      for (let k = 1; k < idx.length - 1; k++)
        for (const i of [idx[0], idx[k], idx[k + 1]]) soup.push(verts[i * 3], verts[i * 3 + 1], verts[i * 3 + 2]);
    }
  }
  if (!soup.length) throw new Error('OBJ file has no faces');
  return welded(soup);
}

export function parseMesh(bytes: Uint8Array, format: string): ImportedMesh {
  const f = format.toLowerCase().replace(/^\./, '');
  if (f === 'stl') return parseStl(bytes);
  if (f === 'obj') return parseObj(bytes);
  throw new Error(`unsupported mesh format "${format}" (use STL or OBJ)`);
}
