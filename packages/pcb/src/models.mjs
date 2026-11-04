// What a part looks like in board.glb. The converter (circuit-json-to-gltf) draws what a cad_component names; the worker
// has no network, so every model arrives with the export:
//   - a catalogue part: EasyEDA's own OBJ, true millimetres, z = 0 on the board (the server sends the text and where the
//     footprint puts it: parts[ref].obj, at, rot),
//   - a module on headers: built here from its dataset entry (the can, the buttons, its USB-C where it really is, the real
//     board size), never the DIP its pin rows are soldered to,
//   - anything the server describes (parts[ref].prims: a key switch, an accessory, what the designer modelled itself),
//   - nothing known: a plain box of the footprint, parts[ref].h high.
// Primitive models are OBJ text too, so one path draws them all. Their frame: mm, the part's footprint origin, z = 0 on the
// board's top face, z up.
import { createHash } from 'node:crypto';
import boardsData from '../../geom/src/boards.json' with { type: 'json' };
import modulesData from './modules.json' with { type: 'json' };

const DATASET = Object.fromEntries((boardsData.boards ?? []).map((b) => [b.id, b]));
const SCHEME = 'fw-model://';
const SEGMENTS = 20;

const f3 = (v) => String(Math.round(v * 1000) / 1000);
const rgb = (hex) => {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex ?? ''));
  const n = m ? parseInt(m[1], 16) : 0x333333;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => (c / 255).toFixed(3)).join(' ');
};

/** The closed plan outline of a primitive, counter-clockwise: [[x, y], ...] around its own centre. */
function outlineOf(p) {
  const [w, d] = p.size;
  if (p.shape === 'cyl') {
    return Array.from({ length: SEGMENTS }, (_, i) => {
      const a = (2 * Math.PI * i) / SEGMENTS;
      return [(Math.cos(a) * w) / 2, (Math.sin(a) * d) / 2];
    });
  }
  const r = Math.min(Number(p.r) || 0, w / 2, d / 2);
  if (r <= 0) return [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]];
  const out = [];
  for (const [cx, cy, a0] of [[w / 2 - r, d / 2 - r, 0], [-w / 2 + r, d / 2 - r, 90], [-w / 2 + r, -d / 2 + r, 180], [w / 2 - r, -d / 2 + r, 270]]) {
    for (let i = 0; i <= 5; i++) {
      const a = ((a0 + i * 18) * Math.PI) / 180;
      out.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
    }
  }
  return out;
}

/**
 * [{shape: 'box' | 'cyl', at: [x, y, z] (centre in plan, z its bottom), size: [w, d, h], r? (a box's corner radius),
 * axis? ('y' | 'x': the outline stands up and h runs along that axis, a USB shell lying down), color: '#rrggbb', taper?
 * (the top's share of the bottom's plan)}] -> OBJ text.
 */
export function primsToObj(prims) {
  const lines = [];
  const colors = [...new Set(prims.map((p) => p.color ?? '#333333'))];
  colors.forEach((c, i) => lines.push(`newmtl m${i}`, `Ka ${rgb(c)}`, `Kd ${rgb(c)}`, 'Ks 0.2 0.2 0.2', 'endmtl'));
  let base = 1;
  for (const p of prims) {
    const ol = outlineOf(p), n = ol.length, h = p.size[2], t = p.taper ?? 1;
    const [ax, ay, az] = p.at;
    // a lying primitive: its outline is (across, up) and h runs along the axis, centred on `at` along it
    const put = p.axis === 'y' ? ([x, y, z]) => [ax + x, ay - h / 2 + z, az + p.size[1] / 2 + y]
      : p.axis === 'x' ? ([x, y, z]) => [ax - h / 2 + z, ay + x, az + p.size[1] / 2 + y]
        : ([x, y, z]) => [ax + x, ay + y, az + z];
    for (const z of [0, h]) {
      const s = z ? t : 1;
      for (const [x, y] of ol) lines.push(`v ${put([x * s, y * s, z]).map(f3).join(' ')}`);
    }
    lines.push(`usemtl m${colors.indexOf(p.color ?? '#333333')}`);
    // the axis 'x' frame keeps the handedness of plan + z, axis 'y' turns it over: its faces wind the other way
    const flip = p.axis === 'y';
    const face = (a, b, c) => lines.push(flip ? `f ${a} ${c} ${b}` : `f ${a} ${b} ${c}`);
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n;
      face(base + i, base + j, base + n + j);
      face(base + i, base + n + j, base + n + i);
    }
    for (let i = 1; i < n - 1; i++) {
      face(base, base + i + 1, base + i);
      face(base + n, base + n + i, base + n + i + 1);
    }
    base += 2 * n;
  }
  return lines.join('\n') + '\n';
}

