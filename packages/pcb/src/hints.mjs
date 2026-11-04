// What the agent gets back from a build: root-cause errors first, each with a concrete hint, cascades collapsed.
// tscircuit hides rules that block routing for the whole board (a 100nF decoupling capacitor must sit within 1 mm,
// copper keeps 0.2 mm from non-plated pegs), and once routing is skipped every connection also reports "not
// connected"; without collapsing those the model chases 36 symptoms instead of the one cause.
import { componentBoxes } from './board.mjs';

const OFFLINE = '0402/0603/0805/1206 (resistor, capacitor, led), sod123, sot23, soic8, pushbutton, pinrow4 or <pinheader pinCount>, usbcmidmount (USB-C 16P), jst2, dip14_w15.24mm (XIAO on headers)';
const QUIET = new Set([
  'source_unnamed_trace_warning', 'source_refdes_convention_warning', 'source_missing_manufacturer_part_number_warning',
  'schematic_missing_sheet_warning', 'source_component_pins_underspecified_warning', 'source_no_power_pin_defined_warning',
  'source_no_ground_pin_defined_warning',
]);
const CASCADE = /^(pcb_port_not_connected_error|pcb_trace_missing_error)$/;
const MAX_ERRORS = 12;

const r2 = (v) => Math.round(v * 100) / 100;
const fmt = (v) => String(r2(v));

/** Port positions and net membership, by "U1.V3V3" style names, for hints that point at real coordinates. */
function portIndex(cj) {
  const comp = Object.fromEntries(cj.filter((e) => e.type === 'source_component').map((c) => [c.source_component_id, c.name]));
  const sp = Object.fromEntries(cj.filter((e) => e.type === 'source_port').map((p) => [p.source_port_id, p]));
  const pos = {};
  for (const p of cj.filter((e) => e.type === 'pcb_port')) {
    const s = sp[p.source_port_id];
    if (s) pos[`${comp[s.source_component_id]}.${s.name}`] = [p.x, p.y];
  }
  const labels = {};
  for (const s of Object.values(sp)) (labels[comp[s.source_component_id]] ??= []).push(s.name);
  return { pos, labels, names: Object.values(comp) };
}

function originOf(parts, ref) {
  const p = parts[ref];
  if (!p) return null;
  const o = p.pc.footprint_origin ?? p.pc.center;
  return [o.x, o.y];
}

function decouplingHint(m, cj, nets) {
  const [, , sel, , apart] = m;
  const cap = sel.match(/^\.(\w+) > \.(\w+)$/);
  const ix = portIndex(cj);
  const tips = [];
  if (cap && nets) {
    const ref = cap[1];
    const pins = (ix.labels[ref] ?? []).map((pin) => ({ pin, here: ix.pos[`${ref}.${pin}`], net: nets.portNet[`${ref}.${pin}`] })).filter((p) => p.here && p.net != null);
    // the part it decouples has a pin on each of the capacitor's nets (U1's V3V3 and GND); else the nearest pin per net
    const onNet = (net, part) => (nets.byId[net]?.ports ?? []).filter((p) => !p.startsWith(`${ref}.`) && ix.pos[p] && (!part || p.startsWith(`${part}.`)));
    const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
    const owners = pins.length === 2 ? [...new Set(onNet(pins[0].net).map((p) => p.split('.')[0]))].filter((x) => onNet(pins[1].net, x).length) : [];
    const score = (x) => pins.reduce((s, p) => s + Math.min(...onNet(p.net, x).map((q) => dist(ix.pos[q], p.here))), 0);
    const chip = (x) => ((ix.labels[x] ?? []).length > 4 ? 0 : 1); // an IC or module before a header that shares the nets
    const owner = owners.sort((a, b) => chip(a) - chip(b) || score(a) - score(b))[0] ?? null;
    for (const p of pins) {
      const best = onNet(p.net, owner).sort((a, b) => dist(ix.pos[a], p.here) - dist(ix.pos[b], p.here))[0];
      if (best) tips.push(`${ref}.${p.pin} within 1 mm of ${best} at (${fmt(ix.pos[best][0])}, ${fmt(ix.pos[best][1])})`);
    }
  }
  return `a 100nF capacitor between a supply net and GND counts as decoupling, so each of its traces must be <= 1 mm (now ${apart} mm). `
    + (tips.length ? `Place it so ${tips.join(' and ')}, ` : 'Place its pads right next to the pins it decouples, ')
    + 'or remove it (a module like the XIAO already decouples its own supply).';
}

