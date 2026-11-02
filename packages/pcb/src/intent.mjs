// Checks of what the design promised, which DRC cannot see: a board with 0 DRC errors can still hang its "status" LED
// on 3V3 or put the I2C header in the middle of the board. The model states its intent next to the circuit
//   export const meta = { intent: { edge: { J1: '-y', J2: '+x' }, gpio: { LED1: 'D10', SW1: 'D1' }, nets_max: 30 } }
// and the build checks it against the netlist (source-level connectivity, so it works before routing succeeds) and
// against the fw.board/1 description (edge ports). Plus the hard limits of this pipeline.
import { getSourcePortConnectivityMapFromCircuitJson } from 'circuit-json-to-connectivity-map';
import { EDGE_MM, MODULES, componentBoxes, boardFrame, partRule, rotateEdge } from './board.mjs';

export const LIMITS = { layers: 2, nets: 30, components: 40, size_mm: 100 };
const EDGE_NAMES = { left: '-x', right: '+x', top: '+y', bottom: '-y', '+x': '+x', '-x': '-x', '+y': '+y', '-y': '-y' };
const SUPPLY = /^(V?3V3|V3\.3|VCC|VDD|V?5V|V5|VBUS(_[AB])?|VIN|VUSB|VBAT|VSYS)$/i;
const GROUND = /^(GND(_[AB])?|VSS|SH\d)$/i;
const r2 = (v) => Math.round(v * 100) / 100;
const fmt = (v) => `${v > 0 ? '+' : ''}${r2(v)}`;

/** Nets with at least two ports: {nets: [{id, ports: ['U1.D1', ...], names: ['GND']}], portNet: {'U1.D1': id}, byId}. */
export function netsOf(cj) {
  const comp = Object.fromEntries(cj.filter((e) => e.type === 'source_component').map((c) => [c.source_component_id, c.name]));
  const port = Object.fromEntries(cj.filter((e) => e.type === 'source_port').map((p) => [p.source_port_id, `${comp[p.source_component_id]}.${p.name}`]));
  const netName = Object.fromEntries(cj.filter((e) => e.type === 'source_net').map((n) => [n.source_net_id, n.name]));
  const cm = getSourcePortConnectivityMapFromCircuitJson(cj);
  const nets = [];
  const portNet = {};
  const byId = {};
  for (const [id, members] of Object.entries(cm.netMap ?? {})) {
    const ports = members.filter((m) => port[m]).map((m) => port[m]);
    if (ports.length < 2) continue;
    const net = { id, ports, names: members.filter((m) => netName[m]).map((m) => netName[m]) };
    nets.push(net);
    byId[id] = net;
    for (const p of ports) portNet[p] = id;
  }
  return { nets, portNet, byId };
}

export function countsOf(cj, nets) {
  const n = (t) => cj.filter((e) => e.type === t).length;
  return { components: n('source_component'), nets: nets.nets.length, connections: n('source_trace'), traces: n('pcb_trace'), vias: n('pcb_via') };
}

export function checkLimits(cj, counts) {
  const b = cj.find((e) => e.type === 'pcb_board');
  const issues = [];
  const over = (code, value, limit, msg) => { if (value > limit) issues.push({ code, value, limit, msg }); };
  if (b) {
    over('too_many_layers', b.num_layers ?? 2, LIMITS.layers, `${b.num_layers} copper layers: this pipeline routes 2`);
    over('board_too_large', r2(Math.max(b.width, b.height)), LIMITS.size_mm, `board ${r2(b.width)} x ${r2(b.height)} mm: keep it within ${LIMITS.size_mm} x ${LIMITS.size_mm} mm (the cheap fab tier)`);
  }
  over('too_many_nets', counts.nets, LIMITS.nets, `${counts.nets} nets: carrier boards here stay within ${LIMITS.nets}`);
  over('too_many_components', counts.components, LIMITS.components, `${counts.components} parts: keep it within ${LIMITS.components}`);
  return { ok: issues.length === 0, issues, limits: LIMITS };
}

