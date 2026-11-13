<script lang="ts">
  // What SvelteKit shows when a page itself fails to load or render: never a blank screen.
  import { page } from '$app/state';
  import { t } from '$lib/i18n.svelte';
</script>

<svelte:head><title>{page.status} · IaModelize3d</title></svelte:head>

<main class="fail" role="alert">
  <p class="code mono">{page.status}</p>
  <p>{page.status === 404 ? t('err_not_found') : t('page_failed')}</p>
  <div class="row">
    <button class="btn primary" onclick={() => location.reload()}>{t('reload')}</button>
    <a class="btn" href="/">{t('back')}</a>
  </div>
</main>

<style>
  .fail {
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    align-items: center;
    justify-content: center;
    padding: var(--space-4);
    text-align: center;
  }
  .code {
    color: var(--outline);
    margin: 0;
  }
  p {
    margin: 0;
  }
  .row {
    display: flex;
    gap: var(--space-2);
  }
</style>
