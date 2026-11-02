// STL and 3MF writers. The 3MF follows the Bambu/Orca project layout so that
// parts, modifiers with their own settings and filament slots survive import.
import { zipSync, strToU8 } from 'fflate';
import { meshOf } from './mesh.ts';
import type { Part } from './program.ts';
import type { Manifold } from './kernel.ts';

export function toStl(solid: Manifold): Uint8Array {
  const { positions: P, indices: I } = meshOf(solid);
  const n = I.length / 3;
  const out = new Uint8Array(84 + n * 50);
  const dv = new DataView(out.buffer);
  const header = 'formwright';
  for (let i = 0; i < header.length; i++) out[i] = header.charCodeAt(i);
  dv.setUint32(80, n, true);
  let o = 84;
  for (let f = 0; f < n; f++) {
    const a = I[f * 3] * 3, b = I[f * 3 + 1] * 3, c = I[f * 3 + 2] * 3;
    const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2];
    const vx = P[c] - P[a], vy = P[c + 1] - P[a + 1], vz = P[c + 2] - P[a + 2];
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const l = Math.hypot(nx, ny, nz) || 1;
    nx /= l; ny /= l; nz /= l;
    for (const v of [nx, ny, nz, P[a], P[a + 1], P[a + 2], P[b], P[b + 1], P[b + 2], P[c], P[c + 1], P[c + 2]]) {
      dv.setFloat32(o, v, true);
      o += 4;
    }
    o += 2;
  }
  return out;
}

const esc = (s: string) => s.replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' })[c]!);

function meshXml(solid: Manifold): string {
  const { positions: P, indices: I } = meshOf(solid);
  const v: string[] = [];
  for (let i = 0; i < P.length; i += 3) v.push(`<vertex x="${+P[i].toFixed(5)}" y="${+P[i + 1].toFixed(5)}" z="${+P[i + 2].toFixed(5)}"/>`);
  const t: string[] = [];
  for (let i = 0; i < I.length; i += 3) t.push(`<triangle v1="${I[i]}" v2="${I[i + 1]}" v3="${I[i + 2]}"/>`);
  return `<mesh><vertices>${v.join('')}</vertices><triangles>${t.join('')}</triangles></mesh>`;
}

// The package requires the production extension (components point into another model file with
// p:path), and that extension wants a p:UUID on every object, component, build and item. Stable ids
// keep the output deterministic; Bambu Studio and Orca write the same attributes.
const uuid = (kind: number, n: number) => `${n.toString(16).padStart(8, '0')}-${kind.toString(16).padStart(4, '0')}-4000-8000-000000000000`;

// 'reference' parts (the board ghost of a case) are never written: to3mf drops them.
const SUBTYPE: Record<Exclude<Part['role'], 'reference'>, string> = {
  model: 'normal_part',
  modifier: 'modifier_part',
  negative: 'negative_part',
  support_blocker: 'support_blocker',
  support_enforcer: 'support_enforcer',
};

export interface ThreeMfOptions {
  title?: string;
  // Filament slot per part name (1-based); colors map to slots in order of appearance.
  slots?: Record<string, number>;
  bedCenter?: [number, number];
  objectSettings?: Record<string, string | number | boolean>;
  projectSettings?: Record<string, unknown>;
}

