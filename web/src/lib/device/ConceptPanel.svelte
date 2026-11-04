<script lang="ts">
  // The device's concept (doc.concept) as the designer brainstormed it before the parts: the uses it imagined, the
  // options as small cards (the look, the case's form, stance and mounting, the board), the chosen one marked with why.
  // Read-only: the designer writes it with write_device.
  import type { ConceptOption, DevConcept } from './api';
  import { dt, known } from './i18n';

  let { concept }: { concept: DevConcept } = $props();
  const uses = $derived(concept.uses ?? []);
  const options = $derived(concept.options ?? []);

  const word = (prefix: string, v?: string) => (v ? known(`${prefix}_${v}`, v) : '');
  function facts(o: ConceptOption): string[] {
    const b = o.board;
    return [
      word('cf', o.form),
      word('cs', o.stance),
      o.mounting && o.mounting !== 'none' ? word('cm', o.mounting) : '',
      b?.w && b?.h ? dt('concept_board', { shape: word('cb', b.shape) || '', w: b.w, h: b.h }) : '',
      o.module_edge ? dt('concept_module', { edge: known(`edge_${o.module_edge}`, o.module_edge) }) : '',
    ].filter(Boolean);
  }
</script>

<div class="concept">
  {#if uses.length}
    <h5 class="cap">{dt('concept_uses')}</h5>
    <ul class="uses small">
      {#each uses as u, i (i)}<li>{u}</li>{/each}
    </ul>
  {/if}
  {#if options.length}
    <h5 class="cap">{dt('concept_options')}</h5>
    <ul class="opts">
      {#each options as o (o.name)}
        {@const on = o.name === concept.chosen}
        <li class="opt" class:on>
          <div class="top">
            <span class="nm">{o.name}</span>
            {#if on}<span class="badge"><i class="ti ti-check" aria-hidden="true"></i> {dt('concept_chosen')}</span>{/if}
          </div>
          {#if o.look}<p class="small">{o.look}</p>{/if}
          <p class="xs muted">{facts(o).join(' · ')}</p>
          {#if on && o.panel}<p class="xs"><span class="muted">{dt('concept_panel')}:</span> {o.panel}</p>{/if}
          {#if on && concept.why}<p class="xs why">{concept.why}</p>{/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .concept {
    display: grid;
    gap: var(--space-2);
  }
  .concept p {
    margin: 0;
  }
  .cap {
    margin: 4px 0 0;
    font-size: 11px;
    font-weight: var(--font-weight-semibold);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--on-surface-var);
  }
  .uses {
    margin: 0;
    padding-left: 16px;
    display: grid;
    gap: 3px;
    line-height: 1.35;
  }
  .opts {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 6px;
  }
  .opt {
    display: grid;
    gap: 3px;
    padding: 6px 8px;
    border: 1px solid var(--outline-variant);
    border-radius: 6px;
    line-height: 1.35;
  }
  .opt.on {
    border-color: var(--primary);
    background: color-mix(in srgb, var(--primary) 10%, transparent);
  }
  .top {
    display: flex;
    gap: 8px;
    align-items: baseline;
    justify-content: space-between;
  }
  .nm {
    font-size: 12.5px;
    font-weight: var(--font-weight-semibold);
    color: var(--on-surface);
  }
  .badge {
    font-size: 11px;
    color: var(--primary);
    white-space: nowrap;
  }
  .why {
    color: var(--on-surface);
    font-style: italic;
  }
</style>
