<script lang="ts">
  import { onDestroy } from 'svelte';
  import Icon from './Icon.svelte';
  import PhotoSelect from './PhotoSelect.svelte';
  import Sticker from './Sticker.svelte';
  import QrModal from './QrModal.svelte';
  import { t, unitLabel } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import type { AssetOut } from '$lib/types';

  let { store, onPhotoAR }: { store: ProjectStore; onPhotoAR?: (a: AssetOut) => void } = $props();

  const KINDS = [
    { kind: 'photo', accept: 'image/*', icon: 'image', capture: undefined },
    { kind: 'caliper', accept: 'image/*', icon: 'ruler', capture: 'environment' },
    { kind: 'sketch', accept: 'image/*', icon: 'pencil', capture: 'environment' },
    { kind: 'video', accept: 'video/mp4,video/quicktime,video/*', icon: 'video', capture: 'environment' },
  ];
  const KIND_ICON: Record<string, string> = { photo: 'image', caliper: 'ruler', sketch: 'pencil', video: 'video', audio: 'mic', concept: 'scribble', render: 'cube', print: 'printer' };

  let uploading = $state(0);
  let selecting = $state<AssetOut | null>(null);
  let qr = $state(false);
  let rec: MediaRecorder | null = null;
  let mic: MediaStream | null = null;
  let destroyed = false;
  let recording = $state(false);
  let recStart = $state(0);
  let now = $state(Date.now());

  // anything added here is meant for the agent: it goes straight into the next message
  async function add(kind: string, file: Blob, filename?: string) {
    uploading++;
    const a = await store.upload(file, kind, filename);
    if (a && !store.tray.some((x) => x.id === a.id)) store.tray = [...store.tray, a];
    uploading--;
  }

  async function upload(kind: string, list: FileList | null) {
    for (const f of Array.from(list ?? [])) await add(f.type.startsWith('video/') ? 'video' : kind, f);
  }

  async function toggleRecord() {
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
      rec.onstop = () => {
        stream.getTracks().forEach((tr) => tr.stop());
        mic = null;
        recording = false;
        if (destroyed) return;
        const type = rec?.mimeType || 'audio/webm';
        const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
        add('audio', new Blob(chunks, { type }), `voice.${ext}`);
      };
      rec.start();
      recording = true;
      recStart = Date.now();
      const tick = setInterval(() => {
        now = Date.now();
        if (!recording) clearInterval(tick);
      }, 250);
    } catch (e: any) {
      mic?.getTracks().forEach((tr) => tr.stop());
      mic = null;
      store.addError(t(e?.name === 'NotAllowedError' || e?.name === 'SecurityError' ? 'mic_denied' : 'mic_unavailable'));
    }
  }

  // closing the panel mid-recording turns the microphone off and drops the note
  onDestroy(() => {
    destroyed = true;
    if (rec && rec.state !== 'inactive') rec.stop();
    mic?.getTracks().forEach((tr) => tr.stop());
  });

  const inTray = (a: AssetOut) => store.tray.some((x) => x.id === a.id);
  const toggleTray = (a: AssetOut) => (store.tray = inTray(a) ? store.tray.filter((x) => x.id !== a.id) : [...store.tray, a]);
  const sels = (a: AssetOut) => store.selections.filter((s) => s.asset_id === a.id);
  const isImage = (a: AssetOut) => ['photo', 'sketch', 'caliper', 'concept', 'render', 'print'].includes(a.kind);
  const kindLabel = (k: string) => (k === 'concept' ? t('concepts') : k === 'render' ? t('model') : t(k));
  const assets = $derived([...store.assets].reverse());
</script>

