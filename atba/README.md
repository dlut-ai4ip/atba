# ATBA Implementation Code

The complete implementation of the six-step design from the project's technical appendix. **All six
steps are implemented** (phenomenon input / initial theory matching / literature retrieval producing a
research question / abductive reasoning constructing a new theory / adversarial interrogation /
producing the theoretical contribution report), with a corresponding FastAPI backend and React frontend
(see [`../frontend/`](../frontend)).

## Architectural conventions (followed consistently across steps)

- **Each stage is one independent sub-agent, completing all the judgments that stage requires within a
  single `agent.run()`** — even when a stage internally has multiple checks/sub-mechanisms, or even
  needs to call external tools many times, it only ever fires **one** `agent.run()`; when a check fails
  and needs a retry, it goes through [pydantic-ai](https://github.com/pydantic/pydantic-ai)'s
  `output_validator` + `ModelRetry` mechanism, automatically regenerating within the **same** `run()`,
  never firing a separate external call. Step 1's prior-expectation identification + causal-
  presupposition check + theory-jargon check + phenomenon deconstruction are merged into one `run()`
  under exactly this convention. Step 2 is simpler, a single judgment. **Step 3 is currently the
  heaviest-duty application of this principle** — within a single `run()` it autonomously calls the
  retrieval tool many times (one tool call per candidate theoretical direction, per degradation tier,
  per rewrite retry); the retrieval happens inside step 3's own agent, it isn't outsourced to a separate
  "retrieval agent" as a middleman (this matters — see the D.4 section below).
- **The ordering between stages is still explicit Python code**, not left for some agent to decide
  autonomously "what to do next" — this is a design principle explicitly stated in the project's
  technical appendix ("the model must not be allowed to decide the next step on its own"), and it's also
  where the "auditable" selling point comes from. pydantic-ai is used only at the layer of "how to call
  the model within each stage" — the orchestration of the six steps itself doesn't bring in a graph-
  orchestration framework.
- **Each stage's structured output is persisted to `runs/<run_id>/<stage>.json`** (see
  [`context_store.py`](context_store.py)), serving as the input source for the next stage, rather than
  staying only in the caller process's in-memory objects — under a frontend/backend-separated
  architecture, a single six-step run spans multiple HTTP requests (especially after a "handed off to a
  human" pause, which could resume much later), and later steps must be able to read from persisted
  artifacts, not depend on in-memory state that the previous step's caller process happens to still
  hold. `runs/` isn't checked into version control. Step 3 reads both step 1's (the phenomenon card)
  and step 2's (`selected_theory_directions`, the subset of candidate directions the user checked and
  confirmed in the frontend) persisted output.
- **Each stage's output schema is the pydantic `BaseModel` in `atba/schemas.py`**, which is
  simultaneously the `output_type` fed to pydantic-ai, FastAPI's response body, and the source for the
  human-readable `atba/schemas/<stage>.schema.json` files — after changing `schemas.py`, run
  `python -m atba.export_schemas` to regenerate the schema files; don't hand-edit the `.schema.json`
  files. Field names uniformly use English identifiers (isomorphic with the retrodiction extraction
  schema in appendix C' of 02_技术附录初稿.md); enum fields (like step 3's `hit_level`) use a genuine
  Python `Enum` rather than free text — testing found that letting the model write its own text
  description for this kind of field produces sentences outside the expected set of values, which code
  can't reliably branch on.
- **The system prompt is kept separately in `atba/prompts/<stage>.{zh,en}.md`**, not hardcoded in the
  code; every prompt has both Chinese and English versions (toggled via the `lang="zh"`/`"en"`
  parameter, defaulting to en), but the output field names are always fixed English keys, unaffected by
  language. Reusable "skill" knowledge (strategy/methodology not exclusive to one step) is kept in its
  own file, spliced in by whichever step needs it when loading its system prompt —
  `atba/prompts/retrieval_skill.md` is one such file, used by both step 3 and step 5, see the D.4
  section.
- **Streaming-event classification/conversion logic is factored out into
  [`agent_streaming.py`](agent_streaming.py)**, reused by each step's `stream_stepN` (extracting
  thinking_delta/tool_call_delta, Anthropic's extended-thinking model_settings), so each step doesn't
  have to maintain its own copy that's prone to drifting.

## Current scope and known gaps

