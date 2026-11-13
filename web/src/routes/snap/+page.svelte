<script lang="ts">
  // Snap & collect: point the phone at something, tap it, and it becomes a printable miniature.
  // The tap is the segmentation prompt; the object lights up, can be corrected with more taps,
  // and its cut-out rises into a 3D sticker (built right here from the server's relief) that goes
  // into the collection at once. A full figurine from the agent stays one tap away.
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import Icon from '$lib/components/Icon.svelte';
  import SnapHighlight from '$lib/components/SnapHighlight.svelte';
  import Sticker from '$lib/components/Sticker.svelte';
  import StickerPreview from '$lib/components/StickerPreview.svelte';
  import { api, errorText } from '$lib/api';
  import { collectApi, collectError, type KeepResult, type StickerPayload } from '$lib/collect/api';
  import { ct, num, secs } from '$lib/collect/i18n';
  import { i18n, t, unitLabel } from '$lib/i18n.svelte';
  import { chosenModel, prefs } from '$lib/session.svelte';
  import { place, toImage, toJpeg, type Box, type Fit } from '$lib/snapframe';
  import type { SelectionOut, SnapObject, SnapResult } from '$lib/types';

  type Phase = 'camera' | 'aim' | 'scan' | 'review' | 'sent';
  type Pt = { x: number; y: number; positive: boolean };
  const SIZES = [40, 50, 60]; // mm along the longest side

  let phase = $state<Phase>('camera');
  let camera = $state<'starting' | 'on' | 'off'>('starting');
  let live = $state(false); // first frame is in
  let video = $state<HTMLVideoElement>();
  let stream: MediaStream | null = null;
  let shot = $state<{ url: string; blob: Blob; w: number; h: number; fit: Fit } | null>(null);
  let tap = $state<{ x: number; y: number } | null>(null); // 0..1 on the photo
  let res = $state<SnapResult | null>(null);
  let sel = $state<SelectionOut | null>(null);
  let label = $state('');
  let objects = $state<SnapObject[]>([]);
  let points = $state<Pt[]>([]);
  let box = $state<Box | null>(null);
  let mode = $state<'add' | 'remove'>('add');
  let size = $state(savedSize());
  let busy = $state(false);
  let naming = $state(false);
  let sending = $state(false);
  let queued = $state(false);
  let error = $state<string | null>(null);
  // the instant sticker: relief from the server, 3D from this page's geometry worker
  let sticker = $state.raw<StickerPayload | null>(null); // ~130 KB of relief: replaced whole, never deep-watched
  let lifted = $state(false); // the 3D sticker replaced the flat cut-out
  let built = $state<{ ms: number; size: [number, number, number] } | null>(null);
  let samMs = $state(0); // shutter to highlight, upload included
  let kept = $state<KeepResult | null>(null);
  let keeping = $state(false);
  // a shot the server could not take is kept, so Retry sends the same photo with the same tap
  let failed = $state<{ blob: Blob; w: number; h: number; fit: Fit; x: number; y: number } | null>(null);
  let toastTimer: ReturnType<typeof setTimeout> | undefined;
  let flash = $state(0);
  let count = $state(0);
  let sheetH = $state(0);
  const touch = typeof matchMedia !== 'undefined' && matchMedia('(pointer: coarse)').matches;

  // the stored photo's pixels (same as the shot unless the server had to shrink it)
  const W = $derived(res?.asset.width ?? shot?.w ?? 1);
  const H = $derived(res?.asset.height ?? shot?.h ?? 1);
  const tapPx = $derived(tap ? { x: tap.x * W, y: tap.y * H } : null);
  const focus = $derived.by<Box | null>(() => {
    const b = sel?.data?.bbox_px;
    return (phase === 'review' || phase === 'sent') && Array.isArray(b) && b.length === 4 ? (b as Box) : null;
  });
  const sheet = $derived(phase === 'review' || phase === 'sent');

  function savedSize(): number {
    try {
      const v = Number(localStorage.getItem('fw_snap_size'));
      return SIZES.includes(v) ? v : 50;
    } catch {
      return 50;
    }
  }
  function pickSize(v: number) {
    size = v;
    try {
      localStorage.setItem('fw_snap_size', String(v));
    } catch {
      /* storage unavailable */
    }
  }

  onMount(() => {
    startCamera();
    api
      .collection()
      .then((items) => (count = items.filter((i) => i.state !== 'draft').length))
      .catch(() => {});
    return () => {
      stream?.getTracks().forEach((tr) => tr.stop());
      if (shot) URL.revokeObjectURL(shot.url);
      clearTimeout(toastTimer);
    };
  });

  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      camera = 'off';
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1440 } }, audio: false });
      camera = 'on';
    } catch {
      camera = 'off';
    }
  }

  // the <video> is re-created every time the viewfinder comes back
  $effect(() => {
    if (!video || !stream || video.srcObject === stream) return;
    live = false;
    video.srcObject = stream;
    video.play().catch(() => {});
  });

  function reset() {
    if (shot) URL.revokeObjectURL(shot.url);
    shot = null;
    tap = null;
    res = null;
    sel = null;
    label = '';
    objects = [];
    points = [];
    box = null;
    mode = 'add';
    error = null;
    failed = null;
    queued = false;
    busy = false;
    naming = false;
    sticker = null;
    lifted = false;
    built = null;
    samMs = 0;
    kept = null;
    keeping = false;
  }

  // over the viewfinder an error shows for a few seconds, then the camera is clear again;
  // a shot that can be sent again stays on offer until the next shot replaces it
  function toast(msg: string) {
    error = msg;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      if (error !== msg || failed) return;
      error = null;
    }, 5000);
  }

  function retry() {
    const f = failed;
    if (!f) return;
    clearTimeout(toastTimer);
    reset();
    shot = { url: URL.createObjectURL(f.blob), blob: f.blob, w: f.w, h: f.h, fit: f.fit };
    send(f.x, f.y);
  }

  async function shoot(ev?: PointerEvent) {
    if (phase !== 'camera' || !video?.videoWidth) return;
    let nx = 0.5,
      ny = 0.5;
    if (ev) {
      const r = video.getBoundingClientRect();
      const q = toImage(place(r.width, r.height, video.videoWidth, video.videoHeight, 'cover'), ev.clientX - r.left, ev.clientY - r.top, video.videoWidth, video.videoHeight);
      if (q) [nx, ny] = [q.x / video.videoWidth, q.y / video.videoHeight];
    }
    flash++;
    try {
      const { blob, w, h } = await toJpeg(video);
      reset();
      shot = { url: URL.createObjectURL(blob), blob, w, h, fit: 'cover' };
      send(nx, ny);
    } catch (e) {
      toast(errorText(e));
    }
  }

  async function pickFile(files: FileList | null) {
    const f = files?.[0];
    if (!f) return;
    reset();
    try {
      const bmp = await createImageBitmap(f, { imageOrientation: 'from-image' });
      const { blob, w, h } = await toJpeg(bmp);
      bmp.close();
      shot = { url: URL.createObjectURL(blob), blob, w, h, fit: 'contain' };
    } catch {
      // the server reads the original as well, orientation included
      const url = URL.createObjectURL(f);
      const im = new Image();
      im.src = url;
      await im.decode().catch(() => {});
      shot = { url, blob: f, w: im.naturalWidth || 1, h: im.naturalHeight || 1, fit: 'contain' };
    }
    phase = 'aim';
  }

  async function send(nx: number, ny: number) {
    if (!shot) return;
    tap = { x: nx, y: ny };
    phase = 'scan';
    error = null;
    const t0 = performance.now();
    try {
      const r = await api.snap(shot.blob, { x: nx, y: ny, lang: i18n.lang });
      samMs = performance.now() - t0;
      res = r;
      sel = r.selection;
      label = r.label ?? '';
      objects = r.objects;
      points = [{ x: Math.round(nx * r.asset.width!), y: Math.round(ny * r.asset.height!), positive: true }];
      if (!r.selection) error = t('snap_nothing');
      phase = 'review';
      // the relief comes with the snap answer, or right after it from the cache next to the mask
      const first = (r as SnapResult & { sticker?: StickerPayload | null }).sticker;
      if (first) sticker = first;
      else if (r.selection) loadSticker(r.project.id);
      if (r.label === null) nameIt(r.project.id);
    } catch (e) {
      // a camera shot goes back to the viewfinder, a picked photo stays to be tapped again; either way reset first, so the error survives
      const s = shot;
      if (s.fit === 'cover') {
        reset();
        phase = 'camera';
      } else phase = 'aim';
      failed = { blob: s.blob, w: s.w, h: s.h, fit: s.fit, x: nx, y: ny };
      toast(errorText(e));
    }
  }

  // the name arrives a few seconds after the highlight; it may also widen a tap on a detail to the whole object
  async function nameIt(pid: string) {
    naming = true;
    const edits = seq;
    try {
      const r = await api.snapName(pid);
      if (res?.project.id !== pid) return;
      if (!label.trim()) label = r.label;
      objects = r.objects;
      if (r.selection && seq === edits) {
        sel = r.selection;
        if (error === t('snap_nothing')) error = null;
      }
      // a grown selection, or a person (no photo detail), changes the relief
      if (r.selection && seq === edits) loadSticker(pid);
    } catch {
      /* unnamed is fine: the field stays editable */
    } finally {
      if (res?.project.id === pid) naming = false;
    }
  }

  function onPhotoTap(q: { x: number; y: number }) {
    if (phase === 'aim' && shot) return send(q.x / shot.w, q.y / shot.h);
    if (phase !== 'review' || !res) return;
    // with nothing selected yet any tap is "this one"
    points = [...points, { x: Math.round(q.x), y: Math.round(q.y), positive: mode === 'add' || !sel }];
    reselect();
  }

  let seq = 0;
  async function reselect(newLabel?: string) {
    if (!res) return;
    const my = ++seq;
    busy = true;
    error = null;
    try {
      const r = await api.snapSelect(res.project.id, { points: points.length ? points : undefined, box, label: newLabel ?? null });
      if (my !== seq) return;
      sel = r.selection;
      if (newLabel) label = r.label;
      loadSticker(res.project.id);
    } catch (e) {
      if (my !== seq) return;
      error = errorText(e);
      if (!newLabel) points = points.slice(0, -1);
    } finally {
      if (my === seq) busy = false;
    }
  }

  function pick(o: SnapObject) {
    const b = sel?.data?.bbox_px;
    // the current object stays one tap away
    objects = [...objects.filter((x) => x !== o), ...(sel && Array.isArray(b) ? [{ label, bbox: b as Box }] : [])];
    box = o.bbox;
    points = [];
    mode = 'add';
    reselect(o.label);
  }

  let stickerSeq = 0;
  async function loadSticker(pid: string) {
    const my = ++stickerSeq;
    try {
      const s = await collectApi.sticker(pid, sticker?.key);
      if (my !== stickerSeq || res?.project.id !== pid || 'same' in s) return;
      sticker = s;
    } catch {
      /* no sticker: the flat cut-out and "make a figurine" still work */
    }
  }

  // into the collection as the instant 3D sticker: no agent, ready at once
  async function keep() {
    if (!res || !sel) return;
    keeping = true;
    error = null;
    try {
      kept = await collectApi.keep(res.project.id, { label: label.trim() || undefined, size });
      phase = 'sent';
      queued = false;
      count++;
    } catch (e) {
      error = collectError(e);
    } finally {
      keeping = false;
    }
  }

  async function make() {
    if (!res || !sel) return;
    sending = true;
    error = null;
    const name = label.trim();
    try {
      const r = await api.snapConfirm(res.project.id, { text: ct('figure_msg', { label: name, size }), label: name, model: chosenModel(), reasoning: prefs.reasoning });
      queued = r.queued;
      phase = 'sent';
      count++;
    } catch (e) {
      error = errorText(e);
    } finally {
      sending = false;
    }
  }

  function retake() {
    if (res && phase !== 'sent') api.snapDiscard(res.project.id).catch(() => {});
    reset();
    phase = 'camera';
  }

  function next() {
    reset();
    phase = 'camera';
  }
