<script lang="ts">
  // The parts studio, laid out as the device workspace is (lib/device/ui/workspace.css): workspace tabs in a thin top bar,
  // the AI engineer on the left, the model in the middle, the Properties of the tab on the right.
  import { page } from '$app/state';
  import { goto, replaceState } from '$app/navigation';
  import { onDestroy, onMount, setContext, untrack } from 'svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Logo from '$lib/components/Logo.svelte';
  import Viewer from '$lib/components/Viewer.svelte';
  import StageProgress from '$lib/components/StageProgress.svelte';
  import Conversation from '$lib/components/Conversation.svelte';
  import Composer from '$lib/components/Composer.svelte';
  import ParamsPanel from '$lib/components/ParamsPanel.svelte';
  import MeshOpsPanel from '$lib/components/MeshOpsPanel.svelte';
  import ChecksPanel from '$lib/components/ChecksPanel.svelte';
  import PrintPanel from '$lib/components/PrintPanel.svelte';
  import GetItPanel, { rememberAxoDesign } from '$lib/components/GetItPanel.svelte';
  import MorePanel from '$lib/components/MorePanel.svelte';
  import PcbPanel from '$lib/components/PcbPanel.svelte';
  import SnapHighlight from '$lib/components/SnapHighlight.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import ReplayBar from '$lib/components/ReplayBar.svelte';
  import Sash from '$lib/components/Sash.svelte';
  import { SideDock } from '$lib/dock.svelte';
  import { ProjectStore } from '$lib/project.svelte';
  import { ReplayPlayer } from '$lib/replay.svelte';
  import { stashFirst, takeFirst } from '$lib/pending';
  import { api, download, errorText } from '$lib/api';
  import { i18n, t, isText, projectTitle, unitLabel } from '$lib/i18n.svelte';
  import { refreshMe } from '$lib/session.svelte';
  import { callTitle } from '$lib/steps';
  import { dt } from '$lib/device/i18n';
  import Panel from '$lib/device/ui/Panel.svelte';
  import '$lib/device/ui/workspace.css';
  import type { AssetOut, Calibration, Issue, ScanBox } from '$lib/types';
  import type { Box } from '$lib/snapframe';

  type Tab = 'chat' | 'model' | 'pcb' | 'checks' | 'print' | 'more';

  let store = $state<ProjectStore | null>(null);
  /** ?replay: the recorded run plays back here (/w/<id> opens it), the project itself stays as it is. */
  const replayMode = $derived(page.url.searchParams.has('replay'));
  let player = $state<ReplayPlayer | null>(null);
  let barH = $state(0);
  let tab = $state<Tab>('model');
  let selectedIssue = $state<Issue | null>(null);
  let arAsset = $state<AssetOut | null>(null);
  let viewer = $state<Viewer>();
  let wide = $state(true);
  // the side panels give way on a laptop screen, so the model keeps most of the width
  const dock = new SideDock('studio', {
    left: (w) => Math.round(Math.min(390, Math.max(300, w * 0.24))),
    right: (w) => Math.round(Math.min(360, Math.max(300, w * 0.22))),
  });
  let getIt = $state(false);
  /** What More → Ideas should do once it opens: sketch concepts for a prompt, or start drawing a change. */
  let ideas = $state<{ prompt?: string; draw?: boolean } | null>(null);
  // phones and small tablets: Share and Remix live in an overflow menu
  let menu = $state(false);
  let menuWrap = $state<HTMLElement>();
  // 'f' gives the whole width to the viewer (demo shots)
  let expanded = $state(false);
  /** The board part picked in the case check: the viewer lights up its rays and label. */
  let encFocus = $state<string | null>(null);
  let scanOpen = $state(false);
  /** Board scans the person folded or unfolded (selection id -> folded); unfolded by default next to a wide stage. */
  let scanFolded = $state<Record<string, boolean>>({});

  // the result cards in the conversation show the latest case check of their version
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
    selectedIssue = null;
    arAsset = null;
    getIt = false;
    encFocus = null;
    scanOpen = false;
    const first = takeFirst(id);
    // "Ideas first" from the home page: open the sketches with that text, once (a reload must not start them again)
    const idea = untrack(() => page.url.searchParams.get('ideas'))?.trim();
    // back from the Axo shop's cart to edit this design (?axo=<design id>): "Update in Axo cart" replaces that line
    const axo = untrack(() => page.url.searchParams.get('axo'));
    rememberAxoDesign(id, axo);
    s.load().then(() => {
      // a device has its own workspace: its first message goes along
      if (s.detail?.pack === 'device') {
        if (first) stashFirst(id, first.text, first.files);
        goto(`/d/${id}${replay ? location.search : ''}`, { replaceState: true });
        return;
      }
      p?.start();
      // remembered for this tab: a reload or Back must not bring back a line an update has replaced since
      if (axo && !idea) {
        const u = new URL(location.href);
        u.searchParams.delete('axo');
        replaceState(u.pathname + u.search + u.hash, {});
      }
      if (first && s.detail) s.sendFiles(first.text, first.files);
      // a board project without a 3D model yet: its PCB is the picture
      if (s.detail?.pack === 'pcb' && !s.source && wide) show('pcb');
      if (idea && s.detail) {
        replaceState(location.pathname, {});
        open('more');
        ideas = { prompt: idea };
      }
    });
    return () => {
      p?.dispose();
      s.dispose();
    };
  });

  $effect(() => {
    const mq = matchMedia('(min-width: 980px)');
    const set = () => {
      wide = mq.matches;
      if (wide && tab === 'chat') tab = 'model';
      if (!wide && tab === 'model' && !store?.source) tab = 'chat';
    };
    set();
    mq.addEventListener('change', set);
    return () => mq.removeEventListener('change', set);
  });

  onDestroy(() => store?.dispose());
  // the order panel asks who this is (the Axo cart); a visitor has no composer to ask for it
  onMount(() => void refreshMe());

  const photo = $derived.by(() => {
    if (!store) return null;
    const a = arAsset ?? [...store.assets].reverse().find((x) => x.meta?.calibration?.R);
    const cal = a?.meta?.calibration as Calibration | undefined;
    if (!a || !cal?.R || !cal?.t) return null;
    return { url: a.url, calibration: { ...cal, width: cal.width ?? a.width ?? 1, height: cal.height ?? a.height ?? 1 } };
  });

  // the PCB tab: a board project, or one that has a routed board (or is routing one now)
  const pcbTab = $derived(!!store && (store.detail?.pack === 'pcb' || store.pcb.versions.length > 0 || !!store.pcb.live));
  // a part for a workshop: every check and setting of those tabs is about a printer
  const machined = $derived(store?.detail?.process === 'machined');
  const tabs = $derived<Tab[]>([...(wide ? [] : ['chat' as Tab]), 'model', ...(pcbTab ? ['pcb' as Tab] : []), ...(machined ? [] : ['checks' as Tab, 'print' as Tab]), 'more']);
  const encErrors = $derived(store?.enclosure?.check.findings?.filter((f) => f.severity === 'error').length ?? 0);
  const errCount = $derived(store?.checks?.issues.filter((i) => i.severity === 'error').length ?? 0);
  const warnCount = $derived(store?.checks?.issues.filter((i) => i.severity === 'warn').length ?? 0);
  // a case's checks measure its parts laid out for printing: closed around its board, the case's own outer box (the
  // board ghost carries it) is the size; otherwise the chip says it is the plate's
  const outer = $derived(store?.assembled ? store.build?.parts?.find((p) => p.meta?.enclosure)?.meta?.enclosure?.outerSize : undefined);
  const size = $derived(outer ?? store?.checks?.stats?.size);
  const plate = $derived(!!store?.hasLayout && !outer);
  // the editor header's line: version, size, weight
  const facts = $derived.by(() => {
    const grams = store?.checks?.stats?.estGrams;
    return [
      `v${store?.version}`,
      size ? `${plate ? `${t('size_plate')} ` : ''}${size.map((v) => +v.toFixed(1)).join(' × ')} ${unitLabel('mm')}` : '',
      grams && !machined ? `${Math.round(grams)} ${dt('g')}` : '',
    ].filter(Boolean).join(' · ');
  });
  const job = $derived(store?.currentJob ?? null);
  // what the agent is doing right now, in words: its latest step or status line
  const activity = $derived.by(() => {
    if (!store?.running) return null;
    const it = store.timeline.findLast((i) => i.kind === 'tool' || i.kind === 'status');
    if (it?.kind === 'tool') return callTitle(it.name, it.args, it.title);
    if (it?.kind === 'status') return it.text;
    return t('agent_working');
  });
  // no model yet and the agent is on it: the stage shows what it is doing instead of an empty bed
  const progress = $derived(!!store && !store.build && (!!store.starting || job?.status === 'running' || job?.status === 'waiting'));
  // printability boxes belong to the Checks tab; elsewhere the overhang heat tells the story
  const shownIssues = $derived(tab === 'checks' || selectedIssue ? (store?.checks?.issues ?? []) : []);
  // A hand-written home page example the agent has not reworked yet (slider edits keep it one). After a
  // reload the latest version may be such an edit: then the project's versions say what it started from.
  let editedExample = $state<{ id: string; yes: boolean } | null>(null);
  $effect(() => {
    const s = store;
    if (!s || s.detail?.program?.author !== 'user') return;
    api
      .versions(s.id)
      .then((vs) => (editedExample = { id: s.id, yes: vs[0]?.author === 'example' && vs.every((v) => v.author === 'example' || v.author === 'user') }))
      .catch(() => {});
  });
  // the case and its check against the board, for the viewer
  const enclosure = $derived(store?.enclosure ? { check: store.enclosure.check, stale: !store.enclosureFresh } : null);
  const layout = $derived(store?.hasLayout ? (store.assembled ? 'assembled' : 'print') : null);
  // layout and show_board are a view the viewer switches, not sliders
  const sliderSpecs = $derived.by(() => {
    const specs = store?.build?.paramSpecs ?? {};
    const hide = store?.viewKeys ?? [];
    return hide.length ? Object.fromEntries(Object.entries(specs).filter(([k]) => !hide.includes(k))) : specs;
  });

  // a board read from a photo (scan_board's selection): the photo with its labelled boxes
  const scan = $derived.by(() => {
    const sel = store?.selections.findLast((x) => x.data?.kind === 'board_scan');
    const a = sel ? store?.assets.find((x) => x.id === sel.asset_id) : null;
    if (!sel || !a || !a.width || !a.height) return null;
    const d = sel.data;
    const cal = d.calibration ?? {};
    const box = Array.isArray(d.bbox_px) && d.bbox_px.length === 4 ? (d.bbox_px as Box) : null;
    return {
      id: sel.id, url: a.url, w: a.width, h: a.height, box, boxes: (d.boxes ?? []) as ScanBox[],
      // data.board is the board's id; its JSON went to the program's inputs under data.input
      marking: (d.marking as string | null) ?? null, name: (store?.inputs?.boards?.[String(d.input ?? '').split('.').pop() ?? '']?.name as string | undefined) ?? null,
      scale: cal.method ? t(`scan_scale_${cal.method}`) + (cal.uncertainty_mm ? ` · ±${+Number(cal.uncertainty_mm).toFixed(2)} ${unitLabel('mm')}` : '') : '',
      deltas: Array.isArray(d.deltas) ? d.deltas.length : 0, dataset: d.board_id ? true : false,
    };
  });

  // a case made from a routed board shows that board inside: its glb_map comes with the version's frames
  $effect(() => {
    const v = store?.casePcbVersion;
    if (store && v != null) store.pcb.wantGlb(v);
  });

  // a build starting to route moves to the PCB tab, so its frames are seen
  let routingSeen = false;
  $effect(() => {
    const routing = !!store?.pcb.live;
    untrack(() => {
      if (routing && !routingSeen && (wide || tab !== 'chat')) show('pcb');
      routingSeen = routing;
    });
  });

  const example = $derived(
    !!store &&
      (store.detail?.program?.author === 'example' || (editedExample?.id === store.id && editedExample.yes)) &&
      !store.timeline.some((i) => i.kind === 'program' && i.author !== 'user'),
  );

  // A rebuild brings a new report: keep the picked kind of issue (Checks picks the first of a kind), or drop it.
  $effect(() => {
    const issues = store?.checks?.issues;
    untrack(() => {
      if (!selectedIssue || issues?.includes(selectedIssue)) return;
      const code = selectedIssue.code;
      selectedIssue = issues?.find((i) => i.code === code) ?? null;
    });
  });

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
    menu = false;
    try {
      const p = await api.fork(store.id);
      goto(`/p/${p.id}`);
    } catch (err) {
      store.addError(errorText(err));
    }
  }

  /** Panels are hidden in the expanded viewer: switching to one brings them back. */
  function show(tb: Tab) {
    tab = tb;
    expanded = false;
  }

  /** The same when the person asked for that tab: a right panel they had hidden comes back with it. */
  function open(tb: Tab) {
    show(tb);
    if (dock.right.hidden) dock.show('right');
  }

  function drawChange() {
    open('more');
    ideas = { draw: true };
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      menu = false;
      if (!getIt) expanded = false;
      return;
    }
    const el = e.target as HTMLElement | null;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.ctrlKey && /^[1-9]$/.test(e.key) && tabs[Number(e.key) - 1]) {
      e.preventDefault();
      open(tabs[Number(e.key) - 1]);
      return;
    }
    if (e.key.toLowerCase() !== 'f' || e.ctrlKey || e.metaKey || e.altKey || !wide || getIt) return;
    expanded = !expanded;
  }

  async function download3mf() {
    if (!store) return;
    const name = `${(store.detail?.title ?? 'model').replace(/[^\w-]+/g, '_').slice(0, 40)}.3mf`;
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

  function onAction(a: string) {
    if (a === 'slice' || a === 'probe') open('print');
    else if (a === 'download') download3mf();
    else if (a === 'order' || a === 'share') getIt = true;
  }

  function useConcept(url: string) {
    if (!store) return;
    const a = store.assets.find((x) => x.url === url);
    store.send(t('use_this') + (a ? '' : `: ${url}`), a ? [a.id] : []);
    if (!wide) tab = 'chat';
    else if (dock.left.hidden) dock.show('left');
  }

  /** A stroke sculpted in the viewer becomes the next op of the mesh document. */
  function sculpted(op: Record<string, any>) {
    store?.editDoc((d) => {
      const taken = new Set(d.ops.map((o) => o.id));
      let n = d.ops.filter((o) => o.by === 'user').length + 1;
      let id = `${op.brush}_${n}`;
      while (taken.has(id)) id = `${op.brush}_${++n}`;
      d.ops.push({ id, op: 'sculpt', ...op });
    }, true);
  }

  function askFix(text: string) {
    store?.send(text);
    if (!wide) tab = 'chat';
    else if (dock.left.hidden) dock.show('left');
  }
</script>

<svelte:head><title>{store?.detail ? projectTitle(store.detail.title) : t('studio')} · Formwright</title></svelte:head>

<svelte:window onkeydown={onKey} onclick={(e) => menu && menuWrap && !e.composedPath().includes(menuWrap) && (menu = false)} bind:innerWidth={dock.viewport} />

{#snippet projectName()}
  {#if store?.detail}
    {#if store.readonly}<strong class="pname" title={projectTitle(store.detail.title)}>{projectTitle(store.detail.title)}</strong>
    {:else}<input class="pname" value={projectTitle(store.detail.title)} onchange={rename} aria-label={t('name')} />{/if}
  {/if}
{/snippet}

{#snippet chatArea()}
  {#if store}
    <header class="ah">
      <span class="at">{dt('ai_engineer')}</span>
      {#if store.running}<span class="busy"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {activity}</span>{/if}
      <span class="spacer"></span>
      {#if wide}<button class="hb icon" onclick={() => dock.hide('left')} title={dt('collapse')} aria-label={dt('collapse')}><i class="ti ti-layout-sidebar-left-collapse" aria-hidden="true"></i></button>{/if}
    </header>
    <div class="ab chatbody">
      <Conversation {store} {onAction} onUseConcept={useConcept} />
      {#if player}
        <!-- the player's bar says what to do with the run -->
      {:else if store.readonly}
        <!-- in the composer's place for a visitor: whose project this is, and the way to make it one's own -->
        <div class="remix">
          <span><i class="ti ti-lock" aria-hidden="true"></i> {t('forbidden')}</span>
          {#if Object.keys(store.jobs).length}<a class="hb" href="/w/{store.id}"><i class="ti ti-player-play" aria-hidden="true"></i> {t('replay')}</a>{/if}
          <button class="hb primary" onclick={fork}><i class="ti ti-git-fork" aria-hidden="true"></i> {t('fork')}</button>
        </div>
      {:else}<Composer {store} />{/if}
    </div>
  {/if}
{/snippet}

{#snippet editorHeader()}
  {#if store}
    {#if !wide}{@render projectName()}{/if}
    {#if store.version}
      <span class="meta" title={facts}>{facts}</span>
    {/if}
    {#if job}
      <!-- the stage card says it already -->
      {#if !progress}<span class="busy"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {job.kind !== 'design' ? t(`job_${job.kind}`) : job.stage ? t(`stage.${job.stage}`) : t('agent_working')}</span>{/if}
    {:else if store.building}
      <span class="busy"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('building_model')}</span>
    {:else if store.checking}
      <span class="busy"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('refining')}</span>
    {:else if store.checks && !machined}
      <button class="hb verdict {errCount ? 'err' : warnCount ? 'warn' : 'ok'}" onclick={() => open('checks')} title={errCount ? t('checks_err') : warnCount ? t('checks_warn') : t('checks_ok')}>
        <Icon name={errCount ? 'alert' : 'check'} size={13} />
        {errCount ? t('checks_err') : warnCount ? t('checks_warn') : t('checks_ok')}
      </button>
    {/if}
    <span class="spacer"></span>
    <button class="hb" onclick={download3mf} disabled={!store.source}><i class="ti ti-download" aria-hidden="true"></i> 3MF</button>
    {#if !store.readonly && !machined}
      <button class="hb primary" onclick={() => (getIt = true)} disabled={!store.source} title={t('order')} aria-label={t('order')}><i class="ti ti-package" aria-hidden="true"></i>{#if wide} {t('order')}{/if}</button>
    {/if}
  {/if}
{/snippet}

<div class="bw" class:replay={!!player} class:chatting={!wide && tab === 'chat'} style:--replay-h="{player ? barH : 0}px">
  <header class="top">
    <a class="logo" href="/" title="Formwright" aria-label="Formwright"><Logo size={20} /></a>
    {#if wide}{@render projectName()}{/if}
    {#if store?.detail}
      <nav class="wtabs" role="tablist" aria-label={t('studio')}>
        {#each tabs as tb, i (tb)}
          <button role="tab" class="wt" aria-selected={tab === tb} onclick={() => open(tb)} title="{t(tb)} (Ctrl+{i + 1})">
            <!-- a mark only where there is something to say: the agent at work, or the checks found something -->
            {#if (tb === 'chat' && store.running) || (tb === 'pcb' && store.pcb.live)}<i class="ti ti-loader-2 spin sd" aria-hidden="true"></i>
            {:else if tb === 'checks' && (errCount || encErrors)}<span class="sd d-err"></span>
            {:else if tb === 'checks' && warnCount}<span class="sd d-warn"></span>{/if}
            {t(tb)}
          </button>
        {/each}
      </nav>
    {/if}
    <span class="spacer"></span>
    {#if store?.saveError}<button class="saving warnc retrysave" onclick={() => store?.retrySave()} title="{store.saveError} {t('not_saved_d')}">{t('not_saved')}</button>{/if}
    {#if store?.connection === 'retry'}<span class="saving warnc">{t('reconnecting')}</span>{/if}
    {#if store?.detail}
      {#if store.readonly}
        <button class="hb primary" onclick={fork} title={t('forbidden')} aria-label={t('fork')}><i class="ti ti-git-fork" aria-hidden="true"></i>{#if wide} {t('fork')}{/if}</button>
      {:else if wide}
        {#if Object.keys(store.jobs).length && !store.running}
          <a class="hb icon" href="/w/{store.id}" title={t('watch_your_replay')} aria-label={t('watch_your_replay')}><i class="ti ti-player-play" aria-hidden="true"></i></a>
        {/if}
        <button class="hb icon" onclick={() => (getIt = true)} title={t('share')} aria-label={t('share')}><i class="ti ti-share" aria-hidden="true"></i></button>
        <button class="hb icon" onclick={fork} title={t('fork')} aria-label={t('fork')}><i class="ti ti-git-fork" aria-hidden="true"></i></button>
      {:else}
        <div class="menu" bind:this={menuWrap}>
          <button class="hb icon" onclick={() => (menu = !menu)} aria-haspopup="menu" aria-expanded={menu} aria-label="{t('share')} · {t('fork')}" title="{t('share')} · {t('fork')}">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" /></svg>
          </button>
          {#if menu}
            <div class="pop" role="menu">
              {#if Object.keys(store.jobs).length && !store.running}
                <a role="menuitem" href="/w/{store.id}"><Icon name="play" size={16} /> {t('replay')}</a>
              {/if}
              <button role="menuitem" onclick={() => ((menu = false), (getIt = true))}><Icon name="share" size={16} /> {t('share')}</button>
              <button role="menuitem" onclick={fork}><Icon name="gitfork" size={16} /> {t('fork')}</button>
              <button role="menuitem" onclick={() => ((menu = false), (i18n.lang = i18n.lang === 'ru' ? 'en' : 'ru'))}><span class="lang">{i18n.lang.toUpperCase()}</span> Language</button>
            </div>
          {/if}
        </div>
      {/if}
    {/if}
    {#if wide || !store?.detail || store.readonly}
      <button class="hb icon" onclick={() => (i18n.lang = i18n.lang === 'ru' ? 'en' : 'ru')} title="Language" aria-label="Language"><span class="lang">{i18n.lang.toUpperCase()}</span></button>
    {/if}
  </header>

  {#if store?.loadError}
    <!-- a private project the visitor cannot read: nothing to remix, so no remix offer either -->
    <div class="center" role="alert">
      <p class="err">{isText(store.loadError, 'forbidden') ? t('private_project') : store.loadError}</p>
      {#if store.loadRetrying}<p class="xs muted">{t('load_retrying')}</p><button class="hb primary" onclick={() => store?.retryLoad()}>{t('retry')}</button>{/if}
      <a class="hb" href="/">{t('back')}</a>
    </div>
  {:else if !store?.detail}
    <div class="center"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></div>
  {:else}
    <div
      class="screen"
      class:wide
      class:expanded={wide && expanded}
      class:no-left={dock.left.hidden}
      class:no-right={dock.right.hidden}
      style:--dock-l="{dock.width('left')}px"
      style:--dock-r="{dock.width('right')}px"
    >
      {#if wide}
        <section class="area chat" class:gone={dock.left.hidden}>{@render chatArea()}</section>
        {#if !expanded}<Sash {dock} side="left" label={dt('ai_engineer')} pulse={store.running} />{/if}
      {/if}

      <section class="area editor" class:tight={wide && dock.viewport - dock.width('left') - dock.width('right') < 760}>
        <header class="ah">{@render editorHeader()}</header>
        <div class="ab canvas stage">
          <Viewer
            bind:this={viewer}
            loading={!!store.source && !store.build && !progress}
            build={store.build}
            {machined}
            issues={shownIssues}
            highlight={selectedIssue}
            values={store.values}
            specs={store.build?.paramSpecs ?? {}}
            {photo}
            onParam={(n, v, c) => store!.setParam(n, v, c)}
            sculptable={!!store.meshDoc && !store.running}
            symmetry={store.meshDoc?.symmetry ?? null}
            canUndo={store.undoStack.length > 0}
            onSculpt={sculpted}
            onSymmetry={() => store!.editDoc((d) => (d.symmetry = d.symmetry ? null : 'x'), true)}
            onUndo={() => store!.undoEdit()}
            onDraw={store.readonly || store.replaying ? undefined : drawChange}
            {enclosure}
            board={store.board}
            {layout}
            onLayout={(l) => store!.setAssembled(l === 'assembled')}
            focusPart={encFocus}
            boardGlb={store.caseBoardGlb}
            checking={store.enclosureChecking}
          />
          {#if tab === 'pcb'}<PcbPanel {store} part="stage" />{/if}
          {#if scan && tab !== 'pcb'}
            {#if scanFolded[scan.id] ?? !wide}
              <button class="scanchip pill" onclick={() => (scanFolded[scan.id] = false)} title={t('scan_open')}><Icon name="scan" size={13} /> {t('scan_title')}</button>
            {:else}
              <div class="scanpip card">
                <button class="scanimg" onclick={() => (scanOpen = true)} aria-label={t('scan_open')} title={t('scan_open')}>
                  <SnapHighlight src={scan.url} width={scan.w} height={scan.h} fit="cover" focus={scan.box} boxes={scan.boxes} compact />
                </button>
                <div class="scancap xs">
                  <strong>{scan.marking ? t('scan_read', { m: scan.marking }) : (scan.name ?? t('scan_title'))}</strong>
                  {#if scan.scale}<span class="muted">{scan.scale}</span>{/if}
                </div>
                <button class="scanx" onclick={() => (scanFolded[scan.id] = true)} aria-label={t('close')} title={t('close')}><Icon name="minus" size={14} /></button>
              </div>
            {/if}
          {/if}
          {#if progress}<StageProgress {store} {job} />{/if}
          {#if store.buildError}<div class="builderr mono" role="alert"><strong>{t('model_error')}</strong> {store.buildError}</div>{/if}
        </div>
      </section>

      {#if wide && !expanded}<Sash {dock} side="right" label={dt('properties')} />{/if}

      {#if !wide && tab === 'chat'}
        <section class="area chat">{@render chatArea()}</section>
      {:else}
        <div class="rcol" class:gone={wide && dock.right.hidden}>
          <section class="area props">
            <header class="ah"><span class="at">{dt('properties')}</span></header>
            <div class="ab scroll panels">
              {#if tab === 'model'}
                {#if store.readonly && store.source}<p class="note">{t('readonly_hint')}</p>{/if}
                {#if store.meshDoc}<Panel name="meshops" title={t('mesh_ops')}><MeshOpsPanel {store} /></Panel>{/if}
                <Panel name="partparams" title={dt('part_params')}>
                  <ParamsPanel panel={dt('part_params')} specs={sliderSpecs} values={store.values} agentValues={store.agentValues} building={store.building || (!!store.source && !store.build)} onChange={(n, v, c) => store!.setParam(n, v, c)} />
                </Panel>
              {:else if tab === 'pcb'}
                <Panel name="pcbinfo" title={dt('panel_pcb')}>
                  <PcbPanel {store} part="side" onSend={store.readonly || store.replaying ? undefined : askFix} />
                </Panel>
              {:else if tab === 'checks'}
                <Panel name="partchecks" title={t('checks')}>
                  {#snippet right()}
                    {#if errCount || encErrors}<span class="badge err">{errCount + encErrors}</span>{/if}
                    {#if warnCount}<span class="badge">{warnCount}</span>{/if}
                  {/snippet}
                  <ChecksPanel
                    checks={store.checks}
                    selected={selectedIssue}
                    onSelect={(i) => (selectedIssue = i)}
                    building={store.building}
                    onAskFix={store.readonly ? undefined : askFix}
                    {example}
                    enclosure={store.enclosure?.check ?? null}
                    enclosureStale={!!store.enclosure && !store.enclosureFresh}
                    board={store.board}
                    focusPart={encFocus}
                    onFocusPart={(p) => {
                      encFocus = p;
                      // the rays are drawn around the board in the closed case
                      if (p && store?.hasLayout && !store.assembled) store.setAssembled(true);
                    }}
                    onRecheck={store.readonly || store.replaying ? undefined : () => askFix(t('enc_recheck_msg'))}
                    assembled={!!layout && layout === 'assembled'}
                    enclosureChecking={store.enclosureChecking}
                  />
                </Panel>
              {:else if tab === 'print'}
                <Panel name="partprint" title={t('print')}>
                  <PrintPanel {store} />
                </Panel>
                {#if !wide}<Panel name="partgetit" title={t('get_it')}><GetItPanel {store} readonly={store.readonly} /></Panel>{/if}
              {:else if tab === 'more'}
                <Panel name="partmore" title={t('more')}>
                  <MorePanel {store} snapshot={() => viewer?.snapshot() ?? null} onUseConcept={useConcept} onPhotoAR={(a) => (arAsset = a)} focus={ideas} onFocused={() => (ideas = null)} />
                </Panel>
              {/if}
            </div>
          </section>
        </div>
      {/if}
    </div>
    {#if player}
      <div class="replaybar" bind:clientHeight={barH}><ReplayBar {player} onFork={fork} exit="/p/{store.id}" /></div>
    {/if}
  {/if}
</div>

<!-- a photo taken through the phone capture link is in the composer tray now -->
<div class="toasts" aria-live="polite">
  {#if store?.phoneToast}
    {@const a = store.phoneToast}
    <div class="toast card">
      <img src={a.thumb_url ?? a.url} alt="" />
      <span><Icon name="phone" size={14} /> {t('phone_added')}</span>
      {#if !wide && tab !== 'chat'}<button class="btn small ghost" onclick={() => ((tab = 'chat'), store && (store.phoneToast = null))}>{t('chat')}</button>{/if}
    </div>
  {/if}
</div>

{#if getIt && store}
  <Modal title={t('get_it')} onClose={() => (getIt = false)}>
    <GetItPanel {store} readonly={store.readonly} />
  </Modal>
{/if}

{#if scanOpen && scan}
  <Modal title={t('scan_title')} onClose={() => (scanOpen = false)} wide>
    <div class="scanbig" style:aspect-ratio="{scan.w} / {scan.h}">
      <SnapHighlight src={scan.url} width={scan.w} height={scan.h} fit="contain" focus={scan.box} boxes={scan.boxes} />
    </div>
    <div class="scanfacts">
      {#if scan.marking}<span class="chip accent">{t('scan_read', { m: scan.marking })}</span>{/if}
      {#if scan.name}<span class="chip">{t('scan_found', { name: scan.name })}</span>{/if}
      {#if scan.scale}<span class="chip ok">{scan.scale}</span>{/if}
      {#if scan.boxes.length}<span class="chip">{t('scan_boxes', { n: scan.boxes.length })}</span>{/if}
      {#if scan.deltas}<span class="chip warn">{t('scan_deltas', { n: scan.deltas })}</span>{/if}
    </div>
  </Modal>
{/if}

<style>
  /* 'f': the whole width to the model (demo shots) */
  .screen.wide.expanded {
    grid-template-columns: minmax(0, 1fr);
    padding-inline: 4px;
  }
  .screen.wide.expanded .editor {
    grid-column: 1;
  }
  .screen.expanded .chat,
  .screen.expanded .rcol {
    display: none;
  }
  .rcol {
    display: grid;
    grid-template-rows: minmax(0, 1fr);
    min-height: 0;
  }
  .spacer {
    flex: 1;
  }
  .meta {
    flex: 0 1 auto;
    min-width: 0;
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
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--primary);
    font-size: var(--text-sm);
    white-space: nowrap;
  }
  .retrysave {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    color: var(--warn-text);
  }
  .saving {
    display: inline-flex;
    gap: 5px;
    align-items: center;
    font-size: var(--text-sm);
    color: var(--on-surface-var);
  }
  .warnc {
    color: var(--warn-text);
  }
  .center {
    display: grid;
    place-items: center;
    align-content: center;
    gap: 10px;
  }
  .err {
    color: var(--error);
  }
  .note {
    margin: 0;
    padding: 2px 4px;
    font-size: var(--text-sm);
    line-height: 1.45;
    color: var(--on-surface-var);
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
  /* an editor narrowed by its side panels: its buttons down to their icons, so the last of them stays on screen */
  .editor.tight .ah .hb:not(.primary, .icon) {
    font-size: 0;
    gap: 2px;
    padding: 0 7px;
  }
  /* the case check's verdict, in the editor's header */
  .verdict.ok {
    color: var(--primary);
  }
  .verdict.warn {
    color: var(--warn-text);
  }
  .verdict.err {
    color: var(--error);
  }
  /* a panel's body is a grid: a wide table or row inside scrolls in its place instead of pushing the column out */
  .panels :global(.bp .body > *) {
    min-width: 0;
  }
  .menu {
    position: relative;
  }
  .pop {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    z-index: 40;
    min-width: 180px;
    display: flex;
    flex-direction: column;
    padding: 6px;
    border-radius: var(--radius-card);
    border: var(--border-width) solid var(--outline-variant);
    background: var(--surface-container);
    box-shadow: var(--shadow-pop);
  }
  .pop button,
  .pop a {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 44px;
    padding: 0 12px;
    border: none;
    border-radius: var(--radius-btn);
    background: none;
    font: inherit;
    color: var(--on-surface);
    text-align: left;
    text-decoration: none;
    cursor: pointer;
  }
  .pop button:hover,
  .pop a:hover {
    background: var(--surface-high);
  }
  .stage {
    overflow: hidden;
    display: flex;
  }
  .builderr {
    position: absolute;
    bottom: 60px;
    left: var(--space-3);
    right: var(--space-3);
    background: color-mix(in srgb, var(--error) 12%, var(--surface-container));
    border: var(--border-width) solid color-mix(in srgb, var(--error) 40%, transparent);
    color: var(--error);
    border-radius: var(--radius-card);
    padding: 10px 14px;
    font-size: var(--text-sm);
    max-height: 30%;
    overflow: auto;
    white-space: pre-wrap;
    z-index: 2;
  }
  /* under the top bar, over the middle of the stage: clear of the viewer's toolbar and the composer */
  .toasts {
    position: fixed;
    left: 0;
    right: 0;
    top: 50px;
    z-index: 50;
    display: flex;
    justify-content: center;
    padding: 0 var(--space-4);
    pointer-events: none;
  }
  .toast {
    pointer-events: auto;
    max-width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: 6px 8px 6px 6px;
    border-radius: var(--radius-field);
    box-shadow: var(--shadow-pop);
    font-size: var(--text-base);
    font-weight: var(--font-weight-semibold);
    animation: toast-in var(--dur-base) var(--ease-settle);
  }
  .toast img {
    flex: none;
    width: 40px;
    height: 40px;
    border-radius: var(--radius-btn);
    object-fit: cover;
  }
  .toast span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .toast span :global(.icon) {
    color: var(--primary);
  }
  @keyframes toast-in {
    from {
      transform: translateY(-12px);
      opacity: 0;
    }
  }
  /* a board scan in the stage's corner; opens large */
  .scanpip,
  .scanchip {
    position: absolute;
    z-index: 2;
    top: var(--space-3);
    right: var(--space-3);
  }
  .scanpip {
    width: 176px;
    padding: 0;
    overflow: hidden;
    box-shadow: var(--shadow-pop);
    animation: toast-in var(--dur-base) var(--ease-settle);
  }
  .scanchip {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    font: inherit;
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-tag);
    background: color-mix(in srgb, var(--surface-container) 88%, transparent);
    backdrop-filter: blur(6px);
    color: var(--on-surface-var);
    cursor: pointer;
  }
  .scanimg {
    display: block;
    width: 100%;
    aspect-ratio: 16 / 10;
    padding: 0;
    border: none;
    background: #000;
    cursor: zoom-in;
  }
  .scancap {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px 10px 8px;
    min-width: 0;
  }
  .scancap strong {
    font-weight: var(--font-weight-semibold);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .scanx {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 26px;
    height: 26px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    border: none;
    color: #fff;
    background: rgb(20 20 18 / 0.55);
    cursor: pointer;
  }
  .scanbig {
    width: 100%;
    max-height: 70dvh;
    border-radius: var(--radius-field);
    overflow: hidden;
    background: #000;
  }
  .scanfacts {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: var(--space-3);
  }
  @media (max-width: 979px) {
    .rcol {
      grid-template-rows: auto;
    }
    /* the title has come down from the top bar: it gives the rest of the header some room */
    .editor .ah .pname {
      width: 130px;
    }
    /* the verdict and the work in progress down to their marks: the tabs and the stage say the rest */
    .editor .ah .verdict {
      font-size: 0;
      gap: 0;
      padding: 0 10px;
    }
    .editor .ah .busy {
      flex: none;
      font-size: 0;
    }
    .editor .ah .busy i {
      font-size: var(--text-base);
    }
    /* a short tab leaves its room under the panels, not between them */
    .screen {
      align-content: start;
    }
    .toasts {
      top: 58px;
    }
    /* the chat tab: one screen tall, the model above and the conversation scrolling under it */
    .bw.chatting {
      height: calc(100dvh - var(--replay-h, 0px));
      min-height: 0;
      overflow: hidden;
      grid-template-rows: 50px minmax(0, 1fr);
      padding-bottom: 0;
    }
    .bw.chatting .screen {
      grid-template-rows: min(30dvh, 260px) minmax(0, 1fr);
    }
    .bw.chatting .editor {
      height: auto;
    }
    .chat :global(.composer) {
      padding-bottom: calc(var(--space-3) + env(safe-area-inset-bottom, 0px));
    }
    .scanpip {
      width: 124px;
    }
    .scancap span {
      display: none;
    }
  }
</style>
