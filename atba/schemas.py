"""Data structures for Step 1 (Phenomenon Input & Pre-check).

Field names correspond one-to-one with the output schema in the technical appendix's "Step 1"
section, and are isomorphic with the "phenomenon_deconstruction" sub-schema described in the same
document's appendix C' retrodiction-validation extraction schema, so it can be used directly as the
extraction structure for the retrodiction validation test set in the future (the earlier "historical
quartet library" concept, meant to double as both live-retrieval-comparison infrastructure, has been
retired — see appendix C''s revision notes; retrieval comparison is now handled entirely by D.4's
general-purpose corpus search).

**Field names switched to English (this round's revision)**: field names used to be Chinese (e.g.
"行为主体"), isomorphic with the retrodiction-extraction schema's Chinese field names; now both sides
have switched to English identifiers together, keeping the isomorphism unchanged, just with both using
English keys. Only the keys changed, not the language of the research content itself — content
actually extracted from a paper is still in Chinese where applicable, and the language of Step 1's
model-produced field *values* is still governed by the `lang` parameter (zh/en) — "English" here refers
specifically to the schema structure (field names), not the content language.

Uses pydantic BaseModel rather than dataclass: these classes carry two roles at once —
(1) the runtime counterpart of atba/schemas/step1.schema.json, the output_type fed to the pydantic-ai
    Agent, which the model must produce results matching;
(2) the FastAPI endpoint's response body (.model_dump() is directly serializable).
The two roles ought to be the same definition to begin with — no need to separately maintain a
dataclass + a JSON schema that can drift apart.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class CausalPresuppositionCheck(BaseModel):
    """The causal-presupposition checker's output (checks the raw input text, not the phenomenon
    deconstruction result).

    A hit no longer blocks the pipeline (an earlier version escalated to human review on a hit and
    required the user to rewrite the input — too heavy-handed, and it penalized the entirely normal
    case of "the user already brought their own guess/hypothesis"). On a hit, the user's proposed
    causal explanation is additionally extracted cleanly (`extracted_explanation`); the phenomenon
    deconstruction itself still keeps only pure observational content, without mixing in this
    explanation. `extracted_explanation` is left for step 4's candidate generation to reference as
    "one candidate guess the user already brought," not adopted directly as a conclusion, nor treated
    as something the pipeline has endorsed.
    """

    hit: bool
    evidence_snippets: list[str]
    rationale: str
    extracted_explanation: Optional[str] = Field(
        default=None,
        description="When hit=true: cleanly extract/paraphrase the user's proposed causal explanation, for later steps to reference; empty when there's no hit",
    )


class TheoryJargonCheck(BaseModel):
    """The theory-jargon checker's output (checks the phenomenon_deconstruction field in the same
    output — the two are sibling fields at the same level of Step1Output; semantically the jargon check
    depends on the deconstruction's content to check against, but structurally it isn't nested inside
    it)."""

    hit: bool
    flagged_terms: list[str]
    rationale: str


class PhenomenonDeconstruction(BaseModel):
    """The phenomenon-deconstruction output schema: {actor, observed_behavior, field_constraints,
    apparent_motive, observable_outcome}.

    The theory-jargon check is no longer nested inside this — it's essentially the same kind of thing
    as the causal-presupposition check (a hit + evidence/terms + rationale check result), so it's been
    lifted to the top level of Step1Output, keeping the four check blocks
    (prior_expectation_identification/causal_presupposition_check/theory_jargon_check/
    phenomenon_deconstruction) at the same nesting level, structurally symmetric.

    Field names are kept isomorphic with the "phenomenon_deconstruction" sub-schema described in the
    technical appendix's appendix C' retrodiction-extraction schema, without renaming to accommodate
    purely statistical/non-behavioral phenomena. Instead, adapted in two ways:
    (1) "actor"/"observed_behavior" are loosened in the prompt to mean "the unit of analysis/entity
        involved" and "the observed phenomenon/pattern," without requiring an anthropomorphized
        "behavior";
    (2) "apparent_motive" is made optional — a purely statistical finding (e.g. a correlation between
        macro variables) often has no attributable behavioral motive; the field is allowed to be left
        blank rather than forcing the model to invent a motive that doesn't exist.
    """

    actor: str
    observed_behavior: str
    field_constraints: str
    apparent_motive: Optional[str] = Field(
        default=None,
        description="The apparent motive of the party involved; if the phenomenon has no attributable behavioral actor (e.g. a purely statistical/macro-level finding), leave blank rather than inventing one",
    )
    observable_outcome: str


class PriorExpectationIdentification(BaseModel):
    """Prior-expectation identification: the agent judges for itself, from the input text (+ an
    optional user hint), whether "this phenomenon has a comparable prior expectation/theoretical
    tradition," rather than requiring the caller to manually confirm this before calling.

    Note this is not the real retrieval envisioned by D.4 — this version has no retrieval service
    wired up here; "identified=true" only means the agent, from the input information and its own
    knowledge, can give a reasonable description of a prior expectation — it does not constitute the
    validity guarantee step 3's "research question" requires, which must be traceable to actual
    literature; step 3's retrieval requirement is unaffected by "identified=true" here, and still
    independently runs its own full process. This step only avoids making the user manually confirm
    with a checkbox before proceeding when the information is already sufficient.
    """

    identified: bool
    prior_expectation_description: Optional[str] = Field(
        default=None, description="When identified=true: what the agent believes the prior expectation/theoretical tradition is"
    )
    clarifying_question: Optional[str] = Field(
        default=None, description="When identified=false: the specific clarifying question to ask the user"
    )
    candidate_options: list[str] = Field(
        default_factory=list,
        description="When identified=false: candidate directions offered for the user to choose from (the user may also skip these and type freely)",
    )
    rationale: str


class Step1Output(BaseModel):
    """The complete structured result step 1's single agent run requires the model to produce in one
    shot.

    Following the design "one agent loop per stage, completed within that loop," four independent
    checks/judgments are merged into the same output object of a single call, with the four fields kept
    at the same nesting level, not containing one another:
    - prior_expectation_identification: whether there's enough information to move to the next step
    - causal_presupposition_check: whether the raw input text already carries a causal explanation
    - theory_jargon_check: whether the phenomenon-deconstruction field has theoretical jargon mixed in
      (checks the phenomenon_deconstruction field below — semantically dependent on it, but still a
      sibling field structurally)
    - phenomenon_deconstruction: the five extracted purely-observational fields
    """

    prior_expectation_identification: PriorExpectationIdentification
    causal_presupposition_check: CausalPresuppositionCheck
    theory_jargon_check: TheoryJargonCheck
    phenomenon_deconstruction: PhenomenonDeconstruction


class Step1Status(str, Enum):
    """Step 1's terminal states. The several "not passed" states correspond to different reasons for
    escalating/sending back/asking for more information, and must not be conflated."""

    OK = "passed"
    NEEDS_CLARIFICATION = "needs_clarification"
    BLOCKED_JARGON_PERSISTENT = "blocked_jargon_persistent"
    BLOCKED_AGENT_ERROR = "blocked_agent_error"


class TokenUsage(BaseModel):
    """The token amount consumed by one agent run — shared by all six steps' Result classes (each
    Step*Result's own `usage` field is this type), mapping directly to the handful of user-meaningful
    fields on pydantic-ai's `AgentRunResult.usage` (`RunUsage`), rather than persisting every internal
    detail of RunUsage (things like cache_write_tokens/opentelemetry_attributes) verbatim. When step
    6's report page aggregates and shows "how many tokens did this run cost in total," it's simply
    summing this field across steps 1 through 6 (including each round's usage inside step 5's loop),
    see atba/step6.py's _aggregate_run_usage."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            requests=self.requests + other.requests,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class Step1Result(BaseModel):
    """Step 1's complete output — returns the same structure whether it succeeded or got intercepted
    at any point, to make persisting the audit trail straightforward."""

    run_id: str
    status: Step1Status
    raw_text: str
    # An optional prior-expectation/theoretical-tradition hint the caller (a person or the frontend
    # form) may supply — just auxiliary information for the agent, not a precondition that must be
    # confirmed first; the agent will first try to identify this on its own from raw_text, and the hint
    # only lowers the odds of a NEEDS_CLARIFICATION follow-up. Also reused when resubmitting to answer a
    # NEEDS_CLARIFICATION follow-up question.
    prior_expectation_hint: Optional[str] = None
    prior_expectation: Optional[PriorExpectationIdentification] = None
    causal_check: Optional[CausalPresuppositionCheck] = None
    jargon_check: Optional[TheoryJargonCheck] = None
    deconstruction: Optional[PhenomenonDeconstruction] = None
    note: str = ""
    # Audit-trail field: records which provider/model this output actually came from — running the
    # same phenomenon under a different vendor/model and comparing the difference is also audit
    # information that needs to be traceable, not just the "reference list" kind of traceability in
    # step 6.
    provider: str = ""
    model: str = ""
    # The full deserialized result of pydantic-ai's AgentRunResult.all_messages_json(): includes every
    # ModelRetry round-trip triggered by a theory-jargon-check hit — the auditable evidence for the
    # design "the loop completes within a single stage."
    audit_trail: Optional[list[dict[str, Any]]] = Field(default=None, repr=False)
    # The tokens this agent run itself consumed — excludes any other calls the caller (e.g. step 5's
    # loop controller) separately initiates, which each land in their own Result.usage; see
    # atba/step6.py's _aggregate_run_usage for the aggregation.
    usage: Optional[TokenUsage] = None

    def is_ok(self) -> bool:
        return self.status == Step1Status.OK


