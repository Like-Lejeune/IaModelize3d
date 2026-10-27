<script lang="ts">
  // One line of agent work inside a step group; click to see everything behind it.
  import Icon from './Icon.svelte';
  import { t } from '$lib/i18n.svelte';
  import { KIND_ICON, callTitle, resultTitle, statusLine } from '$lib/steps';
  import type { TimelineItem } from '$lib/project.svelte';

  let { item, onZoom }: { item: TimelineItem; onZoom: (url: string) => void } = $props();

  let open = $state(false);

  const line = $derived.by(() => {
    switch (item.kind) {
      case 'tool': {
        const failed = item.result?.ok === false;
        return {
          icon: failed ? 'alert' : (KIND_ICON[item.tkind] ?? 'check'),
          title: callTitle(item.name, item.args, item.title),
          note: item.result ? resultTitle(item.name, item.args, item.result.summary, item.result.ok, item.result.title) : undefined,
          bad: failed,
          pending: !item.result,
          more: !!(item.args || item.result?.summary || item.result?.image),
        };
      }
      case 'critic':
        return {
          icon: 'eye',
          title: t('critic'),
          note: t(item.verdict) + (item.score != null ? ` · ${t('score_of', { s: item.score })}` : ''),
          bad: item.verdict !== 'pass',
          pending: false,
          more: item.issues.length > 0,
        };
      case 'facts':
        return { icon: 'search', title: t('facts'), note: String(item.items.length), bad: false, pending: false, more: item.items.length > 0 };
      case 'memory':
        return { icon: 'brain', title: item.items.map((m) => m.name).join(', '), note: undefined, bad: false, pending: false, more: false };
      case 'status':
        return { icon: 'info', title: statusLine(item.text), note: undefined, bad: false, pending: false, more: false };
      default:
        return { icon: 'check', title: item.kind, note: undefined, bad: false, pending: false, more: false };
    }
  });

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

<div class="step" class:open class:pending={line.pending} class:bad={line.bad}>
  <button class="head" onclick={() => (open = !open)} disabled={!line.more} aria-expanded={line.more ? open : undefined}>
    <span class="ico" aria-hidden="true">{#if line.pending}<span class="dot"></span>{:else}<Icon name={line.icon} size={14} />{/if}</span>
    <span class="txt">
      <span class="title" class:shimmer={line.pending}>{line.title}</span>
      {#if line.note}<span class="note">{line.note}</span>{/if}
    </span>
    {#if line.more}<span class="chev" aria-hidden="true"><Icon name="chevron" size={13} /></span>{/if}
  </button>
  {#if open}
    <div class="body">
      {#if item.kind === 'tool'}
        {#if item.result?.image}
          <button class="thumb" onclick={() => onZoom(item.result!.image!)} aria-label={t('view')}><img src={item.result.image} alt="" loading="lazy" /></button>
        {/if}
        {#if item.args}<pre>{pretty(item.args)}</pre>{/if}
        {#if item.result?.summary}<pre>{pretty(item.result.summary)}</pre>{/if}
      {:else if item.kind === 'critic'}
        <ul>{#each item.issues as is, i (i)}<li class:major={is.severity === 'major'}>{is.text}</li>{/each}</ul>
      {:else if item.kind === 'facts'}
        <ul>
          {#each item.items as f, i (i)}
            <li>
              {f.subject} · {f.attribute}: <strong class="mono">{typeof f.value === 'number' ? f.value : String(f.value).replace(/^"|"$/g, '')} {f.unit ?? ''}</strong>
              {#if f.source_url}<a href={f.source_url} target="_blank" rel="noopener noreferrer">{new URL(f.source_url).hostname.replace(/^www\./, '')} ↗</a>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
</div>

<style>
  .step + :global(.step) {
    border-top: 1px solid var(--line);
  }
  .head {
    width: 100%;
    display: grid;
    grid-template-columns: 18px minmax(0, 1fr) 14px;
    gap: 8px;
    align-items: start;
    padding: 7px 10px;
    border: none;
    background: none;
    text-align: left;
    color: var(--text-2);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .head:disabled {
    cursor: default;
    opacity: 1;
  }
  .head:not(:disabled):hover {
    background: var(--panel-2);
  }
  .ico {
    height: 20px;
    display: grid;
    place-items: center;
    color: var(--muted);
  }
  .bad .ico {
    color: var(--err);
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent);
    animation: fw-dot 1s ease-in-out infinite alternate;
  }
  @keyframes fw-dot {
    to {
      opacity: 0.3;
    }
  }
  .txt {
    min-width: 0;
    display: flex;
    flex-direction: column;
    line-height: 20px;
  }
  .title,
  .note {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .open .title,
  .open .note {
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .note {
    font-size: var(--fs-xs);
    color: var(--muted);
    line-height: 17px;
  }
  .bad .note {
    color: var(--err);
  }
  .chev {
    height: 20px;
    display: grid;
    place-items: center;
    color: var(--muted);
    transition: transform 0.12s;
  }
  .open .chev {
    transform: rotate(90deg);
  }
  .body {
    padding: 0 10px 10px 36px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: var(--fs-sm);
  }
  .thumb {
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
  pre {
    margin: 0;
    font-family: var(--mono);
    font-size: 11px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 220px;
    overflow: auto;
    background: var(--panel-2);
    border-radius: 6px;
    padding: 6px 8px;
    color: var(--text-2);
  }
  ul {
    margin: 0;
    padding-left: 18px;
    color: var(--text-2);
  }
  li.major {
    font-weight: 550;
  }
</style>
