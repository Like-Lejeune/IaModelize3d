<script lang="ts" module>
  import type { Accessory, DevNode, NodeView, PinView } from './api';

  /** acc: the library's card of an accessory node; lit: one of a group the person picked (a requirement, a layout);
   *  face: what the case does over the part; placed: the designer's own placement (place or a layout) of it. */
  export type PartData = {
    node: DevNode; view?: NodeView; issues: number; power: boolean; hl?: string | null; acc?: Accessory | null; lit?: boolean;
    face?: string; placed?: string | null;
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

  // supply nets keep one colour everywhere; signal nets get one of a fixed set by name
  const POWER_COLOR: Record<string, string> = { GND: 'var(--net-gnd)', AGND: 'var(--net-gnd)' };
  const HUES = [205, 145, 28, 280, 340, 95, 180, 50];
  export function netColor(name: string | null | undefined): string {
    if (!name) return 'var(--on-surface-var)';
    const up = name.toUpperCase();
    if (POWER_COLOR[up]) return POWER_COLOR[up];
    if (/^V?3V3|VDD|VCC|V1V8$/.test(up)) return 'var(--net-3v3)';
    if (/^(V5|V5V|VBUS|VSYS|VIN|V12|V9)$/.test(up)) return 'var(--net-5v)';
    if (up === 'VBAT') return 'var(--net-bat)';
    let h = 0;
    for (const ch of up) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return `hsl(${HUES[h % HUES.length]} 62% var(--net-l))`;
  }
</script>

<script lang="ts">
  import { Handle, Position, type NodeProps } from '@xyflow/svelte';
  import { POWER_NET } from './store.svelte';
  import { FACE_ICON } from './facets';
  import { dt, usd } from './i18n';

  let { id, data, selected }: NodeProps & { data: PartData } = $props();
  const node = $derived(data.node);
  const view = $derived(data.view);
  const acc = $derived(node.kind === 'accessory' ? (data.acc ?? null) : null);
  // a header's pins are its labels; an accessory's those of its library card until the server's view arrives
  const ownPins = $derived(node.kind === 'header' ? node.pins : node.kind === 'accessory' ? acc?.pins : undefined);
  const pins = $derived<PinView[]>(view?.pins?.length ? view.pins : (ownPins ?? []).map((name) => ({ name, net: null })));
  const [left, right] = $derived(sides(node, pins));
  const part = $derived(view?.part ?? {});
  const title = $derived(
    node.kind === 'resistor' || node.kind === 'capacitor' ? `${node.value ?? ''} ${node.package ?? ''}`.trim()
      : node.kind === 'led' ? `${dt('k_led')} · ${node.color ?? 'green'}`
        : node.kind === 'accessory' ? (acc?.name ?? part.mpn ?? node.accessory ?? dt('k_accessory'))
          : part.mpn ?? dt(`k_${node.kind}`),
  );
  const price = $derived(view?.price_usd ?? (node.kind === 'accessory' ? acc?.price_usd : null) ?? null);
  const face = $derived(data.face && data.face !== 'none' ? data.face : null);
  const named = (p: PinView) => !!p.net && !/^n\d+$/.test(p.net);
</script>

{#snippet pinRow(p: PinView, side: 'left' | 'right')}
  <div class="pin {side}" class:wired={!!p.net} class:lit={!!data.hl && p.net === data.hl}>
    <Handle type="source" id={p.name} position={side === 'left' ? Position.Left : Position.Right} class="h" style="--c: {netColor(p.net)}" />
    {#if side === 'right' && named(p)}<span class="tag" class:pw={POWER_NET.test(p.net ?? '')} style="--c: {netColor(p.net)}">{p.net}</span>{/if}
    <span class="pname">{p.name}{#if p.count}<sub>×{p.count}</sub>{/if}</span>
    {#if side === 'left' && named(p)}<span class="tag" class:pw={POWER_NET.test(p.net ?? '')} style="--c: {netColor(p.net)}">{p.net}</span>{/if}
  </div>
{/snippet}

<div class="part k-{node.kind}" class:selected class:lit={!!data.lit} class:bad={data.issues > 0 || !!part.error} class:loading={node.kind === 'chip' && !view}>
  <header>
    <i class="ti {KIND_ICON[node.kind] ?? 'ti-cpu'} kicon" aria-hidden="true"></i>
    <strong class="ref mono">{id}</strong>
    <span class="title" title={title}>{title}</span>
    {#if face}<i class="ti {FACE_ICON[face as keyof typeof FACE_ICON]} badge" title="{dt('face')}: {dt(`face_${face}`)}{node.face ? '' : ` (${dt('face_auto')})`}" aria-hidden="true"></i>{/if}
    {#if data.placed}<i class="ti ti-map-pin badge" title={data.placed} aria-hidden="true"></i>{/if}
    {#if node.edge}<span class="edge" title="{dt('edge')}: {dt(`edge_${node.edge}`)}">{EDGE_ARROW[node.edge]}</span>{/if}
    {#if data.issues > 0}<i class="ti ti-alert-triangle warn" aria-hidden="true"></i>{/if}
  </header>
  {#if node.label}<div class="role">{node.label}</div>{/if}
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
      {#if part.lcsc}<span class="mono">{part.lcsc}</span>{/if}
      {#if part.basic === true}<span class="b">basic</span>{/if}
      {#if view?.price_usd != null}<span>{usd(view.price_usd, 3)}</span>{/if}
      {#if part.stock != null}<span class:out={part.stock <= 0}>{part.stock > 0 ? `${part.stock >= 1000 ? Math.round(part.stock / 1000) + 'k' : part.stock}` : '0'}</span>{/if}
    </div>
  {/if}
</div>

<style>
  .part {
    width: 230px;
    background: var(--surface-container-low);
    border: 1px solid var(--outline-variant);
    border-radius: 12px;
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.12);
    font-size: 12px;
    color: var(--on-surface);
    position: relative;
    --accent: var(--outline);
  }
  .part::before {
    content: '';
    position: absolute;
    inset: 0 auto 0 0;
    width: 4px;
    border-radius: 12px 0 0 12px;
    background: var(--accent);
  }
  .part.selected {
    border-color: var(--primary);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary) 35%, transparent);
  }
  .part.lit {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 45%, transparent), 0 0 14px color-mix(in srgb, var(--primary) 40%, transparent);
  }
  /* a module fitted by hand: an outline rather than a card, as it is not soldered by the fab */
  .k-accessory {
    --accent: #2bb3a3;
    border-style: dashed;
    border-color: color-mix(in srgb, var(--accent) 60%, var(--outline-variant));
    background: color-mix(in srgb, var(--accent) 6%, var(--surface-container-low));
  }
  .k-accessory .fit {
    color: var(--accent);
    display: inline-flex;
    gap: 3px;
    align-items: center;
  }
  .badge {
    font-size: 13px;
    color: var(--on-surface-var);
  }
  .part.bad {
    border-color: color-mix(in srgb, var(--error) 60%, var(--outline-variant));
  }
  .part.loading {
    opacity: 0.75;
  }
  .k-module { --accent: var(--primary); }
  .k-chip { --accent: var(--info, #4f8cff); }
  .k-led { --accent: #e0b400; }
  .k-usb_c, .k-jst { --accent: var(--net-5v); }
  .k-header { --accent: var(--ok, #3fb950); }
  .k-button { --accent: #b48ead; }
  header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 7px 10px 5px 12px;
    min-width: 0;
  }
  .kicon {
    font-size: 15px;
    color: var(--accent);
  }
  .ref {
    font-size: 12px;
  }
  .title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--on-surface-var);
  }
  .edge {
    font-size: 12px;
    padding: 0 5px;
    border-radius: 6px;
    background: var(--surface-container-highest);
  }
  .warn {
    color: var(--error);
  }
  .role {
    padding: 0 12px 4px;
    font-size: 11px;
    color: var(--on-surface-var);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
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
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pin:not(.wired) .pname {
    color: var(--on-surface-var);
  }
  .pname sub {
    font-size: 9px;
    margin-left: 1px;
    color: var(--on-surface-var);
  }
  .tag {
    font-family: var(--font-mono);
    font-size: 9.5px;
    line-height: 14px;
    padding: 0 4px;
    border-radius: 4px;
    color: var(--c);
    border: 1px solid color-mix(in srgb, var(--c) 55%, transparent);
    background: color-mix(in srgb, var(--c) 12%, transparent);
    white-space: nowrap;
  }
  .tag.pw {
    font-weight: var(--font-weight-semibold);
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
    padding: 5px 12px 7px;
    border-top: 1px solid var(--outline-variant);
    font-size: 10.5px;
    color: var(--on-surface-var);
  }
  .foot .b {
    color: var(--ok, #3fb950);
  }
  .foot .out {
    color: var(--error);
  }
</style>
