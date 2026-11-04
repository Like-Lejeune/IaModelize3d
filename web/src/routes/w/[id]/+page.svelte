<script lang="ts">
  // A replay's address: it opens the workspace the run was made in, playing. ?at=<event seq> opens that moment, paused.
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import Header from '$lib/components/Header.svelte';
  import { api, errorText } from '$lib/api';
  import { isText, t } from '$lib/i18n.svelte';

  let error = $state<string | null>(null);

  $effect(() => {
    const id = page.params.id!;
    const at = Number(page.url.searchParams.get('at'));
    let gone = false;
    error = null;
    api
      .project(id)
      .then((d) => {
        if (!gone) goto(`/${d.pack === 'device' ? 'd' : 'p'}/${id}?replay=1${at > 0 ? `&at=${at}` : ''}`, { replaceState: true });
      })
      .catch((e) => {
        if (!gone) error = errorText(e);
      });
    return () => (gone = true);
  });
</script>

<Header />
{#if error}
  <div class="center"><p class="err">{isText(error, 'forbidden') ? t('private_project') : error}</p><a class="btn" href="/replays">{t('replays')}</a></div>
{:else}
  <div class="center"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></div>
{/if}

<style>
  .center {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-8) var(--space-4);
    text-align: center;
  }
  .err {
    color: var(--error);
    margin: 0;
  }
</style>
