<script lang="ts">
  // IaModelize3d Parts: the catalog of parts that were designed, checked and (most) printed and QC'd already, searched
  // by brand, model or part number, ordered with no design step; below it, your own parts and your orders. A delivered
  // order the farm shows to everyone is one click away ('See a delivered order').
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { plural, t } from '$lib/i18n.svelte';
  import { intentKey, shop, shopError } from '$lib/shop/api';
  import { kzt, money, moneyRange, mm, orderTitle, st, statusTone, when } from '$lib/shop/i18n';
  import type { DeliveryMethod, Listing, Order, Quote, ShowcaseCard, Tariff } from '$lib/shop/types';

  let q = $state('');
  let results = $state<Listing[] | null>(null);
  let mine = $state<Listing[] | null>(null);
  let orders = $state<Order[] | null>(null);
  let tariff = $state<Tariff | null>(null);
  let error = $state<string | null>(null);
  let mineError = $state<string | null>(null);

  let showcase = $state<ShowcaseCard | null>(null);

  // the one card being ordered, as '<section>:<listing id>': a part of yours is in the catalog and in "Your parts",
  // and only the copy that was clicked opens
  type Where = 'catalog' | 'mine';
  let open = $state<string | null>(null);
  const openId = $derived(open ? open.slice(open.indexOf(':') + 1) : null);
  let qty = $state(1);
  let delivery = $state<DeliveryMethod>('courier');
  let contact = $state('');
  let quote = $state<Quote | null>(null);
  let quoteError = $state<string | null>(null);
  let busy = $state<string | null>(null);
  let reporting = $state<string | null>(null);
  let reason = $state('');
  let notice = $state<string | null>(null);

  async function search() {
    try {
      results = await shop.listings(q.trim());
      error = null;
    } catch (e) {
      error = shopError(e);
    }
  }

  // a failed fetch keeps what is on the page and says so: never an empty list that was not empty
  async function loadMine() {
    const [l, o] = await Promise.allSettled([shop.myListings(), shop.orders()]);
    if (l.status === 'fulfilled') mine = l.value;
    if (o.status === 'fulfilled') orders = o.value;
    const failure = l.status === 'rejected' ? l.reason : o.status === 'rejected' ? o.reason : null;
    mineError = failure ? shopError(failure) : null;
  }

  // /parts?listing=<id> ('Order the same part' on a delivered order the farm shows): that card, open, in view
  async function openListing(id: string) {
    if (!results?.some((li) => li.id === id)) {
      try {
        const li = await shop.listing(id);
        results = [li, ...(results ?? [])];
      } catch {
        return; // taken down or private since
      }
    }
    qty = 1;
    open = `catalog:${id}`;
    setTimeout(() => document.getElementById(`li-${id}`)?.scrollIntoView({ block: 'center' }), 100);
  }

  onMount(() => {
    const want = page.url.searchParams.get('listing');
    search().then(() => {
      if (want) openListing(want);
    });
    loadMine();
    shop.tariff().then((t) => (tariff = t)).catch(() => {});
    shop.showcaseLatest().then((c) => (showcase = c)).catch(() => {});
    // the header's "Orders" link lands on this page's section
    if (location.hash === '#orders' || location.hash === '#mine') setTimeout(() => document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: 'start' }), 300);
    const id = setInterval(() => document.visibilityState === 'visible' && (mineError || orders?.some((o) => o.working || ['requested', 'designing'].includes(o.status))) && loadMine(), 8000);
    return () => clearInterval(id);
  });

  // search as you type, a moment after the last key
  let first = true;
  $effect(() => {
    void q;
    if (first) {
      first = false;
      return;
    }
    const h = setTimeout(search, 250);
    return () => clearTimeout(h);
  });

  // the instant range for the card being ordered, again when the quantity or delivery change
  $effect(() => {
    const key = open;
    const id = openId;
    const o = { quantity: Math.max(1, Math.min(200, Math.round(qty) || 1)), delivery };
    if (!id) return;
    quote = null;
    quoteError = null;
    const h = setTimeout(() => {
      shop
        .listingQuote(id, o)
        .then((r) => open === key && (quote = r))
        .catch((e) => (quoteError = shopError(e)));
    }, 200);
    return () => clearTimeout(h);
  });

  // the same order sent again (a lost answer, a second click) is the same order; another card or form is a new one
  let orderKey: string | null = null;
  $effect(() => {
    void [open, qty, delivery, contact];
    orderKey = null;
  });

  function toggle(li: Listing, where: Where) {
    reporting = null;
    if (open === `${where}:${li.id}`) {
      open = null;
      return;
    }
    qty = 1;
    open = `${where}:${li.id}`;
  }

  async function order(li: Listing) {
    busy = open;
    quoteError = null;
    orderKey ??= intentKey();
    try {
      const o = await shop.orderListing(li.id, { quantity: Math.max(1, Math.min(200, Math.round(qty) || 1)), delivery, contact }, orderKey);
      goto(`/orders/${o.id}`);
    } catch (e) {
      quoteError = shopError(e);
      busy = null;
    }
  }

  async function publish(li: Listing) {
    busy = `share_${li.id}`;
    notice = null;
    try {
      await shop.share({ project_id: li.project_id, public: true });
      await Promise.all([loadMine(), search()]);
    } catch (e) {
      notice = shopError(e);
    } finally {
      busy = null;
    }
  }

  async function report(li: Listing) {
    busy = `report_${li.id}`;
    try {
      // an anonymous report waits for the farm unless enough people sent one (shop/routes.py report_listing)
      const r = await shop.report(li.id, reason);
      reporting = null;
      reason = '';
      notice = st(r.flagged ? 'parts.reported' : 'parts.reported_queued');
      await search();
    } catch (e) {
      notice = shopError(e);
    } finally {
      busy = null;
    }
  }

  const fits = (li: Listing) => li.compatible_with || li.part_numbers?.join(', ') || '';
  const ordersOf = (n: number) => plural(n, ['order', 'orders'], ['заказ', 'заказа', 'заказов']);
