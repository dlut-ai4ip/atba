"""Step 5: Adversarial Interrogation — the runnable implementation.

Corresponds to the technical appendix's "Step 5" section. **Core design constraint**: this step runs
as a sub-agent independent from step 4's generation process, given only the candidate theory's
object-level content, never told how the candidate theory was authored/scored/selected — `_task_text`
picks only the "theory content" fields `theory_elements`/`borrowed_or_modified_construct`/
`why_existing_insufficient`/`explanation_of_phenomenon` from Step4Result, deliberately excluding
`virtue_scores`/`novelty_check`/`lakatos_judgment`/`selection_rationale` — those are all step 4's own
meta-reasoning, and leaking them to step 5 would turn "independent interrogation" into "read the
generator's own self-justification and nod along," defeating the point of this step.

**This file handles only a single round of interrogation** (like step 4, an independently testable/
callable module that knows nothing about "the loop") — whether an interrogation failure should send
things back to step 4 to regenerate, and how many rounds, is atba/abductive_loop.py's responsibility.

**The relabeling-suspicion question also plugs into D.4's retrieval capability**: the agent can't just
judge out of thin air whether "this is just an existing construct wearing a new label" — like steps 3
and 4, `search_scopus`/`get_paper_abstract` are wired into `toolsets` for independent retrieval
verification — in particular, step 4's own novelty-check conclusion (which step 5 can't even see) must
never be trusted here.
"""

from __future__ import annotations

import json
import os
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
from .prompts import step5_system_prompt
from .schemas import (
    CandidateTheory,
    InterrogationVerdict,
    PhenomenonDeconstruction,
    Step1Result,
    Step3Result,
    Step4Result,
    Step5Output,
    Step5Result,
    Step5Status,
)

DEFAULT_PROVIDER = os.environ.get("ATBA_LLM_PROVIDER") or "anthropic"

STEP5_TOOL_NAME = "report_step5_output"


def _build_agent(provider: str, model_name: Optional[str], lang: str) -> Agent[None, Step5Output]:
    model = build_model(provider, model_name)
    agent = Agent(
        model=model,
        toolsets=[build_retrieval_toolset()],
        output_type=ToolOutput(
            Step5Output,
            name=STEP5_TOOL_NAME,
            description="Report step 5's final result: the interrogation record across the three question types, an honest list of unresolved weaknesses, the overall verdict, and (when the verdict is fails) the revision instruction for step 4 plus the specific field it pinpoints.",
        ),
        system_prompt=step5_system_prompt(lang=lang),
        retries=8,
        name="atba_step5",
    )
    return _attach_output_validator(agent, lang)


def _attach_output_validator(agent: Agent[None, Step5Output], lang: str) -> Agent[None, Step5Output]:
    """When overall_verdict=fails, loop_back_target_field is an Optional field (required only in that
    case, so it can't be marked required outright) — the same reason atba/step3.py's
    _attach_conditional_field_validator needs an extra output_validator: relying on the prompt text
    alone isn't reliable enough."""

    @agent.output_validator
    def _check_loop_back_target_field(data: Step5Output) -> Step5Output:
        if data.overall_verdict == InterrogationVerdict.FAILS and data.loop_back_target_field is None:
            raise ModelRetry(
                "overall_verdict是fails，但没有填写loop_back_target_field——请从候选理论的"
                "theory_elements/borrowed_or_modified_construct/why_existing_insufficient/"
                "explanation_of_phenomenon里定位具体是哪个字段站不住脚，填对应的取值；如果核心"
                "机制整体站不住脚、没法归到某一个具体字段，填whole_candidate，不能留空。"
                if lang == "zh"
                else "overall_verdict is fails but loop_back_target_field is empty — pinpoint which "
                "field of the candidate theory's theory_elements/borrowed_or_modified_construct/"
                "why_existing_insufficient/explanation_of_phenomenon doesn't hold up, and fill in the "
                "corresponding value; if the core mechanism fails as a whole and can't be attributed to "
                "one specific field, use whole_candidate — it cannot be left empty."
            )
        return data

    return agent


