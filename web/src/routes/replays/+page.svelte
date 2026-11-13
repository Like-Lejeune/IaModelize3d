<script lang="ts">
  // The replay gallery: agent runs their owners chose to list, picked ones first. Opening one plays it (/w/<id>).
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import RunCard from '$lib/components/RunCard.svelte';
  import { api, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { FeaturedRun as Run } from '$lib/types';

  const PAGE = 24;
  const KINDS = [
    { id: '', label: 'replays_all' },
    { id: 'device', label: 'replays_devices' },
    { id: 'part', label: 'replays_parts' },
  ];
  const SORTS = [
    { id: 'new', label: 'replays_new' },
    { id: 'popular', label: 'replays_popular' },
  ];
  // in the address, so a filtered gallery can be linked and Back returns to it
  const kind = $derived(page.url.searchParams.get('kind') ?? '');
  const sort = $derived(page.url.searchParams.get('sort') ?? 'new');

  let runs = $state<Run[] | null>(null);
  let more = $state(false);
  let loading = $state(false);
  let error = $state<string | null>(null);

  $effect(() => {
    const k = kind;
    const s = sort;
    let gone = false;
    runs = null;
    error = null;
    api
      .replays({ kind: k, sort: s })
      .then((r) => {
        if (gone) return;
        runs = r;
        more = r.length === PAGE;
      })
      .catch((e) => {
        if (gone) return;
        error = errorText(e);
        runs = [];
      });
    return () => (gone = true);
  });

  async function loadMore() {
    if (!runs || loading) return;
    loading = true;
    try {
      const r = await api.replays({ kind, sort, offset: runs.length });
      runs = [...runs, ...r];
      more = r.length === PAGE;
    } catch (e) {
      error = errorText(e);
    } finally {
      loading = false;
    }
  }

  function filter(key: string, value: string) {
    const u = new URL(page.url);
    if (value) u.searchParams.set(key, value);
    else u.searchParams.delete(key);
    goto(u.pathname + u.search, { replaceState: true, keepFocus: true, noScroll: true });
  }
</script>

<svelte:head><title>{t('replays')} · IaModelize3d</title></svelte:head>

<Header />

<main class="wrap">
  <header class="head">
    <h1>{t('replays')}</h1>
    <p class="muted">{t('replays_hint')}</p>
  </header>
  <div class="filters">
    <div class="seg" role="radiogroup" aria-label={t('replays_kind')}>
      {#each KINDS as k (k.id)}<button role="radio" aria-checked={kind === k.id} onclick={() => filter('kind', k.id)}>{t(k.label)}</button>{/each}
    </div>
    <div class="seg" role="radiogroup" aria-label={t('replays_sort')}>
      {#each SORTS as s (s.id)}<button role="radio" aria-checked={sort === s.id} onclick={() => filter('sort', s.id === 'new' ? '' : s.id)}>{t(s.label)}</button>{/each}
    </div>
  </div>
  {#if error}<p class="err" role="alert">{error}</p>{/if}
  {#if !runs}
    <div class="center"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></div>
  {:else if !runs.length}
    {#if !error}
      <div class="none">
        <Icon name="play" size={28} />
        <p>{t('replays_empty')}</p>
        <a class="btn primary" href="/">{t('replays_empty_cta')}</a>
      </div>
    {/if}
  {:else}
    <div class="runs">
      {#each runs as r (r.id)}<RunCard run={r} />{/each}
    </div>
    {#if more}
      <button class="btn more" onclick={loadMore} disabled={loading}>
        {#if loading}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{/if}
        {t('replays_more')}
      </button>
    {/if}
  {/if}
</main>

<style>
  .wrap {
    max-width: 1200px;
    margin: 0 auto;
    padding: var(--space-6) var(--space-5);
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  h1 {
    font-size: var(--text-2xl, 1.6rem);
    margin: 0;
  }
  .head p {
    margin: 4px 0 0;
  }
  .filters {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .seg {
    display: inline-flex;
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-btn);
    overflow: hidden;
  }
  .seg button {
    padding: 6px 14px;
    border: none;
    background: none;
    color: var(--on-surface-var);
    font: inherit;
    font-size: var(--text-md);
    cursor: pointer;
  }
  .seg button:hover {
    background: var(--surface-high);
  }
  .seg button[aria-checked='true'] {
    background: var(--surface-high);
    color: var(--on-surface);
    font-weight: var(--font-weight-semibold);
  }
  .runs {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: var(--space-4);
  }
  .more {
    align-self: center;
  }
  .center,
  .none {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-7) 0;
    color: var(--on-surface-var);
    text-align: center;
  }
  .none p {
    margin: 0;
  }
  .err {
    color: var(--error);
    margin: 0;
  }
  @media (max-width: 720px) {
    .wrap {
      padding: var(--space-4);
    }
    .runs {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-3);
    }
  }
</style>
