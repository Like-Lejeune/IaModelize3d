// Strings of the instant sticker and the collection plate, English and Russian. The language is the app's
// (i18n.lang from $lib/i18n.svelte, read only).
import { i18n } from '$lib/i18n.svelte';

type Dict = Record<string, string>;

const en: Dict = {
  sticker_size: 'Longest side',
  keep: 'Add to collection',
  figure: 'Make a figurine · ~5 min',
  figure_msg: 'Make a collectible miniature of this: {label}, about {size} mm along its longest side.',
  chip_sam: 'SAM 3.1 · {s} s',
  chip_name: 'Muse Spark · {name}',
  chip_naming: 'Muse Spark · naming…',
  lifting: 'Lifting into 3D…',
  built: '3D in {s} s',
  server_preview: 'Preview from the server',
  preview_label: '3D sticker preview',
  kept: 'In your collection',
  kept_hint: '{w} × {h} mm · ≈ {min} min · {g} g on the farm’s Bambu Lab A1',
  kept_plate: 'Collect a few more and print them all on one plate.',
  two_colour: 'Two colours: swap filament at 1.6 mm',
  // collection
  walk: 'Walk · {date}',
  select: 'Select',
  select_all: 'All',
  cancel: 'Cancel',
  select_hint: 'Tap the finds to put on one plate',
  print_n: 'Print {n} on one plate',
  print_one: 'Pick at least one find',
  plate_building: 'Laying out the plate…',
  plate_bed: '{printer} · {w} × {h} mm bed',
  plate_ready: 'Plate of {n}: {w} × {h} mm',
  plate_est: '≈ {min} min · {g} g · no supports',
  plate_price: 'Print at the farm ≈ {print}, delivery {delivery}',
  plate_open: 'Open the plate',
  a1_mini_note: 'Too big for an A1 mini (180 × 180 mm bed): print it on an A1, or pick fewer finds.',
  a1_mini_ok: 'Fits an A1 mini too.',
  err_plate_too_big: 'These finds do not fit one 256 × 256 mm bed: pick fewer, or a smaller size.',
  err_keep_busy: 'The agent is modelling this find right now: open the project or wait for it.',
  err_nothing_to_plate: 'None of the chosen finds has an outline to make a sticker of.',
  err_no_selection: 'Nothing is selected on this photo yet: tap the object.',
};

const ru: Dict = {
  sticker_size: 'По длинной стороне',
  keep: 'В коллекцию',
  figure: 'Сделать фигурку · ~5 мин',
  figure_msg: 'Сделай коллекционную миниатюру: {label}, около {size} мм по длинной стороне.',
  chip_sam: 'SAM 3.1 · {s} с',
  chip_name: 'Muse Spark · {name}',
  chip_naming: 'Muse Spark · называю…',
  lifting: 'Поднимаю в 3D…',
  built: '3D за {s} с',
  server_preview: 'Превью с сервера',
  preview_label: 'Превью 3D-стикера',
  kept: 'В коллекции',
  kept_hint: '{w} × {h} мм · ≈ {min} мин · {g} г на Bambu Lab A1 фермы',
  kept_plate: 'Соберите ещё несколько и напечатайте всё одним столом.',
  two_colour: 'Два цвета: смена филамента на 1,6 мм',
  walk: 'Прогулка · {date}',
  select: 'Выбрать',
  select_all: 'Все',
  cancel: 'Отмена',
  select_hint: 'Отметьте находки для одного стола',
  print_n: 'Напечатать {n} на одном столе',
  print_one: 'Отметьте хотя бы одну находку',
  plate_building: 'Раскладываю стол…',
  plate_bed: '{printer} · стол {w} × {h} мм',
  plate_ready: 'Стол из {n}: {w} × {h} мм',
  plate_est: '≈ {min} мин · {g} г · без поддержек',
  plate_price: 'Печать на ферме ≈ {print}, доставка {delivery}',
  plate_open: 'Открыть стол',
  a1_mini_note: 'На A1 mini (стол 180 × 180 мм) не поместится: печатайте на A1 или выберите меньше находок.',
  a1_mini_ok: 'Поместится и на A1 mini.',
  err_plate_too_big: 'Эти находки не помещаются на один стол 256 × 256 мм: выберите меньше или размер поменьше.',
  err_keep_busy: 'Агент сейчас моделирует эту находку: откройте проект или подождите.',
  err_nothing_to_plate: 'Ни у одной из выбранных находок нет контура для стикера.',
  err_no_selection: 'На фото ещё ничего не выделено: коснитесь предмета.',
};

export function ct(key: string, vars?: Record<string, string | number>): string {
  let s = (i18n.lang === 'ru' ? ru[key] : undefined) ?? en[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

/** Tenge first, US dollars in brackets: "4 890 ₸ ($9.40)". */
export function money(kzt: number, usd?: number | null): string {
  const t = `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(kzt).replace(/ /g, ' ')} ₸`;
  return usd == null ? t : `${t} ($${usd.toFixed(2)})`;
}

/** A number in the UI language: "4.9" / "4,9". */
export function num(v: number, digits = 1): string {
  return v.toLocaleString(i18n.lang === 'ru' ? 'ru-RU' : 'en-GB', { maximumFractionDigits: digits });
}

/** "30 Oct" / "30 окт." for a unix time. */
export function day(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(i18n.lang === 'ru' ? 'ru-RU' : 'en-GB', { day: 'numeric', month: 'short' });
}

/** Seconds with one decimal under 10 s ("1.4"), whole seconds above; a comma in Russian. */
export function secs(ms: number): string {
  const s = ms / 1000;
  const v = s < 10 ? s.toFixed(1) : String(Math.round(s));
  return i18n.lang === 'ru' ? v.replace('.', ',') : v;
}
