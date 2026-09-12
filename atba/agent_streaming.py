"""Shared glue code across steps: converts "pydantic-ai streaming events → NDJSON events."

When stream_step1 was first implemented, the extraction logic for thinking_delta/tool_call_delta and
the model_settings for Anthropic extended thinking were private code inside step 1's own file. Step 2
needed the exact same set of logic — per the "one agent run per step" architecture, steps 3 through 6
would eventually each need their own stream_stepN too; rather than each of six files maintaining its
own copy that could quietly drift apart, it made sense to factor this out now (while implementing step
2), so every future step's streaming support only needs one async for loop + a couple of conditionals,
without re-transplanting this event-classification logic.

**This round's revision**: steps 1 and 2's single run only makes one tool call (the final
report_stepN_output), so tool_call_delta events not carrying call-attribution information didn't
matter — there's only one stream of incremental text anyway, and the frontend can just accumulate it
into one buffer. Step 3's single run makes many search_scopus/get_paper_abstract calls; if the frontend
kept concatenating every tool_call_delta's text indiscriminately into the same buffer, it would smear
several different calls' argument text together into one unstructured, unreadable mess (this really
happened). Now every event carries `call_id` (from pydantic-ai's `tool_call_id`, unchanged throughout
one tool call from start to return) + `tool_name` (included only when available, not repeated on every
delta event); the frontend buckets by `call_id`, so it can display "call #1's arguments" separately
from "call #2's arguments" instead of mixing them together. Also added `tool_result` (the complete
result once a tool call actually returns, not incremental — an MCP tool's return value arrives all at
once to begin with, there's no need, and no point, pretending it's "generated incrementally") and
`tool_result_retry` (the call-failure feedback wrapped in a RetryPromptPart when pydantic-ai's
output_validator+ModelRetry mechanism triggers a retry — not a normal return value, the frontend needs
to display it in a different style, it must not be parsed as if it were a search result).

**Step 6 adds `text_delta`**: steps 1 through 5's "final answer" is always structured JSON forced
through one tool call via `ToolOutput`; the model's own free text (`TextPart`/`TextPartDelta`) used to
only ever appear during "thinking out loud" moments along the way (e.g. a short explanatory aside step
3 occasionally emits between two rounds of retrieval), never the final deliverable, so
`classify_stream_event` never handled this part kind — the final result always went through a tool
call regardless. Step 6 is different: its output **is** a markdown report itself (the `Agent` carries
no `output_type`, whose default output type is `str`), so the report's full text is the model's free-
text output, and needs to be watchable in real time as it streams — without this branch, the report-
writing process in step 6 would show nothing at all in the frontend until the run finishes and the
entire text appears at once, violating this app's consistent requirement that "the thinking/generation
process must be watchable in real time."
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic_ai import AgentRunResultEvent
from pydantic_ai.messages import (
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
)

from .schemas import TokenUsage

# Only used to explicitly turn on extended thinking for Anthropic — DeepSeek has no corresponding
# setting, not because DeepSeek necessarily has no thinking content: testing found the current default
# model deepseek-v4-flash (see llm.py) produces reasoning content on its own, while also supporting
# function calling, and thinking_delta events can be observed on the streaming endpoint without any
# extra configuration. In other words, whether thinking_delta appears depends on whether the specific
# model itself produces reasoning/thinking content, not something this constant controls — this
# constant only governs whether the Anthropic side explicitly requests it.
ANTHROPIC_THINKING_BUDGET = 3000


def anthropic_thinking_model_settings(provider: str) -> Optional[dict]:
    """When provider=="anthropic", returns the model_settings that turn on extended thinking; returns
    None for other providers (not needed, and no corresponding setting exists)."""
    if provider != "anthropic":
        return None
    return {"anthropic_thinking": {"type": "enabled", "budget_tokens": ANTHROPIC_THINKING_BUDGET}}


# The values the reasoning_effort field in a DeepSeek request body actually accepts — see the mapping
# table in DeepSeek's API docs' "thinking mode" section (five tiers: low/medium/high/xhigh/max; the
# server internally collapses medium/high/xhigh into the same "high" tier, but that's DeepSeek's own
# API behavior — all 5 options are kept here as-is for the user to choose from, without pre-simplifying
# on their behalf).
DEEPSEEK_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_DEEPSEEK_REASONING_EFFORT = "high"  # Matches DeepSeek's own default ("effort defaults to high")


def deepseek_reasoning_model_settings(provider: str, reasoning_effort: Optional[str]) -> Optional[dict]:
    """When provider=="deepseek" and a valid reasoning_effort is given, returns the model_settings that
    control "thinking effort" — `openai_reasoning_effort` is pydantic-ai OpenAIChatModelSettings' field
    name, forwarded as-is into the actual request body's `reasoning_effort` (DeepSeek goes through an
    OpenAI-compatible protocol, see atba/llm.py). This is a completely different mechanism from
    Anthropic's extended thinking (Anthropic uses a fixed token budget, DeepSeek uses tiered effort) —
    not merged into one function, since the two are mutually exclusive (a single request only ever
    uses one provider); callers combine them via "whichever matches, use that":
    `anthropic_thinking_model_settings(provider) or deepseek_reasoning_model_settings(provider,
    reasoning_effort)`, see each stepN.py's stream_stepN/run_stepN.

    Returns None when reasoning_effort is empty (the user didn't pass one / passed an invalid value) —
    doesn't force a value in, letting DeepSeek use its own default tier (per the docs: "thinking mode is
    on by default, and effort defaults to high"), which has the same effect as explicitly passing
    "high," but without needlessly writing a field into the request body the user never actively
    chose."""
    if provider != "deepseek" or not reasoning_effort:
        return None
    if reasoning_effort not in DEEPSEEK_REASONING_EFFORTS:
        return None
    return {"openai_reasoning_effort": reasoning_effort}


# OpenAI's own reasoning models (the o-series, gpt-5) accept a different tier set than DeepSeek's —
# "minimal" is a real fourth tier (gpt-5 added it; the older o-series tops out at "high"), and OpenAI has
# no "xhigh"/"max" — so this is its own function with its own tier list, not a shared one, following the
# same "provider-specific, not merged" reasoning as deepseek_reasoning_model_settings above (a single
# call only ever targets one provider, so there's nothing to actually share).
OPENAI_REASONING_EFFORTS = ("minimal", "low", "medium", "high")
DEFAULT_OPENAI_REASONING_EFFORT = "medium"  # OpenAI's own API default


def openai_reasoning_model_settings(provider: str, reasoning_effort: Optional[str]) -> Optional[dict]:
    """When provider=="openai" and a valid reasoning_effort is given, returns the model_settings that
    control OpenAI's own reasoning effort. Reuses the same `openai_reasoning_effort` pydantic-ai
    settings field as deepseek_reasoning_model_settings (both go through OpenAIChatModel — DeepSeek via
    an OpenAI-compatible shim, OpenAI natively — and that field is what forwards into the actual
    request body's `reasoning_effort`, see atba/llm.py), just gated on a different provider name and
    tier list. Unlike DeepSeek's reasoner, OpenAI's reasoning-capable models support function calling,
    so — unlike atba/llm.py's DeepSeek branch — there's no "don't point this at a reasoning model"
    warning needed here; any OpenAI chat-completions model tolerates this field being present, reasoning
    or not.

    Returns None when reasoning_effort is empty or not one of OPENAI_REASONING_EFFORTS, letting the
    model use its own default tier rather than forcing a value the caller never actively chose."""
    if provider != "openai" or not reasoning_effort:
        return None
    if reasoning_effort not in OPENAI_REASONING_EFFORTS:
        return None
    return {"openai_reasoning_effort": reasoning_effort}


def extract_usage(run_result: Any) -> TokenUsage:
    """Converts pydantic-ai's `AgentRunResult.usage` (`RunUsage`) into our own condensed `TokenUsage`
    — picking only the handful of fields meaningful to a user (see the comment on `TokenUsage` in
    schemas.py), rather than persisting every internal detail field of `RunUsage` (things like
    cache_write_tokens/opentelemetry_attributes) verbatim. Both `run_sync()`'s and
    `run_stream_events()`'s result objects have this `.usage` attribute (the same `AgentRunResult`
    type) — steps 1 through 6's run_stepN/stream_stepN all call this function before persisting,
    rather than each repeating its own copy of the conversion logic."""
    u = run_result.usage
    return TokenUsage(
        requests=u.requests,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        total_tokens=u.total_tokens,
    )


def coerce_stream_text(value: Any) -> str:
    """Uniformly converts a pydantic-ai streaming event's args/args_delta/content (str | dict | list |
    None) into a string, for the frontend to display directly as-is — no field-level incremental
    parsing happens here; the final displayed result is still the complete output object obtained once
    the run finishes, this is only meant to give the user progress feedback that "it isn't stuck,
    content is growing."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def classify_stream_event(event: object) -> tuple[Optional[dict], Optional[object]]:
    """Translates a single raw event produced by agent.run_stream_events() into
    (an NDJSON increment event or None, a run_result or None).

    The caller calls this function on each event inside its own `async for event in events:` loop:
    yield the first value if it's not None, and store the second value if it's not None (once the loop
    ends, this is the final AgentRunResult) — not merged into one "forward while collecting" generator,
    because an async generator can't carry a return value out through StopIteration the way a regular
    generator can when it ends; the caller still needs its own loop variable to hold onto run_result.
    """
    if isinstance(event, PartStartEvent):
        part = event.part
        if isinstance(part, ThinkingPart) and part.content:
            return {"type": "thinking_delta", "text": part.content}, None
        if isinstance(part, TextPart) and part.content:
            return {"type": "text_delta", "text": part.content}, None
        if isinstance(part, ToolCallPart):
            evt: dict[str, Any] = {
                "type": "tool_call_delta",
                "call_id": part.tool_call_id or "",
                "text": coerce_stream_text(part.args) if part.args else "",
            }
            if part.tool_name:
                evt["tool_name"] = part.tool_name
            return evt, None
    elif isinstance(event, PartDeltaEvent):
        delta = event.delta
        if isinstance(delta, ThinkingPartDelta) and delta.content_delta:
            return {"type": "thinking_delta", "text": delta.content_delta}, None
        if isinstance(delta, TextPartDelta) and delta.content_delta:
            return {"type": "text_delta", "text": delta.content_delta}, None
        if isinstance(delta, ToolCallPartDelta):
            evt = {
                "type": "tool_call_delta",
                "call_id": delta.tool_call_id or "",
                "text": coerce_stream_text(delta.args_delta) if delta.args_delta else "",
            }
            if delta.tool_name_delta:
                evt["tool_name"] = delta.tool_name_delta
            return evt, None
    elif isinstance(event, FunctionToolResultEvent):
        part = event.part
        call_id = getattr(part, "tool_call_id", None) or ""
        tool_name = getattr(part, "tool_name", None) or ""
        if isinstance(part, RetryPromptPart):
            # Retry feedback triggered by output_validator+ModelRetry (like step 1's theory-jargon
            # check) or by the MCP tool itself erroring — not a normal tool return value; the frontend
            # must not parse this text as if it were a "search result."
            return {
                "type": "tool_result_retry",
                "call_id": call_id,
                "tool_name": tool_name,
                "text": coerce_stream_text(part.content),
            }, None
        return {
            "type": "tool_result",
            "call_id": call_id,
            "tool_name": tool_name,
            "content": coerce_stream_text(part.content),
        }, None
    elif isinstance(event, AgentRunResultEvent):
        return None, event.result
    return None, None