class CandidateTheoryDirection(BaseModel):
    """A single candidate theoretical direction produced by step 2. Only scopes "which direction to
    look in," without judging whether a gap exists or requiring already-traceable literature — that's
    step 3's job."""

    theory_name: str = Field(description="The theory/theoretical-tradition name")
    relevance_rationale: str = Field(
        description="A preliminary explanation of why this direction might be relevant to the phenomenon — must point to which specific part of the phenomenon it corresponds to, not just name the theory"
    )


class Step2Output(BaseModel):
    """The complete structured result step 2's single agent run requires the model to produce: a set of
    candidate theoretical directions.

    Much simpler than step 1 — a single judgment, with no verification loop needing automatic in-run
    retries like the theory-jargon check. min_length=2: doesn't accept turning in just one "most
    likely" direction — step 2's value lies precisely in not narrowing to a single direction too early,
    letting step 3's retrieval results test which direction actually holds up on their own.
    """

    candidate_theory_directions: list[CandidateTheoryDirection] = Field(
        min_length=2,
        description="Does not require a single answer — produce several potentially-relevant theoretical directions for step 3 to retrieve and verify one by one",
    )


class Step2Status(str, Enum):
    """Step 2's terminal states. There's no NEEDS_CLARIFICATION/BLOCKED_JARGON_PERSISTENT branch like
    step 1 — step 2 is just an associative match of theoretical directions against a phenomenon card
    that has already passed step 1's checks; in principle it always produces a result, and the only
    failure mode is the model call itself breaking."""

    OK = "passed"
    BLOCKED_AGENT_ERROR = "blocked_agent_error"


class Step2Result(BaseModel):
    """Step 2's complete output. Same pattern as Step1Result: run_id + status + persisted + audit
    trail."""

    run_id: str
    status: Step2Status
    candidate_theory_directions: list[CandidateTheoryDirection] = Field(default_factory=list)
    # The subset of candidate_theory_directions the user checked off to send into step 3's retrieval —
    # not produced by the agent, a manual filtering result (see atba/step2.py's save_step2_selection).
    # Empty means "not yet selected," not "selected zero" — once step 3 is implemented, this field
    # should be its input source, rather than asking the user to select again on step 3's page.
    selected_theory_directions: list[CandidateTheoryDirection] = Field(default_factory=list)
    note: str = ""
    provider: str = ""
    model: str = ""
    audit_trail: Optional[list[dict[str, Any]]] = Field(default=None, repr=False)
    # The tokens this agent run itself consumed — excludes any other calls the caller (e.g. step 5's
    # loop controller) separately initiates, which each land in their own Result.usage; see
    # atba/step6.py's _aggregate_run_usage for the aggregation.
    usage: Optional[TokenUsage] = None

    def is_ok(self) -> bool:
        return self.status == Step2Status.OK


class ResearchApproach(str, Enum):
    """The **first tier** of producing a research question: gap-spotting or problematization —
    corresponding to the top-level framework of Alvesson & Sandberg's (2011) "Generating Research
    Questions Through Problematization" (AMR 36(2): 247-271) itself, which is the paper's actual
    structure: two paths for constructing a research question are distinguished first, each with its
    own specific types (tier 2) underneath.

    **Changed this round from a "pick-one-of-three flat enum" to a "two-tier structure"**: an earlier
    design crammed theory_void/mechanism_gap/problematization into the same flat
    `ResearchQuestionType` enum, conflating "which path to take" (tier 1) with "which specific type
    within that path" (tier 2) — that's not the paper's actual structure; the paper explicitly states
    gap-spotting and problematization are "two starkly different ways of constructing a research
    question," each with its own subtype system (theory_void/mechanism_gap under gap-spotting; the five
    types of problematizable assumption A&S propose under problematization, see
    ProblematizedAssumptionType) — not three options at the same level.

    The two aren't mutually exclusive (the A&S original explicitly notes this): gap-spotting is
    management's dominant approach (empirical statistics A&S cite show ~93% of published research is
    gap-spotting), but tends to produce contributions that are "incremental but not very interesting";
    problematization is rarer and has a higher bar, but is more likely to produce theory that's
    "interesting" in Davis's (1971) sense, and hence more influential. By design, the agent isn't
    required to pick one upfront — instead, while retrieving and reading literature for a candidate
    direction, it applies both lenses at once (see problematization_skill.md), preferring
    problematization unless it fails the check of "not too obvious, not too absurd," in which case it
    falls back to gap-spotting — this is the A&S original's own position, not a shortcut this project
    invented."""

    GAP_SPOTTING = "gap_spotting"
    PROBLEMATIZATION = "problematization"


class GapType(str, Enum):
    """The **second tier** of producing a research question — used only when
    research_approach=gap_spotting, corresponding to the two gap types originally defined in the
    technical appendix's §A/§B. When research_approach=problematization, the corresponding tier-2 type
    is ProblematizationDetail.assumption_type (see ProblematizedAssumptionType), not this enum — the
    two paths' tier-2 type systems don't share the same field."""

    THEORY_VOID = "theory_void"  # Theory-void: after exhausting three-tier degrading retrieval + rewrite retries, genuinely no literature discusses this directly
    MECHANISM_GAP = "mechanism_gap"  # Mechanism-gap: relevant literature was found, but its mechanistic explanation doesn't cover some specific aspect of the phenomenon


class MechanismGapCharacterization(str, Enum):
    """The **third tier** of producing a research question — used only when gap_type=mechanism_gap
    (theory_void has no such tier: there's no literature to speak of, so "would applying the logic
    straightforwardly predict the opposite direction" is moot). Distinguishes two qualitatively
    different kinds of "gap." Per Whetten (1989)'s "What Constitutes a Theoretical Contribution?" (AMR
    14(4): 490-495): merely pointing out "existing theory doesn't cover this" is not by itself
    sufficient grounds for a theoretical contribution (original: "discovering that a mainstream model
    has low predictive validity ... does not by itself constitute a theoretical contribution. theorists
    need to understand why this anomaly exists") — the truly weighty evidence is "applying existing
    theory's core logic straightforwardly here would yield a prediction that contradicts/opposes the
    phenomenon"; in that case step 4's task isn't simply "filling a gap" but "revising the theory," a
    far stronger basis for contribution than mere non-coverage.

    This distinction was proven necessary in testing: in run b45f39c3's phenomenon, ODT's prediction
    for a same-cohort-peer reference frame (inverted-U) versus its prediction for a base-model reference
    frame (if the same balancing logic is applied straightforwardly, also inverted-U) — what was
    actually observed was the opposite, a U-shape. This isn't "ODT hasn't studied this" — it's "ODT's
    core logic predicts the wrong direction here" — but the original mechanism_gap type conflated these
    two cases, causing both step 4 and step 6 to treat it as merely "filling an unexplored gap,"
    weakening the stronger theoretical significance this phenomenon actually carried."""

    UNCHARTED = "uncharted"  # Existing theory genuinely hasn't studied this aspect, purely unexplored territory — fill the gap
    ANOMALOUS_REVERSAL = "anomalous_reversal"  # Applying existing theory's core logic straightforwardly here would yield a prediction that contradicts/opposes the phenomenon — not merely uncovered, but challenged by the phenomenon, requiring the theory to be revised


class ProblematizedAssumptionType(str, Enum):
    """The five types of problematizable assumption Alvesson & Sandberg (2011) propose, ordered from
    narrow to broad in scope/depth — the **tier-2** type for the research_approach=problematization
    path (symmetric to GapType, the tier-2 type for the gap_spotting path), used only under that path,
    to keep the agent from vaguely claiming "this assumption is problematic" without first
    characterizing which type the assumption it identified is, then constructing an alternative
    assumption using the method appropriate to that type (see problematization_skill.md).
    """

    IN_HOUSE = "in_house"  # An assumption shared within a specific theory/school (e.g. trait theory assuming leadership = individual traits)
    ROOT_METAPHOR = "root_metaphor"  # A metaphor/image for the object of study (e.g. metaphorizing organizational culture as a unity)
    PARADIGM = "paradigm"  # An ontological/epistemological/methodological assumption (e.g. a subject-object dualist view of capability)
    IDEOLOGY = "ideology"  # A political/moral/gender-related assumption (e.g. taking "why don't employees work harder" as a legitimate question by default)
    FIELD = "field"  # An assumption shared across multiple schools/paradigms, rarely questioned (e.g. "people are rational decision-makers," which bounded rationality challenges)


