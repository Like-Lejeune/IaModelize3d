// Project state for the studio and recipe pages: server detail + event log grouped by
// job + the live local build of the current program.
import { api, ApiError, errorInfo, errorText, isTransient } from './api';
import { GeomClient } from './geom/client';
import { i18n, t } from './i18n.svelte';
import { pcbApi } from './pcb/api';
import { DeviceStore } from './device/store.svelte';
import { chosenModel, prefs, refreshMe } from './session.svelte';
import { streamEvents, type EventStream } from './sse';
import { KIND_STAGE, kindOf } from './steps';
import type {
  AssetOut, BoardSpec, BuildResult, CheckReport, CriticVerdict, EnclosureChecks, EventRow, JobCost, PcbDrc, PcbVersion, ProjectDetail, ResultCard,
  RouteFrame, RouteFrames, SelectionOut, SnapObject,
} from './types';

export type { ResultCard };

type Base = { key: string; ts: number; job?: string | null };
// older servers passed the model's options through as {label, value} objects
const optionLabel = (o: any): string => (typeof o === 'string' ? o : String(o?.label ?? o?.value ?? ''));

export type TimelineItem =
  | (Base & { kind: 'user'; text: string; assets?: string[]; previews?: string[] })
  | (Base & { kind: 'agent'; text: string })
  | (Base & { kind: 'status'; text: string; say?: boolean })
  | (Base & { kind: 'thinking'; text: string })
  // model: who called the tool (the designer); models: the ones that did the work, e.g. SAM for a measure step
  | (Base & { kind: 'tool'; id: string; name: string; tkind: string; title?: string; args: any; model?: string; models?: string[]; result?: { ok: boolean; summary?: string; image?: string; title?: string } })
  | (Base & { kind: 'critic'; verdict: string; score?: number | null; issues: NonNullable<CriticVerdict['issues']>; render?: string } & Pick<CriticVerdict, 'model' | 'version' | 'blocking' | 'forced_by' | 'reviewer'>)
  | (Base & { kind: 'ask'; job_id: string; question_id: string; question: string; options: string[]; allow_text: boolean; answered?: string })
  | (Base & { kind: 'facts'; items: any[] })
  | (Base & { kind: 'program'; version: number; summary?: string; render?: string; author?: string })
  | (Base & { kind: 'concepts'; images: { url: string; prompt?: string; asset_id?: string }[] })
  | (Base & { kind: 'variants'; items: { version: number; render?: string; summary?: string }[] })
  | (Base & { kind: 'slice'; data: any })
  | (Base & { kind: 'probe'; data: any })
  | (Base & { kind: 'memory'; items: { kind: string; name: string }[] })
  // code and projectId come from the API error: 'job_running' names the project that holds the slot
  // retry: what the Retry button (or the connection coming back, for code 'offline') does
  | (Base & { kind: 'error'; text: string; code?: string; projectId?: string; retry?: () => void });

