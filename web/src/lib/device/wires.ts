// The schematic's wires, routed together so they stay apart: orthogonal, around the parts, never under one. A wire leaves
// its pin straight out, then takes the cheapest way over the tracks that run along the parts' edges. Wires go one at a
// time and each one sees what is already there: a track another net took costs a lot, so two nets in a channel run side
// by side, while a wire of the same net joins its own and the net reads as one bus, with a dot where it branches.
// Plain TypeScript with no Svelte state, so `node --test web/test/wires.test.ts` imports it as is.

export type Pt = [number, number];
export type Box = { x: number; y: number; w: number; h: number };
export type Wire = { id: string; net: string; a: Pt; aDir: number; b: Pt; bDir: number };
export type Routed = { ways: Record<string, Pt[]>; joints: Record<string, Pt[]> };

const CLEAR = 12; // how far from a part a wire may pass
const CHANNEL = 22; // where the first track runs from a part's edge
const TRACK = 16; // between tracks: wide enough to tell two wires apart at the zoom a whole sheet fits in
const TRACKS = 4; // on each side of a part
const STUB = 22; // straight out of a pin before the first bend
const BEND = 40; // what a bend costs, in pixels of way
const SEP = TRACK - 1; // two nets closer than this read as one wire
const NEAR = 200; // running closer than SEP along another net's wire, on top of twice the length
const OVERLAP = 400; // running along another net's wire, on top of four times the length
const TOUCH = 150; // turning on a point of another net's wire
const CROSS = 20; // crossing another net's wire
const SHARED = 0.3; // running along a wire of the same net, per pixel

const half = (n: number) => Math.round(n * 2) / 2;
const uniq = (v: number[]) => [...new Set(v.map(half))].sort((a, b) => a - b);

/** A small heap of [priority, state]. */
class Heap {
  private h: [number, number][] = [];
  get size() {
    return this.h.length;
  }
  clear() {
    this.h.length = 0;
  }
  push(c: number, k: number) {
    const h = this.h;
    h.push([c, k]);
    for (let i = h.length - 1; i > 0; ) {
      const p = (i - 1) >> 1;
      if (h[p][0] <= h[i][0]) break;
      [h[p], h[i]] = [h[i], h[p]];
      i = p;
    }
  }
  pop(): [number, number] {
    const h = this.h;
    const top = h[0];
    const last = h.pop()!;
    if (h.length) {
      h[0] = last;
      for (let i = 0; ; ) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < h.length && h[l][0] < h[m][0]) m = l;
        if (r < h.length && h[r][0] < h[m][0]) m = r;
        if (m === i) break;
        [h[m], h[i]] = [h[i], h[m]];
        i = m;
      }
    }
    return top;
  }
}

