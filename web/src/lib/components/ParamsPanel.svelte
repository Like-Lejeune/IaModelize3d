<script lang="ts">
  import { t } from '$lib/i18n.svelte';
  import type { ParamSpec } from '$lib/types';

  let {
    specs,
    values,
    onChange,
  }: {
    specs: Record<string, ParamSpec>;
    values: Record<string, any>;
    onChange: (name: string, value: any, commit: boolean) => void;
  } = $props();

  const SOURCE_ICON: Record<string, string> = {
    photo: '📷', caliper: '📏', standard: '📘', search: '🔎', user: '👤', assumed: '❔', design: '✎', memory: '🧠',
  };

  const groups = $derived.by(() => {
    const out = new Map<string, [string, ParamSpec][]>();
    for (const [name, spec] of Object.entries(specs ?? {})) {
      if (spec.hidden) continue;
      const g = spec.group ?? '';
      if (!out.has(g)) out.set(g, []);
      out.get(g)!.push([name, spec]);
    }
    return [...out.entries()];
  });

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
    return typeof v === 'number' ? (Math.abs(v) >= 100 ? v.toFixed(1) : +v.toFixed(2)) : v;
  }
</script>

<div class="params">
  {#if !groups.length}
    <p class="muted">{t('no_program')}</p>
  {/if}
  {#each groups as [group, items] (group)}
    {#if group}<div class="section-title">{group}</div>{/if}
    {#each items as [name, s] (name)}
      {@const k = kind(s)}
      <div class="param">
        <div class="head">
          <label for="p-{name}">{s.label ?? name}</label>
          {#if s.source}<span class="chip src" title={s.source}>{SOURCE_ICON[s.source] ?? '•'} {s.source}</span>{/if}
          <span class="val mono">{fmt(values[name])}{s.unit ? ` ${s.unit}` : ''}</span>
        </div>
        {#if k === 'number' || k === 'int' || k === 'seed'}
          <div class="row nowrap">
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
            <input
              class="num"
              type="number"
              aria-label="{s.label ?? name} value"
              min={s.min}
              max={s.max}
              step={step(s)}
              value={values[name]}
              onchange={(e) => onChange(name, Number((e.currentTarget as HTMLInputElement).value), true)}
            />
            {#if k === 'seed'}
              <button class="btn small" aria-label="random seed" onclick={() => onChange(name, Math.floor(Math.random() * ((s.max ?? 9999) - (s.min ?? 0))) + (s.min ?? 0), true)}>🎲</button>
            {/if}
          </div>
        {:else if k === 'bool'}
          <input id="p-{name}" type="checkbox" checked={!!values[name]} onchange={(e) => onChange(name, (e.currentTarget as HTMLInputElement).checked, true)} />
        {:else if k === 'choice' && s.options}
          <select id="p-{name}" value={values[name]} onchange={(e) => onChange(name, (e.currentTarget as HTMLSelectElement).value, true)}>
            {#each s.options as o (o)}<option value={o}>{o}</option>{/each}
          </select>
        {:else if k === 'color'}
          <input id="p-{name}" type="color" value={values[name]} onchange={(e) => onChange(name, (e.currentTarget as HTMLInputElement).value, true)} />
        {:else}
          <input id="p-{name}" type="text" value={values[name]} onchange={(e) => onChange(name, (e.currentTarget as HTMLInputElement).value, true)} />
        {/if}
      </div>
    {/each}
  {/each}
</div>

<style>
  .params {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .param {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .head {
    display: flex;
    gap: 6px;
    align-items: center;
    font-size: 13.5px;
    min-width: 0;
  }
  .head label {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .src {
    font-size: 11px;
    padding: 0 6px;
  }
  .val {
    margin-left: auto;
    color: var(--muted);
    white-space: nowrap;
  }
  .nowrap {
    flex-wrap: nowrap;
  }
  input[type='range'] {
    flex: 1;
    min-width: 0;
    accent-color: var(--accent);
  }
  .num {
    width: 76px;
  }
</style>
