<script lang="ts">
  // A recorded agent run on the home page and in the replay gallery: opening it plays the real work back (photo, SAM
  // mask, millimetres, program, review) and costs nothing.
  import Icon from './Icon.svelte';
  import { fmtDuration, i18n, projectTitle, t } from '$lib/i18n.svelte';
  import { isOpenWeights, modelName } from '$lib/models';
  import type { FeaturedRun as Run } from '$lib/types';

  let { run: r }: { run: Run } = $props();

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
  const title = $derived((sameLang(r.title) ? '' : i18n.lang === 'ru' ? r.title_ru : r.title_en) || projectTitle(r.title));
</script>

<article class="card run">
  <a class="pic" href="/w/{r.id}" aria-label="{t('watch_replay')}: {title}">
    {#if r.cover}<img src={r.cover} alt="" loading="lazy" />{:else}<span class="ph"><Icon name="cube" size={28} /></span>{/if}
    <span class="play" aria-hidden="true"><Icon name="play" size={18} /></span>
  </a>
  <div class="meta">
    <strong>{title}</strong>
    {#if r.summary && sameLang(r.summary)}<span class="muted xs sum">{r.summary}</span>{/if}
    <span class="muted xs facts">
      {#if r.duration_s}<span><Icon name="history" size={12} /> {fmtDuration(r.duration_s)}</span>{/if}
      {#if r.versions}<span><Icon name="layers" size={12} /> v{r.versions}</span>{/if}
      {#if r.views}<span title={t('replays_views', { n: r.views })}><Icon name="eye" size={12} /> {r.views}</span>{/if}
    </span>
    {#if Object.keys(r.models ?? {}).length}
      <ul class="models" aria-label={t('powered_by')}>
        {#each chips(r.models) as c (c.name)}
          <li class="chip xs" class:accent={c.open}>{c.name}{#if c.calls}<span class="mono n">×{c.calls}</span>{/if}</li>
        {/each}
      </ul>
    {/if}
    <a class="btn small watch" href="/w/{r.id}"><Icon name="play" size={14} /> {t('watch_replay')}</a>
  </div>
</article>

<style>
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
    background: var(--render-bg);
    overflow: hidden;
  }
  .pic img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform var(--dur-slow) var(--ease-settle);
  }
  .pic:hover img {
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
    font-size: var(--text-xl);
    box-shadow: 0 2px 12px rgb(0 0 0 / 0.3);
    transition: transform var(--dur-base) var(--ease-settle);
  }
  .pic:hover .play {
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
    font-size: var(--text-base);
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
  @media (max-width: 720px) {
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
