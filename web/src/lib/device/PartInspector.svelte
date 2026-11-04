<script lang="ts">
  // The selected part as properties panels: the part itself (role, value, board edge, what the case does over it, who
  // placed it), its LCSC card (or, for a module fitted by hand, its library card), the requirements it serves and the
  // net each pin is on. Labels on the left, values on the right, as a properties editor reads.
  import Icon from '$lib/components/Icon.svelte';
  import { deviceApi, priceAt, type Accessory, type Edge, type Face, type PartCard } from './api';
  import { errorText } from '$lib/api';
  import { EDGE_KINDS, type DeviceStore } from './store.svelte';
  import { dt, patternName, usd } from './i18n';
  import { netColor } from './PartNode.svelte';
  import { loadLibrary } from './PartLibrary.svelte';
  import { FACES, FACE_KINDS, accessoriesOf, autoFace, layoutOf, requirementsOf, sizeText } from './facets';
  import Panel from './ui/Panel.svelte';

  let { device, readonly = false }: { device: DeviceStore; readonly?: boolean } = $props();

  const s = $derived(device.state);
  const node = $derived(s?.doc.nodes.find((n) => n.id === device.selected) ?? null);
  const view = $derived(node ? s?.view.nodes[node.id] : undefined);
  const part = $derived(view?.part ?? {});
  const nets = $derived(s?.doc.nets ?? []);
  const netNames = $derived([...new Set(['GND', 'V3V3', ...nets.map((n) => n.name).filter((x): x is string => !!x)])]);

  let accs = $state<Accessory[]>([]);
  loadLibrary().then((l) => (accs = accessoriesOf(l))).catch(() => {});
  const acc = $derived(node?.kind === 'accessory' ? (accs.find((a) => a.key === node.accessory) ?? null) : null);
  // 'auto' reads as what the server (or the kind's default) gives the part
  const autoF = $derived<Face>(node ? (view?.face && !node.face ? view.face : autoFace(node, part, acc)) : 'none');
  const lay = $derived(node ? layoutOf(s?.doc, node.id) : null);
  const reqs = $derived(node ? requirementsOf(s?.doc, node.id) : []);
  const edgeOk = $derived(!!node && EDGE_KINDS.includes(node.kind) && (node.kind !== 'accessory' || acc?.mount === 'cable' || !!node.edge));
  function swapAccessory(key: string) {
    if (!node || !key || key === node.accessory) return;
    const a = accs.find((x) => x.key === key);
    device.setNode(node.id, { accessory: key, ...(a && (!node.label || node.label === acc?.name) ? { label: a.name } : {}) });
  }
  /** The designer's spot becomes the person's own: it can then be moved and turned like any placed part. */
  function takePlace() {
    if (!node?.place) return;
    device.setNode(node.id, { pcb: { x: node.place.x, y: node.place.y, rot: node.place.rot ?? 0 } });
  }

  // ---- swapping a chip for another LCSC part (its wiring stays; pins it lacks show up as problems)
  let replacing = $state(false);
  let q = $state('');
  let hits = $state<PartCard[] | null>(null);
  let busy = $state(false);
  let qErr = $state<string | null>(null);
  $effect(() => {
    void device.selected;
    replacing = false;
    hits = null;
  });
  async function search() {
    if (!q.trim()) return;
    busy = true;
    qErr = null;
    try {
      hits = await deviceApi.search(q.trim());
    } catch (e) {
      qErr = errorText(e);
    } finally {
      busy = false;
    }
  }
  function swap(h: PartCard) {
    if (!node) return;
    device.setNode(node.id, { lcsc: h.lcsc });
    replacing = false;
  }
  function pinAt(k: 'x' | 'y' | 'rot', v: string) {
    if (!node?.pcb) return;
    const n = Number(v);
    if (!Number.isFinite(n)) return;
    device.setNode(node.id, { pcb: { ...node.pcb, [k]: k === 'rot' ? n : Math.round(n * 10) / 10 } });
  }

  function netOfPin(pin: string): string {
    const i = nets.findIndex((n) => n.pins.includes(`${node!.id}.${pin}`));
    if (i < 0) return '';
    return nets[i].name ?? `#${i}`;
  }
  function assign(pin: string, value: string) {
    if (!node) return;
    if (value === '__new') {
      const name = prompt(dt('new_net_prompt'))?.trim().replace(/[^A-Za-z0-9_]/g, '_');
      if (!name) return;
      value = /^[A-Za-z_]/.test(name) ? name : `N${name}`;
    }
    device.assign(`${node.id}.${pin}`, value);
  }
  function others(i: number): string {
    return nets[i].pins.filter((p) => !p.startsWith(`${node?.id}.`)).slice(0, 3).join(', ');
  }
