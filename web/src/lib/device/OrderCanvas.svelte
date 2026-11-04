<script lang="ts">
  // The Manufacturing stage's main view: what each step costs and when the devices are ready (the bill of materials
  // has its own stage), and the ready-made modules the workshop fits by hand, each with its price.
  import { t } from '$lib/i18n.svelte';
  import type { QuoteState } from './quote.svelte';
  import { accName, dt, usd, kzt, date, groupNote, known } from './i18n';

  let { q, built }: { q: QuoteState; built: boolean } = $props();
  const quote = $derived(q.quote);
  // quote_for lists them as BOM rows of kind 'accessory' (or of the 'modules' group)
  const fitted = $derived((quote?.bom ?? []).filter((b) => b.kind === 'accessory' || !!b.accessory || b.group === 'modules'));
</script>

<div class="oc">
  {#if !built}
    <div class="empty">
      <i class="ti ti-building-factory-2 big" aria-hidden="true"></i>
      <h3>{dt('mfg_empty_title')}</h3>
      <p class="muted small">{dt('quote_need_build')}</p>
    </div>
  {:else if !quote}
    <div class="empty">{#if q.error}<p class="err small" role="alert">{q.error}</p><button class="btn small" onclick={() => q.retry()} disabled={q.busy}>{t('retry')}</button>{:else}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{/if}</div>
  {:else}
    <div class="scroll" class:busy={q.busy}>
      <section class="summary">
        <div class="big-total">
          <span class="lbl xs muted">{dt('total_for', { n: quote.qty })}</span>
          <strong>{usd(quote.total_usd)}</strong>
          <span class="muted">{kzt(quote.total_kzt)} · {dt('per_device', { p: usd(quote.per_device_usd) })} · {dt('ready_by', { d: date(quote.eta) })}</span>
          <span class="xs muted">{dt('quote_estimate')}</span>
        </div>
      </section>

      <section>
        <h3>{dt('cost')}</h3>
        <div class="bars">
          {#each quote.groups as g (g.key)}
            <div class="bar">
              <span class="gname">{known(`g_${g.key}`, g.key)}</span>
              <span class="track"><span class="fill" style="width: {Math.max(2, (g.usd / quote.total_usd) * 100)}%"></span></span>
              <span class="mono">{usd(g.usd)}</span>
              <span class="xs muted note">{groupNote(g)}</span>
            </div>
          {/each}
        </div>
      </section>

      {#if fitted.length}
        <section>
          <h3>{dt('fitted_title')}</h3>
          <p class="xs muted">{dt('accessory_d')}</p>
          <table class="fit">
            <tbody>
              {#each fitted as b, i (i)}
                <tr>
                  <td class="mono refs">{b.refs.join(', ')}</td>
                  <td>{#if b.url}<a href={b.url} target="_blank" rel="noopener noreferrer">{accName(b.name ?? b.mpn ?? b.label ?? '')}</a>{:else}{accName(b.name ?? b.mpn ?? b.label ?? '')}{/if}</td>
                  <td class="r mono">{b.qty} × {usd(b.unit_usd)}</td>
                  <td class="r mono">{usd(b.total_usd)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </section>
      {/if}

      <section>
        <h3>{dt('timeline')}</h3>
        <ol class="timeline">
          {#each quote.timeline as s, i (s.key)}
            <li><span class="dot">{i + 1}</span><span>{known(`t_${s.key}`, s.key)}</span><span class="muted small">{date(s.by)}</span></li>
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
    font-size: var(--text-lg);
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
    font-size: var(--text-4xl);
    line-height: 1.1;
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
    font-size: var(--text-md);
  }
  .track {
    height: 8px;
    border-radius: var(--radius-xs);
    background: var(--surface-container-high, var(--surface-high));
    overflow: hidden;
  }
  .fill {
    display: block;
    height: 100%;
    border-radius: var(--radius-xs);
    background: var(--primary);
  }
  .bar .mono {
    text-align: right;
  }
  .note {
    grid-column: 2 / -1;
    margin-top: -4px;
  }
  .fit {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-md);
  }
  .fit td {
    padding: 5px 8px;
    border-bottom: 1px solid var(--divider);
  }
  .fit .refs {
    font-size: var(--text-sm);
    color: var(--on-surface-var);
    width: 1%;
    white-space: nowrap;
  }
  .fit .r {
    text-align: right;
    white-space: nowrap;
  }
  .fit a {
    color: var(--primary);
    text-decoration: none;
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
    font-size: var(--text-md);
  }
  .dot {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: var(--text-xs);
    background: var(--surface-high);
    color: var(--on-surface-var);
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
    font-size: var(--text-4xl);
    color: var(--on-surface-var);
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
