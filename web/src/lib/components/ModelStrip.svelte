<script lang="ts">
  // "Meta models in this run": one chip per model with what it did, its calls and spend.
  // Takes one job's cost or a list of them (the recipe page passes all of a project's jobs).
  import { t } from '$lib/i18n.svelte';
  import { fmtUsd, modelUsage, type ModelRole } from '$lib/models';
  import type { JobCost } from '$lib/types';

  let { cost, label = true }: { cost: JobCost | (JobCost | null | undefined)[] | null | undefined; label?: boolean } = $props();

  const uses = $derived(modelUsage(cost));

  const roleLabel = (r: ModelRole) => t(`model_role.${r}`);
</script>

{#if uses.length}
  <div class="strip" role="group" aria-label={t('models_in_run')}>
    {#if label}<span class="lbl">{t('models_in_run')}</span>{/if}
    <div class="chips">
      {#each uses as u (u.name)}
        <span class="chip model" class:open={u.open} title={u.ids.join(', ')}>
          <span class="name">{u.name}</span>
          {#if u.open}<span class="ow">{t('open_weights')}</span>{/if}
          {#if u.roles.length}<span class="role">{u.roles.map(roleLabel).join(', ')}</span>{/if}
          {#if u.calls}<span class="mono">×{u.calls}</span>{/if}
          {#if u.usd > 0}<span class="mono">{fmtUsd(u.usd)}</span>{/if}
        </span>
      {/each}
    </div>
  </div>
{/if}

<style>
  .strip {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .lbl {
    font-size: var(--text-xs);
    font-weight: var(--font-weight-semibold);
    color: var(--outline);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .model {
    font-weight: normal;
    color: var(--outline);
    white-space: normal;
    flex-wrap: wrap;
    row-gap: 0;
  }
  .name {
    font-weight: var(--font-weight-semibold);
    color: var(--on-surface);
  }
  .ow {
    color: var(--primary);
    font-weight: var(--font-weight-semibold);
  }
  .model.open {
    border-color: color-mix(in srgb, var(--primary) 40%, transparent);
  }
</style>
