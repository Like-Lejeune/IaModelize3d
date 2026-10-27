<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Viewer from '$lib/components/Viewer.svelte';
  import ParamsPanel from '$lib/components/ParamsPanel.svelte';
  import ChecksPanel from '$lib/components/ChecksPanel.svelte';
  import GetItPanel from '$lib/components/GetItPanel.svelte';
  import { ProjectStore } from '$lib/project.svelte';
  import { api, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { Issue } from '$lib/types';

  let store = $state<ProjectStore | null>(null);
  let selectedIssue = $state<Issue | null>(null);
  let error = $state<string | null>(null);
  let tab = $state<'model' | 'checks' | 'get'>('model');

  $effect(() => {
    const s = new ProjectStore(page.params.id!, true);
    store = s;
    s.load();
    return () => s.dispose();
  });

  let watching = $state(false);
  async function watch() {
    if (!store) return;
    watching = true;
    try {
      const p = await api.replay(store.id, 4);
      goto(`/p/${p.id}`);
    } catch (e) {
      error = errorText(e);
      watching = false;
    }
  }

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
  <div class="center"><p class="err">{store.loadError}</p><a class="btn" href="/">{t('back')}</a></div>
{:else if !store?.detail}
  <div class="center"><span class="spin"></span></div>
{:else}
  <main class="recipe">
    <section class="view card">
      <Viewer
        loading={!!store.source && !store.build}
        build={store.build}
        issues={store.checks?.issues ?? []}
        highlight={selectedIssue}
        values={store.values}
        specs={store.build?.paramSpecs ?? {}}
        onParam={(n, v, c) => store!.setParam(n, v, c)}
      />
    </section>
    <aside class="side card">
      <div class="intro">
        <span class="chip accent">{t('recipe_by')}</span>
        {#if store.build?.meta?.description}<p class="small">{store.build.meta.description}</p>{/if}
        <p class="muted small">{t('readonly_hint')}</p>
        <div class="row">
          <button class="btn primary" onclick={fork}><Icon name="gitfork" size={15} /> {t('fork')}</button>
          <button class="btn" onclick={watch} disabled={watching}>{#if watching}<span class="spin"></span>{:else}<Icon name="play" size={14} />{/if} {t('watch')}</button>
          <a class="btn ghost" href="/">{t('make_your_own')}</a>
        </div>
        {#if error}<p class="err small">{error}</p>{/if}
      </div>
      <div class="seg" role="tablist">
        {#each ['model', 'checks', 'get'] as tb (tb)}
          <button role="tab" aria-selected={tab === tb} onclick={() => (tab = tb as any)}>{t(tb === 'get' ? 'get_it' : tb)}</button>
        {/each}
      </div>
      <div class="body">
        {#if tab === 'model'}
          <ParamsPanel specs={store.build?.paramSpecs ?? {}} values={store.values} agentValues={store.agentValues} building={store.building || (!!store.source && !store.build)} onChange={(n, v, c) => store!.setParam(n, v, c)} />
        {:else if tab === 'checks'}
          <ChecksPanel checks={store.checks} selected={selectedIssue} onSelect={(i) => (selectedIssue = i)} building={store.building} />
        {:else}
          <GetItPanel {store} readonly />
        {/if}
      </div>
    </aside>
  </main>
{/if}

<style>
  .ttl {
    font-size: var(--fs-md);
  }
  .center {
    display: grid;
    place-items: center;
    gap: 12px;
    padding: 60px 16px;
  }
  .err {
    color: var(--err);
  }
  .recipe {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 380px;
    gap: 10px;
    padding: 10px;
    height: calc(100dvh - 55px);
  }
  .view {
    min-height: 0;
    overflow: hidden;
    display: flex;
  }
  .side {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 14px;
    min-height: 0;
    overflow: auto;
  }
  /* a scrolling flex column would otherwise squash the tabs once the sliders arrive */
  .side > * {
    flex-shrink: 0;
  }
  .intro {
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: flex-start;
  }
  .intro p {
    margin: 0;
  }
  @media (max-width: 900px) {
    .recipe {
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: min(52dvh, 460px) auto;
      height: auto;
    }
    .side {
      overflow: visible;
    }
  }
</style>
