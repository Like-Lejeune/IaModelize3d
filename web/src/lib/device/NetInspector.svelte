<script lang="ts">
  // The net picked in the Outliner or on a wire: its name and every pin on it.
  import Panel from './ui/Panel.svelte';
  import type { DeviceStore } from './store.svelte';
  import { POWER_NET } from './store.svelte';
  import { netColor } from './PartNode.svelte';
  import { dt } from './i18n';

  let { device, readonly = false }: { device: DeviceStore; readonly?: boolean } = $props();
  const nets = $derived(device.state?.doc.nets ?? []);
  const index = $derived(nets.findIndex((n, i) => (n.name ?? `n${i}`) === device.selectedNet));
  const net = $derived(index >= 0 ? nets[index] : null);
  const label = (ref: string) => device.state?.doc.nodes.find((n) => n.id === ref.split('.')[0])?.label;

  function rename(v: string) {
    const name = v.trim().replace(/[^A-Za-z0-9_]/g, '_');
    if (!net || index < 0) return;
    const clean = name ? (/^[A-Za-z_]/.test(name) ? name : `N${name}`) : '';
    if (clean && nets.some((n, i) => i !== index && n.name === clean)) return;
    device.edit((d) => {
      if (clean) d.nets[index].name = clean;
      else delete d.nets[index].name;
    }, `net ${clean || 'unnamed'}`);
    device.pickNet(clean || `n${index}`);
  }
  function drop() {
    if (index < 0) return;
    device.edit((d) => d.nets.splice(index, 1), 'net removed');
    device.pickNet(null);
  }
</script>

{#if net}
  <Panel name="net" title={dt('panel_net')}>
    {#snippet right()}<span class="sw" style="--c: {netColor(device.selectedNet)}"></span>{/snippet}
    <label class="pr"><span>{dt('net_name')}</span>
      <input class="mono" value={net.name ?? ''} placeholder={dt('net_unnamed')} disabled={readonly} onchange={(e) => rename(e.currentTarget.value)} />
    </label>
    <div class="pr"><span>{dt('net_kind')}</span><span class="v">{POWER_NET.test(net.name ?? '') ? dt('net_power') : dt('net_signal')}</span></div>
    <ul class="pins">
      {#each net.pins as ref (ref)}
        <li><button onclick={() => device.pickNode(ref.split('.')[0])}><span class="mono">{ref}</span>{#if label(ref)}<span class="muted">{label(ref)}</span>{/if}</button></li>
      {/each}
    </ul>
    {#if !readonly}<button class="act danger" onclick={drop}><i class="ti ti-unlink" aria-hidden="true"></i> {dt('net_drop')}</button>{/if}
  </Panel>
{/if}

<style>
  .pr {
    display: grid;
    grid-template-columns: 38% 1fr;
    align-items: center;
    gap: 10px;
    min-height: var(--bw-row, 26px);
    font-size: var(--text-md);
  }
  .pr > span:first-child {
    color: var(--on-surface-var);
    text-align: right;
  }
  .pr input {
    font: inherit;
    font-size: var(--text-md);
    height: var(--bw-row, 26px);
    padding: 0 8px;
    color: var(--on-surface);
    background: var(--bw-field);
    border: 1px solid var(--bw-field-border);
    border-radius: var(--radius-xs);
    min-width: 0;
  }
  .v {
    font-size: var(--text-md);
  }
  .sw {
    width: 10px;
    height: 10px;
    border-radius: var(--radius-xs);
    background: var(--c);
  }
  .pins {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 2px;
  }
  .pins button {
    width: 100%;
    display: flex;
    gap: 8px;
    align-items: center;
    height: 24px;
    padding: 0 8px;
    border: none;
    border-radius: var(--radius-xs);
    background: none;
    color: var(--on-surface);
    font: inherit;
    font-size: var(--text-md);
    text-align: left;
    cursor: pointer;
  }
  .pins button:hover {
    background: color-mix(in srgb, var(--on-surface) 7%, transparent);
  }
  .pins .muted {
    font-size: var(--text-sm);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .act {
    justify-self: start;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 26px;
    padding: 0 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--bw-field-border);
    background: var(--surface-high);
    color: var(--on-surface);
    font: inherit;
    font-size: var(--text-md);
    cursor: pointer;
  }
  .act.danger:hover {
    color: var(--error);
    border-color: var(--error);
  }
</style>
