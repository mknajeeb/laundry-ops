/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { TRANSLATIONS } from "./translations";

const STORAGE_KEY = "washpro_locale";

function readStoredLocale() {
  try {
    const a = localStorage.getItem(STORAGE_KEY);
    if (a === "es" || a === "en") return a;
  } catch {
    /* quota / private mode */
  }
  try {
    const b = sessionStorage.getItem(STORAGE_KEY);
    if (b === "es" || b === "en") return b;
  } catch {
    /* ignore */
  }
  if (typeof navigator !== "undefined" && navigator.language) {
    return String(navigator.language).toLowerCase().startsWith("es") ? "es" : "en";
  }
  return "en";
}

function persistLocale(l) {
  try {
    localStorage.setItem(STORAGE_KEY, l);
  } catch {
    /* ignore */
  }
  try {
    sessionStorage.setItem(STORAGE_KEY, l);
  } catch {
    /* ignore */
  }
  if (typeof document !== "undefined") {
    document.documentElement.lang = l === "es" ? "es" : "en";
  }
}

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(() => {
    const l = readStoredLocale();
    if (typeof document !== "undefined") {
      document.documentElement.lang = l === "es" ? "es" : "en";
    }
    return l;
  });

  const setLocale = useCallback((next) => {
    const l = next === "es" ? "es" : "en";
    persistLocale(l);
    setLocaleState(l);
  }, []);

  const t = useCallback(
    (key, vars) => {
      const table = TRANSLATIONS[locale] || TRANSLATIONS.en;
      let out = table[key] ?? TRANSLATIONS.en[key] ?? key;
      if (vars && typeof vars === "object" && typeof out === "string") {
        out = out.replace(/\{(\w+)\}/g, (_, name) =>
          vars[name] != null ? String(vars[name]) : `{${name}}`,
        );
      }
      return out;
    },
    [locale]
  );

  const value = useMemo(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n outside I18nProvider");
  return ctx;
}
