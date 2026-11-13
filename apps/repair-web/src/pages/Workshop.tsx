import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import { useSession } from "../App";
import { DELIVERY, STATUS, errorText, money } from "../fr";
import { usePolled } from "../hooks";
import type { Board, Material, Order, Printer } from "../types";
import { orderTitle, statusClass } from "./Orders";

/** The workshop's board: requests to check, payments to verify, prints to start, parts to measure and hand over. */
export default function Workshop() {
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
      setProblem(`${orderId}: ${errorText(a.code ?? "", a.message)}`);
    } finally {
      setBusy(null);
    }
  }

  if (error && !board) {
    const denied = (error as ApiError).code === "not_operator";
    return (
      <main className="narrow">
        <h1>Atelier</h1>
        <p className="alert error">{denied ? "Cette page est réservée à l'atelier. Ouvrez le lien de connexion qu'il vous a envoyé." : "Le tableau n'a pas pu être chargé."}</p>
      </main>
    );
  }
  if (!board) return <main><p className="empty">Chargement du tableau…</p></main>;

  const held = board.upstream.filter((o) => o.safety === "held");
  const upstream = board.upstream.filter((o) => o.safety !== "held");
  const lane = (s: Order["status"]) => board.orders.filter((o) => o.status === s);
  const toShip = board.done.filter((o) => o.status === "shipped");

  return (
    <main>
      <h1>Atelier</h1>
      <p className="help">
        {me?.org?.name ? `${me.org.name}, ` : ""}file d'impression estimée à {board.queue_hours.toFixed(1)} h. Le tableau se met à jour tout seul.
      </p>
      {problem && <p className="alert error" role="alert">{problem}</p>}

      <div className="board">
        <Lane title="Demandes à examiner" hint="le contrôle de sécurité n'a pas pu trancher" orders={held}>
          {(o) => (
            <>
              <button className="btn small" disabled={busy === o.id} onClick={() => act(o.id, () => api.review(o.id, "approve"))}>Accepter</button>
              <button className="btn danger small" disabled={busy === o.id}
                      onClick={() => { const n = prompt("Motif du refus, lu par le client :") ?? ""; if (n) act(o.id, () => api.review(o.id, "refuse", n)); }}>
                Refuser
              </button>
            </>
          )}
        </Lane>

        <Lane title="Payées" hint="vérifier le paiement, puis lancer l'impression" orders={lane("paid")}>
          {(o) => <PaidControls order={o} printers={board.printers} busy={busy === o.id} act={act} />}
        </Lane>

        <Lane title="En impression" hint="à retirer du plateau" orders={lane("printing")}>
          {(o) => <button className="btn small" disabled={busy === o.id} onClick={() => act(o.id, () => api.printed(o.id))}>Impression terminée</button>}
        </Lane>

        <Lane title="Contrôle qualité" hint="photographier la pièce sur la feuille A4" orders={lane("qc")}>
          {(o) => <QcControls order={o} busy={busy === o.id} act={act} />}
        </Lane>

        <Lane title="Expédiées" hint="en attente de la confirmation du client" orders={toShip}>
          {(o) => <button className="btn quiet small" disabled={busy === o.id} onClick={() => act(o.id, () => api.opsDelivered(o.id))}>Marquer comme reçue</button>}
        </Lane>

        <Lane title="En amont" hint="lecture, conception et devis en cours" orders={upstream}>
          {() => null}
        </Lane>

        <Printers printers={board.printers} onAdd={(name, material) => act("imprimante", () => api.addPrinter(name, material))} />
      </div>
    </main>
  );
}

function Lane({ title, hint, orders, children }: { title: string; hint: string; orders: Order[]; children: (o: Order) => React.ReactNode }) {
  return (
    <section className={`sheet lane${orders.length ? "" : " idle"}`} aria-label={title}>
      <h2>{title} <small>{orders.length ? `${orders.length} en cours, ${hint}` : "rien pour l'instant"}</small></h2>
      {orders.map((o) => (
        <div className="job" key={o.id}>
          <div>
            <Link to={`/commandes/${o.id}`}><b>{o.ref}</b></Link> {orderTitle(o)}{" "}
            <span className={statusClass(o.status)}>{STATUS[o.status]}</span>
            <div className="meta">
              {o.quantity} × {o.material}, {DELIVERY[o.delivery?.method ?? "pickup"].label.toLowerCase()}
              {o.quote.total != null && `, ${money(o.quote.total, o.quote.currency)}`}
              {o.customer?.contact && `, ${o.customer.contact}`}
            </div>
            {o.intake.review?.why && <div className="meta">Motif : {o.intake.review.why}</div>}
          </div>
          <div className="controls">{children(o)}</div>
        </div>
      ))}
    </section>
  );
}

