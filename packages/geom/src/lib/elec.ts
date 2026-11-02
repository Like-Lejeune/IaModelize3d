// Enclosures for electronics (lib.elec): a fw.board/1 JSON (board.schema.json) in, a snap-fit case out.
// One code path for dataset boards (boards.json), boards measured from a photo and PCBs from the PCB
// pipeline. A program gets its board only through inputs.boards.<name>; this library never reads the
// dataset. check_enclosure (../enclosure.ts) verifies what is built here against the same board model.
import type { CrossSection, Manifold, Wasm } from '../kernel.ts';
import { detail } from '../kernel.ts';
import type { PrinterProfile } from './index.ts';

type V2 = [number, number];
type V3 = [number, number, number];

// ---------------------------------------------------------------- fw.board/1
// Board frame: origin at the bottom-left corner of the PCB seen from the component side, x right,
// y up, z up from the PCB BOTTOM face, mm. Component heights are above the face they sit on.
export type BoardEdge = '+x' | '-x' | '+y' | '-y';
export type BoardAccess = 'port' | 'press' | 'light' | 'cable' | 'none';

export interface BoardComponent {
  id: string;
  type: string; // key of the dataset's `typical` table: usb_c, usb_micro_b, tact_6x6, led_0603, ...
  side: 'top' | 'bottom';
  access: BoardAccess;
  w: number; // along x; for a port, along its edge
  h: number; // body height above the face it sits on (from z0)
  d?: number; // along y; for a port, the body depth into the board from its front
  // ports (connectors on an edge)
  edge?: BoardEdge;
  at?: number; // centre along the edge (x for ±y edges, y for ±x edges)
  z0?: number; // bottom of the body above the face (also allowed for non-ports: modules on headers)
  protrude?: number; // how far the front sticks out past the edge (negative: set back)
  plug?: V2 | null; // cross-section of the mating plug's overmold [along the edge, height]
  plugR?: number; // corner radius of that overmold
  // everything else
  x?: number;
  y?: number;
  normal?: V3;
  src?: string;
  verify?: string[];
  uncertainty_mm?: number;
  note?: string;
  evidence?: Record<string, unknown>;
}

export interface BoardHole {
  x: number;
  y: number;
  d: number;
  plated?: boolean;
  use?: 'mount' | 'pin' | 'tooling'; // missing means mount
  src?: string;
  verify?: string[];
  uncertainty_mm?: number;
}

export interface BoardKeepout {
  id: string;
  rect: [number, number, number, number]; // x0, y0, x1, y1
  z?: number[]; // z range in the board frame (default: the whole column)
  rule: 'no_metal' | 'no_material' | 'airflow' | 'keep_open';
  src?: string;
  verify?: string[];
  note?: string;
}

export type BoardOutline = ({ kind: 'rect'; w: number; h: number; r?: number } | { kind: 'poly'; points: V2[]; w: number; h: number }) & {
  src?: string;
  verify?: string[];
};

export interface BoardSpec {
  schema: 'fw.board/1';
  id: string;
  name: string;
  aliases?: string[];
  source: {
    kind: 'dataset' | 'photo' | 'photo+dataset' | 'pcb';
    urls?: string[];
    asset_id?: string;
    selection_id?: string;
    dataset_id?: string;
    pcb_job?: string; // 'pcb:v{n}'
    checked?: string;
    calibration?: { method?: 'a4' | 'card' | 'board_holes'; residual_mm?: number; [k: string]: unknown };
  };
  sources?: Record<string, string>;
  frame?: string;
  uncertainty_mm?: number;
  pcb: { outline: BoardOutline; thickness: number; holes: BoardHole[]; [k: string]: unknown };
  components: BoardComponent[];
  keepouts?: BoardKeepout[];
  heights?: { top_max?: number; bottom_max?: number; [k: string]: unknown };
  mount?: { preferred?: string; screw?: string; [k: string]: unknown };
  [k: string]: unknown;
}

export interface Box3 {
  min: V3;
  max: V3;
}

// A component resolved into the board frame: its box, and for a port the mouth (centre of the
// connector front) and the outward normal of its edge.
export interface BoardPart extends BoardComponent {
  box: Box3;
  mouth: V3 | null;
  normal: V3;
  zFace: number;
}

export interface BoardModel {
  spec: BoardSpec;
  W: number;
  H: number;
  T: number;
  outline: CrossSection;
  comps: BoardPart[];
  holes: BoardHole[];
  mounts: BoardHole[]; // holes with use 'mount' (or none): what standoffs and pegs go through
  keepouts: BoardKeepout[];
  topMax: number;
  bottomMax: number;
}

export const EDGE_NORMAL: Record<BoardEdge, V3> = { '+x': [1, 0, 0], '-x': [-1, 0, 0], '+y': [0, 1, 0], '-y': [0, -1, 0] };
const YAW: Record<BoardEdge, number> = { '+x': 0, '+y': 90, '-x': 180, '-y': 270 };
const EPS = 0.01;
const ARC_SAG = 0.01; // mm a port window's corner chord may cut into its arc
// segments per 360 deg for an arc of radius r that sags at most ARC_SAG (coarser in preview builds)
const arcSegments = (r: number) => 4 * Math.max(2, Math.ceil(Math.PI / Math.acos(Math.max(0, 1 - (ARC_SAG * detail.factor) / r)) / 4));
const STRAIN_TAB = 0.018; // bending strain a press tongue is sized for when the program gives no tabLen
const LID_COLOR = '#e8965a';
export const BOARD_COLOR = '#4f8df7';

const isMount = (h: BoardHole) => (h.use ?? 'mount') === 'mount';
const tall = (c: BoardPart, min = 0.05) => c.box.max[2] - c.box.min[2] > min;

