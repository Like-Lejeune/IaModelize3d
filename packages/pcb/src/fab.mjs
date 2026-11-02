// Fabrication files: Gerber + Excellon zip, BOM and pick-and-place in JLCPCB's column layout.
// The zip uses Protel extensions (GTL, GBL, ...), which fab houses recognise without asking, and leaves out F_Fab:
// an independent parser (tracespace whats-that-gerber) took it for a drill file. Coordinates are the circuit's own
// (board centre at the origin) in Gerbers and CPL alike, so the two line up at the fab.
// LCSC numbers come from the circuit's supplierPartNumbers as written and are not checked against the catalogue
// here (the worker has no network): the BOM says so in its lcsc_verified column.
import { zipSync, strToU8 } from 'fflate';
import { convertCircuitJsonToGerberFiles } from 'circuit-json-to-gerber';
import { convertCircuitJsonToBomRows } from 'circuit-json-to-bom-csv';
import { convertCircuitJsonToPickAndPlaceRows } from 'circuit-json-to-pnp-csv';

export const PROTEL = {
  'F_Cu.gbr': 'GTL', 'B_Cu.gbr': 'GBL', 'F_SilkScreen.gbr': 'GTO', 'B_SilkScreen.gbr': 'GBO', 'F_Mask.gbr': 'GTS',
  'B_Mask.gbr': 'GBS', 'F_Paste.gbr': 'GTP', 'B_Paste.gbr': 'GBP', 'Edge_Cuts.gbr': 'GKO',
};
const DRILLS = { 'drill-L1-L2.drl': 'DRL', 'drill_npth.drl': 'NPTH.DRL' };
const SKIP = new Set(['F_Fab.gbr', 'B_Fab.gbr']);
// JLC places parts with its own zero orientation per package; corrections (degrees, added to ours) belong here once
// checked against JLC's placement preview. Until then every entry is 0 and the CPL notes it.
export const JLC_ROTATION = { '0402': 0, '0603': 0, '0805': 0, sod123: 0, sot23: 0, usbcmidmount: 0, pushbutton: 0 };
const ZIP_TIME = new Date('2026-01-01T00:00:00Z'); // fixed, so the same board gives the same zip bytes

const csvCell = (v) => {
  const s = v == null ? '' : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
const csv = (rows) => rows.map((r) => r.map(csvCell).join(',')).join('\n') + '\n';
const mm = (v) => `${(Math.round(v * 1000) / 1000).toFixed(3)}mm`;

export function gerberZip(cj, base = 'board') {
  const files = convertCircuitJsonToGerberFiles(cj);
  const entries = {};
  const layers = [];
  for (const [name, text] of Object.entries(files)) {
    if (SKIP.has(name)) continue;
    const ext = PROTEL[name] ?? DRILLS[name];
    if (!ext) continue; // an unknown layer would only confuse the fab's importer
    const out = ext === 'NPTH.DRL' ? `${base}-NPTH.DRL` : `${base}.${ext}`;
    entries[out] = [strToU8(text), { mtime: ZIP_TIME }];
    layers.push(out);
  }
  return { zip: zipSync(entries, { level: 6, mtime: ZIP_TIME }), layers: layers.sort() };
}

export async function bomCsv(cj) {
  const rows = await convertCircuitJsonToBomRows({ circuitJson: cj });
  const groups = new Map();
  for (const r of rows) {
    const lcsc = r.supplier_part_number_columns?.['JLCPCB Part #'] ?? '';
    const comment = r.comment || r.value || '';
    const key = `${comment}|${r.footprint}|${lcsc}`;
    if (!groups.has(key)) groups.set(key, { comment, footprint: r.footprint ?? '', lcsc, refs: [] });
    groups.get(key).refs.push(r.designator);
  }
  const out = [['Comment', 'Designator', 'Footprint', 'LCSC', 'lcsc_verified']];
  for (const g of groups.values()) out.push([g.comment, g.refs.join(','), g.footprint, g.lcsc, 'false']);
  return { csv: csv(out), lines: groups.size };
}

export function cplCsv(cj) {
  const rows = convertCircuitJsonToPickAndPlaceRows(cj);
  const cad = Object.fromEntries(cj.filter((e) => e.type === 'cad_component').map((c) => [c.source_component_id, c.footprinter_string ?? '']));
  const srcByName = Object.fromEntries(cj.filter((e) => e.type === 'source_component').map((s) => [s.name, s.source_component_id]));
  const out = [['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation']];
  for (const r of rows) {
    const fp = cad[srcByName[r.designator]] ?? '';
    const key = Object.keys(JLC_ROTATION).find((k) => fp.replace(/^(res|cap|led)/, '').startsWith(k));
    const rot = (((r.rotation ?? 0) + (key ? JLC_ROTATION[key] : 0)) % 360 + 360) % 360;
    out.push([r.designator, mm(r.mid_x), mm(r.mid_y), r.layer === 'bottom' ? 'Bottom' : 'Top', String(rot)]);
  }
  return { csv: csv(out), lines: rows.length, rotation_checked: false };
}
