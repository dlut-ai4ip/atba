import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ command }) => {
  // A production build (vite build) must explicitly set VITE_API_BASE_URL — even if the value
  // deliberately chosen is an empty string (same-domain reverse-proxy mode, see the "Production
  // build" section of README.md). It must not silently fall back to the `?? "http://localhost:8000"`
  // default in src/api.ts — that fallback is only meant for local dev via `npm run dev`. Once baked
  // into a production dist/ that's committed to version control, the site would ship with every API
  // request pointing at the visitor's own localhost:8000, all failing — and the build process itself
  // wouldn't raise any error, only surfacing once a user notices it deployed broken. This has already
  // happened twice from forgetting to go through build-prod.ps1 and running a bare `npm run build`
  // directly. This turns "forgot to set it" from a runtime hazard that only surfaces after deployment
  // into an immediate build-time failure — a bare `npm run build` now just errors out instead of
  // producing a dist/ that looks normal but actually points at localhost, forcing it to go through
  // build-prod.ps1 (or have this variable set manually). `npm run dev` (command==='serve') is
  // unaffected — local development can still leave everything unset, using src/api.ts's
  // localhost:8000 default.
  if (command === 'build' && process.env.VITE_API_BASE_URL === undefined) {
    throw new Error(
      'A production build must explicitly set the VITE_API_BASE_URL environment variable (even an ' +
        'empty string, meaning same-domain reverse-proxy mode via relative paths) — otherwise it ' +
        'silently falls back to the http://localhost:8000 default meant for local dev in src/api.ts, ' +
        'and every API request will hit the visitor\'s own computer once deployed, with no error at ' +
        'build time — this has already caused two bad dist/ commits before.\n' +
        'Use .\\build-prod.ps1 to build (defaults to the production backend https://your-backend-domain.example), ' +
        'or set this environment variable explicitly before running npm run build — see the ' +
        '"Production build" section of frontend/README.md.',
    )
  }
  return {
    plugins: [react()],
  }
})
