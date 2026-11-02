// node --test web/test/steps.test.ts: a version step of a case keeps its check against the board in the other UI language.
// steps.ts imports './i18n.svelte' (a rune module): the hook adds the .ts that Vite adds, and $state is a plain value here.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

register(
  'data:text/javascript,' +
    encodeURIComponent('export async function resolve(s, c, next) { return next(s.endsWith("/i18n.svelte") ? s + ".ts" : s, c); }'),
);
(globalThis as any).$state = (v: unknown) => v;
const { resultTitle, parseSummary } = await import('../src/lib/steps.ts');
const { i18n } = await import('../src/lib/i18n.svelte.ts');

const PARAMS = Object.fromEntries(Array.from({ length: 30 }, (_, i) => [`param_${i}`, i * 1.5]));
const BRIEF_OK = { ok: true, version: 3, summary: { usb_clearance_mm: 0.29, button_gap_mm: 0.3, snap_strain_pct: 1.67 }, errors: [], warnings: [] };

/** A build result the way tools.py writes it (case_fit right after printable), cut at 600 characters as loop.py does. */
function summary(caseFit: Record<string, unknown> | null, enclosure: Record<string, unknown> = BRIEF_OK): string {
  const r: Record<string, unknown> = { ok: true, version: 3, size_mm: [65.7, 56, 8.9], volume_mm3: 9100, est_grams: 10.9, printable: true };
  if (caseFit) r.case_fit = caseFit;
  Object.assign(r, { score: 100, issues: [{ code: 'overhang', severity: 'warn', msg: 'a short overhang under the lid lip' }], params: PARAMS, enclosure });
  return JSON.stringify(r).slice(0, 600);
}

function title(lang: 'en' | 'ru', s: string, server: string): string | undefined {
  i18n.lang = lang;
  return resultTitle('edit_program', {}, s, true, server);
}

test('a case that fits keeps the verdict in RU, as the EN step says it', () => {
  const s = summary({ fits: true, usb_clearance_mm: 0.29 });
  assert.equal(s.length, 600);
  assert.ok(!s.includes('"enclosure"'), 'the brief itself is past the cut');
  const en = 'Version 3 — 65.7 × 56 × 8.9 mm, printable; fits the board, USB 0.29 mm';
  assert.equal(title('ru', s, en), 'Версия 3 — 65.7 × 56 × 8.9 мм, печатается; плата влезает, USB 0.29 мм');
  assert.equal(title('en', s, en), en, 'the server title in the UI language wins');
  assert.equal(title('en', s, 'Версия 3 — 65.7 × 56 × 8.9 мм, печатается; плата влезает, USB 0.29 мм'), en);
});

test('a case that does not fit yet names its problems in the other language', () => {
  const s = summary({ fits: false, problems: [{ code: 'button_reach', part: 'BOOTSEL', value: 1.2 }], usb_clearance_mm: 0.29 });
  assert.equal(
    title('ru', s, 'Version 2 — 65.7 × 56 × 8.9 mm, printable; does not fit the board yet: BOOTSEL button out of reach'),
    'Версия 3 — 65.7 × 56 × 8.9 мм, печатается; плата пока не влезает: BOOTSEL не нажимается',
  );
  const many = summary({ fits: false, problems: Array.from({ length: 6 }, (_, i) => ({ code: 'port_blocked', part: `J${i}` })), more: 2 });
  assert.match(title('en', many, 'Версия 3')!, /; does not fit the board yet: J0 plug blocked, J1 plug blocked, \+6 more$/);
});

test('an engine failure of the check, and old runs without the verdict', () => {
  assert.match(title('ru', summary({ ran: false }), 'Version 3 — …')!, /; проверка корпуса не запустилась$/);
  // recorded before the verdict existed: today's text, no suffix
  assert.equal(title('ru', summary(null), 'Version 3 — 65.7 × 56 × 8.9 mm, printable; fits the board, USB 0.29 mm'), 'Версия 3 — 65.7 × 56 × 8.9 мм, печатается');
});

test('a whole summary reads the brief itself; a nested ok is not the step failing', () => {
  const whole = JSON.stringify({ ok: true, version: 4, size_mm: [30, 20, 10], printable: true, enclosure: { ...BRIEF_OK, ok: false, errors: [{ code: 'lid_fit' }] } });
  assert.equal(title('ru', whole, 'Version 4 — …'), 'Версия 4 — 30 × 20 × 10 мм, печатается; плата пока не влезает: крышка не садится');
  // cut, with the brief's "ok": false inside the 600 characters
  const cut = JSON.stringify({ ok: true, version: 5, size_mm: [30, 20, 10], printable: true, case_fit: { fits: false, problems: [{ code: 'lid_fit' }] },
    enclosure: { ok: false, summary: {}, errors: [{ code: 'lid_fit', msg: 'x'.repeat(600) }] } }).slice(0, 600);
  assert.equal(parseSummary(cut)?.ok, undefined);
  assert.equal(title('en', cut, 'Версия 5'), 'Version 5 — 30 × 20 × 10 mm, printable; does not fit the board yet: the lid does not fit');
  assert.equal(parseSummary('{"ok": false, "error": "boom"')?.ok, false);
});

