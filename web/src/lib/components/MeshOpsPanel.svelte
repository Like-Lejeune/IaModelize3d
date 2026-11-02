<script lang="ts">
  // The operation list of a mesh document: what the agent (or you) did to the surface, in order.
  // Switching an op off, tuning a value or removing it rebuilds locally from that op on.
  import Icon from './Icon.svelte';
  import { t } from '$lib/i18n.svelte';
  import type { MeshDoc, ProjectStore } from '$lib/project.svelte';

  let { store }: { store: ProjectStore } = $props();

  const doc = $derived(store.meshDoc as MeshDoc);
  let open = $state<string | null>(null);

  const ICON: Record<string, string> = {
    clay: 'sphere', import: 'download', program: 'cube', sculpt: 'brush', move: 'move', scale: 'resize', rotate: 'rotate',
    smooth: 'wave', relax: 'wave', inflate: 'balloon', displace: 'texture', remesh: 'grid-dots', subdivide: 'grid-dots',
    refine: 'grid-dots', decimate: 'grid-dots', mirror: 'flip', cut: 'minus', base: 'minus', boolean: 'layers', transform: 'maximize',
    hollow: 'package', offset: 'layers', script: 'wand',
  };
  const BRUSH_ICON: Record<string, string> = {
    grab: 'hand-grab', draw: 'brush', inflate: 'balloon', crease: 'scribble', smooth: 'wave', flatten: 'minus', pinch: 'arrows-minimize',
  };
  // numbers a person may want to tune, in the order they are shown
  const FIELDS = ['strength', 'radius', 'amount', 'blend', 'smooth', 'amplitude', 'scale', 'depth', 'wall', 'iterations', 'angle', 'distance', 'levels', 'edge', 'detail', 'tolerance'];
  const FACTOR_BRUSHES = new Set(['smooth', 'flatten', 'pinch']);

  const keyOf = (op: MeshDoc['ops'][number], i: number) => op.id ?? `#${i}`;
  const fields = (op: MeshDoc['ops'][number]) => FIELDS.filter((f) => typeof op[f] === 'number');
  // op names in the UI language; an op this list does not know yet keeps its own name
  const opName = (op: string) => (t(`op.${op}`) === `op.${op}` ? op : t(`op.${op}`));
  const title = (op: MeshDoc['ops'][number]) => (op.op === 'sculpt' && op.brush ? `${t('brush.' + op.brush)}` : opName(op.op));

  function range(op: MeshDoc['ops'][number], f: string): [number, number, number] {
    const v = Number(op[f]);
    if (f === 'strength' && op.op === 'sculpt' && FACTOR_BRUSHES.has(op.brush)) return [0, 1, 0.01];
    if (f === 'strength' || f === 'amount') return [Math.min(-1, -Math.abs(v) * 3), Math.max(1, Math.abs(v) * 3), 0.05];
    if (f === 'iterations' || f === 'levels') return [0, Math.max(10, v * 3), 1];
    if (f === 'angle') return [-180, 180, 1];
    return [0, Math.max(1, Math.abs(v) * 3), Math.abs(v) >= 10 ? 0.5 : 0.05];
  }

  function set(i: number, f: string, v: number, commit: boolean) {
    store.editDoc((d) => {
      d.ops[i][f] = Math.round(v * 1000) / 1000;
    }, commit);
  }
  const toggle = (i: number) => store.editDoc((d) => (d.ops[i].enabled = d.ops[i].enabled === false ? true : false), true);
  const remove = (i: number) => store.editDoc((d) => d.ops.splice(i, 1), true);
  const symmetry = () => store.editDoc((d) => (d.symmetry = d.symmetry ? null : 'x'), true);
</script>

