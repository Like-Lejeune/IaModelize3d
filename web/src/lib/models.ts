// Meta models by the names people know, and what each one did in a run. The job meter
// (server/iamodelize3d/llm/client.py CostMeter) counts calls and purposes per model id.
import type { JobCost } from './types';

const NAMES: [RegExp, string | ((m: RegExpMatchArray) => string)][] = [
  [/muse[-_ ]spark[-_ ]open/i, 'Muse Spark Open'],
  [/glimmer/i, 'Muse Glimmer'],
  [/^muse-spark-(\d+(?:\.\d+)?)/i, (m) => `Muse Spark ${m[1]}`],
  [/^muse-wonder/i, 'Muse Wonder'],
  [/^muse-image/i, 'Muse Image'],
  [/voice/i, 'Muse Voice Transcribe'],
  [/^sam[-_ ]?(\d+(?:\.\d+)?)/i, (m) => `SAM ${m[1]}`],
];

/** "muse-spark-1.3-contributor" -> "Muse Spark 1.3", "meta-models/muse-spark-open-1026" -> "Muse Spark Open" */
export function modelName(id: string): string {
  const bare = id.replace(/^.*\//, '');
  for (const [re, out] of NAMES) {
    const m = bare.match(re);
    if (m) return typeof out === 'string' ? out : out(m);
  }
  return bare
    .split(/[-_]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/** Served from published weights (Baseten, a self-hosted vLLM), not the Meta API. */
export const isOpenWeights = (id: string) => /^meta-models\//i.test(id) || /spark[-_ ]open|glimmer/i.test(id);

/** The cheaper tier whose requests may help train future Meta models. */
export const isContributor = (id: string) => /-contributor$/i.test(id);

// 'classify' is a shop order's intake; 'task' is a design run's first read of the request (pack, title, safety)
export const ROLES = ['designer', 'critic', 'measure', 'search', 'image', 'voice', 'classify', 'task', 'translate'] as const;
export type ModelRole = (typeof ROLES)[number];

// purposes the server tags its calls with (server/iamodelize3d/llm/client.py: the json() name or purpose)
// -> the role shown on the chip (i18n `model_role.*`)
const ROLE_OF: Record<string, ModelRole> = {
  designer: 'designer', video: 'designer', critic: 'critic', search: 'search', facts: 'search',
  concept: 'image', edit: 'image', voice: 'voice', classify: 'task', intake: 'classify', snap_name: 'classify', english: 'translate',
  detect: 'measure', ground: 'measure', caliper: 'measure', tap: 'measure', box: 'measure', 'board identification': 'measure',
};

/**
 * What a call with this purpose did; SAM calls carry their text prompt as the purpose, so any SAM call measures.
 * `intake`: the call was part of a shop order's intake (Spark's 'intake' read and the open model's 'classify' second
 * opinion), where 'classify' reads the order; in a design run it only routes the request.
 */
export function roleOf(id: string, purpose?: string | null, intake = false): ModelRole | null {
  if (/^sam/i.test(id.replace(/^.*\//, ''))) return 'measure';
  if (purpose === 'classify' && intake) return 'classify';
  if (purpose && ROLE_OF[purpose]) return ROLE_OF[purpose];
  if (/^muse-image/i.test(id)) return 'image';
  if (/voice/i.test(id)) return 'voice';
  return null;
}

export interface ModelUse {
  name: string;
  ids: string[];
  calls: number;
  usd: number;
  roles: ModelRole[];
  open: boolean;
}

/**
 * One entry per model across one or more jobs, the busiest first. Ids that read the same
 * ("muse-spark-1.3" and its contributor tier) share an entry. Runs recorded before calls were
 * counted have only by_model (USD), so their models show without a count.
 */
export function modelUsage(costs: JobCost | (JobCost | null | undefined)[] | null | undefined): ModelUse[] {
  const out = new Map<string, ModelUse>();
  for (const c of Array.isArray(costs) ? costs : [costs]) {
    if (!c) continue;
    const intake = Object.values(c.purposes_by_model ?? {}).some((p) => 'intake' in (p ?? {}));
    for (const id of new Set([...Object.keys(c.calls_by_model ?? {}), ...Object.keys(c.by_model ?? {})])) {
      const name = modelName(id);
      const u = out.get(name) ?? { name, ids: [], calls: 0, usd: 0, roles: [], open: false };
      if (!u.ids.includes(id)) u.ids.push(id);
      u.calls += c.calls_by_model?.[id] ?? 0;
      u.usd += c.by_model?.[id] ?? 0;
      u.open ||= isOpenWeights(id);
      const purposes = Object.keys(c.purposes_by_model?.[id] ?? {});
      for (const r of (purposes.length ? purposes : [null]).map((p) => roleOf(id, p, intake))) if (r && !u.roles.includes(r)) u.roles.push(r);
      out.set(name, u);
    }
  }
  for (const u of out.values()) u.roles.sort((a, b) => ROLES.indexOf(a) - ROLES.indexOf(b));
  return [...out.values()].sort((a, b) => b.calls - a.calls || b.usd - a.usd);
}

/** "$0.004", "$0.12": small spends keep a significant digit. */
export const fmtUsd = (usd: number) => `$${usd >= 0.1 ? usd.toFixed(2) : usd >= 0.01 ? usd.toFixed(3) : usd > 0 ? usd.toPrecision(1) : '0'}`;
