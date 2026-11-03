// The routed board as the board editor sees it: circuit.json read into parts, pads (with their nets and their offsets
// from their part, so a moved part carries them), traces, pours and holes; the person's traces (fw.device/1 `routes`)
// drawn the same way; 45/90 degree corners; what is still to route; an autorouted trace turned into a hand one. Plain functions without Svelte (test/copper.test.ts runs them). Coordinates
// are mm from the board's centre, +y up, as in the device document.

export type Layer = 'top' | 'bottom';
export type Pt = { x: number; y: number; via?: boolean };
/** A trace the person drew: pad to pad ('R3.pin1', as the board names them), the layer it leaves `from` on. */
export type Route = { from: string; to: string; layer: Layer; width: number; points: Pt[] };
/** A pad as routed (x, y) and relative to its part's centre at the part's routed rotation (dx, dy). */
export type Pad = { key: string; comp: string; x: number; y: number; dx: number; dy: number; w: number; h: number; round: boolean; tht: boolean; net: string };
export type Seg = { x1: number; y1: number; x2: number; y2: number; layer: Layer; w: number };
export type Trace = { id: string; hand: boolean; from: string | null; to: string | null; net: string; segs: Seg[]; vias: [number, number][]; route: any[] };
export type Part = { id: string; x: number; y: number; rot: number; w: number; h: number };
export type Pose = { x: number; y: number; rot: number };
/** A pour as built: its outline and the holes the solver cut round other nets' copper. */
export type Pour = { layer: Layer; net: string; rings: [number, number][][] };
export type Copper = {
  board: { w: number; h: number };
  pads: Pad[];
  traces: Trace[];
  parts: Part[];
  holes: { x: number; y: number; d: number }[];
  /** net key -> its name where it has one */
  netName: Record<string, string>;
  /** pads one part joins inside itself (a button's 1-2 and 3-4) */
  internal: [string, string][];
  /** where a trace to each pad starts or ends (its port; a pad name may have several pads) */
  portAt: Map<string, [number, number]>;
  /** the same, as an offset from the port's part */
  portOf: Map<string, { comp: string; dx: number; dy: number }>;
  pours: Pour[];
};

const EPS = 1e-6;
const r3 = (v: number) => Math.round(v * 1000) / 1000 + 0;
export const flip = (l: Layer): Layer => (l === 'top' ? 'bottom' : 'top');

/** A union-find over string keys. */
function sets() {
  const parent = new Map<string, string>();
  const find = (a: string): string => {
    let r = a;
    while (parent.has(r) && parent.get(r) !== r) r = parent.get(r)!;
    while (parent.has(a) && parent.get(a) !== r) {
      const n = parent.get(a)!;
      parent.set(a, r);
      a = n;
    }
    return r;
  };
  const join = (a: string, b: string) => {
    const ra = find(a), rb = find(b);
    if (ra !== rb) parent.set(ra, rb);
  };
  return { find, join };
}

/** A trace's copper from its route: the runs between wire points on one layer, and its vias. */
function segsOf(route: any[], cx: number, cy: number): { segs: Seg[]; vias: [number, number][] } {
  const segs: Seg[] = [];
  const vias: [number, number][] = [];
  let prev: any = null;
  for (const p of route) {
    if (p.route_type === 'via') {
      vias.push([r3(p.x - cx), r3(p.y - cy)]);
      continue;
    }
    if (p.route_type !== 'wire') continue;
    if (prev && prev.layer === p.layer && Math.hypot(p.x - prev.x, p.y - prev.y) > EPS)
      segs.push({ x1: prev.x - cx, y1: prev.y - cy, x2: p.x - cx, y2: p.y - cy, layer: p.layer === 'bottom' ? 'bottom' : 'top', w: p.width ?? prev.width ?? 0.2 });
    prev = p;
  }
  return { segs, vias };
}

