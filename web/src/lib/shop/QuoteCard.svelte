<script lang="ts">
  // The price of an order. First the kernel's instant range (not payable), then the binding quote from an
  // OrcaSlicer run of the exact file the farm will print: grams, minutes, the breakdown, the ETA, and "Pay".
  // A ready model is priced while Muse Spark 1.3 reads the request: Pay stays off until that safety check clears, and
  // with "choose for me" until the price is in the material the intake picked. An expired price is sliced again on
  // request. Cancelling asks once more, inline.
  import { onMount } from 'svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { t } from '$lib/i18n.svelte';
  import { shop, shopError } from './api';
  import { day, grams, kzt, minutes, money, moneyRange, st, usd } from './i18n';
  import type { DeliveryMethod, Order, Tariff } from './types';

  let { order, onChange }: { order: Order; onChange?: (o: Order) => void } = $props();

  const q = $derived(order.quote ?? {});
  const has = $derived(q.total != null);
  const firm = $derived(!!q.binding);
  const customer = $derived(order.actor === 'customer');
  const canPay = $derived(customer && order.status === 'quoted' && order.next.includes('paid'));
  // the price is there, the intake's verdict is not (yet), or "choose for me" is pricing the material it chose: Pay is
  // shown, and off
  const updating = $derived(customer && order.status === 'quoted' && !!order.working && order.safety === 'ok');
  // ... and when that slice failed: the price stays in the first material, Pay off, until the slicer's next try
  const due = $derived(customer && order.status === 'quoted' && order.safety === 'ok' && !!order.material_due);
  const waiting = $derived(customer && order.status === 'quoted' && (order.safety === 'pending' || order.safety === 'held' || updating || due));
  const revive = $derived(customer && order.status === 'expired' && order.next.includes('quoted'));
  // OrcaSlicer runs once there is a model: right away for a catalog or studio part (while the intake reads it), after
  // the design for a new one
  const slicing = $derived(
    order.working &&
      !order.problem?.code &&
      (order.status === 'quoted' ||
        (order.intake?.request?.kind === 'photo' ? order.status === 'designing' && !!order.project?.version : order.status === 'requested')),
  );
  const pickup = $derived(q.delivery?.method === 'pickup');
  // the promise of a quote: while it can still come true (not once shipped, nor on an expired, cancelled or refused order)
  const promise = $derived(['requested', 'designing', 'needs_info', 'quoted', 'paid', 'printing', 'qc'].includes(order.status));

  let tariff = $state<Tariff | null>(null);
  let editing = $state(false);
  let qty = $state(1);
  let material = $state('PLA');
  let delivery = $state<DeliveryMethod>('courier');
  let busy = $state<string | null>(null);
  let error = $state<string | null>(null);
  let asking = $state(false); // "Cancel order" pressed once: the card asks before it cancels

  onMount(() => {
    shop.tariff().then((t) => (tariff = t)).catch(() => {});
  });

  function edit() {
    qty = q.quantity ?? order.quantity;
    // "choose for me": the intake's pick, until the customer picks one here
    material = order.material_due ?? q.material ?? order.material;
    delivery = q.delivery?.method ?? order.delivery?.method ?? 'courier';
    editing = !editing;
  }

  async function run(what: string, call: () => Promise<Order>) {
    busy = what;
    error = null;
    try {
      onChange?.(await call());
      if (what === 'requote') editing = false;
    } catch (e) {
      error = shopError(e);
    } finally {
      busy = null;
    }
  }
</script>

