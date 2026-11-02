<script lang="ts">
  // What the agent is doing while there is no model to show yet: the stages, the object SAM cut out
  // of the photo, the step running now and the latest render, so the viewer is never a blank box.
  import { fade } from 'svelte/transition';
  import Icon from './Icon.svelte';
  import Sticker from './Sticker.svelte';
  import { t } from '$lib/i18n.svelte';
  import { STAGES, callTitle, statusLine } from '$lib/steps';
  import type { JobInfo, ProjectStore } from '$lib/project.svelte';

  let { store, job }: { store: ProjectStore; job: JobInfo | null } = $props();

  // "done" is the model itself, which replaces this card
  const steps = STAGES.filter((s) => s !== 'done');
  const design = $derived(!job || job.kind === 'design');
  const current = $derived(job?.stage ?? 'understand');

  // a phone's stage is short: smaller pictures keep the stepper and the current step in view
  const small = matchMedia('(max-width: 640px)').matches;
  // the photo the latest message carries (a shop order's part on A4, not the rating plate uploaded after it), else
  // one with its object cut out, else the newest
  const photo = $derived.by(() => {
    const photos = store.assets.filter((a) => a.kind === 'photo');
    const sent = store.timeline.findLast((i) => i.kind === 'user' && !!i.assets?.length);
    const ids = sent?.kind === 'user' ? (sent.assets ?? []) : [];
    return photos.find((a) => ids.includes(a.id)) ?? [...photos].reverse().find((a) => store.target(a.id)) ?? photos[photos.length - 1] ?? null;
  });
  const target = $derived(photo ? store.target(photo.id) : null);
  const label = $derived(photo ? store.targetLabel(photo.id) : null);

  const doing = $derived.by(() => {
    if (store.starting) return store.starting;
    const busy = job ? store.timeline.findLast((i) => i.kind === 'tool' && i.job === job.id && !i.result) : null;
    if (busy?.kind === 'tool') return callTitle(busy.name, busy.args, busy.title);
    return store.status ? statusLine(store.status) : t('agent_working');
  });

  function state(s: string): 'done' | 'now' | 'next' {
    if (s === current) return 'now';
    return job?.reached.includes(s) || steps.indexOf(s as (typeof steps)[number]) < steps.indexOf(current as (typeof steps)[number]) ? 'done' : 'next';
  }
</script>

<div class="sp" transition:fade={{ duration: 260 }} aria-live="polite">
  <div class="card-in">
    {#if design}
      <ol class="stepper">
        {#each steps as s (s)}
          {@const st = state(s)}
          <li class={st}>
            <span class="dot" aria-hidden="true">{#if st === 'done'}<Icon name="check" size={11} />{/if}</span>
            <span class="xs">{t(`stage.${s}`)}</span>
          </li>
        {/each}
      </ol>
    {:else if job}
      <strong class="kind">{t(`job_${job.kind}`)}</strong>
    {/if}

    <div class="body">
      {#if store.lastRender}
        {#key store.lastRender}<img class="render" src={store.lastRender} alt="" in:fade={{ duration: 400 }} />{/key}
      {:else if photo && target?.mask_url}
        <span class="cut"><Sticker photo={photo.url} mask={target.mask_url} bbox={target.data?.bbox_px ?? null} size={small ? 84 : 150} /></span>
      {:else if photo}
        <img class="render shot" src={photo.thumb_url ?? photo.url} alt="" />
      {/if}
      {#if photo && target && label}<span class="chip xs target"><Icon name="target" size={12} /> {label}</span>{/if}
    </div>

    <p class="now small"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> <span>{doing}</span></p>
    <p class="hint xs muted">{t('stage_overlay_hint')}</p>
  </div>
</div>

<style>
  .sp {
    position: absolute;
    inset: 0;
    z-index: 1;
    display: grid;
    place-items: center;
    padding: var(--space-6) var(--space-4) 56px;
    /* the empty bed stays visible around the card, and so do the view tools under it */
    background: radial-gradient(closest-side, color-mix(in srgb, var(--surface) 88%, transparent), transparent);
    pointer-events: none;
  }
  .card-in {
    width: min(100%, 420px);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-3);
    text-align: center;
  }
  .stepper {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    width: 100%;
  }
  .stepper li {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    position: relative;
    color: var(--outline);
  }
  /* the line between two steps */
  .stepper li + li::before {
    content: '';
    position: absolute;
    top: 8px;
    right: calc(50% + 12px);
    width: calc(100% - 24px);
    height: 2px;
    border-radius: 1px;
    background: var(--outline-variant);
  }
  .stepper li.done::before,
  .stepper li.now::before {
    background: var(--primary);
  }
  .dot {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    border: 2px solid var(--outline-variant);
    background: var(--surface);
  }
  .done .dot {
    border-color: var(--primary);
    background: var(--primary);
    color: var(--on-primary);
  }
  .now .dot {
    border-color: var(--primary);
    box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary) 22%, transparent);
    animation: sp-pulse 1.2s ease-in-out infinite alternate;
  }
  .now,
  .done {
    color: var(--on-surface);
  }
  .now .xs {
    font-weight: var(--font-weight-semibold);
  }
  .stepper .xs {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  @keyframes sp-pulse {
    to {
      box-shadow: 0 0 0 7px color-mix(in srgb, var(--primary) 8%, transparent);
    }
  }
  .kind {
    font-size: var(--text-product-spec);
  }
  .body {
    position: relative;
    display: grid;
    place-items: center;
    min-height: 0;
  }
  .render {
    display: block;
    max-width: min(100%, 260px);
    max-height: 26dvh;
    border-radius: var(--radius-card);
    border: var(--border-width) solid var(--outline-variant);
    background: #f6f6f3;
  }
  .shot {
    opacity: 0.8;
  }
  .cut :global(.sticker) {
    filter: drop-shadow(0 4px 14px rgb(0 0 0 / 0.35));
  }
  .target {
    margin-top: var(--space-2);
  }
  .now {
    margin: 0;
    display: inline-flex;
    gap: 6px;
    align-items: center;
    max-width: 100%;
    color: var(--primary);
    font-weight: var(--font-weight-semibold);
  }
  .now span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .hint {
    margin: 0;
    max-width: 340px;
    text-wrap: balance;
  }
  @media (max-width: 640px) {
    .sp {
      padding: var(--space-2) var(--space-3) 44px;
    }
    .card-in {
      gap: var(--space-2);
    }
    .render {
      max-height: 84px;
    }
    .hint {
      display: none;
    }
  }
</style>
