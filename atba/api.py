"""ATBA's backend HTTP API (FastAPI).

Frontend/backend split: frontend/ only accesses ATBA's capabilities through the REST interfaces here,
never importing Python code directly. atba/ itself remains an independently usable Python package
(usable via the CLI or direct import) — this layer just adds an HTTP surface on top of it.

Running (install dependencies first):
    pip install -r atba/requirements.txt
    uvicorn atba.api:app --reload --port 8000

Interactive docs: once started, visit http://localhost:8000/docs
"""

from __future__ import annotations

import json
import os
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .abductive_loop import MAX_LOOP_ROUNDS, run_step4_5_loop, stream_step4_5_loop
from .agent_streaming import (
    DEEPSEEK_REASONING_EFFORTS,
    DEFAULT_DEEPSEEK_REASONING_EFFORT,
    DEFAULT_OPENAI_REASONING_EFFORT,
    OPENAI_REASONING_EFFORTS,
)
from .auth import create_token, require_auth, verify_credentials
from .context_store import list_runs, load_manifest, load_stage_output
from .llm import DEFAULT_MODELS, SUPPORTED_PROVIDERS
from .schemas import (
    CandidateTheoryDirection,
    Step1Result,
    Step2Result,
    Step3Result,
    Step4Result,
    Step5Result,
    Step6Result,
)
from .step1 import run_step1, stream_step1
from .step2 import run_step2, save_step2_selection, stream_step2
from .step3 import run_step3, stream_step3
from .step4 import run_step4, stream_step4
from .step6 import run_step6, stream_step6

app = FastAPI(
    title="ATBA API",
    description="Abductive Theory-Building Agent — all six steps currently implemented (phenomenon input / theory matching / literature retrieval & research question / abductive reasoning & theory construction / adversarial interrogation / theoretical contribution report)",
    version="0.1.0",
)

