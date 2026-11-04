<script lang="ts" module>
  // The Axo shop's cart "Edit" sends the buyer back to the studio as /p/<id>?axo=<design id>: that cart line is what
  // "Update in Axo cart" replaces, remembered per project for this tab (the studio page takes it off the URL)
  const AXO_DESIGN = /^[0-9a-f]{32}$/;
  const axoKey = (projectId: string) => `fw_axo:${projectId}`;

  export function rememberAxoDesign(projectId: string, design: string | null | undefined) {
    if (!design || !AXO_DESIGN.test(design)) return;
    try {
      sessionStorage.setItem(axoKey(projectId), design);
    } catch {
      /* storage unavailable: the button adds a new line instead */
    }
  }

  export function axoDesign(projectId: string): string | null {
    try {
      const d = sessionStorage.getItem(axoKey(projectId));
      return d && AXO_DESIGN.test(d) ? d : null;
    } catch {
      return null;
    }
  }
</script>

<script lang="ts">
  import Icon from './Icon.svelte';
  import { api, ApiError, download, errorText } from '$lib/api';
  import { t, projectTitle } from '$lib/i18n.svelte';
  import { session } from '$lib/session.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import { shop } from '$lib/shop/api';
  import { moneyRange, st } from '$lib/shop/i18n';
  import type { Quote } from '$lib/shop/types';

  let { store, readonly = false }: { store: ProjectStore; readonly?: boolean } = $props();

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
  const replayUrl = $derived(`${location.origin}/w/${store.id}`);
  const xUrl = $derived(
    `https://x.com/intent/post?text=${encodeURIComponent(t('share_x_text', { title: projectTitle(store.detail?.title) }))}&url=${encodeURIComponent(recipeUrl)}`,
  );

  // Who can see this: the owner, whoever has the link, or everyone on the replay gallery. Each step wider says first what
  // it shows (the whole run, photos included); going narrower takes effect at once.
  type Level = 'private' | 'link' | 'gallery';
  const LEVELS: Level[] = ['private', 'link', 'gallery'];
  const level = $derived<Level>(store.detail?.listed ? 'gallery' : store.detail?.public ? 'link' : 'private');
  let asking = $state<Level | null>(null);
  const photos = $derived(store.assets.filter((a) => a.kind === 'photo').length);
  const hasRun = $derived(Object.keys(store.jobs).length > 0);

  async function setLevel(to: Level) {
    busy = 'publish';
    error = null;
    asking = null;
    try {
      const p = await api.patchProject(store.id, { public: to !== 'private', listed: to === 'gallery' });
      if (store.detail) {
        store.detail.public = p.public;
        store.detail.listed = p.listed;
      }
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = null;
    }
  }

  function pickLevel(to: Level) {
    if (to === level) asking = null;
    else if (LEVELS.indexOf(to) > LEVELS.indexOf(level)) asking = to;
    else setLevel(to);
  }

  let copiedWhat = $state<string | null>(null);
  async function copyLink(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      copiedWhat = url;
      setTimeout(() => (copiedWhat = null), 1800);
    } catch {
      prompt('URL', url);
    }
  }

  // The Axo shop (axo.kz) when the server has it connected (/api/me): the version goes into its cart as a design. Not for
  // a device, whose order is the whole device, not one printed part
  let axoOff = $state(false);
  const axoShown = $derived(!!session.me?.axo_cart && !axoOff && store.detail?.pack !== 'device');
  let axoReplace = $state<string | null>(null);
  $effect(() => {
    axoReplace = axoDesign(store.id);
  });
  const AXO_ERR: Record<string, string> = {
    not_configured: 'err_axo_off',
    axo_unavailable: 'err_axo_down',
    axo_auth: 'err_axo_auth',
    axo_too_large: 'err_axo_large',
  };

  async function toAxo() {
    busy = 'axo';
    error = null;
    try {
      const r = await api.axoCart(store.id, { version: store.version || undefined, ...(axoReplace ? { replace: axoReplace } : {}) });
      // the cart line holds the new design now: a second update replaces that one
      if (axoReplace && r.design_id) rememberAxoDesign(store.id, (axoReplace = r.design_id));
      window.location.href = r.url;
    } catch (e) {
      busy = null;
      const code = e instanceof ApiError ? e.code : undefined;
      if (code === 'not_configured') axoOff = true;
      error = code === 'axo_rejected' ? t('err_axo_rejected', { d: (e as ApiError).message }) : code && AXO_ERR[code] ? t(AXO_ERR[code]) : errorText(e);
    }
  }
