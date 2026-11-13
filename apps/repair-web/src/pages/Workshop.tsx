import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import { useSession } from "../App";
import { useLang } from "../i18n";
import { DELIVERY, STATUS, errorText, money, orderTitle } from "../texts";
import { usePolled } from "../hooks";
import type { Board, Material, Order, Printer } from "../types";
import { statusClass } from "./Orders";

/** The workshop's board: requests to check, payments to verify, prints to start, parts to measure and hand over. */
export default function Workshop() {
  const { lang, tr } = useLang();
  const { me } = useSession();
  const { data: board, error, reload } = usePolled(() => api.board(), 6000);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function act(orderId: string, run: () => Promise<unknown>) {
    setBusy(orderId);
    setProblem(null);
    try {
      await run();
      await reload();
    } catch (e) {
      const a = e as ApiError;
      setProblem(`${orderId}: ${errorText(lang, a.code ?? "", a.message)}`);
    } finally {
      setBusy(null);
    }
  }

  if (error && !board) {
    const denied = (error as ApiError).code === "not_operator";
    return (
      <main className="narrow">
        <h1>{tr("Atelier", "Workshop")}</h1>
        <p className="alert error">{denied
          ? tr("Cette page est réservée à l'atelier. Ouvrez le lien de connexion qu'il vous a envoyé.", "This page is for the workshop only. Open the sign-in link you were sent.")
          : tr("Le tableau n'a pas pu être chargé.", "The board could not be loaded.")}</p>
      </main>
    );
  }
  if (!board) return <main><p className="empty">{tr("Chargement du tableau…", "Loading the board…")}</p></main>;

  const held = board.upstream.filter((o) => o.safety === "held");
  const upstream = board.upstream.filter((o) => o.safety !== "held");
  const lane = (s: Order["status"]) => board.orders.filter((o) => o.status === s);
  const toShip = board.done.filter((o) => o.status === "shipped");
  const hours = board.queue_hours.toFixed(1);

  return (
    <main>
      <h1>{tr("Atelier", "Workshop")}</h1>
      <p className="help">
        {me?.org?.name ? `${me.org.name}, ` : ""}
        {tr(`file d'impression estimée à ${hours} h. Le tableau se met à jour tout seul.`, `print queue estimated at ${hours} h. The board updates by itself.`)}
      </p>
      {problem && <p className="alert error" role="alert">{problem}</p>}

      <div className="board">
        <Lane title={tr("Demandes à examiner", "Requests to review")} hint={tr("le contrôle de sécurité n'a pas pu trancher", "the safety check could not decide")} orders={held}>
          {(o) => (
            <>
              <button className="btn small" disabled={busy === o.id} onClick={() => act(o.id, () => api.review(o.id, "approve"))}>{tr("Accepter", "Accept")}</button>
              <button className="btn danger small" disabled={busy === o.id}
                      onClick={() => { const n = prompt(tr("Motif du refus, lu par le client :", "Reason for refusing, read by the customer:")) ?? ""; if (n) act(o.id, () => api.review(o.id, "refuse", n)); }}>
                {tr("Refuser", "Refuse")}
              </button>
            </>
          )}
        </Lane>

        <Lane title={tr("Payées", "Paid")} hint={tr("vérifier le paiement, puis lancer l'impression", "check the payment, then start the print")} orders={lane("paid")}>
          {(o) => <PaidControls order={o} printers={board.printers} busy={busy === o.id} act={act} />}
        </Lane>

        <Lane title={tr("En impression", "Printing")} hint={tr("à retirer du plateau", "to take off the bed")} orders={lane("printing")}>
          {(o) => <button className="btn small" disabled={busy === o.id} onClick={() => act(o.id, () => api.printed(o.id))}>{tr("Impression terminée", "Print finished")}</button>}
        </Lane>

        <Lane title={tr("Contrôle qualité", "Quality check")} hint={tr("photographier la pièce sur la feuille A4", "photograph the part on the A4 sheet")} orders={lane("qc")}>
          {(o) => <QcControls order={o} busy={busy === o.id} act={act} />}
        </Lane>

        <Lane title={tr("Expédiées", "Shipped")} hint={tr("en attente de la confirmation du client", "waiting for the customer to confirm")} orders={toShip}>
          {(o) => <button className="btn quiet small" disabled={busy === o.id} onClick={() => act(o.id, () => api.opsDelivered(o.id))}>{tr("Marquer comme reçue", "Mark as received")}</button>}
        </Lane>

        <Lane title={tr("En amont", "Upstream")} hint={tr("lecture, conception et devis en cours", "reading, design and pricing under way")} orders={upstream}>
          {() => null}
        </Lane>

        <Printers printers={board.printers} onAdd={(name, material) => act(tr("imprimante", "printer"), () => api.addPrinter(name, material))} />
      </div>
    </main>
  );
}

