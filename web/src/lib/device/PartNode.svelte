<script lang="ts" module>
  import type { Accessory, DevNode, NodeView, PinView } from './api';

  /** acc: the library's card of an accessory node; lit: one of a group the person picked (a requirement, a layout);
   *  face: what the case does over the part; placed: the designer's own placement (place or a layout) of it. */
  export type PartData = {
    node: DevNode; view?: NodeView; issues: number; power: boolean; hl?: string | null; acc?: Accessory | null; lit?: boolean;
    face?: string; placed?: string | null;
    /** Drawn mirrored: its pins swap sides to face what they are wired to. */
    flip?: boolean;
  };

  export const KIND_ICON: Record<string, string> = {
    module: 'ti-cpu', chip: 'ti-cpu-2', resistor: 'ti-wave-square', capacitor: 'ti-battery-2', led: 'ti-bulb', diode: 'ti-chevrons-right',
    button: 'ti-hand-click', header: 'ti-plug-connected', usb_c: 'ti-usb', jst: 'ti-battery-charging', hole: 'ti-circle-dashed', accessory: 'ti-puzzle',
  };
  const EDGE_ARROW: Record<string, string> = { '-x': '←', '+x': '→', '-y': '↓', '+y': '↑' };
  const TWO = new Set(['resistor', 'capacitor', 'led', 'diode', 'button', 'jst']);

  /** Pins on the left and the right: two-pin parts one each side, headers and modules on a cable on one side (in their
   *  connector's order), ICs like a DIP package. */
  export function sides(node: DevNode, pins: PinView[]): [PinView[], PinView[]] {
    if (TWO.has(node.kind)) return [pins.slice(0, 1), pins.slice(1)];
    if (node.kind === 'header' || node.kind === 'accessory') return [pins, []];
    const half = Math.ceil(pins.length / 2);
    return [pins.slice(0, half), pins.slice(half).reverse()];
  }

  // supply nets keep one colour everywhere; signal nets take the next of a set in the order of the device, so no two of a
  // device's nets look alike (no reds among them: a wire must not look like an error)
  const POWER_COLOR: Record<string, string> = { GND: 'var(--net-gnd)', AGND: 'var(--net-gnd)' };
  const HUES = [210, 130, 275, 180, 55, 320, 95, 245, 160, 35, 300, 195];
  const hue = (i: number) => `hsl(${HUES[i % HUES.length]} 72% var(--net-l))`;

  function supplyColor(up: string): string | null {
    if (POWER_COLOR[up]) return POWER_COLOR[up];
    if (/^V?3V3|VDD|VCC|V1V8$/.test(up)) return 'var(--net-3v3)';
    if (/^(V5|V5V|VBUS|VSYS|VIN|V12|V9)$/.test(up)) return 'var(--net-5v)';
    if (up === 'VBAT') return 'var(--net-bat)';
    return null;
  }

  /** The colour of each net of a device, by its key (its name, else n + its index). */
  export function netColors(nets: { name?: string | null }[]): Record<string, string> {
    const out: Record<string, string> = {};
    let k = 0;
    nets.forEach((net, i) => {
      const key = net.name ?? `n${i}`;
      out[key] = supplyColor(key.toUpperCase()) ?? hue(k++);
    });
    return out;
  }

  let assigned = $state.raw<Record<string, string>>({});
  /** The device on show: what netColor answers from, in every view of it. */
  export function useNetColors(colors: Record<string, string>) {
    assigned = colors;
  }

  export function netColor(name: string | null | undefined): string {
    if (!name) return 'var(--on-surface-var)';
    if (assigned[name]) return assigned[name];
    const up = name.toUpperCase();
    const supply = supplyColor(up);
    if (supply) return supply;
    let h = 0;
    for (const ch of up) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return hue(h);
  }
</script>

