import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { DELIVERY, MATERIAL, PATH, STATUS, STATUS_HINT, date, errorText, money, note, when } from "../fr";
import { usePolled } from "../hooks";
import type { Delivery, Material, Order } from "../types";
import { orderTitle, statusClass } from "./Orders";

const FINAL = ["delivered", "refused", "cancelled"];
// the workshop's Mobile Money numbers, set at build time (apps/repair-web/.env)
const MOMO_MTN = import.meta.env.VITE_MOMO_MTN as string | undefined;
const MOMO_ORANGE = import.meta.env.VITE_MOMO_ORANGE as string | undefined;

export default function OrderPage() {
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
      setProblem(errorText(a.code ?? "", a.message));
    } finally {
      setBusy(false);
    }
  }

  if (error && !o) {
    return (
      <main className="narrow">
        <h1>Commande introuvable</h1>
        <p>Cette commande n'existe pas ou a été passée depuis un autre appareil.</p>
        <Link to="/commandes">Voir mes commandes</Link>
      </main>
    );
  }
  if (!o) return <main className="narrow"><p className="empty">Chargement de la commande…</p></main>;

  const step = PATH.indexOf(o.status === "needs_info" ? "designing" : o.status === "expired" ? "quoted" : o.status);

  return (
    <main className="narrow">
      <section className="sheet">
        <div className="order-head">
          <div>
            <p className="help" style={{ margin: 0 }}>Commande {o.ref}</p>
            <h1 style={{ fontSize: "var(--s3)" }}>{orderTitle(o)}</h1>
            <span className={statusClass(o.status)}>{STATUS[o.status]}</span>
          </div>
          {o.project.cover && <div className="cover" role="img" aria-label="Aperçu de la pièce conçue" style={{ backgroundImage: `url(${o.project.cover})` }} />}
        </div>
        {step >= 0 && (
          <>
            <ol className="track" aria-label={`Étape ${step + 1} sur ${PATH.length} : ${STATUS[o.status]}`}>
              {PATH.map((s, i) => <li key={s} className={i < step ? "done" : i === step ? "now" : ""} title={STATUS[s]} />)}
            </ol>
            <div className="track-caption"><span>Demande</span><span>Reçue</span></div>
          </>
        )}
        <p style={{ marginTop: "1rem" }}>{STATUS_HINT[o.status]}</p>
        {problem && <p className="alert error" role="alert">{problem}</p>}
        {o.status === "refused" && o.intake.reason && <p className="alert warn">{o.intake.reason}</p>}
        {o.safety === "held" && !FINAL.includes(o.status) && (
          <p className="alert info">L'atelier vérifie d'abord cette demande. Vous serez prévenu dès qu'elle avance.</p>
        )}
      </section>

      {o.status === "needs_info" && <Question order={o} busy={busy} onAnswer={(t) => act(() => api.answer(o.id, t))} />}

      {(o.status === "quoted" || o.status === "expired") && (
        <Price order={o} busy={busy} onChange={(b) => act(() => api.requote(o.id, b))}
               onPay={(b) => act(() => api.pay(o.id, b))} />
      )}

      {o.status === "paid" && o.payment?.mode === "mobile_money" && !o.payment.verified && (
        <section className="sheet">
          <h2>Paiement en vérification</h2>
          <p>
            L'atelier vérifie votre paiement {o.payment.operator === "orange" ? "Orange Money" : "MTN MoMo"} (référence{" "}
            <b>{o.payment.reference}</b>) avant de lancer l'impression.
          </p>
        </section>
      )}

      {o.status === "paid" && o.payment?.mode === "on_pickup" && (
        <section className="sheet"><p>Vous paierez {money(o.payment.amount, o.payment.currency)} en espèces au retrait de la pièce.</p></section>
      )}

      {o.status === "shipped" && (
        <section className="sheet">
          <h2>Votre pièce est en route</h2>
          <p>Confirmez la réception quand vous l'avez en main : cela clôt la commande et efface votre numéro de téléphone.</p>
          <button className="btn" disabled={busy} onClick={() => act(() => api.received(o.id))}>J'ai reçu ma pièce</button>
        </section>
      )}

      {o.timeline && o.timeline.length > 0 && (
        <section className="sheet">
          <h2>Suivi</h2>
          <ul className="journal">
            {[...o.timeline].reverse().map((e, i) => (
              <li key={`${e.ts}-${i}`}><time>{when(e.ts)}</time><span>{note(e)}</span></li>
            ))}
          </ul>
        </section>
      )}

      {o.next.includes("cancelled") && (
        <div className="actions">
          <button className="btn danger small" disabled={busy}
                  onClick={() => { if (confirm("Annuler cette commande ?")) act(() => api.cancel(o.id)); }}>
            Annuler la commande
          </button>
        </div>
      )}
    </main>
  );
}

