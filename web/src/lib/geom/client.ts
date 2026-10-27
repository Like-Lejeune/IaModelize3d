// Main-thread side of the geometry worker: latest-wins build queue and a watchdog
// that restarts the worker when a program hangs.
import type { BuildError, BuildResult } from '../types';

type Pending = { resolve: (v: any) => void; reject: (e: any) => void; timer: ReturnType<typeof setTimeout> };

export interface BuildArgs {
  source: string;
  params?: Record<string, any>;
  inputs?: any;
  printer?: any;
  level?: 'none' | 'fast' | 'full';
  vaseMode?: boolean;
}

export class GeomClient {
  private worker: Worker | null = null;
  private seq = 0;
  private pending = new Map<number, Pending>();
  private busy = false;
  private queued: { args: BuildArgs; resolve: (v: BuildResult | BuildError) => void } | null = null;
  timeoutMs = 5000;

  private spawn() {
    this.worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
    this.worker.onmessage = (ev) => {
      const p = this.pending.get(ev.data.id);
      if (!p) return;
      clearTimeout(p.timer);
      this.pending.delete(ev.data.id);
      p.resolve(ev.data);
    };
    this.worker.onerror = (ev) => {
      for (const [, p] of this.pending) {
        clearTimeout(p.timer);
        p.reject(new Error(ev.message || 'geometry worker failed'));
      }
      this.pending.clear();
      this.restart();
    };
  }

  private restart() {
    this.worker?.terminate();
    this.worker = null;
  }

  private call<T>(msg: Record<string, any>, timeout = this.timeoutMs): Promise<T> {
    if (!this.worker) this.spawn();
    const id = ++this.seq;
    return new Promise<T>((resolve, reject) => {
      // the first call also loads wasm, so give it extra time
      const timer = setTimeout(() => {
        this.pending.delete(id);
        this.restart();
        reject(new Error(`geometry took longer than ${Math.round(timeout / 1000)} s`));
      }, timeout + (this.seq === 1 ? 10000 : 0));
      this.pending.set(id, { resolve, reject, timer });
      this.worker!.postMessage({ ...msg, id });
    });
  }

  /** Latest-wins: while a build runs, only the newest request is kept. */
  build(args: BuildArgs): Promise<BuildResult | BuildError> {
    return new Promise((resolve) => {
      if (this.busy) {
        this.queued?.resolve({ ok: false, stage: 'superseded', message: 'superseded' });
        this.queued = { args, resolve };
        return;
      }
      this.run(args, resolve);
    });
  }

  private async run(args: BuildArgs, resolve: (v: BuildResult | BuildError) => void) {
    this.busy = true;
    try {
      resolve(await this.call<BuildResult | BuildError>({ type: 'build', ...args }, args.level === 'full' ? 20000 : this.timeoutMs));
    } catch (e: any) {
      resolve({ ok: false, stage: 'timeout', message: e?.message ?? String(e) });
    } finally {
      this.busy = false;
      const next = this.queued;
      this.queued = null;
      if (next) this.run(next.args, next.resolve);
    }
  }

  async exportFile(args: BuildArgs & { format: 'stl' | '3mf'; title?: string }): Promise<Blob> {
    const r = await this.call<{ ok: boolean; bytes?: Uint8Array; mime?: string; message?: string }>({ type: 'export', ...args }, 30000);
    if (!r.ok || !r.bytes) throw new Error(r.message ?? 'export failed');
    return new Blob([r.bytes as BlobPart], { type: r.mime });
  }

  dispose() {
    this.restart();
  }
}
