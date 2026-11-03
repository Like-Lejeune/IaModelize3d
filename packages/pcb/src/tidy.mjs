// Copper the way a person draws it: after the autorouter, every trace's runs (the stretches between its pads and vias,
// on one layer) are straightened and given 45° and 90° corners. The router's paths meander in many short steps; this
// keeps their endpoints and vias where they are and replaces what lies between with as few octilinear segments as fit.
// Nothing is trusted blindly: the checks run again, and a trace whose new shape breaks a clearance tries the other
// corner order, then goes back to the router's own path.

const EPS = 0.4;      // mm the simplified run may stray from the router's path before a point is kept
const MIN_SEG = 0.05;

const near = (a, b) => Math.abs(a - b) < 1e-6;

/** Douglas–Peucker on [{x, y}] (endpoints kept). */
function simplify(pts, eps) {
  if (pts.length <= 2) return pts;
  const [a, b] = [pts[0], pts[pts.length - 1]];
  const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1e-9;
  let worst = 0, at = 0;
  for (let i = 1; i < pts.length - 1; i++) {
    const d = Math.abs(dy * pts[i].x - dx * pts[i].y + b.x * a.y - b.y * a.x) / L;
    if (d > worst) [worst, at] = [d, i];
  }
  if (worst <= eps) return [a, b];
  return [...simplify(pts.slice(0, at + 1), eps).slice(0, -1), ...simplify(pts.slice(at), eps)];
}

/** A -> B in at most two octilinear segments: the diagonal first ('diag') or the straight part first ('straight'). */
function octi(a, b, order) {
  const dx = b.x - a.x, dy = b.y - a.y, ax = Math.abs(dx), ay = Math.abs(dy);
  if (ax < MIN_SEG || ay < MIN_SEG || Math.abs(ax - ay) < MIN_SEG) return [b];
  const d = Math.min(ax, ay), sx = Math.sign(dx), sy = Math.sign(dy);
  const m = order === 'diag' ? { x: a.x + sx * d, y: a.y + sy * d } : { x: b.x - sx * d, y: b.y - sy * d };
  return [m, b];
}

/** One run (same layer, between pads/vias) as octilinear points, the first point excluded. */
function runShape(run, order) {
  const simple = simplify(run, EPS);
  const out = [];
  for (let i = 1; i < simple.length; i++) out.push(...octi(simple[i - 1], simple[i], order));
  // drop points that end up on a straight line with their neighbours
  const pts = [run[0], ...out];
  const keep = [pts[0]];
  for (let i = 1; i < pts.length - 1; i++) {
    const p = keep[keep.length - 1], q = pts[i], r = pts[i + 1];
    const cross = (q.x - p.x) * (r.y - q.y) - (q.y - p.y) * (r.x - q.x);
    if (Math.abs(cross) > 1e-6 && Math.hypot(q.x - p.x, q.y - p.y) > 1e-6) keep.push(q);
  }
  keep.push(pts[pts.length - 1]);
  return keep.slice(1);
}

/** A trace's route re-shaped: each run of wire points on one layer keeps its two ends (pads, vias) and becomes
 * octilinear in between; vias and the points around them stay where the router put them. */
function reshape(route, order) {
  const out = [];
  let i = 0;
  while (i < route.length) {
    const p = route[i];
    if (p.route_type !== 'wire') {
      out.push(p);
      i++;
      continue;
    }
    let j = i;
    while (j + 1 < route.length && route[j + 1].route_type === 'wire' && route[j + 1].layer === p.layer) j++;
    const run = route.slice(i, j + 1);
    if (run.length < 2) out.push(...run);
    else {
      out.push(run[0]);
      const shaped = runShape(run.map((q) => ({ x: q.x, y: q.y })), order);
      const { start_pcb_port_id, end_pcb_port_id, ...plain } = run[0];
      for (const q of shaped.slice(0, -1)) out.push({ ...plain, x: round(q.x), y: round(q.y) });
      out.push(run[run.length - 1]);
    }
    i = j + 1;
  }
  return out;
}

const round = (v) => Math.round(v * 1000) / 1000;

/** The traces an error is about: by id, or by the display name ('.U1 > .V5 to .U2 > .VDD') a message quotes. */
function traceIdsOf(err, names) {
  const ids = new Set();
  for (const [k, v] of Object.entries(err)) {
    if (k === 'pcb_trace_id' && typeof v === 'string') ids.add(v);
    if (k === 'pcb_trace_ids' && Array.isArray(v)) v.forEach((x) => ids.add(x));
  }
  const msg = String(err.message ?? '');
  for (const m of msg.matchAll(/pcb_trace_\d+/g)) ids.add(m[0]);
  for (const [name, id] of names) if (name && msg.includes(name)) ids.add(id);
  return ids;
}

/**
 * Tidy every trace of a routed circuit in place, keeping only what the checks accept. Returns
 * {drc (the checks of the final copper), tidied, reverted, segments: [before, after]}.
 */
export async function tidyTraces(cj, runChecks) {
  // the autorouter's traces only (ids from its connections): a trace the person drew stays as they drew it
  const traces = cj.filter((e) => e.type === 'pcb_trace' && Array.isArray(e.route) && /^source_/.test(e.pcb_trace_id ?? ''));
  const original = new Map(traces.map((t) => [t.pcb_trace_id, t.route]));
  const segs = () => traces.reduce((n, t) => n + Math.max(0, t.route.filter((p) => p.route_type === 'wire').length - 1), 0);
  const before = segs();
  const baseline = await runChecks(cj);
  const known = new Set(baseline.map((e) => `${e.type}|${e.message}`));
  const order = new Map();
  for (const t of traces) {
    t.route = reshape(t.route, 'diag');
    order.set(t.pcb_trace_id, 'diag');
  }
  // what the checks call each trace in their messages
  const display = new Map(cj.filter((e) => e.type === 'source_trace').map((e) => [e.source_trace_id, e.display_name]));
  const names = traces.map((t) => [display.get(t.source_trace_id), t.pcb_trace_id]);
  let drc = baseline;
  const reverted = new Set();
  for (let round = 0; round < 5; round++) {
    drc = await runChecks(cj);
    const fresh = drc.filter((e) => !known.has(`${e.type}|${e.message}`));
    if (!fresh.length) break;
    const blame = new Set();
    for (const e of fresh) for (const id of traceIdsOf(e, names)) if (original.has(id) && !reverted.has(id)) blame.add(id);
    if (!blame.size || round === 4) {
      // a new problem no changed trace is named in (or still one at the end): every trace gets its router path back
      for (const t of traces) t.route = original.get(t.pcb_trace_id);
      drc = baseline;
      reverted.clear();
      traces.forEach((t) => reverted.add(t.pcb_trace_id));
      break;
    }
    for (const t of traces) {
      if (!blame.has(t.pcb_trace_id)) continue;
      if (order.get(t.pcb_trace_id) === 'diag') {
        t.route = reshape(original.get(t.pcb_trace_id), 'straight');
        order.set(t.pcb_trace_id, 'straight');
      } else {
        t.route = original.get(t.pcb_trace_id);
        reverted.add(t.pcb_trace_id);
      }
    }
  }
  return { drc, tidied: traces.length - reverted.size, reverted: reverted.size, segments: [before, segs()] };
}