<div class="assets">
  <!-- adding files is the owner's: a visitor (or the recipe page) only looks at what the run used -->
  {#if !store.readonly}
    <p class="xs muted hint">{t('assets_hint')}</p>
    <div class="kinds">
      {#each KINDS as k (k.kind)}
        <label class="btn small">
          <Icon name={k.icon} size={15} /> {t(k.kind)}
          <input class="sr-only" type="file" accept={k.accept} capture={k.capture as any} multiple={k.kind !== 'video'} onchange={(e) => upload(k.kind, (e.currentTarget as HTMLInputElement).files)} />
        </label>
      {/each}
      <button class="btn small" class:rec={recording} onclick={toggleRecord} aria-pressed={recording}>
        <Icon name={recording ? 'stop' : 'mic'} size={15} />
        {recording ? t('recording', { s: Math.round((now - recStart) / 1000) }) : t('voice')}
      </button>
      <button class="btn small" onclick={() => (qr = true)}><Icon name="phone" size={15} /> {t('phone')}</button>
    </div>
  {/if}
  {#if uploading}<div class="xs muted row"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('upload')}…</div>{/if}

  {#if !assets.length && !uploading}
    <div class="empty xs muted">{t('no_assets')}</div>
  {/if}

  <div class="grid">
    {#each assets as a (a.id)}
      <div class="asset card" class:on={inTray(a)}>
        {#if isImage(a) && store.readonly}
          <!-- marking objects on a photo writes to the project: a visitor opens the photo itself -->
          <a class="pic" href={a.url} target="_blank" rel="noopener">
            <img src={a.thumb_url ?? a.url} alt={kindLabel(a.kind)} loading="lazy" />
            {#if sels(a).length}<span class="badge">{sels(a).length}</span>{/if}
          </a>
        {:else if isImage(a)}
          <button class="pic" onclick={() => (selecting = a)} title={t('select_object')} aria-label={t('select_object')}>
            <img src={a.thumb_url ?? a.url} alt={kindLabel(a.kind)} loading="lazy" />
            {#if sels(a).length}<span class="badge">{sels(a).length}</span>{/if}
          </button>
        {:else if a.kind === 'video'}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video src={a.url} poster={a.thumb_url ?? undefined} controls preload="metadata"></video>
        {:else if a.kind === 'audio'}
          <audio src={a.url} controls preload="none"></audio>
          {#if a.meta?.transcript}<p class="xs tr">“{a.meta.transcript}”</p>{/if}
        {/if}
        <div class="foot xs">
          <Icon name={KIND_ICON[a.kind] ?? 'image'} size={13} />
          <span class="kind">{kindLabel(a.kind)}</span>
          {#if a.meta?.calibration}
            <span class="chip ok cal" title={a.meta.calibration.reference ?? t('calibrated')}><Icon name="ruler" size={11} /> {t('calibrated')}</span>
          {/if}
        </div>
        {#each sels(a) as s (s.id)}
          <div class="sel xs">
            {#if s.mask_url}<Sticker photo={a.url} mask={s.mask_url} bbox={s.data?.bbox_px ?? null} size={30} />{/if}
            <span><strong>{s.name && s.name !== s.role ? s.name : t(`role.${s.role}`)}</strong>{s.name && s.name !== s.role ? ` · ${t(`role.${s.role}`)}` : ''}{s.data?.size_mm ? ` · ${s.data.size_mm.map((v: number) => v.toFixed(1)).join('×')} ${unitLabel('mm')}` : ''}</span>
          </div>
        {/each}
        <div class="acts">
          {#if a.kind !== 'render' && !store.readonly}
            <button class="btn small" class:primary={!inTray(a)} onclick={() => toggleTray(a)} aria-pressed={inTray(a)}>
              <Icon name={inTray(a) ? 'check' : 'plus'} size={13} /> {inTray(a) ? t('in_message') : t('attach_to_msg')}
            </button>
          {/if}
          {#if a.meta?.calibration && onPhotoAR && store.build}
            <button class="btn small ghost" onclick={() => onPhotoAR?.(a)} title={t('photo_ar')}><Icon name="eye" size={13} /> {t('photo_ar')}</button>
          {/if}
        </div>
      </div>
    {/each}
  </div>
</div>

{#if selecting}
  <PhotoSelect projectId={store.id} asset={selecting} selections={store.selections} onClose={() => (selecting = null)} />
{/if}
{#if qr}
  <QrModal projectId={store.id} onClose={() => (qr = false)} />
{/if}

<style>
  .assets {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .hint {
    margin: 0;
  }
  .kinds {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .rec {
    border-color: var(--error);
    color: var(--error);
  }
  .empty {
    border: var(--border-width) dashed var(--outline);
    border-radius: var(--radius-card);
    padding: 18px;
    text-align: center;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 8px;
  }
  .asset {
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }
  .asset.on {
    border-color: var(--primary);
  }
  .pic {
    position: relative;
    border: none;
    padding: 0;
    background: none;
    cursor: pointer;
  }
  a.pic {
    display: block;
  }
  .pic img,
  video {
    width: 100%;
    aspect-ratio: 4 / 3;
    object-fit: cover;
    border-radius: var(--radius-btn);
    display: block;
    background: var(--surface);
  }
  audio {
    width: 100%;
  }
  .badge {
    position: absolute;
    top: 4px;
    right: 4px;
    background: var(--primary);
    color: var(--on-primary);
    border-radius: var(--radius-tag);
    font-size: var(--text-xs);
    padding: 1px 7px;
  }
  .foot {
    display: flex;
    gap: 5px;
    align-items: center;
    flex-wrap: wrap;
    color: var(--on-surface-var);
  }
  .kind {
    font-weight: var(--font-weight-semibold);
  }
  .cal {
    gap: 3px;
  }
  .acts {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
  }
  .acts .btn {
    flex: 1;
    justify-content: center;
  }
  .sel {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .tr {
    margin: 0;
    color: var(--outline);
  }
</style>
