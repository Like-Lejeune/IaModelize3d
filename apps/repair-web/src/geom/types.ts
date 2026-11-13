// The studio's types: the IaModelize3d API's project objects and events (server/iamodelize3d/models.py) and the
// geometry worker's build results (packages/geom). Mirrors web/src/lib/types.ts, trimmed to what the studio uses.

export type Vec3 = [number, number, number];

export interface ParamSpec {
  value: number | string | boolean;
  kind?: "number" | "int" | "bool" | "choice" | "color" | "seed";
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

export interface Issue {
  code: string;
  severity: "error" | "warn" | "info";
  message: string;
  hint?: string;
}

export interface CheckReport {
  ok?: boolean;
  issues: Issue[];
  stats?: { estGrams?: number; estMinutes?: number; volume?: number; bbox?: { min: Vec3; max: Vec3 }; [k: string]: unknown };
  [k: string]: unknown;
}

export interface PartInfo {
  name: string;
  role: string;
  color?: string;
  bbox: { min: Vec3; max: Vec3 };
  volume: number;
}

/** Viewer-ready buffers made in the geometry worker (packages/geom/src/display.ts). */
export interface DisplayBuffers {
  position: Float32Array;
  heat: Uint8Array;
  groups: [number, number, number][];
  ghost: Float32Array;
  referencePosition: Float32Array;
  reference: [number, number, number][];
  edges: Float32Array;
  triangles: number;
}

export interface BuildResult {
  ok: true;
  meta: Record<string, any>;
  paramSpecs: Record<string, ParamSpec>;
  params: Record<string, any>;
  handles: unknown[];
  parts: PartInfo[];
  checks?: CheckReport;
  display: DisplayBuffers;
  quality: "preview" | "final";
  ms: number;
}

export interface BuildError {
  ok: false;
  stage: string;
  message: string;
}

// ------------------------------------------------------------------ the project API
export interface AssetOut {
  id: string;
  kind: string;
  url: string;
  thumb_url?: string | null;
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
  role: "user" | "agent" | "system";
  text: string;
  data: Record<string, any>;
  created_at: number;
}

export interface ProjectDetail {
  id: string;
  title: string;
  status: string;
  version: number;
  cover?: string | null;
  created_at: number;
  updated_at: number;
  assets: AssetOut[];
  program?: ProgramOut | null;
  messages: MessageOut[];
  last_seq: number;
  job?: { id: string; kind: string; status: string; cost_usd: number } | null;
  can_edit?: boolean;
  material?: string | null;
}

export interface EventRow {
  seq: number;
  job_id?: string | null;
  type: string;
  data: Record<string, any>;
  ts: number;
}

export interface VersionRow {
  version: number;
  summary: string | null;
  author: string;
  created_at: number;
}
