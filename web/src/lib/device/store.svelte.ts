// The device graph of a project as the node editor and the Device tab see it: the server's document and its view
// (pins and their nets, part cards), the person's edits applied at once and saved a moment later, and the build that
// is running ('device.build' events) until its PCB version arrives.
import { ApiError, errorText } from '$lib/api';
import { deviceApi, type DevNet, type DevNode, type DeviceDoc, type DeviceState, type Edge } from './api';

export type BuildInfo = {
  running: boolean;
  attempt?: number;
  size?: [number, number];
  ok?: boolean;
  pcbVersion?: number | null;
  programVersion?: number | null;
  error?: string | null;
  errors?: { type?: string; message?: string; hint?: string }[];
  at?: number;
};

const PREFIX: Record<string, string> = {
  module: 'U', chip: 'U', resistor: 'R', capacitor: 'C', led: 'LED', diode: 'D', button: 'SW', header: 'J', usb_c: 'J', jst: 'J', hole: 'H',
};
export const EDGE_KINDS = ['usb_c', 'header', 'jst', 'module'];
// supply and ground nets are labels on their pins rather than wires (device.py POWER_NET)
export const POWER_NET = /^(GND|AGND|V3V3|V3V|V1V8|V5|V5V|VBUS|VSYS|VBAT|VIN|VCC|VDD|V12|V9)$/i;

export class DeviceStore {
  state = $state.raw<DeviceState | null>(null);
  loaded = $state(false);
  error = $state<string | null>(null);
  selected = $state<string | null>(null);
  /** The net picked in the Outliner (its name, or '#<index>' for an unnamed one): its wires and pins light up. */
  selectedNet = $state<string | null>(null);
  /** Earlier documents of this sitting, for undo (Ctrl+Z) and redo. */
  private past: DeviceDoc[] = [];
  private future: DeviceDoc[] = [];
  canUndo = $state(false);
  canRedo = $state(false);
  saving = $state(false);
  build = $state<BuildInfo>({ running: false });
  /** Bumped when the agent (or another tab) wrote a version: the editor lays out nodes it has not placed yet. */
  arrived = $state(0);
  private timer: ReturnType<typeof setTimeout> | null = null;
  private rev = 0;
  private sentRev = 0;
  private pendingSummary = '';

  constructor(private projectId: string, private readonly canEdit: () => boolean) {}

  get doc(): DeviceDoc | null {
    return this.state?.doc ?? null;
  }
  get empty(): boolean {
    return !this.state || !this.state.doc.nodes.length;
  }
  /** The board on show was built from an older graph than the one in the editor. */
  get stale(): boolean {
    const s = this.state;
    if (!s?.pcb) return !!s?.doc.nodes.length;
    return s.pcb.stale;
  }