export function to3mf(all: Part[], o: ThreeMfOptions = {}): Uint8Array {
  const parts = all.filter((p) => p.role !== 'reference') as (Part & { role: keyof typeof SUBTYPE })[];
  const NS = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02';
  const PNS = 'http://schemas.microsoft.com/3dmanufacturing/production/2015/06';
  const objectsPath = '/3D/Objects/object_1.model';
  // assign filament slots by distinct color unless given
  const colorSlots = new Map<string, number>();
  const slotOf = (p: Part) => {
    if (o.slots?.[p.name]) return o.slots[p.name];
    const key = p.color ?? '#default';
    if (!colorSlots.has(key)) colorSlots.set(key, colorSlots.size + 1);
    return colorSlots.get(key)!;
  };
  const subObjects = parts.map((p, i) => `<object id="${i + 1}" p:UUID="${uuid(1, i + 1)}" type="model">${meshXml(p.solid)}</object>`).join('');
  const parentId = parts.length + 1;
  const components = parts.map((_, i) => `<component p:path="${objectsPath}" objectid="${i + 1}" p:UUID="${uuid(2, i + 1)}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>`).join('');
  const [cx, cy] = o.bedCenter ?? [128, 128];
  // center the object's XY on the bed
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of parts) {
    const b = p.solid.boundingBox();
    minX = Math.min(minX, b.min[0]); minY = Math.min(minY, b.min[1]);
    maxX = Math.max(maxX, b.max[0]); maxY = Math.max(maxY, b.max[1]);
  }
  const tx = cx - (minX + maxX) / 2, ty = cy - (minY + maxY) / 2;
  const model = `<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="${NS}" xmlns:p="${PNS}" requiredextensions="p">
<metadata name="Application">Formwright</metadata>
<metadata name="Title">${esc(o.title ?? 'model')}</metadata>
<resources><object id="${parentId}" p:UUID="${uuid(1, parentId)}" type="model"><components>${components}</components></object></resources>
<build p:UUID="${uuid(3, 1)}"><item objectid="${parentId}" p:UUID="${uuid(4, 1)}" transform="1 0 0 0 1 0 0 0 1 ${tx.toFixed(4)} ${ty.toFixed(4)} 0" printable="1"/></build>
</model>`;
  const objectsModel = `<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="${NS}" xmlns:p="${PNS}" requiredextensions="p"><resources>${subObjects}</resources><build/></model>`;
  const meta = (k: string, v: unknown) => `<metadata key="${esc(k)}" value="${esc(String(v))}"/>`;
  const partsCfg = parts
    .map((p, i) => {
      const settings = Object.entries(p.settings ?? {}).map(([k, v]) => meta(k, v)).join('');
      const slot = p.role === 'model' ? meta('extruder', slotOf(p)) : '';
      return `<part id="${i + 1}" subtype="${SUBTYPE[p.role]}">${meta('name', p.name)}${meta('matrix', '1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1')}${slot}${settings}</part>`;
    })
    .join('');
  const objSettings = Object.entries(o.objectSettings ?? {}).map(([k, v]) => meta(k, v)).join('');
  const modelSettings = `<?xml version="1.0" encoding="UTF-8"?>
<config><object id="${parentId}">${meta('name', o.title ?? 'model')}${meta('extruder', 1)}${objSettings}${partsCfg}</object>
<plate>${meta('plater_id', 1)}${meta('plater_name', '')}${meta('locked', 'false')}<model_instance>${meta('object_id', parentId)}${meta('instance_id', 0)}${meta('identify_id', 1)}</model_instance></plate></config>`;
  const files: Record<string, Uint8Array> = {
    '[Content_Types].xml': strToU8(
      `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="config" ContentType="text/xml"/><Default Extension="png" ContentType="image/png"/></Types>`,
    ),
    '_rels/.rels': strToU8(
      `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>`,
    ),
    '3D/3dmodel.model': strToU8(model),
    '3D/_rels/3dmodel.model.rels': strToU8(
      `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="${objectsPath}" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>`,
    ),
    '3D/Objects/object_1.model': strToU8(objectsModel),
    'Metadata/model_settings.config': strToU8(modelSettings),
  };
  if (o.projectSettings) files['Metadata/project_settings.config'] = strToU8(JSON.stringify(o.projectSettings, null, 2));
  return zipSync(files, { level: 6 });
}

// Colors per slot, in slot order, for the slicer's filament list.
export function slotColors(parts: Part[]): string[] {
  const seen: string[] = [];
  for (const p of parts) if (p.role === 'model' && p.color && !seen.includes(p.color)) seen.push(p.color);
  return seen;
}
