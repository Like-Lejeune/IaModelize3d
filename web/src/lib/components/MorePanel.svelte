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
  }: { store: ProjectStore; snapshot: () => string | null; onUseConcept: (url: string) => void; onPhotoAR: (a: AssetOut) => void } = $props();

  let sub = $state<'assets' | 'concepts' | 'versions'>('assets');
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
    <CreatePanel {store} {snapshot} {onUseConcept} />
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
