// Program param labels, groups and choices in the person's language. Programs stay English (the model reads and
// writes them); this only changes what the panel shows. Exact phrases first (every label the shipped programs use),
// then word rules for the model's own labels when every word is known ("Lid thickness" -> "Толщина крышки",
// "Screw hole diameter" -> "Диаметр отверстия под винт"); anything else stays English. Plain TypeScript with no
// Svelte state, so `node --test web/test/paramtext.test.ts` imports it as is.

export type Lang = 'en' | 'ru';

// ------------------------------------------------------------------ exact phrases (lower case keys)
const EXACT: Record<string, string> = {
  // agent/elec_tools.py: the board case
  wall: 'Стенка',
  floor: 'Дно',
  lid: 'Крышка',
  'gap around the board': 'Зазор вокруг платы',
  'space under the board': 'Высота под платой',
  'gap around plugs': 'Зазор вокруг штекеров',
  'led window': 'Окно светодиода',
  'board mount': 'Крепление платы',
  'printed stand-in for the pcb': 'Печатный макет платы',
  layout: 'Вид',
  'show the board': 'Показать плату',
  // agent/examples.py, showcase.py, agent/prompts.py (params and viewer handles)
  'shelf thickness': 'Толщина полки',
  'clamp depth': 'Глубина зажима',
  'hook reach': 'Вылет крючка',
  reach: 'Вылет',
  width: 'Ширина',
  thickness: 'Толщина',
  'hole (m5 clearance)': 'Отверстие под M5',
  'edge chamfer': 'Фаска по краю',
  height: 'Высота',
  'bottom radius': 'Радиус снизу',
  'top radius': 'Радиус сверху',
  bottom: 'Низ',
  top: 'Верх',
  ribs: 'Рёбра',
  twist: 'Закрутка',
  'holder hole': 'Отверстие под патрон',
  length: 'Длина',
  depth: 'Глубина',
  hooks: 'Крючки',
  angle: 'Угол',
  'lean angle': 'Угол наклона',
  'phone with case': 'Телефон в чехле',
  'back rest': 'Спинка',
  'front lip': 'Передний бортик',
  // collect.py, vision/relief.py: snap stickers and the collection plate
  'sticker size': 'Размер стикера',
  gap: 'Зазор',
  'longest side': 'Длинная сторона',
  relief: 'Рельеф',
  base: 'Основание',
  border: 'Рамка',
  // labels the model wrote in real runs that the word rules would get wrong or cannot read
  'overall height': 'Общая высота',
  'figure height': 'Высота фигурки',
  'ear height': 'Высота ушей',
  'eye diameter': 'Диаметр глаз',
  'eye slant': 'Наклон глаз',
  'nose color': 'Цвет носа',
  'tail diameter': 'Диаметр хвоста',
  'length nose to hind toe': 'Длина от носа до задних лап',
  'wire axle diameter': 'Диаметр проволочной оси',
  'clip opening': 'Раскрытие клипсы',
  'board clearance': 'Зазор вокруг платы',
  'headroom over tallest part': 'Запас над самой высокой деталью',
  'half thickness': 'Половина толщины',
  'corner radius': 'Радиус углов',
  'side gap': 'Зазор на сторону',
  'side clearance': 'Зазор на сторону',
  'side length': 'Длина стороны',
  'rounded corners': 'Скруглённые углы',
  puff: 'Пухлость',
  style: 'Стиль',
  seed: 'Вариант',
  variation: 'Вариант',
  'random seed': 'Вариант',
};

const GROUPS: Record<string, string> = {
  shell: 'Корпус',
  fit: 'Посадка',
  access: 'Доступ',
  shape: 'Форма',
  form: 'Форма',
  strength: 'Прочность',
  size: 'Размеры',
  sizes: 'Размеры',
  dimensions: 'Размеры',
  color: 'Цвет',
  colour: 'Цвет',
  colors: 'Цвета',
  colours: 'Цвета',
  base: 'Основание',
  mount: 'Крепление',
  mounting: 'Крепление',
  clearance: 'Зазоры',
  clearances: 'Зазоры',
  tolerances: 'Допуски',
  layout: 'Раскладка',
  view: 'Вид',
  look: 'Внешний вид',
  appearance: 'Внешний вид',
  style: 'Стиль',
  details: 'Детали',
  detail: 'Детали',
  advanced: 'Дополнительно',
  extras: 'Дополнительно',
  geometry: 'Геометрия',
  structure: 'Конструкция',
  features: 'Элементы',
  hardware: 'Крепёж',
  fasteners: 'Крепёж',
  assembly: 'Сборка',
  print: 'Печать',
  printing: 'Печать',
  main: 'Основное',
  general: 'Общее',
  options: 'Параметры',
  decor: 'Декор',
  decoration: 'Декор',
  ventilation: 'Вентиляция',
  text: 'Текст',
};

