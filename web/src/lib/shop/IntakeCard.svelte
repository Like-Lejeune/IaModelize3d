<script lang="ts">
  // What the intake desk read from the request: Muse Spark 1.3 (brand, model and part number verbatim, the safety
  // gate), the voice note's transcript, the open model's second opinion, and the questions left for the designer.
  import Icon from '$lib/components/Icon.svelte';
  import { i18n } from '$lib/i18n.svelte';
  import { modelName } from '$lib/models';
  import { shop, shopError } from './api';
  import { sameLang, skipText, st } from './i18n';
  import type { Order } from './types';

  let {
    order,
    photos = [],
    onChange,
  }: { order: Order; photos?: { url: string; role: string }[]; onChange?: (o: Order) => void } = $props();

  const it = $derived(order.intake ?? {});
  const req = $derived(it.request);
  const read = $derived(typeof it.refuse === 'boolean' || !!it.error);
  // a ready model is quoted while it is read: still reading on a quoted order
  const reading = $derived(!read && (order.status === 'requested' || order.status === 'quoted'));
  const refused = $derived(order.status === 'refused');
  const held = $derived(!!it.review && !it.reviewed && (order.status === 'requested' || order.status === 'quoted'));
  const spark = $derived(it.model ? modelName(it.model) : 'Muse Spark 1.3');
  const second = $derived(it.classify && !it.classify.error ? it.classify : null);

  // the part as the customer named it when the UI speaks their language, the English name otherwise
  const partName = $derived.by(() => {
    const p = it.part ?? {};
    const own = it.language?.slice(0, 2) === i18n.lang ? p.name_user : null;
    const t = i18n.lang === 'ru' ? second?.title_ru : second?.title_en;
    return own || t || p.name_en || p.name_user || '';
  });
  const fits = $derived([it.appliance?.brand, it.appliance?.model].filter(Boolean).join(' '));
  // the customer's own words (a new part's request), so they can see it arrived as sent, without the English labels
  // the models read (an older order: its text without those lines); the voice note is shown apart
  const said = $derived.by(() => {
    if (req?.kind !== 'photo') return '';
    const typed =
      req.words ??
      (req.text ?? '')
        .split('\n')
        .filter((l) => !/^(Appliance|Part number|Quantity|Voice note): /.test(l))
        .join('\n');
    return [typed.trim(), [req.appliance, req.part_number].filter((x) => x?.trim()).join(' · ')].filter(Boolean).join('\n');
  });
  // the form's quantity when one was given, else what the intake read (the server keeps it on the order)
  const qty = $derived(order.quantity);
  const life = $derived(
    [
      it.environment?.wet ? st('intake.wet') : '',
      typeof it.environment?.max_temp_c === 'number' && it.environment.max_temp_c > 30 ? st('intake.temp', { t: it.environment.max_temp_c }) : '',
      it.environment?.food_contact ? st('intake.food') : '',
    ].filter(Boolean),
  );

  let answer = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);

  async function send(text: string) {
    if (!text.trim() || busy) return;
    busy = true;
    error = null;
    try {
      onChange?.(await shop.answer(order.id, text.trim()));
      answer = '';
    } catch (e) {
      error = shopError(e);
    } finally {
      busy = false;
    }
  }
</script>

