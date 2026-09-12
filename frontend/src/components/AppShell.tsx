import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useT } from "../i18n";
import { clearToken } from "../lib/auth";
import { LanguageToggle } from "./LanguageToggle";
import { ThemeToggle } from "./ThemeToggle";

const COLLAPSE_STORAGE_KEY = "atba-sidebar-collapsed";

// The new overall shell — corresponds to the shared "left sidebar + header" frame in
// design/input.png and design/agent_run.png; the login page (design/login.png) is a separate,
// independently centered card layout that doesn't use this shell (see LoginPage.tsx's own container).
//
// The sidebar's nav items — at the user's request, the old "Library"/"History" placeholders (with no
// corresponding backend data model, purely "coming soon" spots that appeared in the design mockup)
// have been removed; the "Projects/run history" item was renamed to "History," with its icon changed
// from a folder to a clock (matching the icon the old "History" placeholder used) — the sidebar now
// has just the one genuinely usable nav item.
//
// There used to be a "settings" gear here too (SettingsGear, holding four things: Provider/prompt
// language/theory-jargon-retry cap/backend connection status) — removed entirely at the user's request:
// Provider and the retry cap now use the defaults hardcoded in settings.tsx, no longer exposed to the
// user; only "language" still needs to stay (model calls really do have separate zh/en prompt sets), so
// it moved down to where the sidebar's old "Support" placeholder used to be, becoming a genuinely
// usable item (see LanguageToggle.tsx).
//
// Collapse/expand — a pure frontend preference, using the same "persist to localStorage" approach as
// theme/language (not put in the Settings Context: only this one component cares about it, no need to
// share it across components). Collapsing narrows the sidebar down to just an icon column, hiding text
// labels via CSS (see .shell-sidebar-collapsed in App.css), not rendering out two separate DOM trees.
function getStoredCollapsed(): boolean {
  return typeof localStorage !== "undefined" && localStorage.getItem(COLLAPSE_STORAGE_KEY) === "1";
}

