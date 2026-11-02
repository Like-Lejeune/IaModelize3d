<script lang="ts">
  import Icon from './Icon.svelte';
  import { tick, untrack } from 'svelte';
  import { api } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';

  let {
    store,
    snapshot,
    onUseConcept,
    focus = null,
    onFocused,
  }: {
    store: ProjectStore;
    snapshot: () => string | null;
    onUseConcept: (url: string) => void;
    /** Sketch concepts for this prompt right away ("Ideas first"), or start drawing a change (viewer toolbar). */
    focus?: { prompt?: string; draw?: boolean } | null;
    onFocused?: () => void;
  } = $props();

  let prompt = $state('');
  let instruction = $state('');
  let canvas = $state<HTMLCanvasElement>();
  let base = $state<string | null>(null);
  let drawing = false;
  let strokes = $state(0);

  async function concepts() {
    if (!prompt.trim()) return;
    await store.startSide(() => api.concepts(store.id, prompt.trim(), 4));
  }

  function grab() {
    base = snapshot();
    strokes = 0;
    queueMicrotask(paintBase);
  }

  function paintBase() {
    if (!canvas || !base) return;
    const im = new Image();
    im.onload = () => {
      canvas!.width = im.naturalWidth;
      canvas!.height = im.naturalHeight;
      const ctx = canvas!.getContext('2d')!;
      ctx.drawImage(im, 0, 0);
    };
    im.src = base;
  }

  function pos(e: PointerEvent) {
    const r = canvas!.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * canvas!.width, ((e.clientY - r.top) / r.height) * canvas!.height];
  }

  function down(e: PointerEvent) {
    if (!canvas) return;
    drawing = true;
    canvas.setPointerCapture(e.pointerId);
    const ctx = canvas.getContext('2d')!;
    ctx.strokeStyle = '#ff2d55';
    ctx.lineWidth = Math.max(4, canvas.width / 160);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    const [x, y] = pos(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
  }
  function move(e: PointerEvent) {
    if (!drawing || !canvas) return;
    const ctx = canvas.getContext('2d')!;
    const [x, y] = pos(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  }
  function up() {
    if (drawing) strokes++;
    drawing = false;
  }

  async function sendEdit() {
    if (!canvas || !instruction.trim()) return;
    const png = canvas.toDataURL('image/png').split(',')[1];
    await store.startSide(() => api.visualEdit(store.id, instruction.trim(), png));
    instruction = '';
  }

  // each request is handled once and handed back, so opening the tab again does not repeat it
  $effect(() => {
    const f = focus;
    if (!f) return;
    untrack(() => {
      onFocused?.();
      if (f.prompt) {
        prompt = f.prompt;
        if (!store.running) concepts();
      }
      if (f.draw && store.build) {
        grab();
        tick().then(() => canvas?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
      }
    });
  });
</script>

<div class="stack">
  <section class="stack">
    <h3 class="section-title">{t('concepts')}</h3>
    <p class="muted small">{t('concepts_hint')}</p>
    <div class="row nowrap">
      <input type="text" bind:value={prompt} placeholder={t('concepts_placeholder')} aria-label={t('concepts')} style="flex:1;min-width:0" />
      <button class="btn" onclick={concepts} disabled={!prompt.trim() || store.running}><Icon name="sparkles" size={16} /> {t('generate')}</button>
    </div>
    {#if store.concepts.length}
      <div class="cgrid">
        {#each store.concepts as c (c.url)}
          <figure>
            <img src={c.url} alt={c.prompt ?? 'concept'} loading="lazy" />
            <button class="btn small" onclick={() => onUseConcept(c.url)}>{t('use_this')}</button>
          </figure>
        {/each}
      </div>
    {/if}
  </section>

  <section class="stack">
    <h3 class="section-title">{t('visual_edit')}</h3>
    <p class="muted small">{t('visual_edit_hint')}</p>
    <button class="btn" onclick={grab} disabled={!store.build}><Icon name={base ? 'refresh' : 'photo-edit'} size={16} /> {t('visual_edit')}</button>
    {#if base}
      <canvas bind:this={canvas} class="draw" onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} aria-label={t('visual_edit_hint')}></canvas>
      <div class="row nowrap">
        <input type="text" bind:value={instruction} placeholder={t('instruction')} aria-label={t('instruction')} style="flex:1;min-width:0" />
        <button class="btn primary" onclick={sendEdit} disabled={!instruction.trim() || !strokes || store.running}>{t('send')}</button>
      </div>
    {/if}
  </section>
</div>

<style>
  section + section {
    border-top: var(--border-width) solid var(--divider);
    padding-top: var(--space-4);
  }
  .nowrap {
    flex-wrap: nowrap;
  }
  .cgrid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }
  .cgrid figure {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .cgrid img {
    width: 100%;
    border-radius: var(--radius-btn);
    border: var(--border-width) solid var(--outline-variant);
  }
  .draw {
    width: 100%;
    border-radius: var(--radius-btn);
    border: var(--border-width) solid var(--outline-variant);
    touch-action: none;
    cursor: crosshair;
    background: var(--surface);
  }
</style>
