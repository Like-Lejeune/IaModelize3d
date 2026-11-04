<script lang="ts">
  // The firmware files of the device, one tab per file, with line numbers and syntax colours; empty until the agent
  // writes them. The colours are a <pre> laid exactly under a textarea whose own text is transparent: same font, same
  // metrics, the same scroll (both sit in one scrolling box), so typing stays a plain textarea. The server's check of the
  // code (firmware.check: compiled, or read by a checker) shows over it: a badge, and its errors and warnings below the
  // code, each opening its file at its line, which is marked in the text.
  import Icon from '$lib/components/Icon.svelte';
  import { deviceApi, type FwDiag } from './api';
  import type { DeviceStore } from './store.svelte';
  import { dt } from './i18n';
  import { codeLang, highlight } from './highlight';
  import { untrack, tick } from 'svelte';

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
  let box = $state<HTMLDivElement>();

  // ---- the server's check: errors and warnings, each with its file and line
  const check = $derived(fw?.check ?? null);
  type Diag = FwDiag & { sev: 'error' | 'warning' };
  const diags = $derived<Diag[]>([
    ...(check?.errors ?? []).map((d) => ({ ...d, sev: 'error' as const })),
    ...(check?.warnings ?? []).map((d) => ({ ...d, sev: 'warning' as const })),
  ]);
  const nErr = $derived(check?.errors?.length ?? 0);
  // a diagnostic names its file as the compiler did ('/tmp/x/sketch/dice.ino'): match it to a tab by its base name
  const fileOf = (d: FwDiag) => {
    const base = (d.file ?? '').split(/[\\/]/).pop() ?? '';
    return files.find(([n]) => n === d.file || n === base)?.[0] ?? (files.length === 1 ? files[0][0] : null);
  };
  const marks = $derived(diags.filter((d) => d.line && fileOf(d) === name).map((d) => ({ line: d.line!, sev: d.sev, msg: d.msg })));
  // typed after the check: its lines may have moved (a new check, not a copy of the document, clears it)
  let typedSince = $state(false);
  const checkKey = $derived(JSON.stringify(check));
  $effect(() => {
    void checkKey;
    untrack(() => (typedSince = false));
  });
  let showDiags = $state(true);

  /** Open a diagnostic's file and put the caret on its line, scrolled into the middle of the view. */
  async function go(d: FwDiag) {
    const f = fileOf(d);
    if (f) picked = f;
    await tick();
    if (!d.line || !area || !box) return;
    const at = src.split('\n').slice(0, d.line - 1).reduce((n, l) => n + l.length + 1, 0);
    const end = at + (src.split('\n')[d.line - 1]?.length ?? 0);
    const lh = parseFloat(getComputedStyle(area).lineHeight) || 19;
    box.scrollTo({ top: Math.max(0, 12 + (d.line - 1) * lh - box.clientHeight / 3), behavior: 'smooth' });
    area.focus({ preventScroll: true });
    area.setSelectionRange(at, end);
  }

  // typing edits the file in place; the save goes with the next pause (DeviceStore.edit)
  function typed(text: string) {
    src = text;
    typedSince = true;
    if (!name) return;
    const file = name;
    device.edit((d) => {
      if (d.firmware) d.firmware.files[file] = text;
    }, `firmware ${file} edited`);
  }
  const where = (d: FwDiag) => `${fileOf(d) ?? d.file ?? ''}${d.line ? `:${d.line}` : ''}`;
  function askFix() {
    const list = (check?.errors ?? []).slice(0, 8).map((d) => `${where(d)} ${d.msg}`).join('; ');
    onSend?.(dt('fw_fix_msg', { e: list }));
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
      {#if check}
        <button class="chk" class:ok={check.ok && !nErr} class:err={!check.ok || nErr > 0} class:stale={typedSince} onclick={() => (showDiags = !showDiags)}
          title={`${check.tool ?? ''}${typedSince ? ` · ${dt('fw_check_stale')}` : ''}`} aria-expanded={showDiags}>
          <i class="ti {check.ok && !nErr ? 'ti-circle-check' : 'ti-alert-triangle'}" aria-hidden="true"></i>
          {check.ok && !nErr ? dt('fw_check_ok') : dt('fw_check_bad', { n: nErr })}{#if check.warnings?.length}{' · '}{dt('fw_check_warn', { n: check.warnings.length })}{/if}
        </button>
      {:else}
        <span class="chk none" title={dt('fw_unchecked_d')}><i class="ti ti-help-circle" aria-hidden="true"></i> {dt('fw_unchecked')}</span>
      {/if}
      <button class="btn small ghost" onclick={copy}><Icon name={copied ? 'check' : 'copy'} size={14} /> {copied ? dt('copied') : dt('copy')}</button>
      <a class="btn small" href={deviceApi.firmwareUrl(projectId, name)} download={name}><Icon name="download" size={14} /> {dt('download')}</a>
    </div>
    <div class="code" role="region" aria-label={name} bind:this={box}>
      <pre class="nums" aria-hidden="true">{lines.map((_, i) => i + 1).join('\n')}</pre>
      <div class="ed">
        {#each marks as m, i (i)}<div class="mark {m.sev}" style="top: calc(12px + {m.line - 1} * 1.55em)" title={m.msg}></div>{/each}
        <pre class="hl" aria-hidden="true" bind:this={under}>{@html html}</pre>
        <textarea class="src" bind:this={area} spellcheck="false" wrap="off" autocomplete="off" autocapitalize="off" readonly={readonly} value={src} rows="1"
          oninput={(e) => typed(e.currentTarget.value)} onscroll={sync} aria-label={name}></textarea>
      </div>
    </div>
    {#if diags.length && showDiags}
      <div class="diags" role="region" aria-label={dt('fw_problems')}>
        <div class="dh">
          <strong>{dt('fw_problems')}</strong>
          {#if typedSince}<span class="muted">{dt('fw_check_stale')}</span>{/if}
          <span class="spacer"></span>
          {#if onSend && nErr && !readonly}<button class="btn small" onclick={askFix}><Icon name="wand" size={13} /> {dt('ask_agent_fix')}</button>{/if}
        </div>
        {#each diags as d, i (i)}
          <button class="dg {d.sev}" onclick={() => go(d)}>
            <i class="ti {d.sev === 'error' ? 'ti-alert-triangle' : 'ti-info-circle'}" aria-hidden="true"></i>
            <span class="mono at">{where(d)}</span>
            <span class="msg">{d.msg}{#if d.hint}<span class="hint">{d.hint}</span>{/if}</span>
          </button>
        {/each}
      </div>
    {/if}
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
    font-size: var(--text-sm);
    font-family: var(--font-mono);
    padding: 2px 8px;
    border-radius: var(--radius-xs);
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
    font-size: var(--text-md);
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
    word-spacing: normal;
    font-variant-ligatures: none;
    white-space: pre;
    tab-size: 2;
  }
  /* the colours and the textarea in one grid cell: the <pre> sets the size, the textarea fills it */
  .ed {
    display: grid;
    position: relative;
    z-index: 0;
  }
  /* a line the check complains about: a band under its text, as wide as the code */
  .mark {
    position: absolute;
    left: 0;
    right: 0;
    height: 1.55em;
    z-index: -1;
    pointer-events: none;
    background: color-mix(in srgb, var(--warn) 16%, transparent);
    border-left: 3px solid var(--warn);
  }
  .mark.error {
    background: color-mix(in srgb, var(--error) 18%, transparent);
    border-left-color: var(--error);
  }
  .chk {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 24px;
    padding: 0 9px;
    border-radius: var(--radius-lg);
    border: 1px solid var(--outline-variant);
    background: transparent;
    color: var(--on-surface-var);
    font: inherit;
    font-size: var(--text-sm);
    white-space: nowrap;
    cursor: pointer;
  }
  .chk.ok {
    color: var(--ok);
    border-color: color-mix(in srgb, var(--ok) 45%, transparent);
    background: color-mix(in srgb, var(--ok) 10%, transparent);
  }
  .chk.err {
    color: var(--error);
    border-color: color-mix(in srgb, var(--error) 45%, transparent);
    background: color-mix(in srgb, var(--error) 10%, transparent);
  }
  .chk.stale {
    opacity: 0.65;
  }
  .chk.none {
    cursor: default;
  }
  .diags {
    flex: none;
    max-height: 34%;
    overflow: auto;
    border-top: 1px solid var(--divider);
    background: var(--surface-container-low);
    font-size: var(--text-md);
  }
  .dh {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 10px;
    position: sticky;
    top: 0;
    background: var(--surface-container-low);
    font-size: var(--text-sm);
  }
  .dg {
    display: grid;
    grid-template-columns: 16px auto 1fr;
    gap: 8px;
    align-items: baseline;
    width: 100%;
    padding: 4px 10px;
    border: none;
    background: none;
    color: var(--on-surface);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .dg:hover {
    background: color-mix(in srgb, var(--on-surface) 6%, transparent);
  }
  .dg i {
    color: var(--warn-text);
  }
  .dg.error i {
    color: var(--error);
  }
  .dg .at {
    font-size: var(--text-sm);
    color: var(--on-surface-var);
    white-space: nowrap;
  }
  .dg .msg {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .hint {
    display: block;
    color: var(--on-surface-var);
    font-size: var(--text-sm);
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
    font-size: var(--text-4xl);
    color: var(--primary);
  }
</style>
