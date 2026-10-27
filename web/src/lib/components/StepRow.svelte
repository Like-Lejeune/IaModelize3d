<script lang="ts">
  import Icon from './Icon.svelte';
  import { t } from '$lib/i18n.svelte';
  import { KIND_ICON, callTitle, resultTitle } from '$lib/steps';
  import type { TimelineItem } from '$lib/project.svelte';

  let { item, onZoom }: { item: Extract<TimelineItem, { kind: 'tool' }>; onZoom: (url: string) => void } = $props();

  const pending = $derived(!item.result);
  const failed = $derived(item.result?.ok === false);
  const title = $derived(callTitle(item.name, item.args, item.title));
  const outcome = $derived(item.result ? resultTitle(item.name, item.args, item.result.summary, item.result.ok, item.result.title) : undefined);

  function pretty(v: any): string {
    if (v == null) return '';
    if (typeof v === 'string') {
      try {
        return JSON.stringify(JSON.parse(v), null, 1);
      } catch {
        return v;
      }
    }
    return JSON.stringify(v, null, 1);
  }
</script>

<div class="step" class:pending class:failed>
  <span class="ico" aria-hidden="true">
    {#if pending}<span class="spin"></span>{:else}<Icon name={failed ? 'alert' : (KIND_ICON[item.tkind] ?? 'check')} size={15} />{/if}
  </span>
  <div class="body">
    <div class="title">{title}</div>
    {#if outcome}<div class="outcome" class:bad={failed}>{outcome}</div>{/if}
    {#if item.result?.image}
      <button class="thumb" onclick={() => onZoom(item.result!.image!)} aria-label={t('view')}>
        <img src={item.result.image} alt="" loading="lazy" />
      </button>
    {/if}
    {#if item.args || item.result?.summary}
      <details class="raw">
        <summary>{t('details')}</summary>
        {#if item.args}<pre>{pretty(item.args)}</pre>{/if}
        {#if item.result?.summary}<pre>{pretty(item.result.summary)}</pre>{/if}
      </details>
    {/if}
  </div>
</div>

<style>
  .step {
    display: grid;
    grid-template-columns: 22px minmax(0, 1fr);
    gap: 8px;
    padding: 5px 0;
    font-size: var(--fs-sm);
  }
  .ico {
    width: 22px;
    height: 22px;
    border-radius: 7px;
    display: grid;
    place-items: center;
    background: var(--panel-3);
    color: var(--text-2);
  }
  .failed .ico {
    background: var(--err-soft);
    color: var(--err);
  }
  .pending .ico {
    background: var(--accent-soft);
  }
  .body {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding-top: 1px;
  }
  .title {
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .pending .title {
    color: var(--text);
    font-weight: 550;
  }
  .outcome {
    color: var(--muted);
    font-size: var(--fs-xs);
    overflow-wrap: anywhere;
  }
  .outcome.bad {
    color: var(--err);
  }
  .thumb {
    margin-top: 4px;
    padding: 0;
    border: 1px solid var(--line);
    border-radius: 8px;
    overflow: hidden;
    background: var(--panel-2);
    width: min(100%, 300px);
    cursor: zoom-in;
  }
  .thumb img {
    display: block;
    width: 100%;
  }
  .raw summary {
    font-size: var(--fs-xs);
    color: var(--muted);
    cursor: pointer;
    width: fit-content;
    list-style: none;
  }
  .raw summary::before {
    content: '▸ ';
  }
  .raw[open] summary::before {
    content: '▾ ';
  }
  .raw pre {
    margin: 4px 0 0;
    font-family: var(--mono);
    font-size: 11px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 220px;
    overflow: auto;
    background: var(--panel-2);
    border-radius: 6px;
    padding: 6px;
  }
</style>
