<script lang="ts" module>
  import { deviceApi, type Library } from './api';

  // fetched once for the page: the menu opens with its modules already there
  let cached: Promise<Library> | null = null;
  export function loadLibrary(): Promise<Library> {
    cached ??= deviceApi.library().catch((e) => {
      cached = null;
      throw e;
    });
    return cached;
  }
</script>

<script lang="ts">
  // The Add menu's list (Shift+A, as in Blender): one search field over the modules, the ready-made modules fitted by
  // hand (accessories: an OLED, a PIR, a soil probe), the basic parts and the live LCSC catalogue. Typing filters the modules and basics at once and searches LCSC after a short pause; arrows move,
  // Enter adds, Esc closes (AddMenu).
  import { errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import { priceAt, type DevNode, type PartCard } from './api';
  import { accessoriesOf } from './facets';
  import { dt, usd } from './i18n';

  let { onAdd }: { onAdd: (node: Omit<DevNode, 'id'>) => void } = $props();

  let lib = $state<Library | null>(null);
  let q = $state('');
  let basic = $state(false);
  let hits = $state<PartCard[] | null>(null);
  let busy = $state(false);
  let err = $state<string | null>(null);
  let active = $state(0);
  let input = $state<HTMLInputElement>();
  let list = $state<HTMLElement>();
  let seq = 0;

  // the basics and the search work without it, but the list must say the modules are missing
  let libErr = $state<string | null>(null);
  function getLibrary() {
    libErr = null;
    loadLibrary().then((l) => (lib = l)).catch((e) => (libErr = errorText(e)));
  }
  getLibrary();
  $effect(() => {
    input?.focus();
  });

  // the catalogue after a pause in typing; a newer search wins
  $effect(() => {
    const term = q.trim(), b = basic;
    if (term.length < 2) {
      hits = null;
      busy = false;
      return;
    }
    const my = ++seq;
    const t = setTimeout(async () => {
      busy = true;
      err = null;
      try {
        const r = await deviceApi.search(term, b);
        if (my === seq) hits = r;
      } catch (e) {
        if (my === seq) err = errorText(e);
      } finally {
        if (my === seq) busy = false;
      }
    }, 320);
    return () => clearTimeout(t);
  });

  type Item = { key: string; icon: string; name: string; sub: string; right?: string; tag?: 'basic' | 'ext' | 'hand'; node: Omit<DevNode, 'id'> };
  const BASICS: { kind: string; name?: string; extra?: Partial<DevNode>; words: string }[] = [
    { kind: 'resistor', extra: { value: '10k', package: '0603' }, words: 'resistor r pull' },
    { kind: 'capacitor', extra: { value: '100nF', package: '0603' }, words: 'capacitor cap c decoupling' },
    { kind: 'led', extra: { color: 'green' }, words: 'led light' },
    { kind: 'button', words: 'button switch tact' },
    { kind: 'button', name: 'k_key_mx', extra: { switch: 'mx', label: 'key' }, words: 'key switch mechanical mx cherry gateron keyboard keypad клавиша свитч' },
    { kind: 'button', name: 'k_key_choc', extra: { switch: 'choc', label: 'key' }, words: 'key switch mechanical choc kailh low profile keyboard клавиша свитч' },
    { kind: 'button', name: 'k_key_arcade', extra: { switch: 'arcade', label: 'button' }, words: 'arcade big button game quiz кнопка аркадная' },
    { kind: 'button', name: 'k_key_stomp', extra: { switch: 'stomp', label: 'pedal' }, words: 'stomp foot switch pedal педаль ножная' },
    { kind: 'header', name: 'k_terminal_5', extra: { connector: 'terminal_5', pins: ['P1', 'P2'], edge: '-y' }, words: 'terminal screw block wire power клемма винтовая' },
    { kind: 'header', extra: { pins: ['V3V3', 'GND', 'SDA', 'SCL'], edge: '-y' }, words: 'header pin connector i2c' },
    { kind: 'usb_c', extra: { edge: '-y' }, words: 'usb usb-c type-c power' },
    { kind: 'jst', extra: { edge: '+x' }, words: 'jst battery ph' },
    { kind: 'diode', words: 'diode schottky' },
  ];
  const ICON: Record<string, string> = {
    resistor: 'ti-wave-square', capacitor: 'ti-battery-2', led: 'ti-bulb', button: 'ti-hand-click', header: 'ti-plug-connected', usb_c: 'ti-usb',
    jst: 'ti-battery-charging', diode: 'ti-chevrons-right',
  };
  const DEFAULT: Record<string, string> = { resistor: '10k', capacitor: '100nF', led: 'green', header: '4 pins' };

  const matches = (hay: string) => {
    const term = q.trim().toLowerCase();
    return !term || term.split(/\s+/).every((w) => hay.toLowerCase().includes(w));
  };
  const modules = $derived<Item[]>(
    (lib?.modules ?? [])
      .filter((m) => matches(`${m.name} ${m.mcu} ${m.wireless.join(' ')} module mcu`))
      .map((m) => ({
        key: `m:${m.module}`, icon: 'ti-cpu', name: m.name.replace('Raspberry Pi ', 'RPi ').replace('Seeed ', ''),
        sub: [m.mcu, ...m.wireless].join(' · '), right: usd(m.price_usd), node: { kind: 'module', module: m.module, edge: '+y', label: 'MCU' },
      })),
  );
  // ready-made modules (an OLED, a PIR, a soil probe, a LiPo): the board gets their connector, the workshop fits them
  const accessories = $derived<Item[]>(
    accessoriesOf(lib)
      .filter((a) => matches(`${a.name} ${a.key} ${a.kind ?? ''} ${a.note ?? ''} ${(a.pins ?? []).join(' ')} module accessory ${dt('lib_accessories')}`))
      .map((a) => ({
        key: `a:${a.key}`, icon: 'ti-puzzle', name: a.name, sub: [a.mount ? dt(`mount_${a.mount}`) : '', (a.pins ?? []).join(' ')].filter(Boolean).join(' · '),
        right: a.price_usd != null ? usd(a.price_usd) : undefined, tag: 'hand',
        node: { kind: 'accessory', accessory: a.key, label: a.name, ...(a.mount === 'cable' ? { edge: '-y' as const } : {}) },
      })),
  );
  const basics = $derived<Item[]>(
    BASICS.filter((b) => matches(`${dt(b.name ?? `k_${b.kind}`)} ${b.words}`)).map((b) => ({
      key: `b:${b.name ?? b.kind}`, icon: b.name ? 'ti-keyboard' : ICON[b.kind], name: dt(b.name ?? `k_${b.kind}`), sub: DEFAULT[b.kind] ?? '', tag: b.name ? ('hand' as const) : undefined, node: { kind: b.kind, ...(b.extra ?? {}) },
    })),
  );
  const parts = $derived<Item[]>(
    (hits ?? []).map((h) => ({
      key: `c:${h.lcsc}`, icon: 'ti-cpu-2', name: h.mpn ?? h.lcsc, sub: [h.lcsc, h.package, h.stock ? dt('stock', { n: h.stock.toLocaleString() }) : dt('no_stock')].filter(Boolean).join(' · '),
      right: usd(priceAt(h.prices, 10), 3), tag: h.basic ? 'basic' : 'ext', node: { kind: 'chip', lcsc: h.lcsc, label: h.mpn ?? undefined },
    })),
  );
  const sections = $derived(
    [
      { title: dt('lib_modules'), items: modules },
      { title: dt('lib_accessories'), items: accessories },
      { title: dt('lib_basics'), items: basics },
      { title: dt('lib_lcsc'), items: parts, lcsc: true },
    ].filter((s) => s.items.length || (s.lcsc && q.trim().length >= 2)),
  );
  const flat = $derived(sections.flatMap((s) => s.items));
  $effect(() => {
    // a new list starts at its first row
    void flat.length;
    void q;
    active = 0;
  });

  function key(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!flat.length) return;
      active = (active + (e.key === 'ArrowDown' ? 1 : flat.length - 1)) % flat.length;
      list?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const it = flat[active];
      if (it) onAdd(it.node);
    }
  }
  const indexOf = (it: Item) => flat.indexOf(it);
