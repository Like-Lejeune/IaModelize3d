// The studio's state for one project: the conversation with the designer agent (from the project's event stream),
// the current program and its parameters, the model built in the browser, the versions. A plain class that notifies
// React (useStudio below); a simplified port of web/src/lib/project.svelte.ts (IaModelize3d).
import { useEffect, useMemo, useSyncExternalStore } from "react";
import { ApiError } from "../api";
import { GeomClient } from "../geom/client";
import type { BuildResult, CheckReport, EventRow, ParamSpec, ProjectDetail, VersionRow } from "../geom/types";
import { projects } from "./api";
import { streamEvents, type EventStream } from "./sse";

type Base = { key: string; ts: number; job?: string | null };
export type Item =
  | (Base & { kind: "user"; text: string; previews?: string[] })
  | (Base & { kind: "agent"; text: string })
  | (Base & { kind: "status"; text: string })
  | (Base & { kind: "tool"; id: string; name: string; title?: string; ok?: boolean; summary?: string; image?: string })
  | (Base & { kind: "ask"; jobId: string; questionId: string; question: string; options: string[]; allowText: boolean; answered?: string })
  | (Base & { kind: "program"; version: number; summary?: string; render?: string; author?: string })
  | (Base & { kind: "critic"; verdict: string; issues: { text?: string; message?: string }[] })
  | (Base & { kind: "error"; text: string; code?: string });

export interface JobState {
  id: string;
  status: "running" | "waiting" | "done" | "failed" | "cancelled" | "refused" | string;
  started: number;
  finished?: number;
}

const label = (o: any): string => (typeof o === "string" ? o : String(o?.label ?? o?.value ?? ""));

export class StudioStore {
  // what React reads
  detail: ProjectDetail | null = null;
  loadError: string | null = null;
  items: Item[] = [];
  job: JobState | null = null;
  statusText: string | null = null;
  sending = false;
  stopping = false;

  source: string | null = null;
  inputs: Record<string, any> | null = null;
  values: Record<string, any> = {};
  specs: Record<string, ParamSpec> = {};
  version = 0;
  build: BuildResult | null = null;
  checks: CheckReport | null = null;
  building = false;
  buildError: string | null = null;
  versions: VersionRow[] = [];
  saving = false;
  saveError: string | null = null;

  private listeners = new Set<() => void>();
  private tick = 0;
  private stream: EventStream | null = null;
  private seen = new Set<number>();
  private historySeq = 0;
  private geom = new GeomClient();
  private rev = 0;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;
  private loadToken = 0;
  readonly clientId = `react-${Math.random().toString(36).slice(2, 10)}`;

  constructor(public readonly id: string) {}

  // ---------------------------------------------------------------- React glue
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  snapshot = () => this.tick;
  private changed() {
    this.tick++;
    for (const fn of this.listeners) fn();
  }

  get working() {
    return !!this.job && (this.job.status === "running" || this.job.status === "waiting");
  }

  get waitingAnswer() {
    return [...this.items].reverse().find((x): x is Extract<Item, { kind: "ask" }> => x.kind === "ask" && !x.answered) ?? null;
  }

  // ---------------------------------------------------------------- loading
  async load() {
    if (this.disposed) {
      // React's StrictMode mounts, unmounts and mounts again in development: start afresh
      this.disposed = false;
      this.geom = new GeomClient();
      this.seen.clear();
      this.items = [];
    }
    const token = ++this.loadToken;
    try {
      const d = await projects.get(this.id);
      if (this.disposed || token !== this.loadToken) return;
      this.detail = d;
      this.historySeq = d.last_seq;
      if (d.job && (d.job.status === "running" || d.job.status === "waiting")) this.job = { id: d.job.id, status: d.job.status, started: Date.now() / 1000 };
      if (d.program) {
        this.source = d.program.source;
        this.inputs = d.program.inputs ?? null;
        this.values = { ...(d.program.params ?? {}) };
        this.version = d.program.version;
        if (this.inputs && Object.keys(this.inputs).length) this.geom.setInputs(this.inputs);
        this.rebuild("final");
      }
      this.changed();
      this.stream = streamEvents(this.id, 0, (e) => this.onEvent(e));
      this.loadVersions();
    } catch (e) {
      this.loadError = e instanceof ApiError && e.status === 404 ? "Ce projet n'existe pas ou n'est pas à vous." : "Le projet n'a pas pu être chargé.";
      this.changed();
    }
  }

  async loadVersions() {
    try {
      this.versions = await projects.versions(this.id);
      this.changed();
    } catch {
      /* the list is a convenience */
    }
  }

  dispose() {
    this.disposed = true;
    this.stream?.close();
    this.geom.dispose();
    if (this.saveTimer) clearTimeout(this.saveTimer);
  }

  // ---------------------------------------------------------------- events from the agent
  private push(item: Item) {
    if (this.items.some((x) => x.key === item.key)) return;
    this.items = [...this.items, item].sort((a, b) => a.ts - b.ts);
  }

