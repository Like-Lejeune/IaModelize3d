<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Picker from '$lib/components/Picker.svelte';
  import { api, errorText } from '$lib/api';
  import { stashFirst } from '$lib/pending';
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
      const p = await api.createProject();
      stashFirst(p.id, text.trim() || t('tmpl.copy'), files.map((f) => f.file));
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
        <button class="round send pressable" onclick={start} disabled={!ready} aria-label={t('send')} title={t('send')}>
          {#if busy}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="arrow-up" size={18} />{/if}
        </button>
      </div>
    </div>

    <div class="strip">
      <Picker label={t('model')} value={prefs.model} options={modelOptions} onpick={(v) => setPref('model', v)} />
      <Picker label={t('reasoning')} value={prefs.reasoning} options={reasoningOptions} quiet onpick={(v) => setPref('reasoning', v)} />
    </div>
    {#if error}<p class="err small" role="alert">{error}</p>{/if}
    <div class="collect">
      <a class="snapcta pressable" href="/snap">
        <span class="snapic"><Icon name="camera" size={20} /></span>
        <span class="snaptx"><strong>{t('snap_title')}</strong><span class="muted xs">{t('snap_cta_hint')}</span></span>
      </a>
      <a class="btn ghost small" href="/collection"><Icon name="grid" size={15} /> {t('collection')}</a>
    </div>
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
  .strip {
    display: flex;
    justify-content: flex-end;
    gap: 2px;
    padding: 0 10px;
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
  .snaptx .xs {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
</style>
