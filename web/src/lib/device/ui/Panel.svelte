<script lang="ts">
  // A collapsible panel of a properties column (Blender's Properties editor): a thin header with a disclosure arrow,
  // the body below. Its open state is kept per name in this browser.
  import type { Snippet } from 'svelte';

  let { name, title, open: start = true, right, children }: { name: string; title: string; open?: boolean; right?: Snippet; children: Snippet } = $props();

  const key = `fw.panel.${name}`;
  let open = $state(start);
  $effect(() => {
    try {
      const v = localStorage.getItem(key);
      if (v != null) open = v === '1';
    } catch {
      /* storage off: the default stands */
    }
  });
  function toggle() {
    open = !open;
    try {
      localStorage.setItem(key, open ? '1' : '0');
    } catch {
      /* not kept */
    }
  }
</script>

<section class="bp" class:open>
  <header>
    <button class="tog" onclick={toggle} aria-expanded={open}>
      <i class="ti ti-chevron-right ar" aria-hidden="true"></i>
      <span>{title}</span>
    </button>
    {#if right}<span class="right">{@render right()}</span>{/if}
  </header>
  {#if open}<div class="body">{@render children()}</div>{/if}
</section>

<style>
  .bp {
    background: var(--bw-panel);
    border-radius: var(--bw-r, 6px);
  }
  header {
    display: flex;
    align-items: center;
    height: 32px;
    padding-right: var(--bw-pad, 10px);
  }
  .tog {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    height: 100%;
    padding: 0 var(--bw-pad, 10px);
    border: none;
    background: none;
    color: var(--on-surface);
    font: inherit;
    font-size: 13px;
    font-weight: var(--font-weight-semibold);
    text-align: left;
    cursor: pointer;
  }
  .ar {
    font-size: 12px;
    color: var(--on-surface-var);
    transition: transform var(--dur-fast) var(--ease-standard);
  }
  .open .ar {
    transform: rotate(90deg);
  }
  .right {
    display: flex;
    gap: 4px;
    align-items: center;
    font-size: 11px;
    color: var(--on-surface-var);
  }
  .body {
    padding: 2px var(--bw-pad, 10px) 12px;
    display: grid;
    gap: 8px;
  }
</style>
