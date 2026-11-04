// Circuit JSON -> fw.board/1 (packages/geom/src/board.schema.json, contract C1): the same description the enclosure
// library gets for a dataset board or a board measured from a photo, so "case for our PCB" and "case for that board"
// run through one lib.elec. Frame: mm, origin at the bottom-left corner of the PCB seen from the component side,
// x right, y up, z up from the PCB bottom face; component heights are above the face they sit on.
// Geometry comes from the routed circuit (courtyards, holes) and is exact; only connector and part heights come from
// the typical table, and those carry verify ['h']. Modules (a XIAO on headers) expand into their own components from
// the dataset entry, raised by the seat height (z0), so the XIAO's own USB-C becomes a second port on z 3.7-6.9.
import boardsData from '../../geom/src/boards.json' with { type: 'json' };
import modulesData from './modules.json' with { type: 'json' };

const TYPICAL = boardsData.typical ?? {};
const DATASET = Object.fromEntries((boardsData.boards ?? []).map((b) => [b.id, b]));
export const MODULES = modulesData.modules;
export const EDGE_MM = modulesData.edge_mm ?? 1.0;
const ANGLE = { '+x': 0, '+y': 90, '-x': 180, '-y': 270 };
const EDGE_AT = { 0: '+x', 90: '+y', 180: '-x', 270: '-y' };
const FRAME = 'mm. Origin at the bottom-left corner of the PCB seen from the component (top) side; x right, y up, z up from the PCB bottom face. Component z values are heights above the face they sit on. Generated from the routed circuit.';

const r2 = (v) => Math.round(v * 100) / 100;
const norm = (deg) => ((Math.round(deg / 90) * 90) % 360 + 360) % 360;
export const rotateEdge = (edge, deg) => EDGE_AT[norm(ANGLE[edge] + deg)];

/** Board rectangle and the shift from the circuit frame (centre origin) to fw.board/1 (bottom-left origin). */
export function boardFrame(cj) {
  const b = cj.find((e) => e.type === 'pcb_board');
  if (!b) throw new Error('the circuit has no <board>');
  const W = b.width, H = b.height;
  const origin = [b.center.x - W / 2, b.center.y - H / 2];
  const poly = Array.isArray(b.outline) && b.outline.length >= 3 ? b.outline.map((p) => [p.x - origin[0], p.y - origin[1]]) : null;
  return { board: b, W, H, origin, poly, fw: (x, y) => [x - origin[0], y - origin[1]] };
}

/** Where a polygon outline's boundary lies on an edge's side at u along that edge (x for the +-y edges, y for +-x), or null. */
export function rimAt(poly, edge, u) {
  const t = edge[1] === 'y' ? 0 : 1;
  const hits = [];
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    if (a[t] === b[t] || u < Math.min(a[t], b[t]) || u > Math.max(a[t], b[t])) continue;
    hits.push(a[1 - t] + ((u - a[t]) / (b[t] - a[t])) * (b[1 - t] - a[1 - t]));
  }
  if (!hits.length) return null;
  return edge[0] === '+' ? Math.max(...hits) : Math.min(...hits);
}

