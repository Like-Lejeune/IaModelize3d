// A recorded run's event log as a player's timeline: the moments it plays them at (long silences squeezed), and the marks
// on its scrubber. No state here; replay.svelte.ts plays it.
import type { EventRow } from './types';

/** A silence longer than this plays as this: the model thinking for a minute, or the person coming back a day later. */
export const MAX_GAP_S = 20;

export type MarkKind = 'ask' | 'question' | 'version' | 'board' | 'graph' | 'review' | 'done' | 'error';
export interface Mark {
  t: number;
  kind: MarkKind;
  seq: number;
  /** The version number of a 'version', 'board' or 'graph' mark. */
  n?: number;
}

type UserMessage = { id: string; role: string; text: string; data?: any; created_at: number };

/**
 * The log with the person's messages that have no event of their own (runs recorded before 'user.message' existed) put
 * in by their time, under negative seqs that no event has. The result is in time order.
 */
export function withMessages(events: EventRow[], messages: UserMessage[]): EventRow[] {
  const said = events.filter((e) => e.type === 'user.message');
  const extra: EventRow[] = [];
  for (const m of messages) {
    if (m.role !== 'user' || said.some((e) => e.data?.text === m.text && Math.abs(e.ts - m.created_at) < 600)) continue;
    extra.push({ seq: -1 - extra.length, type: 'user.message', data: { text: m.text, asset_ids: m.data?.asset_ids }, ts: m.created_at });
  }
  return extra.length ? [...events, ...extra].sort((a, b) => a.ts - b.ts) : events;
}

/** When each event plays, in seconds from the first, at 1×. */
export function clockOf(events: EventRow[]): number[] {
  const at: number[] = [];
  for (let i = 0; i < events.length; i++) at.push(i ? at[i - 1] + Math.min(Math.max(events[i].ts - events[i - 1].ts, 0), MAX_GAP_S) : 0);
  return at;
}

/** How many events have played by moment t: the index of the first one still to come. */
export function indexAfter(at: number[], t: number): number {
  let lo = 0;
  let hi = at.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (at[mid] <= t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function marksOf(events: EventRow[], at: number[]): Mark[] {
  const marks: Mark[] = [];
  events.forEach((e, i) => {
    const add = (kind: MarkKind, n?: number) => marks.push({ t: at[i], kind, seq: e.seq, ...(n != null ? { n } : {}) });
    const v = typeof e.data?.version === 'number' ? e.data.version : undefined;
    if (e.type === 'user.message') add('ask');
    else if (e.type === 'ask') add('question');
    else if (e.type === 'program.updated') add('version', v);
    else if (e.type === 'pcb.version') add('board', v);
    else if (e.type === 'device.version' && e.data?.author !== 'user') add('graph', v);
    else if (e.type === 'critic') add('review', v);
    else if (e.type === 'job.finished') add(e.data?.status === 'failed' ? 'error' : 'done');
    else if (e.type === 'error' || e.type === 'job.failed') add('error');
  });
  return marks;
}