export function readCopper(cj: any[]): Copper | null {
  const b = cj.find((e) => e.type === 'pcb_board');
  if (!b) return null;
  const cx = b.center?.x ?? 0, cy = b.center?.y ?? 0;
  const name = new Map<string, string>(cj.filter((e) => e.type === 'source_component').map((e) => [e.source_component_id, e.name]));
  const srcKey = new Map<string, string>(cj.filter((e) => e.type === 'source_port').map((e) => [e.source_port_id, `${name.get(e.source_component_id)}.${e.name}`]));
  const pcbSrc = new Map<string, string>(cj.filter((e) => e.type === 'pcb_port').map((e) => [e.pcb_port_id, e.source_port_id]));
  // nets: the ports each source trace joins (to each other or to a net), and the pins a part joins inside itself
  const { find, join } = sets();
  for (const t of cj.filter((e) => e.type === 'source_trace')) {
    const ids = [...(t.connected_source_port_ids ?? []), ...(t.connected_source_net_ids ?? []).map((n: string) => `net:${n}`)];
    for (const id of ids.slice(1)) join(ids[0], id);
  }
  const internal: [string, string][] = [];
  for (const c of cj.filter((e) => e.type === 'source_component')) {
    for (const g of c.internally_connected_source_port_ids ?? []) {
      for (const id of g.slice(1)) {
        join(g[0], id);
        const a = srcKey.get(g[0]), k = srcKey.get(id);
        if (a && k) internal.push([a, k]);
      }
    }
  }
  const netName: Record<string, string> = {};
  for (const n of cj.filter((e) => e.type === 'source_net')) if (n.name) netName[find(`net:${n.source_net_id}`)] = n.name;
  const keyOf = (pcbPort?: string) => (pcbPort ? srcKey.get(pcbSrc.get(pcbPort) ?? '') ?? null : null);
  const compName = new Map<string, string>(cj.filter((e) => e.type === 'pcb_component').map((c) => [c.pcb_component_id, name.get(c.source_component_id) ?? '']));
  const compAt = new Map<string, [number, number]>(cj.filter((e) => e.type === 'pcb_component').map((c) => [c.pcb_component_id, [c.center.x, c.center.y]]));
  const netOf = (pcbPort?: string) => find(pcbSrc.get(pcbPort ?? '') ?? `lone:${pcbPort}`);

  const pads: Pad[] = [];
  for (const p of cj.filter((e) => (e.type === 'pcb_smtpad' || e.type === 'pcb_plated_hole') && e.pcb_port_id)) {
    const key = keyOf(p.pcb_port_id);
    if (!key) continue;
    const tht = p.type === 'pcb_plated_hole';
    const round = p.shape === 'circle' || (tht && !p.rect_pad_width);
    const w = p.width ?? p.rect_pad_width ?? p.outer_diameter ?? (p.radius ? p.radius * 2 : 1);
    const h = p.height ?? p.rect_pad_height ?? p.outer_diameter ?? (p.radius ? p.radius * 2 : 1);
    const at = compAt.get(p.pcb_component_id) ?? [p.x, p.y];
    pads.push({ key, comp: compName.get(p.pcb_component_id) ?? key.split('.')[0], x: r3(p.x - cx), y: r3(p.y - cy), dx: r3(p.x - at[0]), dy: r3(p.y - at[1]), w, h, round, tht, net: netOf(p.pcb_port_id) });
  }
  const traces: Trace[] = [];
  for (const t of cj.filter((e) => e.type === 'pcb_trace' && Array.isArray(e.route) && e.route.length)) {
    const first = t.route[0], last = t.route[t.route.length - 1];
    const { segs, vias } = segsOf(t.route, cx, cy);
    traces.push({
      id: t.pcb_trace_id,
      // the autorouter names its traces after the connections; a pcbPath trace gets a plain id
      hand: !/^source_/.test(t.pcb_trace_id ?? ''),
      from: keyOf(first.start_pcb_port_id),
      to: keyOf(last.end_pcb_port_id),
      net: netOf(first.start_pcb_port_id ?? last.end_pcb_port_id),
      segs,
      vias,
      route: t.route.map((p: any) => ({ ...p, x: p.x - cx, y: p.y - cy })),
    });
  }
  const parts: Part[] = cj
    .filter((e) => e.type === 'pcb_component' && name.get(e.source_component_id))
    .map((c) => ({ id: name.get(c.source_component_id)!, x: r3(c.center.x - cx), y: r3(c.center.y - cy), rot: (((c.rotation ?? 0) % 360) + 360) % 360, w: c.width ?? 1, h: c.height ?? 1 }));
  const holes = cj.filter((e) => e.type === 'pcb_hole').map((e) => ({ x: e.x - cx, y: e.y - cy, d: e.hole_diameter ?? 3.2 }));
  const portAt = new Map<string, [number, number]>();
  const portOf = new Map<string, { comp: string; dx: number; dy: number }>();
  for (const p of cj.filter((e) => e.type === 'pcb_port')) {
    const key = keyOf(p.pcb_port_id);
    if (!key || portAt.has(key) || typeof p.x !== 'number') continue;
    portAt.set(key, [r3(p.x - cx), r3(p.y - cy)]);
    const at = compAt.get(p.pcb_component_id);
    if (at) portOf.set(key, { comp: compName.get(p.pcb_component_id) ?? key.split('.')[0], dx: r3(p.x - at[0]), dy: r3(p.y - at[1]) });
  }
  // pours: a brep (outer ring and the holes round other copper), a polygon or a rect
  const netNames = new Map<string, string>(cj.filter((e) => e.type === 'source_net').map((n) => [n.source_net_id, n.name]));
  const pours: Pour[] = [];
  for (const p of cj.filter((e) => e.type === 'pcb_copper_pour')) {
    const ring = (vs: any[]) => (vs ?? []).map((v: any) => [r3(v.x - cx), r3(v.y - cy)] as [number, number]);
    let rings: [number, number][][] = [];
    if (p.shape === 'brep' && p.brep_shape) rings = [ring(p.brep_shape.outer_ring?.vertices), ...(p.brep_shape.inner_rings ?? []).map((r: any) => ring(r.vertices))];
    else if (p.shape === 'polygon') rings = [ring(p.points)];
    else if (p.shape === 'rect' && p.center) {
      const { x, y } = p.center, w = p.width / 2, h = p.height / 2;
      rings = [ring([{ x: x - w, y: y - h }, { x: x + w, y: y - h }, { x: x + w, y: y + h }, { x: x - w, y: y + h }])];
    }
    if (rings.length) pours.push({ layer: p.layer === 'top' ? 'top' : 'bottom', net: netNames.get(p.source_net_id) ?? '', rings });
  }
  return { board: { w: b.width, h: b.height }, pads, traces, parts, holes, netName, internal, portAt, portOf, pours };
}

