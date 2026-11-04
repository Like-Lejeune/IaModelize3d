<script lang="ts">
  import Icon from './Icon.svelte';
  import { i18n, t, fmtMinutes, unitLabel, encText, fmtClearance, fmtValue, partName } from '$lib/i18n.svelte';
  import type { BoardSpec, CheckReport, EnclosureChecks, EnclosureFinding, Issue } from '$lib/types';

  let {
    checks,
    selected = null,
    onSelect,
    building = false,
    onAskFix,
    example = false,
    enclosure = null,
    enclosureStale = false,
    board = null,
    focusPart = null,
    onFocusPart,
    onRecheck,
    assembled = false,
    enclosureChecking = false,
  }: {
    checks: CheckReport | null;
    selected?: Issue | null;
    onSelect: (i: Issue | null) => void;
    building?: boolean;
    onAskFix?: (text: string) => void;
    /** A hand-written home page example (author 'example'): no agent run explains its checks. */
    example?: boolean;
    /** A case's check against its board (checks.enclosure, C5). */
    enclosure?: EnclosureChecks | null;
    /** Made on another version or other params than the ones on show. */
    enclosureStale?: boolean;
    board?: BoardSpec | null;
    /** The board part whose finding is open: the viewer lights up its rays. */
    focusPart?: string | null;
    onFocusPart?: (part: string | null) => void;
    onRecheck?: () => void;
    /** The case is shown closed: the printability report below is the print layout's. */
    assembled?: boolean;
    /** The studio is checking the case against its board for the values on show. */
    enclosureChecking?: boolean;
  } = $props();

  // Plain-language names for the slicer-like checks (server titles are English and technical).
  const NAMES: Record<string, [string, string]> = {
    floating_island: ['Part starts in mid-air — prints on supports', 'Часть начинается в воздухе — печать с поддержками'],
    overhang: ['Steep overhang — supports help', 'Крутое нависание — помогут поддержки'],
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
    floating_island: 'Поддержки включатся в настройках печати. Без них — конус или ребро снизу, или повернуть деталь.',
    overhang: 'Поддержки включатся в настройках печати. Без них — фаска 45° снизу или повернуть деталь.',
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

  // ---- the case against its board
  const SEV = { error: 0, warn: 1, info: 2 } as Record<string, number>;
  const encFindings = $derived([...(enclosure?.findings ?? [])].sort((a, b) => SEV[a.severity] - SEV[b.severity]));
  const encProblems = $derived(encFindings.filter((f) => f.severity !== 'info'));
  const encPassed = $derived(encFindings.filter((f) => f.severity === 'info'));
  const encLevel = $derived(!enclosure ? 'none' : enclosure.error || encFindings.some((f) => f.severity === 'error') ? 'err' : encProblems.length ? 'warn' : 'ok');
  const sm = $derived(enclosure?.summary);
  // the button the gap is about, for the tile's label
  const button = $derived(encFindings.find((f) => f.code === 'button_reach')?.part);
  const boardFrom = $derived.by(() => {
    const k = board?.source?.kind;
    return k === 'pcb' ? t('enc_board_pcb') : k?.startsWith('photo') ? t('enc_board_photo') : k === 'dataset' ? t('enc_board_dataset') : '';
  });
  let passedOpen = $state(false);
  let encOpen = $state<string | null>(null);
  const fkey = (f: EnclosureFinding) => `${f.code}:${f.part}`;
  const ru = $derived(i18n.lang === 'ru');

  function pick(f: EnclosureFinding) {
    const k = fkey(f);
    encOpen = encOpen === k ? null : k;
    onFocusPart?.(encOpen ? f.part : null);
  }
</script>

<div class="checks">
  {#if enclosure}
    <section class="enc" aria-label={t('enc_title')}>
      <h3 class="section-title">{t('enc_title')}</h3>
      <div class="sum {encLevel}">
        <span class="light"><Icon name={encLevel === 'ok' ? 'check' : 'alert'} size={16} /></span>
        <div>
          <strong>{t(encLevel === 'ok' ? 'enc_ok' : encLevel === 'warn' ? 'enc_warn' : 'enc_err')}</strong>
          <div class="small">
            {#if board}{board.name}{boardFrom ? ` · ${boardFrom}` : ''}{:else}{t(encLevel === 'ok' ? 'enc_ok_d' : encLevel === 'warn' ? 'enc_warn_d' : 'enc_err_d')}{/if}
          </div>
        </div>
      </div>
      {#if enclosure.error}<p class="small err-text">{enclosure.error}</p>{/if}
      {#if enclosure.by === 'studio' && !enclosureStale}
        <p class="xs muted note by">{ru ? 'Проверено здесь, в браузере, после вашей правки — тем же ядром, что у агента' : 'Checked here in the browser after your edit, with the same kernel the agent uses'}</p>
      {/if}
      {#if sm && (sm.usb_clearance_mm != null || sm.button_gap_mm != null || sm.snap_strain_pct != null)}
        <dl class="stats">
          {#if sm.usb_clearance_mm != null}<div><dt>{t('enc_usb')}</dt><dd class="mono">{fmtClearance(sm.usb_clearance_mm)}</dd></div>{/if}
          {#if sm.button_gap_mm != null}<div><dt>{button ? `${t('enc_button')} · ${partName(button)}` : t('enc_button')}</dt><dd class="mono">{fmtValue(sm.button_gap_mm, 'mm')}</dd></div>{/if}
          {#if sm.snap_strain_pct != null}<div><dt>{t('enc_snaps')}</dt><dd class="mono">{fmtValue(sm.snap_strain_pct, '%')}</dd></div>{/if}
        </dl>
      {/if}
      {#if enclosureStale && enclosureChecking}
        <div class="stale busy small" aria-live="polite">
          <span><i class="ti ti-loader-2 spin" aria-hidden="true"></i> {ru ? 'Проверяю корпус по плате для новых значений…' : 'Checking the case against the board for the new values…'}</span>
        </div>
      {:else if enclosureStale}
        <div class="stale small">
          <span>{t('enc_stale', { v: enclosure.version })}</span>
          {#if onRecheck}<button class="btn small" onclick={onRecheck}><Icon name="refresh" size={14} /> {t('enc_recheck')}</button>{/if}
        </div>
      {/if}
      {#if encProblems.length}
        <ul class="groups">
          {#each encProblems as f (fkey(f))}
            {@render finding(f)}
          {/each}
        </ul>
      {/if}
      {#if encPassed.length}
        <button class="fold small" onclick={() => (passedOpen = !passedOpen)} aria-expanded={passedOpen}>
          <span class="chev" class:open={passedOpen}><Icon name="chevron" size={12} /></span>
          {t('enc_passed', { n: encPassed.length })}
        </button>
        {#if passedOpen}
          <ul class="groups">
            {#each encPassed as f (fkey(f))}
              {@render finding(f)}
            {/each}
          </ul>
        {/if}
      {/if}
    </section>
    {#if checks}<h3 class="section-title">{t('checks')}</h3>{/if}
    {#if assembled && checks}<p class="xs muted note">{t('checks_print_layout')}</p>{/if}
  {/if}
  {#if !checks}
    <div class="empty">
      {#if building}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<Icon name="check-circle" size={40} />{/if}
      <strong>{building ? t('checks_running') : t('no_program')}</strong>
    </div>
  {:else}
    <div class="sum {level}">
      <span class="light"><Icon name={level === "ok" ? "check" : "alert"} size={16} /></span>
      <div>
        <strong>{t(level === 'ok' ? 'checks_ok' : level === 'warn' ? 'checks_warn' : 'checks_err')}</strong>
        <div class="small">{t(level === 'ok' ? 'checks_ok_d' : level === 'warn' ? (example ? 'checks_warn_example' : 'checks_warn_d') : 'checks_err_d')}</div>
      </div>
      {#if building}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{/if}
    </div>

    {#if s}
      <dl class="stats">
        <div><dt>{t('size')}</dt><dd class="mono">{s.size.map((v) => +v.toFixed(1)).join(' × ')} {unitLabel('mm')}</dd></div>
        <div><dt>{t('weight')} · {t('est')}</dt><dd class="mono">≈ {Math.round(s.estGrams)} {t('grams')}</dd></div>
        <div><dt>{t('time')} · {t('est')}</dt><dd class="mono">≈ {fmtMinutes(s.estMinutes)}</dd></div>
        {#if s.layers}
          <div>
            <dt>{t('layers')}</dt>
            <dd class="mono">{s.layers}</dd>
            {#if s.sliceStep}<span class="xs muted step">{t('layers_checked', { mm: +s.sliceStep.toFixed(2) })}</span>{/if}
          </div>
        {/if}
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

{#snippet finding(f: EnclosureFinding)}
  <li class={f.severity}>
    <button class="g" class:lit={focusPart === f.part && encOpen === fkey(f)} aria-expanded={encOpen === fkey(f)} onclick={() => pick(f)}>
      <span class="dot" aria-hidden="true"></span>
      <span class="ttl">{encText(f)}</span>
    </button>
    {#if encOpen === fkey(f)}
      <div class="detail">
        <!-- the kernel's own words, with the number as measured -->
        <div class="xs muted mono raw">{f.msg}</div>
        {#if onAskFix && f.severity !== 'info'}
          <button class="btn small" onclick={() => onAskFix?.(t('ask_fix_msg', { t: encText(f) }))}><Icon name="wand" size={14} /> {t('ask_fix')}</button>
        {/if}
      </div>
    {/if}
  </li>
{/snippet}

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
  .sum {
    display: flex;
    gap: 11px;
    align-items: flex-start;
    padding: 13px 15px;
    border-radius: var(--radius-card);
    border: var(--border-width) solid var(--outline-variant);
    font-size: var(--text-base);
  }
  .sum strong {
    display: block;
    font-weight: var(--font-weight-semibold);
  }
  .sum .small {
    color: var(--on-surface-var);
  }
  .sum.ok {
    background: color-mix(in srgb, var(--primary) 9%, var(--surface));
    border-color: color-mix(in srgb, var(--primary) 30%, var(--outline-variant));
  }
  .sum.warn {
    background: color-mix(in srgb, var(--warn) 10%, var(--surface));
    border-color: color-mix(in srgb, var(--warn) 35%, var(--outline-variant));
  }
  .sum.err {
    background: color-mix(in srgb, var(--error) 12%, var(--surface));
    border-color: color-mix(in srgb, var(--error) 40%, var(--outline-variant));
  }
  .light {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    flex: none;
  }
  .ok .light {
    background: var(--primary);
    color: var(--on-primary);
  }
  .warn .light {
    background: var(--warn);
    color: #241a05;
  }
  .err .light {
    background: var(--error);
    color: var(--surface);
  }
  .stats {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
    margin: 0;
  }
  .stats div {
    background: var(--surface);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-field);
    padding: 8px 12px;
  }
  dt {
    font-size: var(--text-sm);
    font-weight: var(--font-weight-semibold);
    color: var(--outline);
  }
  dd {
    margin: 0;
    font-size: var(--text-base);
    font-weight: var(--font-weight-semibold);
    color: var(--on-surface);
  }
  .step {
    display: block;
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
    border: var(--border-width) solid transparent;
    border-radius: var(--radius-field);
    padding: 8px 10px;
    font-family: inherit;
    text-align: left;
    color: var(--on-surface);
  }
  .g:hover,
  .g[aria-expanded='true'] {
    background: var(--surface);
    border-color: var(--outline-variant);
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex: none;
    background: var(--info);
  }
  .error .dot {
    background: var(--error);
  }
  .warn .dot {
    background: var(--warn);
  }
  .ttl {
    flex: 1;
    min-width: 140px;
    font-size: var(--text-md);
    font-weight: var(--font-weight-semibold);
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
  .enc {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-bottom: var(--space-3);
    border-bottom: var(--border-width) solid var(--divider);
  }
  .stale {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    padding: 10px 12px;
    border-radius: var(--radius-field);
    background: color-mix(in srgb, var(--warn) 10%, var(--surface));
    color: var(--on-surface-var);
  }
  .stale.busy {
    background: var(--surface);
  }
  .note.by {
    margin: -4px 0 0;
  }
  .err-text {
    color: var(--error);
    margin: 0;
  }
  .note {
    margin: -6px 0 0;
  }
  .g.lit {
    border-color: var(--primary);
  }
  /* a check against the board that passed */
  .enc .info .dot {
    background: var(--primary);
  }
  .raw {
    overflow-wrap: anywhere;
  }
  .fold {
    display: flex;
    align-items: center;
    gap: 4px;
    width: fit-content;
    padding: 2px 0;
    border: none;
    background: none;
    color: var(--outline);
    cursor: pointer;
    font-family: inherit;
  }
  .fold:hover {
    color: var(--on-surface);
  }
  .chev {
    display: grid;
    transition: transform 0.12s;
  }
  .chev.open {
    transform: rotate(90deg);
  }
</style>