<script lang="ts">
  import { Handle, Position, type NodeProps } from '@xyflow/svelte';
  import { POWER_NET } from './store.svelte';
  import { accName, dt, stockText, usd } from './i18n';

  let { id, data, selected }: NodeProps & { data: PartData } = $props();
  const node = $derived(data.node);
  const view = $derived(data.view);
  const acc = $derived(node.kind === 'accessory' ? (data.acc ?? null) : null);
  // a header's pins are its labels; an accessory's those of its library card until the server's view arrives
  const ownPins = $derived(node.kind === 'header' ? node.pins : node.kind === 'accessory' ? acc?.pins : undefined);
  const pins = $derived<PinView[]>(view?.pins?.length ? view.pins : (ownPins ?? []).map((name) => ({ name, net: null })));
  const pair = $derived(sides(node, pins));
  const left = $derived(data.flip ? pair[1] : pair[0]);
  const right = $derived(data.flip ? pair[0] : pair[1]);
  const part = $derived(view?.part ?? {});
  const title = $derived(
    node.kind === 'resistor' || node.kind === 'capacitor' ? `${node.value ?? ''} ${node.package ?? ''}`.trim()
      : node.kind === 'led' ? `${dt('k_led')} · ${node.color ?? 'green'}`
        : node.kind === 'accessory' ? accName(acc?.name ?? part.mpn ?? node.accessory ?? dt('k_accessory'))
          : part.mpn ?? dt(`k_${node.kind}`),
  );
  const price = $derived(view?.price_usd ?? (node.kind === 'accessory' ? acc?.price_usd : null) ?? null);
  const face = $derived(data.face && data.face !== 'none' ? data.face : null);
  const named = (p: PinView) => !!p.net && !/^n\d+$/.test(p.net);
  const isPower = (p: PinView) => POWER_NET.test(p.net ?? '');
  // supply nets are labels unless their wires are on: then no colour of their own to read as a warning
  const pinColor = (p: PinView) => (isPower(p) && !data.power ? 'var(--on-surface-var)' : netColor(p.net));
  // what the case does over the part, where the designer placed it, the board edge it faces: in words, not badges
  const notes = $derived(
    [
      face ? dt(`face_${face}`) : '',
      data.placed ?? '',
      node.edge ? `${dt('edge')}: ${dt(`edge_${node.edge}`)}` : '',
    ].filter(Boolean),
  );
</script>

