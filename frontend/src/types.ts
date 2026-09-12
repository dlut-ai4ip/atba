// Corresponds field-for-field to the pydantic models in atba/schemas.py (the response body of the
// backend's /api/step1). Remember to keep this in sync when the backend schema changes — the two sides
// are currently kept in sync by hand, there's no auto-generated TS type.
// Field names were uniformly switched to English (kept in sync with the retrodiction extraction schema
// in appendix C' of 02_技术附录初稿.md) — only the schema structure uses English keys; the language of
// the content values is still decided by the backend's lang parameter (zh/en).

// The token amount consumed by one agent run — all six steps' Result types share this same structure,
// corresponding directly to TokenUsage in atba/schemas.py (the backend's summary of the fields from
// pydantic-ai's RunUsage that are meaningful to a user).
export interface TokenUsage {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export type Step1Status =
  | "passed"
  | "needs_clarification"
  | "blocked_jargon_persistent"
  | "blocked_agent_error";

export interface CausalPresuppositionCheck {
  hit: boolean;
  evidence_snippets: string[];
  rationale: string;
  // When hit=true: the user's cleanly-extracted causal explanation; this no longer blocks the
  // pipeline, it's only used as reference input for step 4's candidate generation.
  extracted_explanation: string | null;
}

export interface TheoryJargonCheck {
  hit: boolean;
  flagged_terms: string[];
  rationale: string;
}

export interface PhenomenonDeconstruction {
  actor: string;
  observed_behavior: string;
  field_constraints: string;
  // null when there's no attributable behavioral actor (e.g. a purely statistical/macro-level
  // finding) — a motive is never forced/fabricated
  apparent_motive: string | null;
  observable_outcome: string;
  // Theory-jargon detection is no longer nested here — it's the same kind of "check result" as
  // causal_check, so it was promoted to the jargon_check field at Step1Result's top level, keeping
  // the four check blocks (prior_expectation/causal_check/jargon_check/deconstruction) at the same
  // level, structurally symmetric.
}

export interface PriorExpectationIdentification {
  identified: boolean;
  prior_expectation_description: string | null;
  clarifying_question: string | null;
  candidate_options: string[];
  rationale: string;
}

export interface Step1Result {
  run_id: string;
  status: Step1Status;
  raw_text: string;
  prior_expectation_hint: string | null;
  prior_expectation: PriorExpectationIdentification | null;
  causal_check: CausalPresuppositionCheck | null;
  jargon_check: TheoryJargonCheck | null;
  deconstruction: PhenomenonDeconstruction | null;
  note: string;
  provider: string;
  model: string;
  audit_trail: Record<string, unknown>[] | null;
  usage: TokenUsage | null;
}

export interface Step1Request {
  text: string;
  prior_expectation_hint?: string;
  lang: "zh" | "en";
  provider: "anthropic" | "deepseek" | "openai";
  model?: string;
  // Only takes effect when provider="deepseek" or provider="openai" — the thinking-effort tier, see
  // HealthResponse.deepseek_reasoning_efforts / .openai_reasoning_efforts (the two providers' tier
  // lists differ, see the comment there)
  reasoning_effort?: string;
  max_jargon_retries: number;
  run_id?: string;
}

// Step 2: initial theory matching. No separate text input — the only input is the run_id of an
// already-completed step 1; the backend reads that run's phenomenon card off disk itself (see the
// atba/step2.py docstring).

export type Step2Status = "passed" | "blocked_agent_error";

export interface CandidateTheoryDirection {
  theory_name: string;
  relevance_rationale: string;
}

export interface Step2Result {
  run_id: string;
  status: Step2Status;
  candidate_theory_directions: CandidateTheoryDirection[];
  // The subset the user checked off to send into step 3's retrieval — not produced by the agent, this
  // is the result of manual human selection (see save_step2_selection in atba/step2.py). An empty
  // array means "nothing selected yet," not "0 selected."
  selected_theory_directions: CandidateTheoryDirection[];
  note: string;
  provider: string;
  model: string;
  audit_trail: Record<string, unknown>[] | null;
  usage: TokenUsage | null;
}

export interface Step2Request {
  run_id: string;
  lang: "zh" | "en";
  provider: "anthropic" | "deepseek" | "openai";
  model?: string;
  // Only takes effect when provider="deepseek" or provider="openai" — the thinking-effort tier, see
  // HealthResponse.deepseek_reasoning_efforts / .openai_reasoning_efforts (the two providers' tier
  // lists differ, see the comment there)
  reasoning_effort?: string;
}

export interface Step2SelectionRequest {
  selected_theory_directions: CandidateTheoryDirection[];
}

// Step 3: retrieve literature, produce a research question. No separate input — only accepts run_id;
// the backend reads that run's phenomenon card off disk (step 1) + the confirmed candidate theoretical
// directions (step 2's selected_theory_directions). Within a single run, the agent autonomously calls
// search_scopus (the D.4 retrieval tool) multiple times, see atba/step3.py.

export type Step3Status = "passed" | "no_gap_found" | "retrieval_unavailable" | "blocked_agent_error";

// Corresponds value-for-value to atba/schemas.py's HitLevel — not free text, so the frontend doesn't
// have to guess what sentence the agent might write. The retrieval_unavailable/not_examined values
// exist specifically to distinguish "the retrieval tool itself is malfunctioning" from "a real search
// happened but found no hit" — this distinction decides what tone of message Step3ResultSummary shows,
// and the two must not be conflated.
export type HitLevel =
  | "exact_mechanism"
  | "theory_family"
  | "discipline_broad"
  | "exhausted_no_hit"
  | "retrieval_unavailable"
  | "not_examined";

// **Tier 1** of producing a research question — gap-spotting (finding a shortfall) or problematization
// (challenging an implicit assumption shared by the existing literature), corresponding to the
// top-level framework of Alvesson & Sandberg's (2011, AMR) paper itself, see
// atba/prompts/problematization_skill.md. **Tier 2** depends on tier 1: under gap_spotting it's
// GapType; under problematization it's ProblematizationDetail.assumption_type (defined below) — the
// two paths' tier-2 type systems don't share the same field, they aren't three options at the same
// level stuffed into one enum.
export type ResearchApproach = "gap_spotting" | "problematization";

// **Tier 2** — used only when research_approach=gap_spotting.
export type GapType = "theory_void" | "mechanism_gap";

// Corresponds value-for-value to atba/schemas.py's ProblematizedAssumptionType, ranging from narrow to
// broad — this is the **tier 2** type for the research_approach=problematization path (symmetric to
// GapType for the gap_spotting path).
export type ProblematizedAssumptionType = "in_house" | "root_metaphor" | "paradigm" | "ideology" | "field";

export interface CitedEvidence {
  title: string;
  authors: string[];
  year: string | null;
  doi: string | null;
  source_title: string | null;
  relevant_snippet: string;
  // The full original abstract of this paper from search_scopus's returned results (copied verbatim
  // by the agent, not rewritten) — left for reviewers to independently check whether relevant_snippet
  // is being quoted out of context. null when Scopus itself doesn't have an indexed abstract, not an
  // agent oversight.
  abstract: string | null;
}

// Corresponds field-for-field to atba/schemas.py's ProblematizationDetail — non-null when
// research_approach=problematization, null in every other case. The field itself is the structured
// output of Davis's (1971) three-way self-check + principles 2-6 of A&S's (2011) methodology, not a
// block of free text.
export interface ProblematizationDetail {
  assumption_type: ProblematizedAssumptionType;
  identified_assumption: string;
  assumption_evidence: CitedEvidence[];
  why_worth_challenging: string;
  alternative_assumption: string;
  interestingness_check: string;
}

export interface DirectionSearchRecord {
  theory_name: string;
  hit_level: HitLevel;
  queries_tried: string[];
  verdict: string;
  cited_evidence: CitedEvidence[];
}

// **Tier 3** — used only when gap_type=mechanism_gap (per Whetten's (1989) distinction between an
// "anomaly" and merely being "uncovered"), see atba/schemas.py's MechanismGapCharacterization.
export type MechanismGapCharacterization = "uncharted" | "anomalous_reversal";

// A dedicated deep-retrieval pass targeting the anchor theoretical direction — **moved from step 4 to
// step 3 this round** (see the module-level comment on TheoreticalGroundingRecord in
// atba/schemas.py): done only on the one direction that research_question has locked onto, serving as
// background evidence on "the anchor theory's current state" when step 4 generates candidates — not
// the source of a mechanism a candidate theory would borrow (that's MechanismGroundingRecord).
export interface TheoreticalGroundingRecord {
  anchor_theory: string;
  queries_tried: string[];
  key_findings: CitedEvidence[];
  established_boundary_conditions: string;
  internal_tensions_or_gaps: string;
}

export interface Step3Result {
  run_id: string;
  status: Step3Status;
  examined_directions: DirectionSearchRecord[];
  research_approach: ResearchApproach | null;
  gap_type: GapType | null;
  research_question: string | null;
  // The name of the candidate theoretical direction anchored on when producing research_question,
  // matching some entry's theory_name in examined_directions.
  anchor_theory_direction: string | null;
  problematization_detail: ProblematizationDetail | null;
  mechanism_gap_characterization: MechanismGapCharacterization | null;
  coverage_report: string;
  rationale: string;
  cross_source_tension_note: string | null;
  // Only has a value when research_question is non-empty — the deep retrieval done on
  // anchor_theory_direction, see TheoreticalGroundingRecord.
  anchor_theory_grounding: TheoreticalGroundingRecord | null;
  note: string;
  provider: string;
  model: string;
  audit_trail: Record<string, unknown>[] | null;
  usage: TokenUsage | null;
}

export interface Step3Request {
  run_id: string;
  lang: "zh" | "en";
  provider: "anthropic" | "deepseek" | "openai";
  model?: string;
  // Only takes effect when provider="deepseek" or provider="openai" — the thinking-effort tier, see
  // HealthResponse.deepseek_reasoning_efforts / .openai_reasoning_efforts (the two providers' tier
  // lists differ, see the comment there)
  reasoning_effort?: string;
}

export interface HealthResponse {
  status: string;
  providers: Record<string, string>;
  max_loop_rounds: number;
  // The selectable DeepSeek/OpenAI thinking-effort tiers and defaults — defined in exactly one place,
  // the backend's atba/agent_streaming.py; when the frontend renders the thinking-effort dropdown it
  // reads from here, instead of maintaining a copy on each side that's prone to drifting. The two
  // providers' tier lists genuinely differ (OpenAI has "minimal", DeepSeek has "xhigh"/"max"), so this
  // is two separate pairs of fields rather than one shared list — Anthropic has no equivalent here at
  // all, since its extended thinking is a fixed token budget, not a tiered selection.
  deepseek_reasoning_efforts: string[];
  default_deepseek_reasoning_effort: string;
  openai_reasoning_efforts: string[];
  default_openai_reasoning_effort: string;
}

// POST /api/auth/login — see atba/auth.py, a single account (username/password configured in the
// backend's environment variables), not a multi-user account system.
export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  /** Unix timestamp in seconds */
  expires_at: number;
}