const LOOK = {
  usb_c: '#c9ccd1', usb_micro_b: '#c9ccd1', shield: '#b9bdc4', ufl: '#d4af37', tact_3x4_smd: '#d6d8db', led_0603: '#f2f2ea', pin_header_2_54: '#1a1a1a',
};

/** A module on headers in the primitive frame: its board at its real size, its parts where the dataset has them. */
export function moduleModel(mod, width) {
  const ds = DATASET[mod.dataset_id];
  const [mw, mh] = mod.size;
  const [ox, oy] = mod.offset ?? [0, 0];
  const lift = mod.seat + mod.thickness;
  const local = (x, y) => [x - (mw / 2 + ox), y - (mh / 2 + oy)];
  const out = [{ shape: 'box', at: [0, 0, mod.seat], size: [mw, mh, mod.thickness], r: ds?.pcb?.outline?.r ?? 0.6, color: mod.pcb_color ?? '#1f6f3a' }];
  // the headers it stands on: plastic strips and the pins through them
  const half = Object.keys(mod.pinLabels ?? {}).length / 2;
  for (const sx of [-width / 2, width / 2]) {
    const len = half * 2.54;
    out.push({ shape: 'box', at: [sx, 0, 0], size: [2.5, len, mod.seat], color: '#1a1a1a' });
    for (let i = 0; i < half; i++) {
      out.push({ shape: 'box', at: [sx, ((half - 1) / 2 - i) * 2.54, 0], size: [0.64, 0.64, lift + 0.5], color: '#d4af37' });
    }
  }
  for (const s of [...(ds?.components ?? []), ...(mod.model_extra ?? [])]) {
    const color = s.color ?? LOOK[s.type] ?? '#2a2a2a';
    if (s.access === 'port' && s.edge) {
      const onY = s.edge[1] === 'y', sign = s.edge[0] === '+' ? 1 : -1;
      const mouth = onY ? (sign > 0 ? mh : 0) + sign * s.protrude : (sign > 0 ? mw : 0) + sign * s.protrude;
      const mid = mouth - (sign * s.d) / 2;
      const [x, y] = onY ? local(s.at, mid) : local(mid, s.at);
      const z = lift + (s.z0 ?? 0);
      const axis = onY ? 'y' : 'x';
      out.push({ shape: 'box', at: [x, y, z], size: [s.w, s.h, s.d], r: s.h / 2, axis, color });
      // the dark mouth with its tongue: what says 'a connector' at a glance
      const [mx, my] = onY ? local(s.at, mouth + sign * 0.02) : local(mouth + sign * 0.02, s.at);
      out.push({ shape: 'box', at: [mx, my, z + 0.25], size: [s.w - 0.5, s.h - 0.5, 0.06], r: (s.h - 0.5) / 2, axis, color: '#141414' });
      const [tx, ty] = onY ? local(s.at, mouth + sign * 0.04) : local(mouth + sign * 0.04, s.at);
      out.push({ shape: 'box', at: [tx, ty, z + s.h / 2 - 0.3], size: [s.w - 2.6, 0.6, 0.08], axis, color: '#d4af37' });
      continue;
    }
    if (!(s.h > 0)) continue;
    const [x, y] = local(s.x, s.y);
    out.push({ shape: s.type === 'ufl' ? 'cyl' : 'box', at: [x, y, lift + (s.z0 ?? 0)], size: [s.w, s.d ?? s.w, s.h], color });
    if (s.type === 'tact_3x4_smd') out.push({ shape: 'box', at: [x, y, lift + s.h], size: [s.w * 0.5, (s.d ?? s.w) * 0.5, 0.4], color: '#1a1a1a' });
  }
  return out;
}

const key = (text) => createHash('sha1').update(text).digest('hex').slice(0, 24);

/**
 * The circuit with every cad_component told its model, and the OBJ texts those links stand for.
 * models: {objs: {uuid: OBJ text}, parts: {ref: {prims?, obj?, at?, rot?, h?, color?}}} from the server.
 */
