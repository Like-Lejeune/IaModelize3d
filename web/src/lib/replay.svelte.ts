// The replay player: plays a project's recorded event log into a ProjectStore in replay mode, here in the browser. The
// run's own project is only read, so watching makes no copy and spends nothing, and closing the project's link ends it.
// Going back starts the store over; a jump applies the events it passes over in one go, and only what the moment shows
// (its program, board and device document) is built.
import { api, errorText } from './api';
import { clockOf, indexAfter, marksOf, withMessages, type Mark } from './replaylog';
import type { ProjectStore } from './project.svelte';
import type { EventRow } from './types';

export const SPEEDS = [1, 4, 8, 20];
const TICK_MS = 100;

export class ReplayPlayer {
  loading = $state(true);
  error = $state<string | null>(null);
  /** The project has no recorded run: only its finished state to show. */
  empty = $state(false);
  playing = $state(false);
  finished = $state(false);
  speed = $state(8);
  /** Seconds into the timeline at 1×. */
  clock = $state(0);
  duration = $state(0);
  marks = $state.raw<Mark[]>([]);
  private events: EventRow[] = [];
  private at: number[] = [];
  /** The next event to play. */
  private pos = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private last = 0;
  private disposed = false;

  /** startSeq: open at that event, paused (a link to a moment); null plays from the start. */
  constructor(readonly store: ProjectStore, private readonly startSeq: number | null = null) {}

  async start() {
    try {
      const { events } = await api.replayLog(this.store.id);
      if (this.disposed) return;
      this.events = withMessages(events, this.store.detail?.messages ?? []);
      this.at = clockOf(this.events);
      this.duration = this.at.at(-1) ?? 0;
      this.marks = marksOf(this.events, this.at);
      this.empty = !this.events.length;
    } catch (e) {
      this.error = errorText(e);
      return;
    } finally {
      this.loading = false;
    }
    if (this.empty) return;
    api.replayView(this.store.id).catch(() => {});
    const from = this.startSeq == null ? -1 : this.events.findIndex((e) => e.seq === this.startSeq);
    if (from >= 0) this.seek(this.at[from]);
    else this.play();
  }

  dispose() {
    this.disposed = true;
    this.stop();
  }

  private stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.playing = false;
  }

  play() {
    if (this.playing || this.empty || this.loading || this.disposed) return;
    if (this.finished) this.seek(0);
    this.playing = true;
    this.last = performance.now();
    this.timer = setInterval(() => this.tick(), TICK_MS);
  }

  pause() {
    this.stop();
  }

  toggle() {
    if (this.playing) this.pause();
    else this.play();
  }

  private tick() {
    const t = performance.now();
    // a tab in the background wakes rarely: the run waits for it rather than jumping on
    const dt = Math.min(t - this.last, 1000) / 1000;
    this.last = t;
    this.clock = Math.min(this.clock + dt * this.speed, this.duration);
    const to = indexAfter(this.at, this.clock);
    while (this.pos < to) this.store.replayEvent(this.events[this.pos++], false);
    if (this.pos >= this.events.length) {
      this.stop();
      this.finished = true;
    }
  }

  /** Jump to a moment; a running playback goes on from there. */
  seek(t: number) {
    t = Math.max(0, Math.min(t, this.duration));
    const to = indexAfter(this.at, t);
    if (to < this.pos) {
      this.store.resetReplay();
      this.pos = 0;
    }
    while (this.pos < to) this.store.replayEvent(this.events[this.pos++], true);
    this.store.settleReplay();
    this.clock = t;
    this.finished = this.pos >= this.events.length && !this.playing;
    if (this.playing && this.pos >= this.events.length) {
      this.stop();
      this.finished = true;
    }
  }

  /** The mark after (or before) this moment. */
  step(dir: 1 | -1) {
    // a jump back from just past a mark goes to the one before it, not to it again
    const m = dir > 0 ? this.marks.find((x) => x.t > this.clock + 0.01) : this.marks.findLast((x) => x.t < this.clock - 1);
    if (m) this.seek(m.t);
    else if (dir > 0) this.seek(this.duration);
    else this.seek(0);
  }

  /** The address of this moment: the last event played. */
  momentUrl(): string {
    const e = this.events[this.pos - 1];
    return `${location.origin}/w/${this.store.id}${e && e.seq > 0 ? `?at=${e.seq}` : ''}`;
  }
}
