import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { getEffectiveTheme, subscribeEffectiveTheme, type EffectiveTheme } from "../lib/theme";

// Step 6's report has a "theory relationship diagram" section that requires the agent to output
// Mermaid flowchart syntax (see atba/prompts/step6.md); react-markdown by default just displays a
// ```mermaid code block as plain <code> raw text — this component is responsible for actually
// rendering it as an SVG in the browser. mermaid.render() is used instead of mermaid's own
// <pre class="mermaid"> auto-scan mechanism, because while the report is streaming, the code block's
// content keeps changing (the incremental text isn't finished yet), needing an active re-render every
// time the content changes, not just one scan when the page loads.

// Reads the actual color value from a CSS variable (not the string "var(--text)" itself) —
// mermaid.js's themeVariables need a genuinely resolvable color value it can do color arithmetic on
// (generating hover states/derived colors etc.); handing it a raw CSS var() reference string breaks
// wherever mermaid internally does darken/lighten-style operations on colors, since it can't resolve
// a real color out of it — so getComputedStyle is used here to resolve the CSS variable into a
// concrete color string at the moment of rendering, before handing it to mermaid.
function resolveCssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

// Node styling — per user feedback "the boxes don't need a background color, all text should be
// black": the node fill color is set directly to the same background color as the outer
// .mermaid-diagram container (--panel, see App.css), so visually the box "disappears," leaving only
// the outline and text; text color follows --text (dark gray/black under the light theme, and
// automatically becomes light under the dark theme, not hardcoded black — hardcoding it would instead
// blend into the dark background and become unreadable under the dark theme; the real intent behind
// "all text should be black" is "follow the theme's body-text color," not "use the same black
// regardless of theme").
function buildMermaidThemeVariables() {
  return {
    primaryColor: resolveCssVar("--panel", "#ffffff"),
    primaryTextColor: resolveCssVar("--text", "#1a1a1a"),
    primaryBorderColor: resolveCssVar("--border", "#999999"),
    lineColor: resolveCssVar("--text-dim", "#888888"),
    edgeLabelBackground: resolveCssVar("--panel", "#ffffff"),
    textColor: resolveCssVar("--text", "#1a1a1a"),
    fontFamily: "inherit",
  };
}

// mermaid.js's theme configuration is global singleton state (not held separately by each component
// instance) — the "which theme was last initialized" value is used as a cache key, so multiple diagram
// components mounting under the same theme don't need to call initialize() again each time, but when
// the theme genuinely changes (the user clicked ThemeToggle, or the OS itself switched light/dark
// while pref="system"), it must be re-initialized, or diagrams rendered afterward would still use the
// old theme's colors — this is exactly the bug this fixes: the original implementation only picked a
// theme once, based on the OS's light/dark preference, when the page first loaded, and never changed
// again no matter how the theme was switched within the app afterward, causing diagrams to stay dark
// just because the OS is dark even while the app itself is in light mode — a theme desync (user
// feedback screenshot: diagrams still dark under the light theme). Hit a real mermaid.js pitfall here:
// the built-in theme names `theme: "default"`/`"dark"` each carry a whole pre-computed color palette
// that is **not** overridden just by also passing themeVariables (confirmed by testing:
// changing primaryColor to white still left node fills at mermaid's default #ECECFF pale purple,
// completely unaffected) — only `theme: "base"` is specifically designed as a blank-slate baseline
// theme that draws "entirely from whatever themeVariables you give it," and custom colors only
// actually take effect paired with it. So this no longer distinguishes light/dark via
// theme:"dark"|"default", uniformly using "base" instead, with the light/dark difference expressed
// entirely through the actual --text/--panel/--border values resolveCssVar reads at render time inside
// buildMermaidThemeVariables() — those CSS variables are already correctly resolved for the current
// theme anyway, so there's no need for mermaid's own theme name to judge light/dark a second time.
let mermaidInitializedTheme: EffectiveTheme | null = null;
function ensureMermaidInitialized(theme: EffectiveTheme) {
  if (mermaidInitializedTheme === theme) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "base",
    themeVariables: buildMermaidThemeVariables(),
    securityLevel: "strict",
  });
  mermaidInitializedTheme = theme;
}