- **Step 1** ([`step1.py`](step1.py)) completes four independent judgments within a single agent run:
  1. **Prior-expectation identification** (`prior_expectation_identification`): the agent judges for
     itself, from the input text (+ an optional `prior_expectation_hint`), whether there's enough
     information to proceed to the next step, asking the user only when there isn't — it doesn't
     require the caller to manually confirm before submitting. This isn't real literature retrieval,
     just an information-sufficiency judgment.
  2. **Causal-presupposition check** (`causal_presupposition_check`, checks the raw input text): a hit
     doesn't block the pipeline, it just extracts the user's proposed causal explanation separately, as
     reference material for step 4's candidate generation.
  3. **Phenomenon deconstruction** (`phenomenon_deconstruction`): broken down into a five-field
     structured fact card, keeping only purely observational content.
  4. **Theory-jargon check** (`theory_jargon_check`, checks the phenomenon deconstruction produced
     above): a hit automatically triggers regeneration with jargon feedback within the same run, up to
     `max_jargon_retries` times; if it still doesn't pass, it's escalated to a human.
- **Step 2** ([`step2.py`](step2.py)): based on step 1's persisted phenomenon card, matches 2-4
  possibly relevant theoretical directions (`candidate_theory_directions`), without judging any gap or
  requiring traceable existing literature yet — that's step 3's job. No independent input, only accepts
  `run_id` (must be a run that has completed step 1 with status=passed). The frontend lets the user
  check a subset and calls `save_step2_selection` to persist it (`selected_theory_directions`); step 3
  reads this field as input, without asking the user to select again.
