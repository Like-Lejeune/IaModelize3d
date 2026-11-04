import { api } from './api';
import { t } from './i18n.svelte';
import { isContributor, modelName as friendlyName } from './models';
import type { ModelOption, Usage } from './types';

export const session = $state<{ me: Usage | null }>({ me: null });

export async function refreshMe() {
  try {
    session.me = await api.me();
  } catch {
    /* backend offline */
  }
}

export type ModelKey = ModelOption['key'];
export type Reasoning = 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
export const REASONING: Reasoning[] = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];

// Shown until /api/me answers; the server sends the real ids from its config (Spark Open only when it is configured).
const FALLBACK_MODELS: ModelOption[] = [
  { key: 'contributor', id: 'muse-spark-1.3-contributor', available: true },
  { key: 'spark', id: 'muse-spark-1.3', available: true },
  { key: 'wonder', id: 'muse-wonder-1.0', available: true },
  { key: 'spark_open', id: 'meta-models/muse-spark-open-1026', available: true },
];
export const models = () => (session.me?.models?.length ? session.me.models : FALLBACK_MODELS);

/** "muse-spark-1.3-contributor" -> "Muse Spark 1.3 · contributor": the same model, on the tier that may train Meta models */
export const modelName = (id: string) => (isContributor(id) ? `${friendlyName(id)} · ${t('contributor_tag')}` : friendlyName(id));

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
  model: saved('fw_model', ['contributor', 'spark', 'wonder', 'spark_open'] as const, 'contributor'),
  reasoning: saved('fw_reasoning', REASONING, 'medium'),
});

/** The picked model, or the default one when the plan does not include it. */
export const chosenModel = (): ModelKey => (models().find((m) => m.key === prefs.model)?.available ? prefs.model : 'contributor');

export function setPref<K extends keyof typeof prefs>(key: K, value: (typeof prefs)[K]) {
  prefs[key] = value;
  try {
    localStorage.setItem(`fw_${key}`, value);
  } catch {
    /* storage unavailable */
  }
}
