// Typed client for the FastAPI backend (same origin; the httpOnly cookie `fw_session` holds an opaque session token,
// see server/formwright/sessions.py).
import { t } from './i18n.svelte';
import type { AssetOut, ExampleOut, FeaturedRun, ProjectDetail, ProjectOut, SelectionOut, Usage, Printer, ProgramOut, SnapResult, SnapObject, SpotResult, CollectionItem } from './types';

export type { FeaturedRun };

export class ApiError extends Error {
  status: number;
  /** Machine-readable reason from the JSON body: 'job_running', 'daily_limit', 'model_busy'… */
  code?: string;
  /** The rest of the body; 'job_running' carries the blocker's project_id and job_id. */
  info: Record<string, any>;
  constructor(status: number, message: string, code?: string, info: Record<string, any> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.info = info;
  }
}

export async function req<T>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, body: payload, headers, credentials: 'same-origin', ...init });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let msg = res.statusText;
    let code: string | undefined;
    let info: Record<string, any> = {};
    try {
      // {detail, code, ...info}; an HTTPException may nest the same object under detail
      let j = JSON.parse(text);
      if (j?.detail && typeof j.detail === 'object' && !Array.isArray(j.detail)) j = { ...j.detail, detail: j.detail.detail ?? j.detail.message };
      const { detail, code: c, ...rest } = j ?? {};
      if (typeof detail === 'string') msg = detail;
      // pydantic 422: a list of {loc, msg, type}; the first message says enough
      else if (Array.isArray(detail)) msg = detail[0]?.msg ?? msg;
      else if (detail != null) msg = JSON.stringify(detail);
      if (typeof c === 'string') code = c;
      info = rest;
    } catch {
      // not json: an empty 5xx comes from the dev proxy while the API restarts
      if (res.status >= 500 && !text.trim()) code = 'offline';
    }
    throw new ApiError(res.status, msg || `HTTP ${res.status}`, code, info);
  }
  const ct = res.headers.get('content-type') ?? '';
  if (ct.includes('application/json')) return (await res.json()) as T;
  return (await res.blob()) as unknown as T;
}

