<script lang="ts">
  // The firmware files of the device, one tab per file, with line numbers and syntax colours; empty until the agent
  // writes them. The colours are a <pre> laid exactly under a textarea whose own text is transparent: same font, same
  // metrics, the same scroll (both sit in one scrolling box), so typing stays a plain textarea.
  import Icon from '$lib/components/Icon.svelte';
  import { deviceApi } from './api';
  import type { DeviceStore } from './store.svelte';
  import { dt } from './i18n';
  import { codeLang, highlight } from './highlight';
  import { untrack } from 'svelte';

  let { device, projectId, onSend, readonly = false }: { device: DeviceStore; projectId: string; onSend?: (msg: string) => void; readonly?: boolean } = $props();
  const fw = $derived(device.state?.doc.firmware ?? null);
  const files = $derived(Object.entries(fw?.files ?? {}));
  let picked = $state<string | null>(null);
  const name = $derived(files.find(([n]) => n === picked)?.[0] ?? files[0]?.[0] ?? null);
  // what the textarea holds: the file as saved, or what was just typed (the colours follow the keystroke itself)
  let src = $state('');
  $effect(() => {
    const saved = fw?.files[name ?? ''] ?? '';
    untrack(() => saved !== src && (src = saved));
  });
  const lines = $derived(src.split('\n'));
  // a trailing newline gets its own (empty) line in the textarea; the <pre> needs one more to match
  const html = $derived(highlight(src, codeLang(name ?? '', fw?.lang)) + '\n');
  let area = $state<HTMLTextAreaElement>();
  let under = $state<HTMLPreElement>();

  // typing edits the file in place; the save goes with the next pause (DeviceStore.edit)
  function typed(text: string) {
    src = text;
    if (!name) return;
    const file = name;
    device.edit((d) => {
      if (d.firmware) d.firmware.files[file] = text;
    }, `firmware ${file} edited`);
  }
  // the textarea is as big as its text, so it should never scroll itself; if the caret nudges it, the colours follow
  function sync() {
    if (area && under) under.style.transform = area.scrollLeft || area.scrollTop ? `translate(${-area.scrollLeft}px, ${-area.scrollTop}px)` : '';
  }
  $effect(() => {
    void html;
    sync();
  });
  let copied = $state(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(fw?.files[name ?? ''] ?? '');
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      /* no clipboard here */
    }
  }
</script>

