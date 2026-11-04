// Where the node editor draws parts the person has not placed. The microcontroller first; what its left pins go to stands on
// its left, what its right pins go to on its right, and what those go to further out, so most wires run straight across.
// A part wired by supply nets only stands under the chip it serves; a power input goes on the far left, a module with no
// signal on the far right. Within a column parts follow the pins they connect to. A drawing only: the board's own
// placement comes from the build.
import type { DevNode, DeviceDoc, NodeView } from './api';
import { POWER_NET } from './store.svelte';

export const NODE_W = 240;
const COL_GAP = 140; // seven wire tracks between two columns (wires.ts)
const GAP = 60; // room for wires between two parts of a column
const ROW = 21;
const HEAD = 34;
const COL_MIN = -1;
const COL_MAX = 2;

/** How the view fits the schematic: readable before complete, with room to pan on a small stage. */
export const FIT = { padding: 0.05, maxZoom: 1, minZoom: 0.55 };

const TWO = new Set(['resistor', 'capacitor', 'led', 'diode', 'button', 'jst']);

export function nodeHeight(view: NodeView | undefined, node: DevNode): number {
  const n = view?.pins.length || (node.kind === 'header' ? node.pins?.length ?? 4 : node.kind === 'accessory' ? 4 : 2);
  const column = node.kind === 'header' || node.kind === 'accessory';
  const rows = TWO.has(node.kind) ? 1 : column ? n : Math.ceil(n / 2);
  return 62 + rows * ROW + (node.label ? 16 : 0);
}

/** A pin's place on its part: its side (-1 left, 1 right) and its height from the part's top. */
function pinAt(view: NodeView | undefined, node: DevNode, pin: string): { side: number; y: number } {
  const names = view?.pins.map((p) => p.name) ?? node.pins ?? [];
  const i = Math.max(0, names.indexOf(pin));
  const head = HEAD + (node.label ? 16 : 0);
  if (TWO.has(node.kind)) return { side: i === 0 ? -1 : 1, y: head + ROW / 2 };
  if (node.kind === 'header' || node.kind === 'accessory') return { side: -1, y: head + i * ROW + ROW / 2 };
  const half = Math.ceil(names.length / 2);
  return i < half ? { side: -1, y: head + i * ROW + ROW / 2 } : { side: 1, y: head + (names.length - 1 - i) * ROW + ROW / 2 };
}

/** The parts to draw mirrored, so their wired pins face what they are wired to, as a part is turned on a schematic sheet.
 *  `at` is where each part stands now. The microcontroller keeps its pinout's order. */
export function mirrored(doc: DeviceDoc, views: Record<string, NodeView>, at: Record<string, [number, number]>, withPower: boolean): Set<string> {
  const pull: Record<string, number> = {};
  const byId = new Map(doc.nodes.map((n) => [n.id, n]));
  for (const net of doc.nets) {
    if (!withPower && POWER_NET.test(net.name ?? '')) continue;
    const pins = net.pins.map((p) => ({ id: p.split('.')[0], pin: p.slice(p.indexOf('.') + 1) })).filter((p) => at[p.id]);
    for (const a of pins) {
      const others = pins.filter((b) => b.id !== a.id);
      if (!others.length) continue;
      const node = byId.get(a.id);
      if (!node) continue;
      const way = others.reduce((s, b) => s + at[b.id][0], 0) / others.length - at[a.id][0];
      pull[a.id] = (pull[a.id] ?? 0) + pinAt(views[a.id], node, a.pin).side * way;
    }
  }
  return new Set(doc.nodes.filter((n) => n.kind !== 'module' && (pull[n.id] ?? 0) < 0).map((n) => n.id));
}

