<script lang="ts">
  // One order on the Axo farm's board. Its buttons follow the moves the server allows this operator now (`next`):
  // assign a printer, take it off the plate, the QC photo on A4, ship with a tracking number; once shipped, mark it
  // handed over and show it to everyone as a delivered-order example (without the customer's data). A request nobody
  // could read is let through with the quantity and material the operator read in it.
  import Icon from '$lib/components/Icon.svelte';
  import { shop, shopError } from './api';
  import { grams, minutes, mm, orderTitle, problemText, qcError, st, statusTone, when } from './i18n';
  import type { Order, QcReport, ShopPrinter } from './types';

  let { order, printers, onChange }: { order: Order; printers: ShopPrinter[]; onChange?: (o: Order) => void } = $props();

  const upstream = $derived(['requested', 'designing', 'needs_info', 'quoted'].includes(order.status));
  // a ready model may be quoted already while it waits for the operator (its Pay does)
  const held = $derived(['requested', 'quoted'].includes(order.status) && !!order.intake?.review && !order.intake?.reviewed);
  // the intake model could not read it (it was down): the operator reads it and sets what the design starts from
  const unread = $derived(held && order.status === 'requested' && order.intake?.review?.code === 'intake_failed');
  const done = $derived(order.status === 'shipped' || order.status === 'delivered');
  const qc = $derived<QcReport | null>(order.qc && ('max_mm' in order.qc || 'error' in order.qc) ? (order.qc as QcReport) : null);
  const passed = $derived(order.status === 'qc' && !!qc?.pass);
  const files = $derived(order.slice?.files ?? {});
  const printer = $derived(printers.find((p) => p.id === order.printer_id) ?? null);
  const stats = $derived(order.slice?.stats ?? {});
  const method = $derived(order.delivery?.method ?? 'courier');
  // a printer loaded with this material first, idle first
  const choices = $derived(
    printers
      .filter((p) => p.state !== 'maintenance')
      .sort((a, b) => Number(b.material === order.material) - Number(a.material === order.material) || Number(a.state !== 'idle') - Number(b.state !== 'idle')),
  );

  let pick = $state('');
  let carrier = $state('');
  let tracking = $state('');
  let reason = $state('');
  let refusing = $state(false);
  // the customer's form until the operator changes them (an empty form field: what the order holds, 1 and PLA)
  let qty = $state<number | null>(null);
  let mat = $state<string | null>(null);
  const qtyNow = $derived(qty ?? order.intake?.request?.quantity ?? order.quantity);
  const matNow = $derived(mat ?? order.intake?.request?.material ?? order.material);
  let busy = $state<string | null>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    if (!pick && choices.length) pick = choices[0].id;
  });
  $effect(() => {
    if (!carrier) carrier = method === 'post' ? st('delivery.post') : method === 'courier' ? st('carrier.courier') : '';
  });

  async function run(what: string, call: () => Promise<Order>) {
    busy = what;
    error = null;
    try {
      onChange?.(await call());
    } catch (e) {
      error = shopError(e);
    } finally {
      busy = null;
    }
  }

  function qcPhoto(list: FileList | null) {
    const f = list?.[0];
    if (f) run('qc', () => shop.qc(order.id, f));
  }
</script>

