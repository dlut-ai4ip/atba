// The six-step design, see the technical appendix's §A. All six steps are now wired to the real
// backend.
const STAGES: { id: number; name: string; implemented: boolean }[] = [
  { id: 1, name: "Phenomenon Input", implemented: true },
  { id: 2, name: "Theory Matching", implemented: true },
  { id: 3, name: "Literature Retrieval & Research Question", implemented: true },
  { id: 4, name: "Abductive Reasoning & Theory Construction", implemented: true },
  { id: 5, name: "Adversarial Interrogation", implemented: true },
  { id: 6, name: "Theoretical Contribution Report", implemented: true },
];

export type PlanState = "pending" | "running" | "done" | "needs_input" | "blocked";

// Every step shares the same status-value convention: "passed" = complete; "needs_clarification"
// (step 1) / "no_gap_found" (step 3: every candidate direction was judged to not constitute a puzzle)
// / "blocked_unresolved" (step 5: reached the max loop rounds while still failing interrogation) are
// all grouped as "needs_input" — all three semantically mean "the agent finished the judgment it was
// supposed to make, and it's now up to a human to decide the next step," not "it crashed"; every other
// non-empty string (including genuine infrastructure failures like retrieval_unavailable) is grouped
// as "blocked". No need to write a separate determination function for each step.
function stagePlanState(status: string | null | undefined, loading: boolean): PlanState {
  if (loading) return "running";
  if (!status) return "pending";
  if (status === "passed") return "done";
  if (status === "needs_clarification" || status === "no_gap_found" || status === "blocked_unresolved") return "needs_input";
  return "blocked";
}

const STATE_ICON: Record<PlanState, string> = {
  pending: "○",
  running: "◐",
  done: "✓",
  needs_input: "?",
  blocked: "✕",
};

const STATE_LABEL: Record<PlanState, string> = {
  pending: "Pending",
  running: "In progress",
  done: "Done",
  needs_input: "Needs review",
  blocked: "Sent back",
};

// statuses/runningStep are aggregated by the calling page itself — each RunPage only authoritatively
// knows the state of the steps it directly fetches/runs; the other steps default to displaying
// "pending," and no page is required to look up all six steps (see Step2RunPage, which also passes in
// step 1's status, since it already has to read step 1's phenomenon card anyway, getting it along the
// way at no extra cost).
export function PlanPanel({
  statuses,
  runningStep,
}: {
  statuses: Partial<Record<number, string | null>>;
  runningStep: number | null;
}) {
  return (
    <ol className="plan">
      {STAGES.map((s) => {
        if (!s.implemented) {
          return (
            <li key={s.id} className="plan-item plan-unimplemented">
              <span className="plan-icon">·</span>
              <span className="plan-name">{s.name}</span>
              <span className="plan-tag">Not implemented</span>
            </li>
          );
        }
        const state = stagePlanState(statuses[s.id], runningStep === s.id);
        return (
          <li key={s.id} className={`plan-item plan-${state}`}>
            <span className="plan-icon">{STATE_ICON[state]}</span>
            <span className="plan-name">{s.name}</span>
            <span className="plan-tag">{STATE_LABEL[state]}</span>
          </li>
        );
      })}
    </ol>
  );
}
