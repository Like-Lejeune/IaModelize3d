import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import { useSession } from "../App";
import PhotoSheet from "../components/PhotoSheet";
import { useLang } from "../i18n";
import { DELIVERY, MATERIAL, errorText, money } from "../texts";
import type { Delivery, Material } from "../types";

export default function NewRequest() {
  const { tariff } = useSession();
  const { lang, tr } = useLang();
  const navigate = useNavigate();
  const [photos, setPhotos] = useState<File[]>([]);
  const [plate, setPlate] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [appliance, setAppliance] = useState("");
  const [partNumber, setPartNumber] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [material, setMaterial] = useState<Material | "">("");
  const [delivery, setDelivery] = useState<Delivery>("pickup");
  const [contact, setContact] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // one key per form: a double tap or a retry after a dropped connection gets the same order back
  const key = useRef(crypto.randomUUID());

  const empty = photos.length === 0 && !text.trim() && !appliance.trim() && !partNumber.trim();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (empty) {
      setError(errorText(lang, "empty_request", ""));
      return;
    }
    setSending(true);
    setError(null);
    try {
      const o = await api.createRequest(
        { text, appliance, partNumber, quantity, material: material || null, delivery, contact, photos, plate },
        key.current,
      );
      navigate(`/commandes/${o.id}`);
    } catch (err) {
      const a = err as ApiError;
      setError(errorText(lang, a.code ?? "", a.message || tr("La demande n'a pas pu être envoyée. Vérifiez votre connexion et réessayez.", "The request could not be sent. Check your connection and try again.")));
      setSending(false);
    }
  }

  return (
    <main>
      <section className="hero">
        <div>
          <h1>{tr("Une pièce cassée\u00a0? On la refait à l'imprimante 3D.", "A broken part? We make it again on a 3D printer.")}</h1>
          <p>
            {tr(
              "Posez la pièce sur une feuille A4 et prenez-la en photo. L'atelier la mesure, dessine une pièce de remplacement et vous donne un prix avant d'imprimer.",
              "Put the part on an A4 sheet and take a photo. The workshop measures it, draws a replacement and gives you a price before printing.",
            )}
          </p>
        </div>
        <div className="a4" aria-hidden="true">
          <div className="a4-part" />
          <span className="a4-label">210 × 297 mm</span>
        </div>
      </section>

      <section className="sheet" aria-labelledby="how">
        <h2 id="how">{tr("Comment ça marche", "How it works")}</h2>
        <ol className="steps">
          <li><b>{tr("Vous envoyez la photo", "You send the photo")}</b><span>{tr("La pièce posée sur une feuille A4, et la plaque signalétique de l'appareil si vous l'avez.", "The part on an A4 sheet, and the appliance's rating plate if you have it.")}</span></li>
          <li><b>{tr("Vous recevez un prix", "You get a price")}</b><span>{tr("L'atelier vérifie que la pièce peut être imprimée sans danger, puis la conçoit et la chiffre.", "The workshop checks the part can be printed safely, then designs and prices it.")}</span></li>
          <li><b>{tr("Vous payez, on imprime", "You pay, we print")}</b><span>{tr("La pièce est contrôlée aux bonnes cotes, puis livrée ou remise à l'atelier.", "The part is checked against its dimensions, then delivered or handed over at the workshop.")}</span></li>
        </ol>
      </section>

      <form className="sheet narrow" onSubmit={submit} noValidate style={{ marginTop: "1.25rem" }}>
        <h2>{tr("Votre pièce", "Your part")}</h2>
        <PhotoSheet files={photos} onChange={setPhotos} />

        <div className="field" style={{ marginTop: "1.25rem" }}>
          <label htmlFor="text">{tr("Que s'est-il passé\u00a0?", "What happened?")}</label>
          <textarea
            id="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={tr("Ex. : la roulette du panier de mon lave-vaisselle s'est cassée, l'axe est intact.", "E.g. the wheel of my dishwasher basket broke, the axle is fine.")}
          />
          <small>{tr("En quelques mots : la pièce, ce qui a cassé, où elle se trouve dans l'appareil.", "In a few words: the part, what broke, where it sits in the appliance.")}</small>
        </div>

        <div className="row">
          <div className="field">
            <label htmlFor="appliance">{tr("Appareil (marque et modèle)", "Appliance (brand and model)")}</label>
            <input id="appliance" type="text" value={appliance} onChange={(e) => setAppliance(e.target.value)} placeholder={tr("Ex. : Binatone TS-1880", "E.g. Binatone TS-1880")} />
          </div>
          <div className="field">
            <label htmlFor="pn">{tr("Référence de la pièce", "Part number")}</label>
            <input id="pn" type="text" value={partNumber} onChange={(e) => setPartNumber(e.target.value)} placeholder={tr("Si elle est écrite dessus", "If it is written on it")} />
          </div>
        </div>

        <div className="field">
          <label htmlFor="plate">{tr("Photo de la plaque signalétique (facultatif)", "Photo of the rating plate (optional)")}</label>
          <input id="plate" type="file" accept="image/*" onChange={(e) => setPlate(e.target.files?.[0] ?? null)} />
          <small>{tr("L'étiquette avec le modèle exact, souvent derrière ou sous l'appareil.", "The label with the exact model, often on the back or underneath.")}</small>
        </div>

        <div className="row">
          <div className="field">
            <label htmlFor="qty">{tr("Nombre de pièces", "Number of pieces")}</label>
            <input id="qty" type="number" min={1} max={200} value={quantity} onChange={(e) => setQuantity(Math.max(1, Math.min(200, Number(e.target.value) || 1)))} />
          </div>
          <div className="field">
            <label htmlFor="mat">{tr("Matière", "Material")}</label>
            <select id="mat" value={material} onChange={(e) => setMaterial(e.target.value as Material | "")}>
              <option value="">{tr("L'atelier choisit pour moi", "Let the workshop choose")}</option>
              {(Object.keys(MATERIAL[lang]) as Material[]).map((m) => <option key={m} value={m}>{MATERIAL[lang][m]}</option>)}
            </select>
          </div>
        </div>

        <fieldset className="field" style={{ border: 0, padding: 0, margin: "0 0 1.1rem" }}>
          <legend className="legend" style={{ marginBottom: "0.35rem" }}>{tr("Réception", "Receiving the part")}</legend>
          <div className="choices">
            {(Object.keys(DELIVERY[lang]) as Delivery[]).map((d) => (
              <label className="choice" key={d}>
                <input type="radio" name="delivery" value={d} checked={delivery === d} onChange={() => setDelivery(d)} />
                <div>
                  <b>{DELIVERY[lang][d].label}</b>
                  <span>
                    {DELIVERY[lang][d].hint}
                    {tariff && (tariff.delivery[d].price ? `, ${money(lang, tariff.delivery[d].price, tariff.currency)}` : "")}
                  </span>
                </div>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="field">
          <label htmlFor="contact">{tr("Téléphone ou WhatsApp", "Phone or WhatsApp")}</label>
          <input id="contact" type="tel" inputMode="tel" autoComplete="tel" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="+237 6 …" />
          <small>{tr("Pour vous prévenir quand le prix est prêt. Effacé dès la réception de la pièce.", "To tell you when the price is ready. Erased once you receive the part.")}</small>
        </div>

        {error && <p className="alert error" role="alert">{error}</p>}
        <div className="actions">
          <button className="btn" type="submit" disabled={sending}>{sending ? tr("Envoi en cours…", "Sending…") : tr("Envoyer ma demande", "Send my request")}</button>
          <span className="help">{tr("Gratuit et sans engagement : vous ne payez qu'après avoir vu le prix.", "Free and with no commitment: you only pay after seeing the price.")}</span>
        </div>
      </form>
    </main>
  );
}
