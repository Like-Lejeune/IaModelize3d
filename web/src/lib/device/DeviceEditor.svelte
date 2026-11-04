<script lang="ts">
  // The node editor of a device: parts as nodes with their pins, signal nets as wires, supply nets as labels on the pins
  // (wires on demand). Connecting two pins, deleting a wire or a part and dragging parts edit the device graph
  // (DeviceStore saves it); Build compiles the graph into a placed and routed board on the server.
  import { SvelteFlow, Background, ConnectionMode, Panel, type Node, type Edge as FlowEdge } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import Icon from '$lib/components/Icon.svelte';
  import { setContext, untrack } from 'svelte';
  import PartNode, { netColors, useNetColors, type PartData } from './PartNode.svelte';
  import WireEdge from './WireEdge.svelte';
  import { WireBoard } from './wireboard.svelte';
  import FlowBridge from './FlowBridge.svelte';
  import { loadLibrary } from './PartLibrary.svelte';
  import type { Accessory } from './api';
  import { accessoriesOf, faceOf, layoutOf, refNode } from './facets';
  import { FIT, autoLayout, mirrored } from './layout';
  import { POWER_NET, type DeviceStore } from './store.svelte';
  import { dt, patternName } from './i18n';
  import { t } from '$lib/i18n.svelte';

  let {
    device, readonly = false, onOpen, onAddPart, onDescribe, buildBar = true, toolbar = true, powerWires = $bindable(false), busy = false,
    grid = true, gridStep = 20, magnet = true,
  }: {
    device: DeviceStore;
    readonly?: boolean;
    /** The build's status and button over the canvas; a workspace that shows them in its stage bar turns it off. */
    buildBar?: boolean;
    /** The tools over the canvas; a workspace with them in its area header turns it off. */
    toolbar?: boolean;
    /** Supply nets drawn as wires too (otherwise labels on their pins). */
    powerWires?: boolean;
    /** The agent is drawing the device: an empty canvas says so instead of asking for a description. */
    busy?: boolean;
    /** The sheet's grid, shown or not, and its step; the magnet snaps parts to it and to their neighbours. */
    grid?: boolean;
    gridStep?: number;
    magnet?: boolean;
    onOpen?: (what: 'pcb' | '3d') => void;
    onAddPart?: () => void;
    onDescribe?: () => void;
  } = $props();

  const nodeTypes = { part: PartNode };
  const edgeTypes = { wire: WireEdge };
  const wireBoard = new WireBoard();
  setContext('fw.wires', wireBoard);
  // Shift held: this drag goes free of the magnet
  let free = $state(false);
  let nodes = $state.raw<Node<PartData>[]>([]);
  let edges = $state.raw<FlowEdge[]>([]);
  let bridge = $state<{ fit: () => void; fitTo: (ids: string[]) => void; centre: () => [number, number] }>();

  const issuesBy = $derived.by(() => {
    const out: Record<string, number> = {};
    for (const i of [...(device.state?.issues ?? []), ...(device.state?.lint ?? []), ...(device.state?.rules ?? [])]) {
      if (i.severity === 'info') continue;
      const id = refNode(i.ref);
      out[id] = (out[id] ?? 0) + 1;
    }
    return out;
  });
  // the accessories' cards: their names, pins and prices before the server's view of a new node arrives
  let accs = $state<Record<string, Accessory>>({});
  loadLibrary().then((l) => (accs = Object.fromEntries(accessoriesOf(l).map((a) => [a.key, a])))).catch(() => {});

  $effect(() => {
    const s = device.state;
    if (!s) {
      nodes = [];
      edges = [];
      return;
    }
    const views = s.view.nodes;
    const auto = s.doc.nodes.some((n) => !n.ui) ? autoLayout(s.doc, views) : {};
    const sel = device.selected;
    const hl = device.selectedNet;
    const lit = new Set(device.lit?.ids ?? []);
    const colors = netColors(s.doc.nets);
    untrack(() => useNetColors(colors));
    const where = Object.fromEntries(s.doc.nodes.map((n) => [n.id, n.ui ?? auto[n.id] ?? [0, 0]])) as Record<string, [number, number]>;
    const flipped = mirrored(s.doc, views, where, powerWires);
    // never read `nodes` here: the flow writes it back (measured sizes), which would run this again
    const list: Node<PartData>[] = s.doc.nodes
      .filter((n) => n.kind !== 'hole')
      .map((n) => {
        const at = n.ui ?? auto[n.id] ?? [0, 0];
        const acc = n.kind === 'accessory' ? (accs[n.accessory ?? ''] ?? null) : null;
        const lay = layoutOf(s.doc, n.id);
        const placed = n.pcb ? null : lay ? dt('placed_layout', { p: patternName(lay.layout.pattern) }) : n.place ? dt('placed_designer') : null;
        return {
          id: n.id, type: 'part', position: { x: at[0], y: at[1] },
          data: { node: n, view: views[n.id], issues: issuesBy[n.id] ?? 0, power: powerWires, hl, acc, lit: lit.has(n.id), face: faceOf(n, views[n.id]?.part, acc, views[n.id]?.face), placed, flip: flipped.has(n.id) },
          selected: sel === n.id,
        };
      });
    nodes = list;
    const ids = new Set(list.map((n) => n.id));
    const out: FlowEdge[] = [];
    s.doc.nets.forEach((net, i) => {
      const key = net.name ?? `n${i}`;
      const lit = hl === key;
      const power = POWER_NET.test(net.name ?? '');
      if (power && !powerWires && !lit) return;
      const pins = net.pins.filter((p) => ids.has(p.split('.')[0]));
      const color = colors[net.name ?? `n${i}`];
      for (let k = 1; k < pins.length; k++) {
        const [a, ap] = split(pins[0]);
        const [b, bp] = split(pins[k]);
        out.push({
          id: `n${i}:${pins[0]}~${pins[k]}`, type: 'wire', source: a, sourceHandle: ap, target: b, targetHandle: bp,
          style: lit ? `stroke: ${color}; stroke-width: 2.6px;`
            : `stroke: ${color}; stroke-width: ${power ? 1.2 : 1.8}px;${power ? ' stroke-dasharray: 4 3; opacity: 0.6;' : ''}${hl ? ' opacity: 0.35;' : ''}`,
          data: { a: pins[0], b: pins[k], net: key, color, first: k === 1 },
        });
      }
    });
    edges = out;
  });

  function split(pin: string): [string, string] {
    const i = pin.indexOf('.');
    return [pin.slice(0, i), pin.slice(i + 1)];
  }

  function onconnect(c: { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }) {
    if (readonly || !c.sourceHandle || !c.targetHandle) return;
    device.connect(`${c.source}.${c.sourceHandle}`, `${c.target}.${c.targetHandle}`);
  }

  function ondelete({ nodes: gone, edges: cut }: { nodes: Node[]; edges: FlowEdge[] }) {
    if (readonly) return;
    const dropped = new Set(gone.map((n) => n.id));
    if (gone.length) device.removeNodes(gone.map((n) => n.id));
    for (const e of cut) {
      const d = e.data as { a: string; b: string } | undefined;
      if (d && !dropped.has(d.a.split('.')[0]) && !dropped.has(d.b.split('.')[0])) device.cut(d.a, d.b);
    }
  }

  /** A part dropped this close to a neighbour's edge lines up with it. */
  const ALIGN = 8;
  function aligned(n: Node, others: Node[]): [number, number] {
    let { x, y } = n.position;
    const near = (v: number, list: number[]) => list.find((o) => Math.abs(o - v) <= ALIGN) ?? v;
    x = near(x, others.map((o) => o.position.x));
    y = near(y, others.map((o) => o.position.y));
    return [x, y];
  }
  function ondragstop({ nodes: moved, event }: { nodes: Node[]; event: MouseEvent | TouchEvent }) {
    if (readonly || !moved?.length) return;
    const pulled = magnet && !('shiftKey' in event && event.shiftKey) && moved.length === 1;
    const others = pulled ? nodes.filter((n) => n.id !== moved[0].id) : [];
    device.move(Object.fromEntries(moved.map((n) => [n.id, pulled ? aligned(n, others) : ([n.position.x, n.position.y] as [number, number])])));
  }

  export function fit() {
    bridge?.fit();
  }

  export function tidy() {
    const s = device.state;
    if (!s) return;
    device.move(autoLayout(s.doc, s.view.nodes));
    setTimeout(() => bridge?.fit(), 60);
  }

  /** Where a new part goes: the middle of the view, moved down (then right) until it covers no other part. */
  export function centre(): [number, number] | undefined {
    const c = bridge?.centre();
    if (!c) return undefined;
    const boxes = nodes.map((n) => [n.position.x, n.position.y, n.measured?.width ?? 230, n.measured?.height ?? 120]);
    let [x, y] = c;
    for (let i = 0; i < 36; i++) {
      const hit = boxes.find(([bx, by, bw, bh]) => x < bx + bw + 20 && x + 230 > bx - 20 && y < by + bh + 20 && y + 110 > by - 20);
      if (!hit) break;
      y = hit[1] + hit[3] + 30;
      if (i % 6 === 5) [x, y] = [x + 260, c[1]];
    }
    return [x, y];
  }

  // a group lit from a requirement or a layout: the view goes to its parts
  $effect(() => {
    const ids = device.lit?.ids;
    if (ids?.length) setTimeout(() => bridge?.fitTo(ids), 200);
  });

  const b = $derived(device.build);
  const pcb = $derived(device.state?.pcb ?? null);
  const layouts = $derived(device.state?.doc.layouts ?? []);