class CitedEvidence(BaseModel):
    """The specific literature evidence a research-question statement cites — not a paraphrase, it must
    be traceable back to a real retrieval result (echoing appendix B's "a research-question statement
    must come with a traceable citation"). The Scopus API doesn't return full text, so citations can
    only reach the abstract/metadata level — an inherent limitation of D.4's retrieval channel, not an
    extraction oversight in this project."""

    title: str
    authors: list[str] = Field(
        default_factory=list,
        description=(
            "The author list — must not be left as a placeholder. The two sources differ in "
            "completeness; prefer the more complete one: under this key's entitlement, "
            "search_scopus only returns the first author. get_paper_abstract internally goes through "
            "Semantic Scholar/OpenAlex, which return a full author list along the way (this tool must "
            "be called before deciding to cite anyway to look up the abstract, and the author list "
            "comes back in the same call, no extra call needed). Approach: stash search_scopus's "
            "(first-author) value first, then replace it with the more complete version once "
            "get_paper_abstract returns non-empty authors; only fall back to search_scopus's first "
            "author if neither source finds any authors — never leave it blank. Even when "
            "get_paper_abstract doesn't find an abstract, its authors should still be used if "
            "non-empty — the abstract and the authors are two independent things."
        ),
    )
    year: Optional[str] = None
    doi: Optional[str] = None
    source_title: Optional[str] = Field(default=None, description="The journal name")
    relevant_snippet: str = Field(description="The specific excerpt or point from the abstract/metadata that supports the judgment — must not be just the paper's title")
    abstract: Optional[str] = Field(
        default=None,
        description=(
            "The raw full abstract text obtained by calling the get_paper_abstract tool, copied "
            "verbatim, not rewritten/condensed — relevant_snippet is your own excerpt supporting the "
            "judgment, while abstract is the raw material a reviewer can use to independently verify "
            "whether relevant_snippet takes something out of context or over-interprets — the two must "
            "not be the same text, each serving its own purpose. If get_paper_abstract returns an "
            "empty abstract (Scopus itself doesn't have an abstract for this paper), honestly leave it "
            "blank, don't fabricate one."
        ),
    )


class ProblematizationDetail(BaseModel):
    """Required when research_approach=problematization, left blank otherwise. The structure
    corresponds to the core output of Alvesson & Sandberg's (2011) methodological principles 2 through
    6: identify the assumption → assess it → construct an alternative assumption → self-check against
    Davis's (1971) obvious/absurd/interesting three-way test. Not a free-text paragraph — it's meant to
    force the agent through these specific steps of judgment, rather than jumping straight to the
    conclusion "I think there's an assumption worth challenging here."""

    assumption_type: ProblematizedAssumptionType
    identified_assumption: str = Field(
        description="An assumption identified from the actually retrieved literature that this direction's literature widely shares but rarely states outright/questions — must be read out of real retrieval results, not guessed from common sense about what this field 'should' assume"
    )
    assumption_evidence: list[CitedEvidence] = Field(
        min_length=1,
        description="Specific citations (with abstracts) supporting 'this really is an assumption this body of literature shares' — cannot assert that an entire line of literature shares an assumption based on just one paper's wording",
    )
    why_worth_challenging: str = Field(
        description="Why this assumption is worth challenging: whether it's widely shared yet weakly argued for on its own terms, whether it's starting to lose explanatory power, and — most importantly — which specific part of the phenomenon card is in direct tension with this assumption (cannot just abstractly say 'this assumption is imperfect')"
    )
    alternative_assumption: str = Field(
        description="The alternative assumption direction proposed after the challenge — must be constructed from the literature actually read, not a wholesale adoption of a ready-made opposing paradigm (e.g. reflexively applying an entire poststructuralist/feminist framework) as the alternative assumption — the A&S original calls this 'prepackaged problematization,' not genuine problematizing"
    )
    interestingness_check: str = Field(
        description="A self-assessment of alternative_assumption against Davis's (1971) three-way test: 'that's obvious' (too close to the audience's existing assumption, no point in challenging it) / 'it's absurd' (too total a denial, readers won't accept it) / 'that's interesting' (partly affirms, partly denies the existing assumption — the ideal zone) — only landing in the interesting zone lets this direction be adopted as the final research question; if the self-assessment lands on obvious or absurd, state so honestly and explain in rationale why it fell back to gap-spotting"
    )


class HitLevel(str, Enum):
    """The retrieval-hit tier — not free text; testing found that letting the model write this field
    itself produces descriptive sentences like "retrieval could not be executed (a tool-environment
    failure, not a hit-tier judgment)" instead of one of four fixed tiers, and the code can't reliably
    distinguish "genuinely exhausted all three tiers with no hit" from "retrieval never really ran" —
    two entirely different situations — from such prose. Two explicit infrastructure-failure values
    were added to make this distinction structured, so there's no need to parse the agent's natural
    language."""

    EXACT_MECHANISM = "exact_mechanism"  # Hit at the exact-mechanism-match tier
    THEORY_FAMILY = "theory_family"  # Hit at the theory-family tier
    DISCIPLINE_BROAD = "discipline_broad"  # Hit at the broad-discipline tier
    EXHAUSTED_NO_HIT = "exhausted_no_hit"  # All three tiers + each tier's rewrite retries exhausted with no hit — a legitimate conclusion, not a failure
    RETRIEVAL_UNAVAILABLE = "retrieval_unavailable"  # The search_scopus tool itself errored/is unavailable (e.g. missing key) — not "no hit"
    NOT_EXAMINED = "not_examined"  # Terminated early due to a tool failure on a prior direction; this direction was never actually examined


class DirectionSearchRecord(BaseModel):
    """The complete exploration record for one of step 2's candidate theoretical directions — the
    conclusion reached after attempting the retrieval_skill's three-tier degrading retrieval protocol.
    Step 3's output must include every direction examined, not just report the one finally selected
    (echoing the design where "trying the other directions step 2 matched" matters — the directions
    that were skipped are themselves part of the audit requirement, proving they were genuinely tried
    rather than fabricated)."""

    theory_name: str
    hit_level: HitLevel
    queries_tried: list[str] = Field(
        default_factory=list, description="Every search query actually used with search_scopus for this direction, in the order tried (including rewrite retries)"
    )
    verdict: str = Field(
        description="The conclusion for this direction: e.g. 'the literature already fully explains the phenomenon, no puzzle here' / 'constitutes a theoretical void' / 'constitutes a mechanism gap, the gap is in...' / 'this direction's literature implies assumption X, in tension with the phenomenon, problematizable' / 'retrieval tool failure, cannot judge.' "
        "Rendered as Markdown by the frontend — when there are multiple reasons/points, separate them with a real blank line, don't write one unbroken paragraph; cite specific papers in standard APA author-year format (e.g. '(Zhao et al., 2017)'), not the informal 'journal abbreviation + year + topic tag' style (e.g. 'SMJ 2022 (multilevel OD)')"
    )
    cited_evidence: list[CitedEvidence] = Field(default_factory=list)


class TheoreticalGroundingRecord(BaseModel):
    """A dedicated deep-retrieval pass on the anchor theoretical direction, building up that theory's
    current state of research — **moved from step 4 to step 3 this round** (previously the output of
    step 4's sub-step 0, see git history; a methodology discussion pointed out: "abduction is about
    finding what ODT hasn't done; this step should retrieve ODT but from a different angle" — assigning
    this to step 3, which already handles "the relationship to the anchor theory," so step 4 could
    devote its retrieval budget entirely to "stepping outside the anchor theory to find a mechanism,"
    see MechanismGroundingRecord).

    Only run on **the one direction the research_question locked onto**, not on every direction in
    examined_directions — step 3's earlier "broad and shallow" scan across candidate directions is
    unchanged; only once a direction is confirmed to constitute a gap and a research_question is about
    to be produced does it shift into this "narrow and deep" mode, completed right there in the same
    agent run, not as a separate call.

    Different in nature from step 3's earlier "broad and shallow" scan: that scan only needs to confirm
    a direction constitutes a gap and then stops, without needing to fully map that direction's
    literature; this is "narrow and deep" — having already decided to produce a research question on
    this direction, it needs to work out whether there's any unresolved tension within that direction's
    own literature (such tensions are often exactly where a candidate theory is most worth cutting in,
    see the empirical case in run b45f39c3), serving as the "state of the anchor theory" background for
    step 4's candidate generation (not the source of a mechanism a candidate theory borrows — that's
    left to step 4's own MechanismGroundingRecord to find elsewhere)."""

    anchor_theory: str = Field(description="The name of the theoretical direction this deep retrieval anchors on, i.e. anchor_theory_direction")
    queries_tried: list[str] = Field(default_factory=list, description="Every search query actually used with search_scopus, in the order tried")
    key_findings: list[CitedEvidence] = Field(
        min_length=1,
        description="Key literature retrieved that constitutes this theory's current state of research (including the raw abstract text obtained via get_paper_abstract) — when step 4 generates candidates, judgments like 'why the existing construct doesn't sufficiently cover the research question' must find corresponding support here; it can't fill in details missing here from a background impression of this theory drawn from training knowledge",
    )
    established_boundary_conditions: str = Field(
        description="A summary of this theory's currently known boundary conditions/scope of applicability — reasoned from the literature in key_findings item by item, not a vague generalization. When mentioning a specific paper, use standard APA author-year format (e.g. '(Zhao et al., 2017)'), not the informal 'journal abbreviation + year + topic tag' style (e.g. 'SMJ 2022 (multilevel OD)') — this field gets integrated into the formal report by step 6, and informal citation formats would carry through into the final deliverable"
    )
    internal_tensions_or_gaps: str = Field(
        description="Whether the literature in key_findings contains mutually contradictory findings, unresolved controversies, or a shared blind spot — such tensions are often exactly where a candidate theory is most worth cutting in; record them honestly, don't smooth them over just because they 'look messy.' Same as above, cite specific papers in standard APA author-year format, not journal-abbreviation-plus-topic-tag style"
    )


