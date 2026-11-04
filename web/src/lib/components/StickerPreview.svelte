<script lang="ts">
  // The instant 3D sticker of a snap: built in this page's own geometry worker from the relief the server
  // sent (lib.collect.sticker), shown in a small three.js scene that turns slowly. The flat cut-out rises
  // into relief when the first mesh lands; a new name or size rebuilds it in place. A phone that has not
  // built it within a few seconds gets the server's render meanwhile.
  import * as THREE from 'three';
  import { onMount, untrack } from 'svelte';
  import { GeomClient } from '$lib/geom/client';
  import type { BuildResult } from '$lib/types';
  import type { StickerPayload } from '$lib/collect/api';
  import { ct, secs } from '$lib/collect/i18n';

  let {
    sticker,
    size,
    label,
    fallback = null,
    onbuilt,
  }: {
    sticker: StickerPayload | null;
    size: number;
    label: string;
    /** The server's PNG of the same sticker, asked for when the local build is slow or WebGL is missing. */
    fallback?: (() => Promise<Blob>) | null;
    onbuilt?: (info: { ms: number; size: [number, number, number] }) => void;
  } = $props();

  const SLOW_MS = 4000;
  let host: HTMLDivElement;
  let canvas: HTMLCanvasElement;
  let phase = $state<'idle' | 'building' | 'ready' | 'failed'>('idle');
  let shown = $state(false);
  let ms = $state(0);
  let png = $state<string | null>(null);
  let webgl = true;

  let geom: GeomClient | null = null;
  let renderer: THREE.WebGLRenderer | null = null;
  let scene: THREE.Scene;
  let camera: THREE.PerspectiveCamera;
  const turntable = new THREE.Group();
  const materials = new Map<string, THREE.MeshStandardMaterial>();
  let lift = 0; // performance.now() when the first mesh landed
  let seq = 0;
  let inputsKey = '';
  let slowTimer: ReturnType<typeof setTimeout> | undefined;
  const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

  function material(hex = '#d6d8de') {
    let m = materials.get(hex);
    if (!m) {
      m = new THREE.MeshStandardMaterial({ color: new THREE.Color(hex), roughness: 0.78, metalness: 0.02, flatShading: true });
      materials.set(hex, m);
    }
    return m;
  }

  function clear() {
    for (const c of [...turntable.children]) {
      turntable.remove(c);
      (c as THREE.Mesh).geometry?.dispose();
    }
  }

  function show(b: BuildResult) {
    const d = b.display;
    clear();
    if (!d.position.length) return;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(d.position, 3));
    const mats = d.groups.map(([start, count, part], k) => {
      g.addGroup(start, count, k);
      return material(b.parts[part]?.color);
    });
    g.computeVertexNormals();
    g.computeBoundingBox();
    const box = g.boundingBox!;
    const c = box.getCenter(new THREE.Vector3());
    const mesh = new THREE.Mesh(g, mats);
    mesh.position.set(-c.x, -c.y, 0); // turn about the sticker's middle
    turntable.add(mesh);
    // it turns: frame the footprint's diagonal, not its sides
    const r = Math.hypot(box.max.x - box.min.x, box.max.y - box.min.y) / 2 + 1;
    const dist = (r / Math.tan((camera.fov * Math.PI) / 360)) * 1.08;
    camera.position.copy(new THREE.Vector3(0, -0.78, 1).normalize().multiplyScalar(dist));
    camera.lookAt(0, 0, 0.5);
    if (!shown) lift = performance.now();
    shown = true;
  }

  async function build(s: StickerPayload, sz: number, name: string) {
    if (!geom) return;
    const my = ++seq;
    const key = `${s.key}|${name}`;
    if (key !== inputsKey) {
      // a plain copy: a reactive proxy cannot be posted to the worker
      const inputs = $state.snapshot(s.inputs);
      geom.setInputs({ ...inputs, values: { ...inputs.values, name } });
      inputsKey = key;
    }
    phase = 'building';
    const t0 = performance.now();
    if (!shown && fallback) {
      clearTimeout(slowTimer);
      slowTimer = setTimeout(() => !shown && my === seq && loadFallback(), webgl ? SLOW_MS : 0);
    }
    const r = await geom.preview({ source: s.source, params: { ...$state.snapshot(s.params), size: sz }, quality: 'final' });
    if (my !== seq) return;
    if (!r.ok) {
      if (r.stage === 'superseded') return;
      phase = 'failed';
      if (fallback && !png) loadFallback();
      return;
    }
    ms = performance.now() - t0;
    if (renderer) show(r);
    phase = 'ready';
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (const p of r.parts)
      for (let i = 0; i < 3; i++) {
        lo[i] = Math.min(lo[i], p.bbox.min[i]);
        hi[i] = Math.max(hi[i], p.bbox.max[i]);
      }
    onbuilt?.({ ms, size: [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]] });
  }

  async function loadFallback() {
    if (!fallback) return;
    try {
      const blob = await fallback();
      if (png) URL.revokeObjectURL(png);
      png = URL.createObjectURL(blob);
    } catch {
      /* the local build may still come */
    }
  }

  // a new sticker or size builds now; a name being typed waits until the typing pauses
  let typed: ReturnType<typeof setTimeout> | undefined;
  let lastName = '';
  $effect(() => {
    const s = sticker, sz = size, name = label.trim();
    if (!s) return;
    clearTimeout(typed);
    const wait = untrack(() => shown) && name !== lastName ? 450 : 0;
    lastName = name;
    typed = setTimeout(() => build(s, sz, name), wait);
  });

  function resize() {
    if (!renderer || !host) return;
    const w = host.clientWidth, h = host.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(1, h);
    camera.updateProjectionMatrix();
  }

  onMount(() => {
    geom = new GeomClient();
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(30, 1, 0.5, 2000);
    camera.up.set(0, 0, 1);
    camera.position.set(0, -60, 80);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x6d6a65, 1.5));
    const sun = new THREE.DirectionalLight(0xffffff, 2.1);
    sun.position.set(-60, -40, 120); // low from the side: the relief reads in its shadows
    scene.add(sun);
    scene.add(turntable);
    try {
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(2, devicePixelRatio));
    } catch {
      renderer = null;
      webgl = false;
    }
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    resize();
    let last = performance.now();
    renderer?.setAnimationLoop((now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (!reduced) turntable.rotation.z += dt * 0.45;
      else turntable.rotation.z = -0.35;
      // the cut-out rises into relief: z from flat to full height, with a little overshoot
      const k = lift ? Math.min(1, (now - lift) / 700) : 1;
      const ease = reduced ? 1 : 1 + 2.2 * Math.pow(k - 1, 3) + 1.2 * Math.pow(k - 1, 2);
      turntable.scale.z = Math.max(0.04, ease);
      renderer!.render(scene, camera);
    });
    return () => {
      seq++;
      clearTimeout(slowTimer);
      clearTimeout(typed);
      ro.disconnect();
      renderer?.setAnimationLoop(null);
      clear();
      for (const m of materials.values()) m.dispose();
      renderer?.dispose();
      geom?.dispose();
      geom = null;
      if (png) URL.revokeObjectURL(png);
    };
  });
