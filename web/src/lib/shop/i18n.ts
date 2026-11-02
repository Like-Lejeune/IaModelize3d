// Strings of Formwright Parts in English and Russian. The language is the app's (i18n.lang, read only here);
// prices are in tenge with US dollars in brackets, since the farm (Axo) is in Kazakhstan. The server sends the order's
// journal, its pauses and its QC errors as codes (shop/notes.py); noteText, problemText and qcError say them here.
import { i18n } from '$lib/i18n.svelte';
import { modelName } from '$lib/models';
import type { Order, QcReport, SkippedFile, TimelineEntry } from './types';

type Dict = Record<string, string>;

const en: Dict = {
  'nav.parts': 'Parts',
  'nav.orders': 'Orders',
  'nav.ops': 'Ops',
  'nav.menu': 'Formwright Parts',
  'getit.quote': 'Get a quote',

  'status.requested': 'Request received',
  'status.designing': 'Designing',
  'status.needs_info': 'Question for you',
  'status.quoted': 'Price ready',
  'status.paid': 'Paid',
  'status.printing': 'Printing',
  'status.qc': 'Quality check',
  'status.shipped': 'Shipped',
  'status.delivered': 'Received',
  'status.refused': 'Refused',
  'status.cancelled': 'Cancelled',
  'status.expired': 'Price expired',
  'actor.customer': 'Customer',
  'actor.operator': 'Axo farm',
  'actor.system': 'Formwright',

  'parts.title': 'Formwright Parts',
  'parts.lead': 'The spare part nobody stocks: measured from a photo, checked before you pay, printed by the Axo farm in Kazakhstan and checked again before it ships.',
  'parts.search_ph': 'Part, brand, model or part number, e.g. dishwasher wheel',
  'parts.search': 'Search the catalog',
  'parts.new_cta': 'Not in the catalog? Photograph it on A4',
  'parts.catalog': 'Catalog',
  'parts.catalog_hint': 'Parts that were already designed and checked: no design step, the price in seconds.',
  'parts.empty': 'Nothing found. A photo of the part on an A4 sheet is enough to make it.',
  'parts.catalog_empty': 'The catalog fills up as parts pass their quality check.',
  'parts.compatible': 'Compatible with {x}',
  'parts.order': 'Order',
  'parts.order_again': 'Order again',
  'parts.ordering': 'Ordering…',
  'parts.about': 'about {x}',
  'parts.no_design': 'No design step: the model is checked already',
  'parts.mine': 'Your parts and orders',
  'parts.my_parts': 'Your parts',
  'parts.my_parts_hint': 'Every part you received stays here for a one-tap reorder.',
  'parts.my_orders': 'Orders',
  'parts.no_orders': 'No orders yet.',
  'parts.share': 'Share in the catalog',
  'parts.shared': 'In the catalog',
  'parts.private': 'Only you',
  'parts.report': 'Report',
  'parts.report_ph': 'What is wrong: a trademark, a design right, a safety worry',
  'parts.report_send': 'Send report',
  'parts.reported': 'Thanks: the part is hidden until the farm looks at it.',
  'parts.reported_queued': 'Thanks: the farm will look at the part.',
  'parts.seeded': 'Build checks only, no printed QC yet',
  'parts.ip_note': 'Compatible parts: the functional shape only, never a logo or a trademark.',
  'parts.flagged': 'Hidden after a report',
  'parts.showcase': 'See a delivered order',
  'parts.showcase_hint': 'One real order through the Axo farm: its journal, the price, the QC photo against the model.',
  'badge.printable': 'Printable',
  'badge.critic': 'Critic',
  'badge.qc': 'QC {n} mm',

  'new.title': 'New part',
  'new.lead': 'Put the part on a sheet of A4 paper and take the photo from above. Formwright measures it in millimetres, designs the replacement and checks it before you pay.',
  'new.part_photo': 'Part on A4',
  'new.part_hint': 'The whole sheet in the frame, the camera straight above',
  'new.plate_photo': 'Rating plate',
  'new.plate_hint': 'The sticker with the model number (optional)',
  'new.add_photo': 'Add photo',
  'new.voice': 'Voice note',
  'new.voice_hint': 'Say what it is, what it fits and how many',
  'new.record': 'Record',
  'new.stop': 'Stop',
  'new.remove': 'Remove',
  'new.text': 'What do you need?',
  'new.text_ph': 'e.g. "Bosch dishwasher, the lower basket wheel, 4 pieces"',
  'new.appliance': 'Appliance or model',
  'new.part_number': 'Part number',
  'new.quantity': 'Quantity',
  'new.qty_auto': 'from the request',
  'new.material': 'Material',
  'new.material_auto': 'Choose for me',
  'new.delivery': 'Delivery',
  'new.contact': 'Phone or e-mail',
  'new.contact_hint': 'For the delivery only; deleted once you have the part',
  'new.submit': 'Send request',
  'new.sending': 'Uploading…',
  'new.sending_voice': 'Uploading and transcribing the voice note…',
  'new.need_something': 'Add a photo, a voice note or a few words',
  'new.from_project': 'Order a model from the studio',
  'new.project_hint': 'The model is ready, so there is no design step: OrcaSlicer prices it in about 15 seconds.',
  'new.comment': 'Comment',
  'new.safety': 'We do not print parts whose failure can hurt someone: gas, mains voltage, brakes, child seats.',
  'new.step1': 'Photo on A4',
  'new.step2': 'Model and checks',
  'new.step3': 'Price from the slicer',
  'new.step4': 'Print and QC',
  'new.mic_denied': 'The microphone is blocked for this site.',
  'new.mic_unavailable': 'No microphone to record with.',
  'delivery.pickup': 'Pickup',
  'delivery.courier': 'Courier · Almaty, Astana',
  'delivery.post': 'Kazpost',
  'carrier.courier': 'Courier',
  'days': '{n} d',
  'today': 'today',
  'tomorrow': 'tomorrow',

  'intake.reading': 'Reading the request…',
  'intake.read': 'Read',
  'intake.request': 'Request',
  'intake.pcs': '{n} pcs',
  'intake.no_logo': 'not reproduced: {x}',
  'intake.refused': 'We cannot print this part',
  'intake.refused_hint': 'A printed copy that cracks or melts here could hurt someone. Nothing was charged.',
  'intake.held': 'Waiting for the farm operator',
  'intake.held_failed': 'The request could not be read automatically, so a person looks at it.',
  'intake.approved': 'Checked by the farm operator',
  'intake.second': 'Second opinion',
  'intake.voice': 'Voice note',
  'intake.questions': 'The designer will check',
  'intake.question': 'The designer asks',
  'intake.answer_ph': 'Your answer',
  'intake.send': 'Send',
  'intake.wet': 'wet',
  'intake.temp': 'up to {t} °C',
  'intake.food': 'food contact',
  'intake.skipped': 'Not used: {x}',
  'intake.safety_ok': 'Safety check passed',
  'cond.broken': 'broken',
  'cond.missing': 'missing',
  'cond.worn': 'worn',
  'cond.other': '',

  'quote.title': 'Price',
  'quote.estimate': 'Estimate',
  'quote.estimate_hint': 'From the model\'s own estimate. The binding price comes from OrcaSlicer.',
  'quote.slicing': 'OrcaSlicer is slicing the model…',
  'quote.waiting_model': 'The price comes once the model is ready.',
  'quote.by_orca': 'OrcaSlicer · {s} s',
  'quote.by_operator': 'Quoted by the farm',
  'quote.per_piece': 'per piece',
  'quote.unit': 'Part × {n}',
  'quote.new_part': 'New part: measuring, checks, critic',
  'quote.delivery': 'Delivery',
  'quote.total': 'Total',
  'quote.ready': 'Ready {d}',
  'quote.arrive': 'At your door {d}',
  'quote.pickup_from': 'Pickup from {d}',
  'quote.valid': 'Valid until {d}',
  'quote.supports': 'with supports',
  'quote.no_supports': 'no supports',
  'quote.pay': 'Pay — test mode',
  'quote.pay_hint': 'Test mode: no card is asked for and no money moves.',
  'quote.paid': 'Paid {a} · test mode',
  'quote.change': 'Change',
  'quote.apply': 'Recalculate',
  'quote.recalc': 'OrcaSlicer is recalculating…',
  'quote.cancel': 'Cancel order',
  'quote.farm': 'Farm cost {c} · margin {m}%',
  'quote.rate': '1 $ = {r} ₸',
  'quote.workshop': 'Workshop tariff',
  'quote.safety_pending': 'Safety check in progress…',
  'quote.safety_held': 'The farm operator looks at this request first',
  'quote.safety_hint': 'Muse Spark 1.3 reads the request while OrcaSlicer prices it; Pay opens once the check clears.',
  'quote.updating': 'Pricing it in {m}, the material picked for this part…',
  'quote.expired': 'This price has expired.',
  'quote.fresh': 'Get a fresh quote',
  'quote.material_due': 'The price in {m}, the material picked for this part, is not ready yet: the slicer tries again shortly.',
  'quote.cancel_ask': 'Cancel this order?',
  'quote.cancel_yes': 'Yes, cancel',
  'quote.cancel_no': 'Keep it',

  'tl.title': 'Order history',

  // the order journal (server shop/notes.py codes)
  'note.ordered_studio': 'Ordered from the studio',
  'note.ordered_telegram': 'Ordered from the Telegram chat',
  'note.ordered_catalog': 'Ordered from the catalog: {title}',
  'note.intake_read': 'Read by {model}: {title}',
  'note.intake_unread': 'The request could not be read automatically',
  'note.held_failed': 'Waiting for the farm operator: the safety check could not run',
  'note.held_safety': 'Waiting for the farm operator: the second model calls this part safety-critical',
  'note.approved': 'Let through by the farm operator',
  'note.refused_safety': 'Refused by the safety check',
  'note.refused_operator': 'Refused by the farm operator',
  'note.designing': 'The agent is measuring and designing',
  'note.asked': 'The agent asked a question',
  'note.answered': 'Answered; the agent goes on',
  'note.design_done': 'The design finished',
  'note.quoted': '{g}, {m} per piece × {n}: {total}, {by}',
  'note.requoted': 'Quoted again: {g}, {m} per piece × {n}: {total}, {by}',
  'note.by_orca': 'by OrcaSlicer',
  'note.by_operator': 'by the farm',
  'note.problem': 'Paused: {why}',
  'note.paid_test': 'Test payment',
  'note.expired': 'A fresh quote brings the order back',
  'note.assigned': 'On {printer}',
  'note.resliced': 'sliced again for it: {g} (quoted {q}), the paid price holds',
  'note.printed': 'Off the plate, waiting for the QC photo',
  'note.qc_unmeasured': 'The QC photo could not be measured: {why}',
  'note.qc_pass': 'QC passed: max {max} mm within ±{tol} mm',
  'note.qc_fail': 'QC failed: max {max} mm over ±{tol} mm',
  'note.reprint_qc': 'Back in the queue for a reprint',
  'note.reprint': 'Reprint',
  'problem.slice_failed': 'the slicer could not price it; the farm looks at it',
  'problem.no_model': 'the design ended without a model; the farm or you take it from here',
  'problem.design_unfinished': 'the design stopped before its model passed the checks; the farm looks at it first',
  'problem.bad_material': 'that material is not printed here',
  'problem.guard': 'the order is past quoting',
  'problem.daily_limit': 'today\'s limit is used up; it goes on tomorrow',
  'problem.demo_budget': 'the demo budget for today is used up',
  'problem.ip_daily_cap': 'today\'s limit for this network is used up',
  'problem.job_running': 'another job of this account is still running',
  'problem.project_busy': 'the model is busy with another job',
  'problem.quota': 'a usage limit was reached',
  'problem.other': 'stopped ({code})',
  'qc_err.not_found': 'the part was not found in the photo',
  'qc_err.model_unavailable': 'the measuring model is unavailable; another photo follows',
  'qc_err.no_sheet': 'no A4 sheet or card in the photo, so it cannot be measured in mm',
  'qc_err.version_gone': 'this version of the model is gone',
  'qc_err.other': 'the photo could not be measured',
  'skip.unreadable': '{file}: the file could not be read',
  'skip.voice_untranscribed': 'the voice note could not be transcribed',
  'skip.not_photo': '{file}: a {kind} is not read here, send photos',
  'intake.held_safety': 'The second model calls this part safety-critical, so a person decides.',
  // the open model's part categories (shop/intake_schema.py CATEGORIES)
  'cat.appliance': 'appliance',
  'cat.furniture': 'furniture',
  'cat.automotive': 'automotive',
  'cat.electronics': 'electronics',
  'cat.plumbing': 'plumbing',
  'cat.toy': 'toy',
  'cat.tool': 'tool',
  'cat.garden': 'garden',
  'cat.other': 'other',

  'order.title': 'Order {ref}',
  'order.how': 'How the agent designed it',
  'order.tracking': 'Tracking',
  'order.received': 'I got it',
  'order.received_hint': 'Once it fits, tap here: the part stays under "Your parts" for a one-tap reorder.',
  'order.not_found': 'No such order, or it belongs to someone else.',
  'order.working': 'Formwright is on it…',
  'order.paused': 'Paused',
  'order.back': 'Parts and orders',
  'order.pickup_ready': 'Ready for pickup',
  'order.designing_hint': 'The agent measures the photo and designs the part; a slicer and an independent critic check it.',
  'order.printing_hint': 'Printing on the farm\'s calibrated printer.',
  'order.qc_hint': 'The print is photographed on A4 and its outline compared with the model.',
  'order.delivered_hint': 'Received. It is under "Your parts" now.',
  'order.share_hint': 'It passed QC: share it, and the next person with the same appliance gets it in one tap.',
  'order.studio': 'Open in the studio',
  'order.showcase': 'A delivered order of the Axo farm, shown without the customer\'s details.',
  'order.showcase_on': 'Show to everyone',
  'order.showcase_off': 'Stop showing',
  'order.showcase_shown': 'Shown to everyone',
  'order.qc_passed': 'QC passed',
  'order.order_same': 'Order the same part',
  'order.watch_design': 'Watch how it was designed',
  'order.no_model_next': 'The design stopped without a model. Open the project and press "Continue" to let the agent carry on, or wait: the farm operator sees it too.',
  'order.printed_on': 'Printed on {p}',

  'qc.title': 'Quality check',
  'qc.pass': 'PASS',
  'qc.fail': 'FAIL',
  'qc.max': 'max {n} mm',
  'qc.mean': 'mean {n} mm',
  'qc.caption': 'Outline in plan within ±{t} mm',
  'qc.model': 'Model',
  'qc.print': 'Print',
  'qc.grid': '10 mm grid',
  'qc.honest': 'Seen from above: heights, snaps and threads are checked by the fit, not by this photo.',
  'qc.error': 'The photo could not be measured: {x}',
  'qc.worst': '{n} mm',
  'qc.photo': 'QC photo',

  'ops.title': 'Axo farm',
  'ops.lead': 'Formwright designs and checks each part; the Axo farm prints, checks it again and ships it.',
  'ops.col.upstream': 'Upstream',
  'ops.col.paid': 'Paid',
  'ops.col.printing': 'Printing',
  'ops.col.qc': 'QC',
  'ops.col.ship': 'Ready to ship',
  'ops.empty': 'Nothing here',
  'ops.queue': '{h} h of printing queued',
  'ops.printers': 'Printers',
  'ops.no_printers': 'No printers yet: run scripts/shop_seed.py --apply.',
  'printer.idle': 'idle',
  'printer.printing': 'printing',
  'printer.maintenance': 'maintenance',
  'ops.calibrate': 'Calibrate',
  'ops.coupon': 'Coupon 3MF',
  'ops.calibrated': 'calibrated',
  'ops.uncalibrated': 'not calibrated',
  'ops.to_maintenance': 'Maintenance',
  'ops.to_idle': 'Back to work',
  'ops.not_operator': 'This board is for the operators of the Axo farm.',
  'ops.assign': 'Assign',
  'ops.printed': 'Off the plate',
  'ops.qc_photo': 'QC photo on A4',
  'ops.qc_again': 'Another QC photo',
  'ops.ship': 'Ship',
  'ops.reprint': 'Reprint',
  'ops.carrier': 'Carrier',
  'ops.tracking': 'Tracking number',
  'ops.gcode': 'G-code',
  'ops.3mf': '3MF',
  'ops.approve': 'Let through',
  'ops.refuse': 'Refuse',
  'ops.refuse_ph': 'Reason for the customer',
  'ops.requote': 'Quote again',
  'ops.measuring': 'SAM 3.1 is measuring the print…',
  'ops.pickup': 'Pickup: no tracking needed',
  'ops.attempt': 'print {n}',
  'ops.cancel': 'Cancel',
  'ops.delivered': 'Mark as delivered',
  'ops.refresh': 'Refresh',
  'ops.held': 'Held for review',
  'ops.unread': 'Nobody could read this request: set what the customer asked for',
  'ops.col.done': 'Shipped',
  'ops.done_hint': 'Shipped and delivered orders. One of them can be shown to everyone as an example, without the customer\'s data.',

  'err.bad_move': 'Not possible at this step',
  'err.guard': 'Not yet',
  'err.conflict': 'Someone changed this order a moment ago; it is refreshed now.',
  'err.forbidden': 'This order belongs to someone else.',
  'err.not_found': 'Not found.',
  'err.not_operator': 'Only the farm\'s operators can do this.',
  'err.not_verified': 'A part goes into the catalog once a print of it passed QC.',
  'err.no_model': 'There is no model to price yet.',
  'err.no_estimate': 'No weight estimate for this model yet.',
  'err.bad_material': 'We print PLA, PETG, ASA and TPU.',
  'err.slice_failed': 'The slicer could not price it',
  'err.quote_expired': 'The price expired: recalculate it first.',
  'err.no_question': 'No question is waiting.',
  'err.empty_request': 'Send a photo of the part, a voice note or a few words about it.',
  'err.printer_busy': 'That printer is in maintenance.',
  'err.org_exists': 'You are in a workshop account already.',
  'err.fingerprint_failed': 'The coupon could not be measured',
  'err.bad_preset': 'OrcaSlicer has no such printer preset.',
  'err.too_many_reports': 'That is a lot of reports for one day; the farm is looking at the ones you sent.',
  'err.safety_pending': 'The safety check is still running; Pay opens once it clears.',
  'err.price_updating': 'The price is being updated; Pay opens once it is ready.',
  'err.held': 'The farm operator looks at this request first.',
  'err.not_delivered': 'Only a shipped or delivered order can be shown.',
  'err.material_pending': 'The price in the material picked for this part is not ready yet; Pay opens once it is.',
  'err.too_many_orders': 'Too many open orders for now: pay or cancel one of yours, or try again tomorrow.',
  'err.too_many_pieces': 'An order without an account takes up to 20 pieces.',
};

