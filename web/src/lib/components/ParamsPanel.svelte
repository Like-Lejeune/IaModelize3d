<script lang="ts">
  import Icon from './Icon.svelte';
  import SourceBadge from './SourceBadge.svelte';
  import { i18n, t, unitLabel } from '$lib/i18n.svelte';
  import { paramGroup, paramLabel, paramOption } from '$lib/paramtext';
  import type { ParamSpec } from '$lib/types';

  let {
    specs,
    values,
    onChange,
    agentValues = {},
    building = false,
    panel,
  }: {
    specs: Record<string, ParamSpec>;
    values: Record<string, any>;
    onChange: (name: string, value: any, commit: boolean) => void;
    agentValues?: Record<string, any>;
    building?: boolean;
    /** The heading the panel around it already shows: a group of the same name goes without its own. */
    panel?: string;
  } = $props();

  let legend = $state(false);

  // groups by the heading shown, so 'Shape' and 'Form' (both 'Форма') make one section; `orig` is the program's word
  const groups = $derived.by(() => {
    const out = new Map<string, { orig: string; items: [string, ParamSpec][] }>();
    for (const [name, spec] of Object.entries(specs ?? {})) {
      if (spec.hidden) continue;
      const g = spec.group ?? '';
      const shown = paramGroup(g, i18n.lang);
      if (!out.has(shown)) out.set(shown, { orig: g, items: [] });
      out.get(shown)!.items.push([name, spec]);
    }
    return [...out.entries()];
  });
  /** The original English as a tooltip, only where the panel shows something else. */
  const orig = (shown: string, raw: string) => (shown !== raw ? raw : undefined);

  const sources = $derived([...new Set(Object.values(specs ?? {}).map((s) => (s.source === 'request' ? 'user' : s.source)).filter(Boolean))] as string[]);

  function kind(s: ParamSpec) {
    return s.kind ?? (typeof s.value === 'number' ? 'number' : typeof s.value === 'boolean' ? 'bool' : s.options ? 'choice' : 'text');
  }
  function step(s: ParamSpec) {
    if (s.step) return s.step;
    if (s.kind === 'int' || s.kind === 'seed') return 1;
    const span = (s.max ?? 100) - (s.min ?? 0);
    return span > 50 ? 0.5 : span > 5 ? 0.1 : 0.01;
  }
  function fmt(v: any) {
    return typeof v === 'number' ? (Math.abs(v) >= 100 ? +v.toFixed(1) : +v.toFixed(2)) : v;
  }
  const changed = (name: string) => agentValues[name] !== undefined && agentValues[name] !== values[name];
</script>