/** Every wire's corner points including both pins, and the points where a net branches. */
export function routeAll(wires: Wire[], boxes: Box[]): Routed {
  const ways: Record<string, Pt[]> = {};
  const joints: Record<string, Pt[]> = {};
  if (!wires.length) return { ways, joints };

  const stubOf = (p: Pt, dir: number): Pt => [half(p[0] + dir * STUB), half(p[1])];
  const offs = Array.from({ length: TRACKS }, (_, k) => CHANNEL + k * TRACK);
  const xs = uniq([...wires.flatMap((w) => [stubOf(w.a, w.aDir)[0], stubOf(w.b, w.bDir)[0]]), ...boxes.flatMap((r) => offs.flatMap((o) => [r.x - o, r.x + r.w + o]))]);
  const ys = uniq([...wires.flatMap((w) => [stubOf(w.a, w.aDir)[1], stubOf(w.b, w.bDir)[1]]), ...boxes.flatMap((r) => offs.flatMap((o) => [r.y - o, r.y + r.h + o]))]);
  const nx = xs.length, ny = ys.length;
  const xAt = new Map(xs.map((v, i) => [v, i]));
  const yAt = new Map(ys.map((v, i) => [v, i]));
  const cellOf = (i: number, j: number) => j * nx + i;

  // the grid's steps a part blocks: across from (i, j) to (i + 1, j), down from (i, j) to (i, j + 1)
  const blockH = new Uint8Array(nx * ny);
  const blockV = new Uint8Array(nx * ny);
  for (const r of boxes) {
    const left = r.x - CLEAR, right = r.x + r.w + CLEAR, top = r.y - CLEAR, bottom = r.y + r.h + CLEAR;
    for (let j = 0; j < ny; j++) {
      if (ys[j] <= top || ys[j] >= bottom) continue;
      for (let i = 0; i < nx - 1; i++) if (xs[i + 1] > left && xs[i] < right) blockH[cellOf(i, j)] = 1;
    }
    for (let i = 0; i < nx; i++) {
      if (xs[i] <= left || xs[i] >= right) continue;
      for (let j = 0; j < ny - 1; j++) if (ys[j + 1] > top && ys[j] < bottom) blockV[cellOf(i, j)] = 1;
    }
  }

  // who is on each step and crossing: 0 nobody, n the net numbered n, -1 several
  const usedH = new Int32Array(nx * ny);
  const usedV = new Int32Array(nx * ny);
  const usedN = new Int32Array(nx * ny);
  // the same for the steps on the tracks right next to a wire: tracks of different parts can land a few pixels apart
  const nearH = new Int32Array(nx * ny);
  const nearV = new Int32Array(nx * ny);
  const nearby = (v: number[]) => v.map((a, i) => v.flatMap((b, k) => (k !== i && Math.abs(a - b) < SEP ? [k] : [])));
  const rowsNear = nearby(ys), colsNear = nearby(xs);
  const mark = (arr: Int32Array, k: number, net: number) => {
    arr[k] = arr[k] === 0 || arr[k] === net ? net : -1;
  };
  const netNo = new Map<string, number>();
  const degree = new Map<string, Map<number, Set<string>>>();
  const touch = (net: string, cell: number, what: string) => {
    let d = degree.get(net);
    if (!d) degree.set(net, (d = new Map()));
    let s = d.get(cell);
    if (!s) d.set(cell, (s = new Set()));
    s.add(what);
  };

  const dist = new Float64Array(nx * ny * 2);
  const from = new Int32Array(nx * ny * 2);
  const heap = new Heap();
  // short wires first: they get the straight ways, the long ones go around them
  const order = [...wires].sort((p, q) => Math.abs(p.a[0] - p.b[0]) + Math.abs(p.a[1] - p.b[1]) - (Math.abs(q.a[0] - q.b[0]) + Math.abs(q.a[1] - q.b[1])) || p.id.localeCompare(q.id));
  for (const w of order) {
    if (!netNo.has(w.net)) netNo.set(w.net, netNo.size + 1);
    const net = netNo.get(w.net)!;
    const s = stubOf(w.a, w.aDir), t = stubOf(w.b, w.bDir);
    const si = xAt.get(s[0])!, sj = yAt.get(s[1])!, ti = xAt.get(t[0])!, tj = yAt.get(t[1])!;
    const other = (u: number) => u !== 0 && u !== net;
    dist.fill(Infinity);
    from.fill(-1);
    heap.clear();
    // a state is a crossing and the way the wire came in along: 0 across (as it leaves its pin), 1 up or down
    const start = cellOf(si, sj) * 2;
    dist[start] = 0;
    heap.push(0, start);
    let end = -1;
    while (heap.size) {
      const [, k] = heap.pop();
      const d = k & 1;
      const cell = k >> 1;
      const i = cell % nx, j = (cell - i) / nx;
      const c = dist[k];
      if (i === ti && j === tj) {
        end = k;
        break;
      }
      for (let m = 0; m < 4; m++) {
        const across = m < 2;
        const ni = across ? i + (m === 0 ? 1 : -1) : i;
        const nj = across ? j : j + (m === 2 ? 1 : -1);
        if (ni < 0 || nj < 0 || ni >= nx || nj >= ny) continue;
        const step = across ? cellOf(Math.min(i, ni), j) : cellOf(i, Math.min(j, nj));
        if ((across ? blockH : blockV)[step]) continue;
        const len = across ? Math.abs(xs[ni] - xs[i]) : Math.abs(ys[nj] - ys[j]);
        const used = (across ? usedH : usedV)[step];
        let nc = c + (used === 0 ? len : used === net ? len * SHARED : len * 4 + OVERLAP);
        if (other((across ? nearH : nearV)[step])) nc += len * 2 + NEAR;
        const nd = across ? 0 : 1;
        if (nd !== d) nc += BEND + (other(usedN[cell]) ? TOUCH : 0);
        const ncell = cellOf(ni, nj);
        if (other(usedN[ncell])) nc += CROSS;
        // the last step into a pin is across: coming in up or down means one more bend
        if (ni === ti && nj === tj && nd === 1) nc += BEND;
        const nk = ncell * 2 + nd;
        if (nc < dist[nk]) {
          dist[nk] = nc;
          from[nk] = k;
          heap.push(nc + (Math.abs(xs[ni] - xs[ti]) + Math.abs(ys[nj] - ys[tj])) * SHARED, nk);
        }
      }
    }
    if (end < 0) {
      // walled in (parts dragged on top of each other): a plain step through the middle
      const mx = (s[0] + t[0]) / 2;
      ways[w.id] = simplify([w.a, s, [mx, s[1]], [mx, t[1]], t, w.b]);
      continue;
    }
    const cells: number[] = [];
    for (let k = end; k >= 0; k = from[k]) cells.unshift(k >> 1);
    const way: Pt[] = cells.map((cell) => {
      const i = cell % nx;
      return [xs[i], ys[(cell - i) / nx]];
    });
    cells.forEach((cell, n) => {
      mark(usedN, cell, net);
      if (!n) return;
      const prev = cells[n - 1];
      const across = Math.abs(cell - prev) === 1;
      const step = Math.min(cell, prev);
      mark(across ? usedH : usedV, step, net);
      const si2 = step % nx, sj2 = (step - si2) / nx;
      if (across) for (const r of rowsNear[sj2]) mark(nearH, cellOf(si2, r), net);
      else for (const q of colsNear[si2]) mark(nearV, cellOf(q, sj2), net);
      const name = `${across ? 'h' : 'v'}${step}`;
      touch(w.net, cell, name);
      touch(w.net, prev, name);
    });
    // the straight piece out of a pin counts as a branch at the point it ends
    touch(w.net, cells[0], `a${w.a[0]},${w.a[1]}`);
    touch(w.net, cells[cells.length - 1], `b${w.b[0]},${w.b[1]}`);
    ways[w.id] = simplify([w.a, ...way, w.b]);
  }

  for (const [net, cells] of degree) {
    const dots: Pt[] = [];
    for (const [cell, edges] of cells) {
      if (edges.size < 3) continue;
      const i = cell % nx;
      dots.push([xs[i], ys[(cell - i) / nx]]);
    }
    if (dots.length) joints[net] = dots;
  }
  return { ways, joints };
}

