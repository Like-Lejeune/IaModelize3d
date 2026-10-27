<script lang="ts">
  import Icon from './Icon.svelte';
  import JobCard from './JobCard.svelte';
  import { markdown } from '$lib/md';
  import { t } from '$lib/i18n.svelte';
  import type { JobInfo, ProjectStore, TimelineItem } from '$lib/project.svelte';

  let {
    store,
    onAction,
    onUseConcept,
  }: { store: ProjectStore; onAction: (a: string) => void; onUseConcept?: (url: string) => void } = $props();

  let scroller: HTMLDivElement;
  let feed: HTMLDivElement;
  let zoom = $state<string | null>(null);
  let copied = $state<string | null>(null);
  // follow new output only while the user is at the bottom
  let stuck = true;

  type Entry = { type: 'item'; key: string; ts: number; item: TimelineItem } | { type: 'job'; key: string; ts: number; job: JobInfo; items: TimelineItem[] };

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
      else out.push({ type: 'item', key: it.key, ts: it.ts, item: it });
    }
    for (const j of Object.values(store.jobs)) if (!byJob.has(j.id)) jobEntry(j.id, j.started);
    return out.sort((a, b) => a.ts - b.ts);
  });

  const lastJob = $derived([...entries].reverse().find((e) => e.type === 'job')?.key);
  const userCount = $derived(store.timeline.filter((i) => i.kind === 'user').length);

  const asset = (id: string) => store.assets.find((x) => x.id === id);
  const isImage = (kind: string) => ['photo', 'sketch', 'caliper', 'concept', 'print'].includes(kind);

  function atBottom() {
    return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <= 24;
  }
  function toBottom() {
    scroller.scrollTop = scroller.scrollHeight;
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

<div class="log" bind:this={scroller} onscroll={() => (stuck = atBottom())}>
  <!-- opening a step group or a step is reading, not new output: let it grow downward instead of pinning the bottom -->
  <div class="feed" bind:this={feed} onclickcapture={(e) => (e.target as Element).closest('[aria-expanded]') && (stuck = false)}>
    {#if !entries.length}
      <div class="empty">
        <span class="badge"><Icon name="message" size={22} /></span>
        <h3>{t('empty_chat_t')}</h3>
        <p class="muted small">{t('empty_chat_d')}</p>
      </div>
    {/if}
    {#each entries as e (e.key)}
      {#if e.type === 'job'}
        <JobCard {store} job={e.job} items={e.items} last={e.key === lastJob} onZoom={(u) => (zoom = u)} {onAction} {onUseConcept} />
      {:else if e.item.kind === 'user'}
        {@const u = e.item}
        {@const files = (u.assets ?? []).map(asset).filter((a) => !!a)}
        <div class="user">
          {#if files.length}
            <div class="atts">
              {#each files as a (a.id)}
                {#if isImage(a.kind)}
                  <button class="att" onclick={() => (zoom = a.url)}><img src={a.thumb_url ?? a.url} alt={a.kind} loading="lazy" /></button>
                {:else}
                  <span class="chip">{t(a.kind === 'audio' ? 'voice' : a.kind)}</span>
                {/if}
              {/each}
            </div>
            {#if files.some((a) => a.meta?.faces_blurred)}<span class="xs muted"><Icon name="lock" size={11} /> {t('faces_blurred')}</span>{/if}
          {:else if u.previews?.length}
            <div class="atts">
              {#each u.previews as src (src)}<span class="att loading"><img {src} alt="" /></span>{/each}
            </div>
          {/if}
          {#if u.text}<div class="bubble">{u.text}</div>{/if}
          {#if u.text}
            <div class="actions">
              <button class="act" onclick={() => copy(u.key, u.text)} title={t('copy')} aria-label={t('copy')}><Icon name={copied === u.key ? 'check' : 'copy'} size={14} /></button>
              {#if !store.replaying}
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
        <div class="error small" role="alert"><Icon name="alert" size={15} /> {e.item.text}</div>
      {/if}
    {/each}
  </div>
</div>

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
    gap: 8px;
    padding: 24px 0;
  }
  .empty h3 {
    font-size: var(--fs-md);
  }
  .empty p {
    margin: 0;
  }
  .badge {
    width: 44px;
    height: 44px;
    border-radius: 14px;
    display: grid;
    place-items: center;
    background: var(--accent-soft);
    color: var(--accent);
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
    background: var(--panel-3);
    color: var(--text);
    padding: 8px 12px;
    border-radius: 14px;
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
    border-radius: 7px;
    border: none;
    background: none;
    display: grid;
    place-items: center;
    padding: 0;
    color: var(--muted);
    cursor: pointer;
  }
  .act:hover {
    background: var(--panel-3);
    color: var(--text);
  }
  .atts {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .att {
    padding: 0;
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
    width: 72px;
    height: 72px;
    cursor: zoom-in;
  }
  .att.loading {
    cursor: default;
    opacity: 0.6;
  }
  .att img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .live {
    width: fit-content;
    font-size: var(--fs-sm);
  }
  .agent {
    font-size: var(--fs-md);
    line-height: 1.55;
  }
  .error {
    color: var(--err);
    background: var(--err-soft);
    border-radius: 10px;
    padding: 8px 10px;
    display: flex;
    gap: 6px;
    align-items: flex-start;
  }
  .zoom {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.78);
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
    border-radius: 10px;
  }
</style>
