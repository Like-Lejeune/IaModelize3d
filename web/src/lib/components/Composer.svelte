<script lang="ts">
  import Icon from './Icon.svelte';
  import Picker from './Picker.svelte';
  import CaptureTips from './CaptureTips.svelte';
  import PhotoSelect from './PhotoSelect.svelte';
  import { t, fmtDuration } from '$lib/i18n.svelte';
  import { prefs, setPref, models, modelName, REASONING } from '$lib/session.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import type { AssetOut } from '$lib/types';

  let { store }: { store: ProjectStore } = $props();
  let text = $state('');
  let uploading = $state(0);
  let menu = $state(false);
  let tips = $state(false);
  let dragging = $state(false);
  let selecting = $state<AssetOut | null>(null);
  let rec: MediaRecorder | null = null;
  let recording = $state(false);
  let recStart = $state(0);
  let now = $state(Date.now());
  let area: HTMLTextAreaElement;
  let menuWrap: HTMLDivElement;

  const hasModel = $derived(!!store.source);
  const ready = $derived((!!text.trim() || !!store.tray.length) && !uploading && !store.replaying);
  const modelOptions = $derived(
    models().map((m) => ({
      value: m.key,
      title: modelName(m.id),
      short: modelName(m.id).replace(/^Muse /, ''),
      hint: t(m.available ? `model_${m.key}_d` : 'model_locked'),
      disabled: !m.available,
    })),
  );
  const reasoningOptions = $derived(REASONING.map((r) => ({ value: r, title: t(`reasoning_${r}`) })));

  // status line: the current run, or the last one once it is over
  const job = $derived(store.currentJob ?? Object.values(store.jobs).sort((a, b) => b.started - a.started)[0] ?? null);
  const elapsed = $derived(job ? (job.finished ?? now / 1000) - job.started : 0);
  const tokens = $derived(job?.cost ? (job.cost.tokens_in ?? 0) + (job.cost.tokens_out ?? 0) : 0);

  $effect(() => {
    if (!store.running && !recording) return;
    const id = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(id);
  });

  // "Edit" on a message or a fill-in suggestion hands its text over
  $effect(() => {
    const d = store.draft;
    if (d == null) return;
    store.draft = null;
    text = d;
    queueMicrotask(() => {
      fit();
      area?.focus();
      area?.setSelectionRange(text.length, text.length);
    });
  });

  const SOURCES = [
    { kind: 'photo', icon: 'image', accept: 'image/*', capture: undefined },
    { kind: 'camera', icon: 'camera', accept: 'image/*', capture: 'environment' },
    { kind: 'caliper', icon: 'ruler', accept: 'image/*', capture: 'environment' },
    { kind: 'sketch', icon: 'pencil', accept: 'image/*', capture: 'environment' },
    { kind: 'video', icon: 'video', accept: 'video/mp4,video/quicktime,video/*', capture: 'environment' },
  ];

  function fit() {
    if (!area) return;
    area.style.height = 'auto';
    area.style.height = `${Math.min(area.scrollHeight, 200)}px`;
    area.style.overflowY = area.scrollHeight > 200 ? 'auto' : 'hidden';
  }

  async function addFiles(kind: string, list: FileList | File[] | null | undefined) {
    menu = false;
    if (!list) return;
    for (const f of Array.from(list)) {
      uploading++;
      const k = kind === 'camera' ? 'photo' : f.type.startsWith('video/') ? 'video' : f.type.startsWith('audio/') ? 'audio' : kind;
      const a = await store.upload(f, k);
      if (a) store.tray = [...store.tray, a];
      uploading--;
    }
  }

  async function toggleRecord() {
    menu = false;
    if (recording && rec) {
      rec.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop());
        recording = false;
        const type = rec?.mimeType || 'audio/webm';
        const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
        uploading++;
        const a = await store.upload(new Blob(chunks, { type }), 'audio', `voice.${ext}`);
        if (a) store.tray = [...store.tray, a];
        uploading--;
      };
      rec.start();
      recording = true;
      recStart = Date.now();
      now = recStart;
    } catch (e: any) {
      store.addError(e?.message ?? String(e));
    }
  }

  async function send() {
    if (!ready || store.running) return;
    const v = text.trim();
    const ids = store.tray.map((a) => a.id);
    text = '';
    store.tray = [];
    queueMicrotask(fit);
    await store.send(v || '(see attached)', ids);
  }

  function fmtTokens(n: number) {
    return n >= 1000 ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k` : String(n);
  }

  const isImage = (a: AssetOut) => ['photo', 'sketch', 'caliper', 'print', 'concept'].includes(a.kind);
  const selCount = (a: AssetOut) => store.selections.filter((s) => s.asset_id === a.id).length;
</script>

<svelte:window onclick={(e) => menu && !menuWrap?.contains(e.target as Node) && (menu = false)} />

<div class="composer">
  {#if store.replaying}
    <div class="replay small"><Icon name="play" size={14} /> {t('replay_banner')}</div>
  {/if}
  {#if tips}
    <div class="tipbox card"><CaptureTips compact /><button class="btn small ghost close" onclick={() => (tips = false)} aria-label={t('close')}><Icon name="x" size={14} /></button></div>
  {/if}
  {#if job}
    <div class="meta">
      <span>{fmtDuration(elapsed)}</span>
      {#if tokens}<span>{fmtTokens(tokens)} {t('tokens')}</span>{/if}
    </div>
  {/if}

  <div
    class="box"
    class:dragging
    role="group"
    aria-label={t(hasModel ? 'message_placeholder' : 'message_placeholder_new')}
    ondragover={(e) => {
      e.preventDefault();
      dragging = true;
    }}
    ondragleave={() => (dragging = false)}
    ondrop={(e) => {
      e.preventDefault();
      dragging = false;
      addFiles('photo', e.dataTransfer?.files);
    }}
  >
    {#if store.tray.length || uploading || recording}
      <div class="tray" aria-label={t('attached')}>
        {#each store.tray as a (a.id)}
          <div class="att">
            {#if isImage(a)}
              <button class="thumb" onclick={() => (selecting = a)} title={t('select_object')}>
                <img src={a.thumb_url ?? a.url} alt={a.kind} />
                {#if a.meta?.calibration}<span class="cal" title={t('calibrated')}><Icon name="ruler" size={11} stroke={2.2} /></span>{/if}
                {#if selCount(a)}<span class="sel">{selCount(a)}</span>{/if}
              </button>
            {:else}
              <span class="file"><Icon name={a.kind === 'audio' ? 'mic' : 'video'} size={16} /></span>
            {/if}
            <button class="x" onclick={() => (store.tray = store.tray.filter((x) => x.id !== a.id))} aria-label={t('remove')}><Icon name="x" size={11} stroke={2.4} /></button>
          </div>
        {/each}
        {#if uploading}<div class="att busy"><span class="spin"></span></div>{/if}
        {#if recording}
          <button class="btn small rec" onclick={toggleRecord}><Icon name="stop" size={12} /> {t('recording', { s: Math.round((now - recStart) / 1000) })}</button>
        {/if}
      </div>
    {/if}

    <textarea
      bind:this={area}
      bind:value={text}
      rows="1"
      placeholder={t(hasModel ? 'message_placeholder' : 'message_placeholder_new')}
      aria-label={t(hasModel ? 'message_placeholder' : 'message_placeholder_new')}
      disabled={store.replaying}
      oninput={fit}
      onpaste={(e) => {
        const imgs = Array.from(e.clipboardData?.files ?? []).filter((f) => f.type.startsWith('image/'));
        if (imgs.length) addFiles('photo', imgs);
      }}
      onkeydown={(e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
          e.preventDefault();
          send();
        }
      }}
    ></textarea>

    <div class="row">
      <div class="addwrap" bind:this={menuWrap}>
        <button class="round" onclick={() => (menu = !menu)} aria-expanded={menu} aria-label={t('add')} title={t('add')}><Icon name="plus" size={19} stroke={2} /></button>
        {#if menu}
          <div class="menu card" role="group" aria-label={t('add')}>
            {#each SOURCES as s (s.kind)}
              <label class="mi">
                <Icon name={s.icon} size={16} /> {t(s.kind)}
                <input class="sr-only" type="file" accept={s.accept} capture={s.capture as any} multiple={s.kind !== 'video'} onchange={(e) => addFiles(s.kind, (e.currentTarget as HTMLInputElement).files)} />
              </label>
            {/each}
            <button class="mi tipsbtn" onclick={() => ((tips = true), (menu = false))}><Icon name="help" size={16} /> {t('tips')}</button>
          </div>
        {/if}
      </div>
      <button class="round" class:on={recording} onclick={toggleRecord} aria-label={t('record')} title={t('record')}><Icon name="mic" size={17} /></button>
      <span class="spacer"></span>
      {#if store.running && !store.replaying}
        <button class="round send stop" onclick={() => store.cancel()} aria-label={t('stop')} title={t('stop')}><Icon name="stop" size={13} stroke={2.6} /></button>
      {:else}
        <button class="round send" onclick={send} disabled={!ready} aria-label={t('send')} title={t('send')}><Icon name="arrow-up" size={18} stroke={2.2} /></button>
      {/if}
    </div>
  </div>

  <div class="meta pickers">
    <Picker label={t('model')} value={prefs.model} options={modelOptions} up onpick={(v) => setPref('model', v)} />
    <Picker label={t('reasoning')} value={prefs.reasoning} options={reasoningOptions} quiet up onpick={(v) => setPref('reasoning', v)} />
  </div>
</div>

{#if selecting}
  <PhotoSelect projectId={store.id} asset={selecting} selections={store.selections} onClose={() => (selecting = null)} />
{/if}

<style>
  .composer {
    padding: 8px 12px 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    position: relative;
  }
  .box {
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 14px;
    transition: border-color 0.12s;
  }
  .box:focus-within {
    border-color: var(--line-strong);
  }
  .box.dragging {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  textarea {
    display: block;
    width: 100%;
    border: none;
    background: transparent;
    resize: none;
    font-size: var(--fs-md);
    line-height: 22px;
    padding: 10px 12px 2px;
    /* two lines from the start: the placeholder fits and the first typed line does not shrink the box */
    min-height: 56px;
    max-height: 200px;
    overflow-y: hidden;
  }
  textarea:focus-visible {
    outline: none;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 4px 6px 6px;
    min-width: 0;
  }
  .round {
    flex: none;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    padding: 0;
    background: transparent;
    border: none;
    color: var(--muted);
    cursor: pointer;
    transition:
      background 0.12s,
      color 0.12s;
  }
  .round:hover:not(:disabled) {
    background: var(--panel-3);
    color: var(--text);
  }
  .round.on {
    color: var(--err);
  }
  .send {
    color: var(--text);
    margin-left: 2px;
  }
  .send:disabled {
    cursor: default;
    opacity: 0.4;
  }
  .send.stop {
    background: var(--text);
    color: var(--panel);
  }
  .send.stop:hover {
    background: var(--text-2);
    color: var(--panel);
  }
  .tray {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
    padding: 10px 10px 0;
  }
  .att {
    position: relative;
    width: 52px;
    height: 52px;
  }
  .thumb,
  .file,
  .att.busy {
    width: 52px;
    height: 52px;
    border-radius: 10px;
    border: 1px solid var(--line);
    overflow: hidden;
    padding: 0;
    background: var(--panel);
    display: grid;
    place-items: center;
    position: relative;
  }
  .thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .cal,
  .sel {
    position: absolute;
    bottom: 3px;
    border-radius: 999px;
    font-size: 10px;
    padding: 1px 5px;
    display: inline-flex;
    align-items: center;
  }
  .cal {
    left: 3px;
    background: var(--ok);
    color: #fff;
  }
  .sel {
    right: 3px;
    background: var(--accent);
    color: var(--accent-ink);
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
  .rec {
    color: var(--err);
    border-color: var(--err);
  }
  .tipbox {
    padding: 10px 34px 10px 10px;
    position: relative;
  }
  .close {
    position: absolute;
    top: 4px;
    right: 4px;
  }
  .replay {
    display: flex;
    gap: 8px;
    align-items: center;
    background: var(--info-soft);
    color: var(--info);
    border-radius: 10px;
    padding: 8px 10px;
  }
  .addwrap {
    position: relative;
  }
  .menu {
    position: absolute;
    bottom: 40px;
    left: 0;
    z-index: 30;
    min-width: 200px;
    padding: 6px;
    display: flex;
    flex-direction: column;
    box-shadow: var(--shadow-lg);
  }
  .mi {
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 8px 10px;
    border-radius: 8px;
    border: none;
    background: none;
    cursor: pointer;
    font-size: var(--fs-sm);
    text-align: left;
    color: var(--text);
  }
  .mi:hover,
  .mi:focus-within {
    background: var(--panel-3);
  }
  .tipsbtn {
    border-top: 1px solid var(--line);
    border-radius: 0 0 8px 8px;
    margin-top: 4px;
  }
  /* text lines up with the textarea's 12px inset, clear of the box's 14px corners */
  .meta {
    display: flex;
    gap: 10px;
    padding: 0 12px;
    font-size: 11.5px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .pickers {
    justify-content: flex-end;
    gap: 0;
    /* plus each picker's own 6px padding = the same 12px inset */
    padding: 0 6px;
  }
  .pickers :global(.cur) {
    font-size: 11.5px;
    padding: 1px 6px;
    color: var(--muted);
  }
  .pickers :global(.cur:hover),
  .pickers :global(.cur[aria-expanded='true']) {
    color: var(--text);
  }
</style>
