// Where a photo of w x h pixels sits inside a frame of cw x ch screen pixels: the viewfinder
// fills the screen (cover), a picked photo is shown whole (contain), and once the object is
// found the frame zooms to it. Every overlay (cut-out, outline, taps) uses the same placement.

export type Fit = 'cover' | 'contain';
export type Box = [number, number, number, number]; // x1, y1, x2, y2 in image pixels
export interface Placement {
  x: number; // screen offset of the image's top-left corner
  y: number;
  s: number; // screen pixels per image pixel
}

export function place(cw: number, ch: number, w: number, h: number, fit: Fit, focus?: Box | null, zoom = 1.8): Placement {
  if (!cw || !ch || !w || !h) return { x: 0, y: 0, s: 1 };
  const cover = Math.max(cw / w, ch / h);
  const contain = Math.min(cw / w, ch / h);
  let s = fit === 'cover' ? cover : contain;
  let cx = w / 2;
  let cy = h / 2;
  if (focus) {
    // the whole object with a margin, zoomed in a little on small ones (at most `zoom` x cover), centred where the photo allows
    const bw = Math.max(1, focus[2] - focus[0]);
    const bh = Math.max(1, focus[3] - focus[1]);
    s = Math.min(Math.max(Math.min((cw * 0.8) / bw, (ch * 0.74) / bh), contain), cover * zoom);
    cx = (focus[0] + focus[2]) / 2;
    cy = (focus[1] + focus[3]) / 2;
  }
  const sw = w * s;
  const sh = h * s;
  // no empty bands while the photo is larger than the frame
  const x = sw >= cw ? Math.min(0, Math.max(cw - sw, cw / 2 - cx * s)) : (cw - sw) / 2;
  const y = sh >= ch ? Math.min(0, Math.max(ch - sh, ch / 2 - cy * s)) : (ch - sh) / 2;
  return { x, y, s };
}

/** Screen point (relative to the frame) -> image pixels, or null outside the photo. */
export function toImage(p: Placement, px: number, py: number, w: number, h: number): { x: number; y: number } | null {
  const x = (px - p.x) / p.s;
  const y = (py - p.y) / p.s;
  return x >= 0 && y >= 0 && x <= w && y <= h ? { x, y } : null;
}

export function toScreen(p: Placement, x: number, y: number): { x: number; y: number } {
  return { x: p.x + x * p.s, y: p.y + y * p.s };
}

const load = (src: string) =>
  new Promise<HTMLImageElement>((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = rej;
    im.src = src;
  });

/** Photo pixels where the white-on-black mask is set, on a transparent canvas (at most `max` px on a side). */
export async function cutout(photo: string, mask: string, max = 1400): Promise<HTMLCanvasElement> {
  const [p, m] = await Promise.all([load(photo), load(mask)]);
  const k = Math.min(1, max / Math.max(p.naturalWidth, p.naturalHeight));
  const w = Math.max(1, Math.round(p.naturalWidth * k));
  const h = Math.max(1, Math.round(p.naturalHeight * k));
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const g = c.getContext('2d')!;
  g.drawImage(m, 0, 0, w, h);
  const d = g.getImageData(0, 0, w, h);
  for (let i = 0; i < d.data.length; i += 4) {
    d.data[i + 3] = d.data[i]; // luminance -> alpha
    d.data[i] = d.data[i + 1] = d.data[i + 2] = 0;
  }
  g.putImageData(d, 0, 0);
  g.globalCompositeOperation = 'source-in';
  g.drawImage(p, 0, 0, w, h);
  return c;
}

/** Camera frame or picked file -> JPEG no larger than `max` px, upright. */
export async function toJpeg(src: CanvasImageSource & { videoWidth?: number }, max = 2560): Promise<{ blob: Blob; w: number; h: number }> {
  const sw = (src as HTMLVideoElement).videoWidth || (src as ImageBitmap).width;
  const sh = (src as HTMLVideoElement).videoHeight || (src as ImageBitmap).height;
  const k = Math.min(1, max / Math.max(sw, sh));
  const w = Math.round(sw * k);
  const h = Math.round(sh * k);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  c.getContext('2d')!.drawImage(src, 0, 0, w, h);
  const blob = await new Promise<Blob | null>((r) => c.toBlob(r, 'image/jpeg', 0.9));
  if (!blob) throw new Error('could not encode the photo');
  return { blob, w, h };
}
