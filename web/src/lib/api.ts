// Typed client for the FastAPI backend (same origin; cookie session `fw_uid`).
import { t } from './i18n.svelte';
import type { AssetOut, ProjectDetail, ProjectOut, SelectionOut, Usage, Printer, ProgramOut } from './types';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, body: payload, headers, credentials: 'same-origin', ...init });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg || `HTTP ${res.status}`);
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
  deleteSelection: (id: string, selId: string) => req<{ ok: boolean }>('DELETE', `/api/projects/${id}/selections/${selId}`),

  send: (id: string, text: string, asset_ids: string[] = [], effort: 'auto' | 'hard' = 'auto') =>
    req<{ job_id: string }>('POST', `/api/projects/${id}/messages`, { text, asset_ids, effort }),
  fingerprint: (printerId: string, assetId: string) =>
    req<Record<string, any>>('POST', `/api/printers/${encodeURIComponent(printerId)}/fingerprint`, { asset_id: assetId }),
  answer: (jobId: string, answer: string) => req<{ ok: boolean }>('POST', `/api/jobs/${jobId}/answer`, { answer }),
  cancel: (jobId: string) => req<{ ok: boolean }>('POST', `/api/jobs/${jobId}/cancel`),

  program: (id: string, version: number) => req<ProgramOut>('GET', `/api/projects/${id}/program/${version}`),
  versions: (id: string) => req<{ version: number; summary: string | null; author: string; created_at: number }[]>('GET', `/api/projects/${id}/versions`),
  saveParams: (id: string, params: Record<string, any>) => req<{ version: number; checks: any; params: Record<string, any> }>('PUT', `/api/projects/${id}/params`, { params }),
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
  captureToken: (id: string) => req<{ token: string; url?: string }>('POST', `/api/projects/${id}/capture-token`),

  memory: () => req<{ mine: any[]; global: any[] }>('GET', '/api/memory'),
  forget: (itemId: string) => req<{ ok: boolean }>('DELETE', `/api/memory/${itemId}`),
};

export interface SelectBody {
  points?: { x: number; y: number; positive: boolean }[];
  box?: [number, number, number, number] | null;
  text?: string | null;
  role: string;
  name?: string | null;
}

export interface DetectResult {
  references?: { name: string; kind?: string; bbox: number[]; confidence?: number }[];
  objects?: { label: string; bbox: number[]; suggested_role?: string; confidence?: number }[];
  [k: string]: any;
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError && e.status === 403) return t('forbidden');
  if (e instanceof ApiError && e.status === 413) return t('too_large');
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
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
