<script lang="ts">
  // Inside <SvelteFlow>: the viewport helpers the editor's toolbar needs (fit, the centre of the view for a new part).
  import { useSvelteFlow } from '@xyflow/svelte';

  let { arrived, bridge = $bindable() }: { arrived: number; bridge?: { fit: () => void; fitTo: (ids: string[]) => void; centre: () => [number, number] } } = $props();
  const flow = useSvelteFlow();

  bridge = {
    fit: () => flow.fitView({ padding: 0.18, duration: 350 }),
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
      setTimeout(() => flow.fitView({ padding: 0.18, duration: 400 }), 120);
    }
  });
</script>
