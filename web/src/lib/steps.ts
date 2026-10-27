// How agent steps read in the log: icon, stage, and a human sentence in the UI language.
// The server sends English titles; Russian ones are built here from the same data.
import { i18n } from './i18n.svelte';

export const TOOL_KIND: Record<string, string> = {
  write_program: 'build', edit_program: 'edit', set_params: 'params', inspect_model: 'inspect', render_view: 'render', look_at: 'look',
  scene: 'scene', measure_photo: 'measure', read_caliper: 'caliper', lookup_standard: 'standard', search_dimensions: 'search',
  recall: 'memory', remember_interface: 'memory', ask_user: 'ask', fit_to_photo: 'fit', propose_probe: 'probe',
  concept_images: 'concepts', load_terrain: 'terrain', save_skill: 'skill', compare_print: 'compare', finish: 'finish',
  look: 'look', measure: 'measure', dimensions: 'standard',
};

export const KIND_ICON: Record<string, string> = {
  build: 'cube', edit: 'pencil', params: 'sliders', inspect: 'ruler', render: 'eye', look: 'scan', scene: 'camera',
  measure: 'ruler', caliper: 'caliper', standard: 'book', search: 'search', memory: 'brain', ask: 'help', fit: 'target',
  probe: 'flask', concepts: 'sparkles', terrain: 'mountain', skill: 'package', compare: 'scan', finish: 'check-circle',
};

export const KIND_STAGE: Record<string, string> = {
  build: 'design', edit: 'design', params: 'design', skill: 'design', concepts: 'design', terrain: 'measure', measure: 'measure',
  caliper: 'measure', scene: 'measure', look: 'check', standard: 'measure', search: 'measure', memory: 'understand', ask: 'understand',
  inspect: 'check', render: 'check', fit: 'check', probe: 'check', compare: 'check', finish: 'review',
};

export const STAGES = ['understand', 'measure', 'design', 'check', 'review', 'done'] as const;

export function kindOf(name: string, kind?: string): string {
  return kind ?? TOOL_KIND[name] ?? 'build';
}

const mm = (v: any) => {
  const n = Number(v);
  return isFinite(n) ? String(+n.toFixed(1)) : String(v ?? '');
};
const size = (s: any) => (Array.isArray(s) && s.length ? s.map(mm).join(' × ') + ' мм' : '');

/** Best-effort parse of the (possibly truncated) raw JSON summary. */
export function parseSummary(summary?: string): Record<string, any> | null {
  if (!summary) return null;
  try {
    return JSON.parse(summary);
  } catch {
    const out: Record<string, any> = {};
    const num = (k: string) => {
      const m = new RegExp(`"${k}":\\s*(-?[\\d.]+)`).exec(summary);
      if (m) out[k] = Number(m[1]);
    };
    ['version', 'est_grams', 'uncertainty_mm', 'value_mm', 'mean_mm', 'max_mm', 'count', 'relief_m', 'size_km', 'est_minutes'].forEach(num);
    const s = /"size_mm":\s*\[([^\]]*)\]/.exec(summary);
    if (s) out.size_mm = s[1].split(',').map(Number);
    if (/"ok":\s*false/.test(summary)) out.ok = false;
    if (/"printable":\s*false/.test(summary)) out.printable = false;
    if (/"accepted":\s*true/.test(summary)) out.accepted = true;
    const err = /"error":\s*"([^"]*)/.exec(summary);
    if (err) out.error = err[1];
    return Object.keys(out).length ? out : null;
  }
}

function ruCall(name: string, a: any): string {
  a = a ?? {};
  const s = (v: any) => (typeof v === 'string' && v !== '…' ? v : '');
  switch (name) {
    case 'write_program': return `Пишу модель: ${s(a.summary) || 'первая версия'}`;
    case 'edit_program': return `Меняю: ${s(a.summary) || 'детали'}`;
    case 'set_params': return `Подстраиваю ${a.values && typeof a.values === 'object' ? Object.keys(a.values).join(', ') : 'параметры'}`;
    case 'inspect_model': return 'Измеряю собственную модель';
    case 'render_view': return a.view === 'photo' ? 'Сравниваю с фото' : 'Рендерю виды';
    case 'look_at': return 'Рассматриваю фото внимательнее';
    case 'scene': return 'Читаю замеры с фото';
    case 'measure_photo': return `Измеряю «${s(a.target) || 'объект'}» на фото`;
    case 'read_caliper': return 'Читаю штангенциркуль';
    case 'lookup_standard': return `Смотрю стандарты: ${s(a.query)}`;
    case 'search_dimensions': return `Ищу официальные размеры: ${s(a.query)}`;
    case 'recall': return 'Вспоминаю ваши размеры и предпочтения';
    case 'remember_interface': return `Запоминаю «${s(a.name)}» на будущее`;
    case 'ask_user': return 'Задаю вам вопрос';
    case 'fit_to_photo': return 'Подгоняю размеры под силуэт на фото';
    case 'propose_probe': return `Готовлю пробник для «${s(a.dimension) || 'размера'}»`;
    case 'concept_images': return 'Рисую эскизы';
    case 'load_terrain': return `Загружаю реальные высоты${s(a.place) ? ': ' + a.place : ''}`;
    case 'save_skill': return `Сохраняю модуль «${s(a.name)}» для будущих проектов`;
    case 'compare_print': return 'Сравниваю отпечаток с целью';
    case 'finish': return 'Финальная проверка перед сдачей';
    case 'look': return a.what === 'compare' ? 'Сравниваю модель с фото' : a.what === 'model' ? 'Смотрю на модель со всех сторон' : 'Рассматриваю фото внимательнее';
    case 'measure': return String(a.target).toLowerCase() === 'caliper' ? 'Читаю штангенциркуль' : `Измеряю «${s(a.target) || 'объект'}» на фото`;
    case 'dimensions': return `Ищу размеры: ${s(a.query)}`;
    default: return name.replace(/_/g, ' ');
  }
}

