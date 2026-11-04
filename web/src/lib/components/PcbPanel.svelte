<script lang="ts">
  // The project's PCB (contract C8). part 'stage' is the big picture over the 3D view: the schematic, both
  // copper sides and the board in 3D (board.glb), with the autorouter's frames played over the top copper,
  // live from 'pcb.route' while a build routes. part 'side' is the tab: counts, DRC and intent checks, the fab
  // files, and the next steps that hand the board back to the agent (a case for it, a printed mock-up).
  import * as THREE from 'three';
  import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
  import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
  import Icon from './Icon.svelte';
  import { FAB_FILES, framePath } from '$lib/pcb/api';
  import { sayError, sayIntent, sayLimit, sayWarning } from '$lib/pcb/notes';
  import { i18n, plural, t } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import type { RouteFrame } from '$lib/types';

  // caseActions: the "make a case" asks; a device's case comes with every build, so its workspace leaves them out.
  // replays: play a version's stored routing frames on show; a workspace that only wants the board leaves it off (the
  // frames of a build routing right now are always drawn)
  let { store, part, onSend, caseActions = true, replays = true }: {
    store: ProjectStore; part: 'stage' | 'side'; onSend?: (text: string) => void; caseActions?: boolean; replays?: boolean;
  } = $props();

  const pcb = $derived(store.pcb);
  const v = $derived(pcb.current);
  const art = $derived(v?.artifacts ?? {});
  const live = $derived(pcb.live);
  const drc = $derived(pcb.drc);
  const frames = $derived(pcb.frames);

  // ---------------------------------------------------------------- stage
  type View = 'schematic' | 'top' | 'bottom' | '3d';
  const VIEWS: { id: View; file: string }[] = [
    { id: 'schematic', file: 'schematic.svg' },
    { id: 'top', file: 'pcb_top.svg' },
    { id: 'bottom', file: 'pcb_bottom.svg' },
    { id: '3d', file: 'board.glb' },
  ];
  let view = $state<View>('top');
  // the drawings zoom with the wheel or a double click and pan by dragging once zoomed
  let zoom = $state({ k: 1, x: 0, y: 0 });
  let picEl = $state<HTMLDivElement>();
  let pan: { id: number; x: number; y: number; zx: number; zy: number } | null = null;
  const flat = $derived(!live && !!v && view !== '3d');

  function zoomAt(px: number, py: number, k: number) {
    k = Math.min(8, Math.max(1, k));
    zoom = k === 1 ? { k: 1, x: 0, y: 0 } : { k, x: px - (px - zoom.x) * (k / zoom.k), y: py - (py - zoom.y) * (k / zoom.k) };
  }
  // wheel listeners must not be passive to keep the page from scrolling
  $effect(() => {
    const el = picEl;
    if (!el || !flat) return;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, zoom.k * Math.exp(-e.deltaY * 0.0015));
    };
    el.addEventListener('wheel', wheel, { passive: false });
    return () => el.removeEventListener('wheel', wheel);
  });
  function onDbl(e: MouseEvent) {
    const r = picEl!.getBoundingClientRect();
    zoomAt(e.clientX - r.left, e.clientY - r.top, zoom.k > 1 ? 1 : 2.5);
  }
  function onDown(e: PointerEvent) {
    if (!flat || zoom.k === 1) return;
    pan = { id: e.pointerId, x: e.clientX, y: e.clientY, zx: zoom.x, zy: zoom.y };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }
  function onMove(e: PointerEvent) {
    if (!pan || pan.id !== e.pointerId) return;
    zoom = { ...zoom, x: pan.zx + e.clientX - pan.x, y: pan.zy + e.clientY - pan.y };
  }
  function pickView(id: View) {
    view = id;
    zoom = { k: 1, x: 0, y: 0 };
    stop();
  }
  const views = $derived(VIEWS.filter((x) => art[x.file]));
  const topMap = $derived(frames?.svg_map?.['pcb_top.svg'] ?? null);

  // replay of the stored frames over the top copper: `step` frames are on, the last one drawing itself in
  let step = $state(0);
  let playing = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let replayed = 0;
  let arrivedSeen = 0;

  function stop() {
    if (timer) clearTimeout(timer);
    timer = null;
    playing = false;
  }

  // the frames worth watching: one the router left as it was (a pass that changed nothing) adds a still to the replay
  const played = $derived.by<RouteFrame[]>(() => {
    const out: RouteFrame[] = [];
    for (const f of frames?.frames ?? []) {
      const prev = out[out.length - 1];
      if (!prev || prev.lines.length !== f.lines.length || prev.lines.some((l, i) => l.some((x, j) => x !== f.lines[i][j]))) out.push(f);
    }
    return out;
  });
  // the replay takes about REPLAY_MS whatever the number of frames, and a frame's traces draw in turn over its share
  const REPLAY_MS = 4500;
  const frameMs = $derived(Math.max(700, REPLAY_MS / Math.max(1, played.length)));
  const drawMs = $derived(Math.round(Math.min(900, frameMs * 0.4)));

  function replay() {
    const n = played.length;
    if (!n || !topMap) return;
    stop();
    view = 'top';
    zoom = { k: 1, x: 0, y: 0 };
    playing = true;
    step = 0;
    const tick = () => {
      step++;
      timer = step < n ? setTimeout(tick, frameMs) : setTimeout(() => (playing = false), frameMs + 1400);
    };
    timer = setTimeout(tick, 250);
  }

  // once per version on show, and again when a version arrives live
  $effect(() => {
    if (part !== 'stage' || !replays || !frames?.frames.length || !topMap || !v) return;
    const arrived = pcb.arrived;
    if (replayed === v.version && arrived === arrivedSeen) return;
    replayed = v.version;
    arrivedSeen = arrived;
    replay();
  });
  $effect(() => () => stop());

  const shownFrames = $derived.by<RouteFrame[]>(() => {
    if (live) return live.frames;
    return playing ? played.slice(0, step) : [];
  });
  // the earlier frames faint, the newest bright
  const trail = $derived.by(() => {
    const fs = shownFrames;
    if (!fs.length) return { old: '', now: '' };
    const m = live ? [1, 0, 0, -1, 0, live.h ?? 0] : topMap?.matrix;
    const prev = fs.length > 1 ? fs[fs.length - 2] : null;
    return { old: prev ? framePath(prev.lines, m) : '', now: framePath(fs[fs.length - 1].lines, m) };
  });
  // a replayed frame's traces in CHUNKS groups, each drawing a moment after the one before
  const CHUNKS = 12;
  const chunks = $derived.by(() => {
    const fs = shownFrames;
    if (live || !fs.length || !topMap) return [];
    const lines = fs[fs.length - 1].lines;
    const size = Math.max(1, Math.ceil(lines.length / CHUNKS));
    const out: string[] = [];
    for (let i = 0; i < lines.length; i += size) out.push(framePath(lines.slice(i, i + size), topMap.matrix));
    return out;
  });
  const liveProgress = $derived(live?.progress != null ? Math.round(live.progress * 100) : null);
  // route strokes about 0.15 mm wide, in the drawing's own units (mm live, SVG pixels over the copper)
  const unit = $derived(live ? 1 : (topMap?.matrix[0] ?? 1));

  // ---- the board in 3D (board.glb, mapped into fw.board/1 mm by glb_map)
  let canvas3d = $state<HTMLCanvasElement>();
  let glbState = $state<'loading' | 'ready' | 'error'>('loading');
  $effect(() => {
    const url = art['board.glb'];
    const c = canvas3d;
    const m = frames?.glb_map?.matrix ?? null;
    if (part !== 'stage' || view !== '3d' || !url || !c) return;
    return mount3d(c, url, m);
  });

  function mount3d(canvas: HTMLCanvasElement, url: string, matrix: number[][] | null): () => void {
    glbState = 'loading';
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, devicePixelRatio));
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.5, 5000);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 1.1;
    controls.addEventListener('start', () => (controls.autoRotate = false));
    scene.add(new THREE.HemisphereLight(0xffffff, 0x5a5a5a, 1.7));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(-60, -110, 160);
    scene.add(sun);
    let gone = false;
    let root: THREE.Object3D | null = null;
    new GLTFLoader().load(
      url,
      (gltf) => {
        if (gone) return;
        root = gltf.scene;
        // the GLB is Y-up around the board's centre; glb_map puts it in the board frame (z up, mm)
        if (matrix?.length === 4) root.applyMatrix4(new THREE.Matrix4().fromArray(matrix.flat()).transpose());
        else root.rotation.x = Math.PI / 2;
        scene.add(root);
        const box = new THREE.Box3().setFromObject(root);
        const c = box.getCenter(new THREE.Vector3());
        const r = box.getSize(new THREE.Vector3()).length() / 2 || 30;
        controls.target.copy(c);
        camera.position.copy(c).add(new THREE.Vector3(0.55, -1.1, 0.95).normalize().multiplyScalar(r * 2.7));
        camera.near = Math.max(0.1, r / 60);
        camera.far = r * 120;
        camera.updateProjectionMatrix();
        glbState = 'ready';
      },
      undefined,
      () => !gone && (glbState = 'error'),
    );
    const resize = () => {
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();
    renderer.setAnimationLoop(() => {
      controls.update();
      renderer.render(scene, camera);
    });
    return () => {
      gone = true;
      ro.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      root?.traverse((o: any) => {
        o.geometry?.dispose?.();
        for (const m of Array.isArray(o.material) ? o.material : o.material ? [o.material] : []) {
          for (const k of Object.keys(m)) if (m[k]?.isTexture) m[k].dispose();
          m.dispose();
        }
      });
      renderer.dispose();
    };
  }

  // ---------------------------------------------------------------- side
  const counts = $derived(v?.counts ?? drc?.counts ?? {});
  const errors = $derived(drc?.errors ?? []);
  const warnings = $derived(drc?.warnings ?? []);
  const intentIssues = $derived(drc?.intent?.issues ?? []);
  const limitIssues = $derived(drc?.limits?.issues ?? []);
  const errCount = $derived(drc ? errors.length : (v?.drc.errors ?? 0));
  const ready = $derived(!!v && errCount === 0 && v.intent_ok && v.limits_ok !== false);
  // the engine writes English for the agent: rows say it in the person's language, the original stays in the tooltip
  type Row = { key: string; text: string; raw: string; about?: string | null; hint?: string | null };
  const rows = $derived.by<Row[]>(() => {
    const lang = i18n.lang;
    return [
      ...errors.map((e, i) => ({ key: `e${i}`, ...sayError(e, lang), hint: e.hint })),
      ...intentIssues.map((e, i) => ({ key: `i${i}`, ...sayIntent(e, lang), hint: e.hint })),
      ...limitIssues.map((e, i) => ({ key: `l${i}`, ...sayLimit(e, lang) })),
    ];
  });
  // warnings are not DRC errors: a board with DRC 0 lists them apart, folded, as the routing engine's notes
  const notes = $derived.by<Row[]>(() => warnings.map((w, i) => ({ key: `w${i}`, ...sayWarning(w, i18n.lang), hint: w.hint })));
  let notesOpen = $state(false);
  let open = $state<string | null>(null);
  const busy = $derived(store.running || store.replaying || store.readonly);
  const FILE_LABEL: Record<string, string> = { 'gerbers.zip': 'Gerber zip', 'bom.csv': 'BOM', 'cpl.csv': 'CPL' };
  // Only a clean build (0 DRC errors) gets fab files; a failing one keeps its previews for the picture.
  const fab = $derived(FAB_FILES.filter((f) => art[f]));
  const noFab = $derived.by(() => {
    if (!v || (fab.length && !errCount)) return null;
    const ru = i18n.lang === 'ru';
    if (errCount) {
      const n = plural(errCount, ['DRC error', 'DRC errors'], ['ошибка DRC', 'ошибки DRC', 'ошибок DRC']);
      return ru
        ? `У версии ${v.version} ${n}: Gerber, BOM и CPL делаются только из платы без ошибок DRC — фабрика такую плату не примет.`
        : `Version ${v.version} has ${n}: Gerber, BOM and CPL come only from a board with 0 DRC errors — a fab would reject this one.`;
    }
    return ru ? 'Экспорт файлов для фабрики не удался на этой сборке: попросите агента собрать плату ещё раз.' : 'The fab export failed on this build: ask the agent to build the board again.';
  });
