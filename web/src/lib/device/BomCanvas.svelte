<script lang="ts">
  // The BOM workspace's main view: every part of one device, as a table to read, sort and check against stock.
  import type { DeviceStore } from './store.svelte';
  import { bomOf, type BomRow } from './bom';
  import { dt, usd } from './i18n';

  let { device }: { device: DeviceStore } = $props();
  const rows = $derived(bomOf(device.state));
  let sort = $state<'ref' | 'sum' | 'stock'>('ref');
  const sorted = $derived(
    sort === 'ref' ? rows : [...rows].sort((a, b) => (sort === 'sum' ? (b.sum ?? 0) - (a.sum ?? 0) : (a.stock ?? 1e12) - (b.stock ?? 1e12))),
  );
  const total = $derived(rows.reduce((s, r) => s + (r.sum ?? 0), 0));
  const count = $derived(rows.reduce((s, r) => s + r.qty, 0));
  const low = (r: BomRow) => r.stock != null && r.stock < 100;
</script>

<div class="bc">
  {#if !rows.length}
    <div class="empty"><i class="ti ti-list-details big" aria-hidden="true"></i><strong>{dt('bom_empty')}</strong></div>
  {:else}
    <div class="table">
      <table>
        <thead>
          <tr>
            <th class="sortable" class:on={sort === 'ref'} onclick={() => (sort = 'ref')}>{dt('bom_refs')}</th>
            <th>{dt('bom_part')}</th>
            <th>{dt('package')}</th>
            <th>LCSC</th>
            <th>{dt('bom_class')}</th>
            <th class="r sortable" class:on={sort === 'stock'} onclick={() => (sort = 'stock')}>{dt('bom_stock')}</th>
            <th class="r">{dt('bom_qty')}</th>
            <th class="r">{dt('bom_unit')}</th>
            <th class="r sortable" class:on={sort === 'sum'} onclick={() => (sort = 'sum')}>{dt('bom_sum')}</th>
          </tr>
        </thead>
        <tbody>
          {#each sorted as r (r.key)}
            <tr class:out={r.stock === 0}>
              <td class="mono refs"><button onclick={() => device.pickNode(r.refs[0])}>{r.refs.join(', ')}</button></td>
              <td class="partcell"><span class="pn">{r.part}</span>{#if r.role}<span class="muted role">{r.role}</span>{/if}</td>
              <td class="muted pkg" title={r.pkg}>{r.pkg}</td>
              <td class="mono">{#if r.lcsc && r.url}<a href={r.url} target="_blank" rel="noopener noreferrer">{r.lcsc}</a>{:else}{r.lcsc ?? '—'}{/if}</td>
              <td>{#if r.hand}<span class="tag hand">{dt('hand')}</span>{:else if r.basic === true}<span class="tag basic">basic</span>{:else if r.basic === false}<span class="tag ext">extended</span>{:else}—{/if}</td>
              <td class="r mono" class:warn={low(r)}>{r.stock == null ? '—' : r.stock.toLocaleString()}</td>
              <td class="r mono">{r.qty}</td>
              <td class="r mono">{usd(r.unit, 3)}</td>
              <td class="r mono">{usd(r.sum, 3)}</td>
            </tr>
          {/each}
        </tbody>
        <tfoot>
          <tr><td colspan="6">{dt('bom_total', { lines: rows.length, parts: count })}</td><td class="r mono">{count}</td><td></td><td class="r mono strong">{usd(total)}</td></tr>
        </tfoot>
      </table>
    </div>
  {/if}
</div>

<style>
  .bc {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    background: var(--surface);
  }
  .table {
    flex: 1;
    overflow: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  th,
  td {
    padding: 6px 10px;
    height: 34px;
    text-align: left;
    border-bottom: 1px solid var(--divider);
    white-space: nowrap;
  }
  td.partcell {
    white-space: normal;
    min-width: 160px;
  }
  td.pkg {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  th {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--bw-head, var(--surface-container));
    font-size: 12px;
    font-weight: var(--font-weight-medium);
    color: var(--on-surface-var);
  }
  th.sortable {
    cursor: pointer;
  }
  th.sortable.on {
    color: var(--on-surface);
  }
  th.sortable.on::after {
    content: ' ↓';
  }
  .r {
    text-align: right;
  }
  tbody tr:hover {
    background: color-mix(in srgb, var(--on-surface) 4%, transparent);
  }
  .refs button {
    border: none;
    background: none;
    color: var(--on-surface);
    font: inherit;
    cursor: pointer;
    padding: 0;
  }
  .refs button:hover {
    color: var(--primary);
  }
  .pn {
    font-weight: var(--font-weight-medium);
  }
  .role {
    display: block;
    font-size: 11.5px;
    line-height: 1.3;
  }
  a {
    color: var(--primary);
    text-decoration: none;
  }
  .tag {
    font-size: 11px;
    padding: 1px 6px;
    border-radius: 4px;
  }
  .basic {
    color: var(--ok);
    background: color-mix(in srgb, var(--ok) 14%, transparent);
  }
  .ext {
    color: var(--warn-text);
    background: color-mix(in srgb, var(--warn) 16%, transparent);
  }
  .hand {
    color: var(--on-surface-var);
    background: var(--surface-container-high, var(--surface-high));
  }
  .warn {
    color: var(--warn-text);
  }
  tr.out td {
    color: var(--error);
  }
  tfoot td {
    position: sticky;
    bottom: 0;
    background: var(--bw-head, var(--surface-container));
    color: var(--on-surface-var);
    border-bottom: none;
  }
  .strong {
    color: var(--on-surface);
    font-weight: var(--font-weight-semibold);
  }
  .empty {
    margin: auto;
    display: grid;
    gap: 6px;
    justify-items: center;
    color: var(--on-surface-var);
  }
  .big {
    font-size: 30px;
  }
</style>
