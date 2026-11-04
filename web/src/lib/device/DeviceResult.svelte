<script lang="ts">
  // The hand-over of a device job in the chat: what was built and what was checked, row by row from the facts (the board's
  // DRC, the case's check against the board, the firmware's compile check), and what was not: no run has been on real
  // hardware. The requirements the designer wrote with the parts serving each (a click lights them on the schematic) and
  // the way on to the price and the fab files.
  import type { ProjectStore } from '$lib/project.svelte';
  import type { ResultCard } from '$lib/types';
  import { modelName } from '$lib/models';
  import { dt, sizeIn } from './i18n';

  let { store, result, onAction }: { store: ProjectStore; result: ResultCard; onAction: (a: string) => void } = $props();
  const pcb = $derived(store.pcb.versions.at(-1) ?? null);
  const doc = $derived(store.device.state?.doc ?? null);
  const fw = $derived(doc?.firmware ?? null);
  const check = $derived(fw?.check ?? null);
  const critic = $derived(result.critic ?? null);
  // the case check of this result (make_enclosure's case_fit.case_mm reaches the card as enclosure.summary.case_mm),
  // else the studio's latest
  const enc = $derived(result.enclosure ?? store.enclosure?.check ?? null);
  const caseMm = $derived((enc?.summary as { case_mm?: number[] } | undefined)?.case_mm ?? null);
  const items = $derived([
    {
      stage: 'board', ok: !!pcb && !pcb.drc.errors,
      text: pcb ? (pcb.drc.errors ? dt('st_drc_err', { n: pcb.drc.errors }) : dt('res_board_ok', { v: pcb.version })) : dt('board_empty_title'),
    },
    {
      stage: 'case', ok: store.casePcbVersion != null && enc?.ok !== false,
      text: store.casePcbVersion == null ? dt('case_empty_title') : enc?.ok === false ? dt('res_case_bad') : caseMm ? dt('res_case_ok_size', { s: sizeIn(caseMm) }) : dt('res_case_ok'),
    },
    {
      stage: 'firmware', ok: !!fw && check?.ok !== false,
      text: !fw ? dt('fw_empty_title') : !check ? dt('res_fw_unchecked') : check.ok ? dt('res_fw_ok') : dt('fw_check_bad', { n: check.errors?.length ?? 0 }),
    },
  ]);
  const allOk = $derived(items.every((i) => i.ok));
  const reqs = $derived(doc?.requirements ?? []);
  let open = $state(false);

  function light(id: string, parts: string[]) {
    store.device.light(id, parts);
    onAction('stage:schematic');
  }
</script>

<div class="dr">
  <strong class="ttl">{allOk ? dt('result_title') : dt('result_title_issues')}</strong>
  <ul class="rows">
    {#each items as it (it.stage)}
      <li>
        <button class="it" class:bad={!it.ok} onclick={() => onAction(`stage:${it.stage}`)}>
          <i class="ti {it.ok ? 'ti-check' : 'ti-alert-triangle'}" aria-hidden="true"></i>{it.text}
        </button>
      </li>
    {/each}
  </ul>
  {#if critic?.verdict}<span class="crit" title={modelName(critic.model ?? '')}>{dt('result_review_short', { s: critic.match_score ?? '—' })}</span>{/if}
  {#if reqs.length}
    <button class="fold" onclick={() => (open = !open)} aria-expanded={open}>
      <i class="ti ti-chevron-right ar" class:down={open} aria-hidden="true"></i>{dt('reqs_title', { n: reqs.length })}
    </button>
    {#if open}
      <ul class="reqs">
        {#each reqs as r (r.id)}
          <li>
            <button class="rq" onclick={() => light(r.id, r.parts ?? [])} title={dt('reqs_light')}>
              <span class="mono rid">{r.id}</span>
              <span class="rt">{r.text}{#if r.firmware}<i class="ti ti-code fwi" title={dt('reqs_fw')} aria-hidden="true"></i>{/if}</span>
              <span class="mono parts">{(r.parts ?? []).join(' ')}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
  <button class="go" onclick={() => onAction('stage:make')}>{dt('stage_make')} <i class="ti ti-arrow-right" aria-hidden="true"></i></button>
</div>

<style>
  .dr {
    display: grid;
    gap: 6px;
    padding-top: var(--space-3);
    border-top: 1px solid var(--outline-variant);
    font-size: var(--text-md);
  }
  .ttl {
    font-size: var(--text-md);
  }
  .rows,
  .reqs {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 1px;
  }
  .it {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    padding: 1px 0;
    border: none;
    background: none;
    color: var(--on-surface);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .it:hover {
    text-decoration: underline;
  }
  .it i {
    color: var(--on-surface-var);
  }
  .it.bad {
    color: var(--warn-text);
  }
  .it.bad i {
    color: inherit;
  }
  .crit {
    font-size: var(--text-sm);
    color: var(--on-surface-var);
  }
  .go {
    justify-self: start;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 0;
    border: none;
    background: none;
    color: var(--primary);
    font: inherit;
    font-weight: var(--font-weight-semibold);
    cursor: pointer;
  }
  .go:hover {
    text-decoration: underline;
  }
  .fold {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    justify-self: start;
    padding: 0;
    border: none;
    background: none;
    color: var(--on-surface-var);
    font: inherit;
    cursor: pointer;
  }
  .ar {
    font-size: var(--text-xs);
    transition: transform var(--dur-fast) var(--ease-standard);
  }
  .ar.down {
    transform: rotate(90deg);
  }
  .rq {
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 8px;
    align-items: baseline;
    width: 100%;
    padding: 3px 4px;
    border: none;
    border-radius: var(--radius-xs);
    background: none;
    color: var(--on-surface);
    font: inherit;
    font-size: var(--text-sm);
    text-align: left;
    cursor: pointer;
  }
  .rq:hover {
    background: color-mix(in srgb, var(--on-surface) 7%, transparent);
  }
  .rid,
  .parts {
    font-size: var(--text-xs);
    color: var(--on-surface-var);
  }
  .parts {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fwi {
    font-size: var(--text-xs);
    margin-left: 4px;
    color: var(--on-surface-var);
  }
</style>
