<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { onDestroy } from 'svelte';
  import Header from '$lib/components/Header.svelte';
  import Viewer from '$lib/components/Viewer.svelte';
  import Timeline from '$lib/components/Timeline.svelte';
  import Composer from '$lib/components/Composer.svelte';
  import ParamsPanel from '$lib/components/ParamsPanel.svelte';
  import ChecksPanel from '$lib/components/ChecksPanel.svelte';
  import PrintPanel from '$lib/components/PrintPanel.svelte';
  import AssetsPanel from '$lib/components/AssetsPanel.svelte';
  import CreatePanel from '$lib/components/CreatePanel.svelte';
  import VersionsPanel from '$lib/components/VersionsPanel.svelte';
  import { ProjectStore } from '$lib/project.svelte';
  import { api, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { AssetOut, Calibration, Issue } from '$lib/types';

  type Tab = 'chat' | 'params' | 'checks' | 'print' | 'assets' | 'create' | 'versions';

  let store = $state<ProjectStore | null>(null);
  let tab = $state<Tab>('params');
  let selectedIssue = $state<Issue | null>(null);
  let arAsset = $state<AssetOut | null>(null);
  let viewer = $state<Viewer>();
  let wide = $state(true);

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
      if (wide && tab === 'chat') tab = 'params';
    };
    set();
    mq.addEventListener('change', set);
    return () => mq.removeEventListener('change', set);
  });

  onDestroy(() => store?.dispose());

  const photo = $derived.by(() => {
    if (!store) return null;
    const a = arAsset ?? store.assets.find((x) => x.meta?.calibration);
    const cal = a?.meta?.calibration as Calibration | undefined;
    if (!a || !cal?.R || !cal?.t) return null;
    return { url: a.url, calibration: { ...cal, width: cal.width ?? a.width ?? 1, height: cal.height ?? a.height ?? 1 } };
  });

  const tabs = $derived<Tab[]>(wide ? ['params', 'checks', 'print', 'assets', 'create', 'versions'] : ['chat', 'params', 'checks', 'print', 'assets', 'create', 'versions']);
  const issueCount = $derived(store?.checks?.issues.filter((i) => i.severity !== 'info').length ?? 0);

  async function rename(e: Event) {
    const v = (e.currentTarget as HTMLInputElement).value.trim();
    if (!store?.detail || !v || v === store.detail.title) return;
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

  function useConcept(url: string) {
    if (!store) return;
    const a = store.assets.find((x) => x.url === url);
    store.send(`Use this concept as the visual target${a ? '' : `: ${url}`}`, a ? [a.id] : []);
    if (!wide) tab = 'chat';
  }
</script>

<svelte:head><title>{store?.detail?.title ?? 'Studio'} · Formwright</title></svelte:head>

<div class="page">
  <Header>
    {#if store?.detail}
      <div class="titlebar">
        <input class="title" value={store.detail.title} onchange={rename} aria-label="project title" />
        <span class="chip mono">v{store.version}</span>
        {#if store.connection === 'retry'}<span class="chip warn" title="reconnecting">⟳</span>{/if}
        <button class="btn small ghost hide-sm" onclick={togglePublic}>{store.detail.public ? '🌐 ' + t('unpublish') : t('publish')}</button>
        {#if store.detail.public}<a class="btn small ghost hide-sm" href="/r/{store.id}">{t('recipe')} ↗</a>{/if}
        <button class="btn small ghost hide-sm" onclick={fork}>{t('fork')}</button>
      </div>
    {/if}
  </Header>

  {#if store?.loadError}
    <div class="center"><p class="err">{t('error')}: {store.loadError}</p><a href="/">{t('back')}</a></div>
  {:else if !store?.detail}
    <div class="center muted">{t('loading')}</div>
  {:else}
    <main class="studio" class:wide>
      {#if wide}
        <aside class="left card">
          <Timeline {store} onUseConcept={useConcept} />
          <Composer {store} />
        </aside>
      {/if}
      <section class="center-col">
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
        {#if store.buildError}<div class="builderr mono">{store.buildError}</div>{/if}
      </section>
      <aside class="right card">
        <div class="tabs" role="tablist">
          {#each tabs as tb (tb)}
            <button role="tab" aria-selected={tab === tb} class:on={tab === tb} onclick={() => (tab = tb)}>
              {t(tb === 'create' ? 'concepts' : tb)}
              {#if tb === 'checks' && issueCount}<span class="chip warn n">{issueCount}</span>{/if}
              {#if tb === 'chat' && store.running}<span class="dot" aria-label="running"></span>{/if}
            </button>
          {/each}
        </div>
        <div class="tabbody" class:chat={tab === 'chat'}>
          {#if tab === 'chat'}
            <Timeline {store} onUseConcept={useConcept} />
            <Composer {store} />
          {:else if tab === 'params'}
            <ParamsPanel specs={store.build?.paramSpecs ?? {}} values={store.values} onChange={(n, v, c) => store!.setParam(n, v, c)} />
          {:else if tab === 'checks'}
            <ChecksPanel checks={store.checks} selected={selectedIssue} onSelect={(i) => (selectedIssue = i)} building={store.building} />
          {:else if tab === 'print'}
            <PrintPanel {store} />
          {:else if tab === 'assets'}
            <AssetsPanel {store} onPhotoAR={(a) => (arAsset = a)} />
          {:else if tab === 'create'}
            <CreatePanel {store} snapshot={() => viewer?.snapshot() ?? null} onUseConcept={useConcept} />
          {:else if tab === 'versions'}
            <VersionsPanel {store} />
          {/if}
        </div>
      </aside>
    </main>
  {/if}
</div>

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
    font-weight: 600;
    min-width: 60px;
    flex: 1;
    max-width: 320px;
    padding: 4px 6px !important;
  }
  .title:hover,
  .title:focus {
    border-color: var(--line) !important;
  }
  .center {
    flex: 1;
    display: grid;
    place-items: center;
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
    grid-template-rows: 52vh auto;
  }
  .studio.wide {
    grid-template-columns: 360px minmax(0, 1fr) 350px;
    grid-template-rows: calc(100dvh - 72px);
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
    flex-direction: column;
  }
  .builderr {
    position: absolute;
    top: 8px;
    left: 8px;
    right: 8px;
    background: color-mix(in srgb, var(--err) 12%, var(--panel));
    color: var(--err);
    border: 1px solid color-mix(in srgb, var(--err) 40%, transparent);
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 12px;
    max-height: 30%;
    overflow: auto;
    white-space: pre-wrap;
  }
  .tabs {
    display: flex;
    overflow-x: auto;
    border-bottom: 1px solid var(--line);
    scrollbar-width: none;
    flex: none;
  }
  .tabs button {
    border: none;
    background: none;
    padding: 10px 8px;
    font-size: 12.5px;
    font-weight: 500;
    color: var(--muted);
    white-space: nowrap;
    border-bottom: 2px solid transparent;
    display: flex;
    gap: 4px;
    align-items: center;
  }
  .tabs button.on {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
  .n {
    padding: 0 5px;
    font-size: 11px;
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent);
    animation: pulse 1s ease-in-out infinite alternate;
  }
  @keyframes pulse {
    to {
      opacity: 0.3;
    }
  }
  .tabbody {
    padding: 12px;
    overflow-y: auto;
    flex: 1;
    min-height: 0;
  }
  .tabbody.chat {
    padding: 0;
    display: flex;
    flex-direction: column;
    min-height: 60vh;
  }
  @media (max-width: 1099px) {
    .right {
      overflow: visible;
    }
    .tabbody {
      overflow: visible;
    }
  }
  @media (max-width: 640px) {
    .hide-sm {
      display: none;
    }
    .studio {
      padding: 6px;
      gap: 6px;
      grid-template-rows: 46vh auto;
    }
  }
</style>
