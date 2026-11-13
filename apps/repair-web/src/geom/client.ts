// Adapted from web/src/lib/geom/client.ts (Formwright): the same two worker lanes, for the React studio.
// Main-thread side of the geometry workers. Two lanes, each its own worker and WASM heap:
//   live  - previews while a slider or handle moves (latest wins, never blocked by checks)
//   final - full-quality build for display, then the full printability report; a stale
//           final build is cut short (the worker is replaced) when a newer one comes in
// Inputs (outlines, heightmaps, imported meshes) go to each worker once, not with every build.
import type { BuildError, BuildResult, CheckReport } from './types';

export interface BuildArgs {
  source: string;
  params?: Record<string, any>;
  printer?: any;
  vaseMode?: boolean;
}

type Reply = Record<string, any> & { id: number; ok: boolean; done?: boolean };

interface Job {
  msg: Record<string, any>;
  droppable: boolean; // a newer job of the same lane replaces it while queued
  preemptible: boolean; // a newer job may kill the worker running it
  timeout: number;
  onPartial?: (r: Reply) => void;
  resolve: (r: Reply) => void;
  started?: number;
  cold?: boolean; // the first job of a new worker: it also loads and compiles the WASM kernel
}

const superseded = (): Reply => ({ id: 0, ok: false, done: true, stage: 'superseded', message: 'superseded' });

class Lane {
  private worker: Worker | null = null;
  private current: Job | null = null;
  private currentId = 0;
  private queue: Job[] = [];
  private seq = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private sentInputs = '';
  private fresh = true;
  private closed = false;
  /** Typical duration of this lane's last jobs, ms. */
  typical = 0;

  constructor(
    private name: string,
    private inputs: () => { key: string; value: any },
  ) {}

  private spawn() {
    this.worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module', name: `geom-${this.name}` });
    this.fresh = true;
    this.sentInputs = '';
    this.worker.onmessage = (ev: MessageEvent<Reply>) => {
      const r = ev.data;
      const job = this.current;
      if (!job || r.id !== this.currentId) return;
      if (!r.done) {
        job.onPartial?.(r);
        return;
      }
      if (r.fatal) this.kill(); // its WASM kernel did not load: the next job gets a fresh worker
      this.finish(r);
    };
    this.worker.onerror = (ev) => {
      ev.preventDefault?.();
      this.kill();
      this.finish({ id: this.currentId, ok: false, done: true, stage: 'runtime', message: ev.message || 'geometry worker failed' });
    };
  }

  private kill() {
    this.worker?.terminate();
    this.worker = null;
  }

  private finish(r: Reply) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const job = this.current;
    this.current = null;
    if (job) {
      if (r.ok && job.started) {
        const ms = performance.now() - job.started;
        this.typical = this.typical ? this.typical * 0.5 + ms * 0.5 : ms;
      }
      job.resolve(r);
    }
    this.pump();
  }

  submit(job: Omit<Job, 'resolve'>): Promise<Reply> {
    // after dispose nothing may spawn a worker again
    if (this.closed) return Promise.resolve(superseded());
    return new Promise((resolve) => {
      const j: Job = { ...job, resolve };
      if (j.droppable)
        this.queue = this.queue.filter((q) => {
          if (!q.droppable) return true;
          q.resolve(superseded());
          return false;
        });
      // A stale final build that still has a while to go is cheaper to kill than to wait for,
      // unless the worker is still loading WASM: a new one would only start loading from scratch.
      const cur = this.current;
      if (cur && cur.preemptible && j.preemptible && cur.started && !cur.cold) {
        const left = (this.typical || 1000) - (performance.now() - cur.started);
        if (left > 400) {
          this.kill();
          this.current = null;
          if (this.timer) clearTimeout(this.timer);
          cur.resolve(superseded());
        }
      }
      this.queue.push(j);
      this.pump();
    });
  }

  private pump() {
    if (this.closed || this.current || !this.queue.length) return;
    const job = this.queue.shift()!;
    if (!this.worker) this.spawn();
    const inp = this.inputs();
    if (inp.key && inp.key !== this.sentInputs) {
      this.worker!.postMessage({ id: ++this.seq, type: 'inputs', key: inp.key, inputs: inp.value });
      this.sentInputs = inp.key;
    }
    this.current = job;
    this.currentId = ++this.seq;
    job.started = performance.now();
    // the first job of a new worker also loads and compiles the WASM kernel
    job.cold = this.fresh;
    const grace = this.fresh ? 20000 : 0;
    this.fresh = false;
    this.timer = setTimeout(() => {
      this.kill();
      this.finish({ id: this.currentId, ok: false, done: true, stage: 'timeout', message: `geometry took longer than ${Math.round(job.timeout / 1000)} s` });
    }, job.timeout + grace);
    this.worker!.postMessage({ ...job.msg, id: this.currentId, inputsKey: inp.key || undefined });
  }

  dispose() {
    this.closed = true;
    this.kill();
    if (this.timer) clearTimeout(this.timer);
    for (const q of this.queue) q.resolve(superseded());
    this.queue = [];
    this.current?.resolve(superseded());
    this.current = null;
  }
}

export class GeomClient {
  private inputsKey = '';
  private inputsValue: any = undefined;
  private inputsSeq = 0;
  private live = new Lane('live', () => ({ key: this.inputsKey, value: this.inputsValue }));
  private final = new Lane('final', () => ({ key: this.inputsKey, value: this.inputsValue }));

  /** Inputs for the following builds; sent to each worker once. */
  setInputs(value: any) {
    this.inputsValue = value;
    this.inputsKey = value && Object.keys(value).length ? `i${++this.inputsSeq}` : '';
  }

  /** How long a full-quality build of the current program takes, ms (0 = unknown). */
  get finalMs() {
    return this.final.typical;
  }

  /** Fast build for a moving slider. Coarse meshing for heavy programs, no full checks. */
  async preview(args: BuildArgs & { quality: 'preview' | 'final' }): Promise<BuildResult | BuildError> {
    const r = await this.live.submit({
      msg: { type: 'build', ...args, analyze: args.quality === 'final' ? 'fast' : 'none', heat: true, edges: args.quality === 'final' },
      droppable: true,
      preemptible: false,
      timeout: 30000,
    });
    return r as unknown as BuildResult | BuildError;
  }

  /**
   * Full-quality build: `onDisplay` gets the viewer buffers as soon as the model is built,
   * the promise resolves with the full printability report afterwards.
   */
  async finalize(args: BuildArgs, onDisplay: (r: BuildResult) => void): Promise<{ ok: true; checks: CheckReport } | BuildError> {
    const r = await this.final.submit({
      msg: { type: 'build', ...args, quality: 'final', analyze: 'full', heat: true, edges: true },
      droppable: true,
      preemptible: true,
      timeout: 180000,
      onPartial: (p) => p.ok && onDisplay(p as unknown as BuildResult),
    });
    if (r.ok && r.kind === 'display') onDisplay(r as unknown as BuildResult);
    return r as any;
  }

  async exportFile(args: BuildArgs & { format: 'stl' | '3mf'; title?: string }): Promise<Blob> {
    const r = await this.live.submit({ msg: { type: 'export', ...args }, droppable: false, preemptible: false, timeout: 120000 });
    if (!r.ok || !r.bytes) throw new Error(r.message ?? 'export failed');
    return new Blob([r.bytes as BlobPart], { type: r.mime });
  }

  dispose() {
    this.live.dispose();
    this.final.dispose();
  }
}
