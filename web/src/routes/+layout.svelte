<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { theme } from '$lib/theme/theme.svelte';
  import { i18n } from '$lib/i18n.svelte';
  let { children } = $props();

  onMount(() => void theme.init());
  // <html lang> follows the UI language on every page (screen readers, the browser's translate offer)
  $effect(() => {
    document.documentElement.lang = i18n.lang;
  });
</script>

{@render children()}
