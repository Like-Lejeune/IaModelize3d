<script lang="ts">
  import { onMount } from 'svelte';
  import { api, download, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import type { Printer } from '$lib/types';

  let { store, readonly = false }: { store: ProjectStore; readonly?: boolean } = $props();

  const GOALS = ['fast', 'strong', 'pretty', 'quiet', 'cheap'];
  const MATERIALS = ['PLA', 'PETG', 'ABS', 'ASA', 'TPU'];
  let printers = $state<Printer[]>([]);
  let printer = $state('');
  let material = $state('PLA');
  let goals = $state<string[]>([]);
  let probeParam = $state('');
  let qty = $state(1);
  let color = $state('');
  let comment = $state('');
  let order = $state<Record<string, any> | null>(null);
  let busy = $state<string | null>(null);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      printers = await api.printers();
      try {
        printer = localStorage.getItem('fw_printer') ?? '';
      } catch {
        /* ignore */
      }
      if (!printers.some((p) => p.id === printer || p.name === printer)) printer = printers[0]?.id ?? printers[0]?.name ?? '';
    } catch {
      printers = [];
    }
  });

  const popular = $derived(printers.filter((p) => (p as any).popular));
  const byVendor = $derived.by(() => {
    const m = new Map<string, Printer[]>();
    for (const p of printers) {
      if ((p as any).popular) continue;
      const v = p.vendor ?? 'Other';
      if (!m.has(v)) m.set(v, []);
      m.get(v)!.push(p);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  });

  const numericParams = $derived(
    Object.entries(store.build?.paramSpecs ?? {}).filter(([, s]) => typeof s.value === 'number' && !s.hidden && s.kind !== 'seed'),
  );

  async function dl(format: 'stl' | '3mf') {
    busy = format;
    error = null;
    const name = `${(store.detail?.title ?? 'model').replace(/[^\w-]+/g, '_').slice(0, 40)}.${format}`;
    try {
      const blob = readonly && store.source
        ? await store.geom.exportFile({ source: store.source, params: $state.snapshot(store.values), inputs: $state.snapshot(store.inputs), format, title: store.detail?.title })
        : await api.exportFile(store.id, format, $state.snapshot(store.values));
      await download(blob, name);
    } catch (e) {
      // fall back to the local worker if the server cannot export
      try {
        if (!store.source) throw e;
        const blob = await store.geom.exportFile({ source: store.source, params: $state.snapshot(store.values), inputs: $state.snapshot(store.inputs), format, title: store.detail?.title });
        await download(blob, name);
      } catch (e2) {
        error = errorText(e2);
      }
    } finally {
      busy = null;
    }
  }

  async function slice() {
    try {
      localStorage.setItem('fw_printer', printer);
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

  async function placeOrder() {
    busy = 'order';
    error = null;
    try {
      order = await api.order(store.id, { quantity: qty, material, color: color || undefined, comment: comment || undefined });
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = null;
    }
  }

  let fingerprint = $state<Record<string, any> | null>(null);

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
      await store.send('Here is a photo of the printed part on a reference sheet. Compare it with the target and tell me what to correct.', [a.id]);
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = null;
    }
  }

  function chooseProbe(v: { label: string; value: any }) {
    store.send(`Probe result for ${store.probe?.dimension}: variant ${v.label} (${v.value}) fits best.`);
  }
</script>

<div class="print stack">
  <div class="row">
    <button class="btn" onclick={() => dl('stl')} disabled={!store.source || busy === 'stl'}>⬇ {t('download_stl')}</button>
    <button class="btn" onclick={() => dl('3mf')} disabled={!store.source || busy === '3mf'}>⬇ {t('download_3mf')}</button>
  </div>

  {#if !readonly}
    <section class="stack">
      <h3 class="section-title">{t('slice')}</h3>
      <label class="lab">{t('printer')}
        <select bind:value={printer}>
          {#if !printers.length}<option value="">generic 0.4</option>{/if}
          {#if popular.length}
            <optgroup label="Popular">
              {#each popular as p (p.id ?? p.name)}<option value={p.id ?? p.name}>{p.name}</option>{/each}
            </optgroup>
          {/if}
          {#each byVendor as [vendor, list] (vendor)}
            <optgroup label={vendor}>
              {#each list as p (p.id ?? p.name)}<option value={p.id ?? p.name}>{p.name}</option>{/each}
            </optgroup>
          {/each}
        </select>
      </label>
      <label class="lab">{t('material')}
        <select bind:value={material}>{#each MATERIALS as m (m)}<option>{m}</option>{/each}</select>
      </label>
      <div class="row goals" role="group" aria-label={t('goals')}>
        {#each GOALS as g (g)}
          <button class="chip goal" class:on={goals.includes(g)} aria-pressed={goals.includes(g)} onclick={() => (goals = goals.includes(g) ? goals.filter((x) => x !== g) : [...goals, g])}>{t(`goal.${g}`)}</button>
        {/each}
      </div>
      <button class="btn primary" onclick={slice} disabled={!store.source || store.running}>🖨 {t('slice')}</button>
      {#if store.slice}
        {@const st = store.slice.stats ?? {}}
        <div class="card res">
          <div class="row big">
            <span class="mono">⏱ {st.minutes ?? '?'} {t('minutes')}</span>
            <span class="mono">⚖ {st.grams ?? '?'} {t('grams')}</span>
            {#if st.layers}<span class="mono muted">{st.layers} {t('layers')}</span>{/if}
          </div>
          {#if st.warnings?.length}<ul class="warn">{#each st.warnings as w (w)}<li>{w}</li>{/each}</ul>{/if}
          <div class="section-title">{t('profile_diff')}</div>
          {#if !store.slice.diff?.length}
            <p class="muted small">{t('no_changes')}</p>
          {:else}
            <div class="tbl">
              {#each store.slice.diff as d (d.key)}
                <div class="drow">
                  <span class="mono key">{d.key}</span>
                  <span class="mono">{d.from} → <strong>{d.to}</strong></span>
                  <span class="small reason">{d.reason}{d.evidence ? ` (${typeof d.evidence === 'string' ? d.evidence : JSON.stringify(d.evidence)})` : ''}</span>
                </div>
              {/each}
            </div>
          {/if}
          <div class="row">
            {#if store.slice.files?.project_3mf}<a class="btn small" href={store.slice.files.project_3mf} download>3MF + profile</a>{/if}
            {#if store.slice.files?.gcode}<a class="btn small" href={store.slice.files.gcode} download>G-code</a>{/if}
          </div>
        </div>
      {/if}
    </section>

    <section class="stack">
      <h3 class="section-title">{t('probe')}</h3>
      <p class="muted small">{t('probe_hint')}</p>
      <div class="row">
        <select bind:value={probeParam} aria-label={t('probe_param')} style="flex:1;min-width:0">
          <option value="">{t('probe_param')}…</option>
          {#each numericParams as [n, s] (n)}<option value={n}>{s.label ?? n} ({store.values[n]} {s.unit ?? ''})</option>{/each}
        </select>
        <button class="btn" onclick={probe} disabled={!probeParam || store.running}>🧪 {t('make_probe')}</button>
      </div>
      {#if store.probe}
        <div class="card res">
          {#if store.probe.render}<img src={store.probe.render} alt="probe" class="probe-img" />{/if}
          <div class="row">
            {#each store.probe.variants ?? [] as v (v.label)}
              <button class="btn small" onclick={() => chooseProbe(v)}>{v.label}: {v.value}</button>
            {/each}
          </div>
          <div class="row">
            {#each Object.entries(store.probe.files ?? {}) as [k, url] (k)}<a class="btn small" href={url as string} download>{k}</a>{/each}
          </div>
        </div>
      {/if}
    </section>

    <section class="stack">
      <h3 class="section-title">{t('calib')}</h3>
      <p class="muted small">{t('calib_hint')}</p>
      <div class="row">
        <a class="btn small" href="/api/printers/coupon.3mf" download>⬇ {t('coupon')}</a>
        <label class="btn small" class:disabled={!printer || busy === 'calib'}>
          📷 {t('calib_photo')}
          <input class="sr-only" type="file" accept="image/*" capture="environment" disabled={!printer} onchange={(e) => calibrate((e.currentTarget as HTMLInputElement).files)} />
        </label>
      </div>
      {#if fingerprint}
        <div class="card res mono small">
          {#each Object.entries(fingerprint).filter(([, v]) => typeof v === 'number') as [k, v] (k)}<div>{k}: {(v as number).toFixed(2)}</div>{/each}
        </div>
      {/if}
    </section>

    <section class="stack">
      <h3 class="section-title">{t('compare')}</h3>
      <p class="muted small">{t('compare_hint')}</p>
      <label class="btn small" class:disabled={busy === 'compare' || store.running}>
        📷 {t('compare_photo')}
        <input class="sr-only" type="file" accept="image/*" capture="environment" onchange={(e) => comparePrint((e.currentTarget as HTMLInputElement).files)} />
      </label>
    </section>
  {/if}

  <section class="stack">
    <h3 class="section-title">{t('order')}</h3>
    <p class="muted small">{t('order_hint')}</p>
    <div class="row">
      <label class="lab narrow">{t('quantity')}<input type="number" min="1" max="50" bind:value={qty} /></label>
      <label class="lab narrow">{t('material')}<select bind:value={material}>{#each MATERIALS as m (m)}<option>{m}</option>{/each}</select></label>
      <label class="lab narrow">{t('color')}<input type="text" bind:value={color} placeholder="black" /></label>
    </div>
    <input type="text" bind:value={comment} placeholder={t('comment')} aria-label={t('comment')} />
    <button class="btn primary" onclick={placeOrder} disabled={!store.source || busy === 'order'}>🛒 {t('order')}</button>
    {#if order}
      <div class="card res">
        <strong>{t('order_done')}</strong>
        {#if order.message}<p class="small">{order.message}</p>{/if}
        {#if order.quote}<p class="small mono">{JSON.stringify(order.quote)}</p>{/if}
        {#if order.checkout_url}<a class="btn primary small" href={order.checkout_url} target="_blank" rel="noopener">{t('open_checkout')} ↗</a>{/if}
      </div>
    {/if}
  </section>
  {#if error}<div class="err small">{error}</div>{/if}
</div>

<style>
  section {
    border-top: 1px solid var(--line);
    padding-top: 10px;
  }
  .lab {
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 13px;
  }
  .lab.narrow {
    flex: 1;
    min-width: 80px;
  }
  .lab.narrow input,
  .lab.narrow select {
    width: 100%;
  }
  .goal {
    cursor: pointer;
  }
  .goal.on {
    background: var(--accent-soft);
    border-color: var(--accent);
  }
  .res {
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .big {
    font-size: 15px;
  }
  .tbl {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .drow {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 2px 8px;
    font-size: 12.5px;
    border-bottom: 1px dashed var(--line);
    padding-bottom: 4px;
  }
  .key {
    overflow-wrap: anywhere;
  }
  .reason {
    grid-column: 1 / -1;
    color: var(--muted);
  }
  .warn {
    margin: 0;
    padding-left: 18px;
    color: var(--warn);
    font-size: 13px;
  }
  .probe-img {
    width: 100%;
    border-radius: 6px;
  }
  .small {
    font-size: 12.5px;
  }
  .err {
    color: var(--err);
  }
</style>
