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
  let zoom = $state<string | null>(null);
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

  const assetUrl = (id: string) => {
    const a = store.assets.find((x) => x.id === id);
    return a ? { url: a.thumb_url ?? a.url, kind: a.kind } : null;
  };

  $effect(() => {
    void store.timeline.length;
    void store.status;
    queueMicrotask(() => {
      if (scroller && stuck) scroller.scrollTop = scroller.scrollHeight;
    });
  });

  function onScroll() {
    stuck = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
  }
</script>

<div class="log" bind:this={scroller} onscroll={onScroll}>
  {#if !entries.length}
    <div class="empty">
      <span class="badge"><Icon name="message" size={22} /></span>
      <h3>{t('empty_chat_t')}</h3>
      <p class="muted small">{t('empty_chat_d')}</p>
    </div>
  {/if}
  {#each entries as e (e.key)}
    {#if e.type === 'job'}
      <JobCard {store} job={e.job} items={e.items} onZoom={(u) => (zoom = u)} {onAction} {onUseConcept} />
    {:else if e.item.kind === 'user'}
      <div class="user">
        {#if e.item.assets?.length}
          <div class="atts">
            {#each e.item.assets as id (id)}
              {@const a = assetUrl(id)}
              {#if a && ['photo', 'sketch', 'caliper', 'concept', 'print'].includes(a.kind)}
                <button class="att" onclick={() => (zoom = a.url)}><img src={a.url} alt={a.kind} loading="lazy" /></button>
              {:else if a}
                <span class="chip">{t(a.kind === 'audio' ? 'voice' : a.kind)}</span>
              {/if}
            {/each}
          </div>
        {/if}
        {#if e.item.text}<div class="bubble">{e.item.text}</div>{/if}
      </div>
    {:else if e.item.kind === 'agent'}
      <div class="agent md">{@html markdown(e.item.text)}</div>
    {:else if e.item.kind === 'error'}
      <div class="error small" role="alert"><Icon name="alert" size={15} /> {e.item.text}</div>
    {/if}
  {/each}
</div>

{#if zoom}
  <button class="zoom" onclick={() => (zoom = null)} aria-label={t('close')}><img src={zoom} alt="" /></button>
{/if}

<style>
  .log {
    flex: 1;
    overflow-y: auto;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-height: 0;
    scroll-behavior: smooth;
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
    background: var(--accent-soft);
    color: var(--text);
    padding: 8px 12px;
    border-radius: 14px 14px 4px 14px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
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
  .att img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .agent {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 10px 12px;
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
