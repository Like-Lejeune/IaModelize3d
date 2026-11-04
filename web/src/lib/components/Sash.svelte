<script lang="ts">
  // The seam between a side panel and the editor, a grid track of its own: drag it to resize the panel, pull it to the
  // screen's edge to hide the panel. A hidden panel's seam lies on that edge: dragged or clicked, the panel comes back.
  import { MIN_PANEL, type Side, type SideDock } from '$lib/dock.svelte';
  import { t } from '$lib/i18n.svelte';

  let { dock, side, label, pulse = false }: { dock: SideDock; side: Side; label?: string; pulse?: boolean } = $props();

  const hidden = $derived(dock[side].hidden);
  const hint = $derived(`${label ? `${label}: ` : ''}${t(hidden ? 'dock_restore' : 'dock_resize')}`);
  const inward = $derived(side === 'left' ? 1 : -1);

  let from = $state<{ x: number; width: number } | null>(null);
  let moved = false;

  function down(e: PointerEvent) {
    if (e.button !== 0) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    from = { x: e.clientX, width: dock.width(side) };
    moved = false;
  }
  function move(e: PointerEvent) {
    if (!from) return;
    const dx = e.clientX - from.x;
    if (Math.abs(dx) > 2) moved = true;
    if (moved) dock.drag(side, from.width + dx * inward, from.width);
  }
  function up() {
    if (!from) return;
    if (!moved && hidden) dock.show(side);
    else dock.save();
    from = null;
  }
  function key(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      if (hidden) dock.show(side);
      else dock.hide(side);
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      const grow = (e.key === 'ArrowRight' ? 24 : -24) * inward;
      if (!hidden) dock.drag(side, Math.max(MIN_PANEL, dock.width(side) + grow), 0);
      else if (grow > 0) dock.show(side);
      dock.save();
    }
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  class="sash {side}"
  class:edge={hidden}
  class:held={!!from}
  role="separator"
  aria-orientation="vertical"
  aria-label={hint}
  aria-valuemin={0}
  aria-valuemax={dock.max(side)}
  aria-valuenow={dock.width(side)}
  title={from ? undefined : hint}
  tabindex="0"
  onpointerdown={down}
  onpointermove={move}
  onpointerup={up}
  onpointercancel={up}
  onkeydown={key}
>
  {#if hidden && pulse}<span class="pulse"></span>{/if}
</div>

<style>
  .sash {
    position: relative;
    z-index: 10;
    grid-row: 1;
    cursor: col-resize;
    touch-action: none;
    user-select: none;
    outline: none;
  }
  .sash.left {
    grid-column: 2;
  }
  .sash.right {
    grid-column: 4;
  }
  /* easier to catch than the seam is wide */
  .sash::before {
    content: '';
    position: absolute;
    inset: 0 -3px;
  }
  .sash.edge.left::before {
    inset: 0 -8px 0 0;
  }
  .sash.edge.right::before {
    inset: 0 0 0 -8px;
  }
  /* the line that shows the seam is live */
  .sash::after {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    left: 50%;
    width: 2px;
    margin-left: -1px;
    border-radius: 1px;
    background: var(--primary);
    opacity: 0;
    transition: opacity 0.12s 0.1s;
    pointer-events: none;
  }
  .sash:hover::after,
  .sash:focus-visible::after,
  .sash.held::after {
    opacity: 1;
  }
  /* a hidden panel leaves a grip on the screen's edge */
  .sash.edge:not(:hover, :focus-visible, .held)::after {
    top: calc(50% - 24px);
    bottom: calc(50% - 24px);
    background: var(--outline);
    opacity: 1;
  }
  .pulse {
    position: absolute;
    top: calc(50% - 40px);
    left: 50%;
    width: 7px;
    height: 7px;
    margin-left: -3.5px;
    border-radius: 50%;
    background: var(--primary);
    animation: pulse 1.2s ease-in-out infinite;
    pointer-events: none;
  }
  @keyframes pulse {
    50% {
      opacity: 0.3;
    }
  }
</style>