/** Per component (by reference designator): its source/pcb records and its body box [x0, y0, x1, y1] in the circuit frame. */
export function componentBoxes(cj) {
  const src = Object.fromEntries(cj.filter((e) => e.type === 'source_component').map((s) => [s.source_component_id, s]));
  const cad = Object.fromEntries(cj.filter((e) => e.type === 'cad_component').map((c) => [c.pcb_component_id, c]));
  const boxes = {};
  const grow = (id, x, y) => {
    const b = (boxes[id] ??= [Infinity, Infinity, -Infinity, -Infinity]);
    b[0] = Math.min(b[0], x); b[1] = Math.min(b[1], y); b[2] = Math.max(b[2], x); b[3] = Math.max(b[3], y);
  };
  // courtyards first: tighter and more honest than pcb_component width/height
  for (const e of cj) {
    if (!e.pcb_component_id) continue;
    if (e.type === 'pcb_courtyard_rect') {
      const a = ((e.ccw_rotation ?? 0) * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
      for (const [dx, dy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
        const x = (dx * e.width) / 2, y = (dy * e.height) / 2;
        grow(e.pcb_component_id, e.center.x + x * c - y * s, e.center.y + x * s + y * c);
      }
    } else if (e.type === 'pcb_courtyard_outline') {
      for (const p of e.outline ?? []) grow(e.pcb_component_id, p.x, p.y);
    }
  }
  const out = {};
  for (const pc of cj.filter((e) => e.type === 'pcb_component')) {
    const s = src[pc.source_component_id] ?? {};
    let box = boxes[pc.pcb_component_id];
    if (!box) box = [pc.center.x - pc.width / 2, pc.center.y - pc.height / 2, pc.center.x + pc.width / 2, pc.center.y + pc.height / 2];
    const ref = s.name ?? pc.pcb_component_id;
    out[ref] = {
      ref, pc, src: s, box, center: [pc.center.x, pc.center.y], rotation: pc.rotation ?? 0, layer: pc.layer ?? 'top',
      footprint: cad[pc.pcb_component_id]?.footprinter_string ?? s.footprint ?? '', ftype: s.ftype ?? '',
      mpn: s.manufacturer_part_number ?? null,
    };
  }
  return out;
}

export function partRule(ftype, footprint) {
  return modulesData.parts.find((r) => (!r.ftype || r.ftype === ftype) && (!r.footprint || new RegExp(r.footprint).test(footprint ?? '')));
}

function typicalHeight(key) {
  const t = TYPICAL[key];
  if (!t) return null;
  if (Number.isFinite(t.h)) return t.h;
  if (Number.isFinite(t.body_h)) return t.body_h + (t.pin_above ?? 0); // male header: plastic + pin above it
  return null;
}

/**
 * How far a body's faces lie from each edge. On a shaped board (a polygon outline) from the outline itself: at the body's
 * corners and middle, the nearest, so a part whose corners touch a round rim is at that edge wherever along it it sits.
 */
export function gapsOf([x0, y0, x1, y1], W, H, poly = null) {
  const flat = { '-x': x0, '+x': W - x1, '-y': y0, '+y': H - y1 };
  if (!poly) return flat;
  const near = (edge, a, b, face) => {
    const gaps = [a, (a + b) / 2, b].map((u) => rimAt(poly, edge, u)).filter((r) => r != null).map((r) => (edge[0] === '+' ? r - face : face - r));
    return gaps.length ? Math.min(...gaps) : flat[edge];
  };
  return { '-x': near('-x', y0, y1, x0), '+x': near('+x', y0, y1, x1), '-y': near('-y', x0, x1, y0), '+y': near('+y', x0, x1, y1) };
}

/** How far a point on an edge's normal stands past that edge: from the outline at u on a shaped board. */
function pastEdge(edge, n, u, W, H, poly) {
  const rim = (poly ? rimAt(poly, edge, u) : null) ?? { '+x': W, '-x': 0, '+y': H, '-y': 0 }[edge];
  return edge[0] === '+' ? n - rim : rim - n;
}

function portFields([x0, y0, x1, y1], edge, W, H, poly = null) {
  const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
  switch (edge) {
    case '-y': return { at: mx, w: x1 - x0, d: y1 - y0, protrude: pastEdge(edge, y0, mx, W, H, poly) };
    case '+y': return { at: mx, w: x1 - x0, d: y1 - y0, protrude: pastEdge(edge, y1, mx, W, H, poly) };
    case '-x': return { at: my, w: y1 - y0, d: x1 - x0, protrude: pastEdge(edge, x0, my, W, H, poly) };
    default: return { at: my, w: y1 - y0, d: x1 - x0, protrude: pastEdge(edge, x1, my, W, H, poly) };
  }
}

/** Where a part's port could go: the facing edge (rotated with the part) or, for an any-way part, the nearest edge. */
export function portEdge(rule, rotation, boxFw, W, H, poly = null) {
  const gaps = gapsOf(boxFw, W, H, poly);
  const edge = rule.faces ? rotateEdge(rule.faces, rotation) : Object.entries(gaps).sort((a, b) => a[1] - b[1])[0][0];
  return { edge, gap: gaps[edge], gaps };
}

const roundAll = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === 'number' ? r2(v) : v]));

