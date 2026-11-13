<script lang="ts">
  // The Axo farm's board: orders on their way in (being read, designed, quoted), then paid, printing, QC and ready
  // to ship, with the farm's printers on top, and the latest shipped ones below (one can be shown to everyone).
  // Operators only; it refreshes every 10 s.
  import { onMount, tick } from 'svelte';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { t } from '$lib/i18n.svelte';
  import OpsCard from '$lib/shop/OpsCard.svelte';
  import { shop, shopError } from '$lib/shop/api';
  import { st } from '$lib/shop/i18n';
  import type { OpsQueue, Order, ShopMe, ShopPrinter } from '$lib/shop/types';

  type Col = 'upstream' | 'paid' | 'printing' | 'qc' | 'ship';
  const COLS: Col[] = ['upstream', 'paid', 'printing', 'qc', 'ship'];

  let me = $state<ShopMe | null>(null);
  let board = $state<OpsQueue | null>(null);
  let error = $state<string | null>(null);
  let loading = $state(false);
  let tab = $state<Col | null>(null);
  let busyPrinter = $state<string | null>(null);

  const columns = $derived.by(() => {
    const out: Record<Col, Order[]> = { upstream: [], paid: [], printing: [], qc: [], ship: [] };
    if (!board) return out;
    out.upstream = board.upstream;
    for (const o of board.orders) {
      if (o.status === 'paid') out.paid.push(o);
      else if (o.status === 'printing') out.printing.push(o);
      else if (o.status === 'qc') ((o.qc as { pass?: boolean })?.pass ? out.ship : out.qc).push(o);
    }
    return out;
  });
  // on a phone one column at a time: the first one with work in it
  const shown = $derived<Col>(tab ?? (COLS.slice(1).find((c) => columns[c].length) || 'upstream'));

  async function load() {
    loading = true;
    try {
      board = await shop.queue();
      error = null;
    } catch (e) {
      error = shopError(e);
    } finally {
      loading = false;
    }
  }

  // who is asking comes first: a failed answer is asked again, by the refresh below or the retry button
  async function start() {
    try {
      const m = await shop.me(true);
      me = m;
      error = null;
      if (m.is_operator) load();
    } catch (e) {
      error = shopError(e);
    }
  }

  onMount(() => {
    start();
    const id = setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      if (!me) start();
      else if (me.is_operator) load();
    }, 10000);
    return () => clearInterval(id);
  });

  // a card's action answers with the order as it is now; the board follows right after
  async function changed(o: Order) {
    const shipped = o.status === 'shipped' && !board?.done?.some((x) => x.id === o.id);
    if (board) {
      board.orders = board.orders.map((x) => (x.id === o.id ? o : x));
      board.upstream = board.upstream.map((x) => (x.id === o.id ? o : x));
      board.done = board.done?.map((x) => (x.id === o.id ? o : x));
    }
    await load();
    if (!shipped) return;
    // Ship moves the card under Shipped, below the columns (often off screen): follow it there
    await tick();
    document.getElementById(`op-${o.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  async function printerDo(p: ShopPrinter, call: () => Promise<ShopPrinter>) {
    busyPrinter = p.id;
    error = null;
    try {
      await call();
      await load();
    } catch (e) {
      error = shopError(e);
    } finally {
      busyPrinter = null;
    }
  }
  const calibrated = (p: ShopPrinter) => !!p.fingerprint && Object.keys(p.fingerprint).length > 0;
</script>

<svelte:head><title>{st('ops.title')} · IaModelize3d</title></svelte:head>

<div class="page">
  <Header />
  <main class="wrap">
    <div class="head">
      <div>
        <h1>{st('ops.title')}</h1>
        <p class="muted small">{st('ops.lead')}</p>
      </div>
      {#if board}
        <div class="row">
          <span class="chip info mono">{st('ops.queue', { h: board.queue_hours.toFixed(1) })}</span>
          <button class="btn icon small" onclick={load} disabled={loading} aria-label={st('ops.refresh')} title={st('ops.refresh')}>
            <i class="ti {loading ? 'ti-loader-2 spin' : 'ti-refresh'}" aria-hidden="true"></i>
          </button>
        </div>
      {/if}
    </div>

    {#if error}<p class="err small" role="alert">{error}{#if !board}{' '}<button class="btn small" onclick={() => (me ? load() : start())}>{t('retry')}</button>{/if}</p>{/if}

    {#if me && !me.is_operator}
      <div class="empty card">
        <Icon name="lock" size={28} />
        <p>{st('ops.not_operator')}</p>
        <a class="btn" href="/parts">{st('nav.parts')}</a>
      </div>
    {:else if board}
      <section class="printers">
        <h2 class="section-title">{st('ops.printers')}</h2>
        {#if !board.printers.length}<p class="small muted">{st('ops.no_printers')}</p>{/if}
        <div class="prow">
          {#each board.printers as p (p.id)}
            <div class="printer card" class:busy={p.state === 'printing'} class:off={p.state === 'maintenance'}>
              <div class="row pname">
                <span class="led" aria-hidden="true"></span>
                <strong>{p.name}</strong>
                <span class="chip">{st(`printer.${p.state}`)}{p.order_ref ? ` · ${p.order_ref}` : ''}</span>
              </div>
              <span class="xs muted">{p.material}{p.color ? ` · ${p.color}` : ''} · {calibrated(p) ? st('ops.calibrated') : st('ops.uncalibrated')}</span>
              <div class="row pacts">
                {#if p.state !== 'printing'}
                  <button class="btn small ghost" disabled={busyPrinter === p.id} onclick={() => printerDo(p, () => shop.updatePrinter(p.id, { state: p.state === 'maintenance' ? 'idle' : 'maintenance' }))}>
                    {p.state === 'maintenance' ? st('ops.to_idle') : st('ops.to_maintenance')}
                  </button>
                {/if}
                <label class="btn small ghost" class:disabled={busyPrinter === p.id}>
                  {#if busyPrinter === p.id}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="target" size={13} />{/if} {st('ops.calibrate')}
                  <input class="sr-only" type="file" accept="image/*" capture="environment" onchange={(e) => {
                    const f = (e.currentTarget as HTMLInputElement).files?.[0];
                    if (f) printerDo(p, () => shop.fingerprint(p.id, f));
                  }} />
                </label>
                <a class="btn small ghost" href="/api/printers/coupon.3mf" download><Icon name="download" size={13} /> {st('ops.coupon')}</a>
              </div>
            </div>
          {/each}
        </div>
      </section>

      <div class="seg tabs" role="tablist">
        {#each COLS as c (c)}
          <button role="tab" aria-selected={shown === c} onclick={() => (tab = c)}>{st(`ops.col.${c}`)} <span class="n">{columns[c].length}</span></button>
        {/each}
      </div>

      <div class="board">
        {#each COLS as c (c)}
          <section class="col" class:shown={shown === c} aria-label={st(`ops.col.${c}`)}>
            <h2 class="row colhead">
              <span class="section-title">{st(`ops.col.${c}`)}</span>
              <span class="chip">{columns[c].length}</span>
            </h2>
            {#each columns[c] as o (o.id)}
              <OpsCard order={o} printers={board.printers} onChange={changed} />
            {:else}
              <p class="none xs muted">{st('ops.empty')}</p>
            {/each}
          </section>
        {/each}
      </div>

      {#if board.done?.length}
        <section class="done">
          <div class="row dhead">
            <h2 class="section-title">{st('ops.col.done')}</h2>
            <span class="chip">{board.done.length}</span>
          </div>
          <p class="xs muted">{st('ops.done_hint')}</p>
          <div class="dgrid">
            {#each board.done as o (o.id)}
              <OpsCard order={o} printers={board.printers} onChange={changed} />
            {/each}
          </div>
        </section>
      {/if}
    {:else if !error}
      <div class="board">
        {#each COLS as c (c)}<div class="col shown"><div class="card sk"></div></div>{/each}
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
    max-width: 1560px;
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
    flex-wrap: wrap;
  }
  h1 {
    font-size: var(--text-2xl);
    font-weight: var(--font-weight-bold);
  }
  .head p {
    margin: 4px 0 0;
    max-width: 640px;
  }
  .err {
    color: var(--error);
    margin: 0;
  }
  .printers {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .prow {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .printer {
    padding: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    flex: 0 1 380px;
  }
  .pname {
    gap: 8px;
    flex-wrap: nowrap;
    min-width: 0;
  }
  .pname strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .led {
    flex: none;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--primary);
  }
  .busy .led {
    background: var(--info);
    animation: blink 1.2s ease-in-out infinite;
  }
  .off .led {
    background: var(--warn);
  }
  @keyframes blink {
    50% {
      opacity: 0.35;
    }
  }
  .pacts {
    gap: 2px;
    margin-left: -8px;
  }
  .tabs {
    display: none;
  }
  .tabs .n {
    font-family: var(--font-mono);
    opacity: 0.7;
  }
  .board {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: var(--space-3);
    align-items: start;
  }
  .col {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-2);
    border-radius: var(--radius-card);
    background: var(--surface-container-low);
    min-height: 160px;
    min-width: 0;
  }
  .colhead {
    justify-content: space-between;
    margin: 0;
    padding: 4px 4px 2px;
  }
  .done {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .done p {
    margin: 0;
  }
  .dhead {
    gap: var(--space-2);
  }
  .dgrid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: var(--space-3);
    align-items: start;
  }
  .none {
    margin: 0;
    padding: var(--space-4) var(--space-2);
    text-align: center;
  }
  .sk {
    height: 150px;
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
  @media (max-width: 1100px) {
    .tabs {
      display: flex;
    }
    .board {
      grid-template-columns: minmax(0, 1fr);
    }
    .col {
      display: none;
    }
    .col.shown {
      display: flex;
    }
    .colhead {
      display: none;
    }
  }
  @media (max-width: 520px) {
    .wrap {
      padding: var(--space-4) var(--space-4) var(--space-7);
    }
    /* five equal tabs, the label over its count, so all of them fit a phone without scrolling */
    .tabs {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
    }
    .tabs button {
      flex-direction: column;
      gap: 2px;
      padding: 6px 2px;
      white-space: normal;
      text-align: center;
      font-size: var(--text-xs);
      line-height: 1.15;
      min-width: 0;
    }
    .printer {
      flex-basis: 100%;
    }
  }
</style>
