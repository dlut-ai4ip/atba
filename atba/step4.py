"""Step 4: Abductive Reasoning & Theory Construction — the runnable implementation.

Corresponds to the technical appendix's "Step 4" section, but **its scope has been narrowed at the
user's request**: starting from step 3's research question, it completes five sub-steps in sequence
within **one single agent run** (mechanism-grounding retrieval → candidate generation → relation-graph
construction → pairwise tournament → selection), without doing a novelty check on the construct or a
Lakatos hard-core/protective-belt judgment — those two were originally part of six sub-steps and have
since been moved out; step 4's focus has narrowed to the theoretical contribution itself, see the
module-level comment on `CandidateTheory` in `atba/schemas.py`.

**The retrieval's purpose changed direction this round**: step 4's retrieval sub-step used to run one
more deep retrieval on the theoretical direction step 3 had anchored on (`TheoreticalGroundingRecord`)
— but a methodology discussion pointed out that this amounts to digging in the same place twice; what
abduction should really be looking for is a mechanism that "steps outside" the anchor theory to find
elsewhere. **The work of digging deep into the anchor theory itself has moved to step 3** (see
`atba/step3.py`); step 4's retrieval is now `MechanismGroundingRecord`: the agent first distills, on its
own, an abstract mechanism-pattern description that names no theory, then uses that description to
retrieve **other** literature that can offer a borrowable mechanism — `_build_agent` still attaches
`toolsets=[build_retrieval_toolset()]`, but the retrieval target is entirely different; don't conflate
this with the historical novelty_check or the old `TheoreticalGroundingRecord`. Whether a candidate
overlaps with existing literature, and whether its degree of refinement counts as "progressive," is
still left to step 5's `relabeling_suspicion` follow-up.

**The ranking mechanism changed this round from "the model asserts a ranking itself" to "pairwise
tournament + code computes it"**: the model produces `pairwise_comparisons` (which of each pair of
candidates is stronger), and `_rank_candidates()` computes the final ranking with simple win-counting
(the Copeland method), instead of the model directly outputting `ranked_candidate_names`/
`selected_candidate_name` — see the module-level comment before `PairwiseComparison` in
`atba/schemas.py` for why.

**Revision rounds**: when `round_number > 1`, this function reads the previous round's candidate set and
`mechanism_grounding` from the persisted `step4.json`, and splices them into the task text together with
the caller-supplied `revision_instruction`/`revision_target_candidate`/`revision_target_field` (the
specific candidate and field step 5's interrogation pinpointed), asking the agent to **rewrite only the
one named field of the one named candidate** (rewriting the whole candidate only when
`revision_target_field=whole_candidate`), leaving the other candidates — and any other field of the same
candidate that wasn't named — untouched. This is no longer a vague "targeted revision, no need to start
over," but has structured location information (see "special requirements for revision rounds" in
`atba/prompts/step4.md`).
**Mechanism-grounding retrieval is only run once by default, in round 1**: revision rounds directly
reuse the previous round's `mechanism_grounding` without being forced to retrieve again, unless the
interrogation feedback explicitly points to "a mechanism direction was missed."
**The orchestration of revision rounds itself is not in this file** — whether a revision is needed, and
whether to run another round, is decided by `atba/abductive_loop.py` based on step 5's verdict; this
file's `run_step4`/`stream_step4` only handle "given a round_number and a revision instruction, run one
candidate-generation pass" — they don't know step 5 exists, keeping this module independently testable/
callable.
"""

from __future__ import annotations

import json
import os
from itertools import combinations
from typing import Optional

from pydantic_ai import Agent, ModelRetry, ToolOutput

from .agent_streaming import (
    anthropic_thinking_model_settings,
    classify_stream_event,
    deepseek_reasoning_model_settings,
    extract_usage,
    openai_reasoning_model_settings,
)
from .context_store import load_stage_output, save_stage_output
from .llm import DEFAULT_MODELS, build_model
from .mcp_server import build_retrieval_toolset
from .prompts import step4_system_prompt
from .schemas import (
    CandidateElementField,
    CandidateTheory,
    CausalPresuppositionCheck,
    MechanismBorrowingPattern,
    PairwiseComparison,
    PhenomenonDeconstruction,
    Step1Result,
    Step3Result,
    Step4Output,
    Step4Result,
    Step4Status,
)

