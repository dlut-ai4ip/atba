"""Step 3: Literature Retrieval & Research Question — the runnable implementation.

Corresponds to the technical appendix's "Step 3" section and appendix B's retrieval protocol —
**currently the single most validity-critical link in the whole system**: the research question must
be grounded in literature actually retrieved; the model is never allowed to judge, from impression or
training knowledge alone, that some theoretical direction "hasn't been studied yet" or "has a
theoretical gap."

**This round absorbed the original step 4's sub-step 0 (deep retrieval on the anchor theoretical
direction)**: per a methodology discussion — "abduction is about finding what an existing theory
hasn't done; this step should retrieve that same theory but from a different angle" — everything about
"the relationship to the anchor theory itself" now belongs fully to step 3: the earlier "broad and
shallow" scan across candidate directions is unchanged, but once a direction is locked in and a
research_question is about to be produced, the **same agent run** immediately shifts into "narrow and
deep," working out that direction's boundary conditions/internal tensions
(`anchor_theory_grounding`, see atba/schemas.py's TheoreticalGroundingRecord). This frees up step 4's
retrieval budget entirely for "finding a mechanism outside the anchor theory" (see atba/step4.py),
instead of digging into the anchor theory a second time.

**Relationship to retrieval (answering "what is retrieval_agent's relationship to step3")**: step 3's
agent puts the `search_scopus` tool exposed by `atba/mcp_server.py` **directly** into its own
`toolsets`, and splices the retrieval-strategy knowledge (`atba/prompts/retrieval_skill.md`) into its
own system prompt — retrieval happens inside step 3's **own single** `agent.run()`; the agent can call
`search_scopus` multiple times within that one run (once per candidate direction, per degrading tier,
per rewrite retry), rather than outsourcing retrieval to a separate "retrieval agent" and judging after
the fact. This follows the architectural rule "each step is one independent agent run" — an earlier
version built a standalone `retrieval_agent.py` that wrapped retrieval as an independent agent other
steps could "call," and that design has been abandoned (see the docstring at the top of
atba/mcp_server.py); now "retrieval capability" is just two reusable parts — an MCP tool and a skill —
that whichever agent needs them (step 3 today, step 4's internal novelty check in the future) assembles
directly into its own agent, with no middleman.

**Input source**: step 3 has no independent input, accepting only a `run_id` — it reads that run's
persisted step-1 phenomenon card (`deconstruction` in `step1.json`) and the candidate theoretical
directions the user confirmed in step 2 (`selected_theory_directions` in `step2.json`, which must be
non-empty, otherwise it means the user hasn't made a selection in step 2 yet, and the function errors
out telling the caller to go select first).

**Two entry points, one shared status-determination path**: `run_step3` (sync) is for the CLI/
non-streaming API endpoint; `stream_step3` (async generator) is for `/api/step3/stream` to forward
thinking-process and tool-call increments — the architecture mirrors atba/step1.py's
run_step1/stream_step1 split, reusing atba/agent_streaming.py's streaming-event classification logic
(`classify_stream_event` itself is agnostic to "which tool" — any ToolCallPart's increments get
forwarded, so search_scopus's call-argument increments and the final report_step3_output's increments
both show up in the same event stream; the frontend currently doesn't distinguish between them, just
scrolling them as-is).
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
from .prompts import step3_system_prompt
from .schemas import (
    CandidateTheoryDirection,
    GapType,
    HitLevel,
    PhenomenonDeconstruction,
    ResearchApproach,
    Step1Result,
    Step2Result,
    Step3Output,
    Step3Result,
    Step3Status,
)

DEFAULT_PROVIDER = os.environ.get("ATBA_LLM_PROVIDER") or "anthropic"

# Must match the "name" field in atba/schemas/step3.schema.json and the "call the tool
# report_step3_output" instruction in the prompt file, for the same reason as step1.py's
# STEP1_TOOL_NAME comment.
STEP3_TOOL_NAME = "report_step3_output"


def _build_agent(provider: str, model_name: Optional[str], lang: str) -> Agent[None, Step3Output]:
    model = build_model(provider, model_name)
    agent = Agent(
        model=model,
        toolsets=[build_retrieval_toolset()],
        output_type=ToolOutput(
            Step3Output,
            name=STEP3_TOOL_NAME,
            description=(
                "Report step 3's final result: every candidate theoretical direction examined "
                "(including ones skipped for not constituting a puzzle), the research approach "
                "(gap_spotting/problematization), its specific type, the research question itself, a "
                "coverage report, the rationale, any cross-source tension note, and the state of deep "
                "retrieval on the anchor direction (anchor_theory_grounding)."
            ),
        ),
        system_prompt=step3_system_prompt(lang=lang),
        # A single task may need three-tier degrading retrieval x rewrite-retry separately for
        # multiple candidate directions, and once a direction is locked in, one more round of narrow,
        # deep anchor-theory grounding retrieval (the sub-step moved over from step 4 this round, see
        # schemas.py's TheoreticalGroundingRecord) — more tool calls than before, so the retry budget
        # is raised accordingly.
        retries=10,
        name="atba_step3",
    )
    # This used to read "return Agent(...)" followed by an unreachable
    # "return _attach_conditional_field_validator(agent)" line — the second return was dead code that
    # could never execute, and the agent variable was never actually reassigned, so the
    # output_validator was never really attached. This turned out to be the root cause of an earlier
    # bug where anchor_theory_direction/mechanism_gap_characterization always came back None (not the
    # agent disobeying — the validator simply never took effect).
    return _attach_conditional_field_validator(agent, lang)


def _attach_conditional_field_validator(agent: Agent[None, Step3Output], lang: str) -> Agent[None, Step3Output]:
    """anchor_theory_direction/mechanism_gap_characterization are both Optional fields in the schema
    (required only under specific conditions, so they can't be marked required outright), but testing
    found that relying on the prompt text alone to say "required in this case" isn't reliable enough —
    the first version, run against real data, produced a research_question while leaving both
    conditionally required fields empty. Optional fields aren't enforced by pydantic-ai's JSON schema,
    so an extra output_validator has to be attached: whenever "should have been filled in but wasn't" is
    detected, raise ModelRetry to force it to fill the gap within the same run — a plain-language
    reminder in the prompt isn't enough on its own."""

    def _retry(zh: str, en: str) -> str:
        return zh if lang == "zh" else en

    @agent.output_validator
    def _check_conditional_fields(data: Step3Output) -> Step3Output:
        if data.research_question and data.research_approach is None:
            raise ModelRetry(
                _retry(
                    "你产出了research_question，但没有填写research_approach——请先确定这个研究问题走"
                    "的是gap_spotting还是problematization这条路径（第一层）。",
                    "You produced a research_question but left research_approach empty — first decide "
                    "whether this research question follows the gap_spotting or the problematization "
                    "path (tier 1).",
                )
            )
        if data.research_approach == ResearchApproach.GAP_SPOTTING and data.gap_type is None:
            raise ModelRetry(
                _retry(
                    "research_approach是gap_spotting，但没有填写gap_type——请指定theory_void（理论"
                    "空白型）还是mechanism_gap（机制问题型）（第二层）。",
                    "research_approach is gap_spotting but gap_type is empty — specify whether this is "
                    "theory_void or mechanism_gap (tier 2).",
                )
            )
        if data.research_approach == ResearchApproach.PROBLEMATIZATION and data.problematization_detail is None:
            raise ModelRetry(
                _retry(
                    "research_approach是problematization，但没有填写problematization_detail——"
                    "这种情况下该字段必填（识别的假设/支撑证据/为什么值得挑战/替代假设/Davis三分法自检）。",
                    "research_approach is problematization but problematization_detail is empty — this "
                    "field is required in that case (the identified assumption / supporting evidence / "
                    "why it's worth challenging / the alternative assumption / the Davis three-way "
                    "self-check).",
                )
            )
        if data.research_question and not data.anchor_theory_direction:
            raise ModelRetry(
                _retry(
                    "你产出了research_question，但没有填写anchor_theory_direction——请回填这个研究"
                    "问题实际锚定的候选理论方向名称，必须与examined_directions里某一条的theory_name"
                    "逐字一致。",
                    "You produced a research_question but left anchor_theory_direction empty — fill in "
                    "the candidate theoretical direction this research question actually anchors on; it "
                    "must match one entry's theory_name in examined_directions verbatim.",
                )
            )
        if data.gap_type == GapType.MECHANISM_GAP and data.mechanism_gap_characterization is None:
            raise ModelRetry(
                _retry(
                    "gap_type是mechanism_gap，但没有填写mechanism_gap_characterization（第三层）——"
                    "这不是schema层面的校验故障，这个字段本身允许为空，但业务规则要求gap_type="
                    "mechanism_gap时必须显式给出取值，省略字段或再次传null都不会通过，必须二选一填入"
                    "uncharted（现有理论确实没研究过）或anomalous_reversal（现有理论核心逻辑照直套用"
                    "会预测反方向结果），并在rationale里给出对应的具体推演。",
                    "gap_type is mechanism_gap but mechanism_gap_characterization is empty (tier 3) — "
                    "this isn't a schema-level check failure, the field itself is allowed to be empty, "
                    "but the business rule requires an explicit value whenever gap_type is "
                    "mechanism_gap; omitting it or passing null again will not pass. You must choose "
                    "either uncharted (existing theory genuinely hasn't studied this) or "
                    "anomalous_reversal (applying existing theory's core logic straightforwardly would "
                    "predict the opposite result), and lay out the corresponding reasoning in rationale.",
                )
            )
        if data.research_question and data.anchor_theory_grounding is None:
            raise ModelRetry(
                _retry(
                    "你产出了research_question，但没有填写anchor_theory_grounding——本轮改动把针对"
                    "锚定理论方向的深度检索从第四步挪到了这里：确认某个方向构成缺口、准备产出"
                    "research_question之前，还要针对**这一个**方向（不是其余被扫过又跳过的方向）做一次"
                    "专门的深度检索，摸清它的边界条件与内部张力，供第四步生成候选时作为背景依据。请调用"
                    "search_scopus/get_paper_abstract针对anchor_theory_direction补做这次检索，"
                    "再填写anchor_theory_grounding的全部字段。",
                    "You produced a research_question but left anchor_theory_grounding empty — this "
                    "round moved deep retrieval on the anchor theoretical direction from step 4 to here: "
                    "before confirming a direction constitutes a gap and producing a research_question, "
                    "you must also run one dedicated deep retrieval on **this one** direction (not the "
                    "other directions that were scanned and skipped) to work out its boundary conditions "
                    "and internal tensions, as background for step 4's candidate generation. Call "
                    "search_scopus/get_paper_abstract to run that retrieval against "
                    "anchor_theory_direction, then fill in every field of anchor_theory_grounding.",
                )
            )
        if data.anchor_theory_grounding and data.anchor_theory_grounding.anchor_theory != data.anchor_theory_direction:
            raise ModelRetry(
                _retry(
                    f"anchor_theory_grounding.anchor_theory={data.anchor_theory_grounding.anchor_theory!r}"
                    f"跟anchor_theory_direction={data.anchor_theory_direction!r}不一致——两者必须逐字"
                    "相同，深度检索锚定的必须是同一个方向，不能对不上。",
                    f"anchor_theory_grounding.anchor_theory={data.anchor_theory_grounding.anchor_theory!r} "
                    f"does not match anchor_theory_direction={data.anchor_theory_direction!r} — the two "
                    "must be verbatim identical; the deep retrieval must anchor on the same direction.",
                )
            )
        return data

    return agent


def _load_inputs(run_id: str) -> tuple[PhenomenonDeconstruction, list[CandidateTheoryDirection]]:
    """Step 3's only input source: the phenomenon card step 1 persisted + the candidate directions the
    user confirmed in step 2."""
    step1 = load_stage_output(run_id, "step1", Step1Result)
    if step1.deconstruction is None:
        raise ValueError(
            f"run {run_id} does not yet have a usable phenomenon card (step 1 status={step1.status.value}, "
            "deconstruction is empty): step 3 requires step 1 to have passed (status=passed) first."
        )
    step2 = load_stage_output(run_id, "step2", Step2Result)
    if not step2.is_ok():
        raise ValueError(f"run {run_id}'s step 2 has not passed (status={step2.status.value}); cannot run step 3.")
    if not step2.selected_theory_directions:
        raise ValueError(
            f"run {run_id}'s step 2 has no confirmed candidate theoretical directions yet "
            "(selected_theory_directions is empty): please check at least one direction on the step-2 "
            "page and click 'confirm selection' before running step 3."
        )
    return step1.deconstruction, step2.selected_theory_directions


def _task_text(card: PhenomenonDeconstruction, directions: list[CandidateTheoryDirection]) -> str:
    lines = [
        "## Phenomenon card",
        f"actor: {card.actor}",
        f"observed_behavior: {card.observed_behavior}",
        f"field_constraints: {card.field_constraints}",
        f"apparent_motive: {card.apparent_motive or '(none — the phenomenon has no attributable actor)'}",
        f"observable_outcome: {card.observable_outcome}",
        "",
        "## Candidate theoretical directions (examine in this order)",
    ]
    for i, d in enumerate(directions, 1):
        lines.append(f"{i}. {d.theory_name} — {d.relevance_rationale}")
    return "\n".join(lines)


_INFRA_FAILURE_LEVELS = {HitLevel.RETRIEVAL_UNAVAILABLE, HitLevel.NOT_EXAMINED}


def _derive_result_kwargs(output: Step3Output, lang: str) -> dict:
    """run_step3 (sync) and stream_step3 (streaming) share this result-assembly logic, to keep the two
    paths' status determination from gradually drifting apart — same intent as the
    _derive_result_kwargs in step1.py/step2.py.

    **The distinction between RETRIEVAL_UNAVAILABLE and NO_GAP_FOUND is written here in code, not
    inferred by parsing natural-language rationale**: as soon as any direction's hit_level falls into
    the "infrastructure failure" set, it means search_scopus never worked properly in this task at
    all, and an empty research_question must not be read as "the phenomenon is already explained by
    existing theory" — those are two different things, see Step3Status.RETRIEVAL_UNAVAILABLE's
    docstring.
    """
    shared = dict(
        examined_directions=output.examined_directions,
        research_approach=output.research_approach,
        gap_type=output.gap_type,
        research_question=output.research_question,
        anchor_theory_direction=output.anchor_theory_direction,
        problematization_detail=output.problematization_detail,
        mechanism_gap_characterization=output.mechanism_gap_characterization,
        coverage_report=output.coverage_report,
        rationale=output.rationale,
        cross_source_tension_note=output.cross_source_tension_note,
        anchor_theory_grounding=output.anchor_theory_grounding,
    )
    if output.research_question is None:
        infra_failed = any(d.hit_level in _INFRA_FAILURE_LEVELS for d in output.examined_directions)
        if infra_failed:
            note = (
                "第三步：检索基础设施不可用（search_scopus工具调用失败，常见原因是缺"
                "SCOPUS_API_KEY），未能真正完成任何候选方向的检索判断——这不构成'现象已被现有理论"
                "解释'的结论，请检查检索环境配置（见atba/.env.example）后重新运行本步。"
                if lang == "zh"
                else "Step 3: retrieval infrastructure unavailable (the search_scopus tool call "
                "failed — commonly a missing SCOPUS_API_KEY), so no candidate direction's retrieval "
                "judgment actually completed — this does not amount to a conclusion that 'the "
                "phenomenon is already explained by existing theory.' Check the retrieval "
                "configuration (see atba/.env.example) and rerun this step."
            )
            return dict(status=Step3Status.RETRIEVAL_UNAVAILABLE, note=note, **shared)
        note = (
            f"第三步：检验了{len(output.examined_directions)}个候选方向，均判定'不构成谜题'——"
            "现象目前看来能被现有理论解释，转人工判断是否需要补充理论方向或搁置该现象。"
            if lang == "zh"
            else f"Step 3: examined {len(output.examined_directions)} candidate direction(s), all judged "
            "to not constitute a puzzle — the phenomenon currently appears explainable by existing "
            "theory. Escalating to human judgment on whether to add more theoretical directions or set "
            "this phenomenon aside."
        )
        return dict(status=Step3Status.NO_GAP_FOUND, note=note, **shared)

    if lang == "zh":
        if output.research_approach == ResearchApproach.PROBLEMATIZATION:
            rq_type_label = "问题化型（problematization）"
        elif output.gap_type is not None:
            rq_type_label = {
                GapType.THEORY_VOID: "理论空白型（gap-spotting）",
                GapType.MECHANISM_GAP: "机制问题型（gap-spotting）",
            }.get(output.gap_type, "未知类型")
        else:
            rq_type_label = "未知类型"
        anomaly_suffix = (
            "——且判定为anomalous_reversal（现有理论核心逻辑照直套用会预测反方向，不只是未覆盖，"
            "第四步需要修订理论而非单纯填补空白）"
            if output.mechanism_gap_characterization
            and output.mechanism_gap_characterization.value == "anomalous_reversal"
            else ""
        )
        note = (
            f"第三步通过：检验了{len(output.examined_directions)}个候选方向，产出"
            f"{rq_type_label}研究问题{anomaly_suffix}（完整检索轨迹见 audit_trail）。"
        )
    else:
        if output.research_approach == ResearchApproach.PROBLEMATIZATION:
            rq_type_label = "problematization"
        elif output.gap_type is not None:
            rq_type_label = {
                GapType.THEORY_VOID: "theory-void (gap-spotting)",
                GapType.MECHANISM_GAP: "mechanism-gap (gap-spotting)",
            }.get(output.gap_type, "unknown type")
        else:
            rq_type_label = "unknown type"
        anomaly_suffix = (
            " — characterized as an anomalous reversal (applying existing theory's core logic "
            "straightforwardly would predict the opposite direction, not merely leave it uncovered; "
            "step 4 needs to revise the theory rather than simply fill a gap)"
            if output.mechanism_gap_characterization
            and output.mechanism_gap_characterization.value == "anomalous_reversal"
            else ""
        )
        note = (
            f"Step 3 passed: examined {len(output.examined_directions)} candidate direction(s), produced "
            f"a {rq_type_label} research question{anomaly_suffix} (see audit_trail for the full "
            "retrieval trail)."
        )
    return dict(status=Step3Status.OK, note=note, **shared)


def _agent_error_note(lang: str, exc: Exception) -> str:
    return f"第三步agent调用异常，转人工检查：{exc}" if lang == "zh" else f"Step 3 agent call failed, escalating to human review: {exc}"


def run_step3(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    reasoning_effort: Optional[str] = None,
) -> Step3Result:
    """Run step 3 end to end and return a unified Step3Result; the result is persisted to
    runs/<run_id>/step3.json.

    Args:
        run_id: must be a run that has completed step 2 with selected_theory_directions non-empty.
        provider/model/lang: same convention as the other steps.
        reasoning_effort: DeepSeek's thinking-effort tier, only takes effect when provider=="deepseek",
            see atba/agent_streaming.py's deepseek_reasoning_model_settings.
    """
    card, directions = _load_inputs(run_id)
    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step3Result:
        result = Step3Result(run_id=run_id, provider=provider, model=resolved_model, **kwargs)
        save_stage_output(run_id, "step3", result)
        return result

    agent = _build_agent(provider, model, lang)
    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )
    try:
        run_result = agent.run_sync(_task_text(card, directions), model_settings=model_settings)
    except Exception as exc:  # the model call itself failed, or the retrieval tool errored repeatedly until the retry budget ran out
        return _finish(status=Step3Status.BLOCKED_AGENT_ERROR, note=_agent_error_note(lang, exc))

    output = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    return _finish(
        audit_trail=audit_trail, usage=extract_usage(run_result), **_derive_result_kwargs(output, lang)
    )


