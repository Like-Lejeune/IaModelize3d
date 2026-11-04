<script lang="ts">
  // The order's journal (shop_log): the steps it went through with time and who moved it, under a progress rail.
  // Each note comes as a code with parameters and is said in the UI's language (noteText); the farm sees its details.
  import Icon from '$lib/components/Icon.svelte';
  import { noteText, st, when } from './i18n';
  import type { Order, OrderStatus } from './types';

  let { order, show = 'both', compact = false }: { order: Order; show?: 'rail' | 'log' | 'both'; compact?: boolean } = $props();

  const FINAL_BAD: OrderStatus[] = ['refused', 'cancelled', 'expired'];
  // a part that already has a model (catalog, studio) goes straight to the slicer quote
  const steps = $derived<OrderStatus[]>(
    ['requested', ...(order.intake?.request?.kind === 'photo' ? (['designing'] as OrderStatus[]) : []), 'quoted', 'paid', 'printing', 'qc', 'shipped', 'delivered'] as OrderStatus[],
  );
  // where the order stands on the rail: needs_info is part of designing, a stopped order stays where it stopped
  const reached = $derived.by(() => {
    const seen = new Set<OrderStatus>((order.timeline ?? []).map((e) => (e.status === 'needs_info' ? 'designing' : e.status)));
    seen.add(order.status === 'needs_info' ? 'designing' : order.status);
    let last = 0;
    steps.forEach((s, i) => seen.has(s) && (last = i));
    return last;
  });
  const stopped = $derived(FINAL_BAD.includes(order.status));
  // a stopped order shows the steps it reached and then where it stopped (received · designed · priced · cancelled):
  // no steps it will never take, and none of them current
  const shown = $derived(stopped ? steps.slice(0, reached + 1) : steps);
  // a step that is work rather than a moment (designing, printing, QC) was cut short when the order stopped in it
  const PROCESS: OrderStatus[] = ['designing', 'printing', 'qc'];
  const cut = (i: number) => stopped && i === reached && PROCESS.includes(steps[i]);
  const done = (i: number) => i < reached || (i === reached && (order.status === 'delivered' || (stopped && !cut(i))));
  const entries = $derived(order.timeline ?? []);
</script>

<div class="tl" class:compact>
  {#if show !== 'log'}
  <ol class="rail" aria-label={st('tl.title')}>
    {#each shown as s, i (s)}
      <li title={st(`status.${s}`)} class:done={done(i)} class:now={i === reached && !stopped && order.status !== 'delivered'} class:cut={cut(i)}>
        <span class="dot" aria-hidden="true">
          {#if done(i)}<Icon name="check" size={12} />{/if}
        </span>
        <span class="lbl">{st(`status.${i === reached && order.status === 'needs_info' ? 'needs_info' : s}`)}</span>
      </li>
    {/each}
    {#if stopped}
      <li title={st(`status.${order.status}`)} class="stop">
        <span class="dot" aria-hidden="true"><Icon name="x" size={12} /></span>
        <span class="lbl">{st(`status.${order.status}`)}</span>
      </li>
    {/if}
  </ol>
  {/if}

  {#if show !== 'rail' && entries.length}
    <section class="log">
      <h3 class="section-title">{st('tl.title')}</h3>
      <ul>
        {#each entries as e, i (i)}
          {@const moved = e.status !== e.from}
          {@const note = noteText(e, order.actor === 'operator')}
          <li class:moved class:last={i === entries.length - 1}>
            <span class="pin" aria-hidden="true"></span>
            <div class="body">
              <div class="head">
                {#if moved}<strong>{st(`status.${e.status}`)}</strong>{/if}
                <span class="muted xs">{st(`actor.${e.actor}`)} · {when(e.ts)}</span>
              </div>
              {#if note}<p class="note xs">{note}</p>{/if}
            </div>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</div>

<style>
  .tl {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
  }
  .rail {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    gap: 0;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .rail li {
    flex: 1 1 0;
    min-width: 64px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    position: relative;
    text-align: center;
  }
  /* the line between two steps, drawn from this step's dot to the previous one */
  .rail li + li::before {
    content: '';
    position: absolute;
    top: 10px;
    right: 50%;
    width: 100%;
    height: 2px;
    background: var(--outline-variant);
  }
  .rail li.done::before,
  .rail li.now::before,
  .rail li.cut::before {
    background: var(--primary);
  }
  .rail li.stop::before {
    background: var(--error);
  }
  .dot {
    position: relative;
    z-index: 1;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--surface-container);
    border: 2px solid var(--outline-variant);
    color: var(--on-primary);
  }
  .done .dot {
    background: var(--primary);
    border-color: var(--primary);
  }
  .now .dot {
    border-color: var(--primary);
    box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary) 22%, transparent);
    animation: beat 1.8s var(--ease-standard) infinite;
  }
  .stop .dot {
    background: var(--error);
    border-color: var(--error);
    color: var(--surface);
  }
  /* reached, and stopped before it was done */
  .cut .dot {
    border-color: var(--primary);
    border-style: dashed;
  }
  @keyframes beat {
    50% {
      box-shadow: 0 0 0 7px color-mix(in srgb, var(--primary) 8%, transparent);
    }
  }
  .lbl {
    font-size: var(--text-sm);
    color: var(--outline);
    line-height: 1.2;
  }
  .done .lbl {
    color: var(--on-surface-var);
  }
  .now .lbl {
    color: var(--on-surface);
    font-weight: var(--font-weight-semibold);
  }
  .stop .lbl {
    color: var(--error);
    font-weight: var(--font-weight-semibold);
  }
  .cut .lbl {
    color: var(--on-surface-var);
  }
  .compact .rail li {
    min-width: 44px;
  }
  .compact .lbl {
    display: none;
  }
  .log {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .log ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .log li {
    display: grid;
    grid-template-columns: 14px minmax(0, 1fr);
    gap: var(--space-3);
    position: relative;
    padding-bottom: var(--space-3);
  }
  .log li:not(:last-child)::after {
    content: '';
    position: absolute;
    left: 6px;
    top: 14px;
    bottom: 0;
    width: 2px;
    background: var(--divider);
  }
  .pin {
    width: 8px;
    height: 8px;
    margin: 6px 3px 0;
    border-radius: 50%;
    background: var(--outline-variant);
  }
  .moved .pin {
    background: var(--primary);
  }
  .last .pin {
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 25%, transparent);
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 2px var(--space-2);
  }
  .head strong {
    font-size: var(--text-base);
  }
  .note {
    margin: 2px 0 0;
    color: var(--on-surface-var);
    overflow-wrap: anywhere;
  }
  /* a phone: the dots alone (the status chip above names the step), so the rail fits without scrolling */
  @media (max-width: 560px) {
    .rail li {
      min-width: 0;
    }
    .lbl {
      display: none;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .now .dot {
      animation: none;
    }
  }
</style>