  private onEvent(e: EventRow) {
    if (this.disposed || this.seen.has(e.seq)) return;
    this.seen.add(e.seq);
    const d = e.data ?? {};
    const key = `e${e.seq}`;
    const ts = e.ts;
    const jid = e.job_id ?? d.job_id ?? null;
    const live = e.seq > this.historySeq;
    switch (e.type) {
      case "job.started":
        if (live || (jid && jid === this.job?.id)) this.job = { id: jid, status: "running", started: ts };
        break;
      case "job.finished":
        if (this.job && (!jid || jid === this.job.id)) {
          this.job = { ...this.job, status: d.summary === "refused" ? "refused" : d.status ?? "done", finished: ts };
          this.statusText = null;
          this.stopping = false;
        }
        this.items = this.items.map((x) => (x.kind === "ask" && x.jobId === jid && !x.answered ? { ...x, answered: "—" } : x));
        if (live) this.loadVersions();
        break;
      case "user.message": {
        // our own message is already shown with its local previews
        const mine = this.items.find((x) => x.kind === "user" && x.text === d.text && Math.abs(x.ts - ts) < 600);
        if (!mine) this.push({ kind: "user", key, ts, text: d.text ?? "" });
        break;
      }
      case "agent.message":
        if (d.text) this.push({ kind: "agent", key, ts, job: jid, text: d.text });
        break;
      case "agent.status":
        if (live) this.statusText = d.text ?? null;
        this.push({ kind: "status", key, ts, job: jid, text: d.text ?? "" });
        break;
      case "tool.call":
        this.push({ kind: "tool", key, ts, job: jid, id: d.id ?? key, name: d.name ?? "outil", title: d.title });
        break;
      case "tool.result": {
        const call = [...this.items].reverse().find((x) => x.kind === "tool" && (x.id === d.id || (!d.id && x.name === d.name && x.ok === undefined)));
        if (call && call.kind === "tool") {
          this.items = this.items.map((x) => (x === call ? { ...call, ok: d.ok !== false, summary: d.summary, image: d.image } : x));
        } else if (d.name !== "build") {
          this.push({ kind: "tool", key, ts, job: jid, id: d.id ?? key, name: d.name ?? "outil", title: d.title, ok: d.ok !== false, summary: d.summary, image: d.image });
        }
        break;
      }
      case "program.updated":
        if (d.author !== "user") this.push({ kind: "program", key, ts, job: jid, version: d.version, summary: d.summary, render: d.render, author: d.author });
        if (live) void this.onProgram(d);
        break;
      case "critic":
        this.push({ kind: "critic", key, ts, job: jid, verdict: d.verdict ?? "revise", issues: d.issues ?? [] });
        break;
      case "ask":
        this.push({
          kind: "ask", key, ts, job: jid, jobId: d.job_id ?? jid ?? "", questionId: d.question_id ?? key, question: d.question ?? "",
          options: (d.options ?? []).map(label).filter(Boolean), allowText: d.allow_text !== false,
        });
        if (this.job && jid === this.job.id) this.job = { ...this.job, status: "waiting" };
        break;
      case "answer":
        this.items = this.items.map((x) => (x.kind === "ask" && x.questionId === d.question_id ? { ...x, answered: d.answer ?? "—" } : x));
        if (this.job?.status === "waiting") this.job = { ...this.job, status: "running" };
        break;
      case "error":
      case "job.failed":
        this.push({ kind: "error", key, ts, job: jid, text: d.message ?? d.error ?? "Une erreur est survenue.", code: d.code });
        break;
      default:
        return;
    }
    this.changed();
  }

  /** A new version from the agent (or another tab): take its program and rebuild. Our own save coming back is skipped. */
  private async onProgram(d: any) {
    if (typeof d.version !== "number" || d.version < this.version) return;
    this.version = d.version;
    if (d.client && d.client === this.clientId) return;
    let source: string | undefined = d.source;
    let inputs = d.inputs;
    let params = d.params;
    if (!source && (d.author !== "user" || d.source_changed)) {
      try {
        const p = await projects.program(this.id, d.version);
        source = p.source;
        inputs = p.inputs;
        params ??= p.params;
      } catch {
        return;
      }
    }
    if (source) this.source = source;
    if (inputs) {
      this.inputs = inputs;
      this.geom.setInputs(inputs);
    }
    this.values = { ...(params ?? this.values) };
    this.rebuild("final");
    this.changed();
  }

  // ---------------------------------------------------------------- building in the browser
  /** Builds the current program with the current values; a newer call makes an older one's result stale. */
  async rebuild(quality: "preview" | "final") {
    if (!this.source) return;
    const rev = ++this.rev;
    const args = { source: this.source, params: this.values };
    this.building = true;
    this.changed();
    if (quality === "preview") {
      const r = await this.geom.preview({ ...args, quality: "preview" });
      if (rev !== this.rev || this.disposed) return;
      this.took(r);
      return;
    }
    const r = await this.geom.finalize(args, (display) => {
      if (rev !== this.rev || this.disposed) return;
      this.took(display);
      this.building = true; // the checks are still coming
      this.changed();
    });
    if (rev !== this.rev || this.disposed) return;
    this.building = false;
    if (r.ok) this.checks = r.checks;
    else if ((r as any).stage !== "superseded") this.buildError = (r as any).message ?? "La construction du modèle a échoué.";
    this.changed();
  }

