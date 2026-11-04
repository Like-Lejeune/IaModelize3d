<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { errorText } from '$lib/api';
  import { theme } from '$lib/theme/theme.svelte';
  import { i18n, t } from '$lib/i18n.svelte';
  let { children } = $props();

  // a failure no page caught still gets said; the console keeps the details
  let stray = $state<string | null>(null);
  function onRejection(e: PromiseRejectionEvent) {
    const name = (e.reason as { name?: string } | null)?.name;
    if (name === 'AbortError') return; // a request given up on purpose
    console.error(e.reason);
    stray = errorText(e.reason);
  }

  onMount(() => void theme.init());
  // <html lang> follows the UI language on every page (screen readers, the browser's translate offer)
  $effect(() => {
    document.documentElement.lang = i18n.lang;
  });
</script>

<svelte:window onunhandledrejection={onRejection} />

{@render children()}

{#if stray}
  <div class="stray small" role="alert">
    <span>{stray}</span>
    <button class="btn small ghost" onclick={() => (stray = null)}>{t('close')}</button>
  </div>
{/if}

<style>
  .stray {
    position: fixed;
    left: 50%;
    bottom: var(--space-4);
    transform: translateX(-50%);
    z-index: 1000;
    max-width: min(560px, calc(100vw - 32px));
    display: flex;
    gap: var(--space-3);
    align-items: center;
    padding: 10px 14px;
    color: var(--error);
    background: color-mix(in srgb, var(--error) 12%, var(--surface-container));
    border: var(--border-width) solid color-mix(in srgb, var(--error) 40%, transparent);
    border-radius: var(--radius-card);
  }
</style>
