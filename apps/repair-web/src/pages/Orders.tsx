import { Link } from "react-router-dom";
import { api } from "../api";
import { useLang } from "../i18n";
import { STATUS, orderTitle } from "../texts";
import { usePolled } from "../hooks";
import type { Status } from "../types";

const ACT: Status[] = ["needs_info", "quoted", "shipped"]; // the customer has something to do
const OFF: Status[] = ["refused", "cancelled", "expired"];

export function statusClass(s: Status): string {
  if (ACT.includes(s)) return "pill act";
  if (s === "delivered") return "pill ok";
  if (OFF.includes(s)) return "pill off";
  return "pill";
}

export default function Orders() {
  const { lang, tr } = useLang();
  const { data, error } = usePolled(() => api.orders(), 8000);

  return (
    <main className="narrow">
      <h1>{tr("Mes commandes", "My orders")}</h1>
      {error && <p className="alert error" role="alert">{tr("Les commandes n'ont pas pu être chargées. Vérifiez votre connexion.", "The orders could not be loaded. Check your connection.")}</p>}
      {data && data.length === 0 && (
        <div className="sheet">
          <p>{tr("Vous n'avez pas encore de commande sur cet appareil.", "You have no order on this device yet.")}</p>
          <Link className="btn" to="/">{tr("Faire une demande", "Make a request")}</Link>
        </div>
      )}
      {data && data.length > 0 && (
        <ul className="orders">
          {data.map((o) => (
            <li key={o.id}>
              <Link className="sheet order-link" to={`/commandes/${o.id}`}>
                <span className="cover" style={o.project.cover ? { backgroundImage: `url(${o.project.cover})` } : undefined} aria-hidden="true" />
                <span>
                  <h3>{orderTitle(lang, o)}</h3>
                  <span className="ref">{o.ref}, {o.quantity} {tr("pièce", "piece")}{o.quantity > 1 ? "s" : ""}</span>
                </span>
                <span className={statusClass(o.status)}>{STATUS[lang][o.status]}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
