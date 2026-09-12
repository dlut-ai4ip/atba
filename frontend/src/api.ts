import { clearToken, getToken } from "./lib/auth";
import { DEMO_MANIFEST, DEMO_RUN_ID, DEMO_STEP_RESULTS } from "./demo-data";
import type {
  HealthResponse,
  LoginRequest,
  LoginResponse,
  RunSummary,
  Step1Request,
  Step1Result,
  Step1StreamEvent,
  Step2Request,
  Step2Result,
  Step2SelectionRequest,
  Step2StreamEvent,
  Step3Request,
  Step3Result,
  Step3StreamEvent,
  Step4Request,
  Step4Result,
  Step4StreamEvent,
  Step5Request,
  Step5Result,
  Step5StreamEvent,
  Step6Request,
  Step6Result,
  Step6StreamEvent,
  StreamEvent,
} from "./types";

// The backend README's default startup command is `uvicorn atba.api:app --reload --port 8000`, so
// 8000 is used as the default here too; if the backend runs on a different port locally, override it
// via VITE_API_BASE_URL in .env.local, see .env.example.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// Static demo mode (built via `npm run build:demo`, see DEMO.md): no real backend runs — the six
// read-only GET endpoints are read from a real run bundled into the build under src/demo-data/ —
// component code has no idea it's running in demo mode, it sends whatever request it normally would;
// this just intercepts it and resolves directly, without a real network request. Login and starting a
// new run are skipped entirely (LoginPage/LandingPage are never reached, see main.tsx/App.tsx), but
// **step 2's "confirm selection" is a write that genuinely does get called** — clicking "next step" on
// step 2 always calls selectStep2Directions regardless of demo mode (the component has no branch for
// "don't persist"), so this needs its own interception below rather than only intercepting GETs; a
// bug where this fell through to a real fetch against localhost:8000 and failed with
// ERR_CONNECTION_REFUSED was reported and fixed here. The "Retry" button on every step is a genuine
// write too (re-running the agent) that demo mode fundamentally cannot support — those are hidden via
// the exported IS_DEMO flag in each Step*RunPage.tsx instead of being intercepted here, since silently
// returning the same cached result on "retry" would look like nothing happened, not like a disabled
// feature.
export const IS_DEMO = import.meta.env.VITE_DEMO_MODE === "true";

function resolveDemoGet(path: string): unknown {
  if (path === "/api/health") {
    return {
      status: "ok",
      providers: { anthropic: "configured", deepseek: "configured", openai: "configured" },
      max_loop_rounds: 3,
      deepseek_reasoning_efforts: ["low", "medium", "high"],
      default_deepseek_reasoning_effort: "high",
      openai_reasoning_efforts: ["minimal", "low", "medium", "high"],
      default_openai_reasoning_effort: "medium",
    };
  }
  if (path === "/api/runs") return [DEMO_MANIFEST];
  if (path === `/api/runs/${DEMO_RUN_ID}`) return DEMO_MANIFEST;
  const stepMatch = /^\/api\/runs\/([^/]+)\/step([1-6])$/.exec(path);
  if (stepMatch && stepMatch[1] === DEMO_RUN_ID) {
    const key = `step${stepMatch[2]}` as keyof typeof DEMO_STEP_RESULTS;
    return DEMO_STEP_RESULTS[key];
  }
  throw new ApiError(`Demo mode doesn't support this request: ${path} (a read-only example run, no writes/other runs accepted)`, 404);
}

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// Every endpoint except /api/health and /api/auth/login requires a token (see the protected router
// group in atba/api.py) — attach it if there is one, don't if there isn't (public endpoints don't need
// it anyway, and attaching it does no harm since the backend doesn't check it there).
function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// A 401 can only mean one of two things: never logged in (RequireAuth should have caught this before
// the request was even made, see App.tsx), or the token expired (7-day validity on the backend, see
// atba/auth.py) — either way, this local token can no longer be trusted, so clear it and send the user
// through login again. A hard redirect (not react-router's navigate) is used because request()/
// streamPost() are plain functions outside the React component tree with no access to navigate; the
// hard reload also conveniently clears any leftover page state built on the now-invalid token.
function handleUnauthorized(): void {
  clearToken();
  if (window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // In demo mode, read-only GETs resolve directly from the bundle without a real request — writes
  // (method !== GET, i.e. anything other than !init or init.method unset) aren't intercepted, and fall
  // through to the real fetch below, which naturally fails since there's no backend — this is
  // deliberate: demo mode doesn't promise to support writes, and a failure there is itself a sign that
  // a path that shouldn't be reachable in the demo got called.
  if (IS_DEMO && (!init || !init.method || init.method === "GET")) {
    return resolveDemoGet(path) as T;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders() },
    ...init,
  });
  if (res.status === 401 && path !== "/api/auth/login") {
    handleUnauthorized();
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail ?? res.statusText;
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), res.status);
  }
  return res.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health");
}

