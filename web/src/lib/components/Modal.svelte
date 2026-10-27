<script lang="ts">
  import type { Snippet } from 'svelte';
  let { title, onClose, children, wide = false }: { title: string; onClose: () => void; children: Snippet; wide?: boolean } = $props();
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onClose()} />

<div class="back" role="presentation" onclick={(e) => e.target === e.currentTarget && onClose()}>
  <div class="dlg card" class:wide role="dialog" aria-modal="true" aria-label={title}>
    <div class="top">
      <strong>{title}</strong>
      <button class="btn ghost small" onclick={onClose} aria-label="close">✕</button>
    </div>
    <div class="body">{@render children()}</div>
  </div>
</div>

<style>
  .back {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.45);
    z-index: 40;
    display: grid;
    place-items: center;
    padding: 12px;
  }
  .dlg {
    width: min(440px, 100%);
    max-height: calc(100dvh - 24px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .dlg.wide {
    width: min(980px, 100%);
  }
  .top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 12px;
    border-bottom: 1px solid var(--line);
  }
  .body {
    padding: 12px;
    overflow: auto;
  }
</style>
