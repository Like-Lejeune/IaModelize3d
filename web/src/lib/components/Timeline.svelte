<script lang="ts">
  import { markdown } from '$lib/md';
  import { t } from '$lib/i18n.svelte';
  import type { ProjectStore, TimelineItem } from '$lib/project.svelte';

  let { store, onUseConcept }: { store: ProjectStore; onUseConcept?: (url: string) => void } = $props();
  let scroller: HTMLDivElement;
  let freeText = $state<Record<string, string>>({});
  let zoom = $state<string | null>(null);

  const TOOL_ICONS: Record<string, string> = {
    write_program: '✎', patch_program: '✎', set_params: '⚙', render: '◉', inspect: '⌖', check: '✓', web_search: '🔎', search_dimensions: '🔎',
    lookup_standard: '📏', recall: '🧠', ask_user: '?', fit_params: '⟲', measure: '📐', scene: '📷', propose_probe: '🧪', finish: '■',
  };

  let stuck = true;
  $effect(() => {
    void store.timeline.length;
    void store.status;
    queueMicrotask(() => {
      if (scroller && stuck) scroller.scrollTop = scroller.scrollHeight;
    });
  });

  function onScroll() {
    // follow new items only while the user is at the bottom
    stuck = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
  }

  function args(a: any): string {
    if (a == null) return '';
    const s = typeof a === 'string' ? a : JSON.stringify(a, null, 1);
    return s.length > 1200 ? s.slice(0, 1200) + '…' : s;
  }

  function preview(item: Extract<TimelineItem, { kind: 'tool' }>): string {
    const a = item.args;
    if (!a || typeof a !== 'object') return '';
    for (const k of ['query', 'note', 'question', 'summary', 'reason', 'name']) if (typeof a[k] === 'string') return a[k].slice(0, 90);
    return '';
  }
</script>