// Login itself doesn't need to carry a token (it doesn't have one yet) — it's fine that it still goes
// through request()'s default authHeaders logic, since getToken() is almost certainly null at this
// point anyway; a standalone function exists purely for clearer call-site semantics, not because
// request() can't handle this endpoint.
export function login(req: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function runStep1(req: Step1Request): Promise<Step1Result> {
  return request<Step1Result>("/api/step1", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function getRunStep1(runId: string): Promise<Step1Result> {
  return request<Step1Result>(`/api/runs/${runId}/step1`);
}

export function listRuns(): Promise<RunSummary[]> {
  return request<RunSummary[]>("/api/runs");
}

// A single run's manifest (last_stage/completed_stages... exactly the same shape as each entry in
// listRuns() — the backend's GET /api/runs/{run_id} returns manifest.json directly) — AgentRunPage
// uses this to judge "which step has this run actually reached," so that when a user clicks back to an
// earlier step to view it, the top Stepper still shows later steps that genuinely have results as
// completed/clickable, rather than falling back to the conservative assumption that "only steps before
// the current one count as complete," see that component's usage.
export function getRunManifest(runId: string): Promise<RunSummary> {
  return request<RunSummary>(`/api/runs/${runId}`);
}

// Every step's /api/stepN/stream is NDJSON (one JSON event per line), not SSE — the request itself is
// a POST with a body, and the browser's native EventSource only supports GET, so reading a
// ReadableStream manually via fetch and splitting on newlines is simpler than pulling in an SSE
// polyfill. onEvent is called synchronously as each event arrives (used to update the "thinking
// process"/"structured output being generated" display in real time); the function itself resolves
// once it receives {"type":"final"}, with a return value fully isomorphic to the corresponding
// non-streaming runStepN — callers don't need to think about streaming details. Factored out generic
// so steps 3 and onward don't have to copy this stream-reading logic again for each new streaming
// endpoint.
async function streamPost<TReq, TResult>(
  path: string,
  req: TReq,
  onEvent: (event: StreamEvent<TResult>) => void,
): Promise<TResult> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(req),
  });
  if (res.status === 401) {
    handleUnauthorized();
  }
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail ?? res.statusText;
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), res.status);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: TResult | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newlineIdx = buffer.indexOf("\n");
    while (newlineIdx >= 0) {
      const line = buffer.slice(0, newlineIdx).trim();
      buffer = buffer.slice(newlineIdx + 1);
      if (line) {
        const event = JSON.parse(line) as StreamEvent<TResult>;
        onEvent(event);
        if (event.type === "final") finalResult = event.result;
      }
      newlineIdx = buffer.indexOf("\n");
    }
  }

  if (!finalResult) {
    throw new ApiError("The streaming response ended abnormally without a final result (a \"final\" event)", 0);
  }
  return finalResult;
}

export function streamStep1(
  req: Step1Request,
  onEvent: (event: Step1StreamEvent) => void,
): Promise<Step1Result> {
  return streamPost("/api/step1/stream", req, onEvent);
}

export function runStep2(req: Step2Request): Promise<Step2Result> {
  return request<Step2Result>("/api/step2", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function getRunStep2(runId: string): Promise<Step2Result> {
  return request<Step2Result>(`/api/runs/${runId}/step2`);
}

// Not an agent run — persists the candidate theoretical directions the user checked off in step 2's
// result (see select_step2_directions in atba/api.py); step 3 should read this field as its input.
// In demo mode this is intercepted rather than falling through to a real fetch: unlike every other
// write (retry/new-run/login), this one genuinely gets called on the normal "next step" path — the
// bundled DEMO_STEP_RESULTS.step2 already has selected_theory_directions baked in from the real run
// this demo was generated from, so resolving with that directly is accurate, not a stub.
export function selectStep2Directions(runId: string, req: Step2SelectionRequest): Promise<Step2Result> {
  if (IS_DEMO && runId === DEMO_RUN_ID) {
    return Promise.resolve(DEMO_STEP_RESULTS.step2);
  }
  return request<Step2Result>(`/api/runs/${runId}/step2/selection`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function streamStep2(
  req: Step2Request,
  onEvent: (event: Step2StreamEvent) => void,
): Promise<Step2Result> {
  return streamPost("/api/step2/stream", req, onEvent);
}

export function getRunStep3(runId: string): Promise<Step3Result> {
  return request<Step3Result>(`/api/runs/${runId}/step3`);
}

export function streamStep3(
  req: Step3Request,
  onEvent: (event: Step3StreamEvent) => void,
): Promise<Step3Result> {
  return streamPost("/api/step3/stream", req, onEvent);
}

export function getRunStep4(runId: string): Promise<Step4Result> {
  return request<Step4Result>(`/api/runs/${runId}/step4`);
}

// /api/step4 only runs one round (round_number=1) of candidate generation — the revision round
// triggered by step 5's loop calls the same run_step4/stream_step4 function internally on the backend,
// but not through this HTTP endpoint, see atba/abductive_loop.py.
export function streamStep4(
  req: Step4Request,
  onEvent: (event: Step4StreamEvent) => void,
): Promise<Step4Result> {
  return streamPost("/api/step4/stream", req, onEvent);
}

export function getRunStep5(runId: string): Promise<Step5Result> {
  return request<Step5Result>(`/api/runs/${runId}/step5`);
}

// /api/step5 runs the complete step-4/5 automatic loop (atba/abductive_loop.py) — one call returns the
// loop's terminal state; each round's thinking/tool_call along the way is still forwarded in real time
// via round_marker/phase_final events, rather than waiting for the entire loop to finish before
// dumping the result all at once, see the type comment on Step5StreamEvent.
export function streamStep5(
  req: Step5Request,
  onEvent: (event: Step5StreamEvent) => void,
): Promise<Step5Result> {
  return streamPost("/api/step5/stream", req, onEvent);
}

export function getRunStep6(runId: string): Promise<Step6Result> {
  return request<Step6Result>(`/api/runs/${runId}/step6`);
}

// text_delta events carry the report body's own incremental text, not a JSON fragment — see the type
// comment on Step6StreamEvent.
export function streamStep6(
  req: Step6Request,
  onEvent: (event: Step6StreamEvent) => void,
): Promise<Step6Result> {
  return streamPost("/api/step6/stream", req, onEvent);
}

export { ApiError };
