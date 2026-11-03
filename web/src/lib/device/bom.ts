// The bill of materials read straight off the device graph and its part cards: one line per orderable part (an LCSC
// number, or a module), with designators, package, library class, stock and price. It exists as soon as the schematic
// does; the build adds the fab's own BOM file (bom.csv) next to it.
import type { DeviceState } from './api';

export type BomRow = {
  key: string;
  refs: string[];
  kind: string;
  part: string;
  role: string;
  pkg: string;
  lcsc: string | null;
  url: string | null;
  basic: boolean | null;
  stock: number | null;
  unit: number | null;
  qty: number;
  sum: number | null;
  hand: boolean;
};

const HAND = new Set(['button', 'header', 'jst', 'module']);
const ORDER = ['module', 'chip', 'usb_c', 'jst', 'header', 'button', 'led', 'diode', 'capacitor', 'resistor'];

export function bomOf(s: DeviceState | null): BomRow[] {
  if (!s) return [];
  const rows = new Map<string, BomRow>();
  for (const n of s.doc.nodes) {
    if (n.kind === 'hole') continue;
    const v = s.view.nodes[n.id];
    const p = v?.part ?? {};
    const key = p.lcsc ?? (n.kind === 'module' ? `module:${n.module}` : `${n.kind}:${n.value ?? ''}:${n.package ?? ''}:${n.color ?? ''}`);
    const row = rows.get(key) ?? {
      key, refs: [], kind: n.kind,
      part: p.mpn ?? (n.value ? `${n.value}` : n.kind),
      role: n.label ?? '',
      pkg: p.package ?? n.package ?? '',
      lcsc: p.lcsc ?? null, url: p.url ?? null, basic: p.basic ?? null, stock: p.stock ?? null,
      unit: v?.price_usd ?? null, qty: 0, sum: null, hand: HAND.has(n.kind),
    };
    row.refs.push(n.id);
    row.qty = row.refs.length;
    row.sum = row.unit != null ? row.unit * row.qty : null;
    if (row.role && n.label && row.role !== n.label) row.role = '';
    rows.set(key, row);
  }
  const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });
  return [...rows.values()]
    .map((r) => ({ ...r, refs: r.refs.sort(natural) }))
    .sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind) || natural(a.refs[0], b.refs[0]));
}

/** The same lines as a CSV in JLCPCB's assembly columns (Comment, Designator, Footprint, LCSC). */
export function bomCsv(rows: BomRow[]): string {
  const q = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const lines = ['Comment,Designator,Footprint,LCSC Part #,Quantity'];
  for (const r of rows) lines.push([q(r.part), q(r.refs.join(',')), q(r.pkg), r.lcsc ?? '', String(r.qty)].join(','));
  return lines.join('\n') + '\n';
}
