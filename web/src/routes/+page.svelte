<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import CaptureTips from '$lib/components/CaptureTips.svelte';
  import { api, errorText } from '$lib/api';
  import { t, ago, projectTitle } from '$lib/i18n.svelte';
  import type { ProjectOut } from '$lib/types';

  const PACKS = [
    { id: 'copy', icon: 'camera', photo: true },
    { id: 'household', icon: 'hammer' },
    { id: 'adapter', icon: 'adapter' },
    { id: 'forms', icon: 'vase' },
    { id: 'terrain', icon: 'mountain' },
    { id: 'architecture', icon: 'landmark' },
    { id: 'mechanisms', icon: 'gear' },
    { id: 'stylize', icon: 'figure' },
  ];

  let text = $state('');
  let pack = $state<string | null>(null);
  let files = $state<{ file: File; url: string | null }[]>([]);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let dragging = $state(false);
  let mine = $state<ProjectOut[] | null>(null);
  let gallery = $state<ProjectOut[] | null>(null);
  let input: HTMLTextAreaElement;
  let photoInput: HTMLInputElement;

  onMount(() => {
    api.projects().then((p) => (mine = p)).catch(() => (mine = []));
    api.gallery().then((g) => (gallery = g)).catch(() => (gallery = []));
    return () => files.forEach((f) => f.url && URL.revokeObjectURL(f.url));
  });

  let watching = $state<string | null>(null);
  async function watch(id: string) {
    watching = id;
    try {
      const p = await api.replay(id, 4);
      goto(`/p/${p.id}`);
    } catch (e) {
      error = errorText(e);
      watching = null;
    }
  }

  function choose(p: (typeof PACKS)[number]) {
    pack = p.id;
    text = t(`tmpl.${p.id}`);
    input?.focus();
    input?.setSelectionRange(text.length, text.length);
    if (p.photo && !files.length) photoInput?.click();
  }

  function addFiles(list: FileList | null | undefined) {
    if (!list) return;
    const add = Array.from(list).map((file) => ({ file, url: file.type.startsWith('image/') ? URL.createObjectURL(file) : null }));
    files = [...files, ...add].slice(0, 12);
  }

  function kindOf(f: File) {
    if (f.type.startsWith('video/')) return 'video';
    if (f.type.startsWith('audio/')) return 'audio';
    return 'photo';
  }

  async function start() {
    if ((!text.trim() && !files.length) || busy) return;
    busy = true;
    error = null;
    try {
      const p = await api.createProject(undefined, pack ?? undefined);
      const ids: string[] = [];
      for (const f of files) ids.push((await api.upload(p.id, f.file, kindOf(f.file))).id);
      await api.send(p.id, text.trim() || t('tmpl.copy'), ids);
      goto(`/p/${p.id}`);
    } catch (e) {
      error = errorText(e);
      busy = false;
    }
  }
</script>

<svelte:head><title>Formwright</title></svelte:head>

<Header />

