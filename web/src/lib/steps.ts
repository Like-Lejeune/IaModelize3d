// How agent steps read in the log: icon, stage, and a human sentence in the UI language.
// The server sends titles in the request's language; the other language is built here from the same data.
import { i18n, partName } from './i18n.svelte';

export const TOOL_KIND: Record<string, string> = {
  write_program: 'build', edit_program: 'edit', set_params: 'params', inspect_model: 'inspect', render_view: 'render', look_at: 'look',
  scene: 'scene', measure_photo: 'measure', read_caliper: 'caliper', lookup_standard: 'standard', search_dimensions: 'search',
  recall: 'memory', remember_interface: 'memory', ask_user: 'ask', fit_to_photo: 'fit', propose_probe: 'probe',
  concept_images: 'concepts', load_terrain: 'terrain', save_skill: 'skill', compare_print: 'compare', finish: 'finish',
  look: 'look', measure: 'measure', dimensions: 'standard', mesh_write: 'build', mesh_edit: 'edit',
  scan_board: 'measure', use_board: 'standard', check_enclosure: 'inspect', write_circuit: 'build', check_pcb: 'inspect',
  export_fab: 'export', make_enclosure: 'build',
  search_parts: 'standard', part_info: 'standard', write_device: 'build', build_device: 'build', write_firmware: 'build', quote_device: 'export',
  inspect_board: 'look', inspect_case: 'look', inspect_part: 'inspect', grid: 'look', collage: 'look',
};

export const KIND_ICON: Record<string, string> = {
  build: 'cube', edit: 'pencil', params: 'sliders', inspect: 'ruler', render: 'eye', look: 'scan', scene: 'camera',
  measure: 'ruler', caliper: 'caliper', standard: 'book', search: 'search', memory: 'brain', ask: 'help', fit: 'target',
  probe: 'flask', concepts: 'scribble', terrain: 'mountain', skill: 'package', compare: 'scan', finish: 'check-circle',
  export: 'download',
};

/** Tools whose kind's icon would mislead: a circuit is not a cube, a case is a box. */
export const TOOL_ICON: Record<string, string> = { write_circuit: 'cpu', make_enclosure: 'package', write_device: 'cpu', build_device: 'cpu', search_parts: 'search' };

export const KIND_STAGE: Record<string, string> = {
  build: 'design', edit: 'design', params: 'design', skill: 'design', concepts: 'design', terrain: 'measure', measure: 'measure',
  caliper: 'measure', scene: 'measure', look: 'check', standard: 'measure', search: 'measure', memory: 'understand', ask: 'understand',
  inspect: 'check', render: 'check', fit: 'check', probe: 'check', compare: 'check', finish: 'review', export: 'design',
};

export const STAGES = ['understand', 'measure', 'design', 'check', 'review', 'done'] as const;

export function kindOf(name: string, kind?: string): string {
  // servers that did not know a tool yet sent it as 'other' (the first electronics runs)
  return (kind && kind !== 'other' ? kind : undefined) ?? TOOL_KIND[name] ?? kind ?? 'build';
}

/**
 * The Meta models a step names on its chip: the ones the server says did the work, else what
 * that kind of step always runs on (older events carry no model). Measuring cuts the object out
 * with SAM, unless it reads a caliper; concepts are drawn by Muse Image; a review names its reviewer.
 * A board scan runs SAM 3.1 (board, holes, USB) and Muse Spark (the silkscreen); a circuit is the
 * designer's own writing, routed and checked by the engine.
 */