# During development, a handful of common local frontend dev-server ports are opened directly. A
# production deployment must add its real frontend origin via ATBA_FRONTEND_ORIGINS (atba/.env) rather
# than editing this list in place — the two are on different subdomains typically (e.g.
# theory.example.com talking to theoryapi.example.com), and the browser's cross-origin check happens
# between it and *this* header, not something an nginx reverse proxy can work around by itself, since
# nginx only routes requests. Keeping the real domain in .env instead of hardcoded here also means this
# public repo's own git history never has to carry anyone's actual deployment domain. Comma-separated
# for setups serving more than one frontend origin (e.g. staging + production).
_extra_origins = [o.strip() for o in os.environ.get("ATBA_FRONTEND_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        *_extra_origins,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Except for /api/health (a liveness check, which should be reachable even before login to probe
# whether the backend is up) and /api/auth/login (login itself), every other endpoint requires a valid
# token — otherwise anyone who gets hold of the URL could directly call LLM/retrieval APIs that cost
# real money. This is consolidated with one APIRouter carrying a require_auth dependency, rather than
# manually adding `dependencies=[Depends(require_auth)]` to each of the twenty-odd routes below —
# manually doing it risks missing one; this way it's structurally impossible to miss.
protected = APIRouter(dependencies=[Depends(require_auth)])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    token: str
    expires_at: int = Field(..., description="Token expiry time, a Unix timestamp in seconds")


@app.post("/api/auth/login")
def login(req: LoginRequest) -> LoginResponse:
    """Login itself doesn't need a token (of course) — the username/password come from environment
    variables (see atba/auth.py), not a multi-user account system in a database. A wrong password and a
    nonexistent username both return the same 401 message, without distinguishing "username doesn't
    exist" from "password is wrong," to avoid leaking to a brute-force attacker whether a given username
    is valid."""
    if not verify_credentials(req.username, req.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token, expires_at = create_token(req.username)
    return LoginResponse(token=token, expires_at=expires_at)


class Step1Request(BaseModel):
    text: str = Field(..., min_length=1, description="The raw phenomenon description text")
    prior_expectation_hint: Optional[str] = Field(
        None,
        description=(
            "Optional, a prior expectation/theoretical tradition the user already has in mind (e.g. a "
            "specific paper, a theory name); not a precondition that must be confirmed first — the "
            "agent judges for itself from the input text whether the information is sufficient. Also "
            "reused (with the same run_id) when answering a NEEDS_CLARIFICATION follow-up"
        ),
    )
    lang: str = Field("en", description='System-prompt language, "zh" or "en"; does not affect output field names')
    provider: str = Field("anthropic", description=f"LLM provider, {list(SUPPORTED_PROVIDERS)}")
    model: Optional[str] = Field(None, description="Overrides the given provider's default model name")
    reasoning_effort: Optional[str] = Field(
        None,
        description=(
            f"Thinking-effort tier — only takes effect when provider='deepseek' ({list(DEEPSEEK_REASONING_EFFORTS)}) "
            f"or provider='openai' ({list(OPENAI_REASONING_EFFORTS)}); ignored for provider='anthropic', which uses a "
            "separate fixed token-budget extended-thinking mechanism instead"
        ),
    )
    max_jargon_retries: int = Field(2, ge=0, le=5, description="Max retries within the same agent run when the theory-jargon check fails")
    run_id: Optional[str] = Field(
        None, description="Reuse an existing run (e.g. rerunning the same phenomenon with a different provider); a new one is created if omitted"
    )


@app.get("/api/health")
def health() -> dict:
    """A liveness check + tells the frontend which providers/default models are currently supported
    (for rendering a selector) + the step-4/5 loop's max round count (for the frontend to display copy
    like "at most N more automatic retries," without maintaining this number separately on the frontend
    and backend where it could drift) + DeepSeek's and OpenAI's available thinking-effort tiers and
    default values (likewise, the option lists and defaults are defined once in the backend's
    atba/agent_streaming.py, and the frontend reads from here when rendering the dropdown, rather than
    each side keeping its own copy that could drift). Anthropic has no equivalent field here — its
    extended thinking is a fixed token budget, not a tiered selection, see
    anthropic_thinking_model_settings."""
    return {
        "status": "ok",
        "providers": DEFAULT_MODELS,
        "max_loop_rounds": MAX_LOOP_ROUNDS,
        "deepseek_reasoning_efforts": list(DEEPSEEK_REASONING_EFFORTS),
        "default_deepseek_reasoning_effort": DEFAULT_DEEPSEEK_REASONING_EFFORT,
        "openai_reasoning_efforts": list(OPENAI_REASONING_EFFORTS),
        "default_openai_reasoning_effort": DEFAULT_OPENAI_REASONING_EFFORT,
    }


@protected.post("/api/step1")
def step1(req: Step1Request) -> dict:
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}",
        )
    try:
        result = run_step1(
            raw_text=req.text,
            prior_expectation_hint=req.prior_expectation_hint,
            max_jargon_retries=req.max_jargon_retries,
            provider=req.provider,
            model=req.model,
            lang=req.lang,
            run_id=req.run_id,
            reasoning_effort=req.reasoning_effort,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # Usually a missing API key for the provider — not a client input error, but not something
        # that should be hidden as an "internal server error" either; the readable reason is surfaced
        # directly for the frontend to display. A model call itself failing (auth/network/rate limit)
        # is already caught inside run_step1 and turned into a normally-returned
        # Step1Status.BLOCKED_AGENT_ERROR, so it never reaches here.
        raise HTTPException(status_code=502, detail=str(e))
    return result.model_dump(mode="json")


@protected.post("/api/step1/stream")
async def step1_stream(req: Step1Request) -> StreamingResponse:
    """The streaming version of `/api/step1`: NDJSON (one JSON event per line), not SSE — the request
    itself is a POST with a body, and the browser's native EventSource only supports GET, so reading an
    NDJSON stream manually via fetch is simpler, with no extra SSE framework layer needed.

    Event types are documented in atba/step1.py's stream_step1 docstring; the last line is always
    {"type": "final", ...} — once the frontend reads it, it can stop reading and treat `result` as a
    final result fully isomorphic with /api/step1's.

    Error handling is deliberately different from /api/step1: there, an unsupported provider, or a
    missing API key, are turned into explicit 400/502 status codes respectively, giving the frontend a
    clear reason before any real work starts. But once a streaming response has sent its first chunk,
    the HTTP status code is already 200 and can't be changed — provider validation still happens early
    here (before streaming begins, a normal 400 can still be returned); the missing-API-key case, which
    would normally turn into a 502 inside run_step1, is folded into the normal exception branch inside
    stream_step1, uniformly turned into a BLOCKED_AGENT_ERROR final event sent normally through the
    stream (see stream_step1's docstring).
    """
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}",
        )

    async def gen() -> AsyncIterator[str]:
        async for event in stream_step1(
            raw_text=req.text,
            prior_expectation_hint=req.prior_expectation_hint,
            max_jargon_retries=req.max_jargon_retries,
            provider=req.provider,
            model=req.model,
            lang=req.lang,
            run_id=req.run_id,
            reasoning_effort=req.reasoning_effort,
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


class Step2Request(BaseModel):
    run_id: str = Field(..., description="Must be a run that has completed step 1 (status=passed) — step 2 has no independent phenomenon-text input")
    lang: str = Field("en", description='System-prompt language, "zh" or "en"; does not affect output field names')
    provider: str = Field("anthropic", description=f"LLM provider, {list(SUPPORTED_PROVIDERS)}")
    model: Optional[str] = Field(None, description="Overrides the given provider's default model name")
    reasoning_effort: Optional[str] = Field(
        None,
        description=(
            f"Thinking-effort tier — only takes effect when provider='deepseek' ({list(DEEPSEEK_REASONING_EFFORTS)}) "
            f"or provider='openai' ({list(OPENAI_REASONING_EFFORTS)}); ignored for provider='anthropic', which uses a "
            "separate fixed token-budget extended-thinking mechanism instead"
        ),
    )


@protected.post("/api/step2")
def step2(req: Step2Request) -> dict:
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}",
        )
    try:
        result = run_step2(
            run_id=req.run_id, provider=req.provider, model=req.model, lang=req.lang, reasoning_effort=req.reasoning_effort
        )
    except FileNotFoundError as e:
        # The run_id itself doesn't exist (step 1 was never run)
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        # run_id exists, but step 1 hasn't passed (no usable phenomenon card) — the client called at
        # the wrong time, not an internal server error
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # Same as /api/step1: usually a missing API key for the provider
        raise HTTPException(status_code=502, detail=str(e))
    return result.model_dump(mode="json")


