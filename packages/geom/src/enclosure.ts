// check_enclosure: does the case hold the board it was built around? Pure function over the parts of
// an assembled build (base, lid and the board ghost as a 'reference' part from lib.elec.parts) and the
// fw.board/1 JSON. Plug paths are a grid of rays over the plug's rounded section (the clearance is found
// by bisection on how far that section can grow), then part and PCB collisions, supports, hold-downs
// (can the board tip up or slide: board_retained), button reach, LED windows, display and sensor windows (and what
// holds a display module down), sound grilles, cable exits, room for a loose cell, lid fit, snap strain and
// keep-outs. Manifold.rayCast returns `distance` as a fraction of
// the segment, so everything here works with hit positions.
import type { Manifold, Wasm } from './kernel.ts';
import { withArena } from './kernel.ts';
import { boardGhost, boardModel, coveredBy, EDGE_NORMAL, type BoardEdge, type BoardModel, type BoardPart, type BoardSpec, type Box3, type EnclosureReport } from './lib/elec.ts';
import type { Part } from './program.ts';

type V3 = [number, number, number];

export type FindingCode =
  | 'port_clear' | 'port_blocked' | 'component_clear' | 'board_collision' | 'pcb_seated' | 'board_retained' | 'button_reach'
  | 'button_unreachable' | 'light_window' | 'lid_fit' | 'snap_strain' | 'metal_in_keepout' | 'keepout_ok'
  | 'display_window' | 'sound_grille' | 'sensor_window' | 'cable_exit' | 'battery_space' | 'mounting' | 'key_plate';

export interface Finding {
  code: FindingCode;
  severity: 'error' | 'warn' | 'info';
  msg: string;
  part: string; // board component id, 'pcb', 'lid' or a keep-out id
  value: number | null; // the number the finding is about, in `unit`
  unit?: 'mm' | 'mm3' | '%';
}

export interface PortRay {
  port: string;
  from: V3;
  to: V3; // where it hit the case, or a little past the outer wall
  hit: boolean;
}

export interface EnclosureCheck {
  findings: Finding[];
  rays: PortRay[]; // at most RAYS_PER_PORT per port, for the viewer
  clearance: Record<string, number>; // port id -> mm all round the plug (0 = blocked)
  ms: number;
}

const RAYS_PER_PORT = 12;
const RAY_LEN = 30;
const SLIDE_MAX = 10; // how far the slide rays look (mm)
const LOOSE = 1.2; // total travel (mm) along x or y past which a board without holes rattles
const add = (a: V3, s: number, v: V3): V3 => [a[0] + s * v[0], a[1] + s * v[1], a[2] + s * v[2]];
const r2 = (v: number) => +v.toFixed(2);
const r3 = (v: number) => +v.toFixed(3);
const vol = (s: Manifold) => Math.max(0, s.volume()); // an empty intersection has volume -0
const centre = (c: BoardPart): [number, number] => [(c.box.min[0] + c.box.max[0]) / 2, (c.box.min[1] + c.box.max[1]) / 2];

// Can the board lift or tip off its supports? A rigid plate held down at `holds` and resting on `rests`
// (plan points) escapes only by pivoting about a line with every hold-down on one side and every
// support on the other (a lift is the line at infinity: no holds at all). Such a line, if any, can be
// turned until it runs through two of the points, so the pairs are all there is to try.
export function canTip(holds: [number, number][], rests: [number, number][]): boolean {
  if (!holds.length || !rests.length) return true;
  const pts = [...holds, ...rests];
  const side = (p: number[], q: number[], r: number[]) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  let lines = 0;
  for (let i = 0; i < pts.length; i++)
    for (let j = i + 1; j < pts.length; j++) {
      const p = pts[i], q = pts[j];
      if (Math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-6) continue;
      lines++;
      for (const sg of [1, -1])
        if (holds.every((h) => sg * side(p, q, h) <= 1e-6) && rests.every((r) => sg * side(p, q, r) >= -1e-6)) return true;
    }
  return lines === 0; // all in one spot: it spins about any line through it
}

// The board's place in the parts' frame: from the ghost's box, so it survives the engine moving the
// build onto the bed. `pose` overrides it ([x, y, z] of the board frame origin).
function poseOf(wasm: Wasm, b: BoardModel, ref: Part | undefined, pose?: Partial<{ x: number; y: number; z: number }> | V3): V3 | null {
  if (Array.isArray(pose)) return [pose[0], pose[1], pose[2]];
  if (pose && typeof pose === 'object' && 'z' in pose) return [pose.x ?? 0, pose.y ?? 0, pose.z ?? 0];
  if (!ref) return null;
  const own = boardGhost(wasm, b, { bottomPins: !!ref.meta?.bottomPins }).boundingBox();
  const got = ref.solid.boundingBox();
  return [got.min[0] - own.min[0], got.min[1] - own.min[1], got.min[2] - own.min[2]];
}