export interface JobInfo {
  id: string;
  kind: string;
  status: string; // running | waiting | done | failed | cancelled | budget | refused
  stage: string | null;
  reached: string[];
  started: number;
  finished?: number;
  cost?: JobCost | null;
  summary?: string | null;
  result?: ResultCard | null;
  model?: string;
  /** The model is still answering: seconds so far ('job.heartbeat'), cleared by the job's next event. */
  wait?: { seconds: number; stage?: string | null; outage?: boolean } | null;
  /** The latest reasoning summary the model shared. */
  thought?: string | null;
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

/** The board a case program carries itself (elec_tools.enclosure_program's fallback, the showcase case): `const BOARD = {...};`. */
function boardIn(source: string | null): BoardSpec | null {
  const m = source?.match(/^const BOARD = (\{.*\});$/m);
  if (!m) return null;
  try {
    const b = JSON.parse(m[1]);
    return b?.pcb?.outline && Array.isArray(b.components) ? b : null;
  } catch {
    return null;
  }
}

/** A stored case check; one the studio saved with a slider edit learns its version from the version it was saved with. */
const ofVersion = (enc: EnclosureChecks | null | undefined, version: number): EnclosureChecks | null =>
  !enc ? null : enc.by === 'studio' ? { ...enc, version } : enc;

/** A case program built with lib.elec around a board from inputs.boards. */
const isCase = (source: string | null) => !!source && /lib\.elec|\bE\.enclosure\(|inputs\.boards/.test(source);

type Live = { frames: RouteFrame[]; total: number; progress: number | null; w: number | null; h: number | null };

/** The project's PCB versions (C8) and the build routing right now ('pcb.route' frames until 'pcb.version'). */
export class PcbState {
  versions = $state.raw<PcbVersion[]>([]);
  loaded = $state(false);
  /** The version on show; null follows the latest. */
  picked = $state<number | null>(null);
  /** Frames of the build routing right now, in fw.board/1 mm; null while none is. */
  live = $state.raw<Live | null>(null);
  /** Bumped by every version announced live: the panel replays its routing once. */
  arrived = $state(0);
  /** drc.json and route_frames.json of the version on show. */
  drc = $state.raw<PcbDrc | null>(null);
  frames = $state.raw<RouteFrames | null>(null);
  /** glb_map of versions whose board.glb sits in a case (version -> GLB-to-board-frame matrix, null when it has none). */
  glbMaps = $state.raw<Record<number, number[][] | null>>({});
  /** A replay: versions after this one are not out yet (0: none is); null follows the project. */
  cap: number | null = null;
  private all: PcbVersion[] | null = null;
  private filesFor = 0;
  private token = 0;
  private glbAsked = new Set<number>();

  constructor(private projectId: string) {}

  get current(): PcbVersion | null {
    return (this.picked != null ? this.versions.find((v) => v.version === this.picked) : null) ?? this.versions.at(-1) ?? null;
  }

  async refresh() {
    try {
      if (this.cap == null) this.versions = await pcbApi.versions(this.projectId);
      else if (this.cap > 0) {
        this.all ??= await pcbApi.versions(this.projectId);
        const cap = this.cap;
        this.versions = this.all.filter((v) => v.version <= cap);
      } else this.versions = [];
    } catch {
      /* no PCB API here, or no access: the tab stays hidden */
    }
    this.loaded = true;
    await this.files();
  }

  /** A replay going back to the start: no board yet (the versions it has fetched stay for later). */
  resetReplay() {
    this.cap = 0;
    this.token++;
    this.filesFor = 0;
    this.versions = [];
    this.picked = null;
    this.live = null;
    this.drc = null;
    this.frames = null;
  }

  pick(version: number | null) {
    this.picked = version;
    this.files();
  }

  /** drc.json and route_frames.json of the version on show, fetched once per version. */
  private async files() {
    const v = this.current;
    if (!v || v.version === this.filesFor) return;
    this.filesFor = v.version;
    const token = ++this.token;
    this.drc = null;
    this.frames = null;
    const [drc, frames] = await Promise.all([
      v.artifacts['drc.json'] ? pcbApi.drc(v.artifacts['drc.json']).catch(() => null) : null,
      v.artifacts['route_frames.json'] ? pcbApi.frames(v.artifacts['route_frames.json']).catch(() => null) : null,
    ]);
    if (token !== this.token) return;
    this.drc = drc;
    this.frames = frames;
    if (frames && !(v.version in this.glbMaps)) this.glbMaps = { ...this.glbMaps, [v.version]: frames.glb_map?.matrix ?? null };
  }

  /** board.glb of a version, with the matrix that puts it in the fw.board/1 frame (null until route_frames.json is in). */
  glbOf(version: number): { url: string; matrix: number[][] | null } | null {
    const url = this.versions.find((x) => x.version === version)?.artifacts['board.glb'];
    return url ? { url, matrix: this.glbMaps[version] ?? null } : null;
  }

  /** Fetch a version's glb_map once (route_frames.json carries it), for a case made from that version. */
  async wantGlb(version: number) {
    const v = this.versions.find((x) => x.version === version);
    const url = v?.artifacts['route_frames.json'];
    // the version on show has its frames on the way already (files())
    if (!v || version in this.glbMaps || this.glbAsked.has(version) || this.filesFor === version) return;
    this.glbAsked.add(version);
    const frames = url ? await pcbApi.frames(url).catch(() => null) : null;
    this.glbMaps = { ...this.glbMaps, [version]: frames?.glb_map?.matrix ?? null };
  }

  /** 'pcb.route': the next frame of the build routing now; frame 0 starts a new build. */
  route(d: any) {
    const prev = this.live;
    const restart = !prev || d.frame === 0 || (typeof d.frame === 'number' && d.frame < prev.frames.length);
    const frame: RouteFrame = { progress: typeof d.progress === 'number' ? d.progress : null, lines: Array.isArray(d.lines) ? d.lines : [] };
    this.live = {
      frames: [...(restart ? [] : prev!.frames), frame],
      total: Number(d.total) || 24,
      progress: frame.progress,
      w: d.w ?? prev?.w ?? null,
      h: d.h ?? prev?.h ?? null,
    };
  }

  /** 'pcb.version': the routed build is saved; the latest version goes on show. */
  async added() {
    this.live = null;
    this.picked = null;
    await this.refresh();
    this.arrived++;
  }

  /** The build ended without a version (it failed, or the job stopped). */
  endRoute() {
    this.live = null;
  }
}

export class ProjectStore {
  id: string;
  detail = $state<ProjectDetail | null>(null);
  loadError = $state<string | null>(null);
  /** loadError is a passing one: load() keeps trying and the page comes up by itself. */
  loadRetrying = $state(false);
  /** Why the studio's last edit is not on the server yet; save() keeps trying a passing failure. */
  saveError = $state<string | null>(null);
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
  cost = $state<JobCost | null>(null);
  /** Stop was pressed: the server is winding the job down, and sending waits until it has. */
  stopping = $state(false);
  /** A photo just arrived from the phone (capture link) and went into the tray; cleared after a few seconds. */
  phoneToast = $state<AssetOut | null>(null);
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
  /** Photos whose object is being found right now (asset id -> true). */
  spotting = $state<Record<string, boolean>>({});
  /** What was found on each photo: the name and the other objects there (also in `asset.meta.spot`). */
  spotInfo = $state<Record<string, { label: string; objects: SnapObject[] }>>({});
  /** Text for the composer to pick up (editing an earlier message). */
  draft = $state<string | null>(null);
  /** Mesh engine document behind the current program (null for CAD programs). */
  meshDoc = $derived(meshDocOf(this.source));
  /** Earlier versions of studio edits to the document, newest last. */
  undoStack = $state<string[]>([]);
  // electronics
  /** checks.enclosure (C5) with the program it was made on: its rays fit the model while source and params match. */
  enclosure = $state.raw<{ check: EnclosureChecks; params: Record<string, any>; source: string | null } | null>(null);
  /** The geom worker is checking the case against its board for the values on show (after a slider edit). */
  enclosureChecking = $state(false);
  /** The case shown closed around its board (layout 'assembled' + show_board): a studio view, never saved. */
  assembled = $state(false);
  /** The shown build is that view, so its fast checks are not the print layout's. */
  private shownView = $state(false);
  /** A board built into the program itself (a showcase case without inputs.boards). */
  private builtInBoard = $derived(boardIn(this.source));
  pcb: PcbState;
  /** The device graph of a 'device' project (fw.device/1): the node editor and the Device tab. */
  device: DeviceStore;

  geom = new GeomClient();
  /** Tags our saves so their echo on the event stream is not rebuilt again. */
  readonly clientId = Math.random().toString(36).slice(2);
  private stream: EventStream | null = null;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  // the edit on its way to the server, and how long to wait before trying it again
  private unsaved: { values: Record<string, any>; checks: CheckReport; source: string | null } | null = null;
  private saveWait = 2000;
  private loadWake: (() => void) | null = null;
  private jobWatch: ReturnType<typeof setInterval> | null = null;
  // every change of source or values gets a revision; results older than the shown one are dropped
  private rev = 0;
  private shown = 0;
  private shownFinal = false;
  // the source the server has: studio edits of a mesh document differ from it until saved
  private serverSource: string | null = null;
  private committedSource: string | null = null;
  private seen = new Set<number>();
  private replayTimer: ReturnType<typeof setTimeout> | null = null;
  private spots = new Map<string, Promise<void>>();
  private metaTimer: ReturnType<typeof setTimeout> | null = null;
  private toastTimer: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;
  // events up to this seq were already applied by load(): their programs are not rebuilt
  private historySeq = 0;
  // bumped by every program from the server; a fetch that resolves after a newer one is dropped
  private programToken = 0;
  private inputsJson = '';
  private stoppingJob: string | null = null;
  private stopTimer: ReturnType<typeof setTimeout> | null = null;
  private stopWaiters: (() => void)[] = [];
  // the person picked the case view themselves: checks arriving later do not flip it
  private viewChosen = false;
  // the latest program from the server: what an 'enclosure.checked' of its version was made on
  private known: { version: number; params: Record<string, any>; source: string | null } | null = null;
  private pendingEnc: EnclosureChecks | null = null;
  /** The /r/ recipe page: no event stream, the case laid out for printing as saved. */
  private readonly recipe: boolean;
  /** Someone else's project (the detail's can_edit is false): it opens read-only, with the whole run and a Remix offer. */
  visitor = $state(false);
  /** The replay player feeds this store the run's log (replay.svelte.ts) instead of the project's latest state and stream. */
  readonly replayMode: boolean;
  // what a jump passed over and the moment still shows, for settleReplay
  private caught: { program: any; enclosure: any; route: any[] } = { program: null, enclosure: null, route: [] };

  constructor(id: string, recipe = false, replayMode = false) {
    this.id = id;
    this.recipe = recipe;
    this.replayMode = replayMode;
    this.replaying = replayMode;
    this.pcb = new PcbState(id);
    this.device = new DeviceStore(id, () => !this.readonly);
  }

  /** Nothing here is saved or sent: sliders and handles still move the model in this browser. */
  get readonly(): boolean {
    return this.recipe || this.visitor || this.replayMode;
  }

  /** Back to before the run's first event; the assets stay, its messages show them whenever they come up. */
  resetReplay() {
    this.seen.clear();
    this.caught = { program: null, enclosure: null, route: [] };
    this.timeline = [];
    this.jobs = {};
    this.jobId = this.jobKind = this.status = null;
    this.cost = null;
    this.source = this.serverSource = this.committedSource = null;
    this.version = 0;
    this.setInputs({});
    this.values = {};
    this.agentValues = {};
    this.build = this.fullChecks = this.buildError = this.enclosure = this.known = this.pendingEnc = null;
    this.building = this.checking = this.enclosureChecking = this.assembled = this.shownView = this.shownFinal = false;
    this.concepts = [];
    this.variants = [];
    this.slice = this.probe = this.lastRender = null;
    this.scenes = {};
    this.undoStack = [];
    // whatever is still being fetched or built belongs to the moment left behind
    this.programToken++;
    this.shown = ++this.rev;
    if (this.detail) {
      this.detail.selections = [];
      this.detail.version = 0;
    }
    this.pcb.resetReplay();
    this.device.resetReplay();
  }

  /** One event of the log. fast: its state only, as history is read; settleReplay then builds what the moment shows. */
  replayEvent(e: EventRow, fast: boolean) {
    this.historySeq = fast ? Infinity : -Infinity;
    this.onEvent(e);
  }

  /** The end of a jump: the program, case check, board and device document of the moment it landed on. */
  settleReplay() {
    this.historySeq = -Infinity;
    const { program, enclosure, route } = this.caught;
    this.caught = { program: null, enclosure: null, route: [] };
    if (program && (program.version !== this.version || !this.source)) this.onProgram(program);
    if (enclosure) this.onEnclosure(enclosure);
    this.pcb.refresh();
    for (const frame of route) this.pcb.route(frame);
    this.device.settleReplay();
  }

  get assets(): AssetOut[] {
    return this.detail?.assets ?? [];
  }
  get selections(): SelectionOut[] {
    return this.detail?.selections ?? [];
  }
  /** The object the agent works from on this photo: its latest target selection. */
  target(assetId: string): SelectionOut | null {
    return this.selections.findLast((s) => s.asset_id === assetId && s.role === 'target') ?? null;
  }
  spotOf(assetId: string): { label: string; objects: SnapObject[] } | null {
    return this.spotInfo[assetId] ?? this.assets.find((a) => a.id === assetId)?.meta?.spot ?? null;
  }
  /** The photo's object as people call it; selection names are unique per project ("cat", "cat2"). */
  targetLabel(assetId: string): string | null {
    const sel = this.target(assetId);
    if (!sel) return null;
    const name = sel.name.replaceAll('_', ' ');
    const found = this.spotOf(assetId)?.label;
    return found && name.startsWith(found) && /^\d*$/.test(name.slice(found.length)) ? found : name;
  }
  get checks(): CheckReport | null {
    return this.fullChecks ?? (this.shownView ? null : this.build?.checks) ?? null;
  }
  /** An enclosure program: it shows its case laid out for printing or closed around the board (param layout). */
  get hasLayout(): boolean {
    const s = this.build?.paramSpecs?.layout;
    if (s?.options) return s.options.includes('print') && s.options.includes('assembled');
    return this.values.layout === 'print' || this.values.layout === 'assembled';
  }
  /** Params the studio sets for the view (layout, show_board): hidden from the sliders, never saved. */
  get viewKeys(): string[] {
    if (!this.hasLayout) return [];
    return 'show_board' in this.values || this.build?.paramSpecs?.show_board ? ['layout', 'show_board'] : ['layout'];
  }
  /** The enclosure check was made on the program and params on show, so its rays fit the model. */
  get enclosureFresh(): boolean {
    const e = this.enclosure;
    if (!e || e.source !== this.source) return false;
    return Object.entries(e.params).every(([k, v]) => k === 'layout' || k === 'show_board' || this.values[k] === v);
  }
  /** The board the case is built around: inputs.boards.<name>, or the one the program carries. */
  get board(): BoardSpec | null {
    const name = this.enclosure?.check.board ?? 'board';
    return (this.inputs?.boards?.[name] as BoardSpec | undefined) ?? this.builtInBoard;
  }
  /** The PCB version the case was made from (make_enclosure writes board.source.pcb_job 'pcb:vN'), if any. */
  get casePcbVersion(): number | null {
    const m = /^pcb:v(\d+)$/.exec(this.board?.source?.pcb_job ?? '');
    return m ? Number(m[1]) : null;
  }
  /** That version's real board (board.glb) and the matrix into the board frame: the viewer seats it on the standoffs. */
  get caseBoardGlb(): { url: string; matrix: number[][] } | null {
    const v = this.casePcbVersion;
    const g = v != null ? this.pcb.glbOf(v) : null;
    return g?.matrix ? { url: g.url, matrix: g.matrix } : null;
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

  /** Resolves once the project is in, or the server has refused it: a passing failure is tried again until it is over. */
  async load() {
    let wait = 2000;
    while (!this.disposed) {
      try {
        return await this.loadOnce();
      } catch (e) {
        this.loadError = errorText(e);
        this.loadRetrying = isTransient(e);
        if (!this.loadRetrying) return;
      }
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, wait);
        this.loadWake = () => {
          clearTimeout(timer);
          resolve();
        };
      });
      this.loadWake = null;
      wait = Math.min(wait * 2, 15000);
    }
  }

