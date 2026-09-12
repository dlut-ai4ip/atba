// The data source for static demo mode — bundles a real completed six-step run (DeepSeek + real
// Scopus retrieval, 2026-09-13, phenomenon: "after a company shifted the whole workforce to full
// remote work, collaboration networks shrank from cross-group bridging to within-group closure") into
// the JS bundle, no backend dependency. See the top of ../../DEMO.md; build steps in
// ../../build-demo.ps1.
//
// The reason for hand-writing an `as const satisfies`-style explicit type assertion here instead of
// letting TS infer from the JSON structure is: api.ts's demo interception layer needs to hand these
// objects to callers as genuine Step*Result values (a component shouldn't need to know it's running in
// demo mode); `import ... from "./stepN.json"` by default only infers a broad JSON shape — field names
// line up, but enum/union types get widened to `string`, losing the real Step*Result type guarantee at
// compile time — doing an `as unknown as StepNResult` assertion right here states plainly that "this
// runtime data actually comes from a real run already validated against the current schema," which is
// better than scattering assertions all over api.ts.
import manifest from "./manifest.json";
import step1 from "./step1.json";
import step2 from "./step2.json";
import step3 from "./step3.json";
import step4 from "./step4.json";
import step5 from "./step5.json";
import step6 from "./step6.json";
import type { RunSummary, Step1Result, Step2Result, Step3Result, Step4Result, Step5Result, Step6Result } from "../types";

export const DEMO_RUN_ID = (manifest as { run_id: string }).run_id;

// For display in HistoryPage's listRuns() — the real backend attaches a phenomenon_preview sentence to
// every run; this one is hand-written to match what the real data pipeline would produce (not just a
// throwaway placeholder string).
export const DEMO_MANIFEST: RunSummary = {
  ...(manifest as Omit<RunSummary, "phenomenon_preview" | "status">),
  phenomenon_preview:
    "A large tech company shifted the whole workforce to full-time remote work; employees' collaboration " +
    "networks became more static and siloed even though total hours and meeting time barely changed.",
  status: "passed",
};

export const DEMO_STEP_RESULTS = {
  step1: step1 as unknown as Step1Result,
  step2: step2 as unknown as Step2Result,
  step3: step3 as unknown as Step3Result,
  step4: step4 as unknown as Step4Result,
  step5: step5 as unknown as Step5Result,
  step6: step6 as unknown as Step6Result,
} as const;