/** Without repeated points and points in the middle of a straight run. */
export function simplify(pts: Pt[]): Pt[] {
  const out: Pt[] = [];
  for (const p of pts) {
    const q = out[out.length - 1];
    if (q && q[0] === p[0] && q[1] === p[1]) continue;
    const o = out[out.length - 2];
    if (o && q && ((o[0] === q[0] && q[0] === p[0]) || (o[1] === q[1] && q[1] === p[1]))) out[out.length - 1] = p;
    else out.push(p);
  }
  return out;
}

/** The corner points as an SVG path with rounded corners. */
export function wirePath(pts: Pt[], radius = 5): string {
  if (pts.length < 2) return '';
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i - 1], [bx, by] = pts[i], [cx, cy] = pts[i + 1];
    const r = Math.min(radius, Math.hypot(bx - ax, by - ay) / 2, Math.hypot(cx - bx, cy - by) / 2);
    const inx = bx - Math.sign(bx - ax) * r, iny = by - Math.sign(by - ay) * r;
    const outx = bx + Math.sign(cx - bx) * r, outy = by + Math.sign(cy - by) * r;
    d += `L${inx},${iny}Q${bx},${by} ${outx},${outy}`;
  }
  const [lx, ly] = pts[pts.length - 1];
  return `${d}L${lx},${ly}`;
}
