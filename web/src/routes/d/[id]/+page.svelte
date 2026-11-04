<script lang="ts">
  // The device workspace, laid out like a DCC/EDA tool (Blender's screen): workspace tabs in a thin top bar — Schematic,
  // Board, Case, Firmware, Manufacturing, the order the work happens in — and editor areas under it, each with its own
  // header: the AI engineer (the agent's chat) on the left, the main editor of the workspace in the middle, the Outliner
  // (the device as a tree) and the Properties (collapsible panels for what is selected or what the workspace edits) on
  // the right, a status bar at the bottom. While the agent works, the workspaces follow it.
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { onDestroy, setContext, untrack } from 'svelte';
  import Viewer from '$lib/components/Viewer.svelte';
  import Conversation from '$lib/components/Conversation.svelte';
  import Composer from '$lib/components/Composer.svelte';
  import ParamsPanel from '$lib/components/ParamsPanel.svelte';
  import ChecksPanel from '$lib/components/ChecksPanel.svelte';
  import PcbPanel from '$lib/components/PcbPanel.svelte';
  import GetItPanel from '$lib/components/GetItPanel.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { ProjectStore } from '$lib/project.svelte';
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
  import { accessoriesOf, placedBy, sizeText, sortChecks } from '$lib/device/facets';
  import { dt, patternName, usd } from '$lib/device/i18n';

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
  let quote = $state<QuoteState | null>(null);
  let stage = $state<Stage>('schematic');
  let chatOpen = $state(true);
  let wide = $state(true);
  let sheet = $state(false);
  let share = $state(false);
  let addOpen = $state(false);
  let powerWires = $state(false);
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
    const s = new ProjectStore(id);
    store = s;
    quote = new QuoteState(id);
    stage = 'schematic';
    const first = takeFirst(id);
    s.load().then(() => {
      if (s.detail && s.detail.pack !== 'device' && s.device.empty) {
        goto(`/p/${id}`, { replaceState: true });
        return;
      }
      s.device.refresh();
      if (first) s.sendFiles(first.text, first.files);
      quote?.loadOrders();
    });
    return () => s.dispose();
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
    if (quote && v && ok && qty) quote.load(v);
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
    else chatOpen = true;
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
  async function togglePublic() {
    if (!store?.detail) return;
    try {
      const p = await api.patchProject(store.id, { public: !store.detail.public });
      store.detail.public = p.public;
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
<svelte:window onkeydown={onKey} />

{#snippet chatArea()}
  {#if store}
    <header class="ah">
      <i class="ti ti-sparkles hi" aria-hidden="true"></i>
      <span class="at">{dt('ai_engineer')}</span>
      {#if store.running}<span class="busy"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {activity}</span>{/if}
      <span class="spacer"></span>
      {#if wide}<button class="hb icon" onclick={() => (chatOpen = false)} title={dt('collapse')} aria-label={dt('collapse')}><i class="ti ti-layout-sidebar-left-collapse" aria-hidden="true"></i></button>
      {:else}<button class="hb icon" onclick={() => (sheet = false)} aria-label={dt('close')}><i class="ti ti-x" aria-hidden="true"></i></button>{/if}
    </header>
    <div class="ab chatbody">
      <Conversation {store} {onAction} bare />
      {#if store.readonly}
        <div class="remix"><span><i class="ti ti-lock" aria-hidden="true"></i> {t('forbidden')}</span><button class="hb primary" onclick={fork}><i class="ti ti-git-fork" aria-hidden="true"></i> {t('fork')}</button></div>
      {:else}<Composer {store} placeholder={ds?.doc.nodes.length ? dt('composer_change') : dt('composer_new')} />{/if}
    </div>
  {/if}
{/snippet}

{#snippet editorHeader()}
  {#if store && dev}
    <i class="ti {STAGES.find((s) => s.id === stage)?.icon} hi" aria-hidden="true"></i>
    <span class="at">{dt(`stage_${stage}`)}</span>
    <span class="sep"></span>
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
    {:else if stage === 'board' && pcbV}
      <span class="meta">v{pcbV.version} · {pcbV.counts.components ?? '—'} {dt('pcs')} · {pcbV.counts.traces ?? 0} {dt('traces')} · {pcbV.counts.vias ?? 0} {dt('vias')}</span>
    {:else if stage === 'case' && store.source}
      <span class="meta">v{store.version}{caseMm ? ` · ${sizeText(caseMm)} ${dt('mm')}` : ''}{store.checks?.stats?.estGrams ? ` · ${Math.round(store.checks.stats.estGrams)} ${dt('g')}` : ''}</span>
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
        <!-- the board is up to date: rebuilding is still there, quietly -->
        <button class="hb icon" onclick={() => dev.startBuild()} title={dt('rebuild')} aria-label={dt('rebuild')}><i class="ti ti-refresh" aria-hidden="true"></i></button>
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

<div class="bw">
  <header class="top">
    <a class="logo" href="/" title="Formwright"><img src="/favicon.svg" alt="" onerror={(e) => ((e.currentTarget as HTMLImageElement).style.display = 'none')} /><span>F</span></a>
    {#if store?.detail}
      {#if store.readonly}<strong class="pname">{projectTitle(store.detail.title)}</strong>
      {:else}<input class="pname" value={projectTitle(store.detail.title)} onchange={rename} aria-label={t('name')} />{/if}
    {/if}
    <nav class="wtabs" role="tablist" aria-label={dt('stages')}>
      {#each STAGES as st, i (st.id)}
        <button role="tab" class="wt" aria-selected={stage === st.id} class:locked={status[st.id] === 'locked'} onclick={() => pick(st.id)} title="{dt(`stage_${st.id}`)} (Ctrl+{i + 1})">
          {#if status[st.id] === 'run'}<i class="ti ti-loader-2 spin sd" aria-hidden="true"></i>{:else}<span class="sd d-{status[st.id]}"></span>{/if}
          {dt(`stage_${st.id}`)}
        </button>
      {/each}
    </nav>
    <span class="spacer"></span>
    {#if dev?.saving}<span class="saving"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {dt('saving')}</span>{/if}
    {#if store?.connection === 'retry'}<span class="saving warnc">{t('reconnecting')}</span>{/if}
    {#if !wide}<button class="hb primary" onclick={() => (sheet = true)}><i class="ti ti-sparkles" aria-hidden="true"></i>{#if store?.running}<span class="pulse"></span>{/if}</button>{/if}
    {#if store?.detail}
      {#if store.readonly}<button class="hb primary" onclick={fork}><i class="ti ti-git-fork" aria-hidden="true"></i> {t('fork')}</button>
      {:else}
        <button class="hb icon" onclick={() => (share = true)} title={t('share')} aria-label={t('share')}><i class="ti ti-share" aria-hidden="true"></i></button>
        <button class="hb icon" onclick={fork} title={t('fork')} aria-label={t('fork')}><i class="ti ti-git-fork" aria-hidden="true"></i></button>
      {/if}
    {/if}
    <button class="hb icon" onclick={() => (i18n.lang = i18n.lang === 'ru' ? 'en' : 'ru')} title="Language" aria-label="Language"><span class="lang">{i18n.lang.toUpperCase()}</span></button>
  </header>

  {#if store?.loadError}
    <div class="center"><p class="err">{isText(store.loadError, 'forbidden') ? t('private_project') : store.loadError}</p><a class="hb" href="/">{t('back')}</a></div>
  {:else if !store?.detail || !dev}
    <div class="center"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></div>
  {:else}
    <div class="screen" class:nochat={!wide || !chatOpen}>
      {#if wide}
        {#if chatOpen}
          <section class="area chat">{@render chatArea()}</section>
        {:else}
          <button class="strip" onclick={() => (chatOpen = true)} title={dt('ai_engineer')}>
            <i class="ti ti-sparkles" aria-hidden="true"></i><span>{dt('ai_engineer')}</span>{#if store.running}<span class="pulse"></span>{/if}
          </button>
        {/if}
      {/if}

      <section class="area editor">
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
            <DeviceEditor bind:this={editor} bind:powerWires device={dev} {readonly} buildBar={false} toolbar={false} busy={store.running}
              onAddPart={() => (addOpen = true)} onDescribe={() => (wide ? (chatOpen = true) : (sheet = true))} />
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
              <Viewer
                loading={!!store.source && !store.build}
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

      <div class="rcol">
        <section class="area outl">
          <header class="ah"><i class="ti ti-list-tree hi" aria-hidden="true"></i><span class="at">{dt('outliner')}</span></header>
          <div class="ab scroll"><Outliner {store} {stage} onStage={(s) => pick(s)} /></div>
        </section>
        <section class="area props">
          <header class="ah"><i class="ti ti-adjustments-horizontal hi" aria-hidden="true"></i><span class="at">{dt('properties')}</span><span class="meta">{dt(`stage_${stage}`)}</span></header>
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
                    <dt>{dt('stage_board')}</dt><dd class:warnc={dev.stale} class:okc={!!pcbV && !dev.stale}>{pcbV ? (dev.stale ? dt('kv_stale') : `v${pcbV.version}`) : '—'}</dd>
                    <dt>{dt('version')}</dt><dd>{ds?.version ?? '—'}{dev.saving ? ` · ${dt('saving')}` : ''}</dd>
                    {#each ds?.doc.layouts ?? [] as l, i (i)}
                      <dt>{patternName(l.pattern)}</dt><dd><button class="lk" onclick={() => dev.light(`layout:${i}`, l.nodes ?? [])}>{(l.nodes ?? []).join(' ')}</button></dd>
                    {/each}
                  </dl>
                  {#if ds?.doc.summary}<p class="note">{ds.doc.summary}</p>{/if}
                </Panel>
                {#if concept?.options?.length || concept?.uses?.length}
                  <!-- how it is used and what it looks like, brainstormed before the parts: the chosen option marked -->
                  <Panel name="concept" title={dt('concept')}>
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
                  <p class="note">{dt('ed_d')}</p>
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
                  <ParamsPanel specs={sliderSpecs} values={store.values} agentValues={store.agentValues} building={store.building || !store.build} onChange={(n, v, c) => store!.setParam(n, v, c)} />
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
                  <dt>basic</dt><dd class="okc">{bom.filter((r) => r.basic === true && !r.hand).length}</dd>
                  <dt>extended</dt><dd class="warnc">{bom.filter((r) => r.basic === false && !r.hand).length}</dd>
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
              <Panel name="order" title={dt('order')}>
                <OrderSide q={quote} built={!!pcbV && !pcbV.drc.errors} stale={dev.stale} {readonly} files={fabFiles} />
              </Panel>
            {/if}
          </div>
        </section>
      </div>
    </div>



    {#if !wide && sheet}
      <div class="sheet" role="dialog" aria-label={dt('ai_engineer')}>{@render chatArea()}</div>
    {/if}
  {/if}
</div>

{#if share && store}
  <Modal title={t('share')} onClose={() => (share = false)}>
    <GetItPanel {store} readonly={store.readonly} onPublish={togglePublic} />
  </Modal>
{/if}

<style>
  /* the workspace's own density: small type, tight rows, thin seams between areas (a tool, not a page) */
  .bw {
    /* one set of measures for every area, panel and row, so edges line up */
    --bw-row: 26px;
    --bw-head-h: 34px;
    --bw-pad: 10px;
    --bw-gap: 8px;
    --bw-r: 6px;
    --bw-seam: var(--surface-container-lowest);
    --bw-area: var(--surface-container-low);
    --bw-head: var(--surface-container);
    --bw-panel: var(--surface-container);
    --bw-field: var(--surface);
    --bw-field-border: var(--outline-variant);
    --text-product-spec: 13px;
    --text-product-lead: 14px;
    --text-product-section-title: 15px;
    --text-card-name: 15px;
    --text-card-from: 12px;
    --text-card-meta: 11.5px;
    --text-card-section-label: 11px;
    --space-1: 3px;
    --space-2: 6px;
    --space-3: 8px;
    --space-4: 12px;
    --space-5: 14px;
    --space-6: 18px;
    --space-7: 24px;
    --space-8: 32px;
    --radius-card: 6px;
    --radius-btn: 5px;
    --radius-chip: 5px;
    --radius-field: 5px;
    --radius-segment: 5px;
    --radius-tag: 4px;
    height: 100dvh;
    display: grid;
    grid-template-rows: 38px minmax(0, 1fr);
    background: var(--bw-seam);
    color: var(--on-surface);
    font-size: 13px;
    overflow: hidden;
  }
  .bw :global(.btn) {
    padding: 5px 12px;
    gap: 6px;
    font-weight: var(--font-weight-medium);
  }
  .bw :global(.btn.small) {
    padding: 4px 10px;
  }
  .bw :global(.btn.icon) {
    width: 28px;
    height: 28px;
  }
  .bw :global(.btn.icon.small) {
    width: 26px;
    height: 26px;
  }
  .bw :global(.chip),
  .bw :global(.pill) {
    font-size: 11px;
    padding: 1px 6px;
  }

  /* ---- top bar: the workspaces */
  .top {
    display: flex;
    align-items: center;
    gap: var(--bw-gap);
    padding: 0 var(--bw-pad);
    background: var(--bw-head);
    border-bottom: 1px solid var(--bw-seam);
    min-width: 0;
  }
  .logo {
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    border-radius: 6px;
    background: var(--primary);
    color: var(--on-primary);
    font-weight: var(--font-weight-extrabold);
    text-decoration: none;
    flex: none;
    overflow: hidden;
  }
  .logo img {
    display: none;
  }
  .pname {
    font: inherit;
    font-size: 13px;
    font-weight: var(--font-weight-semibold);
    color: var(--on-surface);
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--bw-r);
    padding: 3px 8px;
    width: 220px;
    min-width: 80px;
    flex: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  input.pname:hover,
  input.pname:focus {
    background: var(--bw-field);
    border-color: var(--bw-field-border);
    outline: none;
  }
  .wtabs {
    display: flex;
    align-items: stretch;
    gap: 1px;
    height: 100%;
    min-width: 0;
    overflow-x: auto;
    scrollbar-width: none;
    margin-left: 6px;
  }
  .wt {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 0 16px;
    margin-top: 6px;
    border: none;
    border-radius: var(--bw-r) var(--bw-r) 0 0;
    background: transparent;
    color: var(--on-surface-var);
    font: inherit;
    font-size: 13px;
    white-space: nowrap;
    cursor: pointer;
  }
  .wt:hover {
    color: var(--on-surface);
    background: color-mix(in srgb, var(--on-surface) 6%, transparent);
  }
  .wt[aria-selected='true'] {
    background: var(--bw-area);
    color: var(--on-surface);
    font-weight: var(--font-weight-semibold);
  }
  .wt.locked {
    opacity: 0.5;
  }
  .sd {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    border: 1.5px solid var(--outline);
    flex: none;
  }
  i.sd {
    width: auto;
    height: auto;
    border: none;
    font-size: 11px;
    color: var(--primary);
  }
  .d-ok {
    background: var(--ok);
    border-color: var(--ok);
  }
  .d-warn,
  .d-stale {
    background: var(--warn);
    border-color: var(--warn);
  }
  .d-err {
    background: var(--error);
    border-color: var(--error);
  }
  .lang {
    font-size: 10.5px;
    font-weight: var(--font-weight-semibold);
  }

  /* ---- header buttons, Blender-sized */
  .hb {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 26px;
    padding: 0 10px;
    border-radius: var(--bw-r);
    border: 1px solid var(--bw-field-border);
    background: var(--surface-high);
    color: var(--on-surface);
    font: inherit;
    font-size: 12.5px;
    white-space: nowrap;
    cursor: pointer;
    text-decoration: none;
    position: relative;
  }
  .hb:hover:not(:disabled) {
    background: var(--surface-container-highest);
  }
  .hb:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .hb.primary {
    background: var(--primary);
    border-color: var(--primary);
    color: var(--on-primary);
  }
  .hb.icon {
    width: 28px;
    padding: 0;
    justify-content: center;
    background: transparent;
    border-color: transparent;
    color: var(--on-surface-var);
  }
  .hb.icon:hover {
    background: var(--surface-high);
    color: var(--on-surface);
  }
  .hb i {
    font-size: 14px;
  }
  :global(.bw .am .hb.on) {
    background: var(--surface-container-highest);
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

  /* ---- the screen: areas with seams */
  .screen {
    display: grid;
    grid-template-columns: 320px minmax(0, 1fr) 320px;
    gap: 4px;
    padding: 4px;
    min-height: 0;
  }
  .screen.nochat {
    grid-template-columns: 32px minmax(0, 1fr) 320px;
  }
  .area {
    display: flex;
    flex-direction: column;
    min-height: 0;
    min-width: 0;
    background: var(--bw-area);
    border-radius: var(--bw-r);
    overflow: hidden;
  }
  .ah {
    display: flex;
    align-items: center;
    gap: var(--bw-gap);
    height: var(--bw-head-h);
    padding: 0 var(--bw-pad);
    background: var(--bw-head);
    flex: none;
    min-width: 0;
  }
  .ah .hi {
    font-size: 15px;
    color: var(--on-surface-var);
  }
  .at {
    font-weight: var(--font-weight-semibold);
    white-space: nowrap;
  }
  .sep {
    width: 1px;
    height: 14px;
    background: var(--bw-field-border);
    margin: 0 2px;
  }
  .meta {
    color: var(--on-surface-var);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .busy {
    display: inline-flex;
    gap: 5px;
    align-items: center;
    color: var(--primary);
    font-size: 12px;
    white-space: nowrap;
  }
  .ab {
    flex: 1;
    min-height: 0;
    position: relative;
  }
  .scroll {
    overflow: auto;
  }
  .canvas {
    background: var(--surface);
  }
  .chatbody {
    display: flex;
    flex-direction: column;
  }
  /* the chat's own spacing is a page's: tighter here */
  .chatbody :global(.feed) {
    padding: 12px;
    gap: 10px;
  }
  .chatbody :global(.composer textarea) {
    line-height: 20px;
    padding: 9px 12px 2px;
    min-height: 48px;
  }
  /* the message field and its buttons without outlines, a little rounder than the workspace's 5px */
  .chatbody :global(.composer .box),
  .chatbody :global(.composer .box:hover),
  .chatbody :global(.composer .box:focus-within) {
    border: none;
    border-radius: 9px;
    box-shadow: none;
  }
  .chatbody :global(.composer .round) {
    border: none;
    border-radius: 8px;
  }
  .remix {
    display: flex;
    gap: 8px;
    align-items: center;
    justify-content: space-between;
    padding: 8px;
    border-top: 1px solid var(--bw-seam);
  }
  .strip {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 10px 0;
    border: none;
    border-radius: var(--bw-r);
    background: var(--bw-head);
    color: var(--on-surface-var);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    position: relative;
  }
  .strip span:not(.pulse) {
    writing-mode: vertical-rl;
    transform: rotate(180deg);
  }
  .strip:hover {
    color: var(--on-surface);
  }
  .strip i {
    color: var(--primary);
  }
  .rcol {
    display: grid;
    grid-template-rows: minmax(140px, 36%) minmax(0, 1fr);
    gap: 4px;
    min-height: 0;
  }
  .panels {
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  /* where a case value came from matters for a measured part; for a generated case it is always the design: no badge */
  .panels :global(.chip.src) {
    display: none;
  }
  .kv {
    display: grid;
    grid-template-columns: 40% 1fr;
    gap: 6px 10px;
    margin: 0;
    font-size: 13px;
  }
  .kv dt {
    color: var(--on-surface-var);
    text-align: right;
  }
  .kv dd {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .keys dt {
    font-family: inherit;
  }
  kbd {
    font-family: var(--font-mono);
    font-size: 10.5px;
    padding: 0 4px;
    border-radius: 3px;
    border: 1px solid var(--bw-field-border);
    background: var(--bw-field);
  }
  .note {
    margin: 0;
    font-size: 12px;
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
    font-size: 10.5px;
    min-width: 16px;
    padding: 0 4px;
    border-radius: 3px;
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
    border-radius: 4px;
    background: none;
    color: var(--on-surface);
    font: inherit;
    font-size: 12.5px;
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
    font-size: 12px;
    color: var(--on-surface-var);
  }
  .rid {
    font-size: 11px;
    color: var(--on-surface-var);
  }
  .rp {
    display: block;
    font-size: 11px;
    color: var(--on-surface-var);
  }
  .okc {
    color: var(--ok);
    font-size: 11.5px;
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
    font-size: 13px;
  }
  .empty p {
    margin: 0;
    font-size: 12px;
  }
  .big {
    font-size: 30px;
    color: var(--on-surface-var);
  }
  .banner {
    position: absolute;
    top: 8px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 5;
    padding: 3px 10px;
    border-radius: 3px;
    background: var(--bw-head);
    border: 1px solid var(--warn);
    color: var(--warn-text);
    font-size: 11.5px;
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
    background: color-mix(in srgb, var(--primary) 12%, var(--bw-head));
    border-bottom: 1px solid var(--bw-seam);
    font-size: 12.5px;
    flex: none;
  }
  .lockbar i {
    color: var(--primary);
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
    border-radius: 4px;
    background: transparent;
    color: var(--on-surface-var);
    font: inherit;
    font-size: 12.5px;
    cursor: pointer;
  }
  .seg2 button[aria-selected='true'] {
    background: var(--surface-container-highest);
    color: var(--on-surface);
  }
  .saving {
    display: inline-flex;
    gap: 5px;
    align-items: center;
    font-size: 12px;
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

  @media (max-width: 1280px) {
    .screen {
      grid-template-columns: 290px minmax(0, 1fr) 300px;
    }
    .screen.nochat {
      grid-template-columns: 32px minmax(0, 1fr) 300px;
    }
    .pname {
      width: 150px;
    }
  }
  /* a phone or a small tablet: one column, the editor over its properties, the AI engineer as a sheet */
  @media (max-width: 979px) {
    .bw {
      height: auto;
      min-height: 100dvh;
      overflow: visible;
      grid-template-rows: 38px auto;
    }
    .top {
      position: sticky;
      top: 0;
      z-index: 20;
    }
    .pname {
      display: none;
    }
    .wtabs {
      margin-left: 2px;
    }
    .wt {
      padding: 0 8px;
    }
    .screen,
    .screen.nochat {
      grid-template-columns: 1fr;
    }
    .editor {
      height: 58dvh;
    }
    .editor .ah {
      overflow-x: auto;
      scrollbar-width: none;
    }
    .rcol {
      grid-template-rows: auto auto;
    }
    .outl .ab {
      max-height: 220px;
    }
    .props .ab {
      overflow: visible;
    }
    .status {
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
