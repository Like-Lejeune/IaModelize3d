<script lang="ts" generics="T extends string">
  // A text button with its arrow that opens a list of options, each with an optional one-line hint.
  import Icon from './Icon.svelte';

  type Option = { value: T; title: string; short?: string; hint?: string; disabled?: boolean };
  let {
    label,
    value,
    options,
    onpick,
    up = false,
  }: { label: string; value: T; options: Option[]; onpick: (v: T) => void; up?: boolean } = $props();

  let open = $state(false);
  let wrap: HTMLDivElement;
  let btn: HTMLButtonElement;
  let menu = $state<HTMLDivElement>();
  let pos = $state('');
  const current = $derived(options.find((o) => o.value === value) ?? options[0]);

  // The menu is fixed to the viewport so a clipping panel cannot cut it: it grows to the right
  // of the button and slides back only as far as the screen edge needs.
  function place() {
    if (!menu) return;
    const r = btn.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.left, innerWidth - menu.offsetWidth - 8));
    pos = `left:${left}px;` + (up ? `bottom:${innerHeight - r.top + 6}px` : `top:${r.bottom + 6}px`);
  }

  $effect(() => {
    if (open && menu) place();
  });

  function pick(v: T) {
    onpick(v);
    open = false;
  }
</script>

<svelte:window
  onclick={(e) => open && !wrap?.contains(e.target as Node) && (open = false)}
  onkeydown={(e) => e.key === 'Escape' && (open = false)}
  onresize={() => (open = false)}
/>

<div class="wrap" bind:this={wrap}>
  <button bind:this={btn} class="cur" onclick={() => (open = !open)} aria-haspopup="listbox" aria-expanded={open} aria-label="{label}: {current?.title}" title={label}>
    <span class="val">{current?.short ?? current?.title}</span>
    <Icon name="chevron-down" size={13} />
  </button>
  {#if open}
    <div bind:this={menu} class="menu" style={pos} role="listbox" aria-label={label}>
      {#each options as o (o.value)}
        <button class="opt" role="option" aria-selected={o.value === value} disabled={o.disabled} onclick={() => pick(o.value)}>
          <span class="on">{#if o.value === value}<Icon name="check" size={13} />{/if}</span>
          <span class="txt">
            <strong>{o.short ?? o.title}</strong>
            {#if o.hint}<span class="hint">{o.hint}</span>{/if}
          </span>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .wrap {
    position: relative;
    min-width: 0;
  }
  .cur {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    border: none;
    background: none;
    padding: 4px 8px;
    border-radius: var(--radius-btn);
    font-family: inherit;
    font-size: var(--text-md);
    color: var(--on-surface-var);
    white-space: nowrap;
    max-width: 100%;
    transition:
      background-color var(--dur-fast) var(--ease-standard),
      color var(--dur-fast) var(--ease-standard);
  }
  .val {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .cur:hover,
  .cur[aria-expanded='true'] {
    background: var(--surface-high);
    color: var(--on-surface);
  }
  .menu {
    position: fixed;
    z-index: 150;
    width: max-content;
    min-width: 120px;
    max-width: min(240px, calc(100vw - 32px));
    padding: var(--space-1);
    display: flex;
    flex-direction: column;
    gap: 1px;
    background: var(--surface-container);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-field);
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.32);
  }
  .opt {
    display: flex;
    gap: 6px;
    align-items: flex-start;
    padding: 4px 10px 4px 6px;
    border: none;
    border-radius: var(--radius-tag);
    background: none;
    font-family: inherit;
    text-align: left;
    color: var(--on-surface);
  }
  .opt:hover:not(:disabled),
  .opt[aria-selected='true'] {
    background: var(--surface-high);
  }
  .opt:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
  .on {
    width: 13px;
    flex: none;
    display: grid;
    height: 18px;
    align-items: center;
    color: var(--primary);
  }
  .txt {
    min-width: 0;
    display: flex;
    flex-direction: column;
    font-size: var(--text-md);
    line-height: 18px;
  }
  .txt strong {
    font-weight: var(--font-weight-semibold);
  }
  .txt strong,
  .hint {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .hint {
    font-size: var(--text-sm);
    line-height: 1.35;
    color: var(--outline);
  }
</style>
