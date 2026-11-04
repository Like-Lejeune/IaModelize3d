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
// what a part needs from the case: port (a wall window), press (a flex tongue), light / sensor / display (a lid opening),
// sound (a lid grille), key (a mechanical key switch: a plate it clips into, a printed keycap), cable (an antenna lead or the
// like, nothing built yet) or none
export type BoardAccess = 'port' | 'press' | 'light' | 'sensor' | 'display' | 'sound' | 'key' | 'cable' | 'none';
// a key switch, mm above the PCB's top face: where the plate's top goes, the stem's top at rest; the plate's cut-out, the
// travel, the keycap's plan and which stem it plugs onto
// stem 'panel': held by the lid in a round hole of `cut` (an arcade button, a foot switch); 'shaft': an encoder's or a potentiometer's
// shaft through a hole, shaft_top above the PCB, a printed knob on it
export interface KeySwitch { plate_top?: number; plate_t?: number; cut: number; travel?: number; stem_top?: number; stem: 'mx' | 'choc' | 'panel' | 'shaft'; cap: [number, number]; depth?: number; shaft_d?: number; shaft_top?: number; knob?: boolean }

export interface BoardComponent {
  key?: KeySwitch;
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
  // light / sensor / display / sound: the lid opening over it [w along x, d along y] (default w x d + 0.6; a sound grille
  // fills w x d) and its shape (round for a TO-5 PIR or a round buzzer)
  window?: V2;
  shape?: 'rect' | 'round';
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

// A ready-made module the fab does not solder (device accessories, server/formwright/accessories.py): on a header over
// the board (mount 'board': an OLED), out of the case on a cable (a probe: a wall exit at edge/at) or loose in the case
// (mount 'inside': a LiPo cell, placed by the case beside or under the board). Board frame, mm.
export interface BoardAccessory {
  id: string;
  key?: string;
  name?: string;
  kind?: 'display' | 'sensor' | 'probe' | 'battery' | 'module';
  mount: 'board' | 'cable' | 'inside';
  x?: number; // centre of the body (mount board)
  y?: number;
  w?: number; // body along x, along y, height
  d?: number;
  h?: number;
  z0?: number; // bottom of the body above the PCB top face (mount board; default 0)
  window?: V2; // what must stay visible (a display's glass) [w, d], centred window_dx/dy off the body centre
  window_dx?: number;
  window_dy?: number;
  shape?: 'rect' | 'round';
  holes?: ({ x: number; y: number; d: number } | number[])[];
  edge?: BoardEdge; // mount cable: the wall the cable leaves through, and where along it
  at?: number;
  cable_d?: number;
  note?: string;
}

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
  accessories?: BoardAccessory[];
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

// An accessory resolved: its kind and mount filled in, and a box in the board frame for one on the board.
export interface BoardAcc extends BoardAccessory {
  kind: NonNullable<BoardAccessory['kind']>;
  box: Box3 | null;
}

export interface BoardModel {
  spec: BoardSpec;
  W: number;
  H: number;
  T: number;
  outline: CrossSection;
  comps: BoardPart[];
  accs: BoardAcc[];
  holes: BoardHole[];
  mounts: BoardHole[]; // holes with use 'mount' (or none): what standoffs and pegs go through
  keepouts: BoardKeepout[];
  topMax: number; // of the components (the accessories on the board have their own boxes)
  bottomMax: number;
}

export const EDGE_NORMAL: Record<BoardEdge, V3> = { '+x': [1, 0, 0], '-x': [-1, 0, 0], '+y': [0, 1, 0], '-y': [0, -1, 0] };
const YAW: Record<BoardEdge, number> = { '+x': 0, '+y': 90, '-x': 180, '-y': 270 };
const EPS = 0.01;
const ARC_SAG = 0.01; // mm a port window's corner chord may cut into its arc
// segments per 360 deg for an arc of radius r that sags at most ARC_SAG (coarser in preview builds)
const arcSegments = (r: number) => 4 * Math.max(2, Math.ceil(Math.PI / Math.acos(Math.max(0, 1 - (ARC_SAG * detail.factor) / r)) / 4));
const KEYCAP_COLOR = '#e8e6df';
const STRAIN_TAB = 0.018; // bending strain a press tongue is sized for when the program gives no tabLen
const LED_SMALL = 2.2; // a light part this narrow or less (0603/0805, a row of them) keeps the round lightD hole
const TIE_SLOT = 2.8, TIE_PLATE = 1.6, TIE_SIDE = 2.4; // cable tie block: zip-tie slot (2.5 mm ties), plate behind it, bore walls
const CELL_GAP = 0.3, RIB_T = 1.2; // a cell's room in its ribs, and the rib thickness (two lines and more)
// the round plan forms: how far a side may grow for rounder corners (soft, round), and the largest soft outer corner
const FORM_GROW = 0.6, FORM_GROW_ROUND = 3.0, FORM_SOFT_R = 14;
// a snap hook may hang on a corner's arc (revolved round it) from this inner radius, at most HOOK_ARC_TURN off the wall's
// normal; a port window or cable exit may sit where the arc has curved in at most ARC_DEV over its width
const HOOK_ARC_R = 12, HOOK_ARC_TURN = 50, ARC_DEV = 1.2;
// stance 'tilt' / 'upright': the printed stand the case leans in (degrees from the desk, its lip, plate and the gap to the case)
const STAND_ANGLE = { tilt: 25, upright: 75 } as const, STAND_LIP = 5, STAND_T = 2.4, STAND_GAP = 0.15;
const STAND_COLOR = '#b9bec6';
const LID_COLOR = '#e8965a';
export const BOARD_COLOR = '#4f8df7';
const CELL_COLOR = '#9aa0a6';

const isMount = (h: BoardHole) => (h.use ?? 'mount') === 'mount';
const tall = (c: BoardPart, min = 0.05) => c.box.max[2] - c.box.min[2] > min;
// The module stacked over a top part (an LED or a button under an OLED on its header): nothing in the lid reaches it.
export const coveredBy = (b: BoardModel, c: BoardPart) =>
  c.side === 'bottom' ? undefined : b.accs.find((a) => a.box && a.box.min[2] >= c.box.max[2] - 0.05
    && c.box.min[0] < a.box.max[0] - 0.2 && c.box.max[0] > a.box.min[0] + 0.2 && c.box.min[1] < a.box.max[1] - 0.2 && c.box.max[1] > a.box.min[1] + 0.2);

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
  // accessories: a module on the board gets its box (z0 above the PCB top face); a cable one its wall (the nearest to
  // its x, y, else -y) and a place along it; the case decides where a loose one ('inside') goes
  const accs: BoardAcc[] = (spec.accessories ?? []).map((a) => {
    const mount = a.mount ?? 'board';
    const kind = a.kind ?? (mount === 'inside' ? 'battery' : mount === 'cable' ? 'probe' : a.window ? 'display' : 'module');
    let box: Box3 | null = null;
    if (mount === 'board' && (a.w ?? 0) > 0 && (a.d ?? 0) > 0) {
      const x = a.x ?? W / 2, y = a.y ?? H / 2, z0 = T + Math.max(0, a.z0 ?? 0);
      box = { min: [x - a.w! / 2, y - a.d! / 2, z0], max: [x + a.w! / 2, y + a.d! / 2, z0 + Math.max(0, a.h ?? 0)] };
    }
    let edge = a.edge, at = a.at;
    if (mount === 'cable' && !(edge && EDGE_NORMAL[edge])) {
      const x = a.x ?? W / 2, y = a.y ?? 0;
      edge = ([['-x', x], ['+x', W - x], ['-y', y], ['+y', H - y]] as [BoardEdge, number][]).sort((p, q) => p[1] - q[1])[0][0];
      at = undefined;
    }
    if (mount === 'cable') at = at ?? (edge![1] === 'x' ? a.y ?? H / 2 : a.x ?? W / 2);
    return { ...a, mount, kind, box, ...(mount === 'cable' ? { edge, at } : {}) };
  });
  return { spec, W, H, T, outline, comps, accs, holes, mounts: holes.filter(isMount), keepouts: spec.keepouts ?? [], topMax, bottomMax };
}

type Plan = { x0: number; y0: number; x1: number; y1: number };
// How far a plan point lies inside the rounded rectangle q with corner radius r (negative: outside it).
const insideBy = (q: Plan, r: number, x: number, y: number) => {
  const dx = Math.abs(x - (q.x0 + q.x1) / 2) - ((q.x1 - q.x0) / 2 - r), dy = Math.abs(y - (q.y0 + q.y1) / 2) - ((q.y1 - q.y0) / 2 - r);
  return r - Math.hypot(Math.max(dx, 0), Math.max(dy, 0)) - Math.min(Math.max(dx, dy), 0);
};
// How far a wall of a rounded rectangle (the straight run lo + r .. hi - r, corners of radius r) has curved in at `a` along it.
const arcDev = (a: number, lo: number, hi: number, r: number) => {
  const t = Math.max(0, lo + r - a, a - (hi - r));
  return t >= r ? Infinity : r - Math.sqrt(r * r - t * t);
};

const boxSolid = (M: Wasm['Manifold'], q: Box3) => M.cube([q.max[0] - q.min[0], q.max[1] - q.min[1], q.max[2] - q.min[2]]).translate(q.min);

// Solid stand-in of the board (PCB with its holes plus the component boxes and the modules on it), in the board frame.
export function boardGhost(wasm: Wasm, b: BoardModel, o: { bottomPins?: boolean } = {}): Manifold {
  const M = wasm.Manifold;
  let pcb = b.outline.extrude(b.T);
  if (b.holes.length) pcb = pcb.subtract(M.union(b.holes.map((h) => M.cylinder(b.T + 2, h.d / 2, h.d / 2, 24).translate([h.x, h.y, -1]))));
  const boxes = b.comps.filter((c) => tall(c)).map((c) => boxSolid(M, c.box));
  for (const a of b.accs) if (a.box && a.box.max[2] - a.box.min[2] > 0.05) boxes.push(boxSolid(M, a.box));
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
  r?: number; // outer corner radius (form 'box')
  form?: 'box' | 'soft' | 'round'; // plan shape: small corners, corners as round as the parts allow, or a pebble
  clips?: 'edge' | 'none'; // edge clips from the lid for a board without mount holes
  windowFit?: number; // per side of a sensor/display/light window past its part (or a display's glass)
  grilleD?: number; // sound grille holes and their pitch
  grillePitch?: number;
  displayGap?: number; // lid (or its rim) over a display module's top
  battery?: 'auto' | 'under' | 'beside'; // where a loose cell goes; auto: whichever case is smaller
  cableRelief?: 'tie' | 'none'; // a zip-tie block inside each cable exit
  // how the device is held where it is used: flat features on the bed side of the base (it still prints floor-down
  // without supports), on walls free of port windows and cable exits. 'ears': two screw ears on opposite walls (a wall
  // plate); 'strap': two slotted ears for a strap or band; 'lanyard': an eyelet for a keyring or cord; 'stake': a spike
  // to push into soil (the device stands on it); 'magnets': pockets under the floor for disc magnets (a fridge); 'contacts':
  // two screw holes through the floor (screw heads as feet, e.g. the probes of a leak puck)
  mounting?: 'none' | 'ears' | 'strap' | 'lanyard' | 'stake' | 'magnets' | 'contacts';
  mountEdge?: 'auto' | BoardEdge; // the wall for ears/strap (its axis), a lanyard or a stake
  stakeLen?: number; // mm past the wall
  magnetD?: number; // disc magnet diameter and thickness
  magnetT?: number;
  minHeight?: number; // outer height at least this (a cube, a tower)
  // how it sits in use (report.pose): 'tilt' and 'upright' (without a stake) get a printed stand it leans in, lid to the
  // user, standing on a wall free of ports (mountEdge, else -y for a display, else the longest); 'wall' without a
  // mounting gets screw ears; 'desk' and 'hand' build nothing
  stance?: 'auto' | 'desk' | 'tilt' | 'upright' | 'wall' | 'hand';
}

