<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import Header from '$lib/components/Header.svelte';
  import Viewer from '$lib/components/Viewer.svelte';
  import ParamsPanel from '$lib/components/ParamsPanel.svelte';
  import ChecksPanel from '$lib/components/ChecksPanel.svelte';
  import PrintPanel from '$lib/components/PrintPanel.svelte';
  import { ProjectStore } from '$lib/project.svelte';
  import { api, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { Issue } from '$lib/types';

  let store = $state<ProjectStore | null>(null);
  let selectedIssue = $state<Issue | null>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    const s = new ProjectStore(page.params.id!, true);
    store = s;
    s.load();
    return () => s.dispose();
  });

  async function fork() {
    if (!store) return;
    try {
      const p = await api.fork(store.id);
      goto(`/p/${p.id}`);
    } catch (e) {
      error = errorText(e);
    }
  }
</script>

<svelte:head><title>{store?.detail?.title ?? t('recipe')} · Formwright</title></svelte:head>

<Header>
  {#if store?.detail}<strong class="ttl">{store.detail.title}</strong>{/if}
</Header>

{#if store?.loadError}
  <p class="center err">{store.loadError}</p>
{:else if !store?.detail}
  <p class="center muted">{t('loading')}</p>
{:else}
  <main class="recipe">
    <section class="view">
      <Viewer
        build={store.build}
        issues={store.checks?.issues ?? []}
        highlight={selectedIssue}
        values={store.values}
        specs={store.build?.paramSpecs ?? {}}
        onParam={(n, v, c) => store!.setParam(n, v, c)}
      />
    </section>
    <aside class="side card">
      <div class="row">
        <button class="btn primary" onclick={fork}>⑂ {t('fork')}</button>
        <span class="muted small">{t('readonly_hint')}</span>
      </div>
      {#if error}<p class="err small">{error}</p>{/if}
      {#if store.build?.meta?.description}<p class="small">{store.build.meta.description}</p>{/if}
      <h3 class="section-title">{t('params')}</h3>
      <ParamsPanel specs={store.build?.paramSpecs ?? {}} values={store.values} onChange={(n, v, c) => store!.setParam(n, v, c)} />
      <h3 class="section-title">{t('checks')}</h3>
      <ChecksPanel checks={store.checks} selected={selectedIssue} onSelect={(i) => (selectedIssue = i)} building={store.building} />
      <PrintPanel {store} readonly />
    </aside>
  </main>
{/if}

<style>
  .ttl {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
  }
  .center {
    text-align: center;
    padding: 40px 16px;
  }
  .err {
    color: var(--err);
  }
  .recipe {
    display: grid;
    gap: 10px;
    padding: 10px;
    grid-template-columns: minmax(0, 1fr);
  }
  .view {
    height: 56vh;
    min-width: 0;
  }
  .side {
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
  }
  .small {
    font-size: 13px;
  }
  @media (min-width: 1000px) {
    .recipe {
      grid-template-columns: minmax(0, 1fr) 360px;
      height: calc(100dvh - 54px);
    }
    .view {
      height: 100%;
    }
    .side {
      overflow-y: auto;
    }
  }
</style>
