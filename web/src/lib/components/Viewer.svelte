<script lang="ts">
  import Icon from './Icon.svelte';
  import * as THREE from 'three';
  import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
  import { onMount, untrack } from 'svelte';
  import { t, unitLabel } from '$lib/i18n.svelte';
  import type { BuildResult, Calibration, Handle, Issue, ParamSpec } from '$lib/types';

  let {
    build = null,
    issues = [],
    highlight = null,
    values = {},
    specs = {},
    photo = null,
    editable = true,
    loading = false,
    onParam,
    sculptable = false,
    symmetry = null,
    canUndo = false,
    onSculpt,
    onSymmetry,
    onUndo,
  }: {
    build?: BuildResult | null;
    issues?: Issue[];
    highlight?: Issue | null;
    values?: Record<string, any>;
    specs?: Record<string, ParamSpec>;
    photo?: { url: string; calibration: Calibration } | null;
    editable?: boolean;
    loading?: boolean;
    onParam?: (name: string, value: any, commit: boolean) => void;
    /** The model is a mesh document: strokes drawn here become sculpt ops. */
    sculptable?: boolean;
    symmetry?: 'x' | 'y' | null;
    canUndo?: boolean;
    onSculpt?: (op: Record<string, any>) => void;
    onSymmetry?: () => void;
    onUndo?: () => void;
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

  // scene colours follow the page theme tokens
  function cssColor(token: string, fallback: string): THREE.Color {
    const v = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
    try {
      return new THREE.Color(v || fallback);
    } catch {
      return new THREE.Color(fallback);
    }
  }

  function makeBed() {
    const g = new THREE.Group();
    const grid = new THREE.GridHelper(260, 26, cssColor('--outline', '#909284'), cssColor('--outline-variant', '#45483c'));
    grid.rotation.x = Math.PI / 2;
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = 0.5;
    g.add(grid);
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(260, 260), new THREE.MeshBasicMaterial({ color: cssColor('--outline', '#909284'), transparent: true, opacity: 0.06, depthWrite: false }));
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

  // Materials live as long as the viewer; each build only swaps geometry. The worker sends
  // ready buffers (packages/geom/src/display.ts), so nothing here loops over triangles.
  // Overhang heat is a vertex attribute mixed in the shader: toggling it is a uniform.
  const heatOn = { value: 1 };
  const partMaterials: THREE.MeshStandardMaterial[] = [];
  const edgeMaterial = new THREE.LineBasicMaterial({ color: 0x30343a, transparent: true, opacity: 0.45 });
  const ghostMaterial = new THREE.MeshStandardMaterial({ color: 0x5ab4ff, transparent: true, opacity: 0.28, depthWrite: false });

  function partMaterial(i: number, hex?: string) {
    let m = partMaterials[i];
    if (!m) {
      m = new THREE.MeshStandardMaterial({ flatShading: true, roughness: 0.75, metalness: 0.02 });
      m.onBeforeCompile = (shader) => {
        shader.uniforms.uHeat = heatOn;
        shader.vertexShader = shader.vertexShader
          .replace('#include <common>', '#include <common>\nattribute float heat;\nuniform float uHeat;\nvarying float vHeat;')
          .replace('#include <begin_vertex>', '#include <begin_vertex>\nvHeat = heat * uHeat;');
        shader.fragmentShader = shader.fragmentShader
          .replace('#include <common>', '#include <common>\nvarying float vHeat;')
          .replace('#include <color_fragment>', '#include <color_fragment>\nif (vHeat > 0.0) diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.745, 0.054, 0.025), min(1.0, 0.25 + vHeat));');
      };
      m.customProgramCacheKey = () => 'fw-heat';
      partMaterials[i] = m;
    }
    m.color.copy(partColor(i, hex));
    if (m.transparent !== photoMode) {
      m.transparent = photoMode;
      m.needsUpdate = true;
    }
    m.opacity = photoMode ? 0.82 : 1;
    return m;
  }

  function clearModel() {
    for (const c of [...modelGroup.children]) {
      modelGroup.remove(c);
      (c as THREE.Mesh).geometry?.dispose();
    }
  }

  function rebuildModel(b: BuildResult) {
    clearModel();
    const d = b.display;
    if (d.position.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(d.position, 3));
      g.setAttribute('heat', new THREE.BufferAttribute(d.heat, 1, true));
      const mats = d.groups.map(([start, count, part], k) => {
        g.addGroup(start, count, k);
        return partMaterial(part, b.parts[part]?.color);
      });
      g.computeBoundingSphere();
      modelGroup.add(new THREE.Mesh(g, mats));
    }
    if (d.edges.length) {
      edgeMaterial.color.set(photoMode ? 0xff7a28 : 0x30343a);
      edgeMaterial.opacity = photoMode ? 0.9 : 0.45;
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(d.edges, 3));
      modelGroup.add(new THREE.LineSegments(g, edgeMaterial));
    }
    if (d.ghost.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(d.ghost, 3));
      g.computeVertexNormals();
      const mesh = new THREE.Mesh(g, ghostMaterial);
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

  // what the hovered handle changes, so the orange dots never read as warnings
  let handlesSeen = $state(false);
  try {
    handlesSeen = localStorage.getItem('fw_handles_seen') === '1';
  } catch {
    /* storage blocked: keep showing the hint */
  }
  $effect(() => {
    if (!hoverHandle || handlesSeen) return;
    handlesSeen = true;
    try {
      localStorage.setItem('fw_handles_seen', '1');
    } catch {
      /* ignore */
    }
  });
  const handleTip = $derived.by(() => {
    if (!build?.handles?.length || !editable || photoMode || sculptOn) return null;
    const h = hoverHandle ? build.handles.find((x) => handleKey(x) === hoverHandle) : null;
    if (!h) return handlesSeen ? null : { hint: true, text: t('handles_hint') };
    const names = h.type === 'point' ? h.params : [h.param];
    const val = names
      .map((n) => {
        const v = values[n];
        const u = specs[n]?.unit;
        return `${typeof v === 'number' ? +v.toFixed(2) : v}${u ? ' ' + unitLabel(u) : ''}`;
      })
      .join(' × ');
    return { hint: false, text: `${h.label ?? specs[names[0]]?.label ?? names[0]} · ${val}` };
  });

  function rebuildHandles() {
    disposeGroup(handleGroup);
    if (!build || !editable || sculptOn) return;
    const size = Math.max(2, Math.min(6, sceneSize() * 0.025));
    for (const h of build.handles ?? []) {
      const key = handleKey(h);
      const at = new THREE.Vector3(...h.at);
      const color = hoverHandle === key ? 0xffffff : cssColor('--primary', '#b1d355');
      const s = new THREE.Mesh(new THREE.SphereGeometry(size, 20, 14), new THREE.MeshBasicMaterial({ color, depthTest: false }));
      s.position.copy(at);
      s.renderOrder = 10;
      s.userData.handle = h;
      handleGroup.add(s);
      const ring = new THREE.Mesh(new THREE.RingGeometry(size * 1.15, size * 1.45, 24), new THREE.MeshBasicMaterial({ color: cssColor('--surface', '#13140f'), side: THREE.DoubleSide, depthTest: false }));
      ring.position.copy(at);
      ring.renderOrder = 9;
      ring.lookAt(camera.position);
      handleGroup.add(ring);
      if ('axis' in h) {
        const a = new THREE.Vector3(...h.axis).normalize();
        const arrow = new THREE.ArrowHelper(a, at, size * 4, cssColor('--primary', '#b1d355'), size * 1.4, size * 0.9);
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

  // ---------- sculpting (mesh documents) ----------
  type Brush = 'grab' | 'draw' | 'inflate' | 'crease' | 'smooth' | 'flatten' | 'pinch';
  const BRUSHES: { id: Brush; icon: string }[] = [
    { id: 'draw', icon: 'brush' }, { id: 'grab', icon: 'hand-grab' }, { id: 'inflate', icon: 'balloon' }, { id: 'crease', icon: 'scribble' },
    { id: 'smooth', icon: 'wave' }, { id: 'flatten', icon: 'minus' }, { id: 'pinch', icon: 'arrows-minimize' },
  ];
  const FACTOR: Brush[] = ['smooth', 'flatten', 'pinch'];
  let sculptOn = $state(false);
  let brush = $state<Brush>('draw');
  let brushRadius = $state(4);
  let brushStrength = $state(1);
  let carve = $state(false);
  let sculptStroke: { points: THREE.Vector3[]; start: THREE.Vector3; end: THREE.Vector3; plane: THREE.Plane } | null = null;
  const cursorMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, depthTest: false, side: THREE.DoubleSide });
  const cursor = new THREE.Mesh(new THREE.RingGeometry(0.9, 1, 48), cursorMat);
  const cursorMirror = new THREE.Mesh(cursor.geometry, new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.4, depthTest: false, side: THREE.DoubleSide }));
  const strokeLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xff7a28, depthTest: false }));
  for (const o of [cursor, cursorMirror, strokeLine]) {
    o.visible = false;
    o.renderOrder = 12;
  }

  function setSculpt(on: boolean) {
    sculptOn = on;
    if (on) {
      const s = sceneSize();
      brushRadius = Math.max(0.5, Math.round(s * 0.04 * 2) / 2);
    }
    cursor.visible = cursorMirror.visible = strokeLine.visible = false;
    issueGroup.visible = !on; // printability boxes would sit in the way of the brush
    controls.enabled = !photoMode;
    rebuildHandles();
  }

  function pickBrush(b: Brush) {
    if (FACTOR.includes(b) !== FACTOR.includes(brush)) brushStrength = FACTOR.includes(b) ? 0.5 : 1;
    brush = b;
  }

  function hitModel(ev: PointerEvent) {
    ray(ev);
    const meshes = modelGroup.children.filter((c) => c instanceof THREE.Mesh && !c.userData.modifier);
    const h = raycaster.intersectObjects(meshes, false)[0];
    if (!h?.face) return null;
    return { point: h.point.clone(), normal: h.face.normal.clone().transformDirection(h.object.matrixWorld) };
  }

  function placeCursor(h: { point: THREE.Vector3; normal: THREE.Vector3 } | null) {
    cursor.visible = !!h;
    cursorMirror.visible = !!h && !!symmetry;
    if (!h) return;
    cursorMat.color.set(carve && !FACTOR.includes(brush) && brush !== 'grab' ? 0xff6a5a : 0xffffff);
    cursor.position.copy(h.point);
    cursor.lookAt(h.point.clone().add(h.normal));
    cursor.scale.setScalar(brushRadius);
    if (symmetry) {
      const k = symmetry === 'x' ? 'x' : 'y';
      const p = h.point.clone(), n = h.normal.clone();
      p[k] = -p[k];
      n[k] = -n[k];
      cursorMirror.position.copy(p);
      cursorMirror.lookAt(p.clone().add(n));
      cursorMirror.scale.setScalar(brushRadius);
    }
  }

  function drawStroke() {
    if (!sculptStroke) return;
    const pts = brush === 'grab' ? [sculptStroke.start, sculptStroke.end] : sculptStroke.points;
    strokeLine.geometry.dispose();
    strokeLine.geometry = new THREE.BufferGeometry().setFromPoints(pts);
    strokeLine.visible = pts.length > 1;
  }

  function finishStroke() {
    const st = sculptStroke;
    sculptStroke = null;
    strokeLine.visible = false;
    if (!st) return;
    const r2 = (v: number) => Math.round(v * 100) / 100;
    const P = (v: THREE.Vector3) => [r2(v.x), r2(v.y), r2(v.z)];
    const op: Record<string, any> = { op: 'sculpt', by: 'user', brush, radius: r2(brushRadius) };
    if (brush === 'grab') {
      if (st.end.distanceTo(st.start) < 0.05) return;
      op.at = P(st.start);
      op.to = P(st.end);
    } else {
      op.strength = r2(carve && !FACTOR.includes(brush) ? -brushStrength : brushStrength);
      // a long stroke keeps every point about a quarter radius apart, at most 160 of them
      const step = Math.max(1, Math.ceil(st.points.length / 160));
      const pts = st.points.filter((_, i) => i % step === 0 || i === st.points.length - 1);
      if (pts.length > 1) op.path = pts.map(P);
      else op.at = P(pts[0]);
    }
    onSculpt?.(op);
  }

  function onKey(ev: KeyboardEvent) {
    if (!sculptOn || !(ev.ctrlKey || ev.metaKey) || ev.key.toLowerCase() !== 'z') return;
    const el = ev.target as HTMLElement | null;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
    ev.preventDefault();
    onUndo?.();
  }

  function onDown(ev: PointerEvent) {
    if (sculptOn && build && editable && !photoMode) {
      const h = hitModel(ev);
      // off the model the drag turns the view as usual
      if (!h) return;
      const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()), h.point);
      sculptStroke = { points: [h.point], start: h.point, end: h.point.clone(), plane };
      carve = ev.altKey ? !carve : carve;
      controls.enabled = false;
      canvas.setPointerCapture(ev.pointerId);
      ev.preventDefault();
      return;
    }
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
    if (sculptOn) {
      const h = hitModel(ev);
      placeCursor(h);
      if (!sculptStroke) return;
      if (brush === 'grab') {
        const q = new THREE.Vector3();
        if (ray(ev).intersectPlane(sculptStroke.plane, q)) sculptStroke.end = q;
      } else if (h && h.point.distanceTo(sculptStroke.points[sculptStroke.points.length - 1]) > brushRadius / 4) sculptStroke.points.push(h.point);
      drawStroke();
      return;
    }
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
    if (sculptStroke) {
      if (ev.altKey) carve = !carve;
      finishStroke();
      controls.enabled = !photoMode;
      try {
        canvas.releasePointerCapture(ev.pointerId);
      } catch {
        /* already released */
      }
      return;
    }
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
    reticle = new THREE.Mesh(new THREE.RingGeometry(0.03, 0.04, 32).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: cssColor('--primary', '#b1d355') }));
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
    scene.background = photoMode ? null : cssColor('--surface', '#13140f');
    const visible = bed?.visible ?? true;
    if (bed) {
      scene.remove(bed);
      disposeGroup(bed);
    }
    bed = makeBed();
    bed.visible = visible;
    scene.add(bed);
    rebuildHandles();
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
    scene.add(modelGroup, issueGroup, handleGroup, cursor, cursorMirror, strokeLine);
    addEventListener('keydown', onKey);
    applyTheme();
    const mq = matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', applyTheme);
    // a picked theme is written inline on <html> and its colours animate; repaint once they settle
    let themeFrame = 0;
    const themeObserver = new MutationObserver(() => {
      cancelAnimationFrame(themeFrame);
      if (!document.documentElement.hasAttribute('data-theme-shift')) themeFrame = requestAnimationFrame(applyTheme);
    });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-theme-shift'] });
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
      themeObserver.disconnect();
      cancelAnimationFrame(themeFrame);
      renderer.setAnimationLoop(null);
      removeEventListener('keydown', onKey);
      cursor.geometry.dispose();
      strokeLine.geometry.dispose();
      xrSession?.end?.();
      controls.dispose();
      clearModel();
      for (const m of [...partMaterials, edgeMaterial, ghostMaterial]) m?.dispose();
      disposeGroup(issueGroup);
      disposeGroup(handleGroup);
      renderer.dispose();
    };
  });

  $effect(() => {
    heatOn.value = showHeat ? 1 : 0;
  });

  $effect(() => {
    const on = showModifiers;
    for (const c of modelGroup.children) if (c.userData.modifier) c.visible = on;
  });

  $effect(() => {
    // new geometry
    const b = build;
    if (!renderer) return;
    if (b) {
      untrack(() => rebuildModel(b));
      const box = bbox();
      const key = box.getSize(new THREE.Vector3()).toArray().map((v) => Math.round(Math.log2(v + 1) * 2)).join(',');
      if (key !== lastFitKey && !photoMode) {
        lastFitKey = key;
        fit();
      }
    } else clearModel();
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
    <canvas bind:this={canvas} onpointerdown={onDown} onpointermove={onMove} onpointerup={onUp} onpointercancel={onUp} onpointerleave={() => !drag && (hoverHandle = null)} aria-label="3D model viewer"></canvas>
    {#if handleTip}<div class="htip xs" class:hint={handleTip.hint}>{handleTip.text}</div>{/if}
    {#if !build}
      <div class="empty muted">
        {#if loading}<span class="loading"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('building_model')}</span>{:else}<span class="ghost"><svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.7z M3.3 7L12 12l8.7-5 M12 22V12" /></svg></span>{/if}
      </div>
    {/if}
  </div>
  {#if sculptOn}
    <div class="sculptbar" role="toolbar" aria-label={t('sculpt')}>
      <div class="brushes">
        {#each BRUSHES as b (b.id)}
          <button class="bb" class:on={brush === b.id} onclick={() => pickBrush(b.id)} aria-pressed={brush === b.id} title={t('brush.' + b.id)} aria-label={t('brush.' + b.id)}><Icon name={b.icon} size={16} /></button>
        {/each}
      </div>
      <label class="sl"><span class="xs">{t('brush_radius')} <span class="mono">{brushRadius}</span></span>
        <input type="range" min="0.5" max={Math.max(20, Math.round(sceneSize() * 0.25))} step="0.5" bind:value={brushRadius} /></label>
      {#if brush !== 'grab'}
        <label class="sl"><span class="xs">{t('brush_strength')} <span class="mono">{brushStrength}</span></span>
          <input type="range" min={FACTOR.includes(brush) ? 0.05 : 0.1} max={FACTOR.includes(brush) ? 1 : 4} step="0.05" bind:value={brushStrength} /></label>
      {/if}
      <div class="row">
        {#if !FACTOR.includes(brush) && brush !== 'grab'}
          <button class="bb" class:on={carve} onclick={() => (carve = !carve)} aria-pressed={carve} title={t('brush_invert')} aria-label={t('brush_invert')}><Icon name="minus" size={15} /></button>
        {/if}
        <button class="bb" class:on={!!symmetry} onclick={() => onSymmetry?.()} aria-pressed={!!symmetry} title={t('symmetry')} aria-label={t('symmetry')}><Icon name="flip" size={15} /></button>
        <button class="bb" onclick={() => onUndo?.()} disabled={!canUndo} title="{t('undo')} (Ctrl+Z)" aria-label={t('undo')}><Icon name="undo" size={15} /></button>
      </div>
      <p class="xs hint">{t('sculpt_hint')}</p>
    </div>
  {/if}
  <div class="tools" bind:this={arOverlay}>
    <button class="btn small" class:on={showHeat} onclick={() => (showHeat = !showHeat)} aria-pressed={showHeat} title={t('heat')}><Icon name="flame" size={14} /> <span class="tl">{t('heat')}</span></button>
    {#if build?.parts?.some((p) => p.role !== 'model')}
      <button class="btn small" class:on={showModifiers} onclick={() => (showModifiers = !showModifiers)} aria-pressed={showModifiers} title={t('modifiers')}><Icon name="layers" size={14} /> <span class="tl">{t('modifiers')}</span></button>
    {/if}
    {#if photo}
      <button class="btn small" class:on={photoMode} onclick={() => setPhotoMode(!photoMode)} aria-pressed={photoMode} title={t('photo_ar')}><Icon name="image" size={14} /> <span class="tl">{t('photo_ar')}</span></button>
    {/if}
    {#if arSupported}
      <button class="btn small" onclick={() => (arActive ? xrSession?.end() : startAR())}><Icon name="cube" size={14} /> {arActive ? t('stop') : t('live_ar')}</button>
    {/if}
    {#if sculptable && editable && !photoMode}
      <button class="btn small" class:on={sculptOn} onclick={() => setSculpt(!sculptOn)} aria-pressed={sculptOn} title={t('sculpt')}><Icon name="brush" size={14} /> <span class="tl">{t('sculpt')}</span></button>
    {/if}
    {#if !photoMode}<button class="btn small icon" onclick={fit} aria-label={t('reset_view')} title={t('reset_view')}><Icon name="maximize" size={14} /></button>{/if}
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
    background: var(--surface);
    border-radius: var(--radius-card);
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
  .htip {
    position: absolute;
    left: 50%;
    top: 10px;
    transform: translateX(-50%);
    background: var(--surface-container);
    border: var(--border-width) solid var(--primary);
    color: var(--on-surface);
    border-radius: var(--radius-tag);
    padding: 3px 10px;
    pointer-events: none;
    white-space: nowrap;
    max-width: calc(100% - 24px);
    overflow: hidden;
    text-overflow: ellipsis;
    z-index: 2;
  }
  .htip.hint {
    top: auto;
    bottom: 48px;
    border-color: var(--outline-variant);
    color: var(--outline);
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
  .loading {
    display: inline-flex;
    gap: 8px;
    align-items: center;
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
  .sculptbar {
    position: absolute;
    top: 8px;
    right: 8px;
    width: 184px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 8px;
    border-radius: var(--radius-card);
    background: color-mix(in srgb, var(--surface-container) 88%, transparent);
    backdrop-filter: blur(6px);
    border: var(--border-width) solid var(--outline-variant);
    z-index: 3;
  }
  .brushes {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
  }
  .sculptbar .row {
    display: flex;
    gap: 4px;
  }
  .bb {
    height: 34px;
    min-width: 34px;
    display: grid;
    place-items: center;
    border-radius: var(--radius-btn);
    border: var(--border-width) solid var(--outline-variant);
    background: var(--surface);
    color: var(--on-surface-var);
    cursor: pointer;
    padding: 0;
  }
  .bb.on {
    border-color: var(--primary);
    color: var(--primary);
    background: color-mix(in srgb, var(--primary) 14%, var(--surface));
  }
  .bb:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .sl {
    display: flex;
    flex-direction: column;
    gap: 2px;
    color: var(--on-surface-var);
  }
  .sl input {
    width: 100%;
  }
  .sculptbar .hint {
    margin: 0;
    color: var(--outline);
  }
  /* phones: one compact strip above the view tools, the model stays visible */
  @media (max-width: 520px) {
    .sculptbar {
      width: auto;
      left: 8px;
      top: auto;
      bottom: 50px;
      padding: 6px;
      gap: 6px;
      display: grid;
      grid-template-columns: 1fr 1fr;
    }
    .brushes {
      grid-column: 1 / -1;
      grid-template-columns: repeat(7, 1fr);
    }
    .bb {
      height: 30px;
      min-width: 30px;
    }
    .sculptbar .row {
      grid-column: 1 / -1;
      justify-content: flex-end;
    }
    .sculptbar .hint {
      display: none;
    }
  }
  .tools .btn {
    background: color-mix(in srgb, var(--surface-container) 85%, transparent);
    backdrop-filter: blur(6px);
  }
  .empty {
    gap: 8px;
  }
  .ghost {
    opacity: 0.35;
  }
  @media (max-width: 520px) {
    .tools .tl {
      display: none;
    }
  }
</style>
