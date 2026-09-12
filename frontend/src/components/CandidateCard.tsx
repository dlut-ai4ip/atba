import { Markdown } from "./Markdown";
import { useT } from "../i18n";
import type { CandidateTheory } from "../types";

// Factored into its own file (not a private function inside Step4ResultSummary.tsx) because
// CandidateCanvas.tsx's detail popover needs to reuse the exact same candidate-card rendering — the
// candidate detail content seen in both views (list/canvas) must match verbatim, not each maintain its
// own copy that could drift apart. Putting it back inside Step4ResultSummary.tsx and exporting it from
// there would create a circular import with CandidateCanvas.tsx (Step4ResultSummary imports
// CandidateCanvas to render the canvas view, and CandidateCanvas would need to import CandidateCard
// back) — factoring it into a standalone file means both sides only import one-way from here, and this
// problem doesn't arise.

export const BORROWING_PATTERN_LABEL_KEY: Record<string, string> = {
  within_tradition: "result4.borrowingPatternWithinTradition",
  adjacent_bridging: "result4.borrowingPatternAdjacent",
  cross_tradition_borrowing: "result4.borrowingPatternCrossTradition",
};

export function CandidateCard({
  candidate,
  rank,
  isSelected,
  isTied,
}: {
  candidate: CandidateTheory;
  rank: number | null;
  isSelected: boolean;
  isTied: boolean;
}) {
  const t = useT();
  const te = candidate.theory_elements;
  const v = candidate.virtue_scores;
  return (
    <li className={`candidate-card${isSelected ? " candidate-selected" : ""}`}>
      <div className="candidate-card-header">
        {rank !== null && <span className="candidate-rank">#{rank}</span>}
        <span className="candidate-name">{candidate.candidate_name}</span>
        {isSelected && <span className="candidate-tag candidate-tag-selected">{t("result4.tagSelected")}</span>}
        {isTied && <span className="candidate-tag candidate-tag-tied">{t("result4.tagTied")}</span>}
        {/* The null-hypothesis baseline — uses a neutral color (not selected's accent or tied's
            warn-style emphasis color); it's not a mark of "performing well," it's just labeling "this
            is the one used as the comparison point," see the comment on
            CandidateTheory.is_baseline in types.ts. */}
        {candidate.is_baseline && <span className="candidate-tag candidate-tag-baseline">{t("result4.tagBaseline")}</span>}
      </div>

      {/* The five theory elements — atba/schemas.py's TheoryElements, shown as a compact definition
          list, not via Markdown (each value is usually one or two sentences, not long text needing
          paragraphs — the .fields dl/dt/dd layout is more compact and easier to scan) */}
      <dl className="fields candidate-theory-elements">
        <dt>{t("result4.x")}</dt>
        <dd>{te.x}</dd>
        <dt>{t("result4.y")}</dt>
        <dd>{te.y}</dd>
        <dt>{t("result4.relationForm")}</dt>
        <dd>{te.relation_form}</dd>
        <dt>{t("result4.mechanism")}</dt>
        <dd>{te.mechanism}</dd>
        <dt>{t("result4.assumption")}</dt>
        <dd>{te.assumption}</dd>
        {te.boundary_conditions && (
          <>
            <dt>{t("result4.boundaryConditionsShort")}</dt>
            <dd>{te.boundary_conditions}</dd>
          </>
        )}
      </dl>

      <div className="summary-field">
        <span className="summary-label">{t("result4.borrowingPattern")}</span>
        <span className="assumption-type-badge">
          {t(BORROWING_PATTERN_LABEL_KEY[candidate.mechanism_borrowing_pattern] ?? candidate.mechanism_borrowing_pattern)}
        </span>
      </div>
      <div className="summary-field-block">
        <span className="summary-label">{t("result4.borrowedConstruct")}</span>
        <Markdown text={candidate.borrowed_or_modified_construct} />
      </div>
      {/* disanalogy_note is only set for a cross-tradition borrowing — this self-disclosure of "where
          it doesn't carry over" is itself part of the candidate's quality, not a dispensable
          disclaimer, so it's placed right after the borrowed construct, not collapsed, see the
          module-level comment on CandidateTheory in schemas.py (echoing Oswick, Fleming & Hanlon
          2011's critique of "domesticated borrowing"). */}
      {candidate.disanalogy_note && (
        <div className="summary-field-block">
          <span className="summary-label">{t("result4.disanalogyNote")}</span>
          <Markdown text={candidate.disanalogy_note} />
        </div>
      )}
      <div className="summary-field-block">
        <span className="summary-label">{t("result4.whyInsufficient")}</span>
        <Markdown text={candidate.why_existing_insufficient} />
      </div>
      <div className="summary-field-block">
        <span className="summary-label">{t("result4.explanation")}</span>
        <Markdown text={candidate.explanation_of_phenomenon} />
      </div>
      <div className="summary-field-block">
        <span className="summary-label">{t("result4.mutualExclusivity")}</span>
        <Markdown text={candidate.mutual_exclusivity_note} />
      </div>

      {/* The four-virtue scoring — this round changed to a "reference only" role: the final ranking
          is no longer derived directly from these four scores, it's computed from
          pairwise_comparisons' pairwise win-counting instead (see below in Step4ResultSummary and
          _rank_candidates in atba/step4.py); the scores + reasoning are still shown here for a
          reviewer's reference/diagnosis. */}
      <div className="virtue-scores">
        <span className="summary-label">{t("result4.virtueScores")}</span>
        <div className="virtue-scores-row">
          <span className="virtue-score">{t("result4.consilience")} {v.consilience}</span>
          <span className="virtue-score">{t("result4.coherence")} {v.coherence}</span>
          <span className="virtue-score">{t("result4.parsimony")} {v.parsimony}</span>
          <span className="virtue-score">{t("result4.precision")} {v.precision}</span>
        </div>
        <Markdown text={v.graph_based_rationale} />
      </div>
    </li>
  );
}