/** Choice values the panel shows on its chips (the program still gets the English value). */
const OPTIONS: Record<string, string> = {
  hole: 'отверстие',
  skin: 'тонкий слой',
  peg: 'штифты',
  pegs: 'штифты',
  screw: 'винты',
  screws: 'винты',
  auto: 'авто',
  print: 'для печати',
  assembled: 'в сборе',
  none: 'нет',
  yes: 'да',
  no: 'нет',
  on: 'вкл',
  off: 'выкл',
  // a yes/no param's value where a card lists it as text
  true: 'да',
  false: 'нет',
};

// ------------------------------------------------------------------ word rules
type Gender = 'm' | 'f' | 'n';
const GI: Record<Gender, number> = { m: 0, f: 1, n: 2 }; // index into adjective forms; 3 is plural

// What is measured: Russian, gender, and whether the thing it measures goes plural ("Hole spacing" -> "Шаг отверстий").
const DIMS: Record<string, [string, Gender, boolean?]> = {
  width: ['ширина', 'f'],
  height: ['высота', 'f'],
  depth: ['глубина', 'f'],
  length: ['длина', 'f'],
  thickness: ['толщина', 'f'],
  diameter: ['диаметр', 'm'],
  radius: ['радиус', 'm'],
  gap: ['зазор', 'm'],
  clearance: ['зазор', 'm'],
  angle: ['угол', 'm'],
  count: ['количество', 'n', true],
  size: ['размер', 'm'],
  spacing: ['шаг', 'm', true],
  pitch: ['шаг', 'm'],
  step: ['шаг', 'm'],
  offset: ['смещение', 'n'],
  chamfer: ['фаска', 'f'],
  bevel: ['фаска', 'f'],
  fillet: ['скругление', 'n'],
  rounding: ['скругление', 'n'],
  tolerance: ['допуск', 'm'],
  margin: ['отступ', 'm'],
  inset: ['отступ', 'm'],
  reach: ['вылет', 'm'],
  distance: ['расстояние', 'n'],
  overhang: ['свес', 'm'],
  tilt: ['наклон', 'm'],
  slant: ['наклон', 'm'],
  twist: ['закрутка', 'f'],
  color: ['цвет', 'm'],
  colour: ['цвет', 'm'],
  scale: ['масштаб', 'm'],
  rotation: ['поворот', 'm'],
  position: ['положение', 'n'],
  protrusion: ['выступ', 'm'],
  taper: ['сужение', 'n'],
  draft: ['уклон', 'm'],
  travel: ['ход', 'm'],
};

interface Noun {
  /** nominative and genitive, singular then plural; null plural for nouns people do not count (дно) */
  f: [string, string, string | null, string | null];
  g: Gender;
  /** a hole-like thing named after what goes in it: "Screw hole" -> "Отверстие под винт" */
  r: boolean;
}

