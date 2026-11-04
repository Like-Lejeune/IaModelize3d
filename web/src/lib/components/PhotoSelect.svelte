<script lang="ts">
  import Icon from './Icon.svelte';
  import Modal from './Modal.svelte';
  import Sticker from './Sticker.svelte';
  import { api, errorText, type DetectResult } from '$lib/api';
  import { t, unitLabel } from '$lib/i18n.svelte';
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
  const sizeText = (d: Record<string, any>) => (d?.size_mm ? `${d.size_mm.map((v: number) => v.toFixed(1)).join(' × ')} ${unitLabel('mm')}` : d?.area_mm2 ? `${Math.round(d.area_mm2)} ${unitLabel('mm2')}` : '');
</script>

<Modal title={t('select_title')} {onClose} wide>
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
      <p class="xs muted how">{t('select_hint')}</p>
      <button class="btn" onclick={detect} disabled={busy}><Icon name="scan" size={15} /> {t('detect')}</button>
      <label class="field">{t('role')}
        <select bind:value={role}>
          {#each ROLES as r (r)}<option value={r}>{t(`role.${r}`)}</option>{/each}
        </select>
      </label>
      <label class="field">{t('name')}<input type="text" bind:value={name} placeholder={t('name_ph')} /></label>
      {#if !points.length && !box}
        <label class="field">{t('text_prompt')}<input type="text" bind:value={text} placeholder={t('text_prompt_ph')} /></label>
      {/if}
      <div class="row">
        <button class="btn primary" onclick={apply} disabled={busy || (!points.length && !box && !text.trim())}>{#if busy}<i class="ti ti-loader-2 spin" aria-hidden="true"></i> {t('finding_outline')}{:else}{t('apply_selection')}{/if}</button>
        <button class="btn" onclick={() => ((points = []), (box = null))}>{t('clear')}</button>
      </div>
      {#if error}<div class="err">{error}</div>{/if}
      {#each mine as s (s.id)}
        <div class="sel card">
          {#if s.mask_url}<Sticker photo={asset.url} mask={s.mask_url} bbox={s.data?.bbox_px ?? null} size={52} />{/if}
          <div class="stack" style="gap:2px;min-width:0">
            <strong>{s.name && s.name !== s.role ? s.name : t(`role.${s.role}`)}</strong>
            <span class="small muted">{s.role === 'target' ? t('will_model') : t(`role.${s.role}`)}</span>
            {#if sizeText(s.data)}<span class="small mono">{sizeText(s.data)}{s.data?.uncertainty_mm ? ` ±${Number(s.data.uncertainty_mm).toFixed(1)}` : ''}</span>{/if}
          </div>
          <button class="btn ghost small icon" aria-label={t('remove')} title={t('remove')} onclick={() => remove(s.id)}><Icon name="x" size={14} /></button>
        </div>
      {/each}
      {#if mine.length}<button class="btn primary block" onclick={onClose}><Icon name="check" size={15} /> {t('done')}</button>{/if}
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
    border-radius: var(--radius-btn);
  }
  .mask {
    position: absolute;
    inset: 0;
    /* striped so the mask still reads on parts that share the accent colour */
    background: repeating-linear-gradient(45deg, var(--primary) 0 6px, var(--on-primary) 6px 10px);
    opacity: 0.6;
    pointer-events: none;
    mask-mode: luminance;
    mask-size: 100% 100%;
    -webkit-mask-size: 100% 100%;
    -webkit-mask-source-type: luminance;
  }
  .mask.role-reference {
    background: var(--info);
  }
  .mask.role-mating {
    background: var(--warn);
  }
  .mask.role-ignore {
    background: var(--outline);
  }
  .pt {
    position: absolute;
    width: 14px;
    height: 14px;
    margin: -7px 0 0 -7px;
    border-radius: 50%;
    background: var(--primary);
    border: 2px solid #fff;
    pointer-events: none;
  }
  .pt.neg {
    background: var(--error);
  }
  .box {
    position: absolute;
    border: 2px solid var(--primary);
    background: color-mix(in srgb, var(--primary) 12%, transparent);
    pointer-events: none;
  }
  .box.live {
    border-style: dashed;
  }
  .sugg {
    position: absolute;
    border: 1.5px dashed var(--info);
    background: color-mix(in srgb, var(--info) 8%, transparent);
    padding: 0;
    line-height: 1.2;
  }
  .sugg span {
    position: absolute;
    left: 0;
    top: 0;
    font-size: var(--text-xs);
    font-weight: var(--font-weight-semibold);
    background: var(--info);
    color: #0d1a2b;
    padding: 2px 6px;
    border-radius: 0 0 var(--radius-tag) 0;
    white-space: nowrap;
  }
  .how {
    margin: 0;
  }
  .sel {
    display: flex;
    gap: var(--space-2);
    align-items: center;
    padding: var(--space-2);
    background: var(--surface);
  }
  .err {
    color: var(--error);
    font-size: var(--text-md);
  }
</style>
