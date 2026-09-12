import { useState } from "react";
import { useT } from "../i18n";
import { applyTheme, getStoredTheme, nextTheme, type ThemePref } from "../lib/theme";

const ICON: Record<ThemePref, React.ReactNode> = {
  system: <MonitorIcon />,
  light: <SunIcon />,
  dark: <MoonIcon />,
};

const LABEL_KEY: Record<ThemePref, string> = {
  system: "theme.system",
  light: "theme.light",
  dark: "theme.dark",
};

// The "inline, embedded in the header" positioning — this button doesn't need a popover, one click
// cycles directly (see nextTheme in lib/theme.ts), saving a click compared to opening a dropdown to
// pick one of three. LoginPage doesn't use AppShell, so it puts its own copy of this at the top of its
// own page (side by side with the existing Chinese/English toggle button), for the same reason: the
// login page also needs to render correctly in both light and dark, and shouldn't lack a theme toggle
// just because it's not inside AppShell.
export function ThemeToggle({ inline = false }: { inline?: boolean }) {
  const [pref, setPref] = useState<ThemePref>(getStoredTheme);
  const t = useT();

  function handleClick() {
    // Uses a functional update rather than reading pref directly from the closure — when two clicks
    // land within the same batching cycle (e.g. calling .click() synchronously back-to-back in an
    // automated test, or a fast-clicking user), reading pref directly would have every click read the
    // same not-yet-committed old value, computing the same "next state" — visually it would look like
    // clicking did nothing. With a functional update, the next state is always computed from the real
    // value after the previous update, independent of when React commits a render.
    setPref((current) => {
      const next = nextTheme(current);
      applyTheme(next);
      return next;
    });
  }

  return (
    <button
      className={inline ? "settings-toggle-inline" : "theme-toggle"}
      onClick={handleClick}
      title={t("theme.toggleTitle", { label: t(LABEL_KEY[pref]) })}
      type="button"
    >
      {ICON[pref]}
    </button>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2.5v2.4M12 19.1v2.4M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M2.5 12h2.4M19.1 12h2.4M4.9 19.1l1.7-1.7M17.4 6.6l1.7-1.7" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a7 7 0 0 0 11 11Z" strokeLinejoin="round" />
    </svg>
  );
}

function MonitorIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4.5" width="18" height="12" rx="1.5" />
      <path d="M8.5 20.5h7M12 16.5v4" />
    </svg>
  );
}
