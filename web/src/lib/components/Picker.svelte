<script lang="ts" generics="T extends string">
  // Quiet text button that opens a list of options, each with an optional one-line hint.
  import Icon from './Icon.svelte';

  type Option = { value: T; title: string; short?: string; hint?: string; disabled?: boolean };
  let {
    label,
    value,
    options,
    onpick,
    quiet = false,
    up = false,
  }: { label: string; value: T; options: Option[]; onpick: (v: T) => void; quiet?: boolean; up?: boolean } = $props();

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
  <button bind:this={btn} class="cur" class:quiet onclick={() => (open = !open)} aria-haspopup="listbox" aria-expanded={open} aria-label="{label}: {current?.title}" title={label}>
    {current?.short ?? current?.title}
  </button>
  {#if open}
    <div bind:this={menu} class="menu" style={pos} role="listbox" aria-label={label}>
      {#each options as o (o.value)}
        <button class="opt" role="option" aria-selected={o.value === value} disabled={o.disabled} onclick={() => pick(o.value)}>
          <span class="on">{#if o.value === value}<Icon name="check" size={12} stroke={2.4} />{/if}</span>
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
    border: none;
    background: none;
    padding: 2px 8px;
    border-radius: 8px;
    font-size: var(--fs-sm);
    color: var(--text-2);
    white-space: nowrap;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
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
    position: fixed;
    z-index: 50;
    width: max-content;
    min-width: 140px;
    max-width: min(240px, calc(100vw - 32px));
    padding: 3px;
    display: flex;
    flex-direction: column;
    gap: 1px;
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 10px;
    box-shadow: none;
  }
  .opt {
    display: flex;
    gap: 6px;
    align-items: flex-start;
    padding: 4px 8px 4px 6px;
    border: none;
    border-radius: 7px;
    background: none;
    text-align: left;
    color: var(--text-2);
  }
  .opt:hover:not(:disabled),
  .opt[aria-selected='true'] {
    background: var(--panel-3);
    color: var(--text);
  }
  .opt:disabled {
    cursor: default;
    opacity: 0.5;
  }
  .on {
    width: 13px;
    flex: none;
    display: grid;
    height: 18px;
    align-items: center;
    color: var(--accent);
  }
  .txt {
    min-width: 0;
    display: flex;
    flex-direction: column;
    font-size: 12.5px;
    line-height: 18px;
  }
  .txt strong {
    font-weight: 500;
  }
  .txt strong,
  .hint {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .hint {
    font-size: 11px;
    line-height: 1.35;
    color: var(--muted);
  }
</style>
