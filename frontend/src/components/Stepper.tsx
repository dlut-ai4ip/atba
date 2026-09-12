import { Link } from "react-router-dom";
import { useT } from "../i18n";
import { STAGES, stagePlanState, type PlanState } from "../lib/stepStatus";

const STATE_ICON: Record<PlanState, string> = {
  pending: "",
  running: "◐",
  done: "✓",
  needs_input: "?",
  blocked: "✕",
};

// The horizontal 6-segment progress bar at the top of design/agent_run.png — replaces the old
// PlanPanel's vertical list, closer to the design mockup visually; the status-determination logic
// reuses lib/stepStatus.ts (sharing the same status→PlanState mapping as the old PlanPanel, no
// separate rule set). statuses/runningStep are passed in by the caller (AgentRunPage), the same
// convention as the old PlanPanel.
//
// The connecting line is no longer a hand-written <span> in JSX — previously, "cramming both the dot
// and the line into the same horizontal flex track" pushed the dot to the track's far left via the
// line's flex:1, while the label below sat on its own line, centered/left-aligned by default, so the
// two didn't line up (user feedback: "the text below the icon isn't centered with the icon"). Now the
// dot is centered on its own inside .stepper-track, and the connecting line is a CSS ::after
// pseudo-element drawn on .stepper-item instead (see App.css), running from the current item's
// midpoint to the next item's midpoint — no longer taking up any JSX/flex layout space, so the dot and
// label can align with each other using the same text-align:center.
//
// A completed (done) node can be clicked to look back — jumping to /runs/:runId/stepN, a route that's
// already "read-only, from persisted results, never re-triggers a model call" (see the top-of-file
// comment in each StepNRunPage.tsx), so clicking back has no side effects. The other states (pending/
// running/needs_input/blocked) aren't clickable: pending hasn't been reached yet, running is currently
// in progress, needs_input/blocked means the current step itself is stuck and needs attention — beyond
// the currently active step, clicking through has no purpose.
export function Stepper({
  runId,
  statuses,
  runningStep,
}: {
  runId: string;
  statuses: Partial<Record<number, string | null>>;
  runningStep: number | null;
}) {
  const t = useT();
  return (
    <ol className="stepper">
      {STAGES.map((s) => {
        const state = stagePlanState(statuses[s.id], runningStep === s.id);
        const label = t(s.nameKey);
        const dot = <span className="stepper-dot">{STATE_ICON[state] || s.id}</span>;
        return (
          <li key={s.id} className={`stepper-item stepper-item-${state}`}>
            {state === "done" ? (
              <Link to={`/runs/${runId}/step${s.id}`} className="stepper-link" title={label}>
                <div className="stepper-track">{dot}</div>
                <span className="stepper-label">{label}</span>
              </Link>
            ) : (
              <>
                <div className="stepper-track">{dot}</div>
                <span className="stepper-label" title={label}>
                  {label}
                </span>
              </>
            )}
          </li>
        );
      })}
    </ol>
  );
}
