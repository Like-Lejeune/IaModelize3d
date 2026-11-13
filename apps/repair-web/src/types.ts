// The shapes the IaModelize3d shop API answers with (server/iamodelize3d/shop/routes.py, present()).
// Only the fields this front reads are typed; the API sends more.

export type Status =
  | "requested" | "designing" | "needs_info" | "quoted" | "paid" | "printing" | "qc" | "shipped" | "delivered"
  | "refused" | "cancelled" | "expired";

export type Delivery = "pickup" | "courier" | "post";
export type Material = "PLA" | "PETG" | "ASA" | "TPU";
export type PayMethod = "test" | "mobile_money" | "on_pickup";

export interface Quote {
  source?: "kernel" | "orca" | "operator";
  binding?: boolean;
  currency?: string;
  quantity?: number;
  material?: string;
  grams_each?: number;
  minutes_each?: number;
  unit_price?: number;
  parts?: number;
  new_part_fee?: number;
  delivery?: { method: Delivery; price: number; days: number };
  total?: number;
  usd?: { rate: number; total: number };
  eta?: { production_days: number; ready_by: string; arrive_by: string };
  range?: { total: [number, number] };
  valid_until?: number;
  // operators only
  cost?: { total: number };
  gross_margin?: number;
}

export interface TimelineEntry {
  status: Status;
  from: Status | null;
  actor: "customer" | "operator" | "system" | string;
  ts: number;
  code: string | null;
  params: Record<string, unknown>;
  note: string;
}

export interface Intake {
  language?: string;
  refuse?: boolean;
  reason?: string;
  material?: string;
  part?: { name_en?: string; name_fr?: string; name_user?: string; part_number?: string; failure?: string };
  appliance?: { kind?: string; brand?: string; model?: string };
  questions?: string[];
  review?: { code: string; why: string } | null;
  request?: { kind?: string; text?: string; words?: string; photos?: { id: string; role: string }[] };
}

export interface Payment {
  mode?: PayMethod;
  amount?: number;
  currency?: string;
  operator?: "mtn" | "orange";
  reference?: string;
  verified?: boolean;
}

export interface Order {
  id: string;
  ref: string;
  status: Status;
  quantity: number;
  material: Material;
  created_at: number;
  updated_at: number;
  title: string;
  title_fr?: string;
  title_en?: string;
  project: { id: string; title: string | null; cover: string | null; version: number | null };
  intake: Intake;
  quote: Quote;
  payment?: Payment;
  delivery?: { method: Delivery };
  customer?: { contact?: string };
  next: Status[];
  actor: "customer" | "operator" | "public";
  safety: "ok" | "pending" | "held" | "refused";
  material_due: string | null;
  working: boolean;
  question?: { question?: string; options?: string[]; allow_text?: boolean } | null;
  qc?: { pass?: boolean; max_mm?: number; tolerance_mm?: number; error?: string; photo_url?: string };
  problem?: { code?: string };
  printer_id?: string | null;
  timeline?: TimelineEntry[];
}

export interface Tariff {
  currency: string;
  usd_rate: number;
  materials: Material[];
  delivery: Record<Delivery, { price: number; days: number; price_usd: number }>;
}

export interface Me {
  user: { id: string; tier: string; name?: string | null };
  org: { id: string; kind: string; name: string } | null;
  is_operator: boolean;
  currency: string;
}

export interface Printer {
  id: string;
  name: string;
  preset_id: string;
  material: string;
  color: string | null;
  state: "idle" | "printing" | "maintenance";
  order_ref: string | null;
}

export interface Board {
  orders: Order[];
  upstream: Order[];
  done: Order[];
  printers: Printer[];
  queue_hours: number;
}
