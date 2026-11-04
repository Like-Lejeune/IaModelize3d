// What a device document says beyond its wiring, read the same way across the device UI: what the case does over a part
// (node.face, else its kind's default as the server resolves it), who put a part where it stands on the board (the
// person's `pcb`, the designer's `place` or one of its layouts, else the build), the requirements a part serves, and
// the design checks sorted into errors and warnings (normalize's issues, lint, device_rules). Types only from ./api, so
// node --test runs it as is.
import type { Accessory, DevLayout, DevNode, DevRequirement, DeviceDoc, DeviceState, Face, Issue, Library, PartBits } from './api';

export const FACES: Face[] = ['light', 'sound', 'sensor', 'display', 'none'];
export const FACE_ICON: Record<Face, string> = { light: 'ti-bulb', sound: 'ti-volume', sensor: 'ti-eye', display: 'ti-device-desktop', none: '' };

// the defaults of fw.device/1 node.face (C1c), for a part whose card the server has not resolved a face for
const SOUND = /buzzer|speaker|piezo|sounder|transducer/i;
const SENSOR = /\bPIR\b|pyroelectric|human body sens|ambient light|light (sensor|intensity)|photo ?(diode|transistor|resistor|sensitive)|\bUV\b|colou?r sensor|\bgas\b|air quality|\bVOC\b|\bCO2\b|humidity|microphone/i;
const LIGHT = /\bLEDs?\b|\bRGB|WS281|SK681|APA10|neopixel/i;
const NOT = /opto|photocoupler|LED driver/i;

/** The face a part gets: the server's resolved one, the node's own, else the default for its kind and card. */
export function faceOf(node: DevNode, part?: PartBits, acc?: Accessory | null, resolved?: Face): Face {
  if (node.face) return node.face;
  if (resolved) return resolved;
  return autoFace(node, part, acc);
}

export function autoFace(node: DevNode, part?: PartBits, acc?: Accessory | null): Face {
  if (node.kind === 'led') return 'light';
  if (node.kind === 'accessory') return acc?.kind === 'display' || acc?.window ? 'display' : acc?.kind === 'sensor' && acc.mount === 'board' ? 'sensor' : 'none';
  if (node.kind !== 'chip') return 'none';
  const text = [part?.category, part?.description, part?.mpn, node.label].filter(Boolean).join(' ');
  if (part?.kind_hint === 'buzzer_active' || part?.kind_hint === 'buzzer_passive' || SOUND.test(text)) return 'sound';
  if (NOT.test(text)) return 'none';
  if (part?.kind_hint === 'led' || part?.kind_hint === 'rgb_led') return 'light';
  if (SENSOR.test(text)) return 'sensor';
  if (LIGHT.test(text)) return 'light';
  return 'none';
}

/** Kinds whose face the person may change: what can shine, sound, sense or show through the lid. */
export const FACE_KINDS = ['led', 'chip', 'accessory'];

/** The layout a node is laid out in by the designer, and its place in the pattern (0-based). */
export function layoutOf(doc: DeviceDoc | null | undefined, id: string): { layout: DevLayout; index: number } | null {
  for (const l of doc?.layouts ?? []) {
    const i = (l.nodes ?? []).indexOf(id);
    if (i >= 0) return { layout: l, index: i };
  }
  return null;
}

/** Who decided where a part stands on the board: the person (pcb wins), the designer (place or a layout), the build. */
export function placedBy(doc: DeviceDoc | null | undefined, node: DevNode | undefined): 'person' | 'designer' | 'build' {
  if (!node) return 'build';
  if (node.pcb) return 'person';
  if (node.place || layoutOf(doc, node.id)) return 'designer';
  return 'build';
}

export function requirementsOf(doc: DeviceDoc | null | undefined, id: string): DevRequirement[] {
  return (doc?.requirements ?? []).filter((r) => (r.parts ?? []).includes(id));
}

const RANK = { error: 2, warning: 1, info: 0 } as const;
/** Every check on the document, each once, as errors (what makes the device wrong) and warnings (for the designer to
 *  weigh). normalize's and resolve's issues are errors unless they say otherwise (a pin or part that could not be read
 *  is a hole in the design); lint is warnings; device_rules carry their own severity. */
export function sortChecks(s: DeviceState | null | undefined): { errors: Issue[]; warnings: Issue[] } {
  const seen = new Map<string, Issue>();
  const add = (list: Issue[] | undefined, fallback: 'error' | 'warning') => {
    for (const i of list ?? []) {
      const sev = i.severity ?? fallback;
      if (sev === 'info') continue;
      const key = `${i.code}|${i.ref}`;
      const had = seen.get(key);
      if (!had || RANK[sev] > RANK[had.severity ?? 'warning']) seen.set(key, { ...i, severity: sev });
    }
  };
  add(s?.issues, 'error');
  add(s?.lint, 'warning');
  add(s?.rules, 'warning');
  const all = [...seen.values()];
  return { errors: all.filter((i) => i.severity === 'error'), warnings: all.filter((i) => i.severity !== 'error') };
}

/** The node a check is about ('U1.GPIO2' → 'U1'). */
export const refNode = (ref: string | undefined) => String(ref ?? '').split('.')[0];

/** A size in mm, one decimal at most: [77.86, 74, 24.6] → '77.9 × 74 × 24.6'. */
export const sizeText = (s: number[] | null | undefined) => (s?.length ? s.map((v) => String(+Number(v).toFixed(1))).join(' × ') : '');

/** The library's accessories as a list with their keys, whichever shape the server sent. */
export function accessoriesOf(lib: Library | null | undefined): Accessory[] {
  const a = lib?.accessories;
  if (!a) return [];
  if (Array.isArray(a)) return a.map((x) => ({ ...x, key: x.key ?? (x as { accessory?: string }).accessory ?? x.name }));
  return Object.entries(a).map(([key, x]) => ({ ...x, key }));
}
