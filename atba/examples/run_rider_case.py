"""Runs step 1 once on the technical appendix's §C delivery-rider case, to check whether the output is
close to the manual walkthrough record.

Requires ANTHROPIC_API_KEY to be set before running. Usage:
    python -m atba.examples.run_rider_case
"""

from __future__ import annotations

import json

from atba.step1 import run_step1

RIDER_PHENOMENON = (
    "某电商平台的算法调度系统让骑手长期存在“表演式忙碌”——"
    "明明有空却假装在处理订单，以避免被系统降低派单优先级。"
)

# Corresponds to the manual judgment for the rider case's step 1 "pre-check" in the technical appendix:
# it hits a prior-literature match — the algorithmic-management literature (e.g. Kellogg, Valentine &
# Christin's 2020 review). This is no longer a precondition that must be confirmed first; it's just
# passed to the agent as a hint, lowering the odds it judges NEEDS_CLARIFICATION.
PRIOR_EXPECTATION_HINT = "算法管理文献综述，如 Kellogg, Valentine & Christin (2020)"


def main() -> None:
    result = run_step1(
        raw_text=RIDER_PHENOMENON,
        prior_expectation_hint=PRIOR_EXPECTATION_HINT,
        # The phenomenon text and hint above are in Chinese (kept as originally written to match the
        # technical appendix's worked example) — lang="zh" here so the model's output language matches
        # its input, rather than mixing Chinese input with the "en" default.
        lang="zh",
    )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(f"\nResult persisted: runs/{result.run_id}/step1.json")


if __name__ == "__main__":
    main()
