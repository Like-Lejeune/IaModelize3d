<script lang="ts">
  // The price stage's side: how many, the order, the fab files, past orders. The total stands in the main view. The order is
  // the Axo shop's: the whole device goes to its cart as one batch and the buyer pays there, delivery included.
  import Icon from '$lib/components/Icon.svelte';
  import { ApiError, errorText } from '$lib/api';
  import { axoDesign, rememberAxoDesign } from '$lib/components/GetItPanel.svelte';
  import { t } from '$lib/i18n.svelte';
  import { session } from '$lib/session.svelte';
  import { deviceApi } from './api';
  import type { QuoteState } from './quote.svelte';
  import { dt, usd } from './i18n';

  let { q, built, stale = false, readonly = false, files, projectId }: { q: QuoteState; built: boolean; stale?: boolean; readonly?: boolean; files: Record<string, string>; projectId: string } = $props();

  const FILE_LABEL: Record<string, string> = { 'gerbers.zip': 'Gerber', 'bom.csv': 'BOM', 'cpl.csv': 'CPL' };
  const AXO_ERR: Record<string, string> = { not_configured: 'err_axo_off', axo_unavailable: 'err_axo_down', axo_auth: 'err_axo_auth', axo_too_large: 'err_axo_large' };

  let sending = $state(false);
  let axoOff = $state(false);
  let error = $state<string | null>(null);
  let axoReplace = $state<string | null>(null);
  $effect(() => {
    axoReplace = axoDesign(projectId);
  });
  const shop = $derived(!!session.me?.axo_cart && !axoOff);
  const cartKzt = $derived(q.quote?.cart?.price_kzt ?? null);

  async function toAxo() {
    sending = true;
    error = null;
    try {
      const r = await deviceApi.axoCart(projectId, { qty: q.qty, ...(axoReplace ? { replace: axoReplace } : {}) });
      // the cart line holds the new design now: a second update replaces that one
      if (axoReplace && r.design_id) rememberAxoDesign(projectId, (axoReplace = r.design_id));
      window.location.href = r.url;
    } catch (e) {
      sending = false;
      const code = e instanceof ApiError ? e.code : undefined;
      if (code === 'not_configured') axoOff = true;
      error = code === 'axo_rejected' ? t('err_axo_rejected', { d: (e as ApiError).message }) : code && AXO_ERR[code] ? t(AXO_ERR[code]) : errorText(e);
    }
  }
</script>

<!-- back from the shop with the browser's Back button: the page comes from the cache with the spinner still on -->
<svelte:window onpageshow={(e) => e.persisted && (sending = false)} />

<div class="os">
  <section class="sec">
    <label class="qty">{dt('qty')}
      <span class="seg">
        {#each [1, 5, 10, 25, 50, 100] as n (n)}
          <button aria-pressed={q.qty === n} onclick={() => (q.qty = n)}>{n}</button>
        {/each}
      </span>
    </label>
    {#if !built}
      <p class="muted small">{dt('quote_need_build')}</p>
    {/if}
  </section>

  {#if !readonly && built && shop}
    <section class="sec">
      <button class="btn primary" onclick={toAxo} disabled={sending || stale || q.busy}>
        {#if sending}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name={axoReplace ? 'refresh' : 'external'} size={15} />{/if}
        {axoReplace ? t('axo_update') : dt('axo_device_add')}
      </button>
      {#if stale}
        <p class="xs muted">{dt('stale_order')}</p>
      {:else if cartKzt !== null}
        <p class="xs muted">{dt('axo_device_d', { qty: q.qty, kzt: cartKzt.toLocaleString('ru-RU') })}</p>
      {/if}
    </section>
  {/if}
  {#if error}<p class="err small" role="alert">{error}</p>{/if}

  {#if Object.keys(files).length}
    <section class="sec">
      <h4 class="cap">{dt('fab_files')}</h4>
      <div class="files">
        {#each Object.entries(files) as [n, url] (n)}<a class="btn small" class:primary={n === 'gerbers.zip'} href={url} download><Icon name="download" size={14} /> {FILE_LABEL[n] ?? n}</a>{/each}
      </div>
      <p class="xs muted">{dt('fab_files_d')}</p>
      {#if built}<a class="btn small" href={deviceApi.packageUrl(projectId, q.qty)} download><Icon name="download" size={14} /> {dt('device_package', { qty: q.qty })}</a>{/if}
    </section>
  {/if}

  {#if !readonly && built && !shop}<p class="soon">{dt('order_soon')}</p>{/if}
  {#if q.error}<p class="err small" role="alert">{q.error} <button class="btn small" onclick={() => q.retry()} disabled={q.busy}>{t('retry')}</button></p>{/if}
  {#if q.ordersError}<p class="err small" role="alert">{q.ordersError} <button class="btn small" onclick={() => q.loadOrders()}>{t('retry')}</button></p>{/if}

  {#if q.orders.length}
    <section class="sec">
      <h4 class="cap">{dt('orders')}</h4>
      <ul class="orders">
        {#each q.orders as o (o.id)}
          <li><span class="mono">{o.ref}</span><span class="small">{o.quantity} × · {usd(o.quote.total_usd)}</span><span class="chip xs">{dt(`status_${o.status}`)}</span></li>
        {/each}
      </ul>
    </section>
  {/if}
</div>

<style>
  .os {
    display: grid;
    gap: 10px;
  }
  .sec {
    display: grid;
    gap: var(--space-2);
  }
  .cap {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--on-surface-var);
  }
  .qty {
    display: grid;
    gap: 6px;
    font-size: var(--text-sm);
    color: var(--on-surface-var);
  }
  .seg {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 3px;
  }
  .seg button {
    font: inherit;
    font-size: var(--text-md);
    height: var(--bw-row, 26px);
    padding: 0;
    border-radius: var(--radius-xs);
    border: 1px solid var(--outline-variant);
    background: var(--surface-container-lowest);
    color: var(--on-surface);
    cursor: pointer;
  }
  .seg button[aria-pressed='true'] {
    background: var(--primary-container);
    color: var(--on-primary-container);
    border-color: var(--primary);
  }
  .total {
    display: grid;
    gap: 2px;
  }
  .total strong {
    font-size: var(--text-2xl);
  }
  .files {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .sec p,
  .soon {
    margin: 0;
  }
  .orders {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 6px;
  }
  .orders li {
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 8px;
    align-items: center;
  }
</style>
