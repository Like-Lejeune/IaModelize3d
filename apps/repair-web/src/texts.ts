// The texts shared across screens, in French and in English: statuses, delivery and material names, the order's
// journal (the API speaks in codes, server/iamodelize3d/shop/notes.py; each code has its sentence here, an unknown code
// falls back to the API's own English line) and the error messages. Amounts and dates follow the language.
import type { Lang } from "./i18n";
import type { Delivery, Material, Order, Status, TimelineEntry } from "./types";

type Both<T> = Record<Lang, T>;

export const STATUS: Both<Record<Status, string>> = {
  fr: {
    requested: "Demande reçue", designing: "Conception en cours", needs_info: "Une question pour vous", quoted: "Prix prêt",
    paid: "Payée", printing: "En impression", qc: "Contrôle qualité", shipped: "Expédiée", delivered: "Reçue",
    refused: "Refusée", cancelled: "Annulée", expired: "Prix expiré",
  },
  en: {
    requested: "Request received", designing: "Being designed", needs_info: "A question for you", quoted: "Price ready",
    paid: "Paid", printing: "Printing", qc: "Quality check", shipped: "Shipped", delivered: "Received",
    refused: "Refused", cancelled: "Cancelled", expired: "Price expired",
  },
};

// What the customer should know or do at each step, in one sentence.
export const STATUS_HINT: Both<Record<Status, string>> = {
  fr: {
    requested: "Nous lisons votre demande et vérifions que la pièce peut être imprimée sans danger.",
    designing: "L'atelier mesure la pièce sur votre photo et dessine la pièce de remplacement.",
    needs_info: "Répondez à la question ci-dessous pour que la conception continue.",
    quoted: "Vérifiez le prix et payez pour lancer l'impression.",
    paid: "Votre pièce attend son tour à l'atelier.",
    printing: "Votre pièce est sur l'imprimante.",
    qc: "Nous mesurons la pièce imprimée pour vérifier qu'elle est aux bonnes cotes.",
    shipped: "Votre pièce est en route. Confirmez la réception quand vous l'avez.",
    delivered: "Pièce reçue. Vous pourrez la recommander depuis vos commandes.",
    refused: "Cette pièce ne peut pas être imprimée par l'atelier.",
    cancelled: "Cette commande est annulée.",
    expired: "Le prix n'est plus valable. Demandez un nouveau prix.",
  },
  en: {
    requested: "We are reading your request and checking that the part can be printed safely.",
    designing: "The workshop is measuring the part on your photo and drawing the replacement.",
    needs_info: "Answer the question below so the design can go on.",
    quoted: "Check the price and pay to start the print.",
    paid: "Your part is waiting for its turn at the workshop.",
    printing: "Your part is on the printer.",
    qc: "We are measuring the printed part to check its dimensions.",
    shipped: "Your part is on its way. Confirm when you have it.",
    delivered: "Part received. You can order it again from your orders.",
    refused: "The workshop cannot print this part.",
    cancelled: "This order is cancelled.",
    expired: "The price is no longer valid. Ask for a new price.",
  },
};

// The path an order follows when all goes well: the progress strip shows it.
export const PATH: Status[] = ["requested", "designing", "quoted", "paid", "printing", "qc", "shipped", "delivered"];

export const DELIVERY: Both<Record<Delivery, { label: string; hint: string }>> = {
  fr: {
    pickup: { label: "Retrait à l'atelier", hint: "Gratuit, dès que la pièce est prête" },
    courier: { label: "Coursier en ville", hint: "Livraison à moto dans la ville de l'atelier" },
    post: { label: "Expédition", hint: "Colis vers une autre ville, par agence de voyage" },
  },
  en: {
    pickup: { label: "Pickup at the workshop", hint: "Free, as soon as the part is ready" },
    courier: { label: "City courier", hint: "Delivered by motorbike in the workshop's city" },
    post: { label: "Shipping", hint: "A parcel to another city, by travel agency" },
  },
};

export const MATERIAL: Both<Record<Material, string>> = {
  fr: {
    PLA: "PLA — pièce d'intérieur, sèche, sous 50 °C",
    PETG: "PETG — humidité, lave-vaisselle, réfrigérateur",
    ASA: "ASA — extérieur, soleil, jusqu'à 90 °C",
    TPU: "TPU — souple (joints, patins, embouts)",
  },
  en: {
    PLA: "PLA — indoors, dry, below 50 °C",
    PETG: "PETG — damp places, dishwasher, fridge",
    ASA: "ASA — outdoors, sun, up to 90 °C",
    TPU: "TPU — flexible (seals, pads, caps)",
  },
};