function Question({ order, busy, onAnswer }: { order: Order; busy: boolean; onAnswer: (text: string) => void }) {
  const [text, setText] = useState("");
  const q = order.question;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) onAnswer(text.trim());
  };
  return (
    <section className="sheet" aria-labelledby="q">
      <h2 id="q">Une question de l'atelier</h2>
      <p style={{ fontSize: "var(--s1)" }}>{q?.question || "L'atelier a besoin d'une précision pour continuer."}</p>
      {q?.options && q.options.length > 0 && (
        <div className="actions" style={{ marginTop: 0, marginBottom: "1rem" }}>
          {q.options.map((opt) => <button key={opt} className="btn quiet" disabled={busy} onClick={() => onAnswer(opt)}>{opt}</button>)}
        </div>
      )}
      {q?.allow_text !== false && (
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="answer">Votre réponse</label>
            <textarea id="answer" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ex. : le trou du milieu fait 8 mm" />
          </div>
          <button className="btn" type="submit" disabled={busy || !text.trim()}>Envoyer la réponse</button>
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
  const q = order.quote;
  const cur = q.currency ?? "XAF";
  const pickup = order.delivery?.method === "pickup";
  const [method, setMethod] = useState<PayBody["method"]>("mobile_money");
  const [operator, setOperator] = useState<"mtn" | "orange">("mtn");
  const [reference, setReference] = useState("");
  const canPay = order.next.includes("paid") && q.binding && !order.working;
  const number = operator === "mtn" ? MOMO_MTN : MOMO_ORANGE;

  const pay = (e: FormEvent) => {
    e.preventDefault();
    onPay(method === "mobile_money" ? { method, operator, reference: reference.trim() } : { method });
  };

  return (
    <section className="sheet" aria-labelledby="price">
      <h2 id="price">Prix</h2>
      {!q.binding && q.range && (
        <p className="alert info">Estimation entre {money(q.range.total[0], cur)} et {money(q.range.total[1], cur)}. Le prix exact arrive dans un instant.</p>
      )}
      <table className="price">
        <tbody>
          <tr><td>{q.quantity} × {orderTitle(order)} ({q.material})</td><td>{money(q.parts, cur)}</td></tr>
          {!!q.new_part_fee && <tr><td>Conception d'une nouvelle pièce</td><td>{money(q.new_part_fee, cur)}</td></tr>}
          {q.delivery && <tr><td>{DELIVERY[q.delivery.method].label}</td><td>{q.delivery.price ? money(q.delivery.price, cur) : "Gratuit"}</td></tr>}
          <tr className="total"><td>Total</td><td>{money(q.total, cur)}</td></tr>
        </tbody>
      </table>
      {q.eta && (
        <p className="help">
          {q.delivery?.method === "pickup" ? `Prête le ${date(q.eta.ready_by)}` : `Livrée vers le ${date(q.eta.arrive_by)}`}, si vous payez aujourd'hui.
        </p>
      )}

      <details style={{ margin: "1rem 0" }}>
        <summary>Changer la matière, la quantité ou la réception</summary>
        <div className="row" style={{ marginTop: "0.75rem" }}>
          <div className="field">
            <label htmlFor="rq-mat">Matière</label>
            <select id="rq-mat" defaultValue={q.material} disabled={busy} onChange={(e) => onChange({ material: e.target.value as Material })}>
              {(Object.keys(MATERIAL) as Material[]).map((m) => <option key={m} value={m}>{MATERIAL[m]}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="rq-qty">Nombre de pièces</label>
            <input id="rq-qty" type="number" min={1} max={200} defaultValue={q.quantity} disabled={busy}
                   onBlur={(e) => { const n = Number(e.target.value); if (n >= 1 && n !== q.quantity) onChange({ quantity: n }); }} />
          </div>
          <div className="field">
            <label htmlFor="rq-del">Réception</label>
            <select id="rq-del" defaultValue={q.delivery?.method} disabled={busy} onChange={(e) => onChange({ delivery: e.target.value as Delivery })}>
              {(Object.keys(DELIVERY) as Delivery[]).map((d) => <option key={d} value={d}>{DELIVERY[d].label}</option>)}
            </select>
          </div>
        </div>
      </details>

      {order.status === "expired" ? (
        <button className="btn" disabled={busy} onClick={() => onChange({})}>Demander un nouveau prix</button>
      ) : (
        <form onSubmit={pay}>
          <fieldset className="field" style={{ border: 0, padding: 0 }}>
            <legend className="legend" style={{ marginBottom: "0.35rem" }}>Paiement</legend>
            <div className="choices">
              <label className="choice">
                <input type="radio" name="pay" checked={method === "mobile_money"} onChange={() => setMethod("mobile_money")} />
                <div><b>Mobile Money</b><span>MTN MoMo ou Orange Money, vérifié par l'atelier avant l'impression</span></div>
              </label>
              {pickup && (
                <label className="choice">
                  <input type="radio" name="pay" checked={method === "on_pickup"} onChange={() => setMethod("on_pickup")} />
                  <div><b>En espèces au retrait</b><span>Vous payez à l'atelier en récupérant la pièce</span></div>
                </label>
              )}
              {import.meta.env.DEV && (
                <label className="choice">
                  <input type="radio" name="pay" checked={method === "test"} onChange={() => setMethod("test")} />
                  <div><b>Paiement de test</b><span>Développement uniquement : aucun argent ne circule</span></div>
                </label>
              )}
            </div>
          </fieldset>
          {method === "mobile_money" && (
            <>
              <div className="row">
                <div className="field">
                  <label htmlFor="op">Opérateur</label>
                  <select id="op" value={operator} onChange={(e) => setOperator(e.target.value as "mtn" | "orange")}>
                    <option value="mtn">MTN MoMo</option>
                    <option value="orange">Orange Money</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="ref">Référence de la transaction</label>
                  <input id="ref" type="text" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Reçue par SMS après l'envoi" />
                </div>
              </div>
              <p className="help">
                Envoyez {money(q.total, cur)} {number ? <>au <b>{number}</b></> : "au numéro Mobile Money de l'atelier"}, puis
                saisissez la référence reçue par SMS.
              </p>
            </>
          )}
          <button className="btn" type="submit" disabled={busy || !canPay || (method === "mobile_money" && !reference.trim())}>
            {method === "mobile_money" ? "J'ai envoyé le paiement" : method === "on_pickup" ? "Confirmer la commande" : `Payer ${money(q.total, cur)} (test)`}
          </button>
          {!canPay && order.safety === "pending" && <p className="help">Le contrôle de sécurité se termine, le paiement s'ouvre dans un instant.</p>}
        </form>
      )}
    </section>
  );
}
