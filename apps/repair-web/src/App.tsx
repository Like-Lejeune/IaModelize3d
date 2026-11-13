import { createContext, lazy, Suspense, useContext, useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { LangProvider, LangSwitch, useLang } from "./i18n";
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
  return (
    <LangProvider>
      <Shell />
    </LangProvider>
  );
}

function Shell() {
  const { tr } = useLang();
  const [session, setSession] = useState<Session>({ me: null, tariff: null });

  useEffect(() => {
    // /me first: it sets the session cookie that every later call carries
    api.me()
      .then(async (me) => setSession({ me, tariff: await api.tariff() }))
      .catch(() => setSession({ me: null, tariff: null }));
  }, []);

  useEffect(() => {
    document.title = tr("IaModelize3d — décrivez, ajustez, imprimez", "IaModelize3d — describe, adjust, print");
  }, [tr]);

  return (
    <SessionContext.Provider value={session}>
      <header className="bar">
        <div className="bar-inner">
          <NavLink to="/" className="brand" end>
            <span className="brand-mark" aria-hidden="true" />
            IaModelize3d
          </NavLink>
          <nav aria-label={tr("Navigation principale", "Main navigation")}>
            <NavLink to="/" end>{tr("Créer", "Create")}</NavLink>
            <NavLink to="/commandes">{tr("Mes commandes", "My orders")}</NavLink>
            {session.me?.is_operator && <NavLink to="/ops">{tr("Atelier", "Workshop")}</NavLink>}
          </nav>
          <LangSwitch />
        </div>
      </header>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/studio/:id" element={<Suspense fallback={<main><p className="empty">{tr("Ouverture du studio…", "Opening the studio…")}</p></main>}><Studio /></Suspense>} />
        <Route path="/reparation" element={<NewRequest />} />
        <Route path="/commandes" element={<Orders />} />
        <Route path="/commandes/:id" element={<OrderPage />} />
        {/* /ops: where the API's operator sign-in link lands (scripts/shop_operator.py) */}
        <Route path="/ops" element={<Workshop />} />
        <Route path="*" element={
          <main className="narrow">
            <h1>{tr("Page introuvable", "Page not found")}</h1>
            <p><NavLink to="/">{tr("Revenir à l'accueil", "Back to the home page")}</NavLink></p>
          </main>
        } />
      </Routes>
    </SessionContext.Provider>
  );
}
