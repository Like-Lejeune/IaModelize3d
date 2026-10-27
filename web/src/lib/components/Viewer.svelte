<script lang="ts">
  import * as THREE from 'three';
  import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
  import { onMount } from 'svelte';
  import { t } from '$lib/i18n.svelte';
  import type { BuildResult, Calibration, Handle, Issue, ParamSpec } from '$lib/types';

  let {
    build = null,
    issues = [],
    highlight = null,
    values = {},
    specs = {},
    photo = null,
    editable = true,
    onParam,
  }: {
    build?: BuildResult | null;
    issues?: Issue[];
    highlight?: Issue | null;
    values?: Record<string, any>;
    specs?: Record<string, ParamSpec>;
    photo?: { url: string; calibration: Calibration } | null;
    editable?: boolean;
    onParam?: (name: string, value: any, commit: boolean) => void;
  } = $props();

  let host: HTMLDivElement;
  let canvas: HTMLCanvasElement;
  let showHeat = $state(true);
  let showModifiers = $state(true);
  let photoMode = $state(false);
  let arSupported = $state(false);
  let arActive = $state(false);
  let arOverlay: HTMLDivElement;
  let hoverHandle = $state<string | null>(null);

  let renderer: THREE.WebGLRenderer;
  let scene: THREE.Scene;
  let camera: THREE.PerspectiveCamera;
  let controls: OrbitControls;
  const modelGroup = new THREE.Group();
  const issueGroup = new THREE.Group();
  const handleGroup = new THREE.Group();
  let bed: THREE.Group;
  let lastFitKey = '';
  let raycaster = new THREE.Raycaster();

  const PALETTE = [0xd6d8de, 0xe8965a, 0x6eaadc, 0x96c878, 0xdc78a0, 0xf0d264];

  function partColor(i: number, hex?: string): THREE.Color {
    if (hex && /^#?[0-9a-f]{6}$/i.test(hex)) return new THREE.Color(hex.startsWith('#') ? hex : `#${hex}`);
    return new THREE.Color(PALETTE[i % PALETTE.length]);
  }

  function makeBed() {
    const g = new THREE.Group();
    const grid = new THREE.GridHelper(260, 26, 0x9a958c, 0xc9c4ba);
    grid.rotation.x = Math.PI / 2;
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = 0.5;
    g.add(grid);
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(260, 260), new THREE.MeshBasicMaterial({ color: 0x8a857c, transparent: true, opacity: 0.06, depthWrite: false }));
    plane.position.z = -0.01;
    g.add(plane);
    return g;
  }

  function disposeGroup(g: THREE.Group) {
    for (const c of [...g.children]) {
      g.remove(c);
      c.traverse((o: any) => {
        o.geometry?.dispose?.();
        if (Array.isArray(o.material)) o.material.forEach((m: any) => m.dispose());
        else o.material?.dispose?.();
      });
    }
  }

  function rebuildModel(b: BuildResult) {
    disposeGroup(modelGroup);
    const P = b.positions, I = b.indices, TP = b.triPart, H = b.heat;
    const nTri = I.length / 3;
    const byRole: Record<string, number[]> = { model: [], other: [] };
    for (let f = 0; f < nTri; f++) (b.parts[TP[f]]?.role === 'model' ? byRole.model : byRole.other).push(f);
    const make = (tris: number[], heat: boolean) => {
      const pos = new Float32Array(tris.length * 9);
      const col = new Float32Array(tris.length * 9);
      const c = new THREE.Color();
      tris.forEach((f, k) => {
        const part = b.parts[TP[f]];
        c.copy(partColor(TP[f], part?.color));
        const h = heat && H ? H[f] : 0;
        if (h > 0) c.lerp(new THREE.Color(0xe0442c), Math.min(1, 0.25 + h));
        for (let v = 0; v < 3; v++) {
          const vi = I[f * 3 + v];
          pos.set([P[vi * 3], P[vi * 3 + 1], P[vi * 3 + 2]], k * 9 + v * 3);
          col.set([c.r, c.g, c.b], k * 9 + v * 3);
        }
      });
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      g.setAttribute('color', new THREE.BufferAttribute(col, 3));
      g.computeVertexNormals();
      return g;
    };
    if (byRole.model.length) {
      const g = make(byRole.model, showHeat);
      const mat = new THREE.MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 0.75, metalness: 0.02, transparent: photoMode, opacity: photoMode ? 0.82 : 1 });
      const mesh = new THREE.Mesh(g, mat);
      modelGroup.add(mesh);
      if (byRole.model.length < 150000) {
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(g, 28), new THREE.LineBasicMaterial({ color: photoMode ? 0xff7a28 : 0x30343a, transparent: true, opacity: photoMode ? 0.9 : 0.45 }));
        modelGroup.add(edges);
      }
    }
    if (byRole.other.length) {
      const g = make(byRole.other, false);
      const mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0x5ab4ff, transparent: true, opacity: 0.28, depthWrite: false }));
      mesh.visible = showModifiers;
      mesh.userData.modifier = true;
      modelGroup.add(mesh);
    }
  }

  function rebuildIssues() {
    disposeGroup(issueGroup);
    for (const is of issues) {
      if (!is.bbox || !is.z) continue;
      const on = highlight === is;
      const color = is.severity === 'error' ? 0xe0442c : is.severity === 'warn' ? 0xe0a52c : 0x4a7fd0;
      const min = new THREE.Vector3(is.bbox.min[0], is.bbox.min[1], is.z[0] - 0.2);
      const max = new THREE.Vector3(is.bbox.max[0], is.bbox.max[1], Math.max(is.z[1] + 0.2, is.z[0] + 0.4));
      const helper = new THREE.Box3Helper(new THREE.Box3(min, max), color);
      (helper.material as THREE.LineBasicMaterial).transparent = true;
      (helper.material as THREE.LineBasicMaterial).opacity = highlight && !on ? 0.25 : 1;
      (helper.material as THREE.LineBasicMaterial).depthTest = false;
      helper.renderOrder = 5;
      issueGroup.add(helper);
    }
  }

  // ---------- handles ----------
  function handleKey(h: Handle) {
    return h.type === 'point' ? h.params.join('+') : h.param;
  }

  function rebuildHandles() {
    disposeGroup(handleGroup);
    if (!build || !editable) return;
    const size = Math.max(2, Math.min(6, sceneSize() * 0.025));
    for (const h of build.handles ?? []) {
      const key = handleKey(h);
      const at = new THREE.Vector3(...h.at);
      const color = hoverHandle === key ? 0xffffff : 0xf2a65a;
      const s = new THREE.Mesh(new THREE.SphereGeometry(size, 20, 14), new THREE.MeshBasicMaterial({ color, depthTest: false }));
      s.position.copy(at);
      s.renderOrder = 10;
      s.userData.handle = h;
      handleGroup.add(s);
      const ring = new THREE.Mesh(new THREE.RingGeometry(size * 1.15, size * 1.45, 24), new THREE.MeshBasicMaterial({ color: 0x1f2328, side: THREE.DoubleSide, depthTest: false }));
      ring.position.copy(at);
      ring.renderOrder = 9;
      ring.lookAt(camera.position);
      handleGroup.add(ring);
      if ('axis' in h) {
        const a = new THREE.Vector3(...h.axis).normalize();
        const arrow = new THREE.ArrowHelper(a, at, size * 4, 0xf2a65a, size * 1.4, size * 0.9);
        arrow.renderOrder = 9;
        handleGroup.add(arrow);
      }
    }
  }

  let drag: null | {
    h: Handle;
    start: number[];
    startMeasure: number[];
    plane?: THREE.Plane;
  } = null;

  function ray(ev: PointerEvent) {
    const r = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    return raycaster.ray;
  }

  function lineParam(rr: THREE.Ray, p0: THREE.Vector3, a: THREE.Vector3) {
    const w = rr.origin.clone().sub(p0);
    const b = rr.direction.dot(a);
    const den = 1 - b * b;
    if (Math.abs(den) < 1e-6) return 0;
    return (a.dot(w) - b * rr.direction.dot(w)) / den;
  }

  function measure(h: Handle, rr: THREE.Ray, plane?: THREE.Plane): number[] {
    if (h.type === 'linear') return [lineParam(rr, new THREE.Vector3(...h.at), new THREE.Vector3(...h.axis).normalize())];
    const q = new THREE.Vector3();
    if (!plane || !rr.intersectPlane(plane, q)) return [NaN, NaN];
    if (h.type === 'radial') {
      const c = new THREE.Vector3(...h.center), a = new THREE.Vector3(...h.axis).normalize();
      const d = q.clone().sub(c);
      d.sub(a.clone().multiplyScalar(d.dot(a)));
      return [d.length()];
    }
    if (h.type === 'angle') {
      const c = new THREE.Vector3(...h.center), a = new THREE.Vector3(...h.axis).normalize();
      const u = new THREE.Vector3(...h.at).sub(c);
      u.sub(a.clone().multiplyScalar(u.dot(a))).normalize();
      const v = a.clone().cross(u);
      const d = q.clone().sub(c);
      return [(Math.atan2(d.dot(v), d.dot(u)) * 180) / Math.PI];
    }
    const idx = h.plane === 'xy' ? [0, 1] : h.plane === 'xz' ? [0, 2] : [1, 2];
    return [q.getComponent(idx[0]), q.getComponent(idx[1])];
  }

  function clampTo(name: string, v: number) {
    const s = specs[name];
    if (!s) return v;
    if (s.min !== undefined) v = Math.max(s.min, v);
    if (s.max !== undefined) v = Math.min(s.max, v);
    const step = s.step ?? (s.kind === 'int' ? 1 : 0.1);
    return Math.round(v / step) * step;
  }

  function onDown(ev: PointerEvent) {
    if (!build || !editable || photoMode) return;
    const rr = ray(ev);
    const hits = raycaster.intersectObjects(handleGroup.children.filter((c) => c.userData.handle), false);
    if (!hits.length) return;
    const h = hits[0].object.userData.handle as Handle;
    let plane: THREE.Plane | undefined;
    if (h.type === 'radial' || h.type === 'angle') plane = new THREE.Plane().setFromNormalAndCoplanarPoint(new THREE.Vector3(...h.axis).normalize(), new THREE.Vector3(...h.at));
    if (h.type === 'point') {
      const n = h.plane === 'xy' ? new THREE.Vector3(0, 0, 1) : h.plane === 'xz' ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
      plane = new THREE.Plane().setFromNormalAndCoplanarPoint(n, new THREE.Vector3(...h.at));
    }
    const names = h.type === 'point' ? h.params : [h.param];
    drag = { h, plane, start: names.map((n) => Number(values[n] ?? 0)), startMeasure: measure(h, rr, plane) };
    controls.enabled = false;
    canvas.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  }

  function onMove(ev: PointerEvent) {
    if (!drag) {
      if (!build || photoMode) return;
      ray(ev);
      const hits = raycaster.intersectObjects(handleGroup.children.filter((c) => c.userData.handle), false);
      const key = hits.length ? handleKey(hits[0].object.userData.handle) : null;
      if (key !== hoverHandle) {
        hoverHandle = key;
        canvas.style.cursor = key ? 'grab' : '';
      }
      return;
    }
    const m = measure(drag.h, ray(ev), drag.plane);
    if (m.some((x) => !Number.isFinite(x))) return;
    const h = drag.h;
    if (h.type === 'point') {
      h.params.forEach((n, i) => onParam?.(n, clampTo(n, drag!.start[i] + (m[i] - drag!.startMeasure[i])), false));
    } else {
      let delta = m[0] - drag.startMeasure[0];
      if (h.type === 'angle') delta = ((delta + 540) % 360) - 180;
      const scale = 'scale' in h && h.scale ? h.scale : 1;
      onParam?.(h.param, clampTo(h.param, drag.start[0] + delta * scale), false);
    }
  }

  function onUp(ev: PointerEvent) {
    if (!drag) return;
    const h = drag.h;
    drag = null;
    controls.enabled = !photoMode;
    try {
      canvas.releasePointerCapture(ev.pointerId);
    } catch {
      /* already released */
    }
    const name = h.type === 'point' ? h.params[0] : h.param;
    onParam?.(name, values[name], true);
  }

  // ---------- camera ----------
  function sceneSize() {
    if (!build?.parts?.length) return 100;
    const box = bbox();
    return box.getSize(new THREE.Vector3()).length() || 100;
  }

  function bbox() {
    const box = new THREE.Box3();
    for (const p of build?.parts ?? []) {
      if (p.role !== 'model') continue;
      box.expandByPoint(new THREE.Vector3(...p.bbox.min));
      box.expandByPoint(new THREE.Vector3(...p.bbox.max));
    }
    if (box.isEmpty()) box.set(new THREE.Vector3(-50, -50, 0), new THREE.Vector3(50, 50, 50));
    return box;
  }

  export function fit() {
    if (!camera) return;
    const box = bbox();
    const c = box.getCenter(new THREE.Vector3());
    const r = box.getSize(new THREE.Vector3()).length() / 2 || 50;
    // fit the bounding sphere into the narrower of the vertical/horizontal fields of view
    const halfV = ((camera.fov / 2) * Math.PI) / 180;
    const halfH = Math.atan(Math.tan(halfV) * camera.aspect);
    const dist = r / Math.sin(Math.min(halfV, halfH));
    camera.position.copy(c.clone().add(new THREE.Vector3(0.9, -1.3, 0.85).normalize().multiplyScalar(dist * 1.05)));
    camera.near = Math.max(0.1, dist / 200);
    camera.far = dist * 50;
    camera.updateProjectionMatrix();
    controls.target.copy(c);
    controls.update();
  }

  /** PNG data URL of the current view (used by Visual edit). */
  export function snapshot(): string | null {
    if (!renderer) return null;
    renderer.render(scene, camera);
    return renderer.domElement.toDataURL('image/png');
  }

  function applyPhotoCamera(cal: Calibration) {
    const [r0, r1, r2, r3, r4, r5, r6, r7, r8] = cal.R;
    const view = new THREE.Matrix4().set(r0, r1, r2, cal.t[0], r3, r4, r5, cal.t[1], r6, r7, r8, cal.t[2], 0, 0, 0, 1);
    view.premultiply(new THREE.Matrix4().makeScale(1, -1, -1));
    camera.matrixAutoUpdate = false;
    camera.matrix.copy(view.clone().invert());
    camera.matrixWorldNeedsUpdate = true;
    const W = cal.width, H = cal.height, n = 1, f = 20000;
    camera.projectionMatrix.set(
      (2 * cal.fx) / W, 0, 1 - (2 * cal.cx) / W, 0,
      0, (2 * cal.fy) / H, (2 * cal.cy) / H - 1, 0,
      0, 0, -(f + n) / (f - n), (-2 * f * n) / (f - n),
      0, 0, -1, 0,
    );
    camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
  }

  function resize() {
    if (!renderer || !host) return;
    const w = host.clientWidth, h = host.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    if (photoMode && photo) {
      applyPhotoCamera(photo.calibration);
    } else {
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
  }

  function setPhotoMode(on: boolean) {
    photoMode = on && !!photo;
    if (photoMode && photo) {
      bed.visible = false;
      controls.enabled = false;
      scene.background = null;
      applyPhotoCamera(photo.calibration);
    } else {
      bed.visible = true;
      controls.enabled = true;
      camera.matrixAutoUpdate = true;
      fit();
    }
    if (build) rebuildModel(build);
    queueMicrotask(resize);
  }

  // ---------- WebXR ----------
  let xrSession: any = null;
  let hitSource: any = null;
  let reticle: THREE.Mesh;
  let arModel: THREE.Group | null = null;

  async function startAR() {
    const xr = (navigator as any).xr;
    if (!xr) return;
    try {
      xrSession = await xr.requestSession('immersive-ar', { requiredFeatures: ['hit-test'], optionalFeatures: ['dom-overlay'], domOverlay: { root: arOverlay } });
    } catch {
      arSupported = false;
      return;
    }
    renderer.xr.enabled = true;
    renderer.xr.setReferenceSpaceType('local');
    await renderer.xr.setSession(xrSession);
    arActive = true;
    bed.visible = false;
    scene.background = null;
    const viewer = await xrSession.requestReferenceSpace('viewer');
    hitSource = await xrSession.requestHitTestSource({ space: viewer });
    reticle = new THREE.Mesh(new THREE.RingGeometry(0.03, 0.04, 32).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0xf2a65a }));
    reticle.matrixAutoUpdate = false;
    reticle.visible = false;
    scene.add(reticle);
    arModel = modelGroup.clone(true);
    arModel.scale.setScalar(0.001); // mm -> m, real size
    arModel.rotation.x = -Math.PI / 2; // Z-up model -> Y-up world
    arModel.visible = false;
    scene.add(arModel);
    modelGroup.visible = false;
    issueGroup.visible = false;
    handleGroup.visible = false;
    xrSession.addEventListener('select', () => {
      if (!reticle.visible || !arModel) return;
      arModel.position.setFromMatrixPosition(reticle.matrix);
      arModel.visible = true;
    });
    xrSession.addEventListener('end', () => {
      arActive = false;
      renderer.xr.enabled = false;
      hitSource = null;
      if (arModel) scene.remove(arModel);
      scene.remove(reticle);
      arModel = null;
      modelGroup.visible = issueGroup.visible = handleGroup.visible = true;
      bed.visible = !photoMode;
      applyTheme();
      resize();
    });
  }

  function applyTheme() {
    const dark = matchMedia('(prefers-color-scheme: dark)').matches && document.documentElement.dataset.theme !== 'light';
    scene.background = photoMode ? null : new THREE.Color(dark ? 0x1b1e22 : 0xeeebe5);
  }

  onMount(() => {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(2, devicePixelRatio));
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(38, 1, 0.5, 10000);
    camera.up.set(0, 0, 1);
    controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8d8a85, 1.4));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(-120, -200, 300);
    scene.add(sun);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5);
    fill.position.set(200, 150, 120);
    scene.add(fill);
    bed = makeBed();
    scene.add(bed, modelGroup, issueGroup, handleGroup);
    applyTheme();
    const mq = matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', applyTheme);
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    resize();
    fit();
    renderer.setAnimationLoop((_t: number, frame: any) => {
      if (frame && hitSource) {
        const ref = renderer.xr.getReferenceSpace();
        const hits = frame.getHitTestResults(hitSource);
        if (hits.length && ref) {
          const pose = hits[0].getPose(ref);
          reticle.visible = true;
          reticle.matrix.fromArray(pose.transform.matrix);
        } else if (reticle) reticle.visible = false;
      } else if (!photoMode) controls.update();
      for (const c of handleGroup.children) if (c instanceof THREE.Mesh && c.geometry instanceof THREE.RingGeometry) c.lookAt(camera.position);
      renderer.render(scene, camera);
    });
    (navigator as any).xr?.isSessionSupported?.('immersive-ar').then((ok: boolean) => (arSupported = !!ok)).catch(() => {});
    return () => {
      ro.disconnect();
      mq.removeEventListener('change', applyTheme);
      renderer.setAnimationLoop(null);
      xrSession?.end?.();
      controls.dispose();
      disposeGroup(modelGroup);
      disposeGroup(issueGroup);
      disposeGroup(handleGroup);
      renderer.dispose();
    };
  });

  $effect(() => {
    // rebuild on new geometry or display toggles
    const b = build;
    void showHeat;
    void showModifiers;
    if (!renderer) return;
    if (b) {
      rebuildModel(b);
      const box = bbox();
      const key = box.getSize(new THREE.Vector3()).toArray().map((v) => Math.round(Math.log2(v + 1) * 2)).join(',');
      if (key !== lastFitKey && !photoMode) {
        lastFitKey = key;
        fit();
      }
    } else disposeGroup(modelGroup);
  });

  $effect(() => {
    void issues;
    void highlight;
    if (renderer) rebuildIssues();
  });

  $effect(() => {
    void build;
    void hoverHandle;
    if (renderer) rebuildHandles();
  });

  $effect(() => {
    if (!photo && photoMode) setPhotoMode(false);
  });
