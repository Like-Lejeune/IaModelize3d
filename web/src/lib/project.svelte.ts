// Project state for the studio and recipe pages: server detail + event log grouped by
// job + the live local build of the current program.
import { api, errorText } from './api';
import { GeomClient } from './geom/client';
import { t } from './i18n.svelte';
import { streamEvents, type EventStream } from './sse';
import { KIND_STAGE, kindOf } from './steps';
import type { AssetOut, BuildResult, CheckReport, EventRow, ProjectDetail, SelectionOut } from './types';

type Base = { key: string; ts: number; job?: string | null };
// older servers passed the model's options through as {label, value} objects
const optionLabel = (o: any): string => (typeof o === 'string' ? o : String(o?.label ?? o?.value ?? ''));

export type TimelineItem =
  | (Base & { kind: 'user'; text: string; assets?: string[] })
  | (Base & { kind: 'agent'; text: string })
  | (Base & { kind: 'status'; text: string })
  | (Base & { kind: 'thinking'; text: string })
  | (Base & { kind: 'tool'; id: string; name: string; tkind: string; title?: string; args: any; result?: { ok: boolean; summary?: string; image?: string; title?: string } })
  | (Base & { kind: 'critic'; verdict: string; score?: number | null; issues: { severity: string; text: string; fix_hint?: string }[]; render?: string })
  | (Base & { kind: 'ask'; job_id: string; question_id: string; question: string; options: string[]; allow_text: boolean; answered?: string })
  | (Base & { kind: 'facts'; items: any[] })
  | (Base & { kind: 'program'; version: number; summary?: string; render?: string; author?: string })
  | (Base & { kind: 'concepts'; images: { url: string; prompt?: string; asset_id?: string }[] })
  | (Base & { kind: 'variants'; items: { version: number; render?: string; summary?: string }[] })
  | (Base & { kind: 'slice'; data: any })
  | (Base & { kind: 'probe'; data: any })
  | (Base & { kind: 'memory'; items: { kind: string; name: string }[] })
  | (Base & { kind: 'error'; text: string });

export interface ResultCard {
  version?: number;
  title?: string;
  size_mm?: number[];
  est_grams?: number;
  est_minutes?: number;
  params_with_sources?: { name: string; label?: string; value: any; unit?: string; source?: string }[];
  checks?: { ok?: boolean; errors?: number; warnings?: number; score?: number };
  critic?: { verdict?: string; match_score?: number | null; issues?: any[] } | null;
  cover?: string;
  render?: string;
  cost_usd?: number;
  next?: { action: string; label?: string }[];
}

export interface JobInfo {
  id: string;
  kind: string;
  status: string; // running | waiting | done | failed | cancelled | budget | refused
  stage: string | null;
  reached: string[];
  started: number;
  finished?: number;
  cost?: { usd: number; tokens_in?: number; tokens_out?: number; cached?: number; cache_ratio?: number } | null;
  summary?: string | null;
  result?: ResultCard | null;
  model?: string;
}

export class ProjectStore {
  id: string;
  detail = $state<ProjectDetail | null>(null);
  loadError = $state<string | null>(null);
  timeline = $state<TimelineItem[]>([]);
  jobs = $state<Record<string, JobInfo>>({});
  // program
  source = $state<string | null>(null);
  version = $state(0);
  inputs = $state<any>({});
  values = $state<Record<string, any>>({});
  agentValues = $state<Record<string, any>>({});
  build = $state<BuildResult | null>(null);
  buildError = $state<string | null>(null);
  building = $state(false);
  fullChecks = $state<CheckReport | null>(null);
  // agent
  jobId = $state<string | null>(null);
  jobKind = $state<string | null>(null);
  status = $state<string | null>(null);
  cost = $state<{ usd: number; tokens_in?: number; tokens_out?: number; cached?: number } | null>(null);
  // composer attachments (uploaded, not yet sent)
  tray = $state<AssetOut[]>([]);
  // side results
  concepts = $state<{ url: string; prompt?: string; asset_id?: string }[]>([]);
  variants = $state<{ version: number; render?: string; summary?: string }[]>([]);
  slice = $state<any>(null);
  probe = $state<any>(null);
  scenes = $state<Record<string, any>>({});
  connection = $state<'open' | 'retry' | 'idle'>('idle');
  lastRender = $state<string | null>(null);
  /** A replayed agent run is playing back: nothing can be sent or answered. */
  replaying = $state(false);

