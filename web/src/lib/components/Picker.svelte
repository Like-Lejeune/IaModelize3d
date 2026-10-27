<script lang="ts" generics="T extends string">
  // Quiet text button that opens a list of options, each with an optional one-line hint.
  import Icon from './Icon.svelte';

  type Option = { value: T; title: string; hint?: string; disabled?: boolean };
  let { label, value, options, onpick, quiet = false }: { label: string; value: T; options: Option[]; onpick: (v: T) => void; quiet?: boolean } = $props();

  let open = $state(false);
  let wrap: HTMLDivElement;
  const current = $derived(options.find((o) => o.value === value) ?? options[0]);

  function pick(v: T) {
    onpick(v);
    open = false;
  }
</script>

<svelte:window
  onclick={(e) => open && !wrap?.contains(e.target as Node) && (open = false)}
  onkeydown={(e) => e.key === 'Escape' && (open = false)}
/>

<div class="wrap" bind:this={wrap}>
  <button class="cur" class:quiet onclick={() => (open = !open)} aria-haspopup="listbox" aria-expanded={open} aria-label="{label}: {current?.title}" title={label}>
    {current?.title}
  </button>
  {#if open}
    <div class="menu card" role="listbox" aria-label={label}>
      {#each options as o (o.value)}
        <button class="opt" role="option" aria-selected={o.value === value} disabled={o.disabled} onclick={() => pick(o.value)}>
          <span class="on">{#if o.value === value}<Icon name="check" size={15} stroke={2.2} />{/if}</span>
          <span class="txt">
            <strong>{o.title}</strong>
            {#if o.hint}<span class="xs muted">{o.hint}</span>{/if}
          </span>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .wrap {
    position: relative;
  }
  .cur {
    border: none;
    background: none;
    padding: 2px 8px;
    border-radius: 8px;
    font-size: var(--fs-sm);
    color: var(--text-2);
    white-space: nowrap;
  }
  .cur.quiet {
    color: var(--muted);
  }
  .cur:hover,
  .cur[aria-expanded='true'] {
    background: var(--panel-3);
    color: var(--text);
  }
  .menu {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 30;
    width: max-content;
    min-width: 180px;
    max-width: min(320px, calc(100vw - 32px));
    padding: 6px;
    display: flex;
    flex-direction: column;
    box-shadow: var(--shadow-lg);
  }
  .opt {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    padding: 6px 8px;
    border: none;
    border-radius: 8px;
    background: none;
    text-align: left;
  }
  .opt:hover:not(:disabled) {
    background: var(--panel-3);
  }
  .opt:disabled {
    cursor: default;
    opacity: 0.55;
  }
  .on {
    width: 16px;
    flex: none;
    display: grid;
    height: 20px;
    align-items: center;
    color: var(--accent);
  }
  .txt {
    display: flex;
    flex-direction: column;
    gap: 1px;
    font-size: var(--fs-sm);
    line-height: 20px;
  }
  .txt .xs {
    line-height: 1.4;
  }
</style>
