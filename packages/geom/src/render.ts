// Software rasterizer: deterministic renders without a GPU, for the agent's critic,
// photo overlays (camera from the reference object) and silhouette fitting.
import { layoutText } from './lib/font.ts';
import type { FlatMesh } from './mesh.ts';

type V3 = [number, number, number];

// OpenCV convention: Xc = R * Xw + t; x right, y down, z forward.
export interface Camera {
  width: number;
  height: number;
  R: number[]; // 9, row-major
  t: V3;
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  ortho?: boolean; // if true, fx is pixels per mm and depth is not divided
}

export interface RenderOptions {
  colors?: Uint8Array; // rgb per triangle
  background?: [number, number, number, number];
  edges?: boolean;
  edgeColor?: [number, number, number];
}

export interface RenderResult {
  rgba: Uint8ClampedArray;
  depth: Float32Array;
  ids: Int32Array;
  width: number;
  height: number;
}

const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: V3): V3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};

export function lookAt(eye: V3, target: V3, upHint: V3 = [0, 0, 1]): { R: number[]; t: V3 } {
  const f = norm(sub(target, eye));
  let r = cross(f, upHint);
  if (Math.hypot(...r) < 1e-6) r = cross(f, [0, 1, 0]);
  r = norm(r);
  const u = cross(r, f);
  const R = [r[0], r[1], r[2], -u[0], -u[1], -u[2], f[0], f[1], f[2]];
  const t: V3 = [-(R[0] * eye[0] + R[1] * eye[1] + R[2] * eye[2]), -(R[3] * eye[0] + R[4] * eye[1] + R[5] * eye[2]), -(R[6] * eye[0] + R[7] * eye[1] + R[8] * eye[2])];
  return { R, t };
}

// Orthographic camera looking along `dir` that frames the given bbox.
export function orthoFit(dir: V3, bbox: { min: V3; max: V3 }, width: number, height: number, margin = 0.1): Camera {
  const c: V3 = [(bbox.min[0] + bbox.max[0]) / 2, (bbox.min[1] + bbox.max[1]) / 2, (bbox.min[2] + bbox.max[2]) / 2];
  const diag = Math.hypot(bbox.max[0] - bbox.min[0], bbox.max[1] - bbox.min[1], bbox.max[2] - bbox.min[2]) || 1;
  const d = norm(dir);
  const eye: V3 = [c[0] - d[0] * diag * 2, c[1] - d[1] * diag * 2, c[2] - d[2] * diag * 2];
  const up: V3 = Math.abs(d[2]) > 0.99 ? [0, 1, 0] : [0, 0, 1];
  const { R, t } = lookAt(eye, c, up);
  let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity;
  for (let i = 0; i < 8; i++) {
    const p: V3 = [i & 1 ? bbox.max[0] : bbox.min[0], i & 2 ? bbox.max[1] : bbox.min[1], i & 4 ? bbox.max[2] : bbox.min[2]];
    const x = R[0] * p[0] + R[1] * p[1] + R[2] * p[2] + t[0];
    const y = R[3] * p[0] + R[4] * p[1] + R[5] * p[2] + t[1];
    minx = Math.min(minx, x); maxx = Math.max(maxx, x); miny = Math.min(miny, y); maxy = Math.max(maxy, y);
  }
  const s = Math.min((width * (1 - 2 * margin)) / Math.max(maxx - minx, 1e-6), (height * (1 - 2 * margin)) / Math.max(maxy - miny, 1e-6));
  return { width, height, R, t, fx: s, fy: s, cx: width / 2 - s * ((minx + maxx) / 2), cy: height / 2 - s * ((miny + maxy) / 2), ortho: true };
}

