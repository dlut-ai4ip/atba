"""Step 6: Theoretical Contribution Report — the runnable implementation.

Corresponds to the technical appendix's "Step 6" section. **Structurally different from the first
five steps**: the output isn't JSON, it's the full text of a markdown report — `_build_agent` has no
`output_type` (pydantic-ai's default output type is `str`), so the model's free-text output is the
final deliverable itself, no longer wrapped in the `ToolOutput` machinery. Consequently no retrieval
tool needs to be attached either: step 6 produces no new reasoning, it only aggregates the judgments
steps 1 through 5 have already made into one coherent report (see the module-level comment on
"Step 6" in `atba/schemas.py`).

**Input sources**: step 1's phenomenon card, step 3's research question plus all retrieved literature,
step 4's full set of candidate theories (including eliminated ones, for the appendix comparison table),
and step 5's final-round interrogation record (including the honestly listed unresolved weaknesses).
Step 6 requires step 5 to have already passed (`Step5Status.OK`) — a `blocked_unresolved` status means
the candidate theory repeatedly failed to survive interrogation, in which case writing a "theoretical
contribution report" is pointless; it should be escalated to human review first, rather than having
step 6 paper over the problem with a report.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from pydantic_ai import Agent, ModelRetry

from .agent_streaming import (
    anthropic_thinking_model_settings,
    classify_stream_event,
    deepseek_reasoning_model_settings,
    extract_usage,
    openai_reasoning_model_settings,
)
from .context_store import load_stage_output, save_stage_output
from .llm import DEFAULT_MODELS, build_model
from .prompts import step6_system_prompt
from .schemas import (
    PhenomenonDeconstruction,
    Step1Result,
    Step2Result,
    Step3Result,
    Step4Result,
    Step5Result,
    Step6Result,
    Step6Status,
    TokenUsage,
)

DEFAULT_PROVIDER = os.environ.get("ATBA_LLM_PROVIDER") or "anthropic"

# The five body-section headings the report must contain (one set per language, matched by lang) —
# not a full markdown-structure validation, just a minimal safety net: catching the rare case where the
# model omits a required section without anyone noticing, see the output_validator attached in
# _build_agent. "Boundary Conditions and Future Research" is a newly added fourth section (the original
# design folded this content into the "Theoretical Contribution" section; it was later split into its
# own section, see "report structure" in atba/prompts/step6.md — separating it out lets the
# "Theoretical Contribution" section read like a standard contribution paragraph, without limitations
# discussion mixed in).
_REQUIRED_HEADINGS = {
    "zh": ["引言", "理论与假设", "理论贡献", "边界条件与未来研究方向", "参考文献"],
    "en": [
        "Introduction",
        "Theory and Hypotheses",
        "Theoretical Contribution",
        "Boundary Conditions and Future Research",
        "References",
    ],
}

_REFERENCES_HEADING = {"zh": "参考文献", "en": "References"}


def _find_references_heading(output: str, lang: str) -> Optional[re.Match]:
    """Locates the "References" level-2 heading line — **does not require the whole line to match the
    heading text exactly**, only that the line starts with `##` and contains this word (a loose match,
    at the same tolerance level as _check_required_sections' `in` substring check). This was a real
    pitfall once: the first version required an exact whole-line match via
    `^##\\s*{heading}\\s*$`, and the model's actual output — variants like "## 5. 参考文献" (with a
    section number, mimicking the "### 5. 参考文献" style the prompt itself used to describe the report
    structure) or "## **参考文献**" — would fail to match because of the extra digit/bold markers on
    the heading line. Once the heading fails to match, _count_reference_items always returns 0, causing
    every `#ref-N` in the body to be misjudged as "out of range," and four consecutive retries all
    failed (this was actually reproduced in testing, see the commit message)."""
    heading = _REFERENCES_HEADING.get(lang, _REFERENCES_HEADING["zh"])
    return re.search(rf"^##[^\n]*{re.escape(heading)}[^\n]*$", output, re.MULTILINE)


def _count_reference_items(output: str, lang: str) -> int:
    """Counts the number of ordered-list items under the "References" level-2 heading, up to the next
    level-2 heading or `---` divider — used to check whether an in-text `#ref-N`'s N is out of range.
    Doesn't require the model's own numbering to be sequentially correct: the frontend doesn't read
    these numbers itself, it assigns `id="ref-N"` to each entry based on the actual order the reference
    list renders into the DOM (see frontend/src/components/ReportView.tsx) — this counts the same way,
    "how many list items are in this range," to stay consistent with how the frontend assigns IDs."""
    m = _find_references_heading(output, lang)
    if not m:
        return 0
    rest = output[m.end() :]
    end = re.search(r"^(##\s|---\s*$)", rest, re.MULTILINE)
    section = rest[: end.start()] if end else rest
    return len(re.findall(r"^\s*\d+[.)]\s+\S", section, re.MULTILINE))


def _dangling_ref_targets(output: str, lang: str) -> list[int]:
    """Picks out every `#ref-N` link target appearing in the body (the part before the References
    section) whose N falls outside the range of the reference list's item count — see the numbering
    rule in the "citation format" section of atba/prompts/step6.zh.md. A mismatched number isn't an
    edge case that can be let slide: the frontend really does navigate by this N, and pointing to a
    nonexistent location is a genuinely bad experience for the reader."""
    m = _find_references_heading(output, lang)
    body = output[: m.start()] if m else output
    targets = {int(n) for n in re.findall(r"\]\(#ref-(\d+)\)", body)}
    if not targets:
        return []
    total = _count_reference_items(output, lang)
    return sorted(n for n in targets if n < 1 or n > total)


def _build_agent(provider: str, model_name: Optional[str], lang: str) -> Agent[None, str]:
    model = build_model(provider, model_name)
    agent = Agent(
        model=model,
        system_prompt=step6_system_prompt(lang=lang),
        retries=4,
        name="atba_step6",
    )

    @agent.output_validator
    def _check_required_sections(output: str) -> str:
        missing = [h for h in _REQUIRED_HEADINGS.get(lang, _REQUIRED_HEADINGS["zh"]) if h not in output]
        if missing:
            raise ModelRetry(
                f"报告缺少必需小节：{missing}。请补全后重新输出完整报告全文（不是只输出缺的部分）。"
                if lang == "zh"
                else f"The report is missing required section(s): {missing}. Please output the complete "
                "report again with these included (not just the missing part)."
            )
        return output

    @agent.output_validator
    def _check_citation_links(output: str) -> str:
        bad = _dangling_ref_targets(output, lang)
        if bad:
            total = _count_reference_items(output, lang)
            raise ModelRetry(
                f"正文里的引用链接指向了不存在的参考文献编号：{bad}（参考文献列表目前共有{total}条，"
                "编号必须落在1~该条数之间，且要跟参考文献列表里条目的实际顺序一一对应）。请检查正文"
                "里[(Author, Year)](#ref-N)链接与参考文献列表的编号是否对应，修正后重新输出完整报告"
                "全文（不是只输出修正的部分）。"
                if lang == "zh"
                else f"In-text citation links point to reference numbers that don't exist: {bad} (the "
                f"References list currently has {total} entries; link numbers must fall between 1 and "
                "that count, matching the list's actual order). Please check that every "
                "[(Author, Year)](#ref-N) link in the body matches the References list's numbering, then "
                "output the complete report again (not just the corrected part)."
            )
        return output

    return agent


def _load_inputs(run_id: str) -> tuple[PhenomenonDeconstruction, Step3Result, Step4Result, Step5Result]:
    step1 = load_stage_output(run_id, "step1", Step1Result)
    if step1.deconstruction is None:
        raise ValueError(f"run {run_id} does not yet have a usable phenomenon card: step 6 requires step 1 to have passed first.")
    step3 = load_stage_output(run_id, "step3", Step3Result)
    if not step3.is_ok() or not step3.research_question:
        raise ValueError(f"run {run_id}'s step 3 has not produced a usable research question yet: step 6 requires step 3 to have passed first.")
    step4 = load_stage_output(run_id, "step4", Step4Result)
    if not step4.is_ok() or not step4.candidates:
        raise ValueError(f"run {run_id}'s step 4 has no candidate theories yet (status={step4.status.value}): step 6 requires step 4 to have passed first.")
    step5 = load_stage_output(run_id, "step5", Step5Result)
    if not step5.is_ok():
        raise ValueError(
            f"run {run_id}'s step 5 status is {step5.status.value}, not passed: step 6 requires the "
            "candidate theory to have survived step 5's adversarial interrogation (or at least not have "
            "been repeatedly judged to have a flawed core mechanism) before a theoretical contribution "
            "report can be written — blocked_unresolved means this candidate theory should first be "
            "escalated to human review; step 6 must not write a report that papers over the problem."
        )
    return step1.deconstruction, step3, step4, step5


def _task_text(
    card: PhenomenonDeconstruction,
    step3: Step3Result,
    step4: Step4Result,
    step5: Step5Result,
) -> str:
    lines = [
        "## Phenomenon card",
        f"actor: {card.actor}",
        f"observed_behavior: {card.observed_behavior}",
        f"field_constraints: {card.field_constraints}",
        f"apparent_motive: {card.apparent_motive or '(none — the phenomenon has no attributable actor)'}",
        f"observable_outcome: {card.observable_outcome}",
        "",
        "## Research question (step 3)",
        f"Anchor theoretical direction: {step3.anchor_theory_direction or '(unknown)'}",
        f"Research approach: {step3.research_approach.value if step3.research_approach else '(unknown)'}"
        + (f" · {step3.gap_type.value}" if step3.gap_type else ""),
        f"Research question: {step3.research_question}",
        f"Retrieval coverage report: {step3.coverage_report}",
        f"Rationale: {step3.rationale}",
    ]
    if step3.mechanism_gap_characterization:
        gap_char = step3.mechanism_gap_characterization.value
        lines.append(
            "Nature of the gap: anomalous_reversal — applying existing theory's (the anchor theoretical "
            "direction's) core logic straightforwardly here would predict the opposite-direction result; "
            "this isn't merely uncovered, it's challenged by the phenomenon. The report's introduction "
            "and theoretical-foundations sections should be worded to reflect 'this is a revision/"
            "extension of existing theory,' not written as simply 'filling an unexplored gap' — the two "
            "are different contribution narratives, see the writing discipline in the system prompt."
            if gap_char == "anomalous_reversal"
            else "Nature of the gap: uncharted — existing theory genuinely hasn't studied this piece; the "
            "report can be written with the standard 'filling a gap' narrative."
        )

    lines.append("")
    lines.append(
        "## The anchor theory's deep-retrieval state (produced in step 3 — the deep retrieval done on "
        "the anchor theoretical direction itself, the main evidence for writing the 'what is the "
        "existing theoretical tradition, why is it insufficient' part of the 'Theoretical Foundations' "
        "section)"
    )
    if step3.anchor_theory_grounding:
        g = step3.anchor_theory_grounding
        lines.append(f"Anchor theory: {g.anchor_theory}")
        lines.append(f"Established boundary conditions: {g.established_boundary_conditions}")
        lines.append(f"Internal tensions/gaps: {g.internal_tensions_or_gaps}")
        lines.append("Key findings (including original abstract text):")
        for e in g.key_findings:
            lines.append(
                f"- {e.title}"
                f"{f' ({e.year})' if e.year else ''}"
                f"{' · ' + ', '.join(e.authors) if e.authors else ''}"
                f"{' · ' + e.source_title if e.source_title else ''}"
                f"{' · DOI: ' + e.doi if e.doi else ''}"
            )
            lines.append(f"  Basis for the judgment: {e.relevant_snippet}")
            if e.abstract:
                lines.append(f"  Original abstract: {e.abstract}")

    lines.append("")
    lines.append(
        "## Step 4's mechanism-grounding retrieval (the output of sub-step 0 — retrieving, outside the "
        "anchor theory, other mechanisms that can explain the gap; the main evidence for writing the "
        "'where the new mechanism was borrowed from, why it can fill this gap' part of the "
        "'Theoretical Foundations' section, a different thing from the anchor-theory retrieval above — "
        "don't mix the two into one section)"
    )
    if step4.mechanism_grounding:
        mg = step4.mechanism_grounding
        lines.append(f"Abstract mechanism pattern: {mg.abstract_mechanism_pattern}")
        if mg.donor_findings:
            lines.append("Retrieved mechanism-source literature (including original abstract text):")
            for e in mg.donor_findings:
                lines.append(
                    f"- {e.title}"
                    f"{f' ({e.year})' if e.year else ''}"
                    f"{' · ' + ', '.join(e.authors) if e.authors else ''}"
                    f"{' · ' + e.source_title if e.source_title else ''}"
                    f"{' · DOI: ' + e.doi if e.doi else ''}"
                )
                lines.append(f"  Basis for the judgment: {e.relevant_snippet}")
                if e.abstract:
                    lines.append(f"  Original abstract: {e.abstract}")
        else:
            lines.append("(No suitable external mechanism was retrieved this time; the selected candidate takes the within-tradition deep-dive route.)")

    lines.append("")
    lines.append(
        "## All literature step 3 actually retrieved (supplementary reference, also needed when "
        "writing the References section — but the Theoretical Foundations section should primarily "
        "draw on step 4's deep retrieval above)"
    )
    for d in step3.examined_directions:
        if not d.cited_evidence:
            continue
        lines.append(f'### Direction "{d.theory_name}"')
        for e in d.cited_evidence:
            lines.append(
                f"- {e.title}"
                f"{f' ({e.year})' if e.year else ''}"
                f"{' · ' + ', '.join(e.authors) if e.authors else ''}"
                f"{' · ' + e.source_title if e.source_title else ''}"
                f"{' · DOI: ' + e.doi if e.doi else ''}"
            )
            if e.abstract:
                lines.append(f"  Original abstract: {e.abstract}")

    lines.append("")
    lines.append(
        f'## All of step 4\'s candidate theories ({len(step4.candidates)} total; selected candidate: '
        f'"{step4.selected_candidate_name}"'
        f"{'; tied candidates: ' + ', '.join(step4.tied_candidate_names) if step4.tied_candidate_names else ''})"
    )
    for c in step4.candidates:
        te = c.theory_elements
        v = c.virtue_scores
        is_selected = c.candidate_name == step4.selected_candidate_name
        lines.append(f'### Candidate "{c.candidate_name}"{" (selected)" if is_selected else ""}')
        lines.append(f"X: {te.x}")
        lines.append(f"Y: {te.y}")
        lines.append(f"Relation form: {te.relation_form}")
        lines.append(f"Mechanism: {te.mechanism}")
        lines.append(f"Assumption: {te.assumption}")
        if te.boundary_conditions:
            lines.append(f"Boundary conditions: {te.boundary_conditions}")
        lines.append(f"Mechanism-borrowing pattern: {c.mechanism_borrowing_pattern.value}")
        lines.append(f"Borrowed/modified existing construct: {c.borrowed_or_modified_construct}")
        if c.disanalogy_note:
            lines.append(f"Self-disclosed limitation of the cross-tradition borrowing (disanalogy_note): {c.disanalogy_note}")
        lines.append(f"Why existing constructs are insufficient: {c.why_existing_insufficient}")
        lines.append(f"Full explanation of the phenomenon: {c.explanation_of_phenomenon}")
        lines.append(f"Mutual-exclusivity self-check: {c.mutual_exclusivity_note}")
        lines.append(
            f"Four-virtue scores: consilience={v.consilience} coherence={v.coherence} "
            f"parsimony={v.parsimony} precision={v.precision}"
        )
        lines.append(f"Scoring rationale: {v.graph_based_rationale}")
        lines.append(f"Rank: {'#' + str(step4.ranked_candidate_names.index(c.candidate_name) + 1) if c.candidate_name in step4.ranked_candidate_names else '(not ranked)'}")
        lines.append("")

    lines.append(
        f'## Step 5\'s adversarial interrogation record (for "{step5.interrogated_candidate_name}", '
        f"overall verdict: {step5.overall_verdict.value if step5.overall_verdict else '(unknown)'})"
    )
    for ex in step5.exchanges:
        lines.append(f"### {ex.question_type.value} (verdict: {ex.verdict.value})")
        lines.append(f"Question: {ex.question}")
        lines.append(f"Response: {ex.assessment}")
    if step5.unanswered_weaknesses:
        lines.append("")
        lines.append("### Honestly listed unresolved weaknesses (must be honestly folded into the report's theoretical-contribution/limitations section, not glossed over)")
        for w in step5.unanswered_weaknesses:
            lines.append(f"- {w}")
    if len(step5.loop_history) > 1:
        lines.append("")
        lines.append(f"### Full loop history ({len(step5.loop_history)} round(s) total, including this final one)")
        for h in step5.loop_history:
            lines.append(
                f'- Round {h.round_number} · "{h.interrogated_candidate_name}" · verdict: {h.overall_verdict.value}'
                + (f" · loop-back instruction: {h.loop_back_instruction}" if h.loop_back_instruction else "")
            )

    return "\n".join(lines)


def _aggregate_run_usage(
    run_id: str, step6_provider: str, step6_model: str, step6_usage: Optional[TokenUsage]
) -> tuple[TokenUsage, list[str]]:
    """Aggregates the total tokens this run actually spent from step 1 through step 6, and every
    provider+model combination actually used (deduplicated, pre-formatted as "model (provider)"
    strings) — used by "this run's stats" at the bottom of the report page.

    Each round's usage inside the step-4/5 loop is **not** obtained by re-reading step4.json/
    step5.json themselves — those two files get overwritten by the next round's save_stage_output every
    round, so only the last round ever survives on disk; the actually-complete per-round usage lives in
    Step5Result.loop_history (each Step5RoundSummary's step4_usage/step5_usage) — that's exactly the
    responsibility an "append-only, never overwritten" field like loop_history should carry, see the
    relevant comment in atba/abductive_loop.py.

    A missing/failed read of any step's output never lets a problem in this statistics feature itself
    take down the report body's generation — it degrades to "this step contributes 0 / isn't counted in
    the model list," without raising; for historical runs that predate this change, earlier steps'
    usage fields will be None (the default value when deserializing old data), and the aggregated total
    will read low — that's an inherent limitation of retroactive instrumentation, not a bug.
    """
    total = TokenUsage()
    models: list[str] = []

    def _note_model(provider: str, model: str) -> None:
        if not provider and not model:
            return
        label = f"{model} ({provider})" if provider else model
        if label not in models:
            models.append(label)

    for stage, cls in (("step1", Step1Result), ("step2", Step2Result), ("step3", Step3Result)):
        try:
            r = load_stage_output(run_id, stage, cls)
        except Exception:
            continue
        if r.usage:
            total = total + r.usage
        _note_model(r.provider, r.model)

    try:
        step5 = load_stage_output(run_id, "step5", Step5Result)
    except Exception:
        step5 = None
    if step5:
        _note_model(step5.provider, step5.model)
        for round_summary in step5.loop_history:
            if round_summary.step4_usage:
                total = total + round_summary.step4_usage
            if round_summary.step5_usage:
                total = total + round_summary.step5_usage
        if not step5.loop_history:
            # Normally there's always at least one round — an empty loop_history is either abnormal or
            # old data; fall back to reading step4.json/step5.json's own usage directly, which is
            # better than the whole loop's spend showing up as 0.
            try:
                step4 = load_stage_output(run_id, "step4", Step4Result)
                if step4.usage:
                    total = total + step4.usage
            except Exception:
                pass
            if step5.usage:
                total = total + step5.usage

    _note_model(step6_provider, step6_model)
    if step6_usage:
        total = total + step6_usage

    return total, models


def _finish_kwargs(
    run_id: str,
    step5: Step5Result,
    report_markdown: str,
    provider: str,
    model: str,
    own_usage: Optional[TokenUsage],
    lang: str,
) -> dict:
    total_usage, models_used = _aggregate_run_usage(run_id, provider, model, own_usage)
    note = (
        f"第六步通过：已生成理论贡献报告全文（{len(report_markdown)}字符），基于候选"
        f"「{step5.interrogated_candidate_name}」。"
        if lang == "zh"
        else f'Step 6 passed: generated the full theoretical contribution report ({len(report_markdown)} '
        f'characters), based on candidate "{step5.interrogated_candidate_name}".'
    )
    return dict(
        status=Step6Status.OK,
        report_markdown=report_markdown,
        source_candidate_name=step5.interrogated_candidate_name,
        note=note,
        total_run_usage=total_usage,
        models_used=models_used,
    )


def _agent_error_note(lang: str, exc: Exception) -> str:
    return f"第六步agent调用异常，转人工检查：{exc}" if lang == "zh" else f"Step 6 agent call failed, escalating to human review: {exc}"


def run_step6(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    reasoning_effort: Optional[str] = None,
) -> Step6Result:
    """Run step 6 end to end and return a unified Step6Result; the result is persisted to
    runs/<run_id>/step6.json."""
    card, step3, step4, step5 = _load_inputs(run_id)
    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step6Result:
        result = Step6Result(run_id=run_id, provider=provider, model=resolved_model, **kwargs)
        save_stage_output(run_id, "step6", result)
        return result

    agent = _build_agent(provider, model, lang)
    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )
    try:
        run_result = agent.run_sync(_task_text(card, step3, step4, step5), model_settings=model_settings)
    except Exception as exc:
        return _finish(status=Step6Status.BLOCKED_AGENT_ERROR, note=_agent_error_note(lang, exc))

    report_markdown = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    own_usage = extract_usage(run_result)
    return _finish(
        audit_trail=audit_trail,
        usage=own_usage,
        **_finish_kwargs(run_id, step5, report_markdown, provider, resolved_model, own_usage, lang),
    )


async def stream_step6(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    reasoning_effort: Optional[str] = None,
):
    """The streaming version of run_step6 — the `text_delta` event carries the report body's own
    incremental text (not a JSON fragment that only takes shape at the end, as with ToolOutput), letting
    the frontend genuinely "read as it's generated," see the "step 6 adds text_delta" section in
    atba/agent_streaming.py's top-of-file docstring."""
    try:
        card, step3, step4, step5 = _load_inputs(run_id)
    except (FileNotFoundError, ValueError) as exc:
        note = f"第六步无法启动：{exc}" if lang == "zh" else f"Step 6 could not start: {exc}"
        final = Step6Result(run_id=run_id, status=Step6Status.BLOCKED_AGENT_ERROR, note=note)
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step6Result:
        result = Step6Result(run_id=run_id, provider=provider, model=resolved_model, **kwargs)
        save_stage_output(run_id, "step6", result)
        return result

    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )
    task_text = _task_text(card, step3, step4, step5)

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
        final = _finish(status=Step6Status.BLOCKED_AGENT_ERROR, note=_agent_error_note(lang, exc))
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    assert run_result is not None, "run_stream_events finished normally without an AgentRunResultEvent — an abnormal state"
    report_markdown = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    own_usage = extract_usage(run_result)
    final = _finish(
        audit_trail=audit_trail,
        usage=own_usage,
        **_finish_kwargs(run_id, step5, report_markdown, provider, resolved_model, own_usage, lang),
    )
    yield {"type": "final", "result": final.model_dump(mode="json")}
