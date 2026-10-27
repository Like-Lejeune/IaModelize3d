<script lang="ts">
  import Icon from './Icon.svelte';
  import { api, download, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';

  let { store, readonly = false, onPublish }: { store: ProjectStore; readonly?: boolean; onPublish?: () => void } = $props();

  const MATERIALS = ['PLA', 'PETG', 'ABS', 'ASA', 'TPU'];
  let busy = $state<string | null>(null);
  let error = $state<string | null>(null);
  let qty = $state(1);
  let material = $state('PLA');
  let color = $state('');
  let comment = $state('');
  let order = $state<Record<string, any> | null>(null);
  let copied = $state(false);

  async function dl(format: 'stl' | '3mf') {
    busy = format;
    error = null;
    const name = `${(store.detail?.title ?? 'model').replace(/[^\w-]+/g, '_').slice(0, 40)}.${format}`;
    const local = () => store.geom.exportFile({ source: store.source!, params: $state.snapshot(store.values), inputs: $state.snapshot(store.inputs), format, title: store.detail?.title });
    try {
      await download(readonly ? await local() : await api.exportFile(store.id, format, $state.snapshot(store.values)), name);
    } catch (e) {
      try {
        if (!store.source) throw e;
        await download(await local(), name);
      } catch (e2) {
        error = errorText(e2);
      }
    } finally {
      busy = null;
    }
  }

  async function placeOrder() {
    busy = 'order';
    error = null;
    try {
      order = await api.order(store.id, { quantity: qty, material, color: color || undefined, comment: comment || undefined });
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = null;
    }
  }

  async function copyLink() {
    const url = `${location.origin}/r/${store.id}`;
    try {
      await navigator.clipboard.writeText(url);
      copied = true;
      setTimeout(() => (copied = false), 1800);
    } catch {
      prompt('URL', url);
    }
  }
</script>

<div class="getit">
  <section class="stack">
    <div class="row">
      <button class="btn primary" onclick={() => dl('3mf')} disabled={!store.source || busy === '3mf'}>
        {#if busy === '3mf'}<span class="spin"></span>{:else}<Icon name="download" size={16} />{/if} {t('download_3mf')}
      </button>
      <button class="btn" onclick={() => dl('stl')} disabled={!store.source || busy === 'stl'}>{t('download_stl')}</button>
    </div>
  </section>

  {#if !readonly}
    <section class="stack">
      <h4 class="section-title">{t('order')}</h4>
      <p class="muted small">{t('order_hint')}</p>
      {#if order}
        <div class="done card">
          {#if order.checkout_url}
            <strong>{t('order_done')}</strong>
            <a class="btn primary" href={order.checkout_url} target="_blank" rel="noopener noreferrer">{t('open_checkout')} ↗</a>
          {:else}
            <span class="small">{order.message ?? order.status}</span>
          {/if}
        </div>
      {:else}
        <div class="form">
          <label class="field">{t('quantity')}<input type="number" min="1" max="50" bind:value={qty} /></label>
          <label class="field">{t('material')}<select bind:value={material}>{#each MATERIALS as m (m)}<option>{m}</option>{/each}</select></label>
          <label class="field">{t('color')}<input type="text" bind:value={color} placeholder="black" /></label>
          <label class="field wide">{t('comment')}<input type="text" bind:value={comment} /></label>
        </div>
        <button class="btn" onclick={placeOrder} disabled={!store.source || busy === 'order'}>
          {#if busy === 'order'}<span class="spin"></span>{:else}<Icon name="package" size={15} />{/if} {t('order')}
        </button>
      {/if}
    </section>

    <section class="stack">
      <h4 class="section-title">{t('share')}</h4>
      <p class="muted small">{t('share_hint')}</p>
      <div class="row">
        <button class="btn small" onclick={onPublish}>
          <Icon name={store.detail?.public ? 'lock' : 'globe'} size={14} /> {store.detail?.public ? t('unpublish') : t('publish')}
        </button>
        {#if store.detail?.public}
          <button class="btn small" onclick={copyLink}><Icon name={copied ? 'check' : 'copy'} size={14} /> {copied ? t('link_copied') : t('share')}</button>
          <a class="btn small ghost" href="/r/{store.id}" target="_blank" rel="noopener">{t('recipe')} ↗</a>
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
  .form {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }
  .form .wide {
    grid-column: 1 / -1;
  }
  .form input,
  .form select {
    width: 100%;
  }
  .done {
    padding: 10px;
    display: flex;
    gap: 10px;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
  }
  .err {
    color: var(--err);
  }
  p {
    margin: 0;
  }
</style>
