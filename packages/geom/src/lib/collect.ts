// Instant collectibles (lib.collect): a snapped object becomes a 3D sticker in a second or two, and a
// walk's worth of them shares one print bed. The inputs come from server/formwright/vision/relief.py:
//   inputs.outlines[key]    loops of the SAM mask in photo pixels (outer loops and holes, even-odd)
//   inputs.heightmaps[key]  relief over the crop, 0..~1.3: a dome from the outline plus a little photo detail
//   inputs.values[key_x0, key_y0, key_x1, key_y1]  that crop in photo pixels; [key_name] the name on the tab
// Three parts in three colours, none overlapping: base (dark, z 0..base), figure (light, above the base) and
// name (on the tab), so a single-nozzle printer makes a two-colour sticker with one filament swap at z = base.
import type { CrossSection, Manifold } from '../kernel.ts';
import { GLYPHS } from './font.ts';

type V2 = [number, number];
type PartFn = (solid: Manifold, o?: { name?: string; color?: string }) => { solid: Manifold; name: string; color?: string };

export interface StickerOptions {
  size?: number; // longest side of the figure's outline, mm
  puff?: number; // relief height above the base at the top of the dome, mm
  base?: number; // base plate thickness, mm: the filament swap height
  border?: number; // die-cut rim around the outline, mm
  name?: string; // text on the tab; '' for none
  edge?: number; // meshing edge of the relief, mm
}

export interface PlateOptions extends StickerOptions {
  gap?: number; // between stickers, mm
  margin?: number; // from the bed edge, mm
  bed?: V2; // the printer profile's bed by default
  names?: Record<string, string>;
}

export const STICKER_COLORS = { base: '#2f3a4a', figure: '#f2efe8', name: '#f2c14e' };
export const STICKER_DEFAULTS = { size: 50, puff: 4, base: 1.6, border: 2.2, edge: 0.4 };
// tab letters: 4.5 mm with a 0.9 mm stroke still read on a 0.4 mm nozzle; 3.5 mm did not
export const NAME_MIN = 4.5;
const NAME_MAX = 5.5;
const NAME_CHARS = 16;

interface Layout {
  key: string;
  o: Required<Omit<StickerOptions, 'name'>>;
  cs: CrossSection; // the figure's outline, mm, centred
  base: CrossSection; // rim + name tab: the sticker's footprint
  text: CrossSection | null;
  height: (x: number, y: number) => number; // relief 0..~1.3 at a point of the outline
}

type Heightmap = { w: number; h: number; data: ArrayLike<number> };
const GRID = 0.25; // mm, the relief's working grid

function sample(d: ArrayLike<number>, w: number, h: number, u: number, t: number): number {
  const i = Math.max(0, Math.min(w - 2, Math.floor(u))), j = Math.max(0, Math.min(h - 2, Math.floor(t)));
  const fu = Math.max(0, Math.min(1, u - i)), ft = Math.max(0, Math.min(1, t - j));
  const a = d[j * w + i], b = d[j * w + i + 1], c = d[(j + 1) * w + i], e = d[(j + 1) * w + i + 1];
  return (a * (1 - fu) + b * fu) * (1 - ft) + (c * (1 - fu) + e * fu) * ft;
}

/** The height map on a W x H grid over the same extent (bilinear). */
function resample(hm: Heightmap, W: number, H: number): Float32Array {
  const out = new Float32Array(W * H);
  for (let j = 0; j < H; j++)
    for (let i = 0; i < W; i++) out[j * W + i] = sample(hm.data, hm.w, hm.h, (i / (W - 1)) * (hm.w - 1), (j / (H - 1)) * (hm.h - 1));
  return out;
}

/**
 * Grayscale opening of a height map with a flat disk of radius `r` mm (erosion, then dilation; cells sx by sy mm).
 * Every level set of the result is a union of such disks, so no horizontal slice of the relief holds a ridge or
 * a peak narrower than 2r: the photo's detail stays, minus what a 0.4 mm nozzle could not draw anyway.
 */
