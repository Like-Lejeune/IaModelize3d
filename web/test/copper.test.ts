// node --test web/test/copper.test.ts: the hand-routing editor's reading of a routed board (a XIAO weather station,
// fixtures/weather.circuit.json trimmed from a real build), its 45/90 degree corners, what is left to route and
// turning an autorouted trace into a hand one.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const { readCopper, octi, align, routeCopper, unrouted, lockTrace, segLength } = await import('../src/lib/device/copper.ts');
const cj = JSON.parse(readFileSync(new URL('./fixtures/weather.circuit.json', import.meta.url), 'utf8'));

test('pads carry their nets: every GND pad is one net, an LED pin another', () => {
  const c = readCopper(cj)!;
  assert.deepEqual(c.board, { w: 36, h: 35 });
  const pad = (k: string) => c.pads.find((p) => p.key === k)!;
  assert.equal(pad('J2.GND').net, pad('U1.GND').net);
  assert.equal(c.netName[pad('J2.GND').net], 'GND');
  assert.notEqual(pad('LED1.pin1').net, pad('LED1.pin2').net);
  assert.equal(pad('U1.GND').tht, true);
  assert.equal(pad('R3.pin1').tht, false);
  // a button's two contacts are a pin pair each
  assert.ok(c.internal.some(([a, b]) => a === 'SW1.pin1' && b === 'SW1.pin2'));
  assert.equal(c.parts.find((p) => p.id === 'U1')!.y, 7);
  // a trace to a pad starts at its port
  assert.deepEqual(c.portAt.get('U1.MOSI'), [7.62, 7]);
});

test('a freshly routed board has nothing left to route; hiding a trace brings its connection back', () => {
  const c = readCopper(cj)!;
  assert.equal(c.traces.length, 32);
  assert.ok(c.traces.every((t) => !t.hand && t.from && t.to));
  assert.deepEqual(unrouted(c, [], new Set()), []);
  const t = c.traces.find((x) => [x.from, x.to].sort().join() === 'R3.pin1,U1.MOSI')!;
  const left = unrouted(c, [], new Set([t.id]));
  assert.equal(left.length, 1);
  // a hand trace between the same pads closes it again
  assert.deepEqual(unrouted(c, [{ from: 'U1.MOSI', to: 'R3.pin1', layer: 'top', width: 0.25, points: [] }], new Set([t.id])), []);
});

test('corners are straight then 45 degrees, or the diagonal first', () => {
  assert.deepEqual(octi([0, 0], [10, 4]), [6, 0]);
  assert.deepEqual(octi([0, 0], [4, -10]), [0, -6]);
  assert.deepEqual(octi([0, 0], [10, 4], true), [4, 4]);
  assert.equal(octi([0, 0], [5, 5]), null);
  assert.equal(octi([0, 0], [0, 7]), null);
  // a pad off the grid: the next grid point is pulled onto its straight or diagonal line
  assert.deepEqual(align([7.62, 12.08], [4, 12], 0.25), [4, 12.08]);
  assert.deepEqual(align([7.62, 12.08], [5.5, 10], 0.25), [5.52, 9.98]);
  assert.deepEqual(align([7.62, 12.08], [4, 10], 0.25), [4, 10]);
});

test('a hand trace draws layer by layer and a via switches the layer', () => {
  const r = { from: 'J2.GND', to: 'U1.GND', layer: 'bottom' as const, width: 0.4, points: [{ x: 0, y: -10 }, { x: 5, y: -5, via: true }] };
  const { segs, vias, endLayer } = routeCopper(r, [0, -15], [5, 0]);
  assert.deepEqual(segs.map((s) => s.layer), ['bottom', 'bottom', 'top']);
  assert.deepEqual(vias, [[5, -5]]);
  assert.equal(endLayer, 'top');
  assert.ok(Math.abs(segLength(segs) - (5 + Math.SQRT2 * 5 + 5)) < 1e-9);
});

test('an autorouted trace locks into a hand trace with its corners and vias', () => {
  const c = readCopper(cj)!;
  const t = c.traces.find((x) => x.vias.length > 0 && x.from && x.to)!;
  const r = lockTrace(t)!;
  assert.equal(r.from, t.from);
  assert.equal(r.to, t.to);
  assert.equal(r.points.filter((p) => p.via).length, t.vias.length);
  // the same copper as the autorouter's
  const start = t.route[0], end = t.route[t.route.length - 1];
  const drawn = routeCopper(r, [start.x, start.y], [end.x, end.y]);
  assert.ok(Math.abs(segLength(drawn.segs) - segLength(t.segs)) < 0.01, `${segLength(drawn.segs)} vs ${segLength(t.segs)}`);
  assert.deepEqual(drawn.segs.map((s) => s.layer), t.segs.map((s) => s.layer));
});

test('a pad moves and turns with its part; a pour reads as its outline and holes', async () => {
  const { carry, turn } = await import('../src/lib/device/copper.ts');
  const c = readCopper(cj)!;
  // R3 turned a quarter about its centre and moved 2 mm right: its pin 1 goes with it
  const r3 = c.parts.find((p) => p.id === 'R3')!;
  const pad = c.pads.find((p) => p.key === 'R3.pin1')!;
  const [x, y] = carry(r3, { x: r3.x + 2, y: r3.y, rot: r3.rot + 90 }, pad.x, pad.y);
  const [dx, dy] = turn(pad.x - r3.x, pad.y - r3.y, 90);
  assert.deepEqual([x, y], [+(r3.x + 2 + dx).toFixed(3), +(r3.y + dy).toFixed(3)]);
  assert.equal(pad.comp, 'R3');
  assert.deepEqual(c.portOf.get('R3.pin1')?.comp, 'R3');
  const pour = {
    type: 'pcb_copper_pour', shape: 'brep', layer: 'bottom', source_net_id: 'source_net_0',
    brep_shape: { outer_ring: { vertices: [{ x: -5, y: -5 }, { x: 5, y: -5 }, { x: 5, y: 5 }, { x: -5, y: 5 }] }, inner_rings: [{ vertices: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }] }] },
  };
  const withPour = readCopper([...cj, pour])!;
  assert.equal(withPour.pours.length, 1);
  assert.equal(withPour.pours[0].net, 'GND');
  assert.equal(withPour.pours[0].rings.length, 2);
});
