<script lang="ts">
  import { onDestroy } from 'svelte';
  import Icon from './Icon.svelte';
  import Picker from './Picker.svelte';
  import CaptureTips from './CaptureTips.svelte';
  import PhotoFocus from './PhotoFocus.svelte';
  import PhotoSelect from './PhotoSelect.svelte';
  import Sticker from './Sticker.svelte';
  import { codeText } from '$lib/api';
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
  let focusing = $state<AssetOut | null>(null);
  let rec: MediaRecorder | null = null;
  let mic: MediaStream | null = null;
  let destroyed = false;
  let recording = $state(false);
  let recStart = $state(0);
  // what Muse Voice Transcribe heard in the last voice note: its length, or why nothing came of it
  // (the code of a limit that stopped it, or null: the speech was not recognized)
  let heard = $state<{ s: number } | { miss: string | null } | null>(null);
  let now = $state(Date.now());
  let area: HTMLTextAreaElement;
  let menuWrap: HTMLDivElement;

  const hasModel = $derived(!!store.source);
  // a Stop is on its way to the server: neither Stop nor Send until the job has really ended
  const stopping = $derived(store.stopping);
  const ready = $derived((!!text.trim() || !!store.tray.length) && !uploading && !store.replaying && !stopping);
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
      if (a) {
        store.tray = [...store.tray, a];
        store.spot(a, text.trim());
      }
      uploading--;
    }
  }

  // the transcript goes into the text box, so the person sees what was heard and can fix it before sending
  function addTranscript(a: AssetOut) {
    const said = String(a.meta?.transcript ?? '').trim();
    if (!said || a.meta?.transcript_error) {
      heard = { miss: a.meta?.transcript_code ? String(a.meta.transcript_code) : null };
      return;
    }
    text = text.trim() ? `${text.trimEnd()} ${said}` : said;
    heard = { s: Math.max(1, Math.round(Number(a.meta?.duration_s) || 0)) };
    queueMicrotask(() => {
      fit();
      area?.focus();
      area?.setSelectionRange(text.length, text.length);
    });
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
      mic = stream;
      rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop());
        mic = null;
        recording = false;
        if (destroyed) return;
        const type = rec?.mimeType || 'audio/webm';
        const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
        uploading++;
        const a = await store.upload(new Blob(chunks, { type }), 'audio', `voice.${ext}`);
        if (a) {
          store.tray = [...store.tray, a];
          if (!destroyed) addTranscript(a);
        }
        uploading--;
      };
      rec.start();
      recording = true;
      recStart = Date.now();
      now = recStart;
    } catch (e: any) {
      mic?.getTracks().forEach((tr) => tr.stop());
      mic = null;
      // NotAllowedError / SecurityError: the person or the browser said no; anything else: no usable microphone
      store.addError(t(e?.name === 'NotAllowedError' || e?.name === 'SecurityError' ? 'mic_denied' : 'mic_unavailable'));
    }
  }

  // leaving the chat (a tab switch on a phone) must not leave the microphone on
  onDestroy(() => {
    destroyed = true;
    if (rec && rec.state !== 'inactive') rec.stop();
    mic?.getTracks().forEach((tr) => tr.stop());
  });

  async function send() {
    if (!ready || store.running) return;
    const v = text.trim();
    const ids = store.tray.map((a) => a.id);
    text = '';
    heard = null;
    store.tray = [];
    queueMicrotask(fit);
    await store.send(v || t('see_attached'), ids);
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
    <div class="tipbox card"><CaptureTips compact /><button class="btn icon ghost small close" onclick={() => (tips = false)} aria-label={t('close')}><Icon name="x" size={14} /></button></div>
  {/if}
  {#if job}
    <div class="meta">
      <span>{fmtDuration(elapsed)}</span>
      {#if tokens}<span>{fmtTokens(tokens)} {t('tokens')}</span>{/if}
      {#if store.running && job.kind === 'design' && !job.finished}<span class="eta">{t('eta_hint')}</span>{/if}
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
            {#if a.kind === 'photo'}
              {@const target = store.target(a.id)}
              <button
                class="thumb"
                class:found={!!target?.mask_url}
                class:scanning={!!store.spotting[a.id]}
                onclick={() => (focusing = a)}
                title={store.spotting[a.id] ? t('spot_finding') : (store.targetLabel(a.id) ?? t('select_object'))}
              >
                {#if target?.mask_url}
                  <Sticker photo={a.url} mask={target.mask_url} bbox={target.data?.bbox_px ?? null} size={46} />
                {:else}
                  <img src={a.thumb_url ?? a.url} alt={a.kind} />
                {/if}
                {#if store.spotting[a.id]}<span class="sweep" aria-hidden="true"></span>{/if}
                {#if store.assets.find((x) => x.id === a.id)?.meta?.calibration?.ok}<span class="cal" title={t('calibrated')}><Icon name="ruler" size={11} /></span>{/if}
              </button>
            {:else if isImage(a)}
              <button class="thumb" onclick={() => (selecting = a)} title={t('select_object')}>
                <img src={a.thumb_url ?? a.url} alt={a.kind} />
                {#if a.meta?.calibration}<span class="cal" title={t('calibrated')}><Icon name="ruler" size={11} /></span>{/if}
                {#if selCount(a)}<span class="sel">{selCount(a)}</span>{/if}
              </button>
            {:else}
              <span class="file"><Icon name={a.kind === 'audio' ? 'mic' : 'video'} size={16} /></span>
            {/if}
            <button class="x" onclick={() => (store.tray = store.tray.filter((x) => x.id !== a.id))} aria-label={t('remove')}><Icon name="x" size={11} /></button>
          </div>
        {/each}
        {#if uploading}<div class="att busy"><i class="ti ti-loader-2 spin" aria-hidden="true"></i></div>{/if}
        {#if recording}
          <button class="btn small rec" onclick={toggleRecord}><Icon name="stop" size={12} /> {t('recording', { s: Math.round((now - recStart) / 1000) })}</button>
        {/if}
      </div>
    {/if}

    {#if heard}
      <div class="heard xs" class:empty={'miss' in heard}>
        <Icon name="mic" size={12} /> {'s' in heard ? t('voice_caption', { s: heard.s }) : codeText(heard.miss) ?? t('voice_empty')}
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
        <button class="round pressable" onclick={() => (menu = !menu)} aria-expanded={menu} aria-label={t('add')} title={t('add')}><Icon name="plus" size={19} /></button>
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
      <button class="round pressable" class:on={recording} onclick={toggleRecord} aria-label={t('record')} title={t('record')}><Icon name="mic" size={17} /></button>
      <span class="spacer"></span>
      {#if store.running && !store.replaying}
        <button class="round pressable send stop" onclick={() => store.cancel()} disabled={stopping} aria-label={t(stopping ? 'stopping' : 'stop')} title={t(stopping ? 'stopping' : 'stop')}>
          {#if stopping}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="stop" size={13} />{/if}
        </button>
      {:else}
        <button class="round pressable send" onclick={send} disabled={!ready} aria-label={t('send')} title={t('send')}><Icon name="arrow-up" size={18} /></button>
      {/if}
    </div>
  </div>

  <div class="meta pickers">
    <Picker label={t('model')} value={prefs.model} options={modelOptions} up onpick={(v) => setPref('model', v)} />
    <Picker label={t('reasoning')} value={prefs.reasoning} options={reasoningOptions} quiet up onpick={(v) => setPref('reasoning', v)} />
  </div>
</div>

{#if focusing}
  <PhotoFocus {store} asset={focusing} onClose={() => (focusing = null)} />
{/if}

{#if selecting}
  <PhotoSelect projectId={store.id} asset={selecting} selections={store.selections} onClose={() => (selecting = null)} />
{/if}

<style>
  .composer {
    padding: var(--space-2) var(--space-3) var(--space-3);
    display: flex;
    flex-direction: column;
    gap: 6px;
    position: relative;
  }
  .box {
    background: var(--surface);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-field);
    transition:
      border-color var(--dur-fast) var(--ease-standard),
      box-shadow var(--dur-fast) var(--ease-standard);
  }
  .box:hover {
    border-color: var(--outline);
  }
  .box:focus-within {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 22%, transparent);
  }
  .box.dragging {
    border-color: var(--primary);
    background: color-mix(in srgb, var(--primary) 9%, var(--surface));
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
    font-size: var(--text-product-spec);
    line-height: 22px;
    padding: 11px 14px 2px;
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
    gap: 6px;
    padding: 4px 8px 8px;
    min-width: 0;
  }
  .round {
    flex: none;
    width: 34px;
    height: 34px;
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
  .round:hover:not(:disabled) {
    background: var(--surface-high);
    color: var(--on-surface);
  }
  .round.on {
    color: var(--error);
    border-color: var(--error);
  }
  .send {
    background: var(--primary);
    border-color: transparent;
    color: var(--on-primary);
  }
  .send:hover:not(:disabled) {
    background: color-mix(in srgb, var(--primary) 92%, white);
    color: var(--on-primary);
  }
  .send:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
  .send.stop {
    background: var(--on-surface);
    color: var(--surface);
  }
  .send.stop:hover:not(:disabled) {
    background: var(--on-surface-var);
    color: var(--surface);
  }
  .heard {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 9px 14px 0;
    color: var(--outline);
  }
  .heard.empty {
    color: var(--warn-text);
  }
  .tray {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
    align-items: center;
    padding: var(--space-3) var(--space-3) 0;
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
    border-radius: var(--radius-btn);
    border: var(--border-width) solid var(--outline-variant);
    overflow: hidden;
    padding: 0;
    background: var(--surface-high);
    color: var(--on-surface-var);
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
  /* the found object, cut out and glowing, instead of the whole photo */
  .thumb.found {
    background: radial-gradient(circle at 50% 55%, color-mix(in srgb, var(--primary) 30%, transparent), transparent 70%), #111;
    border-color: color-mix(in srgb, var(--primary) 60%, transparent);
  }
  .thumb.found :global(.sticker) {
    filter: drop-shadow(0 0 3px var(--primary));
    animation: lift 420ms var(--ease-pop);
  }
  @keyframes lift {
    from {
      transform: scale(0.6);
      opacity: 0;
    }
  }
  .sweep {
    position: absolute;
    inset: 0;
    background: linear-gradient(to bottom, transparent 30%, color-mix(in srgb, var(--primary) 70%, transparent) 50%, transparent 52%);
    background-size: 100% 220%;
    animation: sweep 1.4s var(--ease-standard) infinite;
    pointer-events: none;
  }
  @keyframes sweep {
    from {
      background-position: 0 100%;
    }
    to {
      background-position: 0 -120%;
    }
  }
  .cal,
  .sel {
    position: absolute;
    bottom: 3px;
    border-radius: var(--radius-tag);
    font-size: 10px;
    font-weight: var(--font-weight-semibold);
    padding: 1px 5px;
    display: inline-flex;
    align-items: center;
  }
  .cal {
    left: 3px;
    background: var(--primary-container);
    color: var(--on-primary-container);
  }
  .sel {
    right: 3px;
    background: var(--primary);
    color: var(--on-primary);
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
  .rec {
    color: var(--error);
    border-color: var(--error);
  }
  .tipbox {
    padding: var(--space-3) 44px var(--space-3) var(--space-3);
    position: relative;
  }
  .close {
    position: absolute;
    top: 6px;
    right: 6px;
  }
  .replay {
    display: flex;
    gap: var(--space-2);
    align-items: center;
    background: color-mix(in srgb, var(--info) 16%, transparent);
    color: var(--info-text);
    border-radius: var(--radius-card);
    padding: 10px 14px;
    font-weight: var(--font-weight-semibold);
  }
  .addwrap {
    position: relative;
  }
  .menu {
    position: absolute;
    bottom: 42px;
    left: 0;
    z-index: 30;
    min-width: 220px;
    padding: var(--space-2);
    display: flex;
    flex-direction: column;
    border-radius: var(--radius-field);
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.32);
  }
  .mi {
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 8px 10px;
    border-radius: var(--radius-field);
    border: none;
    background: none;
    cursor: pointer;
    font-family: inherit;
    font-size: var(--text-product-spec);
    text-align: left;
    color: var(--on-surface);
  }
  .mi :global(.icon) {
    color: var(--on-surface-var);
  }
  .mi:hover,
  .mi:focus-within {
    background: var(--surface-high);
  }
  .tipsbtn {
    border-top: var(--border-width) solid var(--divider);
    border-radius: 0 0 var(--radius-field) var(--radius-field);
    margin-top: 4px;
  }
  /* text lines up with the textarea's 14px inset */
  .meta {
    display: flex;
    gap: 10px;
    padding: 0 14px;
    font-size: 11px;
    color: var(--outline);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .eta {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pickers {
    justify-content: flex-end;
    gap: 0;
    /* plus each picker's own 8px padding = the same inset */
    padding: 0 6px;
  }
  .pickers :global(.cur) {
    font-size: 11px;
    padding: 2px 8px;
    color: var(--outline);
  }
  .pickers :global(.cur:hover),
  .pickers :global(.cur[aria-expanded='true']) {
    color: var(--on-surface);
  }
</style>
