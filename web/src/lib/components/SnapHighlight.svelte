<script lang="ts">
  // A photo with the selected object lifted out of it: the rest dims, the object stays bright
  // with a soft glow, and a light runs along its outline. Also the scanning state while the
  // object is being found, the taps that refine the selection, and the labelled boxes of a
  // board scan (holes and ports bright, edge pads faint).
  import { cutout, place, toImage, toScreen, type Box, type Fit } from '$lib/snapframe';
  import type { ScanBox } from '$lib/types';

  let {
    src,
    width,
    height,
    maskUrl = null,
    outline = null,
    fit = 'cover',
    focus = null,
    zoom = 1.8,
    scanning = false,
    scanAt = null,
    points = [],
    label = null,
    anchor = null,
    compact = false,
    boxes = [],
    onTap,
  }: {
    src: string;
    width: number;
    height: number;
    maskUrl?: string | null;
    outline?: number[][] | null;
    fit?: Fit;
    focus?: Box | null;
    /** How far the focus box may zoom in, in multiples of the cover scale (a part on a whole A4 sheet needs more). */
    zoom?: number;
    scanning?: boolean;
    scanAt?: { x: number; y: number } | null;
    points?: { x: number; y: number; positive: boolean }[];
    label?: string | null;
    /** Box the name chip sits on (the focus box by default). */
    anchor?: Box | null;
    compact?: boolean;
    /** Labelled boxes in photo pixels; 'strong' ones flash in first with their label, 'dim' ones stay faint. */
    boxes?: ScanBox[];
    onTap?: (p: { x: number; y: number }) => void;
  } = $props();

  // strong boxes one after another, then the normal ones, then the faint crowd at once
  const RANK = { strong: 0, normal: 1, dim: 2 } as const;
  const shown = $derived.by(() => {
    const order = [...boxes].map((b, i) => ({ b, i, e: b.emphasis ?? 'normal' })).sort((a, b) => RANK[a.e] - RANK[b.e] || a.i - b.i);
    let strong = 0, normal = 0;
    const named = new Set<string>();
    return order.map(({ b, e }) => {
      const delay = e === 'strong' ? 150 + 140 * strong++ : e === 'normal' ? 700 + 70 * normal++ : 900 + Math.random() * 300;
      // a label once per kind (four "mounting hole"s read as one), right-aligned near the photo's right edge
      const text = e === 'strong' && !named.has(b.label) ? b.label : '';
      if (text) named.add(b.label);
      return { ...b, e, delay, text, end: b.box[0] > width * 0.6 };
    });
  });

  let cw = $state(0);
  let ch = $state(0);
  let host = $state<HTMLDivElement>();
  let lit = $state<HTMLCanvasElement>();
  let glow = $state<HTMLCanvasElement>();
  let cut = $state<HTMLCanvasElement | null>(null);
  let moving = $state(false);

  const p = $derived(place(cw, ch, width, height, fit, focus, zoom));
  const path = $derived(outline && outline.length > 2 ? `M${outline.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join('L')}Z` : '');
  const ring = $derived(scanAt ? toScreen(p, scanAt.x, scanAt.y) : null);
  const chip = $derived.by(() => {
    const at = anchor ?? focus;
    if (!label || !at || !cut) return null;
    const a = toScreen(p, (at[0] + at[2]) / 2, at[1]);
    return { x: Math.min(Math.max(a.x, 70), cw - 70), y: Math.max(a.y - 14, 34) };
  });

  // animate reframing only once the first placement is on screen
  $effect(() => {
    if (!cw || !ch || moving) return;
    const id = requestAnimationFrame(() => (moving = true));
    return () => cancelAnimationFrame(id);
  });

  $effect(() => {
    const m = maskUrl;
    cut = null;
    if (!m) return;
    let gone = false;
    cutout(src, m, compact ? 640 : 1400)
      .then((c) => !gone && (cut = c))
      .catch(() => {});
    return () => {
      gone = true;
    };
  });

  $effect(() => {
    for (const el of [lit, glow]) {
      if (!el || !cut) continue;
      el.width = cut.width;
      el.height = cut.height;
      el.getContext('2d')!.drawImage(cut, 0, 0);
    }
  });

  function tap(ev: PointerEvent) {
    if (!onTap || !host) return;
    const r = host.getBoundingClientRect();
    const q = toImage(p, ev.clientX - r.left, ev.clientY - r.top, width, height);
    if (q) onTap(q);
  }
</script>