</script>

<!-- back from the shop with the browser's Back button: the page comes from the cache with the spinner still on -->
<svelte:window onpageshow={(e) => e.persisted && busy === 'axo' && (busy = null)} />

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
      {#if axoShown}
        <div class="axo">
          <button class="btn" onclick={toAxo} disabled={!store.source || !store.version || busy === 'axo'}>
            {#if busy === 'axo'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name={axoReplace ? 'refresh' : 'external'} size={15} />{/if}
            {axoReplace ? t('axo_update') : t('axo_add')}
          </button>
          <span class="muted xs">{t('axo_note')}</span>
        </div>
      {/if}
    </section>

    <section class="stack">
      <h4 class="section-title">{t('publish_title')}</h4>
      <div class="levels" role="radiogroup" aria-label={t('publish_title')}>
        {#each LEVELS as l (l)}
          <label class="level" class:on={(asking ?? level) === l}>
            <input type="radio" name="publish" checked={(asking ?? level) === l} disabled={busy === 'publish'} onchange={() => pickLevel(l)} />
            <span>
              <strong class="small">{t(`publish_${l}`)}</strong>
              <span class="muted xs">{t(`publish_${l}_d`)}</span>
            </span>
          </label>
        {/each}
      </div>
      {#if asking}
        <div class="asking" role="alert">
          <p class="small">
            <Icon name="alert" size={14} /> {t('publish_warn')}
            {#if photos}<strong>{t('publish_photos', { n: photos })}</strong>{/if}
          </p>
          <div class="row">
            <button class="btn small primary" onclick={() => asking && setLevel(asking)}>{t('publish_confirm')}</button>
            <button class="btn small ghost" onclick={() => (asking = null)}>{t('publish_cancel')}</button>
          </div>
        </div>
      {/if}
      {#if store.detail?.public}
        <div class="row">
          {#if store.source}
            <button class="btn small" onclick={() => copyLink(recipeUrl)}>
              <Icon name={copiedWhat === recipeUrl ? 'check' : 'copy'} size={14} /> {copiedWhat === recipeUrl ? t('link_copied') : t('copy_link')}
            </button>
          {/if}
          {#if hasRun}
            <button class="btn small" onclick={() => copyLink(replayUrl)}>
              <Icon name={copiedWhat === replayUrl ? 'check' : 'play'} size={14} /> {copiedWhat === replayUrl ? t('link_copied') : t('copy_replay_link')}
            </button>
          {/if}
          <a class="btn small" href={xUrl} target="_blank" rel="noopener noreferrer">
            <span class="x" aria-hidden="true">𝕏</span> {t('share_x')}
          </a>
          {#if store.source}<a class="btn small ghost" href="/r/{store.id}" target="_blank" rel="noopener">{t('recipe')} ↗</a>{/if}
        </div>
      {/if}
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
  .levels {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .level {
    display: flex;
    gap: var(--space-2);
    align-items: flex-start;
    padding: 8px 10px;
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-btn);
    cursor: pointer;
  }
  .level.on {
    border-color: var(--primary);
  }
  .level > span {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .asking {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: 10px;
    border-radius: var(--radius-btn);
    background: var(--surface-high);
  }
  .asking p {
    margin: 0;
  }
  .quote select {
    width: auto;
  }
  .axo {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
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
