<script lang="ts">
  import Icon from './Icon.svelte';
  import JobCard from './JobCard.svelte';
  import PhotoCard from './PhotoCard.svelte';
  import PhotoFocus from './PhotoFocus.svelte';
  import { markdown } from '$lib/md';
  import { t } from '$lib/i18n.svelte';
  import type { JobInfo, ProjectStore, TimelineItem } from '$lib/project.svelte';
  import type { AssetOut } from '$lib/types';

  let {
    store,
    onAction,
    onUseConcept,
  }: { store: ProjectStore; onAction: (a: string) => void; onUseConcept?: (url: string) => void } = $props();

  let scroller: HTMLDivElement;
  let feed: HTMLDivElement;
  let zoom = $state<string | null>(null);
  let focusing = $state<AssetOut | null>(null);
  let copied = $state<string | null>(null);
  // follow new output only while the user is at the bottom
  let stuck = true;

  type Entry =
    | { type: 'item'; key: string; ts: number; item: TimelineItem }
    | { type: 'job'; key: string; ts: number; job: JobInfo; items: TimelineItem[] }
    // versions saved outside a job (sliders, an example, a remix) in a row: one quiet line
    | { type: 'versions'; key: string; ts: number; from: number; to: number; authors: string[] };
  // what the chat shows outside a job; other job-less events (a stray status) stay out of it
  const SHOWN = new Set(['user', 'agent', 'error']);

  const entries = $derived.by(() => {
    const out: Entry[] = [];
    const byJob = new Map<string, Extract<Entry, { type: 'job' }>>();
    const jobEntry = (id: string, ts: number) => {
      let e = byJob.get(id);
      if (!e) {
        const job = store.jobs[id] ?? { id, kind: 'design', status: 'running', stage: null, reached: [], started: ts };
        // the server announces a job just before echoing the user's message: keep the message first
        e = { type: 'job', key: `job-${id}`, ts: Math.min(ts, job.started) + 3, job, items: [] };
        byJob.set(id, e);
        out.push(e);
      }
      return e;
    };
    for (const it of store.timeline) {
      if (it.job && it.kind !== 'user') jobEntry(it.job, it.ts).items.push(it);
      else if (it.kind === 'program') out.push({ type: 'versions', key: it.key, ts: it.ts, from: it.version, to: it.version, authors: it.author ? [it.author] : [] });
      else if (SHOWN.has(it.kind)) out.push({ type: 'item', key: it.key, ts: it.ts, item: it });
    }
    for (const j of Object.values(store.jobs)) if (!byJob.has(j.id)) jobEntry(j.id, j.started);
    out.sort((a, b) => a.ts - b.ts);
    const merged: Entry[] = [];
    for (const e of out) {
      const prev = merged[merged.length - 1];
      if (e.type === 'versions' && prev?.type === 'versions') {
        prev.from = Math.min(prev.from, e.from);
        prev.to = Math.max(prev.to, e.to);
        for (const a of e.authors) if (!prev.authors.includes(a)) prev.authors.push(a);
      } else merged.push(e);
    }
    return merged;
  });
  // a project with only saved versions (an opened example, slider edits) still gets the invitation
  const talked = $derived(entries.some((e) => e.type !== 'versions'));

  const lastJob = $derived([...entries].reverse().find((e) => e.type === 'job')?.key);
  const userCount = $derived(store.timeline.filter((i) => i.kind === 'user').length);

  const author = (a: string) => (t(`author.${a}`) === `author.${a}` ? a : t(`author.${a}`));
  const versionsLine = (e: Extract<Entry, { type: 'versions' }>) =>
    [t('model_updated'), e.from === e.to ? `v${e.from}` : `v${e.from}–v${e.to}`, e.authors.map(author).join(', ')].filter(Boolean).join(' · ');
  const asset = (id: string) => store.assets.find((x) => x.id === id);
  const isImage = (kind: string) => ['photo', 'sketch', 'caliper', 'concept', 'print'].includes(kind);

  // a queued pin or a late scroll event can arrive after the log is gone (switching tabs on a phone)
  function atBottom() {
    return !scroller || scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <= 24;
  }
  function toBottom() {
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }
  // Only a scroll up lets go of the bottom: our own jump down can land short when the feed grows
  // (images loading) before its scroll event arrives, and must not count as the user leaving.
  let lastTop = 0;
  function onScroll() {
    if (!scroller) return;
    const top = scroller.scrollTop;
    if (top < lastTop - 1) stuck = atBottom();
    else if (atBottom()) stuck = true;
    lastTop = top;
  }

  // Any growth of the feed (new steps, expanded groups, late images) keeps a stuck view pinned.
  $effect(() => {
    const ro = new ResizeObserver(() => stuck && toBottom());
    ro.observe(feed);
    ro.observe(scroller);
    return () => ro.disconnect();
  });

  // Sending a message always brings the view back down.
  $effect(() => {
    void userCount;
    stuck = true;
    queueMicrotask(toBottom);
  });

  async function copy(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      copied = key;
      setTimeout(() => copied === key && (copied = null), 1500);
    } catch {
      /* clipboard blocked */
    }
  }
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && zoom && (zoom = null)} />

