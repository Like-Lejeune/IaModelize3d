import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { projects } from "../studio/api";
import { when } from "../fr";

const EXAMPLES = [
  "Un support de téléphone incliné pour mon bureau",
  "Une boîte de rangement de 120 × 80 mm avec un couvercle",
  "Un crochet mural pour accrocher un casque",
  "La molette de mon ventilateur est cassée, je joins une photo",
];

type Mine = Awaited<ReturnType<typeof projects.list>>;

/** "Que voulez-vous créer ?": the request opens a project and its studio, where the designer takes it from there. */
export default function Home() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mine, setMine] = useState<Mine>([]);

  useEffect(() => {
    projects.list().then(setMine).catch(() => setMine([]));
  }, []);

  async function start(e?: FormEvent) {
    e?.preventDefault();
    const t = text.trim();
    if (!t && !files.length) {
      setError("Décrivez l'objet en quelques mots ou joignez une photo.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const p = await projects.create(t.slice(0, 60) || "Nouvel objet");
      const ids: string[] = [];
      for (const f of files) ids.push((await projects.upload(p.id, f)).id);
      await projects.send(p.id, t || "Voici une photo de l'objet à refaire.", ids);
      navigate(`/studio/${p.id}`);
    } catch {
      setError("Le projet n'a pas pu démarrer. Vérifiez votre connexion et réessayez.");
      setBusy(false);
    }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void start();
    }
  };

  return (
    <main className="home">
      <section className="ask-hero">
        <h1>Que voulez-vous créer&nbsp;?</h1>
        <p>Décrivez un objet ou montrez une pièce en photo. L'IA vous pose les bonnes questions, dessine le modèle en 3D, et vous l'ajustez avant de le faire imprimer.</p>
        <form className="prompt" onSubmit={start}>
          <label htmlFor="prompt" className="sr-only">Votre objet</label>
          <textarea id="prompt" rows={3} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
                    placeholder="Ex. : un support pour poser ma tablette en cuisine, incliné à 60°" autoFocus />
          <div className="prompt-bar">
            <label className="btn quiet small attach">
              {files.length ? `${files.length} photo${files.length > 1 ? "s" : ""}` : "Joindre une photo"}
              <input type="file" accept="image/*" multiple onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])].slice(0, 6)); e.target.value = ""; }} />
            </label>
            <button className="btn" type="submit" disabled={busy}>{busy ? "Ouverture du studio…" : "Commencer"}</button>
          </div>
        </form>
        {error && <p className="alert error" role="alert">{error}</p>}
        <div className="examples" aria-label="Exemples">
          {EXAMPLES.map((x) => <button key={x} type="button" className="chip" onClick={() => setText(x)}>{x}</button>)}
        </div>
        <p className="help">Une pièce cassée à refaire à l'identique ? Posez-la sur une feuille A4 pour la photo : l'IA s'en sert comme règle. <Link to="/reparation">Ou passez par le formulaire de réparation.</Link></p>
      </section>

      {mine.length > 0 && (
        <section aria-labelledby="mine">
          <h2 id="mine">Vos créations</h2>
          <ul className="creations">
            {mine.slice(0, 12).map((p) => (
              <li key={p.id}>
                <Link to={`/studio/${p.id}`} className="sheet creation">
                  <span className="cover" style={p.cover ? { backgroundImage: `url(${p.cover})` } : undefined} aria-hidden="true" />
                  <b>{p.title}</b>
                  <span className="help">{p.version ? `Version ${p.version}, ` : ""}{when(p.updated_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
