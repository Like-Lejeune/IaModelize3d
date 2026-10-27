// Project state for the studio and recipe pages: server detail + event timeline +
// the live local build of the current program.
import { api, errorText } from './api';
import { GeomClient } from './geom/client';
import { streamEvents, type EventStream } from './sse';
import type { AssetOut, BuildResult, CheckReport, EventRow, ProjectDetail, SelectionOut } from './types';

export type TimelineItem =
  | { kind: 'user'; key: string; ts: number; text: string; assets?: string[] }
  | { kind: 'agent'; key: string; ts: number; text: string }
  | { kind: 'status'; key: string; ts: number; text: string }
  | { kind: 'thinking'; key: string; ts: number; text: string }
  | { kind: 'tool'; key: string; ts: number; id: string; name: string; args: any; result?: { ok: boolean; summary?: string; image?: string } }
  | { kind: 'critic'; key: string; ts: number; verdict: string; issues: { severity: string; text: string }[]; render?: string }
  | { kind: 'ask'; key: string; ts: number; job_id: string; question_id: string; question: string; options: string[]; allow_text: boolean; answered?: string }
  | { kind: 'facts'; key: string; ts: number; items: any[] }
  | { kind: 'program'; key: string; ts: number; version: number; summary?: string; render?: string; author?: string }
  | { kind: 'job'; key: string; ts: number; status: string; summary?: string; cost?: any }
  | { kind: 'concepts'; key: string; ts: number; images: { url: string; prompt?: string }[] }
  | { kind: 'variants'; key: string; ts: number; items: { version: number; render?: string; summary?: string }[] }
  | { kind: 'slice'; key: string; ts: number; data: any }
  | { kind: 'probe'; key: string; ts: number; data: any }
  | { kind: 'asset'; key: string; ts: number; asset: AssetOut }
  | { kind: 'error'; key: string; ts: number; text: string };

export class ProjectStore {
  id: string;
  detail = $state<ProjectDetail | null>(null);
  loadError = $state<string | null>(null);
  timeline = $state<TimelineItem[]>([]);
  // program
  source = $state<string | null>(null);
  version = $state(0);
  inputs = $state<any>({});
  values = $state<Record<string, any>>({});
  build = $state<BuildResult | null>(null);
  buildError = $state<string | null>(null);
  building = $state(false);
  fullChecks = $state<CheckReport | null>(null);
  // agent
  jobId = $state<string | null>(null);
  jobKind = $state<string | null>(null);
  status = $state<string | null>(null);
  cost = $state<{ usd: number; tokens_in?: number; tokens_out?: number; cached?: number } | null>(null);
  // side results
  concepts = $state<{ url: string; prompt?: string }[]>([]);
  variants = $state<{ version: number; render?: string; summary?: string }[]>([]);
  slice = $state<any>(null);
  probe = $state<any>(null);
  scenes = $state<Record<string, any>>({});
  connection = $state<'open' | 'retry' | 'idle'>('idle');
  lastRender = $state<string | null>(null);

  geom = new GeomClient();
  private stream: EventStream | null = null;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private fullTimer: ReturnType<typeof setTimeout> | null = null;
  private seen = new Set<number>();
  readonly: boolean;

  constructor(id: string, readonly = false) {
    this.id = id;
    this.readonly = readonly;
  }

  get assets(): AssetOut[] {
    return this.detail?.assets ?? [];
  }
  get selections(): SelectionOut[] {
    return this.detail?.selections ?? [];
  }
  get checks(): CheckReport | null {
    return this.fullChecks ?? this.build?.checks ?? null;
  }
  get running(): boolean {
    return !!this.jobId;
  }

  async load() {
    try {
      const d = await api.project(this.id);
      this.detail = d;
      for (const m of d.messages) {
        if (m.role === 'user') this.timeline.push({ kind: 'user', key: `m${m.id}`, ts: m.created_at, text: m.text, assets: m.data?.asset_ids });
      }
      if (d.program) {
        this.source = d.program.source;
        this.version = d.program.version;
        this.inputs = d.program.inputs ?? {};
        this.values = { ...(d.program.params ?? {}) };
        if (d.program.checks) this.fullChecks = d.program.checks;
        this.rebuild('full');
      }
      if (d.job && d.job.status === 'running') {
        this.jobId = d.job.id;
        this.jobKind = d.job.kind;
      }
      if (!this.readonly) this.connect();
    } catch (e) {
      this.loadError = errorText(e);
    }
  }

