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
  cover?: string | null;
  forked_from?: string | null;
  created_at: number;
  updated_at: number;
}

export interface ProjectDetail extends ProjectOut {
  assets: AssetOut[];
  selections: SelectionOut[];
  program?: ProgramOut | null;
  messages: MessageOut[];
  last_seq: number;
  job?: { id: string; kind: string; status: string; cost_usd: number } | null;
}

export interface Usage {
  user_id: string;
  tier: string;
  today_usd: number;
  limit_usd: number;
  jobs_today: number;
  contributor_consent: boolean;
  models: ModelOption[];
}

export interface ModelOption {
  key: 'contributor' | 'spark' | 'wonder';
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

export interface CheckReport {
  level: 'fast' | 'full';
  ok: boolean;
  score: number;
  issues: Issue[];
  stats: {
    volume: number;
    surfaceArea: number;
    bbox: { min: [number, number, number]; max: [number, number, number] };
    size: [number, number, number];
    triangles: number;
    bodies: number;
    firstLayerArea: number;
    layers?: number;
    estGrams: number;
    estMinutes: number;
  };
  ms: number;
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

export interface PartInfo {
  name: string;
  role: string;
  color?: string;
  settings?: Record<string, any>;
  bbox: { min: Vec3; max: Vec3 };
  volume: number;
}

export interface BuildResult {
  ok: true;
  meta: Record<string, any>;
  paramSpecs: Record<string, ParamSpec>;
  params: Record<string, any>;
  handles: Handle[];
  parts: PartInfo[];
  checks?: CheckReport;
  positions: Float32Array;
  indices: Uint32Array;
  triPart: Uint16Array;
  heat?: Float32Array;
  ms: number;
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

export interface Printer {
  id: string;
  name: string;
  vendor?: string;
  bed?: [number, number, number];
  nozzle?: number;
}