test('a PCB case step (make_enclosure) keeps its verdict in RU from a cut summary', () => {
  const en = 'Case v1 — 111.7 × 115 × 15.5 mm, printable; fits the board, USB 0.29 mm';
  const r: Record<string, unknown> = { ok: true, version: 1, size_mm: [111.7, 115, 15.5], volume_mm3: 19020, est_grams: 23.6, printable: true };
  const cut = (fit: Record<string, unknown> | null) =>
    JSON.stringify({ ...r, ...(fit ? { case_fit: fit } : {}), score: 100, issues: [], params: PARAMS, pcb_version: 1, mockup: true, enclosure: BRIEF_OK }).slice(0, 600);
  i18n.lang = 'ru';
  assert.equal(resultTitle('make_enclosure', { version: 1 }, cut({ fits: true, usb_clearance_mm: 0.29 }), true, en), 'Корпус v1 — на столе 111.7 × 115 × 15.5 мм, печатается; плата влезает, USB 0.29 мм');
  // recorded before the verdict came up front: today's text, no suffix
  assert.equal(resultTitle('make_enclosure', { version: 1 }, cut(null), true, en), 'Корпус v1 — на столе 111.7 × 115 × 15.5 мм, печатается');
  // the size is the print plate's (a 44 × 52 mm board's case lies there in parts): an English title stored before
  // the server said so says it too, and a new one is left as it is
  i18n.lang = 'en';
  assert.equal(resultTitle('make_enclosure', { version: 1 }, cut(null), true, en), 'Case v1 — print plate 111.7 × 115 × 15.5 mm, printable; fits the board, USB 0.29 mm');
  const now = 'Case v1 for PCB v2 — print plate 111.7 × 115 × 15.5 mm, printable';
  assert.equal(resultTitle('make_enclosure', {}, cut(null), true, now), now);
});

// export_fab and make_enclosure as pcb_tools writes them: the counts and the board's version come before the long links and
// the params, so a summary cut at 600 characters still has them; older runs had them past the cut and keep today's text
const PCB = 'p_29f7492139554ffc';
const FAB_FILES = Object.fromEntries(
  ['gerbers.zip', 'bom.csv', 'cpl.csv', 'pcb_top.svg', 'pcb_bottom.svg', 'schematic.svg', 'board.glb'].map((n) => [n, `/api/projects/${PCB}/pcb/1/${n}`]),
);
const LAYERS = ['board-NPTH.DRL', 'board.DRL', 'board.GBL', 'board.GBO', 'board.GBP', 'board.GBS', 'board.GML', 'board.GTL', 'board.GTO', 'board.GTP', 'board.GTS'];
const UNVERIFIED = ['LCSC part numbers are as written in the circuit, not checked against the catalogue', 'CPL rotations are not yet checked against JLCPCB\'s placement preview'];

test('a RU rebuild of export_fab keeps its layer and line counts', () => {
  const en = 'Fab files for PCB v1: Gerber zip (11 layers), BOM (9 lines), CPL (11 lines)';
  const cut = JSON.stringify({ ok: true, version: 1, bom_lines: 9, cpl_lines: 11, layers: LAYERS, files: FAB_FILES, unverified: UNVERIFIED }).slice(0, 600);
  i18n.lang = 'ru';
  assert.equal(resultTitle('export_fab', {}, cut, true, en), 'Файлы для фабрики, плата v1: Gerber zip (11 слоёв), BOM (9 строк), CPL (11 строк)');
  i18n.lang = 'en';
  assert.equal(resultTitle('export_fab', {}, cut, true, 'Файлы для фабрики, плата v1: Gerber zip (11 слоёв), BOM (9 строк), CPL (11 строк)'), en);
  // recorded with the links first: the counts were cut off, so today's text
  const old = JSON.stringify({ ok: true, version: 1, files: FAB_FILES, layers: LAYERS, bom_lines: 9, cpl_lines: 11, unverified: UNVERIFIED }).slice(0, 600);
  assert.ok(!old.includes('"bom_lines"'));
  i18n.lang = 'ru';
  assert.equal(resultTitle('export_fab', {}, old, true, en), 'Файлы для фабрики, плата v1: Gerber zip, BOM, CPL');
});

test('a RU rebuild of make_enclosure keeps the board version the call did not name', () => {
  const head = { ok: true, version: 1 };
  const rest = { size_mm: [111.7, 115, 15.5], volume_mm3: 19020, est_grams: 23.6, printable: true, case_fit: { fits: true, usb_clearance_mm: 0.29 } };
  const tail = { score: 100, issues: [], params: PARAMS, mockup: true, enclosure: BRIEF_OK };
  const en = 'Case v1 for PCB v1 — 111.7 × 115 × 15.5 mm, printable; fits the board, USB 0.29 mm';
  i18n.lang = 'ru';
  const cut = JSON.stringify({ ...head, pcb_version: 1, ...rest, ...tail }).slice(0, 600);
  assert.equal(resultTitle('make_enclosure', {}, cut, true, en), 'Корпус v1 для платы v1 — на столе 111.7 × 115 × 15.5 мм, печатается; плата влезает, USB 0.29 мм');
  // the call named the version: its own line says it, the result does not repeat it
  assert.equal(resultTitle('make_enclosure', { version: 1 }, cut, true, en), 'Корпус v1 — на столе 111.7 × 115 × 15.5 мм, печатается; плата влезает, USB 0.29 мм');
  // recorded with pcb_version after the params: cut off, so today's text
  const old = JSON.stringify({ ...head, ...rest, ...tail, pcb_version: 1 }).slice(0, 600);
  assert.equal(resultTitle('make_enclosure', {}, old, true, en), 'Корпус v1 — на столе 111.7 × 115 × 15.5 мм, печатается; плата влезает, USB 0.29 мм');
});