export function openRelief(data: ArrayLike<number>, w: number, h: number, sx: number, sy: number, r: number): Float32Array {
  const offs: V2[] = [];
  const ri = Math.ceil(r / sx), rj = Math.ceil(r / sy);
  for (let dj = -rj; dj <= rj; dj++) for (let di = -ri; di <= ri; di++) if ((di * sx) ** 2 + (dj * sy) ** 2 <= r * r + 1e-9) offs.push([di, dj]);
  const pass = (src: ArrayLike<number>, pick: (a: number, b: number) => number, edge: number) => {
    const out = new Float32Array(w * h);
    for (let j = 0; j < h; j++)
      for (let i = 0; i < w; i++) {
        let m = src[j * w + i];
        for (const [di, dj] of offs) {
          const x = i + di, y = j + dj;
          m = pick(m, x < 0 || y < 0 || x >= w || y >= h ? edge : src[y * w + x]);
        }
        out[j * w + i] = m;
      }
    return out;
  };
  // outside the crop counts as 0 for the erosion and is ignored by the dilation
  return pass(pass(data, Math.min, 0), Math.max, 0);
}

export function makeCollect(lib: any) {
  const CS = lib.CS;
  const M = lib.M;
  const part: PartFn = lib.part;
  const values = (): Record<string, number | string> => lib.inputs.values ?? {};

  /** Letters the stroke font has (Cyrillic and Kazakh included); anything else would print as '#'. */
  const printable = (s: string) =>
    [...String(s ?? '').toUpperCase()]
      .filter((ch) => ch === ' ' || GLYPHS[ch])
      .join('')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, NAME_CHARS);

  function layout(key: string, opts: StickerOptions): Layout {
    const o = { ...STICKER_DEFAULTS, ...Object.fromEntries(Object.entries(opts).filter(([, v]) => v !== undefined)) } as Layout['o'] & { name?: string };
    const loopsPx: V2[][] | undefined = lib.inputs.outlines?.[key];
    const hm = lib.inputs.heightmaps?.[key];
    lib.assert(loopsPx?.length && hm?.data?.length, `no relief for "${key}": attach inputs.outlines.${key} and inputs.heightmaps.${key} (vision/relief.py)`);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const l of loopsPx!) for (const [x, y] of l) [x0, y0, x1, y1] = [Math.min(x0, x), Math.min(y0, y), Math.max(x1, x), Math.max(y1, y)];
    const v = values();
    const crop = ['x0', 'y0', 'x1', 'y1'].map((c) => Number(v[`${key}_${c}`]));
    const [cx0, cy0, cx1, cy1] = crop.every(Number.isFinite) && crop[2] > crop[0] && crop[3] > crop[1] ? crop : [x0, y0, x1, y1];
    // photo pixels -> mm: the longest side becomes `size`, centred, y up
    const k = o.size / Math.max(x1 - x0, y1 - y0, 1e-6), cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const loops = loopsPx!.map((l) => l.map(([x, y]) => [(x - cx) * k, -(y - cy) * k] as V2));
    // miniature rules: thicken by 0.45 mm (nothing narrower than two lines is left) and fuse gaps under ~1.7 mm,
    // so thin legs and slats still print
    const cs: CrossSection = new CS(loops, 'EvenOdd').simplify(0.08).offset(0.85, 'Round').offset(-0.4, 'Round');
    lib.assert(!cs.isEmpty() && cs.area() > 4, `the outline of "${key}" is too small to print`);
    // the relief resampled on a 0.25 mm grid over the crop and opened there, so what the nozzle can draw does not
    // depend on the photo's resolution
    const cw = (cx1 - cx0) * k, ch = (cy1 - cy0) * k;
    const W = Math.max(2, Math.round(cw / GRID) + 1), Hn = Math.max(2, Math.round(ch / GRID) + 1);
    const fine = openRelief(resample(hm as Heightmap, W, Hn), W, Hn, cw / (W - 1), ch / (Hn - 1), Math.max(0.6, lib.printer.lineWidth * 1.4));
    // (x, y) in mm on the sticker -> relief 0..~1.3, bilinear on the fine grid
    const height = (x: number, y: number) => sample(fine, W, Hn, ((x / k + cx - cx0) / (cx1 - cx0)) * (W - 1), ((-y / k + cy - cy0) / (cy1 - cy0)) * (Hn - 1));
    const outer: CrossSection = cs.offset(o.border, 'Round');
    let base = outer;
    let text: CrossSection | null = null;
    const name = printable(opts.name ?? String(v[`${key}_name`] ?? ''));
    if (name) {
      const ob = outer.bounds();
      const width = ob.max[0] - ob.min[0];
      const size = Math.min(NAME_MAX, Math.max(NAME_MIN, (Math.max(30, width * 0.85) - 4) / (name.length * 0.92)));
      // strokes of at least two lines: thinner letters print as single, broken lines
      const t = lib.std.text2d(name, { size, stroke: Math.max(2 * lib.printer.lineWidth + 0.06, size * 0.17) });
      const tb = t.bounds();
      const tw = tb.max[0] - tb.min[0] + 5, th = size + 4;
      // the tab overlaps the rim by 2 mm, so base and tab print as one plate
      const ty = ob.min[1] - th / 2 + 2;
      base = outer.add(CS.square([tw, th], true).offset(-1.5, 'Round').offset(1.5, 'Round').translate([0, ty]));
      text = t.translate([0, ty]);
    }
    return { key, o, cs, base, text, height };
  }

  function solids(s: Layout, shift: V2 = [0, 0]) {
    const { o } = s;
    const relief: Manifold = lib.sdf
      .heightfield(s.cs, (x: number, y: number) => o.base + 0.6 + o.puff * s.height(x, y), { r: 0.4 })
      .mesh({ edge: o.edge });
    const out = [
      part(s.base.extrude(o.base).translate([shift[0], shift[1], 0]), { name: 'base', color: STICKER_COLORS.base }),
      part(relief.translate([shift[0], shift[1], 0]), { name: 'figure', color: STICKER_COLORS.figure }),
    ];
    if (s.text) out.push(part(s.text.extrude(0.8).translate([shift[0], shift[1], o.base]), { name: 'name', color: STICKER_COLORS.name }));
    return out;
  }

  /** One sticker: die-cut base, photo relief and a name tab. */
  const sticker = (key = 'subject', o: StickerOptions = {}) => solids(layout(key, o));

  /**
   * Every key on one bed, shelf-packed from the bed's corner (tallest first), one part per colour.
   * The packing works on the flat footprints, so a collection that does not fit fails before any meshing.
   */
  function plate(keys?: string[] | string, o: PlateOptions = {}) {
    const list = (Array.isArray(keys) ? keys : String(keys ?? values().keys ?? '').split(',')).map((k) => k.trim()).filter(Boolean);
    lib.assert(list.length, 'plate: no keys (pass them, or set inputs.values.keys = "a,b,c")');
    const bed: V2 = o.bed ?? [lib.printer.bed[0], lib.printer.bed[1]];
    const margin = o.margin ?? 8, gap = o.gap ?? 6;
    const items = list
      .map((key) => {
        const s = layout(key, { ...o, puff: o.puff ?? 3.5, edge: o.edge ?? 0.45, name: o.names?.[key] ?? o.name });
        const b = s.base.bounds();
        return { s, b, w: b.max[0] - b.min[0], h: b.max[1] - b.min[1] };
      })
      .sort((a, b) => b.h - a.h);
    const room: V2 = [bed[0] - 2 * margin, bed[1] - 2 * margin];
    let x = 0, y = 0, row = 0, used = 0;
    const at: V2[] = [];
    for (const it of items) {
      if (x > 0 && x + it.w > room[0]) [x, y, row] = [0, y + row + gap, 0];
      at.push([x - it.b.min[0], y - it.b.min[1]]);
      used = Math.max(used, x + it.w);
      x += it.w + gap;
      row = Math.max(row, it.h);
    }
    const need: V2 = [used, y + row];
    lib.assert(
      need[0] <= room[0] + 1e-6 && need[1] <= room[1] + 1e-6,
      `the collection does not fit one bed: ${list.length} stickers at ${o.size ?? STICKER_DEFAULTS.size} mm need ${need[0].toFixed(0)} x ${need[1].toFixed(0)} mm, ` +
        `the ${bed[0]} x ${bed[1]} mm bed leaves ${room[0]} x ${room[1]}; pick fewer or a smaller size`,
    );
    // centred on the bed, as the viewer and the 3MF place it
    const parts = items.flatMap((it, i) => solids(it.s, [at[i][0] - need[0] / 2, at[i][1] - need[1] / 2]));
    const by = new Map<string, typeof parts>();
    for (const q of parts) by.set(q.name, [...(by.get(q.name) ?? []), q]);
    return [...by.values()].map((qs) => part(qs.length > 1 ? M.union(qs.map((q) => q.solid)) : qs[0].solid, { name: qs[0].name, color: qs[0].color }));
  }

  return { sticker, plate, printable, colors: STICKER_COLORS };
}
