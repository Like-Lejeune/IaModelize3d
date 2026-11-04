// Client for /api/shop (Formwright Parts). Same origin and cookie session as $lib/api, with the shop's own error codes.
import { ApiError, errorText, req as apiReq } from '$lib/api';
import { st } from './i18n';
import type { DeliveryMethod, Listing, OpsQueue, Order, Quote, ShopMe, ShopPrinter, ShowcaseCard, Tariff } from './types';

/** One order intent's Idempotency-Key: a repeat of the same POST (a lost answer, a second click) returns the same order. */
export const intentKey = (): string => crypto.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;

async function req<T>(method: string, path: string, body?: unknown, key?: string): Promise<T> {
  // the headers given here are all the request gets: the JSON type goes along with the key
  const init = key ? { headers: { ...(body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), 'Idempotency-Key': key } } : {};
  const out = await apiReq<T>(method, `/api/shop${path}`, body, init);
  // the shop answers JSON only: anything else is a proxy's page, not an answer
  if (out instanceof Blob) throw new ApiError(502, 'not a JSON answer', 'offline');
  return out;
}

const qs = (o: Record<string, string | number | boolean | undefined | null>) =>
  Object.entries(o)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&');

let meCache: { at: number; p: Promise<ShopMe> } | null = null;

export interface RequestForm {
  text?: string;
  appliance?: string;
  part_number?: string;
  quantity?: number | null;
  material?: string | null;
  delivery: DeliveryMethod;
  contact?: string;
  project_id?: string | null;
  files?: File[];
  plate?: File | null;
  voice?: Blob | null;
}

export const shop = {
  /** Who is asking (operator or not), cached for a minute: the header and every shop page ask. */
  me: (fresh = false): Promise<ShopMe> => {
    if (fresh || !meCache || Date.now() - meCache.at > 60000) {
      const p = req<ShopMe>('GET', '/me');
      meCache = { at: Date.now(), p };
      p.catch(() => (meCache = null));
    }
    return meCache.p;
  },
  tariff: () => req<Tariff>('GET', '/tariff'),

  request: (f: RequestForm, key?: string) => {
    const fd = new FormData();
    for (const k of ['text', 'appliance', 'part_number', 'contact', 'material', 'project_id'] as const) if (f[k]) fd.append(k, String(f[k]));
    if (f.quantity) fd.append('quantity', String(f.quantity));
    fd.append('delivery', f.delivery);
    for (const file of f.files ?? []) fd.append('files', file, file.name);
    if (f.plate) fd.append('plate', f.plate, f.plate.name);
    if (f.voice) {
      const ext = f.voice.type.includes('ogg') ? 'ogg' : f.voice.type.includes('mp4') ? 'm4a' : f.voice.type.includes('wav') ? 'wav' : 'webm';
      fd.append('voice', f.voice, `voice.${ext}`);
    }
    return req<Order>('POST', '/requests', fd, key);
  },
  instantQuote: (projectId: string, o: { quantity?: number; material?: string; delivery?: DeliveryMethod } = {}) =>
    req<Quote>('GET', `/instant-quote/${encodeURIComponent(projectId)}?${qs(o)}`),

  orders: () => req<Order[]>('GET', '/orders'),
  order: (id: string) => req<Order>('GET', `/orders/${id}`),
  /** view 'ops': the farm's board asks, so an operator's own order still comes back as the farm's card. */
  requote: (
    id: string,
    body: { material?: string; quantity?: number; delivery?: DeliveryMethod; printer_id?: string; grams_each?: number; minutes_each?: number },
    view?: 'ops',
  ) => req<Order>('POST', `/orders/${id}/quote${view ? `?view=${view}` : ''}`, body),
  pay: (id: string) => req<Order>('POST', `/orders/${id}/pay`),
  cancel: (id: string) => req<Order>('POST', `/orders/${id}/cancel`),
  answer: (id: string, text: string) => req<Order>('POST', `/orders/${id}/answer`, { text }),
  delivered: (id: string, view?: 'ops') => req<Order>('POST', `/orders/${id}/delivered${view ? `?view=${view}` : ''}`),

  // the farm operator (403 not_operator for everyone else)
  queue: () => req<OpsQueue>('GET', '/ops/queue'),
  addPrinter: (body: { name: string; preset_id?: string; material: string; color?: string }) => req<ShopPrinter>('POST', '/ops/printers', body),
  updatePrinter: (id: string, body: { name?: string; material?: string; color?: string; state?: ShopPrinter['state'] }) =>
    req<ShopPrinter>('POST', `/ops/printers/${id}`, body),
  fingerprint: (id: string, file: File) => {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return req<ShopPrinter>('POST', `/ops/printers/${id}/fingerprint`, fd);
  },
  /** quantity / material: what the operator read in a request the intake could not (written into it before the design). */
  review: (id: string, body: { action: 'approve' | 'refuse'; note?: string; tolerance_mm?: number; quantity?: number; material?: string }) =>
    req<Order>('POST', `/orders/${id}/review`, body),
  assign: (id: string, printerId: string) => req<Order>('POST', `/orders/${id}/assign`, { printer_id: printerId }),
  printed: (id: string) => req<Order>('POST', `/orders/${id}/printed`),
  qc: (id: string, file: File) => {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return req<Order>('POST', `/orders/${id}/qc`, fd);
  },
  reprint: (id: string, note = '') => req<Order>('POST', `/orders/${id}/reprint`, { note }),
  ship: (id: string, body: { carrier: string; tracking: string }) => req<Order>('POST', `/orders/${id}/ship`, body),
  flag: (listingId: string, flagged: boolean) => req<Listing>('POST', `/ops/listings/${listingId}/flag`, { flagged }),
  /** Show a shipped or delivered order to anyone, without the customer's data (or stop). */
  showcase: (id: string, on: boolean) => req<Order>('POST', `/orders/${id}/showcase`, { on }),
  /** The newest order the farm shows to anyone, or null. */
  showcaseLatest: () => req<ShowcaseCard | null>('GET', '/showcase'),

  // the catalog
  listings: (q = '') => req<Listing[]>('GET', `/listings?${qs({ q })}`),
  myListings: () => req<Listing[]>('GET', '/listings?mine=true'),
  listing: (id: string) => req<Listing>('GET', `/listings/${id}`),
  listingQuote: (id: string, o: { quantity?: number; delivery?: DeliveryMethod } = {}) => req<Quote>('GET', `/listings/${id}/quote?${qs(o)}`),
  share: (body: { project_id: string; title?: string; brand?: string; models?: string[]; part_numbers?: string[]; public?: boolean }) =>
    req<Listing>('POST', '/listings', body),
  orderListing: (id: string, body: { quantity: number; delivery: DeliveryMethod; contact?: string }, key?: string) =>
    req<Order>('POST', `/listings/${id}/order`, body, key),
  report: (id: string, reason: string) => req<{ ok: boolean; flagged: boolean }>('POST', `/listings/${id}/report`, { reason }),

  createOrg: (body: { name: string; contact?: string }) => req<ShopMe['org']>('POST', '/orgs', body),
};