DEFAULT_PROVIDER = os.environ.get("ATBA_LLM_PROVIDER") or "anthropic"

STEP4_TOOL_NAME = "report_step4_output"


def _build_agent(provider: str, model_name: Optional[str], lang: str) -> Agent[None, Step4Output]:
    model = build_model(provider, model_name)
    agent = Agent(
        model=model,
        # Retrieval tools are wired back in — for sub-step 0, "mechanism-grounding retrieval," not the
        # historical novelty_check that was removed, nor the anchor-theory deep dive that moved to
        # step 3, see the module docstring above.
        toolsets=[build_retrieval_toolset()],
        output_type=ToolOutput(
            Step4Output,
            name=STEP4_TOOL_NAME,
            description=(
                "Report step 4's final result: the state of the borrowable-mechanism retrieval done "
                "outside the anchor theory (mechanism_grounding), 3-5 mutually exclusive candidate "
                "theories (each with the five theory elements, a mechanism-borrowing-pattern "
                "classification, and four-virtue scores), the pairwise comparison judgments between "
                "candidates (pairwise_comparisons), and the selection rationale."
            ),
        ),
        system_prompt=step4_system_prompt(lang=lang),
        # With the new mechanism-grounding retrieval sub-step, tool-call rounds rose noticeably (to
        # roughly the same tier as step 3), so the retry budget is aligned with step 3's to avoid being
        # judged as an error before retrieval has actually finished.
        retries=8,
        name="atba_step4",
    )
    return _attach_output_validator(agent, lang)


