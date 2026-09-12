"""Command-line entry point: run one step at a time, without needing to start the backend/frontend.

Usage examples (PowerShell; a key placed in atba/.env is read automatically, no need to $env:... it
every time):
    python -m atba.cli step1 --text "..."
    python -m atba.cli step1 --text "..." --prior-hint "Kellogg, Valentine & Christin 2020 review"
    python -m atba.cli step2 --run-id <the run_id from step 1>
    python -m atba.cli step3 --run-id <the run_id from step 2, with a theoretical direction already selected>
    python -m atba.cli step4 --run-id <the run_id from step 3, with a research question already produced>
    python -m atba.cli step5 --run-id <the run_id from step 4, with a candidate theory already selected>
    python -m atba.cli step6 --run-id <the run_id from step 5, status=passed>

Step 1: the agent judges for itself whether the input information is sufficient; if not, the returned
status is needs_clarification, and prior_expectation.clarifying_question/candidate_options in the
output is what you need to supply — rerun with the same --run-id plus --prior-hint carrying your
answer, no need to re-enter the phenomenon description.

Step 2: no independent phenomenon-text input, accepts only --run-id — must be a run that has already
completed step 1 with status=passed; step 2 automatically reads that run's persisted phenomenon card as
input.

Step 3: likewise accepts only --run-id — must be a run that has completed step 2, with the user having
already selected at least one candidate theoretical direction via
/api/runs/{run_id}/step2/selection (or confirmed via checkboxes in the frontend); step 3 automatically
reads the phenomenon card + selected direction(s), autonomously retrieves Scopus literature, judges
per the three-tier degrading protocol, and produces a research question (or an escalate-to-human state
if no direction can constitute a puzzle).

Step 4: accepts only --run-id — must be a run that has completed step 3 with a non-empty
research_question; automatically reads the phenomenon card + research question + all literature step 3
retrieved, and produces 3-5 mutually exclusive candidate theories (each with the five theory elements,
four-virtue scores — no novelty check/Lakatos judgment, both already removed from step 4's scope per
the module-level comment on CandidateTheory in atba/schemas.py) and selects the best candidate. This
command runs only one round (round_number=1) — it doesn't cover the revision round triggered by step
5, which is called automatically from inside step 5's loop, not through this subcommand.

Step 5: accepts only --run-id — must be a run that has completed step 4; uses an independent sub-agent
(which never sees step 4's generation process, only the candidate theory itself) to run an adversarial
interrogation. **This subcommand runs the complete step-4/5 automatic loop** (see
atba/abductive_loop.py): when the interrogation judges a core-mechanism flaw, it automatically sends
things back to step 4 for revision and interrogates again within this same call, looping up to a few
rounds until it passes or is escalated to human review — one call is the loop's terminal state, not a
single round of interrogation.

Step 6: accepts only --run-id — must be a run that has completed step 5 with status=passed; integrates
steps 1 through 5's output into a theoretical contribution report. **The output is not JSON, it's the
full text of a markdown report** (what's printed to stdout is the report itself, not a pretty-printed
JSON structure) — report structure: a condensed introduction / theory and hypotheses (theoretical
foundations + a theory relationship diagram + research hypotheses) / theoretical contribution
(honestly folding in weaknesses step 5's interrogation found) / references, plus an appendix with a
candidate comparison table and a reasoning-trail summary.

**Subcommand structure**: changed from a single entry point (no subcommand needed when only step 1
existed) to `python -m atba.cli <step> ...`; now that all six steps are implemented, this convention
doesn't need to expand further — any future new step should just add a subcommand following the same
pattern.
"""

from __future__ import annotations

import argparse
import json
import sys

from .abductive_loop import run_step4_5_loop
from .llm import SUPPORTED_PROVIDERS
from .step1 import run_step1
from .step2 import run_step2
from .step3 import run_step3
from .step4 import run_step4
from .step6 import run_step6


def _add_common_llm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--lang",
        choices=["zh", "en"],
        default="en",
        help="system prompt语言，默认en（不影响输出字段名，字段名固定为英文key）",
    )
    parser.add_argument(
        "--provider",
        choices=list(SUPPORTED_PROVIDERS),
        default="anthropic",
        help="LLM厂商，默认anthropic；也可用环境变量 ATBA_LLM_PROVIDER 覆盖此默认值",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="覆盖所选provider的默认模型名（不传则用该provider的默认模型）",
    )


def _run_step1(args: argparse.Namespace) -> int:
    result = run_step1(
        raw_text=args.text,
        prior_expectation_hint=args.prior_hint,
        max_jargon_retries=args.max_jargon_retries,
        lang=args.lang,
        provider=args.provider,
        model=args.model,
        run_id=args.run_id,
    )

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(f"\nResult persisted: runs/{result.run_id}/step1.json", file=sys.stderr)
    if result.status.value == "needs_clarification":
        print(
            f"\nMore information needed: {result.prior_expectation.clarifying_question}\n"
            f"Candidate options: {result.prior_expectation.candidate_options}\n"
            f'After answering, rerun: python -m atba.cli step1 --text "..." --run-id {result.run_id} '
            f'--prior-hint "your answer"',
            file=sys.stderr,
        )
    return 0 if result.is_ok() else 1


