<script lang="ts">
  import AssetsPanel from './AssetsPanel.svelte';
  import CreatePanel from './CreatePanel.svelte';
  import VersionsPanel from './VersionsPanel.svelte';
  import { t } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import type { AssetOut } from '$lib/types';

  let {
    store,
    snapshot,
    onUseConcept,
    onPhotoAR,
    focus = null,
    onFocused,
  }: {
    store: ProjectStore;
    snapshot: () => string | null;
    onUseConcept: (url: string) => void;
    onPhotoAR: (a: AssetOut) => void;
    /** Open Ideas and sketch concepts for this prompt, or start drawing a change. */
    focus?: { prompt?: string; draw?: boolean } | null;
    onFocused?: () => void;
  } = $props();

  let sub = $state<'assets' | 'concepts' | 'versions'>('assets');

  $effect.pre(() => {
    if (focus) sub = 'concepts';
  });
</script>

<div class="more">
  <div class="seg" role="tablist">
    {#each ['assets', 'concepts', 'versions'] as s (s)}
      <button role="tab" aria-selected={sub === s} onclick={() => (sub = s as any)}>{t(s)}</button>
    {/each}
  </div>
  {#if sub === 'assets'}
    <AssetsPanel {store} {onPhotoAR} />
  {:else if sub === 'concepts'}
    <CreatePanel {store} {snapshot} {onUseConcept} {focus} {onFocused} />
  {:else}
    <VersionsPanel {store} />
  {/if}
</div>

<style>
  .more {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
</style>
