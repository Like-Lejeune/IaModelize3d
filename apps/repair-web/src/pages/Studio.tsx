import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import Conversation from "../studio/Conversation";
import { OrderPanel, ParamsPanel, VersionsPanel } from "../studio/Panels";
import { useLang } from "../i18n";
import { useStudio } from "../studio/store";
import Viewer from "../studio/Viewer";

type Side = "params" | "versions" | "order";
type Pane = "chat" | "model" | "side"; // on a phone, one pane at a time

export default function Studio() {
  const { tr } = useLang();
  const { id = "" } = useParams();
  const store = useStudio(id);
  const [side, setSide] = useState<Side>("params");
  const [pane, setPane] = useState<Pane>("chat");
  const d = store.detail;

  if (store.loadError) {
    return (
      <main className="narrow">
        <h1>{tr("Projet introuvable", "Project not found")}</h1>
        <p>{store.loadError}</p>
        <Link to="/">{tr("Créer un nouvel objet", "Create a new object")}</Link>
      </main>
    );
  }
  const title = store.build?.meta?.title || d?.title || tr("Nouvel objet", "New object");
  const issues = (store.checks?.issues ?? []).filter((i) => i.severity !== "info");

  return (
    <div className="studio" data-pane={pane}>
      <div className="studio-head">
        <h1>{title}</h1>
        <span className="help">{store.version ? `Version ${store.version}` : tr("Pas encore de modèle", "No model yet")}</span>
        <div className="studio-tools">
          {store.build && <button type="button" className="btn quiet small" onClick={() => store.exportStl(title)}>{tr("Télécharger le STL", "Download the STL")}</button>}
        </div>
      </div>
      <nav className="studio-tabs" aria-label={tr("Volets du studio", "Studio panes")}>
        {(["chat", "model", "side"] as Pane[]).map((p) => (
          <button key={p} type="button" aria-pressed={pane === p} onClick={() => setPane(p)}>
            {p === "chat" ? tr("Discussion", "Chat") : p === "model" ? tr("Modèle 3D", "3D model") : tr("Réglages", "Settings")}
          </button>
        ))}
      </nav>

      <section className="studio-chat" aria-label={tr("Discussion avec l'IA", "Chat with the AI")}>
        <Conversation store={store} />
      </section>

      <section className="studio-model" aria-label={tr("Modèle 3D", "3D model")}>
        <Viewer build={store.build} busy={store.building} />
        {store.buildError && <p className="alert error viewer-alert">{tr("Le modèle ne se construit pas :", "The model does not build:")} {store.buildError}</p>}
        {issues.length > 0 && (
          <details className="checks">
            <summary>{tr(`${issues.length} point${issues.length > 1 ? "s" : ""} à surveiller pour l'impression`, `${issues.length} thing${issues.length > 1 ? "s" : ""} to watch for printing`)}</summary>
            <ul>{issues.slice(0, 8).map((i, n) => <li key={n} className={i.severity}>{i.message}</li>)}</ul>
          </details>
        )}
      </section>

      <aside className="studio-side" aria-label={tr("Réglages, versions et commande", "Settings, versions and order")}>
        <div className="side-tabs" role="tablist">
          {(["params", "versions", "order"] as Side[]).map((s) => (
            <button key={s} role="tab" type="button" aria-selected={side === s} onClick={() => setSide(s)}>
              {s === "params" ? tr("Réglages", "Settings") : s === "versions" ? `Versions${store.versions.length ? ` (${store.versions.length})` : ""}` : tr("Commander", "Order")}
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
