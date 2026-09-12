"""The step-4/5 loop controller: orchestrates the automatic cycle "step 4 generates → step 5
interrogates → (if a core-mechanism flaw) send back to step 4 for revision → interrogate again," until
the candidate theory survives interrogation, or the max round count is reached without passing, at
which point it escalates to human review.

**Why this loop lives in its own file, not inside step4.py or step5.py**: this loop is not itself an
agent run — it's plain Python control flow, responsible for deciding "when should step4/step5 be called
again." Folding it into either step4.py or step5.py would make that file carry two different
responsibilities at once — "run one agent" and "decide whether to run again" — and would also leave the
CLI/API/tests with no clean entry point for "just run one round of interrogation, no automatic looping"
(see the top-of-file docstrings in step4.py/step5.py: "this file only handles a single round of X ...
loop orchestration lives in atba/abductive_loop.py").

**Why the decision to loop lives here rather than in step 4**: by design, step 5 is the "active party" —
it's step 5's interrogation result that decides whether to send things back; step 4 only passively
receives the revision instruction and regenerates (see the technical appendix's "if the interrogation
exposes a core-mechanism flaw in the candidate theory ... the process falls back to step 4 to
regenerate/revise the candidate"). This is also this project's concrete answer to "should steps 4 and 5
be merged into one agent": they are not merged into a single agent (doing so would let step 5 know how
the candidate was authored, destroying the point of the interrogation), but the orchestration work of
"looping" is consolidated in one place, so the user doesn't have to manually click back and forth
between two pages.

**Round numbering**: `round_number` is the same number line across step4.json and step5.json — round N
always refers simultaneously to "the candidate step 4 generated in round N" and "the interrogation step
5 ran on it in round N," never two separately-counted-from-1 numbers that risk not matching up in the
UI. One loop invocation (corresponding to the user clicking "run step 5" once) starts from whatever
round_number is **currently** persisted in step4.json (not forced back to 1 — if this is a retry, a few
revision rounds may already have happened before, and continuing the numbering better satisfies the
"complete audit trail" requirement than restarting from 1), running at most `max_rounds` more rounds of
interrogation (i.e. triggering at most `max_rounds - 1` revision round-trips).

**Max rounds**: 3. This is a compromise between "leaving enough room for one real core-mechanism
critique to produce a substantive improvement" and "avoiding endless retries down a direction that
fundamentally doesn't work, wasting real retrieval/LLM call quota" — not a value derived from any
theory; if testing finds 2 rounds is often not enough, or 4 rounds often still wastes calls, just adjust
this constant, no other code needs to change.
"""

from __future__ import annotations

from typing import AsyncIterator, Optional

from .context_store import save_stage_output
from .schemas import (
    InterrogationVerdict,
    Step4Status,
    Step5Result,
    Step5RoundSummary,
    Step5Status,
    TokenUsage,
)
from .step4 import run_step4, stream_step4
from .step5 import run_step5, stream_step5

MAX_LOOP_ROUNDS = 3


def _current_step4_state(run_id: str) -> tuple[int, Optional[TokenUsage]]:
    """Reads the currently persisted step4.json's round_number+usage, as the starting round for this
    loop invocation — step5.py's _load_inputs already validates that step4.json exists and
    status=passed, so this doesn't re-validate, and just lets the exception propagate as-is if it
    genuinely can't be found (run_step5/stream_step5's internal _load_inputs gives a clearer error
    message). **Also reads out usage along the way**: this round's candidate was already generated
    before this loop invocation began (it might be Step4RunPage's initial call, or the product of a
    previous loop invocation's revision round-trip), and its usage won't surface from anywhere else — if
    this loop invocation actually triggers a revision, this step4.json is about to be overwritten by the
    next round's save_stage_output, so this function is the only remaining chance to read out this usage
    before it's overwritten; once read, it's stuffed directly into this loop's starting
    pending_step4_usage (see run_step4_5_loop/stream_step4_5_loop), attributed to the first round of
    interrogation that "consumes this candidate."""
    from .context_store import load_stage_output
    from .schemas import Step4Result

    step4 = load_stage_output(run_id, "step4", Step4Result)
    return step4.round_number, step4.usage


