import { CitedEvidenceItem } from "./CitedEvidenceItem";
import { Markdown } from "./Markdown";
import { useT } from "../i18n";
import type {
  DirectionSearchRecord,
  HitLevel,
  ProblematizedAssumptionType,
  Step3Result,
  TheoreticalGroundingRecord,
} from "../types";

// The deep retrieval run on the anchor theoretical direction — **moved from step 4 to here this
// round** (see the module-level comment on TheoreticalGroundingRecord in atba/schemas.py: this deep
// dive is part of step 3's "relationship to the anchor theory itself," while step 4's retrieval budget
// went entirely toward "stepping outside the anchor theory to find a mechanism," see
// Step4ResultSummary's MechanismGroundingCard). Expanded by default, not collapsed: this retrieval is
// the main background basis for the research_question, not a dispensable supplementary detail.
function AnchorTheoryGroundingCard({ grounding, id }: { grounding: TheoreticalGroundingRecord; id?: string }) {
  const t = useT();
  return (
    <div className="theoretical-grounding-card" id={id}>
      <span className="summary-label examined-directions-label">
        {t("result3.anchorGroundingHeader", { anchor: grounding.anchor_theory })}
      </span>
      <div className="summary-field-block">
        <span className="summary-label">{t("result4.boundaryConditions")}</span>
        <Markdown text={grounding.established_boundary_conditions} />
      </div>
      <div className="summary-field-block">
        <span className="summary-label">{t("result4.internalTensions")}</span>
        <Markdown text={grounding.internal_tensions_or_gaps} />
      </div>
      {grounding.key_findings.length > 0 && (
        <>
          <span className="summary-label">{t("result4.keyFindings", { n: grounding.key_findings.length })}</span>
          <ul className="cited-evidence-list">
            {grounding.key_findings.map((e, i) => (
              <CitedEvidenceItem key={i} e={e} />
            ))}
          </ul>
        </>
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

// Producing a research question is a two-tier structure (see the module-level comment on
// ResearchApproach/GapType in atba/schemas.py): tier 1 is research_approach (gap_spotting/
// problematization), and tier 2 under gap_spotting is gap_type (theory_void/mechanism_gap) — this
// label composes the final display copy from "tier 1 + tier 2," not three options at the same level
// each looked up separately. This stores i18n keys; the actual copy is in result3.* in
// ../i18n/translations.ts.
const GAP_TYPE_LABEL_KEY: Record<string, string> = {
  theory_void: "result3.gapTypeTheoryVoid",
  mechanism_gap: "result3.gapTypeMechanismGap",
};

const ASSUMPTION_TYPE_LABEL_KEY: Record<ProblematizedAssumptionType, string> = {
  in_house: "result3.assumptionInHouse",
  root_metaphor: "result3.assumptionRootMetaphor",
  paradigm: "result3.assumptionParadigm",
  ideology: "result3.assumptionIdeology",
  field: "result3.assumptionField",
};

// Per Whetten's (1989) distinction between an "anomaly" and merely being "uncovered," see
// MechanismGapCharacterization in atba/schemas.py — tier 3, appearing only when
// gap_type=mechanism_gap.
const GAP_CHARACTERIZATION_LABEL_KEY: Record<string, string> = {
  uncharted: "result3.charUncharted",
  anomalous_reversal: "result3.charAnomalousReversal",
};

const STATUS_LABEL_KEY: Record<string, { key: string; tone: "ok" | "warn" | "block" }> = {
  passed: { key: "result3.statusPassed", tone: "ok" },
  // no_gap_found isn't a failure state — every candidate direction being judged to "not constitute a
  // puzzle" is a legitimate conclusion, it just needs a human to review whether to add more
  // theoretical directions or set the phenomenon aside; the tone uses warn (yellow) rather than block
  // (red), consistent with PlanPanel's needs_input mapping.
  no_gap_found: { key: "result3.statusNoGap", tone: "warn" },
  // retrieval_unavailable is a genuine infrastructure failure (e.g. missing SCOPUS_API_KEY), and must
  // be clearly distinguished from no_gap_found — the user must not be misled into thinking "the
  // phenomenon is already explained by existing theory," see the Step3Status docstring in
  // atba/schemas.py.
  retrieval_unavailable: { key: "result3.statusRetrievalDown", tone: "block" },
  blocked_agent_error: { key: "result1.statusAgentError", tone: "block" },
};

const HIT_LEVEL_LABEL_KEY: Record<HitLevel, string> = {
  exact_mechanism: "result3.hitExactMechanism",
  theory_family: "result3.hitTheoryFamily",
  discipline_broad: "result3.hitDisciplineBroad",
  exhausted_no_hit: "result3.hitExhaustedNoHit",
  retrieval_unavailable: "result3.hitRetrievalFault",
  not_examined: "result3.hitNotExamined",
};

// The hit tier itself already carries a difference in credibility (exact mechanism > theory family >
// broad discipline); color intensity/whether it's a fault provides a layer of visual distinction, not
// all the same gray — a reviewer needs to see "how solid is this evidence" at a glance.
const HIT_LEVEL_TONE: Record<HitLevel, "strong" | "weak" | "fault"> = {
  exact_mechanism: "strong",
  theory_family: "weak",
  discipline_broad: "weak",
  exhausted_no_hit: "weak",
  retrieval_unavailable: "fault",
  not_examined: "fault",
};

function DirectionCard({ record }: { record: DirectionSearchRecord }) {
  const t = useT();
  return (
    <li className={`direction-record tone-${HIT_LEVEL_TONE[record.hit_level]}`}>
      <div className="direction-record-header">
        <span className="direction-record-name">{record.theory_name}</span>
        <span className="hit-level-badge">{t(HIT_LEVEL_LABEL_KEY[record.hit_level])}</span>
      </div>
      <div className="direction-record-verdict">
        <Markdown text={record.verdict} />
      </div>

      {record.queries_tried.length > 0 && (
        <details className="queries-tried">
          <summary>{t("result3.queriesTried", { n: record.queries_tried.length })}</summary>
          <ol>
            {record.queries_tried.map((q, i) => (
              <li key={i}>
                <code>{q}</code>
              </li>
            ))}
          </ol>
        </details>
      )}

      {record.cited_evidence.length > 0 && (
        <ul className="cited-evidence-list">
          {record.cited_evidence.map((e, i) => (
            <CitedEvidenceItem key={i} e={e} />
          ))}
        </ul>
      )}
    </li>
  );
}

// Shown when research_approach=problematization — the structure corresponds to
// atba/schemas.py's ProblematizationDetail: the identified assumption → supporting evidence → why
// it's worth challenging → the alternative assumption → Davis's (1971) three-way self-check, each
// field displayed in its own block rather than mashed into one paragraph, so a reviewer can check off
// each item against Alvesson & Sandberg's (2011) methodology.
function ProblematizationCard({ detail }: { detail: NonNullable<Step3Result["problematization_detail"]> }) {
  const t = useT();
  return (
    <div className="problematization-card">
      <div className="summary-field">
        <span className="summary-label">{t("result3.challengedAssumptionType")}</span>
        <span className="assumption-type-badge">{t(ASSUMPTION_TYPE_LABEL_KEY[detail.assumption_type])}</span>
      </div>
      <div className="summary-field-block">
        <span className="summary-label">{t("result3.identifiedAssumption")}</span>
        <Markdown text={detail.identified_assumption} />
      </div>
      {detail.assumption_evidence.length > 0 && (
        <>
          <span className="summary-label">{t("result3.assumptionEvidence")}</span>
          <ul className="cited-evidence-list">
            {detail.assumption_evidence.map((e, i) => (
              <CitedEvidenceItem key={i} e={e} />
            ))}
          </ul>
        </>
      )}
      <div className="summary-field-block">
        <span className="summary-label">{t("result3.whyWorthChallenging")}</span>
        <Markdown text={detail.why_worth_challenging} />
      </div>
      <div className="summary-field-block">
        <span className="summary-label">{t("result3.alternativeAssumption")}</span>
        <Markdown text={detail.alternative_assumption} />
      </div>
      <div className="summary-field-block">
        <span className="summary-label">{t("result3.davisCheck")}</span>
        <Markdown text={detail.interestingness_check} />
      </div>
    </div>
  );
}

// idPrefix — the same approach as Step4ResultSummary.tsx: only passed by Step3RunPage.tsx for "the
// round currently being displayed," attaching stable ids to the sections below for PageOutlineNav.tsx
// to jump to; when not passed, no id is attached, avoiding duplicate ids when multiple retry rounds
// stack up on the same page.
export function Step3ResultSummary({ result, idPrefix }: { result: Step3Result; idPrefix?: string }) {
  const t = useT();
  const statusEntry = STATUS_LABEL_KEY[result.status];
  const status = statusEntry ? { label: t(statusEntry.key), tone: statusEntry.tone } : { label: result.status, tone: "warn" as const };
  return (
    <div className={`result-summary tone-${status.tone}`}>
      <div className="status-badge">{status.label}</div>
      <p className="note">{result.note}</p>

      {result.research_question && (
        <div className="research-question-card" id={idPrefix && `${idPrefix}-research-question`}>
          <span className="summary-label">
            {t("result3.researchQuestion")} ·{" "}
            {result.research_approach === "problematization"
              ? t("result3.approachProblematization")
              : result.gap_type
                ? t("result3.approachGapSpotting", { gapType: t(GAP_TYPE_LABEL_KEY[result.gap_type]) })
                : result.research_approach}
            {result.anchor_theory_direction && <> · {t("result3.anchor", { name: result.anchor_theory_direction })}</>}
          </span>
          <p className="research-question-text">{result.research_question}</p>
          {result.mechanism_gap_characterization && (
            <div className="summary-field">
              <span className="summary-label">{t("result3.gapNature")}</span>
              <span
                className={
                  result.mechanism_gap_characterization === "anomalous_reversal"
                    ? "assumption-type-badge"
                    : undefined
                }
              >
                {t(GAP_CHARACTERIZATION_LABEL_KEY[result.mechanism_gap_characterization])}
              </span>
            </div>
          )}
          {result.problematization_detail && <ProblematizationCard detail={result.problematization_detail} />}
        </div>
      )}

      {result.anchor_theory_grounding && (
        <AnchorTheoryGroundingCard grounding={result.anchor_theory_grounding} id={idPrefix && `${idPrefix}-anchor-grounding`} />
      )}

      {/* These three fields are multi-point long text the agent writes (commonly a
          "(1) ... (2) ... (3) ..."-style itemized argument), using .summary-field-block (the label on
          its own line) + Markdown rendering (a real blank line between paragraphs is what actually
          creates a new paragraph, per the formatting requirement in the corresponding field's
          description in atba/schemas.py) — can't use the side-by-side .summary-field + plain text
          layout, or multi-point content would get crammed into one hard-to-read block */}
      {result.cross_source_tension_note && (
        <div className="summary-field-block" id={idPrefix && `${idPrefix}-cross-source-tension`}>
          <span className="summary-label">{t("result3.crossSourceTension")}</span>
          <Markdown text={result.cross_source_tension_note} />
        </div>
      )}

      {result.coverage_report && (
        <div className="summary-field-block" id={idPrefix && `${idPrefix}-coverage-report`}>
          <span className="summary-label">{t("result3.coverageReport")}</span>
          <Markdown text={result.coverage_report} />
        </div>
      )}

      {result.rationale && (
        <div className="summary-field-block" id={idPrefix && `${idPrefix}-rationale`}>
          <span className="summary-label">{t("result3.rationale")}</span>
          <Markdown text={result.rationale} />
        </div>
      )}

      {result.examined_directions.length > 0 && (
        <>
          <span className="summary-label examined-directions-label" id={idPrefix && `${idPrefix}-examined-directions`}>
            {t("result3.examinedDirections", { n: result.examined_directions.length })}
          </span>
          <ol className="direction-records">
            {result.examined_directions.map((r, i) => (
              <DirectionCard key={i} record={r} />
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
