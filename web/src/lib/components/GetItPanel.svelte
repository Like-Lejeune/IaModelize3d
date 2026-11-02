<script lang="ts">
  import Icon from './Icon.svelte';
  import { api, download, errorText } from '$lib/api';
  import { t, projectTitle } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import { shop } from '$lib/shop/api';
  import { moneyRange, st } from '$lib/shop/i18n';
  import type { Quote } from '$lib/shop/types';

  let { store, readonly = false, onPublish }: { store: ProjectStore; readonly?: boolean; onPublish?: () => void } = $props();

  // what the Axo farm prints (server/formwright/shop/quote.py)
  const MATERIALS = ['PLA', 'PETG', 'ASA', 'TPU'];
  let busy = $state<string | null>(null);
  let error = $state<string | null>(null);
  let material = $state('PLA');
  // what the project is meant to print in (a ready example's brief: PETG for the dishwasher wheel), until one is picked here
  let picked = $state(false);
  $effect(() => {
    const m = store.detail?.material?.toUpperCase();
    if (!picked && m && MATERIALS.includes(m)) material = m;
  });
  let copied = $state(false);
  let instant = $state<Quote | null>(null);

  // Formwright Parts: the kernel's instant range for this version; the binding price comes from OrcaSlicer on /parts/new
  $effect(() => {
    const v = store.version;
    const m = material;
    instant = null;
    if (readonly || !v) return;
    const h = setTimeout(() => {
      shop
        .instantQuote(store.id, { material: m })
        .then((q) => store.version === v && (instant = q))
        .catch(() => {});
    }, 600);
    return () => clearTimeout(h);
  });

  async function dl(format: 'stl' | '3mf') {
    busy = format;
    error = null;
    // letters of any script are fine in a download name; only separators and symbols go
    const base = (store.detail?.title ?? '').replace(/[^\p{L}\p{N}_-]+/gu, '_').replace(/^_+|_+$/g, '').slice(0, 40);
    const name = `${base || 'model'}.${format}`;
    // built here, from exactly what the viewer shows; the server only as a fallback
    try {
      await download(await store.exportFile(format), name);
    } catch (e) {
      try {
        if (readonly) throw e;
        await download(await api.exportFile(store.id, format, $state.snapshot(store.values)), name);
      } catch (e2) {
        error = errorText(e2);
      }
    } finally {
      busy = null;
    }
  }

  const recipeUrl = $derived(`${location.origin}/r/${store.id}`);
  const xUrl = $derived(
    `https://x.com/intent/post?text=${encodeURIComponent(t('share_x_text', { title: projectTitle(store.detail?.title) }))}&url=${encodeURIComponent(recipeUrl)}`,
  );

  // a link only works for others once the recipe is public
  async function ensurePublic() {
    if (!store.detail || store.detail.public) return;
    const p = await api.patchProject(store.id, { public: true });
    store.detail.public = p.public;
  }

  // one step: publish if needed, then copy the link
  async function share() {
    busy = 'share';
    error = null;
    try {
      await ensurePublic();
      try {
        await navigator.clipboard.writeText(recipeUrl);
        copied = true;
        setTimeout(() => (copied = false), 1800);
      } catch {
        prompt('URL', recipeUrl);
      }
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = null;
    }
  }

  // the X tab opens right away (a popup must come from the click itself); publishing finishes meanwhile
  function postX() {
    ensurePublic().catch((e) => (error = errorText(e)));
  }
</script>

<div class="getit">
  <section class="stack">
    <div class="row">
      <button class="btn primary" onclick={() => dl('3mf')} disabled={!store.source || busy === '3mf'}>
        {#if busy === '3mf'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="download" size={16} />{/if} {t('download_3mf')}
      </button>
      <button class="btn" onclick={() => dl('stl')} disabled={!store.source || busy === 'stl'}>{t('download_stl')}</button>
    </div>
  </section>

  {#if !readonly}
    <section class="stack">
      <h4 class="section-title">{t('order')}</h4>
      <p class="muted small">{st('new.project_hint')}</p>
      <div class="quote">
        <select bind:value={material} onchange={() => (picked = true)} aria-label={t('material')}>{#each MATERIALS as m (m)}<option>{m}</option>{/each}</select>
        <a class="btn" class:disabled={!store.version} href="/parts/new?project={store.id}&material={material}">
          <Icon name="package" size={15} /> {st('getit.quote')}
        </a>
        {#if instant?.range}<span class="range small">≈ {moneyRange(instant.range.total, instant.range.total_usd)}</span>{/if}
      </div>
    </section>

    <section class="stack">
      <h4 class="section-title">{t('share')}</h4>
      <p class="muted small">{t('share_hint')}</p>
      <div class="row">
        <button class="btn small primary" onclick={share} disabled={!store.source || busy === 'share'}>
          {#if busy === 'share'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name={copied ? 'check' : 'copy'} size={14} />{/if}
          {copied ? t('link_copied') : t('share')}
        </button>
        <a class="btn small" class:disabled={!store.source} href={xUrl} target="_blank" rel="noopener noreferrer" onclick={postX}>
          <span class="x" aria-hidden="true">𝕏</span> {t('share_x')}
        </a>
        {#if store.detail?.public}
          <a class="btn small ghost" href="/r/{store.id}" target="_blank" rel="noopener">{t('recipe')} ↗</a>
          <button class="btn small ghost" onclick={onPublish}><Icon name="lock" size={14} /> {t('unpublish')}</button>
        {/if}
      </div>
    </section>
  {/if}
  {#if error}<p class="err small" role="alert">{error}</p>{/if}
</div>

<style>
  .getit {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .quote {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .quote select {
    width: auto;
  }
  .range {
    font-weight: var(--font-weight-semibold);
    font-variant-numeric: tabular-nums;
  }
  .err {
    color: var(--error);
  }
  .x {
    font-weight: var(--font-weight-semibold);
    line-height: 1;
  }
  p {
    margin: 0;
  }
</style>