class Step3Output(BaseModel):
    """The complete structured result step 3's single agent run requires the model to produce.

    "Stopping once a direction produces a candidate research question, without examining the rest of
    the candidate directions" is allowed by design (exhaustively testing every candidate direction is
    not required), but examined_directions must honestly include every direction **actually examined**,
    including ones judged to "not constitute a puzzle" and skipped — this is the baseline for
    auditability; it cannot leave only the "finally selected" one and hide the exploration process.
    """

    examined_directions: list[DirectionSearchRecord] = Field(
        min_length=1, description="Every candidate theoretical direction examined, in the order examined"
    )
    research_approach: Optional[ResearchApproach] = Field(
        default=None,
        description="The **tier-1** choice for producing a research question: gap_spotting or problematization. Empty if every direction was judged to 'not constitute a puzzle' (escalated to human review).",
    )
    gap_type: Optional[GapType] = Field(
        default=None,
        description="**Tier 2** — required only when research_approach=gap_spotting: theory_void or mechanism_gap. Must be left blank when research_approach=problematization — that path's tier 2 is problematization_detail.assumption_type, not this field; the two paths' tier-2 type systems don't share this field.",
    )
    research_question: Optional[str] = Field(default=None, description="The specific research question (RQ) produced; empty corresponds to the escalate-to-human branch")
    anchor_theory_direction: Optional[str] = Field(
        default=None,
        description="The candidate theoretical direction the research_question anchors on when one is produced, which must exactly match one entry's theory_name in examined_directions (the direction that produced this research question). Required whenever research_question is non-empty — this information used to live only in the natural-language prose of verdict/rationale; step 4 needs a structured field to reliably locate 'which theory to run deep retrieval on,' rather than guessing by parsing prose.",
    )
    problematization_detail: Optional[ProblematizationDetail] = Field(
        default=None,
        description="The tier-2 choice and full methodological output for the research_approach=problematization path (including the five-way assumption_type classification) — required only when research_approach=problematization; must be left blank when research_approach=gap_spotting, not filled in perfunctorily just to have something there",
    )
    mechanism_gap_characterization: Optional[MechanismGapCharacterization] = Field(
        default=None,
        description="**Tier 3** — required only when gap_type=mechanism_gap, left blank in every other case (theory_void or the problematization path). Distinguishes whether this gap is 'existing theory genuinely hasn't studied this' (uncharted) or 'applying existing theory's core logic straightforwardly here would yield a prediction that contradicts/opposes the phenomenon' (anomalous_reversal) — the latter is a far weightier basis for theoretical contribution than the former (Whetten 1989). Choosing anomalous_reversal requires spelling out in rationale exactly which of existing theory's core logic, what it would predict if applied straightforwardly, and which specific observation of the phenomenon it contradicts — not a vague 'feels like a conflict'; if that reasoning can't be laid out clearly, honestly choose uncharted instead of picking anomalous_reversal just because it 'sounds weightier.'",
    )
    coverage_report: str = Field(
        description="An overall summary of retrieval coverage: how many directions were searched and to what extent each was covered. Rendered as Markdown by the frontend — when describing multiple directions/points separately, separate entries with a real blank line, or write them as a Markdown ordered list (one item per line); don't write one unbroken paragraph, and don't write a literal backslash-n for a line break (that isn't a real line break, and the frontend will display it verbatim) — a reviewer needs to be able to spot where the points are at a glance. When mentioning a specific paper, use standard APA author-year format (e.g. '(Zhao et al., 2017)'), not the informal 'journal abbreviation + year + topic tag' style (e.g. 'SMJ 2022 (multilevel OD)') — this field gets integrated into the formal report by step 6"
    )
    rationale: str = Field(
        description="Why the process finally settled on this direction/this research-question type (or why every direction was judged to not constitute a puzzle); if a tradeoff was made between problematization and gap-spotting, explain the basis for it. Same as above, separate multiple reasons with Markdown paragraphs/numbered lists rather than one unbroken paragraph; cite specific papers in standard APA author-year format too, not journal-abbreviation-plus-topic-tag style"
    )
    cross_source_tension_note: Optional[str] = Field(
        default=None,
        description="If there's tension/a contradictory finding between at least 2 sources in cited_evidence, flag it explicitly here — don't average it out or selectively ignore it to paper over the disagreement. When listing multiple tensions, use a Markdown paragraph/numbered list rather than one unbroken paragraph; cite specific papers in standard APA author-year format too, not journal-abbreviation-plus-topic-tag style",
    )
    anchor_theory_grounding: Optional[TheoreticalGroundingRecord] = Field(
        default=None,
        description="Required whenever research_question is non-empty: a dedicated deep-retrieval pass run on anchor_theory_direction (the sub-step moved over from step 4 this round, see TheoreticalGroundingRecord's module-level comment) — run only on this one locked-in direction, not on every direction in examined_directions. Left blank when research_question is empty (the escalate-to-human branch) — there's no point deep-diving a direction that didn't end up producing a research question.",
    )


class Step3Status(str, Enum):
    """Step 3's terminal states. NO_GAP_FOUND is not a failure state — "the phenomenon is currently
    explainable by existing theory" is a legitimate conclusion, it just needs to be escalated to human
    judgment on whether to add more theoretical directions or set the phenomenon aside (echoing appendix
    B's "only after every candidate direction has been tried and still can't constitute a puzzle is the
    genuine escalate-to-human branch this step retains").

    **RETRIEVAL_UNAVAILABLE and NO_GAP_FOUND must be kept separate, never merged**: an empty
    research_question can come from two entirely different kinds of reasons — (a) every direction was
    genuinely examined and the literature genuinely already explains the phenomenon (NO_GAP_FOUND, a
    validity judgment about the phenomenon itself); (b) the search_scopus tool itself failed (e.g.
    missing SCOPUS_API_KEY), and the agent never genuinely completed retrieval for any direction at
    all, honestly refusing to fabricate a conclusion (RETRIEVAL_UNAVAILABLE, an infrastructure problem
    with nothing to do with the phenomenon/theory). An early implementation didn't distinguish these
    two, and testing (with 4 candidate directions, in a real missing-key scenario) found this would
    incorrectly display "the tool is broken" as "the phenomenon is already explained by existing
    theory" — a bug that misleads the reviewer, not a harmless simplification: the reviewer would end
    up questioning the phenomenon's own theoretical value on seeing NO_GAP_FOUND, instead of checking
    the environment configuration.
    """

    OK = "passed"
    NO_GAP_FOUND = "no_gap_found"
    RETRIEVAL_UNAVAILABLE = "retrieval_unavailable"
    BLOCKED_AGENT_ERROR = "blocked_agent_error"


class Step3Result(BaseModel):
    """Step 3's complete output. Same pattern as Step1Result/Step2Result: run_id + status + persisted +
    audit trail."""

    run_id: str
    status: Step3Status
    examined_directions: list[DirectionSearchRecord] = Field(default_factory=list)
    research_approach: Optional[ResearchApproach] = None
    gap_type: Optional[GapType] = None
    research_question: Optional[str] = None
    anchor_theory_direction: Optional[str] = None
    problematization_detail: Optional[ProblematizationDetail] = None
    mechanism_gap_characterization: Optional[MechanismGapCharacterization] = None
    coverage_report: str = ""
    rationale: str = ""
    cross_source_tension_note: Optional[str] = None
    anchor_theory_grounding: Optional[TheoreticalGroundingRecord] = None
    note: str = ""
    provider: str = ""
    model: str = ""
    audit_trail: Optional[list[dict[str, Any]]] = Field(default=None, repr=False)
    # The tokens this agent run itself consumed — excludes any other calls the caller (e.g. step 5's
    # loop controller) separately initiates, which each land in their own Result.usage; see
    # atba/step6.py's _aggregate_run_usage for the aggregation.
    usage: Optional[TokenUsage] = None

    def is_ok(self) -> bool:
        return self.status == Step3Status.OK