function Lane({ title, hint, orders, children }: { title: string; hint: string; orders: Order[]; children: (o: Order) => React.ReactNode }) {
  const { lang, tr } = useLang();
  return (
    <section className={`sheet lane${orders.length ? "" : " idle"}`} aria-label={title}>
      <h2>{title} <small>{orders.length ? tr(`${orders.length} en cours, ${hint}`, `${orders.length} open, ${hint}`) : tr("rien pour l'instant", "nothing for now")}</small></h2>
      {orders.map((o) => (
        <div className="job" key={o.id}>
          <div>
            <Link to={`/commandes/${o.id}`}><b>{o.ref}</b></Link> {orderTitle(lang, o)}{" "}
            <span className={statusClass(o.status)}>{STATUS[lang][o.status]}</span>
            <div className="meta">
              {o.quantity} × {o.material}, {DELIVERY[lang][o.delivery?.method ?? "pickup"].label.toLowerCase()}
              {o.quote.total != null && `, ${money(lang, o.quote.total, o.quote.currency)}`}
              {o.customer?.contact && `, ${o.customer.contact}`}
            </div>
            {o.intake.review?.why && <div className="meta">{tr("Motif", "Reason")}: {o.intake.review.why}</div>}
          </div>
          <div className="controls">{children(o)}</div>
        </div>
      ))}
    </section>
  );
}

type Act = (orderId: string, run: () => Promise<unknown>) => Promise<void>;

function PaidControls({ order, printers, busy, act }: { order: Order; printers: Printer[]; busy: boolean; act: Act }) {
  const { tr } = useLang();
  const free = printers.filter((p) => p.state === "idle");
  const [picked, setPicked] = useState("");
  // the operator's pick while that printer is still free, else one loaded with the order's material, else any free one
  const printer = free.some((p) => p.id === picked) ? picked : free.find((p) => p.material === order.material)?.id ?? free[0]?.id ?? "";
  const pay = order.payment ?? {};
  if (pay.mode === "mobile_money" && !pay.verified) {
    return (
      <>
        <span className="meta">{pay.operator === "orange" ? "Orange Money" : "MTN MoMo"}, {tr("réf.", "ref.")} <b>{pay.reference}</b></span>
        <button className="btn small" disabled={busy} onClick={() => act(order.id, () => api.verifyPayment(order.id))}>{tr("Paiement reçu", "Payment received")}</button>
      </>
    );
  }
  if (free.length === 0) return <span className="meta">{tr("Aucune imprimante libre", "No free printer")}</span>;
  return (
    <>
      {pay.mode === "on_pickup" && <span className="meta">{tr("Paiement au retrait", "Pay on pickup")}</span>}
      <select aria-label={tr("Imprimante", "Printer")} value={printer} onChange={(e) => setPicked(e.target.value)}>
        {free.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.material})</option>)}
      </select>
      <button className="btn small" disabled={busy || !printer} onClick={() => act(order.id, () => api.assign(order.id, printer))}>{tr("Lancer l'impression", "Start the print")}</button>
    </>
  );
}

