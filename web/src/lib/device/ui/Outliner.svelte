<script lang="ts">
  // The device as a tree (Blender's Outliner): the workspaces are the tabs above it. Every row does one thing on click:
  // a group folds, a part or a net is selected (and lit on the schematic).
  import type { ProjectStore } from '$lib/project.svelte';
  import type { DevNode } from '../api';
  import { POWER_NET } from '../store.svelte';
  import { netColor } from '../PartNode.svelte';
  import { dt } from '../i18n';

  let { store, stage, onStage }: { store: ProjectStore; stage: string; onStage: (s: 'schematic') => void } = $props();

  const dev = $derived(store.device);
  const ds = $derived(dev.state);
  const GROUPS: { key: string; kinds: string[] }[] = [
    { key: 'g_mcu', kinds: ['module'] },
    { key: 'lib_accessories', kinds: ['accessory'] },
    { key: 'g_chips', kinds: ['chip'] },
    { key: 'g_io', kinds: ['led', 'button'] },
    { key: 'g_conn', kinds: ['usb_c', 'header', 'jst'] },
    { key: 'g_passive', kinds: ['resistor', 'capacitor', 'diode'] },
  ];
  const ICON: Record<string, string> = {
    module: 'ti-cpu', chip: 'ti-cpu-2', resistor: 'ti-wave-square', capacitor: 'ti-battery-2', led: 'ti-bulb', diode: 'ti-chevrons-right',
    button: 'ti-hand-click', header: 'ti-plug-connected', usb_c: 'ti-usb', jst: 'ti-battery-charging', hole: 'ti-circle-dashed', accessory: 'ti-puzzle',
  };
  let folded = $state<Record<string, boolean>>({});
  const groups = $derived(GROUPS.map((g) => ({ ...g, nodes: (ds?.doc.nodes ?? []).filter((n) => g.kinds.includes(n.kind)) })).filter((g) => g.nodes.length));
  const name = (n: DevNode) => n.label || ds?.view.nodes[n.id]?.part.mpn || (n.value ? `${n.value} ${n.package ?? ''}` : dt(`k_${n.kind}`));
  const issues = $derived(new Set([...(ds?.issues ?? []), ...(ds?.lint ?? []), ...(ds?.rules ?? [])].filter((i) => i.severity !== 'info').map((i) => String(i.ref).split('.')[0])));

  function pickNode(id: string) {
    // a second click lets go: the panel below is back to the whole device
    dev.pickNode(dev.selected === id ? null : id);
    if (stage !== 'schematic' && stage !== 'board') onStage('schematic');
  }
  function pickNet(key: string) {
    dev.pickNet(dev.selectedNet === key ? null : key);
    if (stage !== 'schematic') onStage('schematic');
  }
</script>

<div class="ol" role="tree">
  {#each groups as g (g.key)}
    <button class="row l1 grp" onclick={() => (folded[g.key] = !folded[g.key])} aria-expanded={!folded[g.key]}>
      <span class="tw"><i class="ti ti-chevron-right ar" class:down={!folded[g.key]} aria-hidden="true"></i></span>
      <span class="nm">{dt(g.key)}</span><span class="meta">{g.nodes.length}</span><span class="dot"></span>
    </button>
    {#if !folded[g.key]}
      {#each g.nodes as n (n.id)}
        <button class="row l2" class:sel={dev.selected === n.id} onclick={() => pickNode(n.id)} role="treeitem" aria-selected={dev.selected === n.id}>
          <span class="tw"></span><i class="ti {ICON[n.kind] ?? 'ti-cpu'}" aria-hidden="true"></i>
          <span class="ref mono">{n.id}</span>
          <span class="nm">{name(n)}</span>
          <span class="dot" class:d-warn={issues.has(n.id)}></span>
        </button>
      {/each}
    {/if}
  {/each}

  {#if ds?.doc.nets.length}
    <button class="row l1 grp" onclick={() => (folded.nets = !folded.nets)} aria-expanded={!folded.nets}>
      <span class="tw"><i class="ti ti-chevron-right ar" class:down={!folded.nets} aria-hidden="true"></i></span>
      <span class="nm">{dt('g_nets')}</span><span class="meta">{ds.doc.nets.length}</span><span class="dot"></span>
    </button>
    {#if !folded.nets}
      {#each ds.doc.nets as net, i (i)}
        {@const key = net.name ?? `n${i}`}
        <button class="row l2" class:sel={dev.selectedNet === key} onclick={() => pickNet(key)} role="treeitem" aria-selected={dev.selectedNet === key}>
          <span class="tw"></span><span class="swatch" style="--c: {netColor(key)}"></span>
          <span class="nm mono" class:strong={POWER_NET.test(net.name ?? '')}>{net.name ?? net.pins.join(' – ')}</span>
          <span class="meta">{net.pins.length}</span><span class="dot"></span>
        </button>
      {/each}
    {/if}
  {/if}
</div>

<style>
  .ol {
    display: grid;
    padding: 4px 0;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    height: var(--bw-row, 26px);
    padding: 0 var(--bw-pad, 10px) 0 6px;
    border: none;
    background: none;
    color: var(--on-surface);
    font: inherit;
    font-size: var(--text-md);
    text-align: left;
    cursor: pointer;
    min-width: 0;
  }
  .row:hover {
    background: color-mix(in srgb, var(--on-surface) 7%, transparent);
  }
  .row.sel {
    background: color-mix(in srgb, var(--primary) 26%, transparent);
  }
  .l1 {
    padding-left: 6px;
  }
  .l2 {
    padding-left: 18px;
  }
  /* the twisty column: every row has one, so icons and names line up at each level */
  .tw {
    width: 12px;
    flex: none;
    display: grid;
    place-items: center;
  }
  .row i {
    font-size: var(--text-base);
    color: var(--on-surface-var);
    flex: none;
  }
  .nm {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .strong {
    font-weight: var(--font-weight-semibold);
  }
  .grp .nm {
    color: var(--on-surface-var);
  }
  .ref {
    font-size: var(--text-sm);
    color: var(--on-surface-var);
    flex: none;
    min-width: 36px;
  }
  .meta {
    font-size: var(--text-sm);
    color: var(--on-surface-var);
    flex: none;
    max-width: 110px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ar {
    font-size: var(--text-sm) !important;
    transition: transform var(--dur-fast) var(--ease-standard);
  }
  .ar.down {
    transform: rotate(90deg);
  }
  /* a status column at the right edge of every row, filled where there is something to say */
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex: none;
  }
  .d-ok {
    background: var(--ok);
  }
  .d-warn {
    background: var(--warn);
  }
  .d-err {
    background: var(--error);
  }
  .swatch {
    width: 10px;
    height: 10px;
    border-radius: var(--radius-xs);
    background: var(--c);
    flex: none;
    margin: 0 2px;
  }
</style>
