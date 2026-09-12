import { CitedEvidenceItem } from "./CitedEvidenceItem";
import { Markdown } from "./Markdown";
import { useT } from "../i18n";
import type { InterrogationQuestionType, InterrogationVerdict, Step5Result } from "../types";

const STATUS_LABEL_KEY: Record<string, { key: string; tone: "ok" | "warn" | "block" }> = {
  passed: { key: "result5.statusPassed", tone: "ok" },
  // blocked_unresolved isn't an agent-call failure — it's the candidate theory failing to survive
  // adversarial interrogation across several consecutive rounds under the current line of thinking,
  // needing a human judgment call on whether to switch directions; the same "legitimate but needs
  // human review" nature as no_gap_found (step 3), using warn rather than block.
  blocked_unresolved: { key: "result5.statusUnresolved", tone: "warn" },
  blocked_agent_error: { key: "result1.statusAgentError", tone: "block" },
};

const QUESTION_TYPE_LABEL_KEY: Record<InterrogationQuestionType, string> = {
  falsifiability: "result5.qFalsifiability",
  boundary_conditions: "result5.qBoundaryConditions",
  relabeling_suspicion: "result5.qRelabelingSuspicion",
};

const VERDICT_LABEL_KEY: Record<InterrogationVerdict, string> = {
  withstands: "result5.verdictWithstands",
  weak: "result5.verdictWeak",
  fails: "result5.verdictFails",
};

const VERDICT_TONE: Record<InterrogationVerdict, "ok" | "warn" | "block"> = {
  withstands: "ok",
  weak: "warn",
  fails: "block",
};

export function Step5ResultSummary({ result }: { result: Step5Result }) {
  const t = useT();
  const statusEntry = STATUS_LABEL_KEY[result.status];
  const status = statusEntry ? { label: t(statusEntry.key), tone: statusEntry.tone } : { label: result.status, tone: "warn" as const };
  return (
    <div className={`result-summary tone-${status.tone}`}>
      <div className="status-badge">{status.label}</div>
      <p className="note">{result.note}</p>

      {result.interrogated_candidate_name && (
        <div className="research-question-card">
          <span className="summary-label">
            {t("result5.interrogatedCandidate")}
            {result.overall_verdict && (
              <span className={`verdict-badge tone-${VERDICT_TONE[result.overall_verdict]}`}>
                {t(VERDICT_LABEL_KEY[result.overall_verdict])}
              </span>
            )}
          </span>
          <p className="research-question-text">{result.interrogated_candidate_name}</p>
        </div>
      )}

      {result.exchanges.length > 0 && (
        <>
          <span className="summary-label examined-directions-label">
            {t("result5.exchangeRecord", { n: result.exchanges.length })}
          </span>
          <ol className="interrogation-records">
            {result.exchanges.map((ex, i) => (
              <li key={i} className={`interrogation-record tone-${VERDICT_TONE[ex.verdict]}`}>
                <div className="direction-record-header">
                  <span className="direction-record-name">{t(QUESTION_TYPE_LABEL_KEY[ex.question_type])}</span>
                  <span className={`verdict-badge tone-${VERDICT_TONE[ex.verdict]}`}>{t(VERDICT_LABEL_KEY[ex.verdict])}</span>
                </div>
                <p className="interrogation-question">{ex.question}</p>
                <div className="direction-record-verdict">
                  <Markdown text={ex.assessment} />
                </div>
                {/* Usually only a relabeling_suspicion-type follow-up carries actual retrieved
                    literature — independently verifying "is this just an old construct under a new
                    name" must be traceable back to the retrieval results, not merely paraphrased in
                    assessment, see InterrogationRecord.cited_evidence in atba/schemas.py. */}
                {ex.cited_evidence.length > 0 && (
                  <ul className="cited-evidence-list">
                    {ex.cited_evidence.map((e, j) => (
                      <CitedEvidenceItem key={j} e={e} />
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        </>
      )}

      {result.unanswered_weaknesses.length > 0 && (
        <div className="summary-field-block">
          <span className="summary-label">{t("result5.unansweredWeaknesses")}</span>
          <ul className="unanswered-weaknesses">
            {result.unanswered_weaknesses.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {result.loop_history.length > 1 && (
        <>
          <span className="summary-label examined-directions-label">
            {t("result5.loopHistory", { n: result.loop_history.length })}
          </span>
          <ol className="loop-history">
            {result.loop_history.map((h, i) => (
              <li key={i} className={`loop-history-item tone-${VERDICT_TONE[h.overall_verdict]}`}>
                <span className="direction-record-name">
                  {t("result5.roundLabel", { n: h.round_number })} · {h.interrogated_candidate_name}
                </span>
                <span className={`verdict-badge tone-${VERDICT_TONE[h.overall_verdict]}`}>
                  {t(VERDICT_LABEL_KEY[h.overall_verdict])}
                </span>
                {h.loop_back_instruction && (
                  <p className="loop-back-instruction">{t("result5.loopBackInstruction", { text: h.loop_back_instruction })}</p>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