<div class="log" bind:this={scroller} onscroll={onScroll}>
  <!-- opening a step group or a step is reading, not new output: let it grow downward instead of pinning the bottom -->
  <div class="feed" bind:this={feed} onclickcapture={(e) => (e.target as Element).closest('[aria-expanded]') && (stuck = false)}>
    {#each entries as e (e.key)}
      {#if e.type === 'job'}
        <JobCard {store} job={e.job} items={e.items} last={e.key === lastJob} onZoom={(u) => (zoom = u)} {onAction} {onUseConcept} />
      {:else if e.type === 'versions'}
        <div class="versions xs">
          <Icon name="layers" size={12} />
          <span>{versionsLine(e)}</span>
        </div>
      {:else if e.item.kind === 'user'}
        {@const u = e.item}
        {@const files = (u.assets ?? []).map(asset).filter((a) => !!a)}
        <div class="user">
          {#if files.length}
            {@const photos = files.filter((a) => a.kind === 'photo').length}
            <div class="atts">
              {#each files as a (a.id)}
                {#if a.kind === 'photo'}
                  <PhotoCard
                    src={a.url}
                    width={a.width}
                    height={a.height}
                    sel={store.target(a.id)}
                    scan={store.selections.findLast((x) => x.asset_id === a.id && x.data?.kind === 'board_scan') ?? null}
                    label={store.targetLabel(a.id)}
                    scanning={!!store.spotting[a.id]}
                    compact={photos > 1}
                    onOpen={store.readonly || store.replaying ? undefined : () => (focusing = a)}
                  />
                {:else if isImage(a.kind)}
                  <button class="att" onclick={() => (zoom = a.url)}><img src={a.thumb_url ?? a.url} alt={a.kind} loading="lazy" /></button>
                {:else}
                  <span class="chip">{t(a.kind === 'audio' ? 'voice' : a.kind)}</span>
                {/if}
              {/each}
            </div>
            {#if files.some((a) => a.meta?.faces_blurred)}<span class="xs muted"><Icon name="lock" size={11} /> {t('faces_blurred')}</span>{/if}
          {:else if u.previews?.length}
            <div class="atts">
              {#each u.previews as src (src)}<PhotoCard {src} scanning compact={u.previews.length > 1} />{/each}
            </div>
          {/if}
          {#if u.text}<div class="bubble">{u.text}</div>{/if}
          {#if u.text}
            <div class="actions">
              <button class="act" onclick={() => copy(u.key, u.text)} title={t('copy')} aria-label={t('copy')}><Icon name={copied === u.key ? 'check' : 'copy'} size={14} /></button>
              <!-- editing goes to the composer, which a visitor does not have -->
              {#if !store.replaying && !store.readonly}
                <button class="act" onclick={() => (store.draft = u.text)} title={t('edit')} aria-label={t('edit')}><Icon name="pencil" size={13} /></button>
              {/if}
            </div>
          {/if}
        </div>
        {#if store.starting && e === entries[entries.length - 1]}
          <div class="live shimmer" aria-live="polite">{store.starting}</div>
        {/if}
      {:else if e.item.kind === 'agent'}
        <div class="agent md">{@html markdown(e.item.text)}</div>
      {:else if e.item.kind === 'error'}
        {@const err = e.item}
        <!-- a send refused because another project holds the slot: the way there -->
        <div class="error small" role="alert">
          <Icon name="alert" size={15} />
          <span>{err.text}{#if err.code === 'job_running' && err.projectId && err.projectId !== store.id}&nbsp;<a href="/p/{err.projectId}">{t('open_blocking')}</a>{/if}</span>
        </div>
      {/if}
    {/each}
    {#if !talked}
      <div class="empty">
        <Icon name="message" size={40} />
        <h3>{t('empty_chat_t')}</h3>
        <p class="muted small">{t('empty_chat_d')}</p>
      </div>
    {/if}
  </div>
</div>

{#if focusing}
  <PhotoFocus {store} asset={focusing} sent onClose={() => (focusing = null)} />
{/if}

{#if zoom}
  <button class="zoom" onclick={() => (zoom = null)} aria-label={t('close')}><img src={zoom} alt="" /></button>
{/if}

<style>
  .log {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
    overflow-anchor: none;
  }
  .feed {
    padding: 16px 16px 12px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-height: 100%;
  }
  .empty {
    margin: auto;
    text-align: center;
    max-width: 300px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-6) 0;
    color: var(--outline);
  }
  .empty h3 {
    font-size: var(--text-product-section-title);
    font-weight: var(--font-weight-semibold);
    color: var(--on-surface);
  }
  .empty p {
    margin: 0;
    font-size: var(--text-product-spec);
    color: var(--on-surface-var);
  }
  .user {
    align-self: flex-end;
    max-width: 88%;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
  }
  .bubble {
    background: color-mix(in srgb, var(--primary) 9%, var(--surface));
    border: var(--border-width) solid color-mix(in srgb, var(--primary) 30%, var(--outline-variant));
    color: var(--on-surface);
    padding: 9px 12px;
    border-radius: var(--radius-field);
    line-height: 1.5;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .actions {
    display: flex;
    gap: 2px;
    margin-top: -4px;
    opacity: 0;
    transition: opacity 0.12s;
  }
  .user:hover .actions,
  .actions:focus-within {
    opacity: 1;
  }
  .act {
    width: 28px;
    height: 28px;
    border-radius: var(--radius-btn);
    border: none;
    background: none;
    display: grid;
    place-items: center;
    padding: 0;
    color: var(--outline);
    cursor: pointer;
  }
  .act:hover {
    background: var(--surface-high);
    color: var(--on-surface);
  }
  .atts {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .att {
    padding: 0;
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-btn);
    overflow: hidden;
    width: 72px;
    height: 72px;
    cursor: zoom-in;
  }
  .att img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .live {
    width: fit-content;
    font-size: var(--text-card-from);
  }
  .agent {
    font-size: var(--text-product-spec);
    line-height: 1.55;
  }
  .error {
    color: var(--error);
    background: color-mix(in srgb, var(--error) 12%, var(--surface-container));
    border: var(--border-width) solid color-mix(in srgb, var(--error) 40%, transparent);
    border-radius: var(--radius-card);
    padding: 10px 14px;
    display: flex;
    gap: 6px;
    align-items: flex-start;
  }
  .error a {
    color: inherit;
  }
  .versions {
    align-self: center;
    display: flex;
    align-items: center;
    gap: 5px;
    color: var(--outline);
    font-variant-numeric: tabular-nums;
  }
  .zoom {
    position: fixed;
    inset: 0;
    background: color-mix(in srgb, #000 82%, transparent);
    z-index: 60;
    display: grid;
    place-items: center;
    border: none;
    padding: 16px;
    cursor: zoom-out;
  }
  .zoom img {
    max-width: 100%;
    max-height: 100%;
    border-radius: var(--radius-btn);
  }
</style>