# ============================================================
# Step 4: Abductive Reasoning & Theory Construction
# ============================================================
#
# Completes five sub-steps in sequence (mechanism-grounding retrieval → candidate generation →
# relation-graph construction → pairwise tournament → selection) within **one single agent run**, not
# five separate calls — this step is itself the established design of "multi-stage reasoning inside,
# but still one agent run," isomorphic with step 1's "four independent judgments within one run," and
# doesn't violate the architectural rule "each step is one independent agent run."
#
# **Scope narrowed/adjusted three times**:
# (1) Of the six sub-steps originally defined in the technical appendix's §A, the construct-novelty
#     check (retrieval-driven) and the Lakatos hard-core/protective-belt judgment have been removed at
#     the user's request — step 4's focus has narrowed to the theoretical contribution itself; the
#     novelty part's former gatekeeping role has shifted to step 5's relabeling_suspicion follow-up (see
#     the module-level comment on Step5Output), while the Lakatos judgment currently has no replacement.
# (2) Step 4 running on pure reasoning with no retrieval attached once exposed a problem (see the
#     post-mortem on run b45f39c3): candidate theories could only be cobbled together from the shallow
#     retrieval results step 3 happened to carry over, reading like free improvisation detached from the
#     anchor theory's real literature state — failing Whetten's (1989) basic requirement to "reflect a
#     broad, current understanding of the subject." The fix at the time was to add a "theoretical deep
#     retrieval" sub-step to step 4 (TheoreticalGroundingRecord), continuing to dig into the anchor
#     theory itself.
# (3) **A methodology discussion this round overturned the direction of (2)**: the mechanism abduction
#     should actually look for shouldn't be more digging into the anchor theory (that's just digging in
#     the same place twice) — it should "step outside" the anchor theory, into other established
#     theory/mechanism traditions, to find logic that can explain this gap (Gentner's 1983 structure-
#     mapping theory, Hargadon & Sutton's 1997 "technology brokering" support this direction; Oswick,
#     Fleming & Hanlon 2011 warn that "borrowing" easily slides into one-way domesticated borrowing, and
#     genuine theoretical breakthroughs often happen right at "where the borrowing doesn't carry over" —
#     the disanalogy — rather than in the borrowing itself). The former "dig into the anchor theory"
#     work has moved to step 3 (see TheoreticalGroundingRecord's module-level comment), and step 4's
#     retrieval budget has become MechanismGroundingRecord: the agent first distills, on its own, an
#     abstract mechanism-pattern description naming no theory, then retrieves using that description —
#     anchoring the query on causal structure, not a theory's name, which is the only way to find
#     literature that's "structurally similar but from a completely unrelated domain" (Gentner's
#     distinction between "structural similarity" and "surface similarity"). But testing against three
#     retrodiction-validation cases (choi_kim_2026/guerra_agarwal_2026/weiss_radoynovska_2026) showed
#     that real high-quality theory-building doesn't always "step outside" — some dig up a previously
#     assumed but never-tested competing mechanism within the same tradition, some connect an adjacent
#     but non-anchor tradition, and only a minority wholesale borrow an external theory's vocabulary. So
#     "must step outside" is not enforced here; instead each candidate is required to explicitly classify
#     which path it took (`mechanism_borrowing_pattern`), and a cross-tradition borrowing must
#     additionally disclose "where it doesn't carry over" (`disanalogy_note`) — turning this judgment
#     itself into structured content that's auditable and interrogable.
#
# Relation-graph construction is explicitly documented as "an internal auxiliary mechanism, no longer
# produced as its own output" — so there's no relation_graph field here; its reasoning process is
# required to show up in each candidate's VirtueScores.graph_based_rationale and in
# `pairwise_comparisons`.
#
# **The ranking mechanism changed this round from "each scored independently on an absolute scale" to
# "pairwise tournament"**: VirtueScores' four 1-5 scores are still kept (for a reviewer's reference/
# diagnosis), but `ranked_candidate_names`/`selected_candidate_name`/`tied_candidate_names` are no
# longer asserted directly by the model — the model instead outputs `pairwise_comparisons` (judgments
# comparing each pair of candidates), and the code (atba/step4.py) computes the ranking with simple
# win-counting (the Copeland method). See EvoScientist (Lyu et al. 2026) and Google AI co-scientist
# (Gottweis et al. 2025/2026) for the rationale: an LLM making a relative judgment like "which of A and
# B is stronger" separates candidates better and resists noise more than outputting absolute scores
# directly, without needing a calibrated absolute scale. This isn't full Elo (no iterative K-factor
# update, just one round-robin among a single batch of candidates), but it's enough to solve the problem
# of "absolute scores all crowd into 3-4 points, impossible to rank," and completes entirely within
# "one agent run," with no extra round of calls needed.


class MechanismBorrowingPattern(str, Enum):
    """A classification of where a candidate theory's mechanism comes from — doesn't enforce "must step
    outside the anchor theory," instead requiring an explicit statement of which path was taken,
    echoing Oswick, Fleming & Hanlon's (2011) "From Borrowing to Blending" caution against one-way
    borrowing, and this project's own empirical check across three retrodiction-validation cases
    (choi_kim_2026/guerra_agarwal_2026/weiss_radoynovska_2026): real high-quality theory-building
    exhibits all three modes — "cross-tradition borrowing" is not the only legitimate path."""

    WITHIN_TRADITION = "within_tradition"  # Digging within the same tradition into a previously assumed, never systematically tested competing mechanism — doesn't step outside the anchor theory, but also isn't simply filling a gap (e.g. choi_kim_2026's three-lever framework)
    ADJACENT_BRIDGING = "adjacent_bridging"  # Connecting an adjacent but non-anchor theoretical tradition, two traditions rarely discussed together (e.g. weiss_radoynovska_2026 connecting cultural entrepreneurship theory with organizational-wrongdoing literature)
    CROSS_TRADITION_BORROWING = "cross_tradition_borrowing"  # Borrowing an external theoretical vocabulary entirely unrelated to the anchor theory to explain the mechanism (e.g. guerra_agarwal_2026 borrowing reinforcing/balancing loops from systems dynamics) — must also fill in disanalogy_note


class MechanismGroundingRecord(BaseModel):
    """The output of step 4's sub-step 0 (before candidate generation) — **replacing the
    TheoreticalGroundingRecord that moved to step 3 this round**, with a completely different retrieval
    purpose: not continuing to dig into the anchor theory (that's now step 3's job, see
    TheoreticalGroundingRecord's module-level comment), but "stepping outside" the anchor theory to
    retrieve other mechanisms/theories that can explain this gap.

    The retrieval anchor is `abstract_mechanism_pattern` (one sentence naming no theory, describing only
    the causal structure itself, e.g. "the gap between expectation and reality driving escalation," "
    interdependence among heterogeneous actors' activities driving differentiation"), not a theory's
    name — this is the problem this round's design deliberately set out to solve: if the query anchors
    on the anchor theory's name, whatever it retrieves will naturally just be literature from within the
    same theoretical tradition, nowhere close to "stepping outside." Abstracting the causal structure
    being sought first, then retrieving with that abstract description, is the only way to hit
    literature that's structurally similar but from a completely unrelated domain (Gentner's 1983
    structure-mapping theory: analogy is drawn on relational structure, not surface similarity). This
    abstract description is distilled by the agent itself from
    `anchor_theory_grounding.internal_tensions_or_gaps` (the specific aspect step 3 has already worked
    out that the anchor theory can't explain on its own), not invented out of thin air."""

    abstract_mechanism_pattern: str = Field(
        description="A one-sentence causal-structure description naming no theory/discipline — describing 'what kind of mechanism is needed to explain this gap,' for later retrieval to anchor on. Counter-example: 'resource dependence theory' (names a theory); good example: 'resource-acquisition pressure driving strategic escalation' (describes only the structure)."
    )
    queries_tried: list[str] = Field(default_factory=list, description="Every search query actually used with search_scopus around abstract_mechanism_pattern, in the order tried")
    donor_findings: list[CitedEvidence] = Field(
        default_factory=list,
        description="Literature retrieved that might offer a borrowable mechanism (not required to all come from the same theoretical tradition) — a candidate theory's borrowed_or_modified_construct must find corresponding literature support here, and cannot fill in details missing here from a background impression drawn from training knowledge. If exhaustive retrieval genuinely can't find a suitable external mechanism and the candidate takes the within_tradition path (its mechanism comes from anchor_theory_grounding rather than here), leaving this empty is allowed, but rationale must state that a search was genuinely attempted and no suitable external mechanism was found, not that no search happened.",
    )


class TheoryElements(BaseModel):
    """The five theory elements — the schema defined in the technical appendix: `{What: {X, Y}, How,
    Why, Assumption, boundary conditions}`, the data source for step 6's "theory relationship diagram"
    and "hypothesis formalization," though the content itself is produced in step 4 ("step 4's output
    (X/Y/M/A/BC) is already the complete set of theory elements needed for hypothesis formalization" —
    03_学术式研究提案.md). Step 6 only translates this content into H1/H2-style hypothesis statements,
    without redoing the abductive reasoning, so this class is defined only once here for step 6 to reuse
    directly, rather than being redefined a second time and drifting apart."""

    x: str = Field(description="The independent/antecedent construct (one of the What's) — must be an abstract construct, not the phenomenon itself or a specific empirical result already observed")
    y: str = Field(description="The dependent/outcome construct (the other What) — likewise must be an abstract construct, not the phenomenon itself")
    relation_form: str = Field(description="The form of the relationship between X and Y (the How): linear/interactive/nonlinear etc., specific enough to guide later hypothesis formalization")
    mechanism: str = Field(description="The causal mechanism underlying why that relationship holds (the Why) — this is where the candidate theory's real novelty lies, it can't just restate X→Y")
    assumption: str = Field(description="The premise the relationship depends on holding (the Assumption) — cannot be omitted, must be stated explicitly even if it looks 'obvious'")
    boundary_conditions: Optional[str] = Field(
        default=None,
        description="Boundary conditions {When, Where, Who} — not a required field, filled in only when the research explicitly targets a specific scope of applicability",
    )


