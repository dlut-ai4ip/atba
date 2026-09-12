import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { applyTheme, getStoredTheme } from './lib/theme'
import { setToken } from './lib/auth'

// Synchronously writes the saved theme preference to <html data-theme> before React renders — putting
// this inside React's lifecycle (e.g. some component's useEffect) would only take effect after the
// first frame renders, so a user who manually picked dark/light would see a flash of the wrong theme
// before it corrects itself; running it synchronously here avoids that.
applyTheme(getStoredTheme());

// Static demo build (npm run build:demo, see DEMO.md): (1) uses HashRouter instead of BrowserRouter —
// demo.html is a local file:// file opened by double-clicking (or dropped into arbitrary static
// hosting with an uncertain path prefix), and BrowserRouter's reliance on pushState 404s/loses state
// on refresh in that kind of environment; HashRouter's #/runs/... doesn't depend on server-side
// routing and works anywhere; (2) seeds a fake token ahead of time, so App.tsx's RequireAuth passes
// through immediately — demo mode has no real login, nor does it need one, see the IS_DEMO branch in
// api.ts's request() (read-only GETs resolve directly from the bundle, this token is never actually
// used to hit a backend).
const IS_DEMO = import.meta.env.VITE_DEMO_MODE === 'true';
if (IS_DEMO) setToken('demo', true);
const Router = IS_DEMO ? HashRouter : BrowserRouter;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Router>
      <App />
    </Router>
  </StrictMode>,
)
