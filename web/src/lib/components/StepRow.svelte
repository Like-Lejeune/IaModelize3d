<script lang="ts">
  // One line of agent work inside a step group; click to see everything behind it.
  import Icon from './Icon.svelte';
  import { t } from '$lib/i18n.svelte';
  import { isOpenWeights, modelName } from '$lib/models';
  import { KIND_ICON, TOOL_ICON, callTitle, resultTitle, statusLine, stepModels } from '$lib/steps';
  import type { TimelineItem } from '$lib/project.svelte';

  let { item, onZoom }: { item: TimelineItem; onZoom: (url: string) => void } = $props();

  let open = $state(false);

  // a fact's source as a link: a web address only (the model copies it from search results, and a 'javascript:' or
  // scheme-less one must neither run nor break the row), shown by its site
  function site(url: string | null | undefined): string | null {
    if (!url || !/^https?:\/\//i.test(url)) return null;
    try {
      return new URL(url).hostname.replace(/^www\./, '');
    } catch {
      return null;
    }
  }

  // which Meta model did this step, by name; two ids that read the same show once
  const models = $derived(
    [...new Map(stepModels(item).map((id) => [modelName(id), isOpenWeights(id)] as const))].map(([name, open]) => ({ name, open })),
  );

  const line = $derived.by(() => {
    switch (item.kind) {
      case 'tool': {
        const failed = item.result?.ok === false;
        return {
          icon: failed ? 'alert' : (TOOL_ICON[item.name] ?? KIND_ICON[item.tkind] ?? 'check'),
          title: callTitle(item.name, item.args, item.title),
          note: item.result ? resultTitle(item.name, item.args, item.result.summary, item.result.ok, item.result.title) : undefined,
          bad: failed,
          pending: !item.result,
          more: !!(item.args || item.result?.summary || item.result?.image),
        };
      }
      case 'critic': {
        // the finish gate asked for a closer match than the reviewer's own verdict did
        const verdict = item.forced_by && item.score != null ? t('critic_forced', { score: item.score }) : t(item.verdict) + (item.score != null ? ` · ${t('score_of', { s: item.score })}` : '');
        return {
          icon: 'eye',
          title: t('critic'),
          note: verdict + (item.version ? ` · v${item.version}` : ''),
          bad: !!item.forced_by || item.verdict !== 'pass',
          pending: false,
          more: item.issues.length > 0,
        };
      }
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
      {#if line.note || models.length}
        <span class="sub">
          {#if line.note}<span class="note">{line.note}</span>{/if}
          {#each models as m (m.name)}<span class="model" class:weights={m.open}>{m.name}{#if m.open}<span class="ow">&nbsp;· {t('open_weights')}</span>{/if}</span>{/each}
        </span>
      {/if}
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
        <ul>{#each item.issues as is, i (i)}<li class:major={is.severity === 'major'}>{is.text_user || is.text}</li>{/each}</ul>
      {:else if item.kind === 'facts'}
        <ul>
          {#each item.items as f, i (i)}
            <li>
              {f.subject} · {f.attribute}: <strong class="mono">{typeof f.value === 'number' ? f.value : String(f.value).replace(/^"|"$/g, '')} {f.unit ?? ''}</strong>
              {#if site(f.source_url)}<a href={f.source_url} target="_blank" rel="noopener noreferrer">{site(f.source_url)} ↗</a>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
</div>

<style>
  .step + :global(.step) {
    border-top: var(--border-width) solid var(--divider);
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
    color: var(--on-surface-var);
    font-size: var(--text-card-from);
    cursor: pointer;
  }
  .head:disabled {
    cursor: default;
    opacity: 1;
  }
  .head:not(:disabled):hover {
    background: var(--surface-container);
  }
  .ico {
    height: 20px;
    display: grid;
    place-items: center;
    color: var(--outline);
  }
  .bad .ico {
    color: var(--error);
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--primary);
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
  .title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .open .title,
  .open .note {
    white-space: normal;
    overflow-wrap: anywhere;
  }
  /* the result carries the numbers ("PCB v3 — 0 DRC errors, 23 traces…"): two lines before it is cut */
  .note {
    font-size: var(--text-card-meta);
    color: var(--outline);
    line-height: 17px;
    overflow: hidden;
    overflow-wrap: anywhere;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
  }
  .open .note {
    display: block;
  }
  /* the result first; model chips follow, on a line of their own when the column is narrow */
  .sub {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 2px 6px;
    min-width: 0;
  }
  .sub .note {
    flex: 1 1 8em;
    min-width: 0;
  }
  .model {
    flex: none;
    font-size: 11px;
    line-height: 16px;
    padding: 0 6px;
    border-radius: var(--radius-tag);
    background: var(--surface-high);
    color: var(--on-surface-var);
    font-weight: var(--font-weight-semibold);
    white-space: nowrap;
  }
  .model.weights {
    background: color-mix(in srgb, var(--primary) 14%, transparent);
    color: var(--primary);
  }
  .ow {
    font-weight: normal;
  }
  .bad .note {
    color: var(--error);
  }
  .chev {
    height: 20px;
    display: grid;
    place-items: center;
    color: var(--outline);
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
    font-size: var(--text-card-from);
  }
  .thumb {
    padding: 0;
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-btn);
    overflow: hidden;
    background: var(--surface);
    width: min(100%, 300px);
    cursor: zoom-in;
  }
  .thumb img {
    display: block;
    width: 100%;
  }
  pre {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 11px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 220px;
    overflow: auto;
    background: var(--surface-container);
    border-radius: var(--radius-tag);
    padding: 6px 8px;
    color: var(--on-surface-var);
  }
  ul {
    margin: 0;
    padding-left: 18px;
    color: var(--on-surface-var);
  }
  li.major {
    font-weight: var(--font-weight-semibold);
  }
</style>