  geom = new GeomClient();
  private stream: EventStream | null = null;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private fullTimer: ReturnType<typeof setTimeout> | null = null;
  private seen = new Set<number>();
  private replayTimer: ReturnType<typeof setTimeout> | null = null;
  private metaTimer: ReturnType<typeof setTimeout> | null = null;
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
  get currentJob(): JobInfo | null {
    return this.jobId ? this.jobs[this.jobId] ?? null : null;
  }
  /** Latest finished design job's result card, if any. */
  get lastResult(): ResultCard | null {
    const done = Object.values(this.jobs).filter((j) => j.result).sort((a, b) => (b.finished ?? b.started) - (a.finished ?? a.started));
    return done[0]?.result ?? null;
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
        this.agentValues = { ...this.values };
        if (d.program.checks) this.fullChecks = d.program.checks;
        this.rebuild('full');
      }
      if (d.job && (d.job.status === 'running' || d.job.status === 'waiting')) {
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
    if (this.replayTimer) clearTimeout(this.replayTimer);
    if (this.metaTimer) clearTimeout(this.metaTimer);
  }

  /** The agent renames the project and calibrates photos as it works; pick those up once things settle. */
  private refreshMeta() {
    if (this.metaTimer) clearTimeout(this.metaTimer);
    this.metaTimer = setTimeout(async () => {
      try {
        const d = await api.project(this.id);
        if (!this.detail) return;
        this.detail.title = d.title;
        this.detail.cover = d.cover;
        this.detail.public = d.public;
        this.detail.assets = d.assets;
        this.detail.selections = d.selections;
      } catch {
        /* next event retries */
      }
    }, 800);
  }

  // Replay events carry data.replay; the project stays 'working' until the playback ends.
  private markReplay() {
    this.replaying = true;
    if (this.replayTimer) clearTimeout(this.replayTimer);
    this.replayTimer = setTimeout(async () => {
      try {
        const d = await api.project(this.id);
        if (d.status !== 'working') {
          this.replaying = false;
          this.jobId = null;
          if (this.detail) this.detail.status = d.status;
        } else this.markReplay();
      } catch {
        this.replaying = false;
      }
    }, 5000);
  }

  private push(item: TimelineItem) {
    this.timeline.push(item);
    if (this.timeline.length > 1 && this.timeline[this.timeline.length - 2].ts > item.ts) this.timeline.sort((a, b) => a.ts - b.ts);
  }

  private job(id: string | null | undefined, ts: number, kind = 'design'): JobInfo | null {
    if (!id) return null;
    if (!this.jobs[id]) this.jobs[id] = { id, kind, status: 'running', stage: null, reached: [], started: ts };
    return this.jobs[id];
  }

  private setStage(j: JobInfo | null, stage: string) {
    if (!j || !stage) return;
    j.stage = stage;
    if (!j.reached.includes(stage)) j.reached.push(stage);
  }