// the shop's error codes (shop/routes.py) in the UI language; the rest goes through $lib/api's errorText
const SHOP_CODES: Record<string, string> = {
  order_bad_move: 'err.bad_move',
  order_guard: 'err.guard',
  order_conflict: 'err.conflict',
  order_forbidden: 'err.forbidden',
  forbidden: 'err.forbidden',
  not_operator: 'err.not_operator',
  not_verified: 'err.not_verified',
  no_model: 'err.no_model',
  no_estimate: 'err.no_estimate',
  bad_material: 'err.bad_material',
  slice_failed: 'err.slice_failed',
  quote_expired: 'err.quote_expired',
  no_question: 'err.no_question',
  empty_request: 'err.empty_request',
  printer_busy: 'err.printer_busy',
  org_exists: 'err.org_exists',
  fingerprint_failed: 'err.fingerprint_failed',
  bad_preset: 'err.bad_preset',
  too_many_reports: 'err.too_many_reports',
  safety_pending: 'err.safety_pending',
  price_updating: 'err.price_updating',
  material_pending: 'err.material_pending',
  held: 'err.held',
  not_delivered: 'err.not_delivered',
  too_many_orders: 'err.too_many_orders',
  too_many_pieces: 'err.too_many_pieces',
};

/** A shop error in the UI language; a refused move keeps the server's reason (it names what is missing). */
export function shopError(e: unknown): string {
  if (e instanceof ApiError && e.code && SHOP_CODES[e.code]) {
    const text = st(SHOP_CODES[e.code]);
    return ['order_guard', 'order_bad_move', 'slice_failed', 'fingerprint_failed'].includes(e.code) && e.message ? `${text}: ${e.message}` : text;
  }
  if (e instanceof ApiError && e.status === 403 && !e.code) return st('err.forbidden');
  if (e instanceof ApiError && e.status === 404 && !e.code) return st('err.not_found');
  return errorText(e);
}
