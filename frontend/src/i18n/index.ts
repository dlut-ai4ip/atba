import { useSettings } from "../settings";
import { en, zh } from "./translations";

const DICTS = { zh, en };

// vars does the simplest possible string interpolation with {{name}} placeholders — the only
// interpolation scenario in this app is "dropping a dynamic value like run_id/a count into a line of
// copy," which doesn't need the whole ICU plural/date-formatting apparatus; a plain regex replace is
// enough, no dependency like react-i18next needed.
export function translate(lang: "zh" | "en", key: string, vars?: Record<string, string | number>): string {
  let s = DICTS[lang][key] ?? zh[key] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      s = s.replaceAll(`{{${k}}}`, String(v));
    }
  }
  return s;
}

// The interface language reuses the global lang state already in settings.tsx (the same switch as the
// prompt language, see the top-of-file comment in translations.ts) — no separate "UI language" state
// is added, avoiding making the user manage two language settings independently.
export function useT() {
  const { lang } = useSettings();
  return (key: string, vars?: Record<string, string | number>) => translate(lang, key, vars);
}