export interface EnclosureReport {
  zBoard: number;
  zTop: number;
  lidT: number;
  standoff: number;
  inner: { x0: number; y0: number; x1: number; y1: number };
  outerSize: [number, number, number];
  features: Record<string, any>[];
  // how it sits in use; edge: the wall its mounting is on (a stake points down from it) or it stands on in its stand
  pose?: { stance: string; edge?: BoardEdge; angle?: number };
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
  cells: { id: string; box: Box3 }[]; // loose accessories (a LiPo) where the case put them, board frame
  // the printed stand of a tilt or upright stance: lying as printed, and where it is under the case (case frame)
  stand: { print: Manifold; placed: Manifold } | null;
  // printed keycaps, each lying as printed (its top on the bed), and where it sits on its switch (case frame)
  keycaps: { id: string; print: Manifold; placed: Manifold }[];
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

  // ---------------------------------------------------------------- mounting features
  // Flat shapes on the bed side of the base (z from 0), built in a wall's local frame: x outward from the outer face,
  // y along the wall. They start 0.3 mm inside the wall and never reach the cavity; port windows are cut after them.
  function mountFeatures(kind: string, c: { inner: { x0: number; y0: number; x1: number; y1: number }; wall: number; ri: number; floor: number;
    portEdges: Set<BoardEdge>; cables: BoardAcc[]; cellsAt: { x: number; y: number; w: number; d: number }[]; b: BoardModel; o: EnclosureOptions; magnetD: number; magnetT: number }) {
    const { inner, wall, ri, floor, b, o } = c;
    const adds: Manifold[] = [], cuts: Manifold[] = [];
    const note: Record<string, any> = { type: 'mounting', kind };
    let edge: BoardEdge | null = null;
    if (kind === 'none') return { adds, cuts, note, edge };
    const X0 = inner.x0 - wall, X1 = inner.x1 + wall, Y0 = inner.y0 - wall, Y1 = inner.y1 + wall, RO = ri + wall;
    const EDGES: BoardEdge[] = ['-y', '+y', '-x', '+x'];
    const busy = (e: BoardEdge) => c.portEdges.has(e) || c.cables.some((a) => a.edge === e);
    const run = (e: BoardEdge) => (e[1] === 'x' ? Y1 - Y0 : X1 - X0) - 2 * RO; // the straight run of a wall
    // the width a flat tab can take on a wall: its straight run, or on a round wall the chord where it curves in 2 mm
    const span = (e: BoardEdge) => Math.max(run(e), 2 * Math.sqrt(Math.max(0, RO * RO - (RO - 2) ** 2)));
    // how far in the outer face has curved at w/2 off the middle of a wall
    const bend = (e: BoardEdge, w: number) => {
      const t = w / 2 - Math.max(0, run(e)) / 2;
      return t <= 0 ? 0 : t >= RO ? RO : RO - Math.sqrt(RO * RO - t * t);
    };
    const mid = (e: BoardEdge) => (e[1] === 'x' ? (Y0 + Y1) / 2 : (X0 + X1) / 2);
    const opp = (e: BoardEdge) => ((e[0] === '+' ? '-' : '+') + e[1]) as BoardEdge;
    const free = EDGES.filter((e) => !busy(e) && span(e) > 8);
    const want = o.mountEdge && o.mountEdge !== 'auto' ? o.mountEdge : null;
    const T = 3.0; // tab thickness from the bed
    // a tab reaches into a curved wall as far as it bends away, and never into the cavity (0.3 mm of wall stays)
    const cavity = std.rect(inner.x1 - inner.x0 + 0.6, inner.y1 - inner.y0 + 0.6, { r: ri + 0.3, center: false }).translate([inner.x0 - 0.3, inner.y0 - 0.3]).extrude(T + 6).translate([0, 0, -1]);
    const place = (s: Manifold, e: BoardEdge, along: number) => {
      const rot = { '+x': 0, '+y': 90, '-x': 180, '-y': 270 }[e];
      const face = e === '+x' ? X1 : e === '-x' ? X0 : e === '+y' ? Y1 : Y0;
      return s.rotate([0, 0, rot]).translate((e[1] === 'x' ? [face, along, 0] : [along, face, 0]) as V3).subtract(cavity);
    };
    // a flat tab P mm out of the wall and w wide, its outer corners rounded r; clipped to start 0.3 mm inside the wall
    const tab = (e: BoardEdge, P: number, w: number, r: number, h = T) => {
      const ext = bend(e, w);
      const cs = CS.square([P + wall + ext + r, w]).translate([-(wall + ext + r), -w / 2]).offset(-r, 'Round').offset(r, 'Round', 2, 24);
      return cs.extrude(h).intersect(M.cube([P + wall + ext, w + 2, h + 2]).translate([-(wall + ext - 0.3), -w / 2 - 1, -1]));
    };
    const hole = (x: number, d: number, h = T) => M.cylinder(h + 2, d / 2, d / 2, 32).translate([x, 0, -1]);
    const slot = (x0: number, x1: number, len: number, h = T) =>
      CS.square([x1 - x0, len]).translate([x0, -len / 2]).offset(-0.99, 'Round').offset(0.99, 'Round', 2, 12).extrude(h + 2).translate([0, 0, -1]);
    if (kind === 'ears' || kind === 'strap') {
      // a pair of opposite free walls: the asked one's axis first, then the longer runs
      const axisFirst = (e: BoardEdge) => (want && want[1] === e[1] ? 0 : 1);
      const pairs = (['-y', '-x'] as BoardEdge[]).filter((e) => free.includes(e) && free.includes(opp(e))).sort((p, q) => axisFirst(p) - axisFirst(q) || span(q) - span(p));
      const e0 = pairs[0];
      if (!e0) { note.blocked = 'needs two opposite walls free of port windows and cable exits'; return { adds, cuts, note, edge }; }
      const strap = kind === 'strap', len = strap ? Math.min(26, span(e0) - 8) : 0;
      const w = strap ? len + 8 : Math.min(18, span(e0) - 1), P = strap ? 10 : 12;
      for (const e of [e0, opp(e0)]) {
        let s = tab(e, P, w, strap ? 3 : 5);
        // a countersunk hole for a 4 mm wood screw, or the strap slot
        s = strap ? s.subtract(slot(3, 7, len)) : s.subtract(hole(P - 6, 4.4)).subtract(M.cylinder(1.6, 2.2, 4.4, 32).translate([P - 6, 0, T - 1.6 + EPS]));
        adds.push(place(s, e, mid(e)));
      }
      edge = e0;
      Object.assign(note, { edges: [e0, opp(e0)], ...(strap ? { strapW: +len.toFixed(1) } : { screw: '4 mm wood screw, countersunk' }) });
    } else if (kind === 'lanyard' || kind === 'stake') {
      // one free wall: the asked one, else the shortest (a tag's end, a stake under the narrow side)
      const e = want && free.includes(want) ? want : [...free].sort((p, q) => span(p) - span(q))[0];
      if (!e) { note.blocked = 'needs a wall free of port windows and cable exits'; return { adds, cuts, note, edge }; }
      edge = e;
      if (kind === 'lanyard') {
        adds.push(place(tab(e, 8, Math.min(11, span(e) - 1), 4).subtract(hole(4.2, 3.6)), e, mid(e)));
        Object.assign(note, { edge: e, hole: 3.6 });
      } else {
        // a tapered blade with a rib along it; both lie on the bed
        const L = o.stakeLen ?? 70, w0 = Math.min(16, span(e) - 1), x0 = -(wall + bend(e, w0) - 0.3);
        const blade = new CS([[[x0, -w0 / 2], [L - 8, -2.2], [L, 0], [L - 8, 2.2], [x0, w0 / 2]]], 'Positive').extrude(T);
        const rib = new CS([[[x0, -1.2], [L * 0.75, -0.8], [L * 0.75, 0.8], [x0, 1.2]]], 'Positive').extrude(T + 2.5);
        adds.push(place(blade.add(rib), e, mid(e)));
        Object.assign(note, { edge: e, length: L, width: +w0.toFixed(1) });
      }
    } else if (kind === 'magnets' || kind === 'contacts') {
      // along the long axis of the floor, clear of the board's posts (and, for screws, of the cells)
      const longX = inner.x1 - inner.x0 >= inner.y1 - inner.y0, cx = (inner.x0 + inner.x1) / 2, cy = (inner.y0 + inner.y1) / 2;
      const span = (longX ? inner.x1 - inner.x0 : inner.y1 - inner.y0) / 2, cross = (longX ? inner.y1 - inner.y0 : inner.x1 - inner.x0) / 2;
      const d = kind === 'magnets' ? c.magnetD + 0.3 : 3.2;
      const four = kind === 'magnets' && span > 2.2 * d && cross > 2.2 * d;
      const offs: V2[] = four ? [[-1, -1], [1, -1], [-1, 1], [1, 1]] : [[-1, 0], [1, 0]];
      // inside the floor's rounded outline too (a soft or round case's corners)
      const clearOf = (x: number, y: number) => insideBy(inner, ri, x, y) >= d / 2 + 1.5 && b.mounts.every((m) => Math.hypot(m.x - x, m.y - y) > Math.min(m.d + 2.4, 4.6) / 2 + d / 2 + 0.6)
        && (kind === 'magnets' || c.cellsAt.every((q) => Math.abs(q.x - x) > q.w / 2 + d / 2 + 0.5 || Math.abs(q.y - y) > q.d / 2 + d / 2 + 0.5));
      const at: V2[] = [];
      for (const [u, v] of offs) {
        // from the far spot toward the centre until it is clear
        for (let k = 1; k >= 0.2; k -= 0.05) {
          const a = u * k * (span - d / 2 - 1.5), q = v * k * (cross - d / 2 - 1.5);
          const x = longX ? cx + a : cx + q, y = longX ? cy + q : cy + a;
          if (clearOf(x, y)) { at.push([x, y]); break; }
        }
      }
      if (at.length < 2) { note.blocked = 'no clear spots in the floor'; return { adds, cuts, note, edge }; }
      for (const [x, y] of at)
        cuts.push(kind === 'magnets' ? M.cylinder(c.magnetT + 0.2 + 1, d / 2, d / 2, 40).translate([x, y, -1]) : M.cylinder(floor + 2, d / 2, d / 2, 24).translate([x, y, -1]));
      Object.assign(note, { at: at.map(([x, y]) => [+x.toFixed(2), +y.toFixed(2)]), ...(kind === 'magnets' ? { magnet: [c.magnetD, c.magnetT], glue: true } : { screw: 'M3 x 6, head down' }) });
    }
    return { adds, cuts, note, edge };
  }

