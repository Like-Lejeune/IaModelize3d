// Mirrors server/formwright/models.py and the agent's SSE event payloads.

export interface AssetOut {
  id: string;
  kind: string;
  url: string;
  thumb_url?: string | null;
  width?: number | null;
  height?: number | null;
  meta: Record<string, any>;
}

export interface SelectionOut {
  id: string;
  asset_id: string;
  role: string;
  name: string;
  mask_url?: string | null;
  data: Record<string, any>;
}

export interface ProgramOut {
  version: number;
  source: string;
  params: Record<string, any>;
  inputs: Record<string, any>;
  summary?: string | null;
  checks?: CheckReport | null;
  author: string;
  created_at: number;
}

export interface MessageOut {
  id: string;
  role: 'user' | 'agent' | 'system';
  text: string;
  data: Record<string, any>;
  created_at: number;
}

export interface ProjectOut {
  id: string;
  title: string;
  pack?: string | null;
  status: string;
  version: number;
  public: boolean;
  /** On the replay gallery too (public is the link). */
  listed?: boolean;
  cover?: string | null;
  forked_from?: string | null;
  created_at: number;
  updated_at: number;
}

/** A ready example on the home page (server/formwright/showcase.py); texts come in both UI languages. */
export interface ExampleOut {
  key: string;
  pack: string;
  title: Record<'en' | 'ru', string>;
  caption: Record<'en' | 'ru', string>;
  prompt: Record<'en' | 'ru', string>;
  cover: string;
  /** 'part': a spare part with its fit checked (the home page marks it). */
  kind?: 'part' | 'model';
}

/** A finished public agent run on the home page (GET /api/featured) or the gallery (GET /api/replays); it plays back as a replay. */
export interface FeaturedRun {
  id: string;
  title: string;
  /** both names, for a run opened from a ready example (its own titles) or born from a shop order (the intake's) */
  title_en?: string;
  title_ru?: string;
  cover?: string | null;
  pack?: string | null;
  versions: number;
  summary?: string | null;
  duration_s?: number | null;
  /** model id -> calls (USD on runs recorded before calls were counted) */
  models: Record<string, number>;
  views?: number;
  featured?: boolean;
}

/** What a job's meter spent ('cost' and 'job.finished' events, server/formwright/llm/client.py CostMeter). */
export interface JobCost {
  usd: number;
  tokens_in?: number;
  tokens_out?: number;
  tokens_cached?: number;
  cache_ratio?: number;
  calls?: number;
  by_model?: Record<string, number>; // model id -> USD
  calls_by_model?: Record<string, number>;
  purposes_by_model?: Record<string, Record<string, number>>; // model id -> purpose -> calls
}

/** The independent reviewer's verdict on one version ('critic' event, server/formwright/agent/critic.py). */
export interface CriticVerdict {
  verdict?: string; // pass | revise
  match_score?: number | null;
  issues?: { severity: string; text: string; text_user?: string; fix_hint?: string }[];
  version?: number;
  model?: string;
  /** 'fallback' when the configured reviewer failed and the fast model stood in */
  reviewer?: string;
  blocking?: boolean;
  /** set when the finish gate overrode the reviewer's own verdict, e.g. 'match_score<8' */
  forced_by?: string | null;
  note?: string;
}

/** The hand-over card at the end of a design job ('result' event, server/formwright/agent/loop.py result_card). */
export interface ResultCard {
  version?: number;
  title?: string;
  size_mm?: number[];
  est_grams?: number;
  est_minutes?: number;
  params_with_sources?: { name: string; label?: string; value: any; unit?: string | null; source?: string }[];
  checks?: { ok?: boolean; errors?: number; warnings?: number; score?: number | null };
  critic?: CriticVerdict | null;
  /** the version the reviewer saw; older than `version` when the last edits went unreviewed */
  reviewed_version?: number | null;
  cover?: string;
  render?: string | null; // latest iso render
  compare?: string | null; // latest photo-vs-model panel
  cost_usd?: number;
  cost?: JobCost | null;
  next?: { action: string; label?: string }[];
  /** A case for a board: its check against the board (checks.enclosure, C5), or just the summary. */
  enclosure?: Partial<EnclosureChecks> | null;
}

