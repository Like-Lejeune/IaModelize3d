// Client for devices (server/formwright/deviceapi.py): the device graph (fw.device/1) of a project, its build into a
// board, the LCSC catalogue, the quote and the order. Same origin and cookie session as $lib/api.
import { req } from '$lib/api';

export type Edge = '-x' | '+x' | '-y' | '+y';
/** What a part needs from the case above it (fw.device/1 node.face); absent: the server's default for its kind. */
export type Face = 'light' | 'sound' | 'sensor' | 'display' | 'none';
export type DevNode = {
  id: string;
  kind: string;
  label?: string;
  value?: string;
  package?: string;
  color?: string;
  lcsc?: string;
  module?: string;
  /** kind 'accessory': the key of a ready-made module in the library (an OLED, a soil probe, a LiPo), fitted by hand. */
  accessory?: string;
  pins?: string[];
  edge?: Edge;
  face?: Face;
  ui?: [number, number];
  /** Placed by hand on the board: centre in mm from the board's centre, +y up, rotation in degrees. */
  pcb?: { x: number; y: number; rot: number };
  /** Placed by the designer (the agent) where people see or touch it; the person's own `pcb` wins over it. */
  place?: { x: number; y: number; rot?: number };
  note?: string;
};
export type DevNet = { name?: string; pins: string[] };
/** A pattern the designer laid parts out in (the dice pips, a row of keys): expands to `place` for its nodes. */
export type DevLayout = { pattern: 'dice' | 'row' | 'column' | 'grid' | 'ring' | string; nodes: string[]; center?: [number, number]; pitch?: number; cols?: number; radius?: number; rot?: number };
/** What the device must do, written down by the designer before the parts, with the parts that serve each. */
export type DevRequirement = { id: string; text: string; parts?: string[]; firmware?: boolean };
/** One way the device could look and be used (server device_concept): the case's form, stance and mounting, the board. */
export type ConceptOption = {
  name: string; look?: string; panel?: string;
  form?: 'soft' | 'round' | 'box'; stance?: 'desk' | 'tilt' | 'upright' | 'wall' | 'hand' | 'auto';
  mounting?: 'none' | 'ears' | 'strap' | 'lanyard' | 'stake' | 'magnets' | 'contacts';
  board?: { shape?: 'rect' | 'rounded' | 'round'; w?: number; h?: number }; module_edge?: '+y' | '-y' | '+x' | '-x';
};
/** The designer's brainstorm before the parts: the uses, at least three options and the chosen one with why. */
export type DevConcept = { uses?: string[]; options?: ConceptOption[]; chosen?: string; why?: string };
/** A trace drawn by hand: pad to pad as the board names them ('R3.pin1'), corners in mm from the board's centre. */
export type DevRoute = { from: string; to: string; layer: 'top' | 'bottom'; width: number; points: { x: number; y: number; via?: boolean }[] };
/** An area drawn on the board: a pour of a net (no rect: the whole board) or a keepout; rect [x0, y0, x1, y1] in mm. */
export type DevZone =
  | { kind: 'pour'; net: string; layer: 'top' | 'bottom'; rect?: [number, number, number, number] }
  | { kind: 'keepout'; layers: ('top' | 'bottom')[]; rect: [number, number, number, number] };
/** One compiler diagnostic of the firmware (server firmware_check.check): file and line as written. */
export type FwDiag = { code?: string; file?: string; line?: number | null; msg: string; hint?: string };
/** The firmware compiled (or checked) on the server: ok, the tool that judged it, its errors and warnings. */
export type FwCheck = { ok: boolean; tool?: string; errors?: FwDiag[]; warnings?: FwDiag[] };
export type Firmware = { lang: string; files: Record<string, string>; notes?: string; check?: FwCheck | null };
export type DeviceDoc = {
  schema: 'fw.device/1';
  title: string;
  summary?: string;
  board: { w?: number; h?: number; holes?: boolean; shape?: 'rect' | 'rounded' | 'round'; r?: number };
  nodes: DevNode[];
  nets: DevNet[];
  routes?: DevRoute[];
  zones?: DevZone[];
  layouts?: DevLayout[];
  requirements?: DevRequirement[];
  concept?: DevConcept;
  firmware?: Firmware;
};
export type PartBits = {
  lcsc?: string; mpn?: string; brand?: string; package?: string; category?: string; description?: string; stock?: number; basic?: boolean;
  datasheet?: string; image?: string; url?: string; size_mm?: [number, number]; height_mm?: number; error?: string; mcu?: string; wireless?: string[];
  kind_hint?: string; current_ma?: number;
};
export type PinView = { name: string; net: string | null; count?: number };
/** face: what the case does over the part as the server resolved it (the node's own, or its kind's default). */
export type NodeView = { pins: PinView[]; part: PartBits; price_usd: number | null; face?: Face };
/** A design check: severity 'error' blocks a good board, 'warning' is for the designer to weigh (device_rules, lint). */
export type Issue = { code: string; ref: string; msg: string; severity?: 'error' | 'warning' | 'info'; hint?: string };
/** The device reviewer's verdict (agent/critic.py), as in the 'critic' event. */
export type Review = {
  verdict?: string; match_score?: number | null; version?: number; model?: string;
  issues?: { severity: string; text: string; text_user?: string; fix_hint?: string }[];
};
export type DeviceState = {
  version: number | null;
  author: string | null;
  doc: DeviceDoc;
  view: { nodes: Record<string, NodeView>; power: string[]; groups?: Record<string, string[]> };
  issues: Issue[];
  lint: Issue[];
  /** device_rules.check: electrical rules with a severity, when the server sends them apart from lint. */
  rules?: Issue[];
  /** The latest device review, when the server keeps it with the document. */
  review?: Review | null;
  building: boolean;
  pcb: { version: number; ok: boolean; device_version: number | null; intent_ok: boolean; stale: boolean; size_mm?: [number, number] | null } | null;
};
export type PartCard = PartBits & {
  lcsc: string;
  prices: { qty: number; usd: number }[];
  preferred?: boolean;
  pins?: { num: string; name: string; label: string }[];
};
/** A ready-made module the workshop fits by hand (server accessories.py ACCESSORIES): its pins in header order, how it
 *  connects to the carrier board, where it sits and how big it is. */
export type Accessory = {
  key: string; name: string; price_usd?: number; pins?: string[]; connect?: 'header' | 'jst' | 'wires' | 'module_bat' | string;
  mount?: 'board' | 'cable' | 'inside' | string; body?: [number, number, number]; window?: [number, number]; supply?: string; current_ma?: number;
  url?: string; note?: string; kind?: string; cable_d?: number;
};
export type Library = {
  modules: { module: string; name: string; mcu: string; pins: string[]; wireless: string[]; price_usd: number; size_mm: [number, number]; gpio?: Record<string, number>; strapping?: number[] }[];
  primitives: { kind: string; prefix: string; pins: string[] }[];
  /** A list, or the library's own map key → spec (older servers: absent). */
  accessories?: Accessory[] | Record<string, Omit<Accessory, 'key'>>;
};
export type QuoteGroup = { key: string; usd: number; note: string; data?: Record<string, number | string> };
export type BomLine = {
  refs: string[]; kind: string; lcsc: string | null; mpn: string | null; package: string | null; basic: boolean | null; stock: number | null;
  url: string | null; assembly: 'smt' | 'hand' | string; label: string; qty_each: number; qty: number; unit_usd: number; total_usd: number; in_stock: boolean;
  /** an accessory line: its library key and name ('modules' fitted by hand) */
  accessory?: string; name?: string; group?: string;
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