export function render(mesh: FlatMesh, cam: Camera, opts: RenderOptions = {}): RenderResult {
  const { width: W, height: H, R, t } = cam;
  const rgba = new Uint8ClampedArray(W * H * 4);
  const depth = new Float32Array(W * H).fill(Infinity);
  const ids = new Int32Array(W * H).fill(-1);
  const bg = opts.background ?? [0, 0, 0, 0];
  for (let i = 0; i < W * H; i++) rgba.set(bg, i * 4);
  const P = mesh.positions;
  const I = mesh.indices;
  const nTri = I.length / 3;
  const nv = P.length / 3;
  const sx = new Float32Array(nv), sy = new Float32Array(nv), sz = new Float32Array(nv);
  for (let v = 0; v < nv; v++) {
    const x = P[v * 3], y = P[v * 3 + 1], z = P[v * 3 + 2];
    const xc = R[0] * x + R[1] * y + R[2] * z + t[0];
    const yc = R[3] * x + R[4] * y + R[5] * z + t[1];
    const zc = R[6] * x + R[7] * y + R[8] * z + t[2];
    if (cam.ortho) {
      sx[v] = cam.fx * xc + cam.cx;
      sy[v] = cam.fy * yc + cam.cy;
    } else {
      const zz = Math.max(zc, 1e-3);
      sx[v] = (cam.fx * xc) / zz + cam.cx;
      sy[v] = (cam.fy * yc) / zz + cam.cy;
    }
    sz[v] = zc;
  }
  // light from the camera, slightly above and left
  const L = norm([R[6] * -1 + R[3] * 0.45 - R[0] * 0.25, R[7] * -1 + R[4] * 0.45 - R[1] * 0.25, R[8] * -1 + R[5] * 0.45 - R[2] * 0.25]);
  const shade = new Float32Array(nTri);
  const normals = new Float32Array(nTri * 3);
  for (let f = 0; f < nTri; f++) {
    const a = I[f * 3] * 3, b = I[f * 3 + 1] * 3, c = I[f * 3 + 2] * 3;
    const n = norm(cross([P[b] - P[a], P[b + 1] - P[a + 1], P[b + 2] - P[a + 2]], [P[c] - P[a], P[c + 1] - P[a + 1], P[c + 2] - P[a + 2]]));
    normals.set(n, f * 3);
    shade[f] = 0.32 + 0.68 * Math.abs(n[0] * L[0] + n[1] * L[1] + n[2] * L[2]);
  }
  for (let f = 0; f < nTri; f++) {
    const a = I[f * 3], b = I[f * 3 + 1], c = I[f * 3 + 2];
    if (!cam.ortho && (sz[a] <= 1e-3 || sz[b] <= 1e-3 || sz[c] <= 1e-3)) continue;
    const x0 = sx[a], y0 = sy[a], x1 = sx[b], y1 = sy[b], x2 = sx[c], y2 = sy[c];
    const area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0);
    if (Math.abs(area) < 1e-9) continue;
    const minX = Math.max(0, Math.floor(Math.min(x0, x1, x2)));
    const maxX = Math.min(W - 1, Math.ceil(Math.max(x0, x1, x2)));
    const minY = Math.max(0, Math.floor(Math.min(y0, y1, y2)));
    const maxY = Math.min(H - 1, Math.ceil(Math.max(y0, y1, y2)));
    if (minX > maxX || minY > maxY) continue;
    const iz0 = cam.ortho ? sz[a] : 1 / sz[a], iz1 = cam.ortho ? sz[b] : 1 / sz[b], iz2 = cam.ortho ? sz[c] : 1 / sz[c];
    const cr = opts.colors ? opts.colors[f * 3] : 205, cg = opts.colors ? opts.colors[f * 3 + 1] : 208, cb = opts.colors ? opts.colors[f * 3 + 2] : 214;
    const s = shade[f];
    for (let py = minY; py <= maxY; py++) {
      const y = py + 0.5;
      for (let px = minX; px <= maxX; px++) {
        const x = px + 0.5;
        let w0 = (x1 - x) * (y2 - y) - (x2 - x) * (y1 - y);
        let w1 = (x2 - x) * (y0 - y) - (x0 - x) * (y2 - y);
        let w2 = (x0 - x) * (y1 - y) - (x1 - x) * (y0 - y);
        if (area < 0) { w0 = -w0; w1 = -w1; w2 = -w2; }
        if (w0 < 0 || w1 < 0 || w2 < 0) continue;
        const A = Math.abs(area);
        const iz = (w0 * iz0 + w1 * iz1 + w2 * iz2) / A;
        const zc = cam.ortho ? iz : 1 / iz;
        const k = py * W + px;
        if (zc >= depth[k]) continue;
        depth[k] = zc;
        ids[k] = f;
        rgba[k * 4] = cr * s;
        rgba[k * 4 + 1] = cg * s;
        rgba[k * 4 + 2] = cb * s;
        rgba[k * 4 + 3] = 255;
      }
    }
  }
  if (opts.edges !== false) {
    const ec = opts.edgeColor ?? [40, 44, 52];
    const cosLim = Math.cos((28 * Math.PI) / 180);
    const edge = new Uint8Array(W * H);
    for (let y = 0; y < H - 1; y++) {
      for (let x = 0; x < W - 1; x++) {
        const k = y * W + x;
        for (const n of [k + 1, k + W]) {
          const a = ids[k], b = ids[n];
          if (a === b) continue;
          if (a < 0 || b < 0) {
            edge[a < 0 ? n : k] = 1;
            continue;
          }
          const dot = normals[a * 3] * normals[b * 3] + normals[a * 3 + 1] * normals[b * 3 + 1] + normals[a * 3 + 2] * normals[b * 3 + 2];
          const dz = Math.abs(depth[k] - depth[n]) / Math.max(1e-6, Math.abs(depth[k]));
          if (dot < cosLim || dz > 0.02) edge[k] = 1;
        }
      }
    }
    for (let k = 0; k < W * H; k++) {
      if (!edge[k]) continue;
      rgba[k * 4] = ec[0];
      rgba[k * 4 + 1] = ec[1];
      rgba[k * 4 + 2] = ec[2];
      rgba[k * 4 + 3] = 255;
    }
  }
  return { rgba, depth, ids, width: W, height: H };
}

