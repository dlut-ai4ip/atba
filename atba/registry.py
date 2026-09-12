"""Loading utility for prompts and json_schemas.

Per the project convention, prompt text and structured-output json_schemas are never hardcoded in
Python — each is its own file:
- atba/prompts/<name>.<lang>.md   — a step's sub-mechanism's system prompt (plain text; retry-style
  templates may contain {placeholders}), each prompt has both a Chinese and an English version,
  lang is "zh" or "en", defaulting to "en".
- atba/schemas/<name>.schema.json — a step's sub-mechanism's extraction schema, with no separate
  version per language (the tool's parameter field names are English keys, a fixed data contract that
  doesn't change with the system-prompt language).
  The format is a complete Anthropic tool-use tool definition {name, description, input_schema}, where
  input_schema is a standard JSON Schema that can be passed directly to
  client.messages.create(tools=[...]).

Naming convention: <step>_<mechanism>, e.g. step1_causal_check, step1_deconstruction — steps 2 through
6 just add files following the same convention, no need to change this loader.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).parent
PROMPTS_DIR = _PACKAGE_ROOT / "prompts"
SCHEMAS_DIR = _PACKAGE_ROOT / "schemas"

SUPPORTED_LANGS = ("zh", "en")


@lru_cache(maxsize=None)
def load_prompt(name: str, lang: str = "en") -> str:
    """Reads the raw text of atba/prompts/<name>.<lang>.md (with leading/trailing blank lines stripped)."""
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"Unsupported language {lang!r}, currently supported: {SUPPORTED_LANGS}")
    path = PROMPTS_DIR / f"{name}.{lang}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip() + "\n"


@lru_cache(maxsize=None)
def load_tool_schema(name: str) -> dict:
    """Reads atba/schemas/<name>.schema.json and returns a dict usable directly as an Anthropic tool
    definition."""
    path = SCHEMAS_DIR / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"json_schema file not found: {path}")
    with path.open(encoding="utf-8") as f:
        tool = json.load(f)
    for key in ("name", "description", "input_schema"):
        if key not in tool:
            raise ValueError(f"{path} is missing the required field {key!r}, not a valid tool-schema file")
    return tool