class VirtueScores(BaseModel):
    """The four-virtue scoring — the explanatory virtues: consilience/coherence/parsimony/precision.
    The technical appendix stresses that the ranking is "computed by propagation through the relation
    graph," not four independently scored numbers — this still requires four scalar values (for
    ranking/frontend display), but forces a graph_based_rationale paragraph alongside them, making the
    model explain how this score was derived from the candidate-evidence and candidate-candidate
    (explain/contradict/analogy) relationships, rather than scoring by intuition and tacking on an empty
    sentence afterward. A 1-5 integer scale, 5 being strongest.

    **These four are not the same kind of judgment** (in Choudhury, Moeen & Wormald's 2026 terms):
    consilience/coherence/parsimony assess the logical/aesthetic quality of the explanation itself (that
    paper calls this "lovely," unrelated to whether it fits real evidence — an explanation never tested
    can still be very lovely); precision is the only one of the four that assesses "how well this
    explanation's claims/predictions fit the phenomenon's and the evidence's specific details," closer
    to what that paper calls the evidential virtue "likely." When doing a pairwise comparison
    (PairwiseComparison), these two different kinds of judgment must not be conflated — "more lovely"
    (e.g. more parsimonious) does not equal "more likely" (e.g. fitting the specific observed pattern
    better); a candidate can perfectly well be lovely but not likely, or the reverse."""

    consilience: int = Field(ge=1, le=5, description="Breadth of unification (lovely): how much existing evidence/related phenomena this candidate can simultaneously explain")
    coherence: int = Field(ge=1, le=5, description="Internal consistency (lovely): whether the candidate theory's X/Y/mechanism/assumption are self-consistent, not self-contradictory")
    parsimony: int = Field(ge=1, le=5, description="Parsimony (lovely): whether the number of theoretical elements/assumptions needed for the same explanatory power is minimal")
    precision: int = Field(
        ge=1,
        le=5,
        description="Precision (likely, the only evidential virtue of the four): how well the claim/"
        "prediction fits the specific details (rather than the general direction) of the phenomenon "
        "card/research question description — for instance whether the phenomenon takes the specific "
        "shape of 'rising then falling' versus 'falling then rising,' and whether the candidate's "
        "relation_form/mechanism precisely predicts that specific shape rather than vaguely claiming "
        "'a nonlinear relationship.' Judged separately from the first three — don't give precision a "
        "high score just because a candidate happens to be parsimonious/consilient.",
    )
    graph_based_rationale: str = Field(
        description="How these four scores were derived by propagation through the candidate-evidence and candidate-candidate relationship graph — must show the reasoning behind relative comparisons like 'why more/less consilient, parsimonious ... than the other candidate,' not four isolated, hollow justifications for four isolated numbers"
    )


class CandidateTheory(BaseModel):
    """A single candidate theory generated in step 4 — the 3-5 candidates must be **mutually
    exclusive**: if any one candidate holds, it rules out the others holding, rather than each
    "explaining part of the phenomenon" (that's complementary, not the mutually exclusive candidate set
    this step requires).

    **Contains no construct-novelty check / Lakatos hard-core-protective-belt judgment** — these two
    were once part of the design (added when absorbing a methodology discussion, see git history
    `4bd44e6`), but the user explicitly asked to narrow step 4's focus to the theoretical contribution
    itself: generate candidates, give the explanation, score and rank on the four virtues, no Lakatos
    judgment. Whether a candidate overlaps with existing literature, and whether its degree of
    refinement counts as "progressive," is left to step 5's interrogation to handle — **step 5's
    relabeling_suspicion follow-up is therefore the only place left in the whole pipeline that still
    uses retrieval to verify "is this just an existing construct wearing a new label,"** not a
    dispensable duplicate check, see the top-of-file docstring in atba/step5.py.

    **Retrieval has been wired back into step 4** (for a purpose opposite to the historically-removed
    novelty_check, see the module-level comment on the Step 4 section): candidate generation must be
    grounded in `MechanismGroundingRecord.donor_findings` (for cross-tradition/adjacent-tradition
    borrowing) or `anchor_theory_grounding.key_findings` (for digging within the same tradition, from
    step 3) — the specific construct named by `borrowed_or_modified_construct`/
    `why_existing_insufficient` must find corresponding literature support in the relevant findings,
    and cannot be freely improvised from a background impression drawn from training knowledge — this
    is Whetten's (1989) basic requirement to "reflect a broad, current understanding of the
    subject."""

    candidate_name: str = Field(description="A short name for the candidate theory, used to refer to it in ranking/citations/step 5's interrogation")
    is_baseline: bool = Field(
        default=False,
        description="Whether this is the null-hypothesis baseline candidate — the anchor theory applied "
        "directly with no borrowing/modification, used to test whether the other candidates are "
        "actually better than 'changing nothing' (echoing Choudhury, Moeen & Wormald's (2026) discussion "
        "of the 'strict IBE' path — drawing candidates only from existing theory's existing "
        "explanations, without constructing anything new — ATBA's other candidates by default all take "
        "the 'loose' route, and had never actually been compared against the null hypothesis that "
        "'existing theory is already good enough'; this candidate fills that gap). If True: "
        "mechanism_borrowing_pattern must be within_tradition, disanalogy_note must be left blank, "
        "borrowed_or_modified_construct/why_existing_insufficient may be filled with explanatory text "
        "like '(none — this is the null-hypothesis baseline, applying the anchor theory's original "
        "construct as-is, with no modification)' and need not point to newly retrieved literature. "
        "Exactly one candidate in the candidates list must have is_baseline=True, the rest False.",
    )
    theory_elements: TheoryElements
    mechanism_borrowing_pattern: MechanismBorrowingPattern = Field(
        description="Which path this candidate's mechanism comes from — digging within the same "
        "tradition (within_tradition) / connecting an adjacent tradition (adjacent_bridging) / "
        "borrowing a cross-tradition external theoretical vocabulary (cross_tradition_borrowing). "
        "Don't default to cross_tradition_borrowing just to 'seem creative' — fill in whichever this "
        "candidate's mechanism actually comes from, per the material actually retrieved in "
        "MechanismGroundingRecord/anchor_theory_grounding."
    )
    disanalogy_note: Optional[str] = Field(
        default=None,
        description="Required when mechanism_borrowing_pattern=cross_tradition_borrowing: where this "
        "borrowed mechanism **doesn't carry over** in the new setting, and what adjustment/tradeoff was "
        "made to make it fit — cannot only present the parts where the borrowing 'succeeds.' Echoes "
        "Oswick, Fleming & Hanlon's (2011) critique of 'domesticated borrowing' (a superficial borrowing "
        "that files off the rough edges): genuine theoretical breakthroughs often happen right at this "
        "'doesn't carry over' point, rather than in the borrowing itself; left blank for the other two "
        "patterns.",
    )
    borrowed_or_modified_construct: str = Field(
        description="Which existing construct was borrowed/modified — must name a specific construct/"
        "theory, not a vague reference to 'existing theory,' and must find corresponding specific "
        "literature support in MechanismGroundingRecord.donor_findings (cross-tradition/adjacent "
        "borrowing) or anchor_theory_grounding.key_findings (digging within the same tradition), and "
        "cannot fill in details missing here from a background impression drawn from training "
        "knowledge. When mentioning a specific paper, use standard APA author-year format (e.g. "
        "'(Zhao et al., 2017)'), not the informal 'journal abbreviation + year + topic tag' style"
    )
    why_existing_insufficient: str = Field(
        description="Why the existing construct itself isn't sufficient to cover the research question "
        "step 3 identified — can't just say 'nobody has studied this.' Same as above, cite specific "
        "papers in standard APA author-year format"
    )
    explanation_of_phenomenon: str = Field(description="The full argument using this set of theory elements to specifically explain step 1's phenomenon/step 3's research question")
    mutual_exclusivity_note: str = Field(
        description="Why, if this candidate holds, it rules out the other candidates holding — a "
        "mutual-exclusivity self-check; wording should point toward 'ruling out' rather than 'can also "
        "explain part of it,' a complementary framing that signals a problem with the candidate set's "
        "design"
    )
    virtue_scores: VirtueScores


class CandidateElementField(str, Enum):
    """The specific field step 5 pinpoints when sending things back for revision — see the module-level
    comment on Step5Output.loop_back_target_field. Defined here (rather than in the Step 5 section)
    because Step4Result.revision_target_field also needs it, and Step 4's schema is defined earlier in
    this file than Step 5's, avoiding a forward reference. The values correspond to
    CandidateTheory/TheoryElements' field names; WHOLE_CANDIDATE is the special case of "the whole
    candidate needs to be rewritten," not corresponding to any specific field."""

    X = "x"
    Y = "y"
    RELATION_FORM = "relation_form"
    MECHANISM = "mechanism"
    ASSUMPTION = "assumption"
    BOUNDARY_CONDITIONS = "boundary_conditions"
    MECHANISM_BORROWING_PATTERN = "mechanism_borrowing_pattern"
    DISANALOGY_NOTE = "disanalogy_note"
    BORROWED_OR_MODIFIED_CONSTRUCT = "borrowed_or_modified_construct"
    WHY_EXISTING_INSUFFICIENT = "why_existing_insufficient"
    EXPLANATION_OF_PHENOMENON = "explanation_of_phenomenon"
    WHOLE_CANDIDATE = "whole_candidate"  # The core mechanism fails as a whole, and this one candidate needs to be entirely rewritten (not every candidate, just this one being interrogated)


