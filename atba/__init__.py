"""The ATBA (Abductive Theory-Building Agent) implementation package.

All six steps of the pipeline are implemented (see the README for the full architecture); this file
only re-exports step 1 as a convenience shortcut for the earliest, most common entry point — the other
steps are imported directly from their own submodules (`from atba.step2 import run_step2`, etc., see
cli.py/api.py) rather than through this file's __all__.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load configuration from atba/.env (ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / ATBA_LLM_PROVIDER etc.,
# template in the same directory's atba/.env.example). Must run before the `.step1` import below —
# module-level defaults like DEFAULT_PROVIDER are evaluated at import time, and would miss the value if
# this ran later. override=False: values already set manually via $env:... in the shell take priority;
# .env only fills in what wasn't already set.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from .step1 import run_step1, Step1Status  # noqa: E402  (must come after load_dotenv)

__all__ = ["run_step1", "Step1Status"]