/** (dx, dy) turned by deg (counter-clockwise, quarter turns exact). */
export function turn(dx: number, dy: number, deg: number): [number, number] {
  const r = (deg * Math.PI) / 180;
  const c = Math.abs(deg % 90) < 1e-9 ? Math.round(Math.cos(r)) : Math.cos(r), s = Math.abs(deg % 90) < 1e-9 ? Math.round(Math.sin(r)) : Math.sin(r);
  return [r3(dx * c - dy * s), r3(dx * s + dy * c)];
}

/** Where a point fixed to a part goes when the part moves from its routed pose to pose. */
export function carry(from: Pose, to: Pose, x: number, y: number): [number, number] {
  const [dx, dy] = turn(x - from.x, y - from.y, to.rot - from.rot);
  return [r3(to.x + dx), r3(to.y + dy)];
}

/** The corner between a and b so that both runs are straight or 45 degrees: along the longer axis first (or the
 * diagonal first), null when a single straight or diagonal run already joins them. */
export function octi(a: [number, number], b: [number, number], diagFirst = false): [number, number] | null {
  const dx = b[0] - a[0], dy = b[1] - a[1], ax = Math.abs(dx), ay = Math.abs(dy);
  if (ax < EPS || ay < EPS || Math.abs(ax - ay) < EPS) return null;
  const sx = Math.sign(dx), sy = Math.sign(dy), d = Math.min(ax, ay);
  if (diagFirst) return [r3(a[0] + sx * d), r3(a[1] + sy * d)];
  return ax > ay ? [r3(b[0] - sx * d), r3(a[1])] : [r3(a[0]), r3(b[1] - sy * d)];
}

/** A grid point pulled onto the straight or diagonal line from the last corner when it is within tol of one, so a
 * pad off the grid gives no tiny jogs. */