<div class="params">
  {#if !groups.length}
    <div class="empty">
      {#if building}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="sliders" size={40} />{/if}
      <strong>{building ? t('building_model') : t('no_program')}</strong>
      {#if !building}<p class="muted small">{t('no_program_hint')}</p>{/if}
    </div>
  {:else}
    {#each groups as [group, { orig: groupRaw, items }] (group)}
      <section>
        {#if group && group !== panel}<h4 class="section-title" title={orig(group, groupRaw)}>{group}</h4>{/if}
        {#each items as [name, s] (name)}
          {@const k = kind(s)}
          {@const raw = s.label ?? name}
          {@const label = paramLabel(raw, i18n.lang)}
          <div class="param" class:changed={changed(name)}>
            <div class="head">
              <label for="p-{name}" title={orig(label, raw) ?? label}>{label}</label>
              <SourceBadge source={s.source} />
              <span class="spacer"></span>
              {#if changed(name)}
                <button class="reset" onclick={() => onChange(name, agentValues[name], true)} title={t('reset_value')} aria-label={t('reset_value')}><Icon name="refresh" size={12} /></button>
              {/if}
              {#if k === 'number' || k === 'int' || k === 'seed'}
                <input
                  class="num mono"
                  type="number"
                  aria-label={label}
                  min={s.min}
                  max={s.max}
                  step={step(s)}
                  value={fmt(values[name])}
                  onchange={(e) => onChange(name, Number((e.currentTarget as HTMLInputElement).value), true)}
                />
                {#if s.unit}<span class="unit">{unitLabel(s.unit)}</span>{/if}
              {/if}
            </div>
            {#if k === 'number' || k === 'int' || k === 'seed'}
              <div class="slider">
                <input
                  id="p-{name}"
                  type="range"
                  min={s.min ?? 0}
                  max={s.max ?? Math.max(10, Number(s.value) * 3)}
                  step={step(s)}
                  value={values[name]}
                  oninput={(e) => onChange(name, Number((e.currentTarget as HTMLInputElement).value), false)}
                  onchange={(e) => onChange(name, Number((e.currentTarget as HTMLInputElement).value), true)}
                />
                {#if k === 'seed'}
                  <button class="btn small icon" aria-label={t('random_value')} title={t('random_value')} onclick={() => onChange(name, Math.floor(Math.random() * ((s.max ?? 9999) - (s.min ?? 0))) + (s.min ?? 0), true)}><Icon name="refresh" size={14} /></button>
                {/if}
              </div>
            {:else if k === 'bool'}
              <label class="toggle"><input id="p-{name}" type="checkbox" checked={!!values[name]} onchange={(e) => onChange(name, (e.currentTarget as HTMLInputElement).checked, true)} /> <span class="small">{values[name] ? t('bool_on') : t('bool_off')}</span></label>
            {:else if k === 'choice' && s.options}
              <div class="choices" role="radiogroup" aria-label={label}>
                {#if s.options.length <= 4}
                  {#each s.options as o (o)}
                    {@const ol = paramOption(o, i18n.lang)}
                    <button class="chip opt" class:on={values[name] === o} role="radio" aria-checked={values[name] === o} title={orig(ol, o)} onclick={() => onChange(name, o, true)}>{ol}</button>
                  {/each}
                {:else}
                  <select id="p-{name}" value={values[name]} onchange={(e) => onChange(name, (e.currentTarget as HTMLSelectElement).value, true)}>
                    {#each s.options as o (o)}<option value={o}>{paramOption(o, i18n.lang)}</option>{/each}
                  </select>
                {/if}
              </div>
            {:else if k === 'color'}
              <input id="p-{name}" type="color" value={values[name]} onchange={(e) => onChange(name, (e.currentTarget as HTMLInputElement).value, true)} />
            {:else}
              <input id="p-{name}" type="text" value={values[name]} onchange={(e) => onChange(name, (e.currentTarget as HTMLInputElement).value, true)} />
            {/if}
          </div>
        {/each}
      </section>
    {/each}
    {#if sources.length}
      <div class="legend">
        <button class="lbtn xs" onclick={() => (legend = !legend)} aria-expanded={legend}><Icon name="info" size={13} /> {t('legend')}</button>
        {#if legend}
          <ul>
            {#each sources as s (s)}<li><SourceBadge source={s} /> <span class="xs muted">{t(`srcd.${s}`)}</span></li>{/each}
          </ul>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  .params {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: var(--space-3);
    padding: var(--space-7) var(--space-3);
    color: var(--outline);
  }
  .empty strong {
    font-size: var(--text-xl);
    font-weight: var(--font-weight-semibold);
    color: var(--on-surface);
  }
  .empty p {
    margin: 0;
    color: var(--on-surface-var);
  }
  .param {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .head label {
    font-size: var(--text-md);
    color: var(--on-surface);
    font-weight: var(--font-weight-semibold);
    /* two lines before it is cut: 'Gap around the board' fits a narrow column */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-width: 0;
  }
  .num {
    width: 76px;
    padding: 6px 8px;
    text-align: right;
    font-size: var(--text-md);
  }
  .changed .num {
    border-color: var(--primary);
  }
  .unit {
    font-size: var(--text-sm);
    font-weight: var(--font-weight-semibold);
    color: var(--outline);
    width: 24px;
    user-select: none;
  }
  .reset {
    border: none;
    background: none;
    color: var(--primary);
    padding: 2px;
    cursor: pointer;
    display: grid;
    place-items: center;
  }
  .slider {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .slider input[type='range'] {
    flex: 1;
    min-width: 0;
  }
  .choices {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .toggle {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .legend ul {
    list-style: none;
    padding: 0;
    margin: 6px 0 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .lbtn {
    border: none;
    background: none;
    font-family: inherit;
    font-weight: var(--font-weight-semibold);
    color: var(--primary);
    display: inline-flex;
    gap: 5px;
    align-items: center;
    padding: 0;
  }
</style>
