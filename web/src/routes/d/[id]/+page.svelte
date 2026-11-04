<script lang="ts">
  // The device workspace, laid out like a DCC/EDA tool (Blender's screen): workspace tabs in a thin top bar — Schematic,
  // Board, Case, Firmware, Manufacturing, the order the work happens in — and editor areas under it, each with its own
  // header: the AI engineer (the agent's chat) on the left, the main editor of the workspace in the middle, the Outliner
  // (the device as a tree) and the Properties (collapsible panels for what is selected or what the workspace edits) on
  // the right, a status bar at the bottom. While the agent works, the workspaces follow it.
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { onDestroy, setContext, untrack } from 'svelte';
  import Logo from '$lib/components/Logo.svelte';
  import Viewer from '$lib/components/Viewer.svelte';
  import Conversation from '$lib/components/Conversation.svelte';
  import Composer from '$lib/components/Composer.svelte';
  import ParamsPanel from '$lib/components/ParamsPanel.svelte';
  import ChecksPanel from '$lib/components/ChecksPanel.svelte';
  import PcbPanel from '$lib/components/PcbPanel.svelte';
  import GetItPanel from '$lib/components/GetItPanel.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import ReplayBar from '$lib/components/ReplayBar.svelte';
  import Sash from '$lib/components/Sash.svelte';
  import RowSash from '$lib/components/RowSash.svelte';
  import { SideDock } from '$lib/dock.svelte';
  import { ProjectStore } from '$lib/project.svelte';
  import { ReplayPlayer } from '$lib/replay.svelte';
  import { takeFirst } from '$lib/pending';
  import { api, download, errorText } from '$lib/api';
  import { i18n, t, isText, projectTitle } from '$lib/i18n.svelte';
  import { callTitle } from '$lib/steps';
  import type { Issue } from '$lib/types';
  import DeviceEditor from '$lib/device/DeviceEditor.svelte';
  import PartInspector from '$lib/device/PartInspector.svelte';
  import DesignChecks from '$lib/device/DesignChecks.svelte';
  import BoardSettings from '$lib/device/BoardSettings.svelte';
  import FirmwareCode from '$lib/device/FirmwareCode.svelte';
  import PinMap from '$lib/device/PinMap.svelte';
  import OrderCanvas from '$lib/device/OrderCanvas.svelte';
  import OrderSide from '$lib/device/OrderSide.svelte';
  import Panel from '$lib/device/ui/Panel.svelte';
  import Outliner from '$lib/device/ui/Outliner.svelte';
  import NetInspector from '$lib/device/NetInspector.svelte';
  import BomCanvas from '$lib/device/BomCanvas.svelte';
  import BoardEditor from '$lib/device/BoardEditor.svelte';
  import ConceptPanel from '$lib/device/ConceptPanel.svelte';
  import { bomOf, bomCsv } from '$lib/device/bom';
  import AddMenu from '$lib/device/ui/AddMenu.svelte';
  import { QuoteState } from '$lib/device/quote.svelte';
  import type { Accessory, DevNode, Review } from '$lib/device/api';
  import { loadLibrary } from '$lib/device/PartLibrary.svelte';
  import { accessoriesOf, placedBy, sortChecks } from '$lib/device/facets';
  import { dt, patternName, sizeIn, usd } from '$lib/device/i18n';
  import '$lib/device/ui/workspace.css';

  type Stage = 'schematic' | 'board' | 'case' | 'firmware' | 'bom' | 'make';
  type Status = 'empty' | 'run' | 'ok' | 'warn' | 'stale' | 'err' | 'locked';
  const STAGES: { id: Stage; icon: string }[] = [
    { id: 'schematic', icon: 'ti-topology-star-3' },
    { id: 'board', icon: 'ti-cpu' },
    { id: 'case', icon: 'ti-box' },
    { id: 'firmware', icon: 'ti-code' },
    { id: 'bom', icon: 'ti-list-details' },
    { id: 'make', icon: 'ti-building-factory-2' },
  ];

  let store = $state<ProjectStore | null>(null);
  /** ?replay: the recorded run plays back here (/w/<id> opens it), the project itself stays as it is. */
  const replayMode = $derived(page.url.searchParams.has('replay'));
  let player = $state<ReplayPlayer | null>(null);
  let barH = $state(0);
  let quote = $state<QuoteState | null>(null);
  let stage = $state<Stage>('schematic');
  const dock = new SideDock('device', { left: (w) => (w > 1280 ? 320 : 290), right: (w) => (w > 1280 ? 320 : 300) });
  let wide = $state(true);
  let sheet = $state(false);
  let share = $state(false);
  let addOpen = $state(false);
  let powerWires = $state(false);
  // the schematic's grid and magnet, as in the board editor, remembered for this viewer
  const GRIDS = [10, 20, 40];
  const savedGrid = (() => {
    try {
      return JSON.parse(localStorage.getItem('fw_schematic_grid') ?? 'null');
    } catch {
      return null;
    }
  })();
  let gridStep = $state<number>(GRIDS.includes(savedGrid?.g) ? savedGrid.g : 20);
  let showGrid = $state<boolean>(savedGrid?.show ?? true);
  let magnet = $state<boolean>(savedGrid?.magnet ?? true);
  $effect(() => {
    const v = JSON.stringify({ g: gridStep, show: showGrid, magnet });
    try {
      localStorage.setItem('fw_schematic_grid', v);
    } catch {
      /* not kept */
    }
  });
  // the seam between the outliner and the properties: the outliner's height, kept with the dock
  const OUTL_KEY = 'fw.dock.device.outliner';
  let outlH = $state<number | null>((() => {
    try {
      const v = Number(localStorage.getItem(OUTL_KEY));
      return v > 0 ? v : null;
    } catch {
      return null;
    }
  })());
  let rcolH = $state(0);
  const OUTL_MIN = 70;
  const outlMax = $derived(Math.max(OUTL_MIN, rcolH - OUTL_MIN - 4));
  const outlShown = $derived(outlH == null ? null : Math.min(outlH, outlMax));
  function saveOutl() {
    try {
      if (outlH == null) localStorage.removeItem(OUTL_KEY);
      else localStorage.setItem(OUTL_KEY, String(outlH));
    } catch {
      /* not kept */
    }
  }
  /** The board workspace: the editor (placement, routing, zones in one view), or the built board as rendered. */
  let boardMode = $state<'edit' | 'view'>('edit');
  let editor = $state<DeviceEditor>();
  let selectedIssue = $state<Issue | null>(null);
  let encFocus = $state<string | null>(null);
  let pickedAt = 0;

  setContext('fw.enclosure', {
    get current() {
      return store?.enclosure?.check ?? null;
    },
  });

  $effect(() => {
    const id = page.params.id!;
    const replay = replayMode;
    const s = new ProjectStore(id, false, replay);
    const p = replay ? new ReplayPlayer(s, Number(untrack(() => page.url.searchParams.get('at'))) || null) : null;
    store = s;
    player = p;
    quote = new QuoteState(id);
    stage = 'schematic';
    const first = takeFirst(id);
    s.load().then(() => {
      if (s.detail && s.detail.pack !== 'device' && (replay || s.device.empty)) {
        goto(`/p/${id}${replay ? location.search : ''}`, { replaceState: true });
        return;
      }
      s.device.refresh();
      if (first && s.detail) s.sendFiles(first.text, first.files);
      p?.start();
    });
    return () => {
      p?.dispose();
      s.dispose();
    };
  });
  onDestroy(() => store?.dispose());

  $effect(() => {
    const mq = matchMedia('(min-width: 980px)');
    const set = () => (wide = mq.matches);
    set();
    mq.addEventListener('change', set);
    return () => mq.removeEventListener('change', set);
  });

  const dev = $derived(store?.device ?? null);
  const ds = $derived(dev?.state ?? null);
  const pcbV = $derived(store?.pcb.versions.at(-1) ?? null);
  const locked = $derived(!!store?.running && !store.readonly);
  const readonly = $derived(!!store && (store.readonly || store.replaying || locked));
  const checks = $derived(sortChecks(ds));
  const lintN = $derived(checks.errors.length + checks.warnings.length);
  // the library's accessories: the BOM prices a module fitted by hand before the server's view of it is in
  let accessories = $state<Record<string, Accessory>>({});
  loadLibrary().then((l) => (accessories = Object.fromEntries(accessoriesOf(l).map((a) => [a.key, a])))).catch(() => {});
  const bom = $derived(bomOf(ds, accessories));
  // the device review: kept with the document, else the latest reviewer's verdict in this project's history
  const review = $derived.by<Review | null>(() => {
    if (ds?.review) return ds.review;
    const c = store?.timeline.findLast((i) => i.kind === 'critic');
    return c && c.kind === 'critic' ? { verdict: c.verdict, match_score: c.score, issues: c.issues, model: c.model, version: c.version } : null;
  });
  const caseMm = $derived((store?.enclosure?.check.summary as { case_mm?: number[] } | undefined)?.case_mm ?? null);
  const reqs = $derived(ds?.doc.requirements ?? []);
  const concept = $derived(ds?.doc.concept ?? null);
  const routing = $derived(!!dev?.build.running || !!store?.pcb.live);
  const caseOf = $derived(store?.casePcbVersion ?? null);
  const fw = $derived(ds?.doc.firmware ?? null);
  // what the agent is doing right now, in words: its latest step or status line
  const activity = $derived.by(() => {
    if (!store?.running) return null;
    const it = store.timeline.findLast((i) => i.kind === 'tool' || i.kind === 'status');
    if (it?.kind === 'tool') return callTitle(it.name, it.args, it.title);
    if (it?.kind === 'status') return it.text;
    return dt('ai_working');
  });

  const status = $derived.by((): Record<Stage, Status> => {
    const nodes = ds?.doc.nodes.length ?? 0;
    const pcbErr = pcbV?.drc.errors ?? 0;
    const stale = !!dev?.stale;
    const hasCase = !!store?.source && caseOf != null;
    return {
      schematic: nodes ? (checks.errors.length ? 'err' : lintN ? 'warn' : 'ok') : 'empty',
      board: routing ? 'run' : !pcbV ? 'empty' : stale ? 'stale' : pcbErr ? 'err' : 'ok',
      case: !hasCase ? (pcbV ? 'empty' : 'locked') : caseOf !== pcbV?.version ? 'stale' : store?.enclosure?.check.ok === false ? 'err' : 'ok',
      firmware: fw ? (fw.check?.ok === false ? 'err' : 'ok') : nodes ? 'empty' : 'locked',
      bom: !nodes ? 'locked' : bom.some((r) => r.stock === 0) ? 'warn' : 'ok',
      make: !pcbV ? 'locked' : pcbErr || stale ? 'warn' : 'ok',
    };
  });

  function pick(s: Stage) {
    stage = s;
    pickedAt = Date.now();
  }

  // ---- the workspaces follow the agent while it works, unless the person just picked one
  const following = () => !!store?.running && Date.now() - pickedAt > 20_000;
  let seenArrived = 0;
  $effect(() => {
    const a = dev?.arrived ?? 0;
    untrack(() => {
      if (a !== seenArrived && seenArrived !== 0 && following() && stage !== 'firmware') stage = 'schematic';
      seenArrived = a;
    });
  });
  $effect(() => {
    const live = !!store?.pcb.live;
    untrack(() => live && following() && (stage = 'board'));
  });
  let seenCase: number | null = null;
  $effect(() => {
    const v = store?.version ?? null;
    untrack(() => {
      if (caseOf != null && v !== seenCase && seenCase !== null && following()) stage = 'case';
      seenCase = v;
    });
  });
  let hadFw = false;
  $effect(() => {
    const has = !!fw;
    untrack(() => {
      if (has && !hadFw && store?.running && following()) stage = 'firmware';
      hadFw = has;
    });
  });

  $effect(() => {
    const v = pcbV?.version;
    const ok = pcbV && !pcbV.drc.errors;
    const qty = quote?.qty;
    // a replay passes many versions: its quote only when the order is being looked at
    if (quote && v && ok && qty && (!store?.replayMode || stage === 'make')) quote.load(v);
  });

  // ---- the case, as the parts studio shows it
  const enclosure = $derived(store?.enclosure ? { check: store.enclosure.check, stale: !store.enclosureFresh } : null);
  const layout = $derived(store?.hasLayout ? (store.assembled ? 'assembled' : 'print') : null);
  const sliderSpecs = $derived.by(() => {
    const specs = store?.build?.paramSpecs ?? {};
    const hide = store?.viewKeys ?? [];
    return hide.length ? Object.fromEntries(Object.entries(specs).filter(([k]) => !hide.includes(k))) : specs;
  });
  const shownIssues = $derived(selectedIssue ? (store?.checks?.issues ?? []) : []);
  $effect(() => {
    const v = caseOf;
    if (store && v != null) store.pcb.wantGlb(v);
  });
  const fabFiles = $derived(
    Object.fromEntries(Object.entries(pcbV?.artifacts ?? {}).filter(([n]) => ['gerbers.zip', 'bom.csv', 'cpl.csv'].includes(n)) as [string, string][]),
  );

  // ---- actions
  function send(text: string) {
    store?.send(text);
    if (!wide) sheet = true;
    else dock.show('left');
  }
  function addNode(node: Omit<DevNode, 'id'>) {
    store?.device.addNode(node, editor?.centre());
  }
  async function download3mf() {
    if (!store) return;
    const name = `${(store.detail?.title ?? 'case').replace(/[^\w-]+/g, '_').slice(0, 40)}.3mf`;
    try {
      await download(await store.exportFile('3mf'), name);
    } catch {
      try {
        await download(await api.exportFile(store.id, '3mf', $state.snapshot(store.values)), name);
      } catch (e) {
        store.addError(errorText(e));
      }
    }
  }

  function downloadCsv() {
    const blob = new Blob([bomCsv(bom)], { type: 'text/csv' });
    download(blob, `${(store?.detail?.title ?? 'device').replace(/[^\w-]+/g, '_').slice(0, 40)}-bom.csv`);
  }

  function onAction(a: string) {
    if (a.startsWith('stage:')) pick(a.slice(6) as Stage);
    else if (a === 'download') download3mf();
    else if (a === 'order') pick('make');
    else if (a === 'share') share = true;
  }
  async function rename(e: Event) {
    const v = (e.currentTarget as HTMLInputElement).value.trim();
    if (!store?.detail || !v || v === projectTitle(store.detail.title)) return;
    try {
      const p = await api.patchProject(store.id, { title: v });
      store.detail.title = p.title;
    } catch (err) {
      store.addError(errorText(err));
    }
  }
  async function fork() {
    if (!store) return;
    try {
      const p = await api.fork(store.id);
      goto(`/d/${p.id}`);
    } catch (err) {
      store.addError(errorText(err));
    }
  }
  function onKey(e: KeyboardEvent) {
    const el = e.target as HTMLElement | null;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (stage === 'schematic' && !readonly && e.shiftKey && e.key.toLowerCase() === 'a') {
      e.preventDefault();
      addOpen = true;
    } else if (stage === 'schematic' && e.key === 'Home') editor?.fit();
    else if (stage === 'schematic' && !e.ctrlKey && !e.metaKey && e.key.toLowerCase() === 'g') showGrid = !showGrid;
    else if (stage === 'schematic' && !e.ctrlKey && !e.metaKey && e.key.toLowerCase() === 'n') gridStep = GRIDS[(GRIDS.indexOf(gridStep) + (e.shiftKey ? GRIDS.length - 1 : 1)) % GRIDS.length];
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      if (e.shiftKey) dev?.redo();
      else dev?.undo();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
      e.preventDefault();
      dev?.redo();
    } else if (e.ctrlKey && /^[1-6]$/.test(e.key)) {
      e.preventDefault();
      pick(STAGES[Number(e.key) - 1].id);
    }
  }