  connect() {
    this.stream?.close();
    this.stream = streamEvents(this.id, 0, (e) => this.onEvent(e), (s) => (this.connection = s));
  }

  dispose() {
    this.stream?.close();
    this.geom.dispose();
    if (this.saveTimer) clearTimeout(this.saveTimer);
    if (this.fullTimer) clearTimeout(this.fullTimer);
  }

  private push(item: TimelineItem) {
    this.timeline.push(item);
    this.timeline.sort((a, b) => a.ts - b.ts);
  }

  private onEvent(e: EventRow) {
    if (this.seen.has(e.seq)) return;
    this.seen.add(e.seq);
    const d = e.data ?? {};
    const key = `e${e.seq}`;
    const ts = e.ts;
    switch (e.type) {
      case 'job.started':
        this.jobId = d.job_id ?? e.job_id ?? null;
        this.jobKind = d.kind ?? null;
        this.status = null;
        break;
      case 'job.finished':
        if (!d.job_id || d.job_id === this.jobId) {
          this.jobId = null;
          this.jobKind = null;
          this.status = null;
        }
        this.push({ kind: 'job', key, ts, status: d.status, summary: d.summary, cost: d.cost });
        for (const it of this.timeline) if (it.kind === 'ask' && it.job_id === d.job_id && !it.answered) it.answered = '—';
        break;
      case 'user.message':
        if (!this.timeline.some((t) => t.kind === 'user' && t.text === d.text && Math.abs(t.ts - ts) < 30))
          this.push({ kind: 'user', key, ts, text: d.text, assets: d.asset_ids });
        break;
      case 'agent.message':
        this.push({ kind: 'agent', key, ts, text: d.text ?? '' });
        break;
      case 'agent.status':
        this.status = d.text ?? null;
        this.push({ kind: 'status', key, ts, text: d.text ?? '' });
        break;
      case 'agent.thinking':
        this.push({ kind: 'thinking', key, ts, text: d.text ?? '' });
        break;
      case 'tool.call':
        this.push({ kind: 'tool', key, ts, id: d.id ?? key, name: d.name ?? 'tool', args: d.args });
        break;
      case 'tool.result': {
        const call = [...this.timeline].reverse().find((t) => t.kind === 'tool' && (t.id === d.id || (!d.id && t.name === d.name && !t.result)));
        if (call && call.kind === 'tool') call.result = { ok: d.ok !== false, summary: d.summary, image: d.image };
        else this.push({ kind: 'tool', key, ts, id: d.id ?? key, name: d.name ?? 'tool', args: null, result: { ok: d.ok !== false, summary: d.summary, image: d.image } });
        if (d.image) this.lastRender = d.image;
        break;
      }
      case 'program.updated':
        this.onProgram(d);
        this.push({ kind: 'program', key, ts, version: d.version, summary: d.summary, render: d.render, author: d.author });
        if (d.render) this.lastRender = d.render;
        break;
      case 'critic':
        this.push({ kind: 'critic', key, ts, verdict: d.verdict ?? 'revise', issues: d.issues ?? [], render: d.render });
        break;
      case 'ask':
        this.push({ kind: 'ask', key, ts, job_id: d.job_id ?? e.job_id ?? '', question_id: d.question_id ?? key, question: d.question ?? '', options: d.options ?? [], allow_text: d.allow_text !== false });
        break;
      case 'answer': {
        const q = this.timeline.find((t) => t.kind === 'ask' && t.question_id === d.question_id);
        if (q && q.kind === 'ask') q.answered = d.answer;
        break;
      }
      case 'facts':
        this.push({ kind: 'facts', key, ts, items: d.items ?? [] });
        break;
      case 'scene':
        if (d.asset_id) {
          this.scenes[d.asset_id] = d;
          const a = this.detail?.assets.find((x) => x.id === d.asset_id);
          if (a && d.calibration) a.meta = { ...a.meta, calibration: d.calibration };
        }
        break;
      case 'asset.added':
        if (this.detail && !this.detail.assets.some((a) => a.id === d.id)) this.detail.assets.push(d as AssetOut);
        break;
      case 'selection.added':
        if (this.detail && !this.detail.selections.some((s) => s.id === d.id)) this.detail.selections.push(d as SelectionOut);
        break;
      case 'selection.removed':
        if (this.detail) this.detail.selections = this.detail.selections.filter((s) => s.id !== d.id);
        break;
      case 'concepts':
        this.concepts = d.images ?? [];
        this.push({ kind: 'concepts', key, ts, images: d.images ?? [] });
        break;
      case 'variants':
        this.variants = d.items ?? [];
        this.push({ kind: 'variants', key, ts, items: d.items ?? [] });
        break;
      case 'slice':
        this.slice = d;
        this.push({ kind: 'slice', key, ts, data: d });
        break;
      case 'probe':
        this.probe = d;
        this.push({ kind: 'probe', key, ts, data: d });
        break;
      case 'cost':
        this.cost = d as any;
        break;
      case 'error':
      case 'job.failed':
        this.push({ kind: 'error', key, ts, text: d.message ?? d.error ?? 'error' });
        break;
      default:
        break;
    }
  }

