// IaModelize3d Parts: the shapes server/iamodelize3d/shop/routes.py answers with (orders, quotes, QC, the catalog, the farm).
// Money is in tenge (KZT), the binding figure; every amount also comes in US dollars at a fixed demo rate.

export type OrderStatus =
  | 'requested'
  | 'designing'
  | 'needs_info'
  | 'quoted'
  | 'paid'
  | 'printing'
  | 'qc'
  | 'shipped'
  | 'delivered'
  | 'refused'
  | 'cancelled'
  | 'expired';

export type DeliveryMethod = 'pickup' | 'courier' | 'post';
export type Actor = 'customer' | 'operator' | 'system';
/** Who reads an order: its customer, the farm, or anyone (a showcase order, without the customer's data). */
export type Viewer = 'customer' | 'operator' | 'public';

export interface ShopMe {
  user: { id: string; tier: string; name?: string | null };
  org: { id: string; name: string; kind: 'repair_shop' | 'farm'; tier: string; role: string } | null;
  is_operator: boolean;
  currency: string;
  usd_kzt: number;
}

export interface Tariff {
  currency: string;
  usd_kzt: number;
  materials: string[];
  delivery: Record<DeliveryMethod, { price: number; days: number; price_usd: number }>;
}

/** A quote: binding only when it comes from OrcaSlicer (or the operator's own numbers); the kernel's is a range. */
export interface Quote {
  source?: 'orca' | 'kernel' | 'operator';
  binding?: boolean;
  currency?: string;
  quantity?: number;
  material?: string;
  grams_each?: number;
  minutes_each?: number;
  unit_price?: number;
  parts?: number;
  new_part_fee?: number;
  delivery?: { method: DeliveryMethod; price: number; days: number };
  total?: number;
  usd?: { rate: number; unit_price: number; parts: number; new_part_fee: number; delivery: number; total: number };
  eta?: { production_days: number; ready_by: string; arrive_by: string };
  /** Instant quotes only: the low-high band of the kernel's calibration. */
  range?: { total: [number, number]; total_usd: [number, number]; grams_each: [number, number]; minutes_each: [number, number] };
  version?: number;
  valid_until?: number;
  quoted_at?: number;
  printer?: { id: string; name: string } | null;
  supports?: boolean;
  slice_seconds?: number | null;
  files?: SliceFiles | null;
  warnings?: string[];
  // the farm's side, operators only
  cost?: Record<string, number>;
  royalty?: number;
  gross_profit?: number;
  gross_margin?: number;
}

export interface SliceFiles {
  gcode?: string | null;
  project_3mf?: string | null;
}

/** Contract C10: the print's outline against the model's, both in mm on the sheet's own grid. */
export interface QcReport {
  pass: boolean;
  error?: string;
  tolerance_mm?: number;
  max_mm?: number;
  mean_mm?: number;
  rms_mm?: number;
  bias_mm?: number;
  scale?: number;
  regions?: { index?: number; center?: number[]; center_sheet?: number[]; mean_mm?: number; max_mm: number }[];
  photo_url?: string | null;
  mask_url?: string | null;
  printed_mm?: number[][];
  target_mm?: number[][];
  sheet?: { w: number; h: number };
  note?: string;
  note_en?: string;
  holes?: unknown[];
  suggestions?: string[];
  compared_with?: string;
  uncertainty_mm?: number | null;
  reference?: string | null;
  version?: number;
  at?: number;
  /** Why a photo could not be measured (the UI says it in its language; `error` is the farm's own words). */
  error_code?: 'not_found' | 'model_unavailable' | 'no_sheet' | 'version_gone';
}

/** A file the request could not use. Older orders kept an English line instead. */
export interface SkippedFile {
  code: 'unreadable' | 'voice_untranscribed' | 'not_photo';
  file?: string;
  kind?: string;
  /** operators only */
  error?: string;
}

export interface Intake {
  request?: {
    kind: 'photo' | 'project' | 'listing';
    text?: string;
    /** the customer's own text, apart from the labelled lines the models read */
    words?: string;
    /** what the form said (null: 'from the request' / 'choose for me') */
    quantity?: number | null;
    material?: string | null;
    appliance?: string;
    part_number?: string;
    photos?: { id: string; role: 'part' | 'plate' }[];
    transcript?: string;
    skipped?: (SkippedFile | string)[];
  };
  appliance?: { kind?: string; brand?: string; model?: string; serial_or_enr?: string };
  part?: { name_en?: string; name_user?: string; part_number?: string; quantity?: number; condition?: string; failure?: string };
  environment?: { max_temp_c?: number; wet?: boolean; food_contact?: boolean; load?: string };
  material?: string;
  refuse?: boolean;
  reason?: string;
  ip_flags?: string[];
  questions?: string[];
  notes?: string;
  language?: string;
  model?: string;
  classify?: { category?: string; safety_critical?: boolean; why?: string; title_en?: string; title_ru?: string; model?: string | null; error?: string } | null;
  review?: { code: 'intake_failed' | 'safety_disagreement'; why: string } | null;
  reviewed?: { by: string; action: 'approve' | 'refuse'; note: string; at: number } | null;
  answers?: { text: string; at: number }[];
  read_at?: number;
  error?: string;
  tolerance_mm?: number;
}

