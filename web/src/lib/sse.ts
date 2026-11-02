// Server-sent events over fetch: catches every named event type, resumes from the
// last seq after network drops (server also honours Last-Event-ID).
import type { EventRow } from './types';

// The server pings every 15 s. A stream silent for longer is dead without having said so (a dev proxy whose API
// restarted, a laptop that slept): drop it and reconnect.
const IDLE_MS = 40_000;

export interface EventStream {
  close(): void;
}

export function streamEvents(projectId: string, after: number, onEvent: (e: EventRow) => void, onState?: (s: 'open' | 'retry') => void): EventStream {
  let last = after;
  let closed = false;
  let ctrl: AbortController | null = null;
  let delay = 500;
  let idle: ReturnType<typeof setTimeout> | undefined;

  const run = async () => {
    while (!closed) {
      const mine = (ctrl = new AbortController());
      const kick = () => {
        clearTimeout(idle);
        idle = setTimeout(() => mine.abort(), IDLE_MS);
      };
      try {
        kick();
        const res = await fetch(`/api/projects/${projectId}/events?after=${last}`, {
          headers: { Accept: 'text/event-stream', 'Last-Event-ID': String(last) },
          credentials: 'same-origin',
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) throw new Error(`events ${res.status}`);
        onState?.('open');
        delay = 500;
        kick();
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        let buf = '';
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          kick();
          buf += value;
          let idx: number;
          while ((idx = buf.indexOf('\n\n')) >= 0) {
            const block = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const data = block
              .split('\n')
              .filter((l) => l.startsWith('data:'))
              .map((l) => l.slice(5).trimStart())
              .join('\n');
            if (!data) continue;
            try {
              const row = JSON.parse(data) as EventRow;
              if (typeof row.seq === 'number') last = Math.max(last, row.seq);
              onEvent(row);
            } catch {
              /* malformed block */
            }
          }
        }
      } catch (e) {
        if (closed) return;
      } finally {
        clearTimeout(idle);
      }
      if (closed) return;
      onState?.('retry');
      await new Promise((r) => setTimeout(r, delay));
      delay = Math.min(delay * 2, 8000);
    }
  };
  run();
  return {
    close() {
      closed = true;
      ctrl?.abort();
    },
  };
}
