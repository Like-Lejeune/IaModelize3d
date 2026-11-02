<script lang="ts">
  import { onMount, type Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  import { t } from '$lib/i18n.svelte';
  let { title, onClose, children, wide = false }: { title: string; onClose: () => void; children: Snippet; wide?: boolean } = $props();
  let box: HTMLDivElement;

  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  const focusables = () => Array.from(box?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []).filter((el) => el.getClientRects().length > 0);

  // focus goes into the dialog (the dialog itself: no keyboard pops up on a phone) and back to what opened it
  onMount(() => {
    const before = document.activeElement as HTMLElement | null;
    box?.focus();
    return () => before?.isConnected && before.focus();
  });

  // Tab and Shift+Tab cycle inside the dialog
  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') return onClose();
    if (e.key !== 'Tab' || !box) return;
    const list = focusables();
    if (!list.length) return e.preventDefault();
    const first = list[0];
    const last = list[list.length - 1];
    const at = document.activeElement;
    const outside = !box.contains(at) || at === box;
    if (e.shiftKey && (at === first || outside)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (at === last || (outside && at !== box))) {
      e.preventDefault();
      first.focus();
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="scrim" role="presentation" onclick={(e) => e.target === e.currentTarget && onClose()}>
  <div class="modal" class:wide role="dialog" aria-modal="true" aria-label={title} tabindex="-1" bind:this={box}>
    <div class="top">
      <h2 class="title">{title}</h2>
      <button class="btn icon ghost small" onclick={onClose} aria-label={t('close')}><Icon name="x" size={18} /></button>
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
  .modal:focus {
    outline: none;
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