export function stepModels(it: { kind: string; name?: string; tkind?: string; args?: any; model?: string; models?: string[] }): string[] {
  if (it.kind === 'critic') return it.model ? [it.model] : [];
  if (it.kind !== 'tool') return [];
  if (it.name === 'scan_board') return it.models?.length ? it.models : ['sam-3.1', 'muse-spark-1.3'];
  if (it.name === 'write_circuit' || it.name === 'check_pcb') return it.models?.length ? it.models : it.model ? [it.model] : [];
  if (it.tkind === 'measure') {
    if (it.models?.length) return it.models;
    return String(it.args?.target ?? '').toLowerCase() === 'caliper' ? [] : ['sam-3.1'];
  }
  if (it.tkind === 'concepts') return it.models?.length ? it.models : ['muse-image'];
  return [];
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
    // the result's own ok leads its JSON: a nested one (a case build's enclosure brief) is not the step's
    const top = /^\{\s*"ok":\s*(true|false)/.exec(summary);
    if (top ? top[1] === 'false' : /"ok":\s*false/.test(summary)) out.ok = false;
    const fit = caseFit(summary);
    if (fit) out.case_fit = fit;
    if (/"printable":\s*false/.test(summary)) out.printable = false;
    if (/"accepted":\s*true/.test(summary)) out.accepted = true;
    if (/"accepted":\s*false/.test(summary)) out.accepted = false;
    const err = /"error":\s*"([^"]*)/.exec(summary);
    if (err) out.error = err[1];
    const reason = /"reason":\s*"([^"]*)"/.exec(summary);
    if (reason) out.reason = reason[1];
    // a finish: how the review ended comes right after "accepted"
    const review = /"review":\s*"(\w+)"/.exec(summary);
    if (review) out.review = review[1];
    if (/"unresolved":\s*\[\s*"/.test(summary)) out.unresolved = ['…'];
    if (/"unchecked":\s*\[\s*"/.test(summary)) out.unchecked = ['…'];
    elecSummary(summary, out);
    return Object.keys(out).length ? out : null;
  }
}

/** A case build's verdict (tools._case_verdict), right after "printable" so a cut summary keeps it; none when cut inside it. */
function caseFit(summary: string): Record<string, any> | undefined {
  const at = summary.indexOf('"case_fit":');
  const from = at < 0 ? -1 : summary.indexOf('{', at);
  if (from < 0) return undefined;
  for (let i = from, depth = 0; i < summary.length; i++) {
    if (summary[i] === '{') depth++;
    else if (summary[i] === '}' && --depth === 0) {
      try {
        return JSON.parse(summary.slice(from, i + 1));
      } catch {
        return undefined;
      }
    }
  }
  return undefined;
}

/** What the electronics steps need from a cut summary: their numbers come early in the JSON. */
function elecSummary(summary: string, out: Record<string, any>) {
  const int = (k: string) => {
    const m = new RegExp(`"${k}":\\s*(-?[\\d.]+)`).exec(summary);
    return m ? Number(m[1]) : undefined;
  };
  const counts = { traces: int('traces'), vias: int('vias') };
  if (counts.traces !== undefined) out.counts = counts;
  const intent = /"intent":\s*\{"ok":\s*(true|false),\s*"checked":\s*(\d+)/.exec(summary);
  if (intent) out.intent = { ok: intent[1] === 'true', checked: Number(intent[2]) };
  const fab = /"fab":\s*"(ready|none|missing)/.exec(summary);
  if (fab) out.fab = fab[1];
  for (const k of ['pcb_version', 'bom_lines', 'cpl_lines']) if (int(k) !== undefined) out[k] = int(k);
  // export_fab's layer files come before its links (pcb_tools): whole, or not counted at all (older runs had them past the cut)
  const layers = /"layers":\s*\[([^\]]*)\]/.exec(summary);
  if (layers) out.layers = [...layers[1].matchAll(/"([^"]*)"/g)].map((m) => m[1]);
  // the case check: its three numbers, then the findings by code
  const sum = { usb_clearance_mm: int('usb_clearance_mm'), button_gap_mm: int('button_gap_mm'), snap_strain_pct: int('snap_strain_pct') };
  if (/"summary":\s*\{"usb_clearance_mm"/.test(summary)) out.summary = sum;
  for (const [k, next] of [['errors', 'warnings'], ['warnings', 'passed']]) {
    const seg = new RegExp(`"${k}":\\s*\\[(.*?)(?:\\]\\s*,\\s*"${next}"|$)`, 's').exec(summary);
    if (seg) out[k] = [...seg[1].matchAll(/"code":\s*"(\w+)"(?:,\s*"part":\s*"([^"]*)")?/g)].map((m) => ({ code: m[1], part: m[2] }));
  }
  // a board: use_board / scan_board start with it
  const board = /"board":\s*\{"id":\s*"[^"]*",\s*"name":\s*"([^"]*)"(?:,\s*"source":\s*"([^"]*)")?/.exec(summary);
  if (board) out.board = { name: board[1], source: board[2], size_mm: out.size_mm };
  // the case check names its board near the start, so a summary cut at 600 characters still has it
  const bn = /"board_name":\s*"([^"]*)"/.exec(summary);
  if (bn) out.board_name = bn[1];
  const method = /"method":\s*"(\w+)"/.exec(summary);
  if (method) out.calibration = { method: method[1], uncertainty_mm: out.uncertainty_mm };
}

function ruCall(name: string, a: any): string {
  a = a ?? {};
  const s = (v: any) => (typeof v === 'string' && v !== '…' ? v : '');
  switch (name) {
    case 'write_program': return `Пишу модель: ${s(a.summary) || 'первая версия'}`;
    case 'edit_program': return `Меняю: ${s(a.summary) || 'детали'}`;
    case 'mesh_write': return `Леплю модель: ${s(a.summary) || 'первая форма'}`;
    case 'mesh_edit': return `Леплю: ${s(a.summary) || 'детали'}`;
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
    case 'grid': return 'Считываю точные координаты на картинке';
    case 'collage': return 'Собираю картинки на один лист';
    case 'look': return a.what === 'compare' ? 'Сравниваю модель с фото' : a.what === 'model' ? 'Смотрю на модель со всех сторон' : 'Рассматриваю фото внимательнее';
    case 'measure': return String(a.target).toLowerCase() === 'caliper' ? 'Читаю штангенциркуль' : `Измеряю «${s(a.target) || 'объект'}» на фото`;
    case 'dimensions': return `Ищу размеры: ${s(a.query)}`;
    default: return name.replace(/_/g, ' ');
  }
}

const likePct = (r: Record<string, any>): number | undefined => {
  const f = Array.isArray(r.likeness) ? r.likeness[0] : null;
  const v = f ? (f.silhouette_iou ?? f.outline_iou) : undefined;
  return typeof v === 'number' ? Math.round(v * 100) : undefined;
};
const likeness = (r: Record<string, any>): string => (likePct(r) !== undefined ? `, совпадение силуэта ${likePct(r)}%` : '');

function ruResult(name: string, a: any, r: Record<string, any>): string {
  if (r.ok === false) return `Проблема: ${String(r.error ?? r.reason ?? 'не получилось').slice(0, 140)}`;
  switch (name) {
    case 'write_program':
    case 'edit_program':
    case 'mesh_write':
    case 'mesh_edit':
    case 'set_params':
    case 'fit_to_photo': {
      const state = r.printable === false ? 'есть ошибки печати' : 'печатается';
      const like = likeness(r);
      return `Версия ${r.version ?? ''} — ${size(r.size_mm)}${size(r.size_mm) ? ', ' : ''}${state}${like}${caseSuffix(buildCase(r), true)}`;
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
    case 'grid': return 'Сетка готова';
    case 'collage': return 'Картинки на одном листе';
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

// The English side, for a Russian run shown in the English UI: narrate.py's own wording.
function enCall(name: string, a: any): string {
  a = a ?? {};
  const s = (v: any) => (typeof v === 'string' && v !== '…' ? v : '');
  switch (name) {
    case 'write_program': return `Writing the model: ${s(a.summary) || 'first version'}`;
    case 'edit_program': return `Changing: ${s(a.summary) || 'details'}`;
    case 'mesh_write': return `Sculpting the model: ${s(a.summary) || 'first form'}`;
    case 'mesh_edit': return `Sculpting: ${s(a.summary) || 'details'}`;
    case 'set_params': return `Adjusting ${a.values && typeof a.values === 'object' ? Object.keys(a.values).join(', ') : 'parameters'}`;
    case 'inspect_model': return 'Measuring my own model';
    case 'grid': return 'Reading exact coordinates on the picture';
    case 'collage': return 'Laying pictures side by side';
    case 'look': return a.what === 'compare' ? 'Comparing the model with the photo' : a.what === 'model' ? 'Looking at the model from all sides' : 'Taking a closer look at the photo';
    case 'measure': return String(a.target).toLowerCase() === 'caliper' ? 'Reading the caliper' : `Measuring “${s(a.target) || 'the object'}” on the photo`;
    case 'dimensions': return `Looking up dimensions: ${s(a.query)}`;
    case 'remember_interface': return `Remembering “${s(a.name)}” for next time`;
    case 'ask_user': return 'Asking you a question';
    case 'fit_to_photo': return `Fitting ${Array.isArray(a.params) && a.params.length ? a.params.join(', ') : 'the outline'} to the photo silhouette`;
    case 'propose_probe': return `Preparing a test print for ${s(a.dimension) || 'a critical size'}`;
    case 'concept_images': return 'Sketching concepts';
    case 'load_terrain': return `Loading real elevation data${s(a.place) ? ': ' + a.place : ''}`;
    case 'compare_print': return 'Comparing your print with the target';
    case 'finish': return 'Final check before handing over';
    default: return name.replace(/_/g, ' ');
  }
}

function enResult(name: string, r: Record<string, any>): string {
  const sz = (v: any) => (Array.isArray(v) && v.length ? v.map(mm).join(' × ') + ' mm' : '');
  if (r.ok === false) return `Problem: ${String(r.error ?? r.reason ?? 'failed').slice(0, 140)}`;
  switch (name) {
    case 'write_program':
    case 'edit_program':
    case 'mesh_write':
    case 'mesh_edit':
    case 'set_params':
    case 'fit_to_photo': {
      const like = likePct(r) !== undefined ? `, silhouette match ${likePct(r)}%` : '';
      return `Version ${r.version ?? ''} — ${sz(r.size_mm)}${sz(r.size_mm) ? ', ' : ''}${r.printable === false ? 'problems to fix' : 'printable'}${like}${caseSuffix(buildCase(r), false)}`;
    }
    case 'measure':
      if (r.value_mm !== undefined) return `Caliper reads ${mm(r.value_mm)} mm`;
      return r.size_mm ? `Measured: ${sz(r.size_mm)}${r.uncertainty_mm ? ` ±${mm(r.uncertainty_mm)}` : ''}` : 'Found the object';
    case 'dimensions': {
      const n = (Array.isArray(r.standards) ? r.standards.length : 0) + (Array.isArray(r.web) ? r.web.length : 0);
      return n ? `Dimensions found: ${n}` : 'Nothing found';
    }
    case 'grid': return 'Coordinate grid ready';
    case 'collage': return 'Pictures on one sheet';
    case 'look': return likePct(r) !== undefined ? `Silhouette match ${likePct(r)}%` : 'Done';
    case 'inspect_model': return 'Measured the model';
    case 'ask_user': return r.answer ? `You answered: ${r.answer}` : 'No answer — continuing with a stated assumption';
    case 'propose_probe': return 'Test print ready';
    case 'concept_images': return `Concepts ready: ${r.count ?? ''}`;
    case 'load_terrain': return `Elevation loaded: ${mm(r.relief_m)} m relief over ${mm(r.size_km)} km`;
    case 'compare_print': return `Print deviates ${mm(r.mean_mm)} mm on average (max ${mm(r.max_mm)})`;
    case 'finish': return r.accepted ? 'Approved' : `Not yet: ${r.reason ?? 'needs fixes'}`;
    case 'remember_interface': return 'Saved to your setup';
    default: return 'Done';
  }
}

// ------------------------------------------------------------------ electronics
// The board, the case checked against it and the PCB read the same in both languages: built here from the args
// and the summary (cut at 600 characters, so only its front is sure), the way server/formwright/agent/narrate.py
// builds them. A replay in the other UI language, or a run from before the server named these steps, still says
// what happened, with its numbers.
const ELEC_TOOLS = new Set(['scan_board', 'use_board', 'check_enclosure', 'write_circuit', 'check_pcb', 'export_fab', 'make_enclosure',
  'search_parts', 'part_info', 'write_device', 'build_device', 'write_firmware', 'quote_device', 'inspect_board', 'inspect_case', 'inspect_part']);
const PCB_LOOKS: Record<string, [string, string, string, string]> = {
  pcb: ['Looking at the routed board from the top', 'Смотрю на разведённую плату сверху', 'from the top', 'сверху'],
  pcb_bottom: ['Looking at the board from below', 'Смотрю на плату снизу', 'from below', 'снизу'],
  schematic: ['Reading the schematic', 'Читаю схему', 'schematic', 'схема'],
};
const REASON_RU: Record<string, string> = {
  'printability errors remain': 'остались ошибки печатаемости', 'needs fixes': 'нужны правки',
  'the reviewer found major problems': 'ревьюер нашёл серьёзные замечания',
  'the board is not ready': 'плата ещё не готова', 'the case check found errors': 'проверка корпуса нашла ошибки',
};
const SCALE: Record<string, [string, string]> = {
  board_holes: ['scale from its holes', 'масштаб по её отверстиям'], a4: ['scale from the A4 sheet', 'масштаб по листу A4'],
  card: ['scale from the bank card', 'масштаб по банковской карте'], board_outline: ['scale from its outline', 'масштаб по контуру платы'],
  none: ['no scale reference', 'без эталона масштаба'],
};
const CASE_PROBLEM: Record<string, [string, string]> = {
  port_blocked: ['{p} plug blocked', '{p} перекрыт'], board_collision: ['the board hits the case', 'плата задевает корпус'],
  component_clear: ['{p} touches a wall', '{p} касается стенки'], pcb_seated: ['the board is not held', 'плата не закреплена'],
  button_reach: ['{p} button out of reach', '{p} не нажимается'], button_unreachable: ['{p} button out of reach', '{p} не нажимается'],
  light_window: ['{p} window blocked', '{p} закрыт пластиком'],
  display_window: ['{p} display window blocked', 'окно экрана {p} перекрыто'], sensor_window: ['{p} sensor covered', 'датчик {p} закрыт'],
  sound_grille: ['no sound holes over {p}', 'нет отверстий над {p}'], cable_exit: ['no cable exit for {p}', 'нет выхода кабеля {p}'],
  battery_space: ['no room for {p}', 'нет места для {p}'],
  lid_fit: ['the lid does not fit', 'крышка не садится'], snap_strain: ['snaps bend {v} %', 'защёлки гнутся на {v} %'],
  metal_in_keepout: ['metal in an antenna keep-out', 'металл в зоне антенны'],
};

const mm2 = (v: any) => {
  const n = Number(v);
  return isFinite(n) ? String(+n.toFixed(2)) : String(v ?? '');
};
const sizeIn = (s: any, ru: boolean) => (Array.isArray(s) && s.length ? s.map(mm).join(' × ') + (ru ? ' мм' : ' mm') : '');
const count = (n: number, en: [string, string], ruW: [string, string, string], ru: boolean) => (ru ? ruN(n, ruW) : `${n} ${n === 1 ? en[0] : en[1]}`);
const usb = (v: number, ru: boolean) => (v >= 1.99 ? `USB ≥ 2 ${ru ? 'мм' : 'mm'}` : `USB ${mm2(v)} ${ru ? 'мм' : 'mm'}`);
const isNum = (v: any): v is number => typeof v === 'number' && isFinite(v);
const verOf = (v: any) => (/^\d+$/.test(String(v ?? '')) ? String(v) : '');
/** use_board with a whole board JSON (the tool takes it over board_id); the step preview may show it as '…'. */
const ownBoard = (a: any) => !!a.spec && (typeof a.spec === 'object' || !a.board_id);

function caseProblems(enc: Record<string, any>, ru: boolean): string[] {
  const out = (enc.errors ?? []).map((f: any) => {
    const [en, r] = CASE_PROBLEM[f.code] ?? [String(f.code ?? 'error').replace(/_/g, ' '), String(f.code ?? 'ошибка').replace(/_/g, ' ')];
    return (ru ? r : en).replace('{p}', f.part ? partName(f.part) : '').replace('{v}', isNum(f.value) ? f.value.toFixed(1) : '');
  });
  return out.length <= 3 ? out : [...out.slice(0, 2), ru ? `ещё ${out.length - 2}` : `+${out.length - 2} more`];
}

function caseDetails(enc: Record<string, any>, ru: boolean): string[] {
  const s = enc.summary ?? {};
  const out = isNum(s.usb_clearance_mm) ? [usb(s.usb_clearance_mm, ru)] : [];
  const aside = (enc.warnings ?? []).find((w: any) => w.code === 'button_unreachable');
  if (aside) out.push(`${partName(aside.part ?? '')} ${ru ? 'нажимается только без крышки' : 'only with the lid off'}`);
  else if (isNum(s.button_gap_mm)) out.push(ru ? 'все кнопки нажимаются' : 'all buttons reach');
  if (isNum(s.snap_strain_pct)) out.push(`${ru ? 'защёлки' : 'snaps'} ${s.snap_strain_pct.toFixed(1)} %`);
  return out;
}

const caseRan = (enc: any) => !!enc && typeof enc === 'object' && ('errors' in enc || 'summary' in enc);

function caseSuffix(enc: any, ru: boolean): string {
  if (!enc || typeof enc !== 'object') return '';
  if (!caseRan(enc)) return ru ? '; проверка корпуса не запустилась' : '; the case check did not run';
  if (enc.errors?.length) return `; ${ru ? 'плата пока не влезает' : 'does not fit the board yet'}: ${caseProblems(enc, ru).join(', ')}`;
  const u = enc.summary?.usb_clearance_mm;
  return `; ${ru ? 'плата влезает' : 'fits the board'}${isNum(u) ? ', ' + usb(u, ru) : ''}`;
}

/**
 * A version build of a case (pack 'enclosure' checks every build against its board): the case check as caseSuffix reads it.
 * A whole summary has the brief itself; a cut one only the short verdict up front. Older runs have neither: no suffix.
 */
function buildCase(r: Record<string, any>): Record<string, any> | undefined {
  if (r.enclosure && typeof r.enclosure === 'object') return r.enclosure;
  const f = r.case_fit;
  if (!f || typeof f !== 'object') return undefined;
  if (f.ran === false) return {};
  const problems = Array.isArray(f.problems) ? f.problems : [];
  // past six only their number came along: caseProblems shows the first two and counts the rest
  const more = Array.from({ length: isNum(f.more) ? f.more : 0 }, () => ({}));
  return { errors: [...problems, ...more], summary: isNum(f.usb_clearance_mm) ? { usb_clearance_mm: f.usb_clearance_mm } : {} };
}

/** DRC errors of a PCB brief as the board's own version counts them (drc_errors; an older brief's '3 DRC error(s): …'). */
const drc = (r: Record<string, any>) => {
  if (typeof r.drc_errors === 'number') return r.drc_errors;
  const m = /^(\d+) DRC/.exec(String(r.error ?? ''));
  return m ? Number(m[1]) : (r.errors?.length ?? 0);
};
const drcText = (n: number, ru: boolean) => count(n, ['DRC error', 'DRC errors'], ['ошибка DRC', 'ошибки DRC', 'ошибок DRC'], ru);

function intentText(intent: any, ru: boolean, met: boolean): string {
  if (!intent) return '';
  if (!intent.checked) return ru ? 'замысел не указан' : 'no intent stated';
  if (intent.ok === false) {
    const n = intent.issues?.length;
    return (ru ? 'замысел не выполнен' : 'intent not met') + (n ? `: ${n}` : '');
  }
  return met ? (ru ? 'замысел выполнен' : 'intent met') : '';
}

function elecCall(name: string, a: any, ru: boolean): string | undefined {
  const s = (v: any) => (typeof v === 'string' && v !== '…' ? v : '');
  const v = verOf(a.version);
  switch (name) {
    case 'search_parts': return `${ru ? 'Ищу в каталоге LCSC' : 'Searching the LCSC catalogue'}: ${s(a.query)}`;
    case 'part_info': return ru ? `Читаю распиновку ${s(a.lcsc) || 'детали'}` : `Reading the pins of ${s(a.lcsc) || 'the part'}`;
    case 'write_device': {
      const change = !!a.edits && !a.doc;
      const verb = change ? (ru ? 'Меняю устройство' : 'Changing the device') : ru ? 'Собираю схему устройства' : 'Drawing the device';
      return `${verb}: ${s(a.summary) || (ru ? 'первая версия' : 'first version')}`;
    }
    case 'build_device': return ru ? 'Размещаю детали и развожу плату' : 'Placing and routing the board';
    case 'write_firmware': return `${ru ? 'Пишу прошивку' : 'Writing the firmware'} (${s(a.lang) || 'arduino'})`;
    case 'quote_device': return ru ? `Считаю цену ${a.qty || 5} готовых устройств` : `Pricing ${a.qty || 5} finished devices`;
    case 'inspect_board':
      return s(a.focus) ? (ru ? `Рассматриваю на плате: ${a.focus}` : `Looking closely at ${a.focus} on the board`) : ru ? 'Рассматриваю плату' : 'Looking closely at the board';
    case 'inspect_case':
      return s(a.focus) ? (ru ? `Смотрю, как ${a.focus} стоит в корпусе` : `Looking at ${a.focus} in the case`) : ru ? 'Рассматриваю корпус' : 'Looking closely at the case';
    case 'inspect_part': return ru ? `Собираю всё о детали ${s(a.id)}` : `Reading everything about ${s(a.id) || 'the part'}`;
    case 'scan_board': return (ru ? 'Сканирую плату на фото' : 'Scanning the board on the photo') + (s(a.hint) ? `: ${a.hint}` : '');
    case 'use_board': {
      if (!ownBoard(a)) return `${ru ? 'Беру плату из базы' : 'Taking the board from the dataset'}: ${s(a.board_id)}`;
      const named = typeof a.spec === 'object' ? s(a.spec.name) : '';
      return (ru ? 'Подключаю плату по её размерам' : 'Attaching the board from its own numbers') + (named ? `: ${named}` : '');
    }
    case 'check_enclosure': return ru ? 'Сверяю корпус с платой' : 'Checking the case against the board';
    case 'write_circuit': {
      const change = !!a.edits && !a.source;
      const verb = change ? (ru ? 'Меняю схему' : 'Changing the circuit') : ru ? 'Пишу схему' : 'Writing the circuit';
      return `${verb}: ${s(a.summary) || (change ? (ru ? 'детали' : 'details') : ru ? 'первая версия' : 'first version')}`;
    }
    case 'check_pcb': return v ? (ru ? `Проверяю плату v${v}` : `Checking PCB v${v}`) : ru ? 'Проверяю плату' : 'Checking the board';
    case 'export_fab': return (ru ? 'Готовлю Gerber, BOM и CPL' : 'Exporting Gerber, BOM and CPL') + (v ? (ru ? ` для платы v${v}` : ` for PCB v${v}`) : '');
    case 'make_enclosure':
      return (v ? (ru ? `Делаю корпус для платы v${v}` : `Making the case for PCB v${v}`) : ru ? 'Делаю корпус для платы' : 'Making the case for the board') +
        (a.with_mockup !== false ? (ru ? ' и макет платы для печати' : ' and a printable mock-up of it') : '');
    case 'look': {
      const l = PCB_LOOKS[String(a.what)];
      return l ? l[ru ? 1 : 0] : undefined;
    }
  }
  return undefined;
}

function elecResult(name: string, a: any, r: Record<string, any>, ru: boolean): string | undefined {
  const pcb = ru ? 'Плата' : 'PCB';
  switch (name) {
    case 'search_parts': {
      if (!Array.isArray(r.parts)) return undefined;
      const hits = r.parts.slice(0, 3).map((h: any) => `${h.mpn} (${h.lcsc})`).join(', ');
      return `${count(r.parts.length, ['part', 'parts'], ['деталь', 'детали', 'деталей'], ru)}${hits ? ': ' + hits : ''}`;
    }
    case 'part_info':
      if (!r.lcsc) return undefined;
      return `${r.mpn} (${r.lcsc}): ${count((r.pins ?? []).length, ['pin', 'pins'], ['вывод', 'вывода', 'выводов'], ru)}, ${r.package}`;
    case 'write_device': {
      if (r.version == null) return undefined;
      const bits = [count(Number(r.nodes) || 0, ['part', 'parts'], ['деталь', 'детали', 'деталей'], ru), count(Number(r.nets) || 0, ['net', 'nets'], ['цепь', 'цепи', 'цепей'], ru)];
      if (r.issues?.length) bits.push(ru ? `проблем: ${r.issues.length}` : `problems: ${r.issues.length}`);
      if (r.design_errors?.length) bits.push(ru ? `ошибок в схеме: ${r.design_errors.length}` : `design errors: ${r.design_errors.length}`);
      if (r.design_warnings?.length) bits.push(ru ? `замечаний: ${r.design_warnings.length}` : `notes: ${r.design_warnings.length}`);
      return `${ru ? 'Устройство' : 'Device'} v${r.version} — ${bits.join(', ')}`;
    }
    case 'build_device': {
      if (r.version == null || !r.counts) return undefined;
      const size = Array.isArray(r.board_mm) ? `, ${r.board_mm.map((x: number) => +x.toFixed(1)).join(' × ')} ${ru ? 'мм' : 'mm'}` : '';
      const intent = r.intent && r.intent.ok === false ? `, ${intentText(r.intent, ru, false)}` : '';
      return `${pcb} v${r.version} — ${drcText(drc(r), ru)}${intent}${size}`;
    }
    case 'write_firmware': {
      if (!r.files) return undefined;
      const head = `${ru ? 'Прошивка' : 'Firmware'}: ${r.files.join(', ')}`;
      const chk = r.check && typeof r.check === 'object' ? r.check : null;
      if (!chk) return head;
      if (!chk.ran) return head + (ru ? ' — не проверена' : ' — not checked');
      if (chk.ok) return head + (ru ? ' — проверка пройдена' : ' — check passed');
      const n = typeof chk.errors === 'number' ? chk.errors : r.errors?.length || 1;
      return head + (ru ? ` — ошибок проверки: ${n}` : ` — check failed: ${n}`);
    }
    case 'inspect_board': {
      if (r.ok !== true || r.version == null) return undefined;
      const what = r.id ?? r.net ?? (r.focus === 'region' ? (ru ? 'участок' : 'a region') : ru ? 'вся плата' : 'the whole board');
      return `${pcb} v${r.version}: ${what}`;
    }
    case 'inspect_case': {
      if (r.ok !== true || r.case_version == null) return undefined;
      const mode = ({ assembled: ['assembled', 'в сборе'], lid_off: ['lid off', 'без крышки'], exploded: ['exploded', 'в разнесённом виде'],
        section: ['section', 'в разрезе'] } as Record<string, [string, string]>)[String(r.mode)] ?? [String(r.mode), String(r.mode)];
      return `${ru ? 'Корпус' : 'Case'} v${r.case_version}, ${mode[ru ? 1 : 0]}${r.part?.id ? ': ' + r.part.id : ''}`;
    }
    case 'inspect_part':
      if (r.ok !== true || !r.id) return undefined;
      return `${r.id}${Array.isArray(r.pins) ? ': ' + count(r.pins.length, ['pin', 'pins'], ['вывод', 'вывода', 'выводов'], ru) : ''}`;
    case 'quote_device':
      if (r.total_usd == null) return undefined;
      return ru ? `${r.qty} шт.: $${String(r.total_usd).replace('.', ',')} (${r.total_kzt} ₸), готово к ${String(r.eta).split('-').reverse().join('.')}` : `${r.qty} devices: $${r.total_usd} (${r.total_kzt} KZT), ready by ${r.eta}`;
    case 'scan_board':
    case 'use_board': {
      const b = r.board;
      if (r.ok === false || !b?.name) return undefined;
      const sz = sizeIn((b.size_mm ?? []).slice(0, 2), ru);
      const built = r.build?.ok && r.build.version ? (ru ? `; корпус обновлён: v${r.build.version}` : `; case updated: v${r.build.version}`) : '';
      if (name === 'use_board') {
        const head = ownBoard(a) ? (ru ? 'Плата по её размерам' : 'Board from its own numbers') : ru ? 'Плата из базы' : 'Board from the dataset';
        return `${head}: ${b.name}${sz ? ', ' + sz : ''}${built}`;
      }
      // a long board pushes the calibration past the cut: then the scale is not named at all
      const cal = r.calibration ?? {};
      const known = !!cal.method && cal.method !== 'none';
      const scale = !cal.method ? '' : ', ' + (SCALE[cal.method] ?? SCALE.none)[ru ? 1 : 0] + (known && isNum(cal.uncertainty_mm) ? ` ±${mm2(cal.uncertainty_mm)} ${ru ? 'мм' : 'mm'}` : '');
      if (b.source === 'photo') return `${ru ? 'Плата измерена' : 'Board measured'}: ${sz || b.name}${scale}${built}`;
      return `${ru ? 'Плата распознана' : 'Board read'}: ${b.name}${scale}${built}`;
    }
    case 'check_enclosure': {
      if (!caseRan(r)) return undefined;
      // the call line says what was checked: the result starts with the verdict, in the checks panel's words
      const board = r.board_name ?? (ru ? 'Плата' : 'The board');
      if (r.errors?.length) return `${board} ${ru ? 'пока не влезает' : 'does not fit yet'} — ${caseProblems(r, ru).join(', ')}`;
      const notes = (r.warnings ?? []).filter((w: any) => w.code !== 'button_unreachable').length;
      const details = [...caseDetails(r, ru), ...(notes ? [ru ? `замечаний: ${notes}` : `notes: ${notes}`] : [])].join(', ');
      return `${board} ${ru ? 'влезает' : 'fits'}${details ? ' — ' + details : ''}`;
    }
    case 'write_circuit': {
      if (r.version == null || !r.counts) return undefined;
      const c = r.counts;
      const parts = [drcText(drc(r), ru)];
      if (isNum(c.traces)) parts.push(count(c.traces, ['trace', 'traces'], ['трасса', 'трассы', 'трасс'], ru));
      if (isNum(c.vias)) parts.push(count(c.vias, ['via', 'vias'], ['переход', 'перехода', 'переходов'], ru));
      const intent = intentText(r.intent, ru, false);
      return `${pcb} v${r.version} — ${[...parts, ...(intent ? [intent] : [])].join(', ')}`;
    }
    case 'check_pcb': {
      if (r.version == null || !r.counts) return undefined;
      const fab = r.fab == null ? '' : String(r.fab).startsWith('ready') ? (ru ? 'файлы для фабрики готовы' : 'fab files ready') : ru ? 'файлов для фабрики нет' : 'no fab files';
      const intent = r.intent ? intentText(r.intent, ru, true) : '';
      return `${pcb} v${r.version}: ${[drcText(drc(r), ru), intent, fab].filter(Boolean).join(', ')}`;
    }
    case 'export_fab': {
      if (r.version == null) return undefined;
      if (r.ok === false) {
        const why = /DRC/.test(String(r.error ?? '')) ? (ru ? 'остались ошибки DRC' : 'it still has DRC errors') : ru ? 'экспорт не удался' : 'the export failed';
        return ru ? `Нет файлов для фабрики у платы v${r.version}: ${why}` : `No fab files for PCB v${r.version} yet: ${why}`;
      }
      const lines = (k: string) => (isNum(r[`${k}_lines`]) ? ` (${count(r[`${k}_lines`], ['line', 'lines'], ['строка', 'строки', 'строк'], ru)})` : '');
      const layers = Array.isArray(r.layers) ? ` (${count(r.layers.length, ['layer', 'layers'], ['слой', 'слоя', 'слоёв'], ru)})` : '';
      return `${ru ? `Файлы для фабрики, плата v${r.version}` : `Fab files for PCB v${r.version}`}: Gerber zip${layers}, BOM${lines('bom')}, CPL${lines('cpl')}`;
    }
    case 'make_enclosure': {
      if (r.ok === false || r.version == null) return undefined;
      const errors = (r.issues ?? []).filter((i: any) => i.severity === 'error').length;
      const state = r.printable === false || errors ? (ru ? `проблем: ${errors}` : `problems to fix: ${errors}`) : ru ? 'печатается' : 'printable';
      // the call line names the PCB version when the model gave one
      const of = r.pcb_version && !verOf(a.version) ? (ru ? ` для платы v${r.pcb_version}` : ` for PCB v${r.pcb_version}`) : '';
      const sz = sizeIn(r.size_mm, ru);
      return `${ru ? 'Корпус' : 'Case'} v${r.version}${of} — ${sz ? sz + ', ' : ''}${state}${caseSuffix(buildCase(r), ru)}`;
    }
    case 'look': {
      const l = PCB_LOOKS[String(a.what)];
      if (!l || r.version == null) return undefined;
      return `${pcb} v${r.version}${l === PCB_LOOKS.schematic ? ': ' : ' '}${l[ru ? 3 : 2]}`;
    }
    case 'finish':
      // the gate's reasons are a fixed set (the case and board gates among them): both languages are known
      if (r.accepted === true) return ru ? 'Одобрено' : 'Approved';
      if (r.accepted === false && r.reason && REASON_RU[r.reason]) return ru ? `Пока нет: ${REASON_RU[r.reason]}` : `Not yet: ${r.reason}`;
  }
  return undefined;
}

/**
 * A finish accepted while the reviewer still says revise (from the third finish on the review only reports), or with no
 * reviewer answering: handed over, not approved. Older servers titled these 'Approved' too, so the summary decides.
 */
function handedOver(r: Record<string, any>, ru: boolean): string | undefined {
  if (r.accepted !== true) return undefined;
  if (r.unresolved?.length || r.review === 'notes') return ru ? 'Сдано; у ревьюера остались замечания' : 'Handed over; the reviewer still has notes';
  if (r.review === 'none') return ru ? 'Сдано без проверки: ревьюер не ответил' : 'Handed over without a review: the reviewer did not answer';
  if (r.unchecked?.length) return ru ? 'Сдано; одну из проверок выполнить не удалось' : 'Handed over; a check could not run';
  return undefined;
}

// Server titles come in the language of the request; the local ones cover older events
// and the case where the UI language differs from the request language (a Russian run in the English UI too).
const looksRu = (s?: string) => !!s && /[а-яё]/i.test(s);
/** What servers sent for steps they had no words for yet: the tool's own name, or a bare 'Done'. */
const generic = (name: string, title?: string) => !title || title === name.replace(/_/g, ' ') || title === 'Done' || title === 'Готово';

export function callTitle(name: string, args: any, serverTitle?: string): string {
  const ru = i18n.lang === 'ru';
  const fits = !!serverTitle && ru === looksRu(serverTitle);
  if (fits && !(ELEC_TOOLS.has(name) && generic(name, serverTitle))) return serverTitle!;
  const own = elecCall(name, args ?? {}, ru);
  if (own) return own;
  if (fits) return serverTitle!;
  return ru ? ruCall(name, args) : enCall(name, args);
}

export function resultTitle(name: string, args: any, summary: string | undefined, ok: boolean, serverTitle?: string): string | undefined {
  const title = stepResult(name, args, summary, ok, serverTitle);
  return name === 'make_enclosure' && title ? onPlate(title) : title;
}

// a case step's size is its print plate (base, lid and the board mock-up laid out), not the case assembled: say so,
// also in the titles stored before the server did
function onPlate(title: string): string {
  return title.replace(/^(Case v\d+(?: for PCB v\d+)? — )(?=\d)/, '$1print plate ').replace(/^(Корпус v\d+(?: для платы v\d+)? — )(?=\d)/, '$1на столе ');
}

function stepResult(name: string, args: any, summary: string | undefined, ok: boolean, serverTitle?: string): string | undefined {
  const ru = i18n.lang === 'ru';
  if (name === 'finish') {
    const handed = handedOver(parseSummary(summary) ?? {}, ru);
    if (handed) return handed;
  }
  const fits = !!serverTitle && ru === looksRu(serverTitle);
  if (fits && !(ELEC_TOOLS.has(name) && generic(name, serverTitle))) return serverTitle;
  const r = parseSummary(summary) ?? (ok ? {} : { ok: false });
  const own = elecResult(name, args ?? {}, r, ru);
  if (own) return own;
  if (fits) return serverTitle;
  // a failed step's server title is already the friendly reading of the error (narrate.failure_title):
  // rebuilding it here would show the raw error instead
  if (serverTitle && (!ok || r.ok === false)) return serverTitle;
  return ru ? ruResult(name, args, r) : enResult(name, r);
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
  [/^Reading the board on the photo$/, 'Читаю плату на фото'],
  [/^Placing and routing the board$/, 'Расставляю детали и развожу плату'],
  [/^Placing and routing the board \(([\d.]+) x ([\d.]+) mm\)$/, (m) => `Развожу плату ${m[1]} × ${m[2]} мм`],
  [/^Looking at the case$/, 'Смотрю на корпус'],
  [/^Looking at the case around (.+)$/, (m) => `Смотрю на корпус вокруг ${m[1]}`],
  [/^Checking the firmware$/, 'Проверяю прошивку'],
  [/^Running the firmware on a virtual board$/, 'Запускаю прошивку на виртуальной плате'],
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
  finish: { en: ['ran the final review', (n) => `ran ${n} final reviews`], ru: ['провёл финальную проверку', (n) => `${ruN(n, ['финальная проверка', 'финальные проверки', 'финальных проверок'])}`] },
  concepts: { en: ['sketched concepts', () => 'sketched concepts'], ru: ['нарисовал эскизы', () => 'нарисовал эскизы'] },
  probe: { en: ['prepared a test piece', () => 'prepared test pieces'], ru: ['подготовил пробник', () => 'подготовил пробники'] },
  terrain: { en: ['loaded terrain', () => 'loaded terrain'], ru: ['загрузил рельеф', () => 'загрузил рельеф'] },
  skill: { en: ['saved a module', () => 'saved modules'], ru: ['сохранил модуль', () => 'сохранил модули'] },
  // electronics, by tool: a circuit is not "the model", a case check is not "measured the model"
  circuit: { en: ['routed the board', (n) => `routed ${n} board versions`], ru: ['развёл плату', (n) => `развёл ${ruN(n, ['версию платы', 'версии платы', 'версий платы'])}`] },
  pcb_check: { en: ['checked the board', (n) => `checked the board ${n} times`], ru: ['проверил плату', (n) => `проверил плату ${ruN(n, ['раз', 'раза', 'раз'])}`] },
  fab: { en: ['exported the fab files', () => 'exported the fab files'], ru: ['выгрузил файлы для фабрики', () => 'выгрузил файлы для фабрики'] },
  case: { en: ['made the case', (n) => `made ${n} cases`], ru: ['сделал корпус', (n) => `сделал ${ruN(n, ['корпус', 'корпуса', 'корпусов'])}`] },
  case_check: { en: ['checked the case against the board', (n) => `checked the case ${n} times`], ru: ['сверил корпус с платой', (n) => `сверил корпус с платой ${ruN(n, ['раз', 'раза', 'раз'])}`] },
  board_scan: { en: ['read the board from the photo', () => 'read the board from the photo'], ru: ['прочитал плату на фото', () => 'прочитал плату на фото'] },
  board: { en: ['picked the board', () => 'picked the board'], ru: ['выбрал плату', () => 'выбрал плату'] },
  // a device, by tool: the schematic, its firmware and the looks at what came out each say so
  parts: { en: ['looked up parts', () => 'looked up parts'], ru: ['подобрал детали', () => 'подобрал детали'] },
  device: { en: ['drew the schematic', (n) => `drew ${n} schematic versions`], ru: ['нарисовал схему', (n) => `нарисовал ${ruN(n, ['версию схемы', 'версии схемы', 'версий схемы'])}`] },
  firmware: { en: ['wrote the firmware', (n) => `wrote the firmware ${n} times`], ru: ['написал прошивку', (n) => `написал прошивку ${ruN(n, ['раз', 'раза', 'раз'])}`] },
  look_board: { en: ['looked at the board', (n) => `looked at the board ${n} times`], ru: ['осмотрел плату', (n) => `осмотрел плату ${ruN(n, ['раз', 'раза', 'раз'])}`] },
  look_case: { en: ['looked at the case', (n) => `looked at the case ${n} times`], ru: ['осмотрел корпус', (n) => `осмотрел корпус ${ruN(n, ['раз', 'раза', 'раз'])}`] },
  look_part: { en: ['read up on a part', (n) => `read up on ${n} parts`], ru: ['изучил деталь', (n) => `изучил ${ruN(n, ['деталь', 'детали', 'деталей'])}`] },
  quote: { en: ['worked out the price', () => 'worked out the price'], ru: ['посчитал цену', () => 'посчитал цену'] },
};
const GROUP_OF: Record<string, string> = {
  render: 'look', compare: 'look', fit: 'measure', caliper: 'measure', scene: 'measure', standard: 'search',
};
const GROUP_OF_TOOL: Record<string, string> = {
  write_circuit: 'circuit', check_pcb: 'pcb_check', export_fab: 'fab', make_enclosure: 'case', check_enclosure: 'case_check',
  scan_board: 'board_scan', use_board: 'board',
  search_parts: 'parts', part_info: 'parts', write_device: 'device', build_device: 'circuit', write_firmware: 'firmware',
  inspect_board: 'look_board', inspect_case: 'look_case', inspect_part: 'look_part', quote_device: 'quote',
};

export function groupSummary(items: { kind: string; tkind?: string; name?: string }[]): string {
  const counts = new Map<string, number>();
  for (const it of items) {
    const k = it.kind === 'tool' ? (GROUP_OF_TOOL[it.name ?? ''] ?? GROUP_OF[it.tkind ?? ''] ?? it.tkind ?? 'build') : null;
    if (k && PHRASE[k]) counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const lang = i18n.lang === 'ru' ? 'ru' : 'en';
  const parts = [...counts].map(([k, n]) => (n === 1 ? PHRASE[k][lang][0] : PHRASE[k][lang][1](n)));
  const s = parts.join(', ') || (lang === 'ru' ? 'подготовка' : 'getting ready');
  return s.charAt(0).toUpperCase() + s.slice(1);
}
