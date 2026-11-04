<script lang="ts">
  // Recorded agent runs picked for the home page, and the way to all the published ones.
  import { onMount } from 'svelte';
  import RunCard from './RunCard.svelte';
  import { api } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { FeaturedRun as Run } from '$lib/types';

  let runs = $state<Run[] | null>(null);

  onMount(() => {
    api.featured().then((r) => (runs = r)).catch(() => (runs = []));
  });
</script>

{#if runs?.length}
  <section class="block" aria-labelledby="featured-title">
    <div class="bhead">
      <div>
        <h2 id="featured-title">{t('featured_title')}</h2>
        <p class="muted small">{t('featured_hint')}</p>
      </div>
      <a class="btn ghost small" href="/replays">{t('all_replays')}</a>
    </div>
    <div class="runs">
      {#each runs as r (r.id)}<RunCard run={r} />{/each}
    </div>
  </section>
{/if}

<style>
  .block {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .bhead {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--space-3);
  }
  .bhead p {
    margin: 2px 0 0;
  }
  h2 {
    font-size: var(--text-xl);
  }
  .runs {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-4);
  }
  @media (max-width: 720px) {
    .runs {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-3);
    }
  }
</style>