{#snippet confirmCancel()}
  <div class="row foot ask" role="group" aria-label={st('quote.cancel_ask')}>
    <span class="small">{st('quote.cancel_ask')}</span>
    <span class="spacer"></span>
    <!-- the two answers stay together when a phone wraps the row -->
    <span class="row answers">
      <button class="btn small danger" disabled={!!busy} onclick={() => run('cancel', () => shop.cancel(order.id))}>
        {#if busy === 'cancel'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{/if}
        {st('quote.cancel_yes')}
      </button>
      <button class="btn small ghost" disabled={!!busy} onclick={() => (asking = false)}>{st('quote.cancel_no')}</button>
    </span>
  </div>
{/snippet}

<section class="quote card" class:firm class:stale={order.status === 'expired'}>
  <div class="row head">
    <h3 class="section-title">{st('quote.title')}</h3>
    {#if firm && q.source === 'orca'}
      <span class="chip ok"><Icon name="layers" size={13} /> {st('quote.by_orca', { s: q.slice_seconds != null ? Math.round(q.slice_seconds) : '—' })}</span>
    {:else if firm}
      <span class="chip ok"><Icon name="user" size={13} /> {st('quote.by_operator')}</span>
    {:else if has}
      <span class="chip">{st('quote.estimate')}</span>
    {/if}
  </div>

  {#if !has}
    <p class="muted small">
      {#if slicing}<i class="ti ti-loader-2 spin" aria-hidden="true"></i> {st('quote.slicing')}{:else}{st('quote.waiting_model')}{/if}
    </p>
  {:else if !firm && q.range}
    <div class="big approx">≈ {moneyRange(q.range.total, q.range.total_usd)}</div>
    <p class="spec small">
      {grams(q.range.grams_each[0])}–{grams(q.range.grams_each[1])} · {minutes(q.range.minutes_each[0])}–{minutes(q.range.minutes_each[1])} {st('quote.per_piece')} · {st('intake.pcs', { n: q.quantity ?? order.quantity })} · {q.material}
    </p>
    <p class="muted xs">{st('quote.estimate_hint')}</p>
    {#if slicing || busy === 'requote'}
      <p class="row slicing small"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {st('quote.slicing')}</p>
    {/if}
  {:else}
    <div class="big">{kzt(q.total)} <span class="usd">({usd(q.usd?.total)})</span></div>
    <p class="spec small">
      <span class="mono">{grams(q.grams_each)}</span> · <span class="mono">{minutes(q.minutes_each)}</span> {st('quote.per_piece')} · {st('intake.pcs', { n: q.quantity ?? order.quantity })} · {q.material}
      {#if q.printer?.name}· {q.printer.name}{/if}
      · {q.supports ? st('quote.supports') : st('quote.no_supports')}
    </p>
    <dl class="lines small">
      <dt>{st('quote.unit', { n: q.quantity ?? 1 })} <span class="muted mono">· {kzt(q.unit_price)}</span></dt>
      <dd class="mono">{money(q.parts, q.usd?.parts)}</dd>
      {#if q.new_part_fee}
        <dt>{st('quote.new_part')}</dt>
        <dd class="mono">{money(q.new_part_fee, q.usd?.new_part_fee)}</dd>
      {/if}
      <dt>{st('quote.delivery')} · {st(`delivery.${q.delivery?.method ?? 'courier'}`)}{#if q.delivery?.days}, {st('days', { n: q.delivery.days })}{/if}</dt>
      <dd class="mono">{money(q.delivery?.price, q.usd?.delivery)}</dd>
      <dt class="total">{st('quote.total')}</dt>
      <dd class="total mono">{money(q.total, q.usd?.total)}</dd>
    </dl>
    <!-- the promise of a quote: once shipped, the order's own times say when -->
    {#if q.eta && promise}
      <p class="row eta small">
        <Icon name="package" size={15} />
        <span>{st('quote.ready', { d: day(q.eta.ready_by) })}</span>
        <span class="muted">·</span>
        <span>{pickup ? st('quote.pickup_from', { d: day(q.eta.ready_by) }) : st('quote.arrive', { d: day(q.eta.arrive_by) })}</span>
      </p>
    {/if}
    {#if q.cost && q.gross_margin != null}
      <p class="xs muted mono">{st('quote.farm', { c: kzt(q.cost.total), m: Math.round(q.gross_margin * 100) })}</p>
    {/if}
    <!-- the slicer's own warnings (English, technical) are the farm's to act on -->
    {#if !customer}{#each q.warnings ?? [] as w (w)}<p class="xs warn">{w}</p>{/each}{/if}
  {/if}

  {#if order.payment?.at}
    <p class="row paid small"><Icon name="check-circle" size={15} /> {st('quote.paid', { a: money(order.payment.amount, order.payment.amount_usd) })}</p>
  {/if}

  {#if canPay || waiting}
    {#if editing}
      <div class="form">
        <label class="field">{st('new.quantity')}<input type="number" min="1" max="200" bind:value={qty} /></label>
        <label class="field">{st('new.material')}
          <select bind:value={material}>{#each tariff?.materials ?? ['PLA', 'PETG', 'ASA', 'TPU'] as m (m)}<option>{m}</option>{/each}</select>
        </label>
        <label class="field wide">{st('new.delivery')}
          <select bind:value={delivery}>
            {#each ['pickup', 'courier', 'post'] as const as d (d)}
              <option value={d}>{st(`delivery.${d}`)}{tariff ? ` · ${kzt(tariff.delivery[d].price)}` : ''}</option>
            {/each}
          </select>
        </label>
      </div>
      <div class="row">
        <!-- the material goes only when picked here: it then is the customer's own, no longer "choose for me" -->
        <button class="btn" disabled={!!busy} onclick={() => run('requote', () => shop.requote(order.id, { quantity: Math.max(1, Math.min(200, Math.round(qty) || 1)), ...(material !== q.material ? { material } : {}), delivery }))}>
          {#if busy === 'requote'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i> {st('quote.recalc')}{:else}<Icon name="refresh" size={15} /> {st('quote.apply')}{/if}
        </button>
        <button class="btn ghost" disabled={!!busy} onclick={() => (editing = false)}>{t('close')}</button>
      </div>
    {:else}
      {#if waiting}
        <p class="row safety small" role="status">
          {#if order.safety === 'pending'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i> {st('quote.safety_pending')}
          {:else if order.safety === 'held'}<Icon name="user" size={15} /> {st('quote.safety_held')}
          {:else if updating}<i class="ti ti-loader-2 spin" aria-hidden="true"></i> {order.material_due ? st('quote.updating', { m: order.material_due }) : st('order.working')}
          {:else}<Icon name="refresh" size={15} /> {st('quote.material_due', { m: order.material_due ?? '' })}{/if}
        </p>
      {/if}
      <button class="btn primary large block pay" disabled={!!busy || waiting} onclick={() => run('pay', () => shop.pay(order.id))}>
        {#if busy === 'pay'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="lock" size={17} />{/if}
        {st('quote.pay')} · {kzt(q.total)}
      </button>
      <p class="xs muted center">{waiting && order.safety === 'pending' ? st('quote.safety_hint') : st('quote.pay_hint')}</p>
      {#if asking}
        {@render confirmCancel()}
      {:else}
        <div class="row foot">
          <button class="btn small" disabled={!!busy} onclick={edit}><Icon name="sliders" size={14} /> {st('quote.change')}</button>
          {#if q.valid_until}<span class="xs muted">{st('quote.valid', { d: new Date(q.valid_until * 1000).toLocaleDateString() })}</span>{/if}
          <span class="spacer"></span>
          <button class="btn small ghost danger" disabled={!!busy} onclick={() => (asking = true)}>{st('quote.cancel')}</button>
        </div>
      {/if}
    {/if}
  {:else if revive}
    <p class="small muted">{st('quote.expired')}</p>
    <button class="btn primary block" disabled={!!busy} onclick={() => run('requote', () => shop.requote(order.id, {}))}>
      {#if busy === 'requote'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i> {st('quote.recalc')}{:else}<Icon name="refresh" size={16} /> {st('quote.fresh')}{/if}
    </button>
  {:else if customer && order.next.includes('cancelled') && order.status !== 'paid'}
    {#if asking}
      {@render confirmCancel()}
    {:else}
      <div class="row foot">
        <span class="spacer"></span>
        <button class="btn small ghost danger" disabled={!!busy} onclick={() => (asking = true)}>{st('quote.cancel')}</button>
      </div>
    {/if}
  {/if}
  {#if tariff && has}<p class="xs muted rate">{st('quote.rate', { r: q.usd?.rate ?? tariff.usd_kzt })}</p>{/if}
  {#if error}<p class="err small" role="alert">{error}</p>{/if}
</section>

<style>
  .quote {
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .quote.firm {
    border-color: color-mix(in srgb, var(--primary) 45%, var(--outline-variant));
  }
  /* an expired price stays readable, but it is not the one to pay */
  .stale .big,
  .stale .spec,
  .stale .lines,
  .stale .eta {
    opacity: 0.55;
  }
  .head {
    justify-content: space-between;
  }
  .big {
    font-size: var(--text-card-price);
    font-weight: var(--font-weight-bold);
    letter-spacing: -0.4px;
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
    animation: land var(--dur-slow) var(--ease-settle);
  }
  .big.approx {
    font-size: var(--text-product-section-title);
    color: var(--on-surface-var);
  }
  .usd {
    font-size: var(--text-product-lead);
    color: var(--outline);
    font-weight: var(--font-weight-semibold);
  }
  @keyframes land {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
  }
  .spec {
    margin: 0;
    color: var(--on-surface-var);
  }
  .lines {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 6px var(--space-3);
    margin: 0;
    padding: var(--space-3) 0 0;
    border-top: var(--border-width) solid var(--divider);
  }
  dt {
    color: var(--on-surface-var);
    min-width: 0;
  }
  dd {
    margin: 0;
    text-align: right;
    white-space: nowrap;
  }
  .total {
    font-weight: var(--font-weight-bold);
    color: var(--on-surface);
    padding-top: 6px;
    border-top: var(--border-width) solid var(--divider);
  }
  .eta {
    margin: 0;
    color: var(--primary);
    gap: 6px;
  }
  .paid {
    margin: 0;
    color: var(--primary);
    gap: 6px;
  }
  .slicing {
    margin: 0;
    color: var(--primary);
  }
  .safety {
    margin: 0;
    gap: 6px;
    color: var(--warn-text);
  }
  .warn {
    color: var(--warn-text);
    margin: 0;
  }
  .form {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .form .wide {
    grid-column: 1 / -1;
  }
  .form input,
  .form select {
    width: 100%;
  }
  .pay {
    margin-top: var(--space-1);
  }
  .center {
    text-align: center;
    margin: -4px 0 0;
  }
  .foot {
    gap: var(--space-2);
  }
  .ask {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-btn);
    background: color-mix(in srgb, var(--error) 8%, transparent);
  }
  .answers {
    gap: var(--space-2);
    flex-wrap: nowrap;
  }
  .rate {
    margin: 0;
    text-align: right;
  }
  p {
    margin: 0;
  }
  .err {
    color: var(--error);
  }
</style>
