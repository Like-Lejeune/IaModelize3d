import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { useLang } from "../i18n";
import { DELIVERY, MATERIAL, PATH, STATUS, STATUS_HINT, date, errorText, money, note, orderTitle, when } from "../texts";
import { usePolled } from "../hooks";
import type { Delivery, Material, Order } from "../types";
import { statusClass } from "./Orders";

const FINAL = ["delivered", "refused", "cancelled"];
// the workshop's Mobile Money numbers, set at build time (apps/repair-web/.env)
const MOMO_MTN = import.meta.env.VITE_MOMO_MTN as string | undefined;
const MOMO_ORANGE = import.meta.env.VITE_MOMO_ORANGE as string | undefined;

export default function OrderPage() {
  const { lang, tr } = useLang();
  const { id = "" } = useParams();
  const { data: o, error, setData } = usePolled(() => api.order(id), 4000, (x) => !FINAL.includes(x.status));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function act(run: () => Promise<Order>) {
    setBusy(true);
    setProblem(null);
    try {
      setData(await run());
    } catch (e) {
      const a = e as ApiError;
      setProblem(errorText(lang, a.code ?? "", a.message));
    } finally {
      setBusy(false);
    }
  }

  if (error && !o) {
    return (
      <main className="narrow">
        <h1>{tr("Commande introuvable", "Order not found")}</h1>
        <p>{tr("Cette commande n'existe pas ou a été passée depuis un autre appareil.", "This order does not exist or was placed from another device.")}</p>
        <Link to="/commandes">{tr("Voir mes commandes", "See my orders")}</Link>
      </main>
    );
  }
  if (!o) return <main className="narrow"><p className="empty">{tr("Chargement de la commande…", "Loading the order…")}</p></main>;

  const step = PATH.indexOf(o.status === "needs_info" ? "designing" : o.status === "expired" ? "quoted" : o.status);
  const operator = o.payment?.operator === "orange" ? "Orange Money" : "MTN MoMo";

  return (
    <main className="narrow">
      <section className="sheet">
        <div className="order-head">
          <div>
            <p className="help" style={{ margin: 0 }}>{tr("Commande", "Order")} {o.ref}</p>
            <h1 style={{ fontSize: "var(--s3)" }}>{orderTitle(lang, o)}</h1>
            <span className={statusClass(o.status)}>{STATUS[lang][o.status]}</span>
          </div>
          {o.project.cover && <div className="cover" role="img" aria-label={tr("Aperçu de la pièce conçue", "Preview of the designed part")} style={{ backgroundImage: `url(${o.project.cover})` }} />}
        </div>
        {step >= 0 && (
          <>
            <ol className="track" aria-label={tr(`Étape ${step + 1} sur ${PATH.length} : ${STATUS.fr[o.status]}`, `Step ${step + 1} of ${PATH.length}: ${STATUS.en[o.status]}`)}>
              {PATH.map((s, i) => <li key={s} className={i < step ? "done" : i === step ? "now" : ""} title={STATUS[lang][s]} />)}
            </ol>
            <div className="track-caption"><span>{tr("Demande", "Request")}</span><span>{tr("Reçue", "Received")}</span></div>
          </>
        )}
        <p style={{ marginTop: "1rem" }}>{STATUS_HINT[lang][o.status]}</p>
        {problem && <p className="alert error" role="alert">{problem}</p>}
        {o.status === "refused" && o.intake.reason && <p className="alert warn">{o.intake.reason}</p>}
        {o.safety === "held" && !FINAL.includes(o.status) && (
          <p className="alert info">{tr("L'atelier vérifie d'abord cette demande. Vous serez prévenu dès qu'elle avance.", "The workshop checks this request first. You will be told as soon as it moves on.")}</p>
        )}
      </section>

      {o.status === "needs_info" && <Question order={o} busy={busy} onAnswer={(t) => act(() => api.answer(o.id, t))} />}

      {(o.status === "quoted" || o.status === "expired") && (
        <Price order={o} busy={busy} onChange={(b) => act(() => api.requote(o.id, b))}
               onPay={(b) => act(() => api.pay(o.id, b))} />
      )}

      {o.status === "paid" && o.payment?.mode === "mobile_money" && !o.payment.verified && (
        <section className="sheet">
          <h2>{tr("Paiement en vérification", "Payment being checked")}</h2>
          <p>
            {tr(`L'atelier vérifie votre paiement ${operator} (référence `, `The workshop is checking your ${operator} payment (reference `)}
            <b>{o.payment.reference}</b>
            {tr(") avant de lancer l'impression.", ") before starting the print.")}
          </p>
        </section>
      )}

      {o.status === "paid" && o.payment?.mode === "on_pickup" && (
        <section className="sheet"><p>{tr(
          `Vous paierez ${money(lang, o.payment.amount, o.payment.currency)} en espèces au retrait de la pièce.`,
          `You will pay ${money(lang, o.payment.amount, o.payment.currency)} in cash when you pick up the part.`,
        )}</p></section>
      )}

      {o.status === "shipped" && (
        <section className="sheet">
          <h2>{tr("Votre pièce est en route", "Your part is on its way")}</h2>
          <p>{tr(
            "Confirmez la réception quand vous l'avez en main : cela clôt la commande et efface votre numéro de téléphone.",
            "Confirm when you have it in hand: this closes the order and erases your phone number.",
          )}</p>
          <button className="btn" disabled={busy} onClick={() => act(() => api.received(o.id))}>{tr("J'ai reçu ma pièce", "I received my part")}</button>
        </section>
      )}

      {o.timeline && o.timeline.length > 0 && (
        <section className="sheet">
          <h2>{tr("Suivi", "Tracking")}</h2>
          <ul className="journal">
            {[...o.timeline].reverse().map((e, i) => (
              <li key={`${e.ts}-${i}`}><time>{when(lang, e.ts)}</time><span>{note(lang, e)}</span></li>
            ))}
          </ul>
        </section>
      )}

      {o.next.includes("cancelled") && (
        <div className="actions">
          <button className="btn danger small" disabled={busy}
                  onClick={() => { if (confirm(tr("Annuler cette commande ?", "Cancel this order?"))) act(() => api.cancel(o.id)); }}>
            {tr("Annuler la commande", "Cancel the order")}
          </button>
        </div>
      )}
    </main>
  );
}

