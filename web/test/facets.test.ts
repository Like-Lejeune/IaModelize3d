// node --test web/test/facets.test.ts: what the device UI reads off a document beyond its wiring: the case's face over
// a part (cards of parts from the 2026-11-03 runs: the WS2812 that got no window, the PIR, the buzzers, the S8050), who
// placed a part (the person's pcb, the designer's place or dice layout), the checks sorted into errors and warnings,
// and the BOM's lines for modules fitted by hand.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { accessoriesOf, autoFace, faceOf, layoutOf, placedBy, requirementsOf, sortChecks, sizeText } = await import('../src/lib/device/facets.ts');
const { bomOf, bomCsv } = await import('../src/lib/device/bom.ts');

const chip = (id: string) => ({ id, kind: 'chip', lcsc: 'C1' });

test('face defaults: LEDs and addressable RGB light, buzzers sound, PIR and light sensors sense, the rest closed', () => {
  assert.equal(autoFace({ id: 'LED1', kind: 'led' }), 'light');
  assert.equal(autoFace(chip('LED1'), { mpn: 'XL-5050RGBC-2812B', category: 'RGB LEDs(Built-in IC)' }), 'light');
  assert.equal(autoFace(chip('BZ1'), { mpn: 'MLT-5020', category: 'Buzzers', description: 'Electromagnetic Passive (Externally Driven) SMD' }), 'sound');
  assert.equal(autoFace(chip('BZ2'), { mpn: 'HND-2319', category: 'Buzzers', description: '90dB Active Buzzer (Built-in Driving Circuit) Piezoelectric' }), 'sound');
  assert.equal(autoFace(chip('U2'), { mpn: 'AM312', category: 'Human Body Sensing Sensor', description: 'TO-5-3 Human Body Sensing Sensor ROHS' }), 'sensor');
  assert.equal(autoFace(chip('U3'), { mpn: 'BH1750FVI-TR', category: 'Ambient Light Sensors', description: 'I2C Light Intensity WSOF-6' }), 'sensor');
  assert.equal(autoFace(chip('Q1'), { mpn: 'S8050', category: 'Bipolar (BJT)', description: '1 NPN 500mA SOT-23' }), 'none');
  assert.equal(autoFace(chip('U4'), { mpn: 'PC817', category: 'Optocouplers - Phototransistor Output' }), 'none');
  assert.equal(autoFace(chip('U5'), { mpn: 'QMA6100P', category: 'Accelerometers' }), 'none');
  assert.equal(autoFace({ id: 'R1', kind: 'resistor' }), 'none');
  // the catalogue's kind_hint settles it without words
  assert.equal(autoFace(chip('BZ3'), { kind_hint: 'buzzer_active' }), 'sound');
  // an accessory with a lid window is a display
  assert.equal(autoFace({ id: 'A1', kind: 'accessory', accessory: 'oled_096' }, {}, { key: 'oled_096', name: 'OLED', window: [22, 11] }), 'display');
  assert.equal(autoFace({ id: 'A2', kind: 'accessory', accessory: 'soil' }, {}, { key: 'soil', name: 'Soil probe', mount: 'cable' }), 'none');
});

test("a node's own face wins over the server's resolved one, which wins over the default", () => {
  const led = { id: 'LED1', kind: 'led' };
  assert.equal(faceOf(led), 'light');
  assert.equal(faceOf(led, {}, null, 'none'), 'none');
  assert.equal(faceOf({ ...led, face: 'sensor' as const }, {}, null, 'none'), 'sensor');
});