export interface ProjectDetail extends ProjectOut {
  assets: AssetOut[];
  selections: SelectionOut[];
  program?: ProgramOut | null;
  messages: MessageOut[];
  last_seq: number;
  job?: { id: string; kind: string; status: string; cost_usd: number } | null;
  /** The printer the project prints on (its brief.printer: an Orca preset id or name), when the server sends it. */
  printer?: string | null;
  /** Whether this viewer may change it (its owner): false for a visitor, whose studio opens read-only. */
  can_edit?: boolean;
  /** What it is meant to print in (its brief.material, e.g. a ready example's PETG), when the brief says. */
  material?: string | null;
}

export interface Usage {
  user_id: string;
  tier: string;
  today_usd: number;
  limit_usd: number;
  jobs_today: number;
  models: ModelOption[];
  /** The Axo shop is connected on this server: the studio offers "Add to Axo cart". */
  axo_cart?: boolean;
}

export interface ModelOption {
  key: 'contributor' | 'spark' | 'wonder' | 'spark_open';
  id: string;
  available: boolean;
}

export interface EventRow {
  seq: number;
  job_id?: string | null;
  type: string;
  data: Record<string, any>;
  ts: number;
}

export type Severity = 'error' | 'warn' | 'info';

export interface Issue {
  code: string;
  severity: Severity;
  message: string;
  z?: [number, number];
  bbox?: { min: [number, number]; max: [number, number] };
  value?: number;
  limit?: number;
  hints: string[];
}

export interface ChecksStats {
  volume: number;
  surfaceArea: number;
  bbox: { min: [number, number, number]; max: [number, number, number] };
  size: [number, number, number];
  triangles: number;
  bodies: number;
  firstLayerArea: number;
  /** Print layers at the printer's layer height. */
  layers?: number;
  /** Slices the mini-slicer walked, one every `sliceStep` mm (fewer than the layers on tall parts). */
  slicesChecked?: number;
  sliceStep?: number;
  estGrams: number;
  estMinutes: number;
}

export interface CheckReport {
  level: 'fast' | 'full';
  ok: boolean;
  score: number;
  issues: Issue[];
  stats: ChecksStats;
  ms: number;
  /** A case program's check against its board, kept with the version by the agent (C5). */
  enclosure?: EnclosureChecks;
  /** 'client' when the studio saved this report with a slider change. */
  by?: string;
}

// ---- electronics: a case around a board (packages/geom/src/enclosure.ts, server/formwright/agent/elec_tools.py)
export type EnclosureCode =
  | 'port_clear' | 'port_blocked' | 'component_clear' | 'board_collision' | 'pcb_seated' | 'button_reach' | 'button_unreachable'
  | 'light_window' | 'lid_fit' | 'snap_strain' | 'metal_in_keepout' | 'keepout_ok' | 'board_retained'
  | 'display_window' | 'sound_grille' | 'sensor_window' | 'cable_exit' | 'battery_space';

export interface EnclosureFinding {
  code: EnclosureCode | string;
  severity: Severity; // passing checks are 'info'
  msg: string; // English, from the kernel
  part: string; // a board component id, 'pcb', 'lid' or a keep-out id
  value: number | null; // in `unit`; port clearance is capped at 2 mm (1.998 = "2 mm or more")
  unit?: 'mm' | 'mm3' | '%';
}

/** One plug path from a port's mouth outward: to where it hit the case, or a little past the outer wall. */
export interface PortRay {
  port: string;
  from: Vec3;
  to: Vec3;
  hit: boolean;
}

/** inspect op 'enclosure' (C3): the case rebuilt assembled around the board ghost, in that build's frame. */
export interface EnclosureCheck {
  op?: 'enclosure';
  findings: EnclosureFinding[];
  rays: PortRay[];
  clearance: Record<string, number>; // port id -> mm all round the plug (0 = blocked)
  ms?: number;
}

