import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useLang } from "../i18n";
import { projects } from "../studio/api";
import { when } from "../texts";

const EXAMPLES = {
  fr: [
    "Un support de téléphone incliné pour mon bureau",
    "Une boîte de rangement de 120 × 80 mm avec un couvercle",
    "Un crochet mural pour accrocher un casque",
    "La molette de mon ventilateur est cassée, je joins une photo",
  ],
  en: [
    "A tilted phone stand for my desk",
    "A 120 × 80 mm storage box with a lid",
    "A wall hook to hang a headset",
    "The knob of my fan is broken, here is a photo",
  ],
};

type Mine = Awaited<ReturnType<typeof projects.list>>;

/** "Que voulez-vous créer ?": the request opens a project and its studio, where the designer takes it from there. */
export default function Home() {
  const { lang, tr } = useLang();
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
      setError(tr("Décrivez l'objet en quelques mots ou joignez une photo.", "Describe the object in a few words or attach a photo."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const p = await projects.create(t.slice(0, 60) || tr("Nouvel objet", "New object"));
      const ids: string[] = [];
      for (const f of files) ids.push((await projects.upload(p.id, f)).id);
      await projects.send(p.id, t || tr("Voici une photo de l'objet à refaire.", "Here is a photo of the object to make again."), ids);
      navigate(`/studio/${p.id}`);
    } catch {
      setError(tr("Le projet n'a pas pu démarrer. Vérifiez votre connexion et réessayez.", "The project could not start. Check your connection and try again."));
      setBusy(false);
    }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void start();
    }
  };

  const photos = files.length;
  return (
    <main className="home">
      <section className="ask-hero">
        <h1>{tr("Que voulez-vous créer ?", "What do you want to make?")}</h1>
        <p>
          {tr(
            "Décrivez un objet ou montrez une pièce en photo. L'IA vous pose les bonnes questions, dessine le modèle en 3D, et vous l'ajustez avant de le faire imprimer.",
            "Describe an object or show a part in a photo. The AI asks the right questions, draws the 3D model, and you adjust it before having it printed.",
          )}
        </p>
        <form className="prompt" onSubmit={start}>
          <label htmlFor="prompt" className="sr-only">{tr("Votre objet", "Your object")}</label>
          <textarea id="prompt" rows={3} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} autoFocus
                    placeholder={tr("Ex. : un support pour poser ma tablette en cuisine, incliné à 60°", "E.g. a stand to hold my tablet in the kitchen, tilted at 60°")} />
          <div className="prompt-bar">
            <label className="btn quiet small attach">
              {photos ? `${photos} photo${photos > 1 ? "s" : ""}` : tr("Joindre une photo", "Attach a photo")}
              <input type="file" accept="image/*" multiple onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])].slice(0, 6)); e.target.value = ""; }} />
            </label>
            <button className="btn" type="submit" disabled={busy}>{busy ? tr("Ouverture du studio…", "Opening the studio…") : tr("Commencer", "Start")}</button>
          </div>
        </form>
        {error && <p className="alert error" role="alert">{error}</p>}
        <div className="examples" aria-label={tr("Exemples", "Examples")}>
          {EXAMPLES[lang].map((x) => <button key={x} type="button" className="chip" onClick={() => setText(x)}>{x}</button>)}
        </div>
        <p className="help">
          {tr(
            "Une pièce cassée à refaire à l'identique ? Posez-la sur une feuille A4 pour la photo : l'IA s'en sert comme règle. ",
            "A broken part to make again exactly? Put it on an A4 sheet for the photo: the AI uses it as a ruler. ",
          )}
          <Link to="/reparation">{tr("Ou passez par le formulaire de réparation.", "Or use the repair form.")}</Link>
        </p>
      </section>

      {mine.length > 0 && (
        <section aria-labelledby="mine">
          <h2 id="mine">{tr("Vos créations", "Your creations")}</h2>
          <ul className="creations">
            {mine.slice(0, 12).map((p) => (
              <li key={p.id}>
                <Link to={`/studio/${p.id}`} className="sheet creation">
                  <span className="cover" style={p.cover ? { backgroundImage: `url(${p.cover})` } : undefined} aria-hidden="true" />
                  <b>{p.title}</b>
                  <span className="help">{p.version ? `Version ${p.version}, ` : ""}{when(lang, p.updated_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
