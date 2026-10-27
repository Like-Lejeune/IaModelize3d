<script lang="ts">
  import Modal from './Modal.svelte';
  import Sticker from './Sticker.svelte';
  import { api, errorText, type DetectResult } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { AssetOut, SelectionOut } from '$lib/types';

  let {
    projectId,
    asset,
    selections,
    onClose,
  }: { projectId: string; asset: AssetOut; selections: SelectionOut[]; onClose: () => void } = $props();

  const ROLES = ['target', 'reference', 'mating', 'caliper', 'ignore'];
  let img = $state<HTMLImageElement>();
  let points = $state<{ x: number; y: number; positive: boolean }[]>([]);
  let box = $state<[number, number, number, number] | null>(null);
  const initialRole = () => (asset.kind === 'caliper' ? 'caliper' : 'target');
  let role = $state(initialRole());
  let name = $state('');
  let text = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  let detected = $state<DetectResult | null>(null);
  let result = $state<SelectionOut | null>(null);
  let dragStart = $state<{ x: number; y: number; t: number; alt: boolean } | null>(null);
  let dragNow = $state<{ x: number; y: number } | null>(null);
  let pressTimer: ReturnType<typeof setTimeout> | null = null;
  let longPressed = false;

  const W = $derived(asset.width ?? img?.naturalWidth ?? 1);
  const H = $derived(asset.height ?? img?.naturalHeight ?? 1);
  const mine = $derived(selections.filter((s) => s.asset_id === asset.id));

  function toImage(ev: PointerEvent) {
    const r = img!.getBoundingClientRect();
    const sx = (img!.naturalWidth || W) / r.width;
    const sy = (img!.naturalHeight || H) / r.height;
    return { x: Math.round((ev.clientX - r.left) * sx), y: Math.round((ev.clientY - r.top) * sy) };
  }

  function down(ev: PointerEvent) {
    const p = toImage(ev);
    dragStart = { ...p, t: Date.now(), alt: ev.altKey };
    longPressed = false;
    pressTimer = setTimeout(() => {
      longPressed = true;
    }, 550);
    (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
  }
  function move(ev: PointerEvent) {
    if (!dragStart) return;
    const p = toImage(ev);
    if (Math.hypot(p.x - dragStart.x, p.y - dragStart.y) > 12) {
      if (pressTimer) clearTimeout(pressTimer);
      dragNow = p;
    }
  }
  function up(ev: PointerEvent) {
    if (pressTimer) clearTimeout(pressTimer);
    if (!dragStart) return;
    const p = toImage(ev);
    if (dragNow) {
      box = [Math.min(dragStart.x, p.x), Math.min(dragStart.y, p.y), Math.max(dragStart.x, p.x), Math.max(dragStart.y, p.y)];
    } else {
      points = [...points, { x: dragStart.x, y: dragStart.y, positive: !(dragStart.alt || longPressed) }];
    }
    dragStart = null;
    dragNow = null;
  }

  async function detect() {
    busy = true;
    error = null;
    try {
      detected = await api.detect(projectId, asset.id);
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = false;
    }
  }

  function useSuggestion(b: number[], r?: string, label?: string) {
    box = [b[0], b[1], b[2], b[3]];
    points = [];
    if (r) role = r;
    if (label && !name) name = label;
  }

  async function apply() {
    busy = true;
    error = null;
    try {
      result = await api.select(projectId, asset.id, {
        points: points.length ? points : undefined,
        box,
        text: !points.length && !box && text.trim() ? text.trim() : null,
        role,
        name: name.trim() || null,
      });
      points = [];
      box = null;
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = false;
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteSelection(projectId, id);
    } catch (e) {
      error = errorText(e);
    }
  }

  const pct = (v: number, of: number) => `${(v / of) * 100}%`;
  const sizeText = (d: Record<string, any>) => (d?.size_mm ? `${d.size_mm.map((v: number) => v.toFixed(1)).join(' × ')} mm` : d?.area_mm2 ? `${Math.round(d.area_mm2)} mm²` : '');
</script>

<Modal title={t('select_hint')} {onClose} wide>
  <div class="wrap">
    <div class="pic">
      <div class="frame" role="application" aria-label={t('select_hint')} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={() => (dragStart = null)}>
        <img bind:this={img} src={asset.url} alt="" draggable="false" />
        {#each mine as s (s.id)}
          {#if s.mask_url}<span class="mask role-{s.role}" style:mask-image="url({s.mask_url})" style:-webkit-mask-image="url({s.mask_url})"></span>{/if}
        {/each}
        {#each points as p, i (i)}
          <span class="pt" class:neg={!p.positive} style:left={pct(p.x, img?.naturalWidth || W)} style:top={pct(p.y, img?.naturalHeight || H)}></span>
        {/each}
        {#if box}
          <span class="box" style:left={pct(box[0], img?.naturalWidth || W)} style:top={pct(box[1], img?.naturalHeight || H)} style:width={pct(box[2] - box[0], img?.naturalWidth || W)} style:height={pct(box[3] - box[1], img?.naturalHeight || H)}></span>
        {/if}
        {#if dragStart && dragNow}
          <span class="box live" style:left={pct(Math.min(dragStart.x, dragNow.x), img?.naturalWidth || W)} style:top={pct(Math.min(dragStart.y, dragNow.y), img?.naturalHeight || H)} style:width={pct(Math.abs(dragNow.x - dragStart.x), img?.naturalWidth || W)} style:height={pct(Math.abs(dragNow.y - dragStart.y), img?.naturalHeight || H)}></span>
        {/if}
        {#each [...(detected?.references ?? []).map((r) => ({ b: r.bbox, label: r.name, role: 'reference' })), ...(detected?.objects ?? []).map((o) => ({ b: o.bbox, label: o.label, role: o.suggested_role ?? 'target' }))] as s, i (i)}
          <button
            class="sugg"
            style:left={pct(s.b[0], img?.naturalWidth || W)}
            style:top={pct(s.b[1], img?.naturalHeight || H)}
            style:width={pct(s.b[2] - s.b[0], img?.naturalWidth || W)}
            style:height={pct(s.b[3] - s.b[1], img?.naturalHeight || H)}
            onpointerdown={(e) => e.stopPropagation()}
            onclick={() => useSuggestion(s.b, s.role, s.label)}
          ><span>{s.label} · {t(`role.${s.role}`)}</span></button>
        {/each}
      </div>
    </div>
    <div class="side stack">
      <button class="btn" onclick={detect} disabled={busy}>✨ {t('detect')}</button>
      <label class="stack lab">{t('role')}
        <select bind:value={role}>
          {#each ROLES as r (r)}<option value={r}>{t(`role.${r}`)}</option>{/each}
        </select>
      </label>
      <label class="stack lab">{t('name')}<input type="text" bind:value={name} placeholder="part, shelf, A4…" /></label>
      {#if !points.length && !box}
        <label class="stack lab">Text prompt<input type="text" bind:value={text} placeholder="the plastic clip" /></label>
      {/if}
      <div class="row">
        <button class="btn primary" onclick={apply} disabled={busy || (!points.length && !box && !text.trim())}>{busy ? '…' : t('apply_selection')}</button>
        <button class="btn" onclick={() => ((points = []), (box = null))}>{t('clear')}</button>
      </div>
      {#if error}<div class="err">{error}</div>{/if}
      {#each mine as s (s.id)}
        <div class="sel card">
          {#if s.mask_url}<Sticker photo={asset.url} mask={s.mask_url} bbox={s.data?.bbox_px ?? null} size={52} />{/if}
          <div class="stack" style="gap:2px;min-width:0">
            <strong>{s.name}</strong>
            <span class="small muted">{t(`role.${s.role}`)}{s.role === 'target' ? ` — ${t('will_model')}` : ''}</span>
            {#if sizeText(s.data)}<span class="small mono">{sizeText(s.data)}{s.data?.uncertainty_mm ? ` ±${Number(s.data.uncertainty_mm).toFixed(1)}` : ''}</span>{/if}
          </div>
          <button class="btn ghost small" aria-label="remove" onclick={() => remove(s.id)}>✕</button>
        </div>
      {/each}
    </div>
  </div>
</Modal>

<style>
  .wrap {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 260px;
    gap: 12px;
  }
  @media (max-width: 760px) {
    .wrap {
      grid-template-columns: 1fr;
    }
  }
  .frame {
    position: relative;
    touch-action: none;
    user-select: none;
    cursor: crosshair;
    line-height: 0;
  }
  .frame img {
    width: 100%;
    height: auto;
    display: block;
    border-radius: 8px;
  }
  .mask {
    position: absolute;
    inset: 0;
    background: var(--accent);
    opacity: 0.5;
    pointer-events: none;
    mask-mode: luminance;
    mask-size: 100% 100%;
    -webkit-mask-size: 100% 100%;
    -webkit-mask-source-type: luminance;
  }
  .mask.role-reference {
    background: #3d6fb4;
  }
  .mask.role-mating {
    background: #2f8f5b;
  }
  .mask.role-ignore {
    background: #777;
  }
  .pt {
    position: absolute;
    width: 14px;
    height: 14px;
    margin: -7px 0 0 -7px;
    border-radius: 50%;
    background: #2f8f5b;
    border: 2px solid #fff;
    pointer-events: none;
  }
  .pt.neg {
    background: #c2412d;
  }
  .box {
    position: absolute;
    border: 2px solid var(--accent);
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    pointer-events: none;
  }
  .box.live {
    border-style: dashed;
  }
  .sugg {
    position: absolute;
    border: 1.5px dashed #3d6fb4;
    background: rgb(61 111 180 / 0.08);
    padding: 0;
    line-height: 1.2;
  }
  .sugg span {
    position: absolute;
    left: 0;
    top: 0;
    font-size: 11px;
    background: #3d6fb4;
    color: #fff;
    padding: 1px 4px;
    white-space: nowrap;
  }
  .lab {
    font-size: 13px;
    gap: 3px;
  }
  .sel {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 6px;
  }
  .small {
    font-size: 12px;
  }
  .err {
    color: var(--err);
    font-size: 13px;
  }
</style>