function Question({ order, busy, onAnswer }: { order: Order; busy: boolean; onAnswer: (text: string) => void }) {
  const { tr } = useLang();
  const [text, setText] = useState("");
  const q = order.question;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) onAnswer(text.trim());
  };
  return (
    <section className="sheet" aria-labelledby="q">
      <h2 id="q">{tr("Une question de l'atelier", "A question from the workshop")}</h2>
      <p style={{ fontSize: "var(--s1)" }}>{q?.question || tr("L'atelier a besoin d'une précision pour continuer.", "The workshop needs one more detail to go on.")}</p>
      {q?.options && q.options.length > 0 && (
        <div className="actions" style={{ marginTop: 0, marginBottom: "1rem" }}>
          {q.options.map((opt) => <button key={opt} className="btn quiet" disabled={busy} onClick={() => onAnswer(opt)}>{opt}</button>)}
        </div>
      )}
      {q?.allow_text !== false && (
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="answer">{tr("Votre réponse", "Your answer")}</label>
            <textarea id="answer" value={text} onChange={(e) => setText(e.target.value)} placeholder={tr("Ex. : le trou du milieu fait 8 mm", "E.g. the middle hole is 8 mm")} />
          </div>
          <button className="btn" type="submit" disabled={busy || !text.trim()}>{tr("Envoyer la réponse", "Send the answer")}</button>
        </form>
      )}
    </section>
  );
}

type PayBody = { method: "test" | "mobile_money" | "on_pickup"; operator?: "mtn" | "orange"; reference?: string };

