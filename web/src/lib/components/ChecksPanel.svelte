<script lang="ts">
  import Icon from './Icon.svelte';
  import { i18n, t, fmtMinutes, unitLabel } from '$lib/i18n.svelte';
  import type { CheckReport, Issue } from '$lib/types';

  let {
    checks,
    selected = null,
    onSelect,
    building = false,
    onAskFix,
  }: {
    checks: CheckReport | null;
    selected?: Issue | null;
    onSelect: (i: Issue | null) => void;
    building?: boolean;
    onAskFix?: (text: string) => void;
  } = $props();

  // Plain-language names for the slicer-like checks (server titles are English and technical).
  const NAMES: Record<string, [string, string]> = {
    floating_island: ['Part starts in mid-air — needs support', 'Часть начинается в воздухе — нужна опора'],
    overhang: ['Steep overhang — may droop', 'Крутое нависание — может провиснуть'],
    long_bridge: ['Long unsupported span', 'Длинный пролёт без опоры'],
    too_thin: ['Too thin to print — will disappear', 'Слишком тонко — не напечатается'],
    thin_wall: ['Very thin wall — fragile', 'Очень тонкая стенка — хрупко'],
    fine_detail: ['Tiny details will be rounded', 'Мелкие детали скруглятся'],
    exceeds_bed: ['Does not fit the print bed', 'Не помещается на стол принтера'],
    small_contact: ['Small footprint — may come loose', 'Маленькая опора — может оторваться'],
    tip_over: ['Tall and narrow — may wobble', 'Высокое и узкое — может качаться'],
    multiple_bodies: ['Several separate pieces', 'Несколько отдельных частей'],
    short_layer_time: ['Small layers cool too little', 'Мелкие слои не успевают остыть'],
    vase_incompatible: ['Cannot print in vase mode', 'Нельзя печатать в режиме вазы'],
    invalid_mesh: ['Geometry is broken', 'Геометрия повреждена'],
    empty: ['Model is empty', 'Модель пустая'],
    elephant_foot: ['Bottom edge will bulge', 'Нижний край расплывётся'],
    horizontal_hole: ['Round hole in a wall will sag', 'Круглое отверстие в стенке провиснет'],
    small_text: ['Text too fine', 'Текст слишком мелкий'],
    fit_clearance: ['Parts too tight to move', 'Слишком малый зазор между частями'],
    load_across_layers: ['Load pulls layers apart', 'Нагрузка рвёт слои'],
  };
  const HINT_RU: Record<string, string> = {
    floating_island: 'Добавить опору-конус снизу или повернуть деталь.',
    overhang: 'Заменить нависание фаской 45° или повернуть деталь.',
    long_bridge: 'Сократить пролёт или поставить ребро посередине.',
    too_thin: 'Утолщить хотя бы до 0,9 мм или убрать элемент.',
    thin_wall: 'Делать стенки кратными ширине линии: 0,84 / 1,26 мм.',
    fine_detail: 'Обычно не страшно; утолщить, только если важна острая кромка.',
    exceeds_bed: 'Повернуть по диагонали или разрезать с шипами.',
    small_contact: 'Положить большой плоской стороной вниз или добавить кайму.',
    tip_over: 'Печатать лёжа или расширить основание.',
    multiple_bodies: 'Если так задумано — ок; иначе соединить.',
    short_layer_time: 'Печатать несколько копий или замедлить мелкие слои.',
    vase_incompatible: 'В режиме вазы — один контур на слой, без отверстий и крышки.',
  };

  type Group = { code: string; severity: string; title: string; count: number; z: [number, number] | null; hints: string[]; first: Issue };
  const groups = $derived.by(() => {
    if (!checks) return [] as Group[];
    const m = new Map<string, Group>();
    for (const is of checks.issues) {
      const g = m.get(is.code);
      if (!g) {
        m.set(is.code, { code: is.code, severity: is.severity, title: name(is.code, is.message), count: 1, z: is.z ? [...is.z] as [number, number] : null, hints: is.hints ?? [], first: is });
      } else {
        g.count++;
        if (is.severity === 'error') g.severity = 'error';
        if (is.z && g.z) g.z = [Math.min(g.z[0], is.z[0]), Math.max(g.z[1], is.z[1])];
      }
    }
    const order = { error: 0, warn: 1, info: 2 } as Record<string, number>;
    return [...m.values()].sort((a, b) => order[a.severity] - order[b.severity] || b.count - a.count);
  });

  function name(code: string, fallback: string) {
    const n = NAMES[code];
    return n ? n[i18n.lang === 'ru' ? 1 : 0] : fallback.split(':')[0];
  }
  function hint(g: Group) {
    return i18n.lang === 'ru' && HINT_RU[g.code] ? [HINT_RU[g.code]] : g.hints.slice(0, 2);
  }

  const errors = $derived(groups.filter((g) => g.severity === 'error').length);
  const warns = $derived(groups.filter((g) => g.severity === 'warn').length);
  const level = $derived(!checks ? 'none' : errors ? 'err' : warns ? 'warn' : 'ok');
  const s = $derived(checks?.stats);
  let open = $state<string | null>(null);