test('placement: the person’s pcb wins, then the designer’s place or layout, else the build', () => {
  const doc = {
    schema: 'fw.device/1' as const, title: 'Dice', board: {}, nets: [],
    nodes: [
      { id: 'LED1', kind: 'led' }, { id: 'LED2', kind: 'led', pcb: { x: 1, y: 2, rot: 0 } }, { id: 'SW1', kind: 'button', place: { x: 0, y: -12 } },
      { id: 'R1', kind: 'resistor' },
    ],
    layouts: [{ pattern: 'dice', nodes: ['LED1', 'LED2', 'LED3', 'LED4', 'LED5', 'LED6', 'LED7'], pitch: 8 }],
    requirements: [{ id: 'R1', text: 'Shows 1 to 6 as dice pips', parts: ['LED1', 'LED2'] }, { id: 'R2', text: 'Rolls on a press', parts: ['SW1'], firmware: true }],
  };
  const n = (id: string) => doc.nodes.find((x) => x.id === id);
  assert.equal(placedBy(doc, n('LED1')), 'designer');
  assert.equal(placedBy(doc, n('LED2')), 'person');
  assert.equal(placedBy(doc, n('SW1')), 'designer');
  assert.equal(placedBy(doc, n('R1')), 'build');
  assert.deepEqual(layoutOf(doc, 'LED2')?.index, 1);
  assert.equal(layoutOf(doc, 'SW1'), null);
  assert.deepEqual(requirementsOf(doc, 'SW1').map((r) => r.id), ['R2']);
});

test('checks: unreadable parts and rules with severity error are errors, lint warnings, each once', () => {
  const s = {
    issues: [{ code: 'bad_pin', ref: 'BZ1.P_2', msg: 'BZ1 has no pin P_2' }],
    lint: [
      { code: 'decoupling', ref: 'BZ1', msg: 'BZ1 has no capacitor on its supply' },
      { code: 'led_resistor', ref: 'LED3', msg: 'LED3 has no series resistor' },
    ],
    rules: [
      { code: 'led_resistor', ref: 'LED3', msg: 'LED3 without a resistor burns out', severity: 'error' as const, hint: 'add 1k' },
      { code: 'gpio_current', ref: 'BZ1', msg: '30 mA from a GPIO', severity: 'warning' as const },
      { code: 'note', ref: 'U1', msg: 'fine', severity: 'info' as const },
    ],
  };
  const { errors, warnings } = sortChecks(s as any);
  assert.deepEqual(errors.map((e) => `${e.code}:${e.ref}`), ['bad_pin:BZ1.P_2', 'led_resistor:LED3']);
  assert.equal(errors[1].hint, 'add 1k');
  assert.deepEqual(warnings.map((e) => e.code), ['decoupling', 'gpio_current']);
  assert.deepEqual(sortChecks(null), { errors: [], warnings: [] });
});

test('the BOM prices a module fitted by hand from its library card, as its own line', () => {
  const state = {
    version: 1, author: 'agent', building: false, pcb: null, issues: [], lint: [],
    doc: {
      schema: 'fw.device/1' as const, title: 'Soil', board: {}, nets: [],
      nodes: [{ id: 'U1', kind: 'module', module: '113991054' }, { id: 'A1', kind: 'accessory', accessory: 'oled_096', label: 'Display' }, { id: 'A2', kind: 'accessory', accessory: 'oled_096' }],
    },
    view: { power: [], nodes: { U1: { pins: [], part: { mpn: 'Seeed XIAO ESP32-C3' }, price_usd: 4.99 } } },
  };
  const accs = { oled_096: { key: 'oled_096', name: 'SSD1306 0.96" OLED module', price_usd: 2.5, url: 'https://example.com/oled' } };
  const rows = bomOf(state as any, accs);
  const oled = rows.find((r) => r.kind === 'accessory')!;
  assert.deepEqual(oled.refs, ['A1', 'A2']);
  assert.equal(oled.part, 'SSD1306 0.96" OLED module');
  assert.equal(oled.fitted, true);
  assert.equal(oled.lcsc, null);
  assert.equal(oled.sum, 5);
  assert.deepEqual(rows.map((r) => r.kind), ['module', 'accessory']);
  assert.match(bomCsv(rows), /SSD1306 0\.96"" OLED module",A1,A2|"SSD1306 0\.96"" OLED module","A1,A2"/);
});

test('the library’s accessories come as a list or as the map of keys', () => {
  assert.deepEqual(accessoriesOf({ modules: [], primitives: [] }), []);
  assert.deepEqual(accessoriesOf({ modules: [], primitives: [], accessories: { pir_am312: { name: 'PIR' } } }).map((a) => a.key), ['pir_am312']);
  assert.deepEqual(accessoriesOf({ modules: [], primitives: [], accessories: [{ key: 'lipo_500', name: 'LiPo' }] }).map((a) => a.key), ['lipo_500']);
  assert.equal(sizeText([77.86, 74, 24.6]), '77.9 × 74 × 24.6');
});
