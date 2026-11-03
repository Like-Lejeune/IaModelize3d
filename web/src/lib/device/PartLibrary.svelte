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
  // The Add menu's list (Shift+A, as in Blender): one search field over the modules, the basic parts and the live LCSC
  // catalogue. Typing filters the modules and basics at once and searches LCSC after a short pause; arrows move,
  // Enter adds, Esc closes (AddMenu).
  import { errorText } from '$lib/api';
  import { priceAt, type DevNode, type PartCard } from './api';
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

  loadLibrary().then((l) => (lib = l)).catch(() => {});
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

  type Item = { key: string; icon: string; name: string; sub: string; right?: string; tag?: 'basic' | 'ext'; node: Omit<DevNode, 'id'> };
  const BASICS: { kind: string; extra?: Partial<DevNode>; words: string }[] = [
    { kind: 'resistor', extra: { value: '10k', package: '0603' }, words: 'resistor r pull' },
    { kind: 'capacitor', extra: { value: '100nF', package: '0603' }, words: 'capacitor cap c decoupling' },
    { kind: 'led', extra: { color: 'green' }, words: 'led light' },
    { kind: 'button', words: 'button switch tact' },
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
  const basics = $derived<Item[]>(
    BASICS.filter((b) => matches(`${dt(`k_${b.kind}`)} ${b.words}`)).map((b) => ({
      key: `b:${b.kind}`, icon: ICON[b.kind], name: dt(`k_${b.kind}`), sub: DEFAULT[b.kind] ?? '', node: { kind: b.kind, ...(b.extra ?? {}) },
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
    {#each sections as s (s.title)}
      <div class="sec">{s.title}</div>
      {#each s.items as it (it.key)}
        {@const i = indexOf(it)}
        <button class="row" class:active={i === active} data-i={i} role="option" aria-selected={i === active}
          onpointerenter={() => (active = i)} onclick={() => onAdd(it.node)}>
          <i class="ti {it.icon}" aria-hidden="true"></i>
          <span class="nm">{it.name}</span>
          <span class="sub">{it.sub}</span>
          {#if it.tag}<span class="tag" class:ext={it.tag === 'ext'}>{it.tag === 'basic' ? dt('basic') : dt('extended')}</span>{/if}
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
    font-size: 12.5px;
  }
  .qf {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 6px 0 9px;
    margin: 6px;
    border-radius: 5px;
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
    font-size: 12.5px;
    outline: none;
  }
  .pill {
    height: 20px;
    padding: 0 7px;
    border-radius: 10px;
    border: 1px solid var(--outline-variant);
    background: transparent;
    color: var(--on-surface-var);
    font: inherit;
    font-size: 11px;
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
    font-size: 10.5px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
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
    border-radius: 4px;
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
    font-size: 14px;
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
    font-size: 11.5px;
  }
  .tag {
    flex: none;
    font-size: 10.5px;
    color: var(--ok);
  }
  .tag.ext {
    color: var(--warn-text);
  }
  .rt {
    flex: none;
    color: var(--on-surface-var);
    font-size: 11.5px;
    font-variant-numeric: tabular-nums;
  }
  .note {
    padding: 6px 8px;
    color: var(--on-surface-var);
    font-size: 12px;
  }
  .foot {
    flex: none;
    padding: 5px 10px;
    border-top: 1px solid var(--bw-seam, var(--outline-variant));
    color: var(--on-surface-var);
    font-size: 11px;
  }
</style>