</script>

<svelte:head><title>{st('parts.title')} · IaModelize3d</title></svelte:head>

{#snippet card(li: Listing, where: Where)}
  {@const key = `${where}:${li.id}`}
  <article class="li card" class:open={open === key} id={where === 'catalog' ? `li-${li.id}` : undefined}>
    <div class="pic">
      {#if li.cover}<img src={li.cover} alt={orderTitle(li)} loading="lazy" />{:else}<Icon name="cube" size={30} />{/if}
      {#if li.mine}<span class="chip own">{li.public ? st('parts.shared') : st('parts.private')}</span>{/if}
    </div>
    <div class="meta">
      <strong class="name">{orderTitle(li)}</strong>
      {#if fits(li)}<span class="xs fits">{li.compatible_with ? st('parts.compatible', { x: li.compatible_with }) : ''}{#if li.part_numbers?.length}<span class="mono">{' · '}№ {li.part_numbers.join(', ')}</span>{/if}</span>{/if}
      <div class="badges">
        {#if li.verified?.printable}<span class="chip ok"><Icon name="check" size={11} /> {st('badge.printable')}</span>{/if}
        {#if li.verified?.critic === 'pass'}<span class="chip ok"><Icon name="eye" size={11} /> {st('badge.critic')}</span>{/if}
        {#if li.verified?.qc_pass === true && li.verified.qc_max_mm != null}<span class="chip ok mono"><Icon name="ruler" size={11} /> {st('badge.qc', { n: mm(li.verified.qc_max_mm) })}</span>{/if}
        {#if li.orders}<span class="chip">{ordersOf(li.orders)}</span>{/if}
        {#if li.verified?.seeded && !li.verified.qc_pass}<span class="chip" title={st('parts.seeded')}><Icon name="info" size={11} /></span>{/if}
        <span class="chip">{li.material}</span>
      </div>
    </div>

    {#if open === key}
      <div class="buy">
        <div class="buyrow">
          <label class="field">{st('new.quantity')}<input type="number" min="1" max="200" bind:value={qty} /></label>
          <label class="field">{st('new.delivery')}
            <select bind:value={delivery}>
              {#each ['courier', 'post', 'pickup'] as const as d (d)}<option value={d}>{st(`delivery.${d}`)}{tariff ? ` · ${kzt(tariff.delivery[d].price)}` : ''}</option>{/each}
            </select>
          </label>
        </div>
        <input type="text" bind:value={contact} placeholder={st('new.contact')} maxlength="200" aria-label={st('new.contact')} />
        <div class="quote">
          {#if quote?.range}
            <strong>≈ {moneyRange(quote.range.total, quote.range.total_usd)}</strong>
            <span class="xs muted">{st('parts.no_design')}</span>
          {:else if !quoteError}
            <span class="xs muted"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></span>
          {/if}
        </div>
        <!-- a failed order as well as a failed price: it shows whatever the price above says -->
        {#if quoteError}<p class="xs err" role="alert">{quoteError}</p>{/if}
        <button class="btn primary block" disabled={busy === key} onclick={() => order(li)}>
          {#if busy === key}<i class="ti ti-loader-2 spin" aria-hidden="true"></i> {st('parts.ordering')}{:else}<Icon name="package" size={16} /> {st('parts.order')}{/if}
        </button>
      </div>
    {/if}

    {#if reporting === li.id}
      <div class="buy">
        <input type="text" bind:value={reason} placeholder={st('parts.report_ph')} maxlength="500" aria-label={st('parts.report')} />
        <div class="row">
          <button class="btn small danger" disabled={busy === `report_${li.id}`} onclick={() => report(li)}>{st('parts.report_send')}</button>
          <button class="btn small ghost" onclick={() => (reporting = null)}>×</button>
        </div>
      </div>
    {/if}

    <div class="row acts">
      <button class="btn small" class:primary={open !== key} onclick={() => toggle(li, where)}>
        {#if open === key}×{:else}<Icon name="package" size={14} /> {li.mine ? st('parts.order_again') : st('parts.order')}{/if}
      </button>
      {#if li.mine && !li.public}
        <button class="btn small ghost" disabled={busy === `share_${li.id}`} onclick={() => publish(li)}><Icon name="share" size={13} /> {st('parts.share')}</button>
      {:else if !li.mine}
        <button class="btn small ghost report" onclick={() => ((reporting = reporting === li.id ? null : li.id), (open = null))}>{st('parts.report')}</button>
      {/if}
    </div>
  </article>
{/snippet}

<div class="page">
  <Header />
  <main class="wrap">
    <section class="hero">
      <div class="lead">
        <h1>{st('parts.title')}</h1>
        <p>{st('parts.lead')}</p>
      </div>
      <form class="search" role="search" onsubmit={(e) => (e.preventDefault(), search())}>
        <Icon name="search" size={18} />
        <input type="search" bind:value={q} placeholder={st('parts.search_ph')} aria-label={st('parts.search')} />
      </form>
      <a class="btn primary large cta" href="/parts/new"><Icon name="camera" size={18} /> {st('parts.new_cta')}</a>
      {#if showcase}
        <a class="shown card" href="/orders/{showcase.id}">
          <span class="sthumb">{#if showcase.cover}<img src={showcase.cover} alt="" loading="lazy" />{:else}<Icon name="package" size={18} />{/if}</span>
          <span class="stext">
            <strong class="small">{st('parts.showcase')} <Icon name="arrow-right" size={13} /></strong>
            <span class="xs muted">{orderTitle(showcase)} · <span class="mono">{showcase.ref}</span>{showcase.qc_pass ? ` · ${st('order.qc_passed')}` : ''}</span>
            <span class="xs muted">{st('parts.showcase_hint')}</span>
          </span>
        </a>
      {/if}
    </section>

    {#if error}<p class="err small" role="alert">{error} <button class="btn small" onclick={search}>{t('retry')}</button></p>{/if}
    {#if notice}<p class="notice small" role="status">{notice}</p>{/if}

    <section class="sect">
      <div class="bhead">
        <h2>{st('parts.catalog')}</h2>
        <span class="muted small">{st('parts.catalog_hint')}</span>
      </div>
      {#if results === null}
        {#if !error}<div class="grid">{#each [0, 1, 2, 3] as i (i)}<div class="card sk"></div>{/each}</div>{/if}
      {:else if !results.length}
        {#if !error}
          <div class="empty card">
            <Icon name="scan" size={28} />
            <p>{q.trim() ? st('parts.empty') : st('parts.catalog_empty')}</p>
          </div>
        {/if}
      {:else}
        <div class="grid">
          {#each results as li (li.id)}{@render card(li, 'catalog')}{/each}
        </div>
      {/if}
    </section>

    <section class="sect" id="mine">
      <div class="bhead">
        <h2>{st('parts.mine')}</h2>
      </div>
      {#if mine?.length}
        <h3 class="section-title">{st('parts.my_parts')}</h3>
        <p class="xs muted sub">{st('parts.my_parts_hint')}</p>
        <div class="grid">
          {#each mine as li (li.id)}{@render card(li, 'mine')}{/each}
        </div>
      {/if}

      <h3 class="section-title" id="orders">{st('parts.my_orders')}</h3>
      {#if mineError}<p class="err small" role="alert">{mineError} <button class="btn small" onclick={loadMine}>{t('retry')}</button></p>{/if}
      {#if orders === null}
        {#if !mineError}<div class="card sk row-sk"></div>{/if}
      {:else if !orders.length}
        <p class="small muted">{st('parts.no_orders')}</p>
      {:else}
        <ul class="orders">
          {#each orders as o (o.id)}
            <li>
              <a class="ord card" href="/orders/{o.id}">
                <span class="thumb">{#if o.project?.cover}<img src={o.project.cover} alt="" loading="lazy" />{:else}<Icon name="package" size={18} />{/if}</span>
                <span class="otext">
                  <span class="row orow">
                    <span class="mono xs">{o.ref}</span>
                    <span class="chip {statusTone(o.status)}">{#if o.working}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{/if}{st(`status.${o.status}`)}</span>
                  </span>
                  <strong class="small">{orderTitle(o)}</strong>
                </span>
                <span class="oside">
                  {#if o.quote?.total != null}
                    <span class="mono small">{o.quote.binding ? money(o.quote.total, o.quote.usd?.total) : `≈ ${kzt(o.quote.total)}`}</span>
                  {/if}
                  <span class="xs muted">{when(o.updated_at)}</span>
                </span>
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    </section>

    <p class="xs muted ip"><Icon name="lock" size={12} /> {st('parts.ip_note')}</p>
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
    gap: var(--space-6);
  }
  .hero {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: 'lead lead' 'search cta';
    gap: var(--space-4);
    align-items: center;
  }
  .lead {
    grid-area: lead;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  h1 {
    font-size: var(--text-3xl);
    font-weight: var(--font-weight-semibold);
  }
  .lead p {
    margin: 0;
    max-width: 680px;
    color: var(--on-surface-var);
    font-size: var(--text-lg);
  }
  .search {
    grid-area: search;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 0 var(--space-4);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-card);
    background: var(--surface-container);
    color: var(--outline);
    transition: border-color var(--dur-fast) var(--ease-standard);
  }
  .search:focus-within {
    border-color: var(--primary);
  }
  .search input {
    flex: 1;
    border: none;
    background: transparent;
    padding: 14px 0;
    font-size: var(--text-lg);
    box-shadow: none;
  }
  .cta {
    grid-area: cta;
  }
  .shown {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    color: var(--on-surface);
    text-decoration: none;
    min-width: 0;
  }
  .shown:hover {
    border-color: var(--outline);
    text-decoration: none;
  }
  .sthumb {
    flex: none;
    width: 52px;
    height: 52px;
    border-radius: var(--radius-btn);
    background: var(--render-bg);
    display: grid;
    place-items: center;
    color: var(--outline);
    overflow: hidden;
  }
  .sthumb img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .stext {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .stext strong {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--primary);
  }
  .sect {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    scroll-margin-top: calc(var(--header-h, 68px) + var(--space-4));
  }
  #orders {
    scroll-margin-top: calc(var(--header-h, 68px) + var(--space-4));
    margin-top: var(--space-3);
  }
  .bhead {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  h2 {
    font-size: var(--text-xl);
    font-weight: var(--font-weight-bold);
  }
  .sub {
    margin: -6px 0 0;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: var(--space-4);
    align-items: start;
  }
  .li {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    transition: border-color var(--dur-fast) var(--ease-standard);
  }
  .li:hover,
  .li.open {
    border-color: var(--outline);
  }
  .pic {
    position: relative;
    aspect-ratio: 4 / 3;
    background: var(--render-bg);
    display: grid;
    place-items: center;
    color: var(--outline);
  }
  .pic img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    padding: var(--space-3);
  }
  .own {
    position: absolute;
    top: 8px;
    left: 8px;
    background: var(--surface-container);
  }
  .meta {
    padding: var(--space-3) var(--space-3) 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  .name {
    font-size: var(--text-base);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fits {
    color: var(--on-surface-var);
    overflow-wrap: anywhere;
  }
  .badges {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
  }
  .badges .chip {
    min-height: 20px;
    padding: 0 6px;
    font-size: var(--text-xs);
    gap: 3px;
  }
  .buy {
    padding: var(--space-3) var(--space-3) 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .buyrow {
    display: grid;
    grid-template-columns: minmax(0, 0.7fr) minmax(0, 1.3fr);
    gap: var(--space-2);
  }
  .buy input,
  .buy select {
    width: 100%;
    padding: 8px 10px;
    font-size: var(--text-md);
  }
  .buy select {
    padding-right: 30px;
  }
  .quote {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-height: 40px;
  }
  .acts {
    padding: var(--space-3);
    margin-top: auto;
  }
  .report {
    margin-left: auto;
    color: var(--outline);
  }
  .orders {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .ord {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    color: var(--on-surface);
    text-decoration: none;
    min-width: 0;
  }
  .ord:hover {
    border-color: var(--outline);
    text-decoration: none;
  }
  .thumb {
    flex: none;
    width: 48px;
    height: 48px;
    border-radius: var(--radius-btn);
    background: var(--render-bg);
    display: grid;
    place-items: center;
    color: var(--outline);
    overflow: hidden;
  }
  .thumb img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .otext {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1;
  }
  .otext strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .orow {
    gap: 6px;
  }
  .oside {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
    text-align: right;
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
    max-width: 440px;
  }
  .sk {
    aspect-ratio: 4 / 4.6;
    animation: sk-pulse var(--t-skeleton) ease-in-out infinite;
  }
  .row-sk {
    aspect-ratio: auto;
    height: 64px;
  }
  .err {
    color: var(--error);
    margin: 0;
  }
  .notice {
    margin: 0;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-btn);
    background: var(--surface-container);
    color: var(--on-surface-var);
  }
  .ip {
    margin: 0;
    display: flex;
    gap: 6px;
    align-items: baseline;
  }
  @media (max-width: 720px) {
    .hero {
      grid-template-columns: minmax(0, 1fr);
      grid-template-areas: 'lead' 'search' 'cta';
    }
    .cta {
      white-space: normal;
      text-align: center;
    }
    h1 {
      font-size: var(--text-3xl);
    }
  }
  @media (max-width: 520px) {
    .wrap {
      padding: var(--space-4) var(--space-4) var(--space-7);
      gap: var(--space-5);
    }
    .grid {
      grid-template-columns: minmax(0, 1fr);
    }
    .pic {
      aspect-ratio: 16 / 9;
    }
    .oside {
      display: none;
    }
  }
</style>