def _load_inputs(run_id: str) -> tuple[PhenomenonDeconstruction, Step3Result, Step4Result]:
    """Step 5's input sources: step 1's phenomenon card, step 3's research question (as objective
    background, not the candidate theory author's self-justification), and the **current** candidate
    set persisted by step 4 (loop_history — which round's which candidate to interrogate — is decided
    by the caller, atba/abductive_loop.py; this always reads whatever is currently persisted in
    step4.json)."""
    step1 = load_stage_output(run_id, "step1", Step1Result)
    if step1.deconstruction is None:
        raise ValueError(f"run {run_id} does not yet have a usable phenomenon card: step 5 requires step 1 to have passed first.")
    step3 = load_stage_output(run_id, "step3", Step3Result)
    if not step3.is_ok() or not step3.research_question:
        raise ValueError(f"run {run_id}'s step 3 has not produced a usable research question yet: step 5 requires step 3 to have passed first.")
    step4 = load_stage_output(run_id, "step4", Step4Result)
    if not step4.is_ok() or not step4.selected_candidate_name:
        raise ValueError(f"run {run_id}'s step 4 has not selected a candidate theory yet (status={step4.status.value}): step 5 requires step 4 to have passed first.")
    return step1.deconstruction, step3, step4


def _selected_candidate(step4: Step4Result) -> CandidateTheory:
    for c in step4.candidates:
        if c.candidate_name == step4.selected_candidate_name:
            return c
    raise ValueError(
        f"run {step4.run_id}'s step 4 has selected_candidate_name={step4.selected_candidate_name!r} "
        "which cannot be found in the candidates list — step 4's persisted data is inconsistent and "
        "needs manual inspection."
    )


def _task_text(card: PhenomenonDeconstruction, step3: Step3Result, candidate: CandidateTheory) -> str:
    """Deliberately picks only the candidate theory's object-level content — excluding
    virtue_scores/novelty_check/lakatos_judgment/step 4's selection_rationale, per this file's
    top-of-file docstring on the core design constraint."""
    te = candidate.theory_elements
    lines = [
        "## Phenomenon card (objective background, not the candidate theory author's self-justification)",
        f"actor: {card.actor}",
        f"observed_behavior: {card.observed_behavior}",
        f"field_constraints: {card.field_constraints}",
        f"apparent_motive: {card.apparent_motive or '(none)'}",
        f"observable_outcome: {card.observable_outcome}",
        "",
        "## Research question (objective background)",
        f"{step3.research_question}",
        "",
        f"## Candidate theory under interrogation: {candidate.candidate_name}",
        f"X (independent/antecedent construct): {te.x}",
        f"Y (dependent/outcome construct): {te.y}",
        f"Relation form: {te.relation_form}",
        f"Mechanism: {te.mechanism}",
        f"Assumption: {te.assumption}",
        f"Boundary conditions: {te.boundary_conditions or '(not specified)'}",
        f"Mechanism-borrowing pattern: {candidate.mechanism_borrowing_pattern.value}",
        f"Borrowed/modified construct: {candidate.borrowed_or_modified_construct}",
        f"Why existing constructs are insufficient: {candidate.why_existing_insufficient}",
        f"Full explanation of the phenomenon: {candidate.explanation_of_phenomenon}",
    ]
    if candidate.disanalogy_note:
        lines.append(
            f"Self-disclosed limitation of the cross-tradition borrowing (disanalogy_note): "
            f"{candidate.disanalogy_note} — this is where the candidate theory's author disclosed, in "
            "their own words, where the borrowing doesn't carry over; your interrogation should focus "
            "on verifying whether this disclosure is honest, and whether it downplays a more serious "
            "mismatch."
        )
    return "\n".join(lines)