export const api = {
  me: () => req<Usage>('GET', '/api/me'),
  consent: (contributor: boolean) => req<{ ok: boolean }>('POST', '/api/me/consent', { contributor }),

  projects: () => req<ProjectOut[]>('GET', '/api/projects'),
  gallery: () => req<ProjectOut[]>('GET', '/api/gallery'),
  /** Curated recorded runs for the home page; [] until some are featured. */
  featured: () => req<FeaturedRun[]>('GET', '/api/featured'),
  examples: () => req<ExampleOut[]>('GET', '/api/examples'),
  /** A copy of the example as the user's own project, model included: no agent run. */
  openExample: (key: string, lang: string) => req<ProjectOut>('POST', `/api/examples/${encodeURIComponent(key)}`, { lang }),
  createProject: (title?: string, pack?: string) => req<ProjectOut>('POST', '/api/projects', { title, pack }),
  project: (id: string) => req<ProjectDetail>('GET', `/api/projects/${id}`),
  patchProject: (id: string, body: { title?: string; pack?: string; public?: boolean }) => req<ProjectOut>('PATCH', `/api/projects/${id}`, body),
  fork: (id: string) => req<ProjectOut>('POST', `/api/projects/${id}/fork`),
  replay: (id: string, speed = 4) => req<ProjectOut>('POST', `/api/projects/${id}/replay?speed=${speed}`),

  upload: (id: string, file: Blob, kind: string, filename?: string) => {
    const fd = new FormData();
    fd.append('kind', kind);
    fd.append('file', file, filename ?? (file as File).name ?? `${kind}.bin`);
    return req<AssetOut>('POST', `/api/projects/${id}/assets`, fd);
  },
  detect: (id: string, assetId: string) => req<DetectResult>('POST', `/api/projects/${id}/assets/${assetId}/detect`),
  select: (id: string, assetId: string, body: SelectBody) => req<SelectionOut>('POST', `/api/projects/${id}/assets/${assetId}/select`, body),
  /** Find and cut out the object on a fresh photo; `hint` is the request text. */
  spot: (id: string, assetId: string, body: { hint?: string | null; lang: string }) => req<SpotResult>('POST', `/api/projects/${id}/assets/${assetId}/spot`, body),
  deleteSelection: (id: string, selId: string) => req<{ ok: boolean }>('DELETE', `/api/projects/${id}/selections/${selId}`),

  send: (id: string, text: string, asset_ids: string[] = [], opts: { model?: string; reasoning?: string } = {}) =>
    req<{ job_id: string }>('POST', `/api/projects/${id}/messages`, { text, asset_ids, ...opts }),
  fingerprint: (printerId: string, assetId: string) =>
    req<Record<string, any>>('POST', `/api/printers/${encodeURIComponent(printerId)}/fingerprint`, { asset_id: assetId }),
  answer: (jobId: string, answer: string) => req<{ ok: boolean }>('POST', `/api/jobs/${jobId}/answer`, { answer }),
  cancel: (jobId: string) => req<{ ok: boolean }>('POST', `/api/jobs/${jobId}/cancel`),

  program: (id: string, version: number) => req<ProgramOut>('GET', `/api/projects/${id}/program/${version}`),
  versions: (id: string) => req<{ version: number; summary: string | null; author: string; created_at: number }[]>('GET', `/api/projects/${id}/versions`),
  saveParams: (id: string, params: Record<string, any>, checks?: unknown, client?: string) =>
    req<{ version: number; params: Record<string, any> }>('PUT', `/api/projects/${id}/params`, { params, checks, client }),
  saveProgram: (id: string, body: { source: string; params: Record<string, any>; checks?: unknown; summary?: string; client?: string }) =>
    req<{ version: number; params: Record<string, any> }>('PUT', `/api/projects/${id}/program`, body),
  exportFile: (id: string, format: 'stl' | '3mf', params?: Record<string, any>) => req<Blob>('POST', `/api/projects/${id}/export`, { format, params }),
  render: (id: string, body: { view?: string; heat?: boolean; params?: Record<string, any> }) => req<Blob>('POST', `/api/projects/${id}/render`, body),

  printers: () => req<Printer[]>('GET', '/api/printers'),
  slice: (id: string, body: { printer?: string; material: string; goals: string[]; params?: Record<string, any> }) =>
    req<{ job_id: string }>('POST', `/api/projects/${id}/slice`, body),
  probe: (id: string, body: Record<string, any>) => req<{ job_id: string }>('POST', `/api/projects/${id}/probe`, body),
  concepts: (id: string, prompt: string, n = 4) => req<{ job_id: string }>('POST', `/api/projects/${id}/concepts`, { prompt, n }),
  breed: (id: string, parents: number[], n = 6) => req<{ job_id: string }>('POST', `/api/projects/${id}/breed`, { parents, n }),
  visualEdit: (id: string, instruction: string, sketch_png: string) =>
    req<{ job_id: string }>('POST', `/api/projects/${id}/visual-edit`, { instruction, sketch_png }),
  order: (id: string, body: { quantity: number; material: string; color?: string; comment?: string }) =>
    req<Record<string, any>>('POST', `/api/projects/${id}/order`, body),
  /** The version as a design in the Axo shop's cart; `replace` is the design Axo sent the buyer back to edit. `url` opens the cart. */
  axoCart: (id: string, body: { version?: number; replace?: string }) =>
    req<{ url: string; design_id?: string; price_kzt?: number | null }>('POST', `/api/projects/${id}/axo-cart`, body),
  captureToken: (id: string) => req<{ token: string; url?: string }>('POST', `/api/projects/${id}/capture-token`),

  memory: () => req<{ mine: any[]; global: any[] }>('GET', '/api/memory'),
  forget: (itemId: string) => req<{ ok: boolean }>('DELETE', `/api/memory/${itemId}`),

  /** Phone shot: x, y is the tap on the photo (0..1), SAM's positive point. */
  snap: (file: Blob, o: { x: number; y: number; lang: string }) => {
    const fd = new FormData();
    fd.append('file', file, 'snap.jpg');
    fd.append('x', String(o.x));
    fd.append('y', String(o.y));
    fd.append('lang', o.lang);
    return req<SnapResult>('POST', '/api/snap', fd);
  },
  snapName: (id: string) => req<{ label: string; objects: SnapObject[]; selection: SelectionOut | null }>('GET', `/api/snap/${id}/name`),
  snapSelect: (id: string, body: { points?: { x: number; y: number; positive: boolean }[]; box?: number[] | null; label?: string | null }) =>
    req<{ selection: SelectionOut; label: string }>('POST', `/api/snap/${id}/select`, body),
  snapConfirm: (id: string, body: { text: string; label?: string; model?: string; reasoning?: string }) =>
    req<{ queued: boolean; job_id: string | null }>('POST', `/api/snap/${id}/confirm`, body),
  snapDiscard: (id: string) => req<{ ok: boolean }>('DELETE', `/api/snap/${id}`),
  collection: () => req<CollectionItem[]>('GET', '/api/collection'),
};