const ru: Dict = {
  'nav.parts': 'Детали',
  'nav.orders': 'Заказы',
  'nav.ops': 'Ферма',
  'nav.menu': 'Formwright Parts',
  'getit.quote': 'Получить котировку',

  'status.requested': 'Заявка принята',
  'status.designing': 'Проектируем',
  'status.needs_info': 'Нужен ответ',
  'status.quoted': 'Цена готова',
  'status.paid': 'Оплачен',
  'status.printing': 'Печатается',
  'status.qc': 'Проверка',
  'status.shipped': 'Отправлен',
  'status.delivered': 'Получен',
  'status.refused': 'Отказ',
  'status.cancelled': 'Отменён',
  'status.expired': 'Цена истекла',
  'actor.customer': 'Клиент',
  'actor.operator': 'ферма Axo',
  'actor.system': 'Formwright',

  'parts.title': 'Formwright Parts',
  'parts.lead': 'Запчасть, которой нет на складе: обмер по фото, проверка до оплаты, печать на ферме Axo в Казахстане и ещё одна проверка перед отправкой.',
  'parts.search_ph': 'Деталь, бренд, модель или номер, например колесо посудомойки',
  'parts.search': 'Поиск по каталогу',
  'parts.new_cta': 'Нет в каталоге? Сфотографируйте на листе A4',
  'parts.catalog': 'Каталог',
  'parts.catalog_hint': 'Детали, которые уже спроектированы и проверены: без проектирования, цена за секунды.',
  'parts.empty': 'Ничего не нашлось. Чтобы сделать деталь, хватит её фото на листе A4.',
  'parts.catalog_empty': 'Каталог пополняется, когда детали проходят контроль качества.',
  'parts.compatible': 'Совместимо с {x}',
  'parts.order': 'Заказать',
  'parts.order_again': 'Заказать ещё',
  'parts.ordering': 'Заказываем…',
  'parts.about': 'около {x}',
  'parts.no_design': 'Без проектирования: модель уже проверена',
  'parts.mine': 'Ваши детали и заказы',
  'parts.my_parts': 'Ваши детали',
  'parts.my_parts_hint': 'Каждая полученная деталь остаётся здесь: повторный заказ в одно касание.',
  'parts.my_orders': 'Заказы',
  'parts.no_orders': 'Заказов пока нет.',
  'parts.share': 'В общий каталог',
  'parts.shared': 'В каталоге',
  'parts.private': 'Только вам',
  'parts.report': 'Пожаловаться',
  'parts.report_ph': 'Что не так: товарный знак, права на дизайн, опасность',
  'parts.report_send': 'Отправить жалобу',
  'parts.reported': 'Спасибо: деталь скрыта, пока её не проверит ферма.',
  'parts.reported_queued': 'Спасибо: ферма проверит деталь.',
  'parts.seeded': 'Только проверки сборки, печатного QC ещё нет',
  'parts.ip_note': 'Совместимые детали: только функциональная форма, без логотипов и товарных знаков.',
  'parts.flagged': 'Скрыта после жалобы',
  'parts.showcase': 'Посмотреть выполненный заказ',
  'parts.showcase_hint': 'Реальный заказ через ферму Axo: журнал, цена, QC-фото рядом с моделью.',
  'badge.printable': 'Печатается',
  'badge.critic': 'Критик',
  'badge.qc': 'QC {n} мм',

  'new.title': 'Новая деталь',
  'new.lead': 'Положите деталь на лист бумаги A4 и сфотографируйте сверху. Formwright измерит её в миллиметрах, спроектирует замену и проверит до оплаты.',
  'new.part_photo': 'Деталь на листе A4',
  'new.part_hint': 'Весь лист в кадре, камера прямо сверху',
  'new.plate_photo': 'Табличка прибора',
  'new.plate_hint': 'Наклейка с моделью (необязательно)',
  'new.add_photo': 'Добавить фото',
  'new.voice': 'Голосом',
  'new.voice_hint': 'Скажите, что это, от какого прибора и сколько штук',
  'new.record': 'Записать',
  'new.stop': 'Стоп',
  'new.remove': 'Убрать',
  'new.text': 'Что нужно?',
  'new.text_ph': 'например «посудомойка Bosch, колёсико нижней корзины, 4 шт»',
  'new.appliance': 'Прибор или модель',
  'new.part_number': 'Номер детали',
  'new.quantity': 'Количество',
  'new.qty_auto': 'из заявки',
  'new.material': 'Материал',
  'new.material_auto': 'Подобрать',
  'new.delivery': 'Доставка',
  'new.contact': 'Телефон или e-mail',
  'new.contact_hint': 'Только для доставки; удаляем, когда деталь у вас',
  'new.submit': 'Отправить заявку',
  'new.sending': 'Загружаем…',
  'new.sending_voice': 'Загружаем и расшифровываем голос…',
  'new.need_something': 'Добавьте фото, голос или пару слов',
  'new.from_project': 'Заказ модели из студии',
  'new.project_hint': 'Модель готова, проектировать не нужно: OrcaSlicer посчитает цену примерно за 15 секунд.',
  'new.comment': 'Комментарий',
  'new.safety': 'Не печатаем детали, поломка которых опасна: газ, сеть 230 В, тормоза, детские кресла.',
  'new.step1': 'Фото на A4',
  'new.step2': 'Модель и проверки',
  'new.step3': 'Цена из слайсера',
  'new.step4': 'Печать и QC',
  'new.mic_denied': 'Микрофон для этого сайта запрещён.',
  'new.mic_unavailable': 'Нет микрофона для записи.',
  'delivery.pickup': 'Самовывоз',
  'delivery.courier': 'Курьер · Алматы, Астана',
  'delivery.post': 'Казпочта',
  'carrier.courier': 'Курьер',
  'days': '{n} дн.',
  'today': 'сегодня',
  'tomorrow': 'завтра',

  'intake.reading': 'Читаем заявку…',
  'intake.read': 'Прочитано',
  'intake.request': 'Заявка',
  'intake.pcs': '{n} шт',
  'intake.no_logo': 'не воспроизводим: {x}',
  'intake.refused': 'Эту деталь мы не печатаем',
  'intake.refused_hint': 'Если печатная копия треснет или расплавится, кто-то может пострадать. Деньги не списаны.',
  'intake.held': 'Ждёт оператора фермы',
  'intake.held_failed': 'Заявку не удалось прочитать автоматически, её посмотрит человек.',
  'intake.approved': 'Проверено оператором фермы',
  'intake.second': 'Второе мнение',
  'intake.voice': 'Голосовая заметка',
  'intake.questions': 'Конструктор уточнит',
  'intake.question': 'Вопрос конструктора',
  'intake.answer_ph': 'Ваш ответ',
  'intake.send': 'Отправить',
  'intake.wet': 'влажно',
  'intake.temp': 'до {t} °C',
  'intake.food': 'контакт с едой',
  'intake.skipped': 'Не использовано: {x}',
  'intake.safety_ok': 'Проверка безопасности пройдена',
  'cond.broken': 'сломана',
  'cond.missing': 'потеряна',
  'cond.worn': 'изношена',
  'cond.other': '',

  'quote.title': 'Цена',
  'quote.estimate': 'Оценка',
  'quote.estimate_hint': 'По оценке самой модели. Окончательную цену считает OrcaSlicer.',
  'quote.slicing': 'OrcaSlicer нарезает модель…',
  'quote.waiting_model': 'Цена появится, когда модель будет готова.',
  'quote.by_orca': 'OrcaSlicer · {s} с',
  'quote.by_operator': 'Цена от фермы',
  'quote.per_piece': 'на штуку',
  'quote.unit': 'Деталь × {n}',
  'quote.new_part': 'Новая деталь: обмер, проверки, критик',
  'quote.delivery': 'Доставка',
  'quote.total': 'Итого',
  'quote.ready': 'Готово {d}',
  'quote.arrive': 'Привезём {d}',
  'quote.pickup_from': 'Забрать можно {d}',
  'quote.valid': 'Цена действует до {d}',
  'quote.supports': 'с поддержками',
  'quote.no_supports': 'без поддержек',
  'quote.pay': 'Оплатить — тестовый режим',
  'quote.pay_hint': 'Тестовый режим: карта не нужна, деньги не списываются.',
  'quote.paid': 'Оплачено {a} · тестовый режим',
  'quote.change': 'Изменить',
  'quote.apply': 'Пересчитать',
  'quote.recalc': 'OrcaSlicer пересчитывает…',
  'quote.cancel': 'Отменить заказ',
  'quote.farm': 'Себестоимость {c} · маржа {m}%',
  'quote.rate': '1 $ = {r} ₸',
  'quote.workshop': 'Тариф мастерской',
  'quote.safety_pending': 'Идёт проверка безопасности…',
  'quote.safety_held': 'Сначала заявку посмотрит оператор фермы',
  'quote.safety_hint': 'Muse Spark 1.3 читает заявку, пока OrcaSlicer считает цену; оплата откроется после проверки.',
  'quote.updating': 'Пересчитываем цену в {m} — материале, подобранном для этой детали…',
  'quote.expired': 'Срок действия цены истёк.',
  'quote.fresh': 'Пересчитать цену',
  'quote.material_due': 'Цена в {m} — материале, подобранном для этой детали, — ещё не готова: слайсер скоро попробует снова.',
  'quote.cancel_ask': 'Отменить этот заказ?',
  'quote.cancel_yes': 'Да, отменить',
  'quote.cancel_no': 'Оставить',

  'tl.title': 'История заказа',

  'note.ordered_studio': 'Заказ из студии',
  'note.ordered_telegram': 'Заказ из чата Telegram',
  'note.ordered_catalog': 'Заказ из каталога: {title}',
  'note.intake_read': 'Прочитано · {model}: {title}',
  'note.intake_unread': 'Заявку не удалось прочитать автоматически',
  'note.held_failed': 'Ждёт оператора фермы: проверка безопасности не запустилась',
  'note.held_safety': 'Ждёт оператора фермы: вторая модель считает деталь критичной для безопасности',
  'note.approved': 'Оператор фермы пропустил заявку',
  'note.refused_safety': 'Отказ по проверке безопасности',
  'note.refused_operator': 'Оператор фермы отказал',
  'note.designing': 'Агент измеряет и проектирует',
  'note.asked': 'Агент задал вопрос',
  'note.answered': 'Ответ получен, агент продолжает',
  'note.design_done': 'Проектирование закончено',
  'note.quoted': '{g}, {m} на штуку × {n}: {total}, {by}',
  'note.requoted': 'Пересчитано: {g}, {m} на штуку × {n}: {total}, {by}',
  'note.by_orca': 'по OrcaSlicer',
  'note.by_operator': 'цена от фермы',
  'note.problem': 'Пауза: {why}',
  'note.paid_test': 'Тестовая оплата',
  'note.expired': 'Новый расчёт цены вернёт заказ',
  'note.assigned': 'На принтере {printer}',
  'note.resliced': 'нарезано заново: {g} (в цене {q}), оплаченная цена не меняется',
  'note.printed': 'Снято со стола, ждёт QC-фото',
  'note.qc_unmeasured': 'QC-фото не удалось измерить: {why}',
  'note.qc_pass': 'QC пройден: макс. {max} мм в пределах ±{tol} мм',
  'note.qc_fail': 'QC не пройден: макс. {max} мм больше ±{tol} мм',
  'note.reprint_qc': 'Снова в очереди на перепечатку',
  'note.reprint': 'Перепечатка',
  'problem.slice_failed': 'слайсер не смог посчитать цену; ферма разбирается',
  'problem.no_model': 'проектирование закончилось без модели; дальше — ферма или вы',
  'problem.design_unfinished': 'проектирование остановилось раньше, чем модель прошла проверки; сначала её посмотрит ферма',
  'problem.bad_material': 'такой материал мы не печатаем',
  'problem.guard': 'цена по заказу уже посчитана',
  'problem.daily_limit': 'дневной лимит исчерпан; продолжим завтра',
  'problem.demo_budget': 'демо-бюджет на сегодня исчерпан',
  'problem.ip_daily_cap': 'лимит для этой сети на сегодня исчерпан',
  'problem.job_running': 'ещё идёт другая задача этого аккаунта',
  'problem.project_busy': 'модель занята другой задачей',
  'problem.quota': 'достигнут лимит использования',
  'problem.other': 'остановлен ({code})',
  'qc_err.not_found': 'деталь на фото не найдена',
  'qc_err.model_unavailable': 'модель измерения недоступна; будет ещё одно фото',
  'qc_err.no_sheet': 'на фото нет листа A4 или карты, поэтому в миллиметрах не измерить',
  'qc_err.version_gone': 'этой версии модели больше нет',
  'qc_err.other': 'фото не удалось измерить',
  'skip.unreadable': '{file}: файл не удалось прочитать',
  'skip.voice_untranscribed': 'голосовую заметку не удалось расшифровать',
  'skip.not_photo': '{file}: такой файл ({kind}) здесь не читаем, пришлите фото',
  'intake.held_safety': 'Вторая модель считает деталь критичной для безопасности, поэтому решает человек.',
  'cat.appliance': 'бытовая техника',
  'cat.furniture': 'мебель',
  'cat.automotive': 'авто',
  'cat.electronics': 'электроника',
  'cat.plumbing': 'сантехника',
  'cat.toy': 'игрушки',
  'cat.tool': 'инструмент',
  'cat.garden': 'сад',
  'cat.other': 'другое',

  'order.title': 'Заказ {ref}',
  'order.how': 'Как агент проектировал',
  'order.tracking': 'Трек-номер',
  'order.received': 'Получил',
  'order.received_hint': 'Когда деталь встанет на место, нажмите: она останется в «Ваших деталях» для повторного заказа в одно касание.',
  'order.not_found': 'Такого заказа нет, или он чужой.',
  'order.working': 'Formwright работает…',
  'order.paused': 'Пауза',
  'order.back': 'Детали и заказы',
  'order.pickup_ready': 'Можно забирать',
  'order.designing_hint': 'Агент измеряет фото и проектирует деталь; слайсер и независимый критик её проверяют.',
  'order.printing_hint': 'Печатаем на откалиброванном принтере фермы.',
  'order.qc_hint': 'Отпечаток фотографируют на листе A4 и сравнивают его контур с моделью.',
  'order.delivered_hint': 'Получено. Деталь теперь в «Ваших деталях».',
  'order.share_hint': 'Деталь прошла QC: поделитесь ей, и следующий владелец такого же прибора закажет её в одно касание.',
  'order.studio': 'Открыть в студии',
  'order.showcase': 'Выполненный заказ фермы Axo, показан без данных клиента.',
  'order.showcase_on': 'Показывать всем',
  'order.showcase_off': 'Не показывать',
  'order.showcase_shown': 'Виден всем',
  'order.qc_passed': 'QC пройден',
  'order.order_same': 'Заказать такую же',
  'order.watch_design': 'Посмотреть, как её проектировали',
  'order.no_model_next': 'Проектирование остановилось без модели. Откройте проект и нажмите «Продолжить», чтобы агент продолжил, — или подождите: оператор фермы тоже это видит.',
  'order.printed_on': 'Напечатано на {p}',

  'qc.title': 'Контроль качества',
  'qc.pass': 'PASS',
  'qc.fail': 'FAIL',
  'qc.max': 'макс. {n} мм',
  'qc.mean': 'в среднем {n} мм',
  'qc.caption': 'Контур в плане ±{t} мм',
  'qc.model': 'Модель',
  'qc.print': 'Отпечаток',
  'qc.grid': 'сетка 10 мм',
  'qc.honest': 'Вид сверху: высоты, защёлки и резьбу проверяет примерка, а не это фото.',
  'qc.error': 'Фото не удалось измерить: {x}',
  'qc.worst': '{n} мм',
  'qc.photo': 'QC-фото',

  'ops.title': 'Ферма Axo',
  'ops.lead': 'Formwright проектирует и проверяет деталь; ферма Axo печатает, проверяет ещё раз и отправляет.',
  'ops.col.upstream': 'В работе',
  'ops.col.paid': 'Оплачено',
  'ops.col.printing': 'Печать',
  'ops.col.qc': 'Проверка',
  'ops.col.ship': 'К отправке',
  'ops.empty': 'Пусто',
  'ops.queue': 'В очереди {h} ч печати',
  'ops.printers': 'Принтеры',
  'ops.no_printers': 'Принтеров нет: запустите scripts/shop_seed.py --apply.',
  'printer.idle': 'свободен',
  'printer.printing': 'печатает',
  'printer.maintenance': 'обслуживание',
  'ops.calibrate': 'Калибровка',
  'ops.coupon': 'Купон 3MF',
  'ops.calibrated': 'откалиброван',
  'ops.uncalibrated': 'не откалиброван',
  'ops.to_maintenance': 'На обслуживание',
  'ops.to_idle': 'В работу',
  'ops.not_operator': 'Эта доска для операторов фермы Axo.',
  'ops.assign': 'Назначить',
  'ops.printed': 'Снято со стола',
  'ops.qc_photo': 'QC-фото на A4',
  'ops.qc_again': 'Ещё одно QC-фото',
  'ops.ship': 'Отгрузить',
  'ops.reprint': 'Перепечатать',
  'ops.carrier': 'Перевозчик',
  'ops.tracking': 'Трек-номер',
  'ops.gcode': 'G-code',
  'ops.3mf': '3MF',
  'ops.approve': 'Пропустить',
  'ops.refuse': 'Отказать',
  'ops.refuse_ph': 'Причина для клиента',
  'ops.requote': 'Пересчитать цену',
  'ops.measuring': 'SAM 3.1 измеряет отпечаток…',
  'ops.pickup': 'Самовывоз: трек-номер не нужен',
  'ops.attempt': 'печать {n}',
  'ops.cancel': 'Отменить',
  'ops.delivered': 'Отметить вручение',
  'ops.refresh': 'Обновить',
  'ops.held': 'Ждёт решения',
  'ops.unread': 'Заявку не удалось прочитать: укажите, что просил клиент',
  'ops.col.done': 'Отправлено',
  'ops.done_hint': 'Отправленные и полученные заказы. Один из них можно показать всем как пример, без данных клиента.',

  'err.bad_move': 'На этом шаге так нельзя',
  'err.guard': 'Пока нельзя',
  'err.conflict': 'Заказ только что изменили; он обновлён.',
  'err.forbidden': 'Это чужой заказ.',
  'err.not_found': 'Не найдено.',
  'err.not_operator': 'Это может только оператор фермы.',
  'err.not_verified': 'В каталог деталь попадает, когда её отпечаток прошёл QC.',
  'err.no_model': 'Модели для расчёта цены пока нет.',
  'err.no_estimate': 'У этой модели ещё нет оценки веса.',
  'err.bad_material': 'Печатаем PLA, PETG, ASA и TPU.',
  'err.slice_failed': 'Слайсер не смог посчитать цену',
  'err.quote_expired': 'Цена истекла: сначала пересчитайте.',
  'err.no_question': 'Вопросов нет.',
  'err.empty_request': 'Пришлите фото детали, голосовую заметку или пару слов о ней.',
  'err.printer_busy': 'Этот принтер на обслуживании.',
  'err.org_exists': 'Вы уже в аккаунте мастерской.',
  'err.fingerprint_failed': 'Купон не удалось измерить',
  'err.bad_preset': 'В OrcaSlicer нет такого профиля принтера.',
  'err.too_many_reports': 'Слишком много жалоб за день; ферма уже смотрит те, что вы отправили.',
  'err.safety_pending': 'Проверка безопасности ещё идёт; оплата откроется после неё.',
  'err.price_updating': 'Цена пересчитывается; оплата откроется, как только она будет готова.',
  'err.held': 'Сначала заявку посмотрит оператор фермы.',
  'err.not_delivered': 'Показать можно только отправленный или полученный заказ.',
  'err.material_pending': 'Цена в подобранном для детали материале ещё не готова; оплата откроется, когда она будет готова.',
  'err.too_many_orders': 'Сейчас открыто слишком много заказов: оплатите или отмените один из своих либо попробуйте завтра.',
  'err.too_many_pieces': 'Заказ без аккаунта — до 20 штук.',
};

