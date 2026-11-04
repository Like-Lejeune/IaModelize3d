<script lang="ts">
  // The seam between two blocks stacked in a column: drag it to share the height out, a double click goes back to the
  // default. `height` is the upper block's, null while nobody has moved the seam.
  let {
    height = $bindable<number | null>(null),
    min,
    max,
    label,
    onsave,
  }: { height?: number | null; min: number; max: number; label: string; onsave?: () => void } = $props();

  let el = $state<HTMLElement>();
  let from = $state<{ y: number; height: number } | null>(null);
  const clamp = (v: number) => Math.round(Math.max(min, Math.min(v, max)));
  /** What the upper block measures on screen: the seam's top within the column. */
  const current = () => {
    const parent = el?.parentElement?.getBoundingClientRect();
    return el && parent ? el.getBoundingClientRect().top - parent.top : min;
  };

  function down(e: PointerEvent) {
    if (e.button !== 0) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    from = { y: e.clientY, height: current() };
  }
  function move(e: PointerEvent) {
    if (from) height = clamp(from.height + e.clientY - from.y);
  }
  function up() {
    if (!from) return;
    from = null;
    onsave?.();
  }
  function key(e: KeyboardEvent) {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    e.preventDefault();
    height = clamp(current() + (e.key === 'ArrowDown' ? 24 : -24));
    onsave?.();
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  bind:this={el}
  class="rsash"
  class:held={!!from}
  role="separator"
  aria-orientation="horizontal"
  aria-label={label}
  aria-valuemin={min}
  aria-valuemax={max}
  aria-valuenow={height ?? undefined}
  title={from ? undefined : label}
  tabindex="0"
  onpointerdown={down}
  onpointermove={move}
  onpointerup={up}
  onpointercancel={up}
  onkeydown={key}
  ondblclick={() => ((height = null), onsave?.())}
></div>

<style>
  .rsash {
    position: relative;
    z-index: 10;
    cursor: row-resize;
    touch-action: none;
    user-select: none;
    outline: none;
  }
  /* easier to catch than the seam is high */
  .rsash::before {
    content: '';
    position: absolute;
    inset: -3px 0;
  }
  /* the line that shows the seam is live */
  .rsash::after {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    top: 50%;
    height: 2px;
    margin-top: -1px;
    border-radius: 1px;
    background: var(--primary);
    opacity: 0;
    transition: opacity 0.12s 0.1s;
    pointer-events: none;
  }
  .rsash:hover::after,
  .rsash:focus-visible::after,
  .rsash.held::after {
    opacity: 1;
  }
</style>