<section class="intake card" class:refused class:held>
  {#if photos.length}
    <div class="photos">
      {#each photos as p (p.url)}
        <figure>
          <img src={p.url} alt="" loading="lazy" />
          <figcaption class="xs">{st(p.role === 'plate' ? 'new.plate_photo' : 'new.part_photo')}</figcaption>
        </figure>
      {/each}
    </div>
  {/if}

  {#if said}
    <div class="said">
      <span class="chip"><Icon name="message" size={13} /> {st('intake.request')}</span>
      <p class="small own">«{said}»</p>
    </div>
  {/if}

  {#if req?.transcript}
    <div class="said">
      <span class="chip info"><Icon name="mic" size={13} /> Muse Voice Transcribe</span>
      <p class="small">«{req.transcript}»</p>
    </div>
  {/if}

  {#if reading}
    <div class="row reading">
      <i class="ti ti-loader-2 spin" aria-hidden="true"></i>
      <span>{st('intake.reading')}</span>
      <span class="chip accent">Muse Spark 1.3</span>
    </div>
  {:else if read && !it.error}
    <!-- a request that could not be read has nothing under 'Read': the held box (then the operator's line) says it -->
    <div class="read">
      <div class="row top">
        <span class="section-title">{st('intake.read')}</span>
        {#if it.model}<span class="chip accent"><Icon name="sparkles" size={13} /> {spark}</span>{/if}
      </div>
      <p class="line">
        {#if fits}<strong class="mono">{fits}</strong><span class="sep">·</span>{/if}
        <span>{partName}</span>
        <span class="sep">·</span><span>{st('intake.pcs', { n: qty })}</span>
        <span class="sep">·</span><span>{order.material}</span>
      </p>
      <div class="row facts">
        {#if it.part?.part_number}<span class="chip mono">№ {it.part.part_number}</span>{/if}
        {#if it.part?.condition && st(`cond.${it.part.condition}`)}<span class="chip">{st(`cond.${it.part.condition}`)}</span>{/if}
        {#each life as l (l)}<span class="chip">{l}</span>{/each}
        {#each it.ip_flags ?? [] as f (f)}<span class="chip warn"><Icon name="lock" size={12} /> {st('intake.no_logo', { x: f })}</span>{/each}
      </div>
      {#if it.part?.failure && (sameLang(it.part.failure) || order.actor === 'operator')}<p class="small muted">{it.part.failure}</p>{/if}
    </div>
  {/if}

  {#if refused && it.refuse}
    <div class="verdict bad" role="status">
      <Icon name="alert" size={20} />
      <div>
        <strong>{st('intake.refused')}</strong>
        {#if it.reason && (sameLang(it.reason) || order.actor === 'operator')}<p class="small">{it.reason}</p>{/if}
        <p class="xs muted">{st('intake.refused_hint')}</p>
      </div>
    </div>
  {:else if held}
    <div class="verdict wait" role="status">
      <Icon name="user" size={20} />
      <div>
        <strong>{st('intake.held')}</strong>
        <p class="small">{it.review?.code === 'intake_failed' ? st('intake.held_failed') : st('intake.held_safety')}</p>
        {#if it.review?.code !== 'intake_failed' && it.review?.why && (sameLang(it.review.why) || order.actor === 'operator')}
          <p class="xs muted">«{it.review.why}»</p>
        {/if}
      </div>
    </div>
  {:else if read && (!it.error || it.reviewed)}
    <!-- read, or let through by the operator when it could not be read -->
    <div class="row safe xs">
      <Icon name="check-circle" size={14} />
      <span>{it.reviewed ? st('intake.approved') : st('intake.safety_ok')}</span>
      {#if second}
        <span class="muted">· {st('intake.second')}: {second.model ? modelName(second.model) : ''}{second.category ? `, ${st(`cat.${second.category}`)}` : ''}</span>
      {/if}
    </div>
  {/if}

  {#if order.status === 'needs_info' && order.question}
    <div class="ask">
      <span class="section-title">{st('intake.question')}</span>
      <p>{order.question.question}</p>
      {#if order.question.options?.length}
        <div class="row">
          {#each order.question.options as opt (opt)}
            <button class="chip" disabled={busy} onclick={() => send(opt)}>{opt}</button>
          {/each}
        </div>
      {/if}
      {#if order.question.allow_text !== false}
        <form class="row answer" onsubmit={(e) => (e.preventDefault(), send(answer))}>
          <input type="text" bind:value={answer} placeholder={st('intake.answer_ph')} maxlength="2000" />
          <button class="btn primary small" disabled={busy || !answer.trim()}>
            {#if busy}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="send" size={14} />{/if}
            {st('intake.send')}
          </button>
        </form>
      {/if}
    </div>
  {:else if it.questions?.length && !refused && ['requested', 'designing'].includes(order.status)}
    <div class="qs">
      <span class="section-title">{st('intake.questions')}</span>
      <ul class="small">
        {#each it.questions as q (q)}<li><Icon name="help" size={14} /> {q}</li>{/each}
      </ul>
    </div>
  {/if}

  {#each req?.skipped ?? [] as s, i (i)}<p class="xs muted">{st('intake.skipped', { x: skipText(s, order.actor === 'operator') })}</p>{/each}
  {#if error}<p class="err small" role="alert">{error}</p>{/if}
</section>

<style>
  .intake {
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    animation: rise var(--dur-slow) var(--ease-settle);
  }
  .intake.refused {
    border-color: color-mix(in srgb, var(--error) 55%, var(--outline-variant));
  }
  .intake.held {
    border-color: color-mix(in srgb, var(--warn) 50%, var(--outline-variant));
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
  }
  .photos {
    display: flex;
    gap: var(--space-2);
    overflow-x: auto;
    scrollbar-width: none;
  }
  figure {
    margin: 0;
    flex: none;
    width: 112px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  figure img {
    width: 100%;
    aspect-ratio: 4 / 3;
    object-fit: cover;
    border-radius: var(--radius-btn);
    display: block;
    background: #000;
  }
  figcaption {
    color: var(--outline);
  }
  .said {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
  .said p {
    margin: 0;
    color: var(--on-surface-var);
    font-style: italic;
  }
  .said p.own {
    white-space: pre-line;
    overflow-wrap: anywhere;
  }
  .reading {
    color: var(--on-surface-var);
  }
  .read {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .top {
    justify-content: space-between;
  }
  .line {
    margin: 0;
    font-size: var(--text-product-lead);
    line-height: 1.4;
    overflow-wrap: anywhere;
  }
  .sep {
    color: var(--outline);
    margin: 0 6px;
  }
  .facts {
    gap: 6px;
  }
  .verdict {
    display: flex;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-btn);
  }
  .verdict p {
    margin: 2px 0 0;
  }
  .verdict.bad {
    background: color-mix(in srgb, var(--error) 14%, transparent);
    color: var(--error);
  }
  .verdict.bad p:not(.muted) {
    color: var(--on-surface);
  }
  .verdict.wait {
    background: color-mix(in srgb, var(--warn) 14%, transparent);
    color: var(--warn-text);
  }
  .verdict.wait p {
    color: var(--on-surface);
  }
  .safe {
    color: var(--primary);
    gap: 6px;
  }
  .ask,
  .qs {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-top: var(--space-3);
    border-top: var(--border-width) solid var(--divider);
  }
  .ask p {
    margin: 0;
  }
  .answer input {
    flex: 1;
    min-width: 160px;
  }
  .qs ul {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 4px;
    color: var(--on-surface-var);
  }
  .qs li {
    display: flex;
    gap: 6px;
    align-items: baseline;
  }
  p {
    margin: 0;
  }
  .err {
    color: var(--error);
  }
</style>
