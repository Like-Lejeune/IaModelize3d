<script lang="ts">
  // The hand-over of a device job in the chat: what is ready and whether it is right (the board's DRC, the case's check
  // against the board, the firmware's compile check), the case as it stands assembled (the result's size_mm is the
  // print plate, lid and base side by side, so it is named as such), the requirements the designer wrote with the parts
  // serving each (a click lights them on the schematic) and the way on to manufacturing.
  import type { ProjectStore } from '$lib/project.svelte';
  import type { ResultCard } from '$lib/types';
  import { modelName } from '$lib/models';
  import { sizeText } from './facets';
  import { dt } from './i18n';

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
  const plate = $derived(result.size_mm?.length ? result.size_mm : null);
  const items = $derived([
    { stage: 'board', ok: !!pcb && !pcb.drc.errors, text: pcb ? (pcb.drc.errors ? dt('st_drc_err', { n: pcb.drc.errors }) : `${dt('stage_board')} v${pcb.version}`) : dt('stage_board') },
    { stage: 'case', ok: store.casePcbVersion != null && enc?.ok !== false, text: dt('stage_case') },
    { stage: 'firmware', ok: !!fw && check?.ok !== false, text: check && !check.ok ? dt('fw_check_bad', { n: check.errors?.length ?? 0 }) : dt('stage_firmware') },
  ]);
  const allOk = $derived(items.every((i) => i.ok));
  const reqs = $derived(doc?.requirements ?? []);
  let open = $state(false);

  function light(id: string, parts: string[]) {
    store.device.light(id, parts);
    onAction('stage:schematic');
  }
</script>

<div class="dr" class:warn={!allOk}>
  <div class="line">
    <i class="ti {allOk ? 'ti-circle-check ok' : 'ti-alert-triangle wc'}" aria-hidden="true"></i>
    <span class="ttl">{allOk ? dt('result_title') : dt('result_title_issues')}</span>
    {#each items as it (it.stage)}
      <button class="it" class:ok={it.ok} class:bad={!it.ok} onclick={() => onAction(`stage:${it.stage}`)}><i class="ti {it.ok ? 'ti-check' : 'ti-minus'}" aria-hidden="true"></i>{it.text}</button>
    {/each}
    {#if critic?.verdict}<span class="crit" title={modelName(critic.model ?? '')}>{dt('result_review_short', { s: critic.match_score ?? '—' })}</span>{/if}
    <button class="go" onclick={() => onAction('stage:make')}>{dt('stage_make')} <i class="ti ti-arrow-right" aria-hidden="true"></i></button>
  </div>
  {#if caseMm || plate}
    <div class="sizes">
      {#if caseMm}<span>{dt('size_case')} <span class="mono">{sizeText(caseMm)} {dt('mm')}</span></span>{/if}
      {#if plate}<span class="muted" title={dt('size_plate_d')}>{dt('size_plate')} <span class="mono">{sizeText(plate)} {dt('mm')}</span></span>{/if}
    </div>
  {/if}
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
</div>

<style>
  .dr {
    display: grid;
    gap: 4px;
    padding: 6px 8px;
    border-radius: 4px;
    border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--outline-variant));
    background: color-mix(in srgb, var(--ok) 7%, transparent);
    font-size: 12px;
  }
  .dr.warn {
    border-color: color-mix(in srgb, var(--warn) 50%, var(--outline-variant));
    background: color-mix(in srgb, var(--warn) 7%, transparent);
  }
  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 6px;
  }
  .ok {
    color: var(--ok);
  }
  .wc {
    color: var(--warn-text);
  }
  .ttl {
    font-weight: var(--font-weight-semibold);
    margin-right: 4px;
  }
  .it,
  .go {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    height: 20px;
    padding: 0 7px;
    border-radius: 6px;
    border: none;
    background: var(--surface-container);
    color: var(--on-surface-var);
    font: inherit;
    font-size: 11.5px;
    cursor: pointer;
  }
  .it.ok {
    color: var(--on-surface);
  }
  .it.ok i {
    color: var(--ok);
  }
  .it.bad i {
    color: var(--warn-text);
  }
  .crit {
    font-size: 11px;
    color: var(--on-surface-var);
  }
  .go {
    margin-left: auto;
    background: var(--primary);
    color: var(--on-primary);
  }
  .sizes {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 12px;
    font-size: 11.5px;
    padding-left: 2px;
  }
  .sizes .mono {
    font-size: 11px;
  }
  .fold {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    justify-self: start;
    padding: 0 2px;
    border: none;
    background: none;
    color: var(--on-surface-var);
    font: inherit;
    font-size: 11.5px;
    cursor: pointer;
  }
  .ar {
    font-size: 11px;
    transition: transform var(--dur-fast) var(--ease-standard);
  }
  .ar.down {
    transform: rotate(90deg);
  }
  .reqs {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 1px;
  }
  .rq {
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 8px;
    align-items: baseline;
    width: 100%;
    padding: 3px 4px;
    border: none;
    border-radius: 4px;
    background: none;
    color: var(--on-surface);
    font: inherit;
    font-size: 12px;
    text-align: left;
    cursor: pointer;
  }
  .rq:hover {
    background: color-mix(in srgb, var(--on-surface) 7%, transparent);
  }
  .rid,
  .parts {
    font-size: 10.5px;
    color: var(--on-surface-var);
  }
  .parts {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fwi {
    font-size: 11px;
    margin-left: 4px;
    color: var(--on-surface-var);
  }
</style>