</script>

<div class="lib">
  <div class="qf">
    <i class="ti ti-search" aria-hidden="true"></i>
    <input class="q" bind:this={input} bind:value={q} onkeydown={key} placeholder={dt('search_ph')} aria-label={dt('add_part')} spellcheck="false" autocomplete="off" />
    {#if busy}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{/if}
    <button class="pill" class:on={basic} onclick={() => (basic = !basic)} aria-pressed={basic} title={dt('search_basic')}>basic</button>
  </div>

  <div class="list" bind:this={list} role="listbox" aria-label={dt('add_part')}>
    {#if libErr}<div class="note" role="alert">{libErr} <button class="btn small" onclick={getLibrary}>{t('retry')}</button></div>{/if}
    {#each sections as s (s.title)}
      <div class="sec">{s.title}</div>
      {#each s.items as it (it.key)}
        {@const i = indexOf(it)}
        <button class="row" class:active={i === active} data-i={i} role="option" aria-selected={i === active}
          onpointerenter={() => (active = i)} onclick={() => onAdd(it.node)}>
          <i class="ti {it.icon}" aria-hidden="true"></i>
          <span class="nm">{it.name}</span>
          <span class="sub">{it.sub}</span>
          {#if it.tag}<span class="tag" class:ext={it.tag === 'ext'} class:hand={it.tag === 'hand'}>{it.tag === 'basic' ? dt('basic') : it.tag === 'hand' ? dt('fitted_hand_short') : dt('extended')}</span>{/if}
          {#if it.right}<span class="rt">{it.right}</span>{/if}
        </button>
      {/each}
      {#if 'lcsc' in s && s.lcsc && !s.items.length}
        <div class="note">{busy || !hits ? dt('lib_searching') : err ?? dt('no_hits')}</div>
      {/if}
    {:else}
      <div class="note">{dt('no_hits')}</div>
    {/each}
  </div>
  <div class="foot">{dt('lib_hint')}</div>
</div>

<style>
  .lib {
    display: flex;
    flex-direction: column;
    min-height: 0;
    max-height: inherit;
    font-size: var(--text-md);
  }
  .qf {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 6px 0 9px;
    margin: 6px;
    border-radius: var(--radius-xs);
    border: 1px solid var(--bw-field-border, var(--outline-variant));
    background: var(--bw-field, var(--surface-container-lowest));
    color: var(--on-surface-var);
    flex: none;
  }
  .qf:focus-within {
    border-color: var(--primary);
  }
  .qf input.q {
    flex: 1;
    min-width: 0;
    height: 100%;
    padding: 0;
    border: none;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    color: var(--on-surface);
    font: inherit;
    font-size: var(--text-md);
    outline: none;
  }
  .pill {
    height: 20px;
    padding: 0 7px;
    border-radius: var(--radius-md);
    border: 1px solid var(--outline-variant);
    background: transparent;
    color: var(--on-surface-var);
    font: inherit;
    font-size: var(--text-xs);
    cursor: pointer;
  }
  .pill.on {
    border-color: var(--primary);
    color: var(--primary);
    background: color-mix(in srgb, var(--primary) 12%, transparent);
  }
  .list {
    overflow: auto;
    min-height: 0;
    padding: 0 4px 4px;
  }
  .sec {
    padding: 8px 8px 3px;
    font-size: var(--text-xs);
    color: var(--on-surface-var);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    height: 26px;
    padding: 0 8px;
    border: none;
    border-radius: var(--radius-xs);
    background: transparent;
    color: var(--on-surface);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .row.active {
    background: color-mix(in srgb, var(--primary) 18%, transparent);
  }
  .row i {
    width: 14px;
    font-size: var(--text-base);
    color: var(--primary);
    flex: none;
  }
  .nm {
    flex: none;
    max-width: 48%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: var(--font-weight-medium);
  }
  .sub {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--on-surface-var);
    font-size: var(--text-sm);
  }
  .tag {
    flex: none;
    font-size: var(--text-xs);
    color: var(--ok);
  }
  .tag.ext {
    color: var(--warn-text);
  }
  .tag.hand {
    color: #2bb3a3;
  }
  .rt {
    flex: none;
    color: var(--on-surface-var);
    font-size: var(--text-sm);
    font-variant-numeric: tabular-nums;
  }
  .note {
    padding: 6px 8px;
    color: var(--on-surface-var);
    font-size: var(--text-sm);
  }
  .foot {
    flex: none;
    padding: 5px 10px;
    border-top: 1px solid var(--bw-seam, var(--outline-variant));
    color: var(--on-surface-var);
    font-size: var(--text-xs);
  }
</style>