// A module on headers: its PCB as a slab at z0 = seat, the header strips under it, and its own parts lifted by
// seat + thickness (z0), its ports included when they reach the carrier's edge.
function expandModule(c, mod, fwCenter, W, H, pins, poly = null) {
  const ds = DATASET[mod.dataset_id];
  const [mw, mh] = mod.size;
  const off = mod.offset ?? [0, 0];
  const rot = norm(c.rotation);
  const a = (rot * Math.PI) / 180, ca = Math.round(Math.cos(a)), sa = Math.round(Math.sin(a));
  const ref = c.ref;
  // module frame (bottom-left origin, as in the dataset) -> carrier fw frame
  const place = (x, y) => {
    const dx = x - (mw / 2 + off[0]), dy = y - (mh / 2 + off[1]);
    return [fwCenter[0] + dx * ca - dy * sa, fwCenter[1] + dx * sa + dy * ca];
  };
  const swap = rot === 90 || rot === 270;
  const lift = mod.seat + mod.thickness;
  const seatVerify = (mod.verify ?? []).includes('seat');
  const ev = { ref, footprint: c.footprint, module: mod.name };
  const [bx, by] = place(mw / 2, mh / 2);
  const comps = [roundAll({
    id: ref, type: String(mod.dataset_id ?? 'module').replace(/-/g, '_'), side: c.layer, access: 'none', x: bx, y: by,
    w: swap ? mh : mw, d: swap ? mw : mh, z0: mod.seat, h: mod.thickness, normal: [0, 0, 1], src: 'modules',
    verify: seatVerify ? ['z0'] : [], evidence: ev, note: `${mod.name}: module PCB ${mod.thickness} mm on ${mod.seat} mm header spacers`,
  })];
  // header plastic under the module, one strip per pin row (rows run along the module's long side)
  if (mod.seat > 0 && pins.length) {
    const along = swap ? 0 : 1; // the coordinate that runs along a row
    const rows = new Map();
    for (const p of pins) {
      const key = Math.round(p[1 - along] * 10) / 10;
      if (!rows.has(key)) rows.set(key, []);
      rows.get(key).push(p[along]);
    }
    let i = 0;
    for (const [across, vals] of [...rows.entries()].sort((x, y) => x[0] - y[0])) {
      const lo = Math.min(...vals) - 1.27, hi = Math.max(...vals) + 1.27;
      const mid = (lo + hi) / 2;
      comps.push(roundAll({
        id: `${ref}_hdr_${++i}`, type: 'pin_header_2_54', side: c.layer, access: 'none', x: along ? across : mid, y: along ? mid : across,
        w: along ? 2.5 : hi - lo, d: along ? hi - lo : 2.5, h: mod.seat, normal: [0, 0, 1], src: 'modules', verify: seatVerify ? ['h'] : [], evidence: ev,
      }));
    }
  }
  const keepouts = [];
  if (!ds) return { comps, keepouts };
  for (const s of ds.components ?? []) {
    const verify = [...new Set([...(s.verify ?? []), ...(seatVerify ? ['z0'] : [])])];
    if (s.access === 'port' && s.edge) {
      const mouth = { '+y': [s.at, mh + s.protrude], '-y': [s.at, -s.protrude], '+x': [mw + s.protrude, s.at], '-x': [-s.protrude, s.at] }[s.edge];
      const m = place(mouth[0], mouth[1]);
      const edge = rotateEdge(s.edge, rot);
      const at = edge[1] === 'x' ? m[1] : m[0];
      const protrude = pastEdge(edge, edge[1] === 'x' ? m[0] : m[1], at, W, H, poly);
      const z0 = lift + (s.z0 ?? 0);
      if (protrude >= -EDGE_MM) {
        comps.push(roundAll({
          id: `${ref}_${s.id}`, type: s.type, side: c.layer, access: 'port', edge, at, w: s.w, h: s.h, d: s.d, z0,
          protrude, plug: s.plug ?? null, ...(s.plugR != null ? { plugR: s.plugR } : {}), src: 'modules', verify, evidence: ev,
          note: `${mod.name} ${s.id}, z ${r2(z0)}-${r2(z0 + s.h)} over the carrier`,
        }));
        continue;
      }
      // facing the right way but deep inside the board: the case wall cannot reach it
      const inward = { '+x': [-1, 0], '-x': [1, 0], '+y': [0, -1], '-y': [0, 1] }[edge];
      comps.push(roundAll({
        id: `${ref}_${s.id}`, type: s.type, side: c.layer, access: 'none', x: m[0] + inward[0] * (s.d / 2), y: m[1] + inward[1] * (s.d / 2),
        w: edge[1] === 'y' ? s.w : s.d, d: edge[1] === 'y' ? s.d : s.w, z0, h: s.h, normal: [0, 0, 1], src: 'modules', verify, evidence: ev,
        note: `${mod.name} ${s.id} faces ${edge} but its mouth is ${r2(-protrude)} mm inside the board edge: not reachable through the case wall`,
      }));
      continue;
    }
    const [x, y] = place(s.x, s.y);
    comps.push(roundAll({
      id: `${ref}_${s.id}`, type: s.type, side: c.layer, access: s.access, x, y, w: swap ? s.d : s.w, d: swap ? s.w : s.d, z0: lift, h: s.h,
      normal: s.normal ?? [0, 0, 1], src: 'modules', verify, evidence: ev, ...(s.note ? { note: s.note } : {}),
    }));
  }
  for (const k of ds.keepouts ?? []) {
    const p0 = place(k.rect[0], k.rect[1]), p1 = place(k.rect[2], k.rect[3]);
    keepouts.push({ id: `${ref}_${k.id}`, rect: [Math.min(p0[0], p1[0]), Math.min(p0[1], p1[1]), Math.max(p0[0], p1[0]), Math.max(p0[1], p1[1])].map(r2), rule: k.rule, src: 'modules', ...(k.z ? { z: k.z } : {}) });
  }
  return { comps, keepouts };
}