</script>

<div class="viewer" class:photo={photoMode}>
  <div class="stage" bind:this={host} style:aspect-ratio={photoMode && photo ? `${photo.calibration.width} / ${photo.calibration.height}` : undefined}>
    {#if photoMode && photo}<img class="bg" src={photo.url} alt="" />{/if}
    <canvas bind:this={canvas} onpointerdown={onDown} onpointermove={onMove} onpointerup={onUp} onpointercancel={onUp} aria-label="3D model viewer"></canvas>
    {#if !build}
      <div class="empty muted">{t('no_program')}</div>
    {/if}
  </div>
  <div class="tools" bind:this={arOverlay}>
    <button class="btn small" class:on={showHeat} onclick={() => (showHeat = !showHeat)} aria-pressed={showHeat}>🔥 {t('heat')}</button>
    {#if build?.parts?.some((p) => p.role !== 'model')}
      <button class="btn small" class:on={showModifiers} onclick={() => (showModifiers = !showModifiers)} aria-pressed={showModifiers}>◫ {t('modifiers')}</button>
    {/if}
    {#if photo}
      <button class="btn small" class:on={photoMode} onclick={() => setPhotoMode(!photoMode)} aria-pressed={photoMode}>📷 {t('photo_ar')}</button>
    {/if}
    {#if arSupported}
      <button class="btn small" onclick={() => (arActive ? xrSession?.end() : startAR())}>{arActive ? t('stop') : '🕶 ' + t('live_ar')}</button>
    {/if}
    {#if !photoMode}<button class="btn small" onclick={fit} aria-label={t('reset_view')}>⤢</button>{/if}
  </div>
</div>

<style>
  .viewer {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 240px;
    display: flex;
    flex-direction: column;
    background: var(--panel-2);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .stage {
    position: relative;
    flex: 1;
    min-height: 0;
  }
  .viewer.photo .stage {
    flex: none;
    width: 100%;
    max-height: 100%;
    margin: auto;
  }
  .bg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: fill;
  }
  canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
    touch-action: none;
  }
  .empty {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    text-align: center;
    padding: 24px;
    pointer-events: none;
  }
  .tools {
    position: absolute;
    left: 8px;
    bottom: 8px;
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    right: 8px;
  }
  .tools .btn {
    background: color-mix(in srgb, var(--panel) 85%, transparent);
    backdrop-filter: blur(6px);
  }
  .tools .btn.on {
    border-color: var(--accent);
    color: var(--accent);
  }
</style>