  /** "Retry" on a page that could not load: now instead of at the next try. */
  retryLoad() {
    this.loadWake?.();
  }

  private async loadOnce() {
    const d = await api.project(this.id);
    if (this.disposed) return;
    this.loadError = null;
    this.loadRetrying = false;
    this.detail = d;
    // the same rule as the server's 403 on a send; older servers do not say, and the studio stays as it was
    this.visitor = d.can_edit === false;
    if (this.replayMode) {
      this.resetReplay();
      return;
    }
    this.historySeq = d.last_seq;
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
      this.takeView();
      if (d.program.checks) this.fullChecks = d.program.checks;
      this.known = { version: d.program.version, params: { ...(d.program.params ?? {}) }, source: d.program.source };
      const enc = ofVersion(d.program.checks?.enclosure, d.program.version);
      if (enc) this.useEnclosure(enc, this.known);
      this.refresh();
      // a slider edit since keeps no case check: the newest earlier one still has the rays
      if (!enc && !this.recipe && isCase(d.program.source)) this.findEnclosure();
    }
    if (d.job && (d.job.status === 'running' || d.job.status === 'waiting')) {
      this.jobId = d.job.id;
      this.jobKind = d.job.kind;
    }
    this.pcb.refresh();
    if (d.pack === 'device') this.device.refresh();
    // a visitor's studio follows the run too: the stream only reads
    if (!this.recipe) this.connect();
  }

  connect() {
    if (this.disposed) return;
    this.stream?.close();
    this.stream = streamEvents(this.id, 0, (e) => this.onEvent(e), (s) => {
      const back = s === 'open' && this.connection === 'retry';
      this.connection = s;
      if (back) this.reconnected();
    });
    if (!this.jobWatch) {
      this.jobWatch = setInterval(() => this.checkJob(), 30000);
      window.addEventListener('beforeunload', this.warnUnsaved);
    }
  }

  private warnUnsaved = (e: BeforeUnloadEvent) => {
    if (this.hasUnsaved) e.preventDefault();
  };

  /** The connection is back: what failed for lack of it goes again by itself, and its errors are over. */
  private reconnected() {
    const offline = this.timeline.filter((x): x is Extract<TimelineItem, { kind: 'error' }> => x.kind === 'error' && x.code === 'offline');
    this.timeline = this.timeline.filter((x) => !offline.includes(x as any));
    for (const e of offline) e.retry?.();
    this.retrySave();
    if (this.detail?.pack === 'device') {
      this.device.retrySave();
      this.device.refresh();
    }
    this.pcb.refresh();
  }

  /** A job.finished that never came (the job's bookkeeping failed, or the stream missed it) must not leave a run going on screen. */
  private async checkJob() {
    const id = this.jobId;
    if (!id || this.connection !== 'open' || this.stopping || this.replayMode) return;
    let job: ProjectDetail['job'] | undefined;
    try {
      job = (await api.project(this.id)).job;
    } catch {
      return;
    }
    if (this.disposed || this.jobId !== id) return;
    if (!job) this.release(id, 'failed');
    else if (job.id === id && job.status !== 'running' && job.status !== 'waiting') this.release(id, job.status);
  }

  /** Close the stream and the workers; work still in flight finds the store disposed and stops. */
  dispose() {
    if (this.disposed) return;
    // leaving the page within the save's short delay must not lose the edit
    if (this.saveTimer && this.unsaved) void this.flushSave();
    this.disposed = true;
    this.loadWake?.();
    if (this.jobWatch) clearInterval(this.jobWatch);
    window.removeEventListener('beforeunload', this.warnUnsaved);
    this.stream?.close();
    this.stream = null;
    this.geom.dispose();
    if (this.saveTimer) clearTimeout(this.saveTimer);
    if (this.replayTimer) clearTimeout(this.replayTimer);
    if (this.metaTimer) clearTimeout(this.metaTimer);
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.endStop();
  }

  /** The agent renames the project and calibrates photos as it works; pick those up once things settle. */
  private refreshMeta() {
    if (this.metaTimer) clearTimeout(this.metaTimer);
    this.metaTimer = setTimeout(async () => {
      try {
        const d = await api.project(this.id);
        if (this.disposed || !this.detail) return;
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
        if (this.disposed) return;
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
    if (this.disposed || this.seen.has(e.seq)) return;
    this.seen.add(e.seq);
    const d = e.data ?? {};
    const key = `e${e.seq}`;
    const ts = e.ts;
    const jid = e.job_id ?? d.job_id ?? null;
    const live = e.seq > this.historySeq;
    // what the project's newest state would bring, which a replay's moment must not get
    const latest = live && !this.replayMode;
    // the history of a finished replay copy is not a playback
    if (d.replay && !this.replayMode && (live || this.detail?.status === 'working')) this.markReplay();
    // anything the job does ends the wait for the model
    if (jid && e.type !== 'job.heartbeat' && e.type !== 'cost' && this.jobs[jid]?.wait) this.jobs[jid].wait = null;
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
      case 'job.heartbeat': {
        const j = this.job(jid, ts);
        if (j && !j.finished) j.wait = { seconds: Number(d.seconds) || 0, stage: d.stage ?? null, outage: !!d.outage };
        break;
      }
      case 'job.finished': {
        const j = this.job(jid, ts);
        if (j) {
          j.status = d.summary === 'refused' ? 'refused' : (d.status ?? 'done');
          j.finished = ts;
          j.summary = d.summary;
          if (d.cost) j.cost = d.cost;
          if (j.status === 'done') this.setStage(j, 'done');
        }
        // history: the header and load() already have what these would fetch
        if (latest) refreshMe();
        if (this.replayMode) this.caught.route = [];
        if (!jid || jid === this.jobId) {
          this.jobId = null;
          this.jobKind = null;
          this.status = null;
        }
        if (this.stopping && (!jid || jid === this.stoppingJob)) this.endStop();
        for (const it of this.timeline) if (it.kind === 'ask' && it.job_id === jid && !it.answered) it.answered = '—';
        if (latest) this.refreshMeta();
        this.pcb.endRoute();
        this.device.endAgentBuild();
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
      case 'agent.thinking': {
        this.push({ kind: 'thinking', key, ts, job: jid, text: d.text ?? '' });
        const j = this.job(jid, ts);
        if (j && d.text) j.thought = d.text;
        break;
      }
      case 'tool.call': {
        const tk = kindOf(d.name ?? '', d.kind);
        this.push({ kind: 'tool', key, ts, job: jid, id: d.id ?? key, name: d.name ?? 'tool', tkind: tk, title: d.title, args: d.args, model: d.model, models: d.models });
        const j = this.job(jid, ts);
        if (j && !j.reached.includes('done')) this.setStage(j, KIND_STAGE[tk] ?? j.stage ?? 'design');
        break;
      }
      case 'tool.result': {
        const call = [...this.timeline].reverse().find((x) => x.kind === 'tool' && (x.id === d.id || (!d.id && x.name === d.name && !x.result)));
        const res = { ok: d.ok !== false, summary: d.summary, image: d.image, title: d.title };
        if (call && call.kind === 'tool') {
          call.result = res;
          call.model ??= d.model;
          call.models ??= d.models;
        } else if (d.name !== 'build')
          this.push({ kind: 'tool', key, ts, job: jid, id: d.id ?? key, name: d.name ?? 'tool', tkind: kindOf(d.name ?? '', d.kind), title: d.title, args: null, model: d.model, models: d.models, result: res });
        if (d.image) this.lastRender = d.image;
        // a saved board announced itself before this; a failed build leaves its frames behind
        if (d.name === 'write_circuit' || d.name === 'build_device') this.pcb.endRoute();
        if (d.name === 'build_device') this.device.endAgentBuild();
        break;
      }
      case 'enclosure.checked':
        // history: load() took the latest version's check from the server
        if (live) this.onEnclosure(d);
        else if (this.replayMode) this.caught.enclosure = d;
        break;
      case 'pcb.route':
        if (live) this.pcb.route(d);
        else if (this.replayMode) this.caught.route = d.frame === 0 ? [d] : [...this.caught.route, d];
        break;
      case 'pcb.version':
        if (this.replayMode) {
          this.pcb.cap = d.version;
          this.device.atBoard(d.version);
          this.caught.route = [];
          if (live) this.device.refresh();
        }
        if (live) this.pcb.added();
        break;
      case 'device.version':
      case 'device.build':
        if (live || this.replayMode) this.device.onEvent(e.type, d, jid, !live);
        break;
      case 'program.updated':
        // history: load() already applied the program it ended with
        if (live) this.onProgram(d);
        else if (this.replayMode) this.caught.program = d;
        this.push({ kind: 'program', key, ts, job: jid, version: d.version, summary: d.summary, render: d.render, author: d.author });
        if (d.render) this.lastRender = d.render;
        break;
      case 'critic':
        this.push({
          kind: 'critic', key, ts, job: jid, verdict: d.verdict ?? 'revise', score: d.match_score, issues: d.issues ?? [], render: d.render,
          model: d.model, version: d.version, blocking: d.blocking, forced_by: d.forced_by, reviewer: d.reviewer,
        });
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
        if (latest && d.meta?.via === 'phone') this.fromPhone(d as AssetOut);
        break;
      case 'selection.added':
        if (this.detail && !this.detail.selections.some((s) => s.id === d.id)) this.detail.selections.push(d as SelectionOut);
        if (latest) this.refreshMeta();
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
        this.push({ kind: 'error', key, ts, job: jid, text: d.message ?? d.error ?? t('err_internal'), code: d.code });
        break;
      default:
        break;
    }
  }

  private onEnclosure(d: any) {
    const enc = d.enclosure as EnclosureChecks | undefined;
    if (!enc || typeof d.version !== 'number') return;
    if (this.known && this.known.version === d.version) {
      if (this.useEnclosure(enc, this.known)) this.refresh();
    } else this.pendingEnc = enc; // its program.updated is still being fetched
  }

  private async onProgram(d: any) {
    if (typeof d.version !== 'number' || d.version < this.version) return;
    // our own save coming back: nothing to rebuild
    const ownSave = (d.client && d.client === this.clientId) || (d.author === 'user' && !d.source && !d.source_changed && this.source && sameValues(d.params, this.values));
    this.version = d.version;
    if (this.detail) this.detail.version = d.version;
    if (ownSave) return;
    const token = ++this.programToken;
    let source: string | undefined = d.source;
    let inputs = d.inputs;
    if (!source) {
      try {
        const p = await api.program(this.id, d.version);
        if (this.disposed || token !== this.programToken) return;
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
    this.takeView();
    this.fullChecks = d.checks ?? null;
    this.known = { version: d.version, params: { ...(d.params ?? {}) }, source: this.source };
    const enc: EnclosureChecks | null = ofVersion(d.checks?.enclosure, d.version) ?? (this.pendingEnc?.version === d.version ? this.pendingEnc : null);
    this.pendingEnc = null;
    if (enc) this.useEnclosure(enc, this.known);
    this.refresh();
  }

  /** A case check and the program it was made on; the first one shows the case closed, rays and all. */
  private useEnclosure(check: EnclosureChecks, base: { params: Record<string, any>; source: string | null }): boolean {
    this.enclosure = { check, params: base.params, source: base.source };
    if (this.viewChosen || this.recipe || this.assembled || !this.hasLayout || !check.rays?.length) return false;
    this.assembled = true;
    return true;
  }

  /** The newest case check among the versions before the latest (slider edits save no check of their own). */
  private async findEnclosure() {
    try {
      const vs = await api.versions(this.id);
      for (const v of vs.slice(0, -1).reverse().slice(0, 4)) {
        const p = await api.program(this.id, v.version);
        if (this.disposed || this.enclosure) return;
        const enc = ofVersion(p.checks?.enclosure, v.version);
        if (!enc) continue;
        if (this.useEnclosure(enc, { params: p.params ?? {}, source: p.source })) this.refresh();
        return;
      }
    } catch {
      /* no rays then */
    }
  }

  /**
   * A version saved with its case closed (layout 'assembled', as studios before the view switch did): the params
   * go back to the print layout, and the studio shows it closed instead.
   */
  private takeView() {
    if (this.values.layout !== 'assembled') return;
    for (const o of [this.values, this.agentValues]) {
      if (o.layout === 'assembled') o.layout = 'print';
      if (o.show_board === true) o.show_board = false;
    }
    if (!this.viewChosen && !this.recipe) this.assembled = true;
  }

  /** Show the case closed around its board, or laid out for printing. Only the view changes: nothing is saved. */
  setAssembled(on: boolean) {
    this.viewChosen = true;
    if (this.assembled === on) return;
    this.assembled = on;
    this.refresh();
  }

  /** The values to build with: the view on top for the screen; the print layout for checks, saves and files. */
  private params(display: boolean): Record<string, any> {
    const v = $state.snapshot(this.values);
    if (!this.hasLayout) return v;
    const closed = display && this.assembled;
    v.layout = closed ? 'assembled' : 'print';
    if ('show_board' in v || this.build?.paramSpecs?.show_board) v.show_board = closed;
    return v;
  }

  private setInputs(inputs: any) {
    inputs = inputs ?? {};
    // the same inputs again (most new versions keep them) leave the workers' cached copy in place
    const json = JSON.stringify(inputs);
    if (json === this.inputsJson) return;
    this.inputsJson = json;
    this.inputs = inputs;
    this.geom.setInputs(inputs);
  }

  /** Heavy programs preview at coarse quality while dragging; light ones always build in full. */
  private get heavy() {
    return this.geom.finalMs === 0 || this.geom.finalMs > 150;
  }

  /** New program or inputs: a quick preview first for heavy programs, the full build and checks next. */
  refresh() {
    if (this.disposed || !this.source) return;
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

  private show(r: BuildResult, rev: number, final: boolean, view = false) {
    if (rev < this.shown || (rev === this.shown && this.shownFinal && !final)) return;
    this.build = r;
    this.shown = rev;
    this.shownFinal = final;
    this.shownView = view;
    this.buildError = null;
    this.building = rev !== this.rev;
    // parameters the program clamped/rounded (not the view the studio put on top)
    if (rev === this.rev) {
      const skip = this.viewKeys;
      for (const [k, v] of Object.entries(r.params)) if (!skip.includes(k) && this.values[k] !== v) this.values[k] = v;
    }
  }

  private failed(rev: number, r: { stage: string; message: string }) {
    if (r.stage === 'superseded' || rev !== this.rev) return;
    this.buildError = `${r.stage}: ${r.message}`;
    this.building = false;
    this.checking = false;
  }

  private async runPreview(rev: number, quality: 'preview' | 'final') {
    const view = this.hasLayout && this.assembled;
    const r = await this.geom.preview({ source: this.source!, params: this.params(true), quality });
    if (!r.ok) return this.failed(rev, r);
    this.show(r, rev, quality === 'final', view);
  }

  private async runFinal(rev: number, save: boolean) {
    this.checking = true;
    const values = this.params(false);
    const source = this.source!;
    // a case shown closed: the full build checks (and saves) the print layout, the live lane draws the view
    const view = this.hasLayout && this.assembled;
    if (view) this.runPreview(rev, 'final');
    // a case whose check is older than these values is checked against its board again, after the report
    const enclosure = this.caseCheckFor();
    this.enclosureChecking = !!enclosure;
    // client.ts hands extra build fields to the worker as they are
    const args = { source, params: values, ...(enclosure ? { enclosure } : {}) };
    const r = await this.geom.finalize(args, (d) => !view && this.show(d, rev, true));
    if (!r.ok) {
      if (r.stage !== 'superseded' && rev === this.rev) this.enclosureChecking = false;
      return this.failed(rev, r);
    }
    if (rev !== this.rev) return;
    this.fullChecks = r.checks;
    this.checking = false;
    const check = enclosure ? this.takeCheck((r as { enclosure?: any }).enclosure, values, source) : null;
    if (enclosure) this.enclosureChecking = false;
    if (save) this.save(values, check ? { ...r.checks, enclosure: check } : r.checks);
  }

  /** What the worker checks the case against: inputs.boards.<name>, or the board the program carries; null when the check on show fits. */
  private caseCheckFor(): { board: string; spec?: BoardSpec } | null {
    if (!this.hasLayout || this.enclosureFresh || this.meshDoc) return null;
    const boards = this.inputs?.boards ?? {};
    const name = this.enclosure?.check.board ?? ('board' in boards ? 'board' : Object.keys(boards)[0]);
    if (name && boards[name]) return { board: name };
    return this.builtInBoard ? { board: 'board', spec: $state.snapshot(this.builtInBoard) as BoardSpec } : null;
  }

  /** The worker's case check of these values goes on show, unless the agent's own check of them came in meanwhile. */
  private takeCheck(res: any, values: Record<string, any>, source: string): EnclosureChecks | null {
    if (!res || res.error || !Array.isArray(res.findings) || this.enclosureFresh) return null;
    const check: EnclosureChecks = { ...res, version: this.version, by: 'studio' };
    if (this.useEnclosure(check, { params: values, source })) this.refresh();
    return check;
  }

  private save(values: Record<string, any>, checks: CheckReport) {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.unsaved = { values, checks, source: this.source };
    this.saveWait = 2000;
    this.saveTimer = setTimeout(() => this.flushSave(), 600);
  }

  /** Sends the latest edit. Only a save that answered ends it: a passing failure is tried again, the newest edit taking its place. */
  private async flushSave() {
    const job = this.unsaved;
    this.saveTimer = null;
    if (!job) return;
    const { values, checks, source } = job;
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
      // the studio's case check went with this save: it is the check of that version now
      const e = this.enclosure;
      if (checks.enclosure && e?.check === checks.enclosure && e.check.version !== r.version) this.enclosure = { ...e, check: { ...e.check, version: r.version } };
      if (this.unsaved === job) this.unsaved = null;
      this.saveError = null;
    } catch (e) {
      if (this.disposed) return;
      this.saveError = errorText(e);
      if (this.unsaved !== job || !isTransient(e) || this.saveTimer) return;
      this.saveTimer = setTimeout(() => this.flushSave(), this.saveWait);
      this.saveWait = Math.min(this.saveWait * 2, 30000);
    }
  }

  /** The connection came back, or the person asked: the edit that is still waiting goes now. */
  retrySave() {
    if (!this.unsaved) return;
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveWait = 2000;
    void this.flushSave();
  }

  /** Edits that closing the page now would lose. */
  get hasUnsaved(): boolean {
    return !!this.unsaved || this.device.hasUnsaved;
  }

  /** STL/3MF of the current values, built locally. */
  exportFile(format: 'stl' | '3mf') {
    return this.geom.exportFile({ source: this.source!, params: this.params(false), format, title: this.detail?.title });
  }

  /** `retry`: what Retry on the error does, with the file still in hand. */
  async upload(file: Blob, kind: string, filename?: string, retry?: () => void): Promise<AssetOut | null> {
    if (this.refused()) return null; // someone else's project: the server takes no files into it
    try {
      const a = await api.upload(this.id, file, kind, filename);
      if (this.detail && !this.detail.assets.some((x) => x.id === a.id)) this.detail.assets.push(a);
      return a;
    } catch (e) {
      this.fail(e, retry);
      return null;
    }
  }

  /** Find and cut out the object on a fresh photo. The agent need not wait: the server has it wait for the cut-out before measuring. */
  spot(a: AssetOut, hint?: string): Promise<void> {
    if (a.kind !== 'photo' || this.readonly) return Promise.resolve();
    const known = this.spots.get(a.id);
    if (known) return known;
    this.spotting[a.id] = true;
    const run = api
      .spot(this.id, a.id, { hint: hint || null, lang: i18n.lang })
      .then((r) => {
        this.spotInfo[a.id] = { label: r.label ?? '', objects: r.objects };
        if (r.selection) this.putTarget(r.selection);
      })
      .catch(() => {
        /* the agent looks for the object itself */
      })
      .finally(() => delete this.spotting[a.id]);
    this.spots.set(a.id, run);
    return run;
  }

  /** A new target on a photo takes the place of the earlier ones there, as on the server. */
  putTarget(sel: SelectionOut) {
    if (!this.detail) return;
    this.detail.selections = [...this.detail.selections.filter((s) => s.id !== sel.id && !(s.asset_id === sel.asset_id && s.role === 'target')), sel];
  }

  /** A visitor's send, answer or side job: the server would refuse it (403), so the notice comes without the round trip. */
  private refused(): boolean {
    if (!this.readonly) return false;
    this.addError(t('forbidden'), { code: 'forbidden' });
    return true;
  }

  async send(text: string, assetIds: string[] = []) {
    if (this.replaying || this.refused()) return;
    const ts = Date.now() / 1000;
    this.push({ kind: 'user', key: `local${ts}`, ts, job: null, text, assets: assetIds });
    await this.startJob(text, assetIds, ts);
  }

  /**
   * First message from the home page: shown at once with local previews, the job starts once the files are in. A file
   * that did not get there stops it: a job without its photo spends money on the wrong thing. Retry goes on from there.
   */
  async sendFiles(text: string, files: File[], ids: string[] = [], key = `local${Date.now() / 1000}`) {
    const ts = Number(key.slice(5));
    if (!this.timeline.some((x) => x.key === key)) {
      const previews = files.filter((f) => f.type.startsWith('image/')).map((f) => URL.createObjectURL(f));
      this.push({ kind: 'user', key, ts, job: null, text, assets: [], previews });
    }
    ids = [...ids];
    try {
      for (const [i, f] of files.entries()) {
        this.starting = files.length > 1 ? t('uploading_n', { i: i + 1, n: files.length }) : t('uploading_one');
        const kind = f.type.startsWith('video/') ? 'video' : f.type.startsWith('audio/') ? 'audio' : 'photo';
        const a = await this.upload(f, kind, undefined, () => this.sendFiles(text, files.slice(i), ids, key));
        if (!a) return;
        ids.push(a.id);
        this.spot(a, text);
      }
      const item = this.timeline.find((x) => x.key === key);
      if (item?.kind === 'user') item.assets = ids;
      await this.startJob(text, ids, ts);
    } finally {
      this.starting = null;
    }
  }

  private async startJob(text: string, assetIds: string[], ts: number) {
    // a job that is still stopping holds the slot: starting now would be refused
    await this.stopped();
    if (this.disposed) return;
    // nothing else says the message is on its way, and a second one must wait for the answer
    this.starting = t('agent_starting');
    try {
      const r = await api.send(this.id, text, assetIds, { model: chosenModel(), reasoning: prefs.reasoning });
      this.jobId = r.job_id;
      this.jobKind = 'design';
      this.job(r.job_id, ts + 0.001, 'design');
    } catch (e) {
      this.fail(e, () => void this.startJob(text, assetIds, ts));
    } finally {
      this.starting = null;
    }
  }

  continueJob() {
    return this.send(t('continue_msg'));
  }

  async answer(item: Extract<TimelineItem, { kind: 'ask' }>, answer: string) {
    if (this.refused()) return;
    try {
      await api.answer(item.job_id, answer);
      item.answered = answer;
    } catch (e) {
      this.fail(e);
    }
  }

  /**
   * Stop the running job. The server only signals it, and the job keeps its slot until it has
   * wound down, so the job stays current (and sending waits) until its job.finished arrives,
   * or until the project shows it is no longer running.
   */
  async cancel() {
    const id = this.jobId;
    if (!id) return;
    if (!this.stopping) {
      this.stopping = true;
      this.stoppingJob = id;
      try {
        await api.cancel(id);
      } catch (e) {
        // 404: nothing runs under this id on the server (it ended meanwhile, or a restart lost it)
        if (e instanceof ApiError && e.status === 404) this.release(id, 'cancelled');
        else this.fail(e);
      }
      if (this.stoppingJob === id) this.pollStopped(id, 6);
    }
    return this.stopped();
  }

  /** Resolves once no stop is in progress. */
  private stopped(): Promise<void> {
    return this.stopping ? new Promise((resolve) => this.stopWaiters.push(resolve)) : Promise.resolve();
  }

  // In case job.finished is missed (stream reconnecting): look every 10 s, give up after a minute.
  private pollStopped(id: string, tries: number) {
    if (this.stopTimer) clearTimeout(this.stopTimer);
    this.stopTimer = setTimeout(async () => {
      let job: ProjectDetail['job'] | undefined;
      try {
        job = (await api.project(this.id)).job;
      } catch {
        /* look again */
      }
      if (this.disposed || this.stoppingJob !== id) return;
      const over = job !== undefined && (job?.id !== id || (job.status !== 'running' && job.status !== 'waiting'));
      if (!over && tries > 1) return this.pollStopped(id, tries - 1);
      this.release(id, over ? (job?.id === id ? job.status : 'cancelled') : undefined);
    }, 10000);
  }

  /** The job is over as far as the server knows: let go of it here; `status` closes its card. */
  private release(id: string, status?: string) {
    const j = this.jobs[id];
    if (status && j && !j.finished) j.status = status;
    if (this.jobId === id) {
      this.jobId = null;
      this.jobKind = null;
      this.status = null;
    }
    this.endStop();
  }

  private endStop() {
    if (this.stopTimer) clearTimeout(this.stopTimer);
    this.stopTimer = null;
    this.stopping = false;
    this.stoppingJob = null;
    for (const resolve of this.stopWaiters.splice(0)) resolve();
  }

  async startSide(fn: () => Promise<{ job_id: string }>) {
    await this.stopped();
    if (this.disposed || this.refused()) return;
    try {
      const r = await fn();
      this.jobId = r.job_id;
    } catch (e) {
      this.fail(e, () => void this.startSide(fn));
    }
  }

  /** A photo taken through the phone capture link lands in the composer tray, and its object is found at once. */
  private fromPhone(a: AssetOut) {
    if (this.readonly || this.replaying || this.tray.some((x) => x.id === a.id)) return;
    this.tray.push(a);
    this.spot(a);
    this.phoneToast = a;
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => (this.phoneToast = null), 5000);
  }

  addError(text: string, info: { code?: string; projectId?: string; retry?: () => void } = {}) {
    this.push({ kind: 'error', key: `err${Date.now()}${Math.random()}`, ts: Date.now() / 1000, job: null, text, code: info.code, projectId: info.projectId, retry: info.retry });
  }

  /** `retry` stays with a failure that may pass or that a moment's wait can cure (another run still holding the slot). */
  private fail(e: unknown, retry?: () => void) {
    const info = errorInfo(e);
    const again = isTransient(e) || info.code === 'job_running' || info.code === 'project_busy';
    this.addError(info.text, { ...info, retry: again ? retry : undefined });
  }

  /** The Retry button of an error: the error goes, its action runs again. */
  retryError(key: string) {
    const item = this.timeline.find((x) => x.key === key);
    if (item?.kind !== 'error') return;
    this.timeline = this.timeline.filter((x) => x.key !== key);
    item.retry?.();
  }
}
