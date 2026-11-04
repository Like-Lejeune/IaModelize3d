// The side panels of a workspace: how wide each is and whether it is hidden, kept per workspace in this browser. A seam
// dragged resizes its panel; pulled well past the panel's smallest width the panel hides, and its seam stays on the
// screen's edge to pull it back from.

export type Side = 'left' | 'right';
type Panel = { width: number | null; hidden: boolean };

/** A shown panel is never narrower than this. */
export const MIN_PANEL = 240;
/** Asked to be narrower than this, a panel hides. */
const HIDE_BELOW = 100;
/** The editor between the panels keeps this much: a narrower window takes it from the panels. */
const MIN_CENTER = 460;

export class SideDock {
  left = $state<Panel>({ width: null, hidden: false });
  right = $state<Panel>({ width: null, hidden: false });
  viewport = $state(window.innerWidth);

  private key: string;
  private defaults: Record<Side, (viewport: number) => number>;

  private sized = $derived.by(() => {
    const wanted = (p: Panel, side: Side) => (p.hidden ? 0 : (p.width ?? this.defaults[side](this.viewport)));
    const l = wanted(this.left, 'left');
    const r = wanted(this.right, 'right');
    const over = l + r - (this.viewport - MIN_CENTER);
    const fit = (w: number) => (w && over > 0 ? Math.max(MIN_PANEL, Math.round(w - (over * w) / (l + r))) : w);
    return { left: fit(l), right: fit(r) };
  });

  constructor(name: string, defaults: Record<Side, (viewport: number) => number>) {
    this.key = `fw.dock.${name}`;
    this.defaults = defaults;
    try {
      const v = JSON.parse(localStorage.getItem(this.key) ?? 'null');
      for (const side of ['left', 'right'] as const) {
        if (typeof v?.[side]?.width === 'number') this[side].width = v[side].width;
        this[side].hidden = v?.[side]?.hidden === true;
      }
    } catch {
      /* storage off: the defaults stand */
    }
  }

  /** The panel's width as laid out now, 0 while hidden. */
  width(side: Side) {
    return this.sized[side];
  }

  /** The most a panel may take with the other one as it is. */
  max(side: Side) {
    return Math.max(MIN_PANEL, this.viewport - MIN_CENTER - this.sized[side === 'left' ? 'right' : 'left']);
  }

  /** One step of a drag begun at width `from`: a hidden panel comes back at its width from before it was pulled away. */
  drag(side: Side, wanted: number, from: number) {
    const p = this[side];
    if (wanted < HIDE_BELOW) {
      p.hidden = true;
      if (from) p.width = from;
      return;
    }
    p.hidden = false;
    p.width = Math.round(Math.max(MIN_PANEL, Math.min(wanted, this.max(side))));
  }

  show(side: Side) {
    this[side].hidden = false;
    this.save();
  }

  hide(side: Side) {
    this[side].hidden = true;
    this.save();
  }

  save() {
    try {
      localStorage.setItem(this.key, JSON.stringify({ left: this.left, right: this.right }));
    } catch {
      /* not kept */
    }
  }
}