<main class="home">
  <section class="hero">
    <h1>{t('tagline')}</h1>
    <p class="sub">{t('subtag')}</p>

    <div
      class="create card"
      class:dragging
      role="group"
      aria-label={t('start')}
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
      <textarea
        bind:this={input}
        bind:value={text}
        rows="3"
        placeholder={t('prompt_placeholder')}
        aria-label={t('prompt_placeholder')}
        onkeydown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) start();
        }}
      ></textarea>
      {#if files.length}
        <div class="files">
          {#each files as f, i (f.file.name + i)}
            <div class="file">
              {#if f.url}<img src={f.url} alt={f.file.name} />{:else}<span class="ficon"><Icon name={f.file.type.startsWith('video') ? 'video' : 'mic'} size={18} /></span>{/if}
              <button class="x" aria-label="{t('remove')} {f.file.name}" onclick={() => (files = files.filter((_, j) => j !== i))}><Icon name="x" size={11} stroke={2.4} /></button>
            </div>
          {/each}
        </div>
      {/if}
      <div class="bar">
        <label class="btn small">
          <Icon name="image" size={15} /> {t('attach_photos')}
          <input bind:this={photoInput} class="sr-only" type="file" accept="image/*,video/*,audio/*" multiple onchange={(e) => addFiles((e.currentTarget as HTMLInputElement).files)} />
        </label>
        <label class="btn small camera">
          <Icon name="camera" size={15} /> {t('take_photo')}
          <input class="sr-only" type="file" accept="image/*" capture="environment" onchange={(e) => addFiles((e.currentTarget as HTMLInputElement).files)} />
        </label>
        <span class="spacer"></span>
        <span class="kb xs muted"><span class="kbd">Ctrl</span> + <span class="kbd">Enter</span></span>
        <button class="btn primary" onclick={start} disabled={busy || (!text.trim() && !files.length)}>
          {#if busy}<span class="spin"></span> {t('starting')}{:else}{t('start')} <Icon name="chevron" size={16} />{/if}
        </button>
      </div>
      {#if error}<p class="err small" role="alert">{error}</p>{/if}
    </div>
  </section>

  <section class="block">
    <h2 class="section-title">{t('starters')}</h2>
    <div class="starters">
      {#each PACKS as p (p.id)}
        <button class="starter card" class:on={pack === p.id} onclick={() => choose(p)}>
          <span class="si"><Icon name={p.icon} size={20} /></span>
          <span class="st">{t(`pack.${p.id}`)}</span>
          <span class="sd xs muted">{t(`ex.${p.id}`)}</span>
        </button>
      {/each}
    </div>
  </section>

  <section class="block how">
    <h2 class="section-title">{t('how_title')}</h2>
    <ol class="steps">
      {#each [1, 2, 3] as n (n)}
        <li class="card">
          <span class="num">{n}</span>
          <strong>{t(`how_${n}_t`)}</strong>
          <p class="small muted">{t(`how_${n}_d`)}</p>
        </li>
      {/each}
    </ol>
    <div class="trick card">
      <div>
        <strong>{t('trick_t')}</strong>
        <p class="small muted">{t('trick_d')}</p>
      </div>
      <CaptureTips />
    </div>
  </section>

  {#if mine === null || mine.length}
    <section class="block">
      <h2 class="section-title">{t('my_projects')}</h2>
      <div class="grid">
        {#if mine === null}
          {#each [1, 2, 3] as i (i)}<div class="skeleton tileskel"></div>{/each}
        {:else}
          {#each mine as p (p.id)}
            <a class="proj card" href="/p/{p.id}">
              <div class="cover">
                {#if p.cover}<img src={p.cover} alt="" loading="lazy" />{:else}<Icon name="cube" size={28} />{/if}
                {#if p.public}<span class="chip ok pub"><Icon name="globe" size={11} /> {t('published')}</span>{/if}
              </div>
              <div class="meta">
                <strong class="pt">{projectTitle(p.title)}</strong>
                <span class="xs muted">{p.status === 'working' ? t('agent_working') : ago(p.updated_at)}{p.version ? ` · v${p.version}` : ''}</span>
              </div>
            </a>
          {/each}
        {/if}
      </div>
    </section>
  {/if}

  <section class="block">
    <h2 class="section-title">{t('gallery')}</h2>
    {#if gallery && !gallery.length}
      <p class="muted small">{t('empty_gallery')}</p>
    {:else}
      <div class="grid">
        {#each gallery ?? [] as p (p.id)}
          <div class="proj card">
            <a class="plink" href="/r/{p.id}">
              <div class="cover">{#if p.cover}<img src={p.cover} alt="" loading="lazy" />{:else}<Icon name="cube" size={28} />{/if}</div>
              <div class="meta"><strong class="pt">{projectTitle(p.title)}</strong><span class="xs muted">{ago(p.updated_at)}</span></div>
            </a>
            <button class="btn small ghost watch" onclick={() => watch(p.id)} disabled={watching === p.id}>
              {#if watching === p.id}<span class="spin"></span>{:else}<Icon name="play" size={13} />{/if} {t('watch')}
            </button>
          </div>
        {/each}
      </div>
    {/if}
  </section>
</main>

<style>
  .home {
    max-width: 1080px;
    margin: 0 auto;
    padding: 28px 16px 64px;
    display: flex;
    flex-direction: column;
    gap: 36px;
  }
  .hero {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  h1 {
    font-size: clamp(28px, 5vw, var(--fs-2xl));
    letter-spacing: -0.03em;
    max-width: 760px;
  }
  .sub {
    margin: 0 0 8px;
    color: var(--text-2);
    max-width: 640px;
    font-size: var(--fs-md);
  }
  .create {
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    box-shadow: var(--shadow);
  }
  .create.dragging {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .create textarea {
    border: none;
    background: transparent;
    resize: none;
    font-size: 17px;
    padding: 6px;
    min-height: 84px;
  }
  .create textarea:focus-visible {
    outline: none;
  }
  .files {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .file {
    position: relative;
    width: 64px;
    height: 64px;
    border-radius: 10px;
    border: 1px solid var(--line);
    overflow: visible;
  }
  .file img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: 10px;
  }
  .ficon {
    display: grid;
    place-items: center;
    width: 100%;
    height: 100%;
    color: var(--muted);
  }
  .x {
    position: absolute;
    top: -6px;
    right: -6px;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: 1px solid var(--line);
    background: var(--panel);
    display: grid;
    place-items: center;
    padding: 0;
  }
  .bar {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .err {
    color: var(--err);
    margin: 0;
  }
  .block {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .starters {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 10px;
  }
  .starter {
    display: grid;
    grid-template-columns: 36px minmax(0, 1fr);
    grid-template-rows: auto auto;
    column-gap: 10px;
    align-items: center;
    text-align: left;
    padding: 12px;
    cursor: pointer;
    transition:
      border-color 0.12s,
      transform 0.06s;
  }
  .starter:hover {
    border-color: var(--line-strong);
  }
  .starter.on {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .si {
    grid-row: span 2;
    width: 36px;
    height: 36px;
    border-radius: 10px;
    background: var(--accent-soft);
    color: var(--accent);
    display: grid;
    place-items: center;
  }
  .st {
    font-weight: 600;
    font-size: var(--fs-sm);
  }
  .steps {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }
  .steps li {
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .steps p {
    margin: 0;
  }
  .num {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: var(--text);
    color: var(--bg);
    display: grid;
    place-items: center;
    font-weight: 700;
    font-size: 13px;
  }
  .trick {
    display: grid;
    grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr);
    gap: 16px;
    padding: 14px;
    align-items: center;
  }
  .trick p {
    margin: 6px 0 0;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 10px;
  }
  .proj {
    text-decoration: none;
    color: var(--text);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    transition: border-color 0.12s;
  }
  .proj:hover {
    border-color: var(--line-strong);
  }
  .plink {
    color: inherit;
    text-decoration: none;
    display: flex;
    flex-direction: column;
  }
  .watch {
    margin: 0 8px 8px;
    justify-content: flex-start;
  }
  .pub {
    position: absolute;
    top: 6px;
    left: 6px;
    gap: 3px;
  }
  .cover {
    position: relative;
    aspect-ratio: 4 / 3;
    background: var(--panel-2);
    display: grid;
    place-items: center;
    color: var(--muted);
  }
  .cover img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .meta {
    padding: 8px 10px 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .pt {
    font-size: var(--fs-sm);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tileskel {
    aspect-ratio: 4 / 3;
  }
  @media (max-width: 760px) {
    .steps,
    .trick {
      grid-template-columns: minmax(0, 1fr);
    }
    .kb {
      display: none;
    }
  }
  @media (max-width: 520px) {
    .starters,
    .grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .starter {
      grid-template-columns: minmax(0, 1fr);
      row-gap: 6px;
      align-items: start;
      padding: 10px;
    }
    .si {
      grid-row: auto;
      width: 32px;
      height: 32px;
    }
  }
  @media (hover: none) {
    .camera {
      order: -1;
    }
  }
</style>