class PairwiseComparison(BaseModel):
    """One pairwise comparison between candidates — the actual basis for the ranking (see the module-
    level comment on the Step 4 section, "the ranking mechanism changed this round from ..."). Requires
    one record to be produced for every C(n,2) combination among `candidates` (3 candidates = 3
    records, 5 candidates = 10 records); atba/step4.py's output_validator verifies this, and incomplete
    coverage gets sent back with a ModelRetry."""

    candidate_a: str = Field(description="One of the two candidates being compared, its candidate_name")
    candidate_b: str = Field(description="The other candidate being compared, its candidate_name, must differ from candidate_a")
    winner: str = Field(
        description="The stronger candidate of this pair — must be filled with either candidate_a's or candidate_b's exact text, or 'tie' (when it's genuinely a toss-up — don't force a pick just to 'look decisive')"
    )
    rationale: str = Field(
        description="Why winner is stronger (or why it's a tie) — based on a relative comparison of the four virtues, same requirement as VirtueScores.graph_based_rationale: show genuine relative argumentation, not a hollow 'A is better because A is more persuasive'"
    )


class Step4Output(BaseModel):
    """The complete structured result step 4's single agent run requires the model to produce — the
    final snapshot of what the five sub-steps produced."""

    mechanism_grounding: MechanismGroundingRecord = Field(
        description="The output of sub-step 0: before candidate generation, stepping outside the anchor theory to retrieve other mechanisms that can explain this gap. A revision round (round_number>1) should directly reuse the record already produced in the previous round, without needing to retrieve again, unless step 5's interrogation feedback explicitly points to 'a missed mechanism direction needs to be added'"
    )
    candidates: list[CandidateTheory] = Field(
        min_length=3,
        max_length=5,
        description="3-5 mutually exclusive candidate theories, in generation order. Exactly one of them must be the null-hypothesis baseline candidate with is_baseline=True (see CandidateTheory.is_baseline); across the remaining candidates' mechanism_borrowing_pattern: with 3-4 candidates, at least 2 types must be covered; with 5 candidates, all 3 types must be covered — they cannot all crowd onto the same path.",
    )
    pairwise_comparisons: list[PairwiseComparison] = Field(
        description="The pairwise comparison judgments among candidates, must cover every C(n,2) combination — the ranking is computed from these judgments (see atba/step4.py), not asserted directly by you, so the quality of the judgments given here directly determines how accurate the ranking is"
    )
    selection_rationale: str = Field(description="Combining the pairwise comparison results, why the top-ranked candidate was ultimately selected (if there's a tie, explain where the tie is and why it's hard to break)")


class Step4Status(str, Enum):
    OK = "passed"
    BLOCKED_AGENT_ERROR = "blocked_agent_error"


class Step4Result(BaseModel):
    """Step 4's complete output. Same pattern as the earlier steps, with round_number/
    revision_instruction added — step 4 may be asked to regenerate after step 5's interrogation finds a
    core-mechanism flaw; these two fields record "which round of generation this is" and "if
    round_number>1, what specific revision instruction was received," for audit purposes and for the
    frontend to display a round label.

    **`ranked_candidate_names`/`selected_candidate_name`/`tied_candidate_names` are no longer fields
    the model asserts directly** — they're computed by atba/step4.py._rank_candidates() from the
    model-produced `pairwise_comparisons` via win-counting (the Copeland method), filled in only at
    persist time; Step4Output itself doesn't contain these three fields."""

    run_id: str
    status: Step4Status
    round_number: int = Field(default=1, description="Which round of the step4⇄step5 loop this is — the first generation is 1, incrementing each time it's regenerated after being sent back for a step-5 core-mechanism flaw")
    revision_instruction: Optional[str] = Field(
        default=None, description="If round_number>1, the core-mechanism-flaw feedback from step 5 received for this round's generation (see Step5Output.loop_back_instruction)"
    )
    revision_target_candidate: Optional[str] = Field(
        default=None,
        description="If round_number>1: which candidate step 5's interrogation this round targeted (Step5Output.interrogated_candidate_name) — a revision round's candidate generation only needs to rewrite this one candidate (or a specific field of it, see revision_target_field), leaving the others untouched, no need to start over from scratch.",
    )
    revision_target_field: Optional[CandidateElementField] = Field(
        default=None,
        description="If round_number>1: the specific field step 5 pinpointed (see Step5Output.loop_back_target_field) — WHOLE_CANDIDATE means the core mechanism fails as a whole and this one candidate needs to be entirely rewritten; any other value means only that one field of that one candidate needs to be rewritten, with the candidate's other fields left untouched.",
    )
    mechanism_grounding: Optional[MechanismGroundingRecord] = None
    candidates: list[CandidateTheory] = Field(default_factory=list)
    pairwise_comparisons: list[PairwiseComparison] = Field(default_factory=list)
    ranked_candidate_names: list[str] = Field(default_factory=list)
    selected_candidate_name: str = ""
    tied_candidate_names: list[str] = Field(default_factory=list)
    selection_rationale: str = ""
    note: str = ""
    provider: str = ""
    model: str = ""
    audit_trail: Optional[list[dict[str, Any]]] = Field(default=None, repr=False)
    # The tokens this agent run itself consumed — excludes any other calls the caller (e.g. step 5's
    # loop controller) separately initiates, which each land in their own Result.usage; see
    # atba/step6.py's _aggregate_run_usage for the aggregation.
    usage: Optional[TokenUsage] = None

    def is_ok(self) -> bool:
        return self.status == Step4Status.OK


# ============================================================
# Step 5: Adversarial Interrogation
# ============================================================
#
# Core design principle (the technical appendix's "Step 5" section): this step runs as a **sub-agent
# independent from the generation step** — a different prompt context, sharing none of step 4's
# "creative intent," given only the candidate theory itself (see atba/step5.py's _task_text: only
# TheoryElements+explanation_of_phenomenon and similar object-level theory content is passed, not
# virtue_scores/selection_rationale — step 4's own meta-reasoning — let alone audit_trail), to create
# genuine adversariality rather than the model affirming its own output. This is this project's answer
# to "should steps 4 and 5 be merged into one agent": no, they cannot be merged — merging would mean
# the interrogator knows how the candidate was authored, directly destroying the point of this step.
#
# **Step 4 no longer does a construct-novelty check** (removed at the user's request, see the module-
# level comment on the Step4Output section) — which means the `relabeling_suspicion` follow-up is no
# longer "step 5 independently re-checking a novelty conclusion step 4 already reached," but **the only
# place left in the whole pipeline that still uses retrieval to verify "is this just an existing
# construct wearing a new label"** — carrying more weight than in the original design; this retrieval
# must not be dropped along with step 4's simplification.


class InterrogationQuestionType(str, Enum):
    FALSIFIABILITY = "falsifiability"  # Falsifiability: what observation would refute this theory?
    BOUNDARY_CONDITIONS = "boundary_conditions"  # Boundary conditions: does this construct still hold in a different setting?
    RELABELING_SUSPICION = "relabeling_suspicion"  # Relabeling suspicion: is this just an existing construct given a new name?


class InterrogationVerdict(str, Enum):
    WITHSTANDS = "withstands"  # The candidate theory's current formulation already answers this follow-up well
    WEAK = "weak"  # Answers it, but the argument is weak, worth strengthening (not a core-mechanism flaw, no need to send back to step 4)
    FAILS = "fails"  # Cannot be reasonably answered, and points to the candidate theory's core mechanism itself not holding up


class InterrogationRecord(BaseModel):
    question_type: InterrogationQuestionType
    question: str = Field(description="A specific follow-up question raised against this candidate theory — must be specific to this theory's actual content, not a generic template")
    assessment: str = Field(description="Based only on the candidate theory's given content (and nothing else — cannot invoke a creation process you weren't told about) judge whether this follow-up can be reasonably answered, and why")
    verdict: InterrogationVerdict
    cited_evidence: list[CitedEvidence] = Field(
        default_factory=list,
        description="When question_type=relabeling_suspicion, the literature found during independent retrieval verification (including raw abstract text) — the judgment of 'is this just an existing construct wearing a new label' must be traceable to real retrieval results, not concluded from a background impression drawn from training knowledge; the other two question types usually don't need retrieval, leave blank",
    )