// 'english: им.ед род.ед им.мн род.мн род [r]' ('-' for no plural). Ambiguous words (body, head, case, arm, wire,
// seat, key) are left out on purpose: "Body width" could be a figure's or a box's and stays English.
const NOUN_LINES = `
wall: стенка стенки стенки стенок f
floor: дно дна - - n
lid: крышка крышки крышки крышек f
cover: крышка крышки крышки крышек f
cap: колпачок колпачка колпачки колпачков m
base: основание основания основания оснований n
clip: клипса клипсы клипсы клипс f
snap: защёлка защёлки защёлки защёлок f
latch: защёлка защёлки защёлки защёлок f
slot: паз паза пазы пазов m r
hole: отверстие отверстия отверстия отверстий n r
pocket: гнездо гнезда гнёзда гнёзд n r
socket: гнездо гнезда гнёзда гнёзд n r
recess: углубление углубления углубления углублений n r
cutout: вырез выреза вырезы вырезов m r
notch: вырез выреза вырезы вырезов m r
groove: канавка канавки канавки канавок f r
channel: канал канала каналы каналов m r
opening: проём проёма проёмы проёмов m r
window: окно окна окна окон n
board: плата платы платы плат f
pcb: плата платы платы плат f
shelf: полка полки полки полок f
hook: крючок крючка крючки крючков m
screw: винт винта винты винтов m
bolt: болт болта болты болтов m
nut: гайка гайки гайки гаек f
washer: шайба шайбы шайбы шайб f
insert: вставка вставки вставки вставок f
magnet: магнит магнита магниты магнитов m
thread: резьба резьбы резьбы резьб f
rib: ребро ребра рёбра рёбер n
post: стойка стойки стойки стоек f
standoff: стойка стойки стойки стоек f
peg: штифт штифта штифты штифтов m
pin: штифт штифта штифты штифтов m
leg: ножка ножки ножки ножек f
foot: опора опоры опоры опор f
support: опора опоры опоры опор f
handle: ручка ручки ручки ручек f
knob: ручка ручки ручки ручек f
grip: рукоятка рукоятки рукоятки рукояток f
cable: кабель кабеля кабели кабелей m
cord: шнур шнура шнуры шнуров m
tube: трубка трубки трубки трубок f
pipe: труба трубы трубы труб f
rod: стержень стержня стержни стержней m
bar: планка планки планки планок f
axle: ось оси оси осей f
shaft: вал вала валы валов m
wheel: колесо колеса колёса колёс n
gear: шестерня шестерни шестерни шестерён f
tooth: зуб зуба зубья зубьев m
spoke: спица спицы спицы спиц f
button: кнопка кнопки кнопки кнопок f
port: порт порта порты портов m
plug: штекер штекера штекеры штекеров m
connector: разъём разъёма разъёмы разъёмов m
led: светодиод светодиода светодиоды светодиодов m
sensor: датчик датчика датчики датчиков m
screen: экран экрана экраны экранов m
display: экран экрана экраны экранов m
camera: камера камеры камеры камер f
fan: вентилятор вентилятора вентиляторы вентиляторов m
switch: переключатель переключателя переключатели переключателей m
lip: бортик бортика бортики бортиков m
rim: бортик бортика бортики бортиков m
edge: край края края краёв m
corner: угол угла углы углов m
border: рамка рамки рамки рамок f
frame: рамка рамки рамки рамок f
plate: пластина пластины пластины пластин f
sticker: стикер стикера стикеры стикеров m
tile: плитка плитки плитки плиток f
spring: пружина пружины пружины пружин f
tray: лоток лотка лотки лотков m
stand: подставка подставки подставки подставок f
holder: держатель держателя держатели держателей m
mount: крепление крепления крепления креплений n
bracket: кронштейн кронштейна кронштейны кронштейнов m
clamp: зажим зажима зажимы зажимов m
jaw: губка губки губки губок f
flange: фланец фланца фланцы фланцев m
boss: бобышка бобышки бобышки бобышек f
spacer: проставка проставки проставки проставок f
ring: кольцо кольца кольца колец n
loop: петля петли петли петель f
hinge: петля петли петли петель f
strap: ремешок ремешка ремешки ремешков m
text: текст текста тексты текстов m
font: шрифт шрифта шрифты шрифтов m
letter: буква буквы буквы букв f
logo: логотип логотипа логотипы логотипов m
pattern: узор узора узоры узоров m
grid: сетка сетки сетки сеток f
cell: ячейка ячейки ячейки ячеек f
compartment: отсек отсека отсеки отсеков m
divider: перегородка перегородки перегородки перегородок f
box: коробка коробки коробки коробок f
drawer: ящик ящика ящики ящиков m
pot: горшок горшка горшки горшков m
vase: ваза вазы вазы ваз f
cup: стакан стакана стаканы стаканов m
shade: плафон плафона плафоны плафонов m
lamp: лампа лампы лампы ламп f
bulb: лампа лампы лампы ламп f
phone: телефон телефона телефоны телефонов m
enclosure: корпус корпуса корпуса корпусов m
housing: корпус корпуса корпуса корпусов m
shell: оболочка оболочки оболочки оболочек f
layer: слой слоя слои слоёв m
nozzle: сопло сопла сопла сопел n
dot: точка точки точки точек f
cube: кубик кубика кубики кубиков m
block: блок блока блоки блоков m
backrest: спинка спинки спинки спинок f
blade: лопасть лопасти лопасти лопастей f
door: дверца дверцы дверцы дверец f
tab: язычок язычка язычки язычков m
tongue: язычок язычка язычки язычков m
figure: фигурка фигурки фигурки фигурок f
model: модель модели модели моделей f
part: деталь детали детали деталей f
piece: деталь детали детали деталей f
ear: ухо уха уши ушей n
eye: глаз глаза глаза глаз m
nose: нос носа носы носов m
tail: хвост хвоста хвосты хвостов m
paw: лапа лапы лапы лап f
wing: крыло крыла крылья крыльев n
cheek: щека щеки щёки щёк f
style: стиль стиля стили стилей m
`;

