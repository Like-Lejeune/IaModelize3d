// Everything the customer and the workshop read, in French. The API journal speaks in codes (server/formwright/shop/
// notes.py); each code has its sentence here, and an unknown code falls back to the API's own English line.
import type { Delivery, Material, Status, TimelineEntry } from "./types";

export const STATUS: Record<Status, string> = {
  requested: "Demande reçue",
  designing: "Conception en cours",
  needs_info: "Une question pour vous",
  quoted: "Prix prêt",
  paid: "Payée",
  printing: "En impression",
  qc: "Contrôle qualité",
  shipped: "Expédiée",
  delivered: "Reçue",
  refused: "Refusée",
  cancelled: "Annulée",
  expired: "Prix expiré",
};

// What the customer should know or do at each step, in one sentence.
export const STATUS_HINT: Record<Status, string> = {
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
};

// The path an order follows when all goes well: the progress strip shows it.
export const PATH: Status[] = ["requested", "designing", "quoted", "paid", "printing", "qc", "shipped", "delivered"];

export const DELIVERY: Record<Delivery, { label: string; hint: string }> = {
  pickup: { label: "Retrait à l'atelier", hint: "Gratuit, dès que la pièce est prête" },
  courier: { label: "Coursier en ville", hint: "Livraison à moto dans la ville de l'atelier" },
  post: { label: "Expédition", hint: "Colis vers une autre ville, par agence de voyage" },
};

export const MATERIAL: Record<Material, string> = {
  PLA: "PLA — pièce d'intérieur, sèche, sous 50 °C",
  PETG: "PETG — humidité, lave-vaisselle, réfrigérateur",
  ASA: "ASA — extérieur, soleil, jusqu'à 90 °C",
  TPU: "TPU — souple (joints, patins, embouts)",
};

const nf = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });

export function money(amount: number | undefined | null, currency = "XAF"): string {
  if (amount == null) return "—";
  const unit = currency === "XAF" ? "FCFA" : currency;
  return `${nf.format(amount)} ${unit}`;
}

export function date(value: string | number | undefined): string {
  if (value == null) return "";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(`${value}T12:00:00`);
  return d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

export function when(ts: number): string {
  return new Date(ts * 1000).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

const BY = (p: Record<string, unknown>) => (p.by === "orca" ? "calculé par le trancheur" : "prix fixé par l'atelier");
const QTE = (p: Record<string, unknown>) =>
  `${p.grams} g et ${Math.round(Number(p.minutes))} min par pièce × ${p.quantity} : ${money(Number(p.total), String(p.currency ?? "XAF"))}`;

const NOTE: Record<string, (p: Record<string, any>) => string> = {
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
  quoted: (p) => `${QTE(p)}, ${BY(p)}`,
  requoted: (p) => `Nouveau prix : ${QTE(p)}, ${BY(p)}`,
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
};

export function note(e: TimelineEntry): string {
  const f = e.code ? NOTE[e.code] : undefined;
  if (f) return f(e.params ?? {});
  if (e.status === "delivered") return NOTE.delivered({});
  if (e.status === "cancelled") return NOTE.cancelled({});
  return e.note || STATUS[e.status];
}

export function errorText(code: string, fallback: string): string {
  const known: Record<string, string> = {
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
  };
  return known[code] ?? fallback;
}
