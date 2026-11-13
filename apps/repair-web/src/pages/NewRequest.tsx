import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import { useSession } from "../App";
import PhotoSheet from "../components/PhotoSheet";
import { DELIVERY, MATERIAL, errorText, money } from "../fr";
import type { Delivery, Material } from "../types";

export default function NewRequest() {
  const { tariff } = useSession();
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
      setError(errorText("empty_request", ""));
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
      setError(errorText(a.code ?? "", a.message || "La demande n'a pas pu être envoyée. Vérifiez votre connexion et réessayez."));
      setSending(false);
    }
  }

  return (
    <main>
      <section className="hero">
        <div>
          <h1>Une pièce cassée ? On la refait à l'imprimante 3D.</h1>
          <p>
            Posez la pièce sur une feuille A4 et prenez-la en photo. L'atelier la mesure, dessine une pièce de remplacement et
            vous donne un prix avant d'imprimer.
          </p>
        </div>
        <div className="a4" aria-hidden="true">
          <div className="a4-part" />
          <span className="a4-label">210 × 297 mm</span>
        </div>
      </section>

      <section className="sheet" aria-labelledby="how">
        <h2 id="how">Comment ça marche</h2>
        <ol className="steps">
          <li><b>Vous envoyez la photo</b><span>La pièce posée sur une feuille A4, et la plaque signalétique de l'appareil si vous l'avez.</span></li>
          <li><b>Vous recevez un prix</b><span>L'atelier vérifie que la pièce peut être imprimée sans danger, puis la conçoit et la chiffre.</span></li>
          <li><b>Vous payez, on imprime</b><span>La pièce est contrôlée aux bonnes cotes, puis livrée ou remise à l'atelier.</span></li>
        </ol>
      </section>

      <form className="sheet narrow" onSubmit={submit} noValidate style={{ marginTop: "1.25rem" }}>
        <h2>Votre pièce</h2>
        <PhotoSheet files={photos} onChange={setPhotos} />

        <div className="field" style={{ marginTop: "1.25rem" }}>
          <label htmlFor="text">Que s'est-il passé ?</label>
          <textarea
            id="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Ex. : la roulette du panier de mon lave-vaisselle s'est cassée, l'axe est intact."
          />
          <small>En quelques mots : la pièce, ce qui a cassé, où elle se trouve dans l'appareil.</small>
        </div>

        <div className="row">
          <div className="field">
            <label htmlFor="appliance">Appareil (marque et modèle)</label>
            <input id="appliance" type="text" value={appliance} onChange={(e) => setAppliance(e.target.value)} placeholder="Ex. : Binatone TS-1880" />
          </div>
          <div className="field">
            <label htmlFor="pn">Référence de la pièce</label>
            <input id="pn" type="text" value={partNumber} onChange={(e) => setPartNumber(e.target.value)} placeholder="Si elle est écrite dessus" />
          </div>
        </div>

        <div className="field">
          <label htmlFor="plate">Photo de la plaque signalétique (facultatif)</label>
          <input id="plate" type="file" accept="image/*" onChange={(e) => setPlate(e.target.files?.[0] ?? null)} />
          <small>L'étiquette avec le modèle exact, souvent derrière ou sous l'appareil.</small>
        </div>

        <div className="row">
          <div className="field">
            <label htmlFor="qty">Nombre de pièces</label>
            <input id="qty" type="number" min={1} max={200} value={quantity} onChange={(e) => setQuantity(Math.max(1, Math.min(200, Number(e.target.value) || 1)))} />
          </div>
          <div className="field">
            <label htmlFor="mat">Matière</label>
            <select id="mat" value={material} onChange={(e) => setMaterial(e.target.value as Material | "")}>
              <option value="">L'atelier choisit pour moi</option>
              {(Object.keys(MATERIAL) as Material[]).map((m) => <option key={m} value={m}>{MATERIAL[m]}</option>)}
            </select>
          </div>
        </div>

        <fieldset className="field" style={{ border: 0, padding: 0, margin: "0 0 1.1rem" }}>
          <legend className="legend" style={{ marginBottom: "0.35rem" }}>Réception</legend>
          <div className="choices">
            {(Object.keys(DELIVERY) as Delivery[]).map((d) => (
              <label className="choice" key={d}>
                <input type="radio" name="delivery" value={d} checked={delivery === d} onChange={() => setDelivery(d)} />
                <div>
                  <b>{DELIVERY[d].label}</b>
                  <span>
                    {DELIVERY[d].hint}
                    {tariff && (tariff.delivery[d].price ? `, ${money(tariff.delivery[d].price, tariff.currency)}` : "")}
                  </span>
                </div>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="field">
          <label htmlFor="contact">Téléphone ou WhatsApp</label>
          <input id="contact" type="tel" inputMode="tel" autoComplete="tel" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="+237 6 …" />
          <small>Pour vous prévenir quand le prix est prêt. Effacé dès la réception de la pièce.</small>
        </div>

        {error && <p className="alert error" role="alert">{error}</p>}
        <div className="actions">
          <button className="btn" type="submit" disabled={sending}>{sending ? "Envoi en cours…" : "Envoyer ma demande"}</button>
          <span className="help">Gratuit et sans engagement : vous ne payez qu'après avoir vu le prix.</span>
        </div>
      </form>
    </main>
  );
}
