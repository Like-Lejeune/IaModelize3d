<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { theme } from '$lib/theme/theme.svelte';
  let { children } = $props();

  onMount(() => void theme.init());
</script>

{@render children()}
