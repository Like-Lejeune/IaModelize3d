// The studio's side panels: the parameters the agent exposed (each with its range, unit and where the number comes
// from), the versions, and the order form that sends the current version to the workshop's price.
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useSession } from "../App";
import { useLang, type Lang } from "../i18n";
import { DELIVERY, MATERIAL, errorText, money, when } from "../texts";
import type { ParamSpec } from "../geom/types";
import type { Delivery, Material } from "../types";
import type { StudioStore } from "./store";

const SOURCE: Record<Lang, Record<string, string>> = {
  fr: {
    caliper: "mesuré au pied à coulisse",
    photo: "mesuré sur la photo",
    measured: "mesuré",
    user: "donné par vous",
    standard: "valeur standard",
    spec: "fiche technique",
    design: "choix de conception",
    assumed: "supposé",
  },
  en: {
    caliper: "measured with a caliper",
    photo: "measured on the photo",
    measured: "measured",
    user: "given by you",
    standard: "standard value",
    spec: "datasheet",
    design: "design choice",
    assumed: "assumed",
  },
};

export function ParamsPanel({ store }: { store: StudioStore }) {
  const { lang, tr } = useLang();
  const entries = Object.entries(store.specs).filter(([, s]) => !s.hidden);
  if (!store.build) return <p className="empty">{tr("Les réglages apparaîtront avec la première version du modèle.", "Settings will show up with the model's first version.")}</p>;
  if (!entries.length) return <p className="empty">{tr("Ce modèle n'a pas de réglage. Demandez une modification à l'IA.", "This model has no settings. Ask the AI for a change.")}</p>;
  const groups = new Map<string, [string, ParamSpec][]>();
  for (const e of entries) {
    const g = (lang === "en" && e[1].group_en) || e[1].group || "";
    groups.set(g, [...(groups.get(g) ?? []), e]);
  }
  return (
    <div className="params">
      {[...groups].map(([g, list]) => (
        <fieldset key={g || "main"} className="param-group">
          {g && <legend>{g}</legend>}
          {list.map(([name, spec]) => <Param key={name} name={name} spec={spec} value={store.values[name] ?? spec.value} store={store} />)}
        </fieldset>
      ))}
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button type="button" className="btn quiet small" onClick={() => store.resetParams()}>{tr("Revenir aux valeurs de l'IA", "Back to the AI's values")}</button>
        <span className="help">{store.saving ? tr("Enregistrement…", "Saving…") : store.saveError ? store.saveError : tr(`Version ${store.version} enregistrée`, `Version ${store.version} saved`)}</span>
      </div>
    </div>
  );
}

function Param({ name, spec, value, store }: { name: string; spec: ParamSpec; value: any; store: StudioStore }) {
  const { lang, tr } = useLang();
  const label = (lang === "en" && spec.label_en) || spec.label || name.replace(/_/g, " ");
  const id = `p-${name}`;
  const src = spec.source ? SOURCE[lang][spec.source] ?? spec.source : null;
  const kind = spec.kind ?? (typeof spec.value === "boolean" ? "bool" : typeof spec.value === "string" ? "choice" : "number");

  if (kind === "bool") {
    return (
      <label className="param check">
        <input type="checkbox" checked={!!value} onChange={(e) => store.setParam(name, e.target.checked, true)} />
        <span>{label}</span>
      </label>
    );
  }
  if (kind === "choice" && spec.options) {
    return (
      <div className="param">
        <label htmlFor={id}>{label}</label>
        <select id={id} value={String(value)} onChange={(e) => store.setParam(name, e.target.value, true)}>
          {spec.options.map((o) => <option key={o}>{o}</option>)}
        </select>
      </div>
    );
  }
  const min = spec.min ?? 0;
  const max = spec.max ?? Math.max(Number(spec.value) * 3, 10);
  const step = spec.step ?? (kind === "int" ? 1 : 0.1);
  const n = Number(value);
  return (
    <div className="param">
      <div className="param-head">
        <label htmlFor={id}>{label}</label>
        <span className="param-value">
          <input
            type="number" aria-label={`${label}, ${tr("valeur", "value")}`} value={Number.isFinite(n) ? n : ""} min={min} max={max} step={step}
            onChange={(e) => store.setParam(name, clamp(Number(e.target.value), min, max), false)}
            onBlur={(e) => store.setParam(name, clamp(Number(e.target.value), min, max), true)}
          />
          {spec.unit && <span>{spec.unit}</span>}
        </span>
      </div>
      <input
        id={id} type="range" min={min} max={max} step={step} value={Number.isFinite(n) ? n : min}
        onChange={(e) => store.setParam(name, Number(e.target.value), false)}
        onPointerUp={(e) => store.setParam(name, Number((e.target as HTMLInputElement).value), true)}
        onKeyUp={(e) => store.setParam(name, Number((e.target as HTMLInputElement).value), true)}
      />
      {src && <small className="param-src">{src}</small>}
    </div>
  );
}

const clamp = (v: number, lo: number, hi: number) => (Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo);

