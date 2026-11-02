<script lang="ts">
  // Recorded agent runs picked for the home page: a replay re-plays the event log, so watching one
  // shows the real work (photo, SAM mask, millimetres, program, review) and costs nothing.
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  import { api, errorText } from '$lib/api';
  import { fmtDuration, i18n, projectTitle, t } from '$lib/i18n.svelte';
  import { isOpenWeights, modelName } from '$lib/models';
  import type { FeaturedRun as Run } from '$lib/types';

  let runs = $state<Run[] | null>(null);
  let opening = $state<string | null>(null);
  let error = $state<string | null>(null);

  onMount(() => {
    api.featured().then((r) => (runs = r)).catch(() => (runs = []));
  });

  /** One chip per model as people know it; the count shows when the run recorded calls, not only dollars. */
  function chips(models: Record<string, number>) {
    const out = new Map<string, { name: string; calls: number; open: boolean }>();
    for (const [id, v] of Object.entries(models ?? {})) {
      const name = modelName(id);
      const c = out.get(name) ?? { name, calls: 0, open: false };
      if (Number.isInteger(v)) c.calls += v;
      c.open ||= isOpenWeights(id);
      out.set(name, c);
    }
    return [...out.values()].sort((a, b) => b.calls - a.calls);
  }

  // the agent's own summary is in its run's language: under the other UI language's headings it is left out
  const sameLang = (text: string) => /[а-яё]/i.test(text) === (i18n.lang === 'ru');
  // the run's own title in its language; in the other one the example's title when the run is an example's, else its own
  const title = (r: Run) => (sameLang(r.title) ? '' : i18n.lang === 'ru' ? r.title_ru : r.title_en) || projectTitle(r.title);

  async function watch(r: Run) {
    if (opening) return;
    opening = r.id;
    error = null;
    try {
      const copy = await api.replay(r.id, 8);
      goto(`/p/${copy.id}`);
    } catch (e) {
      error = errorText(e);
      opening = null;
    }
  }
</script>

{#if runs?.length}
  <section class="block" aria-labelledby="featured-title">
    <div class="bhead">
      <h2 id="featured-title">{t('featured_title')}</h2>
      <p class="muted small">{t('featured_hint')}</p>
    </div>
    <div class="runs">
      {#each runs as r (r.id)}
        <article class="card run">
          <button class="pic" onclick={() => watch(r)} disabled={!!opening && opening !== r.id} aria-label="{t('watch_replay')}: {title(r)}">
            {#if r.cover}<img src={r.cover} alt="" loading="lazy" />{:else}<span class="ph"><Icon name="cube" size={28} /></span>{/if}
            <span class="play" aria-hidden="true">{#if opening === r.id}<i class="ti ti-loader-2 spin"></i>{:else}<Icon name="play" size={18} />{/if}</span>
          </button>
          <div class="meta">
            <strong>{title(r)}</strong>
            {#if r.summary && sameLang(r.summary)}<span class="muted xs sum">{r.summary}</span>{/if}
            <span class="muted xs facts">
              {#if r.duration_s}<span><Icon name="history" size={12} /> {fmtDuration(r.duration_s)}</span>{/if}
              {#if r.versions}<span><Icon name="layers" size={12} /> v{r.versions}</span>{/if}
            </span>
            {#if Object.keys(r.models ?? {}).length}
              <ul class="models" aria-label={t('powered_by')}>
                {#each chips(r.models) as c (c.name)}
                  <li class="chip xs" class:accent={c.open}>{c.name}{#if c.calls}<span class="mono n">×{c.calls}</span>{/if}</li>
                {/each}
              </ul>
            {/if}
            <button class="btn small watch" onclick={() => watch(r)} disabled={!!opening} aria-busy={opening === r.id}>
              {#if opening === r.id}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="play" size={14} />{/if}
              {t('watch_replay')}
            </button>
          </div>
        </article>
      {/each}
    </div>
    {#if error}<p class="err small" role="alert">{error}</p>{/if}
  </section>
{/if}

<style>
  .block {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .bhead p {
    margin: 2px 0 0;
  }
  h2 {
    font-size: var(--text-product-section-title);
  }
  .runs {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-4);
  }
  .run {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  /* renders come on this light backdrop, as on the example tiles */
  .pic {
    position: relative;
    display: block;
    aspect-ratio: 4 / 3;
    padding: 0;
    border: none;
    background: #f6f6f3;
    overflow: hidden;
    cursor: pointer;
  }
  .pic:disabled {
    cursor: default;
    opacity: 0.55;
  }
  .pic img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform var(--dur-slow) var(--ease-settle);
  }
  .pic:hover:not(:disabled) img {
    transform: scale(1.05);
  }
  .ph {
    display: grid;
    place-items: center;
    width: 100%;
    height: 100%;
    color: var(--outline);
  }
  /* in the corner, so the model itself stays in view */
  .play {
    position: absolute;
    right: var(--space-3);
    bottom: var(--space-3);
    width: 44px;
    height: 44px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: color-mix(in srgb, var(--primary) 92%, transparent);
    color: var(--on-primary);
    font-size: 18px;
    box-shadow: 0 2px 12px rgb(0 0 0 / 0.3);
    transition: transform var(--dur-base) var(--ease-settle);
  }
  .pic:hover:not(:disabled) .play {
    transform: scale(1.08);
  }
  .meta {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: var(--space-3);
    min-width: 0;
  }
  /* two lines: a Russian title runs longer, and the phone card is narrow */
  .meta strong {
    font-size: var(--text-product-spec);
    font-weight: var(--font-weight-semibold);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .sum {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .facts {
    display: flex;
    gap: var(--space-3);
  }
  .facts span {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .models {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .models .n {
    opacity: 0.75;
  }
  .watch {
    margin-top: auto;
    align-self: flex-start;
  }
  .err {
    color: var(--error);
    margin: 0;
  }
  @media (max-width: 720px) {
    .runs {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-3);
    }
    .run {
      flex-direction: row;
    }
    .pic {
      flex: none;
      width: 38%;
      aspect-ratio: 1;
    }
    .play {
      right: var(--space-2);
      bottom: var(--space-2);
      width: 36px;
      height: 36px;
    }
  }
</style>