</script>

{#if node}
  <Panel name="part" title={`${node.id} · ${dt(`k_${node.kind}`)}`}>
    {#snippet right()}
      {#if !readonly}<button class="ib" onclick={() => device.removeNodes([node.id])} title={dt('delete')} aria-label={dt('delete')}><i class="ti ti-trash" aria-hidden="true"></i></button>{/if}
    {/snippet}
    <label class="pr"><span>{dt('label')}</span>
      <input value={node.label ?? ''} disabled={readonly} placeholder={dt('label_ph')} onchange={(e) => device.setNode(node.id, { label: e.currentTarget.value.trim() || undefined })} />
    </label>
    {#if node.kind === 'resistor' || node.kind === 'capacitor'}
      <label class="pr"><span>{dt('value')}</span>
        <input value={node.value ?? ''} disabled={readonly} onchange={(e) => device.setNode(node.id, { value: e.currentTarget.value.trim() })} />
      </label>
      <label class="pr"><span>{dt('package')}</span>
        <select value={node.package ?? '0603'} disabled={readonly} onchange={(e) => device.setNode(node.id, { package: e.currentTarget.value })}>
          {#each ['0402', '0603', '0805', '1206'] as p (p)}<option value={p}>{p}</option>{/each}
        </select>
      </label>
    {/if}
    {#if node.kind === 'led'}
      <label class="pr"><span>{dt('color')}</span>
        <select value={node.color ?? 'green'} disabled={readonly} onchange={(e) => device.setNode(node.id, { color: e.currentTarget.value })}>
          {#each ['green', 'red', 'blue', 'yellow', 'white'] as c (c)}<option value={c}>{dt(`c_${c}`)}</option>{/each}
        </select>
      </label>
    {/if}
    {#if node.kind === 'header'}
      <label class="pr"><span>{dt('pins')}</span>
        <input value={(node.pins ?? []).join(', ')} disabled={readonly} title={dt('pin_labels')}
          onchange={(e) => device.setNode(node.id, { pins: e.currentTarget.value.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean) })} />
      </label>
    {/if}
    {#if node.kind === 'accessory'}
      <label class="pr"><span>{dt('accessory')}</span>
        <select value={node.accessory ?? ''} disabled={readonly || !accs.length} onchange={(e) => swapAccessory(e.currentTarget.value)}>
          {#if !acc}<option value={node.accessory ?? ''}>{node.accessory ?? '—'}</option>{/if}
          {#each accs as a (a.key)}<option value={a.key}>{a.name}</option>{/each}
        </select>
      </label>
    {/if}
    {#if FACE_KINDS.includes(node.kind)}
      <label class="pr"><span title={dt('face_d')}>{dt('face')}</span>
        <select value={node.face ?? ''} disabled={readonly} onchange={(e) => device.setNode(node.id, { face: (e.currentTarget.value || undefined) as Face | undefined })}>
          <option value="">{dt('face_auto')} · {dt(`face_${autoF}`)}</option>
          {#each FACES as f (f)}<option value={f}>{dt(`face_${f}`)}</option>{/each}
        </select>
      </label>
    {/if}
    {#if node.pcb}
      <div class="pr"><span title={dt('pinned_d')}>{dt('on_board')}</span>
        <div class="xyr">
          <input type="number" step="0.5" value={node.pcb.x} disabled={readonly} onchange={(e) => pinAt('x', e.currentTarget.value)} aria-label="X" title="X, mm" />
          <input type="number" step="0.5" value={node.pcb.y} disabled={readonly} onchange={(e) => pinAt('y', e.currentTarget.value)} aria-label="Y" title="Y, mm" />
          <select value={node.pcb.rot} disabled={readonly} onchange={(e) => pinAt('rot', e.currentTarget.value)} aria-label={dt('rotation')}>
            {#each [0, 90, 180, 270] as r (r)}<option value={r}>{r}°</option>{/each}
          </select>
          {#if !readonly}<button class="ib" onclick={() => device.setNode(node.id, { pcb: undefined })} title={node.place || lay ? dt('unpin_designer') : dt('unpin')} aria-label={dt('unpin')}><i class="ti ti-pinned-off" aria-hidden="true"></i></button>{/if}
        </div>
      </div>
      {#if node.place || lay}<p class="note">{dt('place_overrides')}</p>{/if}
    {:else if node.place}
      <div class="pr"><span title={dt('place_designer_d')}>{dt('place_designer')}</span>
        <div class="xyr ro">
          <span class="mono">{node.place.x} · {node.place.y}{node.place.rot ? ` · ${node.place.rot}°` : ''}</span>
          {#if lay}<span class="muted">{patternName(lay.layout.pattern)} {lay.index + 1}/{lay.layout.nodes.length}</span>{/if}
          {#if !readonly}<button class="mini" onclick={takePlace} title={dt('place_take_d')}>{dt('place_take')}</button>{/if}
        </div>
      </div>
    {:else if lay}
      <div class="pr"><span title={dt('place_designer_d')}>{dt('place_designer')}</span>
        <span class="muted">{patternName(lay.layout.pattern)} · {lay.index + 1}/{lay.layout.nodes.length}</span>
      </div>
    {/if}
    {#if EDGE_KINDS.includes(node.kind) && edgeOk}
      <div class="pr"><span title={dt('edge_hint')}>{dt('edge')}</span>
        <div class="seg5" role="radiogroup" aria-label={dt('edge')}>
          {#each ['', '-x', '+y', '-y', '+x'] as e (e)}
            <button role="radio" aria-checked={(node.edge ?? '') === e} disabled={readonly || (node.kind === 'module' && !e)} onclick={() => device.setEdge(node.id, e as Edge | '')}
              title={e ? dt(`edge_${e}`) : dt('edge_none')}>{e ? { '-x': '←', '+y': '↑', '-y': '↓', '+x': '→' }[e] : '·'}</button>
          {/each}
        </div>
      </div>
    {/if}
  </Panel>

  {#if node.kind === 'accessory'}
    <Panel name="accessory" title={dt('panel_accessory')}>
      {#snippet right()}<span class="fitc"><i class="ti ti-hand-grab" aria-hidden="true"></i> {dt('fitted_hand_short')}</span>{/snippet}
      <div class="pmeta"><strong>{acc?.name ?? part.mpn ?? node.accessory}</strong></div>
      <dl class="kv">
        {#if acc?.price_usd != null || view?.price_usd != null}<dt>{dt('f_price_each')}</dt><dd>{usd(view?.price_usd ?? acc?.price_usd)}</dd>{/if}
        {#if acc?.connect}<dt>{dt('acc_connect')}</dt><dd>{dt(`connect_${acc.connect}`)}</dd>{/if}
        {#if acc?.mount}<dt>{dt('acc_mount')}</dt><dd>{dt(`mount_${acc.mount}`)}</dd>{/if}
        {#if acc?.body}<dt>{dt('acc_body')}</dt><dd>{sizeText(acc.body)} {dt('mm')}</dd>{/if}
        {#if acc?.window}<dt>{dt('acc_window')}</dt><dd>{sizeText(acc.window)} {dt('mm')}</dd>{/if}
        {#if acc?.supply}<dt>{dt('acc_supply')}</dt><dd>{acc.supply}</dd>{/if}
        {#if acc?.current_ma}<dt>{dt('acc_current')}</dt><dd>{acc.current_ma} mA</dd>{/if}
        {#if acc?.pins?.length}<dt>{dt('pins')}</dt><dd>{acc.pins.join(' · ')}</dd>{/if}
      </dl>
      <p class="note">{dt('accessory_d')}</p>
      {#if acc?.note}<p class="desc muted">{acc.note}</p>{/if}
      {#if acc?.url}<div class="links"><a href={acc.url} target="_blank" rel="noopener noreferrer">{dt('acc_page')} <Icon name="external" size={11} /></a></div>{/if}
    </Panel>
  {/if}

  {#if reqs.length}
    <Panel name="partreqs" title={dt('reqs_served')}>
      {#each reqs as r (r.id)}
        <button class="req" onclick={() => device.light(r.id, r.parts ?? [])}><span class="mono rid">{r.id}</span><span>{r.text}</span></button>
      {/each}
    </Panel>
  {/if}

  {#if node.kind !== 'accessory' && (part.mpn || part.lcsc)}
    <Panel name="lcsc" title={dt('panel_lcsc')}>
      {#snippet right()}
        {#if part.lcsc}<span class="mono">{part.lcsc}</span>{/if}
        {#if node.kind === 'chip' && !readonly}<button class="mini" onclick={() => (replacing = !replacing)} aria-expanded={replacing}>{dt('replace')}</button>{/if}
      {/snippet}
      {#if replacing}
        <form class="rs" onsubmit={(e) => (e.preventDefault(), search())}>
          <input bind:value={q} placeholder={dt('replace_ph')} aria-label={dt('replace')} />
          <button class="mini" type="submit" disabled={busy}>{#if busy}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else}<i class="ti ti-search" aria-hidden="true"></i>{/if}</button>
        </form>
        {#if qErr}<p class="errc">{qErr}</p>{/if}
        {#if hits}
          <div class="hits">
            {#each hits.filter((h) => h.lcsc !== part.lcsc) as h (h.lcsc)}
              <button class="hit" onclick={() => swap(h)}>
                <span class="hm">{h.mpn}</span>
                <span class="hd">{h.lcsc} · {h.package} · {h.stock ? h.stock.toLocaleString() : dt('no_stock')} · ${(priceAt(h.prices, 10) ?? 0).toFixed(3)}</span>
              </button>
            {/each}
          </div>
        {/if}
        <p class="note">{dt('replace_d')}</p>
      {/if}
      <div class="pcard">
        {#if part.image}<img src={part.image} alt="" referrerpolicy="no-referrer" />{/if}
        <div class="pmeta">
          <strong>{part.mpn}</strong>
          {#if part.brand}<span class="muted">{part.brand}</span>{/if}
        </div>
      </div>
      <dl class="kv">
        {#if part.package}<dt>{dt('package')}</dt><dd>{part.package}</dd>{/if}
        {#if part.basic != null}<dt>JLCPCB</dt><dd class:okc={part.basic} class:warnc={!part.basic}>{part.basic ? dt('basic') : dt('extended')}</dd>{/if}
        {#if part.stock != null}<dt>{dt('f_stock')}</dt><dd class:errc={!part.stock}>{part.stock ? part.stock.toLocaleString() : dt('no_stock')}</dd>{/if}
        {#if view?.price_usd != null}<dt>{dt('f_price')}</dt><dd>${view.price_usd.toFixed(3)}</dd>{/if}
        {#if part.size_mm}<dt>{dt('f_size')}</dt><dd>{part.size_mm[0]} × {part.size_mm[1]} {dt('mm')}</dd>{/if}
        {#if part.height_mm}<dt>{dt('f_height')}</dt><dd>{part.height_mm} {dt('mm')}</dd>{/if}
        {#if part.mcu}<dt>MCU</dt><dd>{part.mcu}{part.wireless?.length ? ` · ${part.wireless.join(', ')}` : ''}</dd>{/if}
      </dl>
      {#if part.description}<p class="desc muted">{part.description}</p>{/if}
      <div class="links">
        {#if part.url}<a href={part.url} target="_blank" rel="noopener noreferrer">{dt('lcsc_page')} <Icon name="external" size={11} /></a>{/if}
        {#if part.datasheet}<a href={part.datasheet} target="_blank" rel="noopener noreferrer">{dt('datasheet')} <Icon name="external" size={11} /></a>{/if}
      </div>
      {#if part.error}<p class="errc">{part.error}</p>{/if}
    </Panel>
  {/if}

  {#if view?.pins.length}
    <Panel name="pins" title={dt('pins')}>
      {#snippet right()}{view.pins.filter((p) => p.net).length}/{view.pins.length}{/snippet}
      {#each view.pins as p (p.name)}
        {@const cur = netOfPin(p.name)}
        <div class="pr">
          <span class="mono">{p.name}{#if p.count}<sub>×{p.count}</sub>{/if}</span>
          <select value={cur} disabled={readonly} onchange={(e) => assign(p.name, e.currentTarget.value)} style="--c: {netColor(cur || null)}" class="mono" class:on={!!cur}>
            <option value="">{dt('no_net')}</option>
            {#each netNames as n (n)}<option value={n}>{n}</option>{/each}
            {#each nets as net, i (i)}{#if !net.name}<option value={`#${i}`}>↔ {others(i)}</option>{/if}{/each}
            <option value="__new">{dt('new_net')}</option>
          </select>
        </div>
      {/each}
    </Panel>
  {/if}
{/if}

<style>
  .pr {
    display: grid;
    grid-template-columns: 38% 1fr;
    align-items: center;
    gap: 10px;
    font-size: 13px;
    min-height: var(--bw-row, 26px);
  }
  .pr > span {
    color: var(--on-surface-var);
    text-align: right;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pr input,
  .pr select {
    font: inherit;
    font-size: 13px;
    height: var(--bw-row, 26px);
    padding: 0 8px;
    min-width: 0;
    color: var(--on-surface);
    background: var(--bw-field);
    border: 1px solid var(--bw-field-border);
    border-radius: 5px;
  }
  .pr select.on {
    color: var(--c);
  }
  .pr sub {
    font-size: 9px;
  }
  .seg5 {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    border: 1px solid var(--bw-field-border);
    border-radius: 5px;
    overflow: hidden;
  }
  .seg5 button {
    height: 24px;
    border: none;
    border-left: 1px solid var(--bw-field-border);
    background: var(--bw-field);
    color: var(--on-surface);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
  }
  .seg5 button:first-child {
    border-left: none;
  }
  .seg5 button[aria-checked='true'] {
    background: var(--primary);
    color: var(--on-primary);
  }
  .seg5 button:disabled {
    opacity: 0.4;
  }
  .xyr {
    display: grid;
    grid-template-columns: 1fr 1fr 64px auto;
    gap: 4px;
    min-width: 0;
  }
  .xyr input,
  .xyr select {
    min-width: 0;
  }
  .xyr.ro {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 8px;
    font-size: 12px;
  }
  .fitc {
    color: #2bb3a3;
    display: inline-flex;
    gap: 3px;
    align-items: center;
  }
  .req {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 8px;
    align-items: baseline;
    text-align: left;
    padding: 3px 4px;
    border: none;
    border-radius: 4px;
    background: none;
    color: var(--on-surface);
    font: inherit;
    font-size: 12.5px;
    cursor: pointer;
  }
  .req:hover {
    background: color-mix(in srgb, var(--on-surface) 7%, transparent);
  }
  .rid {
    font-size: 11px;
    color: var(--on-surface-var);
  }
  .mini {
    height: 22px;
    padding: 0 8px;
    border-radius: 5px;
    border: 1px solid var(--bw-field-border);
    background: var(--bw-field);
    color: var(--on-surface);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
  }
  .rs {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 4px;
  }
  .rs input {
    font: inherit;
    font-size: 13px;
    height: var(--bw-row, 26px);
    padding: 0 8px;
    color: var(--on-surface);
    background: var(--bw-field);
    border: 1px solid var(--bw-field-border);
    border-radius: 5px;
  }
  .rs .mini {
    height: var(--bw-row, 26px);
  }
  .hits {
    display: grid;
    gap: 2px;
    max-height: 220px;
    overflow: auto;
  }
  .hit {
    display: grid;
    text-align: left;
    padding: 5px 8px;
    border-radius: 5px;
    border: none;
    background: none;
    color: var(--on-surface);
    font: inherit;
    cursor: pointer;
  }
  .hit:hover {
    background: color-mix(in srgb, var(--on-surface) 7%, transparent);
  }
  .hm {
    font-size: 13px;
    font-weight: var(--font-weight-medium);
  }
  .hd {
    font-size: 11.5px;
    color: var(--on-surface-var);
  }
  .note {
    margin: 0;
    font-size: 11.5px;
    color: var(--on-surface-var);
  }
  .ib {
    width: 20px;
    height: 20px;
    border: none;
    border-radius: 3px;
    background: none;
    color: var(--on-surface-var);
    cursor: pointer;
  }
  .ib:hover {
    background: var(--bw-field);
    color: var(--error);
  }
  .pcard {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .pcard img {
    width: 44px;
    height: 44px;
    object-fit: contain;
    background: #fff;
    border-radius: 5px;
  }
  .pmeta {
    display: grid;
    font-size: 12px;
    min-width: 0;
  }
  .pmeta .muted {
    font-size: 11px;
  }
  .kv {
    display: grid;
    grid-template-columns: 38% 1fr;
    gap: 5px 10px;
    margin: 0;
    font-size: 13px;
  }
  .kv dt {
    color: var(--on-surface-var);
    text-align: right;
  }
  .kv dd {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .okc {
    color: var(--ok);
  }
  .warnc {
    color: var(--warn-text);
  }
  .errc {
    color: var(--error);
  }
  .desc {
    margin: 0;
    font-size: 11px;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .links {
    display: flex;
    gap: 12px;
    font-size: 11.5px;
  }
  .links a {
    color: var(--primary);
    text-decoration: none;
  }
</style>
