<script lang="ts">
  // The object on an uploaded photo, full screen, as in the snap review: tap the object you mean,
  // add parts or cut them away, or take one of the other objects found on the photo. Every change
  // becomes the photo's target selection, which the agent models from.
  import { untrack } from 'svelte';
  import Icon from './Icon.svelte';
  import SnapHighlight from './SnapHighlight.svelte';
  import { api, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import type { Box } from '$lib/snapframe';
  import type { AssetOut, SnapObject } from '$lib/types';

  type Pt = { x: number; y: number; positive: boolean };
  let {
    store,
    asset,
    sent = false,
    onClose,
  }: {
    store: ProjectStore;
    asset: AssetOut;
    /** The photo already went to the agent: a change is worth a new run. */
    sent?: boolean;
    onClose: () => void;
  } = $props();

  const W = $derived(asset.width ?? 1);
  const H = $derived(asset.height ?? 1);
  const sel = $derived(store.target(asset.id));
  const scanning = $derived(!!store.spotting[asset.id]);
  const bbox = $derived.by<Box | null>(() => {
    const b = sel?.data?.bbox_px;
    return Array.isArray(b) && b.length === 4 ? (b as Box) : null;
  });

  // what the selection started from: the found object's box, refined by taps
  const found = () => {
    const b = store.target(asset.id)?.data?.bbox_px as Box | undefined;
    return { label: store.targetLabel(asset.id) ?? '', bbox: Array.isArray(b) && b.length === 4 ? b : null };
  };
  const initial = found();
  let start = $state(initial);
  // opened while the photo is still being scanned: the object found is the start once it is in
  let awaiting = untrack(() => !!store.spotting[asset.id]) && !initial.bbox;
  let points = $state<Pt[]>([]);
  let box = $state<Box | null>(initial.bbox);
  let label = $state(initial.label);
  let mode = $state<'add' | 'remove'>('add');
  let busy = $state(false);
  let changed = $state(false);
  let error = $state<string | null>(null);
  let leaving = $state(false);
  let sheetH = $state(0);

  const others = $derived.by<SnapObject[]>(() => {
    const found = store.spotOf(asset.id)?.objects ?? [];
    const first = start.bbox && start.label ? [{ label: start.label, bbox: start.bbox }] : [];
    return [...first, ...found].filter((o) => o.label !== label);
  });

  // every change can be taken back
  type Step = { points: Pt[]; box: Box | null; label: string };
  let history = $state<Step[]>([]);
  // taps wait for the scan, so nothing has changed by then; a name typed meanwhile is kept
  $effect(() => {
    if (!awaiting || scanning || busy || history.length) return;
    awaiting = false;
    const f = found();
    if (!f.bbox) return;
    start = f;
    box = f.bbox;
    if (!untrack(() => label.trim())) label = f.label;
  });
  const inside =(b: Box | null | undefined, p: { x: number; y: number }) => !!b && p.x >= b[0] && p.x <= b[2] && p.y >= b[1] && p.y <= b[3];
  const area = (b: Box) => (b[2] - b[0]) * (b[3] - b[1]);

  function change(next: Partial<Step>) {
    history = [...history, { points, box, label }];
    if (next.points) points = next.points;
    if (next.box !== undefined) box = next.box;
    if (next.label !== undefined) label = next.label;
    apply(() => restore(history.length - 1));
  }

  function restore(i: number) {
    const st = history[i];
    if (!st) return;
    history = history.slice(0, i);
    points = st.points;
    box = st.box;
    label = st.label;
  }

  function tap(q: { x: number; y: number }) {
    if (scanning) return;
    const p = { x: Math.round(q.x), y: Math.round(q.y), positive: mode === 'add' || !sel };
    // taps while the outline is being cut refine that same request
    if (busy) return change({ points: [...points, p] });
    // a tap on another object (one of those found, or beside the selection) means "this one"
    const other = p.positive ? others.find((o) => inside(o.bbox, p) && (!bbox || !inside(bbox, p) || area(o.bbox) < 0.8 * area(bbox))) : undefined;
    if (other) change({ points: [p], box: [...other.bbox] as Box, label: other.label });
    else if (p.positive && !inside(bbox, p)) change({ points: [p], box: null, label: '' });
    else change({ points: [...points, p] });
  }

  function pick(o: SnapObject) {
    mode = 'add';
    change({ points: [], box: [...o.bbox] as Box, label: o.label });
  }

  function undo() {
    if (busy || !history.length) return;
    restore(history.length - 1);
    if (points.length || box) apply();
  }

  // one request at a time; changes made meanwhile go out together as soon as it is back
  let again = false;
  async function apply(rollback?: () => void) {
    if (busy) {
      again = true;
      return;
    }
    busy = true;
    error = null;
    try {
      do {
        again = false;
        const s = await api.select(store.id, asset.id, { points: points.length ? points : undefined, box, role: 'target', name: label.trim() || null, replace: true });
        store.putTarget(s);
        changed = true;
      } while (again);
    } catch (e) {
      error = errorText(e);
      rollback?.();
    } finally {
      busy = false;
    }
  }

  async function redo() {
    leaving = true;
    try {
      if (store.jobId) await store.cancel();
      onClose();
      await store.send(t('spot_redo_msg', { label: label.trim() || t('spot_title').toLowerCase() }));
    } finally {
      leaving = false;
    }
  }
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onClose()} />

