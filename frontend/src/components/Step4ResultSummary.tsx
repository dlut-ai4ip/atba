import { useState } from "react";
import { CandidateCanvas } from "./CandidateCanvas";
import { CandidateCard } from "./CandidateCard";
import { CitedEvidenceItem } from "./CitedEvidenceItem";
import { Markdown } from "./Markdown";
import { useT } from "../i18n";
import type { MechanismGroundingRecord, PairwiseComparison, Step4Result } from "../types";

const STATUS_LABEL_KEY: Record<string, { key: string; tone: "ok" | "warn" | "block" }> = {
  passed: { key: "result4.statusPassed", tone: "ok" },
  blocked_agent_error: { key: "result1.statusAgentError", tone: "block" },
};

// Output of sub-step 0 — **this round replaces the TheoreticalGroundingCard that used to sit here**
// (the deep-dive retrieval into the anchor theory's current state has moved to Step3ResultSummary, see
// that file's AnchorTheoryGroundingCard): what's shown here is the retrieval result from "stepping
// outside the anchor theory to find a mechanism." donor_findings is allowed to be empty (when the
// selected candidate follows a deep-dive route within the same tradition) — an explanatory sentence is
// shown instead of leaving it blank, see MechanismGroundingRecord in atba/schemas.py.
function MechanismGroundingCard({ grounding, id }: { grounding: MechanismGroundingRecord; id?: string }) {
  const t = useT();
  return (
    <div className="theoretical-grounding-card" id={id}>
      <span className="summary-label examined-directions-label">{t("result4.mechanismGroundingHeader")}</span>
      <div className="summary-field-block">
        <span className="summary-label">{t("result4.abstractMechanismPattern")}</span>
        <Markdown text={grounding.abstract_mechanism_pattern} />
      </div>
      {grounding.donor_findings.length > 0 ? (
        <>
          <span className="summary-label">{t("result4.donorFindings", { n: grounding.donor_findings.length })}</span>
          <ul className="cited-evidence-list">
            {grounding.donor_findings.map((e, i) => (
              <CitedEvidenceItem key={i} e={e} />
            ))}
          </ul>
        </>
      ) : (
        <p className="note">{t("result4.noDonorFindings")}</p>
      )}
      {grounding.queries_tried.length > 0 && (
        <details className="queries-tried">
          <summary>{t("result3.queriesTried", { n: grounding.queries_tried.length })}</summary>
          <ol>
            {grounding.queries_tried.map((q, i) => (
              <li key={i}>
                <code>{q}</code>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

// The pairwise comparison judgments — the actual basis for the ranking (see the module-level comment
// preceding PairwiseComparison in atba/schemas.py). Collapsed by default: a reviewer usually only
// needs to see the final ranking/selection rationale; the full pairwise-comparison process is a detail
// meant to be expanded only when verifying "how was the ranking actually computed" — the same
// "process material collapsed by default" treatment as queries-tried.
function PairwiseComparisonsList({ comparisons, id }: { comparisons: PairwiseComparison[]; id?: string }) {
  const t = useT();
  if (comparisons.length === 0) return null;
  return (
    <details className="queries-tried" id={id}>
      <summary>{t("result4.pairwiseComparisons", { n: comparisons.length })}</summary>
      <ul className="cited-evidence-list">
        {comparisons.map((c, i) => (
          <li key={i}>
            <div className="summary-label">
              「{c.candidate_a}」 vs 「{c.candidate_b}」 ——{" "}
              {c.winner === "tie" ? t("result4.pairwiseTie") : `${t("result4.pairwiseWinnerPrefix")}${c.winner}`}
            </div>
            <Markdown text={c.rationale} />
          </li>
        ))}
      </ul>
    </details>
  );
}

// idPrefix — optional, only passed by Step4RunPage.tsx for "the round currently being displayed"
// (the last round, when there have been multiple manual retries, see the comment where it's called in
// that file), used to attach stable ids to the sections below for PageOutlineNav.tsx to jump to. When
// not passed (e.g. an old retry round that's been superseded in history), no id is attached, avoiding
// duplicate ids — invalid HTML — appearing on the same page.
export function Step4ResultSummary({ result, idPrefix }: { result: Step4Result; idPrefix?: string }) {
  const t = useT();
  const statusEntry = STATUS_LABEL_KEY[result.status];
  const status = statusEntry ? { label: t(statusEntry.key), tone: statusEntry.tone } : { label: result.status, tone: "warn" as const };
  const rankOf = (name: string) => {
    const i = result.ranked_candidate_names.indexOf(name);
    return i === -1 ? null : i + 1;
  };
  // Two views, list/canvas — list by default (lowest-risk change, doesn't affect existing usage), the
  // canvas view is the "flowith-like card canvas" the user requested: candidate nodes are laid out in
  // a ring connected by their pairwise-comparison relationships (pairwise_comparisons), not simple
  // decorative grouping, see CandidateCanvas.tsx. A pure frontend display preference, doesn't need to
  // persist to localStorage — every time this step is entered, the list is shown by default; the
  // canvas is an auxiliary view to "switch to for a look when you want to see the relationships," not
  // the persistent primary view.
  const [view, setView] = useState<"list" | "canvas">("list");
  return (
    <div className={`result-summary tone-${status.tone}`}>
      {/* Narrative content (status/revision notes/mechanism-grounding retrieval/selection
          rationale/pairwise comparisons) keeps a narrow column, laid out at paragraph width, for
          comfortable line length when reading long text; the candidate-card area isn't placed inside
          this narrow column — see .candidate-cards-section below, which needs to use the full width of
          the (now-widened) step-card, unconstrained by this layer's max-width. Split apart after user
          feedback "candidate cards should be able to spread out," see the .result-summary-prose/
          .candidate-cards-section comments in App.css. */}
      <div className="result-summary-prose">
        <div className="status-badge">{status.label}</div>
        {result.round_number > 1 && (
          <div className="revision-round-tag">
            {t("result4.revisionRound", { n: result.round_number })}
            {result.revision_instruction ? t("result4.revisionRoundSuffix") : ""}
          </div>
        )}
        <p className="note">{result.note}</p>

        {result.revision_instruction && (
          <div className="summary-field-block">
            <span className="summary-label">{t("result4.revisionInstruction")}</span>
            <Markdown text={result.revision_instruction} />
            {result.revision_target_candidate && (
              <p className="note">
                {t("result4.revisionTarget", {
                  candidate: result.revision_target_candidate,
                  field:
                    result.revision_target_field === "whole_candidate"
                      ? t("result4.revisionTargetWholeCandidate")
                      : result.revision_target_field ?? "",
                })}
              </p>
            )}
          </div>
        )}

        {result.mechanism_grounding && (
          <MechanismGroundingCard grounding={result.mechanism_grounding} id={idPrefix && `${idPrefix}-mechanism-grounding`} />
        )}

        {result.selection_rationale && (
          <div className="summary-field-block" id={idPrefix && `${idPrefix}-selection-rationale`}>
            <span className="summary-label">{t("result4.selectionRationale")}</span>
            <Markdown text={result.selection_rationale} />
          </div>
        )}

        <PairwiseComparisonsList comparisons={result.pairwise_comparisons} id={idPrefix && `${idPrefix}-pairwise-comparisons`} />
      </div>

      {result.candidates.length > 0 && (
        <div className="candidate-cards-section" id={idPrefix && `${idPrefix}-candidates`}>
          <div className="candidate-view-toggle-row">
            <span className="summary-label examined-directions-label">
              {t("result4.candidateSet", { n: result.candidates.length })}
            </span>
            <div className="candidate-view-toggle" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={view === "list"}
                className={`candidate-view-toggle-btn${view === "list" ? " active" : ""}`}
                onClick={() => setView("list")}
              >
                {t("result4.viewList")}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "canvas"}
                className={`candidate-view-toggle-btn${view === "canvas" ? " active" : ""}`}
                onClick={() => setView("canvas")}
              >
                {t("result4.viewCanvas")}
              </button>
            </div>
          </div>

          {view === "list" ? (
            <ol className="candidate-cards">
              {[...result.candidates]
                .sort((a, b) => (rankOf(a.candidate_name) ?? 99) - (rankOf(b.candidate_name) ?? 99))
                .map((c, i) => (
                  <CandidateCard
                    key={i}
                    candidate={c}
                    rank={rankOf(c.candidate_name)}
                    isSelected={c.candidate_name === result.selected_candidate_name}
                    isTied={result.tied_candidate_names.includes(c.candidate_name)}
                  />
                ))}
            </ol>
          ) : (
            <CandidateCanvas
              candidates={result.candidates}
              rankedNames={result.ranked_candidate_names}
              selectedName={result.selected_candidate_name}
              tiedNames={result.tied_candidate_names}
              comparisons={result.pairwise_comparisons}
            />
          )}
        </div>
      )}
    </div>
  );
}