function QcControls({ order, busy, act }: { order: Order; busy: boolean; act: Act }) {
  const { tr } = useLang();
  const passed = order.qc?.pass;
  const pickup = order.delivery?.method === "pickup";
  if (passed) {
    return (
      <>
        <span className="pill ok">{tr("Contrôle réussi", "Check passed")}{order.qc?.max_mm != null ? `, ${order.qc.max_mm} mm` : ""}</span>
        <button className="btn small" disabled={busy}
                onClick={() => {
                  if (pickup) return act(order.id, () => api.ship(order.id, tr("Retrait à l'atelier", "Pickup at the workshop"), ""));
                  const carrier = prompt(tr("Transporteur (coursier, agence de voyage) :", "Carrier (courier, travel agency):")) ?? "";
                  const tracking = carrier ? prompt(tr("Numéro de suivi ou du bordereau :", "Tracking or waybill number:")) ?? "" : "";
                  if (carrier && tracking) return act(order.id, () => api.ship(order.id, carrier, tracking));
                }}>
          {pickup ? tr("Remise au client", "Hand over to the customer") : tr("Expédier", "Ship")}
        </button>
      </>
    );
  }
  return (
    <>
      {order.qc?.error && <span className="meta">{order.qc.error}</span>}
      <label className="btn small quiet" style={{ position: "relative" }}>
        {tr("Photo de contrôle", "Check photo")}
        <input type="file" accept="image/*" capture="environment" disabled={busy}
               style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer" }}
               onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) act(order.id, () => api.qc(order.id, f)); }} />
      </label>
      <button className="btn danger small" disabled={busy}
              onClick={() => { const n = prompt(tr("Défaut constaté :", "Defect found:")) ?? ""; if (n) act(order.id, () => api.reprint(order.id, n)); }}>
        {tr("Réimprimer", "Print again")}
      </button>
    </>
  );
}

function Printers({ printers, onAdd }: { printers: Board["printers"]; onAdd: (name: string, material: Material) => void }) {
  const { tr } = useLang();
  const [name, setName] = useState("");
  const [material, setMaterial] = useState<Material>("PLA");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) {
      onAdd(name.trim(), material);
      setName("");
    }
  };
  const state = {
    idle: tr("libre", "free"),
    printing: tr("occupée", "busy"),
    maintenance: tr("en maintenance", "in maintenance"),
  } as const;
  return (
    <section className="sheet" aria-label={tr("Imprimantes", "Printers")}>
      <h2>{tr("Imprimantes", "Printers")}</h2>
      <div className="printers">
        {printers.length === 0 && <p className="empty">{tr("Ajoutez la première imprimante de l'atelier.", "Add the workshop's first printer.")}</p>}
        {printers.map((p) => (
          <span key={p.id} className={p.state === "idle" ? "pill ok" : "pill"}>
            {p.name}, {p.material}, {state[p.state]}{p.order_ref ? ` (${p.order_ref})` : ""}
          </span>
        ))}
      </div>
      <form className="row" onSubmit={submit} style={{ marginTop: "1rem", alignItems: "end" }}>
        <div className="field" style={{ margin: 0 }}>
          <label htmlFor="pr-name">{tr("Nom", "Name")}</label>
          <input id="pr-name" type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder={tr("Ex. : A1 n° 1", "E.g. A1 no. 1")} />
        </div>
        <div className="field" style={{ margin: 0 }}>
          <label htmlFor="pr-mat">{tr("Matière chargée", "Loaded material")}</label>
          <select id="pr-mat" value={material} onChange={(e) => setMaterial(e.target.value as Material)}>
            {(["PLA", "PETG", "ASA", "TPU"] as Material[]).map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
        <button className="btn" type="submit" disabled={!name.trim()}>{tr("Ajouter l'imprimante", "Add the printer")}</button>
      </form>
    </section>
  );
}