<div class="fwc">
  {#if fw && name}
    <div class="bar">
      <div class="ftabs" role="tablist">
        {#each files as [n] (n)}
          <button role="tab" aria-selected={n === name} onclick={() => (picked = n)}><i class="ti ti-file-code" aria-hidden="true"></i> {n}</button>
        {/each}
      </div>
      <span class="spacer"></span>
      <button class="btn small ghost" onclick={copy}><Icon name={copied ? 'check' : 'copy'} size={14} /> {copied ? dt('copied') : dt('copy')}</button>
      <a class="btn small" href={deviceApi.firmwareUrl(projectId, name)} download={name}><Icon name="download" size={14} /> {dt('download')}</a>
    </div>
    <div class="code" role="region" aria-label={name}>
      <pre class="nums" aria-hidden="true">{lines.map((_, i) => i + 1).join('\n')}</pre>
      <div class="ed">
        <pre class="hl" aria-hidden="true" bind:this={under}>{@html html}</pre>
        <textarea class="src" bind:this={area} spellcheck="false" wrap="off" autocomplete="off" autocapitalize="off" readonly={readonly} value={src} rows="1"
          oninput={(e) => typed(e.currentTarget.value)} onscroll={sync} aria-label={name}></textarea>
      </div>
    </div>
  {:else}
    <div class="empty">
      <i class="ti ti-code big" aria-hidden="true"></i>
      <h3>{dt('fw_empty_title')}</h3>
      <p class="muted small">{dt('fw_empty_d')}</p>
      {#if onSend}<button class="btn primary" onclick={() => onSend?.(dt('firmware_msg'))}><Icon name="wand" size={15} /> {dt('firmware_ask')}</button>{/if}
    </div>
  {/if}
</div>

<style>
  .fwc {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    background: var(--surface-container-lowest);
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 6px;
    border-bottom: 1px solid var(--divider);
    flex-wrap: wrap;
  }
  .ftabs {
    display: flex;
    gap: 4px;
    min-width: 0;
    overflow-x: auto;
  }
  .ftabs button {
    font: inherit;
    font-size: 12px;
    font-family: var(--font-mono);
    padding: 2px 8px;
    border-radius: 3px;
    border: 1px solid transparent;
    background: transparent;
    color: var(--on-surface-var);
    cursor: pointer;
    white-space: nowrap;
  }
  .ftabs button[aria-selected='true'] {
    background: var(--surface-container);
    border-color: var(--outline-variant);
    color: var(--on-surface);
  }
  .spacer {
    flex: 1;
  }
  .code {
    flex: 1;
    min-height: 0;
    overflow: auto;
    display: grid;
    grid-template-columns: auto 1fr;
    font-family: var(--font-mono);
    font-size: 12.5px;
    line-height: 1.55;
  }
  /* the numbers, the colours and the textarea share every metric, or the caret drifts off its letters */
  .code pre,
  textarea.src {
    margin: 0;
    padding: 12px 14px;
    border: none;
    font: inherit;
    line-height: inherit;
    letter-spacing: normal;
    word-spacing: normal;
    font-variant-ligatures: none;
    white-space: pre;
    tab-size: 2;
  }
  /* the colours and the textarea in one grid cell: the <pre> sets the size, the textarea fills it */
  .ed {
    display: grid;
  }
  .hl,
  textarea.src {
    grid-area: 1 / 1;
  }
  .hl {
    color: var(--on-surface);
    pointer-events: none;
    --c-kw: #c792ea;
    --c-type: #82aaff;
    --c-fn: #ffcb6b;
    --c-str: #c3e88d;
    --c-num: #f78c6c;
    --c-pp: #89ddff;
  }
  /* the same hues, dark enough for a light page */
  @media (prefers-color-scheme: light) {
    :global(:root:not([data-theme='dark'])) .hl {
      --c-kw: #7b3fc4;
      --c-type: #1f5fbf;
      --c-fn: #8a5b00;
      --c-str: #3d7a1c;
      --c-num: #b04a1e;
      --c-pp: #0b6f86;
    }
  }
  :global(:root[data-theme='light']) .hl {
    --c-kw: #7b3fc4;
    --c-type: #1f5fbf;
    --c-fn: #8a5b00;
    --c-str: #3d7a1c;
    --c-num: #b04a1e;
    --c-pp: #0b6f86;
  }
  /* colour only: an italic or bold face could change the glyph widths under the caret */
  .hl :global(.t-com) {
    color: var(--outline);
  }
  .hl :global(.t-kw) {
    color: var(--c-kw);
  }
  .hl :global(.t-type) {
    color: var(--c-type);
  }
  .hl :global(.t-fn) {
    color: var(--c-fn);
  }
  .hl :global(.t-str) {
    color: var(--c-str);
  }
  .hl :global(.t-num),
  .hl :global(.t-lit) {
    color: var(--c-num);
  }
  .hl :global(.t-pp) {
    color: var(--c-pp);
  }
  textarea.src {
    width: 100%;
    height: 100%;
    min-width: 0;
    outline: none;
    resize: none;
    overflow: hidden;
    background: transparent;
    color: transparent;
    caret-color: var(--on-surface);
  }
  textarea.src::selection {
    background: color-mix(in srgb, var(--primary) 32%, transparent);
  }
  .nums {
    text-align: right;
    color: var(--outline);
    user-select: none;
    border-right: 1px solid var(--divider);
    position: sticky;
    left: 0;
    background: var(--surface-container-lowest);
  }
  .empty {
    margin: auto;
    max-width: 420px;
    text-align: center;
    display: grid;
    gap: var(--space-2);
    justify-items: center;
    padding: var(--space-5);
  }
  .empty h3 {
    margin: 0;
  }
  .empty p {
    margin: 0;
  }
  .big {
    font-size: 36px;
    color: var(--primary);
  }
</style>
