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
  import ChecksPanel from '$lib/components/ChecksPanel.svelte';
  import PrintPanel from '$lib/components/PrintPanel.svelte';
  import GetItPanel from '$lib/components/GetItPanel.svelte';
  import MorePanel from '$lib/components/MorePanel.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { ProjectStore } from '$lib/project.svelte';
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
    s.load();
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
      await download(await api.exportFile(store.id, '3mf', $state.snapshot(store.values)), name);
    } catch (e) {
      store.addError(errorText(e));
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
    <div class="center"><span class="spin"></span></div>
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
          />
          <div class="overlay tl">
            {#if job}
              <span class="pill work"><span class="spin"></span> {job.kind !== 'design' ? t(`job_${job.kind}`) : job.stage ? t(`stage.${job.stage}`) : t('agent_working')}</span>
            {:else if store.building}
              <span class="pill"><span class="spin"></span> {t('building_model')}</span>
            {:else if store.checks}
              <button class="pill {errCount ? 'err' : warnCount ? 'warn' : 'ok'}" onclick={() => (tab = 'checks')}>
                <Icon name={errCount ? 'alert' : 'check'} size={13} stroke={2.4} />
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
    background: transparent !important;
    border: 1px solid transparent !important;
    font-weight: 650;
    min-width: 60px;
    flex: 0 1 340px;
    padding: 4px 8px !important;
    font-size: var(--fs-md);
    text-overflow: ellipsis;
  }
  .title:hover,
  .title:focus {
    border-color: var(--line) !important;
    background: var(--panel) !important;
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
    color: var(--err);
  }
  .studio {
    flex: 1;
    display: grid;
    gap: 10px;
    padding: 10px;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: min(46dvh, 460px) auto;
  }
  .studio.wide {
    grid-template-columns: 390px minmax(0, 1fr) 360px;
    grid-template-rows: calc(100dvh - 76px);
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
    top: 10px;
    left: 10px;
  }
  .overlay.tr {
    top: 10px;
    right: 10px;
    font-size: var(--fs-xs);
    background: color-mix(in srgb, var(--panel) 85%, transparent);
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 3px 10px;
    backdrop-filter: blur(6px);
  }
  .pill {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    font-size: var(--fs-xs);
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: color-mix(in srgb, var(--panel) 88%, transparent);
    backdrop-filter: blur(6px);
    color: var(--text-2);
  }
  .pill.ok {
    color: var(--ok);
  }
  .pill.warn {
    color: var(--warn);
  }
  .pill.err {
    color: var(--err);
  }
  .pill.work {
    color: var(--accent);
  }
  .builderr {
    position: absolute;
    bottom: 56px;
    left: 10px;
    right: 10px;
    background: var(--err-soft);
    color: var(--err);
    border-radius: 10px;
    padding: 8px 10px;
    font-size: 12px;
    max-height: 30%;
    overflow: auto;
    white-space: pre-wrap;
    z-index: 2;
  }
  .tabs {
    padding: 8px;
    border-bottom: 1px solid var(--line);
    flex: none;
  }
  .n {
    font-size: 10.5px;
    min-width: 17px;
    height: 17px;
    border-radius: 9px;
    display: inline-grid;
    place-items: center;
    padding: 0 4px;
    color: #fff;
  }
  .n.err {
    background: var(--err);
  }
  .n.warn {
    background: var(--warn);
  }
  .live {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent);
    animation: fw-blink 1s ease-in-out infinite alternate;
  }
  @keyframes fw-blink {
    to {
      opacity: 0.3;
    }
  }
  .tabbody {
    padding: 14px;
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
    gap: 8px;
    padding: 10px 12px;
    border-top: 1px solid var(--line);
    background: var(--panel);
  }
  .getbar .btn {
    flex: 1;
  }
  .getit-inline {
    margin-top: 18px;
    padding-top: 14px;
    border-top: 1px solid var(--line);
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
      top: 54px;
      z-index: 5;
      background: var(--panel);
      border-radius: var(--radius) var(--radius) 0 0;
    }
  }
  @media (max-width: 640px) {
    .hide-sm {
      display: none;
    }
    .studio {
      padding: 6px;
      gap: 6px;
      grid-template-rows: min(44dvh, 380px) auto;
    }
    .tabbody {
      padding: 12px;
    }
  }
</style>