def _attach_output_validator(agent: Agent[None, Step4Output], lang: str) -> Agent[None, Step4Output]:
    """Two hard checks, neither expressible as a schema-level constraint (pydantic's min_length/
    max_length can't express a cross-field relationship like "this list must match the combinatorics of
    another field") — they must be verified at runtime with an output_validator, raising ModelRetry on a
    hit to force a fix — the same approach as atba/step3.py's _attach_conditional_field_validator."""

    def _retry(zh: str, en: str) -> str:
        return zh if lang == "zh" else en

    @agent.output_validator
    def _check_pairwise_and_disanalogy(data: Step4Output) -> Step4Output:
        names = [c.candidate_name for c in data.candidates]
        name_set = set(names)
        if len(name_set) != len(names):
            raise ModelRetry(
                _retry(
                    f"candidates里的candidate_name有重复：{names}——每个候选的命名必须互不相同，才能在pairwise_comparisons里无歧义地互相指代。",
                    f"Duplicate candidate_name values in candidates: {names} — every candidate's name "
                    "must be unique so pairwise_comparisons can refer to them unambiguously.",
                )
            )

        expected_pairs = {frozenset(pair) for pair in combinations(names, 2)}
        got_pairs = {frozenset((c.candidate_a, c.candidate_b)) for c in data.pairwise_comparisons}
        missing = expected_pairs - got_pairs
        if missing:
            missing_desc = ", ".join(f'"{a}" vs "{b}"' for a, b in (tuple(p) for p in missing))
            raise ModelRetry(
                _retry(
                    f"pairwise_comparisons没有覆盖全部候选两两组合，缺了这几对：{missing_desc}——"
                    f"{len(names)}个候选需要产出C({len(names)},2)={len(expected_pairs)}条比较记录，"
                    "一对都不能少，也不要多产出不存在的候选名字组合。",
                    f"pairwise_comparisons does not cover every pairwise combination of candidates; "
                    f"missing: {missing_desc} — {len(names)} candidates require "
                    f"C({len(names)},2)={len(expected_pairs)} comparison records; none may be skipped, "
                    "and no nonexistent candidate-name combination should be added either.",
                )
            )
        extra_pairs = got_pairs - expected_pairs
        if extra_pairs:
            raise ModelRetry(
                _retry(
                    "pairwise_comparisons里出现了candidates列表中不存在的候选名字组合，请核对"
                    "candidate_a/candidate_b的拼写是否跟candidates里的candidate_name逐字一致。",
                    "pairwise_comparisons contains a candidate-name combination that doesn't exist in "
                    "the candidates list — check that candidate_a/candidate_b's spelling matches a "
                    "candidate_name in candidates verbatim.",
                )
            )
        for c in data.pairwise_comparisons:
            if c.winner not in (c.candidate_a, c.candidate_b, "tie"):
                raise ModelRetry(
                    _retry(
                        f"pairwise_comparisons里「{c.candidate_a}」vs「{c.candidate_b}」这一条的winner"
                        f"={c.winner!r}，必须是这两个候选名字之一，或者字面值'tie'，不能是别的字符串。",
                        f'The entry "{c.candidate_a}" vs "{c.candidate_b}" in pairwise_comparisons has '
                        f"winner={c.winner!r}, which must be one of these two candidate names, or the "
                        "literal 'tie' — no other string is allowed.",
                    )
                )

        for c in data.candidates:
            if c.mechanism_borrowing_pattern == MechanismBorrowingPattern.CROSS_TRADITION_BORROWING and not c.disanalogy_note:
                raise ModelRetry(
                    _retry(
                        f"候选「{c.candidate_name}」的mechanism_borrowing_pattern是"
                        "cross_tradition_borrowing，但没有填写disanalogy_note——跨传统借用必须交代"
                        "这个机制在新场景里哪里对不上、做了什么修正，不能只呈现借用成功的部分（呼应"
                        "Oswick, Fleming & Hanlon对'domesticated borrowing'的批评）。",
                        f'Candidate "{c.candidate_name}" has mechanism_borrowing_pattern='
                        "cross_tradition_borrowing but left disanalogy_note empty — a cross-tradition "
                        "borrowing must spell out where the mechanism doesn't fit the new setting and "
                        "what was adjusted; it can't only present the parts where the borrowing "
                        "succeeds (echoing Oswick, Fleming & Hanlon's critique of 'domesticated "
                        "borrowing').",
                    )
                )

        # The null-baseline candidate — echoing Choudhury, Moeen & Wormald's (2026) discussion of
        # "strict IBE" (candidates drawn only from existing theory's existing explanations, nothing
        # newly constructed): ATBA's other candidates by default always take the "loose" route (always
        # constructing a new explanation), and had never actually been compared against the null
        # hypothesis that "existing theory is already good enough, no change needed." This enforces
        # exactly one candidate with is_baseline=True, and it must be within_tradition — a baseline is
        # by definition "the anchor theory applied as-is," and shouldn't borrow from/connect to another
        # tradition, or it wouldn't be a null hypothesis anymore.
        baseline_candidates = [c for c in data.candidates if c.is_baseline]
        if len(baseline_candidates) != 1:
            raise ModelRetry(
                _retry(
                    f"candidates里is_baseline=True的候选有{len(baseline_candidates)}个，必须恰好1个"
                    "——需要有且只有一个候选代表'锚定理论原样不做任何借用/修改'的零假设基线，用来检验"
                    "其余候选是否真的比'什么都不改'更好。",
                    f"{len(baseline_candidates)} candidate(s) have is_baseline=True; there must be "
                    "exactly one — there needs to be one and only one candidate representing the "
                    "null-hypothesis baseline of 'the anchor theory applied as-is, no borrowing or "
                    "modification,' to test whether the other candidates are actually better than "
                    "'changing nothing.'",
                )
            )
        baseline = baseline_candidates[0]
        if baseline.mechanism_borrowing_pattern != MechanismBorrowingPattern.WITHIN_TRADITION:
            raise ModelRetry(
                _retry(
                    f"基线候选「{baseline.candidate_name}」（is_baseline=True）的mechanism_borrowing_"
                    f"pattern是{baseline.mechanism_borrowing_pattern.value}，必须是within_tradition"
                    "——基线的定义就是'原样沿用锚定理论'，不能同时又说自己借用/连接了别的理论传统，"
                    "那样就不是零假设了。",
                    f'The baseline candidate "{baseline.candidate_name}" (is_baseline=True) has '
                    f"mechanism_borrowing_pattern={baseline.mechanism_borrowing_pattern.value}, which "
                    "must be within_tradition — a baseline is by definition 'the anchor theory applied "
                    "as-is,' and can't simultaneously claim to borrow from or connect to another "
                    "theoretical tradition, or it stops being a null hypothesis.",
                )
            )

        # Breadth constraint on borrowing patterns — echoing the same paper's discussion of
        # tree-of-thought-style "breadth-first exploration across branches": mechanism_borrowing_pattern
        # is essentially the "branch type" of candidate generation, but left unchecked, 3-5 candidates
        # could easily all crowd onto the same path (e.g. all within_tradition), defeating the purpose
        # of breadth exploration. The more candidates, the more variety is required — with 5 candidates
        # there should be enough room to touch all three paths.
        patterns = {c.mechanism_borrowing_pattern for c in data.candidates}
        min_patterns = 3 if len(data.candidates) >= 5 else 2
        if len(patterns) < min_patterns:
            pattern_desc = ", ".join(p.value for p in patterns)
            raise ModelRetry(
                _retry(
                    f"{len(data.candidates)}个候选的mechanism_borrowing_pattern只覆盖了{len(patterns)}种"
                    f"（{pattern_desc}），至少要覆盖{min_patterns}种不同的机制借用模式——不能让候选集合"
                    "挤在同一条探索路径上（比如全都within_tradition），那样候选之间的差异只是措辞不同，"
                    "不是真正不同的解释方向。",
                    f"The {len(data.candidates)} candidates' mechanism_borrowing_pattern only covers "
                    f"{len(patterns)} type(s) ({pattern_desc}); at least {min_patterns} distinct "
                    "mechanism-borrowing patterns are required — the candidate set can't all crowd onto "
                    "the same exploration path (e.g. all within_tradition), or the candidates would "
                    "differ only in wording, not in genuinely different explanatory directions.",
                )
            )
        return data

    return agent


