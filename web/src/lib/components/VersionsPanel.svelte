<script lang="ts">
  import { api } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';

  let { store }: { store: ProjectStore } = $props();
  let list = $state<{ version: number; summary: string | null; author: string; created_at: number }[]>([]);
  let picked = $state<number[]>([]);

  $effect(() => {
    void store.version;
    api.versions(store.id).then((v) => (list = v.reverse())).catch(() => {});
  });

  function toggle(v: number) {
    picked = picked.includes(v) ? picked.filter((x) => x !== v) : [...picked, v];
  }

  async function breed() {
    await store.startSide(() => api.breed(store.id, picked, 6));
    picked = [];
  }

  const when = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
</script>

<div class="stack">
  <p class="muted small">{t('breed_hint')}</p>
  <button class="btn" onclick={breed} disabled={picked.length < 1 || store.running}>🧬 {t('breed')} ({picked.length})</button>
  {#if store.variants.length}
    <div class="vgrid">
      {#each store.variants as v (v.version)}
        <figure>
          {#if v.render}<img src={v.render} alt="v{v.version}" loading="lazy" />{/if}
          <figcaption class="small">v{v.version} {v.summary ?? ''}</figcaption>
        </figure>
      {/each}
    </div>
  {/if}
  <ul class="vers">
    {#each list as v (v.version)}
      <li class:cur={v.version === store.version}>
        <label class="row">
          <input type="checkbox" checked={picked.includes(v.version)} onchange={() => toggle(v.version)} aria-label="pick v{v.version}" />
          <span class="chip">v{v.version}</span>
          <span class="sum">{v.summary ?? ''}</span>
        </label>
        <span class="muted small">{v.author} · {when(v.created_at)}{v.version === store.version ? ` · ${t('current')}` : ''}</span>
      </li>
    {/each}
  </ul>
</div>

<style>
  .vers {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .vers li {
    border: 1px solid var(--line);
    border-radius: 9px;
    padding: 6px 8px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .vers li.cur {
    border-color: var(--accent);
  }
  .row {
    flex-wrap: nowrap;
    min-width: 0;
  }
  .sum {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
  }
  .small {
    font-size: 12px;
  }
  .vgrid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
    gap: 6px;
  }
  .vgrid figure {
    margin: 0;
  }
  .vgrid img {
    width: 100%;
    border-radius: 6px;
    border: 1px solid var(--line);
  }
</style>
