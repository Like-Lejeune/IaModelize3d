<script lang="ts">
  import { t } from '$lib/i18n.svelte';

  let { source }: { source?: string | null } = $props();
  const s = $derived(source === 'request' ? 'user' : (source ?? ''));
  const tone = $derived(
    ({ photo: 'ok', caliper: 'ok', standard: 'info', search: 'info', user: 'accent', memory: 'info', assumed: 'warn', design: '' } as Record<string, string>)[s] ?? '',
  );
</script>

{#if s}
  <span class="chip src {tone}" title={t(`srcd.${s}`)}>{t(`src.${s}`)}</span>
{/if}

<style>
  .src {
    font-size: var(--text-xs);
    padding: 0 7px;
  }
</style>
