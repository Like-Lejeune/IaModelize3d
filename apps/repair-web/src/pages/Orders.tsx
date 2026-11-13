import { Link } from "react-router-dom";
import { api } from "../api";
import { STATUS } from "../fr";
import { usePolled } from "../hooks";
import type { Order, Status } from "../types";

const ACT: Status[] = ["needs_info", "quoted", "shipped"]; // the customer has something to do
const OFF: Status[] = ["refused", "cancelled", "expired"];

export function statusClass(s: Status): string {
  if (ACT.includes(s)) return "pill act";
  if (s === "delivered") return "pill ok";
  if (OFF.includes(s)) return "pill off";
  return "pill";
}

export function orderTitle(o: Order): string {
  return o.title_fr || o.title || "Pièce détachée";
}

export default function Orders() {
  const { data, error } = usePolled(() => api.orders(), 8000);

  return (
    <main className="narrow">
      <h1>Mes commandes</h1>
      {error && <p className="alert error" role="alert">Les commandes n'ont pas pu être chargées. Vérifiez votre connexion.</p>}
      {data && data.length === 0 && (
        <div className="sheet">
          <p>Vous n'avez pas encore de commande sur cet appareil.</p>
          <Link className="btn" to="/">Faire une demande</Link>
        </div>
      )}
      {data && data.length > 0 && (
        <ul className="orders">
          {data.map((o) => (
            <li key={o.id}>
              <Link className="sheet order-link" to={`/commandes/${o.id}`}>
                <span className="cover" style={o.project.cover ? { backgroundImage: `url(${o.project.cover})` } : undefined} aria-hidden="true" />
                <span>
                  <h3>{orderTitle(o)}</h3>
                  <span className="ref">{o.ref}, {o.quantity} pièce{o.quantity > 1 ? "s" : ""}</span>
                </span>
                <span className={statusClass(o.status)}>{STATUS[o.status]}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
