// The PCB engine's lines in the person's language. tscircuit writes its warnings and errors in English for the agent
// ("Port pin3 on SW1 is missing a trace"); the panel shows them by kind in RU/EN and keeps the original line for the
// tooltip and the details. A kind it does not know keeps the original as its text (the EN UI) or a plain title (RU).
import type { PcbIssue } from '$lib/types';

export type Lang = 'en' | 'ru';
/** text: what the panel says; about: what it means for the board (warnings), null when the text says it all. */
export interface Said {
  text: string;
  about: string | null;
  raw: string;
}

// ".D1 > .cathode" -> "D1.cathode"
const sel = (s: string) => s.trim().replace(/^\./, '').replace(/\s*>\s*\./g, '.');
const num = (v: string, lang: Lang) => {
  const n = Math.round(Number(v) * 100) / 100;
  return Number.isFinite(n) ? (lang === 'ru' ? String(n).replace('.', ',') : String(n)) : v;
};
const EDGE: Record<string, { en: string; ru: string }> = {
  '-x': { en: 'left', ru: 'левого' },
  '+x': { en: 'right', ru: 'правого' },
  '-y': { en: 'bottom', ru: 'нижнего' },
  '+y': { en: 'top', ru: 'верхнего' },
};
const edge = (e: string, lang: Lang) => EDGE[e]?.[lang] ?? e;

type Rule = { re: RegExp; say: (m: RegExpMatchArray, lang: Lang) => { en: string; ru: string } };
const W = (en: string, ru: string) => ({ en, ru });

// warnings: what the routing engine noticed on a board that may well have 0 DRC errors
const WARNINGS: Record<string, Rule[] | { en: string; ru: string }> = {
  source_pin_missing_trace_warning: [
    {
      re: /^Port (\S+) on (\S+) is missing a trace/,
      say: ([, pin, ref]) => W(`${ref} ${pin} is not connected`, `Вывод ${pin} у ${ref} не подключён`),
    },
  ],
  pcb_trace_warning: [
    {
      re: /Trace \[(.+?) to (.+?)\] is routed thinner than requested \(requested: ([\d.]+)mm, actual: ([\d.]+)mm\)/,
      say: ([, a, b, want, got], lang) =>
        W(
          `Trace ${sel(a)} → ${sel(b)} is narrower than requested: ${num(got, lang)} mm instead of ${num(want, lang)} mm`,
          `Дорожка ${sel(a)} → ${sel(b)} уже заданной: ${num(got, lang)} мм вместо ${num(want, lang)} мм`,
        ),
    },
  ],
  pcb_trace_style_warning: W('A trace segment runs off the 45° grid', 'Отрезок дорожки идёт не под углом, кратным 45°'),
  pcb_trace_too_long_warning: W('A trace is longer than it should be', 'Дорожка длиннее, чем стоило бы'),
  pcb_trace_too_many_vias_warning: W('A trace changes layers many times', 'Дорожка много раз меняет слой'),
  pcb_component_missing_courtyard_warning: W('A part has no courtyard outline', 'У детали нет контура посадочного места'),
  pcb_connector_not_in_accessible_orientation_warning: W('A connector does not face outwards', 'Разъём развёрнут не наружу'),
  pcb_keepout_overlap_warning: W('Something sits in a keep-out zone', 'Что-то заходит в запретную зону'),
  pcb_fabricator_extra_charge_warning: W('The fab may charge extra for this board', 'Фабрика может взять доплату за эту плату'),
  source_confusing_net_name_warning: W('A net name is easy to confuse', 'Имя цепи легко перепутать'),
  source_property_ignored_warning: W('A part property was ignored', 'Свойство детали не учтено'),
  source_part_not_found_warning: W('A part was not found in the catalogue', 'Деталь не найдена в каталоге'),
  supplier_footprint_mismatch_warning: W("A supplier part number does not match its footprint", 'Номер детали поставщика не совпадает с посадочным местом'),
  schematic_component_overlap_warning: W('Parts overlap on the schematic drawing', 'Детали на чертеже схемы перекрываются'),
  schematic_element_outside_sheet_warning: W('Something is drawn outside the schematic sheet', 'Часть схемы выходит за лист'),
  board_json_warning: W('No board description for the case', 'Описание платы для корпуса не собралось'),
  drc_crash_warning: W('The independent DRC run failed', 'Независимая проверка DRC не запустилась'),
};

