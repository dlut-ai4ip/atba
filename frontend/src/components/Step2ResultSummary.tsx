import { useT } from "../i18n";
import type { Step2Result } from "../types";

const STATUS_LABEL_KEY: Record<string, { key: string; tone: "ok" | "warn" | "block" }> = {
  passed: { key: "result2.statusPassed", tone: "ok" },
  blocked_agent_error: { key: "result1.statusAgentError", tone: "block" },
};

interface Props {
  result: Step2Result;
  // Optional: only "the current round, and it passed" result needs interactive checkboxes —
  // history/failed results are shown read-only (when selectable is omitted or false, it degrades to a
  // plain read-only card list, no checkbox rendered). selectedIndices/onToggle come as a pair.
  selectable?: boolean;
  selectedIndices?: Set<number>;
  onToggle?: (index: number) => void;
  // Same idPrefix as Step4ResultSummary.tsx — only passed by Step2RunPage.tsx for "the round
  // currently being displayed," attaching stable ids to the candidate-direction list for
  // PageOutlineNav.tsx to jump to.
  idPrefix?: string;
}

// Step 2 has no needs_clarification-style pending state, so it doesn't need a branch like
// ClarificationCard's — every round of run_step2/stream_step2 is either passed or blocked, so the
// result summary can just be displayed directly.
export function Step2ResultSummary({ result, selectable, selectedIndices, onToggle, idPrefix }: Props) {
  const t = useT();
  const statusEntry = STATUS_LABEL_KEY[result.status];
  const status = statusEntry ? { label: t(statusEntry.key), tone: statusEntry.tone } : { label: result.status, tone: "warn" as const };
  return (
    <div className={`result-summary tone-${status.tone}`}>
      <div className="status-badge">{status.label}</div>
      <p className="note">{result.note}</p>

      {result.candidate_theory_directions.length > 0 && (
        <ol className="theory-directions" id={idPrefix && `${idPrefix}-directions`}>
          {result.candidate_theory_directions.map((d, i) => {
            const checked = selectedIndices?.has(i) ?? false;
            return (
              <li key={i} className={`theory-direction-card${checked ? " selected" : ""}`}>
                {selectable && (
                  <input
                    type="checkbox"
                    className="theory-direction-checkbox"
                    checked={checked}
                    onChange={() => onToggle?.(i)}
                    aria-label={t("result2.selectAria", { name: d.theory_name })}
                  />
                )}
                <div className="theory-direction-body">
                  <div className="theory-direction-name">{d.theory_name}</div>
                  <p className="theory-direction-rationale">{d.relevance_rationale}</p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
