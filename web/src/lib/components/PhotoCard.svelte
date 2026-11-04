<script lang="ts">
  // A photo in the conversation with its object lifted out: scanned while the object is being
  // found, then the cut-out glows with its name. A tap opens the editor to fix the outline.
  // A board read from the photo (scan_board) shows its labelled boxes over it, framed on the board.
  import Icon from './Icon.svelte';
  import SnapHighlight from './SnapHighlight.svelte';
  import { t } from '$lib/i18n.svelte';
  import type { Box } from '$lib/snapframe';
  import type { ScanBox, SelectionOut } from '$lib/types';

  let {
    src,
    width = null,
    height = null,
    sel = null,
    scan = null,
    label = null,
    scanning = false,
    compact = false,
    onOpen,
  }: {
    src: string;
    width?: number | null;
    height?: number | null;
    sel?: SelectionOut | null;
    /** The board scan of this photo (selection data.kind 'board_scan'). */
    scan?: SelectionOut | null;
    label?: string | null;
    scanning?: boolean;
    compact?: boolean;
    onOpen?: () => void;
  } = $props();

  // a local preview has no stored size yet
  let natural = $state<{ w: number; h: number } | null>(null);
  $effect(() => {
    if (width && height) return;
    const im = new Image();
    im.onload = () => (natural = { w: im.naturalWidth, h: im.naturalHeight });
    im.src = src;
  });
  const W = $derived(width || natural?.w || 1);
  const H = $derived(height || natural?.h || 1);
  // a board scan keeps a wide photo whole (every box on it), as a strip
  const ratio = $derived(Math.min(Math.max(W / H, 0.75), scan ? 2.4 : 1.4));
  const boxOf = (b: unknown): Box | null => (Array.isArray(b) && b.length === 4 ? (b as Box) : null);
  const bbox = $derived(boxOf(sel?.data?.bbox_px));
  // the scan's boxes are in photo pixels, the board's own box frames them
  const scanBox = $derived(boxOf(scan?.data?.bbox_px));
  const boxes = $derived((Array.isArray(scan?.data?.boxes) ? scan!.data.boxes : []) as ScanBox[]);
  // closer in on a small object; a large one stays framed by the whole card
  const focus = $derived(scanBox ?? (bbox && (bbox[2] - bbox[0]) / W < 0.6 && (bbox[3] - bbox[1]) / H < 0.6 ? bbox : null));
</script>

<div class="pc" class:compact style:aspect-ratio={ratio}>
  {#if natural || (width && height)}
    <SnapHighlight
      {src}
      width={W}
      height={H}
      fit="cover"
      {focus}
      maskUrl={sel?.mask_url ?? null}
      outline={sel?.data?.outline_px ?? null}
      {scanning}
      label={compact ? null : label}
      anchor={bbox ?? scanBox}
      {boxes}
      {compact}
      onTap={onOpen && !scanning ? () => onOpen() : undefined}
    />
  {/if}
  {#if scanning}
    <span class="tag work"><i class="ti ti-loader-2 spin" aria-hidden="true"></i>{#if !compact}{t('spot_finding')}{/if}</span>
  {:else if onOpen}
    <button class="tag fix" onclick={onOpen} title={t('spot_fix_hint')} aria-label={t('spot_fix_hint')}>
      <Icon name={sel ? 'pencil' : 'target'} size={12} />{#if !compact}{sel ? t('spot_fix') : t('spot_none')}{/if}
    </button>
  {/if}
</div>

<style>
  .pc {
    position: relative;
    width: 300px;
    max-width: 100%;
    border-radius: var(--radius-card);
    overflow: hidden;
    background: #000;
    border: var(--border-width) solid var(--outline-variant);
  }
  .pc.compact {
    width: 136px;
    border-radius: var(--radius-btn);
  }
  .tag {
    position: absolute;
    right: 8px;
    bottom: 8px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    border-radius: var(--radius-full);
    font-size: var(--text-sm);
    font-weight: var(--font-weight-semibold);
    color: #fff;
    background: rgb(20 20 18 / 0.55);
    backdrop-filter: blur(10px) saturate(1.4);
    -webkit-backdrop-filter: blur(10px) saturate(1.4);
    border: 1px solid rgb(255 255 255 / 0.18);
  }
  .compact .tag {
    right: 5px;
    bottom: 5px;
    padding: 4px 6px;
  }
  .work {
    color: var(--primary);
    pointer-events: none;
  }
  .fix {
    cursor: pointer;
    opacity: 0.9;
    transition:
      opacity var(--dur-fast) var(--ease-standard),
      background-color var(--dur-fast) var(--ease-standard);
  }
  .fix:hover {
    opacity: 1;
    background: rgb(40 40 36 / 0.7);
  }
</style>