function overlapHint(a, b, parts) {
  const A = parts[a], B = parts[b];
  if (!A || !B) return 'move the two parts apart until their courtyards no longer touch';
  // move the smaller of the two; the separating move is the shorter of the x and y overlaps plus a margin
  const area = (p) => (p.box[2] - p.box[0]) * (p.box[3] - p.box[1]);
  const [mov, fix] = area(A) <= area(B) ? [A, B] : [B, A];
  const ox = Math.min(mov.box[2], fix.box[2]) - Math.max(mov.box[0], fix.box[0]);
  const oy = Math.min(mov.box[3], fix.box[3]) - Math.max(mov.box[1], fix.box[1]);
  const sx = Math.sign(mov.center[0] - fix.center[0]) || 1, sy = Math.sign(mov.center[1] - fix.center[1]) || 1;
  const o = originOf(parts, mov.ref);
  const dx = sx * (ox + 0.3), dy = sy * (oy + 0.3);
  const opt = [];
  opt.push(`by ${dx > 0 ? '+' : ''}${fmt(dx)} mm in x (pcbX ${fmt(o[0])} -> ${fmt(o[0] + dx)})`);
  opt.push(`by ${dy > 0 ? '+' : ''}${fmt(dy)} mm in y (pcbY ${fmt(o[1])} -> ${fmt(o[1] + dy)})`);
  if (Math.abs(dy) < Math.abs(dx)) opt.reverse();
  return `courtyards of ${a} and ${b} overlap by ${fmt(ox)} x ${fmt(oy)} mm: move ${mov.ref} ${opt.join(' or ')}`;
}