  // ---------------------------------------------------------------- enclosure
  function enclosure(b: BoardModel, o: EnclosureOptions = {}): Enclosure {
    const wall = o.wall ?? 2.0, lidT = o.lid ?? 1.6;
    // a case that lives on a wall needs something to hang by: screw ears when no mounting is named
    const mountKind = (o.mounting ?? 'none') === 'none' && o.stance === 'wall' ? 'ears' : o.mounting ?? 'none', magnetT = o.magnetT ?? 2, magnetD = o.magnetD ?? 10;
    // magnet pockets come up from below: the floor keeps 0.8 mm over them
    const floor = Math.max(o.floor ?? 1.6, mountKind === 'magnets' ? magnetT + 0.2 + 0.8 : 0);
    const clear = o.clear ?? 0.5, topGap = o.topGap ?? 1.2, fit = o.fit ?? std.fit('slide') / 2;
    // grooves and window chamfers leave at least two lines of wall (0.9 mm on a 0.4 nozzle), or it prints as thin_wall
    const wallMin = Math.max(0.9, 2 * printer.lineWidth + 0.06);
    const portFit = o.portFit ?? 0.3, chamfer = Math.min(o.chamfer ?? 0.6, Math.max(0, wall - wallMin));
    let standoff = Math.max(o.standoff ?? 2.5, b.bottomMax + 0.6);
    // snap hooks hang beside the board on the two long sides: reserve a band for them
    const hook = { t: o.hookT ?? 1.0, over: o.hookOver ?? 0.4, width: o.hookW ?? 6, lead: 0.6 };
    const band = o.lidStyle === 'plain' ? 0 : hook.t + hook.over + fit + 0.4;
    const longX = b.H >= b.W; // long sides are the ±x sides when the board is tall
    // a round PCB has no long side: the band goes all round, so the walls stay a circle (the hooks hang round its arcs)
    const disc = b.spec.pcb.outline.kind === 'poly' && Math.abs(b.W - b.H) < 0.5 && Math.abs(b.outline.area() - (Math.PI * b.W * b.H) / 4) < 0.03 * b.W * b.H;
    const pad = { x: clear + (longX || disc ? band : 0), y: clear + (longX && !disc ? 0 : band) };
    const onBoard = b.accs.filter((a) => a.box);
    const body = [...b.comps.filter((c) => c.access !== 'port').map((c) => c.box), ...onBoard.map((a) => a.box!)].reduce(
      (a, q) => ({ x0: Math.min(a.x0, q.min[0]), y0: Math.min(a.y0, q.min[1]), x1: Math.max(a.x1, q.max[0]), y1: Math.max(a.y1, q.max[1]) }),
      { x0: 0, y0: 0, x1: b.W, y1: b.H },
    );
    const inner = { x0: body.x0 - pad.x, y0: body.y0 - pad.y, x1: body.x1 + pad.x, y1: body.y1 + pad.y };
    const grow = (e: BoardEdge, by: number) => {
      if (by <= 0) return;
      if (e === '+x') inner.x1 += by;
      else if (e === '-x') inner.x0 -= by;
      else if (e === '+y') inner.y1 += by;
      else inner.y0 -= by;
    };
    const room = (e: BoardEdge) => (e === '+x' ? inner.x1 - body.x1 : e === '-x' ? body.x0 - inner.x0 : e === '+y' ? inner.y1 - body.y1 : body.y0 - inner.y0);
    const portEdges = new Set(b.comps.filter((c) => c.access === 'port' && c.edge).map((c) => c.edge!));
    const hookSide = (e: BoardEdge) => o.lidStyle !== 'plain' && (e[1] === 'x') === longX;

    // --- cable exits (probes, leads): the tie block inside each needs a bay between the wall and the board
    const cables = b.accs.filter((a) => a.mount === 'cable');
    const relief = o.cableRelief !== 'none', tieL = TIE_SLOT + TIE_PLATE;
    if (relief) for (const e of new Set(cables.map((a) => a.edge!))) grow(e, tieL + 0.5 - room(e));

    // --- loose accessories (a LiPo): under the board on taller standoffs, or in a bay beside it (never on a side with
    // ports or cable exits), whichever makes the smaller case; floor ribs keep it from sliding
    const shortY = b.H >= b.W; // short ends are the ±y ends of a tall board: ledges go there on a board without holes
    const ledges = b.mounts.length ? [] : [0, 1].map((end) => {
      const span = (shortY ? b.W : b.H) * 0.6, deep = 3.0;
      return shortY
        ? [(b.W - span) / 2, end ? b.H - deep : 0, (b.W + span) / 2, end ? b.H : deep]
        : [end ? b.W - deep : 0, (b.H - span) / 2, end ? b.W : deep, (b.H + span) / 2];
    });
    const accNeed = () => Math.max(0, ...onBoard.map((a) => a.box!.max[2] - b.T + (a.kind === 'display' ? o.displayGap ?? 0.2 : topGap)));
    const heightOver = (so: number) => floor + so + b.T + Math.max(b.topMax + topGap, accNeed()) + lidT; // outer height
    const volume = (q: typeof inner, hgt: number) => (q.x1 - q.x0 + 2 * wall) * (q.y1 - q.y0 + 2 * wall) * hgt;
    const ring = CELL_GAP + RIB_T;
    const ol = b.spec.pcb.outline;
    const shaped = ol.kind === 'poly' || (ol.r ?? 0) > 0;
    const pcbRing = b.outline.offset(clear, shaped ? 'Round' : 'Miter').toPolygons() as V2[][];
    const onPcb = (x: number, y: number) => {
      let wind = 0;
      for (const l of pcbRing)
        for (let i = 0; i < l.length; i++) {
          const [x0, y0] = l[i], [x1, y1] = l[(i + 1) % l.length], cross = (x1 - x0) * (y - y0) - (x - x0) * (y1 - y0);
          if (y0 <= y && y1 > y && cross > 0) wind++;
          else if (y0 > y && y1 <= y && cross < 0) wind--;
        }
      return wind !== 0;
    };
    const under: number[][] = []; // floor rects taken by cells under the board
    const cellsAt: { a: BoardAcc; x: number; y: number; w: number; d: number; h: number; place: 'under' | 'beside'; side?: BoardEdge }[] = [];
    for (const a of b.accs.filter((a) => a.mount === 'inside' && (a.w ?? 0) > 0 && (a.d ?? 0) > 0)) {
      const h = Math.max(0.5, a.h ?? 5);
      // under: the spot closest to the board centre (0.5 mm grid) clear of the standoffs, ledges and other cells, within
      // the board and its clear (the snap hooks hang in the band beside it, a tie block stands in a cable bay)
      const spot = (w: number, d: number): V2 | null => {
        const hw = w / 2 + ring, hd = d / 2 + ring;
        let best: V2 | null = null, bd = Infinity;
        for (let x = body.x0 - clear + hw; x <= body.x1 + clear - hw + 1e-9; x += 0.5)
          for (let y = body.y0 - clear + hd; y <= body.y1 + clear - hd + 1e-9; y += 0.5) {
            const q = [x - hw, y - hd, x + hw, y + hd];
            if (b.mounts.some((m) => Math.hypot(Math.max(q[0] - m.x, 0, m.x - q[2]), Math.max(q[1] - m.y, 0, m.y - q[3])) < Math.min(m.d + 2.4, 4.6) / 2 + 0.3)) continue;
            if ([...ledges, ...under].some((r) => q[0] < r[2] && q[2] > r[0] && q[1] < r[3] && q[3] > r[1])) continue;
            const dd = Math.hypot(x - b.W / 2, y - b.H / 2);
            // under a shaped PCB: inside its outline, as the walls will follow it
            if (dd < bd && (!shaped || [[q[0], q[1]], [q[2], q[1]], [q[2], q[3]], [q[0], q[3]]].every(([px, py]) => onPcb(px, py)))) [bd, best] = [dd, [x, y]];
          }
        return best;
      };
      const so = Math.max(standoff, b.bottomMax + h + 0.4); // the cell's top under the header pins, with room to spare
      type Opt = { place: 'under' | 'beside'; vol: number; w: number; d: number; x: number; y: number; side?: BoardEdge; so?: number; q?: typeof inner };
      const opts: Opt[] = [];
      for (const [w, d] of [[a.w!, a.d!], [a.d!, a.w!]]) {
        const s = spot(w, d);
        if (s) opts.push({ place: 'under', vol: volume(inner, heightOver(so)), w, d, x: s[0], y: s[1], so });
        for (const side of ['+x', '-x', '+y', '-y'] as BoardEdge[]) {
          if (portEdges.has(side) || cables.some((c) => c.edge === side)) continue;
          const onX = side[1] === 'x', sg = side[0] === '+' ? 1 : -1;
          const perp = (onX ? w : d) + 2 * ring + (hookSide(side) ? band : 0), along = (onX ? d : w) + 2 * ring;
          const q = { ...inner };
          if (onX) sg > 0 ? (q.x1 += perp) : (q.x0 -= perp);
          else sg > 0 ? (q.y1 += perp) : (q.y0 -= perp);
          const [lo, hi] = onX ? [q.y0, q.y1] : [q.x0, q.x1];
          const short = along - (hi - lo);
          if (short > 0) onX ? ((q.y0 -= short / 2), (q.y1 += short / 2)) : ((q.x0 -= short / 2), (q.x1 += short / 2));
          const mid = Math.max((onX ? q.y0 : q.x0) + along / 2, Math.min((onX ? q.y1 : q.x1) - along / 2, (onX ? b.H : b.W) / 2));
          const wallAt = onX ? (sg > 0 ? inner.x1 : inner.x0) : sg > 0 ? inner.y1 : inner.y0; // the old wall: the bay starts there
          const c = wallAt + sg * (ring + (onX ? w : d) / 2);
          opts.push({ place: 'beside', vol: volume(q, heightOver(standoff)), w, d, x: onX ? c : mid, y: onX ? mid : c, side, q });
        }
      }
      // a bay beside a shaped PCB would break the shape the case follows: under it when it can
      const want = o.battery ?? (shaped && opts.some((p) => p.place === 'under') ? 'under' : 'auto');
      const pick = opts.filter((p) => want === 'auto' || p.place === want).sort((p, q) => p.vol - q.vol)[0] ?? opts.sort((p, q) => p.vol - q.vol)[0];
      if (!pick) continue; // no side free of ports for a bay and no room under: battery_space reports it
      if (pick.place === 'under') {
        standoff = pick.so!;
        under.push([pick.x - pick.w / 2 - ring, pick.y - pick.d / 2 - ring, pick.x + pick.w / 2 + ring, pick.y + pick.d / 2 + ring]);
      } else Object.assign(inner, pick.q!);
      cellsAt.push({ a, x: pick.x, y: pick.y, w: pick.w, d: pick.d, h, place: pick.place, side: pick.side });
    }

    const zBoard = floor + standoff; // PCB bottom in enclosure coords
    // lid underside = top of the walls: over the tallest part, a module on the board (a display just under it, so the lid
    // holds it), a cell beside the board, and high enough for a cable exit over the board top and 1 mm under the lid joint
    const cableD = (a: BoardAcc) => Math.max(1, a.cable_d ?? 4) + 0.6;
    const zTop = Math.max(zBoard + b.T + Math.max(b.topMax + topGap, accNeed()), ...cellsAt.map((c) => floor + c.h + 1.0), ...cables.map((a) => zBoard + b.T + 0.3 + cableD(a) + 1.0),
      ...b.comps.filter((c) => c.access === 'key' && c.key?.plate_top != null).map((c) => zBoard + b.T + c.key!.plate_top! - lidT), // the plate is in the lid or under it
      (o.minHeight ?? 0) - lidT);
    // --- the plan shape. 'box': the classic small corners. 'soft': every corner as round as the parts inside allow, a side
    // growing at most FORM_GROW mm for it. 'round': a pebble, asking for half the short side, a side growing up to
    // FORM_GROW_ROUND mm (a port window is cut for the plug's whole overmold, so it still reaches; check_enclosure verifies
    // it). The port windows and cable exits keep to the straight runs of the walls or where a big arc has barely curved
    // in (ARC_DEV); the snap hooks to the straight runs, or round a big corner's arc.
    const form = o.form ?? 'box';
    let ri = Math.max(0.3, (o.r ?? 2.5) - wall); // inner corner radius (the outer one is ri + wall)
    const formNote: Record<string, any> = { type: 'form', form };
    // what the walls must keep `clear` off: the PCB's own outline (a shaped PCB, rounded, round or notched, lets the corners
    // come in further than its bounding box) and the boxes of the parts, modules and cells on and beside it
    const boxes = [...b.comps.filter((c) => c.access !== 'port').map((c) => [c.box.min[0], c.box.min[1], c.box.max[0], c.box.max[1]]),
      ...onBoard.map((a) => [a.box!.min[0], a.box!.min[1], a.box!.max[0], a.box!.max[1]]),
      ...cellsAt.map((c) => [c.x - c.w / 2 - ring, c.y - c.d / 2 - ring, c.x + c.w / 2 + ring, c.y + c.d / 2 + ring])]
      .map(([x0, y0, x1, y1]) => [[x0 - clear, y0 - clear], [x1 + clear, y0 - clear], [x1 + clear, y1 + clear], [x0 - clear, y1 + clear]] as V2[]);
    const pts = [...pcbRing.flat(), ...boxes.flat()];
    // the same outlines every 1.5 mm, for a hook on an arc whose room to flex must keep off them
    const dense = [...pcbRing, ...boxes].flatMap((l) => l.flatMap((p, i) => {
      const q = l[(i + 1) % l.length], k = Math.max(1, Math.ceil(Math.hypot(q[0] - p[0], q[1] - p[1]) / 1.5));
      return Array.from({ length: k }, (_, j) => [p[0] + ((q[0] - p[0]) * j) / k, p[1] + ((q[1] - p[1]) * j) / k] as V2);
    }));
    // A snap hook at `a` along a wall of the plan q (corners rr): on the straight run, or (form not 'box') round a corner
    // of HOOK_ARC_R and more, revolved about its centre C at angle th (deg), so its fit and catch stay as on a flat wall.
    // Its plan (with the room it flexes in) as a rect; null when it does not fit there.
    const hookDeep = fit + hook.t + 2 * hook.over;
    type HookAt = { plan: number[]; arc?: { C: V2; th: number } };
    const hookAt = (side: BoardEdge, a: number, q: Plan, rr: number): HookAt | null => {
      const onX = side[1] === 'x', lo = onX ? q.y0 : q.x0, hi = onX ? q.y1 : q.x1, hw = hook.width / 2;
      const wallN = side === '+x' ? q.x1 : side === '-x' ? q.x0 : side === '+y' ? q.y1 : q.y0, sg = side[0] === '+' ? 1 : -1;
      if (a - hw >= lo + rr + 0.3 && a + hw <= hi - rr - 0.3) {
        const n0 = Math.min(wallN, wallN - sg * hookDeep), n1 = Math.max(wallN, wallN - sg * hookDeep);
        return { plan: onX ? [n0, a - hw, n1, a + hw] : [a - hw, n0, a + hw, n1] };
      }
      if (form === 'box' || rr < HOOK_ARC_R) return null;
      const c = a < (lo + hi) / 2 ? lo + rr : hi - rr, s = (a - c) / rr;
      // wholly on the arc, and not too far round it
      if (Math.abs(a - c) < hw || Math.abs(s) > Math.sin((HOOK_ARC_TURN * Math.PI) / 180)) return null;
      const cn = wallN - sg * rr, C: V2 = onX ? [cn, c] : [c, cn];
      const k = Math.sqrt(1 - s * s), dir: V2 = onX ? [sg * k, s] : [s, sg * k];
      const th = Math.atan2(dir[1], dir[0]), dth = hook.width / rr / 2 + 0.6 / rr;
      // the board and its parts stay inside the radius the hook flexes in to
      for (const p of dense) {
        const dx = p[0] - C[0], dy = p[1] - C[1];
        let da = Math.atan2(dy, dx) - th;
        da = Math.atan2(Math.sin(da), Math.cos(da));
        if (Math.abs(da) <= dth && Math.hypot(dx, dy) > rr - hookDeep + 0.05) return null;
      }
      const ring2 = [-dth, 0, dth].flatMap((d) => [rr - hookDeep, rr].map((r) => [C[0] + r * Math.cos(th + d), C[1] + r * Math.sin(th + d)]));
      const xs = ring2.map((p) => p[0]), ys = ring2.map((p) => p[1]);
      return { plan: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)], arc: { C, th: (th * 180) / Math.PI } };
    };
    if (form !== 'box') {
      const EDGES: BoardEdge[] = ['+x', '-x', '+y', '-y'];
      const spansOn: Record<BoardEdge, V2[]> = { '+x': [], '-x': [], '+y': [], '-y': [] };
      for (const c of b.comps.filter((c) => c.access === 'port' && c.edge && c.mouth)) {
        const plug = c.plug ?? [c.w, c.h], half = Math.max(plug[0], c.w) / 2 + portFit + chamfer + 0.6;
        const a = c.edge![1] === 'x' ? c.mouth![1] : c.mouth![0];
        spansOn[c.edge!].push([a - half, a + half]);
      }
      for (const a of cables.filter((a) => a.edge && a.at != null)) spansOn[a.edge!].push([a.at! - cableD(a) / 2 - TIE_SIDE - 1.5, a.at! + cableD(a) / 2 + TIE_SIDE + 1.5]);
      // the outward growth each side needs for every point near a corner to sit inside that corner's arc of radius rr
      const need = (rr: number): Record<BoardEdge, number> => {
        const corner = (sx: number, sy: number) => {
          let g = 0;
          const ok = (dx: number, dy: number, gg: number) => Math.max(0, rr - dx - gg) ** 2 + Math.max(0, rr - dy - gg) ** 2 <= rr * rr + 1e-9;
          for (const [px, py] of pts) {
            const dx = sx < 0 ? px - inner.x0 : inner.x1 - px, dy = sy < 0 ? py - inner.y0 : inner.y1 - py;
            if (dx >= rr || dy >= rr || ok(dx, dy, g)) continue;
            let lo = g, hi = rr;
            for (let i = 0; i < 30; i++) { const m = (lo + hi) / 2; if (ok(dx, dy, m)) hi = m; else lo = m; }
            g = hi;
          }
          return g;
        };
        const bl = corner(-1, -1), br = corner(1, -1), tl = corner(-1, 1), tr = corner(1, 1);
        return { '-x': Math.max(bl, tl), '+x': Math.max(br, tr), '-y': Math.max(bl, br), '+y': Math.max(tl, tr) };
      };
      // a board held only by edge clips and ledges (no mount holes) is located by the walls: they must not move away
      const budget = !b.mounts.length ? 0 : form === 'round' ? FORM_GROW_ROUND : FORM_GROW;
      // where a snap hook may hang on a wall: off the port windows by what the hook code keeps (half a hook and 2 mm)
      const hookOff = (e: BoardEdge) => b.comps.filter((c) => c.access === 'port' && c.edge === e && c.mouth).map((c) => {
        const plug = c.plug ?? [c.w, c.h], half = Math.max(plug[0], c.w) / 2 + portFit + hook.width / 2 + 2;
        const a = e[1] === 'x' ? c.mouth![1] : c.mouth![0];
        return [a - half, a + half];
      });
      const fits = (rr: number) => {
        const gr = need(rr);
        if (EDGES.some((e) => gr[e] > budget + 1e-6)) return null;
        for (const e of EDGES) if (gr[e] < 1e-4) gr[e] = 0; // the search's last bit of slack, not a growth
        const q = { x0: inner.x0 - gr['-x'], x1: inner.x1 + gr['+x'], y0: inner.y0 - gr['-y'], y1: inner.y1 + gr['+y'] };
        for (const e of EDGES) {
          const [lo, hi] = e[1] === 'x' ? [q.y0, q.y1] : [q.x0, q.x1];
          if (spansOn[e].some(([a0, a1]) => (rr < HOOK_ARC_R ? a0 < lo + rr || a1 > hi - rr : Math.max(arcDev(a0, lo, hi, rr), arcDev(a1, lo, hi, rr)) > ARC_DEV))) return null;
          if (hookSide(e)) {
            // room for as many hooks as the side gets (two past 40 mm), on the straight run or a big arc and clear of the
            // port windows (the same grid of places and the same pick as the hook code below)
            const off = hookOff(e), nHooks = (longX ? b.H : b.W) > 40 ? 2 : 1;
            const cands: number[] = [];
            for (let f = 0.15; f <= 0.851; f += 0.025) {
              const a = lo + (hi - lo) * +f.toFixed(3);
              if (!off.some(([s0, s1]) => a > s0 && a < s1) && hookAt(e, a, q, rr)) cands.push(a);
            }
            const chosen: number[] = [];
            for (const want of Array.from({ length: nHooks }, (_, i) => lo + (hi - lo) * (nHooks === 1 ? 0.5 : (i + 1) / (nHooks + 1)))) {
              const pick = cands.filter((a) => chosen.every((g) => Math.abs(g - a) > hook.width + 4)).sort((p, q) => Math.abs(p - want) - Math.abs(q - want))[0];
              if (pick !== undefined) chosen.push(pick);
            }
            if (chosen.length < nHooks) return null;
          }
          if (rr > (hi - lo) / 2 - 0.05) return null;
        }
        return { gr, q };
      };
      const short = Math.min(inner.x1 - inner.x0, inner.y1 - inner.y0);
      // a shaped PCB's case follows it as far as the parts allow, a soft one too (a round board gets a round case)
      const want = form === 'round' || shaped ? short / 2 + budget : Math.min(FORM_SOFT_R, Math.max(4, 0.3 * (short + 2 * wall))) - wall;
      let lo = ri, hi = Math.max(ri, want), best = fits(ri) ? ri : null;
      if (best != null && fits(hi)) best = hi;
      else if (best != null) {
        // what fits is not one interval (hooks leave the straight runs before an arc is big enough to carry them): the
        // largest radius that fits on a 1 mm grid from the top, then that step in fine
        for (let m = hi - 1; m > lo; m -= 1) if (fits(m)) { lo = best = m; hi = m + 1; break; }
        for (let i = 0; i < 12; i++) { const m = (lo + hi) / 2; if (fits(m)) lo = best = m; else hi = m; }
      }
      if (best != null) {
        const { gr, q } = fits(best)!;
        Object.assign(inner, q);
        ri = best;
        formNote.cornerR = +(ri + wall).toFixed(2);
        formNote.grown = Object.fromEntries(EDGES.filter((e) => gr[e] > 0.005).map((e) => [e, +gr[e].toFixed(2)]));
        if (best < want - 0.05 && best < short / 2 - 0.1) formNote.limited = `asked for ${(want + wall).toFixed(1)} mm corners; ${EDGES.some((e) => spansOn[e].length) ? 'port windows, cable exits and ' : ''}the parts near the corners allow ${(ri + wall).toFixed(1)}`;
      } else formNote.limited = 'a port window or cable exit sits in a corner: kept the box corners';
    }
    const innerCS: CrossSection = std.rect(inner.x1 - inner.x0, inner.y1 - inner.y0, { r: ri, center: false }).translate([inner.x0, inner.y0]);
    const outerCS = innerCS.offset(wall, 'Round');
    const at = (p: V3): V3 => [p[0], p[1], p[2] + zBoard]; // board frame -> enclosure frame
    const report: EnclosureReport = { zBoard, zTop, lidT, standoff, inner, outerSize: [0, 0, 0], features: [formNote] };
    // the round forms also soften the edges the hand meets: the base's foot and the lid's top
    const edgeR = form === 'box' ? 0.4 : 0.8;

    // --- base: tray with floor and walls
    let base: Manifold = std.extrude(outerCS, zTop, { chamferBottom: Math.min(edgeR, floor - 0.4) }).subtract(innerCS.extrude(zTop + 1).translate([0, 0, floor]));
    const baseAdds: Manifold[] = [], baseCuts: Manifold[] = [];

    // cells: corner ribs on the floor (L-shaped, 0.3 mm off the cell), and the report of where each went
    const cells: Enclosure['cells'] = [];
    for (const c of cellsAt) {
      const rh = Math.min(3, Math.max(1.2, 0.6 * c.h)), ax = Math.min(5, c.w / 3), ay = Math.min(5, c.d / 3);
      for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
        const px = c.x + sx * (c.w / 2 + CELL_GAP), py = c.y + sy * (c.d / 2 + CELL_GAP);
        const rib = (x0: number, x1: number, y0: number, y1: number) =>
          M.cube([Math.abs(x1 - x0), Math.abs(y1 - y0), rh + EPS]).translate([Math.min(x0, x1), Math.min(y0, y1), floor - EPS]);
        baseAdds.push(rib(px - sx * ax, px + sx * RIB_T, py, py + sy * RIB_T), rib(px, px + sx * RIB_T, py - sy * ay, py + sy * RIB_T));
      }
      const box: Box3 = { min: [c.x - c.w / 2, c.y - c.d / 2, floor - zBoard], max: [c.x + c.w / 2, c.y + c.d / 2, floor + c.h - zBoard] };
      cells.push({ id: c.a.id, box });
      report.features.push({ type: 'battery', for: c.a.id, key: c.a.key, placement: c.place, ...(c.side ? { side: c.side } : {}), size: [c.w, c.d, c.h],
        box: { min: box.min.map((v) => +v.toFixed(2)), max: box.max.map((v) => +v.toFixed(2)) }, ribs: 4, ribH: +rh.toFixed(2),
        hold: c.place === 'under' ? 'board' : 'lid bars', underPins: c.place === 'under' ? +(standoff - b.bottomMax - c.h).toFixed(2) : undefined });
    }
    for (const a of b.accs.filter((a) => a.mount === 'inside' && !cells.some((c) => c.id === a.id)))
      report.features.push({ type: 'battery', for: a.id, key: a.key, blocked: (a.w ?? 0) > 0 && (a.d ?? 0) > 0 ? 'no room under the board and every side has ports or cable exits' : 'no size (w, d, h) for it' });

    // --- how it is held where it is used (o.mounting), and how it sits in use (report.pose, for views)
    const mounting = mountFeatures(mountKind, { inner, wall, ri, floor, portEdges, cables, cellsAt, b, o, magnetD, magnetT });
    baseAdds.push(...mounting.adds); baseCuts.push(...mounting.cuts);
    report.features.push(mounting.note);
    const STANCE: Record<string, string> = { stake: 'upright', ears: 'wall', strap: 'wall', lanyard: 'hand', magnets: 'wall', contacts: 'desk', none: 'desk' };
    if (mountKind !== (o.mounting ?? 'none')) mounting.note.fromStance = true;
    report.pose = { stance: !o.stance || o.stance === 'auto' ? STANCE[mountKind] ?? 'desk' : o.stance, ...(mounting.edge ? { edge: mounting.edge } : {}) };

    // --- the stand of a tilt or upright stance: a printed cradle the case leans in with its lid to the user. Its side view
    // has nothing but itself under any point, so it prints without supports: a slope under the floor and a ledge before
    // the wall the case stands on, on a plate that reaches behind the case's centre of mass.
    let stand: Enclosure['stand'] = null;
    const stanceNow = report.pose.stance;
    if (stanceNow === 'tilt' || stanceNow === 'upright') {
      const X0 = inner.x0 - wall, X1 = inner.x1 + wall, Y0 = inner.y0 - wall, Y1 = inner.y1 + wall, cH = zTop + lidT;
      const len = (e: BoardEdge) => (e[1] === 'x' ? Y1 - Y0 : X1 - X0); // the wall's length; its depth is the other side
      const free = (['-y', '-x', '+x', '+y'] as BoardEdge[]).filter((e) => !portEdges.has(e) && !cables.some((a) => a.edge === e));
      const named = o.mountEdge && o.mountEdge !== 'auto' ? o.mountEdge : null;
      // a display reads with +y up: the case stands on -y if it can; else on the longest free wall (the steadiest)
      const shows = b.comps.some((c) => c.access === 'display') || onBoard.some((a) => a.kind === 'display');
      const e = named && free.includes(named) ? named : shows && free.includes('-y') ? '-y' : [...free].sort((p, q) => len(q) - len(p))[0];
      if (mountKind === 'stake') { /* it stands on its stake */ }
      else if (mountKind !== 'none' && mountKind !== 'magnets') report.features.push({ type: 'stand', blocked: `${mountKind} and a stand exclude each other: no stand for stance ${stanceNow}` });
      else if (!e) report.features.push({ type: 'stand', blocked: 'every wall has a port window or a cable exit: nothing to stand on' });
      else {
        const deg = STAND_ANGLE[stanceNow], a = (deg * Math.PI) / 180, cs = Math.cos(a), sn = Math.sin(a), g = STAND_GAP, lipT = 3;
        const L = (e[1] === 'x' ? X1 - X0 : Y1 - Y0), S = Math.min(70, (stanceNow === 'tilt' ? 0.7 : 0.45) * L);
        const lipH = stanceNow === 'upright' ? Math.max(STAND_LIP, 0.8 * cH) : STAND_LIP, w = Math.max(20, Math.min(90, 0.7 * len(e)));
        const zO = Math.max(STAND_T, 1 + (g + lipT) * sn - lipH * cs); // the case's lower front edge over the bed
        const on = (ss: number, nn: number): V2 => [ss * cs - nn * sn, zO + ss * sn + nn * cs]; // slope frame -> side view
        const Pf = on(-(g + lipT), lipH), T = on(S, -g), uCom = on(L / 2, cH / 2)[0], uBack = Math.max(T[0] + 3, uCom + 15);
        // the slope's top ends in a 1.2 mm flat: a knife edge would print as a sliver
        // and so does the ledge's peak, cut flat 0.4 mm under its point
        const Pb = on(-g, lipH), O = on(-g, -g), top = Pb[1] - 0.4;
        const toward = (q: V2): V2 => { const k = (Pb[1] - top) / Math.max(1e-6, Pb[1] - q[1]); return [Pb[0] + (q[0] - Pb[0]) * k, top]; };
        const side: CrossSection = std.poly([[Pf[0], 0], [uBack, 0], [uBack, STAND_T], [T[0] + 1.2, STAND_T], [T[0] + 1.2, T[1]], T, O, toward(O), toward(Pf), Pf]);
        const print = side.extrude(w).rotate([90, 0, 0]).translate([0, w / 2, 0]);
        const faceAt: V3 = e === '-y' ? [(X0 + X1) / 2, Y0, 0] : e === '+y' ? [(X0 + X1) / 2, Y1, 0] : e === '-x' ? [X0, (Y0 + Y1) / 2, 0] : [X1, (Y0 + Y1) / 2, 0];
        // under the case: the slope frame on the case's own axes (the wall's outer face at s = 0, the floor's underside at n = 0)
        const placed = side.translate([0, -zO]).rotate(-deg).extrude(w).translate([0, 0, -w / 2]).rotate([90, 0, 0]).rotate([0, 0, 90]).rotate([0, 0, YAW[e] - 270]).translate(faceAt);
        stand = { print, placed };
        report.pose.edge = e;
        report.pose.angle = deg;
        report.features.push({ type: 'stand', edge: e, angle: deg, width: +w.toFixed(1), depth: +(uBack - Pf[0]).toFixed(1), height: +Math.max(T[1], top).toFixed(1) });
      }
    }

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
      const toWall = insideBy(inner, ri, h.x, h.y) - fit;
      const postR = Math.max(0.9, Math.min(1.8, near - 0.3, toWall));
      posts.push({ x: h.x, y: h.y, r: postR, kind, near: +near.toFixed(2) });
      report.features.push({ type: 'mount', at: [h.x, h.y], kind, d: h.d, standoffD: sd, postD: +(2 * postR).toFixed(2), metalOk });
    }

    if (!b.mounts.length) {
      // no holes: ledges under the short ends, and hold-down posts over them where the top side is free
      const freeOf = (x0: number, y0: number, x1: number, y1: number) =>
        !tops.some((c) => c.box.min[0] < x1 + 0.3 && c.box.max[0] > x0 - 0.3 && c.box.min[1] < y1 + 0.3 && c.box.max[1] > y0 - 0.3);
      for (const r0 of ledges) {
        // inside the walls, whatever their shape (a shaped PCB's end is no straight edge)
        base = base.add(CS.square([r0[2] - r0[0], r0[3] - r0[1]]).translate([r0[0], r0[1]]).intersect(innerCS).extrude(standoff + EPS).translate([0, 0, floor - EPS]));
        const cx = (r0[0] + r0[2]) / 2, cy = (r0[1] + r0[3]) / 2;
        const pr = 1.2;
        const spot = ([[cx, cy], [r0[0] + pr, cy], [r0[2] - pr, cy], [cx, r0[1] + pr], [cx, r0[3] - pr]] as V2[]).find(([x, y]) => freeOf(x - pr, y - pr, x + pr, y + pr) && onPcb(x, y) && insideBy(inner, ri, x, y) > pr + fit);
        if (spot) posts.push({ x: spot[0], y: spot[1], r: pr, kind: 'ledge', near: 0 });
        report.features.push({ type: 'mount', kind: 'ledge', rect: r0.map((v) => +v.toFixed(2)), holdDown: !!spot, ...(spot ? { post: spot.map((v) => +v.toFixed(2)) } : {}) });
      }
    }

    // --- lid: plate + hold-down posts (the openings, flex buttons and clips come after the snap hooks)
    let lid: Manifold = std.extrude(outerCS, lidT, { chamferTop: Math.min(edgeR, lidT / 2) }).translate([0, 0, zTop]);
    const lidAdds: Manifold[] = [], lidCuts: Manifold[] = [];
    for (const p of posts) {
      const len = zTop - (zBoard + b.T + 0.1);
      lidAdds.push(M.cylinder(len + EPS, p.r, p.r, 24).translate([p.x, p.y, zTop - len]));
    }
    const keepClear: number[][] = []; // plan rects [x0, y0, x1, y1] of lid features the edge clips stay off
    const overlaps = (r: number[], q: number[], m = 0) => r[0] < q[2] + m && r[2] > q[0] - m && r[1] < q[3] + m && r[3] > q[1] - m;
    const r2 = (v: number) => +v.toFixed(2);

    // --- cable exits: a round hole (cable + 0.6) through the wall at edge/at, centred on the wall's height between the
    // board top and the lid joint, and behind it a tie block: a zip-tie slot across the cable between the wall and a
    // plate with the same bore. A tie cinched round the cable in the slot takes a pull on the probe off the connector.
    const portComps = b.comps.filter((c) => c.access === 'port' && c.mouth);
    const portSpan = (c: BoardPart) => {
      const plug = c.plug ?? [c.w, c.h], half = (Math.max(plug[0], c.w) + 2 * portFit) / 2 + chamfer, ac = c.edge![1] === 'x' ? c.mouth![1] : c.mouth![0];
      return [ac - half, ac + half];
    };
    const wallSpans: { edge: BoardEdge; a0: number; a1: number }[] = []; // cable exits along their walls: the snap hooks keep off
    for (const a of cables) {
      const e = a.edge!, onX = e[1] === 'x', sg = e[0] === '+' ? 1 : -1;
      const hd = cableD(a), hr = hd / 2, bw = hd + 2 * TIE_SIDE;
      const [lo, hi] = onX ? [inner.y0, inner.y1] : [inner.x0, inner.x1];
      const taken = [...portComps.filter((c) => c.edge === e).map(portSpan), ...wallSpans.filter((s) => s.edge === e).map((s) => [s.a0, s.a1])];
      const free = (s: number) => s - bw / 2 >= lo + 1.5 && s + bw / 2 <= hi - 1.5 && !taken.some(([s0, s1]) => s + bw / 2 > s0 - 0.6 && s - bw / 2 < s1 + 0.6);
      let s: number | null = null;
      for (let k = 0; k <= 4 * (hi - lo) && s === null; k++) for (const v of k ? [a.at! + k / 4, a.at! - k / 4] : [a.at!]) if (s === null && free(v)) s = v;
      if (s === null) {
        report.features.push({ type: 'cable_exit', for: a.id, key: a.key, edge: e, blocked: `no ${r2(bw)} mm of the ${e} wall is free of port windows and other exits` });
        continue;
      }
      // centred between the board top and 1 mm under the lid joint (zTop is high enough for it)
      const zLo = Math.max(floor + 0.8, zBoard + b.T + 0.3) + hr, zHi = zTop - 1.0 - hr;
      const zc = (zLo + Math.max(zLo, zHi)) / 2;
      // local frame: outward +x, the inner wall face at x = 0, along the wall y, z as in the case
      const wallIn = onX ? (sg > 0 ? inner.x1 : -inner.x0) : sg > 0 ? inner.y1 : -inner.y0;
      const place = (q: Manifold) => q.translate([wallIn, 0, 0]).rotate([0, 0, YAW[e]]).translate(onX ? [0, s!, 0] : [s!, 0, 0]);
      const depthIn = relief ? tieL + 1 : 1;
      baseCuts.push(place(M.cylinder(wall + depthIn + 1, hr, hr, arcSegments(hr)).rotate([0, 90, 0]).translate([-depthIn, 0, zc])));
      if (relief) {
        const zb = Math.min(zc + hr + 1.6, zTop - 0.4), zs = Math.max(floor + 0.4, zc - hr - 1.5);
        const block = M.cube([tieL + 0.5, bw, zb - floor + EPS]).translate([-tieL, -bw / 2, floor - EPS])
          .subtract(M.cube([TIE_SLOT, bw + 2, zb - zs + 1]).translate([-TIE_SLOT, -bw / 2 - 1, zs]));
        baseAdds.push(place(block));
      }
      const face = onX ? (sg > 0 ? inner.x1 : inner.x0) : sg > 0 ? inner.y1 : inner.y0;
      const plan = onX ? [Math.min(face, face - sg * tieL), s - bw / 2, Math.max(face, face - sg * tieL), s + bw / 2] : [s - bw / 2, Math.min(face, face - sg * tieL), s + bw / 2, Math.max(face, face - sg * tieL)];
      if (relief) keepClear.push(plan);
      wallSpans.push({ edge: e, a0: s - bw / 2, a1: s + bw / 2 });
      const inside = onX ? [face - sg * (tieL + 1), s, zc - zBoard] : [s, face - sg * (tieL + 1), zc - zBoard];
      report.features.push({ type: 'cable_exit', for: a.id, key: a.key, edge: e, at: r2(s), z: r2(zc - zBoard), d: r2(hd), cable_d: a.cable_d ?? 4,
        relief: relief ? 'tie slot' : 'none', ...(relief ? { block: [r2(tieL), r2(bw)] } : {}), inside: inside.map(r2), ...(Math.abs(s - a.at!) > 0.01 ? { moved: r2(s - a.at!) } : {}) });
    }

    // --- lid openings, planned here so the snap hooks and the press tongues keep off them; cut after those, shrunk where
    // a post, hook or tongue still overlaps (or reported blocked). Light: a small chip LED keeps the classic round hole
    // (lightD, or a 0.4 mm skin), a bigger one (5050 RGB, PLCC, THT) gets a window like a sensor or a display: its
    // `window`, else the footprint + windowFit a side, round for shape round, with a 45 deg flare on the lid's outer face
    // (a wider view; the lid prints top-down, so the flare needs no support). Sound: a grille of grilleD holes on a
    // grillePitch hex grid over the part (at least 5; a 3 x 3 pattern over a small buzzer), all one extrusion.
    type Open = { id: string; type: 'light' | 'sensor' | 'display' | 'sound'; shape: 'rect' | 'round'; cx: number; cy: number; w: number; d: number;
      chamfer: number; legacy?: boolean; skin?: boolean; holes?: V2[]; pitch?: number; acc?: BoardAcc; zLow: number; rect?: number[] };
    const opens: Open[] = [];
    const lc = Math.max(0, Math.min(1.0, lidT - 0.8));
    const wf = o.windowFit ?? 0.3, lightD = o.lightD ?? 2.0, skin = o.lights === 'skin';
    const gD = o.grilleD ?? 1.5, gMin = gD + (printer.holeDelta ?? 0) + wallMin, gP = Math.max(o.grillePitch ?? 3, gMin);
    const grille = (w: number, d: number, round: boolean): { holes: V2[]; pitch: number } => {
      const m = 0.5 + gD / 2, rx = w / 2 - m, ry = d / 2 - m, dy = (gP * Math.sqrt(3)) / 2;
      const holes: V2[] = [];
      if (rx > 0 && ry > 0)
        for (let j = -Math.ceil(ry / dy); j <= Math.ceil(ry / dy); j++)
          for (let i = -Math.ceil(rx / gP) - 1; i <= Math.ceil(rx / gP) + 1; i++) {
            const x = i * gP + (j & 1 ? gP / 2 : 0), y = j * dy;
            if (round ? (x * x) / (rx * rx) + (y * y) / (ry * ry) <= 1 + 1e-9 : Math.abs(x) <= rx + 1e-9 && Math.abs(y) <= ry + 1e-9) holes.push([x, y]);
          }
      if (holes.length >= 5) return { holes, pitch: gP };
      return { holes: [-1, 0, 1].flatMap((i) => [-1, 0, 1].map((j) => [i * gMin, j * gMin] as V2)), pitch: gMin };
    };
    for (const c of b.comps.filter((c) => (c.access === 'light' || c.access === 'sensor' || c.access === 'display' || c.access === 'sound') && c.side !== 'bottom')) {
      const cx = (c.box.min[0] + c.box.max[0]) / 2, cy = (c.box.min[1] + c.box.max[1]) / 2, pw = c.box.max[0] - c.box.min[0], pd = c.box.max[1] - c.box.min[1];
      const type = c.access as Open['type'], round = c.shape === 'round', over = coveredBy(b, c);
      if (over) {
        report.features.push({ type: type === 'sound' ? 'sound_grille' : type === 'light' ? 'light' : `${type}_window`, for: c.id, covered: over.id });
        continue;
      }
      if (type === 'sound') {
        const [gw, gd] = c.window ?? [pw, pd], g = grille(gw, gd, round);
        opens.push({ id: c.id, type, shape: round ? 'round' : 'rect', cx, cy, w: gw, d: gd, chamfer: 0, holes: g.holes.map(([x, y]) => [cx + x, cy + y]), pitch: g.pitch, zLow: zTop });
      } else if (type === 'light' && !c.window && !c.shape && Math.min(pw, pd) <= LED_SMALL) {
        const lr = skin ? 1.8 : lightD / 2;
        opens.push({ id: c.id, type, shape: 'round', cx, cy, w: 2 * lr, d: 2 * lr, chamfer: 0, legacy: true, skin, zLow: zTop });
      } else {
        let [ww, wd] = c.window ?? [pw + 2 * wf, pd + 2 * wf];
        if (round) ww = wd = Math.max(ww, wd);
        const sk = type === 'light' && skin;
        opens.push({ id: c.id, type, shape: round ? 'round' : 'rect', cx, cy, w: ww, d: wd, chamfer: sk ? 0 : lc, skin: sk, zLow: zTop });
      }
    }
    // a module on the board: a window over its glass (a display without one shows its body less 1 mm a side); a display
    // is held down onto its header by the lid just over it, or by a rim hanging from the lid round the window
    for (const a of onBoard.filter((a) => a.window || a.kind === 'display')) {
      const q = a.box!, round = a.shape === 'round';
      const cx = (q.min[0] + q.max[0]) / 2 + (a.window ? a.window_dx ?? 0 : 0), cy = (q.min[1] + q.max[1]) / 2 + (a.window ? a.window_dy ?? 0 : 0);
      let [ww, wd] = a.window ? [a.window[0] + 2 * wf, a.window[1] + 2 * wf] : [q.max[0] - q.min[0] - 2, q.max[1] - q.min[1] - 2];
      if (round) ww = wd = Math.max(ww, wd);
      const top = zBoard + q.max[2] + (o.displayGap ?? 0.2);
      const zLow = a.kind === 'display' && zTop - top > 0.3 ? top : zTop;
      opens.push({ id: a.id, type: a.kind === 'display' ? 'display' : 'sensor', shape: round ? 'round' : 'rect', cx, cy, w: ww, d: wd, chamfer: lc, acc: a, zLow });
    }
    const planOf = (op: Open, m = 0): number[] => {
      if (op.holes) {
        const xs = op.holes.map((h) => h[0]), ys = op.holes.map((h) => h[1]), r = gD / 2 + m;
        return [Math.min(...xs) - r, Math.min(...ys) - r, Math.max(...xs) + r, Math.max(...ys) + r];
      }
      const hw = op.w / 2 + op.chamfer + m, hd = op.d / 2 + op.chamfer + m;
      return [op.cx - hw, op.cy - hd, op.cx + hw, op.cy + hd];
    };
    // lid parts that hang over the board besides the posts: display rims (sized after the window is final, planned at
    // their largest) and bars over a cell beside the board; the tongues and the clips keep off them too
    const lidRects: number[][] = [];
    for (const op of opens) {
      keepClear.push(planOf(op));
      if (op.zLow < zTop) {
        const q = op.acc!.box!;
        lidRects.push([q.min[0] + 0.2, q.min[1] + 0.2, q.max[0] - 0.2, q.max[1] - 0.2]);
      }
    }
    const bars: number[][] = [];
    for (const c of cellsAt.filter((c) => c.place === 'beside')) {
      if (zTop - (floor + c.h + 0.8) < 0.3) continue;
      for (const f of [1 / 3, 2 / 3]) {
        const along = c.w >= c.d; // bars across the narrow side, at a third and two thirds of the long one
        const x = c.x - c.w / 2 + f * c.w, y = c.y - c.d / 2 + f * c.d;
        bars.push(along ? [x - 0.6, c.y - c.d / 2 + 1, x + 0.6, c.y + c.d / 2 - 1] : [c.x - c.w / 2 + 1, y - 0.6, c.x + c.w / 2 - 1, y + 0.6]);
      }
      lidRects.push(...bars.slice(-2));
      for (const q of bars.slice(-2)) lidAdds.push(M.cube([q[2] - q[0], q[3] - q[1], zTop - (floor + c.h + 0.8) + EPS]).translate([q[0], q[1], floor + c.h + 0.8]));
    }
    // key switches: a well in the lid over them, as wide as the caps and their play, its floor the plate they clip into
    const keys = b.comps.filter((c) => c.access === 'key' && c.key && c.side !== 'bottom' && !coveredBy(b, c));
    const KEY_PLAY = 0.5, KEY_WALL = 1.2;
    const keyAt = (c: BoardPart) => [(c.box.min[0] + c.box.max[0]) / 2, (c.box.min[1] + c.box.max[1]) / 2];
    const keyRect = (c: BoardPart, m: number) => {
      const [cx, cy] = keyAt(c), [cw, cd] = c.key!.cap;
      return [cx - cw / 2 - m, cy - cd / 2 - m, cx + cw / 2 + m, cy + cd / 2 + m];
    };
    lidRects.push(...keys.map((c) => keyRect(c, KEY_PLAY + KEY_WALL)));
    keepClear.push(...lidRects);

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
      // ...and the cable exits, and the lid openings, rims and bars that come within the hooks' room of the wall
      const hw = hook.width / 2, deep = fit + hook.t + 2 * hook.over, nPortSpans = spans.length;
      for (const s of wallSpans) spans.push({ edge: s.edge, a0: s.a0 - hw - 1, a1: s.a1 + hw + 1 });
      for (const q of [...opens.map((op) => planOf(op)), ...lidRects])
        for (const side of (longX ? ['+x', '-x'] : ['+y', '-y']) as BoardEdge[]) {
          const dist = side === '+x' ? inner.x1 - q[2] : side === '-x' ? q[0] - inner.x0 : side === '+y' ? inner.y1 - q[3] : q[1] - inner.y0;
          if (dist < deep + 0.5) spans.push(side[1] === 'x' ? { edge: side, a0: q[1] - hw - 0.5, a1: q[3] + hw + 0.5 } : { edge: side, a0: q[0] - hw - 0.5, a1: q[2] + hw + 0.5 });
        }
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
          // on the straight run of the wall, or round a corner big enough to carry it (then off the lid's openings too)
          const at = form !== 'box' ? hookAt(side, a, inner, ri) : null;
          if (form !== 'box' && !at) return false;
          if (at?.arc && [...opens.map((op) => planOf(op)), ...lidRects].some((q) => overlaps(q, at.plan, 0.5))) return false;
          return !spans.some((s) => s.edge === side && a > s.a0 && a < s.a1);
        };
        const chosen: number[] = [];
        for (const want of ideal) {
          const pick = cands
            .filter((f) => free(f) && chosen.every((g) => Math.abs(g - f) * (hi - lo) > hook.width + 4))
            .sort((p, q) => Math.abs(p - want) - Math.abs(q - want))[0];
          if (pick !== undefined) chosen.push(pick);
        }
        if (chosen.length < n) report.features.push({ type: 'warning', text: `only ${chosen.length} of ${n} snap hooks fit on the ${side} wall between port windows${spans.length > nPortSpans && spans.slice(nPortSpans).some((s) => s.edge === side) ? ', cable exits and lid openings' : ''}` });
        for (const along of chosen) {
          const curved = form !== 'box' ? hookAt(side, lo + (hi - lo) * along, inner, ri)?.arc : undefined;
          if (curved) {
            // round the arc: the hook's profile and its groove revolved about the corner's centre, so the catch runs along it
            const gz0 = -(tipCut + 0.25), gz1 = -(Lh - 0.6 * over) + 0.15, R = ri - fit - hook.t;
            const prof = (std.snapHookProfile({ length: Lh, thickness: hook.t, overhang: over, lead: hook.lead, tipMin }) as V2[]).map(([u, v]) => [R + v, -u] as V2);
            const turn = (sec: CrossSection, w: number) => {
              const deg = (w / ri) * (180 / Math.PI), segs = 4 * Math.ceil((360 / (deg / 8)) / 4);
              return sec.revolve(segs, deg).rotate([0, 0, curved.th - deg / 2]).translate([curved.C[0], curved.C[1], zTop]);
            };
            lidAdds.push(turn(std.poly(prof), hook.width));
            // the groove starts a little inside the wall's chords, so no sliver of wall stays in front of it
            base = base.subtract(turn(std.poly([[ri - 0.15, gz0], [ri + gd, gz0], [ri + gd, gz1], [ri - 0.15, gz1 + gd + 0.15]]), hook.width + 0.8));
            hooks.push({ side, along: +along.toFixed(2) });
            const plan = hookAt(side, lo + (hi - lo) * along, inner, ri)!.plan;
            keepClear.push(plan);
            hookPlan.push(plan);
            continue;
          }
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
          const ac = side[1] === 'x' ? shift[1] : shift[0];
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
    const presses = b.comps.filter((c) => c.access === 'press' && c.side !== 'bottom' && (c.normal?.[2] ?? 1) > 0.5 && !coveredBy(b, c));
    const DIR = { '+y': [0, 1], '-y': [0, -1], '+x': [1, 0], '-x': [-1, 0] } as const;
    const tongues: { id: string; rect: number[] }[] = [];
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
        // and a slot through a lid window or grille, a display rim or a cell bar (a classic LED hole may meet a slot and
        // stays open: the DevKitC's EN tongue runs past its power LED)
        const openHit = opens.some((op) => !op.legacy && op.id !== c.id && overlaps(tongue(d), planOf(op), 0.4)) || lidRects.some((q) => overlaps(tongue(d), q, 0.4))
          || tongues.some((t) => overlaps(tongue(d), t.rect));
        return { d, ok: inside && !postHit && !hookHit && !openHit, score: (inside ? 3 : 0) + (postHit ? 0 : 1) + (hookHit ? 0 : 1) + (openHit ? 0 : 1) };
      }).sort((a, z) => z.score - a.score);
      // only parts that reach into the plunger zone limit its diameter
      const others = b.comps.filter((d) => d !== c && d.side !== 'bottom' && d.box.max[2] > c.box.max[2] + 0.05);
      const room = Math.min(...others.map((d) => Math.hypot(Math.max(d.box.min[0] - cx, 0, cx - d.box.max[0]), Math.max(d.box.min[1] - cy, 0, cy - d.box.max[1]))), 99);
      const plungerD = Math.max(1.2, Math.min(2.6, 2 * (room - 0.4)));
      const tab = flexTab({ at: [cx, cy], t: lidT, len: L, width: tw, dir: dirs[0].d, plunger, plungerD });
      lidCuts.push(tab.cut.translate([0, 0, zTop]));
      lidAdds.push(tab.add.translate([0, 0, zTop]));
      keepClear.push(tongue(tab.dir));
      tongues.push({ id: c.id, rect: tongue(tab.dir) });
      const strain = (1.5 * lidT * (gap + travel)) / (L * L);
      report.features.push({ type: 'flex_button', for: c.id, at: [cx, cy], dir: tab.dir, len: L, width: tab.width, plunger: +plunger.toFixed(2), plungerD: +plungerD.toFixed(2), gap, strain: +strain.toFixed(4), clearOfPosts: dirs[0].ok });
    }
    if (o.buttons === 'none' && presses.length) report.features.push({ type: 'buttons_off', for: presses.map((c) => c.id) });

    // --- key switches: the plate at the height the switch clips at, its top sunk into the lid when the case stands higher than
    // that (a module beside the keys); neighbouring wells become one. The cap is printed for this case: its skirt stops short
    // of the plate at the bottom of the travel
    const keycaps: Enclosure['keycaps'] = [];
    const rectCS = (q: number[]) => std.rect(q[2] - q[0], q[3] - q[1], { center: false }).translate([q[0], q[1]]);
    const closed = (rects: number[][], m: number): CrossSection => CS.union(rects.map(rectCS)).offset(m, 'Miter').offset(-m, 'Miter');
    const inTheWay = (c: BoardPart, q: number[], z: number) => [...b.comps, ...b.accs.filter((a) => a.box).map((a) => ({ id: a.id, box: a.box! }))].filter((d) => d.id !== c.id && d.box.max[2] + zBoard > z - 0.1)
      .filter((d) => d.box.min[0] < q[2] && d.box.max[0] > q[0] && d.box.min[1] < q[3] && d.box.max[1] > q[1]).map((d) => d.id);
    // a round hole in the lid: the panel part's body hangs from it, a shaft comes through and takes a printed knob
    for (const c of keys.filter((c) => c.key!.plate_top == null)) {
      const k = c.key!, [cx, cy] = keyAt(c), lidTop = zTop + lidT;
      lidCuts.push(M.cylinder(lidT + 2, k.cut / 2 + (printer.holeDelta ?? 0) / 2, k.cut / 2 + (printer.holeDelta ?? 0) / 2, 48).translate([cx, cy, zTop - 1]));
      let rise = 99;
      if (k.stem === 'shaft') {
        const shaftTop = zBoard + b.T + (k.shaft_top ?? 20), sr = (k.shaft_d ?? 6) / 2 + 0.05, knobD = k.cap[0];
        rise = +(shaftTop - lidTop).toFixed(2);
        const zBottom = lidTop + 0.6, h = Math.max(8, shaftTop + 2 - zBottom);
        // the bore holds the shaft's flat side: the knob turns it, whichever way an encoder or a pot is keyed
        const bore = M.cylinder(h - 2, sr, sr, 28).subtract(M.cube([sr, 2 * sr + 1, h], false).translate([sr * 0.5, -sr - 0.5, -0.5]));
        const knob: Manifold = M.cylinder(h, knobD / 2, knobD / 2 - 0.8, 64).subtract(bore);
        if (k.knob !== false) keycaps.push({ id: c.id, print: knob.rotate([180, 0, 0]).translate([0, 0, h]), placed: knob.translate([cx, cy, zBottom]) });
      }
      const q = keyRect(c, 0);
      const hc = k.cut / 2 + 0.5;
      const hit = posts.filter((p) => Math.abs(p.x - cx) < hc + p.r && Math.abs(p.y - cy) < hc + p.r).map((p) => `the hold-down post at ${r2(p.x)}, ${r2(p.y)}`);
      const under = k.stem === 'panel' ? inTheWay(c, [cx - k.cut / 2, cy - k.cut / 2, cx + k.cut / 2, cy + k.cut / 2], zBoard + b.T + 0.5) : [];
      report.features.push({ type: 'key_plate', for: c.id, stem: k.stem, at: [r2(cx), r2(cy)], plate_z: r2(lidTop), plate_t: lidT, cut: k.cut, well: 0, lid_top: r2(lidTop), rise, travel: 0, under, posts: hit,
        outside: q[0] < inner.x0 || q[1] < inner.y0 || q[2] > inner.x1 || q[3] > inner.y1 });
    }
    const byPlate = new Map<number, BoardPart[]>();
    for (const c of keys.filter((c) => c.key!.plate_top != null)) byPlate.set(c.key!.plate_top!, [...(byPlate.get(c.key!.plate_top!) ?? []), c]);
    for (const [plateTop, group] of byPlate) {
      const zP = zBoard + b.T + plateTop, plateT = group[0].key!.plate_t!;
      const floorZ = zP - plateT;
      const well = closed(group.map((c) => keyRect(c, KEY_PLAY)), 1.5);
      const shellPlan = closed(group.map((c) => keyRect(c, KEY_PLAY + KEY_WALL)), 1.5);
      if (floorZ < zTop) lidAdds.push(shellPlan.extrude(zTop - floorZ + EPS).translate([0, 0, floorZ]));
      if (zP < zTop + lidT) lidCuts.push(well.extrude(zTop + lidT - zP + 1).translate([0, 0, zP]));
      for (const c of group) {
        const k = c.key!, [cx, cy] = keyAt(c), fit = printer.holeDelta ?? 0;
        // the cut-out through the plate; a plate inside a thicker lid gets room under it for the clips
        lidCuts.push(M.cube([k.cut + fit, k.cut + fit, plateT + 2], true).translate([cx, cy, floorZ + plateT / 2]));
        if (floorZ > zTop) lidCuts.push(M.cube([k.cut + 2.4, k.cut + 2.4, floorZ - zTop + 1], true).translate([cx, cy, (floorZ + zTop - 1) / 2]));
        const [cw, cd] = k.cap, topT = 1.6, wallT = 1.2;
        const skirt = Math.max(0.8, k.stem_top! - plateTop - k.travel! - 0.4); // how far it hangs below the stem's top
        let cap: Manifold = std.rect(cw, cd, { r: 1.2 }).extrude(skirt + topT, 0, 0, [0.84, 0.84]);
        cap = cap.subtract(std.rect(cw - 2 * wallT, cd - 2 * wallT, { r: 0.6 }).extrude(skirt, 0, 0, [0.86, 0.86]));
        if (k.stem === 'mx') {
          const socket = 3.4; // deep enough to grip the stem, short enough to reach the housing only at the end of the travel
          const tube = M.cylinder(socket + 0.2, 2.75, 2.75, 28).translate([0, 0, skirt - socket]);
          const cross = M.union([M.cube([4.15, 1.35, socket], true), M.cube([1.35, 4.15, socket], true)]).translate([0, 0, skirt - socket / 2]);
          cap = cap.add(tube).subtract(cross);
        } else {
          for (const x of [-2.85, 2.85]) cap = cap.add(M.cube([1.1, 2.9, 3.2], true).translate([x, 0, skirt - 1.5]));
        }
        const capZ = zBoard + b.T + k.stem_top! - skirt; // the skirt's edge at rest
        const placed = cap.translate([cx, cy, capZ]);
        const pb = cap.rotate([180, 0, 0]).boundingBox();
        keycaps.push({ id: c.id, print: cap.rotate([180, 0, 0]).translate([0, 0, -pb.min[2]]), placed });
        const top = capZ + skirt + topT;
        const near = inTheWay(c, keyRect(c, KEY_PLAY + KEY_WALL), floorZ);
        const q = keyRect(c, KEY_PLAY + KEY_WALL);
        // a post under the plate's rim just hangs from the plate; only one in the cut-out meets the switch
        const hc = k.cut / 2 + 1;
        const hit = posts.filter((p) => Math.abs(p.x - cx) < hc + p.r && Math.abs(p.y - cy) < hc + p.r).map((p) => `the hold-down post at ${r2(p.x)}, ${r2(p.y)}`);
        const outside = q[0] < inner.x0 || q[1] < inner.y0 || q[2] > inner.x1 || q[3] > inner.y1;
        report.features.push({ type: 'key_plate', for: c.id, stem: k.stem, at: [r2(cx), r2(cy)], plate_z: r2(zP), plate_t: plateT, cut: k.cut, well: r2(Math.max(0, zTop + lidT - zP)), cap_top: r2(top), lid_top: r2(zTop + lidT), rise: r2(top - (zTop + lidT)), travel: k.travel, skirt: r2(skirt), under: near, posts: hit, outside });
      }
    }

    // --- the openings, cut now that the posts, hooks and tongues are placed: a window shrinks off the one it overlaps
    // (the side that keeps the most of it), a round one gets smaller, a grille drops the holes over it; under half the
    // window (or fewer than 5 holes) left, it is blocked and check_enclosure reports it
    const blockers = [
      ...posts.map((p) => ({ what: `the hold-down post at ${r2(p.x)}, ${r2(p.y)}`, q: [p.x - p.r, p.y - p.r, p.x + p.r, p.y + p.r] })),
      ...hookPlan.map((q) => ({ what: 'a snap hook', q })),
      ...tongues.map((t) => ({ what: `the press tongue of ${t.id}`, q: t.rect })),
    ];
    const lim = [inner.x0, inner.y0, inner.x1, inner.y1];
    const area = (q: number[]) => Math.max(0, q[2] - q[0]) * Math.max(0, q[3] - q[1]);
    for (const op of opens) {
      const m = op.chamfer + 0.4, why: string[] = [];
      let status = 'ok';
      if (op.legacy) {
        // the classic LED hole (or skin) at the LED, as it always was
        if (op.skin) lidCuts.push(M.cylinder(lidT - 0.4 + EPS, op.w / 2, op.w / 2, 24).translate([op.cx, op.cy, zTop - EPS]));
        else lidCuts.push(std.holeZ(op.w, lidT, { at: [op.cx, op.cy, zTop + lidT], through: true }));
        report.features.push({ type: 'light', for: op.id, mode: op.skin ? 'skin 0.4' : `hole ${r2(op.w)}` });
        continue;
      }
      if (op.holes) {
        const r = gD / 2 + 0.4, keep = op.holes.filter(([x, y]) => {
          const q = [x - r, y - r, x + r, y + r], hit = blockers.find((k) => overlaps(q, k.q));
          if (hit && !why.includes(hit.what)) why.push(hit.what);
          return !hit && q[0] > lim[0] + fit + 0.3 && q[2] < lim[2] - fit - 0.3 && q[1] > lim[1] + fit + 0.3 && q[3] < lim[3] - fit - 0.3;
        });
        if (keep.length < op.holes.length) status = keep.length >= 5 ? 'shrunk' : 'blocked';
        op.holes = keep;
      } else {
        let q = planOf(op, -op.chamfer); // the straight window; the flare and a 0.4 mm web keep m off a blocker
        const want = area(q);
        for (const k of blockers.filter((k) => overlaps(q, k.q, m))) {
          why.push(k.what);
          const g = [k.q[0] - m, k.q[1] - m, k.q[2] + m, k.q[3] + m];
          if (op.shape === 'round') {
            const rr = Math.min(q[2] - q[0], q[3] - q[1]) / 2, cx = (q[0] + q[2]) / 2, cy = (q[1] + q[3]) / 2;
            const dist = Math.hypot(Math.max(g[0] - cx, 0, cx - g[2]), Math.max(g[1] - cy, 0, cy - g[3]));
            const nr = Math.min(rr, dist);
            q = [cx - nr, cy - nr, cx + nr, cy + nr];
          } else
            q = [[q[0], q[1], Math.min(q[2], g[0]), q[3]], [Math.max(q[0], g[2]), q[1], q[2], q[3]], [q[0], q[1], q[2], Math.min(q[3], g[1])], [q[0], Math.max(q[1], g[3]), q[2], q[3]]]
              .sort((p, z) => area(z) - area(p))[0];
        }
        // and inside the walls: the lid over the wall top is the joint
        const e = op.chamfer + fit + 0.3;
        q = [Math.max(q[0], lim[0] + e), Math.max(q[1], lim[1] + e), Math.min(q[2], lim[2] - e), Math.min(q[3], lim[3] - e)];
        if (op.shape === 'round') {
          const nr = Math.min(q[2] - q[0], q[3] - q[1]) / 2, cx = op.cx, cy = op.cy;
          q = nr > 0 ? [cx - nr, cy - nr, cx + nr, cy + nr] : [cx, cy, cx, cy];
        }
        const got = area(q);
        if (got < want - 1e-6) status = got >= 0.5 * want && Math.min(q[2] - q[0], q[3] - q[1]) >= 1.0 ? 'shrunk' : 'blocked';
        op.rect = q;
      }
      const about = { ...(status !== 'ok' ? { [status]: why.length ? why.join(', ') : 'the walls' } : {}) };
      if (status === 'blocked') {
        report.features.push({ type: op.type === 'sound' ? 'sound_grille' : op.type === 'light' ? 'light' : `${op.type}_window`, for: op.id, ...about });
        continue;
      }
      if (op.holes) {
        // one cross-section of every hole, one extrusion, one subtraction with the other lid cuts
        const r = (gD + (printer.holeDelta ?? 0)) / 2, n = 16;
        const loops = op.holes.map(([x, y]) => Array.from({ length: n }, (_, i) => [x + r * Math.cos((2 * Math.PI * i) / n), y + r * Math.sin((2 * Math.PI * i) / n)] as V2));
        lidCuts.push(new CS(loops, 'Positive').extrude(lidT + 2).translate([0, 0, zTop - 1]));
        report.features.push({ type: 'sound_grille', for: op.id, count: op.holes.length, d: gD, pitch: r2(op.pitch!), shape: op.shape, holes: op.holes.map(([x, y]) => [r2(x), r2(y)]), ...about });
        continue;
      }
      const q = op.rect!, w = q[2] - q[0], d = q[3] - q[1], cx = (q[0] + q[2]) / 2, cy = (q[1] + q[3]) / 2;
      const sec: CrossSection = op.shape === 'round' ? CS.circle(w / 2, arcSegments(w / 2)) : std.rect(w, d, { r: Math.min(0.8, w / 2 - 0.01, d / 2 - 0.01) });
      if (op.skin) lidCuts.push(sec.extrude(lidT - 0.4 + EPS).translate([cx, cy, zTop - EPS]));
      else {
        lidCuts.push(sec.extrude(zTop + lidT + 1 - (op.zLow - 1)).translate([cx, cy, op.zLow - 1]));
        // the flare: a frustum whose sides all rise at 45 deg (the top scaled by the chamfer on each side)
        const c = op.chamfer;
        if (c > 0) lidCuts.push(sec.extrude(c + 1, 0, 0, [(w + 2 * (c + 1)) / w, (d + 2 * (c + 1)) / d]).translate([cx, cy, zTop + lidT - c]));
      }
      const feat: Record<string, any> = { type: op.type === 'light' ? 'light' : `${op.type}_window`, for: op.id, ...(op.type === 'light' ? { mode: op.skin ? 'skin 0.4' : 'window' } : {}),
        shape: op.shape, w: r2(w), d: r2(d), at: [r2(cx), r2(cy)], chamfer: r2(op.skin ? 0 : op.chamfer), ...about };
      if (op.acc) {
        feat.accessory = op.acc.key ?? op.acc.id;
        const body = op.acc.box!;
        // what holds a display down: the lid just over it, or a rim from the lid (1.2 mm round the window, on the module)
        let hold = [body.min[0], body.min[1], body.max[0], body.max[1]];
        if (op.zLow < zTop) {
          hold = [Math.max(q[0] - 1.2, body.min[0] + 0.2), Math.max(q[1] - 1.2, body.min[1] + 0.2), Math.min(q[2] + 1.2, body.max[0] - 0.2), Math.min(q[3] + 1.2, body.max[1] - 0.2)];
          if (area(hold) > area(q) + 0.5) lidAdds.push(M.cube([hold[2] - hold[0], hold[3] - hold[1], zTop - op.zLow + EPS]).translate([hold[0], hold[1], op.zLow]));
          feat.rim = { h: r2(zTop - op.zLow), rect: hold.map(r2) };
        }
        // the middle of each band of it beside the window that is 0.6 mm wide or more: where it presses
        const press = [[(hold[0] + q[0]) / 2, cy, q[0] - hold[0]], [(hold[2] + q[2]) / 2, cy, hold[2] - q[2]], [cx, (hold[1] + q[1]) / 2, q[1] - hold[1]], [cx, (hold[3] + q[3]) / 2, hold[3] - q[3]]]
          .filter((p) => p[2] >= 0.6).map((p) => [r2(p[0]), r2(p[1])]);
        if (op.type === 'display') Object.assign(feat, { hold: press.length ? (op.zLow < zTop ? 'rim' : 'lid') : 'header', press, gap: r2(o.displayGap ?? 0.2) });
      }
      report.features.push(feat);
    }

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
          // inside the walls, also where they curve in (a round case; the box has none to keep off)
          const placedClip = clip.translate(onX ? [e, s, 0] : [s, e, 0]);
          lidAdds.push(form === 'box' ? placedClip : placedClip.intersect(innerCS.offset(-fit, 'Round').extrude(zTop + 1).translate([0, 0, -0.5])));
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
    if (baseAdds.length) base = base.add(M.union(baseAdds));
    if (baseCuts.length) base = base.subtract(M.union(baseCuts));

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
    return { base, lid, at, report, posts, hooks, clips, ports, cells, stand, keycaps, zBoard, zTop, lidT, inner, wall, board: b };
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
      const printed = [part(L.base, { name: 'base' }), part(L.lid, { name: 'lid', color: lidColor })];
      if (enc.stand) {
        // behind the base (a mock-up plate goes in front of it)
        const bb = enc.base.boundingBox(), sb = enc.stand.print.boundingBox();
        printed.push(part(enc.stand.print.translate([bb.min[0] - sb.min[0], bb.max[1] + 6 - sb.min[1], 0]), { name: 'stand', color: STAND_COLOR }));
      }
      if (enc.keycaps.length) {
        // a tray of keycaps beyond the lid, four to a column, tops on the bed
        const lb = L.lid.boundingBox(), step = 24;
        printed.push(part(M.union(enc.keycaps.map((k, i) => k.print.translate([lb.max[0] + 16 + Math.floor(i / 4) * step, lb.min[1] + 10 + (i % 4) * step, 0]))), { name: 'keycaps', color: KEYCAP_COLOR }));
      }
      return printed;
    }
    const out = [part(enc.base, { name: 'base' }), part(enc.lid, { name: 'lid', color: lidColor })];
    if (enc.stand) out.push(part(enc.stand.placed, { name: 'stand', color: STAND_COLOR }));
    if (enc.keycaps.length) out.push(part(M.union(enc.keycaps.map((k) => k.placed)), { name: 'keycaps', color: KEYCAP_COLOR }));
    if (o.ghost) {
      const g = ghost(enc.board, { bottomPins: o.bottomPins }).translate([0, 0, enc.zBoard]);
      out.push(part(g, { name: 'board', role: 'reference', color: BOARD_COLOR, meta: { board: enc.board.spec.id, bottomPins: !!o.bottomPins, enclosure: enc.report } }));
      // a loose cell where the case put it (after the board: the board ghost is the first reference part)
      for (const c of enc.cells) out.push(part(boxSolid(M, c.box).translate([0, 0, enc.zBoard]), { name: c.id, role: 'reference', color: CELL_COLOR, meta: { accessory: c.id } }));
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
