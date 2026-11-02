<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  import { api, errorText } from '$lib/api';
  import { t, fmtMinutes, i18n, unitLabel } from '$lib/i18n.svelte';
  import { paramLabel } from '$lib/paramtext';
  import type { ProjectStore } from '$lib/project.svelte';
  import type { Printer } from '$lib/types';

  let { store }: { store: ProjectStore } = $props();

  const GOALS = ['strong', 'fast', 'pretty', 'quiet', 'cheap'];
  const MATERIALS = ['PLA', 'PETG', 'ABS', 'ASA', 'TPU'];
  let printers = $state<Printer[]>([]);
  let printer = $state('');
  let material = $state('PLA');
  let goals = $state<string[]>([]);
  let probeParam = $state('');
  let busy = $state<string | null>(null);
  let error = $state<string | null>(null);
  let fingerprint = $state<Record<string, any> | null>(null);

  // Which printer to slice for: the project's own (brief.printer, or the one its last slice used), then the one the
  // person picked here before, then the farm's (the server marks it default: the Axo farm prints on a Bambu Lab A1).
  // Only a pick from the list is remembered, so an old default never sticks.
  onMount(async () => {
    try {
      printers = await api.printers();
      let picked = '';
      try {
        picked = localStorage.getItem('fw_printer_pick') ?? '';
        material = localStorage.getItem('fw_material') ?? 'PLA';
      } catch {
        /* storage unavailable */
      }
      const known = (k: string | null | undefined) => (k ? printers.find((p) => p.id === k || p.name === k) : undefined);
      const p = known(store.detail?.printer) ?? known(store.slice?.printer?.id) ?? known(picked) ?? printers.find((x) => x.default) ?? printers[0];
      printer = p?.id ?? p?.name ?? '';
    } catch {
      printers = [];
    }
  });

  function pickPrinter() {
    try {
      localStorage.setItem('fw_printer_pick', printer);
    } catch {
      /* ignore */
    }
  }

  const popular = $derived(printers.filter((p) => (p as any).popular));
  const byVendor = $derived.by(() => {
    const m = new Map<string, Printer[]>();
    for (const p of printers) {
      if ((p as any).popular) continue;
      const v = p.vendor ?? t('print_other');
      if (!m.has(v)) m.set(v, []);
      m.get(v)!.push(p);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  });
  const numericParams = $derived(Object.entries(store.build?.paramSpecs ?? {}).filter(([, s]) => typeof s.value === 'number' && !s.hidden && s.kind !== 'seed'));
  const slicing = $derived(store.running && store.jobKind === 'slice');

  async function slice() {
    try {
      localStorage.setItem('fw_material', material);
    } catch {
      /* ignore */
    }
    await store.startSide(() => api.slice(store.id, { printer: printer || undefined, material, goals, params: $state.snapshot(store.values) }));
  }

  async function probe() {
    if (!probeParam) return;
    const s = store.build?.paramSpecs?.[probeParam];
    await store.startSide(() => api.probe(store.id, { dimension: probeParam, value: store.values[probeParam], unit: s?.unit ?? 'mm', label: s?.label }));
  }

  function chooseProbe(v: { label: string; value: any }) {
    store.send(t('probe_fit_msg', { dim: store.probe?.dimension ?? '', label: v.label, value: v.value }));
  }

  async function calibrate(files: FileList | null) {
    const f = files?.[0];
    if (!f || !printer) return;
    busy = 'calib';
    error = null;
    try {
      const a = await api.upload(store.id, f, 'print');
      fingerprint = await api.fingerprint(printer, a.id);
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = null;
    }
  }

  async function comparePrint(files: FileList | null) {
    const f = files?.[0];
    if (!f) return;
    busy = 'compare';
    error = null;
    try {
      const a = await api.upload(store.id, f, 'print');
      await store.send(t('compare_print_msg'), [a.id]);
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = null;
    }
  }

  // slicer keys in words people use; the raw key stays in the tooltip
  const SETTING: Record<string, [string, string]> = {
    wall_loops: ['Walls', 'Стенки'],
    sparse_infill_density: ['Infill', 'Заполнение'],
    sparse_infill_pattern: ['Infill pattern', 'Узор заполнения'],
    sparse_infill_speed: ['Infill speed', 'Скорость заполнения'],
    top_shell_layers: ['Top layers', 'Верхние слои'],
    bottom_shell_layers: ['Bottom layers', 'Нижние слои'],
    layer_height: ['Layer height', 'Высота слоя'],
    outer_wall_speed: ['Outer wall speed', 'Скорость внешней стенки'],
    inner_wall_speed: ['Inner wall speed', 'Скорость внутренних стенок'],
    outer_wall_acceleration: ['Outer wall acceleration', 'Ускорение внешней стенки'],
    inner_wall_acceleration: ['Inner wall acceleration', 'Ускорение внутренних стенок'],
    outer_wall_line_width: ['Outer wall line width', 'Ширина линии внешней стенки'],
    initial_layer_speed: ['First layer speed', 'Скорость первого слоя'],
    brim_type: ['Brim', 'Кайма'],
    brim_width: ['Brim width', 'Ширина каймы'],
    brim_ears: ['Brim ears', 'Ушки каймы'],
    enable_support: ['Supports', 'Поддержки'],
    support_used: ['Supports', 'Поддержки'],
    support_type: ['Support type', 'Тип поддержек'],
    support_threshold_angle: ['Support angle', 'Угол поддержек'],
    seam_position: ['Seam', 'Шов'],
    ironing_type: ['Ironing', 'Разглаживание'],
    elefant_foot_compensation: ['Elephant-foot compensation', 'Компенсация «слоновьей ноги»'],
    detect_thin_wall: ['Thin walls', 'Тонкие стенки'],
    wall_generator: ['Wall generator', 'Генератор стенок'],
    only_one_wall_top: ['Single top wall', 'Одна стенка сверху'],
    fan_max_speed: ['Max fan', 'Макс. обдув'],
  };
  const settingName = (k: string) => SETTING[k]?.[i18n.lang === 'ru' ? 1 : 0] ?? k.replaceAll('_', ' ');
  // evidence tags like "goal:strong" read as "Priorities: Strong"
  const evPart = (x: any) => (typeof x === 'string' && x.startsWith('goal:') ? `${t('goals')}: ${t(`goal.${x.slice(5)}`)}` : typeof x === 'string' ? x : JSON.stringify(x));
  const ev = (e: any) => (Array.isArray(e) ? e.map(evPart).join(', ') : e ? evPart(e) : '');
</script>

<div class="print">
  <section class="stack">
    <p class="muted small lead">{t('slice_hint')}</p>
    <label class="field">{t('printer')}
      <select bind:value={printer} onchange={pickPrinter}>
        {#if !printers.length}<option value="">{t('generic_nozzle')}</option>{/if}
        {#if popular.length}
          <optgroup label={t('popular')}>{#each popular as p (p.id ?? p.name)}<option value={p.id ?? p.name}>{p.name}</option>{/each}</optgroup>
        {/if}
        {#each byVendor as [vendor, list] (vendor)}
          <optgroup label={vendor}>{#each list as p (p.id ?? p.name)}<option value={p.id ?? p.name}>{p.name}</option>{/each}</optgroup>
        {/each}
      </select>
    </label>
    <div class="field">{t('material')}
      <div class="seg mat" role="radiogroup" aria-label={t('material')}>
        {#each MATERIALS as m (m)}<button role="radio" aria-checked={material === m} class:on={material === m} onclick={() => (material = m)}>{m}</button>{/each}
      </div>
    </div>
    <div class="field">{t('goals')}
      <div class="row goals" role="group">
        {#each GOALS as g (g)}
          <button class="chip goal" class:on={goals.includes(g)} aria-pressed={goals.includes(g)} onclick={() => (goals = goals.includes(g) ? goals.filter((x) => x !== g) : [...goals, g])}>{t(`goal.${g}`)}</button>
        {/each}
      </div>
    </div>
    <button class="btn primary large" onclick={slice} disabled={!store.source || store.running}>
      {#if slicing}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="printer" size={17} />{/if} {t('prepare_print')}
    </button>
  </section>

  {#if store.slice}
    {@const st = store.slice.stats ?? {}}
    <section class="res card">
      <div class="row hdr"><Icon name="check-circle" size={16} /> <strong>{t('sliced')}</strong></div>
      <dl class="big">
        <div><dt>{t('time')}</dt><dd class="mono">{fmtMinutes(st.minutes)}</dd></div>
        <div><dt>{t('weight')}</dt><dd class="mono">{Math.round(st.grams ?? 0)} {t('grams')}</dd></div>
        {#if st.filament_m}<div><dt>{t('filament')}</dt><dd class="mono">{(+st.filament_m).toFixed(1)} {unitLabel('m')}</dd></div>{/if}
        {#if st.layers}<div><dt>{t('layers')}</dt><dd class="mono">{st.layers}</dd></div>{/if}
        {#if st.supports}<div><dt>{settingName('support_used')}</dt><dd>{t('yes')}</dd></div>{/if}
      </dl>
      {#if st.warnings?.length}<ul class="warnings">{#each st.warnings as w (w)}<li class="small">{w}</li>{/each}</ul>{/if}
      <div class="section-title">{t('profile_diff')}</div>
      {#if !store.slice.diff?.length}
        <p class="muted small">{t('no_changes')}</p>
      {:else}
        <ul class="diff">
          {#each store.slice.diff as d (d.key + (d.part ?? ''))}
            <li>
              <div class="row"><span class="key" title={d.key}>{settingName(d.key)}</span><span class="mono xs">{d.from} → <strong>{d.to}</strong></span></div>
              <div class="small reason">{d.reason}</div>
              {#if d.evidence}<div class="xs muted">{ev(d.evidence)}</div>{/if}
            </li>
          {/each}
        </ul>
      {/if}
      <div class="row">
        {#if store.slice.files?.project_3mf}<a class="btn primary small" href={store.slice.files.project_3mf} download><Icon name="download" size={14} /> {t('project_3mf')}</a>{/if}
        {#if store.slice.files?.gcode}<a class="btn small" href={store.slice.files.gcode} download>{t('gcode')}</a>{/if}
      </div>
    </section>
  {/if}

  <details class="tool">
    <summary><Icon name="flask" size={15} /> {t('probe')}<span class="chev"><Icon name="chevron-down" size={16} /></span></summary>
    <p class="muted small">{t('probe_hint')}</p>
    <div class="row">
      <select bind:value={probeParam} aria-label={t('probe_param')} style="flex:1;min-width:0">
        <option value="">{t('probe_param')}…</option>
        {#each numericParams as [n, s] (n)}<option value={n}>{paramLabel(s.label ?? n, i18n.lang)} ({store.values[n]} {s.unit ? unitLabel(s.unit) : ''})</option>{/each}
      </select>
      <button class="btn small" onclick={probe} disabled={!probeParam || store.running}>{t('make_probe')}</button>
    </div>
    {#if store.probe}
      <div class="probe">
        {#if store.probe.render}<img src={store.probe.render} alt="" />{/if}
        <div class="xs muted">{t('fits_best')}:</div>
        <div class="row">{#each store.probe.variants ?? [] as v (v.label)}<button class="btn small" onclick={() => chooseProbe(v)}>{v.label} · {v.value}</button>{/each}</div>
        <div class="row">{#each Object.entries(store.probe.files ?? {}) as [k, url] (k)}<a class="btn small ghost" href={url as string} download><Icon name="download" size={13} /> {k}</a>{/each}</div>
      </div>
    {/if}
  </details>

  <details class="tool">
    <summary><Icon name="target" size={15} /> {t('calib')}<span class="chev"><Icon name="chevron-down" size={16} /></span></summary>
    <p class="muted small">{t('calib_hint')}</p>
    <div class="row">
      <a class="btn small" href="/api/printers/coupon.3mf" download><Icon name="download" size={13} /> {t('coupon')}</a>
      <!-- the photo goes into the project: its owner's only (a visitor still gets the coupon) -->
      {#if !store.readonly}
        <label class="btn small" class:disabled={!printer || busy === 'calib'} title={printer ? '' : t('pick_printer_first')}>
          {#if busy === 'calib'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="camera" size={13} />{/if} {t('calib_photo')}
          <input class="sr-only" type="file" accept="image/*" capture="environment" disabled={!printer} onchange={(e) => calibrate((e.currentTarget as HTMLInputElement).files)} />
        </label>
      {/if}
    </div>
    {#if fingerprint}
      <dl class="fp mono xs">{#each Object.entries(fingerprint).filter(([, v]) => typeof v === 'number') as [k, v] (k)}<div><dt>{k}</dt><dd>{(v as number).toFixed(2)}</dd></div>{/each}</dl>
    {/if}
  </details>

  {#if !store.readonly}
    <details class="tool">
      <summary><Icon name="scan" size={15} /> {t('compare')}<span class="chev"><Icon name="chevron-down" size={16} /></span></summary>
      <p class="muted small">{t('compare_hint')}</p>
      <label class="btn small" class:disabled={busy === 'compare' || store.running}>
        {#if busy === 'compare'}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="camera" size={13} />{/if} {t('compare_photo')}
        <input class="sr-only" type="file" accept="image/*" capture="environment" onchange={(e) => comparePrint((e.currentTarget as HTMLInputElement).files)} />
      </label>
    </details>
  {/if}

  {#if error}<p class="err small" role="alert">{error}</p>{/if}
</div>

<style>
  .print {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .lead {
    margin: 0;
  }
  .mat button {
    padding-inline: 8px;
  }
  .res {
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .hdr {
    color: var(--primary);
  }
  .big {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
    margin: 0;
  }
  .big div {
    background: var(--surface);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-field);
    padding: 8px 12px;
  }
  dt {
    font-size: var(--text-card-meta);
    font-weight: var(--font-weight-semibold);
    color: var(--outline);
  }
  dd {
    margin: 0;
    font-size: var(--text-product-lead);
    font-weight: var(--font-weight-semibold);
    color: var(--on-surface);
  }
  .warnings {
    margin: 0;
    padding-left: 18px;
    color: var(--warn-text);
  }
  .diff {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .diff li {
    box-shadow: inset 3px 0 0 0 var(--primary);
    padding-left: 12px;
  }
  .key {
    font-size: 12px;
    font-weight: var(--font-weight-semibold);
  }
  .reason {
    color: var(--on-surface-var);
  }
  .tool {
    background: var(--surface);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-card);
    padding: 12px 14px;
  }
  .tool summary {
    cursor: pointer;
    font-size: var(--text-product-spec);
    color: var(--on-surface);
    font-weight: var(--font-weight-semibold);
    display: flex;
    gap: 8px;
    align-items: center;
    list-style: none;
  }
  .tool summary::-webkit-details-marker {
    display: none;
  }
  .chev {
    margin-left: auto;
    display: grid;
    color: var(--outline);
    transition: transform var(--dur-fast) var(--ease-standard);
  }
  .tool[open] .chev {
    transform: rotate(180deg);
  }
  .tool[open] summary {
    margin-bottom: 6px;
  }
  .tool p {
    margin: 0 0 8px;
  }
  .probe {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 8px;
  }
  .probe img {
    max-width: 200px;
    border-radius: var(--radius-btn);
    border: var(--border-width) solid var(--outline-variant);
  }
  .fp {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 4px;
    margin: 8px 0 0;
  }
  .fp dd {
    font-size: 12px;
  }
  .err {
    color: var(--error);
  }
</style>
