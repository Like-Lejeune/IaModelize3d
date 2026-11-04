<script lang="ts">
  // A new spare-part request: the part on an A4 sheet (camera or file), the rating plate, a voice note, a few
  // fields. With ?project=<id> it orders a model made in the studio instead: no design step, straight to the slicer.
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Header from '$lib/components/Header.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { api } from '$lib/api';
  import { projectTitle, t } from '$lib/i18n.svelte';
  import { intentKey, shop, shopError } from '$lib/shop/api';
  import { kzt, moneyRange, st } from '$lib/shop/i18n';
  import type { DeliveryMethod, Quote, Tariff } from '$lib/shop/types';
  import type { ProjectDetail } from '$lib/types';

  const projectId = $derived(page.url.searchParams.get('project'));

  let tariff = $state<Tariff | null>(null);
  let parts = $state<{ file: File; url: string }[]>([]);
  let plate = $state<{ file: File; url: string } | null>(null);
  let voice = $state<{ blob: Blob; url: string; secs: number } | null>(null);
  let text = $state('');
  let appliance = $state('');
  let partNumber = $state('');
  let quantity = $state<number | null>(null);
  let material = $state('');
  let delivery = $state<DeliveryMethod>('courier');
  let contact = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);

  let project = $state<ProjectDetail | null>(null);
  let projectError = $state<string | null>(null);
  let projectTry = $state(0);
  let instant = $state<Quote | null>(null);
  let instantError = $state<string | null>(null);

  // the voice note
  let rec: MediaRecorder | null = null;
  let mic: MediaStream | null = null;
  let recording = $state(false);
  let recStart = 0;
  let tick = $state(0);
  let timer: ReturnType<typeof setInterval> | undefined;

  const ready = $derived(
    !busy && (!!projectId ? !!project?.version : parts.length > 0 || !!plate || !!voice || !!(text.trim() || appliance.trim() || partNumber.trim())),
  );

  onMount(() => {
    shop.tariff().then((t) => (tariff = t)).catch(() => {});
    // the studio's "Get a quote" passes the material it priced
    const m = page.url.searchParams.get('material')?.toUpperCase();
    if (m && ['PLA', 'PETG', 'ASA', 'TPU'].includes(m)) material = m;
  });

  $effect(() => {
    const id = projectId;
    void projectTry;
    project = null;
    projectError = null;
    if (!id) return;
    api.project(id).then((p) => (project = p)).catch((e) => (projectError = shopError(e)));
  });

  // the same request sent again (a lost answer) is the same order; a changed form is a new one
  let requestKey: string | null = null;
  $effect(() => {
    void [text, appliance, partNumber, quantity, material, delivery, contact, projectId, parts, plate, voice];
    requestKey = null;
  });

  // the instant range of a studio model, again whenever the quantity, material or delivery change
  $effect(() => {
    const id = projectId;
    const o = { quantity: quantity || 1, material: material || 'PLA', delivery };
    if (!id) return;
    const h = setTimeout(() => {
      shop
        .instantQuote(id, o)
        .then((q) => ((instant = q), (instantError = null)))
        .catch((e) => ((instant = null), (instantError = shopError(e))));
    }, 250);
    return () => clearTimeout(h);
  });

  function addParts(list: FileList | null) {
    const add = Array.from(list ?? [])
      .filter((f) => f.type.startsWith('image/'))
      .map((file) => ({ file, url: URL.createObjectURL(file) }));
    parts = [...parts, ...add].slice(0, 6);
  }
  function setPlate(list: FileList | null) {
    const f = list?.[0];
    if (!f) return;
    if (plate) URL.revokeObjectURL(plate.url);
    plate = { file: f, url: URL.createObjectURL(f) };
  }
  function dropPart(i: number) {
    URL.revokeObjectURL(parts[i].url);
    parts = parts.filter((_, j) => j !== i);
  }

  async function toggleRecord() {
    if (recording && rec) {
      rec.stop();
      return;
    }
    error = null;
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
        clearInterval(timer);
        const blob = new Blob(chunks, { type: rec?.mimeType || 'audio/webm' });
        if (voice) URL.revokeObjectURL(voice.url);
        voice = blob.size ? { blob, url: URL.createObjectURL(blob), secs: Math.round((Date.now() - recStart) / 1000) } : null;
      };
      rec.start();
      recording = true;
      recStart = Date.now();
      tick = 0;
      timer = setInterval(() => (tick = Math.round((Date.now() - recStart) / 1000)), 500);
    } catch (e: any) {
      mic?.getTracks().forEach((tr) => tr.stop());
      mic = null;
      error = st(e?.name === 'NotAllowedError' || e?.name === 'SecurityError' ? 'new.mic_denied' : 'new.mic_unavailable');
    }
  }
  function dropVoice() {
    if (voice) URL.revokeObjectURL(voice.url);
    voice = null;
  }

  onDestroy(() => {
    if (rec && rec.state !== 'inactive') rec.stop();
    mic?.getTracks().forEach((tr) => tr.stop());
    clearInterval(timer);
    parts.forEach((p) => URL.revokeObjectURL(p.url));
    if (plate) URL.revokeObjectURL(plate.url);
    if (voice) URL.revokeObjectURL(voice.url);
  });

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!ready) {
      if (!projectId) error = st('new.need_something');
      return;
    }
    busy = true;
    error = null;
    requestKey ??= intentKey();
    try {
      const o = await shop.request({
        text,
        appliance,
        part_number: partNumber,
        quantity: quantity && quantity > 0 ? Math.min(200, Math.round(quantity)) : null,
        material: material || null,
        delivery,
        contact,
        project_id: projectId,
        files: parts.map((p) => p.file),
        plate: plate?.file ?? null,
        voice: voice?.blob ?? null,
      }, requestKey);
      goto(`/orders/${o.id}`);
    } catch (err) {
      error = shopError(err);
      busy = false;
    }
  }

  const secs = (n: number) => `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`;
