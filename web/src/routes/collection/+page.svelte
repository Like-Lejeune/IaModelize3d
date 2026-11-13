<script lang="ts">
  // The album of snapped objects: each one is a printable model (or on its way to one), grouped by the walk
  // (the day) they were collected on. Select a few and they go on one print bed together as stickers.
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import SnapHighlight from '$lib/components/SnapHighlight.svelte';
  import Sticker from '$lib/components/Sticker.svelte';
  import { api, errorText } from '$lib/api';
  import { collectApi, collectError, type PlateResult } from '$lib/collect/api';
  import { ct, day, money, num } from '$lib/collect/i18n';
  import { ago, plural, projectTitle, t } from '$lib/i18n.svelte';
  import type { CollectionItem } from '$lib/types';

  let items = $state<CollectionItem[] | null>(null);
  let error = $state<string | null>(null);
  let selecting = $state(false);
  const picked = new SvelteSet<string>();
  let plating = $state(false);
  let plate = $state<PlateResult | null>(null);
  let plateError = $state<string | null>(null);

  const shown = $derived((items ?? []).filter((i) => i.state !== 'draft' || i.mask_url));
  const pending = $derived(shown.some((i) => i.state === 'modelling' || i.state === 'queued'));
  const ready = $derived(shown.filter((i) => i.state === 'ready').length);
  // a walk = the finds of one day, newest first (the list already comes newest first)
  const walks = $derived.by(() => {
    const out: { key: string; at: number; items: CollectionItem[] }[] = [];
    for (const it of shown) {
      const d = new Date(it.created_at * 1000);
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      const last = out[out.length - 1];
      if (last?.key === key) last.items.push(it);
      else out.push({ key, at: it.created_at, items: [it] });
    }
    return out;
  });
  // anything with an outline can be a sticker on the plate
  const selectable = (it: CollectionItem) => !!it.mask_url;

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
    const id = setInterval(() => (pending || error) && load(), 5000);
    return () => clearInterval(id);
  });

  const chip = (s: CollectionItem['state']) => (s === 'ready' ? 'ok' : s === 'failed' ? 'err' : s === 'draft' ? '' : 'accent');

  function startSelect() {
    selecting = true;
    plate = null;
    plateError = null;
  }
  function stopSelect() {
    selecting = false;
    picked.clear();
    plate = null;
    plateError = null;
  }
  function toggle(it: CollectionItem) {
    if (!selectable(it)) return;
    if (picked.has(it.id)) picked.delete(it.id);
    else picked.add(it.id);
    plate = null;
    plateError = null;
  }
  function toggleWalk(list: CollectionItem[]) {
    const ok = list.filter(selectable);
    const all = ok.every((i) => picked.has(i.id));
    for (const i of ok) all ? picked.delete(i.id) : picked.add(i.id);
    plate = null;
    plateError = null;
  }

  async function printPlate() {
    if (!picked.size || plating) return;
    plating = true;
    plateError = null;
    plate = null;
    // in the order they appear on the page
    const ids = shown.filter((i) => picked.has(i.id)).map((i) => i.id);
    try {
      plate = await collectApi.plate({ ids });
    } catch (e) {
      plateError = collectError(e);
    } finally {
      plating = false;
    }
  }
</script>

<svelte:head><title>{t('collection')} · IaModelize3d</title></svelte:head>

