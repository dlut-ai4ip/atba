// Shared logic for determining the status of the six steps — this used to live in
// components/PlanPanel.tsx; once PlanPanel (a vertical-list UI) was replaced by Stepper.tsx (the
// horizontal-progress-bar UI from design/agent_run.png), the pure-logic part was moved out into its
// own file so both UI components (now just Stepper.tsx) can reuse it, instead of each maintaining its
// own copy of the STAGES/status mapping.

// name was changed to nameKey (an i18n translation key, see stages.* in ../i18n/translations.ts) —
// STAGES is a module-level constant, not a component, so it has no access to the useT() hook; it can
// only store the key, leaving the actual displayed text to whichever consumer (Stepper.tsx/
// AgentRunPage.tsx) calls t(stage.nameKey) to translate it.
export const STAGES: { id: number; nameKey: string }[] = [
  { id: 1, nameKey: "stages.1" },
  { id: 2, nameKey: "stages.2" },
  { id: 3, nameKey: "stages.3" },
  { id: 4, nameKey: "stages.4" },
  { id: 5, nameKey: "stages.5" },
  { id: 6, nameKey: "stages.6" },
];

export type PlanState = "pending" | "running" | "done" | "needs_input" | "blocked";

// Every step shares the same status-value convention: "passed" = complete; "needs_clarification"
// (step 1) / "no_gap_found" (step 3: every candidate direction was judged to not constitute a puzzle)
// / "blocked_unresolved" (step 5: reached the max loop rounds while still failing interrogation) are
// all grouped as "needs_input" — all three semantically mean "the agent finished the judgment it was
// supposed to make, and it's now up to a human to decide the next step," not "it crashed"; every other
// non-empty string (including genuine infrastructure failures like retrieval_unavailable) is grouped
// as "blocked". No need to write a separate determination function for each step.
export function stagePlanState(status: string | null | undefined, loading: boolean): PlanState {
  if (loading) return "running";
  if (!status) return "pending";
  if (status === "passed") return "done";
  if (status === "needs_clarification" || status === "no_gap_found" || status === "blocked_unresolved") return "needs_input";
  return "blocked";
}

// Parses a stage name like "step3" from manifest.json/RunSummary into a number — both HistoryPage.tsx
// (the history list jumping to whichever step a run actually stopped at) and AgentRunPage.tsx (the top
// Stepper judging whether steps beyond the one currently being viewed also already have results) need
// the same parsing rule, so it's factored into a shared function — no duplicate implementation, and
// only one place to change later if needed. Returns null when a number can't be parsed or falls outside
// the 1-6 range; callers each decide their own fallback.
export function parseStageNumber(stage: string): number | null {
  const m = /step(\d+)/.exec(stage);
  const n = m ? parseInt(m[1], 10) : NaN;
  return n >= 1 && n <= 6 ? n : null;
}