  private onEvent(e: EventRow) {
    if (this.seen.has(e.seq)) return;
    this.seen.add(e.seq);
    const d = e.data ?? {};
    const key = `e${e.seq}`;
    const ts = e.ts;
    const jid = e.job_id ?? d.job_id ?? null;
    if (d.replay) this.markReplay();
    switch (e.type) {
      case 'job.started': {
        const j = this.job(jid, ts, d.kind ?? 'design');
        if (j) {
          j.kind = d.kind ?? j.kind;
          j.model = d.model;
          j.status = 'running';
        }
        this.jobId = jid;
        this.jobKind = d.kind ?? null;
        this.status = null;
        break;
      }
      case 'job.stage':
        this.setStage(this.job(jid, ts), d.stage);
        break;
      case 'job.finished': {
        const j = this.job(jid, ts);
        if (j) {
          j.status = d.summary === 'refused' ? 'refused' : (d.status ?? 'done');
          j.finished = ts;
          j.summary = d.summary;
          if (d.cost) j.cost = d.cost;
          if (j.status === 'done') this.setStage(j, 'done');
        }
        if (!jid || jid === this.jobId) {
          this.jobId = null;
          this.jobKind = null;
          this.status = null;
        }
        for (const it of this.timeline) if (it.kind === 'ask' && it.job_id === jid && !it.answered) it.answered = '—';
        this.refreshMeta();
        break;
      }
      case 'user.message':
        if (!this.timeline.some((x) => x.kind === 'user' && x.text === d.text && Math.abs(x.ts - ts) < 60)) this.push({ kind: 'user', key, ts, job: null, text: d.text, assets: d.asset_ids });
        break;
      case 'agent.message':
        this.push({ kind: 'agent', key, ts, job: jid, text: d.text ?? '' });
        break;
      case 'agent.status':
        this.status = d.text ?? null;
        this.push({ kind: 'status', key, ts, job: jid, text: d.text ?? '' });
        break;
      case 'agent.thinking':
        this.push({ kind: 'thinking', key, ts, job: jid, text: d.text ?? '' });
        break;
      case 'tool.call': {
        const tk = kindOf(d.name ?? '', d.kind);
        this.push({ kind: 'tool', key, ts, job: jid, id: d.id ?? key, name: d.name ?? 'tool', tkind: tk, title: d.title, args: d.args });
        const j = this.job(jid, ts);
        if (j && !j.reached.includes('done')) this.setStage(j, KIND_STAGE[tk] ?? j.stage ?? 'design');
        break;
      }
      case 'tool.result': {
        const call = [...this.timeline].reverse().find((x) => x.kind === 'tool' && (x.id === d.id || (!d.id && x.name === d.name && !x.result)));
        const res = { ok: d.ok !== false, summary: d.summary, image: d.image, title: d.title };
        if (call && call.kind === 'tool') call.result = res;
        else if (d.name !== 'build') this.push({ kind: 'tool', key, ts, job: jid, id: d.id ?? key, name: d.name ?? 'tool', tkind: kindOf(d.name ?? '', d.kind), title: d.title, args: null, result: res });
        if (d.image) this.lastRender = d.image;
        break;
      }
      case 'program.updated':
        this.onProgram(d);
        this.push({ kind: 'program', key, ts, job: jid, version: d.version, summary: d.summary, render: d.render, author: d.author });
        if (d.render) this.lastRender = d.render;
        break;
      case 'critic':
        this.push({ kind: 'critic', key, ts, job: jid, verdict: d.verdict ?? 'revise', score: d.match_score, issues: d.issues ?? [], render: d.render });
        break;
      case 'result': {
        const j = this.job(jid, ts);
        if (j) j.result = d as ResultCard;
        break;
      }
      case 'ask':
        this.push({ kind: 'ask', key, ts, job: jid, job_id: d.job_id ?? jid ?? '', question_id: d.question_id ?? key, question: d.question ?? '', options: (d.options ?? []).map(optionLabel).filter(Boolean), allow_text: d.allow_text !== false });
        { const j = this.job(jid, ts); if (j) j.status = 'waiting'; }
        break;
      case 'answer': {
        const q = this.timeline.find((x) => x.kind === 'ask' && x.question_id === d.question_id);
        if (q && q.kind === 'ask') q.answered = d.answer ?? '—';
        const j = this.job(jid, ts);
        if (j && j.status === 'waiting') j.status = 'running';
        break;
      }
      case 'facts':
        this.push({ kind: 'facts', key, ts, job: jid, items: d.items ?? [] });
        break;
      case 'memory':
        this.push({ kind: 'memory', key, ts, job: jid, items: d.items ?? [] });
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
        this.refreshMeta();
        break;
      case 'selection.removed':
        if (this.detail) this.detail.selections = this.detail.selections.filter((s) => s.id !== d.id);
        break;
      case 'concepts':
        this.concepts = d.images ?? [];
        this.push({ kind: 'concepts', key, ts, job: jid, images: d.images ?? [] });
        break;
      case 'variants':
        this.variants = d.items ?? [];
        this.push({ kind: 'variants', key, ts, job: jid, items: d.items ?? [] });
        break;
      case 'slice':
        this.slice = d;
        this.push({ kind: 'slice', key, ts, job: jid, data: d });
        break;
      case 'probe':
        this.probe = d;
        this.push({ kind: 'probe', key, ts, job: jid, data: d });
        break;
      case 'cost': {
        this.cost = d as any;
        const j = this.job(jid, ts);
        if (j) j.cost = d as any;
        break;
      }
      case 'error':
      case 'job.failed':
        this.push({ kind: 'error', key, ts, job: jid, text: d.message ?? d.error ?? 'error' });
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
    if (d.author !== 'user') this.agentValues = { ...this.values };
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
        this.addError(errorText(e));
      }
    }, 900);
  }

  async upload(file: Blob, kind: string, filename?: string): Promise<AssetOut | null> {
    try {
      const a = await api.upload(this.id, file, kind, filename);
      if (this.detail && !this.detail.assets.some((x) => x.id === a.id)) this.detail.assets.push(a);
      return a;
    } catch (e) {
      this.addError(errorText(e));
      return null;
    }
  }

  async send(text: string, assetIds: string[] = [], effort: 'auto' | 'hard' = 'auto') {
    if (this.replaying) return;
    const ts = Date.now() / 1000;
    this.push({ kind: 'user', key: `local${ts}`, ts, job: null, text, assets: assetIds });
    try {
      const r = await api.send(this.id, text, assetIds, effort);
      this.jobId = r.job_id;
      this.jobKind = 'design';
      this.job(r.job_id, ts + 0.001, 'design');
    } catch (e) {
      this.addError(errorText(e));
    }
  }

  continueJob() {
    return this.send(t('continue_msg'));
  }

  async answer(item: Extract<TimelineItem, { kind: 'ask' }>, answer: string) {
    try {
      await api.answer(item.job_id, answer);
      item.answered = answer;
    } catch (e) {
      this.addError(errorText(e));
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
      this.addError(errorText(e));
    }
  }

  addError(text: string) {
    this.push({ kind: 'error', key: `err${Date.now()}${Math.random()}`, ts: Date.now() / 1000, job: null, text });
  }
}