  async refresh() {
    if (this.timer || this.saving) return; // the person's edit wins; its save brings the server's view back
    try {
      const s = await deviceApi.get(this.projectId);
      this.state = s;
      this.error = null;
      if (s.building && !this.build.running) this.build = { running: true };
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) this.error = errorText(e);
    }
    this.loaded = true;
  }

  // ------------------------------------------------------------------ edits
  /** Apply an edit to the local document at once and save it shortly after (several quick edits go in one save). */
  edit(mutate: (d: DeviceDoc) => void, summary = '') {
    if (!this.state || !this.canEdit()) return;
    const before = structuredClone($state.snapshot(this.state.doc)) as DeviceDoc;
    const doc: DeviceDoc = structuredClone(before);
    mutate(doc);
    if (JSON.stringify(doc) === JSON.stringify(before)) return;
    this.past.push(before);
    if (this.past.length > 60) this.past.shift();
    this.future = [];
    this.canUndo = true;
    this.canRedo = false;
    this.state = { ...this.state, doc };
    this.rev++;
    if (summary) this.pendingSummary = summary;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), 500);
  }

  async flush() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (!this.state || this.sentRev === this.rev) return;
    const rev = this.rev;
    this.sentRev = rev;
    this.saving = true;
    try {
      const s = await deviceApi.put(this.projectId, this.state.doc, this.pendingSummary);
      // a newer edit is already on the way: keep the local document, take the server's view of the pins
      if (rev === this.rev) this.state = s;
      else this.state = { ...s, doc: this.state.doc };
      this.error = null;
    } catch (e) {
      this.error = errorText(e);
    } finally {
      this.saving = false;
    }
    if (this.sentRev !== this.rev && !this.timer) this.timer = setTimeout(() => this.flush(), 300);
  }

  /** Back to the document before the last edit (and forward again): saved like any edit. */
  undo() {
    this.travel(this.past, this.future);
  }
  redo() {
    this.travel(this.future, this.past);
  }
  private travel(from: DeviceDoc[], to: DeviceDoc[]) {
    if (!this.state || !from.length || !this.canEdit()) return;
    to.push(structuredClone($state.snapshot(this.state.doc)) as DeviceDoc);
    const doc = from.pop()!;
    this.state = { ...this.state, doc };
    this.canUndo = this.past.length > 0;
    this.canRedo = this.future.length > 0;
    this.rev++;
    if (this.selected && !doc.nodes.some((n) => n.id === this.selected)) this.selected = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), 400);
  }

  /** Pick a part (the net selection goes) or a net (the part selection goes). */
  pickNode(id: string | null) {
    this.selected = id;
    if (id) this.selectedNet = null;
  }
  pickNet(key: string | null) {
    this.selectedNet = key;
    if (key) this.selected = null;
  }

  nextId(kind: string): string {
    const prefix = PREFIX[kind] ?? 'U';
    const used = new Set(this.doc?.nodes.map((n) => n.id) ?? []);
    let i = 1;
    while (used.has(`${prefix}${i}`)) i++;
    return `${prefix}${i}`;
  }

  addNode(node: Omit<DevNode, 'id'> & { id?: string }, at?: [number, number]): string {
    const id = node.id ?? this.nextId(node.kind);
    this.edit((d) => {
      d.nodes.push({ ...node, id, ...(at ? { ui: [Math.round(at[0]), Math.round(at[1])] } : {}) } as DevNode);
    }, `added ${id}`);
    this.selected = id;
    return id;
  }

  removeNodes(ids: string[]) {
    if (!ids.length) return;
    const drop = new Set(ids);
    this.edit((d) => {
      d.nodes = d.nodes.filter((n) => !drop.has(n.id));
      d.nets = d.nets.map((n) => ({ ...n, pins: n.pins.filter((p) => !drop.has(p.split('.')[0])) })).filter((n) => n.pins.length >= 2 || n.name);
    }, `removed ${ids.join(', ')}`);
    if (this.selected && drop.has(this.selected)) this.selected = null;
  }

  setNode(id: string, fields: Partial<DevNode>) {
    this.edit((d) => {
      const n = d.nodes.find((x) => x.id === id);
      if (n) {
        Object.assign(n, fields);
        for (const k of Object.keys(fields) as (keyof DevNode)[]) if (fields[k] === undefined || fields[k] === '') delete n[k];
      }
    }, `changed ${id}`);
  }

  move(positions: Record<string, [number, number]>) {
    this.edit((d) => {
      for (const n of d.nodes) if (positions[n.id]) n.ui = [Math.round(positions[n.id][0]), Math.round(positions[n.id][1])];
    });
  }

  /** Join two pins: into the net either is on (two nets become one), or a new net. */
  connect(a: string, b: string, name?: string) {
    if (a === b) return;
    this.edit((d) => {
      const na = d.nets.find((n) => n.pins.includes(a));
      const nb = d.nets.find((n) => n.pins.includes(b));
      if (na && nb && na === nb) return;
      if (na && nb) {
        na.pins.push(...nb.pins.filter((p) => !na.pins.includes(p)));
        if (!na.name && nb.name) na.name = nb.name;
        d.nets = d.nets.filter((n) => n !== nb);
      } else if (na) na.pins.push(b);
      else if (nb) nb.pins.push(a);
      else d.nets.push({ pins: [a, b], ...(name ? { name } : {}) });
    }, `connected ${a} – ${b}`);
  }

  /** Put a pin on the named net (made if missing), or take it off every net with name ''. */
  assign(pin: string, net: string) {
    this.edit((d) => {
      for (const n of d.nets) n.pins = n.pins.filter((p) => p !== pin);
      if (net) {
        const target = d.nets.find((n) => (n.name ?? '') === net) ?? d.nets[Number(net.replace(/^#/, ''))];
        if (target) target.pins.push(pin);
        else d.nets.push({ name: net, pins: [pin] });
      }
      d.nets = d.nets.filter((n) => n.pins.length >= 2 || (n.name && n.pins.length));
    }, net ? `${pin} to ${net}` : `disconnected ${pin}`);
  }

  /** Remove the wire between two pins: the second pin leaves the net. */
  cut(a: string, b: string) {
    this.edit((d) => {
      const net = d.nets.find((n) => n.pins.includes(a) && n.pins.includes(b));
      if (!net) return;
      net.pins = net.pins.filter((p) => p !== b);
      d.nets = d.nets.filter((n) => n.pins.length >= 2 || (n.name && n.pins.length));
    }, `cut ${a} – ${b}`);
  }

  setEdge(id: string, edge: Edge | '') {
    this.setNode(id, { edge: (edge || undefined) as Edge | undefined });
  }

  netOf(pin: string): DevNet | null {
    return this.doc?.nets.find((n) => n.pins.includes(pin)) ?? null;
  }

  // ------------------------------------------------------------------ build
  async startBuild() {
    await this.flush();
    this.build = { running: true };
    try {
      await deviceApi.build(this.projectId);
    } catch (e) {
      this.build = { running: false, ok: false, error: errorText(e), at: Date.now() };
    }
  }

  /** 'device.version' and 'device.build' from the project's event stream. */
  onEvent(type: string, d: any) {
    if (type === 'device.version') {
      if (d.author !== 'user') this.arrived++;
      this.refresh();
    } else if (type === 'device.build') {
      if (d.state === 'start') this.build = { running: true };
      else if (d.state === 'attempt') this.build = { ...this.build, running: true, attempt: d.attempt, size: d.size_mm };
      else if (d.state === 'done') {
        this.build = {
          running: false, ok: !!d.ok, pcbVersion: d.pcb_version ?? null, programVersion: d.program_version ?? null, size: d.size_mm,
          error: d.error ?? null, errors: d.errors ?? [], at: Date.now(),
        };
        this.refresh();
      }
    }
  }
}