{#snippet pinRow(p: PinView, side: 'left' | 'right')}
  <div class="pin {side}" class:wired={!!p.net} class:lit={!!data.hl && p.net === data.hl}>
    <Handle type="source" id={p.name} position={side === 'left' ? Position.Left : Position.Right} class="h" style="--c: {pinColor(p)}" />
    {#if side === 'right' && named(p)}<span class="tag" class:pw={isPower(p)} style="--c: {pinColor(p)}">{p.net}</span>{/if}
    <span class="pname">{p.name}{#if p.count}<sub>×{p.count}</sub>{/if}</span>
    {#if side === 'left' && named(p)}<span class="tag" class:pw={isPower(p)} style="--c: {pinColor(p)}">{p.net}</span>{/if}
  </div>
{/snippet}

<div class="part k-{node.kind}" class:selected class:lit={!!data.lit} class:bad={data.issues > 0 || !!part.error} class:loading={node.kind === 'chip' && !view}>
  <header>
    <i class="ti {KIND_ICON[node.kind] ?? 'ti-cpu'} kicon" aria-hidden="true"></i>
    <strong class="ref mono">{id}</strong>
    <span class="title" title={title}>{title}</span>
    {#if data.issues > 0}<i class="ti ti-alert-triangle warn" title={dt('side_checks')} aria-hidden="true"></i>{/if}
  </header>
  {#if node.label}<div class="role">{node.label}</div>{/if}
  {#if notes.length}<div class="notes" title={notes.join(' · ')}>{notes.join(' · ')}</div>{/if}
  <div class="pins">
    <div class="col">
      {#each left as p (p.name)}{@render pinRow(p, 'left')}{/each}
    </div>
    <div class="col r">
      {#each right as p (p.name)}{@render pinRow(p, 'right')}{/each}
    </div>
  </div>
  {#if node.kind === 'accessory'}
    <!-- a ready-made module: not on the fab's BOM, the workshop fits it by hand -->
    <div class="foot">
      <span class="fit"><i class="ti ti-hand-grab" aria-hidden="true"></i> {dt('fitted_hand')}</span>
      {#if acc?.mount}<span>{dt(`mount_${acc.mount}`)}</span>{/if}
      {#if price != null}<span>{usd(price, 2)}</span>{/if}
    </div>
  {:else if node.kind === 'chip' && !view}
    <div class="foot muted"><i class="ti ti-loader-2 spin" aria-hidden="true"></i> LCSC {node.lcsc}</div>
  {:else if part.lcsc || view?.price_usd != null}
    <div class="foot">
      {#if part.lcsc}<span class="mono" title={part.basic === true ? dt('basic') : part.basic === false ? dt('extended') : undefined}>{part.lcsc}</span>{/if}
      {#if view?.price_usd != null}<span>{usd(view.price_usd, 3)}</span>{/if}
      {#if part.stock != null}<span class="stock" class:out={part.stock <= 0} title={dt('f_stock')}>{stockText(part.stock)}</span>{/if}
    </div>
  {/if}
</div>

<style>
  .part {
    width: 240px;
    background: var(--surface-container-low);
    border: 1px solid var(--outline-variant);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
    color: var(--on-surface);
    position: relative;
  }
  .part.selected {
    border-color: var(--primary);
    box-shadow: 0 0 0 1px var(--primary);
  }
  .part.lit {
    border-color: var(--primary);
    box-shadow: 0 0 0 2px var(--primary);
  }
  /* a module fitted by hand: an outline rather than a card, as it is not soldered by the fab */
  .k-accessory {
    border-style: dashed;
    background: transparent;
  }
  .k-accessory .fit {
    display: inline-flex;
    gap: 3px;
    align-items: center;
  }
  .part.bad {
    border-color: var(--error);
  }
  .part.loading {
    opacity: 0.75;
  }
  header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 7px 12px 5px;
    min-width: 0;
  }
  .kicon {
    font-size: var(--text-base);
    color: var(--on-surface-var);
  }
  .ref {
    font-size: var(--text-sm);
    font-weight: var(--font-weight-semibold);
  }
  .title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--on-surface-var);
  }
  .warn {
    color: var(--error);
  }
  .role,
  .notes {
    padding: 0 12px 4px;
    font-size: var(--text-xs);
    color: var(--on-surface-var);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .notes {
    color: var(--outline);
  }
  .pins {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    padding: 4px 0 6px;
    border-top: 1px solid var(--outline-variant);
  }
  .col {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
  }
  .col.r {
    align-items: flex-end;
  }
  .pin {
    position: relative;
    height: 21px;
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 0 12px;
    min-width: 0;
    max-width: 100%;
  }
  .pname {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pin:not(.wired) .pname {
    color: var(--on-surface-var);
  }
  .pname sub {
    font-size: var(--text-2xs);
    margin-left: 1px;
    color: var(--on-surface-var);
  }
  .tag {
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    line-height: 14px;
    padding: 0 4px;
    border-radius: var(--radius-xs);
    color: var(--c);
    border: 1px solid currentColor;
    white-space: nowrap;
  }
  .tag.pw {
    border-color: var(--outline-variant);
  }
  /* the whole pin row is the handle, as a pin with its name is in a schematic editor: a wire starts anywhere on it
     and ends on any pin row (DeviceEditor's connectionRadius snaps to the nearest); the dot is drawn at its edge */
  .pin :global(.h) {
    position: absolute;
    inset: 0;
    width: auto;
    height: auto;
    min-width: 0;
    min-height: 0;
    transform: none;
    border: none;
    border-radius: 0;
    background: transparent;
    cursor: crosshair;
  }
  .pin :global(.h::after) {
    content: '';
    position: absolute;
    top: 50%;
    width: 10px;
    height: 10px;
    margin-top: -5px;
    border-radius: 50%;
    box-sizing: border-box;
    border: 2px solid var(--surface-container-low);
    background: var(--outline);
  }
  .pin.left :global(.h::after) {
    left: -5px;
  }
  .pin.right :global(.h::after) {
    right: -5px;
  }
  .pin.wired :global(.h::after) {
    background: var(--c);
  }
  .pin:hover {
    background: color-mix(in srgb, var(--primary) 10%, transparent);
  }
  .pin.lit {
    background: color-mix(in srgb, var(--primary) 18%, transparent);
  }
  .pin.lit .pname {
    color: var(--on-surface);
    font-weight: var(--font-weight-semibold);
  }
  .pin :global(.h:hover::after) {
    background: var(--primary);
  }
  .foot {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 5px 12px 6px;
    border-top: 1px solid var(--outline-variant);
    font-size: var(--text-xs);
    color: var(--on-surface-var);
  }
  .foot .stock {
    margin-left: auto;
  }
  .foot .out {
    color: var(--error);
  }
</style>