<div class="tl" bind:this={scroller} onscroll={onScroll} aria-live="polite">
  {#if !store.timeline.length}
    <p class="muted hint">{t('no_program')}</p>
  {/if}
  {#each store.timeline as item (item.key)}
    {#if item.kind === 'user'}
      <div class="msg user"><div class="bubble">{item.text}</div></div>
    {:else if item.kind === 'agent'}
      <div class="msg agent"><div class="bubble md">{@html markdown(item.text)}</div></div>
    {:else if item.kind === 'status'}
      <div class="status muted">· {item.text}</div>
    {:else if item.kind === 'thinking'}
      <details class="think">
        <summary class="muted">💭 {t('thinking')}</summary>
        <div class="md small">{@html markdown(item.text)}</div>
      </details>
    {:else if item.kind === 'tool'}
      <details class="tool" class:fail={item.result && !item.result.ok}>
        <summary>
          <span class="ico">{TOOL_ICONS[item.name] ?? '▸'}</span>
          <span class="mono">{item.name}</span>
          <span class="muted pv">{item.result?.summary ?? preview(item)}</span>
          {#if !item.result}<span class="spin" aria-label="running"></span>{/if}
        </summary>
        {#if item.args}<pre class="mono">{args(item.args)}</pre>{/if}
        {#if item.result?.summary}<div class="small">{item.result.summary}</div>{/if}
      </details>
      {#if item.result?.image}
        <button class="thumb" onclick={() => (zoom = item.result!.image!)}><img src={item.result.image} alt="render" loading="lazy" /></button>
      {/if}
    {:else if item.kind === 'critic'}
      <div class="card critic" class:pass={item.verdict === 'pass'}>
        <div class="row"><strong>{t('critic')}</strong><span class="chip" class:ok={item.verdict === 'pass'} class:warn={item.verdict !== 'pass'}>{t(item.verdict)}</span></div>
        {#if item.issues.length}
          <ul>
            {#each item.issues as is, i (i)}<li><span class="sev {is.severity}">●</span> {is.text}</li>{/each}
          </ul>
        {/if}
        {#if item.render}<button class="thumb" onclick={() => (zoom = item.render!)}><img src={item.render} alt="critic view" loading="lazy" /></button>{/if}
      </div>
    {:else if item.kind === 'ask'}
      <div class="card ask">
        <div class="md">{@html markdown(item.question)}</div>
        {#if item.answered}
          <div class="chip ok">✓ {item.answered}</div>
        {:else}
          <div class="row">
            {#each item.options as opt (opt)}
              <button class="btn small" onclick={() => store.answer(item, opt)}>{opt}</button>
            {/each}
          </div>
          {#if item.allow_text}
            <form
              class="row"
              onsubmit={(e) => {
                e.preventDefault();
                const v = (freeText[item.key] ?? '').trim();
                if (v) store.answer(item, v);
              }}
            >
              <input type="text" placeholder={t('your_answer')} bind:value={freeText[item.key]} aria-label={t('your_answer')} style="flex:1" />
              <button class="btn small primary" type="submit">{t('answer')}</button>
            </form>
          {/if}
        {/if}
      </div>
    {:else if item.kind === 'facts'}
      <div class="card facts">
        <div class="section-title">{t('facts')}</div>
        {#each item.items as f, i (i)}
          <div class="fact">
            <span>{f.subject}: {f.attribute}</span>
            <strong class="mono">{typeof f.value === 'number' ? f.value : String(f.value).replace(/^"|"$/g, '')} {f.unit ?? ''}</strong>
            <span class="chip">{f.source_kind}</span>
            {#if f.source_url}<a href={f.source_url} target="_blank" rel="noopener noreferrer" class="small">↗</a>{/if}
          </div>
        {/each}
      </div>
    {:else if item.kind === 'program'}
      <div class="prog">
        <span class="chip">v{item.version}</span>
        <span class="small">{item.summary ?? (item.author === 'user' ? t('params') : '')}</span>
        {#if item.render}<button class="thumb inline" onclick={() => (zoom = item.render!)}><img src={item.render} alt="v{item.version}" loading="lazy" /></button>{/if}
      </div>
    {:else if item.kind === 'job'}
      <div class="job muted small">
        — {item.status}{item.summary ? `: ${item.summary}` : ''}
        {#if item.cost?.usd !== undefined}<span class="chip mono">${Number(item.cost.usd).toFixed(3)}</span>{/if}
      </div>
    {:else if item.kind === 'concepts'}
      <div class="concepts">
        {#each item.images as im (im.url)}
          <figure>
            <button class="thumb" onclick={() => (zoom = im.url)}><img src={im.url} alt={im.prompt ?? 'concept'} loading="lazy" /></button>
            {#if onUseConcept}<button class="btn small" onclick={() => onUseConcept?.(im.url)}>{t('use_this')}</button>{/if}
          </figure>
        {/each}
      </div>
    {:else if item.kind === 'variants'}
      <div class="concepts">
        {#each item.items as v (v.version)}
          <figure>
            {#if v.render}<button class="thumb" onclick={() => (zoom = v.render!)}><img src={v.render} alt="v{v.version}" loading="lazy" /></button>{/if}
            <figcaption class="small">v{v.version} {v.summary ?? ''}</figcaption>
          </figure>
        {/each}
      </div>
    {:else if item.kind === 'slice'}
      <div class="card small">🖨 {item.data?.stats?.minutes ?? '?'} {t('minutes')} · {item.data?.stats?.grams ?? '?'} {t('grams')}</div>
    {:else if item.kind === 'probe'}
      <div class="card small">🧪 {t('probe')}: {item.data?.dimension ?? ''} — {(item.data?.variants ?? []).map((v: any) => v.label).join(' / ')}</div>
    {:else if item.kind === 'asset'}
      <div class="small muted">📎 {item.asset.kind}</div>
    {:else if item.kind === 'error'}
      <div class="err small">⚠ {item.text}</div>
    {/if}
  {/each}
  {#if store.running}
    <div class="working"><span class="spin"></span> {store.status ?? t('agent_working')}</div>
  {/if}
</div>

{#if zoom}
  <button class="zoom" onclick={() => (zoom = null)} aria-label="close"><img src={zoom} alt="" /></button>
{/if}

<style>
  .tl {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-height: 0;
  }
  .hint {
    text-align: center;
    margin-top: 30px;
  }
  .msg {
    display: flex;
  }
  .msg.user {
    justify-content: flex-end;
  }
  .bubble {
    max-width: 92%;
    padding: 8px 12px;
    border-radius: 14px;
    background: var(--panel-2);
    border: 1px solid var(--line);
    overflow-wrap: anywhere;
  }
  .user .bubble {
    background: var(--accent-soft);
    border-color: color-mix(in srgb, var(--accent) 35%, transparent);
    white-space: pre-wrap;
  }
  .status {
    font-size: 13px;
    padding-left: 4px;
  }
  .think summary,
  .tool summary {
    cursor: pointer;
    font-size: 13px;
    list-style: none;
    display: flex;
    gap: 6px;
    align-items: center;
    min-width: 0;
  }
  .tool {
    border: 1px solid var(--line);
    border-radius: 9px;
    padding: 5px 8px;
    background: var(--panel);
  }
  .tool.fail {
    border-color: color-mix(in srgb, var(--err) 45%, transparent);
  }
  .tool pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 240px;
    overflow: auto;
    font-size: 11.5px;
    margin: 6px 0 0;
  }
  .ico {
    width: 16px;
    text-align: center;
  }
  .pv {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    min-width: 0;
  }
  .thumb {
    border: 1px solid var(--line);
    padding: 0;
    background: none;
    border-radius: 8px;
    overflow: hidden;
    max-width: 280px;
    display: block;
  }
  .thumb img {
    display: block;
    width: 100%;
  }
  .thumb.inline {
    max-width: 120px;
  }
  .critic {
    padding: 8px 10px;
    font-size: 13.5px;
  }
  .critic ul {
    margin: 6px 0;
    padding-left: 16px;
  }
  .sev.error {
    color: var(--err);
  }
  .sev.warn,
  .sev.major {
    color: var(--warn);
  }
  .sev.info,
  .sev.minor {
    color: var(--info);
  }
  .ask .chip {
    align-self: flex-start;
  }
  .ask {
    padding: 10px;
    border-color: var(--accent);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .facts {
    padding: 8px 10px;
  }
  .fact {
    display: flex;
    gap: 6px;
    align-items: center;
    font-size: 13px;
    flex-wrap: wrap;
  }
  .prog {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .job {
    text-align: center;
  }
  .concepts {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 8px;
  }
  .concepts figure {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .small {
    font-size: 13px;
  }
  .err {
    color: var(--err);
  }
  .working {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 13.5px;
    color: var(--muted);
    padding: 4px;
  }
  .spin {
    width: 12px;
    height: 12px;
    border: 2px solid var(--line);
    border-top-color: var(--accent);
    border-radius: 50%;
    display: inline-block;
    animation: sp 0.8s linear infinite;
    flex: none;
  }
  @keyframes sp {
    to {
      transform: rotate(360deg);
    }
  }
  .zoom {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.75);
    z-index: 50;
    display: grid;
    place-items: center;
    border: none;
    padding: 16px;
  }
  .zoom img {
    max-width: 100%;
    max-height: 100%;
    border-radius: 8px;
  }
</style>