def _rank_candidates(candidates: list[CandidateTheory], comparisons: list[PairwiseComparison]) -> tuple[list[str], str, list[str]]:
    """Compute the final ranking from pairwise comparison judgments — a simplified Copeland method:
    1 point per win, 0.5 points each on a tie, sorted by total score descending; ties on total score go
    into tied_candidate_names, and selected_candidate_name is whichever tied candidate comes first in
    candidates' original generation order (not an arbitrary pick — "generation order" is the one
    meaningful, unambiguous, deterministic tiebreaker, so the same run doesn't produce a different
    selected candidate each time.

    **This is not full Elo**: there's no iterative K-factor update, just one round-robin among a single
    batch of candidates — but that's already enough to solve the problem of "absolute scores all crowd
    into 3-4 points, impossible to rank," without needing extra model calls, still completing within
    "one agent run" — see the module-level comment before PairwiseComparison in atba/schemas.py."""

    scores: dict[str, float] = {c.candidate_name: 0.0 for c in candidates}
    for cmp in comparisons:
        if cmp.winner == "tie":
            scores[cmp.candidate_a] = scores.get(cmp.candidate_a, 0.0) + 0.5
            scores[cmp.candidate_b] = scores.get(cmp.candidate_b, 0.0) + 0.5
        else:
            scores[cmp.winner] = scores.get(cmp.winner, 0.0) + 1.0

    original_order = {c.candidate_name: i for i, c in enumerate(candidates)}
    ranked = sorted(scores.keys(), key=lambda name: (-scores[name], original_order.get(name, 0)))
    if not ranked:
        return [], "", []

    top_score = scores[ranked[0]]
    tied = [name for name in ranked if scores[name] == top_score]
    selected = min(tied, key=lambda name: original_order.get(name, 0))
    tied_others = [name for name in tied if name != selected]
    return ranked, selected, tied_others


