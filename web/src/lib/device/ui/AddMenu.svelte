<script lang="ts">
  // The schematic's Add menu (Shift+A, as in Blender): the library of modules and basics and the LCSC search, in a
  // popover under the editor's header. Picking a part adds it and closes the menu.
  import type { DevNode } from '../api';
  import PartLibrary, { loadLibrary } from '../PartLibrary.svelte';
  import { dt } from '../i18n';

  let { open = $bindable(false), onAdd }: { open?: boolean; onAdd: (n: Omit<DevNode, 'id'>) => void } = $props();
  let wrap = $state<HTMLElement>();
  // ready before the first open
  loadLibrary().catch(() => {});
</script>

<svelte:window
  onkeydown={(e) => open && e.key === 'Escape' && (open = false)}
  onpointerdown={(e) => open && wrap && !e.composedPath().includes(wrap) && (open = false)}
/>

<div class="am" bind:this={wrap}>
  <button class="hb" class:on={open} onclick={() => (open = !open)} aria-expanded={open} title="{dt('add_part')} (Shift+A)">
    <i class="ti ti-plus" aria-hidden="true"></i> {dt('menu_add')} <i class="ti ti-chevron-down caret" aria-hidden="true"></i>
  </button>
  {#if open}
    <div class="pop" role="dialog" aria-label={dt('add_part')}>
      <PartLibrary onAdd={(n) => (onAdd(n), (open = false))} />
    </div>
  {/if}
</div>

<style>
  .am {
    position: relative;
  }
  .pop {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    z-index: 40;
    display: flex;
    flex-direction: column;
    width: 360px;
    max-height: min(70vh, 540px);
    border-radius: var(--radius-sm);
    border: 1px solid var(--outline-variant);
    background: var(--bw-panel);
    box-shadow: var(--shadow-pop);
  }
  .hb .caret {
    font-size: var(--text-xs);
    opacity: 0.7;
  }
</style>