export function VersionsPanel({ store }: { store: StudioStore }) {
  const { lang, tr } = useLang();
  const [busy, setBusy] = useState<number | null>(null);
  if (!store.versions.length) return <p className="empty">{tr("Aucune version pour l'instant.", "No version yet.")}</p>;
  return (
    <ol className="versions" reversed>
      {[...store.versions].reverse().map((v) => (
        <li key={v.version} className={v.version === store.version ? "current" : ""}>
          <div>
            <b>Version {v.version}</b> <span className="help">{v.author === "user" ? tr("vos réglages", "your settings") : v.author === "agent" ? tr("par l'IA", "by the AI") : v.author}, {when(lang, v.created_at)}</span>
            {v.summary && <p>{translateSummary(lang, v.summary)}</p>}
          </div>
          {v.version !== store.version && (
            <button type="button" className="btn quiet small" disabled={busy !== null || store.working}
                    onClick={async () => { setBusy(v.version); try { await store.restore(v.version); } finally { setBusy(null); } }}>
              {busy === v.version ? tr("Restauration…", "Restoring…") : tr("Revenir à celle-ci", "Go back to this one")}
            </button>
          )}
        </li>
      ))}
    </ol>
  );
}

function translateSummary(lang: Lang, s: string): string {
  if (lang === "en") return s;
  if (s === "parameters changed") return "Réglages modifiés";
  if (s === "edited in the studio") return "Modifiée dans le studio";
  return s;
}

export function OrderPanel({ store, title }: { store: StudioStore; title: string }) {
  const { tariff } = useSession();
  const { lang, tr } = useLang();
  const navigate = useNavigate();
  const [quantity, setQuantity] = useState(1);
  const [material, setMaterial] = useState<Material>("PLA");
  const [delivery, setDelivery] = useState<Delivery>("pickup");
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errors = (store.checks?.issues ?? []).filter((i) => i.severity === "error");
  const stats = store.checks?.stats;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.set("project_id", store.id);
      form.set("text", title);
      form.set("quantity", String(quantity));
      form.set("material", material);
      form.set("delivery", delivery);
      form.set("contact", contact);
      const res = await fetch("/api/shop/requests", { method: "POST", body: form, credentials: "same-origin", headers: { "Idempotency-Key": `${store.id}-v${store.version}-${quantity}-${material}-${delivery}` } });
      const body = await res.json();
      if (!res.ok) {
        const inner = typeof body?.detail === "object" ? body.detail : body;
        throw new ApiError(res.status, inner?.code ?? "", inner?.detail ?? tr("La commande n'a pas pu être créée.", "The order could not be created."));
      }
      navigate(`/commandes/${body.id}`);
    } catch (err) {
      const a = err as ApiError;
      setError(errorText(lang, a.code, a.message));
      setBusy(false);
    }
  }

  if (!store.build) return <p className="empty">{tr("Le modèle doit exister avant d'être commandé.", "The model must exist before it can be ordered.")}</p>;
  return (
    <form onSubmit={submit}>
      <p>{tr(
        `L'atelier imprime la version ${store.version}, la contrôle et vous la remet. Le prix exact arrive après le calcul d'impression.`,
        `The workshop prints version ${store.version}, checks it and hands it to you. The exact price comes after the print is worked out.`,
      )}</p>
      {stats?.estGrams != null && (
        <p className="help">{tr(
          `Environ ${Math.round(Number(stats.estGrams))} g de matière par pièce${stats.estMinutes ? ` et ${Math.round(Number(stats.estMinutes))} min d'impression` : ""}.`,
          `About ${Math.round(Number(stats.estGrams))} g of material per piece${stats.estMinutes ? ` and ${Math.round(Number(stats.estMinutes))} min of printing` : ""}.`,
        )}</p>
      )}
      {errors.length > 0 && <p className="alert warn">{tr(
        `Le modèle a ${errors.length} problème${errors.length > 1 ? "s" : ""} d'impression. Demandez à l'IA de les corriger avant de commander.`,
        `The model has ${errors.length} printing problem${errors.length > 1 ? "s" : ""}. Ask the AI to fix them before ordering.`,
      )}</p>}
      <div className="row">
        <div className="field">
          <label htmlFor="o-qty">{tr("Nombre de pièces", "Number of pieces")}</label>
          <input id="o-qty" type="number" min={1} max={200} value={quantity} onChange={(e) => setQuantity(Math.max(1, Math.min(200, Number(e.target.value) || 1)))} />
        </div>
        <div className="field">
          <label htmlFor="o-mat">{tr("Matière", "Material")}</label>
          <select id="o-mat" value={material} onChange={(e) => setMaterial(e.target.value as Material)}>
            {(Object.keys(MATERIAL[lang]) as Material[]).map((m) => <option key={m} value={m}>{MATERIAL[lang][m]}</option>)}
          </select>
        </div>
      </div>
      <div className="field">
        <label htmlFor="o-del">{tr("Réception", "Delivery")}</label>
        <select id="o-del" value={delivery} onChange={(e) => setDelivery(e.target.value as Delivery)}>
          {(Object.keys(DELIVERY[lang]) as Delivery[]).map((d) => (
            <option key={d} value={d}>{DELIVERY[lang][d].label}{tariff?.delivery[d].price ? `, ${money(lang, tariff.delivery[d].price, tariff.currency)}` : ""}</option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="o-contact">{tr("Téléphone ou WhatsApp", "Phone or WhatsApp")}</label>
        <input id="o-contact" type="tel" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="+237 6 …" />
      </div>
      {error && <p className="alert error" role="alert">{error}</p>}
      <button className="btn" type="submit" disabled={busy || store.working || errors.length > 0}>{busy ? tr("Calcul du prix…", "Working out the price…") : tr("Demander le prix", "Ask for the price")}</button>
    </form>
  );
}
