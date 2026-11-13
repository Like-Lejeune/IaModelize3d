import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import type { Me, Tariff } from "./types";
import NewRequest from "./pages/NewRequest";
import Orders from "./pages/Orders";
import OrderPage from "./pages/OrderPage";
import Workshop from "./pages/Workshop";

interface Session {
  me: Me | null;
  tariff: Tariff | null;
}

const SessionContext = createContext<Session>({ me: null, tariff: null });
export const useSession = () => useContext(SessionContext);

export default function App() {
  const [session, setSession] = useState<Session>({ me: null, tariff: null });

  useEffect(() => {
    // /me first: it sets the session cookie that every later call carries
    api.me()
      .then(async (me) => setSession({ me, tariff: await api.tariff() }))
      .catch(() => setSession({ me: null, tariff: null }));
  }, []);

  return (
    <SessionContext.Provider value={session}>
      <header className="bar">
        <div className="bar-inner">
          <NavLink to="/" className="brand" end>
            <span className="brand-mark" aria-hidden="true" />
            Réparation
          </NavLink>
          <nav aria-label="Navigation principale">
            <NavLink to="/" end>Nouvelle demande</NavLink>
            <NavLink to="/commandes">Mes commandes</NavLink>
            {session.me?.is_operator && <NavLink to="/ops">Atelier</NavLink>}
          </nav>
        </div>
      </header>
      <Routes>
        <Route path="/" element={<NewRequest />} />
        <Route path="/commandes" element={<Orders />} />
        <Route path="/commandes/:id" element={<OrderPage />} />
        {/* /ops: where the API's operator sign-in link lands (scripts/shop_operator.py) */}
        <Route path="/ops" element={<Workshop />} />
        <Route path="*" element={<main className="narrow"><h1>Page introuvable</h1><p><NavLink to="/">Revenir à l'accueil</NavLink></p></main>} />
      </Routes>
    </SessionContext.Provider>
  );
}
