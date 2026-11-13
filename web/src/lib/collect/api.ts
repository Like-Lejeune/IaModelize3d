// Snap & collect without the agent (server/iamodelize3d/collect.py): the instant sticker, "keep" and the
// collection plate. Over $lib/api's request; errors are its ApiError, so errorText() still applies.
import { ApiError, errorText, req as apiReq } from '$lib/api';
import type { ProjectOut } from '$lib/types';
import { ct } from './i18n';

/** Program inputs of one sticker (vision/relief.py): loops in photo pixels, a relief over the crop. */
export interface StickerInputs {
  outlines: Record<string, [number, number][][]>;
  heightmaps: Record<string, { w: number; h: number; data: number[] }>;
  values: Record<string, number | string>;
}

export interface StickerPayload {
  key: string; // selection + detail: unchanged key, unchanged sticker
  selection_id: string;
  source: string; // a lib.collect.sticker program
  inputs: StickerInputs;
  params: { size: number };
  size_mm: [number, number]; // the figure's outline at params.size
  detail: number; // 0 for people
  ms?: number;
}

/** Grams and minutes as Orca would slice them on the farm's A1, and the farm's price in tenge (USD next to it). */
export interface Estimate {
  grams: number;
  minutes: number;
  grams_range: [number, number];
  minutes_range: [number, number];
  source: string;
  price?: {
    currency: string;
    print: number;
    delivery: number;
    total: number;
    usd: { rate: number; print: number; delivery: number; total: number };
    binding: boolean;
  };
}

export interface KeepResult {
  version: number;
  cover: string;
  size_mm: number[];
  ok: boolean;
  score: number | null;
  issues: string[];
  est: Estimate;
  project: ProjectOut;
}

export interface PlateResult {
  project_id: string;
  project: ProjectOut;
  fits: boolean;
  bed: [number, number];
  printer: string | null;
  a1_mini: boolean; // also fits the 180 x 180 bed of an A1 mini
  size_mm: number[];
  count: number;
  skipped: string[];
  ok: boolean;
  score: number | null;
  est: Estimate;
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const out = await apiReq<T>(method, path, body);
  // the one picture aside, these answer JSON: anything else is a proxy's page, not an answer
  if (out instanceof Blob && !path.endsWith('.png')) throw new ApiError(502, 'not a JSON answer', 'offline');
  return out;
}

export const collectApi = {
  /** The current selection's sticker; with `have` (a key) the server answers {same: true} when nothing changed. */
  sticker: (id: string, have?: string) =>
    req<StickerPayload | { key: string; same: true }>('GET', `/api/snap/${id}/sticker${have ? `?have=${encodeURIComponent(have)}` : ''}`),
  /** The same sticker rendered on the server, for a phone whose own build is too slow. */
  stickerPng: (id: string, body: { size: number; label?: string | null }) => req<Blob>('POST', `/api/snap/${id}/sticker.png`, body),
  keep: (id: string, body: { label?: string; size: number }) => req<KeepResult>('POST', `/api/snap/${id}/keep`, body),
  plate: (body: { ids: string[]; size_mm?: number; gap?: number }) => req<PlateResult>('POST', '/api/collection/plate', body),
};

// this feature's error codes; everything else reads as the app's own errors
const CODES: Record<string, string> = {
  plate_too_big: 'err_plate_too_big',
  project_busy: 'err_keep_busy',
  nothing_to_plate: 'err_nothing_to_plate',
  no_selection: 'err_no_selection',
  no_sticker: 'err_no_selection',
};

export function collectError(e: unknown): string {
  if (e instanceof ApiError && e.code && CODES[e.code]) return ct(CODES[e.code]);
  return errorText(e);
}