@protected.post("/api/step2/stream")
async def step2_stream(req: Step2Request) -> StreamingResponse:
    """The streaming version of `/api/step2`, behaving symmetrically to `/api/step1/stream` — see its
    docstring. One thing specific to step 2: cases where the run fundamentally can't start (run_id
    doesn't exist / step 1 hasn't passed) are uniformly turned into a BLOCKED_AGENT_ERROR final event
    inside stream_step2, rather than returning an early 404/400 like /api/step2 (non-streaming) does —
    a streaming response's HTTP status code is already fixed at 200 before the first chunk is sent, and
    can't be changed afterward."""
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}",
        )

    async def gen() -> AsyncIterator[str]:
        async for event in stream_step2(
            run_id=req.run_id, provider=req.provider, model=req.model, lang=req.lang, reasoning_effort=req.reasoning_effort
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


class Step3Request(BaseModel):
    run_id: str = Field(
        ..., description="Must be a run that has completed step 2 with selected_theory_directions non-empty — step 3 has no independent input"
    )
    lang: str = Field("en", description='System-prompt language, "zh" or "en"; does not affect output field names')
    provider: str = Field("anthropic", description=f"LLM provider, {list(SUPPORTED_PROVIDERS)}")
    model: Optional[str] = Field(None, description="Overrides the given provider's default model name")
    reasoning_effort: Optional[str] = Field(
        None,
        description=(
            f"Thinking-effort tier — only takes effect when provider='deepseek' ({list(DEEPSEEK_REASONING_EFFORTS)}) "
            f"or provider='openai' ({list(OPENAI_REASONING_EFFORTS)}); ignored for provider='anthropic', which uses a "
            "separate fixed token-budget extended-thinking mechanism instead"
        ),
    )


@protected.post("/api/step3")
async def step3(req: Step3Request) -> dict:
    """Step 3: literature retrieval, produce a research question. Step 3's agent autonomously calls
    D.4's search_scopus tool multiple times within this one call (see atba/step3.py), so response times
    can be noticeably longer than steps 1/2 — this is expected behavior."""
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}",
        )
    try:
        result = run_step3(
            run_id=req.run_id, provider=req.provider, model=req.model, lang=req.lang, reasoning_effort=req.reasoning_effort
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        # run_id exists, but step 2 hasn't passed / no candidate direction has been confirmed yet —
        # the client called at the wrong time, not an internal server error
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result.model_dump(mode="json")


@protected.post("/api/step3/stream")
async def step3_stream(req: Step3Request) -> StreamingResponse:
    """The streaming version of `/api/step3`, behaving symmetrically to `/api/step2/stream` — see its
    docstring."""
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}",
        )

    async def gen() -> AsyncIterator[str]:
        async for event in stream_step3(
            run_id=req.run_id, provider=req.provider, model=req.model, lang=req.lang, reasoning_effort=req.reasoning_effort
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


class Step4Request(BaseModel):
    run_id: str = Field(..., description="Must be a run that has completed step 3 with research_question non-empty — step 4 has no independent input")
    lang: str = Field("en", description='System-prompt language, "zh" or "en"; does not affect output field names')
    provider: str = Field("anthropic", description=f"LLM provider, {list(SUPPORTED_PROVIDERS)}")
    model: Optional[str] = Field(None, description="Overrides the given provider's default model name")
    reasoning_effort: Optional[str] = Field(
        None,
        description=(
            f"Thinking-effort tier — only takes effect when provider='deepseek' ({list(DEEPSEEK_REASONING_EFFORTS)}) "
            f"or provider='openai' ({list(OPENAI_REASONING_EFFORTS)}); ignored for provider='anthropic', which uses a "
            "separate fixed token-budget extended-thinking mechanism instead"
        ),
    )


@protected.post("/api/step4")
def step4(req: Step4Request) -> dict:
    """Step 4: abductive reasoning, construct a new theory. **This endpoint only runs one round
    (round_number=1) of candidate generation** — it doesn't cover the revision round triggered by step
    5's interrogation; that revision round is called automatically from inside /api/step5
    (atba/abductive_loop.py) when needed, not through this endpoint. This endpoint corresponds to the
    user clicking "run"/"retry" on step 4's page: every call is a fresh round_number=1 generation, not
    a continuation of the previous round."""
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}")
    try:
        result = run_step4(
            run_id=req.run_id, provider=req.provider, model=req.model, lang=req.lang, reasoning_effort=req.reasoning_effort
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result.model_dump(mode="json")


@protected.post("/api/step4/stream")
async def step4_stream(req: Step4Request) -> StreamingResponse:
    """The streaming version of `/api/step4`, behaving symmetrically to the other stepN/stream
    endpoints — see /api/step3/stream's docstring."""
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}")

    async def gen() -> AsyncIterator[str]:
        async for event in stream_step4(
            run_id=req.run_id, provider=req.provider, model=req.model, lang=req.lang, reasoning_effort=req.reasoning_effort
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


class Step5Request(BaseModel):
    run_id: str = Field(..., description="Must be a run that has completed step 4 (status=passed) — step 5 has no independent input")
    lang: str = Field("en", description='System-prompt language, "zh" or "en"; does not affect output field names')
    provider: str = Field("anthropic", description=f"LLM provider, {list(SUPPORTED_PROVIDERS)}")
    model: Optional[str] = Field(None, description="Overrides the given provider's default model name")
    reasoning_effort: Optional[str] = Field(
        None,
        description=(
            f"Thinking-effort tier — only takes effect when provider='deepseek' ({list(DEEPSEEK_REASONING_EFFORTS)}) "
            f"or provider='openai' ({list(OPENAI_REASONING_EFFORTS)}); ignored for provider='anthropic', which uses a "
            "separate fixed token-budget extended-thinking mechanism instead"
        ),
    )


@protected.post("/api/step5")
def step5(req: Step5Request) -> dict:
    """Step 5: adversarial interrogation. **This endpoint runs the complete step-4/5 automatic loop**
    (atba/abductive_loop.py), not a single round of interrogation — when the interrogation judges the
    candidate theory's core mechanism to be flawed, it automatically sends things back to step 4 for
    revision and interrogates again within this same call, looping up to MAX_LOOP_ROUNDS rounds until
    it passes or is escalated to human review; one call returns the loop's terminal state. Response
    times can be noticeably longer than other steps (equivalent to up to MAX_LOOP_ROUNDS rounds of step
    5's agent + up to MAX_LOOP_ROUNDS-1 rounds of step 4's agent), which is expected behavior."""
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}")
    try:
        result = run_step4_5_loop(
            run_id=req.run_id, provider=req.provider, model=req.model, lang=req.lang, reasoning_effort=req.reasoning_effort
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result.model_dump(mode="json")


@protected.post("/api/step5/stream")
async def step5_stream(req: Step5Request) -> StreamingResponse:
    """The streaming version of `/api/step5` — has two more event types than the other stepN/stream
    endpoints (`round_marker`/`phase_final`), letting the frontend correctly display "which round's
    step 4 or step 5 is this," see atba/abductive_loop.py's stream_step4_5_loop docstring.
    `type:"final"` only ever appears once, when the entire loop genuinely ends."""
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}")

    async def gen() -> AsyncIterator[str]:
        async for event in stream_step4_5_loop(
            run_id=req.run_id, provider=req.provider, model=req.model, lang=req.lang, reasoning_effort=req.reasoning_effort
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


class Step6Request(BaseModel):
    run_id: str = Field(..., description="Must be a run that has completed step 5 (status=passed) — step 6 has no independent input")
    lang: str = Field("en", description='Report language, "zh" or "en" — unlike the other steps, this directly determines the report body\'s language')
    provider: str = Field("anthropic", description=f"LLM provider, {list(SUPPORTED_PROVIDERS)}")
    model: Optional[str] = Field(None, description="Overrides the given provider's default model name")
    reasoning_effort: Optional[str] = Field(
        None,
        description=(
            f"Thinking-effort tier — only takes effect when provider='deepseek' ({list(DEEPSEEK_REASONING_EFFORTS)}) "
            f"or provider='openai' ({list(OPENAI_REASONING_EFFORTS)}); ignored for provider='anthropic', which uses a "
            "separate fixed token-budget extended-thinking mechanism instead"
        ),
    )


@protected.post("/api/step6")
def step6(req: Step6Request) -> dict:
    """Step 6: produce the theoretical contribution report. **The response body's `report_markdown`
    field is the complete markdown report text itself**, not a bunch of structured fields like the
    other steps — the frontend renders this field directly."""
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}")
    try:
        result = run_step6(
            run_id=req.run_id, provider=req.provider, model=req.model, lang=req.lang, reasoning_effort=req.reasoning_effort
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result.model_dump(mode="json")


@protected.post("/api/step6/stream")
async def step6_stream(req: Step6Request) -> StreamingResponse:
    """The streaming version of `/api/step6` — `text_delta` events appear in the event stream (the
    incremental text of the report body itself, not thinking, and not some tool call's arguments); the
    frontend uses this to implement "read as it's generated," see the "step 6 adds text_delta" section
    in atba/agent_streaming.py's top-of-file docstring."""
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider {req.provider!r}, currently supported: {list(SUPPORTED_PROVIDERS)}")

    async def gen() -> AsyncIterator[str]:
        async for event in stream_step6(
            run_id=req.run_id, provider=req.provider, model=req.model, lang=req.lang, reasoning_effort=req.reasoning_effort
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@protected.get("/api/runs")
def get_runs() -> list[dict]:
    """Lists every run's manifest (including a phenomenon-text preview), for the frontend's "run
    history" list page — each step has its own route (/runs/{run_id}/step1, .../step2, etc. going
    forward), and this endpoint is the data source for the "look back at past history" list."""
    return list_runs()


@protected.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """Queries which step a given run has currently reached, and each step's status — corresponds to
    runs/<run_id>/manifest.json."""
    try:
        return load_manifest(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@protected.get("/api/runs/{run_id}/step1")
def get_run_step1(run_id: str) -> dict:
    """Re-reads a run's already-persisted step-1 output — step 2's sub-agent, and the frontend
    refreshing the page, both go through this endpoint, rather than depending on an object still
    sitting in some process's memory."""
    try:
        result = load_stage_output(run_id, "step1", Step1Result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result.model_dump(mode="json")


@protected.get("/api/runs/{run_id}/step2")
def get_run_step2(run_id: str) -> dict:
    """Re-reads a run's already-persisted step-2 output, used symmetrically to get_run_step1."""
    try:
        result = load_stage_output(run_id, "step2", Step2Result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result.model_dump(mode="json")


@protected.get("/api/runs/{run_id}/step3")
def get_run_step3(run_id: str) -> dict:
    """Re-reads a run's already-persisted step-3 output, used symmetrically to get_run_step1."""
    try:
        result = load_stage_output(run_id, "step3", Step3Result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result.model_dump(mode="json")


@protected.get("/api/runs/{run_id}/step4")
def get_run_step4(run_id: str) -> dict:
    """Re-reads a run's already-persisted step-4 output, used symmetrically to get_run_step1. If step
    5's loop has triggered a revision round, what's read here is always the **latest round's**
    candidates (step4.json is persisted with an overwrite on every round, see atba/step4.py)."""
    try:
        result = load_stage_output(run_id, "step4", Step4Result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result.model_dump(mode="json")


@protected.get("/api/runs/{run_id}/step5")
def get_run_step5(run_id: str) -> dict:
    """Re-reads a run's already-persisted step-5 output, used symmetrically to get_run_step1."""
    try:
        result = load_stage_output(run_id, "step5", Step5Result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result.model_dump(mode="json")


@protected.get("/api/runs/{run_id}/step6")
def get_run_step6(run_id: str) -> dict:
    """Re-reads a run's already-persisted step-6 output, used symmetrically to get_run_step1."""
    try:
        result = load_stage_output(run_id, "step6", Step6Result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result.model_dump(mode="json")


class Step2SelectionRequest(BaseModel):
    selected_theory_directions: list[CandidateTheoryDirection] = Field(
        ..., description="The subset of step 2's candidate_theory_directions the user checked off, to send into step 3's retrieval"
    )


@protected.post("/api/runs/{run_id}/step2/selection")
def select_step2_directions(run_id: str, req: Step2SelectionRequest) -> dict:
    """Not an agent run, purely persisting a manual filtering result — writes the theory directions the
    user checked off back into step2.json, see save_step2_selection in atba/step2.py. Step 3 should
    read this field as its input, rather than asking the user to select again on step 3's page."""
    try:
        result = save_step2_selection(run_id, req.selected_theory_directions)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result.model_dump(mode="json")


# Mounted last — every @protected.get/@protected.post decorator above only registers a route onto this
# router object as it executes; making these routes actually take effect on the app requires this
# include_router step. It's placed at the end of the file simply because every route definition comes
# before it; there's no real ordering dependency.
app.include_router(protected)