type Act = (orderId: string, run: () => Promise<unknown>) => Promise<void>;

function PaidControls({ order, printers, busy, act }: { order: Order; printers: Printer[]; busy: boolean; act: Act }) {
  const free = printers.filter((p) => p.state === "idle");
  const [picked, setPicked] = useState("");
  // the operator's pick while that printer is still free, else one loaded with the order's material, else any free one
  const printer = free.some((p) => p.id === picked) ? picked : free.find((p) => p.material === order.material)?.id ?? free[0]?.id ?? "";
  const pay = order.payment ?? {};
  if (pay.mode === "mobile_money" && !pay.verified) {
    return (
      <>
        <span className="meta">{pay.operator === "orange" ? "Orange Money" : "MTN MoMo"}, réf. <b>{pay.reference}</b></span>
        <button className="btn small" disabled={busy} onClick={() => act(order.id, () => api.verifyPayment(order.id))}>Paiement reçu</button>
      </>
    );
  }
  if (free.length === 0) return <span className="meta">Aucune imprimante libre</span>;
  return (
    <>
      {pay.mode === "on_pickup" && <span className="meta">Paiement au retrait</span>}
      <select aria-label="Imprimante" value={printer} onChange={(e) => setPicked(e.target.value)}>
        {free.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.material})</option>)}
      </select>
      <button className="btn small" disabled={busy || !printer} onClick={() => act(order.id, () => api.assign(order.id, printer))}>Lancer l'impression</button>
    </>
  );
}

function QcControls({ order, busy, act }: { order: Order; busy: boolean; act: Act }) {
  const passed = order.qc?.pass;
  const pickup = order.delivery?.method === "pickup";
  if (passed) {
    return (
      <>
        <span className="pill ok">Contrôle réussi{order.qc?.max_mm != null ? `, ${order.qc.max_mm} mm` : ""}</span>
        <button className="btn small" disabled={busy}
                onClick={() => {
                  if (pickup) return act(order.id, () => api.ship(order.id, "Retrait à l'atelier", ""));
                  const carrier = prompt("Transporteur (coursier, agence de voyage) :") ?? "";
                  const tracking = carrier ? prompt("Numéro de suivi ou du bordereau :") ?? "" : "";
                  if (carrier && tracking) return act(order.id, () => api.ship(order.id, carrier, tracking));
                }}>
          {pickup ? "Remise au client" : "Expédier"}
        </button>
      </>
    );
  }
  return (
    <>
      {order.qc?.error && <span className="meta">{order.qc.error}</span>}
      <label className="btn small quiet" style={{ position: "relative" }}>
        Photo de contrôle
        <input type="file" accept="image/*" capture="environment" disabled={busy}
               style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer" }}
               onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) act(order.id, () => api.qc(order.id, f)); }} />
      </label>
      <button className="btn danger small" disabled={busy}
              onClick={() => { const n = prompt("Défaut constaté :") ?? ""; if (n) act(order.id, () => api.reprint(order.id, n)); }}>
        Réimprimer
      </button>
    </>
  );
}

function Printers({ printers, onAdd }: { printers: Board["printers"]; onAdd: (name: string, material: Material) => void }) {
  const [name, setName] = useState("");
  const [material, setMaterial] = useState<Material>("PLA");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) {
      onAdd(name.trim(), material);
      setName("");
    }
  };
  const state = { idle: "libre", printing: "occupée", maintenance: "en maintenance" } as const;
  return (
    <section className="sheet" aria-label="Imprimantes">
      <h2>Imprimantes</h2>
      <div className="printers">
        {printers.length === 0 && <p className="empty">Ajoutez la première imprimante de l'atelier.</p>}
        {printers.map((p) => (
          <span key={p.id} className={p.state === "idle" ? "pill ok" : "pill"}>
            {p.name}, {p.material}, {state[p.state]}{p.order_ref ? ` (${p.order_ref})` : ""}
          </span>
        ))}
      </div>
      <form className="row" onSubmit={submit} style={{ marginTop: "1rem", alignItems: "end" }}>
        <div className="field" style={{ margin: 0 }}>
          <label htmlFor="pr-name">Nom</label>
          <input id="pr-name" type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex. : A1 n° 1" />
        </div>
        <div className="field" style={{ margin: 0 }}>
          <label htmlFor="pr-mat">Matière chargée</label>
          <select id="pr-mat" value={material} onChange={(e) => setMaterial(e.target.value as Material)}>
            {(["PLA", "PETG", "ASA", "TPU"] as Material[]).map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
        <button className="btn" type="submit" disabled={!name.trim()}>Ajouter l'imprimante</button>
      </form>
    </section>
  );
}