// what a warning means for the board, shown when its row is opened
const ABOUT: Record<string, { en: string; ru: string }> = {
  source_pin_missing_trace_warning: W(
    'A pin with no trace. On a 4-leg button it usually means the legs are wired wrong: pins 1-2 and 3-4 are one contact each.',
    'Вывод без дорожки. У кнопки с 4 ножками это обычно значит, что ножки подключены неверно: 1-2 — один контакт, 3-4 — другой.',
  ),
  pcb_trace_warning: W(
    'The router could not keep the full width everywhere, usually beside a via. The narrower trace still carries about 0.5 A; the fab files are unaffected.',
    'Трассировщик не везде сохранил ширину — обычно возле переходного отверстия. Узкая дорожка всё равно держит около 0,5 А; файлы для фабрики это не меняет.',
  ),
  pcb_trace_style_warning: W(
    'Only how the routing looks: the autorouter drew this segment at its own angle. The board works the same.',
    'Только внешний вид разводки: трассировщик провёл отрезок под своим углом. На работу платы это не влияет.',
  ),
};

const ERRORS: Record<string, Rule[]> = {
  pcb_button_short_error: [
    {
      re: /^(\S+) (\S+) and (\S+) are one contact inside the switch \(legs [\d.]+ mm apart\), so (.+) and (.+) are shorted together/,
      say: ([, ref, a, b, x, y]) =>
        W(`${ref}: ${a} and ${b} are one contact of the button, so ${x} and ${y} are shorted`, `${ref}: ${a} и ${b} — один контакт кнопки, ${x} и ${y} замкнуты накоротко`),
    },
  ],
  pcb_autorouting_error: [
    {
      re: /maximum length for (.+?) to (.+?) cannot be satisfied: its endpoints are ([\d.]+)mm apart/,
      say: ([, a, b, d], lang) =>
        W(
          `Decoupling capacitor ${sel(a)} is ${num(d, lang)} mm from ${sel(b)}; at most 1 mm is allowed, so nothing was routed`,
          `Конденсатор развязки ${sel(a)} стоит в ${num(d, lang)} мм от ${sel(b)}, а можно не дальше 1 мм — трассировка не запускалась`,
        ),
    },
    {
      re: /Autorouting was skipped because (\d+) PCB placement error/,
      say: ([, n]) => W(`Not routed yet: fix the placement first (${n})`, `Трассировка не запускалась: сначала исправьте расстановку (${n})`),
    },
  ],
  pcb_component_outside_board_error: [
    {
      re: /Component (\S+) extends outside board boundaries by ([\d.]+)mm/,
      say: ([, ref, d], lang) => W(`${ref} sticks out of the board by ${num(d, lang)} mm`, `${ref} выходит за край платы на ${num(d, lang)} мм`),
    },
  ],
  pcb_footprint_overlap_error: [{ re: /^(\S+) overlaps (\S+):/, say: ([, a, b]) => W(`${a} overlaps ${b}`, `${a} наезжает на ${b}`) }],
  pcb_courtyard_overlap_error: [
    { re: /Courtyard of (\S+) overlaps with courtyard of (\S+)/, say: ([, a, b]) => W(`${a} and ${b} are too close`, `${a} и ${b} стоят слишком близко`) },
  ],
  external_footprint_load_error: [
    { re: /./, say: () => W('A footprint that is not in the offline set', 'Посадочное место не из офлайн-набора') },
  ],
};