const NOUNS: Record<string, Noun> = {};
for (const line of NOUN_LINES.trim().split('\n')) {
  const [en, rest] = line.split(':');
  const w = rest.trim().split(/\s+/);
  const opt = (s: string) => (s === '-' ? null : s);
  NOUNS[en.trim()] = { f: [w[0], w[1], opt(w[2]), opt(w[3])], g: w[4] as Gender, r: w[5] === 'r' };
}
const IRREGULAR: Record<string, string> = { teeth: 'tooth', feet: 'foot', shelves: 'shelf' };

interface Adj {
  /** nominative and genitive: m f n plural */
  nom: string[];
  gen: string[];
  /** where it is said after a measure instead: "Top gap" -> "Зазор сверху" */
  adv?: string;
  /** belongs to the measure, not the part: "Overall body width" -> "Общая ширина …" */
  dim?: boolean;
  /** may stand right before a measure: "Inner diameter" -> "Внутренний диаметр" */
  bare?: boolean;
}
const hard = (s: string, end = 'ый'): Adj => ({ nom: [s + end, s + 'ая', s + 'ое', s + 'ые'], gen: [s + 'ого', s + 'ой', s + 'ого', s + 'ых'] });
const soft = (s: string): Adj => ({ nom: [s + 'ий', s + 'яя', s + 'ее', s + 'ие'], gen: [s + 'его', s + 'ей', s + 'его', s + 'их'] });
const velar = (s: string): Adj => ({ nom: [s + 'ий', s + 'ая', s + 'ое', s + 'ие'], gen: [s + 'ого', s + 'ой', s + 'ого', s + 'их'] });
const sib = (s: string): Adj => ({ nom: [s + 'ий', s + 'ая', s + 'ее', s + 'ие'], gen: [s + 'его', s + 'ей', s + 'его', s + 'их'] });

const ADJS: Record<string, Adj> = {
  top: { ...soft('верхн'), adv: 'сверху' },
  upper: { ...soft('верхн'), adv: 'сверху' },
  bottom: { ...soft('нижн'), adv: 'снизу' },
  lower: { ...soft('нижн'), adv: 'снизу' },
  front: { ...soft('передн'), adv: 'спереди' },
  back: { ...soft('задн'), adv: 'сзади' },
  rear: { ...soft('задн'), adv: 'сзади' },
  side: { ...hard('боков', 'ой'), adv: 'сбоку' },
  left: { ...hard('лев'), adv: 'слева' },
  right: { ...hard('прав'), adv: 'справа' },
  inner: { ...soft('внутренн'), bare: true },
  inside: { ...soft('внутренн'), bare: true },
  internal: { ...soft('внутренн'), bare: true },
  outer: { ...soft('внешн'), bare: true },
  outside: { ...soft('внешн'), bare: true },
  external: { ...soft('внешн'), bare: true },
  overall: { ...sib('общ'), dim: true },
  total: { ...sib('общ'), dim: true },
  max: { ...hard('максимальн'), dim: true },
  maximum: { ...hard('максимальн'), dim: true },
  min: { ...hard('минимальн'), dim: true },
  minimum: { ...hard('минимальн'), dim: true },
  nominal: { ...hard('номинальн'), dim: true },
  extra: { ...hard('дополнительн'), bare: true },
  additional: { ...hard('дополнительн'), bare: true },
  center: { ...hard('центральн'), bare: true },
  centre: { ...hard('центральн'), bare: true },
  central: { ...hard('центральн'), bare: true },
  middle: { ...hard('центральн'), bare: true },
  main: hard('основн', 'ой'),
  mounting: hard('крепёжн'),
  vent: hard('вентиляционн'),
  round: hard('кругл'),
  square: hard('квадратн'),
  flat: velar('плоск'),
};
// nouns that name a kind, not an owner, when another noun follows: "Spring clip" -> "Пружинная клипса"
const KIND: Record<string, Adj> = { spring: hard('пружинн') };