<div class="focus" role="dialog" aria-modal="true" aria-label={t('spot_title')} style:--sheet="{sheetH + 16}px">
  <div class="stage">
    <SnapHighlight
      src={asset.url}
      width={W}
      height={H}
      fit="contain"
      focus={bbox}
      maskUrl={sel?.mask_url ?? null}
      outline={sel?.data?.outline_px ?? null}
      scanning={scanning || busy}
      {points}
      label={sel ? label.trim() || null : null}
      onTap={tap}
    />
  </div>

  <header class="bar">
    <button class="glass round" onclick={onClose} aria-label={t('close')} title={t('close')}><Icon name="x" size={20} /></button>
    <strong class="ttl">{t('spot_title')}</strong>
    {#if sel}
      <div class="glass seg" role="radiogroup" aria-label={t('snap_edit_hint')}>
        <button role="radio" aria-checked={mode === 'add'} class:on={mode === 'add'} onclick={() => (mode = 'add')}><Icon name="plus" size={16} /> <span>{t('snap_add')}</span></button>
        <button role="radio" aria-checked={mode === 'remove'} class:on={mode === 'remove'} onclick={() => (mode = 'remove')}><Icon name="minus" size={16} /> <span>{t('snap_remove')}</span></button>
      </div>
    {/if}
  </header>

  <section class="panel" aria-live="polite" bind:clientHeight={sheetH}>
    <div class="name-row">
      <input class="name" bind:value={label} aria-label={t('snap_name')} placeholder={t('snap_name')} maxlength="40" />
      {#if busy || scanning}<i class="ti ti-loader-2 spin busy" aria-hidden="true"></i>{/if}
      {#if history.length}
        <button class="btn ghost small icon" onclick={undo} disabled={busy} aria-label={t('spot_undo')} title={t('spot_undo')}><Icon name="undo" size={16} /></button>
      {/if}
    </div>
    {#if error}
      <p class="err small" role="alert">{error}</p>
    {:else}
      <p class="muted xs">{scanning ? t('spot_finding') : sel ? t('spot_hint') : t('snap_file_hint')}</p>
    {/if}
    {#if others.length}
      <div class="group">
        <span class="section-title">{t('snap_other')}</span>
        <div class="scroll">
          {#each others as o (o.label + o.bbox.join())}
            <button class="chip" onclick={() => pick(o)} disabled={busy || scanning}>{o.label}</button>
          {/each}
        </div>
      </div>
    {/if}
    {#if sent && changed && !store.jobId}<p class="muted xs">{t('spot_later')}</p>{/if}
    <div class="acts">
      {#if sent && changed}
        <button class="btn" onclick={onClose}>{t('done')}</button>
        <button class="btn primary grow" onclick={redo} disabled={busy || leaving || !sel}>
          {#if leaving}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="refresh" size={16} />{/if}
          {t('spot_redo')}
        </button>
      {:else}
        <button class="btn primary grow" onclick={onClose} disabled={busy}><Icon name="check" size={16} /> {t('done')}</button>
      {/if}
    </div>
  </section>
</div>

<style>
  .focus {
    position: fixed;
    inset: 0;
    z-index: 200;
    background: #000;
    color: #fff;
    overflow: hidden;
    animation: open 260ms var(--ease-out);
  }
  @keyframes open {
    from {
      opacity: 0;
    }
  }
  .stage {
    position: absolute;
    inset: 0 0 var(--sheet) 0;
  }
  /* glass chrome over the photo, the same in both themes like the snap screen */
  .glass {
    background: rgb(20 20 18 / 0.48);
    backdrop-filter: blur(12px) saturate(1.4);
    -webkit-backdrop-filter: blur(12px) saturate(1.4);
    border: 1px solid rgb(255 255 255 / 0.16);
    color: #fff;
  }
  .round {
    width: 42px;
    height: 42px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    flex: none;
    cursor: pointer;
    padding: 0;
  }
  .round:hover {
    background: rgb(40 40 36 / 0.6);
  }
  .bar {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: calc(env(safe-area-inset-top) + var(--space-3)) var(--space-4) var(--space-6);
    background: linear-gradient(to bottom, rgb(0 0 0 / 0.55), transparent);
    pointer-events: none;
  }
  .bar > * {
    pointer-events: auto;
  }
  .ttl {
    flex: 1;
    min-width: 0;
    font-size: var(--text-product-lead);
    font-weight: var(--font-weight-bold);
    text-shadow: 0 1px 6px rgb(0 0 0 / 0.5);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .seg {
    display: flex;
    padding: 3px;
    border-radius: 999px;
    gap: 2px;
  }
  .seg button {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: 0;
    background: transparent;
    color: rgb(255 255 255 / 0.85);
    font-weight: var(--font-weight-semibold);
    font-size: var(--text-card-from);
    padding: 7px 12px;
    border-radius: 999px;
    min-height: 36px;
    transition: background-color var(--dur-fast) var(--ease-standard);
  }
  .seg button.on {
    background: var(--primary);
    color: var(--on-primary);
  }
  .seg button:last-child.on {
    background: var(--error);
    color: #fff;
  }
  /* bottom sheet: themed surface */
  .panel {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    margin: 0 auto;
    max-width: 560px;
    background: var(--surface-container);
    color: var(--on-surface);
    border: var(--border-width) solid var(--outline-variant);
    border-bottom: 0;
    border-radius: 18px 18px 0 0;
    padding: var(--space-4) var(--space-4) calc(env(safe-area-inset-bottom) + var(--space-4));
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    box-shadow: 0 -10px 40px rgb(0 0 0 / 0.45);
    animation: rise 380ms var(--ease-settle);
  }
  @keyframes rise {
    from {
      transform: translateY(40%);
      opacity: 0;
    }
  }
  .panel p {
    margin: 0;
  }
  .name-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .name {
    flex: 1;
    min-width: 0;
    font-size: var(--text-product-section-title);
    font-weight: var(--font-weight-bold);
    padding: 8px 10px;
    border-radius: var(--radius-field);
    border: var(--border-width) solid transparent;
    background: var(--surface-high);
    color: var(--on-surface);
  }
  .name:focus {
    border-color: var(--primary);
    outline: none;
  }
  .busy {
    color: var(--primary);
    font-size: 20px;
  }
  .err {
    color: var(--error);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .scroll {
    display: flex;
    gap: var(--space-2);
    overflow-x: auto;
    scrollbar-width: none;
    margin: 0 calc(-1 * var(--space-4));
    padding: 0 var(--space-4);
  }
  .scroll .chip {
    flex: none;
    white-space: nowrap;
  }
  .acts {
    display: flex;
    gap: var(--space-2);
  }
  .acts .grow {
    flex: 1;
  }
  @media (max-width: 400px) {
    .seg span {
      display: none;
    }
  }
  @media (min-width: 720px) {
    .panel {
      bottom: var(--space-4);
      border-radius: 18px;
      border-bottom: var(--border-width) solid var(--outline-variant);
    }
  }
</style>