</script>

<div class="sp" bind:this={host} role="img" aria-label={ct('preview_label')} aria-busy={phase === 'building'}>
  <canvas bind:this={canvas} class:on={shown}></canvas>
  {#if png && !shown}<img class="png" src={png} alt="" />{/if}
  {#if phase === 'building' && !shown}
    <span class="state"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {ct('lifting')}</span>
  {:else if phase === 'building'}
    <i class="ti ti-loader-2 spin corner" aria-hidden="true"></i>
  {:else if shown && ms}
    <span class="state ms">{ct('built', { s: secs(ms) })}</span>
  {/if}
  {#if png && !shown}<span class="state srv">{ct('server_preview')}</span>{/if}
</div>

<style>
  .sp {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 140px;
    overflow: hidden;
  }
  canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
    opacity: 0;
    transition: opacity var(--dur-slow) var(--ease-standard);
  }
  canvas.on {
    opacity: 1;
  }
  .png {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .state {
    position: absolute;
    left: 50%;
    bottom: 6px;
    transform: translateX(-50%);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
    padding: 3px 10px;
    border-radius: var(--radius-full);
    font-size: var(--text-xs);
    font-weight: var(--font-weight-semibold);
    background: color-mix(in srgb, var(--surface-container) 82%, transparent);
    color: var(--on-surface-var);
  }
  .state.srv {
    top: 6px;
    bottom: auto;
  }
  .state.ms {
    left: auto;
    right: 6px;
    transform: none;
    color: var(--primary);
  }
  .corner {
    position: absolute;
    right: 8px;
    top: 8px;
    color: var(--primary);
  }
</style>
