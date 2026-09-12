"""Citation/evidence authenticity verification — a cross-cutting audit tool spanning steps 3/4/5, not
the output of any single step; it's a post-hoc check run after a run finishes.

**Why this is the one genuinely "objective" piece in the evaluation design**: the rounds of discussion
about "how to evaluate ATBA" kept running into the same limitation — "is this candidate theory any
good" has no objective check independent of LLM judgment; the quality assessment of steps 4/5/6
ultimately has to rely on an LLM-judge (whether absolute scoring or a pairwise tournament). But
`CitedEvidence` is different: the agent claims to have cited a paper that genuinely exists (title+doi),
and **whether that paper exists** is a fact that can be verified programmatically, with no LLM judgment
involved at all — look up the DOI against Semantic Scholar/OpenAlex (reusing
`atba/retrieval.py`'s `get_abstract_by_doi`, the same query path the `get_paper_abstract` tool uses, not
a separate piece of logic) — found means it genuinely exists, not found means it's suspicious (the DOI
may be mistyped, or it may genuinely be fabricated).

**Only verifies "does it exist," not "was it cited correctly"**: `get_abstract_by_doi` doesn't return
the paper's title, so there's no way to programmatically compare "the title the agent claimed" against
"the title the DOI actually corresponds to" (short of wiring up another source that returns titles,
not done this round); judgments like "does relevant_snippet take something out of context" still need
manual/LLM spot-checking, not something this script can do — this script draws the line between "can
be objectively checked" and "needs subjective judgment," it isn't meant to replace manual verification.

**Usage**:
    python -m atba.citation_audit <run_id>
Prints a summary report once done (total citations per stage, the count verified to exist, the count
not found, the count with no DOI to verify). Can also be called as a library function by other scripts
(e.g. the same batch of evaluation tools as atba/eval_step2.py), see `audit_run()`.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from enum import Enum

from .context_store import load_stage_output
from .retrieval import get_abstract_by_doi
from .schemas import CitedEvidence, Step3Result, Step4Result, Step5Result


class CitationVerdict(str, Enum):
    VERIFIED = "verified"  # Has a DOI, and at least one of Semantic Scholar/OpenAlex found it (source non-empty)
    NOT_FOUND = "not_found"  # Has a DOI, but neither source found it — suspicious, possibly a mistyped DOI or a fully fabricated citation
    NO_DOI = "no_doi"  # No DOI to check — doesn't mean the citation is fake, just that this script can't verify it and it needs manual review


@dataclass
class CitationRef:
    """One citation awaiting verification, along with where it was cited (which stage/which location)
    — the report needs to be able to point to a specific citation, not just a vague "found N suspicious
    citations."""

    stage: str  # "step3" / "step4" / "step5"
    location: str  # A human-readable location description, e.g. 'examined_directions[0] "ODT"'
    evidence: CitedEvidence


@dataclass
class CitationAuditResult:
    ref: CitationRef
    verdict: CitationVerdict
    note: str = ""


@dataclass
class AuditReport:
    results: list[CitationAuditResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def verified(self) -> int:
        return sum(1 for r in self.results if r.verdict == CitationVerdict.VERIFIED)

    @property
    def not_found(self) -> int:
        return sum(1 for r in self.results if r.verdict == CitationVerdict.NOT_FOUND)

    @property
    def no_doi(self) -> int:
        return sum(1 for r in self.results if r.verdict == CitationVerdict.NO_DOI)

    @property
    def checkable_hallucination_rate(self) -> float | None:
        """The fraction of not_found among the "has a DOI, genuinely checkable" subset — the
        denominator deliberately excludes no_doi (that subset isn't "verification passed," it's
        "couldn't be verified at all"; mixing it into the denominator would artificially deflate this
        rate, creating a false sense of safety). Returns None when there's no checkable sample, not 0
        (0 would be misread as "zero hallucination," when the real situation is "not tested")."""

        checkable = self.verified + self.not_found
        return None if checkable == 0 else self.not_found / checkable


def collect_cited_evidence(run_id: str) -> list[CitationRef]:
    """Collects every place in a run's steps 3/4/5 output that produces a structured `CitedEvidence` —
    newer retrieval-bearing fields (anchor_theory_grounding/mechanism_grounding/
    InterrogationRecord.cited_evidence) must all be covered, and can't be skipped just because they're
    newly added."""

    refs: list[CitationRef] = []

    try:
        step3 = load_stage_output(run_id, "step3", Step3Result)
    except FileNotFoundError:
        step3 = None
    if step3:
        for i, d in enumerate(step3.examined_directions):
            for e in d.cited_evidence:
                refs.append(CitationRef("step3", f'examined_directions[{i}] "{d.theory_name}"', e))
        if step3.anchor_theory_grounding:
            for e in step3.anchor_theory_grounding.key_findings:
                refs.append(CitationRef("step3", "anchor_theory_grounding.key_findings", e))
        if step3.problematization_detail:
            for e in step3.problematization_detail.assumption_evidence:
                refs.append(CitationRef("step3", "problematization_detail.assumption_evidence", e))

    try:
        step4 = load_stage_output(run_id, "step4", Step4Result)
    except FileNotFoundError:
        step4 = None
    if step4 and step4.mechanism_grounding:
        for e in step4.mechanism_grounding.donor_findings:
            refs.append(CitationRef("step4", "mechanism_grounding.donor_findings", e))

    try:
        step5 = load_stage_output(run_id, "step5", Step5Result)
    except FileNotFoundError:
        step5 = None
    if step5:
        for i, ex in enumerate(step5.exchanges):
            for e in ex.cited_evidence:
                refs.append(CitationRef("step5", f'exchanges[{i}] "{ex.question_type.value}"', e))

    return refs


async def _verify_one(ref: CitationRef) -> CitationAuditResult:
    e = ref.evidence
    if not e.doi:
        return CitationAuditResult(ref, CitationVerdict.NO_DOI, "No DOI — this citation's authenticity needs manual verification")
    result = await get_abstract_by_doi(e.doi)
    if result.source is not None:
        return CitationAuditResult(ref, CitationVerdict.VERIFIED, f"Verified to exist via {result.source}")
    return CitationAuditResult(
        ref,
        CitationVerdict.NOT_FOUND,
        "Neither Semantic Scholar nor OpenAlex could find this DOI — it may be mistyped, or the citation may be entirely fabricated; needs manual review",
    )


async def audit_run(run_id: str) -> AuditReport:
    """Verifies every citation in a run. Deliberately sequential (not concurrent via asyncio.gather) —
    both open sources have implicit rate limits, and concurrent lookups would raise the odds of getting
    rate-limited/timing out; this audit script isn't optimizing for speed, it's optimizing for reliable
    verification results."""

    refs = collect_cited_evidence(run_id)
    report = AuditReport()
    for ref in refs:
        report.results.append(await _verify_one(ref))
    return report


def _print_report(run_id: str, report: AuditReport) -> None:
    print(f"Citation authenticity audit report for run {run_id}")
    print(f"  Total citations: {report.total}")
    print(f"  Verified to exist: {report.verified}")
    print(f"  Not found (suspicious): {report.not_found}")
    print(f"  No DOI (unverifiable): {report.no_doi}")
    rate = report.checkable_hallucination_rate
    print(f"  Suspected hallucination rate among checkable citations: {'(no checkable samples)' if rate is None else f'{rate:.1%}'}")
    if report.not_found:
        print("\n  List of suspicious citations (DOI not found, needs manual review):")
        for r in report.results:
            if r.verdict == CitationVerdict.NOT_FOUND:
                print(f'    - [{r.ref.stage}] {r.ref.location}: "{r.ref.evidence.title}" doi={r.ref.evidence.doi}')


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m atba.citation_audit <run_id>", file=sys.stderr)
        raise SystemExit(1)
    run_id = sys.argv[1]
    report = asyncio.run(audit_run(run_id))
    _print_report(run_id, report)


if __name__ == "__main__":
    main()
