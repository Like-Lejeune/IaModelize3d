<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { onDestroy } from 'svelte';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Viewer from '$lib/components/Viewer.svelte';
  import Conversation from '$lib/components/Conversation.svelte';
  import Composer from '$lib/components/Composer.svelte';
  import ParamsPanel from '$lib/components/ParamsPanel.svelte';
  import MeshOpsPanel from '$lib/components/MeshOpsPanel.svelte';
  import ChecksPanel from '$lib/components/ChecksPanel.svelte';
  import PrintPanel from '$lib/components/PrintPanel.svelte';
  import GetItPanel from '$lib/components/GetItPanel.svelte';
  import MorePanel from '$lib/components/MorePanel.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { ProjectStore } from '$lib/project.svelte';
  import { takeFirst } from '$lib/pending';
  import { api, download, errorText } from '$lib/api';
  import { t, projectTitle, unitLabel } from '$lib/i18n.svelte';
  import type { AssetOut, Calibration, Issue } from '$lib/types';

  type Tab = 'chat' | 'model' | 'checks' | 'print' | 'more';

  let store = $state<ProjectStore | null>(null);
  let tab = $state<Tab>('model');
  let selectedIssue = $state<Issue | null>(null);
  let arAsset = $state<AssetOut | null>(null);
  let viewer = $state<Viewer>();
  let wide = $state(true);
  let getIt = $state(false);

  $effect(() => {
    const id = page.params.id!;
    const s = new ProjectStore(id);
    store = s;
    const first = takeFirst(id);
    s.load().then(() => first && s.sendFiles(first.text, first.files));
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

  const tabs = $derived<Tab[]>(wide ? ['model', 'checks', 'print', 'more'] : ['chat', 'model', 'checks', 'print', 'more']);
  const errCount = $derived(store?.checks?.issues.filter((i) => i.severity === 'error').length ?? 0);
  const warnCount = $derived(store?.checks?.issues.filter((i) => i.severity === 'warn').length ?? 0);
  const size = $derived(store?.checks?.stats?.size);
  const job = $derived(store?.currentJob ?? null);

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
    const p = await api.fork(store.id);
    goto(`/p/${p.id}`);
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
    if (a === 'slice' || a === 'probe') tab = 'print';
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

<svelte:head><title>{store?.detail ? projectTitle(store.detail.title) : 'Studio'} · Formwright</title></svelte:head>

<div class="page">
  <Header>
    {#if store?.detail}
      <div class="titlebar">
        <input class="title" value={projectTitle(store.detail.title)} onchange={rename} aria-label={t('name')} />
        {#if store.version}<span class="chip mono">v{store.version}</span>{/if}
        {#if store.connection === 'retry'}<span class="chip warn">{t('reconnecting')}</span>{/if}
        <span class="spacer"></span>
        <button class="btn ghost small hide-sm" onclick={() => (getIt = true)}><Icon name="share" size={15} /> {t('share')}</button>
        <button class="btn ghost small hide-sm" onclick={fork} title={t('fork')}><Icon name="gitfork" size={15} /> {t('fork')}</button>
      </div>
    {/if}
  </Header>

  {#if store?.loadError}
    <div class="center"><p class="err">{t('error')}: {store.loadError}</p><a class="btn" href="/">{t('back')}</a></div>
  {:else if !store?.detail}
    <div class="center"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></div>
  {:else}
    <main class="studio" class:wide>
      {#if wide}
        <aside class="left card">
          <Conversation {store} {onAction} onUseConcept={useConcept} />
          <Composer {store} />
        </aside>
      {/if}

      <section class="center-col">
        <div class="stage card">
          <Viewer
            bind:this={viewer}
            loading={!!store.source && !store.build}
            build={store.build}
            issues={store.checks?.issues ?? []}
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
          />
          <div class="overlay tl">
            {#if job}
              <span class="pill work"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {job.kind !== 'design' ? t(`job_${job.kind}`) : job.stage ? t(`stage.${job.stage}`) : t('agent_working')}</span>
            {:else if store.building}
              <span class="pill"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('building_model')}</span>
            {:else if store.checking}
              <span class="pill"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('refining')}</span>
            {:else if store.checks}
              <button class="pill {errCount ? 'err' : warnCount ? 'warn' : 'ok'}" onclick={() => (tab = 'checks')}>
                <Icon name={errCount ? 'alert' : 'check'} size={13} />
                {errCount ? t('checks_err') : warnCount ? t('checks_warn') : t('checks_ok')}
              </button>
            {/if}
          </div>
          {#if size}<div class="overlay tr mono">{size.map((v) => +v.toFixed(1)).join(' × ')} {unitLabel('mm')}</div>{/if}
          {#if store.buildError}<div class="builderr mono" role="alert"><strong>{t('model_error')}</strong> {store.buildError}</div>{/if}
        </div>
      </section>

      <aside class="right card">
        <div class="tabs">
          <div class="seg" role="tablist">
            {#each tabs as tb (tb)}
              <button role="tab" aria-selected={tab === tb} onclick={() => (tab = tb)}>
                {t(tb)}
                {#if tb === 'checks' && (errCount || warnCount)}<span class="n {errCount ? 'err' : 'warn'}">{errCount || warnCount}</span>{/if}
                {#if tb === 'chat' && store.running}<span class="live" aria-label={t('agent_working')}></span>{/if}
              </button>
            {/each}
          </div>
        </div>
        <div class="tabbody" class:chat={tab === 'chat'}>
          {#if tab === 'chat'}
            <Conversation {store} {onAction} onUseConcept={useConcept} />
            <Composer {store} />
          {:else if tab === 'model'}
            {#if store.meshDoc}<MeshOpsPanel {store} />{/if}
            <ParamsPanel specs={store.build?.paramSpecs ?? {}} values={store.values} agentValues={store.agentValues} building={store.building || (!!store.source && !store.build)} onChange={(n, v, c) => store!.setParam(n, v, c)} />
          {:else if tab === 'checks'}
            <ChecksPanel checks={store.checks} selected={selectedIssue} onSelect={(i) => (selectedIssue = i)} building={store.building} onAskFix={askFix} />
          {:else if tab === 'print'}
            <PrintPanel {store} />
            {#if !wide}<div class="getit-inline"><GetItPanel {store} onPublish={togglePublic} /></div>{/if}
          {:else if tab === 'more'}
            <MorePanel {store} snapshot={() => viewer?.snapshot() ?? null} onUseConcept={useConcept} onPhotoAR={(a) => (arAsset = a)} />
          {/if}
        </div>
        {#if wide && tab !== 'chat'}
          <div class="getbar">
            <button class="btn primary" onclick={download3mf} disabled={!store.source}><Icon name="download" size={16} /> {t('download_3mf')}</button>
            <button class="btn" onclick={() => (getIt = true)} disabled={!store.source}><Icon name="package" size={16} /> {t('order')}</button>
          </div>
        {/if}
      </aside>
    </main>
  {/if}
</div>

{#if getIt && store}
  <Modal title={t('get_it')} onClose={() => (getIt = false)}>
    <GetItPanel {store} onPublish={togglePublic} />
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
    grid-template-columns: 390px minmax(0, 1fr) 360px;
    grid-template-rows: minmax(0, 1fr);
    /* a fixed height, not flex: a growing chat must scroll inside its panel, not stretch the page */
    flex: none;
    height: calc(100dvh - var(--header-h, 67px));
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
  .tabbody.chat {
    padding: 0;
    display: flex;
    flex-direction: column;
    min-height: 62dvh;
  }
  .getbar {
    display: flex;
    gap: var(--space-2);
    padding: var(--space-3);
    border-top: var(--border-width) solid var(--divider);
    background: var(--surface-container);
  }
  .getbar .btn {
    flex: 1;
  }
  .getit-inline {
    margin-top: var(--space-5);
    padding-top: var(--space-4);
    border-top: var(--border-width) solid var(--divider);
  }
  @media (max-width: 1099px) {
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
    .studio {
      padding: var(--space-2);
      gap: var(--space-2);
      grid-template-rows: min(44dvh, 380px) auto;
    }
    .tabbody {
      padding: var(--space-3);
    }
  }
</style>