const likeness = (r: Record<string, any>): string => {
  const f = Array.isArray(r.likeness) ? r.likeness[0] : null;
  const v = f ? (f.silhouette_iou ?? f.outline_iou) : undefined;
  return typeof v === 'number' ? `, совпадение силуэта ${Math.round(v * 100)}%` : '';
};

function ruResult(name: string, a: any, r: Record<string, any>): string {
  if (r.ok === false) return `Проблема: ${String(r.error ?? r.reason ?? 'не получилось').slice(0, 140)}`;
  switch (name) {
    case 'write_program':
    case 'edit_program':
    case 'set_params':
    case 'fit_to_photo': {
      const state = r.printable === false ? 'есть ошибки печати' : 'печатается';
      const like = likeness(r);
      return `Версия ${r.version ?? ''} — ${size(r.size_mm)}${size(r.size_mm) ? ', ' : ''}${state}${like}`;
    }
    case 'measure':
      if (r.value_mm !== undefined) return `Штангенциркуль: ${mm(r.value_mm)} мм`;
    // falls through
    case 'measure_photo':
      return r.size_mm ? `Измерено: ${size(r.size_mm)}${r.uncertainty_mm ? ` ±${mm(r.uncertainty_mm)}` : ''}` : 'Объект найден';
    case 'read_caliper':
      return r.value_mm ? `Штангенциркуль: ${mm(r.value_mm)} мм` : 'Не удалось прочитать штангенциркуль';
    case 'search_dimensions': {
      const n = Array.isArray(r.facts) ? r.facts.length : undefined;
      return n !== undefined ? `Найдено размеров: ${n}` : 'Поиск выполнен';
    }
    case 'lookup_standard': return 'Значения из стандартов найдены';
    case 'dimensions': {
      const n = (Array.isArray(r.standards) ? r.standards.length : 0) + (Array.isArray(r.web) ? r.web.length : 0);
      return n ? `Найдено размеров: ${n}` : 'Ничего не найдено';
    }
    case 'look': return likeness(r).replace(/^, с/, 'С') || 'Готово';
    case 'inspect_model': return 'Модель измерена';
    case 'scene': return 'Замеры доступны';
    case 'ask_user': return r.answer ? `Вы ответили: ${r.answer}` : 'Без ответа — продолжаю с допущением';
    case 'propose_probe': return 'Пробник готов';
    case 'concept_images': return `Эскизов: ${r.count ?? ''}`;
    case 'load_terrain': return `Высоты загружены: перепад ${mm(r.relief_m)} м на ${mm(r.size_km)} км`;
    case 'compare_print': return `Отклонение отпечатка в среднем ${mm(r.mean_mm)} мм (макс. ${mm(r.max_mm)})`;
    case 'finish': return r.accepted ? 'Одобрено' : `Пока нет: ${r.reason ?? 'нужны правки'}`;
    case 'render_view': return a?.view === 'photo' ? 'Наложение готово' : 'Виды готовы';
    case 'recall': return 'Память проверена';
    case 'remember_interface': return 'Сохранено';
    default: return 'Готово';
  }
}

// Server titles come in the language of the request; the local ones cover older events
// and the case where the UI language differs from the request language.
const looksRu = (s?: string) => !!s && /[а-яё]/i.test(s);

export function callTitle(name: string, args: any, serverTitle?: string): string {
  if (serverTitle && (i18n.lang === 'ru') === looksRu(serverTitle)) return serverTitle;
  if (i18n.lang === 'ru') return ruCall(name, args);
  return serverTitle || name.replace(/_/g, ' ');
}

export function resultTitle(name: string, args: any, summary: string | undefined, ok: boolean, serverTitle?: string): string | undefined {
  if (serverTitle && (i18n.lang === 'ru') === looksRu(serverTitle)) return serverTitle;
  const r = parseSummary(summary) ?? (ok ? {} : { ok: false });
  if (i18n.lang === 'ru') return ruResult(name, args, r);
  return serverTitle;
}

