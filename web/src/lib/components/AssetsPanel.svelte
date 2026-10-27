<script lang="ts">
  import { api, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import type { AssetOut } from '$lib/types';
  import PhotoSelect from './PhotoSelect.svelte';
  import Sticker from './Sticker.svelte';
  import QrModal from './QrModal.svelte';

  let { store, onPhotoAR }: { store: ProjectStore; onPhotoAR?: (a: AssetOut) => void } = $props();

  const KINDS = [
    { kind: 'photo', accept: 'image/*', icon: '📷', capture: 'environment' },
    { kind: 'caliper', accept: 'image/*', icon: '📏', capture: 'environment' },
    { kind: 'sketch', accept: 'image/*', icon: '✏️', capture: 'environment' },
    { kind: 'video', accept: 'video/mp4,video/quicktime,video/*', icon: '🎬', capture: 'environment' },
    { kind: 'audio', accept: 'audio/*', icon: '🎙', capture: undefined },
  ];

  let uploading = $state(0);
  let error = $state<string | null>(null);
  let selecting = $state<AssetOut | null>(null);
  let qr = $state(false);
  let rec: MediaRecorder | null = null;
  let recording = $state(false);
  let recStart = $state(0);
  let now = $state(Date.now());

  async function upload(kind: string, list: FileList | null) {
    if (!list) return;
    error = null;
    for (const f of Array.from(list)) {
      uploading++;
      try {
        const a = await api.upload(store.id, f, kind);
        if (store.detail && !store.detail.assets.some((x) => x.id === a.id)) store.detail.assets.push(a);
      } catch (e) {
        error = errorText(e);
      } finally {
        uploading--;
      }
    }
  }

  async function toggleRecord() {
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
        const blob = new Blob(chunks, { type });
        const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
        uploading++;
        try {
          const a = await api.upload(store.id, blob, 'audio', `voice.${ext}`);
          if (store.detail && !store.detail.assets.some((x) => x.id === a.id)) store.detail.assets.push(a);
        } catch (e) {
          error = errorText(e);
        } finally {
          uploading--;
        }
      };
      rec.start();
      recording = true;
      recStart = Date.now();
      const tick = setInterval(() => {
        now = Date.now();
        if (!recording) clearInterval(tick);
      }, 250);
    } catch (e) {
      error = errorText(e);
    }
  }

  const sels = (a: AssetOut) => store.selections.filter((s) => s.asset_id === a.id);
  const isImage = (a: AssetOut) => ['photo', 'sketch', 'caliper', 'concept', 'render', 'print'].includes(a.kind);
</script>

<div class="assets">
  <div class="kinds">
    {#each KINDS as k (k.kind)}
      {#if k.kind === 'audio'}
        <button class="btn small" class:rec={recording} onclick={toggleRecord} aria-pressed={recording}>
          {recording ? `⏹ ${t('stop')} ${Math.round((now - recStart) / 1000)}s` : `${k.icon} ${t('record')}`}
        </button>
      {/if}
      <label class="btn small">
        {k.icon} {t(k.kind)}
        <input class="sr-only" type="file" accept={k.accept} capture={k.capture as any} multiple={k.kind !== 'video'} onchange={(e) => upload(k.kind, (e.currentTarget as HTMLInputElement).files)} />
      </label>
    {/each}
    <button class="btn small" onclick={() => (qr = true)}>📱 {t('phone')}</button>
  </div>
  {#if uploading}<div class="muted small">{t('upload')}… ({uploading})</div>{/if}
  {#if error}<div class="err small">{error}</div>{/if}

  <div class="grid">
    {#each store.assets as a (a.id)}
      <div class="asset card">
        {#if isImage(a)}
          <button class="pic" onclick={() => (selecting = a)} aria-label="select objects on {a.kind}">
            <img src={a.thumb_url ?? a.url} alt={a.kind} loading="lazy" />
            {#if sels(a).length}<span class="badge chip">{sels(a).length}</span>{/if}
          </button>
        {:else if a.kind === 'video'}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video src={a.url} poster={a.thumb_url ?? undefined} controls preload="metadata"></video>
        {:else if a.kind === 'audio'}
          <audio src={a.url} controls preload="none"></audio>
          {#if a.meta?.transcript}<p class="small tr">“{a.meta.transcript}”</p>{/if}
        {/if}
        <div class="foot">
          <span class="chip">{a.kind}</span>
          {#if a.meta?.calibration}
            <span class="chip ok" title={a.meta.calibration.reference ?? ''}>📐 {a.meta.calibration.reference ?? 'calibrated'}</span>
            {#if onPhotoAR}<button class="btn small ghost" onclick={() => onPhotoAR?.(a)}>AR</button>{/if}
          {/if}
        </div>
        {#each sels(a) as s (s.id)}
          <div class="sel">
            {#if s.mask_url}<Sticker photo={a.url} mask={s.mask_url} bbox={s.data?.bbox_px ?? null} size={36} />{/if}
            <span class="small"><strong>{s.name}</strong> · {t(`role.${s.role}`)}{s.data?.size_mm ? ` · ${s.data.size_mm.map((v: number) => v.toFixed(1)).join('×')} mm` : ''}</span>
          </div>
        {/each}
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
  .kinds {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .rec {
    border-color: var(--err);
    color: var(--err);
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
  .pic {
    position: relative;
    border: none;
    padding: 0;
    background: none;
  }
  .pic img,
  video {
    width: 100%;
    aspect-ratio: 4 / 3;
    object-fit: cover;
    border-radius: 6px;
    display: block;
    background: var(--panel-2);
  }
  audio {
    width: 100%;
  }
  .badge {
    position: absolute;
    top: 4px;
    right: 4px;
    background: var(--accent);
    color: var(--accent-ink);
    border: none;
  }
  .foot {
    display: flex;
    gap: 4px;
    align-items: center;
    flex-wrap: wrap;
  }
  .sel {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .small {
    font-size: 12px;
  }
  .tr {
    margin: 0;
    color: var(--muted);
  }
  .err {
    color: var(--err);
  }
</style>