const VERBS: Record<string, string> = { show: 'Показать', add: 'Добавить', include: 'Добавить' };
const ARTICLES = new Set(['the', 'a', 'an']);
const UNITS: Record<string, string> = { mm: 'мм', cm: 'см', deg: '°', degrees: '°', '°': '°', '%': '%', g: 'г', s: 'с' };
// an abbreviation or a size code: USB, USB-C, M3, M2.5, GPIO; said after its noun ("USB port" -> "Порт USB")
const TAG = /^(?=.*[A-Z])[A-Z0-9][A-Z0-9.\-]+$/;

type Case = 'nom' | 'gen' | 'acc';
interface Unit {
  adjs: Adj[];
  tags: string[];
  noun: Noun | null; // null: a tag on its own ("USB width")
  plural: boolean;
}

function noun(w: string): [Noun, boolean] | null {
  if (NOUNS[w]) return [NOUNS[w], false];
  const sg = IRREGULAR[w] ?? (w.endsWith('es') && NOUNS[w.slice(0, -2)] ? w.slice(0, -2) : w.endsWith('s') ? w.slice(0, -1) : '');
  return sg && NOUNS[sg] ? [NOUNS[sg], true] : null;
}

// inanimate accusative: feminine -а/-я turn into -у/-ю, the rest is the nominative
const accF = (s: string) => s.replace(/а$/, 'у').replace(/я$/, 'ю');
const accAdjF = (s: string) => s.replace(/ая$/, 'ую').replace(/яя$/, 'юю');

function adjForm(a: Adj, c: Case, gi: number): string {
  if (c === 'gen') return a.gen[gi];
  return c === 'acc' && gi === 1 ? accAdjF(a.nom[1]) : a.nom[gi];
}

function unitText(u: Unit, c: Case, forcePlural = false): string | null {
  if (!u.noun) return u.tags.join(' ');
  const pl = u.plural || forcePlural;
  const [nomS, genS, nomP, genP] = u.noun.f;
  let w = pl ? (c === 'gen' ? genP : nomP) : c === 'gen' ? genS : nomS;
  if (w == null) return null;
  if (c === 'acc' && !pl && u.noun.g === 'f') w = accF(w);
  const gi = pl ? 3 : GI[u.noun.g];
  return [...u.adjs.map((a) => adjForm(a, c, gi)), w, ...u.tags].join(' ');
}

/** English noun phrase -> units ("M3 screw hole" -> [screw +M3, hole]); at most a head and one part it belongs to. */
function parseNP(words: string[], raw: string[]): Unit[] | null {
  const units: Unit[] = [];
  let adjs: Adj[] = [];
  let tags: string[] = [];
  for (let i = 0; i < words.length; i++) {
    const kind = i < words.length - 1 ? KIND[words[i]] : undefined;
    const n = kind ? null : noun(words[i]);
    if (kind) adjs.push(kind);
    else if (n) {
      units.push({ adjs, tags, noun: n[0], plural: n[1] });
      adjs = [];
      tags = [];
    } else if (ADJS[words[i]]) adjs.push(ADJS[words[i]]);
    else if (TAG.test(raw[i])) tags.push(raw[i]);
    else return null;
  }
  if (adjs.length) return null;
  if (tags.length) {
    if (units.length) units[units.length - 1].tags.push(...tags);
    else units.push({ adjs: [], tags, noun: null, plural: false });
  }
  return units.length && units.length <= 2 ? units : null;
}