def _load_inputs(run_id: str) -> tuple[PhenomenonDeconstruction, Optional[CausalPresuppositionCheck], Step3Result]:
    """Step 4's input sources: the phenomenon card step 1 persisted (+ the user's own guess extracted by
    the causal-presupposition check, if any), and the research question step 3 persisted."""
    step1 = load_stage_output(run_id, "step1", Step1Result)
    if step1.deconstruction is None:
        raise ValueError(
            f"run {run_id} does not yet have a usable phenomenon card (step 1 status={step1.status.value}, "
            "deconstruction is empty): step 4 requires step 1 to have passed (status=passed) first."
        )
    step3 = load_stage_output(run_id, "step3", Step3Result)
    if not step3.is_ok() or not step3.research_question:
        raise ValueError(
            f"run {run_id}'s step 3 has not produced a usable research question yet (status="
            f"{step3.status.value}): step 4 requires step 3 to have passed and provided a "
            "research_question first."
        )
    return step1.deconstruction, step1.causal_check, step3


def _anchor_theory_name(step3: Step3Result) -> str:
    """Step 3's anchor_theory_direction is a relatively new structured field (older runs don't have it);
    falls back to the first direction in examined_directions that produced a candidate research
    question — not an ideal path, just to avoid outright erroring on old data; new runs should all have
    anchor_theory_direction and never hit this fallback branch."""
    if step3.anchor_theory_direction:
        return step3.anchor_theory_direction
    for d in step3.examined_directions:
        if d.hit_level.value not in ("retrieval_unavailable", "not_examined"):
            return d.theory_name
    return step3.examined_directions[0].theory_name if step3.examined_directions else "(unknown theoretical direction)"