</script>

{#if part === 'stage'}
  <div class="pstage">
    <div class="bar">
      {#if live}
        <span class="pill work"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('pcb_routing')}{liveProgress != null ? ` · ${liveProgress} %` : ''}</span>
      {:else if views.length}
        <div class="seg" role="tablist" aria-label={t('pcb')}>
          {#each views as x (x.id)}
            <button role="tab" aria-selected={view === x.id} onclick={() => pickView(x.id)}>{t(`pcb_${x.id}`)}</button>
          {/each}
        </div>
      {/if}
      <span class="spacer"></span>
      {#if v && !live}<span class="chip mono">v{v.version}</span>{/if}
    </div>

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="pic"
      class:paper={view === 'schematic' && !live}
      class:zoomed={flat && zoom.k > 1}
      bind:this={picEl}
      ondblclick={(e) => flat && onDbl(e)}
      onpointerdown={onDown}
      onpointermove={onMove}
      onpointerup={() => (pan = null)}
      onpointercancel={() => (pan = null)}
    >
      {#if live}
        {@const w = live.w ?? 50}
        {@const h = live.h ?? 50}
        <svg class="fit" viewBox="{-2} {-2} {w + 4} {h + 4}" preserveAspectRatio="xMidYMid meet" role="img" aria-label={t('pcb_routing')}>
          <rect class="board" x="0" y="0" width={w} height={h} rx="0.6" />
          {#if trail.old}<path class="route old" d={trail.old} stroke-width={0.1 * unit} />{/if}
          {#key live.frames.length}<path class="route now" d={trail.now} pathLength="1" stroke-width={0.16 * unit} />{/key}
        </svg>
      {:else if !v}
        <div class="empty">
          {#if !pcb.loaded}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="cpu" size={40} /><strong>{t('pcb_empty')}</strong>{/if}
        </div>
      {:else if view === 'schematic'}
        <div class="zoom" style:transform="translate({zoom.x}px, {zoom.y}px) scale({zoom.k})">
          <img class="fit" src={art['schematic.svg']} alt={t('pcb_schematic')} draggable="false" />
        </div>
      {:else if view === 'top' || view === 'bottom'}
        {@const file = view === 'top' ? 'pcb_top.svg' : 'pcb_bottom.svg'}
        {@const map = frames?.svg_map?.[file] ?? null}
        <div class="zoom" style:transform="translate({zoom.x}px, {zoom.y}px) scale({zoom.k})">
          {#if map}
            <svg class="fit" viewBox="0 0 {map.width} {map.height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label={t(`pcb_${view}`)}>
              <image href={art[file]} x="0" y="0" width={map.width} height={map.height} class="copper" class:under={playing && view === 'top'} />
              {#if view === 'top' && playing}
                {#if trail.old}<path class="route old" d={trail.old} stroke-width={0.1 * unit} />{/if}
                {#key step}
                  {#each chunks as d, i (i)}
                    <path class="route now" {d} pathLength="1" stroke-width={0.16 * unit} style:animation-delay="{Math.round((i * (frameMs - drawMs)) / chunks.length)}ms" style:animation-duration="{drawMs}ms" />
                  {/each}
                {/key}
              {/if}
            </svg>
          {:else}
            <img class="fit" src={art[file]} alt={t(`pcb_${view}`)} draggable="false" />
          {/if}
        </div>
      {:else}
        <canvas class="fit" bind:this={canvas3d} aria-label={t('pcb_3d')}></canvas>
        {#if glbState !== 'ready'}
          <div class="empty">{#if glbState === 'loading'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}{t('pcb_no_preview')}{/if}</div>
        {/if}
      {/if}
    </div>

    <div class="foot">
      {#if live}
        <span class="xs muted">{t('pcb_frame', { i: live.frames.length, n: live.total })}</span>
      {:else if replays && frames?.frames.length && topMap && (view === 'top' || playing)}
        <button class="btn small" onclick={replay} disabled={playing}><Icon name="play" size={14} /> {t('pcb_replay')}</button>
        {#if playing}<span class="xs muted">{t('pcb_frame', { i: Math.max(1, step), n: played.length })}</span>{/if}
      {/if}
      {#if v && !live}
        <span class="spacer"></span>
        <span class="chip" class:ok={ready} class:err={!ready}>
          <Icon name={ready ? 'check' : 'alert'} size={12} />
          {errCount ? plural(errCount, ['DRC error', 'DRC errors'], ['ошибка DRC', 'ошибки DRC', 'ошибок DRC']) : t('pcb_drc_ok')}
        </span>
      {/if}
    </div>
  </div>
{:else}
  <div class="pside">
    {#if !v}
      <div class="empty tall">
        {#if live}
          <i class="ti ti-loader-2 spin" aria-hidden="true"></i>
          <strong>{t('pcb_routing')}{live.progress != null ? ` · ${Math.round(live.progress * 100)} %` : ''}</strong>
        {:else if !pcb.loaded}
          <i class="ti ti-loader-2 spin" aria-hidden="true"></i>
        {:else}
          <Icon name="cpu" size={40} />
          <strong>{t('pcb_empty')}</strong>
          <p class="small muted">{t('pcb_empty_d')}</p>
        {/if}
      </div>
    {:else}
      <div class="head">
        <strong>{t('pcb_version', { v: v.version })}</strong>
        {#if pcb.versions.length > 1}
          <select class="ver" value={v.version} onchange={(e) => pcb.pick(Number((e.currentTarget as HTMLSelectElement).value))} aria-label={t('pcb_version', { v: v.version })}>
            {#each [...pcb.versions].reverse() as x (x.version)}<option value={x.version}>v{x.version}</option>{/each}
          </select>
        {/if}
      </div>

      <div class="sum" class:ok={ready} class:err={!ready}>
        <span class="light"><Icon name={ready ? 'check' : 'alert'} size={16} /></span>
        <div>
          <strong>{ready ? t('pcb_all_ok') : t('pcb_not_ready')}</strong>
          <div class="small">
            {errCount ? plural(errCount, ['DRC error', 'DRC errors'], ['ошибка DRC', 'ошибки DRC', 'ошибок DRC']) : t('pcb_drc_ok')}
            · {v.intent_ok ? t('pcb_intent_ok', { n: drc?.intent?.checked ?? 0 }) : t('pcb_intent_err')}
          </div>
        </div>
      </div>

      <div class="chips">
        <span class="chip">{t('pcb_layers')}</span>
        {#if counts.components != null}<span class="chip">{plural(counts.components, ['part', 'parts'], ['деталь', 'детали', 'деталей'])}</span>{/if}
        {#if counts.nets != null}<span class="chip">{plural(counts.nets, ['net', 'nets'], ['цепь', 'цепи', 'цепей'])}</span>{/if}
        {#if counts.traces != null}<span class="chip">{plural(counts.traces, ['trace', 'traces'], ['трасса', 'трассы', 'трасс'])}</span>{/if}
        {#if counts.vias != null}<span class="chip">{plural(counts.vias, ['via', 'vias'], ['переходное', 'переходных', 'переходных'])}</span>{/if}
        <span class="chip" class:ok={!errCount} class:err={!!errCount}>{plural(errCount, ['DRC error', 'DRC errors'], ['ошибка DRC', 'ошибки DRC', 'ошибок DRC'])}</span>
      </div>

      {#snippet issue(r: Row, sev: 'error' | 'note')}
        <li class={sev}>
          <button class="g" aria-expanded={open === r.key} title={r.raw} onclick={() => (open = open === r.key ? null : r.key)}>
            <span class="dot" aria-hidden="true"></span>
            <span class="ttl">{r.text}</span>
          </button>
          {#if open === r.key}
            <div class="detail small">
              {#if r.about}<p>{r.about}</p>{/if}
              {#if r.raw !== r.text}<p class="raw"><span class="xs muted">{i18n.lang === 'ru' ? 'Текст движка' : 'Engine text'}</span> <span class="mono">{r.raw}</span></p>{/if}
              {#if r.hint}<p><span class="xs muted">{t('pcb_hint')}</span> {r.hint}</p>{/if}
            </div>
          {/if}
        </li>
      {/snippet}

      {#if rows.length}
        <ul class="groups">
          {#each rows as r (r.key)}{@render issue(r, 'error')}{/each}
        </ul>
      {/if}

      {#if notes.length}
        <section class="notes">
          <button class="nh small" aria-expanded={notesOpen} onclick={() => (notesOpen = !notesOpen)}>
            <span class="chev" class:open={notesOpen}><Icon name="chevron" size={12} /></span>
            <span class="ttl">{i18n.lang === 'ru' ? 'Заметки трассировщика' : 'Routing engine notes'} · {notes.length}</span>
            <span class="xs muted">{i18n.lang === 'ru' ? 'не ошибки DRC' : 'not DRC errors'}</span>
          </button>
          {#if notesOpen}
            <ul class="groups">
              {#each notes as r (r.key)}{@render issue(r, 'note')}{/each}
            </ul>
          {/if}
        </section>
      {/if}

      <section class="files">
        <h3 class="section-title">{t('pcb_files')}</h3>
        {#if noFab}
          <p class="nofab small"><Icon name="lock" size={14} /> <span>{noFab}</span></p>
          {#if onSend && errCount}
            <button class="btn small" disabled={busy} onclick={() => onSend?.(i18n.lang === 'ru' ? `Исправь ошибки DRC платы v${v!.version}` : `Fix the DRC errors of PCB v${v!.version}`)}>
              <Icon name="wand" size={14} /> {i18n.lang === 'ru' ? 'Попросить агента исправить' : 'Ask the agent to fix them'}
            </button>
          {/if}
        {:else}
          <div class="row">
            {#each fab as f (f)}
              <a class="btn small" href={art[f]} download><Icon name="download" size={14} /> {FILE_LABEL[f] ?? f}</a>
            {/each}
          </div>
          {#if v?.lcsc_verified}
            <span class="chip ok" title={t('pcb_lcsc_ok_hint')}><Icon name="check" size={12} /> {t('pcb_lcsc_ok')}</span>
          {:else}
            <span class="chip warn" title={t('pcb_lcsc_hint')}><Icon name="info" size={12} /> {t('pcb_lcsc')}</span>
          {/if}
        {/if}
      </section>

      {#if onSend && caseActions}
        <div class="next">
          <button class="btn primary" disabled={busy} onclick={() => onSend?.(t('pcb_case_msg', { v: v!.version }))}><Icon name="package" size={16} /> {t('pcb_make_case')}</button>
          <button class="btn" disabled={busy} onclick={() => onSend?.(t('pcb_mockup_msg', { v: v!.version }))}><Icon name="printer" size={16} /> {t('pcb_mockup')}</button>
        </div>
      {/if}
    {/if}
  </div>
{/if}

<style>
  .pstage {
    position: absolute;
    inset: 0;
    z-index: 3;
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border-radius: var(--radius-card);
    overflow: hidden;
  }
  .bar,
  .foot {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: var(--space-3);
    flex: none;
    min-width: 0;
    flex-wrap: wrap;
  }
  .bar .seg {
    max-width: 100%;
  }
  .bar .seg button {
    padding-inline: 10px;
  }
  .spacer {
    flex: 1;
  }
  .pic {
    position: relative;
    flex: 1;
    min-height: 0;
    margin: 0 var(--space-3);
    border-radius: var(--radius-field);
    background: #0b0d0a;
    overflow: hidden;
  }
  .zoom {
    position: absolute;
    inset: 0;
    transform-origin: 0 0;
  }
  .pic.zoomed {
    cursor: grab;
    touch-action: none;
  }
  .pic.paper {
    background: rgb(245 241 237);
  }
  .fit {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
    object-fit: contain;
  }
  canvas.fit {
    touch-action: none;
  }
  .copper {
    transition: opacity 900ms var(--ease-standard);
  }
  .copper.under {
    opacity: 0.32;
  }
  .board {
    fill: #0f1d12;
    stroke: rgb(255 255 255 / 0.5);
    stroke-width: 0.25;
  }
  .route {
    fill: none;
    stroke-linecap: round;
  }
  .route.old {
    stroke: #3ddc84;
    opacity: 0.28;
  }
  .route.now {
    stroke: #6dffa8;
    stroke-dasharray: 1;
    stroke-dashoffset: 1;
    animation: route-draw 900ms var(--ease-out) forwards;
  }
  @keyframes route-draw {
    to {
      stroke-dashoffset: 0;
    }
  }
  .empty {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    text-align: center;
    color: var(--outline);
    padding: var(--space-4);
  }
  .empty strong {
    color: var(--on-surface);
    font-weight: var(--font-weight-semibold);
  }
  .empty.tall {
    position: static;
    padding: var(--space-7) var(--space-3);
  }
  .empty p {
    margin: 0;
    max-width: 34ch;
  }
  .pill {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    font-size: var(--text-sm);
    font-weight: var(--font-weight-semibold);
    padding: 4px 10px;
    border-radius: var(--radius-tag);
    border: var(--border-width) solid var(--outline-variant);
    background: var(--surface-container);
  }
  .pill.work {
    color: var(--primary);
  }
  /* side */
  .pside {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 8px;
    justify-content: space-between;
  }
  .head strong {
    font-size: var(--text-xl);
    font-weight: var(--font-weight-semibold);
  }
  .ver {
    width: auto;
    min-width: 72px;
    height: 34px;
    padding: 0 8px;
  }
  .sum {
    display: flex;
    gap: 11px;
    align-items: flex-start;
    padding: 13px 15px;
    border-radius: var(--radius-card);
    border: var(--border-width) solid var(--outline-variant);
    font-size: var(--text-base);
  }
  .sum strong {
    display: block;
    font-weight: var(--font-weight-semibold);
  }
  .sum .small {
    color: var(--on-surface-var);
  }
  .sum.ok {
    background: color-mix(in srgb, var(--primary) 9%, var(--surface));
    border-color: color-mix(in srgb, var(--primary) 30%, var(--outline-variant));
  }
  .sum.err {
    background: color-mix(in srgb, var(--error) 12%, var(--surface));
    border-color: color-mix(in srgb, var(--error) 40%, var(--outline-variant));
  }
  .light {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    flex: none;
  }
  .ok .light {
    background: var(--primary);
    color: var(--on-primary);
  }
  .err .light {
    background: var(--error);
    color: var(--surface);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .groups {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .g {
    width: 100%;
    display: flex;
    gap: 8px;
    align-items: flex-start;
    background: none;
    border: var(--border-width) solid transparent;
    border-radius: var(--radius-field);
    padding: 8px 10px;
    font-family: inherit;
    text-align: left;
    color: var(--on-surface);
    cursor: pointer;
  }
  .g:hover,
  .g[aria-expanded='true'] {
    background: var(--surface);
    border-color: var(--outline-variant);
  }
  .dot {
    width: 9px;
    height: 9px;
    margin-top: 5px;
    border-radius: 50%;
    flex: none;
    background: var(--info);
  }
  .error .dot {
    background: var(--error);
  }
  .note .dot {
    background: var(--outline);
  }
  .ttl {
    flex: 1;
    min-width: 0;
    font-size: var(--text-md);
    overflow-wrap: anywhere;
  }
  .detail {
    padding: 4px 8px 8px 25px;
    color: var(--on-surface-var);
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .detail p {
    margin: 0;
  }
  .detail .raw .mono {
    overflow-wrap: anywhere;
  }
  .notes {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .nh {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px 8px;
    background: none;
    border: none;
    padding: 4px 2px;
    font-family: inherit;
    text-align: left;
    color: var(--on-surface-var);
    cursor: pointer;
  }
  .nh .ttl {
    flex: 0 1 auto;
    font-weight: var(--font-weight-semibold);
  }
  .chev {
    display: grid;
    transition: transform 0.12s;
  }
  .chev.open {
    transform: rotate(90deg);
  }
  .files {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    padding-top: var(--space-3);
    border-top: var(--border-width) solid var(--divider);
  }
  .nofab {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    margin: 0;
    padding: 10px 12px;
    border-radius: var(--radius-field);
    background: color-mix(in srgb, var(--error) 8%, var(--surface));
    color: var(--on-surface-var);
  }
  .nofab :global(.icon) {
    margin-top: 2px;
    color: var(--error);
  }
  .files .row,
  .next {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .next {
    padding-top: var(--space-3);
    border-top: var(--border-width) solid var(--divider);
  }
  .next .btn {
    flex: 1 1 auto;
  }
</style>
