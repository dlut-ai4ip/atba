"""LLM provider wiring: turns a provider name ("anthropic" / "deepseek" / "openai") into a pydantic-ai
Model instance.

DeepSeek goes through an OpenAI-compatible protocol; pydantic-ai has a dedicated DeepSeekProvider for
this (internally still an OpenAI-compatible client, with the model class uniformly OpenAIChatModel).
Note that deepseek-reasoner doesn't support function calling/structured output, and every step in this
project requires forced tool calls, so deepseek-chat must be used under DeepSeek, never reasoner.

OpenAI is the native case OpenAIChatModel/OpenAIProvider were built for — no base_url override or
compatibility shim needed, unlike DeepSeek. Unlike DeepSeek's reasoner, OpenAI's own reasoning models
(the o-series, gpt-5) do support function calling, so there's no equivalent "don't use the reasoning
model" restriction here — see openai_reasoning_model_settings in atba/agent_streaming.py for how their
reasoning_effort tiers are wired in.
"""

from __future__ import annotations

import os

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider

DEFAULT_MODELS = {
    # Each provider's default model name, overridable via ATBA_ANTHROPIC_MODEL / ATBA_DEEPSEEK_MODEL /
    # ATBA_OPENAI_MODEL in atba/.env (template in atba/.env.example); a single call can still
    # temporarily override this via --model / the API request body's model field, which takes
    # precedence (see build_model's model_name parameter).
    "anthropic": os.environ.get("ATBA_ANTHROPIC_MODEL") or "claude-sonnet-5",
    "deepseek": os.environ.get("ATBA_DEEPSEEK_MODEL") or "deepseek-chat",
    "openai": os.environ.get("ATBA_OPENAI_MODEL") or "gpt-5",
}

SUPPORTED_PROVIDERS = tuple(DEFAULT_MODELS)


def build_model(provider: str, model_name: str | None = None) -> Model:
    provider = provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported LLM provider {provider!r}, currently supported: {SUPPORTED_PROVIDERS}")

    resolved_name = model_name or DEFAULT_MODELS[provider]

    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Environment variable ANTHROPIC_API_KEY not found. Set it before running, "
                'e.g. in PowerShell: $env:ANTHROPIC_API_KEY = "sk-ant-..."'
            )
        return AnthropicModel(resolved_name, provider=AnthropicProvider(api_key=api_key))

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Environment variable OPENAI_API_KEY not found. Set it before running, "
                'e.g. in PowerShell: $env:OPENAI_API_KEY = "sk-..."'
            )
        return OpenAIChatModel(resolved_name, provider=OpenAIProvider(api_key=api_key))

    # provider == "deepseek"
    if model_name is not None and model_name != "deepseek-chat":
        # Not blocked outright (in case DeepSeek opens up function calling for reasoner in the
        # future), but an explicit warning is given.
        import warnings

        warnings.warn(
            f"A non-default model {model_name!r} was specified under DeepSeek: every step in this "
            "project forces tool calls, and reasoning models like deepseek-reasoner currently don't "
            "support function calling — please confirm compatibility yourself if this isn't "
            "deepseek-chat.",
            stacklevel=2,
        )
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Environment variable DEEPSEEK_API_KEY not found. Set it before running, "
            'e.g. in PowerShell: $env:DEEPSEEK_API_KEY = "sk-..."'
        )
    return OpenAIChatModel(resolved_name, provider=DeepSeekProvider(api_key=api_key))
