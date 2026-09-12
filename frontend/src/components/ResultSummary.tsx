import { useT } from "../i18n";
import type { Step1Result } from "../types";

const STATUS_LABEL_KEY: Record<string, { key: string; tone: "ok" | "warn" | "block" }> = {
  passed: { key: "result1.statusPassed", tone: "ok" },
  needs_clarification: { key: "result1.statusNeedsInfo", tone: "warn" },
  blocked_jargon_persistent: { key: "result1.statusJargonBlocked", tone: "block" },
  blocked_agent_error: { key: "result1.statusAgentError", tone: "block" },
};

// idPrefix — the same approach as Step4ResultSummary.tsx: only passed by Step1RunPage.tsx for "the
// round currently being displayed," attaching stable ids to the sections below for PageOutlineNav.tsx
// to jump to; when not passed, no id is attached, avoiding duplicate ids when multiple rounds
// (retries/answered follow-ups) stack up on the same page.
// Only shown once a "round" (one run_step1 call) has genuinely finished and isn't NEEDS_CLARIFICATION
// — the needs-more-info case is instead handled interactively by ClarificationCard, no need to also
// stack a summary on top of it.
export function ResultSummary({ result, idPrefix }: { result: Step1Result; idPrefix?: string }) {
  const t = useT();
  const statusEntry = STATUS_LABEL_KEY[result.status];
  const status = statusEntry ? { label: t(statusEntry.key), tone: statusEntry.tone } : { label: result.status, tone: "warn" as const };
  return (
    <div className={`result-summary tone-${status.tone}`}>
      <div className="status-badge">{status.label}</div>
      <p className="note">{result.note}</p>

      {result.prior_expectation?.identified && (
        <div className="summary-field" id={idPrefix && `${idPrefix}-prior-expectation`}>
          <span className="summary-label">{t("result1.priorExpectation")}</span>
          <span>{result.prior_expectation.prior_expectation_description}</span>
        </div>
      )}

      {result.causal_check?.hit && (
        <div className="summary-field" id={idPrefix && `${idPrefix}-causal-check`}>
          <span className="summary-label">{t("result1.userGuess")}</span>
          <span>
            {result.causal_check.extracted_explanation}
            {t("result1.userGuessNote")}
          </span>
        </div>
      )}

      {result.deconstruction && (
        <dl className="fields" id={idPrefix && `${idPrefix}-deconstruction`}>
          <dt>{t("result1.actor")}</dt>
          <dd>{result.deconstruction.actor}</dd>
          <dt>{t("result1.observedBehavior")}</dt>
          <dd>{result.deconstruction.observed_behavior}</dd>
          <dt>{t("result1.fieldConstraints")}</dt>
          <dd>{result.deconstruction.field_constraints}</dd>
          <dt>{t("result1.apparentMotive")}</dt>
          <dd>{result.deconstruction.apparent_motive ?? t("result1.apparentMotiveNA")}</dd>
          <dt>{t("result1.observableOutcome")}</dt>
          <dd>{result.deconstruction.observable_outcome}</dd>
        </dl>
      )}

      {result.jargon_check && (
        <p className="reason" id={idPrefix && `${idPrefix}-jargon-check`}>
          {t("result1.jargonCheck")}
          {result.jargon_check.hit ? t("result1.hit") : t("result1.noHit")} —— {result.jargon_check.rationale}
        </p>
      )}
    </div>
  );
}