def _task_text(
    run_id: str,
    card: PhenomenonDeconstruction,
    causal_check: Optional[CausalPresuppositionCheck],
    step3: Step3Result,
    round_number: int,
    revision_instruction: Optional[str],
    revision_target_candidate: Optional[str],
    revision_target_field: Optional[CandidateElementField],
) -> str:
    lines = [
        "## Phenomenon card",
        f"actor: {card.actor}",
        f"observed_behavior: {card.observed_behavior}",
        f"field_constraints: {card.field_constraints}",
        f"apparent_motive: {card.apparent_motive or '(none — the phenomenon has no attributable actor)'}",
        f"observable_outcome: {card.observable_outcome}",
        "",
        "## Research question (produced in step 3)",
        f"Anchor theoretical direction: {_anchor_theory_name(step3)}",
        f"Research approach: {step3.research_approach.value if step3.research_approach else '(unknown)'}"
        + (f" · {step3.gap_type.value}" if step3.gap_type else ""),
        f"Research question: {step3.research_question}",
        f"Rationale: {step3.rationale}",
    ]
    if step3.mechanism_gap_characterization:
        gap_char = step3.mechanism_gap_characterization.value
        if gap_char == "anomalous_reversal":
            lines.append(
                "Nature of the gap: anomalous_reversal — step 3 judged this as not merely 'existing "
                "theory hasn't covered it,' but 'applying existing theory's core logic straightforwardly "
                "here would predict an opposite/contradictory result.' Candidate generation's task is "
                "therefore not simply 'filling a gap,' but explaining how the candidate theory revises/"
                "extends this core logic so it can accommodate both the original prediction and the "
                "opposite-direction result observed in this phenomenon — you can't just route around "
                "this core logic and start fresh elsewhere, or the candidate theory would become "
                "disconnected from step 3's judgment that 'this is a challenge to existing theory.'"
            )
        else:
            lines.append(
                "Nature of the gap: uncharted — existing theory genuinely hasn't studied this piece; "
                "candidate generation's task is to fill in this unexplored territory."
            )
    if step3.anchor_theory_grounding:
        g = step3.anchor_theory_grounding
        findings_lines = "\n".join(
            f"- {e.title}{f' ({e.year})' if e.year else ''}: {e.relevant_snippet}" for e in g.key_findings
        )
        lines += [
            "",
            "## The anchor theory's deep-retrieval state (produced in step 3, anchor_theory_grounding)",
            f"Established boundary conditions: {g.established_boundary_conditions}",
            f"Internal tensions/gaps: {g.internal_tensions_or_gaps}",
            f"Key findings:\n{findings_lines}" if findings_lines else "Key findings: (none)",
            "",
            "**This state is your background evidence for judging 'why existing constructs are "
            "insufficient to cover the research question,' but it is not your own retrieval target — "
            "your mechanism-grounding retrieval (sub-step 0) needs to step outside this theory and find, "
            "elsewhere, a mechanism that can fill the gap above; don't spend your budget continuing to "
            "dig into this theory itself, that work is already done here.**",
        ]
    # The literature step 3 actually retrieved and read the abstract of — not just the paper names
    # mentioned in the rationale prose above, but the full title + authors + year + supporting excerpt +
    # raw abstract. Without this section, "which existing construct was borrowed/modified" could only be
    # made up by the model's own background knowledge of the paper's content, rather than the actual
    # text step 3 really read — which would contradict this project's consistent discipline of "never
    # conclude from impression alone." Grouped by direction, covering every examined_directions entry
    # (not just the one the final research question anchors on), because the construct a candidate
    # theory borrows doesn't necessarily come from the direction the research question ultimately
    # anchored on.
    evidence_lines: list[str] = []
    for d in step3.examined_directions:
        if not d.cited_evidence:
            continue
        evidence_lines.append(f'### Literature retrieved for direction "{d.theory_name}"')
        for e in d.cited_evidence:
            evidence_lines.append(
                f"- {e.title}"
                f"{f' ({e.year})' if e.year else ''}"
                f"{' · ' + ', '.join(e.authors) if e.authors else ''}"
                f"{' · ' + e.source_title if e.source_title else ''}"
            )
            evidence_lines.append(f"  Basis for the judgment: {e.relevant_snippet}")
            if e.abstract:
                evidence_lines.append(f"  Original abstract: {e.abstract}")
    if evidence_lines:
        lines += [
            "",
            "## Literature step 3 actually retrieved (including the original abstract text — when "
            "citing/borrowing a specific construct you must go by the original text here, not "
            "supplement details absent here from your own background knowledge of the paper's content)",
            *evidence_lines,
        ]
    if causal_check and causal_check.hit and causal_check.extracted_explanation:
        lines += [
            "",
            "## The user's own guess (reference only for candidate generation, not implying it's been adopted)",
            causal_check.extracted_explanation,
        ]
    if round_number > 1 and revision_instruction:
        # Revision round: carries over the previous round's (round_number-1) persisted candidate set
        # as-is — the agent needs to know what the unchanged candidates look like to actually
        # "only change the one named, leave the rest alone," instead of reinventing the other
        # candidates from just this one line of revision_instruction feedback. The previous round's
        # result must already exist (if it doesn't, that means the caller passed bad arguments, and
        # erroring out here directly is safer than silently skipping).
        prior = load_stage_output(run_id, "step4", Step4Result)
        prior_summary = "\n\n".join(
            f'### Candidate "{c.candidate_name}"{" (is_baseline=True, null-hypothesis baseline)" if c.is_baseline else ""}\n'
            f"X: {c.theory_elements.x} / Y: {c.theory_elements.y} / Mechanism: {c.theory_elements.mechanism}\n"
            f"Mechanism-borrowing pattern: {c.mechanism_borrowing_pattern.value}\n"
            f"Explanation: {c.explanation_of_phenomenon}"
            for c in prior.candidates
        )
        grounding_note = (
            "This run has no round-1 mechanism_grounding record yet (an abnormal situation that "
            "shouldn't normally happen) — please run a fresh mechanism-grounding retrieval yourself."
        )
        if prior.mechanism_grounding:
            g = prior.mechanism_grounding
            findings_lines = "\n".join(
                f"- {e.title}{f' ({e.year})' if e.year else ''}: {e.relevant_snippet}" for e in g.donor_findings
            )
            grounding_note = (
                f"Abstract mechanism pattern: {g.abstract_mechanism_pattern}\n"
                f"Retrieved mechanism-source literature:\n"
                f"{findings_lines if findings_lines else '(none — this took the within_tradition route)'}\n\n"
                "**This mechanism-grounding retrieval was already done in the previous round — just "
                "reuse it as-is in `mechanism_grounding`, no need to call the retrieval tool again** — "
                "unless step 5's feedback explicitly points to 'a mechanism direction was missed,' in "
                "which case a targeted supplementary retrieval is warranted."
            )
        if revision_target_candidate:
            if revision_target_field == CandidateElementField.WHOLE_CANDIDATE:
                scope_desc = "Step 5 judged the core mechanism as a whole doesn't hold up; this candidate needs to be reconstructed entirely"
            else:
                field_name = revision_target_field.value if revision_target_field else "this field"
                scope_desc = (
                    f"Step 5 only pinpointed this candidate's `{field_name}` field as problematic — "
                    "rewrite only this one field; this candidate's other fields (the rest of "
                    "theory_elements, borrowed_or_modified_construct, explanation_of_phenomenon, etc.) "
                    "should also be kept as-is, don't change them along the way"
                )
            target_note = (
                f'**Only candidate "{revision_target_candidate}" needs to be rewritten; keep every other '
                f"candidate as-is, copying them verbatim into your output — do not rewrite them** "
                f"({scope_desc})."
            )
        else:
            target_note = (
                "Step 5 didn't pinpoint a specific candidate/field — use your own judgment based on the "
                "description in loop_back_instruction to determine the scope of revision needed, and try "
                "not to touch candidates unrelated to this feedback."
            )
        lines += [
            "",
            f"## This is round {round_number}: a revision round",
            f"The mechanism-grounding retrieval result from the previous round (round {prior.round_number}):",
            grounding_note,
            "",
            f"The candidate theory set from the previous round (round {prior.round_number}):",
            prior_summary,
            "",
            "Step 5's independent interrogation found a core-mechanism flaw in one candidate theory from "
            "the previous round; the specific feedback is:",
            revision_instruction,
            "",
            target_note,
            "",
            "You still need to provide the complete `mechanism_grounding` (can reuse the previous "
            "round's), all 3-5 complete candidates (candidates not named should be kept verbatim), and "
            "the complete `pairwise_comparisons` (even if a candidate's content is unchanged, rerun the "
            "pairwise comparison anyway, since the revised candidate's strength relative to the others "
            "may have changed).",
        ]
    return "\n".join(lines)


