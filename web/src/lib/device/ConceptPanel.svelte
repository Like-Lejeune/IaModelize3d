<script lang="ts">
  // The device's concept (doc.concept) as the designer brainstormed it before the parts: what was chosen and why, how it is
  // used, and the other options folded away. Read-only: the designer writes it with write_device.
  import type { ConceptOption, DevConcept } from './api';
  import { dt, known } from './i18n';

  let { concept }: { concept: DevConcept } = $props();
  const uses = $derived(concept.uses ?? []);
  const options = $derived(concept.options ?? []);
  const chosen = $derived(options.find((o) => o.name === concept.chosen) ?? null);
  const others = $derived(options.filter((o) => o !== chosen));

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
  {#if chosen}
    <div class="opt">
      <strong>{chosen.name}</strong>
      {#if chosen.look}<p>{chosen.look}</p>{/if}
      {#if chosen.panel}<p><span class="muted">{dt('concept_panel')}:</span> {chosen.panel}</p>{/if}
      {#if concept.why}<p>{concept.why}</p>{/if}
      <p class="muted">{facts(chosen).join(' · ')}</p>
    </div>
  {/if}
  {#if uses.length}
    <div class="opt">
      <strong>{dt('concept_uses')}</strong>
      <ul>
        {#each uses as u, i (i)}<li>{u}</li>{/each}
      </ul>
    </div>
  {/if}
  {#if others.length}
    <details>
      <summary>{dt('concept_others', { n: others.length })}</summary>
      {#each others as o (o.name)}
        <div class="opt">
          <strong>{o.name}</strong>
          {#if o.look}<p>{o.look}</p>{/if}
          <p class="muted">{facts(o).join(' · ')}</p>
        </div>
      {/each}
    </details>
  {/if}
</div>

<style>
  .concept {
    display: grid;
    gap: var(--space-4);
    font-size: var(--text-sm);
    line-height: 1.4;
  }
  .opt {
    display: grid;
    gap: 3px;
  }
  details .opt {
    margin-top: var(--space-3);
  }
  p {
    margin: 0;
  }
  strong {
    font-size: var(--text-md);
  }
  ul {
    margin: 0;
    padding-left: 16px;
    display: grid;
    gap: 3px;
  }
  summary {
    cursor: pointer;
    color: var(--on-surface-var);
  }
</style>