// Fixed progress lines the server emits in English; the agent's own words pass through untouched.
const RU_STATUS: [RegExp, string | ((m: RegExpMatchArray) => string)][] = [
  [/^Understanding the request$/, 'Разбираю задачу'],
  [/^Measuring the photos$/, 'Измеряю фото'],
  [/^Looking for a reference object to calibrate the photo$/, 'Ищу на фото эталон для масштаба'],
  [/^Reading the caliper$/, 'Читаю показания штангенциркуля'],
  [/^Watching the video$/, 'Смотрю видео'],
  [/^Choosing print settings from the geometry$/, 'Подбираю настройки печати под форму'],
  [/^Sketching concepts$/, 'Рисую эскизы'],
  [/^Breeding (\d+) variants from (\d+) parent\(s\)$/, (m) => `Скрещиваю ${m[2]} → ${m[1]} вариантов`],
  [/^Painting the requested change$/, 'Рисую правку'],
  [/^Searching: (.*)$/, (m) => `Ищу: ${m[1]}`],
  [/^Loading elevation data$/, 'Загружаю данные о рельефе'],
  [/^Independent review of the design$/, 'Независимая проверка модели'],
  [/^Fitting parameters to the photo silhouette$/, 'Подгоняю размеры под силуэт на фото'],
];

/** Progress lines the server writes itself, as opposed to what the model says. */
export function isSystemStatus(text: string): boolean {
  return RU_STATUS.some(([re]) => re.test(text));
}

export function statusLine(text: string): string {
  if (i18n.lang !== 'ru' || looksRu(text)) return text;
  for (const [re, out] of RU_STATUS) {
    const m = text.match(re);
    if (m) return typeof out === 'string' ? out : out(m);
  }
  return text;
}

// What a folded group of steps did, in the spirit of "Read 3 files, ran 2 commands".
type Phrase = { en: [string, (n: number) => string]; ru: [string, (n: number) => string] };
const ruN = (n: number, w: [string, string, string]) => {
  const m10 = n % 10, m100 = n % 100;
  return `${n} ${m10 === 1 && m100 !== 11 ? w[0] : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? w[1] : w[2]}`;
};
const PHRASE: Record<string, Phrase> = {
  build: { en: ['wrote the model', (n) => `wrote ${n} versions`], ru: ['написал модель', (n) => `написал ${ruN(n, ['версию', 'версии', 'версий'])}`] },
  edit: { en: ['edited the model', (n) => `made ${n} edits`], ru: ['поправил модель', (n) => `внёс ${ruN(n, ['правку', 'правки', 'правок'])}`] },
  params: { en: ['tuned parameters', () => 'tuned parameters'], ru: ['подстроил параметры', () => 'подстроил параметры'] },
  look: { en: ['took a look', (n) => `took ${n} looks`], ru: ['посмотрел', (n) => `посмотрел ${ruN(n, ['раз', 'раза', 'раз'])}`] },
  inspect: { en: ['measured the model', () => 'measured the model'], ru: ['измерил модель', () => 'измерил модель'] },
  measure: { en: ['measured the photo', (n) => `took ${n} measurements`], ru: ['измерил фото', (n) => `сделал ${ruN(n, ['замер', 'замера', 'замеров'])}`] },
  search: { en: ['looked up sizes', () => 'looked up sizes'], ru: ['нашёл размеры', () => 'нашёл размеры'] },
  memory: { en: ['checked memory', () => 'checked memory'], ru: ['проверил память', () => 'проверил память'] },
  ask: { en: ['asked you', () => 'asked you'], ru: ['спросил вас', () => 'спросил вас'] },
  finish: { en: ['ran the final review', (n) => `ran ${n} final reviews`], ru: ['прошёл финальную проверку', (n) => `${ruN(n, ['финальная проверка', 'финальные проверки', 'финальных проверок'])}`] },
  concepts: { en: ['sketched concepts', () => 'sketched concepts'], ru: ['нарисовал эскизы', () => 'нарисовал эскизы'] },
  probe: { en: ['prepared a test piece', () => 'prepared test pieces'], ru: ['подготовил пробник', () => 'подготовил пробники'] },
  terrain: { en: ['loaded terrain', () => 'loaded terrain'], ru: ['загрузил рельеф', () => 'загрузил рельеф'] },
  skill: { en: ['saved a module', () => 'saved modules'], ru: ['сохранил модуль', () => 'сохранил модули'] },
};
const GROUP_OF: Record<string, string> = {
  render: 'look', compare: 'look', fit: 'measure', caliper: 'measure', scene: 'measure', standard: 'search',
};

export function groupSummary(items: { kind: string; tkind?: string }[]): string {
  const counts = new Map<string, number>();
  for (const it of items) {
    const k = it.kind === 'tool' ? (GROUP_OF[it.tkind ?? ''] ?? it.tkind ?? 'build') : null;
    if (k && PHRASE[k]) counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const lang = i18n.lang === 'ru' ? 'ru' : 'en';
  const parts = [...counts].map(([k, n]) => (n === 1 ? PHRASE[k][lang][0] : PHRASE[k][lang][1](n)));
  const s = parts.join(', ') || (lang === 'ru' ? 'подготовка' : 'getting ready');
  return s.charAt(0).toUpperCase() + s.slice(1);
}