function Price({ order, busy, onChange, onPay }: {
  order: Order;
  busy: boolean;
  onChange: (b: { material?: Material; quantity?: number; delivery?: Delivery }) => void;
  onPay: (b: PayBody) => void;
}) {
  const { lang, tr } = useLang();
  const q = order.quote;
  const cur = q.currency ?? "XAF";
  const pickup = order.delivery?.method === "pickup";
  const [method, setMethod] = useState<PayBody["method"]>("mobile_money");
  const [operator, setOperator] = useState<"mtn" | "orange">("mtn");
  const [reference, setReference] = useState("");
  const canPay = order.next.includes("paid") && q.binding && !order.working;
  const number = operator === "mtn" ? MOMO_MTN : MOMO_ORANGE;
  const total = money(lang, q.total, cur);

  const pay = (e: FormEvent) => {
    e.preventDefault();
    onPay(method === "mobile_money" ? { method, operator, reference: reference.trim() } : { method });
  };

  return (
    <section className="sheet" aria-labelledby="price">
      <h2 id="price">{tr("Prix", "Price")}</h2>
      {!q.binding && q.range && (
        <p className="alert info">{tr(
          `Estimation entre ${money(lang, q.range.total[0], cur)} et ${money(lang, q.range.total[1], cur)}. Le prix exact arrive dans un instant.`,
          `Estimate between ${money(lang, q.range.total[0], cur)} and ${money(lang, q.range.total[1], cur)}. The exact price is coming in a moment.`,
        )}</p>
      )}
      <table className="price">
        <tbody>
          <tr><td>{q.quantity} × {orderTitle(lang, order)} ({q.material})</td><td>{money(lang, q.parts, cur)}</td></tr>
          {!!q.new_part_fee && <tr><td>{tr("Conception d'une nouvelle pièce", "Designing a new part")}</td><td>{money(lang, q.new_part_fee, cur)}</td></tr>}
          {q.delivery && <tr><td>{DELIVERY[lang][q.delivery.method].label}</td><td>{q.delivery.price ? money(lang, q.delivery.price, cur) : tr("Gratuit", "Free")}</td></tr>}
          <tr className="total"><td>Total</td><td>{total}</td></tr>
        </tbody>
      </table>
      {q.eta && (
        <p className="help">
          {q.delivery?.method === "pickup"
            ? tr(`Prête le ${date(lang, q.eta.ready_by)}, si vous payez aujourd'hui.`, `Ready on ${date(lang, q.eta.ready_by)}, if you pay today.`)
            : tr(`Livrée vers le ${date(lang, q.eta.arrive_by)}, si vous payez aujourd'hui.`, `Delivered around ${date(lang, q.eta.arrive_by)}, if you pay today.`)}
        </p>
      )}

      <details style={{ margin: "1rem 0" }}>
        <summary>{tr("Changer la matière, la quantité ou la réception", "Change the material, quantity or delivery")}</summary>
        <div className="row" style={{ marginTop: "0.75rem" }}>
          <div className="field">
            <label htmlFor="rq-mat">{tr("Matière", "Material")}</label>
            <select id="rq-mat" defaultValue={q.material} disabled={busy} onChange={(e) => onChange({ material: e.target.value as Material })}>
              {(Object.keys(MATERIAL[lang]) as Material[]).map((m) => <option key={m} value={m}>{MATERIAL[lang][m]}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="rq-qty">{tr("Nombre de pièces", "Number of pieces")}</label>
            <input id="rq-qty" type="number" min={1} max={200} defaultValue={q.quantity} disabled={busy}
                   onBlur={(e) => { const n = Number(e.target.value); if (n >= 1 && n !== q.quantity) onChange({ quantity: n }); }} />
          </div>
          <div className="field">
            <label htmlFor="rq-del">{tr("Réception", "Delivery")}</label>
            <select id="rq-del" defaultValue={q.delivery?.method} disabled={busy} onChange={(e) => onChange({ delivery: e.target.value as Delivery })}>
              {(Object.keys(DELIVERY[lang]) as Delivery[]).map((d) => <option key={d} value={d}>{DELIVERY[lang][d].label}</option>)}
            </select>
          </div>
        </div>
      </details>

      {order.status === "expired" ? (
        <button className="btn" disabled={busy} onClick={() => onChange({})}>{tr("Demander un nouveau prix", "Ask for a new price")}</button>
      ) : (
        <form onSubmit={pay}>
          <fieldset className="field" style={{ border: 0, padding: 0 }}>
            <legend className="legend" style={{ marginBottom: "0.35rem" }}>{tr("Paiement", "Payment")}</legend>
            <div className="choices">
              <label className="choice">
                <input type="radio" name="pay" checked={method === "mobile_money"} onChange={() => setMethod("mobile_money")} />
                <div><b>Mobile Money</b><span>{tr("MTN MoMo ou Orange Money, vérifié par l'atelier avant l'impression", "MTN MoMo or Orange Money, checked by the workshop before printing")}</span></div>
              </label>
              {pickup && (
                <label className="choice">
                  <input type="radio" name="pay" checked={method === "on_pickup"} onChange={() => setMethod("on_pickup")} />
                  <div><b>{tr("En espèces au retrait", "Cash on pickup")}</b><span>{tr("Vous payez à l'atelier en récupérant la pièce", "You pay at the workshop when you collect the part")}</span></div>
                </label>
              )}
              {import.meta.env.DEV && (
                <label className="choice">
                  <input type="radio" name="pay" checked={method === "test"} onChange={() => setMethod("test")} />
                  <div><b>{tr("Paiement de test", "Test payment")}</b><span>{tr("Développement uniquement : aucun argent ne circule", "Development only: no money moves")}</span></div>
                </label>
              )}
            </div>
          </fieldset>
          {method === "mobile_money" && (
            <>
              <div className="row">
                <div className="field">
                  <label htmlFor="op">{tr("Opérateur", "Operator")}</label>
                  <select id="op" value={operator} onChange={(e) => setOperator(e.target.value as "mtn" | "orange")}>
                    <option value="mtn">MTN MoMo</option>
                    <option value="orange">Orange Money</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="ref">{tr("Référence de la transaction", "Transaction reference")}</label>
                  <input id="ref" type="text" value={reference} onChange={(e) => setReference(e.target.value)} placeholder={tr("Reçue par SMS après l'envoi", "Received by SMS after sending")} />
                </div>
              </div>
              <p className="help">
                {tr(`Envoyez ${total} `, `Send ${total} `)}
                {number ? <>{tr("au ", "to ")}<b>{number}</b></> : tr("au numéro Mobile Money de l'atelier", "to the workshop's Mobile Money number")}
                {tr(", puis saisissez la référence reçue par SMS.", ", then enter the reference you get by SMS.")}
              </p>
            </>
          )}
          <button className="btn" type="submit" disabled={busy || !canPay || (method === "mobile_money" && !reference.trim())}>
            {method === "mobile_money" ? tr("J'ai envoyé le paiement", "I have sent the payment")
              : method === "on_pickup" ? tr("Confirmer la commande", "Confirm the order")
              : tr(`Payer ${total} (test)`, `Pay ${total} (test)`)}
          </button>
          {!canPay && order.safety === "pending" && <p className="help">{tr("Le contrôle de sécurité se termine, le paiement s'ouvre dans un instant.", "The safety check is finishing; payment opens in a moment.")}</p>}
        </form>
      )}
    </section>
  );
}