export function checkEnclosure(wasm: Wasm, parts: Part[], spec: BoardSpec, pose?: Partial<{ x: number; y: number; z: number }> | V3): EnclosureCheck {
  const t0 = performance.now();
  return withArena(() => {
    const M = wasm.Manifold;
    const findings: Finding[] = [];
    const rays: PortRay[] = [];
    const clearance: Record<string, number> = {};
    const push = (code: FindingCode, severity: Finding['severity'], msg: string, part: string, value: number | null, unit?: Finding['unit']) =>
      findings.push({ code, severity, msg, part, value, ...(unit ? { unit } : {}) });
    // the assembled case's outer size (base and lid in place), once the shell is known
    let size: V3 | undefined;
    const done = () => ({ findings, rays, clearance, ...(size ? { size } : {}), ms: Math.round(performance.now() - t0) });

    const b = boardModel(wasm, spec);
    const refs = parts.filter((p) => p.role === 'reference');
    const ref = refs.find((p) => p.meta?.board === spec.id) ?? refs[0];
    const report: EnclosureReport | undefined = ref?.meta?.enclosure;
    const P = poseOf(wasm, b, ref, pose);
    const models = parts.filter((p) => p.role === 'model');
    if (!P || !models.length) {
      push('pcb_seated', 'error', 'cannot check: the assembled layout has no board ghost; return lib.elec.parts(enc, { layout: p.layout, ghost: p.show_board }) and expose the layout and show_board params', 'pcb', null);
      return done();
    }
    // the case itself: a stand beside it holds the case in use, keycaps ride on the switches: neither is what the board and the plugs meet
    const cased = models.filter((p) => p.name !== 'stand' && p.name !== 'keycaps');
    const shell = cased.length === 1 ? cased[0].solid : M.union(cased.map((p) => p.solid));
    const sb = shell.boundingBox();
    size = [0, 1, 2].map((i) => +(sb.max[i] - sb.min[i]).toFixed(2)) as V3;
    const at = (p: V3): V3 => [p[0] + P[0], p[1] + P[1], p[2] + P[2]];
    // the case report is in the frame the case was built in; the engine may have moved it since
    const dz = report ? P[2] - report.zBoard : 0;
    const firstHit = (from: V3, to: V3) => shell.rayCast(from, to)[0] as { position: V3 } | undefined;
    const features = report?.features ?? [];

    // How far the board can slide each way before its PCB edge or one of its parts meets the case: rays
    // in plan from the PCB edge (mid-thickness, from every outline edge facing that way) and from the
    // part faces. Returns the total travel along x and along y (both ways added), at most 2 x SLIDE_MAX.
    const slide = () => {
      const dirs: [string, V3][] = [['+x', [1, 0, 0]], ['-x', [-1, 0, 0]], ['+y', [0, 1, 0]], ['-y', [0, -1, 0]]];
      const reach: Record<string, number> = { '+x': SLIDE_MAX, '-x': SLIDE_MAX, '+y': SLIDE_MAX, '-y': SLIDE_MAX };
      const cast = (p: V3, k: string, d: V3) => {
        const from = at(add(p, 0.02, d));
        const h = firstHit(from, add(from, SLIDE_MAX, d));
        if (h) reach[k] = Math.min(reach[k], Math.hypot(h.position[0] - from[0], h.position[1] - from[1]) + 0.02);
      };
      for (const poly of b.outline.toPolygons()) {
        let area = 0;
        for (let i = 0; i < poly.length; i++) area += poly[i][0] * poly[(i + 1) % poly.length][1] - poly[(i + 1) % poly.length][0] * poly[i][1];
        if (area <= 0) continue; // a hole in the outline
        for (let i = 0; i < poly.length; i++) {
          const [x0, y0] = poly[i], [x1, y1] = poly[(i + 1) % poly.length];
          const len = Math.hypot(x1 - x0, y1 - y0);
          if (len < 0.2) continue;
          const nx = (y1 - y0) / len, ny = -(x1 - x0) / len; // outward on a counter-clockwise loop
          const k = Math.max(1, Math.round(len / 2));
          for (let j = 0; j < k; j++) {
            const t = (j + 0.5) / k;
            for (const [key, d] of dirs) if (nx * d[0] + ny * d[1] > 0.5) cast([x0 + t * (x1 - x0), y0 + t * (y1 - y0), b.T / 2], key, d);
          }
        }
      }
      for (const c of b.comps.filter((c) => c.box.max[2] - c.box.min[2] > 0.05)) {
        const { min, max } = c.box;
        for (const [key, d] of dirs) {
          const ax = d[0] !== 0 ? 0 : 1, o = 1 - ax; // the face's normal axis and its other axis in plan
          for (const f of [0.1, 0.5, 0.9]) for (const g of [0.25, 0.75]) {
            const p: V3 = [0, 0, min[2] + g * (max[2] - min[2])];
            p[ax] = d[ax] > 0 ? max[ax] : min[ax];
            p[o] = min[o] + f * (max[o] - min[o]);
            cast(p, key, d);
          }
        }
      }
      return { x: reach['+x'] + reach['-x'], y: reach['+y'] + reach['-y'] };
    };

    // --- ports: a grid of rays over the plug section, from the receptacle mouth outward
    for (const c of b.comps.filter((c) => c.access === 'port' && c.mouth)) {
      const n = c.normal, u: V3 = n[0] !== 0 ? [0, 1, 0] : [1, 0, 0], v: V3 = [0, 0, 1];
      const mouth = at(c.mouth!);
      const plug = c.plug ?? [c.w, c.h];
      const pr = c.plug ? (c.plugR ?? 0.6) : 0; // plug overmold corner radius; a bare card or cable is sharp
      const axis = n[0] !== 0 ? 0 : 1;
      const outer = n[axis] > 0 ? sb.max[axis] : -sb.min[axis];
      // perimeter of the rounded plug section inflated by dw, plus a few interior points
      const envelope = (dw: number): [number, number][] => {
        const W = plug[0] / 2 + dw, H = plug[1] / 2 + dw, r = Math.min(pr + dw, W, H);
        const pts: [number, number][] = [[0, 0], [W / 2, 0], [-W / 2, 0], [0, H / 2], [0, -H / 2]];
        for (const [sx, sy] of [[1, 1], [-1, 1], [-1, -1], [1, -1]])
          for (let k = 0; k <= 4; k++) {
            const t = ((k / 4) * Math.PI) / 2;
            pts.push([sx * (W - r + r * Math.cos(t)), sy * (H - r + r * Math.sin(t))]);
          }
        for (let k = 1; k < 6; k++) {
          const a = -W + r + ((2 * W - 2 * r) * k) / 6;
          pts.push([a, H], [a, -H]);
        }
        for (let k = 1; k < 4; k++) {
          const z = -H + r + ((2 * H - 2 * r) * k) / 4;
          pts.push([W, z], [-W, z]);
        }
        return pts;
      };
      const start = (a: number, z: number) => add(add(add(mouth, 0.05, n), a, u), z, v);
      const blockedAt = (dw: number) => envelope(dw).find(([a, z]) => {
        const from = start(a, z);
        return !!firstHit(from, add(from, RAY_LEN, n));
      });
      const blocker = blockedAt(0);
      let lo = 0, hi = 2;
      if (!blocker) for (let k = 0; k < 10; k++) {
        const m = (lo + hi) / 2;
        if (blockedAt(m)) hi = m;
        else lo = m;
      }
      clearance[c.id] = blocker ? 0 : r3(lo);
      // rays for the viewer: centre, the middle of each corner arc and of each side, and the one that hit first
      const env = envelope(0);
      const show = [env[0], env[7], env[12], env[17], env[22], env[29], env[30], env[37], env[38]];
      if (blocker && !show.includes(blocker)) show.push(blocker);
      for (const [a, z] of show.slice(0, RAYS_PER_PORT)) {
        const from = start(a, z);
        const hit = firstHit(from, add(from, RAY_LEN, n));
        const past = Math.max(1, outer - from[axis] * Math.sign(n[axis]) + 3);
        rays.push({ port: c.id, from: from.map(r3) as V3, to: (hit ? hit.position : add(from, past, n)).map(r3) as V3, hit: !!hit });
      }
      push(blocker ? 'port_blocked' : 'port_clear', blocker ? 'error' : 'info',
        blocker
          ? `${c.id}: the ${plug[0]}x${plug[1]} mm plug path is blocked (a ray from the connector hits the case); widen the window (port_fit) or check the port's at/z0/protrude`
          : `${c.id}: a ${plug[0]}x${plug[1]} mm plug reaches the connector; ${lo.toFixed(2)} mm clearance all round`,
        c.id, clearance[c.id], 'mm');
    }

    // --- collisions: every component box, every module on the board and the PCB against the case
    const boxed: { id: string; box: Box3 }[] = [...b.comps, ...b.accs.flatMap((a) => (a.box ? [{ id: a.id, box: a.box }] : []))];
    for (const c of boxed.filter((c) => c.box.max[2] - c.box.min[2] > 0.05)) {
      const box = M.cube([c.box.max[0] - c.box.min[0], c.box.max[1] - c.box.min[1], c.box.max[2] - c.box.min[2]]).translate(at(c.box.min));
      const inside = vol(box.intersect(shell));
      const gap = box.minGap(shell, 3);
      if (inside > 0.01) push('board_collision', 'error', `${c.id}: ${inside.toFixed(2)} mm3 of it is inside the case`, c.id, r3(inside), 'mm3');
      else push('component_clear', gap < 0.15 && (c as BoardPart).access !== 'key' ? 'warn' : 'info', `${c.id}: nearest wall ${gap.toFixed(2)} mm`, c.id, r3(gap), 'mm');
    }
    // a module on its header must clear the parts under and beside it (a tall buzzer under an OLED)
    for (const a of b.accs.filter((a) => a.box))
      for (const c of b.comps) {
        const q = a.box!, d = [0, 1, 2].map((i) => Math.min(q.max[i], c.box.max[i]) - Math.max(q.min[i], c.box.min[i]));
        if (d.every((v) => v > 0.05)) push('board_collision', 'error', `${a.id}: the module runs into ${c.id} (${r2(d[0])} x ${r2(d[1])} x ${r2(d[2])} mm); move one of them or raise the module (z0)`, a.id, r3(d[0] * d[1] * d[2]), 'mm3');
      }
    let pcb: Manifold = b.outline.extrude(b.T);
    if (b.holes.length) pcb = pcb.subtract(M.union(b.holes.map((h) => M.cylinder(b.T + 2, h.d / 2, h.d / 2, 32).translate([h.x, h.y, -1]))));
    const pcbVol = vol(pcb.translate(P).intersect(shell));
    if (pcbVol > 0.01) push('board_collision', 'error', `PCB: ${pcbVol.toFixed(2)} mm3 of it is inside the case (standoffs, pegs or posts too big)`, 'pcb', r3(pcbVol), 'mm3');
    else {
      // seated: something right under the PCB at every support, and something right over it to hold it down
      type Sup = { at: [number, number]; ring: number; rect?: number[]; post?: [number, number] };
      const sup: Sup[] = b.mounts.map((h) => ({ at: [h.x, h.y], ring: h.d / 2 + 0.2 }));
      for (const f of features) if (f.type === 'mount' && f.kind === 'ledge') sup.push({ at: [(f.rect[0] + f.rect[2]) / 2, (f.rect[1] + f.rect[3]) / 2], ring: 0, rect: f.rect, post: f.post });
      const rests: [number, number][] = [], holds: [number, number][] = []; // plan points the board rests on / is held down at
      // only points on this board's PCB count (a clip built for a wider board presses on air)
      const loops = b.outline.toPolygons();
      const onPcb = (x: number, y: number) => {
        let wind = 0;
        for (const l of loops)
          for (let i = 0; i < l.length; i++) {
            const [x0, y0] = l[i], [x1, y1] = l[(i + 1) % l.length];
            const cross = (x1 - x0) * (y - y0) - (x - x0) * (y1 - y0);
            if (y0 <= y && y1 > y && cross > 0) wind++;
            else if (y0 > y && y1 <= y && cross < 0) wind--;
          }
        return wind !== 0;
      };
      const restsOn = (x: number, y: number) => {
        const h = onPcb(x, y) && firstHit(at([x, y, 0.05]), at([x, y, -20]));
        return !!h && h.position[2] >= P[2] - 0.15;
      };
      const heldAt = (x: number, y: number) => {
        const h = onPcb(x, y) && firstHit(at([x, y, b.T + 0.01]), at([x, y, b.T + 20]));
        return !!h && h.position[2] <= P[2] + b.T + 0.4;
      };
      let below = 0, above = 0;
      for (const s of sup) {
        // a standoff: four points round its hole; a ledge: its corners (0.3 in) and centre
        const r = s.rect;
        const pts: [number, number][] = s.ring
          ? [[1, 0], [0, 1], [-1, 0], [0, -1]].map(([x, y]) => [s.at[0] + x * s.ring, s.at[1] + y * s.ring])
          : r ? [s.at, [r[0] + 0.3, r[1] + 0.3], [r[2] - 0.3, r[1] + 0.3], [r[2] - 0.3, r[3] - 0.3], [r[0] + 0.3, r[3] - 0.3]] : [s.at];
        const on = pts.filter(([x, y]) => restsOn(x, y));
        if (on.length) below++;
        rests.push(...on);
        const [hx, hy] = s.post ?? s.at;
        if ((s.ring || s.post) && heldAt(hx, hy)) {
          above++;
          holds.push([hx, hy]);
        }
      }
      // edge clips (boards without holes): the lip presses the rim along its centre line
      const clips = features.filter((f) => f.type === 'clip');
      let clipped = 0;
      for (const f of clips) {
        const on = ((f.press ?? [f.at]) as [number, number][]).filter(([x, y]) => heldAt(x, y));
        if (on.length) clipped++;
        holds.push(...on);
      }
      const tips = canTip(holds, rests);
      const how = [clipped ? `${clipped} edge clip${clipped > 1 ? 's' : ''}` : '', above ? `${above} post${above > 1 ? 's' : ''}` : ''].filter(Boolean).join(' and ');
      const heldOk = b.mounts.length ? above >= sup.length : !tips;
      if (!sup.length) push('pcb_seated', 'warn', 'PCB: no mount holes and no ledges found under it; nothing positions the board', 'pcb', 0);
      else if (!below) push('pcb_seated', 'error', 'PCB: nothing supports it from below (standoffs or ledges do not reach the board)', 'pcb', 0);
      else if (below < sup.length || !heldOk)
        push('pcb_seated', 'warn', `PCB: supported at ${below} of ${sup.length} points, held down from above at ${b.mounts.length ? above : holds.length}; the board can rattle${b.mounts.length || clips.length ? '' : ' (no holes and no edge clips)'}`, 'pcb', below);
      else if (b.mounts.length) push('pcb_seated', 'info', `PCB: sits on ${below} supports and is held down at ${above}; ${pcbVol.toFixed(3)} mm3 overlap (pegs pass the holes)`, 'pcb', below);
      else push('pcb_seated', 'info', `PCB: sits on ${below} ledges and is held down by ${how}`, 'pcb', below);

      // retained: no line to tip it up about, and (without holes, where no pegs locate it) no room to slide
      const play = b.mounts.length ? null : slide();
      const loose = !!play && Math.max(play.x, play.y) > LOOSE;
      const slides = play ? `slides ${play.x.toFixed(2)} mm along x and ${play.y.toFixed(2)} mm along y` : '';
      const held = above + clipped; // posts and clips that reach the board
      let msg: string;
      if (!holds.length) msg = `PCB: nothing holds it down from above, it lifts off its ${b.mounts.length ? 'standoffs' : 'ledges'}${b.mounts.length ? '; hold-down posts must reach the board' : clips.length ? '; the edge clips do not reach the rim' : '; no edge clips fit (or clips: none)'}`;
      else if (tips) msg = `PCB: held down by ${how}, all on one side of it: it can tip up about a line through them; hold it on the other side too`;
      else if (loose) msg = `PCB: held down by ${how} but it ${slides} (${LOOSE} mm at most): add fences beside it or less clear`;
      else msg = b.mounts.length
        ? `PCB: held down by ${how} over its ${b.mounts.length} mount holes; ${[...new Set(features.filter((f) => f.type === 'mount').map((f) => `${f.kind}s`))].join(' and ') || 'they'} locate it`
        : `PCB: held down by ${how}; it ${slides}`;
      push('board_retained', held && !tips && !loose ? 'info' : 'warn', msg, 'pcb', held);
    }

    // --- buttons: a ray straight up from the actuator must meet the plunger within a small gap
    for (const c of b.comps.filter((c) => c.access === 'press')) {
      const over = coveredBy(b, c);
      if (over) {
        push('button_unreachable', 'error', `${c.id}: under ${over.id}: the module covers the button, nothing in the lid reaches it; move the button or the module`, c.id, null);
        continue;
      }
      if (c.side === 'bottom' || (c.normal?.[2] ?? 1) <= 0.5) {
        push('button_unreachable', 'warn', `${c.id}: a ${c.side === 'bottom' ? 'bottom' : 'side'} button has no actuator through the case yet; it stays reachable only with the lid off`, c.id, null);
        continue;
      }
      const [cx, cy] = centre(c);
      const top = at([cx, cy, c.box.max[2]]);
      const hit = firstHit(add(top, 0.001, [0, 0, 1]), add(top, 40, [0, 0, 1]));
      const gap = hit ? hit.position[2] - top[2] : null;
      const f = features.find((f) => f.type === 'flex_button' && f.for === c.id);
      if (!f && features.some((f) => f.type === 'buttons_off')) {
        push('button_unreachable', 'warn', `${c.id}: no plunger (buttons: 'none'); press it with the lid off`, c.id, gap === null ? null : r3(gap), 'mm');
        continue;
      }
      // the tongue must be free: vertical rays through its slots must pass the lid
      let blocked = 0;
      if (f && report) {
        const dv = ({ '+y': [0, 1], '-y': [0, -1], '+x': [1, 0], '-x': [-1, 0] } as Record<string, number[]>)[f.dir];
        const w = [-dv[1], dv[0]], half = (f.width ?? 5) / 2 + 0.4;
        const pts: [number, number][] = [[cx - dv[0] * 2.0, cy - dv[1] * 2.0]];
        for (const t of [0.2, 0.5, 0.8]) for (const s of [-1, 1]) pts.push([cx + dv[0] * (t * f.len - 1.6) + w[0] * s * half, cy + dv[1] * (t * f.len - 1.6) + w[1] * s * half]);
        const z0 = report.zTop + dz - 0.3, z1 = report.zTop + dz + report.lidT + 0.3;
        blocked = pts.filter(([x, y]) => shell.rayCast([x + P[0], y + P[1], z0], [x + P[0], y + P[1], z1]).length).length;
      }
      const strain = f?.strain ?? null;
      const okGap = gap !== null && gap > 0.1 && gap < 0.8;
      const ok = okGap && blocked === 0 && (strain === null || strain < 0.02);
      const tongue = f ? `, tongue ${f.len} mm ${blocked ? `NOT free (${blocked} slot rays blocked)` : 'free'}, bending strain ${(strain! * 100).toFixed(2)} % (PLA limit ~2 %)` : '';
      push(ok ? 'button_reach' : 'button_unreachable', ok ? 'info' : 'error',
        `${c.id}: plunger ${gap === null ? 'missing' : gap.toFixed(2) + ' mm above the button'}${tongue}`, c.id, gap === null ? null : r3(gap), 'mm');
    }

    // --- key switches: a plate at the height the switch clips at, its cut-out open, nothing in the way, the cap free to travel
    for (const c of b.comps.filter((c) => c.access === 'key')) {
      const over = coveredBy(b, c);
      const f = features.find((f) => f.type === 'key_plate' && f.for === c.id);
      if (over || !f) {
        push('key_plate', 'error', `${c.id}: ${over ? `under ${over.id}: the module covers the key switch` : 'no plate in the lid'}; move the key or the module`, c.id, null);
        continue;
      }
      const [cx, cy] = centre(c);
      const z0 = (report?.zTop ?? 0) + dz;
      const blocked = shell.rayCast([cx + P[0], cy + P[1], f.plate_z + dz - f.plate_t - 0.2], [cx + P[0], cy + P[1], z0 + (report?.lidT ?? 2) + 30]).length > 0;
      const why = [...(blocked ? ['the cut-out is blocked'] : []), ...(f.under.length ? [`${f.under.join(', ')} under its plate`] : []), ...f.posts,
        ...(f.outside ? ['its well runs into the case wall: give the board more room around the keys'] : [])];
      if (why.length) push('key_plate', 'error', `${c.id}: ${why.join('; ')}: move the key or the part in the way`, c.id, null);
      else if (f.stem === 'panel') push('key_plate', 'info', `${c.id}: a ${f.cut} mm hole in the lid holds it, ${r3(c.box.max[2] - c.box.min[2])} mm of body under it`, c.id, null);
      else if (f.stem === 'shaft') {
        if (f.rise < 3) push('key_plate', 'warn', `${c.id}: its shaft stands only ${f.rise} mm above the lid: a knob barely grips it; a taller shaft or a lower case`, c.id, f.rise, 'mm');
        else push('key_plate', 'info', `${c.id}: it comes ${f.rise} mm through a ${f.cut} mm hole in the lid`, c.id, f.rise, 'mm');
      } else if (f.rise < f.travel * 0.5) push('key_plate', 'warn', `${c.id}: the keycap stands only ${f.rise} mm above the lid (travel ${f.travel} mm): it sinks into its well when pressed; a lower case (shorter module or display stack) shows more of it`, c.id, f.rise, 'mm');
      else push('key_plate', 'info', `${c.id}: plate ${f.plate_t} mm at z ${f.plate_z}, cut-out ${f.cut} mm open, keycap ${f.rise} mm above the lid, ${f.travel} mm travel`, c.id, f.rise, 'mm');
    }

    // --- lights: open window, or a skin thin enough to glow through
    const featFor = (type: string, id: string) => features.find((f) => f.type === type && f.for === id);
    for (const c of b.comps.filter((c) => c.access === 'light' && c.side !== 'bottom')) {
      const blocked = featFor('light', c.id)?.blocked, over = coveredBy(b, c);
      if (over) {
        push('light_window', 'error', `${c.id}: under ${over.id}: the module hides the LED; move the LED or the module`, c.id, null);
        continue;
      }
      if (blocked) {
        push('light_window', 'error', `${c.id}: no light window: ${blocked} is over the LED; move the LED or that feature`, c.id, null);
        continue;
      }
      const [cx, cy] = centre(c);
      const top = at([cx, cy, c.box.max[2] + 0.01]);
      const hits = shell.rayCast(top, [top[0], top[1], sb.max[2] + 5]) as { position: V3 }[];
      const skin = hits.length >= 2 ? hits[1].position[2] - hits[0].position[2] : hits.length ? 99 : 0;
      push('light_window', !hits.length || skin <= 0.6 ? 'info' : 'warn', `${c.id}: ${hits.length ? `skin ${skin.toFixed(2)} mm over the LED${skin > 0.6 ? ' (too thick to see it)' : ''}` : 'open window'}`, c.id, r2(skin), 'mm');
    }

    // --- sensor and display windows: rays straight up from the part (or the module's top) at the window's centre and a
    // third of the way to its sides must leave the case; a display module must also be held down onto its header (the
    // lid or a rim from it within 0.8 mm over the module where lib.elec says it presses)
    const upHits = (x: number, y: number, z: number) => shell.rayCast(at([x, y, z]), [x + P[0], y + P[1], sb.max[2] + 5]) as { position: V3 }[];
    const openUp = (x: number, y: number, z: number) => !upHits(x, y, z).length;
    const windowCheck = (code: FindingCode, id: string, what: string, c: { box: Box3 }, display: boolean) => {
      const f = featFor(code, id);
      if (f?.blocked) return push(code, 'error', `${id}: no ${what} window: ${f.blocked} is in the way; move the part or that feature`, id, 0, 'mm');
      const [cx, cy] = [(c.box.min[0] + c.box.max[0]) / 2, (c.box.min[1] + c.box.max[1]) / 2];
      const [wx, wy] = f?.at ?? [cx, cy], ww = f?.w ?? c.box.max[0] - c.box.min[0], wd = f?.d ?? c.box.max[1] - c.box.min[1], z = c.box.max[2] + 0.01;
      const pts = [[wx, wy], [wx - ww / 3, wy], [wx + ww / 3, wy], [wx, wy - wd / 3], [wx, wy + wd / 3]];
      const shut = pts.filter(([x, y]) => !openUp(x, y, z)).length;
      const size = f?.shape === 'round' ? `round ${what} window ${r2(ww)} mm` : `${what} window ${r2(ww)} x ${r2(wd)} mm`;
      if (shut) return push(code, 'error', `${id}: ${shut === pts.length ? `no ${what} window in the lid over it` : `the ${what} window over it is partly covered (${shut} of ${pts.length} rays blocked)`}`, id, shut === pts.length ? 0 : r2(Math.min(ww, wd)), 'mm');
      let held = '', sev: Finding['severity'] = f?.shrunk ? 'warn' : 'info';
      if (display) {
        const press = (f?.press ?? []) as [number, number][];
        const on = press.filter(([x, y]) => {
          const h = upHits(x, y, z)[0];
          return !!h && h.position[2] - at([x, y, z])[2] <= 0.8;
        }).length;
        held = on ? `; held down onto its header by the lid${f?.rim ? ` rim (${f.rim.h} mm)` : ''} at ${on} of ${press.length} sides` : '; nothing holds it down but its header';
        if (!on) sev = 'warn';
      }
      push(code, sev, `${id}: ${size} open${f?.shrunk ? `, made smaller to keep off ${f.shrunk}` : ''}${held}`, id, r2(Math.min(ww, wd)), 'mm');
    };
    for (const c of b.comps.filter((c) => c.access === 'sensor' || c.access === 'display')) {
      const code: FindingCode = c.access === 'sensor' ? 'sensor_window' : 'display_window', over = coveredBy(b, c);
      if (c.side === 'bottom') push(code, 'warn', `${c.id}: a ${c.access} on the bottom side gets no opening in the case`, c.id, null);
      else if (over) push(code, 'error', `${c.id}: under ${over.id}: the module covers the ${c.access}; move one of them`, c.id, 0, 'mm');
      else windowCheck(code, c.id, c.access, c, false);
    }
    for (const a of b.accs.filter((a) => a.box && (a.window || a.kind === 'display')))
      windowCheck(a.kind === 'display' ? 'display_window' : 'sensor_window', a.id, a.kind === 'display' ? 'display' : 'sensor', { box: a.box! }, a.kind === 'display');

    // --- sound grilles: the holes lib.elec reports (else a 1 mm grid over the part), each open straight up from its top
    for (const c of b.comps.filter((c) => c.access === 'sound')) {
      if (c.side === 'bottom') {
        push('sound_grille', 'warn', `${c.id}: a buzzer on the bottom side gets no grille in the case`, c.id, null);
        continue;
      }
      const f = featFor('sound_grille', c.id), over = coveredBy(b, c);
      if (over) {
        push('sound_grille', 'warn', `${c.id}: under ${over.id}: no grille over the buzzer, its sound leaves round the module`, c.id, 0);
        continue;
      }
      if (f?.blocked) {
        push('sound_grille', 'error', `${c.id}: no sound grille: ${f.blocked} is over the buzzer; move it or that feature`, c.id, 0);
        continue;
      }
      const z = c.box.max[2] + 0.01, grid: [number, number][] = [];
      if (!f) for (let x = c.box.min[0] + 0.5; x < c.box.max[0]; x += 1) for (let y = c.box.min[1] + 0.5; y < c.box.max[1]; y += 1) grid.push([x, y]);
      const holes = (f?.holes ?? grid) as [number, number][];
      const open = holes.filter(([x, y]) => openUp(x, y, z)).length;
      push('sound_grille', open >= 5 ? (f?.shrunk ? 'warn' : 'info') : 'error',
        f ? `${c.id}: ${open} of ${holes.length} grille holes (${f.d} mm, ${f.pitch} mm pitch) open over it${f.shrunk ? `; the ones over ${f.shrunk} left out` : ''}`
          : `${c.id}: ${open ? `only ${open} open points of a 1 mm grid over it` : 'no sound grille over it'}${open >= 5 ? '' : '; the buzzer is muffled'}`, c.id, open);
    }

    // --- cable exits: rays along the cable from inside the tie block out through the wall, at its axis and its rim
    for (const a of b.accs.filter((a) => a.mount === 'cable')) {
      const f = featFor('cable_exit', a.id);
      if (!f?.inside) {
        push('cable_exit', 'error', `${a.id}: no cable exit for it${f?.blocked ? `: ${f.blocked}` : ' in the case'}; the cable must leave through a wall`, a.id, null);
        continue;
      }
      const n = EDGE_NORMAL[f.edge as BoardEdge], u: V3 = n[0] !== 0 ? [0, 1, 0] : [1, 0, 0], from = at(f.inside as V3), rc = Math.max(0.3, (a.cable_d ?? 4) / 2 - 0.05);
      const shut = [[0, 0], [rc, 0], [-rc, 0], [0, rc], [0, -rc]].filter(([s, zz]) => {
        const p = add(add(from, s, u), zz, [0, 0, 1]);
        return !!firstHit(p, add(p, RAY_LEN, n));
      }).length;
      push('cable_exit', shut ? 'error' : 'info', shut
        ? `${a.id}: a ${a.cable_d ?? 4} mm cable does not pass the ${f.d} mm exit in the ${f.edge} wall (${shut} of 5 rays blocked)`
        : `${a.id}: ${f.d} mm cable exit in the ${f.edge} wall at ${f.at} mm, ${f.z} mm over the board bottom${f.relief === 'tie slot' ? ', a zip-tie slot behind it takes the pull' : ', no strain relief'}${f.moved ? `; moved ${f.moved} mm along the wall off a port window` : ''}`,
        a.id, f.d, 'mm');
    }

    // --- loose cells: the box lib.elec reserved must be clear of the case and of the board (its header pins under it)
    for (const a of b.accs.filter((a) => a.mount === 'inside')) {
      const f = featFor('battery', a.id);
      if (!f?.box) {
        push('battery_space', 'error', `${a.id}: no room for it in the case${f?.blocked ? `: ${f.blocked}` : ''}`, a.id, null);
        continue;
      }
      const q = f.box as Box3, box = M.cube([q.max[0] - q.min[0], q.max[1] - q.min[1], q.max[2] - q.min[2]]).translate(at(q.min));
      const pins = boardGhost(wasm, b, { bottomPins: true }).translate(P);
      const inCase = vol(box.intersect(shell)), inBoard = vol(box.intersect(pins));
      // room over it (the header pins of the board above, or the lid bars): rays up from its top, centre and quarters
      const above = Math.min(...[[0.5, 0.5], [0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]].map(([fx, fy]) => {
        const p = at([q.min[0] + fx * (q.max[0] - q.min[0]), q.min[1] + fy * (q.max[1] - q.min[1]), q.max[2] + 0.001]), top: V3 = [p[0], p[1], sb.max[2] + 5];
        const hits = [...(shell.rayCast(p, top) as { position: V3 }[]), ...(pins.rayCast(p, top) as { position: V3 }[])];
        return hits.length ? Math.min(...hits.map((h) => h.position[2])) - p[2] : 99;
      }));
      const [w, d, h] = f.size ?? [0, 0, 0];
      if (inCase > 0.05 || inBoard > 0.05)
        push('battery_space', 'error', `${a.id}: the ${w} x ${d} x ${h} mm cell runs ${r2(inCase)} mm3 into the case and ${r2(inBoard)} mm3 into the board`, a.id, r3(inCase + inBoard), 'mm3');
      else
        push('battery_space', 'info', `${a.id}: ${w} x ${d} x ${h} mm cell ${f.placement === 'under' ? 'under the board' : `beside the board (${f.side} side)`}, in ${f.ribs} floor ribs; ${r2(above)} mm over it to ${f.placement === 'under' ? 'the header pins' : f.hold === 'lid bars' ? 'the lid bars' : 'the lid'}`, a.id, r2(above), 'mm');
    }

    // --- how it is held and how it sits: what the case could not build (the check's only word on them)
    for (const f of features.filter((f) => (f.type === 'mounting' || f.type === 'stand') && f.blocked))
      push('mounting', 'warn', `${f.type === 'stand' ? 'stand' : `mounting ${f.kind}`}: ${f.blocked}`, 'case', null);

    // --- lid fit: the printed parts must not overlap each other
    let overlap = 0;
    for (let i = 0; i < models.length; i++) for (let j = i + 1; j < models.length; j++) overlap += vol(models[i].solid.intersect(models[j].solid));
    const hk = features.find((f) => f.type === 'snap_hooks');
    const short = features.filter((f) => f.type === 'warning').map((f) => f.text);
    push('lid_fit', overlap > 0.05 ? 'error' : short.length ? 'warn' : 'info',
      `lid vs base overlap ${overlap.toFixed(3)} mm3; ${hk ? `${hk.count} snap hooks, catch ${(hk.overhang - hk.fit).toFixed(2)} mm` : 'no snap hooks'}${short.length ? '; ' + short.join('; ') : ''}`,
      'lid', r3(overlap), 'mm3');
    if (hk) {
      const pct = hk.strain * 100;
      push('snap_strain', pct > 4 ? 'error' : pct > 2 ? 'warn' : 'info',
        `snap hooks bend ${pct.toFixed(2)} % going in (PLA ~2 %, PETG ~4 %)${pct > 1.5 ? '; print in PETG for a lid that opens often' : ''}`, 'lid', r2(pct), '%');
    }

    // --- keep-outs: no metal fasteners near antennas; how much plastic sits in the column
    for (const k of b.keepouts) {
      const screws = features.filter((f) => f.type === 'mount' && f.kind === 'screw' && f.at && f.at[0] >= k.rect[0] && f.at[0] <= k.rect[2] && f.at[1] >= k.rect[1] && f.at[1] <= k.rect[3]);
      const [z0, z1] = k.z && k.z.length >= 2 ? [k.z[0], k.z[1]] : [-15, 15];
      const col = M.cube([k.rect[2] - k.rect[0], k.rect[3] - k.rect[1], z1 - z0]).translate(at([k.rect[0], k.rect[1], z0]));
      const plastic = vol(col.intersect(shell));
      if (k.rule === 'no_metal' && screws.length) push('metal_in_keepout', 'error', `${k.id}: ${screws.length} metal screw(s) in the ${k.id} keep-out; use pegs there (mount: 'peg' or 'auto')`, k.id, screws.length);
      else if ((k.rule === 'no_material' || k.rule === 'keep_open') && plastic > 1)
        push('keepout_ok', 'warn', `${k.id}: ${plastic.toFixed(0)} mm3 of plastic where the board wants ${k.rule === 'keep_open' ? 'open space' : 'no material'}`, k.id, Math.round(plastic), 'mm3');
      else push('keepout_ok', 'info', `${k.id}: no metal; ${plastic.toFixed(0)} mm3 of plastic inside the keep-out column (walls, standoffs, lid)`, k.id, Math.round(plastic), 'mm3');
    }
    return done();
  });
}