export function AppShell({
  title,
  subtitle,
  stepper,
  detailsPanel,
  wide,
  children,
}: {
  title?: string;
  subtitle?: string;
  /** The 6-step progress bar at the top of design/agent_run.png (the Stepper component) — rendered
      inside .shell-header, sharing the same position:sticky layer as the title row, so the progress
      bar stays fixed at the top of the viewport along with the title, not scrolling away with
      .shell-content's content below (user feedback: the progress bar should stay fixed, not scroll
      with the page). Not every page using AppShell has steps to show (LandingPage/HistoryPage don't),
      so this is an optional slot — when omitted, the header just has the title row, with the same
      height and styling as before this was added. */
  stepper?: React.ReactNode;
  /** The persistent "TOOL OUTPUT DETAILS" panel on the right from design/tool_output_panel.png —
      symmetric with .shell-sidebar, the third flex child of .shell (not something inside
      .shell-content, which would get carried away by the main content area's scrollbar and couldn't
      stay fixed on the right edge of the viewport on a wide screen). Takes up no layout space at all
      when omitted, identical to before this was added; the content itself (which call was opened,
      what to show) is managed by the caller via lib/DetailsPanelContext.tsx — this AppShell layer is
      only responsible for the pure layout job of "open a column on the right when there's content." */
  detailsPanel?: React.ReactNode;
  /** Relaxes .shell-content's max-width (980px by default, a readable line width tailored for long
      narrative text) — used only for the one genuine scenario of step 4's horizontal candidate-theory
      cards: candidate cards are fixed-width columns meant for side-by-side comparison, not continuous
      text meant to be "read," and the same 980px cap would instead cram them down to showing barely
      one and a half candidates (user feedback: "candidate cards should be able to spread out"). What
      gets relaxed is the whole step-card's available width, not just carving out the candidate-card
      section on its own — that would make candidate cards visually overflow their own card border,
      looking like a broken layout; the rest of the page that's still narrative text (the selection
      rationale, etc.) each wraps its own narrow column inside .result-summary-prose, so even inside a
      wide card, long text doesn't get stretched too wide to read comfortably, see
      Step4ResultSummary.tsx. */
  wide?: boolean;
  children: React.ReactNode;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const t = useT();
  const [collapsed, setCollapsed] = useState(getStoredCollapsed);

  function handleLogout() {
    clearToken();
    navigate("/login", { replace: true });
  }

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(COLLAPSE_STORAGE_KEY, next ? "1" : "0");
      return next;
    });
  }

  return (
    <div className="shell">
      <aside className={`shell-sidebar${collapsed ? " shell-sidebar-collapsed" : ""}`}>
        <Link to="/" className="shell-logo" title="ATBA">
          <span className="shell-logo-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M12 3a5 5 0 0 0-5 5c0 1.6.7 2.7 1.6 3.7.5.6.9 1.1.9 1.8v1a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1c0-.7.4-1.2.9-1.8.9-1 1.6-2.1 1.6-3.7a5 5 0 0 0-5-5Z"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
              <path d="M10 18h4M10.5 20.5h3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <circle cx="12" cy="8.5" r="1.4" fill="currentColor" />
            </svg>
          </span>
          <span className="shell-logo-text shell-label">
            <strong>ATBA</strong>
            <small>{t("appShell.brandSub")}</small>
          </span>
        </Link>

        <Link to="/" className="shell-new-btn" title={t("appShell.newResearch")}>
          <span aria-hidden="true">+</span> <span className="shell-label">{t("appShell.newResearch")}</span>
        </Link>

        <nav className="shell-nav">
          <Link
            to="/runs"
            className={`shell-nav-item${location.pathname === "/runs" ? " shell-nav-active" : ""}`}
            title={t("appShell.historyRuns")}
          >
            <Icon name="clock" /> <span className="shell-label">{t("appShell.historyRuns")}</span>
          </Link>
        </nav>

        <div className="shell-sidebar-footer">
          <LanguageToggle />
          <button type="button" className="shell-nav-item" onClick={handleLogout} title={t("appShell.logout")}>
            <Icon name="logout" /> <span className="shell-label">{t("appShell.logout")}</span>
          </button>
          <button
            type="button"
            className="shell-nav-item shell-collapse-toggle"
            onClick={toggleCollapsed}
            title={collapsed ? t("appShell.expandSidebar") : t("appShell.collapseSidebar")}
          >
            <Icon name={collapsed ? "chevronRight" : "chevronLeft"} />
            <span className="shell-label">{t("appShell.collapseSidebar")}</span>
          </button>
        </div>
      </aside>

      <div className="shell-main">
        <header className="shell-header">
          <div className="shell-header-row">
            <div className="shell-header-title">
              {title && <h1>{title}</h1>}
              {subtitle && <span className="shell-header-subtitle">{subtitle}</span>}
            </div>
            <div className="shell-header-actions">
              <ThemeToggle inline />
            </div>
          </div>
          {stepper && <div className="shell-header-stepper">{stepper}</div>}
        </header>
        <main className={`shell-content${wide ? " shell-content-wide" : ""}`}>{children}</main>
      </div>

      {detailsPanel && <aside className="shell-details-panel">{detailsPanel}</aside>}
    </div>
  );
}

// Hand-drawn minimal line icons — used only for these few sidebar entries, matching the design
// mockup's thin-line icon style, without pulling in a dedicated icon-library dependency for it (this
// few icons don't justify a several-dozen-kb package).
function Icon({ name }: { name: "clock" | "logout" | "chevronLeft" | "chevronRight" }) {
  const paths: Record<string, React.ReactNode> = {
    clock: <path d="M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16Zm0 3.5V12l3 2" />,
    logout: <path d="M9 4H5.5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1H9M15.5 16l4-4-4-4M19 12H9" />,
    chevronLeft: <path d="M14.5 5.5 8 12l6.5 6.5" />,
    chevronRight: <path d="M9.5 5.5 16 12l-6.5 6.5" />,
  };
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  );
}
