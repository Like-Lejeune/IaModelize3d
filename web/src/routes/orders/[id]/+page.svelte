<script lang="ts">
  // One order, from the request to "I got it": what was read, the price (range, then OrcaSlicer's), the farm's
  // steps with times, the QC overlay, the tracking number. Polls every 3 s while something is moving.
  // A showcase order opened by anyone else reads the same without the customer in it (actor 'public').
  import { onMount, tick } from 'svelte';
  import { page } from '$app/state';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { api } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import IntakeCard from '$lib/shop/IntakeCard.svelte';
  import OrderTimeline from '$lib/shop/OrderTimeline.svelte';
  import QcReport from '$lib/shop/QcReport.svelte';
  import QuoteCard from '$lib/shop/QuoteCard.svelte';
  import { shop, shopError } from '$lib/shop/api';
  import { carrierText, orderTitle, problemText, st, statusTone, when } from '$lib/shop/i18n';
  import type { Order, QcReport as Qc, ShopMe } from '$lib/shop/types';

  const id = $derived(page.params.id ?? '');
  let order = $state<Order | null>(null);
  // an action's failure stays until the next action; a failed poll has its own line, cleared by the next good one
  let error = $state<string | null>(null);
  let loadError = $state<string | null>(null);
  let missing = $state(false);
  let gone = false; // a 404: nothing more to poll for
  let photos = $state<{ url: string; role: string }[]>([]);
  let busy = $state<string | null>(null);
  // in the catalog: the order says so (its owner's listing), or it was shared from this page a moment ago
  let sharedNow = $state(false);
  const shared = $derived(sharedNow || !!order?.own_listing?.public);
  const operator = $derived(order?.actor === 'operator');
  const outsider = $derived(order?.actor === 'public');
  // an operator's own order reads as the customer's (they pay and confirm it here), and still gets the showcase switch
  let me = $state<ShopMe | null>(null);
  const farm = $derived(operator || (!!me?.is_operator && !outsider));

  const FINAL = ['delivered', 'refused', 'cancelled', 'expired'];
  const qc = $derived<Qc | null>(order?.qc && ('max_mm' in order.qc || 'error' in order.qc) ? (order.qc as Qc) : null);
  const kind = $derived(order?.intake?.request?.kind ?? 'listing');
  // the design stopped (no model, or one that fails its checks): the order waits, it is not being designed
  const paused = $derived(!!order && ['no_model', 'design_unfinished', 'design_unreviewed', 'step_failed'].includes(order.problem?.code ?? '') && !FINAL.includes(order.status));
  const hint = $derived.by(() => {
    if (!order) return '';
    if (order.status === 'designing' && !paused) return st('order.designing_hint');
    if (order.status === 'printing') return st('order.printing_hint');
    if (order.status === 'qc') return st('order.qc_hint');
    if (order.status === 'delivered' && !outsider) return st('order.delivered_hint');
    return '';
  });

  // a link to a part of the page (the board's QC chip opens #qc): the page is there only once the order is
  let jumped = false;
  async function load() {
    try {
      const o = await shop.order(id);
      if (order && o.updated_at < order.updated_at) return; // an older answer than the one an action gave
      order = o;
      loadError = null;
      missing = false;
      if (!photos.length && o.intake?.request?.kind === 'photo' && o.intake.request.photos?.length) loadPhotos(o);
      if (!jumped && location.hash.length > 1) {
        jumped = true;
        await tick();
        document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView({ block: 'start' });
      }
    } catch (e) {
      const status = (e as { status?: number }).status;
      gone = status === 404;
      // a refusal in the middle of watching an order is a hiccup, not a lost order
      if (gone || (status === 403 && !order)) missing = true;
      loadError = shopError(e);
    }
  }

  // the request's photos live in the order's own project (the customer's)
  async function loadPhotos(o: Order) {
    try {
      const p = await api.project(o.project_id);
      const role = new Map((o.intake.request?.photos ?? []).map((ph) => [ph.id, ph.role]));
      photos = p.assets.filter((a) => role.has(a.id)).map((a) => ({ url: a.thumb_url || a.url, role: role.get(a.id) ?? 'part' }));
    } catch {
      /* the operator's view of someone else's project: no thumbnails */
    }
  }

  onMount(() => {
    load();
    shop.me().then((m) => (me = m)).catch(() => {});
    const t = setInterval(() => {
      if (document.visibilityState !== 'visible' || gone || order?.actor === 'public') return;
      // a finished order changes no more; one in progress is checked every 3 s
      if (!order || !FINAL.includes(order.status)) load();
    }, 3000);
    return () => clearInterval(t);
  });

  function changed(o: Order) {
    order = { ...o, timeline: order?.timeline };
    load();
  }

  async function run(what: string, call: () => Promise<unknown>) {
    busy = what;
    error = null;
    try {
      const r = await call();
      if (r && typeof r === 'object' && 'status' in r) changed(r as Order);
    } catch (e) {
      error = shopError(e);
    } finally {
      busy = null;
    }
  }