export interface SelectBody {
  points?: { x: number; y: number; positive: boolean }[];
  box?: [number, number, number, number] | null;
  text?: string | null;
  role: string;
  name?: string | null;
  /** Drop the earlier selections of this role on the photo. */
  replace?: boolean;
}

export interface DetectResult {
  references?: { name: string; kind?: string; bbox: number[]; confidence?: number }[];
  objects?: { label: string; bbox: number[]; suggested_role?: string; confidence?: number }[];
  [k: string]: any;
}

// the server's error codes (app.py handlers, quotas.QuotaExceeded) in the UI language
const CODE_TEXT: Record<string, string> = {
  job_running: 'err_job_running',
  project_busy: 'err_project_busy',
  daily_limit: 'err_daily_limit',
  ip_daily_cap: 'err_ip_cap',
  demo_budget: 'err_demo_budget',
  budget: 'err_budget',
  quota: 'err_quota',
  upload_quota: 'err_upload_quota',
  model_busy: 'err_model_busy',
  offline: 'err_offline',
  internal: 'err_internal',
};

/** The localized text for a server error code ('daily_limit'…), or null for a code the UI does not know. */
export function codeText(code: string | null | undefined): string | null {
  const key = code ? CODE_TEXT[code] : undefined;
  return key ? t(key) : null;
}

/** fetch() itself failed: the network is down or the server is restarting. */
const isNetworkError = (e: unknown) => e instanceof TypeError && /fetch|network|load failed/i.test(e.message);

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const text = codeText(e.code);
    if (text) return e.code === 'internal' && e.info.id ? `${text} (${e.info.id})` : text;
    if (e.status === 403) return t('forbidden');
    if (e.status === 404) return t('err_not_found');
    if (e.status === 413) return t('too_large');
    if (e.status === 429) return t('err_quota');
    if (e.status === 502 || e.status === 503 || e.status === 504) return t('err_offline');
    if (e.status >= 500) return t('err_internal');
    return t('err_bad_input', { d: e.message });
  }
  if (isNetworkError(e)) return t('err_offline');
  if (e instanceof Error) return e.message;
  return String(e);
}

/** The text plus what a next step needs: for 'job_running', the project that holds the slot. */
export function errorInfo(e: unknown): { text: string; code?: string; projectId?: string; jobId?: string } {
  const text = errorText(e);
  if (e instanceof ApiError) return { text, code: e.code, projectId: e.info.project_id, jobId: e.info.job_id };
  return { text, code: isNetworkError(e) ? 'offline' : undefined };
}

export async function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
