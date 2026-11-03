<script lang="ts">
  // The hand-over of a device job in the chat, in one line: what is ready (the workspace tabs carry the details) and
  // the way on to manufacturing.
  import type { ProjectStore } from '$lib/project.svelte';
  import type { ResultCard } from '$lib/types';
  import { modelName } from '$lib/models';
  import { dt } from './i18n';

  let { store, result, onAction }: { store: ProjectStore; result: ResultCard; onAction: (a: string) => void } = $props();
  const pcb = $derived(store.pcb.versions.at(-1) ?? null);
  const fw = $derived(store.device.state?.doc.firmware ?? null);
  const critic = $derived(result.critic ?? null);
  const items = $derived([
    { stage: 'board', ok: !!pcb && !pcb.drc.errors, text: pcb ? `${dt('stage_board')} v${pcb.version}` : dt('stage_board') },
    { stage: 'case', ok: store.casePcbVersion != null, text: dt('stage_case') },
    { stage: 'firmware', ok: !!fw, text: dt('stage_firmware') },
  ]);
</script>

<div class="dr">
  <i class="ti ti-circle-check ok" aria-hidden="true"></i>
  <span class="ttl">{dt('result_title')}</span>
  {#each items as it (it.stage)}
    <button class="it" class:ok={it.ok} onclick={() => onAction(`stage:${it.stage}`)}><i class="ti {it.ok ? 'ti-check' : 'ti-minus'}" aria-hidden="true"></i>{it.text}</button>
  {/each}
  {#if critic?.verdict}<span class="crit" title={modelName(critic.model ?? '')}>{dt('result_review_short', { s: critic.match_score ?? '—' })}</span>{/if}
  <button class="go" onclick={() => onAction('stage:make')}>{dt('stage_make')} <i class="ti ti-arrow-right" aria-hidden="true"></i></button>
</div>

<style>
  .dr {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 6px;
    padding: 6px 8px;
    border-radius: 4px;
    border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--outline-variant));
    background: color-mix(in srgb, var(--ok) 7%, transparent);
    font-size: 12px;
  }
  .ok {
    color: var(--ok);
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
  .crit {
    font-size: 11px;
    color: var(--on-surface-var);
  }
  .go {
    margin-left: auto;
    background: var(--primary);
    color: var(--on-primary);
  }
</style>