// A single record from GET /api/runs — the manifest.json body itself (run_id/created_at/updated_at/
// last_stage/completed_stages) plus two "nice-to-have" fields (see list_runs in
// atba/context_store.py): present only when that run has a step1.json, so both are optional.
export interface RunSummary {
  run_id: string;
  created_at: string;
  updated_at: string;
  last_stage: string;
  completed_stages: string[];
  phenomenon_preview?: string;
  status?: Step1Status;
}

// The generic shape of NDJSON events from /api/stepN/stream (see classify_stream_event in
// atba/agent_streaming.py). Whether thinking_delta appears at all depends on whether the specific
// provider/model produces thinking content — Anthropic has extended thinking explicitly turned on by
// the backend; on the DeepSeek side, testing shows the current default model deepseek-v4-flash
// produces it on its own too, it's not exclusive to Anthropic. Every step's streaming events just
// differ in the type of `result` inside "final" — generics avoid redefining this once per step.
//
// call_id stays constant across a single tool call from start to finish (comes from pydantic-ai's
// tool_call_id) — a single run of step 3 makes many search_scopus/get_paper_abstract calls, and the
// frontend must bucket display by call_id, it can't concatenate all tool_call_delta text
// indiscriminately (steps 1/2 only have one final tool call, so bucketing by call_id or not has the
// same effect there, unaffected). tool_name isn't necessarily repeated on every delta event, it's only
// present when pydantic-ai actually supplies it; when absent, the frontend needs to fall back to the
// tool_name it recorded earlier for that same call_id.
// text_delta: an increment of the model's free-text output (TextPart/TextPartDelta) — steps 1 through
// 5's final answers are all forced into JSON via ToolOutput, so any free text the model occasionally
// emits along the way is just incidental process commentary, not something these steps care about;
// step 6 is different, its final answer *is* a markdown report itself (no output_type, see
// atba/step6.py), and text_delta is what carries the report body's real-time increments, see the
// "step 6 adds text_delta" section of atba/agent_streaming.py.
export type StreamEvent<TResult> =
  | { type: "thinking_delta"; text: string }
  | { type: "text_delta"; text: string }
  | { type: "tool_call_delta"; call_id: string; tool_name?: string; text: string }
  | { type: "tool_result"; call_id: string; tool_name: string; content: string }
  | { type: "tool_result_retry"; call_id: string; tool_name: string; text: string }
  | { type: "final"; result: TResult };