// Every pin of a part that answers to `label`: its own name, a pinN alias, or a module alias (D10 = MOSI = GPIO10).
function pinsNamed(cj, label) {
  const [onlyRef, want] = label.includes('.') ? label.split('.', 2) : [null, label];
  const comp = Object.fromEntries(cj.filter((e) => e.type === 'source_component').map((c) => [c.source_component_id, c]));
  const hits = [];
  for (const p of cj.filter((e) => e.type === 'source_port')) {
    const c = comp[p.source_component_id];
    if (!c || (onlyRef && c.name !== onlyRef)) continue;
    const mod = c.manufacturer_part_number ? MODULES[c.manufacturer_part_number] : null;
    const names = new Set([p.name, ...(p.port_hints ?? []), ...(mod?.aliases?.[p.name] ?? [])].map((s) => String(s).toUpperCase()));
    if (names.has(String(want).toUpperCase())) hits.push(`${c.name}.${p.name}`);
  }
  return hits;
}

function gpioCheck(cj, nets, ref, label) {
  const comps = Object.fromEntries(cj.filter((e) => e.type === 'source_component').map((c) => [c.name, c]));
  if (!comps[ref]) return { code: 'intent_unknown_part', ref, msg: `intent names ${ref}, but the circuit has no such part` };
  const targets = pinsNamed(cj, label).filter((p) => !p.startsWith(`${ref}.`));
  if (!targets.length) return { code: 'intent_unknown_pin', ref, msg: `intent says ${ref} is on ${label}, but no part has a pin called ${label}` };
  const targetNets = new Set(targets.map((t) => nets.portNet[t]).filter((x) => x != null));
  const own = Object.entries(nets.portNet).filter(([p]) => p.startsWith(`${ref}.`)).map(([, n]) => n);
  if (own.some((n) => targetNets.has(n))) return null;
  // through one two-pin part in series (the LED's resistor)
  const pinsOf = {};
  for (const [p, n] of Object.entries(nets.portNet)) (pinsOf[p.split('.')[0]] ??= []).push([p, n]);
  const isGround = (id) => (nets.byId[id]?.names ?? []).some((x) => GROUND.test(x)) || (nets.byId[id]?.ports ?? []).some((p) => GROUND.test(p.split('.')[1]));
  const via = [];
  for (const n of own.filter((x) => !isGround(x))) {
    for (const [other, pins] of Object.entries(pinsOf)) {
      if (other === ref) continue;
      const total = cj.filter((e) => e.type === 'source_port' && e.source_component_id === comps[other]?.source_component_id).length;
      if (total !== 2 || pins.length !== 2) continue;
      const i = pins.findIndex(([, pn]) => pn === n);
      if (i < 0) continue;
      const far = pins[1 - i][1];
      if (targetNets.has(far)) return null;
      via.push({ through: other, net: far });
    }
  }
  const describe = (id) => {
    const net = nets.byId[id];
    if (!net) return null;
    const named = net.names[0] ?? net.ports.map((p) => p.split('.')[1]).find((x) => SUPPLY.test(x) || GROUND.test(x));
    return named ?? net.ports.filter((p) => !p.startsWith(`${ref}.`)).slice(0, 3).join('/');
  };
  // the LED's own side of its resistor and its ground return say nothing; where the far ends go does
  const series = new Set(via.map((v) => own.find((n) => (pinsOf[v.through] ?? []).some(([, pn]) => pn === n))));
  const direct = own.filter((n) => !series.has(n) && !isGround(n));
  const reach = [...new Set([...direct.map(describe), ...via.map((v) => { const d = describe(v.net); return d ? `${d} (through ${v.through})` : null; })].filter(Boolean))];
  const onSupply = reach.some((r) => SUPPLY.test(r.split(' ')[0]));
  return {
    code: onSupply ? 'intent_gpio_on_supply' : 'intent_gpio_missing', ref,
    msg: `${ref} should be driven by ${label}, but it reaches ${reach.join(', ') || 'nothing'}`,
    hint: `wire ${ref} (through its series resistor, if any) to .${targets[0].replace('.', ' > .')} instead${onSupply ? ' of the supply: on a supply it is always on and the firmware cannot switch it' : ''}`,
  };
}