  private async onProgram(d: any) {
    if (typeof d.version !== 'number' || d.version < this.version) return;
    const sameUserSave = d.author === 'user' && d.version === this.version + 1 && this.source && !d.source;
    this.version = d.version;
    if (this.detail) this.detail.version = d.version;
    if (sameUserSave) {
      if (d.checks) this.fullChecks = d.checks;
      return;
    }
    let source: string | undefined = d.source;
    let inputs = d.inputs;
    if (!source) {
      try {
        const p = await api.program(this.id, d.version);
        source = p.source;
        inputs = p.inputs;
        if (!d.params) d.params = p.params;
      } catch {
        return;
      }
    }
    this.source = source ?? this.source;
    if (inputs) this.inputs = inputs;
    this.values = { ...(d.params ?? {}) };
    this.fullChecks = d.checks ?? null;
    this.rebuild('full');
  }

  async rebuild(level: 'fast' | 'full' = 'fast') {
    if (!this.source) return;
    this.building = true;
    const r = await this.geom.build({ source: this.source, params: $state.snapshot(this.values), inputs: $state.snapshot(this.inputs), level });
    if (!r.ok) {
      if (r.stage !== 'superseded') this.buildError = `${r.stage}: ${r.message}`;
      this.building = false;
      return;
    }
    this.buildError = null;
    this.build = r;
    if (level === 'full') this.fullChecks = r.checks ?? null;
    else this.fullChecks = null;
    // parameters the program clamped/rounded
    for (const [k, v] of Object.entries(r.params)) if (this.values[k] !== v) this.values[k] = v;
    this.building = false;
  }

  /** Slider/handle moved: fast local rebuild now, full checks + save after release. */
  setParam(name: string, value: any, commit = false) {
    this.values[name] = value;
    this.rebuild('fast');
    if (commit) this.commit();
  }

  commit() {
    if (this.fullTimer) clearTimeout(this.fullTimer);
    this.fullTimer = setTimeout(() => this.rebuild('full'), 400);
    if (this.readonly) return;
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(async () => {
      try {
        await api.saveParams(this.id, $state.snapshot(this.values));
      } catch (e) {
        this.push({ kind: 'error', key: `save${Date.now()}`, ts: Date.now() / 1000, text: errorText(e) });
      }
    }, 600);
  }

  async send(text: string, assetIds: string[] = [], effort: 'auto' | 'hard' = 'auto') {
    const ts = Date.now() / 1000;
    this.push({ kind: 'user', key: `local${ts}`, ts, text, assets: assetIds });
    try {
      const r = await api.send(this.id, text, assetIds, effort);
      this.jobId = r.job_id;
      this.jobKind = 'design';
    } catch (e) {
      this.push({ kind: 'error', key: `err${ts}`, ts: ts + 0.001, text: errorText(e) });
    }
  }

  async answer(item: Extract<TimelineItem, { kind: 'ask' }>, answer: string) {
    try {
      await api.answer(item.job_id, answer);
      item.answered = answer;
    } catch (e) {
      this.push({ kind: 'error', key: `err${Date.now()}`, ts: Date.now() / 1000, text: errorText(e) });
    }
  }

  async cancel() {
    if (!this.jobId) return;
    try {
      await api.cancel(this.jobId);
    } finally {
      this.jobId = null;
    }
  }

  async startSide(fn: () => Promise<{ job_id: string }>) {
    try {
      const r = await fn();
      this.jobId = r.job_id;
    } catch (e) {
      this.push({ kind: 'error', key: `err${Date.now()}`, ts: Date.now() / 1000, text: errorText(e) });
    }
  }

  addError(text: string) {
    this.push({ kind: 'error', key: `err${Date.now()}${Math.random()}`, ts: Date.now() / 1000, text });
  }
}
