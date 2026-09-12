import { useT } from "../i18n";
import { useSettings } from "../settings";

// The "prompt language" that used to live in the settings panel (SettingsGear, since removed, see the
// top-of-file comment in AppShell.tsx) — at the user's request the entire settings panel was dropped;
// the provider/theory-jargon-retry cap use the defaults baked into the code (the useState initial
// values in settings.tsx's SettingsProvider, no longer exposed in the UI), and only "language" moved
// down to where the sidebar's old "Support" placeholder used to be, becoming a genuinely clickable
// item.
//
// **This lang now controls two things at once** (it originally only controlled the prompt language
// sent to the model, see "why it shares the same switch as the prompt language" in the top-of-file
// comment in i18n/translations.ts): toggling it once changes the interface copy (../i18n/*) and the
// prompt templates sent to the model (the zh/en file pairs under atba/prompts/) together, so the user
// doesn't have to manage two language switches separately.
export function LanguageToggle() {
  const { lang, setLang } = useSettings();
  const t = useT();

  return (
    <button
      type="button"
      className="shell-nav-item shell-lang-toggle"
      onClick={() => setLang(lang === "zh" ? "en" : "zh")}
      title={t("appShell.langToggleTitle")}
    >
      <LangIcon />
      {/* .shell-label — when AppShell's sidebar is collapsed (see .shell-sidebar-collapsed in
          App.css), this class is what uniformly hides text labels and leaves only icons; this
          button's text has to follow the same rule, so it can't be a bare text node. */}
      <span className="shell-label">{lang === "zh" ? "中文" : "English"}</span>
    </button>
  );
}

function LangIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.2 2.3 3.4 5.3 3.4 8.5s-1.2 6.2-3.4 8.5c-2.2-2.3-3.4-5.3-3.4-8.5S9.8 5.8 12 3.5Z" />
    </svg>
  );
}
