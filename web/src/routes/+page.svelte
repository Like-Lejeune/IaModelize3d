<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Picker from '$lib/components/Picker.svelte';
  import FeaturedRuns from '$lib/components/FeaturedRuns.svelte';
  import { api, errorText } from '$lib/api';
  import { stashFirst } from '$lib/pending';
  import { ago, i18n, projectTitle, t } from '$lib/i18n.svelte';
  import { isOpenWeights } from '$lib/models';
  import { prefs, setPref, models, modelName, session, REASONING } from '$lib/session.svelte';
  import type { ExampleOut, ProjectOut } from '$lib/types';
  import { dt } from '$lib/device/i18n';

  const ROW = 4; // one row of tiles on a wide screen, two on a phone
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
  // the examples of what the prompt above makes: finished devices, or printed parts
  const shownExamples = $derived(examples?.filter((ex) => (ex.pack === 'device') === (mode === 'device')) ?? null);
  let opening = $state<string | null>(null);
  let exampleError = $state<string | null>(null);
  let mine = $state<ProjectOut[] | null>(null);
  let showAll = $state(false);

  // projects with a model, or getting one; drafts that never got a model stay out
  const recent = $derived((mine ?? []).filter((p) => p.cover || p.status === 'working'));
  const shownRecent = $derived(showAll ? recent : recent.slice(0, ROW));
  const working = $derived(recent.some((p) => p.status === 'working'));

  async function loadMine() {
    try {
      mine = await api.projects();
    } catch {
      mine ??= [];
    }
  }

  onMount(() => {
    if (matchMedia('(hover: hover)').matches) input?.focus();
    api.examples().then((e) => (examples = e)).catch(() => (examples = []));
    loadMine();
    // a model in progress gets its cover when it is done
    const poll = setInterval(() => working && document.visibilityState === 'visible' && loadMine(), 5000);
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

  function addFiles(list: FileList | File[] | null | undefined) {
    if (!list) return;
    const add = Array.from(list).map((file) => ({ file, url: file.type.startsWith('image/') ? URL.createObjectURL(file) : null }));
    files = [...files, ...add].slice(0, 12);
  }

  function fit() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
    input.style.overflowY = input.scrollHeight > 220 ? 'auto' : 'hidden';
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

<svelte:head><title>Formwright</title></svelte:head>

<div class="page">
  <Header />
  <main class="home">
    <section class="hero" aria-labelledby="home-title">
      <div class="modes seg" role="tablist" aria-label={dt('home_mode')}>
        <button role="tab" aria-selected={mode === 'device'} onclick={() => (mode = 'device')}><Icon name="topology" size={15} /> {dt('home_device')}</button>
        <button role="tab" aria-selected={mode === 'part'} onclick={() => (mode = 'part')}><Icon name="cube" size={15} /> {dt('home_part')}</button>
      </div>
      <h1 id="home-title">{mode === 'device' ? dt('home_title') : t('tagline')}</h1>
      <p class="sub">{mode === 'device' ? dt('home_sub') : t('tagline_sub')}</p>
      <p class="powered xs">
        <span class="muted">{t('powered_by')}</span>
        {#each metaModels as m, i (m)}{#if i}<span class="muted" aria-hidden="true">·</span>{/if}<span class="mname">{m}</span>{/each}
      </p>
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

        <div class="row">
          <label class="round add pressable" title={t('attach_photos')}>
            <Icon name="plus" size={20} />
            <input class="sr-only" type="file" accept="image/*,video/*,audio/*" multiple aria-label={t('attach_photos')} onchange={(e) => addFiles((e.currentTarget as HTMLInputElement).files)} />
          </label>
          <textarea
            bind:this={input}
            bind:value={text}
            rows="1"
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
          <button class="round send pressable" onclick={start} disabled={!ready} aria-label={t('send')} title={t('send')}>
            {#if busy}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="arrow-up" size={18} />{/if}
          </button>
        </div>
      </div>

      {#if mode === 'device'}
        <div class="ideas-row">
          {#each DEVICE_IDEAS as k (k)}
            <button class="chip pressable" onclick={() => ((text = dt(k)), input?.focus(), fit())}>{dt(`${k}_short`)}</button>
          {/each}
        </div>
      {/if}
      <div class="strip">
{#if mode === 'part'}
                  <button class="ideas pressable" onclick={ideasFirst} disabled={busy || !text.trim() || !!files.length} title={t('ideas_first_d')}>
          <Icon name="sparkles" size={14} /> {t('ideas_first')}
        </button>
        {/if}
        <Picker label={t('model')} value={prefs.model} options={modelOptions} onpick={(v) => setPref('model', v)} />
        <Picker label={t('reasoning')} value={prefs.reasoning} options={reasoningOptions} quiet onpick={(v) => setPref('reasoning', v)} />
      </div>
      {#if error}<p class="err small" role="alert">{error}</p>{/if}
      <div class="collect">
        <a class="snapcta pressable" href="/parts/new">
          <span class="snapic"><Icon name="package" size={20} /></span>
          <span class="snaptx"><strong>{t('parts_cta')}</strong><span class="muted xs">{t('parts_cta_hint')}</span></span>
        </a>
        <a class="snapcta pressable" href="/snap">
          <span class="snapic"><Icon name="camera" size={20} /></span>
          <span class="snaptx"><strong>{t('snap_title')}</strong><span class="muted xs">{t('snap_cta_hint')}</span></span>
        </a>
        <a class="btn ghost small" href="/collection"><Icon name="grid" size={15} /> {t('collection')}</a>
      </div>
    </section>

    <FeaturedRuns />

    {#if shownExamples === null || shownExamples.length}
      <section class="block" aria-labelledby="examples-title">
        <div class="bhead">
          <div>
            <h2 id="examples-title">{t('examples')}</h2>
            <p class="muted small">{mode === 'device' ? dt('examples_hint') : t('examples_hint')}</p>
          </div>
        </div>
        <div class="grid three">
          {#if shownExamples === null}
            {#each [0, 1, 2, 3, 4, 5] as i (i)}
              <div class="card tile sk" aria-hidden="true">
                <span class="pic skeleton"></span>
                <span class="meta"><span class="line skeleton"></span><span class="line short skeleton"></span></span>
              </div>
            {/each}
          {:else}
            {#each shownExamples as ex (ex.key)}
              <button class="card tile" onclick={() => openExample(ex)} disabled={!!opening && opening !== ex.key} aria-busy={opening === ex.key}>
                <span class="pic">
                  <img src={ex.cover} alt="" loading="lazy" />
                  {#if ex.pack === 'pcb' || ex.pack === 'device'}<span class="kind" aria-hidden="true"><Icon name="cpu" size={15} /></span>
                  {:else if ex.kind === 'part' || SPARE_PARTS.has(ex.key)}<span class="kind spare"><Icon name="package" size={14} />{t('example_spare')}</span>{/if}
                  <span class="go" aria-hidden="true">
                    {#if opening === ex.key}<i class="ti ti-loader-2 spin"></i>{:else}<Icon name="arrow-right" size={16} />{/if}
                  </span>
                </span>
                <span class="meta">
                  <strong class="wraps">{ex.title[i18n.lang] ?? ex.title.en}</strong>
                  <span class="muted xs cap">{ex.caption[i18n.lang] ?? ex.caption.en}</span>
                </span>
              </button>
            {/each}
          {/if}
        </div>
        {#if exampleError}<p class="err small" role="alert">{exampleError}</p>{/if}
      </section>
    {/if}

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
                {#if p.cover}<img src={p.cover} alt="" loading="lazy" />{:else}<span class="ph skeleton"><Icon name="cube" size={28} /></span>{/if}
                {#if p.status === 'working'}
                  <span class="chip accent state"><i class="ti ti-loader-2 spin" aria-hidden="true"></i>{t('recent_working')}</span>
                {/if}
              </span>
              <span class="meta">
                <strong>{projectTitle(p.title)}</strong>
                <span class="muted xs">{ago(p.updated_at)}</span>
              </span>
            </a>
          {/each}
        </div>
      </section>
    {/if}
  </main>
</div>

<style>
  .page {
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
  }
  .home {
    width: 100%;
    max-width: calc(880px + 2 * var(--space-4));
    margin: 0 auto;
    padding: clamp(var(--space-6), 9vh, 88px) var(--space-4) var(--space-8);
    display: flex;
    flex-direction: column;
    gap: var(--space-8);
  }
  .modes {
    display: inline-flex;
    gap: 2px;
    padding: 3px;
    margin: 0 auto var(--space-3);
    border-radius: 10px;
    border: 1px solid var(--outline-variant);
    background: var(--surface-container-low);
  }
  .modes button {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    font: inherit;
    font-size: 13px;
    padding: 6px 14px;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: var(--on-surface-var);
    cursor: pointer;
  }
  .modes button[aria-selected='true'] {
    background: var(--primary-container);
    color: var(--on-primary-container);
  }
  .ideas-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: center;
    margin-top: var(--space-2);
  }
  .ideas-row .chip {
    font: inherit;
    font-size: 12.5px;
    padding: 5px 11px;
    border-radius: 999px;
    border: 1px solid var(--outline-variant);
    background: var(--surface-container-low);
    color: var(--on-surface);
    cursor: pointer;
  }
  .ideas-row .chip:hover {
    border-color: var(--primary);
  }
  .hero {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  h1 {
    text-align: center;
    font-size: var(--text-product-h1);
    font-weight: var(--font-weight-bold);
    text-wrap: balance;
  }
  /* what happens to the part after the tagline: checked, then printed by the farm */
  .sub {
    margin: 0 0 var(--space-4);
    text-align: center;
    text-wrap: balance;
    font-size: var(--text-product-lead);
    color: var(--on-surface-var);
  }
  .create {
    background: var(--surface-container);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-card);
    transition:
      border-color var(--dur-fast) var(--ease-standard),
      box-shadow var(--dur-fast) var(--ease-standard);
  }
  .create:hover {
    border-color: var(--outline);
  }
  .create:focus-within {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 22%, transparent);
  }
  .create.dragging {
    border-color: var(--primary);
    background: color-mix(in srgb, var(--primary) 9%, var(--surface-container));
  }
  .files {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
    padding: var(--space-3) var(--space-3) 0;
  }
  .file {
    position: relative;
    width: 56px;
    height: 56px;
    border-radius: var(--radius-btn);
    border: var(--border-width) solid var(--outline-variant);
    background: var(--surface-high);
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
    border-color: var(--outline);
  }
  .row {
    display: flex;
    align-items: flex-end;
    gap: var(--space-2);
    padding: var(--space-2);
  }
  textarea,
  textarea:hover,
  textarea:focus {
    flex: 1;
    min-width: 0;
    border: none;
    background: transparent;
    box-shadow: none;
    resize: none;
    font-size: 16px;
    line-height: 24px;
    padding: 9px 6px;
    max-height: 220px;
    overflow-y: hidden;
  }
  textarea::placeholder {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  textarea:focus-visible {
    outline: none;
  }
  .round {
    flex: none;
    width: 42px;
    height: 42px;
    border-radius: var(--radius-btn);
    display: grid;
    place-items: center;
    padding: 0;
    background: transparent;
    border: var(--border-width) solid var(--outline-variant);
    color: var(--on-surface-var);
    cursor: pointer;
    transition:
      background-color var(--dur-fast) var(--ease-standard),
      color var(--dur-fast) var(--ease-standard);
  }
  .add:hover,
  .add:focus-within {
    background: var(--surface-high);
    color: var(--on-surface);
  }
  .send {
    background: var(--primary);
    border-color: transparent;
    color: var(--on-primary);
  }
  .send:not(:disabled):hover {
    background: color-mix(in srgb, var(--primary) 92%, white);
  }
  .send:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
  .powered {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 2px 6px;
    margin: calc(-1 * var(--space-2)) 0 var(--space-3);
    text-align: center;
  }
  .mname {
    font-weight: var(--font-weight-semibold);
    color: var(--on-surface-var);
    white-space: nowrap;
  }
  .strip {
    display: flex;
    justify-content: flex-end;
    gap: 2px;
    padding: 0 10px;
  }
  /* the same quiet text button as the pickers next to it, with a mark for what it starts */
  .ideas {
    margin-right: auto;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    border: none;
    background: none;
    padding: 4px 8px;
    border-radius: var(--radius-btn);
    font-family: inherit;
    font-size: var(--text-card-from);
    font-weight: var(--font-weight-semibold);
    color: var(--primary);
    white-space: nowrap;
    cursor: pointer;
  }
  .ideas:not(:disabled):hover {
    background: var(--surface-high);
  }
  .ideas:disabled {
    color: var(--outline);
    cursor: default;
  }
  .err {
    color: var(--error);
    margin: 0;
    padding: 0 var(--space-3);
  }
  .collect {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin-top: var(--space-4);
  }
  .snapcta {
    flex: 0 1 auto;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
    padding: var(--space-2) var(--space-4) var(--space-2) var(--space-2);
    border-radius: var(--radius-card);
    border: var(--border-width) solid var(--outline-variant);
    background: var(--surface-container);
    color: var(--on-surface);
    text-decoration: none;
    transition: border-color var(--dur-fast) var(--ease-standard);
  }
  .snapcta:hover {
    text-decoration: none;
    border-color: var(--primary);
  }
  .snapic {
    flex: none;
    width: 40px;
    height: 40px;
    border-radius: var(--radius-btn);
    display: grid;
    place-items: center;
    background: var(--primary);
    color: var(--on-primary);
  }
  .snaptx {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .snaptx strong {
    font-size: var(--text-product-spec);
  }
  .snaptx .xs,
  .cap {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  /* ---------- examples and recent projects ---------- */
  .block {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .bhead {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--space-3);
    min-height: 34px;
  }
  h2 {
    font-size: var(--text-product-section-title);
  }
  .bhead p {
    margin: 2px 0 0;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--space-4);
  }
  /* the examples: two full rows of three, with bigger covers */
  .grid.three {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .tile {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 0;
    font: inherit;
    text-align: left;
    color: var(--on-surface);
    text-decoration: none;
    transition:
      border-color var(--dur-fast) var(--ease-standard),
      opacity var(--dur-fast) var(--ease-standard),
      transform var(--dur-base) var(--ease-settle);
  }
  .tile:hover:not(:disabled) {
    text-decoration: none;
    border-color: var(--outline);
    transform: translateY(-2px);
  }
  .tile:disabled {
    cursor: default;
    opacity: 0.55;
  }
  /* renders come on this light backdrop; the tile continues it to the edges */
  .pic {
    position: relative;
    display: block;
    aspect-ratio: 1;
    background: #f6f6f3;
    overflow: hidden;
  }
  .pic img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    transform: scale(1.1);
    transition: transform var(--dur-slow) var(--ease-settle);
  }
  .tile:hover:not(:disabled) .pic img {
    transform: scale(1.16);
  }
  .go {
    position: absolute;
    right: var(--space-2);
    bottom: var(--space-2);
    width: 32px;
    height: 32px;
    border-radius: var(--radius-btn);
    display: grid;
    place-items: center;
    background: var(--primary);
    color: var(--on-primary);
    font-size: 16px;
    opacity: 0;
    transform: translateY(4px);
    transition:
      opacity var(--dur-fast) var(--ease-standard),
      transform var(--dur-base) var(--ease-settle);
  }
  .tile:hover:not(:disabled) .go,
  .tile:focus-visible .go,
  .tile[aria-busy='true'] .go {
    opacity: 1;
    transform: none;
  }
  /* the electronics example: a board, not just a print */
  .kind {
    position: absolute;
    left: var(--space-2);
    top: var(--space-2);
    width: 28px;
    height: 28px;
    border-radius: var(--radius-btn);
    display: grid;
    place-items: center;
    background: var(--surface-container);
    color: var(--primary);
    box-shadow: 0 1px 6px rgb(0 0 0 / 0.2);
  }
  /* the replacement part: named, not just marked */
  .kind.spare {
    width: auto;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 0 9px 0 7px;
    font-size: var(--text-card-meta);
    font-weight: var(--font-weight-semibold);
  }
  .state {
    position: absolute;
    left: var(--space-2);
    top: var(--space-2);
    background: var(--surface-container);
    color: var(--primary);
    box-shadow: 0 1px 6px rgb(0 0 0 / 0.25);
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
    padding: var(--space-3);
    min-width: 0;
  }
  .meta strong {
    font-size: var(--text-product-spec);
    font-weight: var(--font-weight-semibold);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* example names are short phrases: better on two lines than cut on a phone */
  .meta strong.wraps {
    white-space: normal;
    text-wrap: balance;
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
    border-radius: 4px;
  }
  .line.short {
    width: 45%;
  }
  @media (max-width: 720px) {
    .home {
      gap: var(--space-7);
    }
    .grid,
    .grid.three {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--space-3);
    }
  }
  /* phones and tablets: a photo is the main way in, so its two starts (a spare part, Snap & collect) come first and wide */
  @media (hover: none) {
    h1,
    .sub,
    .powered {
      order: -2;
    }
    .collect {
      order: -1;
      flex-wrap: wrap;
      justify-content: flex-end;
      margin: 0 0 var(--space-3);
    }
    .snapcta {
      flex: 1 1 100%;
      padding: var(--space-3) var(--space-4) var(--space-3) var(--space-3);
      border-color: var(--primary);
    }
    .snapic {
      width: 48px;
      height: 48px;
    }
  }
  @media (hover: none) and (max-width: 720px) {
    textarea::placeholder {
      white-space: normal;
    }
    /* the example request reads in full instead of ending in an ellipsis (four lines at 390 px) */
    textarea:placeholder-shown {
      min-height: calc(4 * 24px + 18px);
    }
  }
</style>