/** One step of the order's journal. `code` and `params` (server shop/notes.py) are what the UI says, in its own
 * language; `note` is the server's English line, for an entry without a code. */
export interface TimelineEntry {
  status: OrderStatus;
  from: OrderStatus | null;
  actor: Actor;
  note: string;
  ts: number;
  code?: string | null;
  params?: Record<string, any>;
}

/** An order as GET /orders/{id} answers it. A showcase order read by anyone else (actor 'public') carries no user_id,
 * org_id, project_id, contact, address, request text or answers, and its journal has no free text. */
export interface Order {
  id: string;
  ref: string;
  user_id: string;
  org_id?: string | null;
  project_id: string;
  version?: number | null;
  listing_id?: string | null;
  status: OrderStatus;
  intake: Intake;
  quantity: number;
  material: string;
  color?: string | null;
  delivery: { method?: DeliveryMethod };
  customer: { contact?: string };
  quote: Quote;
  payment: { mode?: 'test'; amount?: number; currency?: string; amount_usd?: number; at?: number };
  printer_id?: string | null;
  slice: { id?: string; printer?: { id: string; name: string }; material?: string; stats?: { grams?: number; minutes?: number; supports?: boolean; slice_seconds?: number }; files?: SliceFiles; shop_printer_id?: string | null };
  qc: QcReport | Record<string, never>;
  shipping: { carrier?: string; tracking?: string; at?: number };
  /** Why an automatic step stopped. `detail` (the step's own words) reaches the farm's operators only. */
  problem: { code?: string; detail?: string; at?: number; retry_at?: number | null };
  attempts?: number;
  created_at: number;
  updated_at: number;
  // added by the presenter
  next: OrderStatus[];
  actor: Viewer;
  /** Pay waits for the intake's safety verdict: a ready model is priced while Muse Spark 1.3 reads it. */
  safety?: 'pending' | 'held' | 'refused' | 'ok';
  /** "Choose for me": the material the intake picked while the price is still in another one (Pay waits for its quote). */
  material_due?: string | null;
  /** The farm shows this delivered order to anyone (without the customer's data). */
  showcase?: boolean;
  /** The farm printer it was printed on (the public view). */
  printer?: { name: string; preset_id?: string } | null;
  project: { id: string; title?: string | null; cover?: string | null; version?: number | null };
  title: string;
  /** The title in each UI language (a new part: what the intake read; otherwise the same as title). */
  title_en?: string;
  title_ru?: string;
  /** The owner's listing of this part: in "Your parts" (public false) or in the catalog (public true). */
  own_listing?: { id: string; public: boolean } | null;
  working: boolean;
  question?: { job_id?: string; question_id?: string; question: string; options?: string[]; allow_text?: boolean } | null;
  timeline?: TimelineEntry[];
}

export interface ShopPrinter {
  id: string;
  name: string;
  preset_id: string;
  fingerprint: Record<string, any>;
  material: string;
  color?: string | null;
  state: 'idle' | 'printing' | 'maintenance';
  order_id?: string | null;
  order_ref?: string | null;
}

export interface OpsQueue {
  orders: Order[];
  upstream: Order[];
  /** The latest shipped and delivered orders (where a showcase is picked). */
  done?: Order[];
  printers: ShopPrinter[];
  queue_hours: number;
}

export interface Listing {
  id: string;
  project_id: string;
  version: number;
  title: string;
  // the card's name in each UI language (the server falls back to title)
  title_en?: string;
  title_ru?: string;
  brand: string;
  models: string[];
  part_numbers: string[];
  category: string;
  material: string;
  cover?: string | null;
  verified: { printable?: boolean | null; critic?: string | null; qc_pass?: boolean; qc_max_mm?: number | null; qc_tolerance_mm?: number | null; qc_order?: string | null; seeded?: boolean };
  orders: number;
  public: boolean;
  compatible_with?: string | null;
  mine: boolean;
  flagged: boolean;
  created_at: number;
  updated_at: number;
}

/** GET /showcase: the newest delivered order the farm shows to anyone (/parts links it). */
export interface ShowcaseCard {
  id: string;
  ref: string;
  status: OrderStatus;
  title: string;
  title_en: string;
  title_ru: string;
  cover?: string | null;
  qc_pass: boolean;
}
