// Project state for the studio and recipe pages: server detail + event log grouped by
// job + the live local build of the current program.
import { api, errorText } from './api';
import { GeomClient } from './geom/client';
import { t } from './i18n.svelte';
import { chosenModel, prefs, refreshMe } from './session.svelte';
import { streamEvents, type EventStream } from './sse';
import { KIND_STAGE, kindOf } from './steps';
import type { AssetOut, BuildResult, CheckReport, EventRow, ProjectDetail, SelectionOut } from './types';

type Base = { key: string; ts: number; job?: string | null };
// older servers passed the model's options through as {label, value} objects
const optionLabel = (o: any): string => (typeof o === 'string' ? o : String(o?.label ?? o?.value ?? ''));

export type TimelineItem =
  | (Base & { kind: 'user'; text: string; assets?: string[]; previews?: string[] })
  | (Base & { kind: 'agent'; text: string })
  | (Base & { kind: 'status'; text: string; say?: boolean })
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

/** The current program as a mesh document (mesh engine), or null for a CAD program. */
function meshDocOf(source: string | null): MeshDoc | null {
  if (!source || !source.trimStart().startsWith('{')) return null;
  try {
    const d = JSON.parse(source);
    return d?.engine === 'mesh' && Array.isArray(d.ops) ? d : null;
  } catch {
    return null;
  }
}

export interface MeshDoc {
  engine: 'mesh';
  meta?: Record<string, any>;
  params?: Record<string, any>;
  symmetry?: 'x' | 'y' | null;
  detail?: number;
  ops: (Record<string, any> & { op: string; id?: string; enabled?: boolean; note?: string; by?: string })[];
}

const sameValues = (a: Record<string, any> | undefined, b: Record<string, any>) =>
  !!a && Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([k, v]) => b[k] === v);

export class ProjectStore {
  id: string;
  detail = $state<ProjectDetail | null>(null);
  loadError = $state<string | null>(null);
  timeline = $state<TimelineItem[]>([]);
  jobs = $state<Record<string, JobInfo>>({});
  // program
  source = $state<string | null>(null);
  version = $state(0);
  // big (outlines, heightmaps, imported meshes) and never edited in place: not deeply reactive
  inputs = $state.raw<any>({});
  values = $state<Record<string, any>>({});
  agentValues = $state<Record<string, any>>({});
  build = $state.raw<BuildResult | null>(null);
  buildError = $state<string | null>(null);
  /** The shown model is older than the current values (a build is on its way). */
  building = $state(false);
  /** The full printability report for the current values is being computed. */
  checking = $state(false);
  fullChecks = $state.raw<CheckReport | null>(null);
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
  /** Files of the first message are uploading; the job starts after them. */
  starting = $state<string | null>(null);
  /** Text for the composer to pick up (editing an earlier message). */
  draft = $state<string | null>(null);
  /** Mesh engine document behind the current program (null for CAD programs). */
  meshDoc = $derived(meshDocOf(this.source));
  /** Earlier versions of studio edits to the document, newest last. */
  undoStack = $state<string[]>([]);

