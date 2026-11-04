// Where the node editor draws parts the person has not placed: power inputs on the left, the microcontroller next,
// then the other chips, connectors on the right, and every passive next to the part it serves (the first part it shares
// a signal net with). A drawing only: the board's own placement comes from the build.
import type { DevNode, DeviceDoc, NodeView } from './api';
import { POWER_NET } from './store.svelte';

const W = 230;
const GAP = 34;
const ROW = 21;

export function nodeHeight(view: NodeView | undefined, node: DevNode): number {
  const n = view?.pins.length || (node.kind === 'header' ? node.pins?.length ?? 4 : node.kind === 'accessory' ? 4 : 2);
  const column = node.kind === 'header' || node.kind === 'accessory';
  const rows = ['resistor', 'capacitor', 'led', 'diode', 'button', 'jst'].includes(node.kind) ? 1 : column ? n : Math.ceil(n / 2);
  return 64 + rows * ROW + (node.label ? 16 : 0);
}

const PASSIVE = new Set(['resistor', 'capacitor', 'led', 'diode', 'button']);
const POWER_IN = new Set(['usb_c', 'jst']);

export function autoLayout(doc: DeviceDoc, views: Record<string, NodeView>): Record<string, [number, number]> {
  const nodes = doc.nodes.filter((n) => n.kind !== 'hole');
  const pinsOf = (id: string) => doc.nets.filter((net) => net.pins.some((p) => p.split('.')[0] === id));
  const neighbours = (id: string, signalOnly: boolean) => {
    const out: string[] = [];
    for (const net of pinsOf(id)) {
      if (signalOnly && POWER_NET.test(net.name ?? '')) continue;
      for (const p of net.pins) {
        const o = p.split('.')[0];
        if (o !== id && !out.includes(o)) out.push(o);
      }
    }
    return out;
  };
  const pinCount = (n: DevNode) => views[n.id]?.pins.length ?? 0;
  const mcus = nodes.filter((n) => n.kind === 'module');
  if (!mcus.length) {
    const chips = nodes.filter((n) => n.kind === 'chip').sort((a, b) => pinCount(b) - pinCount(a));
    if (chips[0]) mcus.push(chips[0]);
  }
  const cols: Record<number, DevNode[]> = { 0: [], 1: [], 2: [], 3: [], 4: [], 5: [] };
  const col: Record<string, number> = {};
  for (const n of nodes) {
    if (PASSIVE.has(n.kind)) continue;
    const c = POWER_IN.has(n.kind) ? 0 : mcus.includes(n) ? 2 : n.kind === 'chip' ? 3 : n.kind === 'header' || n.kind === 'accessory' ? 5 : 3;
    cols[c].push(n);
    col[n.id] = c;
  }
  // passives go one column right of what they serve (power-side ones to the right of the input)
  // what a passive serves: a chip before the module (which decouples itself), a signal neighbour before a supply one
  const kindOf = (id: string) => doc.nodes.find((x) => x.id === id)?.kind ?? '';
  const rank = (o: string, signal: boolean) => (kindOf(o) === 'chip' && !mcus.some((m) => m.id === o) ? 0 : 1) + (signal ? 0 : 2);
  const side = (anchor: string) => (col[anchor] === 2 || col[anchor] === 0 ? 1 : Math.min(5, col[anchor] + 1));
  const place = (n: DevNode, c: number) => {
    cols[c].push(n);
    col[n.id] = c;
  };
  const passives = nodes.filter((x) => PASSIVE.has(x.kind));
  // first the ones wired to a part by a signal; then chains of passives (an LED behind its resistor) follow theirs
  const later: DevNode[] = [];
  for (const n of passives) {
    const sig = neighbours(n.id, true).filter((o) => col[o] != null && !PASSIVE.has(kindOf(o))).sort((a, b) => rank(a, true) - rank(b, true));
    if (sig[0]) place(n, side(sig[0]));
    else later.push(n);
  }
  for (const n of later) {
    const via = neighbours(n.id, true).find((o) => PASSIVE.has(kindOf(o)) && col[o] != null);
    if (via) {
      place(n, col[via]);
      continue;
    }
    const pw = neighbours(n.id, false).filter((o) => col[o] != null && !PASSIVE.has(kindOf(o))).sort((a, b) => rank(a, false) - rank(b, false));
    place(n, pw[0] ? side(pw[0]) : 4);
  }
  const X = [-560, -280, 20, 330, 620, 900];
  const out: Record<string, [number, number]> = {};
  for (const [c, list] of Object.entries(cols)) {
    // keep each passive near its anchor's row: order by the anchor's index in its column
    let y = 0;
    for (const n of list) {
      out[n.id] = [X[Number(c)], y];
      y += nodeHeight(views[n.id], n) + GAP;
    }
    const mid = y / 2;
    for (const n of list) out[n.id] = [out[n.id][0], out[n.id][1] - mid];
  }
  return out;
}

export const NODE_W = W;
