<script lang="ts">
  // A colour chip that can be picked; the selected one gets a ring and a tick.
  let {
    color,
    selected = false,
    label,
    tooltip,
    size,
    onclick,
  }: {
    color: string;
    selected?: boolean;
    label?: string;
    tooltip?: string;
    size?: number;
    onclick?: (e: MouseEvent) => void;
  } = $props();

  let hovered = $state(false);
</script>

<button
  type="button"
  class="sw"
  class:selected
  style="background: {color};{size ? ` width: ${size}px; height: ${size}px;` : ''}"
  aria-label={label ?? color}
  aria-pressed={selected}
  {onclick}
  onmouseenter={() => (hovered = true)}
  onmouseleave={() => (hovered = false)}
>
  {#if selected}
    <svg class="check" viewBox="0 0 24 24" aria-hidden="true">
      <path class="halo" d="M5.5 12.5 10 17 18.5 7.5" />
      <path class="tick" d="M5.5 12.5 10 17 18.5 7.5" />
    </svg>
  {/if}
  {#if tooltip && hovered}<span class="tt">{tooltip}</span>{/if}
</button>

<style>
  .sw {
    position: relative;
    width: 22px;
    height: 22px;
    padding: 0;
    border: var(--border-width) solid var(--swatch-inner-ring);
    border-radius: var(--radius-swatch);
    cursor: pointer;
    font-family: inherit;
  }
  .sw.selected {
    outline: 2px solid var(--swatch-selected-ring);
    outline-offset: 2px;
  }
  .check {
    position: absolute;
    left: 18%;
    top: 18%;
    width: 64%;
    height: 64%;
    pointer-events: none;
  }
  .check path {
    fill: none;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .check .halo {
    stroke: var(--surface);
    stroke-width: 5.5;
  }
  .check .tick {
    stroke: var(--swatch-selected-ring);
    stroke-width: 2.6;
  }
  .sw:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
  }
  .tt {
    position: absolute;
    bottom: 142%;
    left: 50%;
    transform: translateX(-50%);
    background: var(--surface-high);
    color: var(--on-surface);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-field);
    padding: 5px 9px;
    font-size: var(--text-sm);
    font-weight: var(--font-weight-medium);
    white-space: nowrap;
    pointer-events: none;
    animation: tt-in var(--dur-fast) var(--ease-standard) both;
    z-index: 6;
  }
  @keyframes tt-in {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }
</style>