</script>

<div class="checks">
  {#if !checks}
    <div class="empty">
      {#if building}<span class="spin"></span>{:else}<Icon name="check-circle" size={22} />{/if}
      <strong>{building ? t('checks_running') : t('no_program')}</strong>
    </div>
  {:else}
    <div class="sum {level}">
      <span class="light"><Icon name={level === "ok" ? "check" : "alert"} size={16} stroke={2.4} /></span>
      <div>
        <strong>{t(level === 'ok' ? 'checks_ok' : level === 'warn' ? 'checks_warn' : 'checks_err')}</strong>
        <div class="small">{t(level === 'ok' ? 'checks_ok_d' : level === 'warn' ? 'checks_warn_d' : 'checks_err_d')}</div>
      </div>
      {#if building}<span class="spin"></span>{/if}
    </div>

    {#if s}
      <dl class="stats">
        <div><dt>{t('size')}</dt><dd class="mono">{s.size.map((v) => +v.toFixed(1)).join(' × ')} {unitLabel('mm')}</dd></div>
        <div><dt>{t('weight')} · {t('est')}</dt><dd class="mono">≈ {Math.round(s.estGrams)} {t('grams')}</dd></div>
        <div><dt>{t('time')} · {t('est')}</dt><dd class="mono">≈ {fmtMinutes(s.estMinutes)}</dd></div>
        {#if s.layers}<div><dt>{t('layers')}</dt><dd class="mono">{s.layers}</dd></div>{/if}
      </dl>
    {/if}

    {#if groups.length}
      <ul class="groups">
        {#each groups as g (g.code)}
          <li class={g.severity}>
            <button
              class="g"
              aria-expanded={open === g.code}
              onclick={() => {
                open = open === g.code ? null : g.code;
                onSelect(open ? g.first : null);
              }}
            >
              <span class="dot" aria-hidden="true"></span>
              <span class="ttl">{g.title}</span>
              {#if g.count > 1}<span class="chip xs">{t('times', { n: g.count })}</span>{/if}
              {#if g.z}<span class="xs muted mono">{t('at_height', { z: g.z[0] === g.z[1] ? g.z[0].toFixed(1) : `${g.z[0].toFixed(0)}–${g.z[1].toFixed(0)}` })}</span>{/if}
            </button>
            {#if open === g.code}
              <div class="detail">
                {#if hint(g).length}
                  <div class="xs muted">{t('how_to_fix')}</div>
                  <ul>{#each hint(g) as h (h)}<li class="small">{h}</li>{/each}</ul>
                {/if}
                {#if onAskFix && g.severity !== 'info'}
                  <button class="btn small" onclick={() => onAskFix?.(t('ask_fix_msg', { t: g.title + (g.z ? ` (${t('at_height', { z: g.z[0].toFixed(1) })})` : '') }))}>
                    <Icon name="wand" size={14} /> {t('ask_fix')}
                  </button>
                {/if}
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>

<style>
  .checks {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 28px 8px;
    color: var(--muted);
  }
  .sum {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 10px 12px;
    border-radius: 12px;
  }
  .sum strong {
    display: block;
  }
  .sum.ok {
    background: var(--ok-soft);
  }
  .sum.warn {
    background: var(--warn-soft);
  }
  .sum.err {
    background: var(--err-soft);
  }
  .light {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: #fff;
    flex: none;
  }
  .ok .light {
    background: var(--ok);
  }
  .warn .light {
    background: var(--warn);
  }
  .err .light {
    background: var(--err);
  }
  .stats {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
    margin: 0;
  }
  .stats div {
    background: var(--panel-2);
    border-radius: 8px;
    padding: 6px 8px;
  }
  dt {
    font-size: var(--fs-xs);
    color: var(--muted);
  }
  dd {
    margin: 0;
    font-size: var(--fs-sm);
  }
  .groups {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .g {
    width: 100%;
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    background: none;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 7px 8px;
    text-align: left;
  }
  .g:hover,
  .g[aria-expanded='true'] {
    background: var(--panel-2);
    border-color: var(--line);
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex: none;
    background: var(--info);
  }
  .error .dot {
    background: var(--err);
  }
  .warn .dot {
    background: var(--warn);
  }
  .ttl {
    flex: 1;
    min-width: 140px;
    font-size: var(--fs-sm);
    font-weight: 550;
  }
  .detail {
    padding: 4px 8px 8px 25px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .detail ul {
    margin: 0;
    padding-left: 16px;
  }
</style>
