// The conversation with the designer: what the person said, what the agent says and asks, its working steps
// (folded into one line each), each new version of the model, and a composer that answers the waiting question or
// asks for a change.
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useLang, type Lang } from "../i18n";
import { when } from "../texts";
import type { Item, StudioStore } from "./store";

// the agent's tools, in words a person understands (server/iamodelize3d/agent/tools.py)
const TOOL: Record<Lang, Record<string, string>> = {
  fr: {
    measure: "Mesure la pièce sur la photo",
    fit_to_photo: "Compare le modèle à la photo",
    scene: "Analyse la photo",
    dimensions: "Cherche des cotes standard",
    search: "Recherche sur le web",
    web_search: "Recherche sur le web",
    write_program: "Dessine le modèle",
    edit_program: "Modifie le modèle",
    mesh_write: "Sculpte le modèle",
    mesh_edit: "Retouche le modèle",
    look: "Regarde le modèle sous plusieurs angles",
    grid: "Relève des positions sur l'image",
    collage: "Compare des versions",
    finish: "Vérifications finales",
    probe: "Prépare une pièce test",
    ask_user: "Vous pose une question",
    remember: "Retient une préférence",
  },
  en: {
    measure: "Measures the part on the photo",
    fit_to_photo: "Compares the model with the photo",
    scene: "Looks at the photo",
    dimensions: "Looks up standard dimensions",
    search: "Searches the web",
    web_search: "Searches the web",
    write_program: "Draws the model",
    edit_program: "Changes the model",
    mesh_write: "Sculpts the model",
    mesh_edit: "Touches up the model",
    look: "Looks at the model from several angles",
    grid: "Reads positions on the image",
    collage: "Compares versions",
    finish: "Final checks",
    probe: "Prepares a test piece",
    ask_user: "Asks you a question",
    remember: "Remembers a preference",
  },
};

export default function Conversation({ store }: { store: StudioStore }) {
  const { tr } = useLang();
  const end = useRef<HTMLDivElement>(null);
  const items = store.items;
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [items.length]);

  return (
    <div className="convo">
      <div className="convo-log" aria-live="polite">
        {items.length === 0 && <p className="empty">{tr("Décrivez l'objet à créer : l'IA vous posera les questions utiles, puis dessinera une première version.", "Describe the object to make: the AI will ask the useful questions, then draw a first version.")}</p>}
        {items.map((it) => <Row key={it.key} item={it} store={store} />)}
        {store.working && (
          <div className="convo-working">
            <span className="dot" aria-hidden="true" />
            {store.job?.status === "waiting" ? tr("L'IA attend votre réponse.", "The AI is waiting for your answer.") : store.statusText || tr("L'IA travaille…", "The AI is working…")}
          </div>
        )}
        <div ref={end} />
      </div>
      <Composer store={store} />
    </div>
  );
}

function Row({ item, store }: { item: Item; store: StudioStore }) {
  const { lang, tr } = useLang();
  switch (item.kind) {
    case "user":
      return (
        <div className="msg me">
          {item.previews && item.previews.length > 0 && (
            <div className="msg-photos">{item.previews.map((u) => <img key={u} src={u} alt={tr("Photo envoyée", "Photo sent")} />)}</div>
          )}
          {item.text && <p>{item.text}</p>}
          <time>{when(lang, item.ts)}</time>
        </div>
      );
    case "agent":
      return <div className="msg ai"><p>{item.text}</p></div>;
    case "status":
      return null; // shown live in the "working" line; the steps below carry the history
    case "tool":
      return (
        <div className={`step${item.ok === false ? " failed" : ""}`}>
          <span className="step-mark" aria-hidden="true" />
          <span>{TOOL[lang][item.name] ?? item.title ?? item.name}</span>
          {item.ok === false && item.summary && <small> : {item.summary.slice(0, 140)}</small>}
        </div>
      );
    case "program":
      return (
        <div className="version-card">
          {item.render && <img src={item.render} alt={tr(`Rendu de la version ${item.version}`, `Render of version ${item.version}`)} />}
          <div>
            <b>Version {item.version}</b>
            {item.summary && <p>{item.summary}</p>}
          </div>
        </div>
      );
    case "critic":
      return (
        <div className={`step${item.verdict === "pass" ? "" : " warn"}`}>
          <span className="step-mark" aria-hidden="true" />
          <span>{item.verdict === "pass" ? tr("Relecture indépendante : modèle validé", "Independent review: model approved") : tr("Relecture indépendante : corrections demandées", "Independent review: changes requested")}</span>
        </div>
      );
    case "ask":
      return <Ask item={item} store={store} />;
    case "error":
      return <p className="alert error" role="alert">{item.text}</p>;
  }
}

function Ask({ item, store }: { item: Extract<Item, { kind: "ask" }>; store: StudioStore }) {
  const { tr } = useLang();
  return (
    <div className={`ask${item.answered ? " done" : ""}`}>
      <p className="ask-q">{item.question}</p>
      {item.answered ? (
        <p className="ask-a">{item.answered === "—" ? tr("Sans réponse", "No answer") : `${tr("Votre réponse :", "Your answer:")} ${item.answered}`}</p>
      ) : (
        <>
          {item.options.length > 0 && (
            <div className="ask-options">
              {item.options.map((o) => <button key={o} type="button" className="btn quiet small" onClick={() => store.answer(item, o)}>{o}</button>)}
            </div>
          )}
          {item.allowText && <p className="help">{tr("Ou répondez avec vos mots ci-dessous.", "Or answer in your own words below.")}</p>}
        </>
      )}
    </div>
  );
}

function Composer({ store }: { store: StudioStore }) {
  const { tr } = useLang();
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const ask = store.waitingAnswer;
  const busy = store.sending || (store.working && !ask);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if ((!t && !files.length) || busy) return;
    void store.send(t, files);
    setText("");
    setFiles([]);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form className="composer" onSubmit={submit}>
      {files.length > 0 && <p className="help">{files.length} photo{files.length > 1 ? "s" : ""} {tr(`jointe${files.length > 1 ? "s" : ""}`, "attached")}</p>}
      <label htmlFor="composer" className="sr-only">{tr("Message à l'IA", "Message to the AI")}</label>
      <textarea
        id="composer"
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        placeholder={ask ? tr("Votre réponse…", "Your answer…") : store.version ? tr("Demandez une modification : plus haut, un trou de 5 mm, des coins arrondis…", "Ask for a change: taller, a 5 mm hole, rounded corners…") : tr("Décrivez l'objet à créer…", "Describe the object to make…")}
      />
      <div className="composer-bar">
        <label className="btn quiet small attach">
          {tr("Photo", "Photo")}
          <input type="file" accept="image/*" multiple onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])].slice(0, 6)); e.target.value = ""; }} />
        </label>
        {store.working && !ask ? (
          <button type="button" className="btn danger small" disabled={store.stopping} onClick={() => store.cancel()}>
            {store.stopping ? tr("Arrêt…", "Stopping…") : tr("Arrêter l'IA", "Stop the AI")}
          </button>
        ) : (
          <button type="submit" className="btn small" disabled={busy || (!text.trim() && !files.length)}>
            {ask ? tr("Répondre", "Answer") : tr("Envoyer", "Send")}
          </button>
        )}
      </div>
    </form>
  );
}