def run_step4_5_loop(
    run_id: str,
    provider: str,
    model: Optional[str],
    lang: str,
    max_rounds: int = MAX_LOOP_ROUNDS,
    reasoning_effort: Optional[str] = None,
) -> Step5Result:
    """The synchronous version: starting from whatever step-4 candidate is currently persisted, runs
    interrogation → (if needed) revision round-trip → interrogation again, until it passes, the agent
    call fails, or max_rounds is reached and it's escalated to human review. The return value is the
    finally-persisted Step5Result (including the full loop_history).
    """
    start_round, pending_step4_usage = _current_step4_state(run_id)
    history: list[Step5RoundSummary] = []
    round_number = start_round
    rounds_run = 0

    while True:
        step5 = run_step5(
            run_id, provider=provider, model=model, lang=lang, round_number=round_number, reasoning_effort=reasoning_effort
        )
        if step5.status != Step5Status.OK:
            # The agent call itself failed (or input validation failed, e.g. step 4 never ran at all)
            # — this isn't "the interrogation didn't pass," this step simply never finished running;
            # returned directly as the terminal state, not counted toward rounds_run, no retry.
            return step5

        rounds_run += 1
        history.append(
            Step5RoundSummary(
                round_number=step5.round_number,
                interrogated_candidate_name=step5.interrogated_candidate_name,
                overall_verdict=step5.overall_verdict or InterrogationVerdict.FAILS,
                loop_back_instruction=step5.loop_back_instruction if step5.overall_verdict == InterrogationVerdict.FAILS else None,
                loop_back_target_field=step5.loop_back_target_field if step5.overall_verdict == InterrogationVerdict.FAILS else None,
                step5_usage=step5.usage,
                step4_usage=pending_step4_usage,
            )
        )
        pending_step4_usage = None

        if step5.overall_verdict != InterrogationVerdict.FAILS:
            # withstands or weak: passed, the pipeline proceeds normally.
            step5.loop_history = history
            save_stage_output(run_id, "step5", step5)
            return step5

        if rounds_run >= max_rounds:
            step5.status = Step5Status.BLOCKED_UNRESOLVED
            step5.note = (
                (
                    f"第五步：连续{rounds_run}轮质询（第{start_round}轮至第{round_number}轮）均判定核心"
                    f"机制存在缺陷，已达本次循环最大轮次（max_rounds={max_rounds}），转人工介入——不是"
                    f"agent调用失败，是候选理论在当前思路下反复未能通过对抗性质询。"
                )
                if lang == "zh"
                else (
                    f"Step 5: {rounds_run} consecutive round(s) of interrogation (round {start_round} "
                    f"through round {round_number}) all judged the core mechanism to be flawed, reaching "
                    f"this loop's max round count (max_rounds={max_rounds}); escalating to human review "
                    "— this is not an agent call failure, it's the candidate theory repeatedly failing "
                    "adversarial interrogation along its current line of thinking."
                )
            )
            step5.loop_history = history
            save_stage_output(run_id, "step5", step5)
            return step5

        # Rounds remain: send back to step 4 for revision, then move into the next round of interrogation.
        round_number += 1
        step4 = run_step4(
            run_id,
            provider=provider,
            model=model,
            lang=lang,
            round_number=round_number,
            revision_instruction=step5.loop_back_instruction,
            revision_target_candidate=step5.interrogated_candidate_name,
            revision_target_field=step5.loop_back_target_field,
            reasoning_effort=reasoning_effort,
        )
        if step4.status != Step4Status.OK:
            note = (
                f"第五步循环：第{round_number}轮修订时第四步agent调用异常，转人工检查：{step4.note}"
                if lang == "zh"
                else f"Step 5 loop: step 4's agent call failed during round {round_number}'s revision, "
                f"escalating to human review: {step4.note}"
            )
            failed = Step5Result(
                run_id=run_id,
                status=Step5Status.BLOCKED_AGENT_ERROR,
                round_number=round_number,
                note=note,
                loop_history=history,
            )
            save_stage_output(run_id, "step5", failed)
            return failed
        pending_step4_usage = step4.usage
        # The loop continues: the next while iteration will call run_step5 with the new round_number,
        # interrogating this freshly revised candidate, at which point the pending_step4_usage recorded
        # above will be stored together into that round's Step5RoundSummary.