/** checks.enclosure of a program version (C5). */
export interface EnclosureChecks extends EnclosureCheck {
  board: string; // the name under inputs.boards
  ok: boolean; // no error findings
  summary: { usb_clearance_mm: number | null; button_gap_mm: number | null; snap_strain_pct: number | null };
  version: number;
  error?: string;
  /** 'studio': checked in the browser after a slider edit (geom worker), not by the agent. */
  by?: 'studio';
}

/** The parts of a fw.board/1 JSON (packages/geom/src/board.schema.json) the studio reads. */
export interface BoardSpec {
  schema?: string;
  id: string;
  name: string;
  source?: { kind?: string; dataset_id?: string; pcb_job?: string; calibration?: { method?: string; residual_mm?: number; uncertainty_mm?: number } };
  pcb: { outline: { kind: string; w: number; h: number }; thickness: number; holes?: { x: number; y: number; d: number; use?: string }[] };
  components: {
    id: string;
    type: string;
    side: 'top' | 'bottom';
    access: string;
    w: number;
    h: number;
    d?: number;
    edge?: '+x' | '-x' | '+y' | '-y';
    at?: number;
    z0?: number;
    protrude?: number;
    x?: number;
    y?: number;
  }[];
  keepouts?: { id: string; rect: [number, number, number, number]; rule: string }[];
}

/** A labelled box of a board scan (selection data.kind 'board_scan'): photo pixels, strong = holes and ports. */
export interface ScanBox {
  label: string;
  box: [number, number, number, number];
  score?: number | null;
  kind?: string;
  source?: 'sam' | 'spark';
  emphasis?: 'strong' | 'normal' | 'dim';
}

// ---- PCB versions (server/formwright/pcbapi.py, C8)
export interface PcbCounts {
  components?: number;
  nets?: number;
  connections?: number;
  traces?: number;
  vias?: number;
}

export interface PcbVersion {
  version: number;
  created_at: number | null;
  counts: PcbCounts;
  drc: { errors: number; warnings: number };
  intent_ok: boolean;
  /** The BOM's LCSC numbers came from the catalogue (a device build). */
  lcsc_verified?: boolean;
  limits_ok?: boolean;
  /** artifact name -> URL; only the files this version has */
  artifacts: Record<string, string>;
}

export interface PcbIssue {
  type: string;
  message: string;
  hint?: string | null;
  ref?: string;
}

/** drc.json of a version: the build's errors and warnings, the intent and limit checks. */
export interface PcbDrc {
  ok: boolean;
  errors: PcbIssue[];
  warnings: PcbIssue[];
  suppressed?: number;
  counts: PcbCounts;
  intent?: { ok: boolean; issues: { code: string; ref?: string; msg: string; hint?: string; value?: unknown }[]; checked?: number };
  limits?: { ok: boolean; issues: { code: string; value: unknown; limit: unknown; msg: string }[]; limits?: Record<string, number> };
}

/** Autorouter drawing at one moment: segments [x1, y1, x2, y2] in fw.board/1 mm. */
export interface RouteFrame {
  progress: number | null;
  lines: [number, number, number, number][];
}

/** route_frames.json: the frames, and how fw.board/1 mm map to the SVGs (px = a*x + e, py = d*y + f). */
export interface RouteFrames {
  frames: RouteFrame[];
  total: number;
  board: { w: number | null; h: number | null };
  svg_map: Record<string, { matrix: number[]; width: number; height: number }>;
  /** GLB to fw.board/1 mm, 4x4 row-major */
  glb_map?: { matrix: number[][] } | null;
}

export interface ParamSpec {
  value: number | string | boolean;
  kind?: 'number' | 'int' | 'bool' | 'choice' | 'color' | 'seed';
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
  label?: string;
  unit?: string;
  source?: string;
  group?: string;
  hidden?: boolean;
}

export type Vec3 = [number, number, number];

export type Handle =
  | { type: 'linear'; param: string; at: Vec3; axis: Vec3; scale?: number; label?: string }
  | { type: 'radial'; param: string; center: Vec3; axis: Vec3; at: Vec3; scale?: number; label?: string }
  | { type: 'angle'; param: string; center: Vec3; axis: Vec3; at: Vec3; label?: string }
  | { type: 'point'; params: [string, string]; at: Vec3; plane: 'xy' | 'xz' | 'yz'; label?: string };

