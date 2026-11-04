<script lang="ts">
  // The QC report (contract C10): the print photographed on A4 with SAM 3.1's mask, and the two outlines in mm on
  // the sheet's grid, the model's already moved onto the print by the server. Honest about what it sees: the
  // outline in plan, not heights or snaps.
  import Icon from '$lib/components/Icon.svelte';
  import SnapHighlight from '$lib/components/SnapHighlight.svelte';
  import { i18n } from '$lib/i18n.svelte';
  import { mm, qcError, st, when } from './i18n';
  import type { QcReport } from './types';

  // operator: the farm also reads the measuring step's own words when a photo could not be measured
  let { qc, operator = false }: { qc: QcReport; operator?: boolean } = $props();

  const tol = $derived(qc.tolerance_mm ?? 0.6);
  const target = $derived(qc.target_mm ?? []);
  const printed = $derived(qc.printed_mm ?? []);
  const drawable = $derived(target.length > 2 && printed.length > 2);

  // the frame around both outlines, in sheet mm (y up), with room for the labels
  const view = $derived.by(() => {
    const pts = [...target, ...printed];
    if (!pts.length) return null;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [x, y] of pts) {
      x0 = Math.min(x0, x);
      x1 = Math.max(x1, x);
      y0 = Math.min(y0, y);
      y1 = Math.max(y1, y);
    }
    const ext = Math.max(x1 - x0, y1 - y0, 10);
    const pad = ext * 0.14 + 3;
    // the frame's own 4:3, so the sheet fills the pane next to the photo
    const w = Math.max(x1 - x0 + 2 * pad, ((y1 - y0 + 2 * pad) * 4) / 3);
    const h = (w * 3) / 4;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    return { x: cx - w / 2, y: cy - h / 2, w, h, ext };
  });
  // SVG y grows down: flip the sheet's y
  const path = (loop: number[][]) => (loop.length ? `M${loop.map(([x, y]) => `${x.toFixed(2)} ${(-y).toFixed(2)}`).join('L')}Z` : '');
  const grid = $derived.by(() => {
    const g = { vMajor: [] as number[], vMinor: [] as number[], hMajor: [] as number[], hMinor: [] as number[] };
    if (!view) return g;
    const step = view.ext > 70 ? 5 : 1;
    for (let x = Math.ceil(view.x / step) * step; x <= view.x + view.w; x += step) (Math.round(x) % 10 === 0 ? g.vMajor : g.vMinor).push(x);
    for (let y = Math.ceil(view.y / step) * step; y <= view.y + view.h; y += step) (Math.round(y) % 10 === 0 ? g.hMajor : g.hMinor).push(y);
    return g;
  });
  const worst = $derived.by(() => {
    const regs = (qc.regions ?? []).filter((r) => r.center_sheet?.length === 2);
    if (!regs.length) return null;
    // max_mm is signed (print smaller than the model: negative); the marker shows the size of the worst one
    return regs.reduce((a, b) => (Math.abs(b.max_mm) > Math.abs(a.max_mm) ? b : a));
  });
  const fs = $derived(view ? view.ext * 0.06 + 1.2 : 3);
  // line widths in mm, about 2 px on screen (a non-scaling stroke would break the pathLength dashes of the draw-in)
  const sw = $derived(view ? view.w / 280 : 0.3);

  // the photo's own size, for the mask overlay
  let size = $state<{ w: number; h: number } | null>(null);
  // where the part is in the photo, as fractions of it, from SAM's mask: the whole A4 sheet is in frame for the
  // calibration, so the pane zooms to the part (it would be a dot) and the mask shows
  let part = $state<[number, number, number, number] | null>(null);
  const focus = $derived<[number, number, number, number] | null>(
    part && size ? [part[0] * size.w, part[1] * size.h, part[2] * size.w, part[3] * size.h] : null,
  );
  $effect(() => {
    const src = qc.mask_url;
    part = null;
    if (!src) return;
    const img = new Image();
    img.onload = () => {
      try {
        const k = Math.min(1, 400 / Math.max(img.naturalWidth, img.naturalHeight));
        const w = Math.max(1, Math.round(img.naturalWidth * k));
        const h = Math.max(1, Math.round(img.naturalHeight * k));
        const c = document.createElement('canvas');
        c.width = w;
        c.height = h;
        const g = c.getContext('2d');
        if (!g) return;
        g.drawImage(img, 0, 0, w, h);
        const d = g.getImageData(0, 0, w, h).data;
        let x0 = w, y0 = h, x1 = -1, y1 = -1;
        for (let y = 0; y < h; y++)
          for (let x = 0; x < w; x++)
            if (d[(y * w + x) * 4] > 127) {
              x0 = Math.min(x0, x);
              x1 = Math.max(x1, x);
              y0 = Math.min(y0, y);
              y1 = Math.max(y1, y);
            }
        if (x1 >= 0) part = [x0 / w, y0 / h, (x1 + 1) / w, (y1 + 1) / h];
      } catch {
        /* an unreadable mask: the whole photo, as before */
      }
    };
    img.src = src;
  });
  $effect(() => {
    const src = qc.photo_url;
    size = null;
    if (!src) return;
    const img = new Image();
    img.onload = () => (size = { w: img.naturalWidth, h: img.naturalHeight });
    img.src = src;
  });