{#snippet body(it: CollectionItem)}
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
    {#if selecting && selectable(it)}
      <span class="tickbox" class:on={picked.has(it.id)} aria-hidden="true">{#if picked.has(it.id)}<Icon name="check" size={16} />{/if}</span>
    {/if}
  </div>
  <div class="meta">
    <strong>{projectTitle(it.title)}</strong>
    <span class="muted xs">{ago(it.created_at)}</span>
  </div>
{/snippet}

<div class="page" class:selecting>
  <Header />
  <main class="wrap">
    <div class="head">
      <div>
        <h1>{t('collection')}</h1>
        {#if shown.length}
          <p class="muted small">
            {plural(shown.length, ['object', 'objects'], ['предмет', 'предмета', 'предметов'])}{#if ready}{' · '}{plural(ready, ['model ready', 'models ready'], ['модель готова', 'модели готовы', 'моделей готово'])}{/if}
          </p>
        {/if}
      </div>
      <div class="head-acts">
        {#if shown.some(selectable)}
          {#if selecting}
            <button class="btn" onclick={stopSelect}>{ct('cancel')}</button>
          {:else}
            <button class="btn" onclick={startSelect}><Icon name="printer" size={18} /> <span class="lbl">{ct('select')}</span></button>
          {/if}
        {/if}
        <!-- with nothing collected yet the empty state below has this button -->
        {#if shown.length}<a class="btn primary" href="/snap"><Icon name="camera" size={18} /> {t('snap')}</a>{/if}
      </div>
    </div>

    {#if error}<p class="err small" role="alert">{error} <button class="btn small" onclick={load}>{t('retry')}</button></p>{/if}

    {#if items === null}
      {#if !error}
        <div class="grid">
          {#each [0, 1, 2, 3] as i (i)}<div class="card sk"></div>{/each}
        </div>
      {/if}
    {:else if !shown.length}
      <div class="empty">
        <p>{t('collection_empty')}</p>
        <a class="btn primary large" href="/snap"><Icon name="camera" size={18} /> {t('snap_title')}</a>
      </div>
    {:else}
      {#each walks as w (w.key)}
        <section class="walk">
          <div class="walk-head">
            <h2>{ct('walk', { date: day(w.at) })} · <span class="muted">{plural(w.items.length, ['find', 'finds'], ['находка', 'находки', 'находок'])}</span></h2>
            {#if selecting && w.items.some(selectable)}
              <button class="chip" class:on={w.items.filter(selectable).every((i) => picked.has(i.id))} onclick={() => toggleWalk(w.items)}>{ct('select_all')}</button>
            {/if}
          </div>
          <div class="grid">
            {#each w.items as it (it.id)}
              {#if selecting}
                <button class="card item pick" class:on={picked.has(it.id)} class:off={!selectable(it)} aria-pressed={picked.has(it.id)} disabled={!selectable(it)} onclick={() => toggle(it)}>
                  {@render body(it)}
                </button>
              {:else}
                <a class="card item" href="/p/{it.id}">{@render body(it)}</a>
              {/if}
            {/each}
          </div>
        </section>
      {/each}
    {/if}
  </main>

  {#if selecting}
    <div class="dock" role="region" aria-label={ct('print_n', { n: picked.size })} aria-live="polite">
      {#if plate}
        <div class="result">
          <img src={plate.project.cover} alt="" />
          <div class="res-text">
            <strong>{ct('plate_ready', { n: plate.count, w: plate.size_mm[0]?.toFixed(0), h: plate.size_mm[1]?.toFixed(0) })}</strong>
            <span class="muted xs">{ct('plate_bed', { printer: plate.printer ?? 'Bambu Lab A1', w: plate.bed[0], h: plate.bed[1] })}</span>
            <span class="small">{ct('plate_est', { min: plate.est.minutes, g: num(plate.est.grams) })}</span>
            {#if plate.est.price}
              <span class="small">{ct('plate_price', { print: money(plate.est.price.print, plate.est.price.usd.print), delivery: money(plate.est.price.delivery, plate.est.price.usd.delivery) })}</span>
            {/if}
            <span class="xs" class:warn={!plate.a1_mini} class:muted={plate.a1_mini}>{plate.a1_mini ? ct('a1_mini_ok') : ct('a1_mini_note')}</span>
          </div>
        </div>
        <div class="dock-acts">
          <button class="btn" onclick={stopSelect}>{ct('cancel')}</button>
          <button class="btn primary grow" onclick={() => goto(`/p/${plate!.project_id}`)}><Icon name="cube" size={17} /> {ct('plate_open')}</button>
        </div>
      {:else}
        {#if plateError}<p class="err small" role="alert">{plateError}</p>{:else}<p class="muted xs">{picked.size ? ct('two_colour') : ct('select_hint')}</p>{/if}
        <div class="dock-acts">
          <button class="btn primary grow" onclick={printPlate} disabled={!picked.size || plating}>
            {#if plating}<i class="ti ti-loader-2 spin" aria-hidden="true"></i> {ct('plate_building')}{:else}<Icon name="printer" size={17} /> {picked.size ? ct('print_n', { n: picked.size }) : ct('print_one')}{/if}
          </button>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .page {
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
  }
  .page.selecting {
    padding-bottom: 200px; /* room under the dock */
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
  .head-acts {
    display: flex;
    gap: var(--space-2);
    flex: none;
  }
  h1 {
    font-size: var(--text-3xl);
    font-weight: var(--font-weight-semibold);
  }
  .head p {
    margin: 4px 0 0;
  }
  .err {
    color: var(--error);
    margin: 0;
  }
  .walk {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .walk-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    min-height: 32px;
  }
  .walk-head h2 {
    margin: 0;
    font-size: var(--text-base);
    font-weight: var(--font-weight-bold);
  }
  .walk-head h2 .muted {
    font-weight: var(--font-weight-regular);
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
    transition: border-color var(--dur-fast) var(--ease-standard);
  }
  .item:hover {
    text-decoration: none;
    border-color: var(--outline);
  }
  button.item {
    padding: 0;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .pick.on {
    border-color: var(--primary);
    box-shadow: 0 0 0 2px var(--primary);
  }
  .pick.off {
    opacity: 0.45;
    cursor: default;
    transform: none;
  }
  .tickbox {
    position: absolute;
    right: 8px;
    top: 8px;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    border: 2px solid #fff;
    background: rgb(0 0 0 / 0.3);
    color: var(--on-primary);
    box-shadow: 0 1px 6px rgb(0 0 0 / 0.3);
  }
  .tickbox.on {
    background: var(--primary);
    border-color: var(--primary);
  }
  .pic {
    position: relative;
    aspect-ratio: 4 / 5;
    background: #000;
    overflow: hidden;
  }
  .pic.model {
    background: var(--render-bg);
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
    font-size: var(--text-base);
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
    font-size: var(--text-lg);
  }

  /* the print dock: what goes on the plate, then the plate itself */
  .dock {
    position: fixed;
    left: 50%;
    bottom: calc(env(safe-area-inset-bottom) + var(--space-3));
    transform: translateX(-50%);
    width: min(560px, calc(100vw - 32px));
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-xl);
    background: var(--surface-container);
    border: var(--border-width) solid var(--outline-variant);
    box-shadow: 0 10px 40px rgb(0 0 0 / 0.35);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    z-index: 20;
    animation: dock-in 300ms var(--ease-settle);
  }
  @keyframes dock-in {
    from {
      transform: translate(-50%, 30%);
      opacity: 0;
    }
  }
  .dock p {
    margin: 0;
  }
  .dock-acts {
    display: flex;
    gap: var(--space-2);
  }
  .dock-acts .grow {
    flex: 1;
  }
  .result {
    display: flex;
    gap: var(--space-3);
    align-items: flex-start;
    min-width: 0;
  }
  .result img {
    flex: none;
    width: 96px;
    height: 96px;
    object-fit: contain;
    border-radius: var(--radius-md);
    background: var(--render-bg);
  }
  .res-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .res-text .warn {
    color: var(--warn-text);
    font-weight: var(--font-weight-semibold);
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
    .head .lbl {
      display: none;
    }
    .result img {
      width: 72px;
      height: 72px;
    }
  }
</style>
