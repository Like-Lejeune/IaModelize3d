// A seamless tile of device line drawings (deviceGlyphs.json, from server/scripts/device_glyphs.py), scattered anew each time:
// staggered rows with some jitter, so it reads as loose drawings rather than a table, and no device beside itself.

export interface Glyph {
  device: string;
  view: string;
  w: number;
  h: number;
  d: string;
}

export const TILE = 1152; // px; COLS and ROWS are even, so the staggered rows meet themselves across the edge
const COLS = 10;
const ROWS = 14; // more rows than columns: the drawings are wider than tall, and a staggered row fits into the gaps of the last
const LONG_SIDE = 96; // px, a drawing's long side at scale 1
const STROKE = 1.05; // in a drawing's own units, 1 unit is about 1 px
const GREY = '#808080'; // the same in every theme: the layer's opacity mutes it

export function patternTile(glyphs: Glyph[], rnd: () => number = Math.random): string {
  const cellW = TILE / COLS;
  const cellH = TILE / ROWS;
  const between = (a: number, b: number) => a + (b - a) * rnd();
  const mod = (i: number, n: number) => (i + n) % n;
  const grid: Glyph[] = [];
  let deck: Glyph[] = [];

  // the neighbours already placed; the last row and column also meet the first across the tile's edge
  const taken = (col: number, row: number) => {
    const near = [[-1, 0], [0, -1], [-1, -1], [1, -1], ...(row === ROWS - 1 ? [[0, 1], [1, 1], [-1, 1]] : []), ...(col === COLS - 1 ? [[1, 0]] : [])];
    return new Set(near.map(([dc, dr]) => grid[mod(row + dr, ROWS) * COLS + mod(col + dc, COLS)]?.device));
  };
  // every drawing comes up about as often: a shuffled deck, dealt without a device next to itself
  const deal = (col: number, row: number) => {
    if (!deck.length) deck = [...glyphs].sort(() => rnd() - 0.5);
    const no = taken(col, row);
    const at = deck.findIndex((g) => !no.has(g.device));
    return deck.splice(Math.max(at, 0), 1)[0];
  };

  const used = new Map<Glyph, number>();
  const uses: string[] = [];
  for (let row = 0; row < ROWS; row++) {
    for (let col = 0; col < COLS; col++) {
      const g = deal(col, row);
      grid[row * COLS + col] = g;
      if (!used.has(g)) used.set(g, used.size);
      const s = (between(0.9, 1.04) * LONG_SIDE) / Math.max(g.w, g.h);
      const a = between(-6, 6);
      const cx = (col + 0.5 + (row % 2) / 2) * cellW + between(-4, 4);
      const cy = (row + 0.5) * cellH + between(-4, 4);
      const reach = (s * Math.hypot(g.w, g.h)) / 2;
      // a drawing over the edge comes in again on the other side
      for (const dx of [-TILE, 0, TILE]) {
        for (const dy of [-TILE, 0, TILE]) {
          const x = cx + dx;
          const y = cy + dy;
          if (x + reach < 0 || x - reach > TILE || y + reach < 0 || y - reach > TILE) continue;
          uses.push(
            `<use href="#g${used.get(g)}" transform="translate(${x.toFixed(1)} ${y.toFixed(1)})rotate(${a.toFixed(1)})scale(${s.toFixed(3)})translate(${-g.w / 2} ${-g.h / 2})"/>`,
          );
        }
      }
    }
  }
  const defs = [...used.keys()].map((g, i) => `<path id="g${i}" d="${g.d}"/>`).join('');
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${TILE}" height="${TILE}" viewBox="0 0 ${TILE} ${TILE}">` +
    `<defs>${defs}</defs>` +
    `<g fill="none" stroke="${GREY}" stroke-width="${STROKE}" stroke-linecap="round" stroke-linejoin="round">${uses.join('')}</g></svg>`
  );
}