const locale = (lang: Lang) => (lang === "fr" ? "fr-FR" : "en-GB");

export function money(lang: Lang, amount: number | undefined | null, currency = "XAF"): string {
  if (amount == null) return "—";
  const unit = currency === "XAF" ? "FCFA" : currency;
  return `${new Intl.NumberFormat(locale(lang), { maximumFractionDigits: 0 }).format(amount)} ${unit}`;
}

export function date(lang: Lang, value: string | number | undefined): string {
  if (value == null) return "";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(`${value}T12:00:00`);
  return d.toLocaleDateString(locale(lang), { weekday: "long", day: "numeric", month: "long" });
}

export function when(lang: Lang, ts: number): string {
  return new Date(ts * 1000).toLocaleString(locale(lang), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** An order's name in the interface's language. */
export function orderTitle(lang: Lang, o: Order): string {
  return (lang === "fr" ? o.title_fr || o.title : o.title_en || o.title) || (lang === "fr" ? "Pièce détachée" : "Spare part");
}

type P = Record<string, any>;

const NOTES: Both<Record<string, (p: P) => string>> = {
  fr: {
    created: () => "Demande créée",
    ordered_studio: () => "Commandée depuis le studio",
    ordered_catalog: (p) => `Commandée depuis le catalogue${p.title ? ` : ${p.title}` : ""}`,
    intake_read: (p) => `Demande lue : ${p.title_fr || p.title || "pièce détachée"}`,
    intake_unread: () => "La demande n'a pas pu être lue automatiquement ; l'atelier la reprend",
    held: () => "En attente d'un contrôle par l'atelier",
    approved: () => "Acceptée par l'atelier",
    refused_safety: (p) => `Refusée par le contrôle de sécurité${p.reason ? ` : ${p.reason}` : ""}`,
    refused_operator: (p) => `Refusée par l'atelier${p.note ? ` : ${p.note}` : ""}`,
    designing: () => "Mesure et conception de la pièce",
    asked: () => "L'atelier vous a posé une question",
    answered: () => "Réponse reçue, la conception reprend",
    design_done: () => "Conception terminée",
    problem: () => "En pause, l'atelier s'en occupe",
    expired: () => "Prix expiré ; un nouveau prix relance la commande",
    paid_test: () => "Paiement de test",
    paid_mobile_money: (p) => `Payée par ${p.operator === "orange" ? "Orange Money" : "MTN MoMo"}, référence ${p.reference}, en cours de vérification`,
    paid_on_pickup: () => "À payer en espèces au retrait",
    payment_verified: () => "Paiement Mobile Money vérifié par l'atelier",
    assigned: (p) => `Sur l'imprimante ${p.printer ?? ""}`.trim(),
    printed: () => "Impression terminée, en attente du contrôle",
    qc_unmeasured: () => "La photo de contrôle n'a pas pu être mesurée ; une autre suit",
    qc_pass: (p) => `Contrôle réussi : écart max ${p.max} mm (tolérance ±${p.tol} mm)`,
    qc_fail: (p) => `Contrôle échoué : écart max ${p.max} mm (tolérance ±${p.tol} mm), réimpression`,
    reprint_qc: () => "Retour dans la file pour une réimpression",
    reprint: (p) => `Réimpression${p.note ? ` : ${p.note}` : ""}`,
    shipped: (p) => `Expédiée${p.carrier ? ` par ${p.carrier}` : ""}${p.tracking ? `, suivi ${p.tracking}` : ""}`,
    delivered: () => "Reçue par le client",
    cancelled: () => "Annulée",
  },
  en: {
    created: () => "Request created",
    ordered_studio: () => "Ordered from the studio",
    ordered_catalog: (p) => `Ordered from the catalog${p.title ? `: ${p.title}` : ""}`,
    intake_read: (p) => `Request read: ${p.title_en || p.title || "spare part"}`,
    intake_unread: () => "The request could not be read automatically; the workshop takes it over",
    held: () => "Waiting for a check by the workshop",
    approved: () => "Accepted by the workshop",
    refused_safety: (p) => `Refused by the safety check${p.reason ? `: ${p.reason}` : ""}`,
    refused_operator: (p) => `Refused by the workshop${p.note ? `: ${p.note}` : ""}`,
    designing: () => "Measuring and designing the part",
    asked: () => "The workshop asked you a question",
    answered: () => "Answer received, the design goes on",
    design_done: () => "Design finished",
    problem: () => "Paused, the workshop is on it",
    expired: () => "Price expired; a new price brings the order back",
    paid_test: () => "Test payment",
    paid_mobile_money: (p) => `Paid by ${p.operator === "orange" ? "Orange Money" : "MTN MoMo"}, reference ${p.reference}, being checked`,
    paid_on_pickup: () => "To be paid in cash on pickup",
    payment_verified: () => "Mobile Money payment checked by the workshop",
    assigned: (p) => `On printer ${p.printer ?? ""}`.trim(),
    printed: () => "Print finished, waiting for the check",
    qc_unmeasured: () => "The check photo could not be measured; another one follows",
    qc_pass: (p) => `Check passed: largest gap ${p.max} mm (tolerance ±${p.tol} mm)`,
    qc_fail: (p) => `Check failed: largest gap ${p.max} mm (tolerance ±${p.tol} mm), printing again`,
    reprint_qc: () => "Back in the queue for a new print",
    reprint: (p) => `Printing again${p.note ? `: ${p.note}` : ""}`,
    shipped: (p) => `Shipped${p.carrier ? ` by ${p.carrier}` : ""}${p.tracking ? `, tracking ${p.tracking}` : ""}`,
    delivered: () => "Received by the customer",
    cancelled: () => "Cancelled",
  },
};

function quotedNote(lang: Lang, p: P, again: boolean): string {
  const by = p.by === "orca" ? (lang === "fr" ? "calculé par le trancheur" : "worked out by the slicer") : lang === "fr" ? "prix fixé par l'atelier" : "set by the workshop";
  const total = money(lang, Number(p.total), String(p.currency ?? "XAF"));
  const min = Math.round(Number(p.minutes));
  const line = lang === "fr"
    ? `${p.grams} g et ${min} min par pièce × ${p.quantity} : ${total}, ${by}`
    : `${p.grams} g and ${min} min each × ${p.quantity}: ${total}, ${by}`;
  return again ? (lang === "fr" ? `Nouveau prix : ${line}` : `New price: ${line}`) : line;
}

export function note(lang: Lang, e: TimelineEntry): string {
  if (e.code === "quoted" || e.code === "requoted") return quotedNote(lang, e.params ?? {}, e.code === "requoted");
  const f = e.code ? NOTES[lang][e.code] : undefined;
  if (f) return f(e.params ?? {});
  if (e.status === "delivered") return NOTES[lang].delivered({});
  if (e.status === "cancelled") return NOTES[lang].cancelled({});
  return e.note || STATUS[lang][e.status];
}

const ERRORS: Both<Record<string, string>> = {
  fr: {
    empty_request: "Ajoutez au moins une photo de la pièce ou quelques mots pour la décrire.",
    too_large: "Ce fichier dépasse 60 Mo. Envoyez une photo plus légère.",
    too_many_orders: "Vous avez déjà beaucoup de commandes ouvertes. Payez, terminez ou annulez-en une d'abord.",
    too_many_pieces: "Sans compte, une commande est limitée à 20 pièces.",
    payment_reference: "Indiquez l'opérateur et la référence de la transaction Mobile Money.",
    payment_method: "Le paiement au retrait n'est possible qu'avec le retrait à l'atelier.",
    quote_expired: "Le prix a expiré. Demandez un nouveau prix.",
    safety_pending: "Le contrôle de sécurité est encore en cours. Réessayez dans un instant.",
    held: "L'atelier vérifie d'abord cette demande.",
    price_updating: "Le prix est en cours de mise à jour. Réessayez dans un instant.",
    no_question: "Aucune question n'attend de réponse.",
    not_operator: "Cette page est réservée à l'atelier.",
  },
  en: {
    empty_request: "Add at least one photo of the part or a few words describing it.",
    too_large: "This file is over 60 MB. Send a lighter photo.",
    too_many_orders: "You already have many open orders. Pay, finish or cancel one first.",
    too_many_pieces: "Without an account, an order is limited to 20 pieces.",
    payment_reference: "Give the operator and the Mobile Money transaction reference.",
    payment_method: "Paying on pickup is only possible with pickup at the workshop.",
    quote_expired: "The price expired. Ask for a new price.",
    safety_pending: "The safety check is still running. Try again in a moment.",
    held: "The workshop checks this request first.",
    price_updating: "The price is being updated. Try again in a moment.",
    no_question: "No question is waiting for an answer.",
    not_operator: "This page is for the workshop only.",
  },
};

export function errorText(lang: Lang, code: string, fallback: string): string {
  return ERRORS[lang][code] ?? fallback;
}
