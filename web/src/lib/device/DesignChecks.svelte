<script lang="ts">
  // What the netlist already tells before any routing, in two piles: errors (a pin or part that could not be read, an
  // electrical rule broken: device_rules with severity 'error') and warnings (lint, rules for the designer to weigh),
  // each naming its part (a click selects it) and how to fix it. Below them the device reviewer's verdict, when there is
  // one: its issues in the person's language.
  import Icon from '$lib/components/Icon.svelte';
  import type { DeviceStore } from './store.svelte';
  import type { Issue, Review } from './api';
  import { refNode, sortChecks } from './facets';
  import { modelName } from '$lib/models';
  import { i18n } from '$lib/i18n.svelte';
  import { dt, known } from './i18n';

  let { device, onSend, review = null }: { device: DeviceStore; onSend?: (msg: string) => void; review?: Review | null } = $props();
  const sorted = $derived(sortChecks(device.state));
  const errors = $derived(sorted.errors);
  const warnings = $derived(sorted.warnings);
  const all = $derived([...errors, ...warnings]);
  // the server says each check in English with its specifics (the part, the pin, the milliamps): in English that is the
  // text; in another language a check the UI knows by its code is said in it, the server's words kept as the details
  const own = (c: Issue) => i18n.lang !== 'en' && known(`lint_${c.code}`, '') !== '';
  const text = (c: Issue) => (own(c) ? dt(`lint_${c.code}`, { ref: c.ref }) : c.msg);
  const details = (c: Issue) => [own(c) ? c.msg : '', c.hint ?? ''].filter(Boolean).join(' · ');
  const issuesOf = $derived((review?.issues ?? []).filter((i) => i.severity !== 'info'));
  const passed = $derived(review?.verdict === 'pass');
</script>

{#snippet list(items: Issue[], sev: 'error' | 'warning')}
  <ul class={sev}>
    {#each items as c, i (i)}
      <li>
        <i class="ti {sev === 'error' ? 'ti-alert-triangle' : 'ti-info-circle'} sev" aria-hidden="true"></i>
        <span class="body">
          <span class="small">
            {#if c.ref}<button class="ref mono" onclick={() => device.pickNode(refNode(c.ref) || null)}>{refNode(c.ref)}</button>{/if}
            {text(c)}
          </span>
          {#if details(c)}<span class="hint xs">{details(c)}</span>{/if}
        </span>
      </li>
    {/each}
  </ul>
{/snippet}

<div class="checks">
  {#if !all.length}
    <p class="ok small"><Icon name="check-circle" size={16} /> {dt('checks_ok')}</p>
    <p class="xs muted">{dt('checks_scope')}</p>
  {:else}
    {#if errors.length}
      <h5 class="cap err">{dt('checks_errors', { n: errors.length })}</h5>
      {@render list(errors, 'error')}
    {/if}
    {#if warnings.length}
      <h5 class="cap warn">{dt('checks_warnings', { n: warnings.length })}</h5>
      {@render list(warnings, 'warning')}
    {/if}
    {#if onSend}
      <button class="btn small" onclick={() => onSend?.(dt('fix_msg', { e: all.map((c) => `${c.severity === 'error' ? 'ERROR ' : ''}${c.ref}: ${c.msg}`).join('; ') }))}><Icon name="wand" size={14} /> {dt('ask_agent_fix')}</button>
    {/if}
  {/if}

  {#if review?.verdict && review.verdict !== 'unavailable'}
    <div class="review">
      <h5 class="cap">
        {dt('review_title')}
        <span class="verdict" class:pass={passed} class:revise={!passed}>{passed ? dt('review_pass') : dt('review_revise')}{review.match_score != null ? ` · ${review.match_score}/10` : ''}</span>
      </h5>
      {#if issuesOf.length}
        <ul class="rv">
          {#each issuesOf as it, i (i)}
            <li class:major={it.severity === 'critical' || it.severity === 'major' || it.severity === 'error'}>
              <i class="ti {it.severity === 'minor' ? 'ti-info-circle' : 'ti-alert-triangle'} sev" aria-hidden="true"></i>
              <span class="small">{it.text_user || it.text}</span>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="xs muted">{dt('review_clean')}</p>
      {/if}
      <p class="xs muted">{dt('review_by', { m: review.model ? modelName(review.model) : '—', v: review.version ?? '—' })}</p>
    </div>
  {/if}
</div>

<style>
  .checks {
    display: grid;
    gap: var(--space-2);
  }
  .ok {
    display: flex;
    gap: 8px;
    align-items: center;
    margin: 0;
    color: var(--ok);
  }
  .checks p {
    margin: 0;
  }
  .cap {
    margin: 4px 0 0;
    font-size: var(--text-xs);
    font-weight: var(--font-weight-semibold);
    color: var(--on-surface-var);
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .cap.err {
    color: var(--error);
  }
  .cap.warn {
    color: var(--warn-text);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 7px;
  }
  li {
    display: grid;
    grid-template-columns: 14px 1fr;
    gap: 6px;
    align-items: baseline;
  }
  .sev {
    font-size: var(--text-md);
    color: var(--warn-text);
  }
  ul.error .sev,
  .rv li.major .sev {
    color: var(--error);
  }
  .body {
    display: grid;
    gap: 2px;
    min-width: 0;
  }
  .hint {
    color: var(--on-surface-var);
  }
  .ref {
    font-size: var(--text-xs);
    border: 1px solid var(--outline-variant);
    background: var(--surface-container);
    color: var(--on-surface);
    border-radius: var(--radius-sm);
    padding: 0 5px;
    margin-right: 4px;
    cursor: pointer;
  }
  .review {
    display: grid;
    gap: 6px;
    padding-top: 6px;
    border-top: 1px solid var(--divider);
  }
  .verdict {
    text-transform: none;
    font-weight: var(--font-weight-medium);
    padding: 0 6px;
    border-radius: var(--radius-xs);
  }
  .verdict.pass {
    color: var(--ok);
    background: color-mix(in srgb, var(--ok) 12%, transparent);
  }
  .verdict.revise {
    color: var(--warn-text);
    background: color-mix(in srgb, var(--warn) 16%, transparent);
  }
</style>