  private took(r: BuildResult | { ok: false; stage?: string; message?: string }) {
    if (!r.ok) {
      if (r.stage !== "superseded") this.buildError = r.message ?? "La construction du modèle a échoué.";
      this.building = false;
      this.changed();
      return;
    }
    this.build = r;
    this.specs = r.paramSpecs ?? {};
    this.buildError = null;
    if (r.checks) this.checks = r.checks;
    this.building = false;
    this.changed();
  }

  // ---------------------------------------------------------------- what the person does
  /** A slider moves (commit=false: preview only) or is released (commit: full build, then saved as a version). */
  setParam(name: string, value: any, commit: boolean) {
    this.values = { ...this.values, [name]: value };
    this.changed();
    void this.rebuild(commit ? "final" : "preview");
    if (commit) this.scheduleSave();
  }

  resetParams() {
    const defaults: Record<string, any> = {};
    for (const [k, s] of Object.entries(this.specs)) defaults[k] = s.value;
    this.values = { ...this.values, ...defaults };
    void this.rebuild("final");
    this.scheduleSave();
    this.changed();
  }

  private scheduleSave() {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => void this.flushSave(), 700);
  }

  private async flushSave() {
    this.saveTimer = null;
    this.saving = true;
    this.changed();
    try {
      const checks = this.checks ? { ...this.checks } : undefined;
      const r = await projects.saveParams(this.id, this.values, checks, this.clientId);
      this.version = Math.max(this.version, r.version);
      this.saveError = null;
      void this.loadVersions();
    } catch (e) {
      this.saveError = e instanceof ApiError ? e.message : "Le réglage n'a pas pu être enregistré.";
    } finally {
      this.saving = false;
      this.changed();
    }
  }

  /** Sends a message (and photos) to the designer: it starts a run, or answers the question waiting if there is one. */
  async send(text: string, files: File[] = []) {
    const ask = this.waitingAnswer;
    if (ask && !files.length) return this.answer(ask, text);
    const ts = Date.now() / 1000;
    const previews = files.filter((f) => f.type.startsWith("image/")).map((f) => URL.createObjectURL(f));
    this.push({ kind: "user", key: `local${ts}`, ts, text, previews });
    this.sending = true;
    this.changed();
    try {
      const ids: string[] = [];
      for (const f of files) ids.push((await projects.upload(this.id, f)).id);
      const r = await projects.send(this.id, text, ids);
      this.job = { id: r.job_id, status: "running", started: ts };
    } catch (e) {
      const a = e as ApiError;
      const text =
        a.code === "job_running" ? "L'IA travaille déjà sur ce projet. Attendez la fin ou arrêtez-la."
        : a.status === 429 ? "La limite d'utilisation du jour est atteinte. Réessayez demain."
        : a.message || "Le message n'a pas pu être envoyé.";
      this.push({ kind: "error", key: `err${Date.now()}`, ts: Date.now() / 1000, text, code: a.code });
    } finally {
      this.sending = false;
      this.changed();
    }
  }

  async answer(item: Extract<Item, { kind: "ask" }>, text: string) {
    try {
      await projects.answer(item.jobId, text);
      this.items = this.items.map((x) => (x.key === item.key ? { ...item, answered: text } : x));
    } catch {
      this.push({ kind: "error", key: `err${Date.now()}`, ts: Date.now() / 1000, text: "La réponse n'a pas pu être envoyée." });
    }
    this.changed();
  }

  async cancel() {
    if (!this.job || this.stopping) return;
    this.stopping = true;
    this.changed();
    try {
      await projects.cancel(this.job.id);
    } catch {
      /* already over */
    }
  }

  /** An earlier version becomes the current one again, as a new version. */
  async restore(version: number) {
    const p = await projects.program(this.id, version);
    this.source = p.source;
    this.inputs = p.inputs ?? null;
    if (this.inputs && Object.keys(this.inputs).length) this.geom.setInputs(this.inputs);
    this.values = { ...p.params };
    this.changed();
    await this.rebuild("final");
    const r = await projects.saveProgram(this.id, { source: p.source, params: p.params, summary: `version ${version} restaurée`, client: this.clientId });
    this.version = r.version;
    void this.loadVersions();
    this.changed();
  }

  async exportStl(title: string) {
    if (!this.source) return;
    const blob = await this.geom.exportFile({ source: this.source, params: this.values, format: "stl", title });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${title.replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "") || "modele"}.stl`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
}

/** The store of project `id`, created once per id and disposed when the page leaves it. */
export function useStudio(id: string): StudioStore {
  const store = useMemo(() => new StudioStore(id), [id]);
  useEffect(() => {
    void store.load();
    return () => store.dispose();
  }, [store]);
  useSyncExternalStore(store.subscribe, store.snapshot);
  return store;
}
