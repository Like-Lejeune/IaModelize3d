<script lang="ts">
  // What the netlist already tells before any routing (device.lint) and what could not be read (unknown pins, parts).
  import Icon from '$lib/components/Icon.svelte';
  import type { DeviceStore } from './store.svelte';
  import { dt } from './i18n';

  let { device, onSend }: { device: DeviceStore; onSend?: (msg: string) => void } = $props();
  const checks = $derived([...(device.state?.issues ?? []), ...(device.state?.lint ?? [])]);
</script>

<div class="checks">
  {#if !checks.length}
    <p class="ok small"><Icon name="check-circle" size={16} /> {dt('checks_ok')}</p>
    <p class="xs muted">{dt('checks_scope')}</p>
  {:else}
    <ul>
      {#each checks as c, i (i)}
        <li>
          <button class="ref mono" onclick={() => (device.selected = String(c.ref).split('.')[0] || null)}>{c.ref || '—'}</button>
          <span class="small">{dt(`lint_${c.code}`) === `lint_${c.code}` ? c.msg : dt(`lint_${c.code}`, { ref: c.ref })}</span>
        </li>
      {/each}
    </ul>
    {#if onSend}
      <button class="btn small" onclick={() => onSend?.(dt('fix_msg', { e: checks.map((c) => `${c.ref}: ${c.msg}`).join('; ') }))}><Icon name="wand" size={14} /> {dt('ask_agent_fix')}</button>
    {/if}
  {/if}
</div>

<style>
  .checks {
    display: grid;
    gap: var(--space-2);
  }
  .ok {
    display: flex;
    gap: 8px;
    align-items: center;
    margin: 0;
    color: var(--ok);
  }
  .checks p {
    margin: 0;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 8px;
  }
  li {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 8px;
    align-items: baseline;
  }
  .ref {
    font-size: 11px;
    border: 1px solid var(--outline-variant);
    background: var(--surface-container);
    color: var(--on-surface);
    border-radius: 6px;
    padding: 1px 6px;
    cursor: pointer;
  }
</style>