export type Step1StreamEvent = StreamEvent<Step1Result>;
export type Step2StreamEvent = StreamEvent<Step2Result>;
export type Step3StreamEvent = StreamEvent<Step3Result>;

// Step 4: abductive reasoning, theory construction. No separate input — only accepts run_id; the
// backend reads step 1's phenomenon card + step 3's research question. /api/step4 runs only one round
// (round_number=1); the revision rounds triggered by step 5's loop don't go through this request type.

export type Step4Status = "passed" | "blocked_agent_error";

// The theory's five elements — atba/schemas.py's TheoryElements, produced by step 4, reused by step 6
// (not implemented at the time this comment was written) for hypothesis formalization from the same
// data, rather than each defining its own copy.
export interface TheoryElements {
  x: string;
  y: string;
  relation_form: string;
  mechanism: string;
  assumption: string;
  boundary_conditions: string | null;
}

export interface VirtueScores {
  consilience: number;
  coherence: number;
  parsimony: number;
  precision: number;
  graph_based_rationale: string;
}

// The classification of a candidate theory's mechanism source — does not require "must step outside
// the anchor theory," see atba/schemas.py's MechanismBorrowingPattern: a deep dive within the same
// tradition into a previously-assumed, never-tested competing mechanism / bridging to an adjacent but
// non-anchor theoretical tradition / borrowing an external theoretical vocabulary from across
// traditions (this case must also fill in disanalogy_note).
export type MechanismBorrowingPattern = "within_tradition" | "adjacent_bridging" | "cross_tradition_borrowing";

