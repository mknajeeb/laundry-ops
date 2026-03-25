/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { TRANSLATIONS } from "./translations";

const STORAGE_KEY = "washpro_locale";

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(() => {
    try {
      const s = localStorage.getItem(STORAGE_KEY);
      return s === "es" ? "es" : "en";
    } catch {
      return "en";
    }
  });

  const setLocale = useCallback((next) => {
    const l = next === "es" ? "es" : "en";
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
    setLocaleState(l);
  }, []);

  const t = useCallback(
    (key) => {
      const table = TRANSLATIONS[locale] || TRANSLATIONS.en;
      return table[key] ?? TRANSLATIONS.en[key] ?? key;
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