</script>

<svelte:head><title>{order ? st('order.title', { ref: order.ref }) : st('parts.title')} · Formwright</title></svelte:head>

<div class="page">
  <Header />
  <main class="wrap">
    <a class="back small" href={outsider ? '/parts' : '/parts#orders'}><Icon name="arrow-left" size={15} /> {outsider ? st('parts.title') : st('order.back')}</a>

    {#if missing}
      <div class="empty card">
        <Icon name="package" size={28} />
        <p>{st('order.not_found')}</p>
        <a class="btn" href="/parts">{st('nav.parts')}</a>
      </div>
    {:else if !order}
      {#if loadError}<p class="err small" role="alert">{loadError} <button class="btn small" onclick={load}>{t('retry')}</button></p>{:else}<div class="card sk"></div>{/if}
    {:else}
      <div class="head">
        <div class="ttl">
          <div class="row">
            <span class="chip mono">{order.ref}</span>
            <span class="chip {paused ? 'warn' : statusTone(order.status)}">
              {#if order.working}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{/if}
              {paused ? st('order.paused') : st(`status.${order.status}`)}
            </span>
            <span class="xs muted">{when(order.created_at)}</span>
          </div>
          <h1>{orderTitle(order)}</h1>
          {#if hint}<p class="muted small">{hint}</p>{/if}
        </div>
        {#if farm && ['shipped', 'delivered'].includes(order.status)}
          <div class="row show">
            {#if order.showcase}<span class="chip ok"><Icon name="eye" size={12} /> {st('order.showcase_shown')}</span>{/if}
            <button class="btn small" class:ghost={order.showcase} disabled={!!busy} onclick={() => run('showcase', () => shop.showcase(order!.id, !order!.showcase))}>
              {#if busy === 'showcase'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="eye" size={14} />{/if}
              {order.showcase ? st('order.showcase_off') : st('order.showcase_on')}
            </button>
          </div>
        {/if}
      </div>

      {#if outsider}
        <p class="showcase small" role="note">
          <Icon name="eye" size={15} /> <span>{st('order.showcase')}</span>
          {#if order.printer?.name}<span class="chip"><Icon name="printer" size={12} /> {st('order.printed_on', { p: order.printer.name })}</span>{/if}
        </p>
        <!-- the rest of the loop: how the part was designed (when that run is public) and the card to order it again -->
        {#if order.project?.id || order.listing_id}
          <div class="row next">
            {#if order.listing_id}<a class="btn primary" href="/parts?listing={order.listing_id}"><Icon name="package" size={15} /> {st('order.order_same')}</a>{/if}
            {#if order.project?.id}<a class="btn" href="/p/{order.project.id}"><Icon name="play" size={15} /> {st('order.watch_design')}</a>{/if}
          </div>
        {/if}
      {/if}

      <OrderTimeline {order} show="rail" />

      {#if order.problem?.code && !FINAL.includes(order.status)}
        <p class="problem small" role="status">
          <Icon name="alert" size={15} /> <strong>{st('order.paused')}</strong>
          {order.problem.code === 'no_model' && order.actor === 'customer' ? st('order.no_model_next') : problemText(order.problem, operator)}
        </p>
      {/if}
      {#if error ?? loadError}<p class="err small" role="alert">{error ?? loadError}</p>{/if}

      <div class="grid">
        <div class="main">
          {#if kind !== 'listing'}
            <IntakeCard {order} {photos} onChange={changed} />
          {/if}

          {#if qc}
            <div id="qc"><QcReport {qc} {operator} /></div>
          {/if}

          {#if order.status === 'shipped' || order.status === 'delivered' || order.shipping?.tracking}
            <section class="card ship">
              <div class="row">
                <Icon name="send" size={18} />
                {#if order.delivery?.method === 'pickup'}
                  <strong>{st('order.pickup_ready')}</strong>
                {:else}
                  <!-- a showcase order keeps its parcel's number to itself -->
                  <span class="muted small">{outsider ? st('status.shipped') : st('order.tracking')}</span>
                  <strong class="mono">{carrierText(order.shipping?.carrier)} {order.shipping?.tracking ?? ''}</strong>
                {/if}
                {#if order.shipping?.at}<span class="xs muted">· {when(order.shipping.at)}</span>{/if}
              </div>
              <!-- the customer's own button: the farm's view of someone else's order does not press it for them -->
              {#if order.status === 'shipped' && order.next.includes('delivered') && order.actor === 'customer'}
                <button class="btn primary large" disabled={!!busy} onclick={() => run('delivered', () => shop.delivered(order!.id))}>
                  {#if busy === 'delivered'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="check" size={18} />{/if}
                  {st('order.received')}
                </button>
                <p class="xs muted">{st('order.received_hint')}</p>
              {/if}
              {#if order.status === 'delivered' && order.actor === 'customer'}
                <div class="row">
                  <a class="btn" href="/parts#mine"><Icon name="refresh" size={15} /> {st('parts.order_again')}</a>
                  {#if qc?.pass && kind !== 'listing' && !shared}
                    <button class="btn ghost" disabled={!!busy} onclick={() => run('share', async () => (await shop.share({ project_id: order!.project_id, public: true }), (sharedNow = true)))}>
                      <Icon name="share" size={15} /> {st('parts.share')}
                    </button>
                  {:else if shared}
                    <span class="chip ok"><Icon name="check" size={12} /> {st('parts.shared')}</span>
                  {/if}
                </div>
                {#if qc?.pass && kind !== 'listing' && !shared}<p class="xs muted">{st('order.share_hint')}</p>{/if}
              {/if}
            </section>
          {/if}

          <section class="card log"><OrderTimeline {order} show="log" /></section>
        </div>

        <aside class="side" class:lead={['quoted', 'paid'].includes(order.status)}>
          {#if !['refused', 'cancelled'].includes(order.status) || order.quote?.total != null}
            <QuoteCard {order} onChange={changed} />
          {/if}
          {#if order.project?.cover}
            <figure class="card model">
              <img src={order.project.cover} alt={orderTitle(order)} />
              {#if kind !== 'listing' && order.actor === 'customer'}
                <a class="btn small ghost" href="/p/{order.project_id}"><Icon name="cube" size={14} /> {st('order.how')}</a>
              {/if}
            </figure>
          {:else if kind === 'photo' && order.actor === 'customer' && ['designing', 'needs_info'].includes(order.status)}
            <a class="btn" href="/p/{order.project_id}"><Icon name="cube" size={15} /> {st('order.how')}</a>
          {/if}
        </aside>
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
    padding: var(--space-5) var(--space-5) var(--space-8);
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .back {
    color: var(--outline);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    align-self: flex-start;
    text-decoration: none;
  }
  .back:hover {
    color: var(--on-surface);
  }
  .ttl {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
  h1 {
    font-size: var(--text-3xl);
    font-weight: var(--font-weight-semibold);
    overflow-wrap: anywhere;
  }
  .ttl p {
    margin: 0;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .head .ttl {
    flex: 1 1 320px;
  }
  .show {
    gap: var(--space-2);
  }
  .showcase {
    margin: 0;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-btn);
    background: var(--surface-container);
    color: var(--on-surface-var);
    display: flex;
    gap: var(--space-2);
    align-items: center;
    flex-wrap: wrap;
  }
  .next {
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 380px);
    gap: var(--space-4);
    align-items: start;
  }
  .main,
  .side {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    min-width: 0;
  }
  .side {
    position: sticky;
    top: calc(var(--header-h, 68px) + var(--space-4));
  }
  .ship {
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .ship .row {
    gap: var(--space-2);
  }
  .ship p {
    margin: 0;
  }
  .ship > .btn {
    align-self: flex-start;
  }
  .log {
    padding: var(--space-4);
  }
  .model {
    margin: 0;
    padding: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    align-items: center;
  }
  .model img {
    width: 100%;
    max-height: 260px;
    object-fit: contain;
    background: var(--render-bg);
    border-radius: var(--radius-btn);
  }
  .problem {
    margin: 0;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-btn);
    background: color-mix(in srgb, var(--warn) 14%, transparent);
    color: var(--on-surface);
    display: flex;
    gap: var(--space-2);
    align-items: baseline;
    flex-wrap: wrap;
    overflow-wrap: anywhere;
  }
  .problem strong {
    color: var(--warn-text);
  }
  .err {
    color: var(--error);
    margin: 0;
  }
  .sk {
    height: 320px;
    animation: sk-pulse var(--t-skeleton) ease-in-out infinite;
  }
  .empty {
    padding: var(--space-7) var(--space-4);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-3);
    text-align: center;
    color: var(--outline);
  }
  .empty p {
    margin: 0;
    color: var(--on-surface-var);
  }
  @media (max-width: 860px) {
    .grid {
      grid-template-columns: minmax(0, 1fr);
    }
    .side {
      position: static;
    }
    /* on a phone the price goes first once there is one to pay */
    .side.lead {
      order: -1;
    }
  }
  @media (max-width: 520px) {
    .wrap {
      padding: var(--space-4) var(--space-4) var(--space-7);
    }
  }
</style>