function npText(units: Unit[], c: Case, forcePlural = false): string | null {
  const head = units[units.length - 1];
  const h = unitText(head, c, forcePlural);
  if (h == null || units.length === 1) return h;
  const of = head.noun?.r ? unitText(units[0], 'acc') : unitText(units[0], 'gen');
  return of == null ? null : `${h} ${head.noun?.r ? 'под ' : ''}${of}`;
}

function rules(words: string[], raw: string[]): string | null {
  if (!words.length) return null;
  // "Number of hooks" -> "Количество крючков"
  if (words[0] === 'number' && words[1] === 'of') {
    const np = parseNP(words.slice(2), raw.slice(2));
    const s = np && npText(np, 'gen', true);
    return s ? `количество ${s}` : null;
  }
  // "Height of lid" reads as "Lid height"
  const of = words.indexOf('of');
  if (of > 0) return rules([...words.slice(of + 1), ...words.slice(0, of)], [...raw.slice(of + 1), ...raw.slice(0, of)]);
  // "Show lid" -> "Показать крышку"
  if (VERBS[words[0]] && words.length > 1) {
    const np = parseNP(words.slice(1), raw.slice(1));
    const s = np && npText(np, 'acc');
    return s ? `${VERBS[words[0]]} ${s}` : null;
  }
  const last = words[words.length - 1];
  const dim = DIMS[last];
  if (!dim) {
    const np = parseNP(words, raw);
    return np && np.some((u) => u.noun) ? npText(np, 'nom') : null;
  }
  const [ru, g, pl] = dim;
  let pre = words.slice(0, -1);
  let preRaw = raw.slice(0, -1);
  const lead: string[] = [];
  while (pre.length && ADJS[pre[0]]?.dim) {
    lead.push(adjForm(ADJS[pre[0]], 'nom', GI[g]));
    pre = pre.slice(1);
    preRaw = preRaw.slice(1);
  }
  const head = [...lead, ru].join(' ');
  if (!pre.length) return head;
  // "Top gap" -> "Зазор сверху"
  if (pre.length === 1 && ADJS[pre[0]]?.adv) return `${head} ${ADJS[pre[0]].adv}`;
  // "Inner diameter" -> "Внутренний диаметр"
  if (pre.every((w) => ADJS[w]?.bare)) return [...lead, ...pre.map((w) => adjForm(ADJS[w], 'nom', GI[g])), ru].join(' ');
  const np = parseNP(pre, preRaw);
  const s = np && npText(np, 'gen', !!pl);
  return s ? `${head} ${s}` : null;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const key = (s: string) => s.trim().replace(/\s+/g, ' ').toLowerCase();

/** The Russian for an English label, or null when the glossary does not know every word. */
export function ruLabel(label: string): string | null {
  const exact = EXACT[key(label)];
  if (exact) return exact;
  // param names stand in for missing labels: wall_thickness, wallThickness
  let s = label.replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[:.]$/, '').trim();
  let unit = '';
  const m = s.match(/^(.*\S)\s*\(\s*([^()\s]+)\s*\)$/);
  if (m && UNITS[m[2].toLowerCase()]) {
    s = m[1];
    unit = ` (${UNITS[m[2].toLowerCase()]})`;
  }
  if (!/^[A-Za-z0-9 .\-]+$/.test(s)) return null;
  const again = EXACT[key(s)];
  if (again) return again + unit;
  const raw = s.split(' ').filter((w) => w && !ARTICLES.has(w.toLowerCase()));
  const out = rules(raw.map((w) => w.toLowerCase()), raw);
  return out ? cap(out) + unit : null;
}

/** A param label as the panel shows it: Russian when the glossary knows it, else the program's own text. */
export function paramLabel(label: string, lang: Lang): string {
  return lang === 'ru' ? (ruLabel(label) ?? label) : label;
}

/** A param group heading (Shell, Fit, Access…). */
export function paramGroup(group: string, lang: Lang): string {
  if (lang !== 'ru' || !group) return group;
  return GROUPS[key(group)] ?? ruLabel(group) ?? group;
}

/** A choice on a param's chips or menu; the value sent to the program stays English. */
export function paramOption(option: string, lang: Lang): string {
  return lang === 'ru' ? (OPTIONS[key(option)] ?? option) : option;
}