// Resolves every component into a box in the board frame and every port into a mouth point plus
// the outward normal of its edge. Plain kernel calls only, so the checks can rebuild it outside a program.
export function boardModel(wasm: Wasm, spec: BoardSpec): BoardModel {
  if (!spec || !spec.pcb || !spec.pcb.outline) throw new Error('board JSON needs pcb.outline (schema fw.board/1)');
  const CS = wasm.CrossSection;
  const o = spec.pcb.outline;
  const W = o.w, H = o.h, T = spec.pcb.thickness ?? 1.6;
  let outline: CrossSection;
  if (o.kind === 'poly') outline = new CS([o.points], 'NonZero');
  else {
    outline = CS.square([W, H], false);
    if (o.r && o.r > 0) outline = outline.offset(-o.r, 'Square').offset(o.r, 'Round');
  }
  const comps: BoardPart[] = (spec.components ?? []).map((c) => {
    const top = c.side !== 'bottom';
    const zFace = top ? T : 0;
    const lift = c.z0 ?? 0;
    let box: Box3;
    let mouth: V3 | null = null;
    let normal: V3 = c.normal ?? (top ? [0, 0, 1] : [0, 0, -1]);
    if (c.access === 'port' && c.edge) {
      normal = EDGE_NORMAL[c.edge];
      const z0 = top ? T + lift : -lift - c.h;
      const z1 = z0 + c.h;
      const outer = c.edge[1] === 'x' ? (c.edge[0] === '+' ? W : 0) : c.edge[0] === '+' ? H : 0;
      const sgn = c.edge[0] === '+' ? 1 : -1;
      const protrude = c.protrude ?? 0;
      const a0 = outer + sgn * protrude, a1 = outer + sgn * (protrude - (c.d ?? 0)); // along the normal axis
      const lo = Math.min(a0, a1), hi = Math.max(a0, a1);
      const at = c.at ?? 0;
      box = c.edge[1] === 'y'
        ? { min: [at - c.w / 2, lo, z0], max: [at + c.w / 2, hi, z1] }
        : { min: [lo, at - c.w / 2, z0], max: [hi, at + c.w / 2, z1] };
      const m: V3 = [(box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, (z0 + z1) / 2];
      if (c.edge[1] === 'y') m[1] = a0;
      else m[0] = a0;
      mouth = m;
    } else {
      const z0 = top ? T + lift : -lift - c.h, z1 = z0 + c.h;
      const x = c.x ?? 0, y = c.y ?? 0, d = c.d ?? c.w;
      box = { min: [x - c.w / 2, y - d / 2, z0], max: [x + c.w / 2, y + d / 2, z1] };
    }
    return { ...c, box, mouth, normal, zFace };
  });
  const topMax = Math.max(spec.heights?.top_max ?? 0, ...comps.filter((c) => c.side !== 'bottom').map((c) => c.box.max[2] - T));
  const bottomMax = Math.max(spec.heights?.bottom_max ?? 0, ...comps.filter((c) => c.side === 'bottom').map((c) => -c.box.min[2]));
  const holes = spec.pcb.holes ?? [];
  return { spec, W, H, T, outline, comps, holes, mounts: holes.filter(isMount), keepouts: spec.keepouts ?? [], topMax, bottomMax };
}

// Solid stand-in of the board (PCB with its holes plus the component boxes), in the board frame.
export function boardGhost(wasm: Wasm, b: BoardModel, o: { bottomPins?: boolean } = {}): Manifold {
  const M = wasm.Manifold;
  let pcb = b.outline.extrude(b.T);
  if (b.holes.length) pcb = pcb.subtract(M.union(b.holes.map((h) => M.cylinder(b.T + 2, h.d / 2, h.d / 2, 24).translate([h.x, h.y, -1]))));
  const boxes = b.comps.filter((c) => tall(c)).map((c) => M.cube([c.box.max[0] - c.box.min[0], c.box.max[1] - c.box.min[1], c.box.max[2] - c.box.min[2]]).translate(c.box.min));
  if (o.bottomPins && b.bottomMax > 0) {
    // header pins under the board, as one slab over the outline (worst case for collisions)
    boxes.push(b.outline.extrude(b.bottomMax).translate([0, 0, -b.bottomMax]));
  }
  return M.union([pcb, ...boxes]);
}

export interface EnclosureOptions {
  wall?: number;
  floor?: number;
  lid?: number;
  clear?: number; // gap between the board (and its parts) and the inner walls
  topGap?: number; // gap above the tallest part
  fit?: number; // sliding fit of the lid in the walls (per side)
  portFit?: number; // gap around a plug in its window
  chamfer?: number; // outside chamfer of port windows
  standoff?: number; // space under the board (at least bottomMax + 0.6)
  mount?: 'peg' | 'auto' | 'screw'; // pegs never put metal near antennas; auto uses screws outside no_metal keep-outs
  screw?: string;
  lights?: 'hole' | 'skin';
  lightD?: number;
  buttons?: 'flex' | 'none';
  lidStyle?: 'hooks' | 'plain';
  hookL?: number;
  hookT?: number;
  hookOver?: number;
  hookW?: number;
  tabLen?: number;
  pressGap?: number; // plunger gap over a button
  r?: number; // outer corner radius
  clips?: 'edge' | 'none'; // edge clips from the lid for a board without mount holes
}

export interface EnclosureReport {
  zBoard: number;
  zTop: number;
  lidT: number;
  standoff: number;
  inner: { x0: number; y0: number; x1: number; y1: number };
  outerSize: [number, number, number];
  features: Record<string, any>[];
}

export interface Enclosure {
  base: Manifold;
  lid: Manifold;
  at: (p: V3) => V3;
  report: EnclosureReport;
  posts: { x: number; y: number; r: number; kind: string; near: number }[];
  hooks: { side: BoardEdge; along: number }[];
  clips: { edge: BoardEdge; at: V2; fence: boolean }[];
  ports: { id: string; w: number; h: number; plugReach: number }[];
  zBoard: number;
  zTop: number;
  lidT: number;
  inner: { x0: number; y0: number; x1: number; y1: number };
  wall: number;
  board: BoardModel;
}

type PartFn = (solid: Manifold, o?: { name?: string; color?: string; role?: string; settings?: Record<string, unknown>; meta?: Record<string, unknown> }) => unknown;

export function makeElec(wasm: Wasm, std: any, printer: PrinterProfile, part: PartFn) {
  const { Manifold: M, CrossSection: CS } = wasm;

  const board = (spec: BoardSpec): BoardModel => boardModel(wasm, spec);
  const ghost = (b: BoardModel, o: { bottomPins?: boolean } = {}): Manifold => boardGhost(wasm, b, o);

  // ---------------------------------------------------------------- features
  // Rounded-rect window through a wall along +X (built in YZ), with an outside chamfer. Its corner arcs
  // get enough segments for a chord to sag at most ARC_SAG inside the true arc: at the global 0.5 mm
  // edge length a 0.9 mm corner has 3 segments a quarter and takes 0.03 mm off a 0.3 mm port fit.
  function portCutter(w: number, h: number, depthIn: number, depthOut: number, o: { r?: number; chamfer?: number } = {}): Manifold {
    const r = Math.min(o.r ?? 0.8, w / 2 - 0.01, h / 2 - 0.01);
    const c = o.chamfer ?? 0.6;
    const sec = (dw: number) => {
      const rr = r + dw;
      const cs = CS.square([h + 2 * dw, w + 2 * dw], true); // cs x = -z, cs y = across
      return rr > 0 ? cs.offset(-rr, 'Square').offset(rr, 'Round', 2, dw ? 0 : arcSegments(rr)) : cs; // the flare never limits the plug
    };
    const parts: Manifold[] = [sec(0).extrude(depthIn + depthOut + 1).translate([0, 0, -depthIn])];
    // flare: narrow at depthOut - c (inside the wall), full chamfer width at the outer face, then 1 mm past it
    if (c > 0) parts.push(std.extrude(sec(c), c + 1, { chamferBottom: c }).translate([0, 0, depthOut - c]));
    // rotate so local Z (extrusion) points along +X
    return M.union(parts).rotate([0, 90, 0]);
  }
  const yawTo = (s: Manifold, edge: BoardEdge) => s.rotate([0, 0, YAW[edge]]);

  // Cantilever tongue cut into a lid plate (lid underside at z = 0, plate up to +t) with a plunger
  // hanging down `plunger` mm at the free end.
  function flexTab(o: { at: V2; t: number; len?: number; width?: number; slot?: number; plunger: number; plungerD?: number; dir?: '+y' | '-y' | '+x' | '-x' }) {
    const L = o.len ?? 10, w = o.width ?? 5, g = o.slot ?? 0.8, t = o.t;
    // tongue along +Y in local frame, root at y = L, free end at y = 0, plunger centred at y = 1.6
    const slot = M.union([
      M.cube([g, L + g, t + 2]).translate([-w / 2 - g, -g, -1]),
      M.cube([g, L + g, t + 2]).translate([w / 2, -g, -1]),
      M.cube([w + 2 * g, g, t + 2]).translate([-w / 2 - g, -g, -1]),
    ]);
    const pd = o.plungerD ?? 2.6;
    const plunger = M.cylinder(o.plunger + EPS, pd / 2, pd / 2, 24).translate([0, 1.6, -o.plunger]);
    const dir = o.dir ?? '+y';
    const rot = { '+y': 0, '-x': 90, '-y': 180, '+x': 270 }[dir];
    const place = (s: Manifold) => s.translate([0, -1.6, 0]).rotate([0, 0, rot]).translate([o.at[0], o.at[1], 0]);
    return { cut: place(slot), add: place(plunger), len: L, width: w, dir };
  }

  // ---------------------------------------------------------------- enclosure
  function enclosure(b: BoardModel, o: EnclosureOptions = {}): Enclosure {
    const wall = o.wall ?? 2.0, floor = o.floor ?? 1.6, lidT = o.lid ?? 1.6;
    const clear = o.clear ?? 0.5, topGap = o.topGap ?? 1.2, fit = o.fit ?? std.fit('slide') / 2;
    // grooves and window chamfers leave at least two lines of wall (0.9 mm on a 0.4 nozzle), or it prints as thin_wall
    const wallMin = Math.max(0.9, 2 * printer.lineWidth + 0.06);
    const portFit = o.portFit ?? 0.3, chamfer = Math.min(o.chamfer ?? 0.6, Math.max(0, wall - wallMin));
    const standoff = Math.max(o.standoff ?? 2.5, b.bottomMax + 0.6);
    // snap hooks hang beside the board on the two long sides: reserve a band for them
    const hook = { t: o.hookT ?? 1.0, over: o.hookOver ?? 0.4, width: o.hookW ?? 6, lead: 0.6 };
    const band = o.lidStyle === 'plain' ? 0 : hook.t + hook.over + fit + 0.4;
    const longX = b.H >= b.W; // long sides are the ±x sides when the board is tall
    const pad = { x: clear + (longX ? band : 0), y: clear + (longX ? 0 : band) };
    const body = b.comps.filter((c) => c.access !== 'port').reduce(
      (a, c) => ({ x0: Math.min(a.x0, c.box.min[0]), y0: Math.min(a.y0, c.box.min[1]), x1: Math.max(a.x1, c.box.max[0]), y1: Math.max(a.y1, c.box.max[1]) }),
      { x0: 0, y0: 0, x1: b.W, y1: b.H },
    );
    const inner = { x0: body.x0 - pad.x, y0: body.y0 - pad.y, x1: body.x1 + pad.x, y1: body.y1 + pad.y };
    const zBoard = floor + standoff; // PCB bottom in enclosure coords
    const zTop = zBoard + b.T + b.topMax + topGap; // lid underside = top of the walls
    const r = o.r ?? 2.5;
    const innerCS: CrossSection = std.rect(inner.x1 - inner.x0, inner.y1 - inner.y0, { r: Math.max(0.3, r - wall), center: false }).translate([inner.x0, inner.y0]);
    const outerCS = innerCS.offset(wall, 'Round');
    const at = (p: V3): V3 => [p[0], p[1], p[2] + zBoard]; // board frame -> enclosure frame
    const report: EnclosureReport = { zBoard, zTop, lidT, standoff, inner, outerSize: [0, 0, 0], features: [] };

    // --- base: tray with floor and walls
    let base: Manifold = std.extrude(outerCS, zTop, { chamferBottom: 0.4 }).subtract(innerCS.extrude(zTop + 1).translate([0, 0, floor]));

    // --- mounting: standoffs; pegs where metal is not allowed (antenna keep-outs) or when asked
    const inKeepout = (x: number, y: number, rule?: string) =>
      b.keepouts.some((k) => (!rule || k.rule === rule) && x >= k.rect[0] && x <= k.rect[2] && y >= k.rect[1] && y <= k.rect[3]);
    const posts: Enclosure['posts'] = [];
    const tops = b.comps.filter((c) => c.side !== 'bottom' && tall(c, 0.3));
    for (const h of b.mounts) {
      const metalOk = !inKeepout(h.x, h.y, 'no_metal');
      const kind = o.mount === 'screw' || o.mount === 'auto' ? (metalOk ? 'screw' : 'peg') : 'peg';
      // nearest component (plan view) limits the hold-down post radius
      const near = Math.min(...tops.map((c) => Math.hypot(Math.max(c.box.min[0] - h.x, 0, h.x - c.box.max[0]), Math.max(c.box.min[1] - h.y, 0, h.y - c.box.max[1]))), 99);
      const sd = Math.min(h.d + 2.4, 4.6);
      let s = M.cylinder(standoff + EPS, sd / 2, sd / 2, 32).translate([h.x, h.y, floor - EPS]);
      if (kind === 'screw') {
        s = s.subtract(std.tapHole(o.screw ?? 'M2', standoff - 0.4, { at: [h.x, h.y, floor + standoff + EPS] }));
      } else {
        const pd = h.d - 0.3; // printed peg, flush with the board top
        s = s.add(M.cylinder(b.T - 0.1, pd / 2, pd / 2 - 0.15, 24).translate([h.x, h.y, floor + standoff]));
      }
      base = base.add(s);
      // the post must not run into the wall either (it hangs from the lid, `fit` inside the walls)
      const toWall = Math.min(h.x - inner.x0, inner.x1 - h.x, h.y - inner.y0, inner.y1 - h.y) - fit;
      const postR = Math.max(0.9, Math.min(1.8, near - 0.3, toWall));
      posts.push({ x: h.x, y: h.y, r: postR, kind, near: +near.toFixed(2) });
      report.features.push({ type: 'mount', at: [h.x, h.y], kind, d: h.d, standoffD: sd, postD: +(2 * postR).toFixed(2), metalOk });
    }

    if (!b.mounts.length) {
      // no holes: ledges under the short ends, and hold-down posts over them where the top side is free
      const shortY = b.H >= b.W; // short ends are the ±y ends of a tall board
      const span = (shortY ? b.W : b.H) * 0.6, deep = 3.0;
      const freeOf = (x0: number, y0: number, x1: number, y1: number) =>
        !tops.some((c) => c.box.min[0] < x1 + 0.3 && c.box.max[0] > x0 - 0.3 && c.box.min[1] < y1 + 0.3 && c.box.max[1] > y0 - 0.3);
      for (const end of [0, 1]) {
        const r0 = shortY
          ? [(b.W - span) / 2, end ? b.H - deep : 0, (b.W + span) / 2, end ? b.H : deep]
          : [end ? b.W - deep : 0, (b.H - span) / 2, end ? b.W : deep, (b.H + span) / 2];
        base = base.add(M.cube([r0[2] - r0[0], r0[3] - r0[1], standoff + EPS]).translate([r0[0], r0[1], floor - EPS]));
        const cx = (r0[0] + r0[2]) / 2, cy = (r0[1] + r0[3]) / 2;
        const pr = 1.2;
        const spot = ([[cx, cy], [r0[0] + pr, cy], [r0[2] - pr, cy], [cx, r0[1] + pr], [cx, r0[3] - pr]] as V2[]).find(([x, y]) => freeOf(x - pr, y - pr, x + pr, y + pr));
        if (spot) posts.push({ x: spot[0], y: spot[1], r: pr, kind: 'ledge', near: 0 });
        report.features.push({ type: 'mount', kind: 'ledge', rect: r0.map((v) => +v.toFixed(2)), holdDown: !!spot, ...(spot ? { post: spot.map((v) => +v.toFixed(2)) } : {}) });
      }
    }

    // --- lid: plate + hold-down posts + light windows (the flex buttons come after the snap hooks)
    let lid: Manifold = std.extrude(outerCS, lidT, { chamferTop: 0.4 }).translate([0, 0, zTop]);
    const lidAdds: Manifold[] = [], lidCuts: Manifold[] = [];
    for (const p of posts) {
      const len = zTop - (zBoard + b.T + 0.1);
      lidAdds.push(M.cylinder(len + EPS, p.r, p.r, 24).translate([p.x, p.y, zTop - len]));
    }
    const keepClear: number[][] = []; // plan rects [x0, y0, x1, y1] of lid features the edge clips stay off
    for (const c of b.comps.filter((c) => c.access === 'light' && c.side !== 'bottom')) {
      const cx = (c.box.min[0] + c.box.max[0]) / 2, cy = (c.box.min[1] + c.box.max[1]) / 2;
      if (o.lights === 'skin') lidCuts.push(M.cylinder(lidT - 0.4 + EPS, 1.8, 1.8, 24).translate([cx, cy, zTop - EPS]));
      else lidCuts.push(std.holeZ(o.lightD ?? 2.0, lidT, { at: [cx, cy, zTop + lidT], through: true }));
      const lr = o.lights === 'skin' ? 1.8 : (o.lightD ?? 2.0) / 2;
      keepClear.push([cx - lr, cy - lr, cx + lr, cy + lr]);
      report.features.push({ type: 'light', for: c.id, mode: o.lights === 'skin' ? 'skin 0.4' : `hole ${o.lightD ?? 2.0}` });
    }

    // --- snap hooks (mech.snapHook) on the long sides, grooves in the walls
    const hooks: Enclosure['hooks'] = [], hookPlan: number[][] = [];
    if (o.lidStyle !== 'plain') {
      const Lh = Math.min(o.hookL ?? 6, zTop - floor - 1.2);
      // the groove leaves wallMin behind it: on a thin wall it is shallower, and the bump shrinks to stay
      // 0.1 mm off the groove floor (catch = over - fit)
      const gd = Math.max(0.1, Math.min(hook.over + 0.3, wall - wallMin));
      const over = Math.min(hook.over, gd + fit - 0.1);
      const strain = (1.5 * hook.t * over) / (Lh * Lh);
      const n = (longX ? b.H : b.W) > 40 ? 2 : 1;
      // spans of the port windows on each edge (plus margin): hooks must not land there
      const spans = b.comps.filter((c) => c.access === 'port' && c.mouth).map((c) => {
        const plug = c.plug ?? [c.w, c.h];
        const half = Math.max(plug[0], c.w) / 2 + portFit + hook.width / 2 + 2;
        const across = c.edge![1] === 'x' ? c.mouth![1] : c.mouth![0];
        return { edge: c.edge, a0: across - half, a1: across + half };
      });
      // the tip is blunted to two lines (a knife edge prints as a too_thin sliver); the groove starts above it
      const tipMin = 2 * printer.lineWidth;
      const tipCut = Lh + hook.lead * (1 - Math.min(tipMin, 0.6 * (hook.t + over)) / (hook.t + over));
      for (const side of (longX ? ['+x', '-x'] : ['+y', '-y']) as BoardEdge[]) {
        const lo = side[1] === 'x' ? inner.y0 : inner.x0, hi = side[1] === 'x' ? inner.y1 : inner.x1;
        const ideal = Array.from({ length: n }, (_, i) => (n === 1 ? 0.5 : (i + 1) / (n + 1)));
        const cands: number[] = [];
        for (let f = 0.15; f <= 0.851; f += 0.025) cands.push(+f.toFixed(3));
        const free = (f: number) => {
          const a = lo + (hi - lo) * f;
          return !spans.some((s) => s.edge === side && a > s.a0 && a < s.a1);
        };
        const chosen: number[] = [];
        for (const want of ideal) {
          const pick = cands
            .filter((f) => free(f) && chosen.every((g) => Math.abs(g - f) * (hi - lo) > hook.width + 4))
            .sort((p, q) => Math.abs(p - want) - Math.abs(q - want))[0];
          if (pick !== undefined) chosen.push(pick);
        }
        if (chosen.length < n) report.features.push({ type: 'warning', text: `only ${chosen.length} of ${n} snap hooks fit on the ${side} wall between port windows` });
        for (const along of chosen) {
          // hook built hanging down from z = 0, bump towards +X, then turned to face `side`
          let hk: Manifold = std.snapHook({ length: Lh, thickness: hook.t, width: hook.width, overhang: over, lead: hook.lead, tipMin }).rotate([0, 90, 0]);
          // the bump sticks out between the blunted tip and z = -(Lh - 0.6 * over) (catch face).
          // Groove roof at 45 deg: no overhang in the base print, and the lid stays removable
          const gz0 = -(tipCut + 0.25), gz1 = -(Lh - 0.6 * over) + 0.15;
          const sec: CrossSection = std.poly([[0, gz0], [gd, gz0], [gd, gz1], [0, gz1 + gd]]); // XZ section, x into the wall
          let groove = sec.extrude(hook.width + 0.8).rotate([90, 0, 0]).translate([0, (hook.width + 0.8) / 2, 0]);
          // local x = 0 is the hook's inner face; its outer face at x = t sits `fit` inside the wall
          const wallIn = side[1] === 'x' ? (side[0] === '+' ? inner.x1 : -inner.x0) : side[0] === '+' ? inner.y1 : -inner.y0;
          hk = hk.translate([wallIn - fit - hook.t, 0, 0]);
          groove = groove.translate([wallIn - 0.01, 0, 0]);
          const shift: V3 = side[1] === 'x' ? [0, inner.y0 + (inner.y1 - inner.y0) * along, zTop] : [inner.x0 + (inner.x1 - inner.x0) * along, 0, zTop];
          const place = (s: Manifold) => s.rotate([0, 0, YAW[side]]).translate(shift);
          lidAdds.push(place(hk));
          base = base.subtract(place(groove));
          hooks.push({ side, along: +along.toFixed(2) });
          // the hook in plan, with room for it to flex inward going over the wall
          const ac = side[1] === 'x' ? shift[1] : shift[0], hw = hook.width / 2, deep = fit + hook.t + 2 * hook.over;
          const plan = side[1] === 'x'
            ? (side[0] === '+' ? [inner.x1 - deep, ac - hw, inner.x1, ac + hw] : [inner.x0, ac - hw, inner.x0 + deep, ac + hw])
            : (side[0] === '+' ? [ac - hw, inner.y1 - deep, ac + hw, inner.y1] : [ac - hw, inner.y0, ac + hw, inner.y0 + deep]);
          keepClear.push(plan);
          hookPlan.push(plan);
        }
      }
      if (hooks.length && gd < hook.over + 0.3 && over - fit < 0.15)
        report.features.push({ type: 'warning', text: `the ${wall} mm wall leaves the snap hooks a ${(over - fit).toFixed(2)} mm catch: use a wall of ${(Math.ceil((wallMin + 0.25) * 10 - 1e-9) / 10).toFixed(1)} mm or more, or lidStyle 'plain'` });
      report.features.push({ type: 'snap_hooks', count: hooks.length, length: +Lh.toFixed(2), thickness: hook.t, overhang: +over.toFixed(3), groove: +gd.toFixed(3), fit, strain: +strain.toFixed(4) });
    }

    // --- flex buttons: a press tongue cut into the lid over each top button, kept off the posts and hooks
    const presses = b.comps.filter((c) => c.access === 'press' && c.side !== 'bottom' && (c.normal?.[2] ?? 1) > 0.5);
    const DIR = { '+y': [0, 1], '-y': [0, -1], '+x': [1, 0], '-x': [-1, 0] } as const;
    const overlaps = (r: number[], q: number[]) => r[0] < q[2] && r[2] > q[0] && r[1] < q[3] && r[3] > q[1];
    for (const c of o.buttons === 'none' ? [] : presses) {
      const cx = (c.box.min[0] + c.box.max[0]) / 2, cy = (c.box.min[1] + c.box.max[1]) / 2;
      const gap = o.pressGap ?? 0.3, travel = 0.25, tw = 5;
      const plunger = zTop - (zBoard + c.box.max[2] + gap);
      // the tongue is as thick as the lid: without a tabLen it is long enough (10 mm at least) to bend gap + travel
      // at 1.8 % strain, under the ~2 % PLA limit check_enclosure holds it to, for any lid
      const L = o.tabLen ?? Math.max(10, Math.ceil(Math.sqrt((1.5 * lidT * (gap + travel)) / STRAIN_TAB) * 10 - 1e-9) / 10);
      // the tongue with its slots in plan: from 1.6 + slot behind the plunger to the root, width + 2 slots across
      const tongue = (d: keyof typeof DIR) => {
        const v = DIR[d], a0 = -1.6 - 0.8, a1 = L - 1.6, hw = tw / 2 + 0.8;
        return v[0]
          ? [cx + Math.min(v[0] * a0, v[0] * a1), cy - hw, cx + Math.max(v[0] * a0, v[0] * a1), cy + hw]
          : [cx - hw, cy + Math.min(v[1] * a0, v[1] * a1), cx + hw, cy + Math.max(v[1] * a0, v[1] * a1)];
      };
      // pick the tongue direction with the most room inside the lid that keeps clear of posts and hooks
      const dirs = (['+y', '-y', '+x', '-x'] as const).map((d) => {
        const v = DIR[d];
        const ex = cx + v[0] * (L - 1.6), ey = cy + v[1] * (L - 1.6);
        const inside = ex > inner.x0 + 1 && ex < inner.x1 - 1 && ey > inner.y0 + 1 && ey < inner.y1 - 1;
        const postHit = posts.some((p) => {
          // distance from post centre to the tongue segment (plus slot) in plan
          const t = Math.max(0, Math.min(1, ((p.x - cx) * v[0] + (p.y - cy) * v[1] + 1.6) / L));
          const qx = cx + v[0] * (t * L - 1.6), qy = cy + v[1] * (t * L - 1.6);
          return Math.hypot(p.x - qx, p.y - qy) < p.r + 2.5 + 0.8;
        });
        // a slot over a hook's root (or the room it flexes in) would cut into it: the longer tongues of a thick lid
        // reach the hook band on a narrow board (the Nano's from lid 2.6)
        const hookHit = hookPlan.some((q) => overlaps(tongue(d), q));
        return { d, ok: inside && !postHit && !hookHit, score: (inside ? 3 : 0) + (postHit ? 0 : 1) + (hookHit ? 0 : 1) };
      }).sort((a, z) => z.score - a.score);
      // only parts that reach into the plunger zone limit its diameter
      const others = b.comps.filter((d) => d !== c && d.side !== 'bottom' && d.box.max[2] > c.box.max[2] + 0.05);
      const room = Math.min(...others.map((d) => Math.hypot(Math.max(d.box.min[0] - cx, 0, cx - d.box.max[0]), Math.max(d.box.min[1] - cy, 0, cy - d.box.max[1]))), 99);
      const plungerD = Math.max(1.2, Math.min(2.6, 2 * (room - 0.4)));
      const tab = flexTab({ at: [cx, cy], t: lidT, len: L, width: tw, dir: dirs[0].d, plunger, plungerD });
      lidCuts.push(tab.cut.translate([0, 0, zTop]));
      lidAdds.push(tab.add.translate([0, 0, zTop]));
      keepClear.push(tongue(tab.dir));
      const strain = (1.5 * lidT * (gap + travel)) / (L * L);
      report.features.push({ type: 'flex_button', for: c.id, at: [cx, cy], dir: tab.dir, len: L, width: tab.width, plunger: +plunger.toFixed(2), plungerD: +plungerD.toFixed(2), gap, strain: +strain.toFixed(4), clearOfPosts: dirs[0].ok });
    }
    if (o.buttons === 'none' && presses.length) report.features.push({ type: 'buttons_off', for: presses.map((c) => c.id) });

    // A port window runs in from the outer wall face to 2 mm past the inner one, and at least portFit past
    // the receptacle mouth: the hook band and a wide clear can leave the board farther than that from the
    // wall, and a plug taller than the room under the lid needs its notch in the lid edge all the way in.
    const portDepth = (c: BoardPart) => {
      const sg = c.edge![0] === '+' ? 1 : -1, ax = c.edge![1] === 'x' ? 0 : 1;
      const wallOuter = sg * (sg > 0 ? (ax ? inner.y1 : inner.x1) : ax ? inner.y0 : inner.x0) + wall; // along the normal
      const reach = Math.max(0, wallOuter - sg * c.mouth![ax]); // how deep the plug body enters the window
      return { wallOuter, reach, depth: Math.max(wall + 2, reach + portFit) };
    };

    // --- edge clips for a board without mount holes: L-shaped tabs hanging from the lid. A lip over the
    // PCB rim holds the board down on its ledges; where there is room beside the board (the hook band),
    // a fence reaches down past the PCB edge so it cannot slide across. They keep off the parts, holes,
    // hooks, press tongues, light holes and port windows; check_enclosure (board_retained) verifies them.
    const clips: Enclosure['clips'] = [];
    if (!b.mounts.length && o.clips !== 'none') {
      const cw = 3, gapF = 0.25, ch = 0.6, margin = 0.3;
      const zL = zBoard + b.T + 0.1, zF = Math.max(zBoard - 1.0, floor + 0.3), zT = zTop + EPS; // lip underside, fence bottom, into the lid
      for (const c of b.comps.filter((c) => c.access === 'port' && c.mouth)) {
        // the window cutter goes into the case past the inner wall face (portDepth), and through the lid
        const plug = c.plug ?? [c.w, c.h];
        const half = (Math.max(plug[0], c.w) + 2 * portFit) / 2 + chamfer, ac = c.edge![1] === 'x' ? c.mouth![1] : c.mouth![0];
        const e = c.edge!, wi = e[1] === 'x' ? (e[0] === '+' ? inner.x1 : inner.x0) : e[0] === '+' ? inner.y1 : inner.y0;
        const inward = portDepth(c).depth - wall + 0.5;
        const d0 = wi - (e[0] === '+' ? inward : -inward);
        keepClear.push(e[1] === 'x' ? [Math.min(wi, d0), ac - half, Math.max(wi, d0), ac + half] : [ac - half, Math.min(wi, d0), ac + half, Math.max(wi, d0)]);
      }
      const keepouts = b.keepouts.filter((k) => k.rule === 'no_material' || k.rule === 'keep_open').map((k) => k.rect);
      const hit = (r: number[], q: number[], m = 0) => r[0] < q[2] + m && r[2] > q[0] - m && r[1] < q[3] + m && r[3] > q[1] - m;
      const boxOf = (c: BoardPart) => [c.box.min[0], c.box.min[1], c.box.max[0], c.box.max[1]];
      const tops = b.comps.filter((c) => c.side !== 'bottom' && tall(c)), bottoms = b.comps.filter((c) => c.side === 'bottom' && c.box.max[2] > -1.0);
      for (const edge of ['-x', '+x', '-y', '+y'] as BoardEdge[]) {
        const sg = edge[0] === '+' ? 1 : -1, onX = edge[1] === 'x';
        const e = sg > 0 ? (onX ? b.W : b.H) : 0, len = onX ? b.H : b.W;
        const room = onX ? (sg > 0 ? inner.x1 - b.W : -inner.x0) : sg > 0 ? inner.y1 - b.H : -inner.y0;
        const out = Math.min(room - fit - 0.1, 2.2); // past the board edge, short of the wall
        const fence = out - gapF >= 1.0 ? out - gapF : 0;
        // plan rect from `a0..a1` across the edge (outward from it) and `s0..s1` along it
        const rect = (a0: number, a1: number, s0: number, s1: number) => {
          const c0 = e + sg * a0, c1 = e + sg * a1;
          return onX ? [Math.min(c0, c1), s0, Math.max(c0, c1), s1] : [s0, Math.min(c0, c1), s1, Math.max(c0, c1)];
        };
        const fits = (s: number, lipIn: number) => {
          const r = rect(-lipIn, out, s - cw / 2, s + cw / 2);
          if (tops.some((c) => hit(r, boxOf(c), margin)) || b.holes.some((h) => hit(r, [h.x - h.d / 2, h.y - h.d / 2, h.x + h.d / 2, h.y + h.d / 2], margin))) return false;
          if (fence && bottoms.some((c) => hit(rect(gapF, out, s - cw / 2, s + cw / 2), boxOf(c), margin))) return false;
          if (keepClear.some((q) => hit(r, q, 0.5)) || keepouts.some((q) => hit(r, q))) return false;
          // the lip must lie on the PCB, not on air past a rounded corner or a notch
          const lr = rect(-lipIn, 0, s - cw / 2, s + cw / 2);
          return CS.square([lr[2] - lr[0], lr[3] - lr[1]]).translate([lr[0], lr[1]]).intersect(b.outline).area() >= 0.8 * lipIn * cw;
        };
        // two clips per edge near its quarters (one in the middle of a short edge), as far as there is room;
        // a 0.6 mm lip where a 0.8 mm one finds fewer spots (a part close to the rim)
        const targets = len >= 2 * cw + 8 ? [0.25, 0.75] : [0.5];
        const place = (lipIn: number) => {
          const free: number[] = [];
          for (let s = cw / 2; s <= len - cw / 2 + 1e-9; s += 0.25) if (fits(s, lipIn)) free.push(s);
          const chosen: number[] = [];
          for (const f of targets) {
            const pick = free.filter((s) => chosen.every((t) => Math.abs(t - s) >= cw + 3)).sort((p, q) => Math.abs(p - f * len) - Math.abs(q - f * len))[0];
            if (pick !== undefined) chosen.push(pick);
          }
          return { lipIn, chosen };
        };
        let best = place(Math.max(0.8, 1.0 - out)); // at least 1 mm thick in all
        if (best.chosen.length < targets.length) {
          const thin = place(Math.max(0.6, 1.0 - out));
          if (thin.chosen.length > best.chosen.length) best = thin;
        }
        const { lipIn, chosen } = best;
        // section across the edge (x outward from it, y = z): the lip, and the fence with a lead-in chamfer
        const sec: CrossSection = std.poly(fence
          ? [[-lipIn, zL], [gapF, zL], [gapF, zF + ch], [gapF + ch, zF], [out, zF], [out, zT], [-lipIn, zT]]
          : [[-lipIn, zL], [out, zL], [out, zT], [-lipIn, zT]]);
        for (const s of chosen) {
          const clip = sec.extrude(cw).rotate([90, 0, 0]).translate([0, cw / 2, 0]).rotate([0, 0, YAW[edge]]);
          lidAdds.push(clip.translate(onX ? [e, s, 0] : [s, e, 0]));
          const mid = e - (sg * lipIn) / 2; // the lip's centre line on the PCB
          const at: V2 = onX ? [mid, s] : [s, mid];
          const press = [s - cw / 2 + 0.4, s + cw / 2 - 0.4].map((a) => (onX ? [mid, a] : [a, mid]).map((v) => +v.toFixed(2)));
          clips.push({ edge, at: [+at[0].toFixed(2), +at[1].toFixed(2)], fence: fence > 0 });
          report.features.push({ type: 'clip', edge, at: [+at[0].toFixed(2), +at[1].toFixed(2)], press, w: cw, lip: +lipIn.toFixed(2), fence: +fence.toFixed(2), gap: gapF });
        }
      }
    }
    if (lidAdds.length) lid = lid.add(M.union(lidAdds));
    if (lidCuts.length) lid = lid.subtract(M.union(lidCuts));

    // --- port windows through walls (and the lid edge when the window reaches it)
    const ports: Enclosure['ports'] = [];
    for (const c of b.comps.filter((c) => c.access === 'port' && c.mouth)) {
      const edge = c.edge!;
      const plug = c.plug ?? [c.w, c.h];
      const w = Math.max(plug[0], c.w) + 2 * portFit, h = Math.max(plug[1], c.h) + 2 * portFit;
      const mouth = at(c.mouth!);
      const { wallOuter, reach, depth } = portDepth(c);
      // window corners follow the plug's rounded overmold, inflated by the same fit...
      const inset = Math.min((w - c.w) / 2, (h - c.h) / 2); // receptacle corner inset from the window sides
      // ...but stay small enough to keep >= 0.2 mm at the receptacle's own corners
      const rBox = (Math.SQRT2 * inset - 0.2) / (Math.SQRT2 - 1);
      const wr = Math.max(0.2, Math.min(c.plug ? (c.plugR ?? 0.6) + portFit : portFit, rBox));
      // a window that stops less than two layers under the lid top (the Zero 2 W's mini-HDMI by 0.10 mm) would leave a
      // skin a slicer drops or prints as one loose layer: it runs up through the lid top instead, with the same sides
      // and bottom corners. A window that ends at the lid top (the Picos' USB) or above it stays as it is.
      const skin = zTop + lidT - (mouth[2] + h / 2);
      const open = skin > EPS && skin < 2 * printer.layer - 1e-6;
      const z0 = mouth[2] - h / 2, hc = open ? zTop + lidT + 1 - z0 : h;
      let cut = portCutter(w, hc, depth, 0, { chamfer, r: Math.min(wr, w / 2 - 0.01, h / 2 - 0.01) }).translate([wallOuter, 0, 0]);
      const across = edge[1] === 'x' ? mouth[1] : mouth[0], zc = open ? z0 + hc / 2 : mouth[2];
      cut = yawTo(cut, edge).translate(edge[1] === 'x' ? [0, across, zc] : [across, 0, zc]);
      base = base.subtract(cut);
      lid = lid.subtract(cut);
      ports.push({ id: c.id, w: +w.toFixed(2), h: +h.toFixed(2), plugReach: +reach.toFixed(2) });
      report.features.push({ type: 'port_window', for: c.id, edge, w: +w.toFixed(2), h: +h.toFixed(2), r: +wr.toFixed(3), plugReachMm: +reach.toFixed(2), chamfer, ...(open ? { openedSkin: +skin.toFixed(2) } : {}) });
    }
    const bb = base.boundingBox();
    report.outerSize = [+(bb.max[0] - bb.min[0]).toFixed(2), +(bb.max[1] - bb.min[1]).toFixed(2), +(zTop + lidT).toFixed(2)];
    return { base, lid, at, report, posts, hooks, clips, ports, zBoard, zTop, lidT, inner, wall, board: b };
  }

  // Lid flipped next to the base, both resting on z = 0 (print layout).
  function printLayout(enc: Enclosure, gap = 6) {
    const bb = enc.base.boundingBox();
    const lid = enc.lid.rotate([180, 0, 0]);
    const lb = lid.boundingBox();
    return { base: enc.base, lid: lid.translate([bb.max[0] + gap - lb.min[0], bb.min[1] - lb.min[1], -lb.min[2]]) };
  }

  // The parts a case program returns: the print layout (what gets sliced and exported), or the
  // assembled case with the board ghost as a 'reference' part (never printed, drawn translucent),
  // which is what check_enclosure (inspect op 'enclosure') and close-up renders look at.
  function parts(enc: Enclosure, o: { layout?: 'print' | 'assembled'; ghost?: boolean; bottomPins?: boolean; lidColor?: string } = {}) {
    const lidColor = o.lidColor ?? LID_COLOR;
    if ((o.layout ?? 'print') !== 'assembled') {
      const L = printLayout(enc);
      return [part(L.base, { name: 'base' }), part(L.lid, { name: 'lid', color: lidColor })];
    }
    const out = [part(enc.base, { name: 'base' }), part(enc.lid, { name: 'lid', color: lidColor })];
    if (o.ghost) {
      const g = ghost(enc.board, { bottomPins: o.bottomPins }).translate([0, 0, enc.zBoard]);
      out.push(part(g, { name: 'board', role: 'reference', color: BOARD_COLOR, meta: { board: enc.board.spec.id, bottomPins: !!o.bottomPins, enclosure: enc.report } }));
    }
    return out;
  }

  // Printed stand-in for a PCB that is not made yet: a plate (1.6 mm) with the board's outline and its
  // mount and pin holes, so a real module (XIAO on headers) and the case can be tried before fabrication.
  function pcbPlate(b: BoardModel, o: { thickness?: number; holes?: ('mount' | 'pin' | 'tooling')[] } = {}): Manifold {
    const t = o.thickness ?? 1.6;
    const use = o.holes ?? ['mount', 'pin'];
    const cuts = b.holes.filter((h) => use.includes(h.use ?? 'mount')).map((h) => std.holeZ(h.d, t, { at: [h.x, h.y, t], through: true }) as Manifold);
    const plate = b.outline.extrude(t);
    return cuts.length ? plate.subtract(M.union(cuts)) : plate;
  }

  return { board, ghost, enclosure, portCutter, flexTab, printLayout, parts, pcbPlate };
}
