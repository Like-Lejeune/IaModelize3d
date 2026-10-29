<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  let { title, onClose, children, wide = false }: { title: string; onClose: () => void; children: Snippet; wide?: boolean } = $props();
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onClose()} />

<div class="scrim" role="presentation" onclick={(e) => e.target === e.currentTarget && onClose()}>
  <div class="modal" class:wide role="dialog" aria-modal="true" aria-label={title}>
    <div class="top">
      <h2 class="title">{title}</h2>
      <button class="btn icon ghost small" onclick={onClose} aria-label="close"><Icon name="x" size={18} /></button>
    </div>
    <div class="body">{@render children()}</div>
  </div>
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 200;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-4);
    background: color-mix(in srgb, #000 55%, transparent);
  }
  .modal {
    width: min(440px, 100%);
    max-height: calc(100dvh - 2 * var(--space-4));
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--surface-container);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-modal);
  }
  .modal.wide {
    width: min(980px, 100%);
  }
  .top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-4) var(--space-4) 0 var(--space-5);
  }
  .title {
    font-size: var(--text-product-section-title);
    font-weight: var(--font-weight-semibold);
    margin: 0;
  }
  .body {
    padding: var(--space-3) var(--space-5) var(--space-5);
    overflow: auto;
    color: var(--on-surface-var);
    font-size: var(--text-product-spec);
  }
</style>
