<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Picker from '$lib/components/Picker.svelte';
  import { api, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import { prefs, setPref, refreshMe, models, modelName, REASONING } from '$lib/session.svelte';

  let text = $state('');
  let files = $state<{ file: File; url: string | null }[]>([]);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let dragging = $state(false);
  let input: HTMLTextAreaElement;

  const modelOptions = $derived(
    models().map((m) => ({ value: m.key, title: modelName(m.id), hint: t(m.available ? `model_${m.key}_d` : 'model_locked'), disabled: !m.available })),
  );
  const reasoningOptions = $derived(REASONING.map((r) => ({ value: r, title: t(`reasoning_${r}`) })));
  const ready = $derived(!busy && (!!text.trim() || !!files.length));

  onMount(() => {
    refreshMe();
    if (matchMedia('(hover: hover)').matches) input?.focus();
    return () => files.forEach((f) => f.url && URL.revokeObjectURL(f.url));
  });

  function addFiles(list: FileList | File[] | null | undefined) {
    if (!list) return;
    const add = Array.from(list).map((file) => ({ file, url: file.type.startsWith('image/') ? URL.createObjectURL(file) : null }));
    files = [...files, ...add].slice(0, 12);
  }

  function kindOf(f: File) {
    if (f.type.startsWith('video/')) return 'video';
    if (f.type.startsWith('audio/')) return 'audio';
    return 'photo';
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
      const p = await api.createProject();
      const ids: string[] = [];
      for (const f of files) ids.push((await api.upload(p.id, f.file, kindOf(f.file))).id);
      const model = models().find((m) => m.key === prefs.model)?.available ? prefs.model : 'contributor';
      await api.send(p.id, text.trim() || t('tmpl.copy'), ids, { model, reasoning: prefs.reasoning });
      goto(`/p/${p.id}`);
    } catch (e) {
      error = errorText(e);
      busy = false;
    }
  }
</script>

<svelte:head><title>Formwright</title></svelte:head>

<main class="home">
  <section class="hero">
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
              <button class="x" aria-label="{t('remove')} {f.file.name}" onclick={() => (files = files.filter((_, j) => j !== i))}><Icon name="x" size={11} stroke={2.4} /></button>
            </div>
          {/each}
        </div>
      {/if}

      <div class="row">
        <label class="round add" title={t('attach_photos')}>
          <Icon name="plus" size={20} stroke={2} />
          <input class="sr-only" type="file" accept="image/*,video/*,audio/*" multiple aria-label={t('attach_photos')} onchange={(e) => addFiles((e.currentTarget as HTMLInputElement).files)} />
        </label>
        <textarea
          bind:this={input}
          bind:value={text}
          rows="1"
          placeholder={t('prompt_placeholder')}
          aria-label={t('prompt_placeholder')}
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
        <button class="round send" onclick={start} disabled={!ready} aria-label={t('send')} title={t('send')}>
          {#if busy}<span class="spin"></span>{:else}<Icon name="arrow-up" size={18} stroke={2.2} />{/if}
        </button>
      </div>
    </div>

    <div class="strip">
      <Picker label={t('model')} value={prefs.model} options={modelOptions} onpick={(v) => setPref('model', v)} />
      <Picker label={t('reasoning')} value={prefs.reasoning} options={reasoningOptions} quiet onpick={(v) => setPref('reasoning', v)} />
    </div>
    {#if error}<p class="err small" role="alert">{error}</p>{/if}
  </section>
</main>

<style>
  .home {
    min-height: 100dvh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 24px 16px;
  }
  .hero {
    width: 100%;
    max-width: 880px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .create {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 14px;
    transition: border-color 0.12s;
  }
  .create:focus-within {
    border-color: var(--line-strong);
  }
  .create.dragging {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .files {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    padding: 12px 12px 0;
  }
  .file {
    position: relative;
    width: 56px;
    height: 56px;
    border-radius: 10px;
    border: 1px solid var(--line);
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
  .row {
    display: flex;
    align-items: flex-end;
    gap: 4px;
    padding: 6px 8px;
  }
  textarea {
    flex: 1;
    min-width: 0;
    border: none;
    background: transparent;
    resize: none;
    font-size: 16px;
    line-height: 24px;
    padding: 6px 4px;
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
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    padding: 0;
    background: transparent;
    border: none;
    color: var(--text);
    cursor: pointer;
    transition:
      background 0.12s,
      color 0.12s;
  }
  .add:hover,
  .add:focus-within {
    background: var(--panel-3);
    color: var(--text);
  }
  .send {
    color: var(--text);
  }
  .send:not(:disabled):hover {
    background: var(--panel-3);
  }
  .send:disabled {
    cursor: default;
    color: var(--muted);
    opacity: 0.5;
  }
  .strip {
    display: flex;
    justify-content: flex-end;
    gap: 2px;
    padding: 0 10px;
  }
  .err {
    color: var(--err);
    margin: 0;
    padding: 0 18px;
  }
</style>
