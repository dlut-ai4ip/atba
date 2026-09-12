// Manual light/dark toggle — the dark skin originally in App.css relied entirely on
// @media(prefers-color-scheme: dark), meaning that as long as the user's OS was in dark mode, the page
// would always render dark with no way to switch back to light from within the page (user feedback:
// "my system is dark so the page is stuck dark"). This adds an explicit preference layer, stored in
// localStorage, written to <html data-theme="light|dark">; when data-theme="system" (this attribute
// not set), behavior is unchanged, still fully governed by @media (see the comments on the
// :root[data-theme="dark"] and :not([data-theme="light"]) rules in App.css).
export type ThemePref = "system" | "light" | "dark";

const STORAGE_KEY = "atba-theme";

// When nothing has ever been manually chosen (this key doesn't exist in localStorage at all — a
// genuinely "new visitor/cleared cache" case), the default is now light mode, no longer "follow the
// system" (per the user's request to "default to light mode"). This is the same class of problem as
// the OS-dark-preference issue: some environmental factor (this time, the state of "never having
// manually chosen") shouldn't be allowed to make an appearance decision for the user that might not be
// what they want.
const DEFAULT_PREF: ThemePref = "light";

export function getStoredTheme(): ThemePref {
  const v = typeof localStorage !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
  if (v === "light" || v === "dark" || v === "system") return v;
  return DEFAULT_PREF;
}

// Choosing "follow system" now also has to be explicitly written to localStorage (not removeItem'd
// like before) — otherwise, if a user cycles through the three-state toggle and lands on "follow
// system," the next page refresh would have getStoredTheme() read a missing key, unable to
// distinguish "the user never chose anything" (which should fall back to the new default, light) from
// "the user explicitly chose to follow the system" (which should fall back to system) — misjudging the
// latter as the former would silently revert the user's explicit choice back to light, see the comment
// on DEFAULT_PREF above; that's exactly the class of problem this change is meant to avoid.
export function applyTheme(pref: ThemePref) {
  const root = document.documentElement;
  if (pref === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", pref);
  }
  localStorage.setItem(STORAGE_KEY, pref);
}

// A three-state cycle: follow system → light → dark → follow system... deliberately not simplified to
// a two-state toggle, because "follow system" is itself a meaningful state a user might want to return
// to (e.g. wanting the page to switch too when their laptop's OS auto-switches to dark at night), not
// an edge case that can be dropped alongside light/dark.
export function nextTheme(current: ThemePref): ThemePref {
  if (current === "system") return "light";
  if (current === "light") return "dark";
  return "system";
}

// The "actually effective light/dark value" (corresponding exactly to what's actually rendered on
// screen) — not the same thing as ThemePref above: when pref="system", it doesn't correspond to any
// concrete light/dark value on its own, you have to check the current OS preference to know which set
// is actually in effect. CSS itself handles this conversion automatically via the
// :root[data-theme]/@media(prefers-color-scheme) rules, no JS involvement needed; **but Mermaid
// diagrams are an exception** — their colors are static values "baked" into the generated SVG by
// mermaid.js at the moment of rendering, and don't automatically recompute on a theme switch the way
// CSS variables do, so MermaidDiagram.tsx needs to actively know "is it currently actually dark or
// light" and re-render when that value changes, see that component's usage.
export type EffectiveTheme = "light" | "dark";

export function getEffectiveTheme(): EffectiveTheme {
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit === "light" || explicit === "dark") return explicit;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// Subscribes to changes in the "actually effective theme" — two independent trigger sources both need
// to be wired up, missing either one leaves some switching method unable to keep up:
// (1) the user explicitly toggling via ThemeToggle (reflected in the <html data-theme> attribute,
//     watched with a MutationObserver);
// (2) when pref="system", the OS itself switching light/dark (reflected in the
//     prefers-color-scheme media query — the data-theme attribute itself doesn't change, so a
//     MutationObserver can't see it, and the matchMedia change event needs a separate subscription).
// Returns an unsubscribe function; the caller cleans up in its own useEffect.
export function subscribeEffectiveTheme(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const media = window.matchMedia?.("(prefers-color-scheme: dark)");
  media?.addEventListener("change", onChange);
  return () => {
    observer.disconnect();
    media?.removeEventListener("change", onChange);
  };
}
