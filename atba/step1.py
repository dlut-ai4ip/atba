"""Step 1: Phenomenon Input & Pre-check — the runnable implementation.

Corresponds to the technical appendix's "Step 1" section, implemented per the architectural rule
"each stage is one sub-agent, completed within a single agent loop":

- Prior-expectation identification (is there enough information to proceed) + causal-presupposition
  check (checks the raw input text) + theory-jargon check (checks the phenomenon-deconstruction field)
  + phenomenon deconstruction — four parallel fields merged into a **single** `run()` of one
  pydantic-ai Agent. When the theory-jargon check triggers, the agent regenerates automatically within
  the same `run()` via `output_validator` + `ModelRetry`, not via a separate outside call.
- The result is persisted to `runs/<run_id>/step1.json` (see `atba/context_store.py`), which becomes
  the input context the next stage (step 2's sub-agent) reads.

**"Pre-check" is not a boolean gate the caller must confirm by hand first**: an earlier version
required the caller to explicitly pass `prior_expectation_confirmed=True` before a model call would
even fire, escalating to human review otherwise — that design was flawed: it required the user to
already know "whether this needs confirming" instead of letting the system judge for itself whether it
has enough information. Now the agent judges for itself, from the input text (plus an optional
caller-supplied `prior_expectation_hint`), whether it has enough information; if so, it proceeds
without requiring any extra confirmation. Only when the information genuinely isn't enough — the agent
itself can't tell which theoretical direction to anchor on — does it return `NEEDS_CLARIFICATION`,
along with a concrete follow-up question and candidate options, for the frontend to render as an
interactive follow-up form; the user answers, resubmits with `prior_expectation_hint` and the same
`run_id` (not a brand-new phenomenon input).

Note that the "prior expectation" identified here is not the same validity guarantee step 2's "baseline
expectation" requires (which must be traceable to actual literature) — this version doesn't yet wire up
a retrieval service (D.4/D.8) at this step; this step only judges "is there enough information to move
on," not an actual literature check. Step 2's retrieval requirement is unaffected by whether this step
set "identified=true" — it still independently runs the full three-tier degrading retrieval.

**A causal-presupposition hit no longer blocks the pipeline**: an earlier version escalated to human
review on a hit and required the user to rewrite the input — that penalized the entirely normal case of
"the user already brought their own guess." Now a hit is simply recorded: the phenomenon deconstruction
itself still keeps only pure observational content (the prompt requires stripping any causal
explanation out of the five fields even on a hit), and the extracted causal explanation is stored
separately in `causal_check.extracted_explanation`, to be used in step 4's candidate generation as one
reference the user brought, not adopted as a conclusion.

**Two entry points, one shared status-determination path**: `run_step1` is the synchronous,
return-everything-at-once version (used by the CLI and the backend's `/api/step1`); `stream_step1` is
an async generator that yields the model's thinking process / structured-output increments as they
arrive, for `/api/step1/stream` to forward to the frontend for live display (both endpoints are visible
under the backend's `/docs`). Both share `_derive_result_kwargs` to determine `status`, so streaming and
non-streaming can never disagree about the same output — the only difference is whether
`agent.run_sync()` or `agent.run_stream_events()` drives the model call.

The classification/transformation of streaming events (extracting thinking_delta/tool_call_delta,
Anthropic extended-thinking model_settings) lives in `atba/agent_streaming.py`, reused by step 2 onward
so each step doesn't maintain its own copy that can drift.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from pydantic_ai import Agent, ModelRetry, ToolOutput
from pydantic_ai.exceptions import UnexpectedModelBehavior

from .agent_streaming import (
    anthropic_thinking_model_settings,
    classify_stream_event,
    deepseek_reasoning_model_settings,
    extract_usage,
    openai_reasoning_model_settings,
)
from .context_store import new_run_id, save_stage_output
from .llm import DEFAULT_MODELS, build_model
from .prompts import step1_jargon_retry_message, step1_system_prompt
from .schemas import Step1Output, Step1Result, Step1Status

DEFAULT_PROVIDER = os.environ.get("ATBA_LLM_PROVIDER") or "anthropic"
DEFAULT_MAX_JARGON_RETRIES = 2

# Must match the "name" field in atba/schemas/step1.schema.json and the "call the tool
# report_step1_output" instruction in each prompt file — otherwise the schema file is decorative and
# the tool name actually sent to the model falls back to pydantic-ai's default "final_result", out of
# sync with the docs (this really happened once and was only caught by looking at the frontend's audit
# trail).
STEP1_TOOL_NAME = "report_step1_output"


def _build_agent(
    provider: str, model_name: Optional[str], lang: str, max_jargon_retries: int
) -> Agent[None, Step1Output]:
    model = build_model(provider, model_name)
    agent: Agent[None, Step1Output] = Agent(
        model=model,
        output_type=ToolOutput(
            Step1Output,
            name=STEP1_TOOL_NAME,
            description=(
                "Report the structured result of step 1's four independent judgments in one shot: "
                "prior-expectation identification + causal-presupposition check + theory-jargon check + "
                "phenomenon deconstruction — four parallel fields, not nested within each other."
            ),
        ),
        system_prompt=step1_system_prompt(lang=lang),
        retries=max_jargon_retries,
        name="atba_step1",
    )

    @agent.output_validator
    def _reject_jargon(data: Step1Output) -> Step1Output:
        jargon = data.theory_jargon_check
        if jargon.hit:
            raise ModelRetry(
                step1_jargon_retry_message(lang=lang, terms=jargon.flagged_terms, reason=jargon.rationale)
            )
        return data

    return agent


def run_step1(
    raw_text: str,
    prior_expectation_hint: Optional[str] = None,
    max_jargon_retries: int = DEFAULT_MAX_JARGON_RETRIES,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    run_id: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> Step1Result:
    """Run step 1 end to end and return a unified Step1Result no matter where it got intercepted; the
    result is also persisted to runs/<run_id>/step1.json.

    Args:
        raw_text: the raw phenomenon description text.
        prior_expectation_hint: optional, a prior expectation/theoretical tradition the user already
            has in mind (e.g. a specific paper, a theory name) — not a precondition that must be
            confirmed first, just something that helps the agent judge and lowers the odds of a
            NEEDS_CLARIFICATION follow-up. Also reused (with the same run_id) when answering a
            NEEDS_CLARIFICATION follow-up question.
        max_jargon_retries: max retries within the same agent run when the theory-jargon check fails.
        provider: "anthropic" or "deepseek"; the default can also be overridden via the
            ATBA_LLM_PROVIDER environment variable.
        model: overrides the given provider's default model name.
        lang: system-prompt language, "zh" or "en".
        run_id: reuse an existing run (e.g. resubmitting after answering a NEEDS_CLARIFICATION
            follow-up, or rerunning with a different provider); a new one is created if omitted.
        reasoning_effort: only takes effect when provider=="deepseek" — DeepSeek's thinking-effort tier
            ("low"/"medium"/"high"/"xhigh"/"max", see atba/agent_streaming.py's
            deepseek_reasoning_model_settings); ignored when provider=="anthropic" (Anthropic's
            thinking effort is a separate, fixed token-budget mechanism).
    """
    run_id = run_id or new_run_id()
    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step1Result:
        result = Step1Result(
            run_id=run_id,
            raw_text=raw_text,
            prior_expectation_hint=prior_expectation_hint,
            provider=provider,
            model=resolved_model,
            **kwargs,
        )
        save_stage_output(run_id, "step1", result)
        return result

    agent = _build_agent(provider, model, lang, max_jargon_retries)
    user_content = raw_text
    if prior_expectation_hint:
        user_content += f"\n\n[User-supplied prior expectation / theoretical tradition hint]\n{prior_expectation_hint}"
    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )

    try:
        run_result = agent.run_sync(user_content, model_settings=model_settings)
    except UnexpectedModelBehavior as exc:
        return _finish(
            status=Step1Status.BLOCKED_JARGON_PERSISTENT,
            note=_jargon_persistent_note(lang, max_jargon_retries, exc),
        )
    except Exception as exc:  # the model call itself failed (auth/network/rate limit) — a different case from "check kept failing"
        return _finish(
            status=Step1Status.BLOCKED_AGENT_ERROR,
            note=_agent_error_note(lang, exc),
        )

    output = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    return _finish(
        audit_trail=audit_trail, usage=extract_usage(run_result), **_derive_result_kwargs(output, lang)
    )


def _jargon_persistent_note(lang: str, max_jargon_retries: int, exc: Exception) -> str:
    if lang == "zh":
        return (
            f"理论术语检测在同一次agent run内部连续重试（上限{max_jargon_retries}次）仍未通过："
            f"{exc}。转人工介入：可能是现象本身难以脱离理论语言描述，"
            "或现象描述本身已经预设了某个理论框架。"
        )
    return (
        f"The theory-jargon check still failed after repeated in-run retries (cap {max_jargon_retries}): "
        f"{exc}. Escalating to human review: the phenomenon may be inherently hard to describe without "
        "theoretical language, or the description may already presuppose a specific theoretical framework."
    )


def _agent_error_note(lang: str, exc: Exception) -> str:
    if lang == "zh":
        return f"第一步agent调用异常，转人工检查：{exc}"
    return f"Step 1 agent call failed, escalating to human review: {exc}"


def _derive_result_kwargs(output: Step1Output, lang: str) -> dict:
    """Turn the model's Step1Output into the kwargs needed to construct a Step1Result (status/note and
    the four check blocks).

    run_step1 (sync) and stream_step1 (streaming) share this status-determination logic — only the way
    the model call is driven differs (run_sync vs. run_stream_events). It's factored out so the two
    paths' judgment of "when does this count as NEEDS_CLARIFICATION/OK" can't gradually drift into two
    inconsistent versions.
    """
    causal_note = ""
    if output.causal_presupposition_check.hit:
        # A hit no longer blocks the pipeline: the phenomenon deconstruction itself still keeps only
        # pure observational content (the prompt requires stripping out purely observational content
        # even on a hit); the extracted causal explanation is attached separately to
        # causal_check.extracted_explanation, left for step 4's candidate generation to use as "one
        # guess the user already brought," not adopted directly as a conclusion.
        if lang == "zh":
            causal_note = (
                "因果预设检测器命中：输入文本已包含因果解释/机制说明。不阻断流程——"
                f"已提取用户提出的解释（「{output.causal_presupposition_check.extracted_explanation}」），"
                "现象解构本身仍只保留纯观察内容；这个解释会作为第四步候选生成时的一个参考候选，"
                "而非直接采纳的结论。"
            )
        else:
            causal_note = (
                "Causal-presupposition check triggered: the input text already contains a causal "
                f'explanation/mechanism account. This does not block the pipeline — the user\'s proposed '
                f'explanation has been extracted ("{output.causal_presupposition_check.extracted_explanation}"), '
                "and the phenomenon deconstruction itself still keeps only pure observational content; "
                "this explanation will be carried into step 4's candidate generation as one reference "
                "candidate, not adopted as a conclusion."
            )

    shared = dict(
        prior_expectation=output.prior_expectation_identification,
        causal_check=output.causal_presupposition_check,
        jargon_check=output.theory_jargon_check,
        deconstruction=output.phenomenon_deconstruction,
    )

    if not output.prior_expectation_identification.identified:
        if lang == "zh":
            note = (
                "信息不足以判断这个现象对应的先验预期/理论传统，需要用户补充信息后重新提交"
                "（带上同一个run_id + 回答填进prior_expectation_hint）。这不是效度层面的"
                "拒绝——因果预设检测与现象解构仍按prompt要求正常产出，供参考。"
                f"追问问题：{output.prior_expectation_identification.clarifying_question}"
            )
        else:
            note = (
                "There isn't enough information to determine the prior expectation/theoretical "
                "tradition this phenomenon maps to; please resubmit with more information (same "
                "run_id, with your answer in prior_expectation_hint). This is not a validity-level "
                "rejection — the causal-presupposition check and phenomenon deconstruction are still "
                "produced as usual, for reference. "
                f"Follow-up question: {output.prior_expectation_identification.clarifying_question}"
            )
        return dict(status=Step1Status.NEEDS_CLARIFICATION, note=f"{note} {causal_note}".strip(), **shared)

    note = (
        "第一步通过（先验预期已识别、理论术语检测最终通过；完整重试过程见 audit_trail）。"
        if lang == "zh"
        else "Step 1 passed (prior expectation identified, theory-jargon check ultimately passed; see audit_trail for the full retry history)."
    )
    return dict(status=Step1Status.OK, note=f"{note} {causal_note}".strip(), **shared)


async def stream_step1(
    raw_text: str,
    prior_expectation_hint: Optional[str] = None,
    max_jargon_retries: int = DEFAULT_MAX_JARGON_RETRIES,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    run_id: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
):
    """The streaming version of run_step1: an async generator that yields event dicts as it runs, for
    atba/api.py's SSE/NDJSON endpoint to forward directly to the frontend. Persistence and status
    determination are fully shared with run_step1 (see _derive_result_kwargs) — only the driving
    mechanism changes, from agent.run_sync() to agent.run_stream_events(), which additionally yields
    incremental events along the way.

    Event types produced:
      - {"type": "thinking_delta", "text": ...}
          Incremental model thinking content. On the Anthropic side this is produced because
          anthropic_thinking_model_settings() (see atba/agent_streaming.py) explicitly turns on
          extended thinking; on the DeepSeek side it isn't something this function configures — the
          current default model deepseek-v4-flash produces reasoning content on its own (confirmed by
          testing). Whether it appears depends on the specific provider/model, not a fixed
          "only Anthropic has this" rule.
      - {"type": "tool_call_delta", "text": ...}
          Incremental raw JSON text of the report_step1_output tool call's arguments; the frontend
          displays this growth as-is.
      - {"type": "final", "result": {...Step1Result.model_dump(mode="json")...}}
          Same shape as run_step1's return value, the sole authoritative result; the preceding
          incremental events are purely for progress display and don't affect this content or the
          persisted result.

    One deliberate difference from run_step1: in run_step1, a RuntimeError raised by build_model inside
    _build_agent (e.g. a missing API key) is not caught by the inner try/except and propagates straight
    out of the function, which atba/api.py's /api/step1 turns explicitly into a 502 (returned before any
    real work starts). But a streaming response's HTTP status code is already fixed at 200 before the
    first chunk is sent, so there's no way to change it to 502 from inside the generator afterward — so
    here RuntimeError is folded into the Exception branch below too, uniformly turned into a
    BLOCKED_AGENT_ERROR result sent normally through the stream, rather than aborting the connection
    with an error.
    """
    run_id = run_id or new_run_id()
    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step1Result:
        result = Step1Result(
            run_id=run_id,
            raw_text=raw_text,
            prior_expectation_hint=prior_expectation_hint,
            provider=provider,
            model=resolved_model,
            **kwargs,
        )
        save_stage_output(run_id, "step1", result)
        return result

    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )

    try:
        agent = _build_agent(provider, model, lang, max_jargon_retries)
        user_content = raw_text
        if prior_expectation_hint:
            user_content += f"\n\n[User-supplied prior expectation / theoretical tradition hint]\n{prior_expectation_hint}"

        run_result = None
        async with agent.run_stream_events(user_content, model_settings=model_settings) as events:
            async for event in events:
                ndjson_event, result = classify_stream_event(event)
                if ndjson_event is not None:
                    yield ndjson_event
                if result is not None:
                    run_result = result
    except UnexpectedModelBehavior as exc:
        final = _finish(
            status=Step1Status.BLOCKED_JARGON_PERSISTENT,
            note=_jargon_persistent_note(lang, max_jargon_retries, exc),
        )
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return
    except Exception as exc:  # includes a missing-API-key RuntimeError, see the docstring's note on the difference
        final = _finish(
            status=Step1Status.BLOCKED_AGENT_ERROR,
            note=_agent_error_note(lang, exc),
        )
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    assert run_result is not None, "run_stream_events finished normally without an AgentRunResultEvent — an abnormal state"
    output = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    final = _finish(
        audit_trail=audit_trail, usage=extract_usage(run_result), **_derive_result_kwargs(output, lang)
    )
    yield {"type": "final", "result": final.model_dump(mode="json")}