async def stream_step3(
    run_id: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    lang: str = "en",
    reasoning_effort: Optional[str] = None,
):
    """The streaming version of run_step3, with event types identical to atba/step1.py's stream_step1
    (thinking_delta/tool_call_delta/final), forwarded by `/api/step3/stream`.

    Shares one trait with stream_step2: failing to obtain the input (run_id doesn't exist, step 2
    hasn't passed, or no candidate direction has been confirmed) means the run fundamentally can't
    start — caught up front here, without persisting anything, directly yielding a
    BLOCKED_AGENT_ERROR final event.
    """
    try:
        card, directions = _load_inputs(run_id)
    except (FileNotFoundError, ValueError) as exc:
        note = f"第三步无法启动：{exc}" if lang == "zh" else f"Step 3 could not start: {exc}"
        final = Step3Result(run_id=run_id, status=Step3Status.BLOCKED_AGENT_ERROR, note=note)
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    resolved_model = model or DEFAULT_MODELS.get(provider, "")

    def _finish(**kwargs) -> Step3Result:
        result = Step3Result(run_id=run_id, provider=provider, model=resolved_model, **kwargs)
        save_stage_output(run_id, "step3", result)
        return result

    model_settings = (
        anthropic_thinking_model_settings(provider)
        or deepseek_reasoning_model_settings(provider, reasoning_effort)
        or openai_reasoning_model_settings(provider, reasoning_effort)
    )

    try:
        agent = _build_agent(provider, model, lang)
        run_result = None
        async with agent.run_stream_events(_task_text(card, directions), model_settings=model_settings) as events:
            async for event in events:
                ndjson_event, result = classify_stream_event(event)
                if ndjson_event is not None:
                    yield ndjson_event
                if result is not None:
                    run_result = result
    except Exception as exc:
        final = _finish(status=Step3Status.BLOCKED_AGENT_ERROR, note=_agent_error_note(lang, exc))
        yield {"type": "final", "result": final.model_dump(mode="json")}
        return

    assert run_result is not None, "run_stream_events finished normally without an AgentRunResultEvent — an abnormal state"
    output = run_result.output
    audit_trail = json.loads(run_result.all_messages_json())
    final = _finish(
        audit_trail=audit_trail, usage=extract_usage(run_result), **_derive_result_kwargs(output, lang)
    )
    yield {"type": "final", "result": final.model_dump(mode="json")}