export function autoLayout(doc: DeviceDoc, views: Record<string, NodeView>): Record<string, [number, number]> {
  const nodes = doc.nodes.filter((n) => n.kind !== 'hole');
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const signal = doc.nets.filter((net) => !POWER_NET.test(net.name ?? ''));
  const pinParts = (net: { pins: string[] }) => net.pins.map((p) => ({ id: p.split('.')[0], pin: p.slice(p.indexOf('.') + 1) })).filter((p) => byId.has(p.id));
  const pinCount = (n: DevNode) => views[n.id]?.pins.length ?? 0;
  const root = nodes.find((n) => n.kind === 'module') ?? [...nodes].filter((n) => n.kind === 'chip').sort((a, b) => pinCount(b) - pinCount(a))[0] ?? nodes[0];
  if (!root) return {};

  // ---- columns, walking the signal nets out from the root
  const col = new Map<string, number>([[root.id, 0]]);
  const clamp = (c: number) => Math.min(COL_MAX, Math.max(COL_MIN, c));
  const queue = [root.id];
  while (queue.length) {
    const u = queue.shift()!;
    const cu = col.get(u)!;
    for (const net of signal) {
      const parts = pinParts(net);
      const mine = parts.find((p) => p.id === u);
      if (!mine) continue;
      for (const o of parts) {
        if (col.has(o.id)) continue;
        const dir = u === root.id ? pinAt(views[u], byId.get(u)!, mine.pin).side : cu < 0 ? -1 : 1;
        col.set(o.id, clamp(cu + dir));
        queue.push(o.id);
      }
    }
  }
  // what no signal reaches: a power input far left, a decoupler under its chip, anything else far right
  const powerIn = new Set(['usb_c', 'jst']);
  const hosts = (n: DevNode) => doc.nets.filter((net) => net.pins.some((p) => p.startsWith(`${n.id}.`))).flatMap((net) => pinParts(net).map((p) => p.id)).filter((id) => id !== n.id);
  for (const n of nodes) {
    if (col.has(n.id)) continue;
    if (powerIn.has(n.kind)) col.set(n.id, COL_MIN);
    else if (n.kind === 'capacitor' || n.kind === 'resistor' || n.kind === 'diode') {
      const host = hosts(n).find((id) => byId.get(id)?.kind === 'chip' && col.has(id)) ?? hosts(n).find((id) => col.has(id));
      col.set(n.id, host ? col.get(host)! : COL_MAX);
    } else col.set(n.id, COL_MAX);
  }

  // ---- heights: each part towards the pins it connects to, then pushed apart
  const y = new Map<string, number>(nodes.map((n, i) => [n.id, i * 40]));
  y.set(root.id, 0);
  const columns = [...new Set(col.values())].sort((a, b) => Math.abs(a) - Math.abs(b));
  const height = (id: string) => nodeHeight(views[id], byId.get(id)!);
  const pull = (id: string): number | null => {
    const n = byId.get(id)!;
    const asked: number[] = [];
    for (const net of signal) {
      const parts = pinParts(net);
      const mine = parts.find((p) => p.id === id);
      if (!mine) continue;
      const own = pinAt(views[id], n, mine.pin).y;
      for (const o of parts) {
        if (o.id === id || col.get(o.id) === col.get(id)) continue;
        asked.push(y.get(o.id)! + pinAt(views[o.id], byId.get(o.id)!, o.pin).y - own);
      }
    }
    return asked.length ? asked.reduce((s, v) => s + v, 0) / asked.length : null;
  };
  for (let pass = 0; pass < 4; pass++) {
    for (const c of columns) {
      if (c === 0) continue;
      const list = nodes.filter((n) => col.get(n.id) === c).map((n) => n.id);
      const wanted = new Map(list.map((id) => [id, pull(id) ?? y.get(id)!]));
      list.sort((a, b) => wanted.get(a)! - wanted.get(b)!);
      let at = -Infinity;
      for (const id of list) {
        const v = Math.max(wanted.get(id)!, at);
        y.set(id, v);
        at = v + height(id) + GAP;
      }
      // the pushing moved the column down: back to where it asks to be on average
      const drift = list.reduce((s, id) => s + (y.get(id)! - wanted.get(id)!), 0) / list.length;
      for (const id of list) y.set(id, y.get(id)! - drift);
    }
  }
  // the middle column may hold more than the root: under it
  let under = height(root.id) + GAP;
  for (const n of nodes) {
    if (n.id !== root.id && col.get(n.id) === 0) {
      y.set(n.id, under);
      under += height(n.id) + GAP;
    }
  }

  const minCol = Math.min(...col.values());
  const out: Record<string, [number, number]> = {};
  for (const n of nodes) out[n.id] = [(col.get(n.id)! - minCol) * (NODE_W + COL_GAP), Math.round(y.get(n.id)!)];
  return out;
}
