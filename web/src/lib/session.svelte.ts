import { api } from './api';
import type { ModelOption, Usage } from './types';

export const session = $state<{ me: Usage | null }>({ me: null });

export async function refreshMe() {
  try {
    session.me = await api.me();
  } catch {
    /* backend offline */
  }
}

export async function setConsent(on: boolean) {
  await api.consent(on);
  await refreshMe();
}

export type ModelKey = ModelOption['key'];
export type Reasoning = 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
export const REASONING: Reasoning[] = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];

// Shown until /api/me answers; the server sends the real ids from its config.
const FALLBACK_MODELS: ModelOption[] = [
  { key: 'contributor', id: 'muse-spark-1.3-contributor', available: true },
  { key: 'spark', id: 'muse-spark-1.3', available: true },
  { key: 'wonder', id: 'muse-wonder-1.0', available: false },
];
export const models = () => (session.me?.models?.length ? session.me.models : FALLBACK_MODELS);

/** "muse-spark-1.3-contributor" -> "Muse Spark 1.3 Contributor" */
export const modelName = (id: string) =>
  id
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');

function saved<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

// What the composer sends with each request; contributor is the default model.
export const prefs = $state<{ model: ModelKey; reasoning: Reasoning }>({
  model: saved('fw_model', ['contributor', 'spark', 'wonder'] as const, 'contributor'),
  reasoning: saved('fw_reasoning', REASONING, 'medium'),
});

export function setPref<K extends keyof typeof prefs>(key: K, value: (typeof prefs)[K]) {
  prefs[key] = value;
  try {
    localStorage.setItem(`fw_${key}`, value);
  } catch {
    /* storage unavailable */
  }
}
