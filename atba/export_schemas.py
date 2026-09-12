"""Exports each step's pydantic output model in atba/schemas.py into an
atba/schemas/<step>.schema.json file.

Background: after switching to pydantic-ai, the tool schema actually fed to the model is generated
automatically at runtime from the Pydantic model via Agent(output_type=...), so there's no longer a
need to hand-maintain a separate .schema.json to pass to the SDK. But the earlier requirement was
"define one json_schema per step" as an independently readable, checkable specification file — so this
is made a product **generated from the model**, rather than a hand-maintained second definition, to
avoid the two definitions drifting apart.

Usage:
    python -m atba.export_schemas
Rerun this every time a model in schemas.py changes, and schemas/*.schema.json will update accordingly.
"""

from __future__ import annotations

import json
from pathlib import Path

from .registry import SCHEMAS_DIR
from .schemas import Step1Output, Step2Output, Step3Output, Step4Output, Step5Output
from .step1 import STEP1_TOOL_NAME  # Single source of truth: kept consistent with the tool name the Agent actually uses, not hand-copied
from .step2 import STEP2_TOOL_NAME
from .step3 import STEP3_TOOL_NAME
from .step4 import STEP4_TOOL_NAME
from .step5 import STEP5_TOOL_NAME

# (filename without extension, tool name, tool description, pydantic model)
_EXPORTS = [
    (
        "step1",
        STEP1_TOOL_NAME,
        "Report the structured result of step 1's four independent judgments in one shot, four "
        "parallel fields: prior_expectation_identification (is there enough information to proceed) + "
        "causal_presupposition_check (checks the raw input text) + theory_jargon_check (checks the "
        "phenomenon_deconstruction field) + phenomenon_deconstruction. The phenomenon_deconstruction "
        "field is isomorphic with the \"phenomenon_deconstruction\" sub-schema described in the "
        "technical appendix's appendix C' retrodiction-extraction schema (same English field names, "
        "though the value content is still the original text extracted from the paper).",
        Step1Output,
    ),
    (
        "step2",
        STEP2_TOOL_NAME,
        "Report the list of candidate theoretical directions matched in step 2 "
        "(candidate_theory_directions, each with theory_name and relevance_rationale), used to scope "
        "step 3's retrieval; does not judge whether a gap exists, does not require already-traceable "
        "literature.",
        Step2Output,
    ),
    (
        "step3",
        STEP3_TOOL_NAME,
        "Report step 3's final result: every candidate theoretical direction examined "
        "(examined_directions, including ones judged to 'not constitute a puzzle' and skipped), the "
        "two-tier structure of producing a research question — tier 1 is research_approach "
        "(gap_spotting or problematization, or empty if no direction constitutes a puzzle), tier 2 "
        "depends on tier 1 (under gap_spotting it's gap_type=theory_void/mechanism_gap, and "
        "mechanism_gap has a further tier 3, mechanism_gap_characterization=uncharted/"
        "anomalous_reversal; under problematization it's problematization_detail.assumption_type, per "
        "Alvesson & Sandberg 2011's methodology) — the research question itself, a coverage report, "
        "the rationale, and (if any) a cross-source tension note. Retrieval itself is done directly by "
        "step 3's agent calling the search_scopus tool exposed by atba/mcp_server.py; the retrieval "
        "strategy is in atba/prompts/retrieval_skill.md, and the gap-spotting/problematization "
        "judgment method is in atba/prompts/problematization_skill.md (both spliced into step 3's "
        "system prompt, see step3_system_prompt() in atba/prompts.py).",
        Step3Output,
    ),
    (
        "step4",
        STEP4_TOOL_NAME,
        "Report step 4's final result: the deep-retrieval result on the anchor theoretical direction "
        "run before candidate generation (theoretical_grounding, including key literature, known "
        "boundary conditions, internal tensions), 3-5 mutually exclusive candidate theories "
        "(candidates, each with the five theory elements theory_elements and four-virtue scores "
        "virtue_scores), the final ranking computed by propagating the four-virtue scores "
        "(ranked_candidate_names), the selected candidate (selected_candidate_name, with any tied "
        "candidates whose ranking is ambiguous listed together in tied_candidate_names for step 5 to "
        "adjudicate), and the selection rationale. Scope has been narrowed at the user's request: no "
        "construct-novelty check, no Lakatos hard-core/protective-belt judgment; but retrieval itself "
        "has been wired back to D.4's retrieval tool for a different purpose (working out the "
        "theory's current state before candidate generation, rather than checking after candidate "
        "generation whether the candidate already exists — see the module-level comments on "
        "TheoreticalGroundingRecord/CandidateTheory in atba/schemas.py) — whether a candidate overlaps "
        "with existing literature is still left to step 5's relabeling_suspicion follow-up to handle.",
        Step4Output,
    ),
    (
        "step5",
        STEP5_TOOL_NAME,
        "Report step 5's final result: the interrogation record across the three follow-up types — "
        "falsifiability/boundary conditions/relabeling suspicion — against the candidate theory under "
        "interrogation (exchanges), an honestly-listed record of unresolved weaknesses "
        "(unanswered_weaknesses), the overall verdict (overall_verdict: withstands/weak/fails), and, "
        "when the verdict is fails, the specific revision instruction sent back to step 4 "
        "(loop_back_instruction). Step 5's agent is **deliberately not told** how the candidate theory "
        "was generated/scored/selected by step 4 — it's given only the candidate theory's own "
        "object-level content, see atba/step5.py's _task_text and the module-level comment on the "
        "\"Step 5\" section in atba/schemas.py. The relabeling-suspicion question's independent "
        "retrieval verification likewise calls the search_scopus/get_paper_abstract tools; the "
        "retrieval strategy is in atba/prompts/retrieval_skill.md.",
        Step5Output,
    ),
]


def export_all() -> None:
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    for stem, tool_name, description, model in _EXPORTS:
        tool = {
            "name": tool_name,
            "description": description,
            "input_schema": model.model_json_schema(),
        }
        path = SCHEMAS_DIR / f"{stem}.schema.json"
        path.write_text(json.dumps(tool, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {path}")


if __name__ == "__main__":
    export_all()
