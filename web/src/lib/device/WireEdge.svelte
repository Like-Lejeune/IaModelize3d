<script lang="ts">
  // One wire of the schematic: the board routes it with the others. A band of the sheet's colour under the line opens a
  // gap where it crosses another net; a dot marks where its own net branches, as on a drawn schematic.
  import { getContext } from 'svelte';
  import { BaseEdge, Position, type EdgeProps } from '@xyflow/svelte';
  import { wirePath } from './wires';
  import type { WireBoard } from './wireboard.svelte';

  let { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, data, interactionWidth }: EdgeProps = $props();
  const board = getContext<WireBoard>('fw.wires');

  const side = (p: Position) => (p === Position.Left ? -1 : 1);
  const net = $derived(String(data?.net ?? id));
  $effect(() => {
    board.want({ id, net, a: [sourceX, sourceY], aDir: side(sourcePosition), b: [targetX, targetY], bDir: side(targetPosition) });
  });
  $effect(() => () => board.drop(id));

  // until the first routing: a plain step through the middle
  const plain = $derived.by(() => {
    const mx = (sourceX + targetX) / 2;
    return wirePath([[sourceX, sourceY], [mx, sourceY], [mx, targetY], [targetX, targetY]]);
  });
  const path = $derived(board.paths[id] ?? plain);
  const dots = $derived(data?.first ? (board.joints[net] ?? []) : []);
</script>

<path d={path} class="wire-halo" fill="none" />
<BaseEdge {id} {path} {style} {interactionWidth} />
{#each dots as d (`${d[0]},${d[1]}`)}
  <circle cx={d[0]} cy={d[1]} r="3" fill={String(data?.color ?? 'currentColor')} class="wire-dot" />
{/each}