</script>

<svelte:head><title>{store?.detail ? projectTitle(store.detail.title) : dt('workspace')} · Formwright</title></svelte:head>
<svelte:window onkeydown={onKey} bind:innerWidth={dock.viewport} />

{#snippet chatArea()}
  {#if store}
    <header class="ah">
      <span class="at">{dt('ai_engineer')}</span>
      {#if store.running}<span class="busy"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {activity}</span>{/if}
      <span class="spacer"></span>
      {#if wide}<button class="hb icon" onclick={() => dock.hide('left')} title={dt('collapse')} aria-label={dt('collapse')}><i class="ti ti-layout-sidebar-left-collapse" aria-hidden="true"></i></button>
      {:else}<button class="hb icon" onclick={() => (sheet = false)} aria-label={dt('close')}><i class="ti ti-x" aria-hidden="true"></i></button>{/if}
    </header>
    <div class="ab chatbody">
      <Conversation {store} {onAction} bare />
      {#if player}
        <!-- the player's bar says what to do with the run -->
      {:else if store.readonly}
        <div class="remix"><span><i class="ti ti-lock" aria-hidden="true"></i> {t('forbidden')}</span><a class="hb" href="/w/{store.id}"><i class="ti ti-player-play" aria-hidden="true"></i> {t('replay')}</a><button class="hb primary" onclick={fork}><i class="ti ti-git-fork" aria-hidden="true"></i> {t('fork')}</button></div>
      {:else}<Composer {store} placeholder={ds?.doc.nodes.length ? dt('composer_change') : dt('composer_new')} />{/if}
    </div>
  {/if}
{/snippet}

{#snippet editorHeader()}
  {#if store && dev}
    {#if stage === 'schematic'}
      {#if !readonly}
        <button class="hb icon" onclick={() => dev.undo()} disabled={!dev.canUndo} title="{dt('undo')} (Ctrl+Z)" aria-label={dt('undo')}><i class="ti ti-arrow-back-up" aria-hidden="true"></i></button>
        <button class="hb icon" onclick={() => dev.redo()} disabled={!dev.canRedo} title="{dt('redo')} (Ctrl+Shift+Z)" aria-label={dt('redo')}><i class="ti ti-arrow-forward-up" aria-hidden="true"></i></button>
        <span class="sep"></span>
        <AddMenu bind:open={addOpen} onAdd={addNode} />
      {/if}
      <button class="hb" onclick={() => editor?.tidy()} disabled={readonly || dev.empty}><i class="ti ti-layout-grid" aria-hidden="true"></i> {dt('layout')}</button>
      <button class="hb" onclick={() => editor?.fit()} title="{dt('fit')} (Home)"><i class="ti ti-focus-centered" aria-hidden="true"></i> {dt('fit')}</button>
      <label class="hb chk" title={dt('power_wires_d')}><input type="checkbox" bind:checked={powerWires} /> {dt('power_short')}</label>
      <span class="sep"></span>
      <button class="hb icon" class:lit={showGrid} onclick={() => (showGrid = !showGrid)} title="{dt('ed_grid')} (G)" aria-label={dt('ed_grid')} aria-pressed={showGrid}><i class="ti ti-grid-dots" aria-hidden="true"></i></button>
      <select class="gsel" bind:value={gridStep} title="{dt('ed_grid_step')} (N)" aria-label={dt('ed_grid_step')}>
        {#each GRIDS as g (g)}<option value={g}>{g}</option>{/each}
      </select>
      <button class="hb" class:lit={magnet} onclick={() => (magnet = !magnet)} title={dt('sch_magnet_d')} aria-pressed={magnet}><i class="ti ti-magnet" aria-hidden="true"></i> {dt('ed_magnet')}</button>
    {:else if stage === 'board' && pcbV}
      <span class="meta">v{pcbV.version} · {pcbV.counts.components ?? '—'} {dt('pcs')} · {pcbV.counts.traces ?? 0} {dt('traces')} · {pcbV.counts.vias ?? 0} {dt('vias')}</span>
    {:else if stage === 'case' && store.source}
      <span class="meta">v{store.version}{caseMm ? ` · ${sizeIn(caseMm)} ${dt('mm')}` : ''}{store.checks?.stats?.estGrams ? ` · ${Math.round(store.checks.stats.estGrams)} ${dt('g')}` : ''}</span>
    {:else if stage === 'firmware' && fw}
      <span class="meta">{fw.lang}</span>
    {:else if stage === 'bom' && bom.length}
      <span class="meta">{dt('bom_total', { lines: bom.length, parts: bom.reduce((n, r) => n + r.qty, 0) })}</span>
    {/if}
    {#if stage === 'board' && pcbV}
      <span class="sep"></span>
      <div class="seg2" role="tablist" aria-label={dt('board_mode')}>
        <button role="tab" aria-selected={boardMode === 'edit'} onclick={() => (boardMode = 'edit')}>{dt('mode_edit')}</button>
        <button role="tab" aria-selected={boardMode === 'view'} onclick={() => (boardMode = 'view')}>{dt('mode_view')}</button>
      </div>
    {/if}
    <span class="spacer"></span>
    {#if stage === 'board' && !readonly && !routing && dev.stale && pcbV}
      <button class="hb primary" onclick={() => dev.startBuild()} title={dt('route_rest_d')}><i class="ti ti-route" aria-hidden="true"></i> {dt('route_rest')}</button>
    {:else if (stage === 'schematic' || stage === 'board') && routing}
      <span class="busy"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {dev.build.size && dev.build.attempt ? dt('building_n', { w: dev.build.size[0], h: dev.build.size[1], n: dev.build.attempt }) : dt('building')}</span>
    {:else if (stage === 'schematic' || stage === 'board') && !readonly && !dev.empty}
      {#if pcbV && !dev.stale}
        <!-- the board is up to date: rebuilding is still there, named but without the accent -->
        <button class="hb" onclick={() => dev.startBuild()}><i class="ti ti-cpu" aria-hidden="true"></i> {dt('rebuild')}</button>
      {:else}
        <button class="hb primary" onclick={() => dev.startBuild()}><i class="ti ti-cpu" aria-hidden="true"></i> {pcbV ? dt('rebuild') : dt('build')}</button>
      {/if}
    {:else if stage === 'case' && store.source}
      <button class="hb" onclick={download3mf}><i class="ti ti-download" aria-hidden="true"></i> 3MF</button>
    {:else if stage === 'bom' && bom.length}
      <button class="hb" onclick={downloadCsv}><i class="ti ti-download" aria-hidden="true"></i> CSV</button>
    {:else if stage === 'firmware' && !fw && !readonly && !dev.empty}
      <button class="hb primary" onclick={() => send(dt('firmware_msg'))}><i class="ti ti-wand" aria-hidden="true"></i> {dt('firmware_ask')}</button>
    {/if}
  {/if}
{/snippet}

<div class="bw" class:replay={!!player} style:--replay-h="{player ? barH : 0}px">
  <header class="top">
    <a class="logo" href="/" title="Formwright" aria-label="Formwright"><Logo size={20} /></a>
    {#if store?.detail}
      {#if store.readonly}<strong class="pname">{projectTitle(store.detail.title)}</strong>
      {:else}<input class="pname" value={projectTitle(store.detail.title)} onchange={rename} aria-label={t('name')} />{/if}
    {/if}
    <nav class="wtabs" role="tablist" aria-label={dt('stages')}>
      {#each STAGES as st, i (st.id)}
        <button role="tab" class="wt" aria-selected={stage === st.id} class:locked={status[st.id] === 'locked'} onclick={() => pick(st.id)} title="{dt(`stage_${st.id}`)} (Ctrl+{i + 1})">
          <!-- a mark only where there is something to say: not made yet, out of date, or wrong -->
          {#if status[st.id] === 'run'}<i class="ti ti-loader-2 spin sd" aria-hidden="true"></i>{:else if status[st.id] !== 'ok' && status[st.id] !== 'locked'}<span class="sd d-{status[st.id]}"></span>{/if}
          {dt(`stage_${st.id}`)}
        </button>
      {/each}
    </nav>
    <span class="spacer"></span>
    {#if dev?.saving}<span class="saving"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {dt('saving')}</span>
    {:else if dev?.state && dev.error && dev.hasUnsaved}<button class="saving warnc retrysave" onclick={() => dev?.retrySave()} title="{dev.error} {t('not_saved_d')}">{t('not_saved')}</button>{/if}
    {#if store?.connection === 'retry'}<span class="saving warnc">{t('reconnecting')}</span>{/if}
    {#if !wide}<button class="hb primary" onclick={() => (sheet = true)} aria-label={dt('ai_engineer')}><i class="ti ti-message" aria-hidden="true"></i>{#if store?.running}<span class="pulse"></span>{/if}</button>{/if}
    {#if store?.detail}
      {#if store.readonly}<button class="hb primary" onclick={fork}><i class="ti ti-git-fork" aria-hidden="true"></i> {t('fork')}</button>
      {:else}
        {#if Object.keys(store.jobs).length && !store.running}
          <a class="hb icon" href="/w/{store.id}" title={t('watch_your_replay')} aria-label={t('watch_your_replay')}><i class="ti ti-player-play" aria-hidden="true"></i></a>
        {/if}
        <button class="hb icon" onclick={() => (share = true)} title={t('share')} aria-label={t('share')}><i class="ti ti-share" aria-hidden="true"></i></button>
        <button class="hb icon spare" onclick={fork} title={t('fork')} aria-label={t('fork')}><i class="ti ti-git-fork" aria-hidden="true"></i></button>
      {/if}
    {/if}
    <button class="hb icon spare" onclick={() => (i18n.lang = i18n.lang === 'ru' ? 'en' : 'ru')} title="Language" aria-label="Language"><span class="lang">{i18n.lang.toUpperCase()}</span></button>
  </header>

  {#if store?.loadError}
    <div class="center" role="alert">
      <p class="err">{isText(store.loadError, 'forbidden') ? t('private_project') : store.loadError}</p>
      {#if store.loadRetrying}<p class="xs muted">{t('load_retrying')}</p><button class="hb primary" onclick={() => store?.retryLoad()}>{t('retry')}</button>{/if}
      <a class="hb" href="/">{t('back')}</a>
    </div>
  {:else if !store?.detail || !dev}
    <div class="center"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></div>
  {:else}
    <div
      class="screen"
      class:wide
      class:no-left={dock.left.hidden}
      class:no-right={dock.right.hidden}
      style:--dock-l="{dock.width('left')}px"
      style:--dock-r="{dock.width('right')}px"
    >
      {#if wide}
        <section class="area chat" class:gone={dock.left.hidden}>{@render chatArea()}</section>
        <Sash {dock} side="left" label={dt('ai_engineer')} pulse={store.running} />
      {/if}

      <section class="area editor" class:tight={wide && dock.viewport - dock.width('left') - dock.width('right') < 960}>
        <header class="ah">{@render editorHeader()}</header>
        {#if locked}
          <div class="lockbar">
            <i class="ti ti-lock" aria-hidden="true"></i>
            <span>{dt('locked')}</span>
            <span class="spacer"></span>
            <button class="hb" onclick={() => store?.cancel()}><i class="ti ti-player-stop" aria-hidden="true"></i> {dt('stop_agent')}</button>
          </div>
        {/if}
        <div class="ab canvas">
          {#if stage === 'schematic'}
            <DeviceEditor bind:this={editor} bind:powerWires device={dev} {readonly} buildBar={false} toolbar={false} busy={store.running} grid={showGrid} {gridStep} {magnet}
              onAddPart={() => (addOpen = true)} onDescribe={() => (wide ? dock.show('left') : (sheet = true))} />
          {:else if stage === 'board'}
            {#if boardMode === 'edit' && pcbV && !store.pcb.live}
              <BoardEditor {store} {readonly} />
            {:else if store.pcb.versions.length || store.pcb.live}
              <PcbPanel {store} part="stage" replays={false} />
            {:else}
              <div class="empty">
                <i class="ti ti-cpu big" aria-hidden="true"></i>
                <strong>{dt('board_empty_title')}</strong>
                <p>{dt('board_empty_d')}</p>
                {#if !readonly && !dev.empty}<button class="hb primary" onclick={() => dev.startBuild()} disabled={routing}><i class="ti ti-cpu" aria-hidden="true"></i> {dt('build')}</button>{/if}
              </div>
            {/if}
          {:else if stage === 'case'}
            {#if store.source}
              {#if store.buildError}<p class="err small builderr" role="alert">{t('model_error')} {store.buildError}</p>{/if}
              <Viewer
                loading={!!store.source && !store.build && !store.buildError}
                build={store.build}
                issues={shownIssues}
                highlight={selectedIssue}
                values={store.values}
                specs={store.build?.paramSpecs ?? {}}
                onParam={(n, v, c) => store!.setParam(n, v, c)}
                {enclosure}
                board={store.board}
                {layout}
                onLayout={(l) => store!.setAssembled(l === 'assembled')}
                focusPart={encFocus}
                boardGlb={store.caseBoardGlb}
                checking={store.enclosureChecking}
                annotations={false}
              />
              {#if status.case === 'stale'}<div class="banner"><i class="ti ti-alert-triangle" aria-hidden="true"></i> {dt('case_stale')}</div>{/if}
            {:else}
              <div class="empty">
                <i class="ti ti-box big" aria-hidden="true"></i>
                <strong>{dt('case_empty_title')}</strong>
                <p>{dt('case_empty_d')}</p>
              </div>
            {/if}
          {:else if stage === 'firmware'}
            <FirmwareCode device={dev} projectId={store.id} {readonly} onSend={readonly ? undefined : send} />
          {:else if stage === 'bom'}
            <BomCanvas device={dev} {accessories} />
          {:else if quote}
            <OrderCanvas q={quote} built={!!pcbV && !pcbV.drc.errors} />
          {/if}
        </div>
      </section>

      {#if wide}<Sash {dock} side="right" label={dt('properties')} />{/if}

      <div class="rcol" class:gone={wide && dock.right.hidden} bind:clientHeight={rcolH} style:--outl-h={wide && outlShown != null ? `${outlShown}px` : undefined}>
        <section class="area outl">
          <header class="ah"><span class="at">{dt('outliner')}</span></header>
          <div class="ab scroll"><Outliner {store} {stage} onStage={(s) => pick(s)} /></div>
        </section>
        {#if wide}<RowSash bind:height={outlH} min={OUTL_MIN} max={outlMax} label={dt('outliner_resize')} onsave={saveOutl} />{/if}
        <section class="area props">
          <header class="ah"><span class="at">{dt('properties')}</span></header>
          <div class="ab scroll panels">
            {#if dev.selected && (stage === 'schematic' || stage === 'board')}
              <PartInspector device={dev} {readonly} />
            {/if}
            {#if dev.selectedNet && stage === 'schematic'}
              <NetInspector device={dev} {readonly} />
            {/if}
            {#if stage === 'schematic'}
              {#if !dev.selected && !dev.selectedNet}
                <Panel name="device" title={dt('panel_device')}>
                  <dl class="kv">
                    <dt>{dt('kv_parts')}</dt><dd>{ds?.doc.nodes.length ?? 0}</dd>
                    <dt>{dt('kv_nets')}</dt><dd>{ds?.doc.nets.length ?? 0}</dd>
                    <dt>{dt('kv_board_version')}</dt><dd class:warnc={dev.stale}>{pcbV ? (dev.stale ? dt('kv_stale') : `v${pcbV.version}`) : '—'}</dd>
                    <dt>{dt('kv_revision')}</dt><dd>{ds?.version ?? '—'}{dev.saving ? ` · ${dt('saving')}` : ''}</dd>
                    {#each ds?.doc.layouts ?? [] as l, i (i)}
                      <dt>{patternName(l.pattern)}</dt><dd><button class="lk" onclick={() => dev.light(`layout:${i}`, l.nodes ?? [])}>{(l.nodes ?? []).join(' ')}</button></dd>
                    {/each}
                  </dl>
                  {#if ds?.doc.summary}<p class="note">{ds.doc.summary}</p>{/if}
                </Panel>
                {#if concept?.options?.length || concept?.uses?.length}
                  <!-- how it is used and what it looks like, brainstormed before the parts: the chosen option marked -->
                  <Panel name="concept_v2" title={dt('concept')} open={false}>
                    {#snippet right()}{(concept?.chosen ?? '').slice(0, 28)}{/snippet}
                    <ConceptPanel concept={concept!} />
                  </Panel>
                {/if}
                {#if reqs.length}
                  <!-- what the device must do, as the designer wrote it first: a click lights the parts serving each -->
                  <Panel name="reqs" title={dt('reqs')}>
                    {#snippet right()}{reqs.length}{/snippet}
                    <ul class="reqs">
                      {#each reqs as r (r.id)}
                        <li>
                          <button class="rq" class:on={dev.lit?.key === r.id} onclick={() => dev.light(r.id, r.parts ?? [])} title={dt('reqs_light')}>
                            <span class="mono rid">{r.id}</span>
                            <span class="rt">{r.text}{#if r.firmware}{' '}<i class="ti ti-code" title={dt('reqs_fw')} aria-hidden="true"></i>{/if}
                              <span class="mono rp">{r.parts?.length ? r.parts.join(' ') : dt('reqs_none')}</span></span>
                          </button>
                        </li>
                      {/each}
                    </ul>
                  </Panel>
                {/if}
              {/if}
              <Panel name="checks" title={dt('side_checks')}>
                {#snippet right()}
                  {#if checks.errors.length}<span class="badge err">{checks.errors.length}</span>{/if}
                  {#if checks.warnings.length}<span class="badge">{checks.warnings.length}</span>{/if}
                  {#if !lintN}<i class="ti ti-check okc" aria-hidden="true"></i>{/if}
                {/snippet}
                <DesignChecks device={dev} {review} onSend={readonly ? undefined : send} />
              </Panel>

            {:else if stage === 'board'}
              {#if boardMode === 'edit'}
                <Panel name="editor" title={dt('ed_title')}>
                  <dl class="kv">
                    <dt>{dt('place_pinned')}</dt><dd>{ds?.doc.nodes.filter((n) => n.pcb).length ?? 0}</dd>
                    {#if ds?.doc.nodes.some((n) => placedBy(ds.doc, n) === 'designer')}<dt>{dt('kv_designer')}</dt><dd>{ds.doc.nodes.filter((n) => placedBy(ds.doc, n) === 'designer').length}</dd>{/if}
                    <dt>{dt('route_count')}</dt><dd>{ds?.doc.routes?.length ?? 0}</dd>
                    <dt>{dt('ed_zones')}</dt><dd>{ds?.doc.zones?.length ?? 0}</dd>
                  </dl>
                  {#if !readonly}
                    <div class="row-btns">
                      {#if ds?.doc.nodes.some((n) => n.pcb)}<button class="hb" onclick={() => dev.edit((d) => { for (const n of d.nodes) delete n.pcb; }, 'hand placement removed')}>{dt('place_free')}</button>{/if}
                      {#if ds?.doc.routes?.length}<button class="hb" onclick={() => dev.edit((d) => delete d.routes, 'hand traces removed')}><i class="ti ti-trash" aria-hidden="true"></i> {dt('route_clear')}</button>{/if}
                      {#if ds?.doc.zones?.length}<button class="hb" onclick={() => dev.edit((d) => delete d.zones, 'zones removed')}><i class="ti ti-trash" aria-hidden="true"></i> {dt('ed_clear_zones')}</button>{/if}
                    </div>
                  {/if}
                </Panel>
              {/if}
              <Panel name="board" title={dt('board_settings')}>
                <BoardSettings device={dev} {readonly} />
                {#if dev.stale && pcbV && !routing}<p class="warnc note"><i class="ti ti-alert-triangle" aria-hidden="true"></i> {dt('stale')}</p>{/if}
              </Panel>
              {#if store.pcb.versions.length}
                <Panel name="pcbinfo" title={dt('panel_pcb')}>
                  <PcbPanel {store} part="side" caseActions={false} onSend={readonly ? undefined : send} />
                </Panel>
              {/if}
            {:else if stage === 'case'}
              {#if store.source}
                <Panel name="caseparams" title={dt('case_params')}>
                  <ParamsPanel panel={dt('case_params')} specs={sliderSpecs} values={store.values} agentValues={store.agentValues} building={store.building || !store.build} onChange={(n, v, c) => store!.setParam(n, v, c)} />
                </Panel>
                <Panel name="casechecks" title={dt('case_checks')}>
                  <ChecksPanel
                    checks={store.checks}
                    selected={selectedIssue}
                    onSelect={(i) => (selectedIssue = i)}
                    building={store.building}
                    onAskFix={readonly ? undefined : send}
                    enclosure={store.enclosure?.check ?? null}
                    enclosureStale={!!store.enclosure && !store.enclosureFresh}
                    board={store.board}
                    focusPart={encFocus}
                    onFocusPart={(p) => {
                      encFocus = p;
                      if (p && store?.hasLayout && !store.assembled) store.setAssembled(true);
                    }}
                    assembled={!!layout && layout === 'assembled'}
                    enclosureChecking={store.enclosureChecking}
                  />
                </Panel>
              {:else}
                <p class="note">{dt('case_empty_d')}</p>
              {/if}
            {:else if stage === 'bom'}
              <Panel name="bomsum" title={dt('bom_summary')}>
                <dl class="kv">
                  <dt>{dt('kv_lines')}</dt><dd>{bom.length}</dd>
                  <dt>{dt('kv_count')}</dt><dd>{bom.reduce((n, r) => n + r.qty, 0)}</dd>
                  <dt>{dt('kv_smt')}</dt><dd>{bom.filter((r) => !r.hand).length}</dd>
                  <dt>{dt('kv_hand')}</dt><dd>{bom.filter((r) => r.hand && !r.fitted).length}</dd>
                  {#if bom.some((r) => r.fitted)}<dt>{dt('fitted_title')}</dt><dd>{bom.filter((r) => r.fitted).length}</dd>{/if}
                  <dt>{dt('basic')}</dt><dd>{bom.filter((r) => r.basic === true && !r.hand).length}</dd>
                  <dt>{dt('extended')}</dt><dd>{bom.filter((r) => r.basic === false && !r.hand).length}</dd>
                  <dt>{dt('kv_cost')}</dt><dd>{usd(bom.reduce((n, r) => n + (r.sum ?? 0), 0))}</dd>
                </dl>
                <p class="note">{dt('bom_note')}</p>
              </Panel>
              {#if bom.some((r) => r.stock != null && r.stock < 100)}
                <Panel name="bomstock" title={dt('bom_attention')}>
                  {#each bom.filter((r) => r.stock != null && r.stock < 100) as r (r.key)}
                    <p class="note warnc">{r.refs.join(', ')} · {r.part}: {r.stock ? dt('stock', { n: r.stock }) : dt('no_stock')}</p>
                  {/each}
                </Panel>
              {/if}
              <Panel name="bomfiles" title={dt('fab_files')}>
                <div class="asks">
                  <button class="hb" onclick={downloadCsv}><i class="ti ti-download" aria-hidden="true"></i> {dt('bom_csv')}</button>
                  {#if fabFiles['bom.csv']}<a class="hb" href={fabFiles['bom.csv']} download><i class="ti ti-download" aria-hidden="true"></i> {dt('bom_csv_fab')}</a>{/if}
                  {#if fabFiles['cpl.csv']}<a class="hb" href={fabFiles['cpl.csv']} download><i class="ti ti-download" aria-hidden="true"></i> CPL</a>{/if}
                </div>
                <p class="note">{fabFiles['bom.csv'] ? dt('bom_csv_d') : dt('bom_csv_nobuild')}</p>
              </Panel>
            {:else if stage === 'firmware'}
              <Panel name="pinmap" title={dt('pinmap')}><PinMap device={dev} /></Panel>
              {#if fw?.notes}<Panel name="fwnotes" title={dt('fw_notes')}><p class="note pre">{fw.notes}</p></Panel>{/if}
              {#if !readonly && fw}
                <Panel name="fwchange" title={dt('fw_change')}>
                  <div class="asks">
                    {#each ['fw_ask_web', 'fw_ask_sleep', 'fw_ask_mqtt'] as k (k)}<button class="hb" onclick={() => send(dt(`${k}_msg`))}>{dt(k)}</button>{/each}
                  </div>
                </Panel>
              {/if}
            {:else if quote}
              <Panel name="order" title={dt('order_panel')}>
                <OrderSide q={quote} built={!!pcbV && !pcbV.drc.errors} stale={dev.stale} {readonly} files={fabFiles} projectId={store.id} />
              </Panel>
            {/if}
          </div>
        </section>
      </div>
    </div>



    {#if !wide && sheet}
      <div class="sheet" role="dialog" aria-label={dt('ai_engineer')}>{@render chatArea()}</div>
    {/if}
    {#if player}<div class="replaybar" bind:clientHeight={barH}><ReplayBar {player} onFork={fork} exit="/d/{store.id}" /></div>{/if}
  {/if}
</div>

{#if share && store}
  <Modal title={t('share')} onClose={() => (share = false)}>
    <GetItPanel {store} readonly={store.readonly} />
  </Modal>
{/if}

<style>
  /* an editor narrowed by its side panels: the header's buttons down to their icons, so the last of them stays on screen */
  .editor.tight .ah .hb:not(.primary, .icon),
  .editor.tight .ah :global(.am .hb) {
    font-size: 0;
    gap: 2px;
    padding: 0 7px;
  }
  :global(.bw .am .hb.on) {
    background: var(--surface-container-highest);
  }
  .gsel {
    height: 26px;
    padding: 0 22px 0 8px;
    background-position: right 7px center;
    background-size: 9px;
    background-color: var(--surface-high);
    border-radius: var(--bw-r);
    font-size: var(--text-md);
    flex: none;
  }
  .hb.chk {
    background: transparent;
    border-color: transparent;
    color: var(--on-surface-var);
  }
  .hb.chk input {
    margin: 0;
  }
  .spacer {
    flex: 1;
  }

  .ah .hi {
    font-size: var(--text-lg);
    color: var(--on-surface-var);
  }
  .sep {
    width: 1px;
    height: 14px;
    background: var(--bw-field-border);
    margin: 0 2px;
  }
  .meta {
    color: var(--on-surface-var);
    font-size: var(--text-sm);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .busy {
    display: inline-flex;
    gap: 5px;
    align-items: center;
    color: var(--primary);
    font-size: var(--text-sm);
    white-space: nowrap;
  }
  .rcol {
    display: grid;
    grid-template-rows: var(--outl-h, minmax(140px, 36%)) 4px minmax(0, 1fr);
    min-height: 0;
  }
  /* where a case value came from matters for a measured part; for a generated case it is always the design: no badge */
  .panels :global(.chip.src) {
    display: none;
  }
  /* a label on the left edge, its value on the right one */
  .kv {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 5px 12px;
    margin: 0;
    font-size: var(--text-md);
  }
  .kv dt {
    color: var(--on-surface-var);
  }
  .kv dd {
    margin: 0;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .keys dt {
    font-family: inherit;
  }
  kbd {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    padding: 0 4px;
    border-radius: var(--radius-xs);
    border: 1px solid var(--bw-field-border);
    background: var(--bw-field);
  }
  .note {
    margin: 0;
    font-size: var(--text-sm);
    line-height: 1.45;
    color: var(--on-surface-var);
  }
  .pre {
    white-space: pre-wrap;
  }
  .asks {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .badge {
    font-size: var(--text-xs);
    min-width: 16px;
    padding: 0 4px;
    border-radius: var(--radius-xs);
    background: color-mix(in srgb, var(--warn) 28%, transparent);
    color: var(--warn-text);
    text-align: center;
  }
  .badge.err {
    background: color-mix(in srgb, var(--error) 24%, transparent);
    color: var(--error);
  }
  .lk {
    border: none;
    background: none;
    padding: 0;
    color: var(--primary);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .reqs {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 2px;
  }
  .rq {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 8px;
    align-items: baseline;
    width: 100%;
    padding: 4px 5px;
    border: none;
    border-radius: var(--radius-xs);
    background: none;
    color: var(--on-surface);
    font: inherit;
    font-size: var(--text-md);
    line-height: 1.35;
    text-align: left;
    cursor: pointer;
  }
  .rq:hover {
    background: color-mix(in srgb, var(--on-surface) 7%, transparent);
  }
  .rq.on {
    background: color-mix(in srgb, var(--primary) 22%, transparent);
  }
  .rq i {
    font-size: var(--text-sm);
    color: var(--on-surface-var);
  }
  .rid {
    font-size: var(--text-xs);
    color: var(--on-surface-var);
  }
  .rp {
    display: block;
    font-size: var(--text-xs);
    color: var(--on-surface-var);
  }
  .okc {
    color: var(--ok);
    font-size: var(--text-sm);
    display: inline-flex;
    gap: 4px;
    align-items: center;
    white-space: nowrap;
  }
  .warnc {
    color: var(--warn-text);
  }
  .empty {
    position: absolute;
    inset: 0;
    margin: auto;
    height: fit-content;
    max-width: 380px;
    display: grid;
    justify-items: center;
    gap: 6px;
    text-align: center;
    padding: 16px;
    color: var(--on-surface-var);
  }
  .empty strong {
    color: var(--on-surface);
    font-size: var(--text-md);
  }
  .empty p {
    margin: 0;
    font-size: var(--text-sm);
  }
  .big {
    font-size: var(--text-3xl);
    color: var(--on-surface-var);
  }
  .banner {
    position: absolute;
    top: 8px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 5;
    padding: 3px 10px;
    border-radius: var(--radius-xs);
    background: var(--bw-head);
    border: 1px solid var(--warn);
    color: var(--warn-text);
    font-size: var(--text-sm);
  }

  .row-btns {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
  }
  .lockbar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px var(--bw-pad);
    background: var(--bw-head);
    border-bottom: 1px solid var(--bw-seam);
    font-size: var(--text-md);
    flex: none;
  }
  .seg2 {
    display: inline-flex;
    padding: 2px;
    gap: 2px;
    border-radius: var(--bw-r);
    background: var(--bw-field);
    border: 1px solid var(--bw-field-border);
  }
  .seg2 button {
    height: 22px;
    padding: 0 10px;
    border: none;
    border-radius: var(--radius-xs);
    background: transparent;
    color: var(--on-surface-var);
    font: inherit;
    font-size: var(--text-md);
    cursor: pointer;
  }
  .seg2 button[aria-selected='true'] {
    background: var(--surface-container-highest);
    color: var(--on-surface);
  }
  .retrysave {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    color: var(--warn-text);
  }
  .builderr {
    margin: 0;
    padding: 8px 12px;
  }
  .saving {
    display: inline-flex;
    gap: 5px;
    align-items: center;
    font-size: var(--text-sm);
    color: var(--on-surface-var);
  }
  .pulse {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--primary);
    animation: pulse 1.2s ease-in-out infinite;
  }
  .hb .pulse {
    position: absolute;
    top: -2px;
    right: -2px;
    background: var(--warn);
  }
  @keyframes pulse {
    50% {
      opacity: 0.3;
    }
  }
  .center {
    display: grid;
    place-items: center;
    align-content: center;
    gap: 10px;
  }

  /* a phone or a small tablet: one column, the editor over its properties, the AI engineer as a sheet */
  @media (max-width: 979px) {
    .bw.replay .sheet {
      bottom: var(--replay-h);
    }
    .seg2 button {
      height: 34px;
    }
    .rcol {
      grid-template-rows: auto auto;
      gap: 4px;
    }
    .outl .ab {
      max-height: 220px;
    }
    .status {
      display: none;
    }
    /* what a phone can do without: the tabs need the room */
    .spare {
      display: none;
    }
    .sheet {
      position: fixed;
      inset: 0;
      z-index: 50;
      background: var(--bw-area);
      display: flex;
      flex-direction: column;
    }
  }
</style>