- **Step 3** ([`step3.py`](step3.py)): **the single most validity-fragile link in the whole system** —
  for each candidate theoretical direction confirmed by step 2, the agent directly attaches D.4's MCP
  retrieval tools (`search_scopus`+`get_paper_abstract`, see the next section), and following a
  three-tier degrading retrieval protocol (exact-mechanism match → theory-family tier → broad-discipline
  tier, rewriting and retrying once per tier before degrading) genuinely retrieves literature, judging
  through two lenses at once whether that direction can explain step 1's phenomenon — gap-spotting
  (theory-void type/mechanism-problem type) and problematization (challenging-type: challenging an
  implicit assumption shared by the retrieved literature, per Alvesson & Sandberg 2011, see
  `atba/prompts/problematization_skill.md`), preferring the problematization type unless it fails
  Davis's (1971) obvious/absurd/interesting self-check, in which case it falls back to gap-spotting; or
  escalating to human review when every direction turns out "not constituting a puzzle." Three terminal
  states: `passed` (a research question was produced) / `no_gap_found` (every direction was judged to
  not constitute a puzzle, **not a failure** — a legitimate conclusion needing human review) /
  `retrieval_unavailable` (a genuine failure of the retrieval tool itself, e.g. a missing API key — an
  entirely different kind of thing from `no_gap_found`, must never be conflated; testing genuinely hit
  this pitfall and it's already been fixed, see the `Step3Status` docstring).
- **Step 4** ([`step4.py`](step4.py)): starting from step 3's research question, completes four
  sub-steps in sequence within **a single agent run** — candidate generation (3-5 mutually exclusive
  candidates), relation-graph construction (internal reasoning, not produced separately), four-virtue
  scoring (consilience/coherence/parsimony/precision, with the ranking computed by propagation from the
  relation graph), and selecting the best candidate. **Scope deliberately narrowed at the user's
  request**: construct-novelty checking and the Lakatos hard-core/protective-belt judgment were
  originally part of the six sub-steps (and testing confirmed they could catch real problems: in one
  test, 1 of 4 candidates was judged to "essentially already exist" in existing literature), but they've
  now been moved out — step 4 therefore doesn't attach the D.4 retrieval tools, it's a pure reasoning
  task, narrowed to focus on the theoretical contribution itself; when generating candidates, the
  literature step 3 actually retrieved (including the original abstract text, grouped by direction, not
  limited to the direction the final research question came from) is fed to the agent in full — "which
  existing construct was borrowed/modified" must be grounded in this original text, not supplemented
  from the model's own background knowledge about paper content. The two fields
  `round_number`/`revision_instruction` record "which round of generation this is, what revision
  instruction it received" — a revision round is triggered by step 5's loop controller; `atba/step4.py`
  itself has no knowledge of the loop's existence (it only handles "run once given these parameters").
- **Step 5** ([`step5.py`](step5.py) + [`abductive_loop.py`](abductive_loop.py)): **the core design
  constraint is independence** — the interrogating agent is given only the candidate theory's own
  object-level content (`theory_elements`/borrowed construct/full explanation), **deliberately
  excluding** step 4's own scoring and selection rationale — "meta-reasoning" — to create genuine
  adversarial pressure rather than self-affirmation; the relabeling-suspicion follow-up attaches the D.4
  retrieval tools for independent verification — since step 4's novelty check was moved out, **this is
  the only place left in the whole pipeline that still retrieves to verify "is this just an old
  construct under a new name."** `step5.py` itself is only responsible for a single round of
  interrogation; the loop orchestration (interrogation judges a core-mechanism flaw → sends it back to
  step 4 for revision → re-interrogates, up to `MAX_LOOP_ROUNDS=3` rounds, escalating to a human beyond
  that) lives in the separate `abductive_loop.py` — not an agent run, pure Python control flow; stuffing
  it into either `step4.py` or `step5.py` would make that file simultaneously responsible for both
  "running one agent call" and "deciding whether to run again," see that file's top-of-file docstring.
- **Step 6** ([`step6.py`](step6.py)): **structurally different from the first five steps** — the
  output isn't JSON, it's the full text of a markdown report itself (the `Agent` has no `output_type`,
  so pydantic-ai's default output type is just `str`), and it doesn't need to — and can't — splice in
  any retrieval/skill fragments, because this step **produces no new reasoning**: whether the candidate
  theory holds up, whether the mechanism is sound — these judgments were already completed in step 4
  (generation + scoring) and step 5 (independent interrogation). It integrates two things: (1) folding
  step 5's honestly-listed `unanswered_weaknesses` verbatim into the report's "boundaries and
  limitations" subsection, without hiding them; (2) translating step 4's five theory elements
  (X/Y/relation form/mechanism/assumption/boundary conditions) into H1/H2-style hypothesis statements —
  the only judgment needed here is "does mechanism M need its own separate mediation hypothesis," a
  writing-level structural judgment, not redoing the abductive reasoning. The report structure is fixed
  at four sections (a condensed introduction / theory and hypotheses [including a Mermaid theory-
  relationship diagram] / theoretical contribution / references) + an appendix (a candidate comparison
  table + a reasoning-trail summary), with a lightweight `output_validator` checking that all four
  section headings are present, triggering a `ModelRetry` if any are missing. References only include
  literature that genuinely appeared in the input, following the project-wide anti-strawman discipline —
  it will never fabricate an entry just because "this paper should probably be mentioned."
- **Steps 1 through 6 all have both a sync and a streaming entry point**: `run_stepN` (synchronous,
  returns the complete result in one shot) is for CLI/non-streaming API endpoints; `stream_stepN` (an
  async generator) yields the model's thinking process/structured output (including intermediate tool
  calls) as incremental text while it runs, for `/api/stepN/stream` to forward to the frontend for real-
  time display. Steps 3/4/5 have noticeably more tool calls per task than the first two steps, and
  correspondingly longer response times — this is expected behavior, especially for step 5, where a
  single `/api/step5` call may genuinely run several rounds of interrogation + revision internally. Step
  6's streaming events have one extra type, `text_delta` (incremental text of the report body itself,
  not thinking, and not the arguments of some tool call — steps 1 through 5's final answers all go
  through `ToolOutput`, and any free text the model produces is just incidental process commentary,
  never the final deliverable, so `classify_stream_event` originally had no handling for this part kind;
  step 6 is different — the full report text *is* the model's free-text output, see the "step 6 adds
  text_delta" section of the top-of-file docstring in `atba/agent_streaming.py`).

## Installation and running

```bash
pip install -r atba/requirements.txt
```

Configure your API keys by copying the template under `atba/` and filling in your own keys (`.env` is
already in `.gitignore` and won't be committed):

```bash
cp atba/.env.example atba/.env
```

`atba/__init__.py` automatically reads `atba/.env` in the same directory on import — the CLI,
`uvicorn atba.api:app`, and the example scripts don't need to manually `$env:...`, and it doesn't matter
which directory you run these commands from. A shell-level environment variable can still override the
value in `.env` (`$env:ANTHROPIC_API_KEY = "sk-ant-..."`), with the manual setting taking priority.

The full annotated list lives in [`.env.example`](.env.example); the variables that actually matter in
practice are:

| Variable | Required? | Default if unset | What it's for |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | One of these three, at minimum | — | Lets `--provider anthropic` (the CLI/API default) actually call a model. |
| `DEEPSEEK_API_KEY` | One of these three, at minimum | — | Lets `--provider deepseek` call a model; needed to reproduce the demo, which was generated with DeepSeek. |
| `OPENAI_API_KEY` | One of these three, at minimum | — | Lets `--provider openai` call a model — the native case `OpenAIChatModel`/`OpenAIProvider` were built for, no compatibility shim needed. |
| `ATBA_LLM_PROVIDER` | Optional | `anthropic` | Which provider is used when a call doesn't explicitly pass `--provider`/`provider=`. |
| `ATBA_ANTHROPIC_MODEL` / `ATBA_DEEPSEEK_MODEL` / `ATBA_OPENAI_MODEL` | Optional | the code's built-in defaults (see `DEFAULT_MODELS` in [`llm.py`](llm.py)) | Overrides a provider's default model name. DeepSeek reasoning models (e.g. `deepseek-reasoner`) don't support function calling, which every step in this pipeline relies on — don't point this at one. OpenAI's own reasoning models don't have this restriction. |
| `SCOPUS_API_KEY` | **Required for step 3 to do real retrieval** | — | Without it, `search_scopus` fails explicitly and step 3 returns `retrieval_unavailable` (an honest failure, never silently faked), see the D.4 section below. A personal Elsevier Developer key usually only grants Search API access, not abstracts — see `get_abstract_via_scopus_raw`'s docstring in [`retrieval.py`](retrieval.py). |
| `SCOPUS_INST_TOKEN` | Optional | — | Only needed if your institution's Scopus access requires an institutional token in addition to the API key. |
| `SEMANTIC_SCHOLAR_API_KEY` / `CONTACT_EMAIL` | Optional | — | Abstract lookup (`get_paper_abstract`) works unauthenticated against Semantic Scholar/OpenAlex; these just raise the rate limit. |
| `ATBA_AUTH_USERNAME` / `ATBA_AUTH_PASSWORD` | **Required to change before any real deployment** | `atba` / `atba` | The single login account for the backend HTTP API/frontend (see [`auth.py`](auth.py)) — not a multi-user system, just a barrier so a casually-shared URL can't call LLM/retrieval APIs that cost real money. Irrelevant for pure CLI usage. |
| `ATBA_AUTH_SECRET_KEY` | **Required to change before any real deployment** | a hardcoded dev value in the code | Signs the login token. Generate a real one with `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `ATBA_RUNS_DIR` | Optional | `runs/` under the repo root | Where each run's `runs/<run_id>/stepN.json` output files are written. |

The last three rows only matter once you run the backend (`uvicorn atba.api:app`) for real, rather than
just the CLI — the default auth credentials/secret key are fine for local experimentation, but must never
ship as-is anywhere reachable by anyone else.

Run the delivery-rider case (corresponding to the manual walkthrough record in §C of the technical
appendix, so you can compare the output for similarity):

```bash
python -m atba.examples.run_rider_case
```

Or run it step by step from the command line:

```bash
# Step 1
python -m atba.cli step1 --text "your phenomenon description"

# If step 1 returns needs_clarification, resubmit with your answer and the same run-id:
python -m atba.cli step1 --text "your phenomenon description" --run-id <the run_id returned by step 1> --prior-hint "your answer"

# Step 2: only needs step 1's run_id, automatically reads that run's persisted phenomenon card
python -m atba.cli step2 --run-id <a run_id with status=passed from step 1>

# Step 3: candidate directions must already be confirmed via the frontend (or by calling
# /api/runs/{run_id}/step2/selection directly)
python -m atba.cli step3 --run-id <a run_id with confirmed candidate directions>

# Step 4: needs a run_id for which step 3 has already produced a research question; only runs one
# round of candidate generation (round_number=1)
python -m atba.cli step4 --run-id <a run_id with status=passed from step 3>

# Step 5: needs a run_id for which step 4 has already selected a candidate theory — runs the complete
# automatic step 4/5 loop, not a single round of interrogation
python -m atba.cli step5 --run-id <a run_id with status=passed from step 4>

# Step 6: needs a run_id with status=passed from step 5 — the output is the full markdown report text,
# printed directly to stdout (not a pretty-printed JSON of structured data — the report itself is meant
# for a human to read)
python -m atba.cli step6 --run-id <a run_id with status=passed from step 5>
```

Every step's result is printed to stdout (step 6 is the exception, printing the report body itself) and
also persisted to `runs/<run_id>/<step>.json`.

## Provider / model selection

```bash
python -m atba.cli step1 --text "..." --provider deepseek
```

`--provider` supports `anthropic` (default) / `deepseek` (OpenAI-compatible protocol, going through
pydantic-ai's built-in `DeepSeekProvider`; deepseek-reasoner doesn't support function calling, so the
default `deepseek-chat` must be used) / `openai` (the native case `OpenAIChatModel`/`OpenAIProvider`
were built for, no compatibility shim needed — and unlike DeepSeek's reasoner, OpenAI's own reasoning
models do support function calling, so there's no equivalent restriction on which OpenAI model you
point this at). The default models are in `DEFAULT_MODELS` in [`llm.py`](llm.py),
overridable with `--model`, or override the default provider with the `ATBA_LLM_PROVIDER` environment
variable.

## Backend HTTP API

```bash
uvicorn atba.api:app --reload --port 8000
```

Interactive docs: `http://localhost:8000/docs`. Frontend and backend are separated — `frontend/` only
accesses this REST interface, it never imports Python code directly. Main endpoints:

- `POST /api/step1` / `POST /api/step1/stream` (NDJSON streaming)
- `POST /api/step2` / `POST /api/step2/stream`
- `POST /api/runs/{run_id}/step2/selection` (persists the user's checked candidate theoretical
  directions — a purely manual filtering result, not an agent run)
- `POST /api/step3` / `POST /api/step3/stream`
- `POST /api/step4` / `POST /api/step4/stream` (runs only one round, round_number=1, of candidate
  generation)
- `POST /api/step5` / `POST /api/step5/stream` (runs the complete automatic step 4/5 loop; the
  streaming version has two more event types than the other stepN/stream endpoints, `round_marker`/
  `phase_final`, used to let the frontend display "which round, step 4 or step 5, is this currently,"
  see the `stream_step4_5_loop` docstring in `atba/abductive_loop.py`)
- `POST /api/step6` / `POST /api/step6/stream` (the response body's `report_markdown` field is the
  complete report text itself, not a pile of structured fields; the streaming version emits
  `text_delta` events carrying the report body's own incremental text)
- `GET /api/runs` (the run history list)
- `GET /api/runs/{run_id}` (the manifest: which step it's reached, each step's status)
- `GET /api/runs/{run_id}/step1`, `.../step2` ... `.../step6` (re-reads a given step's already-persisted
  output)
- `GET /api/health` (a liveness check that also returns `max_loop_rounds` — the maximum round-count
  constant for the step 4/5 loop, sourced from one place shared by both frontend and backend)

## Frontend

`../frontend/` is a Vite+React SPA, see its [README](../frontend/README.md). Every step has its own
independent route (`/runs/:runId/step1` through `.../step6`), refreshable/shareable/reviewable from the
history list, not dependent on in-memory React state; the streaming endpoints drive a real-time display
of the model's thinking process and the generation of its structured output (including retrieval tool
calls). The step 5 page additionally groups the transcript display by "round N · step 4 or step 5,"
since a single `/api/step5/stream` call may genuinely run several rounds internally, see
`Step5RunPage.tsx`. The step 6 page (`Step6RunPage.tsx`) doesn't show thinking/tool_call bubbles — the
report body itself is the display content, with `text_delta` increments fed directly into the
`ReportView` component for real-time rendering, readable as it's generated; `ReportView`
(`components/ReportView.tsx`) additionally attaches `remark-gfm` (to render the appendix's candidate
comparison table, since plain commonmark by default doesn't recognize pipe-table syntax) and a custom
mermaid code-block renderer (`components/MermaidDiagram.tsx`, rendering the theory-relationship
diagram's Mermaid source into SVG in real time, gracefully degrading to raw text when the syntax is
still incomplete mid-stream, without crashing); a one-click export button at the bottom of the page
packages the current full report text into a downloadable `.md` file.

## D.4 retrieval infrastructure: UTD24-journal Scopus retrieval

**Architecture: an MCP tool + a reusable skill, loaded directly by whichever step's agent needs
retrieval, without going through a separate "retrieval agent" as a middleman** (an early version built
a standalone `retrieval_agent.py`, wrapping retrieval as an independent agent for other steps to
"call" — this violated the "each step is one independent agent run" principle and has been scrapped and
redone, see the top-of-file docstring in `atba/mcp_server.py`). Split into two layers:

- **[`atba/mcp_server.py`](mcp_server.py)** — wraps Scopus retrieval into two standard MCP tools:
  `search_scopus` (automatically adds the UTD24 journal scope restriction, calls the real Scopus API,
  returns a paper list without abstracts — an inherent limitation of the Scopus Search API) +
  `get_paper_abstract` (looks up a single paper's full abstract by DOI, going through the two open,
  key-free sources Semantic Scholar/OpenAlex rather than Scopus's own Abstract Retrieval API — this
  project's `SCOPUS_API_KEY` has no abstract-access entitlement for that endpoint, confirmed by testing,
  see the `get_abstract_via_scopus_raw()` docstring in `atba/retrieval.py`). Can run as an independent
  process (`python -m atba.mcp_server`, stdio transport), accessible to any MCP client, not exclusive to
  ATBA. `build_retrieval_toolset()` is for the host agent to drop directly into its own
  `Agent(toolsets=[...])` — step 3 and step 5 attach it this way (step 4 used to attach it as well, but
  no longer needs to once construct-novelty checking was moved out of step 4, see the "Current scope and
  known gaps" section above), without each reimplementing it from scratch.
- **[`atba/prompts/retrieval_skill.{zh,en}.md`](prompts/retrieval_skill.zh.md)** — the strategy
  knowledge for "how to use these two tools well": Scopus query syntax, the three-tier degrading
  retrieval protocol from appendix B, the rewrite-and-retry rules (including the specific rule "don't
  stack too many ANDs," added after actually hitting that pitfall in testing), when to look up an
  abstract, a self-check list to run after every retrieval, and auditing requirements. Step 3's
  `step3_system_prompt()` (see [`prompts.py`](prompts.py)) splices this skill into its own task
  instructions when loading, so the retrieval happens inside step 3's own agent run — step 3's agent can
  call `search_scopus` for multiple candidate directions and multiple degradation tiers per direction,
  all within **one** `run()`. Step 5's relabeling-suspicion verification reuses this same skill text
  (see `step5_system_prompt()`).

The UTD24 journal list and its mapping to exact Scopus source-title strings are in
[`atba/data/utd24_journals.py`](data/utd24_journals.py) (drawing on the same validated mapping and
Scopus API pagination/rate-limiting/error-handling experience from another, earlier project).

**Verification status**: MCP tool integration, step 3's agent autonomously calling the retrieval tool
multiple times within a single run, the three-tier degrade + rewrite-retry strategy, and honest
reporting when the retrieval infrastructure itself fails (never fabricating a conclusion, never
conflating it with "exhausted all three tiers with no hit") have all been tested with real multi-
direction candidate scenarios using a DeepSeek key (see `atba/step3.py`). The one thing not yet tested
is the leg that actually hits the Scopus server and retrieves real papers, which depends on a valid
`SCOPUS_API_KEY` being configured (see `.env.example` — a key obtained through a personal account
usually won't work; Scopus generally requires an institutional subscription).

## Not yet implemented / known gaps

All six steps are implemented and have been run through a real end-to-end pipeline with DeepSeek (steps
1 through 6 running in sequence, including step 6 actually generating a report, rendering the Mermaid
diagram, and exporting a .md file). Still not done:

- **D.6 GUI polish**: the current frontend satisfies the basic requirement of "the entire audit trail
  can be viewed," but visual/interaction-level refinement (like the candidate×four-virtue matrix table
  or the pending-human-review queue mentioned in D.6 of 02_技术附录初稿.md) hasn't started.
- **D.4 local-corpus semantic retrieval** (building an embedding index over `实证案例库/`) isn't
  implemented yet; there's currently only the one channel of real-time Scopus retrieval.
- The code for step 5's loop path — "interrogation finds a core-mechanism flaw → sent back to step 4
  for revision → re-interrogated" — is implemented and has run through real calls, but every tested
  case's interrogation verdict has been `weak` (never triggering a loop-back); the complete loop-back-
  revise-reinterrogate chain triggered by `fails` hasn't yet been verified against a real case.
- Step 6's output quality (whether it genuinely meets "top-journal standard") currently only has a
  qualitative walkthrough, with no accompanying quantitative metric or peer-review design — this is a
  limitation already noted in the step-6 section of §A of 02_技术附录初稿.md itself, not a new gap
  introduced by this implementation.
