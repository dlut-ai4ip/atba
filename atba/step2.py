"""Step 2: Theory Matching — the runnable implementation.

Corresponds to the technical appendix's "Step 2" section: based on the phenomenon card step 1
produced, matches a few plausibly relevant theoretical directions, without yet judging any gap and
without requiring traceable literature — that's step 3's job; this step only scopes step 3's retrieval.

Much simpler than step 1: a single judgment, with no verification loop needing in-run retries like the
theory-jargon check, and no "not enough information, escalate" branch — the phenomenon card has already
passed step 1's checks, so step 2 just does one associative match of theoretical directions against it;
in principle it always produces a result (the only failure mode is the model call itself breaking).

**Step 2 has no independent raw input**: its only input source is a step 1 run that has already
finished and passed (status=passed) — specifically `phenomenon_deconstruction` in
`runs/<run_id>/step1.json` — so run_step2/stream_step2 only accept a run_id, not a text argument; the
caller must first guide the user through step 1. It deliberately does not read step 1's
prior_expectation/causal_check: the former is step 1's own basis for judging "is there enough
information," the latter is a causal explanation kept for step 4's candidate generation to reference —
neither is something this step, "match theoretical directions from the phenomenon card," should be
looking at; keeping them out avoids this step being swayed by information outside the card and
narrowing its judgment prematurely.

Two entry points, one shared status-determination path: `run_step2` (sync) is for the CLI/non-streaming
backend endpoint; `stream_step2` (async generator) is for `/api/step2/stream` to forward thinking-process
increments — the architecture fully mirrors atba/step1.py's run_step1/stream_step1 split, sharing
`_derive_result_kwargs` to determine status, reusing atba/agent_streaming.py's streaming-event
classification logic.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from pydantic_ai import Agent, ToolOutput

from .agent_streaming import (
    anthropic_thinking_model_settings,
    classify_stream_event,
    deepseek_reasoning_model_settings,
    extract_usage,
    openai_reasoning_model_settings,
)
from .context_store import load_stage_output, save_stage_output
from .llm import DEFAULT_MODELS, build_model
from .prompts import step2_system_prompt
from .schemas import (
    CandidateTheoryDirection,
    PhenomenonDeconstruction,
    Step1Result,
    Step2Output,
    Step2Result,
    Step2Status,
)

DEFAULT_PROVIDER = os.environ.get("ATBA_LLM_PROVIDER") or "anthropic"

# Must match the "name" field in atba/schemas/step2.schema.json and the "call the tool
# report_step2_output" instruction in the prompt file — see step1.py's comment on STEP1_TOOL_NAME for
# the same pitfall.
STEP2_TOOL_NAME = "report_step2_output"


def _build_agent(provider: str, model_name: Optional[str], lang: str) -> Agent[None, Step2Output]:
    model = build_model(provider, model_name)
    return Agent(
        model=model,
        output_type=ToolOutput(
            Step2Output,
            name=STEP2_TOOL_NAME,
            description="Report the list of candidate theoretical directions matched in step 2, used to scope step 3's retrieval.",
        ),
        system_prompt=step2_system_prompt(lang=lang),
        retries=2,
        name="atba_step2",
    )


def _load_phenomenon_card(run_id: str) -> PhenomenonDeconstruction:
    """Step 2's only input source: the phenomenon card step 1 persisted. load_stage_output raises
    FileNotFoundError if run_id doesn't exist; raises ValueError if run_id exists but step 1 hasn't
    passed yet (no deconstruction) — the caller (atba/api.py) turns these into 404/400 respectively."""
    step1 = load_stage_output(run_id, "step1", Step1Result)
    if step1.deconstruction is None:
        raise ValueError(
            f"run {run_id} does not yet have a usable phenomenon card (step 1 status={step1.status.value}, "
            "deconstruction is empty): step 2 requires step 1 to have passed (status=passed) first."
        )
    return step1.deconstruction


def _phenomenon_card_text(card: PhenomenonDeconstruction) -> str:
    lines = [
        f"actor: {card.actor}",
        f"observed_behavior: {card.observed_behavior}",
        f"field_constraints: {card.field_constraints}",
        f"apparent_motive: {card.apparent_motive or '(none — the phenomenon has no attributable actor)'}",
        f"observable_outcome: {card.observable_outcome}",
    ]
    return "\n".join(lines)


def save_step2_selection(run_id: str, selected: list[CandidateTheoryDirection]) -> Step2Result:
    """After the user checks which candidate theoretical directions from step 2's result should go into
    step 3's retrieval, write that selection back to runs/<run_id>/step2.json — not a fresh agent run
    (no new model judgment, purely persisting a manual filtering result), so step 3 (and refreshing/
    revisiting this page) can read what the user selected without depending on in-memory checkbox state
    in the frontend. No strong validation such as "must be a subset of candidate_theory_directions" is
    applied to the selection — what's written is the full CandidateTheoryDirection objects (the frontend
    already has them, not indices), so even if the candidate list changes later, what's stored here is
    still exactly what the user saw and selected at the time, unaffected by any reordering."""
    result = load_stage_output(run_id, "step2", Step2Result)
    if not result.is_ok():
        raise ValueError(f"run {run_id}'s step 2 has not passed (status={result.status.value}); cannot select candidate theoretical directions.")
    result.selected_theory_directions = selected
    save_stage_output(run_id, "step2", result)
    return result


def _derive_result_kwargs(output: Step2Output, lang: str) -> dict:
    """run_step2 (sync) and stream_step2 (streaming) share this result-assembly logic, to keep the
    note text/field population from gradually drifting into two inconsistent versions across the two
    paths — same intent as _derive_result_kwargs in step1.py."""
    n = len(output.candidate_theory_directions)
    note = (
        f"第二步通过：匹配到{n}个候选理论方向，供第三步逐一检索验证（完整过程见 audit_trail）。"
        if lang == "zh"
        else f"Step 2 passed: matched {n} candidate theoretical direction(s) for step 3 to retrieve and verify one by one (see audit_trail for the full process)."
    )
    return dict(
        status=Step2Status.OK,
        candidate_theory_directions=output.candidate_theory_directions,
        note=note,
    )


def _agent_error_note(lang: str, exc: Exception) -> str:
    return f"第二步agent调用异常，转人工检查：{exc}" if lang == "zh" else f"Step 2 agent call failed, escalating to human review: {exc}"


def run_step2(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    reasoning_effort: Optional[str] = None,
) -> Step2Result:
    """Run step 2 end to end and return a unified Step2Result; the result is persisted to
    runs/<run_id>/step2.json.

    Args:
        run_id: must be a run that has completed step 1 (status=passed) — step 2 has no independent
            phenomenon-text input.
        provider: "anthropic" or "deepseek"; the default can also be overridden via the
            ATBA_LLM_PROVIDER environment variable.
        model: overrides the given provider's default model name.
        lang: system-prompt language, "zh" or "en".
        reasoning_effort: DeepSeek's thinking-effort tier, only takes effect when provider=="deepseek",
            see atba/agent_streaming.py's deepseek_reasoning_model_settings.
    """
    card = _load_phenomenon_card(run_id)
    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step2Result:
        result = Step2Result(run_id=run_id, provider=provider, model=resolved_model, **kwargs)
        save_stage_output(run_id, "step2", result)
        return result

    agent = _build_agent(provider, model, lang)
    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )
    try:
        run_result = agent.run_sync(_phenomenon_card_text(card), model_settings=model_settings)
    except Exception as exc:  # the model call itself failed (auth/network/rate limit/etc.)
        return _finish(status=Step2Status.BLOCKED_AGENT_ERROR, note=_agent_error_note(lang, exc))

    output = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    return _finish(
        audit_trail=audit_trail, usage=extract_usage(run_result), **_derive_result_kwargs(output, lang)
    )


async def stream_step2(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    reasoning_effort: Optional[str] = None,
):
    """The streaming version of run_step2, with event types identical to atba/step1.py's stream_step1
    (thinking_delta/tool_call_delta/final), forwarded by `/api/step2/stream`.

    One deliberate difference from stream_step1: step 2's input comes from _load_phenomenon_card;
    failing to obtain it (run_id doesn't exist, or step 1 hasn't passed) means the run fundamentally
    can't start, not that the model call failed — this is caught up front here, without persisting
    anything (there's no provider/model info yet, and no point persisting a half-formed result), and
    directly yields a BLOCKED_AGENT_ERROR final event and returns; once a streaming response has begun
    it's already 200 and can't be changed to a 4xx — unlike run_step2, where the same error is raised
    directly as FileNotFoundError/ValueError (turned into 404/400 by /api/step2).
    """
    try:
        card = _load_phenomenon_card(run_id)
    except (FileNotFoundError, ValueError) as exc:
        note = f"第二步无法启动：{exc}" if lang == "zh" else f"Step 2 could not start: {exc}"
        final = Step2Result(run_id=run_id, status=Step2Status.BLOCKED_AGENT_ERROR, note=note)
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step2Result:
        result = Step2Result(run_id=run_id, provider=provider, model=resolved_model, **kwargs)
        save_stage_output(run_id, "step2", result)
        return result

    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )

    try:
        agent = _build_agent(provider, model, lang)
        run_result = None
        async with agent.run_stream_events(_phenomenon_card_text(card), model_settings=model_settings) as events:
            async for event in events:
                ndjson_event, result = classify_stream_event(event)
                if ndjson_event is not None:
                    yield ndjson_event
                if result is not None:
                    run_result = result
    except Exception as exc:  # includes a missing-API-key RuntimeError, same reasoning as stream_step1's docstring
        final = _finish(status=Step2Status.BLOCKED_AGENT_ERROR, note=_agent_error_note(lang, exc))
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    assert run_result is not None, "run_stream_events finished normally without an AgentRunResultEvent — an abnormal state"
    output = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    final = _finish(
        audit_trail=audit_trail, usage=extract_usage(run_result), **_derive_result_kwargs(output, lang)
    )
    yield {"type": "final", "result": final.model_dump(mode="json")}
