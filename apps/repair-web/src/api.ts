// A thin client for /api/shop. The session is a cookie the API sets on the first call (an anonymous customer until
// they sign in), so every request goes out with credentials. Errors come back as {detail, code}.
import type { Board, Delivery, Material, Me, Order, PayMethod, Printer, Tariff } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/shop${path}`, { credentials: "same-origin", ...init });
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  if (!res.ok) {
    // FastAPI wraps our {detail, code} in its own {detail: ...}
    const inner = body?.detail && typeof body.detail === "object" ? body.detail : body;
    const detail = typeof inner?.detail === "string" ? inner.detail : typeof body?.detail === "string" ? body.detail : res.statusText;
    throw new ApiError(res.status, inner?.code ?? `http_${res.status}`, detail);
  }
  return body as T;
}

function safeJson(text: string): any {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

const json = (data: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data ?? {}),
});

export interface NewRequest {
  text: string;
  appliance: string;
  partNumber: string;
  quantity: number | null;
  material: Material | null;
  delivery: Delivery;
  contact: string;
  photos: File[];
  plate: File | null;
}

export const api = {
  me: () => call<Me>("/me"),
  tariff: () => call<Tariff>("/tariff"),
  orders: () => call<Order[]>("/orders"),
  order: (id: string) => call<Order>(`/orders/${id}`),

  createRequest(r: NewRequest, idempotencyKey: string) {
    const form = new FormData();
    form.set("text", r.text);
    form.set("appliance", r.appliance);
    form.set("part_number", r.partNumber);
    if (r.quantity) form.set("quantity", String(r.quantity));
    if (r.material) form.set("material", r.material);
    form.set("delivery", r.delivery);
    form.set("contact", r.contact);
    r.photos.forEach((f) => form.append("files", f, f.name));
    if (r.plate) form.set("plate", r.plate, r.plate.name);
    return call<Order>("/requests", { method: "POST", body: form, headers: { "Idempotency-Key": idempotencyKey } });
  },

  requote: (id: string, body: { material?: Material; quantity?: number; delivery?: Delivery }) =>
    call<Order>(`/orders/${id}/quote`, json(body)),
  pay: (id: string, body: { method: PayMethod; operator?: "mtn" | "orange"; reference?: string }) =>
    call<Order>(`/orders/${id}/pay`, json(body)),
  answer: (id: string, text: string) => call<Order>(`/orders/${id}/answer`, json({ text })),
  cancel: (id: string) => call<Order>(`/orders/${id}/cancel`, { method: "POST" }),
  received: (id: string) => call<Order>(`/orders/${id}/delivered`, { method: "POST" }),

  // the workshop
  board: () => call<Board>("/ops/queue"),
  addPrinter: (name: string, material: Material) => call<Printer>("/ops/printers", json({ name, material })),
  review: (id: string, action: "approve" | "refuse", note = "") => call<Order>(`/orders/${id}/review`, json({ action, note })),
  verifyPayment: (id: string) => call<Order>(`/orders/${id}/payment-verified`, { method: "POST" }),
  assign: (id: string, printerId: string) => call<Order>(`/orders/${id}/assign`, json({ printer_id: printerId })),
  printed: (id: string) => call<Order>(`/orders/${id}/printed`, { method: "POST" }),
  qc(id: string, photo: File) {
    const form = new FormData();
    form.set("file", photo, photo.name);
    return call<Order>(`/orders/${id}/qc`, { method: "POST", body: form });
  },
  reprint: (id: string, note: string) => call<Order>(`/orders/${id}/reprint`, json({ note })),
  ship: (id: string, carrier: string, tracking: string) => call<Order>(`/orders/${id}/ship`, json({ carrier, tracking })),
  opsDelivered: (id: string) => call<Order>(`/orders/${id}/delivered?view=ops`, { method: "POST" }),
};
