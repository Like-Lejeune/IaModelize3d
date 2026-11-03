<script lang="ts">
  import { page } from '$app/state';
  import { goto, replaceState } from '$app/navigation';
  import { onDestroy, setContext, untrack } from 'svelte';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Viewer from '$lib/components/Viewer.svelte';
  import StageProgress from '$lib/components/StageProgress.svelte';
  import Conversation from '$lib/components/Conversation.svelte';
  import Composer from '$lib/components/Composer.svelte';
  import ParamsPanel from '$lib/components/ParamsPanel.svelte';
  import MeshOpsPanel from '$lib/components/MeshOpsPanel.svelte';
  import ChecksPanel from '$lib/components/ChecksPanel.svelte';
  import PrintPanel from '$lib/components/PrintPanel.svelte';
  import GetItPanel from '$lib/components/GetItPanel.svelte';
  import MorePanel from '$lib/components/MorePanel.svelte';
  import PcbPanel from '$lib/components/PcbPanel.svelte';
  import SnapHighlight from '$lib/components/SnapHighlight.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { ProjectStore } from '$lib/project.svelte';
  import { stashFirst, takeFirst } from '$lib/pending';
  import { api, download, errorText } from '$lib/api';
  import { t, isText, projectTitle, unitLabel } from '$lib/i18n.svelte';
  import type { AssetOut, Calibration, Issue, ScanBox } from '$lib/types';
  import type { Box } from '$lib/snapframe';

  type Tab = 'chat' | 'model' | 'pcb' | 'checks' | 'print' | 'more';
  const TAB_ICON: Record<Tab, string> = { chat: 'message', model: 'cube', pcb: 'cpu', checks: 'check-circle', print: 'printer', more: 'grid-dots' };

  let store = $state<ProjectStore | null>(null);
  let tab = $state<Tab>('model');
  let selectedIssue = $state<Issue | null>(null);
  let arAsset = $state<AssetOut | null>(null);
  let viewer = $state<Viewer>();
  let wide = $state(true);
  let getIt = $state(false);
  /** What More → Ideas should do once it opens: sketch concepts for a prompt, or start drawing a change. */
  let ideas = $state<{ prompt?: string; draw?: boolean } | null>(null);
  // phones and tablets: Share and Remix live in an overflow menu
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
    const s = new ProjectStore(id);
    store = s;
    selectedIssue = null;
    arAsset = null;
    getIt = false;
    encFocus = null;
    scanOpen = false;
    const first = takeFirst(id);
    // "Ideas first" from the home page: open the sketches with that text, once (a reload must not start them again)
    const idea = untrack(() => page.url.searchParams.get('ideas'))?.trim();
    s.load().then(() => {
      // a device has its own workspace: its first message goes along
      if (s.detail?.pack === 'device') {
        if (first) stashFirst(id, first.text, first.files);
        goto(`/d/${id}`, { replaceState: true });
        return;
      }
      if (first) s.sendFiles(first.text, first.files);
      // a board project without a 3D model yet: its PCB is the picture
      if (s.detail?.pack === 'pcb' && !s.source && wide) show('pcb');
      if (idea && s.detail) {
        replaceState(location.pathname, {});
        show('more');
        ideas = { prompt: idea };
      }
    });
    return () => s.dispose();
  });

  $effect(() => {
    const mq = matchMedia('(min-width: 1100px)');
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

  const photo = $derived.by(() => {
    if (!store) return null;
    const a = arAsset ?? [...store.assets].reverse().find((x) => x.meta?.calibration?.R);
    const cal = a?.meta?.calibration as Calibration | undefined;
    if (!a || !cal?.R || !cal?.t) return null;
    return { url: a.url, calibration: { ...cal, width: cal.width ?? a.width ?? 1, height: cal.height ?? a.height ?? 1 } };
  });

  // the PCB tab: a board project, or one that has a routed board (or is routing one now)
  const pcbTab = $derived(!!store && (store.detail?.pack === 'pcb' || store.pcb.versions.length > 0 || !!store.pcb.live));
  const tabs = $derived<Tab[]>([...(wide ? [] : ['chat' as Tab]), 'model', ...(pcbTab ? ['pcb' as Tab] : []), 'checks', 'print', 'more']);
  const encErrors = $derived(store?.enclosure?.check.findings?.filter((f) => f.severity === 'error').length ?? 0);
  const errCount = $derived(store?.checks?.issues.filter((i) => i.severity === 'error').length ?? 0);
  const warnCount = $derived(store?.checks?.issues.filter((i) => i.severity === 'warn').length ?? 0);
  // a case's checks measure its parts laid out for printing: closed around its board, the case's own outer box (the
  // board ghost carries it) is the size; otherwise the chip says it is the plate's
  const outer = $derived(store?.assembled ? store.build?.parts?.find((p) => p.meta?.enclosure)?.meta?.enclosure?.outerSize : undefined);
  const size = $derived(outer ?? store?.checks?.stats?.size);
  const plate = $derived(!!store?.hasLayout && !outer);
  const job = $derived(store?.currentJob ?? null);
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

  async function togglePublic() {
    if (!store?.detail) return;
    try {
      const p = await api.patchProject(store.id, { public: !store.detail.public });
      store.detail.public = p.public;
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

  // a visitor can watch someone else's run play back in a copy of their own (free, no model calls)
  let watching = $state(false);
  async function watch() {
    if (!store) return;
    watching = true;
    try {
      const p = await api.replay(store.id, 8);
      goto(`/p/${p.id}`);
    } catch (err) {
      store.addError(errorText(err));
    } finally {
      watching = false;
    }
  }

  /** Panels are hidden in the expanded viewer: switching to one brings them back. */
  function show(tb: Tab) {
    tab = tb;
    expanded = false;
  }

  function drawChange() {
    show('more');
    ideas = { draw: true };
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      menu = false;
      if (!getIt) expanded = false;
      return;
    }
    if (e.key.toLowerCase() !== 'f' || e.ctrlKey || e.metaKey || e.altKey || !wide || getIt) return;
    const el = e.target as HTMLElement | null;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
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
    if (a === 'slice' || a === 'probe') show('print');
    else if (a === 'download') download3mf();
    else if (a === 'order' || a === 'share') getIt = true;
  }

  function useConcept(url: string) {
    if (!store) return;
    const a = store.assets.find((x) => x.url === url);
    store.send(t('use_this') + (a ? '' : `: ${url}`), a ? [a.id] : []);
    if (!wide) tab = 'chat';
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
  }
</script>

<svelte:head><title>{store?.detail ? projectTitle(store.detail.title) : t('studio')} · Formwright</title></svelte:head>

<svelte:window onkeydown={onKey} onclick={(e) => menu && menuWrap && !e.composedPath().includes(menuWrap) && (menu = false)} />

<!-- in the composer's place for a visitor: whose project this is, and the way to make it one's own -->
{#snippet remixOffer()}
  <div class="remix">
    <p class="small"><Icon name="lock" size={14} /> {t('forbidden')}</p>
    <div class="row">
      <button class="btn primary" onclick={fork}><Icon name="gitfork" size={16} /> {t('fork')}</button>
      {#if store && Object.keys(store.jobs).length}
        <button class="btn ghost" onclick={watch} disabled={watching}>
          {#if watching}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="play" size={14} />{/if}
          {t('watch_replay')}
        </button>
      {/if}
    </div>
  </div>
{/snippet}

<div class="page">
  <Header>
    {#if store?.detail && store.readonly}
      <!-- someone else's project: read-only from the start, the remix is the way to change it -->
      <div class="titlebar">
        <strong class="title ro" title={projectTitle(store.detail.title)}>{projectTitle(store.detail.title)}</strong>
        {#if store.version}<span class="chip mono hide-sm">v{store.version}</span>{/if}
        {#if store.connection === 'retry'}<span class="chip warn">{t('reconnecting')}</span>{/if}
        <span class="spacer"></span>
        <!-- on a phone the label gives the title its room: the offer under the chat says it in full -->
        <button class="btn primary small" onclick={fork} title={t('forbidden')} aria-label={t('fork')}><Icon name="gitfork" size={15} /><span class="hide-sm"> {t('fork')}</span></button>
      </div>
    {:else if store?.detail}
      <div class="titlebar">
        <input class="title" value={projectTitle(store.detail.title)} onchange={rename} aria-label={t('name')} />
        {#if store.version}<span class="chip mono hide-sm">v{store.version}</span>{/if}
        {#if store.connection === 'retry'}<span class="chip warn">{t('reconnecting')}</span>{/if}
        <span class="spacer"></span>
        <button class="btn ghost small hide-md" onclick={() => (getIt = true)}><Icon name="share" size={15} /> {t('share')}</button>
        <button class="btn ghost small hide-md" onclick={fork} title={t('fork')}><Icon name="gitfork" size={15} /> {t('fork')}</button>
        <div class="menu show-md" bind:this={menuWrap}>
          <button class="btn icon small ghost" onclick={() => (menu = !menu)} aria-haspopup="menu" aria-expanded={menu} aria-label="{t('share')} · {t('fork')}" title="{t('share')} · {t('fork')}">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" /></svg>
          </button>
          {#if menu}
            <div class="pop" role="menu">
              <button role="menuitem" onclick={() => ((menu = false), (getIt = true))}><Icon name="share" size={16} /> {t('share')}</button>
              <button role="menuitem" onclick={fork}><Icon name="gitfork" size={16} /> {t('fork')}</button>
            </div>
          {/if}
        </div>
      </div>
    {/if}
  </Header>

  {#if store?.loadError}
    <!-- a private project the visitor cannot read: nothing to remix, so no remix offer either -->
    <div class="center"><p class="err">{isText(store.loadError, 'forbidden') ? t('private_project') : store.loadError}</p><a class="btn" href="/">{t('back')}</a></div>
  {:else if !store?.detail}
    <div class="center"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></div>
  {:else}
    <main class="studio" class:wide class:expanded={wide && expanded} class:chatting={!wide && tab === 'chat'}>
      {#if wide}
        <aside class="left card">
          <Conversation {store} {onAction} onUseConcept={useConcept} />
          {#if store.readonly}{@render remixOffer()}{:else}<Composer {store} />{/if}
        </aside>
      {/if}

      <section class="center-col">
        <div class="stage card">
          <Viewer
            bind:this={viewer}
            loading={!!store.source && !store.build && !progress}
            build={store.build}
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
          <div class="overlay tl">
            {#if job}
              <!-- the stage card says it already -->
              {#if !progress}<span class="pill work"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {job.kind !== 'design' ? t(`job_${job.kind}`) : job.stage ? t(`stage.${job.stage}`) : t('agent_working')}</span>{/if}
            {:else if store.building}
              <span class="pill"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('building_model')}</span>
            {:else if store.checking}
              <span class="pill"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('refining')}</span>
            {:else if store.checks}
              <button class="pill {errCount ? 'err' : warnCount ? 'warn' : 'ok'}" onclick={() => show('checks')}>
                <Icon name={errCount ? 'alert' : 'check'} size={13} />
                {errCount ? t('checks_err') : warnCount ? t('checks_warn') : t('checks_ok')}
              </button>
            {/if}
          </div>
          {#if size}<div class="overlay tr mono">{plate ? `${t('size_plate')} ` : ''}{size.map((v) => +v.toFixed(1)).join(' × ')} {unitLabel('mm')}</div>{/if}
          {#if store.buildError}<div class="builderr mono" role="alert"><strong>{t('model_error')}</strong> {store.buildError}</div>{/if}
        </div>
      </section>

      <aside class="right card">
        <div class="tabs" class:many={wide && tabs.length > 4}>
          <div class="seg" role="tablist">
            {#each tabs as tb (tb)}
              <button role="tab" aria-selected={tab === tb} onclick={() => (tab = tb)}>
                <span class="ticon" aria-hidden="true"><Icon name={TAB_ICON[tb]} size={18} /></span>
                <span class="tlabel">{t(tb)}</span>
                <!-- printability errors and the case's errors against its board -->
                {#if tb === 'checks' && (errCount || encErrors || warnCount)}<span class="n {errCount || encErrors ? 'err' : 'warn'}">{errCount + encErrors || warnCount}</span>{/if}
                {#if tb === 'chat' && store.running}<span class="live" aria-label={t('agent_working')}></span>{/if}
              </button>
            {/each}
          </div>
        </div>
        <div class="tabbody" class:chat={tab === 'chat'}>
          {#if tab === 'chat'}
            <Conversation {store} {onAction} onUseConcept={useConcept} />
            {#if store.readonly}{@render remixOffer()}{:else}<Composer {store} />{/if}
          {:else if tab === 'model'}
            {#if store.readonly && store.source}<p class="muted small ro-hint">{t('readonly_hint')}</p>{/if}
            {#if store.meshDoc}<MeshOpsPanel {store} />{/if}
            <ParamsPanel specs={sliderSpecs} values={store.values} agentValues={store.agentValues} building={store.building || (!!store.source && !store.build)} onChange={(n, v, c) => store!.setParam(n, v, c)} />
          {:else if tab === 'pcb'}
            <PcbPanel {store} part="side" onSend={store.readonly || store.replaying ? undefined : askFix} />
          {:else if tab === 'checks'}
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
          {:else if tab === 'print'}
            <PrintPanel {store} />
            {#if !wide}<div class="getit-inline"><GetItPanel {store} readonly={store.readonly} onPublish={togglePublic} /></div>{/if}
          {:else if tab === 'more'}
            <MorePanel {store} snapshot={() => viewer?.snapshot() ?? null} onUseConcept={useConcept} onPhotoAR={(a) => (arAsset = a)} focus={ideas} onFocused={() => (ideas = null)} />
          {/if}
        </div>
        {#if wide && tab !== 'chat'}
          <div class="getbar">
            <button class="btn primary" onclick={download3mf} disabled={!store.source}><Icon name="download" size={16} /> {t('download_3mf')}</button>
            {#if store.readonly}
              <button class="btn" onclick={fork}><Icon name="gitfork" size={16} /> {t('fork')}</button>
            {:else}
              <button class="btn" onclick={() => (getIt = true)} disabled={!store.source}><Icon name="package" size={16} /> {t('order')}</button>
            {/if}
          </div>
        {/if}
      </aside>
    </main>
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
    <GetItPanel {store} readonly={store.readonly} onPublish={togglePublic} />
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
  .page {
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
  }
  .titlebar {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .title {
    background: transparent;
    border-color: transparent;
    font-weight: var(--font-weight-semibold);
    min-width: 60px;
    flex: 0 1 340px;
    height: 42px;
    padding: 0 12px;
    font-size: var(--text-product-lead);
    text-overflow: ellipsis;
  }
  .title:hover {
    border-color: var(--outline-variant);
  }
  .title:focus {
    background: var(--surface-container);
  }
  /* a visitor's title: the same place and size, not editable */
  .title.ro {
    display: block;
    line-height: 40px;
    border: var(--border-width) solid transparent;
    overflow: hidden;
    white-space: nowrap;
  }
  .title.ro:hover {
    border-color: transparent;
  }
  .remix {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    padding-bottom: calc(var(--space-3) + env(safe-area-inset-bottom, 0px));
    border-top: var(--border-width) solid var(--divider);
    background: var(--surface-container);
  }
  .remix p {
    margin: 0;
    color: var(--on-surface-var);
  }
  .remix p :global(.icon) {
    vertical-align: -2px;
  }
  .remix .row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  /* side by side when they fit, else one full-width row each */
  .remix .row .btn {
    flex: 1 1 auto;
  }
  .ro-hint {
    margin: 0 0 var(--space-3);
  }
  .center {
    flex: 1;
    display: grid;
    place-items: center;
    gap: 12px;
    padding: 40px 16px;
    text-align: center;
  }
  .err {
    color: var(--error);
  }
  .studio {
    flex: 1;
    display: grid;
    gap: var(--space-3);
    padding: var(--space-3);
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: min(46dvh, 460px) auto;
  }
  .studio.wide {
    /* the side panels give way on a laptop screen, so the model keeps most of the width */
    grid-template-columns: clamp(300px, 24vw, 390px) minmax(0, 1fr) clamp(300px, 22vw, 360px);
    grid-template-rows: minmax(0, 1fr);
    /* a fixed height, not flex: a growing chat must scroll inside its panel, not stretch the page */
    flex: none;
    height: calc(100dvh - var(--header-h, 67px));
  }
  .studio.wide.expanded {
    grid-template-columns: minmax(0, 1fr);
  }
  .studio.expanded .left,
  .studio.expanded .right {
    display: none;
  }
  /* narrow screens, chat tab: one screen tall, the model above and the conversation scrolling under it */
  .studio.chatting {
    flex: none;
    height: calc(100dvh - var(--header-h, 67px));
    grid-template-rows: min(30dvh, 280px) minmax(0, 1fr);
  }
  .studio.chatting .right {
    overflow: hidden;
  }
  /* the page does not scroll here, and a clipping panel would offset sticky tabs by the header height */
  .studio.chatting .tabs {
    position: static;
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
  .pop button {
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
    cursor: pointer;
  }
  .pop button:hover {
    background: var(--surface-high);
  }
  .show-md,
  .ticon {
    display: none;
  }
  .left,
  .right {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }
  .center-col {
    position: relative;
    min-height: 0;
    min-width: 0;
    display: flex;
  }
  .stage {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    display: flex;
  }
  .overlay {
    position: absolute;
    z-index: 2;
    pointer-events: none;
  }
  .overlay > * {
    pointer-events: auto;
  }
  .overlay.tl {
    top: var(--space-3);
    left: var(--space-3);
  }
  .overlay.tr {
    top: var(--space-3);
    right: var(--space-3);
    font-size: var(--text-card-meta);
    font-weight: var(--font-weight-semibold);
    background: color-mix(in srgb, var(--surface-container) 88%, transparent);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-tag);
    padding: 4px 10px;
    backdrop-filter: blur(6px);
  }
  /* status pill over the 3D view */
  .pill {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    font-family: inherit;
    font-size: var(--text-card-meta);
    font-weight: var(--font-weight-semibold);
    padding: 4px 10px;
    border-radius: var(--radius-tag);
    border: var(--border-width) solid var(--outline-variant);
    background: color-mix(in srgb, var(--surface-container) 88%, transparent);
    backdrop-filter: blur(6px);
    color: var(--on-surface-var);
  }
  button.pill {
    cursor: pointer;
  }
  .pill.ok {
    background: color-mix(in srgb, var(--primary-container) 88%, transparent);
    border-color: transparent;
    color: var(--primary);
  }
  .pill.warn {
    background: color-mix(in srgb, var(--warn) 22%, var(--surface-container));
    border-color: transparent;
    color: var(--warn-text);
  }
  .pill.err {
    background: color-mix(in srgb, var(--error) 20%, var(--surface-container));
    border-color: transparent;
    color: var(--error);
  }
  .pill.work {
    color: var(--primary);
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
    font-size: 12px;
    max-height: 30%;
    overflow: auto;
    white-space: pre-wrap;
    z-index: 2;
  }
  .tabs {
    padding: var(--space-3);
    border-bottom: var(--border-width) solid var(--divider);
    flex: none;
  }
  /* the tabs share the width; tight padding keeps all four in the narrowest right column */
  .tabs .seg button {
    padding-inline: 8px;
  }
  /* five tabs (a board's PCB tab too) in the narrowest right column */
  .tabs.many .seg button {
    padding-inline: 3px;
    font-size: 12px;
  }
  .n {
    font-size: 10px;
    font-weight: var(--font-weight-semibold);
    min-width: 18px;
    height: 18px;
    border-radius: var(--radius-tag);
    display: inline-grid;
    place-items: center;
    padding: 0 5px;
  }
  .n.err {
    background: var(--error);
    color: var(--surface);
  }
  .n.warn {
    background: var(--warn);
    color: #241a05;
  }
  .live {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--primary);
    animation: fw-blink 1s ease-in-out infinite alternate;
  }
  @keyframes fw-blink {
    to {
      opacity: 0.3;
    }
  }
  .tabbody {
    padding: var(--space-4);
    overflow-y: auto;
    flex: 1;
    min-height: 0;
  }
  /* a definite height from the chatting grid: the log scrolls inside and follows new output */
  .tabbody.chat {
    padding: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .tabbody.chat :global(.composer) {
    padding-bottom: calc(var(--space-3) + env(safe-area-inset-bottom, 0px));
  }
  .getbar {
    display: flex;
    gap: var(--space-2);
    padding: var(--space-3);
    border-top: var(--border-width) solid var(--divider);
    background: var(--surface-container);
  }
  /* both fit the narrowest right column (300 px) */
  .getbar .btn {
    flex: 1;
    padding-inline: 8px;
  }
  /* under the header, over the middle of the stage: clear of the viewer's toolbar and the composer */
  .toasts {
    position: fixed;
    left: 0;
    right: 0;
    top: calc(var(--header-h, 67px) + var(--space-3));
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
    font-size: var(--text-product-spec);
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
    top: calc(var(--space-3) + 38px);
    right: var(--space-3);
  }
  .scanpip {
    width: 176px;
    padding: 0;
    overflow: hidden;
    box-shadow: var(--shadow-pop);
    animation: toast-in var(--dur-base) var(--ease-settle);
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
  .getit-inline {
    margin-top: var(--space-5);
    padding-top: var(--space-4);
    border-top: var(--border-width) solid var(--divider);
  }
  @media (max-width: 1099px) {
    /* the header has room for labelled Share and Remix only next to the three-column studio */
    .hide-md {
      display: none;
    }
    .show-md {
      display: block;
    }
    .right {
      overflow: visible;
    }
    .tabbody {
      overflow: visible;
    }
    .tabs {
      position: sticky;
      top: var(--header-h, 67px);
      z-index: 5;
      background: var(--surface-container);
      border-radius: var(--radius-card) var(--radius-card) 0 0;
    }
  }
  @media (max-width: 640px) {
    .hide-sm {
      display: none;
    }
    .title {
      padding: 0 6px;
    }
    /* the status pill goes under the size readout instead of running into it */
    .overlay.tl {
      top: calc(var(--space-3) + 34px);
    }
    .studio {
      padding: var(--space-2);
      gap: var(--space-2);
      grid-template-rows: min(44dvh, 380px) auto;
    }
    .studio.chatting {
      grid-template-rows: min(30dvh, 260px) minmax(0, 1fr);
    }
    .tabbody {
      padding: var(--space-3);
    }
    /* five tabs in 343 px: an icon over a short label, the counters on the icon */
    .tabs {
      padding: var(--space-2);
    }
    .tabs .seg button {
      position: relative;
      flex-direction: column;
      gap: 1px;
      min-width: 0;
      padding: 5px 2px;
      font-size: 11px;
    }
    .ticon {
      display: inline-flex;
    }
    .tlabel {
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .tabs .n {
      position: absolute;
      top: 3px;
      left: calc(50% + 6px);
      min-width: 16px;
      height: 16px;
    }
    .tabs .live {
      position: absolute;
      top: 6px;
      left: calc(50% + 11px);
    }
    .scanpip {
      width: 124px;
    }
    .scancap span {
      display: none;
    }
  }
</style>
