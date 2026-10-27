<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import Header from '$lib/components/Header.svelte';
  import { api, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { ProjectOut } from '$lib/types';

  const PACKS = [
    { id: 'household', icon: '🔩' },
    { id: 'copy', icon: '📷' },
    { id: 'adapter', icon: '🔀' },
    { id: 'forms', icon: '🏺' },
    { id: 'terrain', icon: '⛰️' },
    { id: 'architecture', icon: '🏛️' },
    { id: 'stylize', icon: '🗿' },
  ];

  let text = $state('');
  let pack = $state<string | null>(null);
  let files = $state<File[]>([]);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let dragging = $state(false);
  let mine = $state<ProjectOut[] | null>(null);
  let gallery = $state<ProjectOut[] | null>(null);
  let input: HTMLTextAreaElement;

  onMount(async () => {
    api.projects().then((p) => (mine = p)).catch(() => (mine = []));
    api.gallery().then((g) => (gallery = g)).catch(() => (gallery = []));
  });

  function choose(id: string) {
    pack = pack === id ? null : id;
    if (pack && !text.trim()) text = t(`tmpl.${id}`);
    input?.focus();
  }

  function addFiles(list: FileList | null | undefined) {
    if (!list) return;
    files = [...files, ...Array.from(list)].slice(0, 12);
  }

  function kindOf(f: File) {
    if (f.type.startsWith('video/')) return 'video';
    if (f.type.startsWith('audio/')) return 'audio';
    return 'photo';
  }

  async function start() {
    if (!text.trim() && !files.length) return;
    busy = true;
    error = null;
    try {
      const title = text.trim().split(/\s+/).slice(0, 6).join(' ') || 'New project';
      const p = await api.createProject(title.slice(0, 60), pack ?? undefined);
      const ids: string[] = [];
      for (const f of files) ids.push((await api.upload(p.id, f, kindOf(f))).id);
      if (text.trim()) await api.send(p.id, text.trim(), ids);
      goto(`/p/${p.id}`);
    } catch (e) {
      error = errorText(e);
      busy = false;
    }
  }

  const ago = (ts: number) => {
    const s = Date.now() / 1000 - ts;
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
    if (s < 86400) return `${Math.round(s / 3600)} h`;
    return `${Math.round(s / 86400)} d`;
  };
</script>

<svelte:head><title>Formwright</title></svelte:head>

<Header />

<main class="home">
  <section class="hero">
    <h1>{t('tagline')}</h1>
    <div
      class="prompt card"
      class:dragging
      role="group"
      aria-label="New project"
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
          {#each files as f, i (f.name + i)}
            <span class="chip">
              {f.name.slice(0, 22)}
              <button class="x" aria-label="remove {f.name}" onclick={() => (files = files.filter((_, j) => j !== i))}>×</button>
            </span>
          {/each}
        </div>
      {/if}
      <div class="bar">
        <label class="btn small">
          📎 {t('photo')}
          <input class="sr-only" type="file" accept="image/*,video/*,audio/*" multiple onchange={(e) => addFiles((e.currentTarget as HTMLInputElement).files)} />
        </label>
        <span class="spacer"></span>
        <button class="btn primary" onclick={start} disabled={busy || (!text.trim() && !files.length)}>{busy ? t('loading') : t('start')} →</button>
      </div>
      {#if error}<div class="err">{error}</div>{/if}
    </div>
    <div class="packs">
      {#each PACKS as p (p.id)}
        <button class="chip pack" class:on={pack === p.id} onclick={() => choose(p.id)}>{p.icon} {t(`pack.${p.id}`)}</button>
      {/each}
    </div>
  </section>

  <section class="lists">
    <div>
      <h2 class="section-title">{t('my_projects')}</h2>
      {#if mine === null}
        <p class="muted">{t('loading')}</p>
      {:else if !mine.length}
        <p class="muted">{t('empty_projects')}</p>
      {:else}
        <div class="grid">
          {#each mine as p (p.id)}
            <a class="tile card" href="/p/{p.id}">
              {#if p.cover}<img src={p.cover} alt="" loading="lazy" />{:else}<div class="ph">◇</div>{/if}
              <div class="meta"><strong>{p.title}</strong><span class="muted">v{p.version} · {ago(p.updated_at)}</span></div>
            </a>
          {/each}
        </div>
      {/if}
    </div>
    <div>
      <h2 class="section-title">{t('gallery')}</h2>
      {#if gallery === null}
        <p class="muted">{t('loading')}</p>
      {:else if !gallery.length}
        <p class="muted">{t('empty_gallery')}</p>
      {:else}
        <div class="grid">
          {#each gallery as p (p.id)}
            <a class="tile card" href="/r/{p.id}">
              {#if p.cover}<img src={p.cover} alt="" loading="lazy" />{:else}<div class="ph">◇</div>{/if}
              <div class="meta"><strong>{p.title}</strong><span class="muted">{p.pack ?? ''}</span></div>
            </a>
          {/each}
        </div>
      {/if}
    </div>
  </section>
</main>

<style>
  .home {
    max-width: 1100px;
    margin: 0 auto;
    padding: 28px 16px 60px;
  }
  .hero h1 {
    font-size: clamp(24px, 4.2vw, 40px);
    letter-spacing: -0.02em;
    margin-bottom: 18px;
    max-width: 760px;
  }
  .prompt {
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .prompt.dragging {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .prompt textarea {
    border: none;
    background: transparent;
    font-size: 17px;
    padding: 4px;
    min-height: 84px;
  }
  .prompt textarea:focus-visible {
    outline: none;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .spacer {
    flex: 1;
  }
  .files {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .x {
    border: none;
    background: none;
    padding: 0 2px;
    color: var(--muted);
  }
  .err {
    color: var(--err);
    font-size: 14px;
  }
  .packs {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
  }
  .pack {
    cursor: pointer;
    font-size: 13.5px;
    padding: 6px 12px;
  }
  .pack.on {
    background: var(--accent-soft);
    border-color: var(--accent);
  }
  .lists {
    margin-top: 36px;
    display: grid;
    gap: 28px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 12px;
    margin-top: 8px;
  }
  .tile {
    display: flex;
    flex-direction: column;
    text-decoration: none;
    color: var(--text);
    overflow: hidden;
  }
  .tile img,
  .ph {
    width: 100%;
    aspect-ratio: 4 / 3;
    object-fit: cover;
    background: var(--panel-2);
  }
  .ph {
    display: grid;
    place-items: center;
    font-size: 30px;
    color: var(--muted);
  }
  .meta {
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 13.5px;
  }
  .meta strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
