<script lang="ts">
  // What the board build may choose and what is fixed: its size (found by the build, or given) and the corner holes.
  import type { DeviceStore } from './store.svelte';
  import { dt } from './i18n';

  let { device, readonly = false }: { device: DeviceStore; readonly?: boolean } = $props();
  const board = $derived(device.state?.doc.board ?? {});
  const fixed = $derived(!!(board.w && board.h));
  const edges = $derived((device.state?.doc.nodes ?? []).filter((n) => n.edge));

  function setSize(fix: boolean) {
    device.edit((d) => {
      if (fix) {
        d.board.w = d.board.w ?? 40;
        d.board.h = d.board.h ?? 40;
      } else {
        delete d.board.w;
        delete d.board.h;
      }
    }, fix ? 'board size fixed' : 'board size found by the build');
  }
  function num(k: 'w' | 'h', v: string) {
    const n = Math.max(15, Math.min(100, Number(v) || 40));
    device.edit((d) => (d.board[k] = n), `board ${k} ${n} mm`);
  }
</script>

<div class="bs">
  <div class="f">
    <span>{dt('board_size')}</span>
    <div class="seg2">
      <button aria-pressed={!fixed} disabled={readonly} onclick={() => setSize(false)}>{dt('board_auto')}</button>
      <button aria-pressed={fixed} disabled={readonly} onclick={() => setSize(true)}>{dt('board_fixed')}</button>
    </div>
    {#if fixed}
      <div class="wh">
        <input type="number" min="15" max="100" value={board.w} disabled={readonly} onchange={(e) => num('w', e.currentTarget.value)} aria-label="W" />
        <span>×</span>
        <input type="number" min="15" max="100" value={board.h} disabled={readonly} onchange={(e) => num('h', e.currentTarget.value)} aria-label="H" />
        <span class="muted small">{dt('mm')}</span>
      </div>
    {:else}
      <span class="xs muted">{dt('board_auto_d')}</span>
    {/if}
  </div>
  <label class="chk small">
    <input type="checkbox" checked={board.holes !== false} disabled={readonly} onchange={(e) => device.edit((d) => (d.board.holes = e.currentTarget.checked), 'mounting holes')} />
    {dt('board_holes')}
  </label>
  {#if edges.length}
    <div class="f">
      <span>{dt('board_edges')}</span>
      <ul class="edges">
        {#each edges as n (n.id)}
          <li><button class="mono ref" onclick={() => (device.selected = n.id)}>{n.id}</button><span class="small">{n.label ?? dt(`k_${n.kind}`)}</span><span class="xs muted">{dt(`edge_${n.edge}`)}</span></li>
        {/each}
      </ul>
    </div>
  {/if}
</div>

<style>
  .bs {
    display: grid;
    gap: 8px;
  }
  .f {
    display: grid;
    gap: 6px;
    font-size: var(--text-sm);
    color: var(--on-surface-var);
  }
  .seg2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 3px;
  }
  .seg2 button {
    font: inherit;
    font-size: var(--text-md);
    height: var(--bw-row, 26px);
    padding: 0;
    border-radius: var(--radius-xs);
    border: 1px solid var(--outline-variant);
    background: var(--surface-container-lowest);
    color: var(--on-surface);
    cursor: pointer;
  }
  .seg2 button[aria-pressed='true'] {
    background: var(--primary-container);
    color: var(--on-primary-container);
    border-color: var(--primary);
  }
  .wh {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .wh input {
    width: 70px;
    height: var(--bw-row, 26px);
    font: inherit;
    font-size: var(--text-md);
    color: var(--on-surface);
    background: var(--surface-container-lowest);
    border: 1px solid var(--outline-variant);
    border-radius: var(--radius-xs);
    padding: 0 8px;
  }
  .chk {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .edges {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 4px;
  }
  .edges li {
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 8px;
    align-items: center;
    color: var(--on-surface);
  }
  .ref {
    font-size: var(--text-xs);
    border: 1px solid var(--outline-variant);
    background: var(--surface-container);
    color: var(--on-surface);
    border-radius: var(--radius-sm);
    padding: 1px 6px;
    cursor: pointer;
  }
</style>