def _derive_result_kwargs(output: Step4Output) -> dict:
    ranked, selected, tied = _rank_candidates(output.candidates, output.pairwise_comparisons)
    return dict(
        mechanism_grounding=output.mechanism_grounding,
        candidates=output.candidates,
        pairwise_comparisons=output.pairwise_comparisons,
        ranked_candidate_names=ranked,
        selected_candidate_name=selected,
        tied_candidate_names=tied,
        selection_rationale=output.selection_rationale,
    )


def _agent_error_note(lang: str, exc: Exception) -> str:
    return f"第四步agent调用异常，转人工检查：{exc}" if lang == "zh" else f"Step 4 agent call failed, escalating to human review: {exc}"


def _pass_note(lang: str, round_number: int, output: Step4Output, selected_candidate_name: str) -> str:
    if lang == "zh":
        stage = "通过" if round_number == 1 else f"第{round_number}轮修订完成"
        return f"第四步{stage}：生成{len(output.candidates)}个候选理论，选定「{selected_candidate_name}」。"
    stage = "passed" if round_number == 1 else f"round {round_number} revision complete"
    return f'Step 4 {stage}: generated {len(output.candidates)} candidate theories, selected "{selected_candidate_name}".'


def run_step4(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    round_number: int = 1,
    revision_instruction: Optional[str] = None,
    revision_target_candidate: Optional[str] = None,
    revision_target_field: Optional[CandidateElementField] = None,
    reasoning_effort: Optional[str] = None,
) -> Step4Result:
    """Run step 4 end to end and return a unified Step4Result; the result is persisted to
    runs/<run_id>/step4.json (overwriting the previous round — earlier rounds don't get their own
    separate file; the full audit trail is kept in the loop history maintained by
    atba/abductive_loop.py).

    Args:
        round_number/revision_instruction: set by the caller (fixed at 1/None when the CLI/API calls
            this directly; atba/abductive_loop.py passes an incrementing round_number and step 5's
            feedback when orchestrating revision rounds) — this function itself never decides "whether
            to rerun," it only handles "given these parameters, run once."
        revision_target_candidate/revision_target_field: likewise supplied by the caller, from
            Step5Output's interrogated_candidate_name/loop_back_target_field — pinpoints the revision
            scope, see _task_text.
    """
    card, causal_check, step3 = _load_inputs(run_id)
    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step4Result:
        result = Step4Result(
            run_id=run_id,
            provider=provider,
            model=resolved_model,
            round_number=round_number,
            revision_instruction=revision_instruction if round_number > 1 else None,
            revision_target_candidate=revision_target_candidate if round_number > 1 else None,
            revision_target_field=revision_target_field if round_number > 1 else None,
            **kwargs,
        )
        save_stage_output(run_id, "step4", result)
        return result

    agent = _build_agent(provider, model, lang)
    task_text = _task_text(
        run_id, card, causal_check, step3, round_number, revision_instruction, revision_target_candidate, revision_target_field
    )
    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )
    try:
        run_result = agent.run_sync(task_text, model_settings=model_settings)
    except Exception as exc:
        return _finish(status=Step4Status.BLOCKED_AGENT_ERROR, note=_agent_error_note(lang, exc))

    output = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    result_kwargs = _derive_result_kwargs(output)
    note = _pass_note(lang, round_number, output, result_kwargs["selected_candidate_name"])
    return _finish(status=Step4Status.OK, note=note, audit_trail=audit_trail, usage=extract_usage(run_result), **result_kwargs)