def _run_step2(args: argparse.Namespace) -> int:
    try:
        result = run_step2(run_id=args.run_id, provider=args.provider, model=args.model, lang=args.lang)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Step 2 could not start: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(f"\nResult persisted: runs/{result.run_id}/step2.json", file=sys.stderr)
    return 0 if result.is_ok() else 1


def _run_step3(args: argparse.Namespace) -> int:
    try:
        result = run_step3(run_id=args.run_id, provider=args.provider, model=args.model, lang=args.lang)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Step 3 could not start: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(f"\nResult persisted: runs/{result.run_id}/step3.json", file=sys.stderr)
    return 0 if result.is_ok() else 1


def _run_step4(args: argparse.Namespace) -> int:
    try:
        result = run_step4(run_id=args.run_id, provider=args.provider, model=args.model, lang=args.lang)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Step 4 could not start: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(f"\nResult persisted: runs/{result.run_id}/step4.json", file=sys.stderr)
    return 0 if result.is_ok() else 1


def _run_step5(args: argparse.Namespace) -> int:
    """Runs the complete step-4/5 automatic loop (see atba/abductive_loop.py), not a single round of
    interrogation — same reasoning as the /api/step5 endpoint's docstring."""
    try:
        result = run_step4_5_loop(run_id=args.run_id, provider=args.provider, model=args.model, lang=args.lang)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Step 5 could not start: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(f"\nResult persisted: runs/{result.run_id}/step5.json", file=sys.stderr)
    return 0 if result.is_ok() else 1


def _run_step6(args: argparse.Namespace) -> int:
    """Unlike the other subcommands: what's printed to stdout here is the report_markdown field itself
    (the full report text), not a pretty-printed JSON dump of the whole Step6Result — a report is meant
    to be read by a person and shouldn't be wrapped in JSON escaping/indentation. To see the full
    persisted structure (including the audit trail), read runs/<run_id>/step6.json directly."""
    try:
        result = run_step6(run_id=args.run_id, provider=args.provider, model=args.model, lang=args.lang)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Step 6 could not start: {exc}", file=sys.stderr)
        return 1

    if result.is_ok():
        print(result.report_markdown)
    else:
        print(f"Step 6 did not pass (status={result.status.value}): {result.note}", file=sys.stderr)
    print(f"\nResult persisted: runs/{result.run_id}/step6.json", file=sys.stderr)
    return 0 if result.is_ok() else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="ATBA CLI: run one step at a time via a subcommand")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("step1", help="Run step 1: phenomenon input + pre-check")
    p1.add_argument("--text", required=True, help="The raw phenomenon description text")
    p1.add_argument(
        "--prior-hint",
        default=None,
        help=(
            "Optional, a prior expectation/theoretical tradition hint (e.g. a specific paper, a theory "
            "name) — not a precondition that must be confirmed first, just something to help the agent "
            "judge and lower the odds of a NEEDS_CLARIFICATION follow-up; also used when answering a "
            "follow-up question"
        ),
    )
    p1.add_argument("--max-jargon-retries", type=int, default=2)
    p1.add_argument(
        "--run-id",
        default=None,
        help="Reuse an existing run directory (e.g. resubmitting after answering a NEEDS_CLARIFICATION follow-up, or rerunning with a different provider); a new one is created if omitted",
    )
    _add_common_llm_args(p1)
    p1.set_defaults(func=_run_step1)

    p2 = sub.add_parser("step2", help="Run step 2: theory matching (requires a run-id that has completed step 1)")
    p2.add_argument("--run-id", required=True, help="A run that has completed step 1 (status=passed)")
    _add_common_llm_args(p2)
    p2.set_defaults(func=_run_step2)

    p3 = sub.add_parser(
        "step3",
        help="Run step 3: literature retrieval, produce a research question (requires a run-id that has completed step 2 with at least one candidate theoretical direction selected)",
    )
    p3.add_argument("--run-id", required=True, help="A run that has completed step 2 with selected_theory_directions non-empty")
    _add_common_llm_args(p3)
    p3.set_defaults(func=_run_step3)

    p4 = sub.add_parser(
        "step4",
        help="Run step 4: abductive reasoning, construct new theory (requires a run-id that has completed step 3 with research_question non-empty)",
    )
    p4.add_argument("--run-id", required=True, help="A run that has completed step 3 with research_question non-empty")
    _add_common_llm_args(p4)
    p4.set_defaults(func=_run_step4)

    p5 = sub.add_parser(
        "step5",
        help="Run step 5: adversarial interrogation (requires a run-id that has completed step 4) — runs the complete step-4/5 automatic loop, not a single round of interrogation",
    )
    p5.add_argument("--run-id", required=True, help="A run that has completed step 4 (status=passed)")
    _add_common_llm_args(p5)
    p5.set_defaults(func=_run_step5)

    p6 = sub.add_parser(
        "step6",
        help="Run step 6: produce the theoretical contribution report (requires a run-id that has completed step 5 with status=passed) — outputs the full markdown report text, not JSON",
    )
    p6.add_argument("--run-id", required=True, help="A run that has completed step 5 (status=passed)")
    _add_common_llm_args(p6)
    p6.set_defaults(func=_run_step6)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