</script>

<svelte:head><title>{st(projectId ? 'new.from_project' : 'new.title')} · Formwright</title></svelte:head>

<div class="page">
  <Header />
  <main class="wrap">
    <a class="back small" href="/parts"><Icon name="arrow-left" size={15} /> {st('parts.title')}</a>
    <div class="intro">
      <h1>{st(projectId ? 'new.from_project' : 'new.title')}</h1>
      <p class="muted">{projectId ? st('new.project_hint') : st('new.lead')}</p>
      {#if !projectId}
        <ol class="steps xs">
          {#each ['new.step1', 'new.step2', 'new.step3', 'new.step4'] as s, i (s)}<li><span>{i + 1}</span>{st(s)}</li>{/each}
        </ol>
      {/if}
    </div>

    <form class="form" onsubmit={submit}>
      {#if projectId}
        <section class="card proj">
          {#if project?.cover}<img src={project.cover} alt="" />{:else}<span class="ph"><Icon name="cube" size={28} /></span>{/if}
          <div class="stack">
            <strong>{project ? projectTitle(project.title) : projectError ? '' : '…'}</strong>
            {#if projectError}<span class="xs err" role="alert">{projectError} <button type="button" class="btn small" onclick={() => projectTry++}>{t('retry')}</button></span>{/if}
            {#if instant?.range}
              <span class="price">≈ {moneyRange(instant.range.total, instant.range.total_usd)}</span>
              <span class="xs muted">{st('quote.estimate_hint')}</span>
            {:else if instantError}
              <span class="xs muted">{instantError}</span>
            {/if}
            <a class="xs" href="/p/{projectId}">{st('order.studio')} ↗</a>
          </div>
        </section>
      {:else}
        <section class="shots">
          <div class="tile card main-shot" class:filled={parts.length > 0}>
            <div class="tile-head">
              <!-- the part lying flat on the sheet, the camera straight above it -->
              <svg class="a4" viewBox="0 0 42 56" aria-hidden="true">
                <rect x="1" y="1" width="40" height="54" rx="1.5" class="sheet" />
                <path d="M14 22c0-4 4-6 7-6s7 2 7 6v10c0 4-3 7-7 7s-7-3-7-7z" class="partshape" />
                <circle cx="21" cy="27" r="2.6" class="hole" />
                <path d="M4 50h34M4 48v4M38 48v4" class="dim" />
              </svg>
              <div class="stack">
                <strong>{st('new.part_photo')}</strong>
                <span class="xs muted">{st('new.part_hint')}</span>
              </div>
            </div>
            {#if parts.length}
              <div class="thumbs">
                {#each parts as p, i (p.url)}
                  <span class="thumb"><img src={p.url} alt="" /><button type="button" class="x" onclick={() => dropPart(i)} aria-label={st('new.remove')}><Icon name="x" size={12} /></button></span>
                {/each}
              </div>
            {/if}
            <div class="row">
              <label class="btn small primary">
                <Icon name="camera" size={15} /> {st('new.add_photo')}
                <input class="sr-only" type="file" accept="image/*" capture="environment" onchange={(e) => addParts((e.currentTarget as HTMLInputElement).files)} />
              </label>
              <label class="btn small ghost">
                <Icon name="image" size={15} />
                <span class="sr-only">{st('new.add_photo')}</span>
                <input class="sr-only" type="file" accept="image/*" multiple onchange={(e) => addParts((e.currentTarget as HTMLInputElement).files)} />
              </label>
            </div>
          </div>

          <div class="tile card" class:filled={!!plate}>
            <div class="tile-head">
              <span class="ic"><Icon name="scan" size={20} /></span>
              <div class="stack">
                <strong>{st('new.plate_photo')}</strong>
                <span class="xs muted">{st('new.plate_hint')}</span>
              </div>
            </div>
            {#if plate}
              <span class="thumb wide"><img src={plate.url} alt="" /><button type="button" class="x" onclick={() => (URL.revokeObjectURL(plate!.url), (plate = null))} aria-label={st('new.remove')}><Icon name="x" size={12} /></button></span>
            {/if}
            <label class="btn small">
              <Icon name="camera" size={15} /> {st('new.add_photo')}
              <input class="sr-only" type="file" accept="image/*" capture="environment" onchange={(e) => setPlate((e.currentTarget as HTMLInputElement).files)} />
            </label>
          </div>

          <div class="tile card" class:filled={!!voice} class:live={recording}>
            <div class="tile-head">
              <span class="ic"><Icon name="mic" size={20} /></span>
              <div class="stack">
                <strong>{st('new.voice')}</strong>
                <span class="xs muted">{st('new.voice_hint')}</span>
              </div>
            </div>
            {#if voice && !recording}
              <audio src={voice.url} controls preload="metadata"></audio>
            {/if}
            <div class="row">
              <button type="button" class="btn small" class:primary={recording} onclick={toggleRecord}>
                {#if recording}<Icon name="stop" size={14} /> {st('new.stop')} <span class="mono">{secs(tick)}</span>{:else}<Icon name="mic" size={15} /> {st('new.record')}{/if}
              </button>
              <!-- its length: a phone's narrow player has no room for its own time -->
              {#if voice && !recording}<span class="xs muted mono">{secs(voice.secs)}</span><button type="button" class="btn small ghost" onclick={dropVoice}>{st('new.remove')}</button>{/if}
            </div>
          </div>
        </section>

        <label class="field">{st('new.text')}<textarea rows="2" bind:value={text} placeholder={st('new.text_ph')} maxlength="2000"></textarea></label>
        <div class="two">
          <label class="field">{st('new.appliance')}<input type="text" bind:value={appliance} placeholder="Bosch SMS46GI01E" maxlength="120" /></label>
          <label class="field">{st('new.part_number')}<input type="text" bind:value={partNumber} placeholder="00611475" maxlength="60" /></label>
        </div>
      {/if}

      {#if projectId}
        <label class="field">{st('new.comment')}<input type="text" bind:value={text} maxlength="2000" /></label>
      {/if}
      <div class="three">
        <label class="field">{st('new.quantity')}<input type="number" min="1" max="200" bind:value={quantity} placeholder={projectId ? '1' : st('new.qty_auto')} /></label>
        <label class="field">{st('new.material')}
          <select bind:value={material}>
            <option value="">{st('new.material_auto')}</option>
            {#each tariff?.materials ?? ['PLA', 'PETG', 'ASA', 'TPU'] as m (m)}<option value={m}>{m}</option>{/each}
          </select>
        </label>
        <label class="field">{st('new.delivery')}
          <select bind:value={delivery}>
            {#each ['courier', 'post', 'pickup'] as const as d (d)}
              <option value={d}>{st(`delivery.${d}`)}{tariff ? ` · ${tariff.delivery[d].price ? kzt(tariff.delivery[d].price) : '0 ₸'}` : ''}</option>
            {/each}
          </select>
        </label>
      </div>
      <label class="field">{st('new.contact')}
        <input type="text" bind:value={contact} placeholder="+7 7__ ___ __ __" maxlength="200" autocomplete="tel" />
        <span class="hint xs">{st('new.contact_hint')}</span>
      </label>

      {#if error}<p class="err small" role="alert">{error}</p>{/if}
      <button class="btn primary large block" disabled={busy || (!!projectId && !project?.version)}>
        {#if busy}<i class="ti ti-loader-2 spin" aria-hidden="true"></i> {voice ? st('new.sending_voice') : st('new.sending')}{:else}<Icon name="send" size={17} /> {st('new.submit')}{/if}
      </button>
      <p class="xs muted safety"><Icon name="alert" size={13} /> {st('new.safety')}</p>
    </form>
  </main>
</div>

<style>
  .page {
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
  }
  .wrap {
    width: 100%;
    max-width: var(--container-narrow);
    margin: 0 auto;
    padding: var(--space-5) var(--space-5) var(--space-8);
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .back {
    color: var(--outline);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    align-self: flex-start;
    text-decoration: none;
  }
  .intro {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  h1 {
    font-size: var(--text-3xl);
    font-weight: var(--font-weight-semibold);
  }
  .intro p {
    margin: 0;
    max-width: 600px;
  }
  .steps {
    list-style: none;
    margin: var(--space-1) 0 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px var(--space-4);
    color: var(--on-surface-var);
  }
  .steps li {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .steps span {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: color-mix(in srgb, var(--primary) 16%, transparent);
    color: var(--primary);
    font-weight: var(--font-weight-bold);
    font-size: var(--text-xs);
  }
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .shots {
    display: grid;
    grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--space-3);
  }
  .tile {
    padding: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    justify-content: space-between;
    border-style: dashed;
    transition: border-color var(--dur-fast) var(--ease-standard);
  }
  .tile.filled {
    border-style: solid;
    border-color: color-mix(in srgb, var(--primary) 45%, var(--outline-variant));
  }
  .tile.live {
    border-color: var(--error);
  }
  .tile-head {
    display: flex;
    gap: var(--space-3);
    align-items: flex-start;
  }
  .tile-head .stack {
    gap: 2px;
    min-width: 0;
  }
  .tile-head strong {
    font-size: var(--text-base);
  }
  .a4 {
    flex: none;
    width: 36px;
    height: 48px;
  }
  .sheet {
    fill: #f6f6f3;
    stroke: var(--outline);
    stroke-width: 1;
  }
  .partshape {
    fill: var(--primary);
    opacity: 0.85;
  }
  .hole {
    fill: #f6f6f3;
  }
  .dim {
    stroke: var(--info);
    stroke-width: 1;
    fill: none;
  }
  .ic {
    flex: none;
    width: 36px;
    height: 36px;
    border-radius: var(--radius-btn);
    display: grid;
    place-items: center;
    color: var(--primary);
    background: color-mix(in srgb, var(--primary) 12%, transparent);
  }
  .thumbs {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .thumb {
    position: relative;
    width: 64px;
    height: 64px;
    border-radius: var(--radius-btn);
    overflow: hidden;
    background: #000;
  }
  .thumb.wide {
    width: 100%;
    height: 72px;
  }
  .thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .x {
    position: absolute;
    top: 3px;
    right: 3px;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: none;
    display: grid;
    place-items: center;
    background: rgb(0 0 0 / 0.6);
    color: #fff;
    cursor: pointer;
  }
  audio {
    width: 100%;
    height: 36px;
  }
  label.btn {
    align-self: flex-start;
  }
  .two {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-3);
  }
  .three {
    display: grid;
    grid-template-columns: minmax(0, 0.8fr) minmax(0, 1fr) minmax(0, 1.5fr);
    gap: var(--space-3);
  }
  .field input,
  .field select,
  .field textarea {
    width: 100%;
  }
  .hint {
    color: var(--outline);
    font-weight: var(--font-weight-regular);
  }
  .proj {
    padding: var(--space-3);
    display: flex;
    gap: var(--space-4);
    align-items: center;
  }
  .proj img,
  .proj .ph {
    flex: none;
    width: 96px;
    height: 96px;
    border-radius: var(--radius-btn);
    object-fit: contain;
    background: #f6f6f3;
    display: grid;
    place-items: center;
    color: var(--outline);
  }
  .proj .stack {
    gap: 4px;
    min-width: 0;
  }
  .price {
    font-size: var(--text-xl);
    font-weight: var(--font-weight-bold);
  }
  .err {
    color: var(--error);
    margin: 0;
  }
  .safety {
    margin: 0;
    display: flex;
    gap: 6px;
    align-items: baseline;
  }
  @media (max-width: 640px) {
    .shots {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    }
    .main-shot {
      grid-column: 1 / -1;
    }
    .three {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .three label:last-child {
      grid-column: 1 / -1;
    }
  }
  @media (max-width: 520px) {
    .wrap {
      padding: var(--space-4) var(--space-4) var(--space-7);
    }
    .two {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
