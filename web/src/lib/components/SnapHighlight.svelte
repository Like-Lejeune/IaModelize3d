<script lang="ts">
  // A photo with the selected object lifted out of it: the rest dims, the object stays bright
  // with a soft glow, and a light runs along its outline. Also the scanning state while the
  // object is being found, and the taps that refine the selection.
  import { cutout, place, toImage, toScreen, type Box, type Fit } from '$lib/snapframe';

  let {
    src,
    width,
    height,
    maskUrl = null,
    outline = null,
    fit = 'cover',
    focus = null,
    scanning = false,
    scanAt = null,
    points = [],
    label = null,
    compact = false,
    onTap,
  }: {
    src: string;
    width: number;
    height: number;
    maskUrl?: string | null;
    outline?: number[][] | null;
    fit?: Fit;
    focus?: Box | null;
    scanning?: boolean;
    scanAt?: { x: number; y: number } | null;
    points?: { x: number; y: number; positive: boolean }[];
    label?: string | null;
    compact?: boolean;
    onTap?: (p: { x: number; y: number }) => void;
  } = $props();

  let cw = $state(0);
  let ch = $state(0);
  let host = $state<HTMLDivElement>();
  let lit = $state<HTMLCanvasElement>();
  let glow = $state<HTMLCanvasElement>();
  let cut = $state<HTMLCanvasElement | null>(null);
  let moving = $state(false);

  const p = $derived(place(cw, ch, width, height, fit, focus));
  const path = $derived(outline && outline.length > 2 ? `M${outline.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join('L')}Z` : '');
  const ring = $derived(scanAt ? toScreen(p, scanAt.x, scanAt.y) : null);
  const chip = $derived.by(() => {
    if (!label || !focus || !cut) return null;
    const a = toScreen(p, (focus[0] + focus[2]) / 2, focus[1]);
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
    <img class="photo" class:dim={!!cut} {src} alt="" draggable="false" />
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
