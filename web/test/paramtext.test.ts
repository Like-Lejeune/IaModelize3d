// node --test web/test/paramtext.test.ts (Node strips the types; no build step)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { paramGroup, paramLabel, paramOption, ruLabel } from '../src/lib/paramtext.ts';

const SERVER = join(import.meta.dirname, '..', '..', 'server', 'formwright');

function pyFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (f === '__pycache__') return [];
    return statSync(p).isDirectory() ? pyFiles(p) : f.endsWith('.py') ? [p] : [];
  });
}

// every `label: '…'` / `group: '…'` in the programs the server ships (case, examples, showcase, stickers, prompt)
function shipped(field: 'label' | 'group'): Set<string> {
  const out = new Set<string>();
  const re = new RegExp(`\\b${field}: '([^']+)'`, 'g');
  for (const f of pyFiles(SERVER)) for (const m of readFileSync(f, 'utf8').matchAll(re)) out.add(m[1]);
  return out;
}

test('every shipped label and group has Russian', () => {
  const labels = shipped('label');
  const groups = shipped('group');
  for (const must of ['Wall', 'Gap around the board', 'Board mount', 'Printed stand-in for the PCB', 'Sticker size', 'Lean angle']) assert.ok(labels.has(must), must);
  for (const must of ['Shell', 'Fit', 'Access', 'Shape', 'Strength', 'Form']) assert.ok(groups.has(must), must);
  for (const l of labels) assert.ok(ruLabel(l), `no Russian for label '${l}'`);
  for (const g of groups) assert.notEqual(paramGroup(g, 'ru'), g, `no Russian for group '${g}'`);
});

test('the case program reads naturally', () => {
  const ru = (s: string) => paramLabel(s, 'ru');
  assert.equal(ru('Wall'), 'Стенка');
  assert.equal(ru('Floor'), 'Дно');
  assert.equal(ru('Lid'), 'Крышка');
  assert.equal(ru('Gap around the board'), 'Зазор вокруг платы');
  assert.equal(ru('Board mount'), 'Крепление платы');
  assert.equal(ru('Printed stand-in for the PCB'), 'Печатный макет платы');
  assert.equal(paramGroup('Shell', 'ru'), 'Корпус');
  assert.equal(paramGroup('Fit', 'ru'), 'Посадка');
  assert.equal(paramGroup('Access', 'ru'), 'Доступ');
  assert.equal(paramGroup('Strength', 'ru'), 'Прочность');
  assert.equal(paramGroup('Shape', 'ru'), 'Форма');
});

test('word rules for the model\'s own labels', () => {
  const cases: [string, string][] = [
    ['Wall thickness', 'Толщина стенки'],
    ['Wall Thickness', 'Толщина стенки'],
    ['wall_thickness', 'Толщина стенки'],
    ['wallThickness', 'Толщина стенки'],
    ['Lid height', 'Высота крышки'],
    ['Base thickness', 'Толщина основания'],
    ['Hole diameter', 'Диаметр отверстия'],
    ['Slot width', 'Ширина паза'],
    ['Clip gap', 'Зазор клипсы'],
    ['Wheel diameter', 'Диаметр колеса'],
    ['Standoff height', 'Высота стойки'],
    ['Tile size', 'Размер плитки'],
    ['Outer diameter', 'Внешний диаметр'],
    ['Inner diameter', 'Внутренний диаметр'],
    ['Overall height', 'Общая высота'],
    ['Max overhang', 'Максимальный свес'],
    ['Inner wall thickness', 'Толщина внутренней стенки'],
    ['Top lid thickness', 'Толщина верхней крышки'],
    ['Side wall', 'Боковая стенка'],
    ['Top gap', 'Зазор сверху'],
    ['Bottom thickness', 'Толщина снизу'],
    ['Axle hole', 'Отверстие под ось'],
    ['Screw hole', 'Отверстие под винт'],
    ['Screw hole diameter', 'Диаметр отверстия под винт'],
    ['M3 screw hole', 'Отверстие под винт M3'],
    ['Magnet pocket depth', 'Глубина гнезда под магнит'],
    ['Nut pocket', 'Гнездо под гайку'],
    ['USB-C slot', 'Паз USB-C'],
    ['USB port width', 'Ширина порта USB'],
    ['Side USB port', 'Боковой порт USB'],
    ['LED hole', 'Отверстие под светодиод'],
    ['Lid clip width', 'Ширина клипсы крышки'],
    ['Hook count', 'Количество крючков'],
    ['Rib count', 'Количество рёбер'],
    ['Number of hooks', 'Количество крючков'],
    ['Number of side holes', 'Количество боковых отверстий'],
    ['Hole spacing', 'Шаг отверстий'],
    ['Thread pitch', 'Шаг резьбы'],
    ['Height of the lid', 'Высота крышки'],
    ['Show lid', 'Показать крышку'],
    ['Add text', 'Добавить текст'],
    ['Mounting hole diameter', 'Диаметр крепёжного отверстия'],
    ['Vent slots', 'Вентиляционные пазы'],
    ['Holes', 'Отверстия'],
    ['Wall (mm)', 'Стенка (мм)'],
    ['Wall thickness (mm)', 'Толщина стенки (мм)'],
    ['Tilt (deg)', 'Наклон (°)'],
    ['Rounding', 'Скругление'],
    ['Spring clip', 'Пружинная клипса'],
    ['Spring diameter', 'Диаметр пружины'],
    ['Hinge pin diameter', 'Диаметр штифта петли'],
    ['Tooth count', 'Количество зубьев'],
  ];
  for (const [en, ru] of cases) assert.equal(ruLabel(en), ru, en);
});

test('unknown words keep the English', () => {
  for (const en of ['Body width', 'Head width', 'Sticker 0 / Standee 1', 'Snap-fit depth', 'Lid top thickness', 'Floors', 'port_fit', 'base_r', 'Hook 2 offset', 'Front', 'USB', 'Lid snap hook width'])
    assert.equal(paramLabel(en, 'ru'), en, en);
  // labels the model already wrote in Russian pass through
  assert.equal(paramLabel('Высота банки', 'ru'), 'Высота банки');
  assert.equal(paramGroup('Форма', 'ru'), 'Форма');
  assert.equal(paramGroup('Mystery', 'ru'), 'Mystery');
});

test('the English UI is unchanged', () => {
  for (const s of ['Wall', 'Gap around the board', 'Lid thickness', 'Высота банки']) assert.equal(paramLabel(s, 'en'), s);
  assert.equal(paramGroup('Shell', 'en'), 'Shell');
  assert.equal(paramOption('hole', 'en'), 'hole');
});

test('choices', () => {
  assert.equal(paramOption('hole', 'ru'), 'отверстие');
  assert.equal(paramOption('skin', 'ru'), 'тонкий слой');
  assert.equal(paramOption('peg', 'ru'), 'штифты');
  assert.equal(paramOption('assembled', 'ru'), 'в сборе');
  assert.equal(paramOption('false', 'ru'), 'нет');
  assert.equal(paramOption('false', 'en'), 'false');
  assert.equal(paramOption('round', 'ru'), 'round');
  assert.equal(paramOption('#f2a6ad', 'ru'), '#f2a6ad');
});