// candidate no longer contains novelty_check/lakatos_judgment — moved out of step 4's scope at the
// user's request. But the retrieval itself has been added back to step 4 for a different purpose
// (stepping outside the anchor theory before candidate generation to find a borrowable mechanism,
// rather than checking after candidate generation whether the candidate already exists), see
// MechanismGroundingRecord and the module-level comment on CandidateTheory in atba/schemas.py — whether
// a candidate overlaps with existing literature is still handled by step 5's relabeling_suspicion
// follow-up.
export interface CandidateTheory {
  candidate_name: string;
  // The null-hypothesis baseline candidate — the anchor theory verbatim, with no borrowing/
  // modification, used to test whether the other candidates are genuinely better than "changing
  // nothing" (echoing Choudhury, Moeen & Wormald's 2026 discussion of "strict IBE"). Exactly one entry
  // in the candidates list is true, the rest are false — enforced by the backend's output_validator in
  // atba/step4.py.
  is_baseline: boolean;
  theory_elements: TheoryElements;
  mechanism_borrowing_pattern: MechanismBorrowingPattern;
  // Only has a value when mechanism_borrowing_pattern="cross_tradition_borrowing" — where this
  // borrowed mechanism doesn't fit in the new setting and what correction was made, echoing Oswick,
  // Fleming & Hanlon's (2011) critique of "domesticated borrowing," see the module-level comment on
  // CandidateTheory in atba/schemas.py.
  disanalogy_note: string | null;
  borrowed_or_modified_construct: string;
  why_existing_insufficient: string;
  explanation_of_phenomenon: string;
  mutual_exclusivity_note: string;
  virtue_scores: VirtueScores;
}

// The output of step 4's sub-step 0 (before candidate generation) — **this round replaces
// TheoreticalGroundingRecord, which moved to step 3**: rather than continuing to dig into the anchor
// theory, it "steps outside" the anchor theory to retrieve other mechanisms that could explain this
// gap. The retrieval anchor is abstract_mechanism_pattern (a sentence describing the causal structure
// without naming any theory), not a theory name, see atba/schemas.py's MechanismGroundingRecord.
export interface MechanismGroundingRecord {
  abstract_mechanism_pattern: string;
  queries_tried: string[];
  donor_findings: CitedEvidence[];
}

