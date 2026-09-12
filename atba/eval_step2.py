"""Recall/precision evaluation of Step 2 (theory matching) against the retrodiction validation set.

Corresponds to the evaluation design settled on across several rounds of discussion: Step 2 is the
**only** one of the six steps that can be tested directly against ground truth —
`matched_theory_and_gap_ground_truth.prior_theoretical_direction` (the theoretical tradition a paper
actually takes a stance on) is an objective fact (how the paper itself writes its theoretical
background, not a matter-of-opinion judgment like "which lens should be used"); testing "does the list
of candidate directions Step 2 produced cover it" against this ground truth doesn't run into the
validity problem Step 4/Step 6 hit — "management theory has multiple legitimate lenses, there's no
single correct answer" (per the discussion with the user: ATBA's candidates can't be compared against a
paper's actual constructs for similarity, but Step 2's list of candidate directions can be compared
against the theoretical tradition a paper actually cites, for coverage).

**Two metrics, per DeCE's (Yu et al. 2025) precision/recall two-axis decomposition approach**:
- **Recall**: whether the ground-truth theoretical tradition is covered by the candidate directions
  Step 2 listed — measures "was what should have been found, found."
- **Precision**: of the candidate directions Step 2 listed, how many are genuinely relevant to the
  phenomenon rather than noise directions padded in just to inflate recall — measures "are the ones
  found actually meaningful, not a guess-by-listing-many-directions win."

**Both "is it covered" and "is it relevant" require an LLM-judge** (the ground truth is a piece of text
describing a theoretical tradition, not a theory name that can be string-matched directly) — this
script can't be fully automated to the point of not needing a model at all, but the judgment itself is
tiny (yes/no + one sentence of reasoning), far cheaper than running a real Step 1/Step 2.

**This script makes real LLM API calls** (Step 1 + Step 2 each run once, plus a handful of small
judgment calls per record); by default it **does not** run automatically — `--run-live` must be passed
explicitly, to avoid accidentally triggering it and burning real quota; see `main()`'s argument
descriptions.

Usage:
    python -m atba.eval_step2 --run-live [--provider anthropic] [--limit 3]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from .context_store import new_run_id
from .llm import DEFAULT_MODELS, build_model
from .step1 import run_step1
from .step2 import run_step2

RETRODICTION_SET_PATH = Path("提案初稿/回溯验证测试集.json")


class _RelevanceJudgment(BaseModel):
    """A minimal schema for a one-shot judgment — just a boolean + one sentence of reasoning, no need
    for the elaborate structure of the six-step agent."""

    yes: bool
    rationale: str = Field(description="One sentence explaining the basis for the judgment")


def _build_judge_agent(provider: str, model_name: Optional[str]) -> Agent[None, _RelevanceJudgment]:
    model = build_model(provider, model_name)
    return Agent(
        model=model,
        output_type=_RelevanceJudgment,
        system_prompt=(
            "You are a management-research methodology expert who only answers yes/no judgment "
            "questions, nothing else. Given two descriptions of a theoretical direction, judge whether "
            "they point to the same (or highly overlapping) theoretical tradition/family — an exact "
            "verbatim match isn't required, only that they're substantively discussing the same "
            "theoretical logic. Answer yes/no with one sentence of reasoning."
        ),
        retries=2,
        name="atba_eval_relevance_judge",
    )


async def _judge_covers(agent: Agent[None, _RelevanceJudgment], candidate_desc: str, ground_truth: str) -> bool:
    prompt = f"Candidate theoretical direction description:\n{candidate_desc}\n\nThe paper's actual theoretical tradition (ground truth):\n{ground_truth}\n\nDo these two point to the same/a highly overlapping theoretical tradition?"
    result = await agent.run(prompt)
    return result.output.yes


async def _judge_relevant(agent: Agent[None, _RelevanceJudgment], candidate_desc: str, phenomenon_text: str) -> bool:
    prompt = (
        f"Phenomenon description:\n{phenomenon_text}\n\nCandidate theoretical direction:\n{candidate_desc}\n\n"
        "Is this theoretical direction genuinely relevant to some specific aspect of this phenomenon (not just vaguely 'management theory is somewhat related')?"
    )
    result = await agent.run(prompt)
    return result.output.yes


@dataclass
class RecordEvalResult:
    record_id: str
    run_id: str
    recall_hit: bool
    recall_hit_at_rank: Optional[int]  # Which position (1-indexed) in the candidate list the hit was at; None means no hit
    n_candidates: int
    n_relevant: int
    error: Optional[str] = None

    @property
    def precision(self) -> Optional[float]:
        return None if self.n_candidates == 0 else self.n_relevant / self.n_candidates


@dataclass
class EvalReport:
    results: list[RecordEvalResult] = field(default_factory=list)

    @property
    def recall_at_k(self) -> float:
        scored = [r for r in self.results if r.error is None]
        return 0.0 if not scored else sum(1 for r in scored if r.recall_hit) / len(scored)

    @property
    def mean_precision(self) -> Optional[float]:
        precisions = [r.precision for r in self.results if r.error is None and r.precision is not None]
        return None if not precisions else sum(precisions) / len(precisions)


def _load_retrodiction_records(limit: Optional[int] = None) -> list[dict]:
    if not RETRODICTION_SET_PATH.exists():
        raise FileNotFoundError(
            f"Could not find the retrodiction validation set: {RETRODICTION_SET_PATH} — this script "
            "must be run from the project root (python -m atba.eval_step2), not directly from the "
            "atba/ subdirectory."
        )
    data = json.loads(RETRODICTION_SET_PATH.read_text(encoding="utf-8"))
    records = data["records"]
    return records[:limit] if limit else records


async def evaluate_record(
    record: dict, provider: str, model: Optional[str], judge_provider: str, judge_model: Optional[str], lang: str
) -> RecordEvalResult:
    record_id = record["record_id"]
    phenomenon_text = record["phenomenon_input_text"]
    ground_truth = record.get("matched_theory_and_gap_ground_truth", {}).get("prior_theoretical_direction")
    if not ground_truth:
        return RecordEvalResult(record_id, "", False, None, 0, 0, error="Record has no prior_theoretical_direction ground truth, skipped")

    run_id = new_run_id()
    try:
        step1 = run_step1(phenomenon_text, provider=provider, model=model, lang=lang, run_id=run_id)
        if not step1.is_ok() or step1.deconstruction is None:
            return RecordEvalResult(record_id, run_id, False, None, 0, 0, error=f"Step 1 did not pass: {step1.status.value}")
        step2 = run_step2(run_id, provider=provider, model=model, lang=lang)
        if not step2.is_ok():
            return RecordEvalResult(record_id, run_id, False, None, 0, 0, error=f"Step 2 did not pass: {step2.status.value}")
    except Exception as exc:  # noqa: BLE001 —— an evaluation script; one record failing shouldn't abort the whole batch
        return RecordEvalResult(record_id, run_id, False, None, 0, 0, error=f"Agent call failed: {exc}")

    judge = _build_judge_agent(judge_provider, judge_model)
    candidates = step2.candidate_theory_directions
    hit_rank: Optional[int] = None
    n_relevant = 0
    for i, c in enumerate(candidates, 1):
        desc = f"{c.theory_name} — {c.relevance_rationale}"
        if hit_rank is None and await _judge_covers(judge, desc, ground_truth):
            hit_rank = i
        if await _judge_relevant(judge, desc, phenomenon_text):
            n_relevant += 1

    return RecordEvalResult(
        record_id=record_id,
        run_id=run_id,
        recall_hit=hit_rank is not None,
        recall_hit_at_rank=hit_rank,
        n_candidates=len(candidates),
        n_relevant=n_relevant,
    )


async def run_eval(
    provider: str, model: Optional[str], judge_provider: str, judge_model: Optional[str], lang: str, limit: Optional[int]
) -> EvalReport:
    records = _load_retrodiction_records(limit)
    report = EvalReport()
    for record in records:
        # Deliberately sequential (not asyncio.gather) — these are real calls to real APIs, and running
        # multiple records concurrently easily hits rate limits; this evaluation script isn't
        # optimizing for speed.
        result = await evaluate_record(record, provider, model, judge_provider, judge_model, lang)
        report.results.append(result)
        _print_record_result(result)
    return report


def _print_record_result(r: RecordEvalResult) -> None:
    if r.error:
        print(f"[{r.record_id}] Error: {r.error}")
        return
    hit_desc = f"hit, ranked #{r.recall_hit_at_rank}" if r.recall_hit else "no hit"
    precision_desc = "(no candidates)" if r.precision is None else f"{r.precision:.0%}"
    print(f"[{r.record_id}] recall={hit_desc}; {r.n_candidates} candidate(s), {r.n_relevant} relevant, precision={precision_desc}")


def _print_summary(report: EvalReport) -> None:
    scored = [r for r in report.results if r.error is None]
    print("\n=== Summary ===")
    print(f"Valid evaluated records: {len(scored)}/{len(report.results)}")
    print(f"Recall (recall@k): {report.recall_at_k:.0%}")
    mp = report.mean_precision
    print(f"Mean precision: {'(no data)' if mp is None else f'{mp:.0%}'}")
    if len(scored) < 10:
        print(
            "**Sample-size caveat**: the retrodiction validation set currently has very few records, "
            "so this percentage has limited statistical meaning — first get the evaluation pipeline "
            "working end to end; this number is only worth citing as a conclusion once the dataset is "
            "expanded (see the _extraction_depth_caveat note in 提案初稿/回溯验证测试集.json)."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True, help="Must be passed explicitly to make real API calls — without this flag the script errors out immediately, to avoid accidentally burning quota")
    parser.add_argument("--provider", default=DEFAULT_MODELS and "anthropic")
    parser.add_argument("--model", default=None)
    parser.add_argument("--judge-provider", default=None, help="The provider used for judgment calls, defaults to the same as --provider")
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N records, for debugging")
    args = parser.parse_args()

    judge_provider = args.judge_provider or args.provider
    report = asyncio.run(run_eval(args.provider, args.model, judge_provider, args.judge_model, args.lang, args.limit))
    _print_summary(report)


if __name__ == "__main__":
    main()
