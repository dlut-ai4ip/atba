import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getHealth } from "./api";
import type { HealthResponse } from "./types";

// Run settings (provider/lang/the theory-jargon retry cap) used to be local state in App.tsx; now
// that routing has been split up, LandingPage starting a new run and Step1RunPage handling that run's
// follow-up questions both need the same settings, so they've been lifted into a Context — not out of
// "state management" tidiness for its own sake, there's a genuine cross-page sharing need once routing
// was split.
interface Settings {
  provider: "anthropic" | "deepseek" | "openai";
  setProvider: (p: "anthropic" | "deepseek" | "openai") => void;
  // undefined = "use the provider's default model, don't specify one explicitly in the request" —
  // currently the DeepSeek dropdown only has one real option (the currently configured default model
  // itself), so picking it has the same effect as not picking anything; the undefined initial state is
  // kept so that, once there are more model options in the future, "the user hasn't manually picked
  // one yet" and "the user picked the one that happens to match the default" can stay two distinct
  // things.
  model: string | undefined;
  setModel: (m: string | undefined) => void;
  reasoningEffort: string;
  setReasoningEffort: (e: string) => void;
  lang: "zh" | "en";
  setLang: (l: "zh" | "en") => void;
  maxRetries: number;
  setMaxRetries: (n: number) => void;
  health: HealthResponse | null;
  healthError: string | null;
}

const SettingsContext = createContext<Settings | null>(null);

// Bumped from "atba-lang" to "-v2" once: this public repo defaults to English, but the storage key
// name was previously shared with the private dev repo's frontend served on the same localhost port,
// so a "zh" value saved there would silently carry over here as a false "default" on first load. A
// fresh key name makes every browser start clean (falling through to getStoredLang's "en" default)
// regardless of whatever this origin/port had stored before; from here on it persists exactly like
// before, so an explicit language choice still survives a refresh.
const LANG_STORAGE_KEY = "atba-lang-v2";

// lang now drives both the interface copy (see ../i18n/) and the prompt language sent to the model —
// no longer just an obscure option in "run settings" — so it's persisted to localStorage (the same
// approach as the theme preference in lib/theme.ts); otherwise every full-page refresh/directly
// opening a run link would fall back to the default English, which would feel like "the language
// setting didn't take."
function getStoredLang(): "zh" | "en" {
  const v = typeof localStorage !== "undefined" ? localStorage.getItem(LANG_STORAGE_KEY) : null;
  return v === "zh" ? "zh" : "en";
}

// A fallback value kept consistent with atba/agent_streaming.py's DEFAULT_DEEPSEEK_REASONING_EFFORT —
// only used briefly while /api/health hasn't returned yet; once health comes back it gets overwritten
// with the backend's real configured value (the two are normally equal anyway — this isn't maintaining
// a second copy of authoritative configuration, just giving a reasonable initial display for the
// moment while the health request is still in flight, so the dropdown isn't empty for an instant.
const FALLBACK_REASONING_EFFORT = "high";

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [provider, setProvider] = useState<"anthropic" | "deepseek" | "openai">("deepseek");
  const [model, setModel] = useState<string | undefined>(undefined);
  const [reasoningEffort, setReasoningEffort] = useState(FALLBACK_REASONING_EFFORT);
  const [lang, setLangState] = useState<"zh" | "en">(getStoredLang);
  const [maxRetries, setMaxRetries] = useState(2);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  function setLang(l: "zh" | "en") {
    localStorage.setItem(LANG_STORAGE_KEY, l);
    setLangState(l);
  }

  useEffect(() => {
    getHealth()
      .then((h) => {
        setHealth(h);
        // Once health comes back, sync the displayed thinking-effort value to the backend's real
        // default tier for whichever provider is currently selected — the initial
        // FALLBACK_REASONING_EFFORT is only a best-guess fallback, not guaranteed to exactly match
        // either provider's actual configured default (DeepSeek and OpenAI have different tier lists
        // and defaults, see HealthResponse's comment in types.ts — picking the wrong one here would
        // silently sync toward a tier the current provider doesn't even offer).
        const defaultForProvider = provider === "openai" ? h.default_openai_reasoning_effort : h.default_deepseek_reasoning_effort;
        setReasoningEffort((prev) => (prev === FALLBACK_REASONING_EFFORT ? defaultForProvider : prev));
      })
      .catch((e: unknown) => setHealthError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <SettingsContext.Provider
      value={{
        provider,
        setProvider,
        model,
        setModel,
        reasoningEffort,
        setReasoningEffort,
        lang,
        setLang,
        maxRetries,
        setMaxRetries,
        health,
        healthError,
      }}
    >
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings(): Settings {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be called inside a <SettingsProvider>");
  return ctx;
}
