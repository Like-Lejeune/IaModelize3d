<script lang="ts">
  // The Manufacturing stage's side: how many, the total, the fab files, past orders. Placing an order from here comes
  // later (the workshop's order flow is not wired in yet): a note says so instead of a form.
  import Icon from '$lib/components/Icon.svelte';
  import type { QuoteState } from './quote.svelte';
  import { dt, usd, kzt, date } from './i18n';

  // `stale` (the schematic changed after the board on show) is taken for the order flow to come
  let { q, built, readonly = false, files }: { q: QuoteState; built: boolean; stale?: boolean; readonly?: boolean; files: Record<string, string> } = $props();

  const quote = $derived(q.quote);
  const FILE_LABEL: Record<string, string> = { 'gerbers.zip': 'Gerber', 'bom.csv': 'BOM', 'cpl.csv': 'CPL' };
</script>

<div class="os">
  <section class="sec">
    <label class="qty">{dt('qty')}
      <span class="seg">
        {#each [1, 5, 10, 25, 50, 100] as n (n)}
          <button aria-pressed={q.qty === n} onclick={() => (q.qty = n)}>{n}</button>
        {/each}
      </span>
    </label>
    {#if quote}
      <div class="total">
        <strong>{usd(quote.total_usd)}</strong>
        <span class="muted small">{kzt(quote.total_kzt)}</span>
        <span class="small">{dt('per_device', { p: usd(quote.per_device_usd) })} · {dt('ready_by', { d: date(quote.eta) })}</span>
      </div>
    {:else if !built}
      <p class="muted small">{dt('quote_need_build')}</p>
    {/if}
  </section>

  {#if Object.keys(files).length}
    <section class="sec">
      <h4 class="cap">{dt('fab_files')}</h4>
      <div class="files">
        {#each Object.entries(files) as [n, url] (n)}<a class="btn small" href={url} download><Icon name="download" size={14} /> {FILE_LABEL[n] ?? n}</a>{/each}
      </div>
      <p class="xs muted">{dt('fab_files_d')}</p>
    </section>
  {/if}

  {#if !readonly && built}<p class="xs muted soon">{dt('order_soon')}</p>{/if}
  {#if q.error}<p class="err small">{q.error}</p>{/if}

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
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--on-surface-var);
  }
  .qty {
    display: grid;
    gap: 6px;
    font-size: 12px;
    color: var(--on-surface-var);
  }
  .seg {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 3px;
  }
  .seg button {
    font: inherit;
    font-size: 13px;
    height: var(--bw-row, 26px);
    padding: 0;
    border-radius: 5px;
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
    font-size: 22px;
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