</script>

<svelte:head><title>{t('snap_title')} · IaModelize3d</title></svelte:head>

<main class="snap" class:sheet style:--sheet="{sheet ? sheetH : 0}px">
  <div class="stage">
    {#if phase === 'camera'}
      {#if camera === 'on'}
        <video bind:this={video} class:live playsinline muted autoplay onloadeddata={() => (live = true)} onpointerup={(e) => shoot(e)} aria-label={t('snap_hint')}></video>
        <div class="reticle" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      {:else if camera === 'off'}
        <div class="nocam">
          <span class="nocam-ic"><Icon name="camera" size={34} /></span>
          <p>{t('snap_no_camera')}</p>
          <div class="nocam-row">
            {#if touch}
              <label class="btn primary large">
                <Icon name="camera" size={18} /> {t('take_photo')}
                <input class="sr-only" type="file" accept="image/*" capture="environment" onchange={(e) => pickFile((e.currentTarget as HTMLInputElement).files)} />
              </label>
            {/if}
            <label class="btn large" class:primary={!touch}>
              <Icon name="image" size={18} /> {t('snap_pick')}
              <input class="sr-only" type="file" accept="image/*" onchange={(e) => pickFile((e.currentTarget as HTMLInputElement).files)} />
            </label>
          </div>
        </div>
      {/if}
    {:else if shot}
      <SnapHighlight
        src={shot.url}
        width={W}
        height={H}
        fit={shot.fit}
        {focus}
        maskUrl={sel?.mask_url ?? null}
        outline={sel?.data?.outline_px ?? null}
        scanning={phase === 'scan'}
        scanAt={phase === 'scan' ? tapPx : null}
        points={phase === 'review' && points.length > 1 ? points : []}
        label={sheet && sel ? label.trim() || (naming ? '…' : null) : null}
        onTap={phase === 'aim' || phase === 'review' ? onPhotoTap : undefined}
      />
    {/if}
    {#key flash}{#if flash}<span class="flash" aria-hidden="true"></span>{/if}{/key}
  </div>

  <header class="bar">
    <a class="glass round" href="/" aria-label={t('back')} title={t('back')}><Icon name="arrow-left" size={20} /></a>
    <strong class="ttl">{t('snap_title')}</strong>
    {#if phase === 'review'}
      <div class="glass seg" role="radiogroup" aria-label={t('snap_edit_hint')} title={t('snap_edit_hint')}>
        <button role="radio" aria-checked={mode === 'add'} class:on={mode === 'add'} onclick={() => (mode = 'add')}><Icon name="plus" size={16} /> <span>{t('snap_add')}</span></button>
        <button role="radio" aria-checked={mode === 'remove'} class:on={mode === 'remove'} onclick={() => (mode = 'remove')}><Icon name="minus" size={16} /> <span>{t('snap_remove')}</span></button>
      </div>
    {:else}
      <span class="bar-gap"></span>
    {/if}
  </header>

  {#if error && !sheet}
    <div class="toast" role="alert">
      <span>{error}</span>
      {#if failed}<button class="toast-btn" onclick={retry}><Icon name="refresh" size={14} /> {t('snap_retry')}</button>{/if}
    </div>
  {/if}

  {#if phase === 'camera'}
    <div class="controls">
      {#if camera === 'on'}<p class="hint">{t('snap_hint')}</p>{/if}
      <div class="ctl-row">
        <!-- without a camera the panel above offers the same choices -->
        <label class="glass round big" class:gone={camera === 'off'} title={t('snap_pick')}>
          <Icon name="image" size={22} />
          <input class="sr-only" type="file" accept="image/*" aria-label={t('snap_pick')} onchange={(e) => pickFile((e.currentTarget as HTMLInputElement).files)} />
        </label>
        <button class="shutter" class:gone={camera === 'off'} onclick={() => shoot()} disabled={camera !== 'on' || !live} aria-label={t('snap_shutter')}><span></span></button>
        <a class="glass round big coll" href="/collection" aria-label={t('collection')} title={t('collection')}>
          <Icon name="grid" size={22} />
          {#if count}<span class="badge">{count}</span>{/if}
        </a>
      </div>
    </div>
  {:else if phase === 'aim'}
    <div class="controls">
      <p class="hint">{t('snap_file_hint')}</p>
      <div class="ctl-row">
        <button class="glass pill-btn" onclick={next}><Icon name="x" size={16} /> {t('snap_retake')}</button>
      </div>
    </div>
  {:else if phase === 'scan'}
    <div class="controls">
      <p class="hint working"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('snap_finding')}</p>
    </div>
  {/if}

  {#if sheet}
    <section class="panel" bind:clientHeight={sheetH} aria-live="polite">
      {#if res && sel}
        <!-- the flat cut-out, then the 3D sticker rising out of it -->
        <div class="lift">
          {#if sel.mask_url}
            <span class="cut" class:up={lifted} aria-hidden="true">
              <Sticker photo={res.asset.url} mask={sel.mask_url} bbox={Array.isArray(sel.data?.bbox_px) ? sel.data.bbox_px : null} size={150} />
            </span>
          {/if}
          {#if sticker}
            <StickerPreview
              {sticker}
              {size}
              {label}
              fallback={() => collectApi.stickerPng(res!.project.id, { size, label: label.trim() })}
              onbuilt={(i) => {
                lifted = true;
                built = i;
              }}
            />
          {/if}
          <div class="models">
            {#if samMs}<span class="mchip">{ct('chip_sam', { s: secs(samMs) })}</span>{/if}
            {#if naming}<span class="mchip">{ct('chip_naming')}</span>{:else if label.trim()}<span class="mchip">{ct('chip_name', { name: label.trim() })}</span>{/if}
          </div>
        </div>
      {/if}
      {#if phase === 'review'}
        <div class="name-row">
          <input class="name" bind:value={label} aria-label={t('snap_name')} placeholder={t('snap_name')} maxlength="40" />
          {#if busy || naming}<i class="ti ti-loader-2 spin busy" aria-hidden="true"></i>{/if}
        </div>
        {#if error}
          <p class="err small" role="alert">{error}</p>
        {:else}
          <p class="muted xs">{t('snap_edit_hint')}</p>
        {/if}
        {#if objects.length}
          <div class="group">
            <span class="section-title">{t('snap_other')}</span>
            <div class="scroll">
              {#each objects as o (o.label + o.bbox.join())}
                <button class="chip" onclick={() => pick(o)} disabled={busy}>{o.label}</button>
              {/each}
            </div>
          </div>
        {/if}
        <div class="group">
          <span class="section-title">
            {ct('sticker_size')}{#if built}<span class="dims">{' · '}{built.size[0].toFixed(0)} × {built.size[1].toFixed(0)} × {num(built.size[2])} {unitLabel('mm')}</span>{/if}
          </span>
          <div class="sizes" role="radiogroup" aria-label={ct('sticker_size')}>
            {#each SIZES as v (v)}
              <button class="chip" class:on={size === v} role="radio" aria-checked={size === v} onclick={() => pickSize(v)}>{v} {unitLabel('mm')}</button>
            {/each}
          </div>
        </div>
        <div class="acts">
          <button class="btn icon-btn" onclick={retake} aria-label={t('snap_retake')} title={t('snap_retake')}><Icon name="refresh" size={16} /></button>
          <button class="btn primary grow" onclick={keep} disabled={!sel || busy || keeping || sending}>
            {#if keeping}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="plus" size={16} />{/if}
            {ct('keep')}
          </button>
        </div>
        <button class="figure" onclick={make} disabled={!sel || !label.trim() || busy || sending || keeping}>
          {#if sending}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="cube" size={15} />{/if}
          {ct('figure')}
        </button>
      {:else if kept}
        <div class="done">
          <span class="tick"><Icon name="check" size={20} /></span>
          <div>
            <strong>{ct('kept')}</strong>
            <p class="muted small">
              {ct('kept_hint', { w: kept.size_mm[0]?.toFixed(0) ?? '', h: kept.size_mm[1]?.toFixed(0) ?? '', min: kept.est.minutes, g: num(kept.est.grams) })}
            </p>
            <p class="muted xs">{ct('two_colour')} · {ct('kept_plate')}</p>
          </div>
        </div>
        <div class="acts">
          <button class="btn" onclick={() => res && goto(`/p/${res.project.id}`)}>{t('open')}</button>
          <a class="btn" href="/collection"><Icon name="grid" size={16} /> {t('collection')}</a>
          <button class="btn primary grow" onclick={next}><Icon name="camera" size={16} /> {t('snap_next')}</button>
        </div>
      {:else}
        <div class="done">
          <span class="tick"><Icon name="check" size={20} /></span>
          <div>
            <strong>{queued ? t('collect.queued') : t('snap_started')}</strong>
            <p class="muted small">{queued ? t('snap_queued') : t('snap_started_hint')}</p>
          </div>
        </div>
        <div class="acts">
          <button class="btn" onclick={() => res && goto(`/p/${res.project.id}`)}>{t('open')}</button>
          <a class="btn" href="/collection"><Icon name="grid" size={16} /> {t('collection')}</a>
          <button class="btn primary grow" onclick={next}><Icon name="camera" size={16} /> {t('snap_next')}</button>
        </div>
      {/if}
    </section>
  {/if}
</main>

<style>
  .snap {
    position: fixed;
    inset: 0;
    background: #000;
    color: #fff;
    overflow: hidden;
    touch-action: manipulation;
  }
  .stage {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    bottom: var(--sheet);
  }
  video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    opacity: 0;
    transition: opacity var(--dur-slow) var(--ease-standard);
    cursor: crosshair;
  }
  video.live {
    opacity: 1;
  }
  /* corner brackets: where to aim */
  .reticle {
    position: absolute;
    left: 50%;
    top: 46%;
    width: min(56vw, 300px);
    aspect-ratio: 1;
    transform: translate(-50%, -50%);
    pointer-events: none;
  }
  .reticle i {
    position: absolute;
    width: 26px;
    height: 26px;
    border: 3px solid rgb(255 255 255 / 0.85);
    filter: drop-shadow(0 0 4px rgb(0 0 0 / 0.5));
  }
  .reticle i:nth-child(1) {
    left: 0;
    top: 0;
    border-right: 0;
    border-bottom: 0;
    border-top-left-radius: 10px;
  }
  .reticle i:nth-child(2) {
    right: 0;
    top: 0;
    border-left: 0;
    border-bottom: 0;
    border-top-right-radius: 10px;
  }
  .reticle i:nth-child(3) {
    left: 0;
    bottom: 0;
    border-right: 0;
    border-top: 0;
    border-bottom-left-radius: 10px;
  }
  .reticle i:nth-child(4) {
    right: 0;
    bottom: 0;
    border-left: 0;
    border-top: 0;
    border-bottom-right-radius: 10px;
  }
  .flash {
    position: absolute;
    inset: 0;
    background: #fff;
    pointer-events: none;
    animation: flash 320ms var(--ease-out) forwards;
  }
  @keyframes flash {
    from {
      opacity: 0.85;
    }
    to {
      opacity: 0;
    }
  }

  .nocam {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-4);
    padding: 96px var(--space-5) 140px;
    text-align: center;
    background: #0b0c08;
  }
  .nocam p {
    margin: 0;
    max-width: 320px;
    color: rgb(255 255 255 / 0.8);
    font-size: var(--text-lg);
  }
  .nocam-ic {
    width: 72px;
    height: 72px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: rgb(255 255 255 / 0.8);
    border: 1px solid rgb(255 255 255 / 0.3);
  }
  .nocam-row {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
    justify-content: center;
  }

  /* glass chrome over the photo, the same in both themes like any camera app */
  .glass {
    background: rgb(20 20 18 / 0.48);
    backdrop-filter: blur(12px) saturate(1.4);
    -webkit-backdrop-filter: blur(12px) saturate(1.4);
    border: 1px solid rgb(255 255 255 / 0.16);
    color: #fff;
  }
  .round {
    width: 42px;
    height: 42px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    flex: none;
    cursor: pointer;
    text-decoration: none;
    position: relative;
  }
  .round.big {
    width: 52px;
    height: 52px;
  }
  .round:hover {
    text-decoration: none;
    background: rgb(40 40 36 / 0.6);
  }
  .bar {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: calc(env(safe-area-inset-top) + var(--space-3)) var(--space-4) var(--space-6);
    background: linear-gradient(to bottom, rgb(0 0 0 / 0.55), transparent);
    pointer-events: none;
  }
  .bar > * {
    pointer-events: auto;
  }
  .ttl {
    flex: 1;
    min-width: 0;
    font-size: var(--text-lg);
    font-weight: var(--font-weight-bold);
    text-shadow: 0 1px 6px rgb(0 0 0 / 0.5);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .bar-gap {
    width: 42px;
  }
  .seg {
    display: flex;
    padding: 3px;
    border-radius: var(--radius-full);
    gap: 2px;
  }
  .seg button {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: 0;
    background: transparent;
    color: rgb(255 255 255 / 0.85);
    font-weight: var(--font-weight-semibold);
    font-size: var(--text-md);
    padding: 7px 12px;
    border-radius: var(--radius-full);
    min-height: 36px;
    transition: background-color var(--dur-fast) var(--ease-standard);
  }
  .seg button.on {
    background: var(--primary);
    color: var(--on-primary);
  }
  .seg button:last-child.on {
    background: var(--error);
    color: #fff;
  }

  .toast {
    position: absolute;
    left: 50%;
    top: calc(env(safe-area-inset-top) + 72px);
    transform: translateX(-50%);
    max-width: calc(100vw - 32px);
    margin: 0;
    padding: 8px 14px;
    border-radius: var(--radius-btn);
    background: color-mix(in srgb, var(--error) 88%, black);
    color: #fff;
    font-size: var(--text-md);
    font-weight: var(--font-weight-semibold);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 12px;
  }
  .toast-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 10px;
    border: 1px solid rgba(255, 255, 255, 0.55);
    border-radius: var(--radius-btn);
    background: rgba(255, 255, 255, 0.14);
    color: #fff;
    font: inherit;
    cursor: pointer;
  }

  .controls {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: var(--space-8) var(--space-5) calc(env(safe-area-inset-bottom) + var(--space-6));
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-4);
    background: linear-gradient(to top, rgb(0 0 0 / 0.6), transparent);
    pointer-events: none;
  }
  .controls > * {
    pointer-events: auto;
  }
  .hint {
    margin: 0;
    padding: 7px 14px;
    border-radius: var(--radius-full);
    background: rgb(20 20 18 / 0.5);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    font-size: var(--text-md);
    font-weight: var(--font-weight-semibold);
    text-align: center;
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .hint.working {
    color: var(--primary);
    font-size: var(--text-base);
    padding: 10px 18px;
  }
  .ctl-row {
    width: 100%;
    max-width: 420px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .ctl-row:has(> :only-child) {
    justify-content: center;
  }
  .shutter {
    width: 78px;
    height: 78px;
    border-radius: 50%;
    border: 4px solid #fff;
    background: transparent;
    padding: 5px;
    display: grid;
    place-items: center;
    box-shadow: 0 0 0 1px rgb(0 0 0 / 0.25);
  }
  .shutter span {
    display: block;
    width: 100%;
    height: 100%;
    border-radius: 50%;
    background: #fff;
    transition: transform var(--t-press) ease, background-color var(--dur-fast) var(--ease-standard);
  }
  .shutter:not(:disabled):hover span {
    background: color-mix(in srgb, var(--primary) 30%, white);
  }
  .shutter:not(:disabled):active span {
    transform: scale(0.88);
  }
  .shutter:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .gone {
    visibility: hidden;
  }
  .badge {
    position: absolute;
    top: -4px;
    right: -4px;
    min-width: 20px;
    height: 20px;
    padding: 0 5px;
    border-radius: var(--radius-md);
    background: var(--primary);
    color: var(--on-primary);
    font-size: var(--text-xs);
    font-weight: var(--font-weight-bold);
    display: grid;
    place-items: center;
  }
  .pill-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 10px 16px;
    border-radius: var(--radius-full);
    font-weight: var(--font-weight-semibold);
  }

  /* bottom sheet: themed surface */
  .panel {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    margin: 0 auto;
    max-width: 560px;
    background: var(--surface-container);
    color: var(--on-surface);
    border: var(--border-width) solid var(--outline-variant);
    border-bottom: 0;
    border-radius: 18px 18px 0 0;
    padding: var(--space-4) var(--space-4) calc(env(safe-area-inset-bottom) + var(--space-4));
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    box-shadow: 0 -10px 40px rgb(0 0 0 / 0.45);
    animation: rise 380ms var(--ease-settle);
  }
  @keyframes rise {
    from {
      transform: translateY(40%);
      opacity: 0;
    }
  }
  .panel p {
    margin: 0;
  }
  /* the cut-out and its 3D sticker share one box; the cut-out fades as the relief rises */
  .lift {
    position: relative;
    height: clamp(140px, 24dvh, 200px);
    margin: calc(-1 * var(--space-1)) calc(-1 * var(--space-2)) 0;
    border-radius: var(--radius-lg);
    background: var(--surface-high);
    overflow: hidden;
  }
  .cut {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    transition:
      opacity var(--dur-slow) var(--ease-standard),
      transform var(--dur-slow) var(--ease-standard);
    filter: drop-shadow(0 6px 12px rgb(0 0 0 / 0.35));
  }
  .cut.up {
    opacity: 0;
    transform: translateY(-10px) scale(0.92);
  }
  .models {
    position: absolute;
    left: 8px;
    top: 8px;
    right: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    pointer-events: none;
  }
  .mchip {
    padding: 2px 8px;
    border-radius: var(--radius-full);
    font-size: var(--text-xs);
    font-weight: var(--font-weight-semibold);
    background: color-mix(in srgb, var(--surface-container) 85%, transparent);
    color: var(--on-surface-var);
    border: 1px solid var(--outline-variant);
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dims {
    font-weight: var(--font-weight-regular);
    text-transform: none;
    color: var(--on-surface-var);
  }
  .icon-btn {
    flex: none;
    padding-left: 14px;
    padding-right: 14px;
  }
  .figure {
    align-self: center;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: 0;
    background: transparent;
    color: var(--primary);
    font: inherit;
    font-weight: var(--font-weight-semibold);
    font-size: var(--text-md);
    padding: 4px 10px;
    margin-top: calc(-1 * var(--space-1));
    cursor: pointer;
  }
  .figure:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .name-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .name {
    flex: 1;
    min-width: 0;
    font-size: var(--text-xl);
    font-weight: var(--font-weight-bold);
    padding: 8px 10px;
    border-radius: var(--radius-field);
    border: var(--border-width) solid transparent;
    background: var(--surface-high);
    color: var(--on-surface);
  }
  .name:focus {
    border-color: var(--primary);
    outline: none;
  }
  .busy {
    color: var(--primary);
    font-size: var(--text-2xl);
  }
  .err {
    color: var(--error);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .scroll,
  .sizes {
    display: flex;
    gap: var(--space-2);
  }
  .scroll {
    overflow-x: auto;
    scrollbar-width: none;
    margin: 0 calc(-1 * var(--space-4));
    padding: 0 var(--space-4);
  }
  .scroll .chip {
    flex: none;
    white-space: nowrap;
  }
  .sizes .chip {
    flex: 1;
    text-align: center;
    justify-content: center;
  }
  .acts {
    display: flex;
    gap: var(--space-2);
  }
  .acts .grow {
    flex: 1;
  }
  .done {
    display: flex;
    gap: var(--space-3);
    align-items: flex-start;
  }
  .done strong {
    font-size: var(--text-xl);
  }
  .tick {
    flex: none;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: var(--primary);
    color: var(--on-primary);
    display: grid;
    place-items: center;
    animation: pop 420ms var(--ease-pop);
  }
  @keyframes pop {
    from {
      transform: scale(0.4);
    }
  }
  @media (max-width: 400px) {
    .seg span {
      display: none;
    }
    .acts .btn:not(.grow) {
      padding-left: 12px;
      padding-right: 12px;
    }
  }
  @media (min-width: 720px) {
    .panel {
      bottom: var(--space-4);
      border-radius: var(--radius-xl);
      border-bottom: var(--border-width) solid var(--outline-variant);
    }
  }
</style>