export function withModels(cj, models = {}) {
  const objs = { ...(models.objs ?? {}) };
  const asked = models.parts ?? {};
  const src = Object.fromEntries(cj.filter((e) => e.type === 'source_component').map((s) => [s.source_component_id, s]));
  const pcs = Object.fromEntries(cj.filter((e) => e.type === 'pcb_component').map((p) => [p.pcb_component_id, p]));
  const T = cj.find((e) => e.type === 'pcb_board')?.thickness ?? 1.4;
  const placed = (cad, pc, prims) => {
    const text = primsToObj(prims);
    const id = key(text);
    objs[id] = text;
    const { model_origin_alignment, anchor_alignment, footprinter_string, model_object_fit, size, show_as_bounding_box, ...rest } = cad;
    const at = pc.footprint_origin ?? pc.center;
    const z = (pc.layer === 'bottom' ? -1 : 1) * (T / 2);
    return { ...rest, ...(footprinter_string ? { fw_footprint: footprinter_string } : {}), model_obj_url: SCHEME + id, position: { x: at.x, y: at.y, z }, rotation: { x: 0, y: 0, z: pc.rotation ?? 0 }, model_origin_position: { x: 0, y: 0, z: 0 } };
  };
  const out = cj.map((e) => {
    if (e.type !== 'cad_component') return e;
    const pc = pcs[e.pcb_component_id], s = src[e.source_component_id] ?? {};
    if (!pc) return e;
    const ask = asked[s.name] ?? {};
    if (Array.isArray(ask.prims) && ask.prims.length) return placed(e, pc, ask.prims);
    const mod = s.manufacturer_part_number ? modulesData.modules[s.manufacturer_part_number] : null;
    if (mod) {
      const w = Number(/_w([\d.]+)mm/.exec(mod.footprint)?.[1]) || 15.24;
      return placed(e, pc, moduleModel(mod, w));
    }
    if (ask.obj && objs[ask.obj]) {
      const { model_origin_alignment, anchor_alignment, model_object_fit, size, show_as_bounding_box, ...rest } = e;
      const at = pc.footprint_origin ?? pc.center, r = ((pc.rotation ?? 0) * Math.PI) / 180;
      const [dx, dy, dz] = ask.at ?? [0, 0, 0], [rx, ry, rz] = ask.rot ?? [0, 0, 0];
      return { ...rest, model_obj_url: SCHEME + ask.obj, model_origin_position: { x: 0, y: 0, z: 0 },
        position: { x: at.x + dx * Math.cos(r) - dy * Math.sin(r), y: at.y + dx * Math.sin(r) + dy * Math.cos(r), z: T / 2 + dz }, rotation: { x: rx, y: ry, z: rz + (pc.rotation ?? 0) } };
    }
    if (e.footprinter_string) return e;
    if (s.ftype === 'simple_pin_header') {
      // a pin header has no model of its own but its holes say what it is: plastic over each, a pin through it
      const at = pc.footprint_origin ?? pc.center;
      const holes = cj.filter((h) => h.type === 'pcb_plated_hole' && h.pcb_component_id === e.pcb_component_id);
      const a = ((pc.rotation ?? 0) * Math.PI) / 180, c = Math.cos(a), si = Math.sin(a);
      const prims = holes.flatMap((h) => {
        const dx = h.x - at.x, dy = h.y - at.y, x = dx * c + dy * si, y = -dx * si + dy * c;
        return [{ shape: 'box', at: [x, y, 0], size: [2.5, 2.5, 2.5], color: '#1a1a1a' }, { shape: 'box', at: [x, y, 0], size: [0.64, 0.64, 8.5], color: '#d4af37' }];
      });
      if (prims.length) return placed(e, pc, prims);
    }
    // no model anywhere: the footprint as a block, so no part of the board is simply missing from its picture
    const w = Math.max(0.5, pc.width), d = Math.max(0.5, pc.height);
    const box = { shape: 'box', at: [pc.center.x - (pc.footprint_origin ?? pc.center).x, pc.center.y - (pc.footprint_origin ?? pc.center).y, 0], size: [w, d, ask.h ?? Math.min(2, Math.min(w, d))], color: ask.color ?? '#2b2b2b' };
    return placed(e, { ...pc, rotation: 0 }, [box]);
  });
  return { cj: out, objs };
}

/** Run fn with fetch answering fw-model:// from objs: the converter loads models through fetch, the sandbox has no network. */
export async function withModelFetch(objs, fn) {
  const real = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (!u.startsWith(SCHEME)) return real(url, init);
    const text = objs[u.slice(SCHEME.length).split(/[?#]/)[0]];
    return text == null ? new Response('', { status: 404 }) : new Response(text);
  };
  try {
    return await fn();
  } finally {
    globalThis.fetch = real;
  }
}