async def stream_step4_5_loop(
    run_id: str,
    provider: str,
    model: Optional[str],
    lang: str,
    max_rounds: int = MAX_LOOP_ROUNDS,
    reasoning_effort: Optional[str] = None,
) -> AsyncIterator[dict]:
    """The streaming version of run_step4_5_loop — forwards each round's real thinking/tool_call events
    (from step 5, and from step 4 too whenever a revision round-trip fires) as-is, so the user can watch
    everything that happens in the loop, rather than staring at a spinner for a long time (a consistent
    requirement of this app: the thinking process must be shown in real chronological order, never
    hidden — see the top-of-file comment in TranscriptView.tsx).

    Two new event types beyond the existing ones (thinking_delta/tool_call_delta/tool_result/
    tool_result_retry):
    - `round_marker`: `{"type": "round_marker", "phase": "step4"|"step5", "round": N}` — emitted before
      starting to stream a given round's given phase's events, so the frontend knows "the upcoming
      thinking/tool_call events belong to which round's step 4 or step 5," and can bucket them into the
      right "turn" for display (the same live buffer should be flushed into one complete turn upon
      hitting the next round_marker, rather than concatenated indiscriminately).
    - `phase_final`: `{"type": "phase_final", "phase": ..., "round": N, "result": {...}}` — emitted when
      a given phase in a given round genuinely finishes, replacing the `type:"final"` that phase's own
      stream_stepN would normally emit (that type is reserved for firing exactly once when the **entire
      loop** ends — otherwise the frontend's generic streamPost() would see `type:"final"` and stop
      reading the whole request early, mistaking the first round for the end of the process).
    """
    start_round, pending_step4_usage = _current_step4_state(run_id)
    history: list[Step5RoundSummary] = []
    round_number = start_round
    rounds_run = 0

    while True:
        yield {"type": "round_marker", "phase": "step5", "round": round_number}
        step5 = None
        async for event in stream_step5(
            run_id, provider=provider, model=model, lang=lang, round_number=round_number, reasoning_effort=reasoning_effort
        ):
            if event["type"] == "final":
                step5_dict = event["result"]
                yield {"type": "phase_final", "phase": "step5", "round": round_number, "result": step5_dict}
            else:
                yield event

        step5 = Step5Result.model_validate(step5_dict)
        if step5.status != Step5Status.OK:
            yield {"type": "final", "result": step5.model_dump(mode="json")}
            return

        rounds_run += 1
        history.append(
            Step5RoundSummary(
                round_number=step5.round_number,
                interrogated_candidate_name=step5.interrogated_candidate_name,
                overall_verdict=step5.overall_verdict or InterrogationVerdict.FAILS,
                loop_back_instruction=step5.loop_back_instruction if step5.overall_verdict == InterrogationVerdict.FAILS else None,
                loop_back_target_field=step5.loop_back_target_field if step5.overall_verdict == InterrogationVerdict.FAILS else None,
                step5_usage=step5.usage,
                step4_usage=pending_step4_usage,
            )
        )
        pending_step4_usage = None

        if step5.overall_verdict != InterrogationVerdict.FAILS:
            step5.loop_history = history
            save_stage_output(run_id, "step5", step5)
            yield {"type": "final", "result": step5.model_dump(mode="json")}
            return

        if rounds_run >= max_rounds:
            step5.status = Step5Status.BLOCKED_UNRESOLVED
            step5.note = (
                (
                    f"第五步：连续{rounds_run}轮质询（第{start_round}轮至第{round_number}轮）均判定核心"
                    f"机制存在缺陷，已达本次循环最大轮次（max_rounds={max_rounds}），转人工介入——不是"
                    f"agent调用失败，是候选理论在当前思路下反复未能通过对抗性质询。"
                )
                if lang == "zh"
                else (
                    f"Step 5: {rounds_run} consecutive round(s) of interrogation (round {start_round} "
                    f"through round {round_number}) all judged the core mechanism to be flawed, reaching "
                    f"this loop's max round count (max_rounds={max_rounds}); escalating to human review "
                    "— this is not an agent call failure, it's the candidate theory repeatedly failing "
                    "adversarial interrogation along its current line of thinking."
                )
            )
            step5.loop_history = history
            save_stage_output(run_id, "step5", step5)
            yield {"type": "final", "result": step5.model_dump(mode="json")}
            return

        round_number += 1
        yield {"type": "round_marker", "phase": "step4", "round": round_number}
        step4_dict = None
        async for event in stream_step4(
            run_id,
            provider=provider,
            model=model,
            lang=lang,
            round_number=round_number,
            revision_instruction=step5.loop_back_instruction,
            revision_target_candidate=step5.interrogated_candidate_name,
            revision_target_field=step5.loop_back_target_field,
            reasoning_effort=reasoning_effort,
        ):
            if event["type"] == "final":
                step4_dict = event["result"]
                yield {"type": "phase_final", "phase": "step4", "round": round_number, "result": step4_dict}
            else:
                yield event

        if step4_dict is None or step4_dict.get("status") != Step4Status.OK.value:
            detail = (step4_dict or {}).get("note", "（无详情）" if lang == "zh" else "(no detail)")
            note = (
                f"第五步循环：第{round_number}轮修订时第四步agent调用异常，转人工检查：{detail}"
                if lang == "zh"
                else f"Step 5 loop: step 4's agent call failed during round {round_number}'s revision, "
                f"escalating to human review: {detail}"
            )
            failed = Step5Result(
                run_id=run_id,
                status=Step5Status.BLOCKED_AGENT_ERROR,
                round_number=round_number,
                note=note,
                loop_history=history,
            )
            save_stage_output(run_id, "step5", failed)
            yield {"type": "final", "result": failed.model_dump(mode="json")}
            return
        pending_step4_usage = step4_dict.get("usage")
        # The loop continues: the next while iteration will stream-interrogate this freshly revised
        # candidate, at which point the pending_step4_usage recorded above will be stored together into
        # that round's Step5RoundSummary.