/** 'reference' parts (the board inside a case) are never printed, checked or picked. */
export type PartRole = 'model' | 'modifier' | 'negative' | 'support_blocker' | 'support_enforcer' | 'reference';

export interface PartInfo {
  name: string;
  role: PartRole | string;
  color?: string;
  settings?: Record<string, any>;
  bbox: { min: Vec3; max: Vec3 };
  volume: number;
  meta?: PartMeta;
}

/** A part's meta; a board ghost (lib.elec.parts) says which board it is and how its case was built. */
export interface PartMeta {
  board?: string; // the board's id
  bottomPins?: boolean;
  enclosure?: EnclosureReport;
  /** Where the board's own frame (PCB bottom-left corner, bottom face) sits in the build, mm; set by the geom worker. */
  pose?: Vec3;
  [k: string]: unknown;
}

/** lib.elec's report of how a case was built (packages/geom/src/lib/elec.ts EnclosureReport), in the case's own frame. */
export interface EnclosureReport {
  zBoard: number; // PCB bottom
  zTop: number; // lid underside
  lidT: number;
  standoff: number;
  inner: { x0: number; y0: number; x1: number; y1: number };
  outerSize: Vec3;
  features: ({ type: string; for?: string; at?: [number, number] } & Record<string, any>)[];
}

export interface BuildResult {
  ok: true;
  meta: Record<string, any>;
  paramSpecs: Record<string, ParamSpec>;
  params: Record<string, any>;
  handles: Handle[];
  parts: PartInfo[];
  checks?: CheckReport;
  display: DisplayBuffers;
  quality: 'preview' | 'final';
  ms: number;
}

/** Viewer-ready buffers made in the geometry worker (packages/geom/src/display.ts). */
export interface DisplayBuffers {
  position: Float32Array; // non-indexed, model parts in part order
  heat: Uint8Array; // overhang risk per vertex, 0..255
  groups: [number, number, number][]; // [firstVertex, vertexCount, partIndex]
  ghost: Float32Array; // modifier/negative volumes
  /** 'reference' parts (a board inside its case), non-indexed; reference[i] = [firstVertex, vertexCount, partIndex] */
  referencePosition: Float32Array;
  reference: [number, number, number][];
  edges: Float32Array; // feature-edge segments, empty in previews
  triangles: number;
}

export interface BuildError {
  ok: false;
  stage: string;
  message: string;
}

export interface Calibration {
  reference?: string;
  R: number[];
  t: Vec3;
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  width: number;
  height: number;
  mm_per_px?: number;
}

// ---- snap & collect (server/formwright/vision/snap.py)
export interface SnapObject {
  label: string;
  bbox: [number, number, number, number]; // image pixels
}

/** The object found on an uploaded photo (`asset.meta.spot` keeps label and objects). */
export interface SpotResult {
  selection: SelectionOut | null;
  label: string | null;
  objects: SnapObject[];
}

export interface SnapResult {
  project: ProjectOut;
  asset: AssetOut;
  selection: SelectionOut | null;
  label: string | null; // null until the name arrives (api.snapName)
  objects: SnapObject[];
}

export type CollectState = 'draft' | 'queued' | 'modelling' | 'ready' | 'failed';

export interface CollectionItem {
  id: string;
  title: string;
  subject?: string | null;
  cover?: string | null;
  state: CollectState;
  version: number;
  created_at: number;
  updated_at: number;
  error?: string | null;
  photo?: string | null; // thumbnail of the snap
  width?: number | null; // of the full photo; the thumbnail has the same aspect
  height?: number | null;
  mask_url?: string | null;
  bbox?: [number, number, number, number] | null;
}

export interface Printer {
  id: string;
  name: string;
  vendor?: string;
  bed?: [number, number, number];
  nozzle?: number;
  popular?: boolean;
  /** The farm's own printer (shop farm_preset): the studio slices for it unless the project or the person picked another. */
  default?: boolean;
}