def _derive_result_kwargs(output: Step5Output) -> dict:
    return dict(
        interrogated_candidate_name=output.interrogated_candidate_name,
        exchanges=output.exchanges,
        unanswered_weaknesses=output.unanswered_weaknesses,
        overall_verdict=output.overall_verdict,
        # This used to be missing — without this field, Step5Result had nowhere to receive
        # output.loop_back_instruction, and atba/abductive_loop.py reads step5.loop_back_instruction
        # when actually triggering a revision (overall_verdict=fails); missing this crashed with a
        # plain AttributeError. See the comment on that field in Step5Result.
        loop_back_instruction=output.loop_back_instruction,
        loop_back_target_field=output.loop_back_target_field,
    )


def _agent_error_note(lang: str, exc: Exception) -> str:
    return f"第五步agent调用异常，转人工检查：{exc}" if lang == "zh" else f"Step 5 agent call failed, escalating to human review: {exc}"


def _pass_note(lang: str, round_number: int, output: Step5Output) -> str:
    if lang == "zh":
        return f"第五步第{round_number}轮质询完成：对「{output.interrogated_candidate_name}」的总体判定为{output.overall_verdict.value}。"
    return f'Step 5 round {round_number} interrogation complete: overall verdict on "{output.interrogated_candidate_name}" is {output.overall_verdict.value}.'


def run_step5(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    round_number: int = 1,
    reasoning_effort: Optional[str] = None,
) -> Step5Result:
    """Run a single round of interrogation and return a unified Step5Result; the result is persisted to
    runs/<run_id>/step5.json (overwriting the previous round).

    This is a **single** round of interrogation — it does not judge whether to send things back to
    step 4 to regenerate, and does not call run_step4 itself. Loop orchestration lives in
    atba/abductive_loop.py, which reads this function's returned overall_verdict field to decide the
    next action. round_number is only used for persisting "which round of interrogation this is" and
    doesn't affect this function's behavior — even at round_number=3, this function still only does one
    thing: "interrogate whatever candidate is currently in step4.json."
    """
    card, step3, step4 = _load_inputs(run_id)
    candidate = _selected_candidate(step4)
    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step5Result:
        result = Step5Result(run_id=run_id, provider=provider, model=resolved_model, round_number=round_number, **kwargs)
        save_stage_output(run_id, "step5", result)
        return result

    agent = _build_agent(provider, model, lang)
    task_text = _task_text(card, step3, candidate)
    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )
    try:
        run_result = agent.run_sync(task_text, model_settings=model_settings)
    except Exception as exc:
        return _finish(status=Step5Status.BLOCKED_AGENT_ERROR, note=_agent_error_note(lang, exc))

    output = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    note = _pass_note(lang, round_number, output)
    return _finish(
        status=Step5Status.OK, note=note, audit_trail=audit_trail, usage=extract_usage(run_result), **_derive_result_kwargs(output)
    )


async def stream_step5(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    round_number: int = 1,
    reasoning_effort: Optional[str] = None,
):
    """The streaming version of run_step5, with event types identical to the other steps', forwarded
    event-by-event by atba/abductive_loop.py when it orchestrates the loop."""
    try:
        card, step3, step4 = _load_inputs(run_id)
        candidate = _selected_candidate(step4)
    except (FileNotFoundError, ValueError) as exc:
        note = f"第五步无法启动：{exc}" if lang == "zh" else f"Step 5 could not start: {exc}"
        final = Step5Result(run_id=run_id, status=Step5Status.BLOCKED_AGENT_ERROR, round_number=round_number, note=note)
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step5Result:
        result = Step5Result(run_id=run_id, provider=provider, model=resolved_model, round_number=round_number, **kwargs)
        save_stage_output(run_id, "step5", result)
        return result

    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )
    task_text = _task_text(card, step3, candidate)

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
        final = _finish(status=Step5Status.BLOCKED_AGENT_ERROR, note=_agent_error_note(lang, exc))
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    assert run_result is not None, "run_stream_events finished normally without an AgentRunResultEvent — an abnormal state"
    output = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    note = _pass_note(lang, round_number, output)
    final = _finish(
        status=Step5Status.OK, note=note, audit_trail=audit_trail, usage=extract_usage(run_result), **_derive_result_kwargs(output)
    )
    yield {"type": "final", "result": final.model_dump(mode="json")}