// One comparison between a pair of candidates — the actual basis for the ranking. This round switched
// from "the model asserts a ranking on its own" to a "pairwise tournament," see the module-level
// comment preceding PairwiseComparison in atba/schemas.py: an LLM making relative judgments separates
// results more and is more noise-resistant than absolute scoring (a shared design choice of EvoScientist
// and Google's AI co-scientist).
export interface PairwiseComparison {
  candidate_a: string;
  candidate_b: string;
  // Either candidate_a, candidate_b, or the literal value "tie"
  winner: string;
  rationale: string;
}

// The specific field step 5 pinpoints when sending a candidate back for revision — see
// atba/schemas.py's CandidateElementField.
export type CandidateElementField =
  | "x"
  | "y"
  | "relation_form"
  | "mechanism"
  | "assumption"
  | "boundary_conditions"
  | "mechanism_borrowing_pattern"
  | "disanalogy_note"
  | "borrowed_or_modified_construct"
  | "why_existing_insufficient"
  | "explanation_of_phenomenon"
  | "whole_candidate";

export interface Step4Result {
  run_id: string;
  status: Step4Status;
  round_number: number;
  // If round_number>1: the core-mechanism-flaw feedback received from step 5 that this round's
  // generation was responding to
  revision_instruction: string | null;
  // If round_number>1: which candidate step 5's interrogation this round targeted — a revision only
  // rewrites this one candidate (or one of its specific fields, see revision_target_field), the rest
  // of the candidates are kept as-is.
  revision_target_candidate: string | null;
  revision_target_field: CandidateElementField | null;
  mechanism_grounding: MechanismGroundingRecord | null;
  candidates: CandidateTheory[];
  // The pairwise comparison judgments between candidates — ranked_candidate_names/
  // selected_candidate_name/tied_candidate_names are all computed by the backend from these via a
  // win-count tally, not directly asserted by the model.
  pairwise_comparisons: PairwiseComparison[];
  ranked_candidate_names: string[];
  selected_candidate_name: string;
  // Candidates whose boundary is unclear, left for step 5 to adjudicate — should be an empty array in
  // most cases
  tied_candidate_names: string[];
  selection_rationale: string;
  note: string;
  provider: string;
  model: string;
  audit_trail: Record<string, unknown>[] | null;
  usage: TokenUsage | null;
}

export interface Step4Request {
  run_id: string;
  lang: "zh" | "en";
  provider: "anthropic" | "deepseek" | "openai";
  model?: string;
  // Only takes effect when provider="deepseek" or provider="openai" — the thinking-effort tier, see
  // HealthResponse.deepseek_reasoning_efforts / .openai_reasoning_efforts (the two providers' tier
  // lists differ, see the comment there)
  reasoning_effort?: string;
}

export type Step4StreamEvent = StreamEvent<Step4Result>;

// Step 5: adversarial interrogation. No separate input — only accepts run_id. /api/step5 runs the full
// automatic step 4/5 loop (atba/abductive_loop.py); a single call's return value is the loop's final
// state, not a single round of interrogation.

export type InterrogationQuestionType = "falsifiability" | "boundary_conditions" | "relabeling_suspicion";
export type InterrogationVerdict = "withstands" | "weak" | "fails";

export interface InterrogationRecord {
  question_type: InterrogationQuestionType;
  question: string;
  assessment: string;
  verdict: InterrogationVerdict;
  // When question_type="relabeling_suspicion": the literature found during the independent retrieval
  // verification — the judgment of "is this just an old construct under a new name" must be traceable
  // back to real retrieval results; the other two question types usually have an empty array here.
  cited_evidence: CitedEvidence[];
}

// status has only three terminal states (excluding "loop_back_required" — that's only an internal
// mid-round judgment within the loop, never exposed to the frontend, see the Step5Status docstring in
// atba/schemas.py): passed (covers both withstands and weak, check overall_verdict for which) /
// blocked_unresolved (still hasn't passed after reaching the max round count, handed off to a human) /
// blocked_agent_error.
export type Step5Status = "passed" | "blocked_unresolved" | "blocked_agent_error";