{#if doc}
  <section class="ops">
    <div class="head">
      <h4 class="section-title">{t('mesh_ops')} <span class="muted">· {doc.ops.length}</span></h4>
      <span class="spacer"></span>
      <button class="chip opt" class:on={!!doc.symmetry} onclick={symmetry} aria-pressed={!!doc.symmetry} title={t('symmetry')}>
        <Icon name="flip" size={13} /> {t('symmetry')} {doc.symmetry ? doc.symmetry.toUpperCase() : ''}
      </button>
      <button class="btn small icon" onclick={() => store.undoEdit()} disabled={!store.undoStack.length} aria-label={t('undo')} title={t('undo')}><Icon name="undo" size={14} /></button>
    </div>
    <p class="xs muted hint">{t('mesh_ops_hint')}</p>
    <ol>
      {#each doc.ops as op, i (keyOf(op, i))}
        {@const k = keyOf(op, i)}
        {@const nums = fields(op)}
        <li class:off={op.enabled === false} class:openrow={open === k}>
          <div class="row">
            <span class="n mono xs">{i + 1}</span>
            <button class="name" onclick={() => (open = open === k ? null : k)} aria-expanded={open === k} disabled={!nums.length}>
              <Icon name={op.op === 'sculpt' ? (BRUSH_ICON[op.brush] ?? 'brush') : (ICON[op.op] ?? 'wand')} size={15} />
              <span class="label">{op.id ?? title(op)}</span>
              {#if op.id && op.id !== op.op}<span class="kind xs muted">{title(op)}</span>{/if}
              {#if op.by === 'user'}<span class="mine xs"><Icon name="user" size={11} /> {t('op_by_user')}</span>{/if}
            </button>
            <button class="ico" onclick={() => toggle(i)} aria-label={op.enabled === false ? t('op_on') : t('op_off')} title={op.enabled === false ? t('op_on') : t('op_off')}>
              <Icon name={op.enabled === false ? 'eye-off' : 'eye'} size={15} />
            </button>
            <button class="ico" onclick={() => remove(i)} disabled={i === 0} aria-label={t('op_remove')} title={t('op_remove')}><Icon name="trash" size={15} /></button>
          </div>
          {#if op.note}<p class="note xs muted">{op.note}</p>{/if}
          {#if open === k && nums.length}
            <div class="fields">
              {#each nums as f (f)}
                {@const [lo, hi, step] = range(op, f)}
                <label class="field">
                  <span class="xs">{t('field.' + f)}</span>
                  <input type="range" min={lo} max={hi} {step} value={op[f]}
                    oninput={(e) => set(i, f, Number((e.currentTarget as HTMLInputElement).value), false)}
                    onchange={(e) => set(i, f, Number((e.currentTarget as HTMLInputElement).value), true)} />
                  <input class="num mono" type="number" {step} value={op[f]} aria-label={t('field.' + f)}
                    onchange={(e) => set(i, f, Number((e.currentTarget as HTMLInputElement).value), true)} />
                </label>
              {/each}
            </div>
          {/if}
        </li>
      {/each}
    </ol>
  </section>
{/if}

<style>
  .ops {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .head h4 {
    margin: 0;
  }
  .spacer {
    flex: 1;
  }
  .hint {
    margin: 0;
  }
  ol {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  li {
    border-radius: var(--radius-btn);
    padding: 4px 4px 4px 6px;
    transition: background-color var(--dur-fast) var(--ease-standard);
  }
  li:hover,
  li.openrow {
    background: var(--surface-high);
  }
  li.off .label,
  li.off .n {
    opacity: 0.45;
    text-decoration: line-through;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 4px;
    min-width: 0;
  }
  .n {
    width: 18px;
    color: var(--outline);
    text-align: right;
    flex: none;
  }
  .name {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    border: none;
    background: none;
    color: var(--on-surface);
    padding: 4px;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .name:disabled {
    cursor: default;
  }
  .label {
    font-weight: var(--font-weight-semibold);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .kind {
    white-space: nowrap;
  }
  .mine {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    color: var(--primary);
    white-space: nowrap;
  }
  .ico {
    border: none;
    background: none;
    color: var(--on-surface-var);
    padding: 4px;
    display: grid;
    place-items: center;
    cursor: pointer;
    border-radius: var(--radius-tag);
  }
  .ico:hover:not(:disabled) {
    color: var(--on-surface);
    background: var(--surface-container);
  }
  .ico:disabled {
    opacity: 0.3;
    cursor: default;
  }
  .note {
    margin: 0 0 2px 28px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fields {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 6px 4px 6px 28px;
  }
  .field {
    display: grid;
    grid-template-columns: 92px 1fr 68px;
    align-items: center;
    gap: 8px;
  }
  .field .num {
    padding: 4px 6px;
    text-align: right;
  }
</style>
