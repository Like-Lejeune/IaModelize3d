<script lang="ts">
  // The Manufacturing stage's main view: what each step costs and when the devices are ready (the bill of materials
  // has its own stage).
  import type { QuoteState } from './quote.svelte';
  import { dt, usd, kzt, date, groupNote } from './i18n';

  let { q, built }: { q: QuoteState; built: boolean } = $props();
  const quote = $derived(q.quote);
</script>

<div class="oc">
  {#if !built}
    <div class="empty">
      <i class="ti ti-building-factory-2 big" aria-hidden="true"></i>
      <h3>{dt('mfg_empty_title')}</h3>
      <p class="muted small">{dt('quote_need_build')}</p>
    </div>
  {:else if !quote}
    <div class="empty">{#if q.error}<p class="err small">{q.error}</p>{:else}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{/if}</div>
  {:else}
    <div class="scroll" class:busy={q.busy}>
      <section class="summary">
        <div class="big-total">
          <span class="lbl xs muted">{dt('total_for', { n: quote.qty })}</span>
          <strong>{usd(quote.total_usd)}</strong>
          <span class="muted">{kzt(quote.total_kzt)} · {dt('per_device', { p: usd(quote.per_device_usd) })}</span>
        </div>
        <div class="kpis">
          <div><span class="xs muted">{dt('kpi_board')}</span><strong class="mono">{quote.board_mm[0]} × {quote.board_mm[1]} {dt('mm')}</strong></div>
          <div><span class="xs muted">{dt('kpi_lines')}</span><strong class="mono">{quote.bom.length}</strong></div>
          <div><span class="xs muted">{dt('kpi_ready')}</span><strong>{date(quote.eta)}</strong></div>
        </div>
      </section>

      <section>
        <h3>{dt('cost')}</h3>
        <div class="bars">
          {#each quote.groups as g (g.key)}
            <div class="bar">
              <span class="gname">{dt(`g_${g.key}`)}</span>
              <span class="track"><span class="fill" style="width: {Math.max(2, (g.usd / quote.total_usd) * 100)}%"></span></span>
              <span class="mono">{usd(g.usd)}</span>
              <span class="xs muted note">{groupNote(g)}</span>
            </div>
          {/each}
        </div>
      </section>

      <section>
        <h3>{dt('timeline')}</h3>
        <ol class="timeline">
          {#each quote.timeline as s, i (s.key)}
            <li><span class="dot">{i + 1}</span><span>{dt(`t_${s.key}`)}</span><span class="muted small">{date(s.by)}</span></li>
          {/each}
        </ol>
      </section>
    </div>
  {/if}
</div>

<style>
  .oc {
    position: absolute;
    inset: 0;
    display: flex;
    background: var(--surface);
  }
  .scroll {
    flex: 1;
    overflow: auto;
    padding: var(--space-5);
    display: grid;
    gap: var(--space-5);
    align-content: start;
  }
  .scroll.busy {
    opacity: 0.6;
  }
  section {
    display: grid;
    gap: var(--space-2);
  }
  h3 {
    margin: 0;
    font-size: 15px;
  }
  .summary {
    display: flex;
    gap: var(--space-5);
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
  }
  .big-total {
    display: grid;
    gap: 2px;
  }
  .big-total strong {
    font-size: 34px;
    line-height: 1.1;
  }
  .kpis {
    display: flex;
    gap: var(--space-4);
  }
  .kpis div {
    display: grid;
    gap: 2px;
    padding: 8px 12px;
    border-radius: 10px;
    background: var(--surface-container-low);
    border: 1px solid var(--outline-variant);
  }
  .bars {
    display: grid;
    gap: 6px;
  }
  .bar {
    display: grid;
    grid-template-columns: 170px 1fr 70px;
    gap: 4px 10px;
    align-items: center;
    font-size: 13px;
  }
  .track {
    height: 8px;
    border-radius: 4px;
    background: var(--surface-container-high, var(--surface-high));
    overflow: hidden;
  }
  .fill {
    display: block;
    height: 100%;
    border-radius: 4px;
    background: var(--primary);
  }
  .bar .mono {
    text-align: right;
  }
  .note {
    grid-column: 2 / -1;
    margin-top: -4px;
  }
  .timeline {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 8px;
  }
  .timeline li {
    display: grid;
    grid-template-columns: 22px 1fr auto;
    gap: 10px;
    align-items: center;
    font-size: 13px;
  }
  .dot {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 11px;
    background: var(--primary-container);
    color: var(--on-primary-container);
  }
  .empty {
    margin: auto;
    max-width: 420px;
    text-align: center;
    display: grid;
    gap: var(--space-2);
    justify-items: center;
    padding: var(--space-5);
  }
  .empty h3,
  .empty p {
    margin: 0;
  }
  .big {
    font-size: 36px;
    color: var(--primary);
  }
  @media (max-width: 700px) {
    .scroll {
      padding: var(--space-3);
    }
    .bar {
      grid-template-columns: 120px 1fr 64px;
    }
  }
</style>