<div class="hl" class:compact class:tappable={!!onTap} bind:this={host} bind:clientWidth={cw} bind:clientHeight={ch} role="application" aria-label={label ?? undefined} onpointerup={tap}>
  <div class="frame" class:moving style:width="{width}px" style:height="{height}px" style:transform="translate({p.x}px, {p.y}px) scale({p.s})">
    <img class="photo" class:dim={!!cut} class:boxed={!cut && boxes.length > 0} {src} alt="" draggable="false" />
    {#if maskUrl}
      {#key maskUrl}
        <canvas class="glow" class:on={!!cut} bind:this={glow} style:--r1="{(compact ? 5 : 9) / p.s}px" style:--r2="{(compact ? 1.5 : 2.5) / p.s}px"></canvas>
        <canvas class="lit" class:on={!!cut} bind:this={lit}></canvas>
        {#if path && cut && !compact}
          <svg class="trace" viewBox="0 0 {width} {height}" aria-hidden="true">
            <path class="line" d={path} pathLength="100" stroke-width={1.6 / p.s} />
            <path class="spark" d={path} pathLength="100" stroke-width={3 / p.s} />
          </svg>
        {/if}
      {/key}
    {/if}
    {#if shown.length}
      <svg class="boxes" viewBox="0 0 {width} {height}" aria-hidden="true">
        {#each shown as b, i (i)}
          {@const [x1, y1, x2, y2] = b.box}
          <g class="bx {b.e}" style:animation-delay="{b.delay}ms">
            <rect x={x1} y={y1} width={Math.max(1, x2 - x1)} height={Math.max(1, y2 - y1)} rx={2 / p.s} stroke-width={(b.e === 'dim' ? 1 : 2) / p.s} pathLength="100" />
            {#if b.text && !compact}
              <text x={b.end ? x2 : x1} y={y1 - 4 / p.s} text-anchor={b.end ? 'end' : 'start'} font-size={11 / p.s} stroke-width={3 / p.s}>{b.text}</text>
            {/if}
          </g>
        {/each}
      </svg>
    {/if}
  </div>

  {#if scanning}
    <div class="scan" aria-hidden="true"><span class="band"></span></div>
    {#if ring}<span class="ring" style:left="{ring.x}px" style:top="{ring.y}px" aria-hidden="true"><i></i><i></i></span>{/if}
  {/if}

  {#each points as pt, i (i)}
    {@const s = toScreen(p, pt.x, pt.y)}
    <span class="pt" class:neg={!pt.positive} style:left="{s.x}px" style:top="{s.y}px" aria-hidden="true">{pt.positive ? '+' : '−'}</span>
  {/each}

  {#if chip}
    <span class="label" style:left="{chip.x}px" style:top="{chip.y}px">{label}</span>
  {/if}
</div>

<style>
  .hl {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    background: #000;
    touch-action: manipulation;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
  }
  .hl.tappable {
    cursor: crosshair;
  }
  .frame {
    position: absolute;
    left: 0;
    top: 0;
    transform-origin: 0 0;
    will-change: transform;
  }
  .frame.moving {
    transition: transform 620ms var(--ease-emphasized);
  }
  .frame > * {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
  }
  .photo {
    max-width: none;
    transition: filter 520ms var(--ease-standard);
  }
  .photo.dim {
    filter: brightness(0.4) saturate(0.35);
  }
  .compact .photo.dim {
    filter: brightness(0.5) saturate(0.5);
  }
  .photo.boxed {
    filter: brightness(0.62) saturate(0.6);
  }
  .boxes {
    overflow: visible;
    pointer-events: none;
  }
  .bx {
    opacity: 0;
    animation: box-in 460ms var(--ease-pop) forwards;
  }
  .bx rect {
    fill: color-mix(in srgb, var(--primary) 10%, transparent);
    stroke: var(--primary);
    stroke-dasharray: 100;
    stroke-dashoffset: 100;
    animation: draw 520ms var(--ease-out) forwards;
    animation-delay: inherit;
    filter: drop-shadow(0 0 3px color-mix(in srgb, var(--primary) 70%, transparent));
  }
  .bx.normal rect {
    stroke: color-mix(in srgb, var(--primary) 70%, white);
    fill: none;
    filter: none;
  }
  .bx.dim rect {
    stroke: rgb(255 255 255 / 0.45);
    fill: none;
    filter: none;
  }
  .bx.dim {
    animation-name: box-in-dim;
  }
  .bx text {
    fill: #fff;
    stroke: rgb(0 0 0 / 0.65);
    paint-order: stroke;
    font-weight: var(--font-weight-bold);
    font-family: var(--font-mono, monospace);
  }
  @keyframes box-in {
    from {
      opacity: 0;
    }
    30% {
      opacity: 1;
    }
    to {
      opacity: 1;
    }
  }
  @keyframes box-in-dim {
    to {
      opacity: 0.8;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .bx,
    .bx rect {
      animation: none;
      opacity: 1;
      stroke-dashoffset: 0;
    }
  }
  canvas {
    opacity: 0;
    pointer-events: none;
  }
  .lit.on {
    animation: lit-in 520ms var(--ease-settle) forwards;
  }
  .glow {
    filter: drop-shadow(0 0 var(--r1) var(--primary)) drop-shadow(0 0 var(--r2) var(--primary));
  }
  .glow.on {
    animation:
      lit-in 520ms var(--ease-settle) forwards,
      breathe 2.8s ease-in-out 520ms infinite;
  }
  .trace {
    overflow: visible;
    fill: none;
    pointer-events: none;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .line {
    stroke: color-mix(in srgb, var(--primary) 70%, white);
    stroke-dasharray: 100;
    stroke-dashoffset: 100;
    animation: draw 900ms var(--ease-out) 120ms forwards;
  }
  .spark {
    stroke: #fff;
    stroke-dasharray: 7 93;
    opacity: 0;
    filter: drop-shadow(0 0 3px var(--primary));
    animation:
      fade-in 300ms ease 900ms forwards,
      run 3.2s linear 900ms infinite;
  }
  .scan {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background: color-mix(in srgb, #000 22%, transparent);
    pointer-events: none;
  }
  .band {
    position: absolute;
    left: 0;
    right: 0;
    height: 38%;
    top: 0;
    background: linear-gradient(
      to bottom,
      transparent,
      color-mix(in srgb, var(--primary) 10%, transparent) 70%,
      color-mix(in srgb, var(--primary) 55%, transparent) 99%,
      color-mix(in srgb, var(--primary) 90%, white) 100%
    );
    animation: sweep 1.7s var(--ease-standard) infinite;
  }
  .ring {
    position: absolute;
    width: 0;
    height: 0;
    pointer-events: none;
  }
  .ring i {
    position: absolute;
    left: -22px;
    top: -22px;
    width: 44px;
    height: 44px;
    border-radius: 50%;
    border: 2px solid var(--primary);
    box-shadow: 0 0 12px var(--primary);
    animation: ping 1.6s var(--ease-out) infinite;
  }
  .ring i + i {
    animation-delay: 0.8s;
  }
  .pt {
    position: absolute;
    width: 22px;
    height: 22px;
    margin: -11px 0 0 -11px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-weight: var(--font-weight-bold);
    font-size: 15px;
    line-height: 1;
    background: var(--primary);
    color: var(--on-primary);
    border: 2px solid #fff;
    box-shadow: 0 1px 6px rgb(0 0 0 / 0.5);
    pointer-events: none;
    animation: pop 260ms var(--ease-pop);
  }
  .pt.neg {
    background: var(--error);
    color: #fff;
  }
  .label {
    position: absolute;
    transform: translate(-50%, -100%);
    padding: 5px 12px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--primary) 92%, black);
    color: var(--on-primary);
    font-weight: var(--font-weight-bold);
    font-size: var(--text-product-spec);
    white-space: nowrap;
    max-width: 70vw;
    overflow: hidden;
    text-overflow: ellipsis;
    box-shadow: 0 0 18px color-mix(in srgb, var(--primary) 60%, transparent);
    pointer-events: none;
    animation: chip-in 420ms var(--ease-pop) 300ms both;
  }
  @keyframes lit-in {
    from {
      opacity: 0;
      transform: scale(0.985);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
  @keyframes breathe {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.55;
    }
  }
  @keyframes draw {
    to {
      stroke-dashoffset: 0;
    }
  }
  @keyframes run {
    from {
      stroke-dashoffset: 100;
    }
    to {
      stroke-dashoffset: 0;
    }
  }
  @keyframes fade-in {
    to {
      opacity: 1;
    }
  }
  @keyframes sweep {
    from {
      transform: translateY(-100%);
    }
    to {
      transform: translateY(265%);
    }
  }
  @keyframes ping {
    from {
      transform: scale(0.4);
      opacity: 1;
    }
    to {
      transform: scale(2.2);
      opacity: 0;
    }
  }
  @keyframes pop {
    from {
      transform: scale(0.3);
    }
  }
  @keyframes chip-in {
    from {
      opacity: 0;
      transform: translate(-50%, -60%) scale(0.85);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .band,
    .ring i,
    .glow.on,
    .spark {
      animation: none;
    }
    .spark {
      opacity: 0;
    }
    .frame.moving {
      transition: none;
    }
  }
</style>
