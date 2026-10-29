<script lang="ts">
  // The album of snapped objects: each one is a printable model (or on its way to one).
  import { onMount } from 'svelte';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import SnapHighlight from '$lib/components/SnapHighlight.svelte';
  import Sticker from '$lib/components/Sticker.svelte';
  import { api, errorText } from '$lib/api';
  import { ago, plural, projectTitle, t } from '$lib/i18n.svelte';
  import type { CollectionItem } from '$lib/types';

  let items = $state<CollectionItem[] | null>(null);
  let error = $state<string | null>(null);

  const shown = $derived((items ?? []).filter((i) => i.state !== 'draft' || i.mask_url));
  const pending = $derived(shown.some((i) => i.state === 'modelling' || i.state === 'queued'));
  const ready = $derived(shown.filter((i) => i.state === 'ready').length);

  async function load() {
    try {
      items = await api.collection();
      error = null;
    } catch (e) {
      error = errorText(e);
    }
  }

  onMount(() => {
    load();
    const id = setInterval(() => pending && load(), 5000);
    return () => clearInterval(id);
  });

  const chip = (s: CollectionItem['state']) => (s === 'ready' ? 'ok' : s === 'failed' ? 'err' : s === 'draft' ? '' : 'accent');
</script>

<svelte:head><title>{t('collection')} · Formwright</title></svelte:head>

<div class="page">
  <Header />
  <main class="wrap">
    <div class="head">
      <div>
        <h1>{t('collection')}</h1>
        {#if shown.length}
          <p class="muted small">
            {plural(shown.length, ['object', 'objects'], ['предмет', 'предмета', 'предметов'])}{#if ready} · {plural(ready, ['model ready', 'models ready'], ['модель готова', 'модели готовы', 'моделей готово'])}{/if}
          </p>
        {/if}
      </div>
      <a class="btn primary" href="/snap"><Icon name="camera" size={18} /> {t('snap')}</a>
    </div>

    {#if error}<p class="err small" role="alert">{error}</p>{/if}

    {#if items === null && !error}
      <div class="grid">
        {#each [0, 1, 2, 3] as i (i)}<div class="card sk"></div>{/each}
      </div>
    {:else if !shown.length}
      <div class="empty">
        <span class="empty-ic"><Icon name="scan" size={36} /></span>
        <p>{t('collection_empty')}</p>
        <a class="btn primary large" href="/snap"><Icon name="camera" size={18} /> {t('snap_title')}</a>
      </div>
    {:else}
      <div class="grid">
        {#each shown as it (it.id)}
          <a class="card item" href="/p/{it.id}">
            <div class="pic" class:model={it.state === 'ready' && it.cover}>
              {#if it.state === 'ready' && it.cover}
                <img src={it.cover} alt={it.title} loading="lazy" />
                {#if it.photo && it.mask_url}<span class="orig"><Sticker photo={it.photo} mask={it.mask_url} bbox={it.bbox && it.width && it.height ? it.bbox.map((v) => v * Math.min(1, 512 / Math.max(it.width!, it.height!))) : null} size={46} /></span>{/if}
              {:else if it.photo && it.mask_url && it.width && it.height}
                <SnapHighlight compact src={it.photo} width={it.width} height={it.height} maskUrl={it.mask_url} focus={it.bbox ?? null} scanning={it.state === 'modelling'} />
              {:else if it.photo}
                <img class="dimmed" src={it.photo} alt="" loading="lazy" />
              {/if}
              <span class="chip {chip(it.state)} state">
                {#if it.state === 'modelling'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{/if}
                {t(`collect.${it.state}`)}
              </span>
            </div>
            <div class="meta">
              <strong>{projectTitle(it.title)}</strong>
              <span class="muted xs">{ago(it.created_at)}</span>
            </div>
          </a>
        {/each}
      </div>
    {/if}
  </main>
</div>

<style>
  .page {
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
  }
  .wrap {
    width: 100%;
    max-width: var(--container-wide);
    margin: 0 auto;
    padding: var(--space-6) var(--space-5) var(--space-8);
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
  }
  .head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--space-3);
  }
  h1 {
    font-size: var(--text-cart-h1);
    font-weight: var(--font-weight-bold);
  }
  .head p {
    margin: 4px 0 0;
  }
  .err {
    color: var(--error);
    margin: 0;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: var(--space-4);
  }
  .item {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    color: var(--on-surface);
    text-decoration: none;
    transition:
      border-color var(--dur-fast) var(--ease-standard),
      transform var(--dur-base) var(--ease-settle);
  }
  .item:hover {
    text-decoration: none;
    border-color: var(--outline);
    transform: translateY(-2px);
  }
  .pic {
    position: relative;
    aspect-ratio: 4 / 5;
    background: #000;
    overflow: hidden;
  }
  .pic.model {
    background: #f6f6f3;
  }
  .pic img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .pic.model img {
    object-fit: contain;
    padding: var(--space-2);
  }
  .pic img.dimmed {
    filter: brightness(0.55) saturate(0.5);
  }
  .orig {
    position: absolute;
    right: 8px;
    bottom: 8px;
    padding: 3px;
    border-radius: var(--radius-btn);
    background: rgb(255 255 255 / 0.85);
    box-shadow: 0 2px 8px rgb(0 0 0 / 0.2);
    display: flex;
  }
  .state {
    position: absolute;
    left: 8px;
    top: 8px;
    box-shadow: 0 1px 6px rgb(0 0 0 / 0.25);
  }
  .state:not(.ok):not(.err):not(.accent) {
    background: var(--surface-container);
  }
  .state.accent {
    background: var(--surface-container);
    color: var(--primary);
  }
  .meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--space-3);
    min-width: 0;
  }
  .meta strong {
    font-size: var(--text-product-spec);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sk {
    aspect-ratio: 4 / 5.8;
    animation: sk-pulse var(--t-skeleton) ease-in-out infinite;
  }
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: var(--space-4);
    padding: var(--space-8) var(--space-4);
  }
  .empty p {
    margin: 0;
    max-width: 420px;
    color: var(--on-surface-var);
    font-size: var(--text-product-lead);
  }
  .empty-ic {
    width: 76px;
    height: 76px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: var(--primary);
    background: color-mix(in srgb, var(--primary) 12%, transparent);
  }
  @media (max-width: 520px) {
    .wrap {
      padding: var(--space-4) var(--space-4) var(--space-7);
    }
    .grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--space-3);
    }
    .head .btn {
      padding: 9px 14px;
    }
  }
</style>