/** A hint for one message (also for errors thrown before any Circuit JSON exists: cj and nets may be null). */
export function hintFor(type, message, cj = null, nets = null) {
  const msg = String(message ?? '');
  const parts = cj ? componentBoxes(cj) : {};
  let m;
  if ((m = msg.match(/([\d.]+)mm maximum length for (\.\S+ > \.\S+) to (.+?) cannot be satisfied: its endpoints are ([\d.]+)mm apart/))) {
    return decouplingHint([m[0], m[1], m[2], m[3], m[4]], cj ?? [], nets);
  }
  if ((m = msg.match(/Component (\S+) extends outside board boundaries by ([\d.]+)mm\. Try moving it ([\d.]+)mm (up|down|left|right)/))) {
    const [, ref, , dist, dir] = m;
    const o = originOf(parts, ref);
    const d = Number(dist) + 0.1;
    if (!o) return `move ${ref} ${dist} mm ${dir}`;
    const axis = dir === 'up' || dir === 'down' ? 'Y' : 'X';
    const sign = dir === 'up' || dir === 'right' ? 1 : -1;
    const cur = axis === 'X' ? o[0] : o[1];
    return `set ${ref} pcb${axis}={${fmt(cur + sign * d)}} (now ${fmt(cur)}; ${dist} mm ${dir} plus 0.1 mm margin) so its body stays on the board`;
  }
  if ((m = msg.match(/(\S+?)\.\S+ violates copper-to-board-edge clearance \(measured ([\d.]+)mm, required ([\d.]+)mm\)/))) {
    return `copper must stay ${m[3]} mm from the board edge: move ${m[1]} at least ${fmt(Number(m[3]) - Number(m[2]) + 0.1)} mm inward, or make the board larger`;
  }
  if ((m = msg.match(/^(\S+) overlaps (\S+):/) ?? msg.match(/Courtyard of (\S+) overlaps with courtyard of (\S+)/))) return overlapHint(m[1], m[2], parts);
  if (/too close to non-plated hole/.test(msg)) {
    return 'the router squeezed this trace past a non-plated peg (copper keeps >= 0.2 mm from it). Join the pin to its twin on the same part instead of a net (e.g. <trace from=".J1 > .VBUS_B" to=".J1 > .VBUS_A" />), or move the neighbouring parts 1-2 mm away to give the router room';
  }
  if ((m = msg.match(/Via hole at \(([-\d.]+)mm, ([-\d.]+)mm\) overlaps SMD pad (\w+)\./))) {
    return `the router dropped a via under ${m[3]}'s pad: move ${m[3]} about 1 mm away from its neighbours (routing is deterministic, so the layout has to change)`;
  }
  if (/external footprint|No footprint resolver|Invalid footprint/.test(msg)) {
    return `only offline footprint strings work here (no kicad:, jlcpcb: or standard=): ${OFFLINE}`;
  }
  if ((m = msg.match(/Component "\.(\w+) > " found, but does not have pin "([^"]+)"/))) {
    const labels = cj ? portIndex(cj).labels[m[1]] : null;
    return `${m[1]} has no pin "${m[2]}"` + (labels?.length ? `; its pins: ${[...new Set(labels)].join(', ')}` : '') + '. Selectors are .<name> > .<pin label or pinN>';
  }
  if ((m = msg.match(/Component "\.(\w+) > " not found/))) {
    const names = cj ? portIndex(cj).names : [];
    return `there is no part named ${m[1]}` + (names.length ? ` (parts: ${names.join(', ')})` : '') + '. Selectors are .<name> > .<pin label or pinN>';
  }
  if ((m = msg.match(/Net name "([^"]+)" cannot start with a number/))) {
    return `rename net.${m[1]}: a net name starts with a letter or underscore, e.g. net.V${m[1]} (as V3V3 for 3V3)`;
  }
  if (/Unable to pack all PCB components/.test(msg)) {
    return 'the parts without pcbX/pcbY did not fit around the placed ones and were left at the board\'s centre (the overlaps there follow from this): make the board larger or move the placed parts to leave room';
  }
  if (/Autorouting was skipped because \d+ PCB placement error/.test(msg)) {
    return 'routing runs once the placement errors in this list are fixed';
  }
  if (/routed thinner than requested/.test(msg)) {
    return 'a via or a neighbouring trace squeezed this trace on its way: move the parts beside its path 1-2 mm to give it room, or keep its two ends close so the path is short (the narrower width still carries ~0.5 A)';
  }
  if (/Prefer a multiple of 45/.test(msg)) return "cosmetic: the autorouter's own segment angle, nothing to change in the circuit";
  if ((m = msg.match(/^Port (\S+) on (\S+) is missing a trace/))) {
    const [, pin, ref] = m;
    const sw = parts[ref]?.ftype === 'simple_push_button';
    return sw
      ? `${ref} is a 4-leg switch whose legs pair up inside (pin1-pin2 and pin3-pin4 on the 6x6 footprint): wire the GPIO to pin1 and GND to pin3, and declare internallyConnectedPins={[["pin1", "pin2"], ["pin3", "pin4"]]} so ${pin} needs no trace`
      : `connect ${ref}.${pin} or remove the part: a pin left open is usually a forgotten trace`;
  }
  if ((m = msg.match(/^(\S+) is inferred to face ([xy][+-]).*?should face ([xy][+-])/))) {
    const deg = { 'x+': 0, 'y+': 90, 'x-': 180, 'y-': 270 };
    const turn = ((deg[m[3]] - deg[m[2]]) % 360 + 360) % 360;
    const o = parts[m[1]]?.rotation ?? 0;
    return `${m[1]} opens towards the board (${m[2]}), not out of its edge (${m[3]}): turn it by ${turn}° (pcbRotation ${r2(o)} -> ${r2((o + turn) % 360)}) so a plug can reach it`;
  }
  if (/imports are not allowed/.test(msg)) return 'drop the import lines: write one self-contained file, the circuit elements are built in';
  if (/must `export default/.test(msg)) return 'end the file with export default () => (<board width="..mm" height="..mm"> ... </board>)';
  if (/network is disabled/.test(msg)) return `nothing can be downloaded here; use offline footprint strings: ${OFFLINE}`;
  return null;
}

// A 6x6 through-hole tact switch has four legs but two contacts: the legs 6.5 mm apart are one metal strip, and the
// press joins the strips. tscircuit knows nothing of it, so GPIO on pin1 and GND on pin2 routes clean, passes DRC and the
// intent, and shorts the GPIO to GND on the real board; its only trace is "pin3/pin4 is missing a trace".
const SWITCH_FOOTPRINT = /^pushbutton/;

/** A 4-leg switch footprint's tied pairs from the leg positions: each leg's partner is the one at the middle distance (the
 * long side of the 6.5 x 4.5 mm rectangle; the short side is the switched pair, the diagonal the other strip). */
function tiedLegs(legs) {
  const d = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const pairs = new Map();
  for (const a of legs) {
    const [short, mid, long] = legs.filter((b) => b !== a).sort((p, q) => d(a, p) - d(a, q));
    if (!long || d(a, mid) - d(a, short) < 0.5 || d(a, long) - d(a, mid) < 0.5) return [];
    const key = [a.name, mid.name].sort().join('|');
    pairs.set(key, [a, mid].sort((p, q) => p.name.localeCompare(q.name, 'en', { numeric: true })));
  }
  return [...pairs.values()];
}

/** The nets as the traces state them: tscircuit's connectivity map already merges the pairs a part declares as
 * internallyConnectedPins, which would hide the very short this looks for. {of(sourcePortId) -> net id, members(id) -> {names, ports}}. */
function wiredNets(cj) {
  const up = new Map();
  const find = (x) => { while (up.has(x) && up.get(x) !== x) x = up.get(x); return x; };
  const join = (a, b) => { const ra = find(a), rb = find(b); if (ra !== rb) up.set(ra, rb); };
  for (const t of cj.filter((e) => e.type === 'source_trace')) {
    const ids = [...(t.connected_source_port_ids ?? []), ...(t.connected_source_net_ids ?? [])];
    for (const id of ids) if (!up.has(id)) up.set(id, id);
    for (let i = 1; i < ids.length; i++) join(ids[0], ids[i]);
  }
  const comp = Object.fromEntries(cj.filter((e) => e.type === 'source_component').map((c) => [c.source_component_id, c.name]));
  const portName = Object.fromEntries(cj.filter((e) => e.type === 'source_port').map((p) => [p.source_port_id, `${comp[p.source_component_id]}.${p.name}`]));
  const netName = Object.fromEntries(cj.filter((e) => e.type === 'source_net').map((n) => [n.source_net_id, n.name]));
  const members = new Map();
  for (const id of up.keys()) {
    const r = find(id);
    if (!members.has(r)) members.set(r, { names: [], ports: [] });
    if (netName[id]) members.get(r).names.push(netName[id]);
    else if (portName[id]) members.get(r).ports.push(portName[id]);
  }
  return {
    of: (portId) => (up.has(portId) ? find(portId) : null),
    members: (id) => members.get(id) ?? { names: [], ports: [] },
  };
}

/** pcb_button_short_error records for switches whose tied legs are wired to two different nets. */
export function buttonShorts(cj) {
  const parts = componentBoxes(cj);
  const sp = Object.fromEntries(cj.filter((e) => e.type === 'source_port').map((p) => [p.source_port_id, p]));
  const wired = wiredNets(cj);
  const label = (id, ref) => { const m = wired.members(id); return m.names[0] ?? (m.ports.filter((x) => !x.startsWith(`${ref}.`)).slice(0, 2).join('/') || '?'); };
  const ground = (id) => /^(GND|VSS)/i.test(label(id, ''));
  const out = [];
  for (const p of Object.values(parts)) {
    if (p.ftype !== 'simple_push_button' || !SWITCH_FOOTPRINT.test(p.footprint)) continue;
    const legs = cj.filter((e) => e.type === 'pcb_port' && e.pcb_component_id === p.pc.pcb_component_id && sp[e.source_port_id])
      .map((e) => ({ name: sp[e.source_port_id].name, id: e.source_port_id, x: e.x, y: e.y }));
    const tied = legs.length === 4 ? tiedLegs(legs) : [];
    if (tied.length !== 2) continue;
    for (const [i, [a, b]] of tied.entries()) {
      const na = wired.of(a.id), nb = wired.of(b.id);
      if (na == null || nb == null || na === nb) continue;
      // the ground side moves to the other contact: the GPIO on one strip, GND on the other
      const [keep, move, moved] = ground(na) && !ground(nb) ? [b, na, a] : [a, nb, b];
      const [c, d] = tied[1 - i];
      const m = wired.members(move);
      const q = m.ports.find((x) => !x.startsWith(`${p.ref}.`));
      const target = m.names[0] ? `net.${m.names[0]}` : q ? `.${q.replace('.', ' > .')}` : 'net.GND';
      out.push({
        type: 'pcb_button_short_error', pcb_component_ids: [p.pc.pcb_component_id],
        message: `${p.ref} ${a.name} and ${b.name} are one contact inside the switch (legs ${fmt(Math.hypot(a.x - b.x, a.y - b.y))} mm apart), so ${label(na, p.ref)} and ${label(nb, p.ref)} are shorted together`,
        hint: `keep ${label(move === na ? nb : na, p.ref)} on ${keep.name} and move ${label(move, p.ref)} from ${moved.name} to ${c.name} (the other contact; ${d.name} is tied to it): <trace from=".${p.ref} > .${c.name}" to="${target}" />. Declare internallyConnectedPins={[["${a.name}", "${b.name}"], ["${c.name}", "${d.name}"]]} so the free legs need no trace`,
      });
    }
  }
  return out;
}

/** A trace over its length limit (a decoupling capacitor's maxDecouplingTraceLength): the pads it runs between, the
 * connections it carries (the router merges a net's traces into one) and a hint naming them. */
function tooLong(e, cj) {
  const t = cj.find((x) => x.type === 'pcb_trace' && x.pcb_trace_id === e.pcb_trace_id);
  if (!t) return null;
  const comp = Object.fromEntries(cj.filter((x) => x.type === 'source_component').map((c) => [c.source_component_id, c.name]));
  const sp = Object.fromEntries(cj.filter((x) => x.type === 'source_port').map((p) => [p.source_port_id, p]));
  const pp = Object.fromEntries(cj.filter((x) => x.type === 'pcb_port').map((p) => [p.pcb_port_id, p]));
  const name = (pcbPortId) => { const s = sp[pp[pcbPortId]?.source_port_id]; return s ? `${comp[s.source_component_id]}.${s.name}` : null; };
  const ends = [...new Set((t.route ?? []).flatMap((p) => [p.start_pcb_port_id, p.end_pcb_port_id]).filter(Boolean).map(name).filter(Boolean))];
  const ids = String(e.pcb_trace_id ?? '').match(/source_trace_\d+/g) ?? [e.source_trace_id].filter(Boolean);
  const traces = [...new Set(ids)].map((id) => cj.find((x) => x.type === 'source_trace' && x.source_trace_id === id)?.display_name).filter(Boolean);
  const length = r2(e.actual_trace_length ?? NaN), max = r2(e.maximum_trace_length ?? NaN);
  const hint = `${ends.join(' to ') || 'a trace'} routed ${fmt(length)} mm against a ${fmt(max)} mm limit (it carries ${traces.join(', ') || 'a capacitor connection'}): `
    + 'a decoupling capacitor wants its chip close; place them together, or raise the capacitor\'s maxDecouplingTraceLength';
  return { ends, traces, length, max, hint };
}

function refsOf(e, cj) {
  const ids = e.pcb_component_ids ?? (e.pcb_component_id ? [e.pcb_component_id] : []);
  if (!ids.length) return null;
  const src = Object.fromEntries(cj.filter((x) => x.type === 'source_component').map((s) => [s.source_component_id, s.name]));
  const pc = Object.fromEntries(cj.filter((x) => x.type === 'pcb_component').map((p) => [p.pcb_component_id, src[p.source_component_id]]));
  return pc[ids[0]] ?? null;
}

// warnings a finished device cannot ship with: a connector that opens towards the board cannot take its plug
export const DEVICE_ERRORS = ['pcb_connector_not_in_accessible_orientation_warning'];

/**
 * Errors and warnings of a built circuit plus an independent DRC run: {errors, warnings, suppressed, quiet}.
 * suppressed: cascaded "not connected" errors (routing skipped) and errors past the first 12; quiet: noise warnings by type.
 * promote: warning types counted as errors (DEVICE_ERRORS for a device build).
 */
export function digest(cj, drc = [], nets = null, { promote = [] } = {}) {
  const seen = new Set();
  const all = [];
  for (const e of [...cj, ...drc, ...buttonShorts(cj)]) {
    if (!/_(error|warning)$/.test(e.type ?? '')) continue;
    const key = `${e.type}|${e.message}`;
    if (seen.has(key)) continue;
    seen.add(key);
    all.push(e);
  }
  const isError = (e) => e.type.endsWith('_error') || promote.includes(e.type);
  const errs = all.filter(isError);
  const skipped = errs.some((e) => e.type === 'pcb_autorouting_error');
  const root = errs.filter((e) => !(skipped && CASCADE.test(e.type)));
  let suppressed = errs.length - root.length;
  // root causes first: what blocks routing, then placement, then the rest
  // a packing that gave up leaves the free parts at the board's centre: every overlap there follows from it
  const rank = (e) => (e.type === 'pcb_packing_error' ? -1 : e.type === 'pcb_autorouting_error' ? 0 : /placement|outside|overlap|footprint|selector|source_/.test(e.type + e.message) ? 1 : 2);
  root.sort((a, b) => rank(a) - rank(b));
  const errors = root.slice(0, MAX_ERRORS).map((e) => {
    const ref = refsOf(e, cj);
    const long = e.type === 'pcb_trace_too_long_error' ? tooLong(e, cj) : null;
    return { type: e.type, message: e.message, hint: e.hint ?? long?.hint ?? hintFor(e.type, e.message, cj, nets), ...(ref ? { ref } : {}),
      ...(long ? { ends: long.ends, traces: long.traces, length: long.length, max: long.max } : {}) };
  });
  suppressed += Math.max(0, root.length - MAX_ERRORS);
  const quiet = {};
  const warnings = [];
  for (const e of all.filter((x) => x.type.endsWith('_warning') && !isError(x))) {
    if (QUIET.has(e.type)) { quiet[e.type] = (quiet[e.type] ?? 0) + 1; continue; }
    const hint = hintFor(e.type, e.message, cj, nets);
    warnings.push({ type: e.type, message: e.message, ...(hint ? { hint } : {}) });
  }
  return { errors, warnings, suppressed, quiet };
}
