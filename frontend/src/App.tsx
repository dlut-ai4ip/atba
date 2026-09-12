import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import "./App.css";
import { DEMO_RUN_ID } from "./demo-data";
import { HistoryPage } from "./pages/HistoryPage";
import { LandingPage } from "./pages/LandingPage";
import { LoginPage } from "./pages/LoginPage";
import { AgentRunPage } from "./pages/AgentRunPage";
import { isAuthenticated } from "./lib/auth";
import { SettingsProvider } from "./settings";

// Under a static demo build, "/" shouldn't render LandingPage — that page's submit button would
// genuinely fire off an agent call, and demo mode has no backend to call. Jump straight to the
// bundled example run's step 1 instead, so landing on the page already shows real content, not an
// empty form.
const IS_DEMO = import.meta.env.VITE_DEMO_MODE === "true";

// Each step has its own independent route, so history can be revisited:
//   /login                   — the login page (see atba/auth.py + LoginPage.tsx, real single-account
//                                authentication, no longer just a visual facade)
//   /                        — start a new phenomenon input
//   /runs                    — the run history list
//   /runs/:runId/step1..6    — a given run's results per step, all sharing outer chrome
//                                (AppShell+Stepper+StepCard) provided uniformly by AgentRunPage, while
//                                each step keeps its own independent state machine/content, see the
//                                top-of-file comment in AgentRunPage.tsx.
// <BrowserRouter> is wrapped in main.tsx; only <Routes> lives here. The old version's globally
// viewport-corner-fixed <SettingsGear/> has been folded into AppShell's header bar (each page decides
// for itself whether to show it; LoginPage doesn't need it), no longer rendered globally here.
//
// RequireAuth wraps every route except /login — without a local token (lib/auth.ts's
// isAuthenticated()), it redirects to /login immediately, rather than waiting for an API call that's
// bound to 401 before discovering the user isn't logged in. This is purely a routing-level "don't show
// UI that shouldn't be shown" — the real access control is on the backend (the protected router group
// in atba/api.py); this frontend layer can't actually block anything (e.g. hitting the API directly
// with curl and a fake token), and shouldn't be counted on to.
function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <SettingsProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            IS_DEMO ? (
              <Navigate to={`/runs/${DEMO_RUN_ID}/step1`} replace />
            ) : (
              <RequireAuth>
                <LandingPage />
              </RequireAuth>
            )
          }
        />
        <Route
          path="/runs"
          element={
            <RequireAuth>
              <HistoryPage />
            </RequireAuth>
          }
        />
        <Route
          path="/runs/:runId/step1"
          element={
            <RequireAuth>
              <AgentRunPage step={1} />
            </RequireAuth>
          }
        />
        <Route
          path="/runs/:runId/step2"
          element={
            <RequireAuth>
              <AgentRunPage step={2} />
            </RequireAuth>
          }
        />
        <Route
          path="/runs/:runId/step3"
          element={
            <RequireAuth>
              <AgentRunPage step={3} />
            </RequireAuth>
          }
        />
        <Route
          path="/runs/:runId/step4"
          element={
            <RequireAuth>
              <AgentRunPage step={4} />
            </RequireAuth>
          }
        />
        <Route
          path="/runs/:runId/step5"
          element={
            <RequireAuth>
              <AgentRunPage step={5} />
            </RequireAuth>
          }
        />
        <Route
          path="/runs/:runId/step6"
          element={
            <RequireAuth>
              <AgentRunPage step={6} />
            </RequireAuth>
          }
        />
      </Routes>
    </SettingsProvider>
  );
}