/**
 * fw.board/1 for a routed circuit. opts: {id, name, job ('pcb:v3' once the version is saved)}.
 */
export function boardFromCircuit(cj, { id = 'pcb', name, job, lcsc = {} } = {}) {
  const { board, W, H, origin, poly } = boardFrame(cj);
  const fw = (x, y) => [x - origin[0], y - origin[1]];
  const fwBox = (b) => [b[0] - origin[0], b[1] - origin[1], b[2] - origin[0], b[3] - origin[1]];
  const parts = componentBoxes(cj);
  const refOf = Object.fromEntries(Object.values(parts).map((p) => [p.pc.pcb_component_id, p.ref]));

  const components = [];
  const keepouts = [];
  for (const c of Object.values(parts)) {
    const mod = c.mpn ? MODULES[c.mpn] : null;
    const center = fw(...c.center);
    if (mod) {
      const pins = cj.filter((e) => e.type === 'pcb_plated_hole' && e.pcb_component_id === c.pc.pcb_component_id).map((e) => fw(e.x, e.y));
      const m = expandModule(c, mod, center, W, H, pins, poly);
      components.push(...m.comps);
      keepouts.push(...m.keepouts);
      continue;
    }
    // a catalogue part (footprint 'lcsc:C123'): its height comes from the server, read off the part's 3D model name
    const cat = lcsc[String(c.footprint).replace(/^lcsc:/i, '').toUpperCase()] ?? lcsc[String(c.src.supplier_part_numbers?.jlcpcb?.[0] ?? '').toUpperCase()] ?? null;
    const rule = (cat ? { type: cat.type ?? 'chip', access: cat.access ?? 'none', h: cat.h ?? 2.0, unknown: cat.h == null } : null)
      ?? partRule(c.ftype, c.footprint) ?? { type: 'part', access: 'none', h: 2.0, unknown: true };
    const box = fwBox(c.box);
    const th = rule.typical ? typicalHeight(rule.typical) : null;
    const h = th ?? rule.h ?? 2.0;
    const verify = th != null || rule.unknown ? ['h'] : [];
    const ev = { ref: c.ref, footprint: c.footprint };
    if (rule.port) {
      const { edge, gap } = portEdge(rule, c.rotation, box, W, H, poly);
      if (gap <= EDGE_MM) {
        const p = portFields(box, edge, W, H, poly);
        components.push(roundAll({
          id: c.ref, type: rule.type, side: c.layer, access: 'port', edge, at: p.at, w: p.w, h, d: p.d, z0: 0, protrude: p.protrude,
          plug: TYPICAL[rule.typical]?.plug ?? null, src: 'circuit', verify, evidence: ev,
        }));
        continue;
      }
      components.push(roundAll({
        id: c.ref, type: rule.type, side: c.layer, access: rule.away ?? 'none', x: (box[0] + box[2]) / 2, y: (box[1] + box[3]) / 2,
        w: box[2] - box[0], d: box[3] - box[1], h, normal: [0, 0, c.layer === 'bottom' ? -1 : 1], src: 'circuit', verify, evidence: ev,
        note: `${r2(gap)} mm from the ${edge} edge: not an edge port`,
      }));
      continue;
    }
    components.push(roundAll({
      id: c.ref, type: rule.type, side: c.layer, access: rule.access, x: (box[0] + box[2]) / 2, y: (box[1] + box[3]) / 2,
      w: box[2] - box[0], d: box[3] - box[1], h, normal: [0, 0, c.layer === 'bottom' ? -1 : 1], src: 'circuit', verify, evidence: ev,
      ...(rule.unknown ? { note: `unknown part (${c.footprint || c.ftype}): default height, verify` } : {}),
    }));
  }

  const holes = [];
  for (const e of cj) {
    if (e.type === 'pcb_hole') {
      const [x, y] = fw(e.x, e.y);
      const d = e.hole_diameter ?? Math.max(e.hole_width ?? 0, e.hole_height ?? 0);
      if (!(d > 0)) continue;
      const ref = e.pcb_component_id ? refOf[e.pcb_component_id] : null;
      holes.push(ref ? { x: r2(x), y: r2(y), d, plated: false, use: 'tooling', src: 'circuit', note: `${ref} locating peg` }
        : { x: r2(x), y: r2(y), d, plated: false, use: 'mount', src: 'circuit' });
    } else if (e.type === 'pcb_plated_hole') {
      const [x, y] = fw(e.x, e.y);
      const slot = e.hole_width != null && e.hole_height != null;
      const d = slot ? Math.max(e.hole_width, e.hole_height) : e.hole_diameter;
      if (!(d > 0)) continue;
      holes.push({ x: r2(x), y: r2(y), d, plated: true, use: 'pin', src: 'circuit', ...(slot ? { note: `slot ${e.hole_width} x ${e.hole_height}` } : {}), ...(e.pcb_component_id ? { ref: refOf[e.pcb_component_id] } : {}) });
    }
  }

  const outline = Array.isArray(board.outline) && board.outline.length >= 3
    ? { kind: 'poly', points: board.outline.map((p) => fw(p.x, p.y).map(r2)), w: W, h: H, src: 'circuit' }
    : { kind: 'rect', w: W, h: H, r: board.border_radius ?? 0, src: 'circuit' };
  const tops = components.filter((c) => c.side !== 'bottom').map((c) => (c.z0 ?? 0) + c.h);
  const bottoms = components.filter((c) => c.side === 'bottom').map((c) => (c.z0 ?? 0) + c.h);
  const tht = holes.some((h) => h.plated);
  const mounts = holes.filter((h) => h.use === 'mount');
  const dMin = mounts.length ? Math.min(...mounts.map((h) => h.d)) : 0;
  const screw = dMin >= 3.1 ? 'M3' : dMin >= 2.6 ? 'M2.5' : dMin >= 2.1 ? 'M2' : null;
  return {
    schema: 'fw.board/1',
    id,
    name: name ?? 'PCB',
    aliases: [],
    frame: FRAME,
    source: { kind: 'pcb', ...(job ? { pcb_job: job } : {}) },
    sources: { circuit: 'circuit.json', typical: 'packages/geom/src/boards.json#typical', modules: 'packages/pcb/src/modules.json' },
    uncertainty_mm: 0,
    pcb: { outline, thickness: board.thickness, layers: board.num_layers, holes },
    components,
    keepouts,
    heights: {
      top_max: r2(Math.max(0, ...tops)),
      // soldered through-hole leads poke out under the board
      bottom_max: r2(Math.max(tht ? modulesData.tht_leads_below_mm : 0, ...bottoms)),
      verify: ['top_max', 'bottom_max'],
    },
    mount: mounts.length ? { preferred: 'screw', screw: screw ?? `d${dMin}`, holes: mounts.length } : { preferred: 'pocket_clip' },
  };
}
