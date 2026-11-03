// Client for devices (server/formwright/deviceapi.py): the device graph (fw.device/1) of a project, its build into a
// board, the LCSC catalogue, the quote and the order. Same origin and cookie session as $lib/api.
import { req } from '$lib/api';

export type Edge = '-x' | '+x' | '-y' | '+y';
export type DevNode = {
  id: string;
  kind: string;
  label?: string;
  value?: string;
  package?: string;
  color?: string;
  lcsc?: string;
  module?: string;
  pins?: string[];
  edge?: Edge;
  ui?: [number, number];
  /** Placed by hand on the board: centre in mm from the board's centre, +y up, rotation in degrees. */
  pcb?: { x: number; y: number; rot: number };
  note?: string;
};
export type DevNet = { name?: string; pins: string[] };
/** A trace drawn by hand: pad to pad as the board names them ('R3.pin1'), corners in mm from the board's centre. */
export type DevRoute = { from: string; to: string; layer: 'top' | 'bottom'; width: number; points: { x: number; y: number; via?: boolean }[] };
/** An area drawn on the board: a pour of a net (no rect: the whole board) or a keepout; rect [x0, y0, x1, y1] in mm. */
export type DevZone =
  | { kind: 'pour'; net: string; layer: 'top' | 'bottom'; rect?: [number, number, number, number] }
  | { kind: 'keepout'; layers: ('top' | 'bottom')[]; rect: [number, number, number, number] };
export type Firmware = { lang: string; files: Record<string, string>; notes?: string };
export type DeviceDoc = {
  schema: 'fw.device/1';
  title: string;
  summary?: string;
  board: { w?: number; h?: number; holes?: boolean };
  nodes: DevNode[];
  nets: DevNet[];
  routes?: DevRoute[];
  zones?: DevZone[];
  firmware?: Firmware;
};
export type PartBits = {
  lcsc?: string; mpn?: string; brand?: string; package?: string; category?: string; description?: string; stock?: number; basic?: boolean;
  datasheet?: string; image?: string; url?: string; size_mm?: [number, number]; height_mm?: number; error?: string; mcu?: string; wireless?: string[];
};
export type PinView = { name: string; net: string | null; count?: number };
export type NodeView = { pins: PinView[]; part: PartBits; price_usd: number | null };
export type Issue = { code: string; ref: string; msg: string };
export type DeviceState = {
  version: number | null;
  author: string | null;
  doc: DeviceDoc;
  view: { nodes: Record<string, NodeView>; power: string[]; groups?: Record<string, string[]> };
  issues: Issue[];
  lint: Issue[];
  building: boolean;
  pcb: { version: number; ok: boolean; device_version: number | null; intent_ok: boolean; stale: boolean } | null;
};
export type PartCard = PartBits & {
  lcsc: string;
  prices: { qty: number; usd: number }[];
  preferred?: boolean;
  pins?: { num: string; name: string; label: string }[];
};
export type Library = {
  modules: { module: string; name: string; mcu: string; pins: string[]; wireless: string[]; price_usd: number; size_mm: [number, number] }[];
  primitives: { kind: string; prefix: string; pins: string[] }[];
};
export type QuoteGroup = { key: string; usd: number; note: string; data?: Record<string, number | string> };
export type BomLine = {
  refs: string[]; kind: string; lcsc: string | null; mpn: string | null; package: string | null; basic: boolean | null; stock: number | null;
  url: string | null; assembly: 'smt' | 'hand'; label: string; qty_each: number; qty: number; unit_usd: number; total_usd: number; in_stock: boolean;
};
export type Quote = {
  qty: number; pcb_version: number; program_version: number | null; board_mm: [number, number]; usd_kzt: number;
  groups: QuoteGroup[]; bom: BomLine[]; total_usd: number; total_kzt: number; per_device_usd: number;
  timeline: { key: string; days: number; by: string }[]; eta: string; drc_ok: boolean; unverified: string[];
};
export type DeviceOrder = {
  id: string; ref: string; project_id: string; pcb_version: number | null; program_version: number | null; quantity: number; status: string;
  quote: Quote; timeline: Quote['timeline']; created_at: number; files: Record<string, string>;
};

const P = (id: string) => `/api/projects/${encodeURIComponent(id)}/device`;

export const deviceApi = {
  get: (id: string) => req<DeviceState>('GET', P(id)),
  put: (id: string, doc: DeviceDoc, summary = '') => req<DeviceState>('PUT', P(id), { doc, summary }),
  build: (id: string) => req<{ started: boolean; building?: boolean }>('POST', `${P(id)}/build`),
  quote: (id: string, qty: number) => req<Quote>('GET', `${P(id)}/quote?qty=${qty}`),
  order: (id: string, body: { qty: number; name?: string; contact?: string; city?: string; note?: string }) =>
    req<DeviceOrder>('POST', `${P(id)}/order`, body),
  orders: (id: string) => req<DeviceOrder[]>('GET', `${P(id)}/orders`),
  firmwareUrl: (id: string, name: string) => `${P(id)}/firmware/${encodeURIComponent(name)}`,
  library: () => req<Library>('GET', '/api/device/library'),
  search: (q: string, basic = false) => req<PartCard[]>('GET', `/api/catalog/search?q=${encodeURIComponent(q)}&basic=${basic}&limit=12`),
  part: (code: string) => req<PartCard>('GET', `/api/catalog/part/${encodeURIComponent(code)}`),
};

/** Unit price at a quantity from a card's price breaks. */
export function priceAt(prices: { qty: number; usd: number }[] | undefined, qty: number): number | null {
  if (!prices?.length) return null;
  let best = prices[0].usd;
  for (const p of [...prices].sort((a, b) => a.qty - b.qty)) if (p.qty <= qty) best = p.usd;
  return best;
}