</script>

<section class="qc card" class:pass={qc.pass && !qc.error} class:fail={!qc.pass && !qc.error}>
  <div class="row head">
    <h3 class="section-title">{st('qc.title')}</h3>
    {#if !qc.error && qc.max_mm != null}
      <span class="verdict" class:ok={qc.pass}>{qc.pass ? st('qc.pass') : st('qc.fail')}</span>
    {/if}
  </div>

  {#if qc.error}
    <p class="small err"><Icon name="alert" size={14} /> {st('qc.error', { x: qcError(qc, operator) })}</p>
  {/if}

  <div class="panes" class:single={!drawable || !qc.photo_url}>
    {#if qc.photo_url}
      <figure class="photo">
        {#if size && qc.mask_url}
          <SnapHighlight src={qc.photo_url} width={size.w} height={size.h} maskUrl={qc.mask_url} fit="contain" {focus} zoom={8} />
        {:else}
          <img src={qc.photo_url} alt={st('qc.photo')} />
        {/if}
        <figcaption class="xs">{st('qc.photo')} · SAM 3.1</figcaption>
      </figure>
    {/if}
    {#if drawable && view}
      <figure class="overlay">
        <svg viewBox="{view.x} {-(view.y + view.h)} {view.w} {view.h}" role="img" aria-label="{st('qc.model')} / {st('qc.print')}">
          <rect x={view.x} y={-(view.y + view.h)} width={view.w} height={view.h} class="paper" />
          {#each grid.vMinor as x (x)}<line x1={x} x2={x} y1={-(view.y + view.h)} y2={-view.y} class="minor" />{/each}
          {#each grid.hMinor as y (y)}<line y1={-y} y2={-y} x1={view.x} x2={view.x + view.w} class="minor" />{/each}
          {#each grid.vMajor as x (x)}<line x1={x} x2={x} y1={-(view.y + view.h)} y2={-view.y} class="major" />{/each}
          {#each grid.hMajor as y (y)}<line y1={-y} y2={-y} x1={view.x} x2={view.x + view.w} class="major" />{/each}
          {#key qc.at}
            <path d={path(target)} class="target" pathLength="100" stroke-width={sw} />
            <path d={path(printed)} class="printed" pathLength="100" stroke-width={sw * 1.15} />
          {/key}
          {#if worst?.center_sheet}
            {@const [wx, wy] = worst.center_sheet}
            <circle cx={wx} cy={-wy} r={fs * 0.9} class="worst" class:bad={Math.abs(worst.max_mm) > tol} />
            {@const left = wx + fs * 6 > view.x + view.w}
            <text x={left ? wx - fs * 1.2 : wx + fs * 1.2} y={-wy - fs * 0.5} font-size={fs} text-anchor={left ? 'end' : 'start'} class="wlabel" class:bad={Math.abs(worst.max_mm) > tol}>{st('qc.worst', { n: mm(Math.abs(worst.max_mm)) })}</text>
          {/if}
          <!-- a 10 mm scale bar in the corner -->
          <g class="bar">
            <line x1={view.x + fs} x2={view.x + fs + 10} y1={-(view.y + fs)} y2={-(view.y + fs)} />
            <text x={view.x + fs} y={-(view.y + fs * 1.6)} font-size={fs * 0.8}>10 {i18n.lang === 'ru' ? 'мм' : 'mm'}</text>
          </g>
        </svg>
        <figcaption class="row xs">
          <span class="key target"></span>{st('qc.model')}
          <span class="key printed"></span>{st('qc.print')}
          <span class="muted">· {st('qc.grid')}</span>
        </figcaption>
      </figure>
    {/if}
  </div>

  {#if !qc.error && qc.max_mm != null}
    <div class="row nums">
      <strong class="mono max" class:bad={!qc.pass}>{st('qc.max', { n: mm(qc.max_mm) })}</strong>
      {#if qc.mean_mm != null}<span class="mono">{st('qc.mean', { n: mm(qc.mean_mm) })}</span>{/if}
      <span class="chip" class:ok={qc.pass} class:err={!qc.pass}>{st('qc.caption', { t: tol })}</span>
    </div>
    <p class="xs muted">{st('qc.honest')}{#if qc.at}{' · '}{when(qc.at)}{/if}</p>
  {/if}
</section>

<style>
  .qc {
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .qc.pass {
    border-color: color-mix(in srgb, var(--primary) 50%, var(--outline-variant));
  }
  .qc.fail {
    border-color: color-mix(in srgb, var(--error) 50%, var(--outline-variant));
  }
  .head {
    justify-content: space-between;
  }
  .verdict {
    font-family: var(--font-mono);
    font-weight: var(--font-weight-bold);
    padding: 3px 10px;
    border-radius: var(--radius-tag);
    background: color-mix(in srgb, var(--error) 18%, transparent);
    color: var(--error);
    animation: stamp var(--dur-slow) var(--ease-pop);
  }
  .verdict.ok {
    background: var(--primary);
    color: var(--on-primary);
  }
  @keyframes stamp {
    from {
      transform: scale(1.6);
      opacity: 0;
    }
  }
  .panes {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-3);
  }
  .panes.single {
    grid-template-columns: minmax(0, 1fr);
  }
  figure {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }
  figcaption {
    color: var(--outline);
    gap: 6px;
  }
  .photo :global(.hl),
  .photo img {
    width: 100%;
    aspect-ratio: 4 / 3;
    border-radius: var(--radius-btn);
    overflow: hidden;
    object-fit: contain;
    background: #000;
    display: block;
  }
  svg {
    width: 100%;
    aspect-ratio: 4 / 3;
    border-radius: var(--radius-btn);
    display: block;
    overflow: hidden;
  }
  .paper {
    fill: #f7f7f2;
  }
  .minor {
    stroke: #dfe3e8;
    stroke-width: 0.6;
    vector-effect: non-scaling-stroke;
  }
  .major {
    stroke: #b7c0cb;
    stroke-width: 1;
    vector-effect: non-scaling-stroke;
  }
  path {
    fill: none;
    stroke-linejoin: round;
    stroke-dasharray: 100;
    animation: draw 1.4s var(--ease-emphasized) both;
  }
  path.target {
    stroke: #2f6fdb;
    fill: rgb(47 111 219 / 0.08);
  }
  path.printed {
    stroke: #d2462f;
    animation-delay: 0.5s;
  }
  @keyframes draw {
    from {
      stroke-dashoffset: 100;
    }
    to {
      stroke-dashoffset: 0;
    }
  }
  .worst {
    fill: none;
    stroke: #2c8a3c;
    stroke-width: 1.5;
    vector-effect: non-scaling-stroke;
  }
  .worst.bad {
    stroke: #d2462f;
  }
  .wlabel.bad {
    fill: #d2462f;
  }
  .wlabel {
    fill: #2c8a3c;
    font-family: var(--font-mono);
    font-weight: 700;
  }
  .bar line {
    stroke: #333;
    stroke-width: 2;
    vector-effect: non-scaling-stroke;
  }
  .bar text {
    fill: #333;
    font-family: var(--font-mono);
  }
  .key {
    display: inline-block;
    width: 16px;
    height: 3px;
    border-radius: 2px;
  }
  .key.target {
    background: #2f6fdb;
  }
  .key.printed {
    background: #d2462f;
    margin-left: var(--space-2);
  }
  .nums {
    gap: var(--space-3);
    align-items: baseline;
  }
  .max {
    font-size: var(--text-xl);
    color: var(--primary);
  }
  .max.bad {
    color: var(--error);
  }
  .err {
    color: var(--error);
    margin: 0;
  }
  p {
    margin: 0;
  }
  @media (max-width: 560px) {
    .panes {
      grid-template-columns: minmax(0, 1fr);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    path,
    .verdict {
      animation: none;
    }
  }
</style>