class Step5Output(BaseModel):
    interrogated_candidate_name: str = Field(description="The name of the candidate theory under interrogation — must match the given candidate theory exactly, cannot be renamed")
    exchanges: list[InterrogationRecord] = Field(
        min_length=3,
        description="Must cover at least one each of falsifiability/boundary-conditions/relabeling-suspicion follow-ups; more rounds may be added depending on the candidate theory's specific content",
    )
    unanswered_weaknesses: list[str] = Field(
        default_factory=list,
        description="Honestly list the weaknesses this candidate theory hasn't yet answered well — can't hide weaknesses just because the interrogation record is self-authored too; even when the overall verdict is withstands, list any follow-up that wasn't answered well here honestly",
    )
    overall_verdict: InterrogationVerdict = Field(
        description="The overall verdict combining every follow-up: if any follow-up's verdict=fails, the overall is fails (triggers a send-back to step 4); if no fails but some weak exist, the overall is weak (record the weaknesses, don't send back, proceed to the next step); if every follow-up withstands, the overall is withstands"
    )
    loop_back_instruction: Optional[str] = Field(
        default=None,
        description="Required when overall_verdict=fails: a specific revision instruction for step 4 — pinpointing which core-mechanism aspect doesn't hold up and how it needs to be adjusted; can't just say 'think of a better one,' must be specific to the problem the failed follow-up pointed to; left blank when overall_verdict is not fails",
    )
    loop_back_target_field: Optional[CandidateElementField] = Field(
        default=None,
        description="Required when overall_verdict=fails: pinpoints which specific field of the "
        "`interrogated_candidate_name` candidate doesn't hold up (e.g. mechanism/"
        "borrowed_or_modified_construct) — step 4's revision only needs to rewrite this one field, "
        "leaving the rest untouched — this is to keep one field's flaw from dragging the entire "
        "candidate into being rebuilt from scratch (echoing the critique of Step-wise Rubric Rewards "
        "against a global scalar reward penalizing otherwise-good intermediate steps, see the "
        "evaluation-design section of the technical appendix). If the core mechanism fails as a whole "
        "and can't be attributed to one specific field, fill in `whole_candidate`; left blank when "
        "overall_verdict is not fails.",
    )


class Step5Status(str, Enum):
    """The terminal state persisted once the interrogation process ends. **Only three, not including
    'loop_back_required'** — that isn't a persisted terminal state, it's one of the judgments a single
    round of interrogation within the loop can reach (see Step5Output.overall_verdict); when it fires,
    the loop controller (atba/abductive_loop.py) automatically continues to the next round without
    exposing this intermediate state to the caller — the caller (API/frontend) only ever sees the
    three-way result once the loop finally stops."""

    OK = "passed"  # The interrogation process finished, the final candidate theory is cleared to proceed to
    # the next step (doesn't distinguish withstands/weak — weak just records a weakness worth noting,
    # it doesn't block the pipeline; whether it was withstands or weak is in the overall_verdict field)
    BLOCKED_UNRESOLVED = "blocked_unresolved"  # Reached the max round count while still repeatedly judged fails, escalated to human review
    BLOCKED_AGENT_ERROR = "blocked_agent_error"


class Step5RoundSummary(BaseModel):
    """A condensed record of each round in the loop history — the full candidate theory content already
    lives in that round's corresponding Step4Result (step 4 updates round_number on every generation),
    so this only needs to record "which candidate was interrogated this round, what the verdict was,
    whether it was sent back" — avoiding duplicating the entire candidate theory content in Step5Result
    and letting the two copies drift apart."""

    round_number: int
    interrogated_candidate_name: str
    overall_verdict: InterrogationVerdict
    loop_back_instruction: Optional[str] = None
    loop_back_target_field: Optional[CandidateElementField] = None
    # The tokens this round consumed — step4.json/step5.json each get overwritten by the next round's
    # save_stage_output, so only the "last round's" usage ever survives on disk; loop_history is an
    # append-only field that's never overwritten, so only the usage stored here remains traceable, per
    # round, after the loop finishes (see atba/abductive_loop.py). step5_usage is this round's own
    # interrogation call; step4_usage is the step-4 call that "produced this candidate, for this round's
    # interrogation" — which might be the very first generation (round 1), or a revision after being
    # sent back (round 2 onward).
    step5_usage: Optional[TokenUsage] = None
    step4_usage: Optional[TokenUsage] = None


class Step5Result(BaseModel):
    """Step 5's complete output — only stores the **final** round's complete interrogation record
    (exchanges/unanswered_weaknesses etc.) from the loop; earlier rounds' condensed summaries are in
    loop_history, and the full candidate content has to be looked up in the corresponding round's
    Step4Result (step 4 persists again on every revision, with round_number incrementing, and earlier
    rounds are never overwritten or lost, see atba/abductive_loop.py)."""

    run_id: str
    status: Step5Status
    round_number: int = Field(default=1, description="Which round it was when finally settled/given up on")
    interrogated_candidate_name: str = ""
    exchanges: list[InterrogationRecord] = Field(default_factory=list)
    unanswered_weaknesses: list[str] = Field(default_factory=list)
    overall_verdict: Optional[InterrogationVerdict] = None
    # When overall_verdict=fails, the specific revision instruction for step 4 (see
    # Step5Output.loop_back_instruction) — atba/abductive_loop.py's loop controller needs to read this
    # field to decide "whether to send back to step 4, and with what instruction" — it must be received
    # here as-is, not a dispensable audit-only field: omitting this field would cause the loop
    # controller to crash with a plain AttributeError the moment it actually triggers a send-back
    # (overall_verdict=fails) — this was a genuine bug that existed earlier in this project
    # (_derive_result_kwargs didn't carry it over from Step5Output, and Step5Result didn't declare this
    # field either), just rarely caught early because the "interrogation judged fails" branch is rarely
    # triggered in practice.
    loop_back_instruction: Optional[str] = None
    loop_back_target_field: Optional[CandidateElementField] = None
    loop_history: list[Step5RoundSummary] = Field(default_factory=list, description="A condensed record of every round including this final one, for audit purposes")
    note: str = ""
    provider: str = ""
    model: str = ""
    audit_trail: Optional[list[dict[str, Any]]] = Field(default=None, repr=False)
    # The tokens this agent run itself consumed — excludes any other calls the caller (e.g. step 5's
    # loop controller) separately initiates, which each land in their own Result.usage; see
    # atba/step6.py's _aggregate_run_usage for the aggregation.
    usage: Optional[TokenUsage] = None

    def is_ok(self) -> bool:
        return self.status == Step5Status.OK


# ============================================================
# Step 6: Theoretical Contribution Report
# ============================================================
#
# **Structurally different** from the first five steps: the first five steps all produce structured
# JSON (`Agent(output_type=ToolOutput(...))` forces the model to package its answer into a schema);
# step 6's output **is a markdown report itself** — the Agent in `atba/step6.py` carries no output_type
# (pydantic-ai's default output type is `str`), so the model's free-text output is the final
# deliverable, no longer wrapped in a JSON schema. This isn't cutting corners: a report's natural form
# is one continuous piece of writing, not a bunch of enumerable fields; forcing a schema onto it would
# only force the model to break a continuous argument into mutually unrelated short strings, hurting
# readability instead.
#
# **"Integration + writing, no new reasoning"**: step 6 doesn't rejudge whether the candidate theory
# holds up, doesn't re-verify evidence — those judgments were already completed in steps 1 through 5
# (generation + scoring in step 4, interrogation in step 5). What step 6 actually does is two pieces of
# "synthesis" work: (1) put step 4's candidate-theory draft together with step 5's interrogation
# findings, so the honestly-listed `unanswered_weaknesses` show up in the final report in the right way
# (as a candid statement of boundary conditions/future research directions, rather than being hidden to
# paper over the problem — echoing this project's consistent "auditable" requirement, see the field
# description on Step5Output.unanswered_weaknesses); (2) translate step 4's five theory elements (X/Y/
# relation form/mechanism/assumption/boundary conditions) into formal H1/H2-style research-hypothesis
# statements — this isn't a mechanical substitution, it requires judging whether mechanism M itself
# needs its own separate mediation hypothesis, a structural judgment at the writing level, not redoing
# the abductive reasoning to argue whether the candidate theory holds up (that judgment's own rationale
# is already spelled out in the technical appendix's "hypothesis formalization" section).


class Step6Status(str, Enum):
    OK = "passed"
    BLOCKED_AGENT_ERROR = "blocked_agent_error"


class Step6Result(BaseModel):
    """Step 6's complete output — `report_markdown` is the only substantive content, the rest of the
    fields are persistence/audit metadata around it, the same pattern as the other steps (run_id +
    status + persisted + audit trail)."""

    run_id: str
    status: Step6Status
    report_markdown: str = Field(default="", description="The full text of the theoretical contribution report, in markdown format")
    source_candidate_name: str = Field(default="", description="Which candidate theory, finally settled on by steps 4/5, the report is based on — for auditing whether the report's content is consistent with the candidate theory")
    note: str = ""
    provider: str = ""
    model: str = ""
    audit_trail: Optional[list[dict[str, Any]]] = Field(default=None, repr=False)
    # The tokens this agent run itself consumed — excludes any other calls the caller (e.g. step 5's
    # loop controller) separately initiates, which each land in their own Result.usage; see
    # atba/step6.py's _aggregate_run_usage for the aggregation.
    usage: Optional[TokenUsage] = None
    # The total tokens for the entire run from step 1 through step 6 (including every round inside the
    # step-4/5 loop), for the report page's footer to display "how many tokens this analysis cost in
    # total" — computed and persisted once, only when step 6 genuinely finishes, so the frontend doesn't
    # have to pull down all six stepN.json files itself and sum them, see atba/step6.py's
    # _aggregate_run_usage.
    total_run_usage: Optional[TokenUsage] = None
    # Every provider+model combination actually used across the entire run (deduplicated), pre-
    # formatted into a display string like "model (provider)" — normally there's only one from start to
    # finish (whichever was selected in Settings), but the user could in principle switch providers
    # between steps, so this honestly reflects every combination actually used, not just the one step 6
    # itself used.
    models_used: list[str] = Field(default_factory=list)

    def is_ok(self) -> bool:
        return self.status == Step6Status.OK
