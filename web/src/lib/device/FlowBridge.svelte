<script lang="ts">
  // Inside <SvelteFlow>: the viewport helpers the editor's toolbar needs (fit, the centre of the view for a new part).
  import { useNodes, useSvelteFlow } from '@xyflow/svelte';
  import type { WireBoard } from './wireboard.svelte';
  import { FIT } from './layout';

  let { arrived, board, bridge = $bindable() }: { arrived: number; board: WireBoard; bridge?: { fit: () => void; fitTo: (ids: string[]) => void; centre: () => [number, number] } } = $props();
  const flow = useSvelteFlow();
  const nodes = useNodes();

  // where the parts stand and how big, for the wires: a selection changes the nodes too, and must not route anything again
  const standing = $derived(nodes.current.map((n) => `${n.position.x},${n.position.y},${n.measured?.width ?? 240},${n.measured?.height ?? 110}`).join(';'));
  $effect(() => {
    board.setBoxes(standing.split(';').filter(Boolean).map((v) => {
      const [x, y, w, h] = v.split(',').map(Number);
      return { x, y, w, h };
    }));
  });

  bridge = {
    fit: () => flow.fitView({ ...FIT, duration: 350 }),
    // a group of parts (a requirement's, a layout's), not closer than the whole schematic would be
    fitTo: (ids) => flow.fitView({ nodes: ids.map((id) => ({ id })), padding: 0.35, duration: 350, maxZoom: 1.1 }),
    centre: () => {
      const el = document.querySelector('.device-editor .svelte-flow') as HTMLElement | null;
      const r = el?.getBoundingClientRect();
      const p = flow.screenToFlowPosition({ x: (r?.left ?? 0) + (r?.width ?? 800) / 2, y: (r?.top ?? 0) + (r?.height ?? 600) / 2 });
      return [p.x - 115, p.y - 40];
    },
  };

  // a version from the agent: show all of it once its nodes are measured
  let seen = arrived;
  $effect(() => {
    if (arrived !== seen) {
      seen = arrived;
      setTimeout(() => flow.fitView({ ...FIT, duration: 400 }), 120);
    }
  });
</script>
