// The model in 3D: the parts the geometry worker built (packages/geom display buffers), on a print bed seen from
// three quarters, Z up as on the printer. Orbit with the mouse or a finger; "Porte-à-faux" tints the faces that would
// need supports (the worker's per-vertex heat).
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { BuildResult } from "../geom/types";
import { useLang, type Lang } from "../i18n";

const PART = new THREE.Color("#4f7cac");
const HOT = new THREE.Color("#f2b705");

interface Props {
  build: BuildResult | null;
  busy: boolean;
}

export default function Viewer({ build, busy }: Props) {
  const { lang, tr } = useLang();
  const host = useRef<HTMLDivElement>(null);
  const three = useRef<{ renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; controls: OrbitControls; model: THREE.Group; framed: boolean } | null>(null);
  const [heat, setHeat] = useState(false);
  const [noGl, setNoGl] = useState(false);
  const frameRef = useRef<() => void>(() => {});

  // the scene, once
  useEffect(() => {
    const el = host.current!;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    } catch {
      setNoGl(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.5, 5000);
    camera.up.set(0, 0, 1);
    camera.position.set(160, -200, 140);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 0, 10);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a96a3, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(120, -160, 260);
    scene.add(sun);
    // the bed: a 220 mm plate with a 10 mm grid
    const grid = new THREE.GridHelper(220, 22, 0xb3bec4, 0xd3dadc);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);
    const model = new THREE.Group();
    scene.add(model);
    three.current = { renderer, scene, camera, controls, model, framed: false };

    let shown = false;
    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      if (!w || !h) return; // a hidden pane (the phone layout shows one at a time)
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      // the first time the pane is seen at its real size, the model is framed for it
      if (!shown) {
        shown = true;
        if (three.current?.framed) frameRef.current();
      }
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();
    let raf = 0;
    const loop = () => {
      controls.update();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
      three.current = null;
    };
  }, []);

  // the model, each time a build comes in
  useEffect(() => {
    const t = three.current;
    if (!t) return;
    for (const c of [...t.model.children]) {
      t.model.remove(c);
      (c as THREE.Mesh).geometry?.dispose();
    }
    if (!build) return;
    const d = build.display;
    for (const [first, count, partIndex] of d.groups) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(d.position.subarray(first * 3, (first + count) * 3), 3));
      g.computeVertexNormals();
      const base = build.parts[partIndex]?.color ? new THREE.Color(build.parts[partIndex].color) : PART;
      let material: THREE.Material;
      if (heat && d.heat.length) {
        const colors = new Float32Array(count * 3);
        const c = new THREE.Color();
        for (let i = 0; i < count; i++) {
          c.copy(base).lerp(HOT, d.heat[first + i] / 255);
          colors.set([c.r, c.g, c.b], i * 3);
        }
        g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
        material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.6, metalness: 0.05 });
      } else material = new THREE.MeshStandardMaterial({ color: base, roughness: 0.55, metalness: 0.05 });
      t.model.add(new THREE.Mesh(g, material));
    }
    if (d.ghost.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(d.ghost, 3));
      g.computeVertexNormals();
      t.model.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0xa12c2c, transparent: true, opacity: 0.25, depthWrite: false })));
    }
    if (d.edges.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(d.edges, 3));
      t.model.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x1f3a5f, transparent: true, opacity: 0.45 })));
    }
    if (!t.framed) frame();
  }, [build, heat]);

  frameRef.current = () => frame();

  function frame() {
    const t = three.current;
    if (!t || !t.model.children.length) return;
    const box = new THREE.Box3().setFromObject(t.model);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const r = Math.max(size.length() / 2, 10);
    // the vertical field of view, widened for a narrow screen so the model fits across too
    const fov = (t.camera.fov * Math.PI) / 180;
    const half = Math.min(fov / 2, Math.atan(Math.tan(fov / 2) * t.camera.aspect));
    const dist = r / Math.sin(half);
    const dir = new THREE.Vector3(0.55, -0.7, 0.45).normalize();
    t.camera.position.copy(center).addScaledVector(dir, dist * 1.1);
    t.controls.target.copy(center);
    t.framed = true;
  }

  const size = build ? sizeOf(build, lang) : null;

  return (
    <div className="viewer">
      <div ref={host} className="viewer-canvas" role="img" aria-label={build ? `${tr("Modèle 3D", "3D model")}${size ? `, ${size}` : ""}` : tr("Aucun modèle pour l'instant", "No model yet")} />
      {noGl && <p className="viewer-empty">{tr("Votre navigateur n'affiche pas la 3D (WebGL désactivé).", "Your browser cannot show 3D (WebGL is off).")}</p>}
      {!build && !noGl && <p className="viewer-empty">{busy ? tr("Le modèle se construit…", "Building the model…") : tr("Le modèle apparaîtra ici dès que l'IA aura une première version.", "The model will show here as soon as the AI has a first version.")}</p>}
      {build && (
        <div className="viewer-bar">
          {size && <span className="viewer-size">{size}</span>}
          <button type="button" className="btn quiet small" onClick={frame}>{tr("Recentrer", "Recenter")}</button>
          <button type="button" className={`btn small ${heat ? "" : "quiet"}`} aria-pressed={heat} onClick={() => setHeat(!heat)}>{tr("Porte-à-faux", "Overhangs")}</button>
          {busy && <span className="viewer-busy">{tr("Mise à jour…", "Updating…")}</span>}
        </div>
      )}
    </div>
  );
}

function sizeOf(b: BuildResult, lang: Lang): string | null {
  const parts = b.parts.filter((p) => p.role === "model" || !p.role);
  if (!parts.length) return null;
  const min = [0, 1, 2].map((i) => Math.min(...parts.map((p) => p.bbox.min[i])));
  const max = [0, 1, 2].map((i) => Math.max(...parts.map((p) => p.bbox.max[i])));
  const nf = new Intl.NumberFormat(lang === "fr" ? "fr-FR" : "en-GB", { maximumFractionDigits: 1 });
  return `${nf.format(max[0] - min[0])} × ${nf.format(max[1] - min[1])} × ${nf.format(max[2] - min[2])} mm`;
}