// mermaid.render() doesn't always reject on invalid syntax — testing found that in some syntax-error
// scenarios it resolves with an SVG whose content is a "Syntax error in text" error message, rather
// than throwing, which .catch() can't catch at all, leaving the user staring at mermaid's own
// error-rendered graphic directly on the page. Two layers of defense block this: (1) a pure validation
// pass via mermaid.parse() before rendering (with suppressErrors:true, a failed validation returns
// false instead of throwing, more predictable behavior); (2) after rendering, the resulting SVG string
// is checked for mermaid's own error markers, and a hit is treated as a failure, falling back to the
// display below, instead of smearing mermaid's error graphic in front of the user.
function looksLikeMermaidErrorSvg(svg: string): boolean {
  return /aria-roledescription="error"|Syntax error in text/i.test(svg);
}

// During incremental generation, a mermaid code block that isn't finished yet is very likely to have
// incomplete syntax (e.g. cut off mid-stream); and even once generation finishes, the agent may
// genuinely have produced syntactically broken Mermaid (its wording isn't always perfect) — both cases
// use the same fallback: silently display the raw code text, without throwing an error that blows up
// the entire report page.
//
// **Debouncing is required, not a nice-to-have**: while the report is streaming, this code block's
// content changes with every text_delta received; during the stretch before the diagram is finished,
// every single change would trigger a parse+render that's bound to fail — a failed mermaid.js
// render() call doesn't always fully clean up the temporary measurement DOM nodes it created
// internally (attached directly to document.body, outside React's vdom, so React itself never cleans
// them up) — testing found this to be the main cause of memory ballooning over a long browser session:
// one report's diagram section streaming through could trigger dozens to over a hundred futile
// render() calls, each potentially leaving a little garbage behind, and it became obvious after
// testing a report a few times in one session. Debouncing compresses the calls made during the "the
// text is still changing" stretch into one call once the stream settles, cutting the actual number of
// render() calls from "once per delta" down to "once per code block."
const MERMAID_RENDER_DEBOUNCE_MS = 400;

export function MermaidDiagram({ code }: { code: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const renderIdRef = useRef(0);
  // The actually-effective theme — [code] alone isn't enough as the dependency array; when the theme
  // changes (a ThemeToggle click / the OS switching light/dark), the diagram needs to re-render too,
  // or an already-drawn diagram would stay stuck on the colors from before the switch, see the
  // comments on getEffectiveTheme/subscribeEffectiveTheme in lib/theme.ts.
  const [theme, setTheme] = useState<EffectiveTheme>(getEffectiveTheme);

  useEffect(() => subscribeEffectiveTheme(() => setTheme(getEffectiveTheme())), []);

  useEffect(() => {
    ensureMermaidInitialized(theme);
    const id = ++renderIdRef.current;
    let cancelled = false;

    async function run() {
      try {
        const parseResult = await mermaid.parse(code, { suppressErrors: true });
        if (parseResult === false) {
          throw new Error("mermaid parse failed");
        }
        const { svg: renderedSvg } = await mermaid.render(`mermaid-${Date.now()}-${id}`, code);
        if (cancelled || renderIdRef.current !== id) return;
        if (looksLikeMermaidErrorSvg(renderedSvg)) {
          setFailed(true);
          return;
        }
        setSvg(renderedSvg);
        setFailed(false);
      } catch {
        if (cancelled || renderIdRef.current !== id) return;
        setFailed(true);
      }
    }

    const timer = window.setTimeout(() => void run(), MERMAID_RENDER_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [code, theme]);

  if (failed || !svg) {
    return (
      <pre className="mermaid-fallback">
        <code>{code}</code>
      </pre>
    );
  }
  // eslint-disable-next-line react/no-danger -- mermaid.render()'s output is SVG generated by the
  // rendering library itself, not user input, so this doesn't conflict with this project's principle
  // elsewhere of always rendering the model's free text as plain text/Markdown.
  return <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: svg }} />;
}