export function align(from: [number, number], p: [number, number], tol: number): [number, number] {
  const dx = p[0] - from[0], dy = p[1] - from[1];
  if (Math.abs(dy) <= tol) return [p[0], from[1]];
  if (Math.abs(dx) <= tol) return [from[0], p[1]];
  if (Math.abs(Math.abs(dx) - Math.abs(dy)) <= tol) {
    const d = (Math.abs(dx) + Math.abs(dy)) / 2;
    return [r3(from[0] + Math.sign(dx) * d), r3(from[1] + Math.sign(dy) * d)];
  }
  return p;
}

/** A hand trace's copper between its pads: the runs layer by layer (a via switches) and the vias. */
export function routeCopper(r: Route, start: [number, number], end: [number, number]): { segs: Seg[]; vias: [number, number][]; endLayer: Layer } {
  const segs: Seg[] = [];
  const vias: [number, number][] = [];
  let layer = r.layer;
  let [px, py] = start;
  const run = (x: number, y: number) => {
    if (Math.hypot(x - px, y - py) > EPS) segs.push({ x1: px, y1: py, x2: x, y2: y, layer, w: r.width });
    px = x;
    py = y;
  };
  for (const q of r.points) {
    run(q.x, q.y);
    if (q.via) {
      vias.push([q.x, q.y]);
      layer = flip(layer);
    }
  }
  run(end[0], end[1]);
  return { segs, vias, endLayer: layer };
}

export const segLength = (segs: Seg[]) => segs.reduce((n, s) => n + Math.hypot(s.x2 - s.x1, s.y2 - s.y1), 0);

/** The connections still to make: per net, the islands its pads form through the copper shown (the autorouter's traces
 * not hidden, the hand traces), joined by the shortest lines between islands. */
export function unrouted(c: Copper, routes: Route[], hidden: Set<string>, at: (p: Pad) => [number, number] = (p) => [p.x, p.y]): [number, number, number, number][] {
  const { find, join } = sets();
  for (const t of c.traces) if (!hidden.has(t.id) && t.from && t.to) join(t.from, t.to);
  for (const r of routes) join(r.from, r.to);
  for (const [a, b] of c.internal) join(a, b);
  const byNet = new Map<string, Map<string, [number, number]>>();
  for (const p of c.pads) {
    const m = byNet.get(p.net) ?? new Map();
    if (!m.has(p.key)) m.set(p.key, at(p));
    byNet.set(p.net, m);
  }
  const lines: [number, number, number, number][] = [];
  for (const m of byNet.values()) {
    if (m.size < 2) continue;
    const islands = new Map<string, [number, number][]>();
    for (const [k, at] of m) {
      const r = find(k);
      islands.set(r, [...(islands.get(r) ?? []), at]);
    }
    const isl = [...islands.values()];
    const done = [0];
    while (done.length < isl.length) {
      let best: { j: number; d: number; a: [number, number]; b: [number, number] } | null = null;
      for (const i of done) {
        for (let j = 0; j < isl.length; j++) {
          if (done.includes(j)) continue;
          for (const a of isl[i]) for (const b of isl[j]) {
            const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
            if (!best || d < best.d) best = { j, d, a, b };
          }
        }
      }
      if (!best) break;
      done.push(best.j);
      lines.push([best.a[0], best.a[1], best.b[0], best.b[1]]);
    }
  }
  return lines;
}

/** An autorouted trace as a hand one (kept as it is by every later build), or null when it does not run pad to pad. */
export function lockTrace(t: Trace): Route | null {
  if (!t.from || !t.to || t.route.length < 2) return null;
  const near = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y) < 0.002;
  const start = t.route[0], end = t.route[t.route.length - 1];
  const points: Pt[] = [];
  for (const p of t.route.slice(1, -1)) {
    const last = points[points.length - 1] ?? start;
    if (p.route_type === 'via') {
      if (points.length && near(last, p)) points[points.length - 1].via = true;
      else points.push({ x: r3(p.x), y: r3(p.y), via: true });
    } else if (p.route_type === 'wire' && !near(last, p)) points.push({ x: r3(p.x), y: r3(p.y) });
  }
  if (points.length && !points[points.length - 1].via && near(points[points.length - 1], end)) points.pop();
  const layer: Layer = start.layer === 'bottom' ? 'bottom' : 'top';
  return { from: t.from, to: t.to, layer, width: Math.round((start.width ?? 0.2) * 100) / 100, points };
}
