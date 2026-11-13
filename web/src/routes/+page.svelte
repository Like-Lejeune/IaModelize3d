<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Logo from '$lib/components/Logo.svelte';
  import Picker from '$lib/components/Picker.svelte';
  import FeaturedRuns from '$lib/components/FeaturedRuns.svelte';
  import DevicePattern from '$lib/pattern/DevicePattern.svelte';
  import { api, errorText } from '$lib/api';
  import { stashFirst } from '$lib/pending';
  import { ago, i18n, projectTitle, t } from '$lib/i18n.svelte';
  import { isOpenWeights } from '$lib/models';
  import { prefs, setPref, models, modelName, session, REASONING } from '$lib/session.svelte';
  import type { ExampleOut, ProjectOut } from '$lib/types';
  import { dt } from '$lib/device/i18n';

  const ROW = 12; // two rows of small tiles on a wide screen
  // examples that are a replacement part, marked on their card: the server says so (kind 'part', from showcase.py's
  // fit check); this set covers a server that does not yet
  const SPARE_PARTS = new Set(['rack-wheel']);

  let text = $state('');
  /** What the prompt makes: a finished device (board, parts, case, firmware) or a 3D-printed part. */
  let mode = $state<'device' | 'part'>('device');
  const DEVICE_IDEAS = ['idea_weather', 'idea_plant', 'idea_keypad', 'idea_fridge'];
  let files = $state<{ file: File; url: string | null }[]>([]);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let dragging = $state(false);
  let input: HTMLTextAreaElement;

  const modelOptions = $derived(
    models().map((m) => ({ value: m.key, title: modelName(m.id), short: modelName(m.id).replace(/^Muse /, ''), hint: t(m.available ? `model_${m.key}_d` : 'model_locked'), disabled: !m.available })),
  );
  const reasoningOptions = $derived(REASONING.map((r) => ({ value: r, title: t(`reasoning_${r}`) })));
  const ready = $derived(!busy && (!!text.trim() || !!files.length));
  // the Meta models behind every run; the open-weights one only where this server is set up for it
  const metaModels = $derived(['SAM 3.1', 'Muse Spark', 'Muse Image', 'Muse Voice Transcribe', ...(session.me?.models?.some((m) => isOpenWeights(m.id)) ? ['Muse Spark Open'] : [])]);

  let examples = $state<ExampleOut[] | null>(null);
  // every example, the ones of what the prompt makes first: finished devices, or printed parts
  const shownExamples = $derived.by(() => {
    if (!examples) return null;
    const ofMode = (ex: ExampleOut) => (ex.pack === 'device') === (mode === 'device');
    return [...examples.filter(ofMode), ...examples.filter((ex) => !ofMode(ex))];
  });
  let opening = $state<string | null>(null);
  let exampleError = $state<string | null>(null);
  let mine = $state<ProjectOut[] | null>(null);
  let showAll = $state(false);

  // projects with a model, or getting one; drafts that never got a model stay out
  const recent = $derived((mine ?? []).filter((p) => p.cover || p.status === 'working'));
  const shownRecent = $derived(showAll ? recent : recent.slice(0, ROW));
  const working = $derived(recent.some((p) => p.status === 'working'));

  // what failed to load says so and comes back by itself (or with the button): never an empty list that was not empty
  let listError = $state<string | null>(null);

  async function loadMine() {
    try {
      mine = await api.projects();
      listError = null;
    } catch (e) {
      mine ??= [];
      listError = errorText(e);
    }
  }

  async function loadExamples() {
    try {
      examples = await api.examples();
    } catch (e) {
      examples ??= [];
      listError = errorText(e);
    }
  }

  async function reloadLists() {
    await loadMine();
    if (!examples?.length) await loadExamples();
  }

  onMount(() => {
    if (matchMedia('(hover: hover)').matches) input?.focus();
    loadExamples();
    loadMine();
    // a model in progress gets its cover when it is done
    const poll = setInterval(() => (working || listError) && document.visibilityState === 'visible' && reloadLists(), 5000);
    return () => {
      clearInterval(poll);
      files.forEach((f) => f.url && URL.revokeObjectURL(f.url));
    };
  });

  async function openExample(ex: ExampleOut) {
    if (opening) return;
    opening = ex.key;
    exampleError = null;
    try {
      const p = await api.openExample(ex.key, i18n.lang);
      goto(ex.pack === 'device' ? `/d/${p.id}` : `/p/${p.id}`);
    } catch (e) {
      exampleError = errorText(e);
      opening = null;
    }
  }

  /** The hint at the bottom of the first screen: glides down, and the address stays clean. */
  function toExamples(e: MouseEvent) {
    e.preventDefault();
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.getElementById('examples')?.scrollIntoView({ behavior: still ? 'auto' : 'smooth' });
  }

  function addFiles(list: FileList | File[] | null | undefined) {
    if (!list) return;
    const add = Array.from(list).map((file) => ({ file, url: file.type.startsWith('image/') ? URL.createObjectURL(file) : null }));
    files = [...files, ...add].slice(0, 12);
  }

  function fit() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 320)}px`;
    input.style.overflowY = input.scrollHeight > 320 ? 'auto' : 'hidden';
  }

  async function start() {
    if (!ready) return;
    busy = true;
    error = null;
    try {
      // the studio uploads and starts the job, so the user sees progress instead of a spinner here
      const p = await api.createProject(undefined, mode === 'device' ? 'device' : undefined);
      stashFirst(p.id, text.trim() || t('tmpl.copy'), files.map((f) => f.file));
      goto(mode === 'device' ? `/d/${p.id}` : `/p/${p.id}`);
    } catch (e) {
      error = errorText(e);
      busy = false;
    }
  }

  /** Muse Image sketches a few looks first; the studio opens on Ideas and starts them with this text. */
  async function ideasFirst() {
    const idea = text.trim();
    if (busy || !idea) return;
    busy = true;
    error = null;
    try {
      const p = await api.createProject();
      goto(`/p/${p.id}?ideas=${encodeURIComponent(idea)}`);
    } catch (e) {
      error = errorText(e);
      busy = false;
    }
  }
</script>

<svelte:head><title>IaModelize3d</title></svelte:head>

<div class="page">
  <DevicePattern />
  <Header bare />
  <main class="home">
    <section class="hero" aria-labelledby="home-title">
      <h1 id="home-title" class="sr-only">{mode === 'device' ? dt('home_title') : t('tagline')}</h1>
      <div class="brand">
        <Logo size={36} />
        <span>IaModelize3d</span>
      </div>
      <div
        class="create"
        class:dragging
        role="group"
        aria-label={t('prompt_placeholder')}
        ondragover={(e) => {
          e.preventDefault();
          dragging = true;
        }}
        ondragleave={() => (dragging = false)}
        ondrop={(e) => {
          e.preventDefault();
          dragging = false;
          addFiles(e.dataTransfer?.files);
        }}
      >
        {#if files.length}
          <div class="files">
            {#each files as f, i (f.file.name + i)}
              <div class="file">
                {#if f.url}<img src={f.url} alt={f.file.name} />{:else}<span class="ficon"><Icon name={f.file.type.startsWith('video') ? 'video' : 'mic'} size={18} /></span>{/if}
                <button class="x" aria-label="{t('remove')} {f.file.name}" onclick={() => (files = files.filter((_, j) => j !== i))}><Icon name="x" size={11} /></button>
              </div>
            {/each}
          </div>
        {/if}
        <textarea
          bind:this={input}
          bind:value={text}
          rows="4"
          placeholder={mode === 'device' ? dt('home_placeholder') : t('prompt_placeholder')}
          aria-label={mode === 'device' ? dt('home_placeholder') : t('prompt_placeholder')}
          oninput={fit}
          onpaste={(e) => {
            const imgs = Array.from(e.clipboardData?.files ?? []).filter((f) => f.type.startsWith('image/'));
            if (imgs.length) addFiles(imgs);
          }}
          onkeydown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
              e.preventDefault();
              start();
            }
          }}
        ></textarea>
        <div class="bar">
          <label class="square add pressable" title={t('attach_photos')}>
            <Icon name="plus" size={20} />
            <input class="sr-only" type="file" accept="image/*,video/*,audio/*" multiple aria-label={t('attach_photos')} onchange={(e) => addFiles((e.currentTarget as HTMLInputElement).files)} />
          </label>
          <button class="square send pressable" onclick={start} disabled={!ready} aria-label={t('send')} title={t('send')}>
            {#if busy}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="arrow-up" size={20} />{/if}
          </button>
        </div>
      </div>

      <div class="under">
        <div class="modes" role="tablist" aria-label={dt('home_mode')}>
          <button role="tab" aria-selected={mode === 'device'} onclick={() => (mode = 'device')}>{dt('home_device')}</button>
          <button role="tab" aria-selected={mode === 'part'} onclick={() => (mode = 'part')}>{dt('home_part')}</button>
        </div>
        <div class="pickers">
          <Picker label={t('model')} value={prefs.model} options={modelOptions} onpick={(v) => setPref('model', v)} />
          <Picker label={t('reasoning')} value={prefs.reasoning} options={reasoningOptions} onpick={(v) => setPref('reasoning', v)} />
        </div>
      </div>
      {#if error}<p class="err small" role="alert">{error}</p>{/if}

      <p class="ideas">
        {#if mode === 'device'}
          {#each DEVICE_IDEAS as k, i (k)}
            <button class="idea" onclick={() => ((text = dt(k)), input?.focus(), fit())}>{dt(`${k}_short`)}</button>{#if i < DEVICE_IDEAS.length - 1}<span aria-hidden="true">·</span>{/if}
          {/each}
        {:else}
          <button class="idea" onclick={ideasFirst} disabled={busy || !text.trim() || !!files.length} title={t('ideas_first_d')}>{t('ideas_first')}</button>
        {/if}
      </p>

      <nav class="starts" aria-label={dt('home_mode')}>
        <a class="start main" href="/snap">
          <Icon name="camera" size={24} />
          <span><strong>{t('snap_title')}</strong><small>{t('snap_cta_hint')}</small></span>
        </a>
        <a class="start" href="/collection">
          <Icon name="grid" size={24} />
          <span><strong>{t('collection')}</strong><small>{dt('home_collection_d')}</small></span>
        </a>
        <a class="start" href="/parts/new">
          <Icon name="package" size={24} />
          <span><strong>{t('parts_cta')}</strong><small>{t('parts_cta_hint')}</small></span>
        </a>
      </nav>

      <a class="more" href="#examples" onclick={toExamples}>
        {t('examples')}
        <Icon name="chevron-down" size={13} />
      </a>
    </section>

    <FeaturedRuns />

    <section class="block" id="examples" aria-labelledby="examples-title">
      <h2 id="examples-title">{t('examples')}</h2>
      <div class="grid">
        {#if shownExamples === null}
          {#each [0, 1, 2, 3, 4, 5] as i (i)}
            <div class="card tile sk" aria-hidden="true">
              <span class="pic skeleton"></span>
              <span class="meta"><span class="line skeleton"></span></span>
            </div>
          {/each}
        {:else}
          {#each shownExamples as ex (ex.key)}
            <button class="card tile" onclick={() => openExample(ex)} disabled={!!opening && opening !== ex.key} aria-busy={opening === ex.key}>
              <span class="pic">
                <img src={ex.cover} alt="" loading="lazy" />
                {#if opening === ex.key}<span class="state chip"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></span>{/if}
              </span>
              <span class="meta">
                <strong>{ex.title[i18n.lang] ?? ex.title.en}{#if ex.kind === 'part' || SPARE_PARTS.has(ex.key)}<span class="kind">{` · ${t('example_spare')}`}</span>{/if}</strong>
                <span class="cap">{ex.caption[i18n.lang] ?? ex.caption.en}</span>
              </span>
            </button>
          {/each}
        {/if}
      </div>
      {#if exampleError}<p class="err small" role="alert">{exampleError}</p>{/if}
      {#if listError}<p class="muted small" role="status">{listError} <button class="btn ghost small" onclick={reloadLists}>{t('retry')}</button></p>{/if}
    </section>

    {#if recent.length}
      <section class="block" aria-labelledby="recent-title">
        <div class="bhead">
          <h2 id="recent-title">{t('recent')}</h2>
          {#if recent.length > ROW}
            <button class="btn ghost small" aria-expanded={showAll} aria-controls="recent-grid" onclick={() => (showAll = !showAll)}>
              {showAll ? t('show_less') : t('show_all', { n: recent.length })}
            </button>
          {/if}
        </div>
        <div class="grid" id="recent-grid">
          {#each shownRecent as p (p.id)}
            <a class="card tile" href="/{p.pack === 'device' ? 'd' : 'p'}/{p.id}">
              <span class="pic">
                {#if p.cover}<img src={p.cover} alt="" loading="lazy" />{:else}<span class="ph skeleton"><Icon name="cube" size={22} /></span>{/if}
                {#if p.status === 'working'}
                  <span class="chip accent state"><i class="ti ti-loader-2 spin" aria-hidden="true"></i>{t('recent_working')}</span>
                {/if}
              </span>
              <span class="meta">
                <strong>{projectTitle(p.title)}</strong>
                <span class="cap">{ago(p.updated_at)}</span>
              </span>
            </a>
          {/each}
        </div>
      </section>
    {/if}

    <footer class="foot">{t('powered_by')}: {metaModels.join(', ')}</footer>
  </main>
</div>

<style>
  .page {
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
    position: relative;
    isolation: isolate; /* the pattern lies under the content, over the body's background */
  }
  .home {
    width: 100%;
    max-width: calc(var(--container-wide) + 2 * var(--space-5));
    margin: 0 auto;
    padding: 0 var(--space-5) var(--space-8);
    display: flex;
    flex-direction: column;
    gap: var(--space-8);
  }

  /* ---------- the prompt, in the middle of the first screen ---------- */
  .hero {
    position: relative;
    width: 100%;
    max-width: 880px;
    margin: 0 auto;
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--space-3);
    /* room for the hint below, on both sides so the prompt stays in the middle */
    padding: 72px 0;
  }
  .brand {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
    font-size: var(--text-3xl);
    font-weight: var(--font-weight-semibold);
  }
  .more {
    position: absolute;
    left: 50%;
    bottom: var(--space-3);
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: var(--space-1);
    white-space: nowrap;
    font-size: var(--text-sm);
    font-weight: var(--font-weight-regular);
    color: var(--outline);
    text-decoration: none;
    transition: color var(--dur-fast) var(--ease-standard);
  }
  .more:hover {
    color: var(--on-surface-var);
    text-decoration: none;
  }
  .create {
    background: var(--surface-container);
    border-radius: var(--radius-xl);
    transition: background-color var(--dur-fast) var(--ease-standard);
  }
  .create:focus-within,
  .create.dragging {
    background: var(--surface-high);
  }
  .files {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
    padding: var(--space-4) var(--space-5) 0;
  }
  .file {
    position: relative;
    width: 56px;
    height: 56px;
    border-radius: var(--radius-btn);
    background: var(--surface-container-highest);
  }
  .file img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: var(--radius-btn);
  }
  .ficon {
    display: grid;
    place-items: center;
    width: 100%;
    height: 100%;
    color: var(--outline);
  }
  .x {
    position: absolute;
    top: -7px;
    right: -7px;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: var(--border-width) solid var(--outline-variant);
    background: var(--surface-high);
    color: var(--on-surface-var);
    display: grid;
    place-items: center;
    padding: 0;
  }
  .x:hover {
    color: var(--on-surface);
  }
  textarea,
  textarea:hover,
  textarea:focus {
    display: block;
    width: 100%;
    border: none;
    background: transparent;
    box-shadow: none;
    resize: none;
    font-size: var(--text-xl);
    line-height: 28px;
    padding: var(--space-5) var(--space-5) var(--space-2);
    max-height: 320px;
    overflow-y: hidden;
  }
  textarea:focus-visible {
    outline: none;
  }
  .bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-2) var(--space-3) var(--space-3);
  }
  .square {
    flex: none;
    width: 44px;
    height: 44px;
    border-radius: var(--radius-card);
    display: grid;
    place-items: center;
    padding: 0;
    background: transparent;
    border: none;
    color: var(--on-surface-var);
    cursor: pointer;
    transition:
      background-color var(--dur-fast) var(--ease-standard),
      color var(--dur-fast) var(--ease-standard);
  }
  .add:hover,
  .add:focus-within {
    background: var(--surface-container-highest);
    color: var(--on-surface);
  }
  .send {
    background: var(--primary);
    color: var(--on-primary);
  }
  .send:not(:disabled):hover {
    background: color-mix(in srgb, var(--primary) 90%, white);
  }
  /* nothing to send yet: the colour waits for the words */
  .send:disabled {
    cursor: not-allowed;
    background: var(--surface-container-highest);
    color: var(--outline);
  }
  .under {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .modes {
    display: inline-flex;
    gap: 2px;
  }
  .modes button {
    font: inherit;
    font-size: var(--text-md);
    padding: 5px 12px;
    border: none;
    border-radius: var(--radius-btn);
    background: transparent;
    color: var(--on-surface-var);
    cursor: pointer;
  }
  .modes button:hover {
    color: var(--on-surface);
  }
  .modes button[aria-selected='true'] {
    background: var(--surface-container);
    color: var(--on-surface);
    font-weight: var(--font-weight-medium);
  }
  .pickers {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
    min-width: 0;
  }
  .ideas {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    align-items: baseline;
    gap: 2px 8px;
    margin: 0;
    font-size: var(--text-md);
    color: var(--outline);
  }
  .idea {
    font: inherit;
    padding: 0;
    border: none;
    background: none;
    color: var(--on-surface-var);
    cursor: pointer;
  }
  .idea:hover:not(:disabled) {
    color: var(--on-surface);
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .idea:disabled {
    color: var(--outline);
    cursor: default;
  }
  .err {
    color: var(--error);
    margin: 0;
  }
  .starts {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-3);
    margin-top: var(--space-4);
  }
  .start {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 76px;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-card);
    background: var(--surface-container);
    color: var(--on-surface);
    font-weight: var(--font-weight-regular);
    text-decoration: none;
    transition: background-color var(--dur-fast) var(--ease-standard);
  }
  .start:hover {
    background: var(--surface-high);
    text-decoration: none;
  }
  .start :global(.icon) {
    color: var(--primary);
  }
  .start strong {
    display: block;
    font-size: var(--text-lg);
    line-height: 1.25;
  }
  .start small {
    display: block;
    margin-top: 2px;
    font-size: var(--text-sm);
    line-height: 1.3;
    color: var(--on-surface-var);
  }
  .start.main {
    background: var(--primary);
    color: var(--on-primary);
  }
  .start.main:hover {
    background: color-mix(in srgb, var(--primary) 90%, white);
  }
  .start.main :global(.icon),
  .start.main small {
    color: var(--on-primary);
  }

  /* ---------- examples and recent projects: many small tiles ---------- */
  .block {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    scroll-margin-top: var(--space-4);
  }
  .bhead {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }
  h2 {
    font-size: var(--text-lg);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: var(--space-3);
  }
  .tile {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 0;
    width: 100%;
    border: none;
    font: inherit;
    text-align: left;
    color: var(--on-surface);
    text-decoration: none;
    transition: background-color var(--dur-fast) var(--ease-standard);
  }
  .tile:hover:not(:disabled) {
    text-decoration: none;
    background: var(--surface-high);
  }
  .tile:disabled {
    cursor: default;
    opacity: 0.55;
  }
  /* covers have no backdrop of their own: the tile's surface shows through, in either theme */
  .pic {
    position: relative;
    display: block;
    aspect-ratio: 1;
    background: var(--render-bg);
    overflow: hidden;
  }
  .pic img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .kind {
    font-weight: var(--font-weight-regular);
    color: var(--on-surface-var);
  }
  .state {
    position: absolute;
    left: var(--space-2);
    top: var(--space-2);
    background: var(--surface-container);
  }
  .ph {
    display: grid;
    place-items: center;
    width: 100%;
    height: 100%;
    border-radius: 0;
    color: var(--outline);
  }
  .meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--space-2) var(--space-3) var(--space-3);
    min-width: 0;
  }
  .meta strong {
    font-size: var(--text-md);
    font-weight: var(--font-weight-semibold);
    line-height: 1.3;
  }
  .cap {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    font-size: var(--text-xs);
    line-height: 1.35;
    color: var(--on-surface-var);
  }
  .sk .pic {
    background: var(--surface-high);
    border-radius: 0;
  }
  .line {
    display: block;
    height: 12px;
    width: 70%;
    margin: 3px 0;
    border-radius: var(--radius-xs);
  }
  .foot {
    padding-top: var(--space-4);
    border-top: var(--border-width) solid var(--divider);
    font-size: var(--text-sm);
    color: var(--outline);
  }
  @media (max-width: 720px) {
    .home {
      padding: 0 var(--space-4) var(--space-7);
      gap: var(--space-7);
    }
    .hero {
      padding-top: 64px; /* clear of the buttons in the corner */
    }
    .starts {
      grid-template-columns: minmax(0, 1fr);
    }
    .grid {
      grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    }
    .modes button {
      min-height: 40px;
    }
  }
</style>