/** st('quote.ready', { d: 'tomorrow' }) fills {placeholders}; English when a Russian string is missing. */
export function st(key: string, vars?: Record<string, string | number>): string {
  let s = (i18n.lang === 'ru' ? ru[key] : undefined) ?? en[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

const group = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

/** 9490 -> "9 490 ₸" (tenge prices are whole). */
export const kzt = (v: number | null | undefined) => (v == null || !isFinite(v) ? '—' : `${group.format(Math.round(v))} ₸`);
export const usd = (v: number | null | undefined) => (v == null || !isFinite(v) ? '—' : `$${v.toFixed(2)}`);
/** "9 490 ₸ ($18.25)": tenge is the binding figure, dollars are for readers outside Kazakhstan. */
export const money = (k: number | null | undefined, u: number | null | undefined) => (u == null ? kzt(k) : `${kzt(k)} (${usd(u)})`);
/** "7 990–12 490 ₸ ($15.37–24.02)" */
export function moneyRange(k: [number, number], u?: [number, number] | null): string {
  const t = k[0] === k[1] ? kzt(k[0]) : `${group.format(Math.round(k[0]))}–${kzt(k[1])}`;
  if (!u) return t;
  return `${t} (${u[0] === u[1] ? usd(u[0]) : `${usd(u[0])}–${u[1].toFixed(2)}`})`;
}

/** Millimetres with the precision a caliper would give. */
export const mm = (v: number | null | undefined) => (v == null || !isFinite(v) ? '—' : v < 10 ? v.toFixed(2) : v.toFixed(1));

/** "2026-10-31" -> "tomorrow" / "Sat, 31 Oct". */
export function day(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(`${iso}T12:00:00`);
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000);
  if (diff === 0) return st('today');
  if (diff === 1) return st('tomorrow');
  return d.toLocaleDateString(i18n.lang === 'ru' ? 'ru-RU' : 'en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
}

/** A unix timestamp as "14:05" today, "31 Oct, 14:05" otherwise. */
export function when(ts: number | null | undefined): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const loc = i18n.lang === 'ru' ? 'ru-RU' : 'en-GB';
  const time = d.toLocaleTimeString(loc, { hour: '2-digit', minute: '2-digit' });
  return d.toDateString() === new Date().toDateString() ? time : `${d.toLocaleDateString(loc, { day: 'numeric', month: 'short' })}, ${time}`;
}

/** Print time as "30 min" / "2 h 5 min". */
export function minutes(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—';
  const m = i18n.lang === 'ru' ? 'мин' : 'min';
  if (v < 60) return `${Math.max(1, Math.round(v))} ${m}`;
  return `${Math.floor(v / 60)} ${i18n.lang === 'ru' ? 'ч' : 'h'} ${Math.round(v % 60)} ${m}`;
}

export const grams = (v: number | null | undefined) => (v == null || !isFinite(v) ? '—' : `${v < 10 ? v.toFixed(1) : Math.round(v)} ${i18n.lang === 'ru' ? 'г' : 'g'}`);

const has = (key: string) => key in en;

/** A model's own sentence (the open model's why, the safety check's reason) only when it is in the UI's language. */
export const sameLang = (text: string | null | undefined) => !!text && /[а-яё]/i.test(text) === (i18n.lang === 'ru');

/** The order's title in the UI's language (a new part is named by what the intake read). */
export const orderTitle = (o: Pick<Order, 'title' | 'title_en' | 'title_ru'>) => (i18n.lang === 'ru' ? o.title_ru : o.title_en) || o.title;

/** Why an automatic step stopped; the farm's operators also read the step's own words. */
export function problemText(p: { code?: string; detail?: string } | null | undefined, operator = false): string {
  if (!p?.code) return '';
  const text = has(`problem.${p.code}`) ? st(`problem.${p.code}`) : st('problem.other', { code: p.code });
  // no_model's detail is the same sentence in the server's English: said once
  return operator && p.detail && p.code !== 'no_model' ? `${text} (${p.detail})` : text;
}

/** Why a QC photo could not be measured. */
export function qcError(qc: Pick<QcReport, 'error' | 'error_code'>, operator = false): string {
  const code = qc.error_code;
  if (!code || !has(`qc_err.${code}`)) return operator && qc.error ? qc.error : st('qc_err.other');
  // the measuring step's own words say more than the code when the model was down or found nothing
  return operator && qc.error && (code === 'model_unavailable' || code === 'not_found') ? `${st(`qc_err.${code}`)} (${qc.error})` : st(`qc_err.${code}`);
}

/** A file the request could not use (older orders kept an English line). */
export function skipText(s: SkippedFile | string, operator = false): string {
  if (typeof s === 'string') return s;
  const text = st(`skip.${s.code}`, { file: s.file ?? '', kind: s.kind ?? '' });
  return operator && s.error ? `${text} (${s.error})` : text;
}

/** One journal entry in the UI's language. An entry without a code (an operator's own words) keeps its note. */
export function noteText(e: TimelineEntry, operator = false): string {
  const p = e.params ?? {};
  const own = (base: string, extra?: string | null) => (extra ? `${base}: ${extra}` : base);
  switch (e.code) {
    case null:
    case undefined:
      return e.note;
    case 'created':
      return ''; // the status line says it
    case 'intake_read':
      return st('note.intake_read', { model: p.model ? modelName(p.model) : 'Muse Spark 1.3', title: (i18n.lang === 'ru' ? p.title_ru : p.title_en) || p.title || '' });
    case 'intake_unread':
      return own(st('note.intake_unread'), operator ? p.error : null);
    case 'held':
      return p.review === 'intake_failed' ? st('note.held_failed') : own(st('note.held_safety'), operator || sameLang(p.why) ? p.why : null);
    case 'approved':
      // with what the operator set for a request nobody could read
      return [own(st('note.approved'), p.note), p.quantity ? st('intake.pcs', { n: p.quantity }) : '', p.material ?? ''].filter(Boolean).join(' · ');
    case 'refused_operator':
    case 'reprint':
      return own(st(`note.${e.code}`), p.note);
    case 'refused_safety':
      return own(st('note.refused_safety'), sameLang(p.reason) || operator ? p.reason : null);
    case 'quoted':
    case 'requoted':
      return st(`note.${e.code}`, {
        g: grams(p.grams),
        m: minutes(p.minutes),
        n: p.quantity ?? 1,
        total: money(p.total, p.total_usd),
        by: st(p.by === 'orca' ? 'note.by_orca' : 'note.by_operator'),
      });
    case 'problem':
      return st('note.problem', { why: problemText({ code: p.code, detail: p.detail }, operator) });
    case 'assigned':
      return st('note.assigned', { printer: p.printer ?? '' }) + (p.resliced ? `, ${st('note.resliced', { g: grams(p.grams), q: grams(p.quoted) })}` : '');
    case 'qc_unmeasured':
      return st('note.qc_unmeasured', { why: qcError({ error: p.error, error_code: p.error_code }, operator) });
    case 'qc_pass':
    case 'qc_fail':
      return st(`note.${e.code}`, { max: mm(Number(p.max)), tol: p.tol ?? '' });
    case 'shipped':
      return [carrierText(p.carrier), p.tracking].filter(Boolean).join(' ');
    case 'ordered_catalog':
      return st('note.ordered_catalog', { title: (i18n.lang === 'ru' ? p.title_ru : p.title_en) || p.title || '' });
    default:
      return has(`note.${e.code}`) ? st(`note.${e.code}`) : e.note;
  }
}

/** The board's default carriers in the UI's language (an operator's own carrier name stays as typed). */
export function carrierText(c: string | null | undefined): string {
  const k = (c ?? '').trim().toLowerCase();
  if (k === 'courier' || k === 'курьер') return st('carrier.courier');
  if (k === 'kazpost' || k === 'казпочта') return st('delivery.post');
  return c ?? '';
}

/** The chip colour of an order status (app.css .chip variants). */
export function statusTone(s: string): string {
  if (s === 'delivered' || s === 'shipped') return 'ok';
  if (s === 'refused' || s === 'cancelled' || s === 'expired') return 'err';
  if (s === 'needs_info' || s === 'quoted') return 'warn';
  if (s === 'paid' || s === 'printing' || s === 'qc') return 'info';
  return 'accent';
}
