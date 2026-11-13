// The interface speaks French and English. The language is the one the person picked (kept in this browser), else
// the browser's own when it is English, else French. `tr(fr, en)` puts both wordings side by side where they are used,
// so a screen reads in both languages at a glance; the shared texts (statuses, journal, errors) are in texts.ts.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Lang = "fr" | "en";

const KEY = "iamodelize3d.lang";

function initial(): Lang {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "fr" || saved === "en") return saved;
  } catch {
    /* storage refused (private window): the browser's language decides */
  }
  const nav = (typeof navigator !== "undefined" && (navigator.languages?.[0] || navigator.language)) || "fr";
  return nav.toLowerCase().startsWith("en") ? "en" : "fr";
}

/** The language outside React (the studio's store, which writes its own error lines). */
export let currentLang: Lang = initial();

interface LangState {
  lang: Lang;
  setLang: (l: Lang) => void;
  tr: (fr: string, en: string) => string;
  locale: string;
}

const LangContext = createContext<LangState>({ lang: currentLang, setLang: () => {}, tr: (fr) => fr, locale: "fr-FR" });

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, set] = useState<Lang>(currentLang);
  const setLang = useCallback((l: Lang) => {
    set(l);
    currentLang = l;
    try {
      localStorage.setItem(KEY, l);
    } catch {
      /* not kept: this visit only */
    }
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const value = useMemo<LangState>(
    () => ({ lang, setLang, tr: (fr, en) => (lang === "fr" ? fr : en), locale: lang === "fr" ? "fr-FR" : "en-GB" }),
    [lang, setLang],
  );
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export const useLang = () => useContext(LangContext);

/** The FR / EN switch of the header. */
export function LangSwitch() {
  const { lang, setLang } = useLang();
  return (
    <div className="lang" role="group" aria-label={lang === "fr" ? "Langue" : "Language"}>
      {(["fr", "en"] as Lang[]).map((l) => (
        <button key={l} type="button" aria-pressed={lang === l} onClick={() => setLang(l)} lang={l}
                title={l === "fr" ? "Français" : "English"}>
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