<article class="op card" id="op-{order.id}" class:held class:ready={passed}>
  <div class="top">
    <a class="cover" href="/orders/{order.id}" aria-label={order.ref}>
      {#if order.project?.cover}<img src={order.project.cover} alt="" loading="lazy" />{:else}<Icon name="cube" size={22} />{/if}
    </a>
    <div class="who">
      <div class="row ref">
        <a class="mono" href="/orders/{order.id}">{order.ref}</a>
        {#if upstream}<span class="chip {statusTone(order.status)}">{st(`status.${order.status}`)}</span>{/if}
        {#if order.working}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{/if}
      </div>
      <strong class="title">{orderTitle(order)}</strong>
      <span class="xs muted">
        ×{order.quantity} · {order.material}{order.color ? ` · ${order.color}` : ''}
        {#if stats.grams}· {grams(stats.grams)} · {minutes(stats.minutes)}{/if}
        {#if (order.attempts ?? 0) > 1}· {st('ops.attempt', { n: order.attempts ?? 1 })}{/if}
      </span>
    </div>
  </div>

  {#if order.problem?.code}
    <p class="xs warn"><Icon name="alert" size={13} /> {problemText(order.problem, true)}</p>
  {/if}
  {#if held}
    <p class="xs warn"><Icon name="user" size={13} /> {order.intake.review?.code === 'intake_failed' ? st('note.held_failed') : `${st('ops.held')}: ${order.intake.review?.why}`}</p>
  {/if}

  {#if printer || files.gcode || files.project_3mf}
    <div class="row files">
      {#if printer}<span class="chip"><Icon name="printer" size={12} /> {printer.name}</span>{/if}
      {#if files.gcode}<a class="btn small" href={files.gcode} download><Icon name="download" size={13} /> {st('ops.gcode')}</a>{/if}
      {#if files.project_3mf}<a class="btn small ghost" href={files.project_3mf} download>{st('ops.3mf')}</a>{/if}
    </div>
  {/if}

  {#if qc}
    <a class="qcline row xs" href="/orders/{order.id}#qc">
      {#if qc.error}
        <span class="chip warn">QC</span><span class="muted">{qcError(qc, true)}</span>
      {:else}
        <span class="chip" class:ok={qc.pass} class:err={!qc.pass}>{qc.pass ? st('qc.pass') : st('qc.fail')}</span>
        <span class="mono">{st('qc.max', { n: mm(qc.max_mm) })} / ±{qc.tolerance_mm ?? 0.6}</span>
      {/if}
    </a>
  {/if}

  <!-- the moves, from what the server says this operator may do now -->
  <div class="acts">
    {#if held}
      {#if refusing}
        <input type="text" bind:value={reason} placeholder={st('ops.refuse_ph')} maxlength="500" />
        <div class="row">
          <button class="btn small danger" disabled={!!busy} onclick={() => run('refuse', () => shop.review(order.id, { action: 'refuse', note: reason }))}>{st('ops.refuse')}</button>
          <button class="btn small ghost" onclick={() => (refusing = false)}>×</button>
        </div>
      {:else}
        {#if unread}
          <p class="xs muted">{st('ops.unread')}</p>
          <div class="row set">
            <label class="field">{st('new.quantity')}
              <input type="number" min="1" max="200" value={qtyNow} oninput={(e) => (qty = Number((e.currentTarget as HTMLInputElement).value) || null)} />
            </label>
            <label class="field">{st('new.material')}
              <select value={matNow} onchange={(e) => (mat = (e.currentTarget as HTMLSelectElement).value)}>
                {#each ['PLA', 'PETG', 'ASA', 'TPU'] as m (m)}<option>{m}</option>{/each}
              </select>
            </label>
          </div>
        {/if}
        <div class="row">
          <button class="btn small primary" disabled={!!busy} onclick={() => run('approve', () => shop.review(order.id, unread ? { action: 'approve', quantity: Math.max(1, Math.min(200, Math.round(qtyNow) || 1)), material: matNow } : { action: 'approve' }))}><Icon name="check" size={14} /> {st('ops.approve')}</button>
          <button class="btn small danger" disabled={!!busy} onclick={() => (refusing = true)}>{st('ops.refuse')}</button>
        </div>
      {/if}
    {:else if upstream && order.problem?.code && order.problem.code !== 'no_model' && !order.working}
      <!-- not while an automatic step runs for it (its own quote may land any second) -->
      <button class="btn small" disabled={!!busy} onclick={() => run('requote', () => shop.requote(order.id, {}, 'ops'))}>
        {#if busy === 'requote'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="refresh" size={14} />{/if} {st('ops.requote')}
      </button>
    {/if}

    {#if order.status === 'paid' && order.next.includes('printing')}
      <div class="row assign">
        <select bind:value={pick} aria-label={st('ops.printers')}>
          <!-- an idle printer is the usual one: only a busy one says so (a full line is cut off in a board column) -->
          {#each choices as p (p.id)}<option value={p.id}>{p.name} · {p.material}{p.state === 'idle' ? '' : ` · ${st(`printer.${p.state}`)}`}</option>{/each}
        </select>
        <button class="btn small primary" disabled={!!busy || !pick} onclick={() => run('assign', () => shop.assign(order.id, pick))}>
          {#if busy === 'assign'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="printer" size={14} />{/if} {st('ops.assign')}
        </button>
      </div>
    {/if}

    {#if order.status === 'printing' && order.next.includes('qc')}
      <button class="btn small primary" disabled={!!busy} onclick={() => run('printed', () => shop.printed(order.id))}><Icon name="check" size={14} /> {st('ops.printed')}</button>
    {/if}

    {#if order.status === 'qc' && !passed}
      <label class="btn small primary" class:disabled={!!busy}>
        {#if busy === 'qc'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i> {st('ops.measuring')}{:else}<Icon name="camera" size={14} /> {qc ? st('ops.qc_again') : st('ops.qc_photo')}{/if}
        <input class="sr-only" type="file" accept="image/*" capture="environment" disabled={!!busy} onchange={(e) => qcPhoto((e.currentTarget as HTMLInputElement).files)} />
      </label>
    {/if}

    {#if passed && order.next.includes('shipped')}
      {#if method === 'pickup'}
        <p class="xs muted">{st('ops.pickup')}</p>
      {:else}
        <div class="ship">
          <input type="text" bind:value={carrier} placeholder={st('ops.carrier')} maxlength="60" aria-label={st('ops.carrier')} />
          <input type="text" bind:value={tracking} placeholder={st('ops.tracking')} maxlength="80" aria-label={st('ops.tracking')} />
        </div>
      {/if}
      <button class="btn small primary" disabled={!!busy || (method !== 'pickup' && !tracking.trim())} onclick={() => run('ship', () => shop.ship(order.id, { carrier: carrier.trim(), tracking: tracking.trim() }))}>
        <Icon name="send" size={14} /> {st('ops.ship')}
      </button>
    {/if}

    {#if order.status === 'qc' && order.next.includes('paid')}
      <button class="btn small ghost" disabled={!!busy} onclick={() => run('reprint', () => shop.reprint(order.id))}><Icon name="refresh" size={14} /> {st('ops.reprint')}</button>
    {/if}

    {#if done}
      <!-- the farm hands it over (a pickup, a parcel the customer never confirms): the customer's own button is theirs -->
      {#if order.status === 'shipped' && order.next.includes('delivered')}
        <button class="btn small ghost" disabled={!!busy} onclick={() => run('delivered', () => shop.delivered(order.id, 'ops'))}><Icon name="check" size={14} /> {st('ops.delivered')}</button>
      {/if}
      <div class="row show">
        <span class="chip {statusTone(order.status)}">{st(`status.${order.status}`)}</span>
        <button class="btn small" class:ghost={order.showcase} disabled={!!busy} onclick={() => run('showcase', () => shop.showcase(order.id, !order.showcase))}>
          {#if busy === 'showcase'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="eye" size={14} />{/if}
          {order.showcase ? st('order.showcase_off') : st('order.showcase_on')}
        </button>
        {#if order.showcase}<a class="xs" href="/orders/{order.id}">{st('order.showcase_shown')} ↗</a>{/if}
      </div>
    {/if}
  </div>

  <div class="row foot xs muted">
    <span>{st(`delivery.${method}`)}</span>
    {#if order.customer?.contact}<span class="mono">· {order.customer.contact}</span>{/if}
    <span class="spacer"></span>
    <span>{when(order.updated_at)}</span>
  </div>
  {#if error}<p class="err xs" role="alert">{error}</p>{/if}
</article>

<style>
  .op {
    padding: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    animation: slide var(--dur-slow) var(--ease-settle);
  }
  @keyframes slide {
    from {
      opacity: 0;
      transform: translateX(-8px);
    }
  }
  .op.held {
    border-color: color-mix(in srgb, var(--warn) 55%, var(--outline-variant));
  }
  .op.ready {
    border-color: color-mix(in srgb, var(--primary) 55%, var(--outline-variant));
  }
  .top {
    display: flex;
    gap: var(--space-3);
    min-width: 0;
  }
  .cover {
    flex: none;
    width: 56px;
    height: 56px;
    border-radius: var(--radius-btn);
    background: var(--render-bg);
    display: grid;
    place-items: center;
    color: var(--outline);
    overflow: hidden;
  }
  .cover img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .who {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .ref {
    gap: 6px;
  }
  .ref a {
    color: var(--on-surface);
    font-weight: var(--font-weight-bold);
  }
  .title {
    font-size: var(--text-md);
    line-height: 1.3;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .files {
    gap: 6px;
  }
  .show {
    gap: 6px;
  }
  .qcline {
    gap: 6px;
    color: var(--on-surface-var);
    text-decoration: none;
  }
  .acts {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .acts:empty {
    display: none;
  }
  .acts > .btn,
  .acts > label.btn {
    align-self: flex-start;
  }
  /* the printer list above its button: a board column is narrow */
  .assign {
    flex-direction: column;
    align-items: stretch;
  }
  .assign .btn {
    align-self: flex-start;
  }
  .assign select {
    width: 100%;
    min-width: 0;
    padding-top: 7px;
    padding-bottom: 7px;
    font-size: var(--text-md);
  }
  .set {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
    gap: 6px;
  }
  .set input,
  .set select {
    width: 100%;
    padding: 7px 10px;
    font-size: var(--text-md);
  }
  .ship {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
    gap: 6px;
  }
  .ship input,
  .acts > input {
    padding: 7px 10px;
    font-size: var(--text-md);
  }
  .foot {
    gap: 4px;
    padding-top: var(--space-2);
    border-top: var(--border-width) solid var(--divider);
  }
  .warn {
    color: var(--warn-text);
    margin: 0;
    overflow-wrap: anywhere;
  }
  .err {
    color: var(--error);
    margin: 0;
  }
</style>