export interface Step5RoundSummary {
  round_number: number;
  interrogated_candidate_name: string;
  overall_verdict: InterrogationVerdict;
  loop_back_instruction: string | null;
  loop_back_target_field: CandidateElementField | null;
  // This round's usage — the top-level usage field on disk in step4.json/step5.json gets overwritten
  // every round; only here (appended every round, never overwritten) can you trace back how many
  // tokens each individual round of the loop actually spent, see atba/abductive_loop.py.
  step5_usage: TokenUsage | null;
  step4_usage: TokenUsage | null;
}

export interface Step5Result {
  run_id: string;
  status: Step5Status;
  round_number: number;
  interrogated_candidate_name: string;
  exchanges: InterrogationRecord[];
  unanswered_weaknesses: string[];
  overall_verdict: InterrogationVerdict | null;
  loop_back_instruction: string | null;
  loop_back_target_field: CandidateElementField | null;
  // A condensed record of every round including this final one — the full candidate content should be
  // looked up in the corresponding round's Step4Result, it isn't duplicated here
  loop_history: Step5RoundSummary[];
  note: string;
  provider: string;
  model: string;
  audit_trail: Record<string, unknown>[] | null;
  usage: TokenUsage | null;
}

export interface Step5Request {
  run_id: string;
  lang: "zh" | "en";
  provider: "anthropic" | "deepseek" | "openai";
  model?: string;
  // Only takes effect when provider="deepseek" or provider="openai" — the thinking-effort tier, see
  // HealthResponse.deepseek_reasoning_efforts / .openai_reasoning_efforts (the two providers' tier
  // lists differ, see the comment there)
  reasoning_effort?: string;
}

// /api/step5/stream has two more event types than the other stepN/stream endpoints, see the
// stream_step4_5_loop docstring in atba/abductive_loop.py:
// - round_marker: emitted before starting to forward the events of a given phase in a given round —
//   the frontend uses this to bucket the thinking/tool_call that follow into the correct "turn" (the
//   same live buffer should be flushed into one complete turn upon hitting the next round_marker).
// - phase_final: emitted when a given phase in a given round genuinely finishes running, replacing the
//   "final" that phase would otherwise send on its own ("final" is reserved for the one time the whole
//   loop ends). When phase="step4", result is a Step4Result; when phase="step5", it's a Step5Result —
//   typed as unknown, with the caller narrowing by phase themselves, to avoid excess boilerplate from
//   introducing a union type just for this.
export type Step5StreamEvent =
  | StreamEvent<Step5Result>
  | { type: "round_marker"; phase: "step4" | "step5"; round: number }
  | { type: "phase_final"; phase: "step4" | "step5"; round: number; result: unknown };

// Step 6: produce the theoretical contribution report. No separate input — only accepts run_id; the
// backend reads all the output from steps 1 through 5 and integrates it into a markdown report.
// Structurally different from the other steps: report_markdown is the only substantive content, not a
// pile of structured fields — see the module-level comment in the "step 6" section of
// atba/schemas.py.

export type Step6Status = "passed" | "blocked_agent_error";

export interface Step6Result {
  run_id: string;
  status: Step6Status;
  report_markdown: string;
  source_candidate_name: string;
  note: string;
  provider: string;
  model: string;
  audit_trail: Record<string, unknown>[] | null;
  usage: TokenUsage | null;
  // The total token amount for the whole run (steps 1 through 6, including every round of the step
  // 4/5 loop) — only computed and persisted once step 6 genuinely finishes, see
  // _aggregate_run_usage in atba/step6.py. The "this run's statistics" section at the bottom of the
  // report page uses this field, not the `usage` field above (which only reflects step 6's own single
  // call).
  total_run_usage: TokenUsage | null;
  // The (deduplicated) set of provider+model combinations actually used across the whole run,
  // pre-formatted as a "model (provider)" display string.
  models_used: string[];
}

export interface Step6Request {
  run_id: string;
  // Unlike the other steps: this directly decides the language of the report body itself (the other
  // steps' lang only affects the language of the system prompt itself, with the output field values
  // following their own separate language logic; step 6's output is free text, so when lang=en the
  // report body itself is in English).
  lang: "zh" | "en";
  provider: "anthropic" | "deepseek" | "openai";
  model?: string;
  // Only takes effect when provider="deepseek" or provider="openai" — the thinking-effort tier, see
  // HealthResponse.deepseek_reasoning_efforts / .openai_reasoning_efforts (the two providers' tier
  // lists differ, see the comment there)
  reasoning_effort?: string;
}

export type Step6StreamEvent = StreamEvent<Step6Result>;
