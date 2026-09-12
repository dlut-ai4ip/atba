"""Each stage's structured output is persisted to runs/<run_id>/<stage>.json, becoming the input source
for the next sub-agent — this is the direct filesystem-level realization of the design goal
"reproducible, auditable reasoning trail," and also a necessary mechanism under a frontend/backend-
split architecture: a single six-step run spans multiple HTTP requests (especially after an
"escalate to human" pause, which may resume much later) — later steps can't depend on in-memory objects
still sitting in the previous step's caller process, they can only read from persisted artifacts.

A complete six-step run for one phenomenon is called a "run," identified by a run_id (a uuid4 hex
string), corresponding to a directory runs/<run_id>/ holding one JSON snapshot per stage name:
    runs/<run_id>/step1.json
    runs/<run_id>/step2.json
    ...
    runs/<run_id>/manifest.json  — records the run's creation/update time and which stages have
    completed, for the GUI/CLI to query progress

The storage location can be overridden with the ATBA_RUNS_DIR environment variable, defaulting to
runs/ under the repo root (not committed to version control).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def runs_root() -> Path:
    # Uses `or` rather than dict.get's default-value parameter: `ATBA_RUNS_DIR=` (an empty string) in
    # .env also makes this key "exist in the environment variables," so .get(..., "runs") would return
    # the empty string, not the default — an empty string resolves as a path to the current directory,
    # scattering artifacts across the repo root. This was a real pitfall once, see the comment in
    # .env.example.
    return Path(os.environ.get("ATBA_RUNS_DIR") or "runs")


def new_run_id() -> str:
    return uuid.uuid4().hex


def run_dir(run_id: str) -> Path:
    d = runs_root() / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_stage_output(run_id: str, stage: str, data: BaseModel) -> Path:
    """Writes a step's structured result to runs/<run_id>/<stage>.json, and updates that run's
    manifest."""
    path = run_dir(run_id) / f"{stage}.json"
    path.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    _touch_manifest(run_id, stage)
    return path


def load_stage_output(run_id: str, stage: str, model_cls: type[T]) -> T:
    """For the next stage's sub-agent to read the previous step's output as input context."""
    path = run_dir(run_id) / f"{stage}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Could not find {stage}'s output file: {path}. Please complete that step first, or check that run_id is correct."
        )
    return model_cls.model_validate_json(path.read_text(encoding="utf-8"))


def load_manifest(run_id: str) -> dict:
    path = run_dir(run_id) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Could not find run {run_id}'s manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_runs() -> list[dict]:
    """Lists the manifests of every run under runs/, sorted by update time descending — for the
    frontend's "run history" list page to query, so each run can carry a preview of its phenomenon text
    alongside the run_id itself, without having to click into each one to see which phenomenon it was.

    phenomenon_preview/status are only attached when step1.json exists, and both are "nice to have"
    information: if the manifest itself doesn't have them, they're just skipped, so a corrupted/missing
    artifact in one run doesn't take down the whole list page.
    """
    root = runs_root()
    if not root.exists():
        return []

    out: list[dict] = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        manifest_path = d / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        step1_path = d / "step1.json"
        if step1_path.exists():
            try:
                step1 = json.loads(step1_path.read_text(encoding="utf-8"))
                manifest["phenomenon_preview"] = (step1.get("raw_text") or "")[:80]
                manifest["status"] = step1.get("status")
            except (json.JSONDecodeError, OSError):
                pass
        out.append(manifest)

    out.sort(key=lambda m: m.get("updated_at", ""), reverse=True)
    return out


def _touch_manifest(run_id: str, stage: str) -> None:
    path = run_dir(run_id) / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    now = datetime.now(timezone.utc).isoformat()
    manifest.setdefault("run_id", run_id)
    manifest.setdefault("created_at", now)
    manifest["updated_at"] = now
    manifest["last_stage"] = stage
    completed = manifest.setdefault("completed_stages", [])
    if stage not in completed:
        completed.append(stage)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