export function silhouette(mesh: FlatMesh, cam: Camera): Uint8Array {
  const r = render(mesh, cam, { edges: false });
  const mask = new Uint8Array(cam.width * cam.height);
  for (let k = 0; k < mask.length; k++) mask[k] = r.ids[k] >= 0 ? 1 : 0;
  return mask;
}

export function iou(a: Uint8Array, b: Uint8Array): number {
  let inter = 0, uni = 0;
  for (let i = 0; i < a.length; i++) {
    const x = a[i] > 0, y = b[i] > 0;
    if (x && y) inter++;
    if (x || y) uni++;
  }
  return uni ? inter / uni : 1;
}

// ---- 2D drawing helpers for labels on render sheets ----
export function drawLine(img: Uint8ClampedArray, W: number, H: number, x0: number, y0: number, x1: number, y1: number, color: [number, number, number], thick = 1) {
  const steps = Math.ceil(Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0))) + 1;
  for (let i = 0; i <= steps; i++) {
    const x = Math.round(x0 + ((x1 - x0) * i) / steps);
    const y = Math.round(y0 + ((y1 - y0) * i) / steps);
    for (let dx = 0; dx < thick; dx++)
      for (let dy = 0; dy < thick; dy++) {
        const px = x + dx, py = y + dy;
        if (px < 0 || py < 0 || px >= W || py >= H) continue;
        const k = (py * W + px) * 4;
        img[k] = color[0]; img[k + 1] = color[1]; img[k + 2] = color[2]; img[k + 3] = 255;
      }
  }
}

export function drawText(img: Uint8ClampedArray, W: number, H: number, text: string, x: number, y: number, size: number, color: [number, number, number]) {
  const { lines } = layoutText(text, size, 1.2);
  const thick = size >= 16 ? 2 : 1;
  for (const line of lines)
    for (let i = 1; i < line.length; i++)
      drawLine(img, W, H, x + line[i - 1][0], y - line[i - 1][1], x + line[i][0], y - line[i][1], color, thick);
}

export function drawDot(img: Uint8ClampedArray, W: number, H: number, x: number, y: number, r: number, color: [number, number, number], filled: boolean) {
  for (let dy = -r - 1; dy <= r + 1; dy++)
    for (let dx = -r - 1; dx <= r + 1; dx++) {
      const d = Math.hypot(dx, dy);
      if (d > r + 0.5 || (!filled && d < r - 1.5)) continue;
      const px = Math.round(x + dx), py = Math.round(y + dy);
      if (px < 0 || py < 0 || px >= W || py >= H) continue;
      const k = (py * W + px) * 4;
      img[k] = color[0]; img[k + 1] = color[1]; img[k + 2] = color[2]; img[k + 3] = 255;
    }
}

