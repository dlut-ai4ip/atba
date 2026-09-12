import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError, login } from "../api";
import { ThemeToggle } from "../components/ThemeToggle";
import { useT } from "../i18n";
import { isAuthenticated, setToken } from "../lib/auth";
import { useSettings } from "../settings";

// The real authenticated login page (see atba/auth.py) — a single account, with the username/password
// configured in the backend's environment variables (falling back to atba/atba if unset), not
// a multi-user account system; this is only responsible for collecting input, calling POST
// /api/auth/login, and storing the resulting token (lib/auth.ts). **No longer a pure visual facade**:
// an earlier AskUserQuestion chose "pure visual facade, recommended for now" in order to build the
// overall visual framework first; the user later explicitly requested "implement real login and
// request-authentication functionality," so this was switched to a real call, and the previous "just
// take a look for now →" skip button was removed at the same time — skipping login would only cause
// every subsequent API call to get a 401, it's no longer a genuinely usable path.
//
// Language toggle: shares the same global lang toggle as the sidebar's language toggle
// (LanguageToggle.tsx), see the Settings context — there's no AppShell here, so a standalone
// theme+language toggle button group is placed instead.
export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { lang, setLang } = useSettings();
  const t = useT();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // If already logged in (a valid local token still exists), there's no need to see the login page
  // again — go straight in, consistent with most apps' convention of "visiting /login while already
  // logged in bounces you back to the home page."
  useEffect(() => {
    if (isAuthenticated()) {
      navigate("/", { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await login({ username: username.trim(), password });
      setToken(res.token, remember);
      // RequireAuth (App.tsx) stores the originally intended path in location.state.from — send the
      // user back there after login, rather than always to the home page: e.g. a shared run link that
      // required logging in first should continue on to that run after login, not start over from
      // scratch.
      const from = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(from, { replace: true });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-corner-actions">
        <ThemeToggle inline />
        <button
          className="login-lang-toggle"
          type="button"
          onClick={() => setLang(lang === "zh" ? "en" : "zh")}
        >
          {lang === "zh" ? "EN" : "中"}
        </button>
      </div>

      <div className="login-brand">
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
        <h1>ATBA</h1>
        <p>{t("login.brandSub")}</p>
      </div>

      <form className="login-card" onSubmit={handleSubmit}>
        <h2>{t("login.heading")}</h2>
        <p className="login-card-sub">{t("login.sub")}</p>

        <div className="login-field">
          <label htmlFor="login-username">{t("login.username")}</label>
          <div className="login-input-wrap">
            <input
              id="login-username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={t("login.usernamePlaceholder")}
              autoComplete="username"
              autoFocus
              disabled={submitting}
            />
          </div>
        </div>

        <div className="login-field">
          <label htmlFor="login-password">{t("login.password")}</label>
          <div className="login-input-wrap">
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              disabled={submitting}
            />
          </div>
        </div>

        <label className="login-remember">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
            disabled={submitting}
          />
          <span>{t("login.remember")}</span>
        </label>

        {error && <p className="login-error">{error}</p>}

        <button type="submit" className="login-submit" disabled={submitting || !username.trim() || !password}>
          {submitting ? t("login.submitting") : t("login.submit")}
        </button>

        <p className="login-footer">
          <span>{t("login.footer1")}</span>
          <span>{t("login.footer2")}</span>
        </p>
      </form>
    </div>
  );
}