const INTENT: Record<string, Rule[]> = {
  intent_not_at_edge: [
    {
      re: /should sit on the (\S+) edge, but its body is ([-\d.]+) mm from it/,
      say: ([, e, d], lang) => W('', `должен стоять у ${edge(e, lang)} края, а до края ${num(d, lang)} мм`),
    },
  ],
  intent_wrong_edge: [
    { re: /is on the (\S+) edge, the intent says (\S+)/, say: ([, a, b], lang) => W('', `стоит у ${edge(a, lang)} края, а по замыслу — у ${edge(b, lang)}`) },
  ],
  intent_wrong_facing: [
    {
      re: /is at the (\S+) edge but its opening faces (\S+)/,
      say: ([, a, b], lang) => W('', `стоит у ${edge(a, lang)} края, но разъём смотрит в сторону ${edge(b, lang)} края`),
    },
  ],
  intent_gpio_on_supply: [
    { re: /should be driven by (\S+), but/, say: ([, pin]) => W('', `подключён к питанию, а должен управляться выводом ${pin}`) },
  ],
  intent_gpio_missing: [{ re: /should be driven by (\S+), but/, say: ([, pin]) => W('', `не подключён к выводу ${pin}`) }],
  intent_unknown_part: [{ re: /./, say: () => W('', 'есть в замысле, но не на схеме') }],
  intent_unknown_pin: [{ re: /is on (\S+), but no part has a pin/, say: ([, pin]) => W('', `по замыслу на ${pin}, но такого вывода нет`) }],
  intent_too_many_nets: [{ re: /^(\d+) nets, the intent allows (\d+)/, say: ([, n, max]) => W('', `Цепей ${n}, а по замыслу не больше ${max}`) }],
  intent_bad_edge: [{ re: /./, say: () => W('', 'край в замысле записан неверно') }],
};

const LIMITS: Record<string, (v: unknown, l: unknown) => string> = {
  too_many_layers: (v) => `Слоёв меди: ${v}, а здесь разводятся 2`,
  board_too_large: (v, l) => `Плата больше ${l} × ${l} мм (${v} мм)`,
  too_many_nets: (v, l) => `Цепей ${v}, а здесь — не больше ${l}`,
  too_many_components: (v, l) => `Деталей ${v}, а здесь — не больше ${l}`,
};

function apply(rules: Rule[] | undefined, msg: string, lang: Lang): string | null {
  for (const r of rules ?? []) {
    const m = msg.match(r.re);
    if (m) return r.say(m, lang)[lang] || null;
  }
  return null;
}

/** A warning of a build: the engine's note in the person's language. */
export function sayWarning(w: PcbIssue, lang: Lang): Said {
  const rule = WARNINGS[w.type];
  let text: string | null = null;
  if (Array.isArray(rule)) text = apply(rule, w.message, lang);
  else if (rule) text = rule[lang];
  if (!text) {
    // a kind this table does not know: the English line itself in EN, a plain title in RU
    text = lang === 'en' ? w.message : w.type.startsWith('schematic_') ? 'Замечание к чертежу схемы' : w.type.startsWith('source_') ? 'Замечание к схеме' : 'Замечание трассировщика';
  }
  return { text, about: ABOUT[w.type]?.[lang] ?? null, raw: w.message };
}

/** A DRC error: known kinds in the person's language, the rest as the engine wrote them. */
export function sayError(e: PcbIssue, lang: Lang): Said {
  return { text: apply(ERRORS[e.type], e.message, lang) ?? e.message, about: null, raw: e.message };
}

/** An intent issue ({code, ref, msg}): RU text by code, the engine's English line otherwise. */
export function sayIntent(i: { code: string; ref?: string; msg: string }, lang: Lang): Said {
  if (lang === 'en') return { text: i.msg, about: null, raw: i.msg };
  const t = apply(INTENT[i.code], i.msg, lang);
  return { text: t ? (i.ref && !/^[А-ЯЁ]/.test(t) ? `${i.ref} ${t}` : t) : i.msg, about: null, raw: i.msg };
}

/** A limit issue ({code, value, limit, msg}). */
export function sayLimit(i: { code: string; value: unknown; limit: unknown; msg: string }, lang: Lang): Said {
  const f = lang === 'ru' ? LIMITS[i.code] : null;
  return { text: f ? f(i.value, i.limit) : i.msg, about: null, raw: i.msg };
}