</script>

<svelte:window onkeydown={(e) => e.key === 'Shift' && (free = true)} onkeyup={(e) => e.key === 'Shift' && (free = false)} onblur={() => (free = false)} />

<div class="device-editor">
  <SvelteFlow
    bind:nodes
    bind:edges
    {nodeTypes}
    {edgeTypes}
    connectionMode={ConnectionMode.Loose}
    connectionRadius={28}
    snapGrid={magnet && !free ? [gridStep, gridStep] : undefined}
    fitView
    fitViewOptions={FIT}
    minZoom={0.15}
    maxZoom={2.5}
    nodesDraggable={!readonly}
    nodesConnectable={!readonly}
    deleteKey={readonly ? null : ['Backspace', 'Delete']}
    {onconnect}
    {ondelete}
    onnodedragstop={ondragstop}
    onnodeclick={({ node }) => device.pickNode(node.id)}
    onedgeclick={({ edge }) => device.pickNet((edge.data as { net?: string } | undefined)?.net ?? null)}
    onselectionchange={({ nodes: picked }) => {
      // the flow selects on pointer down, before any click: follow its selection
      if (picked.length === 1 && device.selected !== picked[0].id) device.pickNode(picked[0].id);
    }}
    onpaneclick={() => (device.pickNode(null), device.pickNet(null))}
    proOptions={{ hideAttribution: true }}
    defaultEdgeOptions={{ type: 'wire' }}
  >
    <FlowBridge arrived={device.arrived} bind:bridge board={wireBoard} />
    {#if grid}<Background gap={gridStep} size={1.2} />{/if}
    {#if toolbar}<Panel position="top-left" class="toprow">
      <div class="tools">
        {#if !readonly}
          <button class="btn small" onclick={() => onAddPart?.()} title={dt('add_part')}><Icon name="plus" size={15} /><span class="lbl">{dt('add_part')}</span></button>
        {/if}
        <button class="btn small ghost" onclick={tidy} disabled={!device.state?.doc.nodes.length || readonly} title={dt('layout')}><i class="ti ti-layout-grid" aria-hidden="true"></i><span class="lbl">{dt('layout')}</span></button>
        <button class="btn small ghost" onclick={() => bridge?.fit()} title={dt('fit')}><Icon name="maximize" size={15} /><span class="lbl">{dt('fit')}</span></button>
        <label class="toggle small" title={dt('power_wires')}>
          <input type="checkbox" bind:checked={powerWires} />
          <i class="ti ti-bolt" aria-hidden="true"></i><span class="lbl">{dt('power_wires')}</span>
        </label>
        {#if device.saving}<span class="muted xs">{dt('saving')}</span>{/if}
      </div>
      {#if buildBar}<div class="buildbar">
        {#if b.running}
          <span class="pill work"><i class="ti ti-loader-2 spin" aria-hidden="true"></i>
            <span class="lbl">{b.size && b.attempt ? dt('building_n', { w: b.size[0], h: b.size[1], n: b.attempt }) : dt('building')}</span></span>
        {:else if pcb && !device.stale}
          <button class="pill {pcb.ok ? 'ok' : 'err'}" onclick={() => onOpen?.('pcb')}>
            <Icon name={pcb.ok ? 'check' : 'alert'} size={13} />
            <span class="short">v{pcb.version}</span><span class="lbl">{pcb.ok ? dt('built_ok', { v: pcb.version }) : dt('built_bad', { v: pcb.version })}{b.size ? ` · ${dt('size', { w: b.size[0], h: b.size[1] })}` : ''}</span>
          </button>
          {#if pcb.ok}<button class="btn small ghost" onclick={() => onOpen?.('3d')} title={dt('open_case')}><Icon name="package" size={15} /><span class="lbl">{dt('open_case')}</span></button>{/if}
        {:else if device.stale && pcb}
          <span class="pill warn" title={dt('stale')}><Icon name="alert" size={13} /><span class="lbl">{dt('stale')}</span></span>
        {/if}
        {#if !readonly}
          <button class="btn small primary" onclick={() => device.startBuild()} disabled={b.running || device.empty}>
            <Icon name="cpu" size={15} /><span class="lbl">{pcb ? dt('rebuild') : dt('build')}</span>
          </button>
        {/if}
      </div>{/if}
    </Panel>{/if}
    {#if layouts.length}
      <!-- the designer's patterns (the dice pips, a row of keys): each lights its parts -->
      <Panel position="bottom-left" class="layouts">
        {#each layouts as l, i (i)}
          <button class="lay" class:on={device.lit?.key === `layout:${i}`} onclick={() => device.light(`layout:${i}`, l.nodes ?? [])}
            title={dt('layout_note_d')}>
            <i class="ti ti-map-pin" aria-hidden="true"></i>{patternName(l.pattern)} · <span class="mono">{(l.nodes ?? []).join(', ')}</span>
          </button>
        {/each}
      </Panel>
    {/if}
  </SvelteFlow>

  {#if device.failed}
    <div class="empty">
      <div class="emptycard card" role="alert">
        <Icon name="alert" size={28} />
        <p class="small">{device.error}</p>
        <div class="row"><button class="btn small" onclick={() => device.refresh()}>{t('retry')}</button></div>
      </div>
    </div>
  {:else if device.loaded && device.empty}
    <div class="empty">
      <div class="emptycard card">
        {#if busy}
          <i class="ti ti-loader-2 spin big" aria-hidden="true"></i>
          <h3>{dt('empty_busy')}</h3>
          <p class="muted small">{dt('empty_busy_d')}</p>
        {:else}
        <i class="ti ti-topology-star-3 big" aria-hidden="true"></i>
        <h3>{dt('empty_title')}</h3>
        <p class="muted small">{dt('empty_d')}</p>
        {/if}
        {#if !readonly && !busy}
          <div class="row">
            {#if onDescribe}<button class="btn primary small" onclick={onDescribe}><Icon name="message" size={15} /> {dt('agent_device')}</button>{/if}
            <button class="btn small" onclick={() => onAddPart?.()}><Icon name="plus" size={15} /> {dt('add_part')}</button>
          </div>
        {/if}
      </div>
    </div>
  {/if}
  {#if b.error && !b.running}
    <div class="builderr card small" role="alert"><Icon name="alert" size={14} /> {dt('build_failed')}: {b.error}</div>
  {/if}
</div>

<style>
  .device-editor {
    position: absolute;
    inset: 0;
    z-index: 2;
    container-type: size;
    background: var(--surface);
  }
  .device-editor :global(.svelte-flow) {
    --xy-background-color: var(--surface);
    --xy-background-pattern-dots-color-default: var(--surface-container-highest);
    --xy-edge-stroke-default: var(--outline);
    --xy-connectionline-stroke-default: var(--primary);
    --xy-minimap-background-color-default: var(--surface-container-low);
    --xy-minimap-mask-background-color-default: color-mix(in srgb, var(--surface) 70%, transparent);
    --xy-minimap-node-background-color-default: var(--surface-container-highest);
    --xy-controls-button-background-color-default: var(--surface-container);
    --xy-controls-button-background-color-hover-default: var(--surface-high);
    --xy-controls-button-color-default: var(--on-surface);
    --xy-controls-button-border-color-default: var(--outline-variant);
    --xy-edge-label-background-color-default: var(--surface);
    --xy-edge-label-color-default: var(--on-surface);
    --xy-node-background-color-default: transparent;
    --xy-node-border-default: none;
    --xy-node-boxshadow-selected-default: none;
    --xy-selection-background-color-default: color-mix(in srgb, var(--primary) 10%, transparent);
    --xy-selection-border-default: 1px dashed var(--primary);
    background: var(--surface);
  }
  .device-editor :global(.svelte-flow__node-part) {
    padding: 0;
    border: none;
    background: transparent;
    border-radius: var(--radius-lg);
  }
  .device-editor :global(.svelte-flow__edge-textbg) {
    fill: var(--surface);
  }
  .device-editor :global(.svelte-flow__edge-text) {
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    fill: var(--on-surface-var);
  }
  /* the gap a wire leaves in those it crosses, and the one under the pointer stands out */
  .device-editor :global(.wire-halo) {
    stroke: var(--surface);
    stroke-width: 6px;
    pointer-events: none;
  }
  .device-editor :global(.wire-dot) {
    pointer-events: none;
  }
  .device-editor :global(.svelte-flow__edge:hover .svelte-flow__edge-path) {
    stroke-width: 3px !important;
  }
  .device-editor :global(.svelte-flow__edge.selected .svelte-flow__edge-path) {
    stroke-width: 2.6px !important;
  }
  .device-editor :global(.svelte-flow__controls) {
    box-shadow: none;
    border: 1px solid var(--outline-variant);
    border-radius: var(--radius-md);
    overflow: hidden;
  }
  .device-editor :global(.svelte-flow__minimap) {
    border: 1px solid var(--outline-variant);
    border-radius: var(--radius-md);
    overflow: hidden;
  }
  /* one row across the top: tools on the left, the build on the right, wrapping on a narrow stage */
  .device-editor :global(.toprow) {
    right: 0;
    margin: 10px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: space-between;
    align-items: flex-start;
    pointer-events: none;
  }
  .tools,
  .buildbar {
    pointer-events: auto;
    display: flex;
    gap: 6px;
    align-items: center;
    flex-wrap: wrap;
    padding: 6px;
    border-radius: var(--radius-md);
    background: color-mix(in srgb, var(--surface-container) 88%, transparent);
    border: 1px solid var(--outline-variant);
    backdrop-filter: blur(6px);
  }
  .buildbar {
    justify-content: flex-end;
  }
  .device-editor :global(.layouts) {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    max-width: calc(100% - 20px);
  }
  .lay {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 24px;
    padding: 0 8px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--outline-variant);
    background: color-mix(in srgb, var(--surface-container) 90%, transparent);
    color: var(--on-surface-var);
    font: inherit;
    font-size: var(--text-sm);
    cursor: pointer;
    max-width: 360px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .lay.on {
    border-color: var(--primary);
    color: var(--on-surface);
    background: color-mix(in srgb, var(--primary) 16%, var(--surface-container));
  }
  .lay .mono {
    font-size: var(--text-xs);
  }
  .toggle {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    font-size: var(--text-sm);
    padding: 0 6px;
    cursor: pointer;
    color: var(--on-surface-var);
  }
  .empty {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    pointer-events: none;
    padding: var(--space-4);
  }
  .emptycard {
    pointer-events: auto;
    max-width: 420px;
    padding: var(--space-5);
    text-align: center;
    display: grid;
    gap: var(--space-2);
    justify-items: center;
  }
  .emptycard h3 {
    margin: 0;
  }
  .big {
    font-size: var(--text-4xl);
    color: var(--on-surface-var);
  }
  .row {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
    justify-content: center;
  }
  .builderr {
    position: absolute;
    left: 50%;
    bottom: 16px;
    transform: translateX(-50%);
    max-width: min(560px, 90%);
    padding: 8px 12px;
    z-index: 5;
    color: var(--error);
  }
  .lbl {
    margin-left: 5px;
  }
  .short {
    display: none;
  }
  /* a narrow or short stage (a phone, the studio's middle column on a laptop): icons only, so the parts stay visible */
  @container (max-width: 620px) {
    .lbl {
      display: none;
    }
    .short {
      display: inline;
    }
    .toggle {
      padding: 0 4px;
    }
  }
  @container (max-height: 420px) {
    .device-editor :global(.svelte-flow__minimap) {
      display: none;
    }
  }
</style>