  geom = new GeomClient();
  /** Tags our saves so their echo on the event stream is not rebuilt again. */
  readonly clientId = Math.random().toString(36).slice(2);
  private stream: EventStream | null = null;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  // every change of source or values gets a revision; results older than the shown one are dropped
  private rev = 0;
  private shown = 0;
  private shownFinal = false;
  // the source the server has: studio edits of a mesh document differ from it until saved
  private serverSource: string | null = null;
  private committedSource: string | null = null;
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
    return !!this.jobId || !!this.starting;
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
        this.serverSource = this.committedSource = d.program.source;
        this.version = d.program.version;
        this.setInputs(d.program.inputs ?? {});
        this.values = { ...(d.program.params ?? {}) };
        this.agentValues = { ...this.values };
        if (d.program.checks) this.fullChecks = d.program.checks;
        this.refresh();
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
        refreshMe();
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
        if (!this.timeline.some((x) => x.kind === 'user' && x.text === d.text && Math.abs(x.ts - ts) < 600)) this.push({ kind: 'user', key, ts, job: null, text: d.text, assets: d.asset_ids });
        break;
      case 'agent.message':
        this.push({ kind: 'agent', key, ts, job: jid, text: d.text ?? '' });
        break;
      case 'agent.status':
        this.status = d.text ?? null;
        this.push({ kind: 'status', key, ts, job: jid, text: d.text ?? '', say: d.say });
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
    // our own save coming back: nothing to rebuild
    const ownSave = (d.client && d.client === this.clientId) || (d.author === 'user' && !d.source && !d.source_changed && this.source && sameValues(d.params, this.values));
    this.version = d.version;
    if (this.detail) this.detail.version = d.version;
    if (ownSave) return;
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
    this.serverSource = this.committedSource = this.source;
    this.undoStack = [];
    if (inputs) this.setInputs(inputs);
    this.values = { ...(d.params ?? {}) };
    if (d.author !== 'user') this.agentValues = { ...this.values };
    this.fullChecks = d.checks ?? null;
    this.refresh();
  }

  private setInputs(inputs: any) {
    this.inputs = inputs ?? {};
    this.geom.setInputs(this.inputs);
  }

  /** Heavy programs preview at coarse quality while dragging; light ones always build in full. */
  private get heavy() {
    return this.geom.finalMs === 0 || this.geom.finalMs > 150;
  }

  /** New program or inputs: a quick preview first for heavy programs, the full build and checks next. */
  refresh() {
    if (!this.source) return;
    const rev = ++this.rev;
    this.building = true;
    if (this.heavy) this.runPreview(rev, 'preview');
    this.runFinal(rev, false);
  }

  /**
   * Slider/handle moved. While dragging only the live preview runs (in its own worker,
   * coarse for heavy programs); on release the full build, the full checks and a save.
   * The server does not rebuild anything for this.
   */
  setParam(name: string, value: any, commit = false) {
    this.values[name] = value;
    this.changed(commit);
  }

  /**
   * Change the mesh document (ops panel, strokes sculpted in the viewer). Rebuilds here;
   * only the ops from the first change on are recomputed. `commit` also checks and saves it.
   */
  editDoc(change: (doc: MeshDoc) => void, commit: boolean) {
    if (!this.source || !this.meshDoc) return;
    const doc = JSON.parse(this.source) as MeshDoc;
    change(doc);
    const source = JSON.stringify(doc);
    if (source === this.source && !commit) return;
    this.source = source;
    if (commit && this.committedSource !== source) {
      if (this.committedSource) this.undoStack = [...this.undoStack.slice(-49), this.committedSource];
      this.committedSource = source;
    }
    this.changed(commit);
  }

  /** Back to the document before the last studio edit. */
  undoEdit() {
    const prev = this.undoStack.at(-1);
    if (!prev) return;
    this.undoStack = this.undoStack.slice(0, -1);
    this.source = this.committedSource = prev;
    this.changed(true);
  }

  private changed(commit: boolean) {
    const rev = ++this.rev;
    this.building = true;
    if (!commit) {
      this.runPreview(rev, this.heavy ? 'preview' : 'final');
      return;
    }
    if (this.heavy) this.runPreview(rev, 'preview');
    this.runFinal(rev, !this.readonly);
  }

  private show(r: BuildResult, rev: number, final: boolean) {
    if (rev < this.shown || (rev === this.shown && this.shownFinal && !final)) return;
    this.build = r;
    this.shown = rev;
    this.shownFinal = final;
    this.buildError = null;
    this.building = rev !== this.rev;
    // parameters the program clamped/rounded
    if (rev === this.rev) for (const [k, v] of Object.entries(r.params)) if (this.values[k] !== v) this.values[k] = v;
  }

  private failed(rev: number, r: { stage: string; message: string }) {
    if (r.stage === 'superseded' || rev !== this.rev) return;
    this.buildError = `${r.stage}: ${r.message}`;
    this.building = false;
    this.checking = false;
  }

  private async runPreview(rev: number, quality: 'preview' | 'final') {
    const r = await this.geom.preview({ source: this.source!, params: $state.snapshot(this.values), quality });
    if (!r.ok) return this.failed(rev, r);
    this.show(r, rev, quality === 'final');
  }

  private async runFinal(rev: number, save: boolean) {
    this.checking = true;
    const values = $state.snapshot(this.values);
    const r = await this.geom.finalize({ source: this.source!, params: values }, (d) => this.show(d, rev, true));
    if (!r.ok) return this.failed(rev, r);
    if (rev !== this.rev) return;
    this.fullChecks = r.checks;
    this.checking = false;
    if (save) this.save(values, r.checks);
  }

  private save(values: Record<string, any>, checks: CheckReport) {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    const source = this.source;
    this.saveTimer = setTimeout(async () => {
      try {
        const edited = source !== null && source !== this.serverSource;
        const r = edited
          ? await api.saveProgram(this.id, { source: source!, params: values, checks, summary: 'edited in the studio', client: this.clientId })
          : await api.saveParams(this.id, values, checks, this.clientId);
        if (edited) this.serverSource = source;
        if (r.version > this.version) {
          this.version = r.version;
          if (this.detail) this.detail.version = r.version;
        }
      } catch (e) {
        this.addError(errorText(e));
      }
    }, 600);
  }

  /** STL/3MF of the current values, built locally. */
  exportFile(format: 'stl' | '3mf') {
    return this.geom.exportFile({ source: this.source!, params: $state.snapshot(this.values), format, title: this.detail?.title });
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

  async send(text: string, assetIds: string[] = []) {
    if (this.replaying) return;
    const ts = Date.now() / 1000;
    this.push({ kind: 'user', key: `local${ts}`, ts, job: null, text, assets: assetIds });
    await this.startJob(text, assetIds, ts);
  }

  /** First message from the home page: shown at once with local previews, the job starts once the files are in. */
  async sendFiles(text: string, files: File[]) {
    const ts = Date.now() / 1000;
    const key = `local${ts}`;
    const previews = files.filter((f) => f.type.startsWith('image/')).map((f) => URL.createObjectURL(f));
    this.push({ kind: 'user', key, ts, job: null, text, assets: [], previews });
    const ids: string[] = [];
    try {
      for (const [i, f] of files.entries()) {
        this.starting = files.length > 1 ? t('uploading_n', { i: i + 1, n: files.length }) : t('uploading_one');
        const kind = f.type.startsWith('video/') ? 'video' : f.type.startsWith('audio/') ? 'audio' : 'photo';
        const a = await this.upload(f, kind);
        if (a) ids.push(a.id);
      }
      const item = this.timeline.find((x) => x.key === key);
      if (item?.kind === 'user') item.assets = ids;
      this.starting = t('agent_starting');
      await this.startJob(text, ids, ts);
    } finally {
      this.starting = null;
    }
  }

  private async startJob(text: string, assetIds: string[], ts: number) {
    try {
      const r = await api.send(this.id, text, assetIds, { model: chosenModel(), reasoning: prefs.reasoning });
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