/** A labelled point drawn over the views (where an operation acts). */
export interface Marker {
  at: V3;
  label: string;
}

export interface SheetView {
  name: string;
  dir: V3;
}

export const SHEET_VIEWS: SheetView[] = [
  { name: 'ISO', dir: [-1, 1, -0.8] },
  { name: 'ISO BACK', dir: [1, -1, -0.8] },
  { name: 'FRONT', dir: [0, 1, 0] },
  { name: 'RIGHT', dir: [-1, 0, 0] },
  { name: 'TOP', dir: [0, 0, -1] },
  { name: 'BOTTOM', dir: [0, 0, 1] },
];

// 3x2 sheet of orthographic views with labels, size and a 10 mm scale bar.
// `size` labels the model's real size when bbox only frames a close-up.
export function renderSheet(mesh: FlatMesh, bbox: { min: V3; max: V3 }, opts: { tile?: number; colors?: Uint8Array; views?: SheetView[]; title?: string; size?: number[]; markers?: Marker[] } = {}) {
  const tile = opts.tile ?? 360;
  const views = opts.views ?? SHEET_VIEWS;
  const cols = Math.min(3, views.length);
  const rows = Math.ceil(views.length / cols);
  const W = tile * cols, H = tile * rows + 28;
  const img = new Uint8ClampedArray(W * H * 4);
  for (let i = 0; i < W * H; i++) img.set([246, 246, 243, 255], i * 4);
  views.forEach((v, idx) => {
    const cam = orthoFit(v.dir, bbox, tile, tile, 0.12);
    const r = render(mesh, cam, { colors: opts.colors, background: [246, 246, 243, 255] });
    const ox = (idx % cols) * tile, oy = Math.floor(idx / cols) * tile;
    for (let y = 0; y < tile; y++) img.set(r.rgba.subarray(y * tile * 4, (y + 1) * tile * 4), ((oy + y) * W + ox) * 4);
    drawText(img, W, H, v.name, ox + 8, oy + 18, 12, [90, 90, 90]);
    // markers: filled where visible, hollow where the surface hides them
    for (const m of opts.markers ?? []) {
      const [x, y, z] = m.at;
      const xc = cam.R[0] * x + cam.R[1] * y + cam.R[2] * z + cam.t[0];
      const yc = cam.R[3] * x + cam.R[4] * y + cam.R[5] * z + cam.t[1];
      const zc = cam.R[6] * x + cam.R[7] * y + cam.R[8] * z + cam.t[2];
      const px = cam.fx * xc + cam.cx, py = cam.fy * yc + cam.cy;
      if (px < 2 || py < 2 || px >= tile - 2 || py >= tile - 2) continue;
      const k = Math.floor(py) * tile + Math.floor(px);
      const seen = !(r.depth[k] < zc - Math.max(1, (bbox.max[2] - bbox.min[2]) * 0.03));
      const col: [number, number, number] = seen ? [235, 90, 20] : [150, 150, 160];
      drawDot(img, W, H, ox + px, oy + py, 4, col, seen);
      drawText(img, W, H, m.label.slice(0, 12).toUpperCase(), ox + px + 6, oy + py - 4, 10, col);
    }
    // scale bar: 10 mm in this view's pixels
    const px = cam.fx * 10;
    if (px > 8 && px < tile * 0.8) {
      drawLine(img, W, H, ox + 10, oy + tile - 12, ox + 10 + px, oy + tile - 12, [200, 60, 40], 2);
      drawText(img, W, H, '10MM', ox + 14 + px, oy + tile - 8, 10, [200, 60, 40]);
    }
  });
  const size = (opts.size ?? [0, 1, 2].map((i) => bbox.max[i] - bbox.min[i])).map((v) => v.toFixed(1));
  drawText(img, W, H, `${(opts.title ?? '').slice(0, 40)}  ${size[0]} X ${size[1]} X ${size[2]} MM`, 10, H - 8, 14, [30, 30, 30]);
  return { rgba: img, width: W, height: H };
}
