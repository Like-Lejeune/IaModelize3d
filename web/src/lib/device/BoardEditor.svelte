<script lang="ts">
  // The board editor, one canvas as in KiCad's or EasyEDA's PCB editor: both copper layers (the active one in front),
  // parts, traces, pours and keepouts. Tools on the left: select and move (Esc), route (X), copper pour (Z), keepout (K),
  // measure (M). The grid (G shows it, N changes its step) and the magnet pull every point to the grid, pad centres,
  // vias, trace corners and the board's edges, and a moved part lines up with its neighbours' centres and pads (guides
  // show where); Shift moves freely. Drag a part to move it, R turns it; X over a pad (or the route tool and a click on a pad) starts a
  // trace: clicks put 45/90 degree corners, V or 1/2 drops a via, / turns the bend, a pad of the same net finishes,
  // Backspace steps back, Esc or the right button cancels. A right click elsewhere opens the menu of what is under it;
  // the middle or right button drags the view, the wheel zooms, F fits. Every change goes into the device document at
  // once (Ctrl+Z undoes it); "Route" in the workspace header builds the board again: hand traces and placements stay,
  // the autorouter joins the rest, the pours fill, DRC checks it all. A part's card says who placed it: the person (pcb),
  // the AI engineer (place, or a layout such as the dice pips: a dotted outline) or the build; dragging makes it the person's.
  import { apiError, deadline, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import { pcbApi } from '$lib/pcb/api';
  import type { ProjectStore } from '$lib/project.svelte';
  import type { DeviceDoc, DevNode } from './api';
  import { dt, patternName } from './i18n';
  import { layoutOf, placedBy } from './facets';
  import {
    align, carry, flip, lockTrace, octi, readCopper, routeCopper, segLength, unrouted,
    type Layer, type Pad, type Pose, type Pt, type Route, type Seg,
  } from './copper';

  type Zone = NonNullable<DeviceDoc['zones']>[number];
  let { store, readonly = false }: { store: ProjectStore; readonly?: boolean } = $props();

  const dev = $derived(store.device);
  const pcbV = $derived(store.pcb.versions.at(-1) ?? null);
  let cj = $state.raw<any[] | null>(null);
  let loadedFor = 0;
  let err = $state<string | null>(null);
  let attempt = $state(0);
  // loaded only once it is in: a version that failed is asked for again (the retry below, or the next version)
  $effect(() => {
    const v = pcbV?.version;
    void attempt;
    if (!v || v === loadedFor) return;
    let current = true;
    fetch(pcbApi.url(store.id, v, 'circuit.json'), { credentials: 'same-origin', signal: deadline(60_000) })
      .then(async (r) => (r.ok ? r.json() : Promise.reject(await apiError(r))))
      .then((j) => {
        if (!current) return;
        loadedFor = v;
        cj = j;
        err = null;
        hidden = new Set();
        sel = null;
        draft = null;
      })
      .catch((e) => {
        if (current) err = errorText(e);
      });
    return () => {
      current = false;
    };
  });

  const copper = $derived(cj ? readCopper(cj) : null);
  const doc = $derived(dev.state?.doc ?? null);
  const routes = $derived((doc?.routes ?? []) as Route[]);
  const zones = $derived((doc?.zones ?? []) as Zone[]);
  const built = $derived(new Map((copper?.parts ?? []).map((p) => [p.id, p])));
  const groupOf = $derived(Object.fromEntries(Object.entries(dev.state?.view.groups ?? {}).flatMap(([chip, caps]) => caps.map((c) => [c, chip]))) as Record<string, string>);
  const nodeOf = $derived(new Map((doc?.nodes ?? []).map((n) => [n.id, n])));
  const W = $derived(doc?.board.w ?? copper?.board.w ?? 30);
  const H = $derived(doc?.board.h ?? copper?.board.h ?? 30);
  // the plate's corners: a round board is all corner, a rounded one has the radius it was built with
  const cornerR = $derived(doc?.board.shape === 'round' ? Math.min(W, H) / 2 : doc?.board.shape === 'rounded' ? (doc.board.r ?? Math.min(W, H) / 6) : 0.6);

  // ---- tools and state
  type Tool = 'select' | 'route' | 'pour' | 'keepout' | 'measure';
  let tool = $state<Tool>('select');
  let layer = $state<Layer>('top');
  let width = $state(0.25);
  let pourNet = $state('GND');
  let keepBoth = $state(true);
  let diagFirst = $state(false);
  /** Autorouted traces deleted here: the next build routes those connections again unless drawn by hand. */
  let hidden = $state<Set<string>>(new Set());
  type Sel = { kind: 'part'; id: string } | { kind: 'auto'; id: string } | { kind: 'hand'; i: number } | { kind: 'zone'; i: number };
  let sel = $state<Sel | null>(null);
  type Draft = { from: string; net: string; start: [number, number]; layer0: Layer; layer: Layer; points: Pt[] };
  let draft = $state<Draft | null>(null);
  let cursor = $state<[number, number] | null>(null);
  let hoverPad = $state<Pad | null>(null);
  let moving = $state<Map<string, Pose> | null>(null);
  let rect = $state<{ tool: 'pour' | 'keepout'; a: [number, number]; b: [number, number] } | null>(null);
  let meas = $state<{ a: [number, number]; b: [number, number] } | null>(null);
  let menu = $state<{ x: number; y: number; items: { label: string; key?: string; run: () => void; danger?: boolean }[] } | null>(null);
  let keysOpen = $state(false);
  let flash = $state<string | null>(null);
  let flashTimer: ReturnType<typeof setTimeout> | null = null;
  function say(msg: string) {
    flash = msg;
    if (flashTimer) clearTimeout(flashTimer);
    flashTimer = setTimeout(() => (flash = null), 2600);
  }
  const WIDTHS = [0.2, 0.25, 0.3, 0.4, 0.5, 0.8];
  // the grid and the magnet, remembered for this viewer
  const GRIDS = [0.1, 0.25, 0.5, 1, 1.27, 2.54];
  const saved = (() => {
    try {
      return JSON.parse(localStorage.getItem('fw_board_grid') ?? 'null');
    } catch {
      return null;
    }
  })();
  let gridMm = $state<number>(GRIDS.includes(saved?.g) ? saved.g : 0.5);
  let showGrid = $state<boolean>(saved?.show ?? true);
  let magnet = $state<boolean>(saved?.magnet ?? true);
  $effect(() => {
    const v = JSON.stringify({ g: gridMm, show: showGrid, magnet });
    try {
      localStorage.setItem('fw_board_grid', v);
    } catch {
      // private window: the defaults next time
    }
  });
  let guides = $state<{ x?: number; y?: number }>({});
  let pointer = $state<[number, number] | null>(null);
  let boxW = $state(800);
  let boxH = $state(600);
  const WIDE = /^(V5|V5V|VBUS|VSYS|VBAT|VIN|V12|V9)$/i;
  const pourNets = $derived((doc?.nets ?? []).map((n) => n.name).filter((n): n is string => !!n && !WIDE.test(n)));

  // ---- where everything stands now: a part placed by hand at its pin, a capacitor with its chip, else as routed
  const poses = $derived.by(() => {
    const m = new Map<string, Pose>();
    if (!copper) return m;
    for (const p of copper.parts) {
      const own = moving?.get(p.id) ?? nodeOf.get(p.id)?.pcb;
      if (own) m.set(p.id, { x: own.x, y: own.y, rot: own.rot });
    }
    for (const p of copper.parts) {
      if (m.has(p.id)) continue;
      const chip = groupOf[p.id], cb = chip ? built.get(chip) : undefined, cp = chip ? m.get(chip) : undefined;
      if (cb && cp) {
        const [x, y] = carry(cb, cp, p.x, p.y);
        m.set(p.id, { x, y, rot: (((p.rot + cp.rot - cb.rot) % 360) + 360) % 360 });
      } else m.set(p.id, { x: p.x, y: p.y, rot: p.rot });
    }
    return m;
  });
  const turned = (id: string) => {
    const b = built.get(id), q = poses.get(id);
    return b && q ? ((((q.rot - b.rot) % 360) + 360) % 360) : 0;
  };
  const moved = $derived(new Set((copper?.parts ?? []).filter((p) => {
    const q = poses.get(p.id);
    return q && (Math.abs(q.x - p.x) > 0.005 || Math.abs(q.y - p.y) > 0.005 || q.rot !== p.rot);
  }).map((p) => p.id)));
  function padAt(p: Pad): [number, number] {
    const b = built.get(p.comp), q = poses.get(p.comp);
    return b && q ? carry(b, q, p.x, p.y) : [p.x, p.y];
  }
  function portAt(key: string): [number, number] | null {
    const o = copper?.portOf.get(key);
    const b = o ? built.get(o.comp) : undefined, q = o ? poses.get(o.comp) : undefined;
    if (o && b && q) return carry(b, q, b.x + o.dx, b.y + o.dy);
    return copper?.portAt.get(key) ?? null;
  }
  const padsNow = $derived((copper?.pads ?? []).map((p) => {
    const [x, y] = padAt(p);
    const swap = turned(p.comp) % 180 === 90;
    return { ...p, x, y, w: swap ? p.h : p.w, h: swap ? p.w : p.h };
  }));
  const partsNow = $derived((copper?.parts ?? []).map((p) => {
    const q = poses.get(p.id)!;
    const swap = turned(p.id) % 180 === 90;
    const by = placedBy(doc, nodeOf.get(p.id));
    return { id: p.id, x: q.x, y: q.y, w: swap ? p.h : p.w, h: swap ? p.w : p.h, rot: turned(p.id), silk: p.silk, pinned: by === 'person', designer: by === 'designer', moved: moved.has(p.id) };
  }));
  // an autorouted trace to a part that moved is out of date: its connection shows as a ratsnest line until the build
  const gone = $derived(new Set([...hidden, ...(copper?.traces ?? []).filter((t) => !t.hand && [t.from, t.to].some((k) => k && moved.has(k.split('.')[0]))).map((t) => t.id)]));

  type Item = { kind: 'auto' | 'hand'; key: string; id?: string; i?: number; net: string; segs: Seg[]; vias: [number, number][] };
  const items = $derived.by<Item[]>(() => {
    if (!copper) return [];
    const out: Item[] = copper.traces.filter((t) => !t.hand && !gone.has(t.id)).map((t) => ({ kind: 'auto', key: `a:${t.id}`, id: t.id, net: t.net, segs: t.segs, vias: t.vias }));
    const netOf = new Map(copper.pads.map((p) => [p.key, p.net]));
    routes.forEach((r, i) => {
      const a = portAt(r.from), b = portAt(r.to);
      if (!a || !b) return;
      const c = routeCopper(r, a, b);
      out.push({ kind: 'hand', key: `h:${i}`, i, net: netOf.get(r.from) ?? '', segs: c.segs, vias: c.vias });
    });
    return out;
  });
  const isSel = (it: Item) => !!sel && sel.kind === it.kind && (sel.kind === 'auto' ? it.id === sel.id : it.i === (sel as { i: number }).i);
  const ratsnest = $derived.by(() => {
    if (!copper) return [];
    const byKey = new Map(padsNow.map((p) => [`${p.key}@${p.dx},${p.dy}`, [p.x, p.y] as [number, number]]));
    return unrouted(copper, routes, gone, (p) => byKey.get(`${p.key}@${p.dx},${p.dy}`) ?? [p.x, p.y]);
  });
  // built pours where the document still asks for them
  const pours = $derived((copper?.pours ?? []).filter((p) => zones.some((z) => z.kind === 'pour' && z.layer === p.layer && z.net === p.net)));
  const front = $derived(draft?.layer ?? layer);
  const back = $derived(flip(front));

  const lastAt = $derived<[number, number] | null>(draft ? (draft.points.length ? [draft.points.at(-1)!.x, draft.points.at(-1)!.y] : draft.start) : null);
  const preview = $derived.by<[number, number][]>(() => {
    if (!draft || !cursor || !lastAt) return [];
    const corner = octi(lastAt, cursor, diagFirst);
    return corner ? [lastAt, corner, cursor] : [lastAt, cursor];
  });
  const draftSegs = $derived(draft ? routeCopper({ from: draft.from, to: '', layer: draft.layer0, width, points: draft.points }, draft.start, lastAt ?? draft.start).segs : []);
  const targets = $derived(draft ? padsNow.filter((p) => p.net === draft!.net && p.key !== draft!.from) : []);

  // ---- view
  let svg = $state<SVGSVGElement>();
  let vb = $state({ x: -30, y: -30, w: 60, h: 60 });
  let fitted = 0;
  export function fit() {
    const m = Math.max(W, H) * 0.12;
    vb = { x: -W / 2 - m, y: -H / 2 - m, w: W + 2 * m, h: H + 2 * m };
  }
  $effect(() => {
    if (!copper || fitted === pcbV?.version) return;
    fitted = pcbV?.version ?? 0;
    fit();
  });
  const scale = () => {
    const r = svg!.getBoundingClientRect();
    return Math.max(vb.w / r.width, vb.h / r.height);
  };
  const toBoard = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = svg!.getBoundingClientRect();
    const k = scale();
    const ox = vb.x + vb.w / 2 - (r.width * k) / 2, oy = vb.y + vb.h / 2 - (r.height * k) / 2;
    return [ox + (e.clientX - r.left) * k, -(oy + (e.clientY - r.top) * k)];
  };
  function wheel(e: WheelEvent) {
    e.preventDefault();
    const [bx, by] = toBoard(e);
    const f = Math.min(2, Math.max(0.5, Math.exp(e.deltaY * 0.0012)));
    const nw = Math.min(400, Math.max(3, vb.w * f)), nh = (vb.h * nw) / vb.w;
    vb = { x: bx - (bx - vb.x) * (nw / vb.w), y: -by - (-by - vb.y) * (nh / vb.h), w: nw, h: nh };
  }

  // ---- hit tests in board mm
  function padHit(x: number, y: number) {
    let best: (typeof padsNow)[number] | null = null;
    for (const p of padsNow) {
      const inside = p.round ? Math.hypot(x - p.x, y - p.y) <= Math.max(p.w, p.h) / 2 + 0.1 : Math.abs(x - p.x) <= p.w / 2 + 0.1 && Math.abs(y - p.y) <= p.h / 2 + 0.1;
      if (inside && (!best || Math.hypot(x - p.x, y - p.y) < Math.hypot(x - best.x, y - best.y))) best = p;
    }
    return best;
  }
  function partHit(x: number, y: number) {
    const hit = partsNow.filter((p) => Math.abs(x - p.x) <= p.w / 2 + 0.2 && Math.abs(y - p.y) <= p.h / 2 + 0.2);
    return hit.sort((a, b) => a.w * a.h - b.w * b.h)[0] ?? null;
  }
  function traceHit(x: number, y: number): Item | null {
    const tol = Math.max(0.2, 5 * scale());
    let best: [Item, number] | null = null;
    for (const it of items) {
      for (const s of it.segs) {
        const dx = s.x2 - s.x1, dy = s.y2 - s.y1, L = dx * dx + dy * dy;
        const t = L ? Math.max(0, Math.min(1, ((x - s.x1) * dx + (y - s.y1) * dy) / L)) : 0;
        const d = Math.hypot(x - (s.x1 + t * dx), y - (s.y1 + t * dy)) - s.w / 2 + (s.layer === front ? 0 : 0.05);
        if (d <= tol && (!best || d < best[1])) best = [it, d];
      }
    }
    return best?.[0] ?? null;
  }
  function zoneHit(x: number, y: number): number {
    // the smallest drawn zone under the point (a pour over the whole board is picked from its card or the menu)
    let best = -1, area = Infinity;
    zones.forEach((z, i) => {
      if (!z.rect) return;
      const [x0, y0, x1, y1] = z.rect;
      if (x >= x0 && x <= x1 && y >= y0 && y <= y1 && (x1 - x0) * (y1 - y0) < area) {
        best = i;
        area = (x1 - x0) * (y1 - y0);
      }
    });
    return best;
  }
  const grid = (v: number, step: number) => Math.round(Math.round(v / step) * step * 1000) / 1000;
  const r2 = (v: number) => Math.round(v * 100) / 100;
  const mmPerPx = $derived(Math.max(vb.w / Math.max(1, boxW), vb.h / Math.max(1, boxH)));
  // the magnet's reach: a few screen pixels, whatever the zoom
  const reach = () => 7 * mmPerPx;
  const free = (e: { shiftKey: boolean }) => !magnet || e.shiftKey;
  /** What the magnet pulls to besides the grid: pad centres, vias and trace corners. */
  const anchors = $derived.by(() => {
    const out: [number, number][] = padsNow.map((p) => [p.x, p.y]);
    for (const it of items) {
      for (const v of it.vias) out.push(v);
      for (const sg of it.segs) out.push([sg.x1, sg.y1], [sg.x2, sg.y2]);
    }
    return out;
  });
  function onAnchor(x: number, y: number): [number, number] | null {
    let best: [number, number] | null = null, bd = reach();
    for (const a of anchors) {
      const d = Math.hypot(a[0] - x, a[1] - y);
      if (d < bd) {
        bd = d;
        best = a;
      }
    }
    return best;
  }
  /** A trace corner: the grid, kept on the straight or diagonal line from the last corner. */
  const snapTo = (x: number, y: number, e: { shiftKey: boolean }): [number, number] => {
    if (free(e)) return [r2(x), r2(y)];
    const g: [number, number] = [grid(x, gridMm), grid(y, gridMm)];
    return lastAt ? align(lastAt, g, gridMm) : g;
  };
  /** A measured point: a pad, via or corner nearby, else the grid. */
  const snapPt = (x: number, y: number, e: { shiftKey: boolean }): [number, number] =>
    free(e) ? [r2(x), r2(y)] : (onAnchor(x, y) ?? [grid(x, gridMm), grid(y, gridMm)]);
  /** A zone's corner: the grid, or the board's edge when it is near. */
  function snapEdge(x: number, y: number, e: { shiftKey: boolean }): [number, number] {
    if (free(e)) return [r2(x), r2(y)];
    let gx = grid(x, gridMm), gy = grid(y, gridMm);
    for (const ex of [-W / 2, W / 2]) if (Math.abs(x - ex) < reach()) gx = ex;
    for (const ey of [-H / 2, H / 2]) if (Math.abs(y - ey) < reach()) gy = ey;
    return [gx, gy];
  }
  // the grid drawn: the step, or a multiple of it while the step is too dense to see
  const gridView = $derived.by(() => {
    let step = gridMm;
    for (const k of [1, 2, 5, 10, 20, 50, 100]) {
      step = gridMm * k;
      if (step / mmPerPx >= 8) break;
    }
    return { step, major: step * 5, r: 0.7 * mmPerPx };
  });

  // ---- edits (each one goes into the document; Ctrl+Z undoes it)
  const EDGE_OF_TURN: Record<string, Record<number, string>> = {
    module: { 0: '+y', 90: '-x', 180: '-y', 270: '+x' },
    usb_c: { 0: '-y', 90: '+x', 180: '+y', 270: '-x' },
  };
  function holdBoard(d: DeviceDoc) {
    if (!(d.board.w && d.board.h) && copper) {
      d.board.w = copper.board.w;
      d.board.h = copper.board.h;
    }
  }
  function setEdge(n: DevNode, q: Pose) {
    if (EDGE_OF_TURN[n.kind]) n.edge = EDGE_OF_TURN[n.kind][q.rot] as DevNode['edge'];
    else if (n.kind === 'header' || n.kind === 'jst') {
      const gaps: [string, number][] = [['-x', W / 2 + q.x], ['+x', W / 2 - q.x], ['-y', H / 2 + q.y], ['+y', H / 2 - q.y]];
      const [edge, gap] = gaps.sort((a, b) => a[1] - b[1])[0];
      if (gap < 6) n.edge = edge as DevNode['edge'];
      else delete n.edge;
    }
  }
  /** The part and the capacitors placed with it: they move and turn as one. */
  const withCaps = (id: string) => [id, ...Object.entries(groupOf).filter(([, chip]) => chip === id).map(([cap]) => cap)];
  function place(next: Map<string, Pose>, main: string, summary: string) {
    dev.edit((d) => {
      for (const [id, q] of next) {
        const n = d.nodes.find((x) => x.id === id);
        if (!n) continue;
        n.pcb = { x: Math.round(q.x * 100) / 100, y: Math.round(q.y * 100) / 100, rot: ((Math.round(q.rot / 90) * 90) % 360 + 360) % 360 };
        if (id === main) setEdge(n, n.pcb);
      }
      holdBoard(d);
    }, summary);
  }
  function rotate(id: string, by: number) {
    const c = poses.get(id);
    if (!c) return;
    const next = new Map<string, Pose>();
    for (const m of withCaps(id)) {
      const q = poses.get(m)!;
      const [x, y] = carry(c, { ...c, rot: c.rot + by }, q.x, q.y);
      next.set(m, { x, y, rot: (((q.rot + by) % 360) + 360) % 360 });
    }
    place(next, id, `${id} turned on the board`);
  }
  function unpin(id: string) {
    dev.edit((d) => {
      for (const m of withCaps(id)) delete d.nodes.find((x) => x.id === m)?.pcb;
    }, `${id} placed automatically again`);
  }
  // a hand trace holds only where its parts stand: the first one pins every part
  function pinAll(d: DeviceDoc) {
    for (const p of copper?.parts ?? []) {
      const n = d.nodes.find((x) => x.id === p.id), q = poses.get(p.id);
      if (n && q && !n.pcb) n.pcb = { x: q.x, y: q.y, rot: q.rot };
    }
    holdBoard(d);
  }
  const pair = (a: string, b: string) => [a, b].sort().join('|');
  function addRoutes(rs: Route[], summary: string) {
    if (!rs.length) return;
    dev.edit((d) => {
      d.routes = [...(d.routes ?? []), ...rs];
      pinAll(d);
    }, summary);
    const joined = new Set(rs.map((r) => pair(r.from, r.to)));
    hidden = new Set([...hidden, ...(copper?.traces ?? []).filter((t) => t.from && t.to && joined.has(pair(t.from, t.to))).map((t) => t.id)]);
  }
  function addZone(z: Zone) {
    dev.edit((d) => {
      d.zones = [...(d.zones ?? []), z];
      holdBoard(d);
    }, z.kind === 'pour' ? `${z.net} pour drawn` : 'keepout drawn');
  }
  function removeZone(i: number) {
    dev.edit((d) => {
      d.zones = (d.zones ?? []).filter((_, j) => j !== i);
      if (!d.zones.length) delete d.zones;
    }, 'zone removed');
    sel = null;
  }
  function zoneLayer(i: number) {
    dev.edit((d) => {
      const z = d.zones?.[i];
      if (!z) return;
      if (z.kind === 'pour') z.layer = flip(z.layer);
      else z.layers = z.layers.length === 2 ? ['top'] : z.layers[0] === 'top' ? ['bottom'] : ['top', 'bottom'];
    }, 'zone layer changed');
  }
  function removeSel() {
    if (!sel) return;
    if (sel.kind === 'hand') {
      const i = sel.i, r = routes[i];
      dev.edit((d) => {
        d.routes = (d.routes ?? []).filter((_, j) => j !== i);
        if (!d.routes.length) delete d.routes;
      }, r ? `hand trace ${r.from}-${r.to} removed` : 'hand trace removed');
    } else if (sel.kind === 'auto') hidden = new Set([...hidden, sel.id]);
    else if (sel.kind === 'zone') return removeZone(sel.i);
    else return;
    sel = null;
  }
  function lockOne(id: string) {
    const t = copper?.traces.find((x) => x.id === id);
    const r = t ? lockTrace(t) : null;
    if (!r) return say(dt('route_cannot_lock'));
    addRoutes([r], `trace ${r.from}-${r.to} kept as routed`);
    sel = null;
  }
  export function lockAll() {
    if (!copper) return;
    const rs = copper.traces.filter((t) => !t.hand && !gone.has(t.id)).map(lockTrace).filter((r): r is Route => !!r);
    addRoutes(rs, `all ${rs.length} autorouted traces kept as routed`);
    sel = null;
  }
  export function pourBoard(net = pourNet, on: Layer = layer) {
    if (zones.some((z) => z.kind === 'pour' && !z.rect && z.net === net && z.layer === on)) return;
    addZone({ kind: 'pour', net, layer: on });
  }

  // ---- routing
  function start(p: Pad) {
    if (readonly) return;
    const l: Layer = p.tht ? layer : 'top';
    layer = l;
    const [x, y] = portAt(p.key) ?? padAt(p);
    draft = { from: p.key, net: p.net, start: [x, y], layer0: l, layer: l, points: [] };
    sel = null;
    cursor = [x, y];
  }
  function commit(to: [number, number]) {
    if (!draft || !lastAt) return;
    const corner = octi(lastAt, to, diagFirst);
    const pts = [...draft.points];
    if (corner) pts.push({ x: corner[0], y: corner[1] });
    if (Math.hypot(to[0] - lastAt[0], to[1] - lastAt[1]) > 1e-6) pts.push({ x: to[0], y: to[1] });
    draft = { ...draft, points: pts };
  }
  function via() {
    if (!draft) return;
    if (cursor) commit(cursor);
    const pts = [...draft.points];
    const last = pts.at(-1);
    if (!last || last.via) return say(dt('route_via_where'));
    pts[pts.length - 1] = { ...last, via: true };
    draft = { ...draft, points: pts, layer: flip(draft.layer) };
    layer = draft.layer;
  }
  function stepBack() {
    if (!draft) return;
    if (!draft.points.length) return void (draft = null);
    const pts = [...draft.points];
    const g = pts.pop()!;
    draft = { ...draft, points: pts, layer: g.via ? flip(draft.layer) : draft.layer };
    layer = draft.layer;
  }
  function finish(p: Pad) {
    if (!draft || !lastAt) return;
    const end = portAt(p.key) ?? padAt(p);
    const corner = octi(lastAt, end, diagFirst);
    const pts: Pt[] = draft.points.map((q) => ({ ...q }));
    if (corner) pts.push({ x: corner[0], y: corner[1] });
    if (!p.tht && draft.layer === 'bottom') {
      const last = pts.at(-1);
      if (!last || last.via) return say(dt('route_smd_top'));
      last.via = true;
    }
    const r: Route = { from: draft.from, to: p.key, layer: draft.layer0, width, points: pts };
    draft = null;
    addRoutes([r], `trace ${r.from}-${r.to} drawn by hand`);
  }

  // ---- pointer
  type Act =
    | { k: 'pan'; sx: number; sy: number; vb: typeof vb }
    | { k: 'part'; id: string; sx: number; sy: number; bx: number; by: number; live: boolean; from: Map<string, Pose>; cx: number[]; cy: number[]; mine: [number, number][] }
    | { k: 'rect' }
    | { k: 'measure' }
    | { k: 'right'; sx: number; sy: number; vb: typeof vb; panned: boolean };
  let act: Act | null = null;
  function down(e: PointerEvent) {
    menu = null;
    svg?.setPointerCapture?.(e.pointerId);
    const [x, y] = toBoard(e);
    if (e.button === 1) return void (act = { k: 'pan', sx: e.clientX, sy: e.clientY, vb: { ...vb } });
    if (e.button === 2) return void (act = { k: 'right', sx: e.clientX, sy: e.clientY, vb: { ...vb }, panned: false });
    if (draft) {
      const p = padHit(x, y);
      if (p && p.net === draft.net && !(p.key === draft.from && !draft.points.length)) return finish(p);
      if (p && p.net !== draft.net) return say(dt('route_other_net'));
      cursor = snapTo(x, y, e);
      return commit(cursor);
    }
    if (tool === 'route') {
      const p = padHit(x, y);
      if (p) return start(p);
    } else if ((tool === 'pour' || tool === 'keepout') && !readonly) {
      const a = snapEdge(x, y, e);
      rect = { tool, a, b: a };
      return void (act = { k: 'rect' });
    } else if (tool === 'measure') {
      const a = snapPt(x, y, e);
      meas = { a, b: a };
      return void (act = { k: 'measure' });
    } else {
      const p = partHit(x, y) ?? (padHit(x, y) ? partsNow.find((q) => q.id === padHit(x, y)!.comp) ?? null : null);
      if (p) {
        sel = { kind: 'part', id: p.id };
        dev.pickNode(p.id);
        if (!readonly) {
          // what it lines up with: the other parts' centres and pads, and the board's centre lines
          const group = new Set(withCaps(p.id));
          const pose = poses.get(p.id)!;
          const others = [...partsNow.filter((q) => !group.has(q.id)), ...padsNow.filter((q) => !group.has(q.comp))];
          act = {
            k: 'part', id: p.id, sx: e.clientX, sy: e.clientY, bx: x, by: y, live: false,
            from: new Map(withCaps(p.id).map((m) => [m, { ...poses.get(m)! }])),
            cx: [...new Set([0, ...others.map((q) => r2(q.x))])], cy: [...new Set([0, ...others.map((q) => r2(q.y))])],
            mine: [[0, 0], ...padsNow.filter((q) => q.comp === p.id).map((q) => [q.x - pose.x, q.y - pose.y] as [number, number])],
          };
        }
        return;
      }
      const t = traceHit(x, y);
      if (t) return void (sel = t.kind === 'auto' ? { kind: 'auto', id: t.id! } : { kind: 'hand', i: t.i! });
      const z = zoneHit(x, y);
      if (z >= 0) return void (sel = { kind: 'zone', i: z });
      sel = null;
      dev.pickNode(null);
    }
    act = { k: 'pan', sx: e.clientX, sy: e.clientY, vb: { ...vb } };
  }
  function panBy(a: { sx: number; sy: number; vb: typeof vb }, e: PointerEvent) {
    const r = svg!.getBoundingClientRect();
    const k = Math.max(a.vb.w / r.width, a.vb.h / r.height);
    vb = { ...a.vb, x: a.vb.x - (e.clientX - a.sx) * k, y: a.vb.y - (e.clientY - a.sy) * k };
  }
  function move(e: PointerEvent) {
    const [x, y] = toBoard(e);
    pointer = free(e) ? [r2(x), r2(y)] : [grid(x, gridMm), grid(y, gridMm)];
    if (act?.k === 'pan') return panBy(act, e);
    if (act?.k === 'right') {
      if (act.panned || Math.hypot(e.clientX - act.sx, e.clientY - act.sy) > 4) {
        act.panned = true;
        panBy(act, e);
      }
      return;
    }
    if (act?.k === 'part') {
      if (!act.live && Math.hypot(e.clientX - act.sx, e.clientY - act.sy) < 3) return;
      act.live = true;
      const main = act.from.get(act.id)!;
      const rx = main.x + x - act.bx, ry = main.y + y - act.by;
      let nx = r2(rx), ny = r2(ry);
      let gx: number | undefined, gy: number | undefined;
      if (!free(e)) {
        nx = grid(rx, gridMm);
        ny = grid(ry, gridMm);
        let bx = reach(), by = reach();
        for (const [ox, oy] of act.mine) {
          for (const c of act.cx) {
            const d = Math.abs(c - (rx + ox));
            if (d < bx) [bx, nx, gx] = [d, r2(c - ox), c];
          }
          for (const c of act.cy) {
            const d = Math.abs(c - (ry + oy));
            if (d < by) [by, ny, gy] = [d, r2(c - oy), c];
          }
        }
      }
      guides = { x: gx, y: gy };
      const m = new Map<string, Pose>();
      for (const [id, q] of act.from) m.set(id, { x: q.x + nx - main.x, y: q.y + ny - main.y, rot: q.rot });
      moving = m;
      return;
    }
    if (act?.k === 'rect' && rect) return void (rect = { ...rect, b: snapEdge(x, y, e) });
    if (act?.k === 'measure' && meas) return void (meas = { ...meas, b: snapPt(x, y, e) });
    hoverPad = padHit(x, y);
    if (draft) cursor = hoverPad && hoverPad.net === draft.net ? (portAt(hoverPad.key) ?? [hoverPad.x, hoverPad.y]) : snapTo(x, y, e);
  }
  function up(e: PointerEvent) {
    const a = act;
    act = null;
    if (a?.k === 'part') {
      if (a.live && moving) place(new Map(moving), a.id, `${a.id} moved on the board`);
      moving = null;
      guides = {};
    } else if (a?.k === 'rect' && rect) {
      const [x0, y0] = rect.a, [x1, y1] = rect.b;
      const r: [number, number, number, number] = [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
      if (r[2] - r[0] >= 0.5 && r[3] - r[1] >= 0.5) {
        if (rect.tool === 'pour') addZone({ kind: 'pour', net: pourNet, layer, rect: r });
        else addZone({ kind: 'keepout', layers: keepBoth ? ['top', 'bottom'] : [layer], rect: r });
      }
      rect = null;
    } else if (a?.k === 'right' && !a.panned) rightClick(e);
  }
  function rightClick(e: PointerEvent) {
    // as in EasyEDA: the right button cancels what is being drawn; otherwise it opens the menu of what is under it
    if (draft) return void (draft = null);
    if (rect) return void (rect = null);
    if (meas) meas = null;
    const [x, y] = toBoard(e);
    const box = svg!.parentElement!.getBoundingClientRect();
    const at = { x: e.clientX - box.left, y: e.clientY - box.top };
    const items: NonNullable<typeof menu>['items'] = [];
    const pad = padHit(x, y), part = partHit(x, y), t = traceHit(x, y), z = zoneHit(x, y);
    if (!readonly && pad) items.push({ label: dt('ed_route_from', { pad: pad.key }), key: 'X', run: () => start(pad) });
    if (part) {
      sel = { kind: 'part', id: part.id };
      if (!readonly) {
        items.push({ label: dt('ed_rotate'), key: 'R', run: () => rotate(part.id, 90) });
        if (part.pinned) items.push({ label: nodeOf.get(part.id)?.place || layoutOf(doc, part.id) ? dt('unpin_designer') : dt('unpin'), run: () => unpin(part.id) });
      }
    } else if (t) {
      sel = t.kind === 'auto' ? { kind: 'auto', id: t.id! } : { kind: 'hand', i: t.i! };
      if (!readonly) {
        if (t.kind === 'auto') items.push({ label: dt('route_lock'), key: 'L', run: () => lockOne(t.id!) });
        items.push({ label: dt('route_delete'), key: 'Del', run: removeSel, danger: true });
      }
    } else if (z >= 0) {
      sel = { kind: 'zone', i: z };
      if (!readonly) {
        items.push({ label: dt('ed_zone_layer'), run: () => zoneLayer(z) });
        items.push({ label: dt('route_delete'), key: 'Del', run: () => removeZone(z), danger: true });
      }
    } else {
      sel = null;
      if (!readonly && dev.stale) items.push({ label: dt('route_rest'), run: () => dev.startBuild() });
      if (!readonly && pourNets.includes('GND')) items.push({ label: dt('ed_pour_gnd', { layer: layer === 'top' ? dt('layer_top') : dt('layer_bottom') }), run: () => pourBoard('GND', layer) });
      items.push({ label: dt('ed_fit'), key: 'F', run: fit });
    }
    if (items.length) menu = { x: at.x, y: at.y, items };
  }

  // ---- keys
  function key(e: KeyboardEvent) {
    const el = e.target as HTMLElement | null;
    if (el && /INPUT|TEXTAREA|SELECT/.test(el.tagName)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'escape') {
      if (menu) menu = null;
      else if (draft) draft = null;
      else if (rect) rect = null;
      else if (meas) meas = null;
      else if (tool !== 'select') tool = 'select';
      else sel = null;
    } else if (draft && k === 'backspace') {
      e.preventDefault();
      stepBack();
    } else if (draft && k === 'v') via();
    else if (draft && k === '/') diagFirst = !diagFirst;
    else if (k === '1' || k === '2' || k === 'pageup' || k === 'pagedown') {
      e.preventDefault();
      const want: Layer = k === '1' || k === 'pageup' ? 'top' : 'bottom';
      if (draft && draft.layer !== want) via();
      else if (!draft) layer = want;
    } else if (k === 'x' && !readonly) {
      if (hoverPad && !draft) start(hoverPad);
      tool = 'route';
    } else if (k === 'z' && !readonly) tool = 'pour';
    else if (k === 'k' && !readonly) tool = 'keepout';
    else if (k === 'm') tool = 'measure';
    else if (k === 'g') showGrid = !showGrid;
    else if (k === 'n') gridMm = GRIDS[(GRIDS.indexOf(gridMm) + (e.shiftKey ? GRIDS.length - 1 : 1)) % GRIDS.length];
    else if (k === 'f' || k === 'home') fit();
    else if (!draft && sel?.kind === 'part' && k === 'r' && !readonly) rotate(sel.id, e.shiftKey ? -90 : 90);
    else if (!draft && sel && !readonly && (k === 'delete' || k === 'backspace')) {
      e.preventDefault();
      removeSel();
    } else if (!draft && sel?.kind === 'auto' && k === 'l' && !readonly) lockOne(sel.id);
    else return;
    e.stopPropagation();
  }
  function pickLayer(l: Layer) {
    if (draft && draft.layer !== l) via();
    else if (!draft) layer = l;
  }

  // ---- the selection's card
  const info = $derived.by(() => {
    if (!sel || !copper) return null;
    if (sel.kind === 'part') {
      const p = partsNow.find((q) => q.id === (sel as { id: string }).id), q = poses.get((sel as { id: string }).id);
      const n = nodeOf.get((sel as { id: string }).id);
      if (!p || !q) return null;
      // who put it there: the person (pcb), the designer (place, or a layout such as the dice pips), else the build
      const lay = layoutOf(doc, p.id);
      const tag = p.pinned ? dt('place_pinned') : p.designer ? (lay ? dt('placed_layout', { p: patternName(lay.layout.pattern) }) : dt('placed_designer')) : dt('ed_auto_placed');
      return { kind: 'part' as const, id: p.id, label: n?.label ?? '', x: q.x, y: q.y, rot: q.rot, pinned: p.pinned, designer: p.designer, tag, back: !!(n?.place || lay) };
    }
    if (sel.kind === 'zone') {
      const z = zones[sel.i];
      if (!z) return null;
      const size = z.rect ? `${(z.rect[2] - z.rect[0]).toFixed(1)} × ${(z.rect[3] - z.rect[1]).toFixed(1)} ${dt('mm')}` : dt('ed_whole_board');
      const lay = z.kind === 'pour' ? (z.layer === 'top' ? dt('layer_top') : dt('layer_bottom')) : z.layers.map((l) => (l === 'top' ? dt('layer_top') : dt('layer_bottom'))).join(' + ');
      return { kind: 'zone' as const, i: sel.i, title: z.kind === 'pour' ? `${dt('ed_pour')} ${z.net}` : dt('ed_keepout'), detail: `${lay} · ${size}` };
    }
    const it = items.find((x) => isSel(x));
    if (!it) return null;
    const r = sel.kind === 'hand' ? routes[sel.i] : null;
    const t = sel.kind === 'auto' ? copper.traces.find((x) => x.id === (sel as { id: string }).id) : null;
    return {
      kind: 'trace' as const,
      net: copper.netName[it.net] ?? '',
      ends: r ? `${r.from} → ${r.to}` : t?.from && t?.to ? `${t.from} → ${t.to}` : '',
      layers: [...new Set(it.segs.map((s) => s.layer))].map((l) => (l === 'top' ? dt('layer_top') : dt('layer_bottom'))).join(' + '),
      width: it.segs[0]?.w ?? 0,
      length: segLength(it.segs),
      vias: it.vias.length,
      hand: it.kind === 'hand',
      id: t?.id,
    };
  });
  const COLOR: Record<Layer, string> = { top: 'var(--cu-top)', bottom: 'var(--cu-bottom)' };
  const LIGHT: Record<Layer, string> = { top: 'var(--cu-top-sel)', bottom: 'var(--cu-bottom-sel)' };
  const TOOLS: { id: Tool; icon: string; key: string; edit: boolean }[] = [
    { id: 'select', icon: 'ti-pointer', key: 'Esc', edit: false },
    { id: 'route', icon: 'ti-route', key: 'X', edit: true },
    { id: 'pour', icon: 'ti-texture', key: 'Z', edit: true },
    { id: 'keepout', icon: 'ti-square-off', key: 'K', edit: true },
    { id: 'measure', icon: 'ti-ruler-measure', key: 'M', edit: false },
  ];
  const ringPath = (rings: [number, number][][]) => rings.map((r) => 'M' + r.map((p) => p.join(' ')).join('L') + 'Z').join('');
  const measLen = $derived(meas ? Math.hypot(meas.b[0] - meas.a[0], meas.b[1] - meas.a[1]) : 0);
</script>

<svelte:window onkeydown={key} />

<div class="ed" class:crosshair={!!draft || tool !== 'select'} bind:clientWidth={boxW} bind:clientHeight={boxH}>
  {#if err && !copper}
    <p class="msg" role="alert">{err} <button class="btn small" onclick={() => ((err = null), attempt++)}>{t('retry')}</button></p>
  {:else if !copper}
    <p class="msg"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></p>
  {:else}
    <svg bind:this={svg} viewBox="{vb.x} {vb.y} {vb.w} {vb.h}" preserveAspectRatio="xMidYMid meet" onwheel={wheel}
      onpointerdown={down} onpointermove={move} onpointerup={up} oncontextmenu={(e) => e.preventDefault()}
      ondblclick={(e) => { if (tool === 'select' && !draft) { const [x, y] = toBoard(e); const p = padHit(x, y); if (p) start(p); } }}
      role="application" aria-label={dt('ed_title')}>
      <defs>
        <pattern id="grid-minor" width={gridView.step} height={gridView.step} x={-gridView.step / 2} y={-gridView.step / 2} patternUnits="userSpaceOnUse">
          <circle cx={gridView.step / 2} cy={gridView.step / 2} r={gridView.r} fill="rgba(255, 255, 255, 0.22)" />
        </pattern>
        <pattern id="grid-major" width={gridView.major} height={gridView.major} x={-gridView.major / 2} y={-gridView.major / 2} patternUnits="userSpaceOnUse">
          <circle cx={gridView.major / 2} cy={gridView.major / 2} r={gridView.r * 1.5} fill="rgba(255, 255, 255, 0.38)" />
        </pattern>
        <pattern id="ko-hatch" width="0.8" height="0.8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="0.8" stroke="#e5484d" stroke-width="0.14" />
        </pattern>
      </defs>
      <g transform="scale(1,-1)">
        <rect class="board" x={-W / 2} y={-H / 2} width={W} height={H} rx={cornerR} />
        {#if showGrid}
          <rect x={vb.x} y={-(vb.y + vb.h)} width={vb.w} height={vb.h} fill="url(#grid-minor)" pointer-events="none" />
          <rect x={vb.x} y={-(vb.y + vb.h)} width={vb.w} height={vb.h} fill="url(#grid-major)" pointer-events="none" />
        {/if}
        {#each copper.holes as h, i (i)}<circle class="hole" cx={h.x} cy={h.y} r={h.d / 2} />{/each}
        {#each [back, front] as l (l)}
          <g class:inactive={l !== front}>
            {#each pours.filter((p) => p.layer === l) as p, i (i)}<path class="pour" d={ringPath(p.rings)} style="fill: {COLOR[l]}" />{/each}
            {#each items as it (it.key)}
              {#each it.segs.filter((s) => s.layer === l) as s, j (j)}
                <line class="cu" x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} style="stroke: {isSel(it) ? LIGHT[l] : COLOR[l]}; stroke-width: {s.w}" />
              {/each}
            {/each}
          </g>
          {#if l === back}
            {#each padsNow as p, i (i)}
              {#if p.round}<circle class="pad" class:tht={p.tht} class:dim={!p.tht && front === 'bottom'} cx={p.x} cy={p.y} r={Math.min(p.w, p.h) / 2} />
              {:else}<rect class="pad" class:tht={p.tht} class:dim={!p.tht && front === 'bottom'} x={p.x - p.w / 2} y={p.y - p.h / 2} width={p.w} height={p.h} />{/if}
            {/each}
          {/if}
        {/each}
        {#each items as it (it.key)}
          {#each it.vias as v, j (j)}<circle class="via" class:sel={isSel(it)} cx={v[0]} cy={v[1]} r="0.3" />{/each}
        {/each}
        <!-- zones: a keepout hatched red, a pour still to fill as its outline -->
        {#each zones as z, i (i)}
          {@const r = z.rect ?? [-W / 2 + 0.3, -H / 2 + 0.3, W / 2 - 0.3, H / 2 - 0.3]}
          {#if z.kind === 'keepout'}
            <rect class="ko" class:sel={sel?.kind === 'zone' && sel.i === i} x={r[0]} y={r[1]} width={r[2] - r[0]} height={r[3] - r[1]} />
          {:else}
            <rect class="zone" class:sel={sel?.kind === 'zone' && sel.i === i} x={r[0]} y={r[1]} width={r[2] - r[0]} height={r[3] - r[1]} style="stroke: {COLOR[z.layer]}" />
          {/if}
        {/each}
        {#each partsNow as p (p.id)}
          <g class="silk" transform="translate({p.x} {p.y}) rotate({p.rot})">
            {#each p.silk ?? [] as line, i (i)}<polyline points={line.map((q) => q.join(',')).join(' ')} />{/each}
          </g>
          <rect class="court" class:sel={sel?.kind === 'part' && sel.id === p.id} class:moved={p.moved} class:pinned={p.pinned && !p.moved} class:designer={p.designer && !p.moved}
            x={p.x - p.w / 2 - 0.25} y={p.y - p.h / 2 - 0.25} width={p.w + 0.5} height={p.h + 0.5} rx="0.3" />
        {/each}
        {#each ratsnest as l, i (i)}<line class="rat" x1={l[0]} y1={l[1]} x2={l[2]} y2={l[3]} />{/each}
        {#if draft}
          {#each targets as p, i (i)}<circle class="target" cx={p.x} cy={p.y} r={Math.max(p.w, p.h) / 2 + 0.25} />{/each}
          {#each draftSegs as s, i (i)}<line class="cu draft" x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} style="stroke: {COLOR[s.layer]}; stroke-width: {s.w}" />{/each}
          {#each draft.points.filter((q) => q.via) as q, i (i)}<circle class="via" cx={q.x} cy={q.y} r="0.3" />{/each}
          {#if preview.length > 1}
            <polyline class="cu draft live" points={preview.map((q) => q.join(',')).join(' ')} style="stroke: {COLOR[draft.layer]}; stroke-width: {width}" />
          {/if}
        {/if}
        {#if rect}
          {@const [x0, y0] = rect.a}
          {@const [x1, y1] = rect.b}
          <rect class={rect.tool === 'keepout' ? 'ko' : 'zone'} x={Math.min(x0, x1)} y={Math.min(y0, y1)} width={Math.abs(x1 - x0)} height={Math.abs(y1 - y0)}
            style={rect.tool === 'pour' ? `stroke: ${COLOR[layer]}` : ''} />
        {/if}
        {#if meas}<line class="meas" x1={meas.a[0]} y1={meas.a[1]} x2={meas.b[0]} y2={meas.b[1]} />{/if}
        {#if guides.x !== undefined}<line class="guide" x1={guides.x} y1={-(vb.y + vb.h)} x2={guides.x} y2={-vb.y} style="stroke-width: {mmPerPx}; stroke-dasharray: {4 * mmPerPx} {3 * mmPerPx}" />{/if}
        {#if guides.y !== undefined}<line class="guide" x1={vb.x} y1={guides.y} x2={vb.x + vb.w} y2={guides.y} style="stroke-width: {mmPerPx}; stroke-dasharray: {4 * mmPerPx} {3 * mmPerPx}" />{/if}
      </g>
      {#each partsNow as p (p.id)}
        <text class="lbl" x={p.x} y={-p.y} font-size={Math.max(0.8, Math.min(1.6, Math.min(p.w, p.h) * 0.4))}>{p.id}</text>
      {/each}
      {#if meas && measLen > 0.05}
        <text class="mlbl" x={(meas.a[0] + meas.b[0]) / 2} y={-(meas.a[1] + meas.b[1]) / 2 - 0.6}>{measLen.toFixed(2)} {dt('mm')} · Δx {Math.abs(meas.b[0] - meas.a[0]).toFixed(2)} · Δy {Math.abs(meas.b[1] - meas.a[1]).toFixed(2)}</text>
      {/if}
    </svg>

    <div class="tools" role="toolbar" aria-orientation="vertical" aria-label={dt('ed_title')}>
      {#each TOOLS as t (t.id)}
        <button class:on={tool === t.id} disabled={t.edit && readonly} onclick={() => ((tool = t.id), (draft = null))} title="{dt(`ed_tool_${t.id}`)} ({t.key})" aria-label={dt(`ed_tool_${t.id}`)}>
          <i class="ti {t.icon}" aria-hidden="true"></i>
        </button>
      {/each}
    </div>

    <div class="opts">
      <div class="seg" role="radiogroup" aria-label={dt('route_layer')}>
        <button role="radio" aria-checked={front === 'top'} onclick={() => pickLayer('top')} title="1 / PgUp"><i class="sw top"></i>{dt('layer_top')}</button>
        <button role="radio" aria-checked={front === 'bottom'} onclick={() => pickLayer('bottom')} title="2 / PgDn"><i class="sw bottom"></i>{dt('layer_bottom')}</button>
      </div>
      {#if tool === 'route'}
        <label class="fld">{dt('route_width')}
          <select bind:value={width}>{#each WIDTHS as w (w)}<option value={w}>{w} {dt('mm')}</option>{/each}</select>
        </label>
      {:else if tool === 'pour'}
        <label class="fld">{dt('ed_net')}
          <select bind:value={pourNet}>{#each pourNets as n (n)}<option value={n}>{n}</option>{/each}</select>
        </label>
        <button class="tb" onclick={() => pourBoard()} disabled={readonly}>{dt('ed_whole_board')}</button>
      {:else if tool === 'keepout'}
        <label class="chk"><input type="checkbox" bind:checked={keepBoth} /> {dt('ed_both_layers')}</label>
      {:else if tool === 'select' && !readonly}
        <button class="tb" onclick={lockAll} title={dt('route_lock_all_d')}><i class="ti ti-lock" aria-hidden="true"></i> {dt('route_lock_all')}</button>
      {/if}
      <span class="vsep"></span>
      <button class="tb ic" class:on={showGrid} onclick={() => (showGrid = !showGrid)} title="{dt('ed_grid')} (G)" aria-label={dt('ed_grid')} aria-pressed={showGrid}><i class="ti ti-grid-dots" aria-hidden="true"></i></button>
      <select class="gsel" bind:value={gridMm} title="{dt('ed_grid_step')} (N)" aria-label={dt('ed_grid_step')}>
        {#each GRIDS as g (g)}<option value={g}>{g} {dt('mm')}</option>{/each}
      </select>
      <button class="tb" class:on={magnet} onclick={() => (magnet = !magnet)} title={dt('ed_magnet_d')} aria-pressed={magnet}><i class="ti ti-magnet" aria-hidden="true"></i> {dt('ed_magnet')}</button>
    </div>

    {#if info}
      <div class="card">
        {#if info.kind === 'part'}
          <div class="ct"><b>{info.id}</b><span class="tag" class:dsg={info.designer}>{info.tag}</span></div>
          {#if info.label}<div class="cd">{info.label}</div>{/if}
          <div class="cd mono">X {info.x.toFixed(2)} · Y {info.y.toFixed(2)} · {info.rot}°</div>
          {#if info.designer && !readonly}<div class="cd muted">{dt('placed_designer_move')}</div>{/if}
          {#if !readonly}
            <div class="cb">
              <button class="tb" onclick={() => rotate(info.id, 90)} title="R"><i class="ti ti-rotate-clockwise-2" aria-hidden="true"></i> {dt('ed_rotate')}</button>
              {#if info.pinned}<button class="tb" onclick={() => unpin(info.id)}>{info.back ? dt('unpin_designer') : dt('unpin')}</button>{/if}
            </div>
          {/if}
        {:else if info.kind === 'zone'}
          <div class="ct"><b>{info.title}</b></div>
          <div class="cd">{info.detail}</div>
          {#if !readonly}
            <div class="cb">
              <button class="tb" onclick={() => zoneLayer(info.i)}>{dt('ed_zone_layer')}</button>
              <button class="tb" onclick={() => removeZone(info.i)}><i class="ti ti-trash" aria-hidden="true"></i> {dt('route_delete')}</button>
            </div>
          {/if}
        {:else}
          <div class="ct"><b>{info.net || dt('route_trace')}</b><span class="tag" class:hand={info.hand}>{info.hand ? dt('route_hand') : dt('route_auto')}</span></div>
          <div class="cd mono">{info.ends}</div>
          <div class="cd">{info.layers} · {info.width} {dt('mm')} · {info.length.toFixed(1)} {dt('mm')}{info.vias ? ` · ${dt('route_vias')} ${info.vias}` : ''}</div>
          {#if !readonly}
            <div class="cb">
              {#if !info.hand && info.id}<button class="tb" onclick={() => lockOne(info.id!)} title="L"><i class="ti ti-lock" aria-hidden="true"></i> {dt('route_lock')}</button>{/if}
              <button class="tb" onclick={removeSel} title="Delete"><i class="ti ti-trash" aria-hidden="true"></i> {dt('route_delete')}</button>
            </div>
          {/if}
        {/if}
      </div>
    {/if}

    {#if menu}
      <div class="menu" style="left: {menu.x}px; top: {menu.y}px" role="menu">
        {#each menu.items as m, i (i)}
          <button role="menuitem" class:danger={m.danger} onclick={() => ((menu = null), m.run())}><span>{m.label}</span>{#if m.key}<kbd>{m.key}</kbd>{/if}</button>
        {/each}
      </div>
    {/if}

    {#if flash}<div class="flash" role="status">{flash}</div>{/if}

    <div class="legend">
      {#if ratsnest.length}<span><i class="sw rat"></i>{dt('route_left')}: {ratsnest.length}</span>{/if}
      <!-- the keys on demand, except while drawing a trace, when they are what the person needs next -->
      <button class="keys" onclick={() => (keysOpen = !keysOpen)} aria-expanded={keysOpen}>{dt('ed_keys')}</button>
      {#if keysOpen || draft}<span class="muted">{draft ? dt('route_hint_draw') : dt(`ed_hint_${tool}`)}</span>{/if}
      {#if pointer}<span class="xy">X {pointer[0].toFixed(2)} · Y {pointer[1].toFixed(2)}</span>{/if}
    </div>
  {/if}
</div>

<style>
  .keys {
    padding: 0;
    border: none;
    background: none;
    color: inherit;
    font: inherit;
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
  }
  .ed {
    position: absolute;
    inset: 0;
    background: #101010;
    --cu-top: rgb(200, 52, 52);
    --cu-bottom: rgb(77, 127, 196);
    --cu-top-sel: rgb(255, 150, 140);
    --cu-bottom-sel: rgb(160, 200, 255);
  }
  svg {
    width: 100%;
    height: 100%;
    display: block;
    touch-action: none;
    user-select: none;
  }
  .crosshair svg {
    cursor: crosshair;
  }
  .board {
    fill: #0b0d0b;
    stroke: rgba(255, 255, 255, 0.45);
    stroke-width: 0.15;
  }
  .hole {
    fill: #101010;
    stroke: rgba(255, 255, 255, 0.55);
    stroke-width: 0.12;
  }
  .inactive {
    opacity: 0.32;
  }
  .pour {
    fill-rule: evenodd;
    opacity: 0.38;
  }
  .cu {
    fill: none;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .cu.draft {
    opacity: 0.85;
  }
  .cu.live {
    opacity: 0.6;
  }
  .pad {
    fill: rgb(200, 52, 52);
  }
  .pad.tht {
    fill: #c99a3a;
  }
  .pad.dim {
    opacity: 0.35;
  }
  .via {
    fill: #d8d8d8;
    stroke: #0b0d0b;
    stroke-width: 0.12;
  }
  .via.sel {
    fill: #fff;
  }
  .court {
    fill: none;
    stroke: rgba(242, 237, 161, 0.4);
    stroke-width: 0.08;
  }
  .court.pinned {
    stroke-dasharray: 0.5 0.3;
  }
  .silk polyline {
    fill: none;
    stroke: color-mix(in srgb, var(--on-surface) 62%, transparent);
    stroke-width: 0.14;
    pointer-events: none;
  }
  /* placed by the designer (place, a layout): a dotted outline in the accent of the designer's own marks */
  .court.designer {
    stroke: rgba(120, 200, 255, 0.7);
    stroke-dasharray: 0.15 0.25;
    stroke-width: 0.12;
  }
  .court.moved {
    stroke: #e6b045;
  }
  .court.sel {
    stroke: var(--primary);
    stroke-width: 0.18;
    fill: color-mix(in srgb, var(--primary) 10%, transparent);
  }
  .ko {
    fill: url(#ko-hatch);
    stroke: #e5484d;
    stroke-width: 0.14;
    stroke-dasharray: 0.5 0.3;
  }
  .zone {
    fill: none;
    stroke-width: 0.16;
    stroke-dasharray: 0.8 0.4;
  }
  .ko.sel,
  .zone.sel {
    stroke-width: 0.3;
    stroke-dasharray: none;
  }
  .target {
    fill: none;
    stroke: #f2eda1;
    stroke-width: 0.12;
    stroke-dasharray: 0.3 0.2;
  }
  .rat {
    stroke: #f2eda1;
    stroke-width: 0.12;
    stroke-dasharray: 0.4 0.25;
  }
  .guide {
    stroke: #3fd0ff;
    pointer-events: none;
  }
  .meas {
    stroke: #f2eda1;
    stroke-width: 0.1;
  }
  .lbl,
  .mlbl {
    fill: rgba(242, 237, 161, 0.75);
    text-anchor: middle;
    dominant-baseline: middle;
    font-family: var(--font-mono);
    pointer-events: none;
    paint-order: stroke;
    stroke: #0b0d0b;
    stroke-width: 0.25;
  }
  .mlbl {
    font-size: 1px;
    fill: #f2eda1;
  }
  .tools {
    position: absolute;
    left: 8px;
    top: 8px;
    display: grid;
    gap: 2px;
    padding: 3px;
    border-radius: var(--radius-sm);
    background: rgba(20, 20, 20, 0.9);
  }
  .tools button {
    width: 30px;
    height: 30px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: var(--radius-xs);
    background: transparent;
    color: #bbb;
    font-size: var(--text-xl);
    cursor: pointer;
  }
  .tools button:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.1);
  }
  .tools button.on {
    background: color-mix(in srgb, var(--primary) 30%, transparent);
    color: #fff;
  }
  .tools button:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .opts {
    position: absolute;
    left: 50px;
    top: 8px;
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 4px;
    border-radius: var(--radius-sm);
    background: rgba(20, 20, 20, 0.9);
    color: #ddd;
    font-size: var(--text-md);
  }
  .seg {
    display: inline-flex;
    gap: 2px;
    padding: 2px;
    border-radius: var(--radius-xs);
    background: rgba(255, 255, 255, 0.06);
  }
  .seg button,
  .tb {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 24px;
    padding: 0 9px;
    border: none;
    border-radius: var(--radius-xs);
    background: transparent;
    color: #ccc;
    font: inherit;
    white-space: nowrap;
    cursor: pointer;
  }
  .seg button[aria-checked='true'] {
    background: rgba(255, 255, 255, 0.14);
    color: #fff;
  }
  .tb {
    background: rgba(255, 255, 255, 0.07);
  }
  .tb:hover,
  .seg button:hover {
    background: rgba(255, 255, 255, 0.16);
  }
  .tb.on {
    background: color-mix(in srgb, var(--primary) 30%, transparent);
    color: #fff;
  }
  .tb.ic {
    width: 26px;
    padding: 0;
    justify-content: center;
    font-size: var(--text-lg);
  }
  .vsep {
    width: 1px;
    height: 18px;
    background: rgba(255, 255, 255, 0.12);
  }
  .gsel {
    height: 24px;
    padding: 0 24px 0 7px;
    background-position: right 6px center;
    border-radius: var(--radius-xs);
    border: 1px solid rgba(255, 255, 255, 0.12);
    background-color: #1b1b1b;
    color: #eee;
    font: inherit;
    font-size: var(--text-sm);
  }
  .xy {
    font-family: var(--font-mono);
    color: #bbb;
    font-variant-numeric: tabular-nums;
  }
  .tb:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .fld {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    color: #aaa;
  }
  .fld select {
    height: 24px;
    padding: 0 26px 0 8px;
    background-position: right 6px center;
    border-radius: var(--radius-xs);
    border: 1px solid rgba(255, 255, 255, 0.12);
    background-color: #1b1b1b;
    color: #eee;
    font: inherit;
  }
  .chk {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    color: #ccc;
    padding: 0 6px;
  }
  .card {
    position: absolute;
    right: 8px;
    top: 8px;
    display: grid;
    gap: 4px;
    min-width: 220px;
    padding: 9px 11px;
    border-radius: var(--radius-sm);
    background: rgba(20, 20, 20, 0.92);
    color: #ddd;
    font-size: var(--text-md);
  }
  .ct {
    display: flex;
    gap: 8px;
    align-items: center;
    justify-content: space-between;
  }
  .tag {
    font-size: var(--text-xs);
    padding: 1px 6px;
    border-radius: var(--radius-xs);
    background: rgba(255, 255, 255, 0.08);
    color: #aaa;
  }
  .tag.hand {
    background: color-mix(in srgb, var(--primary) 30%, transparent);
    color: #fff;
  }
  .tag.dsg {
    background: rgba(120, 200, 255, 0.18);
    color: rgb(170, 220, 255);
  }
  .cd {
    color: #aaa;
    font-size: var(--text-sm);
  }
  .mono {
    font-family: var(--font-mono);
  }
  .cb {
    display: flex;
    gap: 6px;
    margin-top: 4px;
  }
  .menu {
    position: absolute;
    z-index: 5;
    display: grid;
    min-width: 200px;
    padding: 4px;
    border-radius: var(--radius-sm);
    background: #1c1c1c;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }
  .menu button {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    height: 26px;
    padding: 0 9px;
    border: none;
    border-radius: var(--radius-xs);
    background: transparent;
    color: #ddd;
    font: inherit;
    font-size: var(--text-md);
    text-align: left;
    cursor: pointer;
  }
  .menu button:hover {
    background: color-mix(in srgb, var(--primary) 25%, transparent);
  }
  .menu button.danger {
    color: #ff8a80;
  }
  kbd {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: #888;
  }
  .flash {
    position: absolute;
    left: 50%;
    top: 46px;
    transform: translateX(-50%);
    padding: 6px 12px;
    border-radius: var(--radius-sm);
    background: rgba(230, 176, 69, 0.95);
    color: #1a1a1a;
    font-size: var(--text-md);
  }
  .legend {
    position: absolute;
    left: 8px;
    bottom: 8px;
    display: flex;
    gap: 14px;
    align-items: center;
    padding: 5px 10px;
    border-radius: var(--radius-sm);
    background: rgba(20, 20, 20, 0.85);
    color: #ddd;
    font-size: var(--text-sm);
  }
  .legend span {
    display: inline-flex;
    gap: 6px;
    align-items: center;
  }
  .sw {
    width: 14px;
    height: 3px;
    border-radius: 2px;
    display: inline-block;
  }
  .sw.top {
    background: var(--cu-top);
  }
  .sw.bottom {
    background: var(--cu-bottom);
  }
  .sw.rat {
    background: #f2eda1;
  }
  .muted {
    color: #999;
  }
  .msg {
    position: absolute;
    inset: 0;
    margin: auto;
    height: fit-content;
    text-align: center;
    color: #aaa;
  }
</style>