async def stream_step4(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    round_number: int = 1,
    revision_instruction: Optional[str] = None,
    revision_target_candidate: Optional[str] = None,
    revision_target_field: Optional[CandidateElementField] = None,
    reasoning_effort: Optional[str] = None,
):
    """The streaming version of run_step4, with event types identical to the other steps' stream_stepN
    (thinking_delta/tool_call_delta/tool_result/tool_result_retry/final), forwarded directly by
    `/api/step4/stream`, and also forwarded event-by-event by `atba/abductive_loop.py` when it
    orchestrates the loop (which attaches round/phase markers before relaying to the final caller, see
    that file)."""
    try:
        card, causal_check, step3 = _load_inputs(run_id)
    except (FileNotFoundError, ValueError) as exc:
        note = f"第四步无法启动：{exc}" if lang == "zh" else f"Step 4 could not start: {exc}"
        final = Step4Result(
            run_id=run_id,
            status=Step4Status.BLOCKED_AGENT_ERROR,
            round_number=round_number,
            note=note,
        )
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step4Result:
        result = Step4Result(
            run_id=run_id,
            provider=provider,
            model=resolved_model,
            round_number=round_number,
            revision_instruction=revision_instruction if round_number > 1 else None,
            revision_target_candidate=revision_target_candidate if round_number > 1 else None,
            revision_target_field=revision_target_field if round_number > 1 else None,
            **kwargs,
        )
        save_stage_output(run_id, "step4", result)
        return result

    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )
    task_text = _task_text(
        run_id, card, causal_check, step3, round_number, revision_instruction, revision_target_candidate, revision_target_field
    )

    try:
        agent = _build_agent(provider, model, lang)
        run_result = None
        async with agent.run_stream_events(task_text, model_settings=model_settings) as events:
            async for event in events:
                ndjson_event, result = classify_stream_event(event)
                if ndjson_event is not None:
                    yield ndjson_event
                if result is not None:
                    run_result = result
    except Exception as exc:
        final = _finish(status=Step4Status.BLOCKED_AGENT_ERROR, note=_agent_error_note(lang, exc))
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    assert run_result is not None, "run_stream_events finished normally without an AgentRunResultEvent — an abnormal state"
    output = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    result_kwargs = _derive_result_kwargs(output)
    note = _pass_note(lang, round_number, output, result_kwargs["selected_candidate_name"])
    final = _finish(status=Step4Status.OK, note=note, audit_trail=audit_trail, usage=extract_usage(run_result), **result_kwargs)
    yield {"type": "final", "result": final.model_dump(mode="json")}