function edgeCheck(cj, board, ref, want) {
  const edge = EDGE_NAMES[want];
  if (!edge) return { code: 'intent_bad_edge', ref, msg: `intent edge for ${ref} is "${want}": use -x, +x, -y, +y (or left, right, bottom, top)` };
  const ports = (board?.components ?? []).filter((c) => (c.id === ref || c.id.startsWith(`${ref}_`)) && c.access === 'port');
  if (ports.some((p) => p.edge === edge)) return null;
  const parts = componentBoxes(cj);
  const part = parts[ref];
  if (!part) return { code: 'intent_unknown_part', ref, msg: `intent names ${ref}, but the circuit has no such part` };
  if (ports.length) {
    return { code: 'intent_wrong_edge', ref, msg: `${ref} is on the ${ports[0].edge} edge, the intent says ${edge}`, hint: `move ${ref} to the ${edge} edge or change the intent` };
  }
  const { W, H, origin } = boardFrame(cj);
  const box = [part.box[0] - origin[0], part.box[1] - origin[1], part.box[2] - origin[0], part.box[3] - origin[1]];
  const rule = partRule(part.ftype, part.footprint);
  const gaps = { '-x': box[0], '+x': W - box[2], '-y': box[1], '+y': H - box[3] };
  const faces = rule?.faces ? rotateEdge(rule.faces, part.rotation) : null;
  const turn = faces && faces !== edge ? `pcbRotation={${[0, 90, 180, 270].find((r) => rotateEdge(rule.faces, r) === edge)}}` : null;
  if (gaps[edge] <= EDGE_MM && turn) {
    return { code: 'intent_wrong_facing', ref, msg: `${ref} is at the ${edge} edge but its opening faces ${faces}`, hint: `turn it with ${turn} (then check it still fits the board)` };
  }
  // a part with no opening of its own (a Pico placed as dip40) only has to sit at that edge: it never becomes a port, so
  // asking for one would chase it forever with 'move by -0.2 mm'. A module is still judged by its own port (U1_usb).
  if (gaps[edge] <= EDGE_MM && !rule?.port && !(part.mpn && MODULES[part.mpn])) return null;
  const shift = gaps[edge] - 0.3; // leave the body 0.3 mm inside the edge
  const o = part.pc.footprint_origin ?? part.pc.center;
  const axis = edge[1] === 'x' ? 'X' : 'Y';
  const sign = edge[0] === '+' ? 1 : -1;
  const cur = axis === 'X' ? o.x : o.y;
  let hint = `move ${ref} by ${fmt(sign * shift)} mm in ${axis.toLowerCase()} (pcb${axis} ${r2(cur)} -> ${r2(cur + sign * shift)}) so its body is within 1 mm of the ${edge} edge`;
  if (turn) hint += `, and turn it to face that edge (${turn}; now it faces ${faces})`;
  return { code: 'intent_not_at_edge', ref, value: r2(gaps[edge]), msg: `${ref} should sit on the ${edge} edge, but its body is ${r2(gaps[edge])} mm from it`, hint };
}

/** intent: {edge: {ref: edge}, gpio: {ref: pin label}, nets_max} -> {ok, issues, checked}. */
export function checkIntent(cj, board, nets, counts, intent) {
  const issues = [];
  let checked = 0;
  if (!intent || typeof intent !== 'object') return { ok: true, issues, checked };
  for (const [ref, want] of Object.entries(intent.edge ?? {})) {
    checked++;
    const i = edgeCheck(cj, board, ref, String(want));
    if (i) issues.push(i);
  }
  for (const [ref, label] of Object.entries(intent.gpio ?? {})) {
    checked++;
    const i = gpioCheck(cj, nets, ref, String(label));
    if (i) issues.push(i);
  }
  if (Number.isFinite(intent.nets_max)) {
    checked++;
    if (counts.nets > intent.nets_max) issues.push({ code: 'intent_too_many_nets', value: counts.nets, msg: `${counts.nets} nets, the intent allows ${intent.nets_max}` });
  }
  return { ok: issues.length === 0, issues, checked };
}
