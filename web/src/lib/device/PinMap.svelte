<script lang="ts">
  // Which microcontroller pin does what, read off the device graph: the table the firmware is written against, with the
  // GPIO number behind each board label (the module's gpio map) and the strapping pins marked, which the firmware must
  // not hold at boot.
  import type { DeviceStore } from './store.svelte';
  import { POWER_NET } from './store.svelte';
  import type { Library } from './api';
  import { loadLibrary } from './PartLibrary.svelte';
  import { dt } from './i18n';
  import { netColor } from './PartNode.svelte';

  let { device }: { device: DeviceStore } = $props();
  let lib = $state<Library | null>(null);
  loadLibrary().then((l) => (lib = l)).catch(() => {});

  // the microcontroller: the module, else the chip with the most pins
  const mcu = $derived.by(() => {
    const s = device.state;
    if (!s) return null;
    const mod = s.doc.nodes.find((n) => n.kind === 'module');
    if (mod) return mod;
    return [...s.doc.nodes].filter((n) => n.kind === 'chip').sort((a, b) => (s.view.nodes[b.id]?.pins.length ?? 0) - (s.view.nodes[a.id]?.pins.length ?? 0))[0] ?? null;
  });
  const rows = $derived.by(() => {
    const s = device.state;
    const m = mcu;
    if (!s || !m) return [];
    const label = (id: string) => s.doc.nodes.find((n) => n.id === id)?.label;
    return s.doc.nets
      .map((net) => {
        const mine = net.pins.filter((p) => p.startsWith(`${m.id}.`));
        if (!mine.length) return null;
        const to = net.pins.filter((p) => !p.startsWith(`${m.id}.`));
        return { pins: mine.map((p) => p.split('.')[1]), net: net.name ?? null, power: POWER_NET.test(net.name ?? ''),
                 to: to.map((p) => ({ ref: p, role: label(p.split('.')[0]) })) };
      })
      .filter((r): r is NonNullable<typeof r> => !!r)
      .sort((a, b) => Number(a.power) - Number(b.power));
  });
  const mod = $derived(mcu?.kind === 'module' ? (lib?.modules.find((m) => m.module === mcu.module) ?? null) : null);
  const gpio = (pin: string) => mod?.gpio?.[pin];
  const strap = (pin: string) => {
    const g = gpio(pin);
    return g != null && !!mod?.strapping?.includes(g);
  };
</script>

{#if mcu}
  <div class="pm">
    <p class="xs muted">{dt('pinmap_of', { id: mcu.id, name: device.state?.view.nodes[mcu.id]?.part.mpn ?? mcu.id })}</p>
    <table>
      <thead><tr><th>{dt('pm_pin')}</th><th>{dt('pm_net')}</th><th>{dt('pm_to')}</th></tr></thead>
      <tbody>
        {#each rows as r, i (i)}
          <tr class:pw={r.power}>
            <td class="mono">{#each r.pins as p, j (p)}{j ? ', ' : ''}{p}{#if !r.power && gpio(p) != null}<span class="gp" class:strap={strap(p)} title={strap(p) ? dt('pm_strap') : undefined}>GPIO{gpio(p)}</span>{/if}{/each}</td>
            <td>{#if r.net}<span class="tag mono" style="--c: {netColor(r.net)}">{r.net}</span>{:else}<span class="muted">—</span>{/if}</td>
            <td class="xs">{#each r.to.slice(0, r.power ? 3 : 6) as t, j (j)}<span class="to"><span class="mono">{t.ref}</span>{#if t.role && !r.power}<span class="muted">{` · ${t.role}`}</span>{/if}</span>{/each}{#if r.power && r.to.length > 3}<span class="muted">{` +${r.to.length - 3}`}</span>{/if}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{:else}
  <p class="small muted">{dt('pinmap_none')}</p>
{/if}

<style>
  .pm {
    display: grid;
    gap: 6px;
  }
  .pm p {
    margin: 0;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th,
  td {
    text-align: left;
    padding: 5px 4px;
    border-bottom: 1px solid var(--divider);
    vertical-align: top;
    font-size: 12px;
  }
  th {
    font-size: 11px;
    font-weight: var(--font-weight-medium);
    color: var(--on-surface-var);
  }
  tr.pw td {
    opacity: 0.75;
  }
  .tag {
    font-size: 10.5px;
    padding: 0 5px;
    border-radius: 4px;
    color: var(--c);
    border: 1px solid color-mix(in srgb, var(--c) 55%, transparent);
    background: color-mix(in srgb, var(--c) 12%, transparent);
  }
  .to {
    display: block;
  }
  .gp {
    display: block;
    font-size: 10px;
    color: var(--on-surface-var);
  }
  .gp.strap {
    color: var(--warn-text);
  }
</style>
