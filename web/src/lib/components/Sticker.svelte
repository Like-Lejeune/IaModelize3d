<script lang="ts">
  // Cut-out of the selected object: photo pixels where the (white-on-black) mask is set,
  // cropped to the selection's bounding box.
  let { photo, mask, bbox = null, size = 56 }: { photo: string; mask: string; bbox?: number[] | null; size?: number } = $props();
  let canvas = $state<HTMLCanvasElement>();

  const load = (src: string) =>
    new Promise<HTMLImageElement>((res, rej) => {
      const im = new Image();
      im.onload = () => res(im);
      im.onerror = rej;
      im.src = src;
    });

  $effect(() => {
    const c = canvas;
    if (!c) return;
    let cancelled = false;
    Promise.all([load(photo), load(mask)])
      .then(([p, m]) => {
        if (cancelled) return;
        const W = p.naturalWidth, H = p.naturalHeight;
        let [x0, y0, x1, y1] = bbox && bbox.length === 4 ? bbox : [0, 0, W, H];
        const pad = Math.max(4, (x1 - x0) * 0.06);
        x0 = Math.max(0, x0 - pad);
        y0 = Math.max(0, y0 - pad);
        x1 = Math.min(W, x1 + pad);
        y1 = Math.min(H, y1 + pad);
        const w = Math.max(1, Math.round(x1 - x0)), h = Math.max(1, Math.round(y1 - y0));
        c.width = w;
        c.height = h;
        const g = c.getContext('2d')!;
        // mask luminance -> alpha
        const mc = document.createElement('canvas');
        mc.width = w;
        mc.height = h;
        const mg = mc.getContext('2d')!;
        mg.drawImage(m, x0 * (m.naturalWidth / W), y0 * (m.naturalHeight / H), w * (m.naturalWidth / W), h * (m.naturalHeight / H), 0, 0, w, h);
        const md = mg.getImageData(0, 0, w, h);
        for (let i = 0; i < md.data.length; i += 4) {
          md.data[i + 3] = md.data[i];
          md.data[i] = md.data[i + 1] = md.data[i + 2] = 0;
        }
        mg.putImageData(md, 0, 0);
        g.drawImage(p, x0, y0, w, h, 0, 0, w, h);
        g.globalCompositeOperation = 'destination-in';
        g.drawImage(mc, 0, 0);
        g.globalCompositeOperation = 'source-over';
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  });
</script>

<canvas bind:this={canvas} class="sticker" style:max-width="{size}px" style:max-height="{size}px" aria-hidden="true"></canvas>

<style>
  .sticker {
    background: repeating-conic-gradient(var(--panel-2) 0 25%, var(--panel) 0 50%) 0 0 / 10px 10px;
    border-radius: 6px;
    flex: none;
    filter: drop-shadow(0 1px 2px rgb(0 0 0 / 0.3));
  }
</style>
