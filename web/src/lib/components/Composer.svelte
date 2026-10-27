<script lang="ts">
  import Icon from './Icon.svelte';
  import CaptureTips from './CaptureTips.svelte';
  import PhotoSelect from './PhotoSelect.svelte';
  import { t } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import type { AssetOut } from '$lib/types';

  let { store }: { store: ProjectStore } = $props();
  let text = $state('');
  let hard = $state(false);
  let uploading = $state(0);
  let menu = $state(false);
  let tips = $state(false);
  let selecting = $state<AssetOut | null>(null);
  let rec: MediaRecorder | null = null;
  let recording = $state(false);
  let recStart = $state(0);
  let now = $state(Date.now());
  let area: HTMLTextAreaElement;

  const waiting = $derived(store.currentJob?.status === 'waiting');
  const hasModel = $derived(!!store.source);
  const suggestions = $derived(
    hasModel
      ? [t('suggest_stronger'), t('suggest_lighter'), t('suggest_round'), t('suggest_explain')].map((s) => ({ label: s, text: s, send: true }))
      : [
          { label: t('suggest_size'), text: t('suggest_size_t'), send: false },
          { label: t('suggest_mount'), text: t('suggest_mount_t'), send: false },
          { label: t('suggest_load'), text: t('suggest_load_t'), send: false },
        ],
  );

  const SOURCES = [
    { kind: 'photo', icon: 'image', accept: 'image/*', capture: undefined },
    { kind: 'camera', icon: 'camera', accept: 'image/*', capture: 'environment' },
    { kind: 'caliper', icon: 'ruler', accept: 'image/*', capture: 'environment' },
    { kind: 'sketch', icon: 'pencil', accept: 'image/*', capture: 'environment' },
    { kind: 'video', icon: 'video', accept: 'video/mp4,video/quicktime,video/*', capture: 'environment' },
  ];

  async function addFiles(kind: string, list: FileList | null) {
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
      const tick = setInterval(() => {
        now = Date.now();
        if (!recording) clearInterval(tick);
      }, 250);
    } catch (e: any) {
      store.addError(e?.message ?? String(e));
    }
  }

  async function send() {
    const v = text.trim();
    if ((!v && !store.tray.length) || uploading) return;
    const ids = store.tray.map((a) => a.id);
    text = '';
    store.tray = [];
    await store.send(v || '(see attached)', ids, hard ? 'hard' : 'auto');
  }

  function suggest(s: { text: string; send: boolean }) {
    if (s.send) {
      text = s.text;
      send();
      return;
    }
    text = (text.trim() ? text.trim() + '. ' : '') + s.text;
    area?.focus();
  }

  const isImage = (a: AssetOut) => ['photo', 'sketch', 'caliper', 'print', 'concept'].includes(a.kind);
  const selCount = (a: AssetOut) => store.selections.filter((s) => s.asset_id === a.id).length;
</script>

<div class="composer">
  {#if store.replaying}
    <div class="replay small"><Icon name="play" size={14} /> {t('replay_banner')}</div>
  {/if}
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
      {#if store.tray.some((a) => isImage(a) && !selCount(a))}<span class="xs muted hint">{t('select_object_hint')}</span>{/if}
    </div>
  {/if}

  {#if tips}
    <div class="tipbox card"><CaptureTips compact /><button class="btn small ghost close" onclick={() => (tips = false)} aria-label={t('close')}><Icon name="x" size={14} /></button></div>
  {/if}

  {#if waiting}<div class="waitnote xs"><Icon name="help" size={13} /> {t('answer')} ↑</div>{/if}

  <textarea
    bind:this={area}
    bind:value={text}
    rows="2"
    placeholder={t(hasModel ? 'message_placeholder' : 'message_placeholder_new')}
    aria-label={t(hasModel ? 'message_placeholder' : 'message_placeholder_new')}
    disabled={store.replaying}
    onkeydown={(e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        send();
      }
    }}
  ></textarea>

  {#if !store.running && !store.replaying && !text.trim()}
    <div class="sugg" role="group">
      {#each suggestions as s (s.label)}<button class="chip sbtn" onclick={() => suggest(s)}>{s.label}</button>{/each}
    </div>
  {/if}

  <div class="bar">
    <div class="addwrap">
      <button class="btn icon small" onclick={() => (menu = !menu)} aria-expanded={menu} aria-label={t('add')} title={t('add')}><Icon name="plus" size={17} /></button>
      {#if menu}
        <div class="menu card" role="group" aria-label={t('add')}>
          {#each SOURCES as s (s.kind)}
            <label class="mi">
              <Icon name={s.icon} size={16} /> {t(s.kind)}
              <input class="sr-only" type="file" accept={s.accept} capture={s.capture as any} multiple={s.kind !== 'video'} onchange={(e) => addFiles(s.kind, (e.currentTarget as HTMLInputElement).files)} />
            </label>
          {/each}
          <button class="mi" onclick={toggleRecord}><Icon name="mic" size={16} /> {t('record')}</button>
          <button class="mi tipsbtn" onclick={() => ((tips = true), (menu = false))}><Icon name="help" size={16} /> {t('tips')}</button>
        </div>
      {/if}
    </div>
    <label class="hard xs" title={t('hard_mode_hint')}><input type="checkbox" bind:checked={hard} /> {t('hard_mode')}</label>
    <span class="spacer"></span>
    {#if store.running && !store.replaying}
      <button class="btn small" onclick={() => store.cancel()}><Icon name="stop" size={12} /> {t('stop')}</button>
    {/if}
    <button class="btn primary small send" onclick={send} disabled={(!text.trim() && !store.tray.length) || !!uploading || store.replaying} aria-label={t('send')}>
      <Icon name="send" size={14} /> <span class="lbl">{t('send')}</span>
    </button>
  </div>
</div>

{#if selecting}
  <PhotoSelect projectId={store.id} asset={selecting} selections={store.selections} onClose={() => (selecting = null)} />
{/if}

<style>
  .composer {
    border-top: 1px solid var(--line);
    padding: 10px 12px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    background: var(--panel);
    position: relative;
  }
  textarea {
    width: 100%;
    min-height: 46px;
    max-height: 180px;
    border-radius: 12px;
    background: var(--panel-2);
  }
  .tray {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }
  .att {
    position: relative;
    width: 58px;
    height: 58px;
  }
  .thumb,
  .file,
  .att.busy {
    width: 58px;
    height: 58px;
    border-radius: 10px;
    border: 1px solid var(--line);
    overflow: hidden;
    padding: 0;
    background: var(--panel-2);
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
  .hint {
    flex-basis: 100%;
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
  .waitnote {
    color: var(--accent);
    display: flex;
    gap: 4px;
    align-items: center;
    font-weight: 600;
  }
  .sugg {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .sbtn {
    cursor: pointer;
    background: var(--panel);
  }
  .sbtn:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 8px;
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
  .hard {
    display: flex;
    gap: 5px;
    align-items: center;
    color: var(--muted);
    cursor: pointer;
    white-space: nowrap;
  }
  @media (max-width: 420px) {
    .send .lbl {
      display: none;
    }
  }
</style>
