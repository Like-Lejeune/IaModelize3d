import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import Conversation from "../studio/Conversation";
import { OrderPanel, ParamsPanel, VersionsPanel } from "../studio/Panels";
import { useStudio } from "../studio/store";
import Viewer from "../studio/Viewer";

type Side = "params" | "versions" | "order";
type Pane = "chat" | "model" | "side"; // on a phone, one pane at a time

export default function Studio() {
  const { id = "" } = useParams();
  const store = useStudio(id);
  const [side, setSide] = useState<Side>("params");
  const [pane, setPane] = useState<Pane>("chat");
  const d = store.detail;

  if (store.loadError) {
    return (
      <main className="narrow">
        <h1>Projet introuvable</h1>
        <p>{store.loadError}</p>
        <Link to="/">Créer un nouvel objet</Link>
      </main>
    );
  }
  const title = store.build?.meta?.title || d?.title || "Nouvel objet";
  const issues = (store.checks?.issues ?? []).filter((i) => i.severity !== "info");

  return (
    <div className="studio" data-pane={pane}>
      <div className="studio-head">
        <h1>{title}</h1>
        <span className="help">{store.version ? `Version ${store.version}` : "Pas encore de modèle"}</span>
        <div className="studio-tools">
          {store.build && <button type="button" className="btn quiet small" onClick={() => store.exportStl(title)}>Télécharger le STL</button>}
        </div>
      </div>
      <nav className="studio-tabs" aria-label="Volets du studio">
        {(["chat", "model", "side"] as Pane[]).map((p) => (
          <button key={p} type="button" aria-pressed={pane === p} onClick={() => setPane(p)}>
            {p === "chat" ? "Discussion" : p === "model" ? "Modèle 3D" : "Réglages"}
          </button>
        ))}
      </nav>

      <section className="studio-chat" aria-label="Discussion avec l'IA">
        <Conversation store={store} />
      </section>

      <section className="studio-model" aria-label="Modèle 3D">
        <Viewer build={store.build} busy={store.building} />
        {store.buildError && <p className="alert error viewer-alert">Le modèle ne se construit pas : {store.buildError}</p>}
        {issues.length > 0 && (
          <details className="checks">
            <summary>{issues.length} point{issues.length > 1 ? "s" : ""} à surveiller pour l'impression</summary>
            <ul>{issues.slice(0, 8).map((i, n) => <li key={n} className={i.severity}>{i.message}</li>)}</ul>
          </details>
        )}
      </section>

      <aside className="studio-side" aria-label="Réglages, versions et commande">
        <div className="side-tabs" role="tablist">
          {(["params", "versions", "order"] as Side[]).map((s) => (
            <button key={s} role="tab" type="button" aria-selected={side === s} onClick={() => setSide(s)}>
              {s === "params" ? "Réglages" : s === "versions" ? `Versions${store.versions.length ? ` (${store.versions.length})` : ""}` : "Commander"}
            </button>
          ))}
        </div>
        <div className="side-body" role="tabpanel">
          {side === "params" && <ParamsPanel store={store} />}
          {side === "versions" && <VersionsPanel store={store} />}
          {side === "order" && <OrderPanel store={store} title={title} />}
        </div>
      </aside>
    </div>
  );
}
