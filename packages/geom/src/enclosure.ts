// check_enclosure: does the case hold the board it was built around? Pure function over the parts of
// an assembled build (base, lid and the board ghost as a 'reference' part from lib.elec.parts) and the
// fw.board/1 JSON. Plug paths are a grid of rays over the plug's rounded section (the clearance is found
// by bisection on how far that section can grow), then part and PCB collisions, supports, hold-downs
// (can the board tip up or slide: board_retained), button reach, LED windows, lid fit, snap strain and
// keep-outs. Manifold.rayCast returns `distance` as a fraction of
// the segment, so everything here works with hit positions.
import type { Manifold, Wasm } from './kernel.ts';
import { withArena } from './kernel.ts';
import { boardGhost, boardModel, type BoardModel, type BoardPart, type BoardSpec, type EnclosureReport } from './lib/elec.ts';
import type { Part } from './program.ts';

type V3 = [number, number, number];

export type FindingCode =
  | 'port_clear' | 'port_blocked' | 'component_clear' | 'board_collision' | 'pcb_seated' | 'board_retained' | 'button_reach'
  | 'button_unreachable' | 'light_window' | 'lid_fit' | 'snap_strain' | 'metal_in_keepout' | 'keepout_ok';

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
    const done = () => ({ findings, rays, clearance, ms: Math.round(performance.now() - t0) });

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
    const shell = models.length === 1 ? models[0].solid : M.union(models.map((p) => p.solid));
    const sb = shell.boundingBox();
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

    // --- collisions: every component box and the PCB against the case
    for (const c of b.comps.filter((c) => c.box.max[2] - c.box.min[2] > 0.05)) {
      const box = M.cube([c.box.max[0] - c.box.min[0], c.box.max[1] - c.box.min[1], c.box.max[2] - c.box.min[2]]).translate(at(c.box.min));
      const inside = vol(box.intersect(shell));
      const gap = box.minGap(shell, 3);
      if (inside > 0.01) push('board_collision', 'error', `${c.id}: ${inside.toFixed(2)} mm3 of it is inside the case`, c.id, r3(inside), 'mm3');
      else push('component_clear', gap < 0.15 ? 'warn' : 'info', `${c.id}: nearest wall ${gap.toFixed(2)} mm`, c.id, r3(gap), 'mm');
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

    // --- lights: open window, or a skin thin enough to glow through
    for (const c of b.comps.filter((c) => c.access === 'light' && c.side !== 'bottom')) {
      const [cx, cy] = centre(c);
      const top = at([cx, cy, c.box.max[2] + 0.01]);
      const hits = shell.rayCast(top, [top[0], top[1], sb.max[2] + 5]) as { position: V3 }[];
      const skin = hits.length >= 2 ? hits[1].position[2] - hits[0].position[2] : hits.length ? 99 : 0;
      push('light_window', !hits.length || skin <= 0.6 ? 'info' : 'warn', `${c.id}: ${hits.length ? `skin ${skin.toFixed(2)} mm over the LED${skin > 0.6 ? ' (too thick to see it)' : ''}` : 'open window'}`, c.id, r2(skin), 'mm');
    }

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
