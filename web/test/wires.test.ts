import test from 'node:test';
import assert from 'node:assert/strict';
import { routeAll, simplify, wirePath, type Box, type Pt, type Wire } from '../src/lib/device/wires.ts';

/** How many segments of the way run through a box (its outline counts as outside). */
function crossings(way: Pt[], box: Box): number {
  let n = 0;
  for (let i = 1; i < way.length; i++) {
    const [x1, y1] = way[i - 1], [x2, y2] = way[i];
    if (Math.max(x1, x2) > box.x && Math.min(x1, x2) < box.x + box.w && Math.max(y1, y2) > box.y && Math.min(y1, y2) < box.y + box.h) n++;
  }
  return n;
}

/** The length two ways run on top of each other. */
function overlap(p: Pt[], q: Pt[]): number {
  let total = 0;
  for (let i = 1; i < p.length; i++) {
    for (let j = 1; j < q.length; j++) {
      const [ax, ay] = p[i - 1], [bx, by] = p[i], [cx, cy] = q[j - 1], [dx, dy] = q[j];
      if (ax === bx && cx === dx && ax === cx) total += Math.max(0, Math.min(Math.max(ay, by), Math.max(cy, dy)) - Math.max(Math.min(ay, by), Math.min(cy, dy)));
      if (ay === by && cy === dy && ay === cy) total += Math.max(0, Math.min(Math.max(ax, bx), Math.max(cx, dx)) - Math.max(Math.min(ax, bx), Math.min(cx, dx)));
    }
  }
  return total;
}

const orthogonal = (way: Pt[]) => way.every((p, i) => i === 0 || p[0] === way[i - 1][0] || p[1] === way[i - 1][1]);
const wire = (id: string, net: string, a: Pt, aDir: number, b: Pt, bDir: number): Wire => ({ id, net, a, aDir, b, bDir });

test('a wire goes around the part between its pins', () => {
  const left: Box = { x: 0, y: 0, w: 200, h: 100 };
  const middle: Box = { x: 300, y: -100, w: 200, h: 300 };
  const right: Box = { x: 600, y: 0, w: 200, h: 100 };
  const way = routeAll([wire('w', 'A', [200, 50], 1, [600, 50], -1)], [left, middle, right]).ways.w;
  assert.equal(crossings(way, middle), 0);
  assert.ok(orthogonal(way));
  assert.deepEqual(way[0], [200, 50]);
  assert.deepEqual(way[way.length - 1], [600, 50]);
});

test('a wire back around its own part does not run through it', () => {
  const own: Box = { x: 0, y: 0, w: 200, h: 100 };
  const other: Box = { x: 0, y: 200, w: 200, h: 100 };
  const way = routeAll([wire('w', 'A', [200, 50], 1, [0, 250], -1)], [own, other]).ways.w;
  assert.equal(crossings(way, own), 0);
  assert.equal(crossings(way, other), 0);
});

test('with a clear way the wire has no bends to spare', () => {
  assert.deepEqual(routeAll([wire('w', 'A', [0, 0], 1, [300, 0], -1)], []).ways.w, [[0, 0], [300, 0]]);
});

test('nets in one channel run side by side, not on top of each other', () => {
  const left: Box = { x: 0, y: 0, w: 200, h: 300 };
  const right: Box = { x: 320, y: 0, w: 200, h: 300 };
  const wires = [
    wire('a', 'A', [200, 30], 1, [320, 250], -1),
    wire('b', 'B', [200, 60], 1, [320, 220], -1),
    wire('c', 'C', [200, 90], 1, [320, 190], -1),
    wire('d', 'D', [200, 120], 1, [320, 160], -1),
  ];
  const { ways } = routeAll(wires, [left, right]);
  for (const p of wires) for (const q of wires) if (p.id < q.id) assert.equal(overlap(ways[p.id], ways[q.id]), 0, `${p.id} over ${q.id}`);
});

test('nets keep a track apart where there is room, even when tracks of two parts land close together', () => {
  const left: Box = { x: 0, y: 0, w: 200, h: 300 };
  const right: Box = { x: 320, y: 0, w: 200, h: 300 };
  const wires = [
    wire('a', 'A', [200, 30], 1, [320, 250], -1),
    wire('b', 'B', [200, 60], 1, [320, 220], -1),
    wire('c', 'C', [200, 90], 1, [320, 190], -1),
  ];
  const { ways } = routeAll(wires, [left, right]);
  const runs = (way: Pt[]) => way.slice(1).flatMap((p, i) => (p[0] === way[i][0] ? [{ x: p[0], y1: Math.min(p[1], way[i][1]), y2: Math.max(p[1], way[i][1]) }] : []));
  for (const p of wires) for (const q of wires) {
    if (p.id >= q.id) continue;
    for (const r of runs(ways[p.id])) for (const s of runs(ways[q.id])) {
      const along = Math.min(r.y2, s.y2) - Math.max(r.y1, s.y1);
      if (along > 20) assert.ok(Math.abs(r.x - s.x) >= 15, `${p.id} and ${q.id} run ${along} px at ${Math.abs(r.x - s.x)} px apart`);
    }
  }
});

test('wires of one net join into a bus and the branch gets a dot', () => {
  const left: Box = { x: 0, y: 0, w: 200, h: 100 };
  const up: Box = { x: 400, y: -200, w: 200, h: 100 };
  const down: Box = { x: 400, y: 200, w: 200, h: 100 };
  const { ways, joints } = routeAll([wire('a', 'N', [200, 50], 1, [400, -150], -1), wire('b', 'N', [200, 50], 1, [400, 250], -1)], [left, up, down]);
  assert.ok(overlap(ways.a, ways.b) > 0);
  assert.equal(joints.N?.length, 1);
});

test('crossing nets get no dot', () => {
  const { joints } = routeAll([wire('a', 'A', [0, 0], 1, [300, 200], -1), wire('b', 'B', [0, 200], 1, [300, 0], -1)], []);
  assert.deepEqual(joints, {});
});

test('parts on top of each other still give a wire', () => {
  const box: Box = { x: -50, y: -50, w: 500, h: 500 };
  const way = routeAll([wire('w', 'A', [0, 0], 1, [300, 40], -1)], [box]).ways.w;
  assert.ok(way.length >= 2);
  assert.ok(orthogonal(way));
});

test('forty wires route quickly enough to follow a drag', () => {
  const boxes: Box[] = [];
  for (let c = 0; c < 4; c++) for (let r = 0; r < 5; r++) boxes.push({ x: c * 340, y: r * 150, w: 240, h: 120 });
  const wires: Wire[] = [];
  for (let n = 0; n < 40; n++) {
    const p = boxes[n % boxes.length], q = boxes[(n * 7 + 3) % boxes.length];
    wires.push(wire(`w${n}`, `N${n}`, [p.x + 240, p.y + 40 + (n % 4) * 20], 1, [q.x, q.y + 40 + (n % 3) * 20], -1));
  }
  const t = performance.now();
  routeAll(wires, boxes);
  assert.ok(performance.now() - t < 250);
});

test('simplify keeps only the corners', () => {
  assert.deepEqual(simplify([[0, 0], [10, 0], [10, 0], [20, 0], [20, 10]]), [[0, 0], [20, 0], [20, 10]]);
});

test('the path starts and ends on the pins and rounds its corners', () => {
  const d = wirePath([[0, 0], [20, 0], [20, 20]]);
  assert.ok(d.startsWith('M0,0'));
  assert.ok(d.endsWith('L20,20'));
  assert.ok(d.includes('Q20,0'));
});
