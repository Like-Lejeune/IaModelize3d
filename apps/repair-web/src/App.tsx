import { createContext, lazy, Suspense, useContext, useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import type { Me, Tariff } from "./types";
import Home from "./pages/Home";
import NewRequest from "./pages/NewRequest";
import Orders from "./pages/Orders";
import OrderPage from "./pages/OrderPage";
import Workshop from "./pages/Workshop";

// the studio brings three.js and the geometry worker: loaded when a studio opens
const Studio = lazy(() => import("./pages/Studio"));

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
            Atelier 3D
          </NavLink>
          <nav aria-label="Navigation principale">
            <NavLink to="/" end>Créer</NavLink>
            <NavLink to="/commandes">Mes commandes</NavLink>
            {session.me?.is_operator && <NavLink to="/ops">Atelier</NavLink>}
          </nav>
        </div>
      </header>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/studio/:id" element={<Suspense fallback={<main><p className="empty">Ouverture du studio…</p></main>}><Studio /></Suspense>} />
        <Route path="/reparation" element={<NewRequest />} />
        <Route path="/commandes" element={<Orders />} />
        <Route path="/commandes/:id" element={<OrderPage />} />
        {/* /ops: where the API's operator sign-in link lands (scripts/shop_operator.py) */}
        <Route path="/ops" element={<Workshop />} />
        <Route path="*" element={<main className="narrow"><h1>Page introuvable</h1><p><NavLink to="/">Revenir à l'accueil</NavLink></p></main>} />
      </Routes>
    </SessionContext.Provider>
  );
}
