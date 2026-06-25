"""
alfred/model_factory.py — Provider-agnostic model builder.

Returns the correct pydantic-ai model object based on the model name string.
All Alfred skills and the main AlfredAgent use this so switching providers
is a single env-var change (ALFRED_MODEL=gpt-4o or ALFRED_MODEL=claude-sonnet-4-6),
not a code change.

Routing rules:
  gpt-* / o1* / o3*  →  OpenAI
  gemini-*           →  Google
  claude-* (default) →  Anthropic
"""
from __future__ import annotations


def build_model(model_name: str):
    """
    Build a pydantic-ai model object for the given model name string.

    Reads API keys from config.settings. Raises ValueError if the required
    API key for the detected provider is not configured.
    """
    from config import settings

    if model_name.startswith(("gpt-", "o1", "o3", "o4")):
        if not settings.openai_api_key:
            raise ValueError(
                f"ALFRED_MODEL is set to '{model_name}' but OPENAI_API_KEY is not configured."
            )
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider
        return OpenAIModel(
            model_name,
            provider=OpenAIProvider(api_key=settings.openai_api_key),
        )

    if model_name.startswith("gemini-"):
        if not settings.google_api_key:
            raise ValueError(
                f"ALFRED_MODEL is set to '{model_name}' but GOOGLE_API_KEY is not configured."
            )
        from pydantic_ai.models.gemini import GeminiModel
        from pydantic_ai.providers.google import GoogleProvider
        return GeminiModel(
            model_name,
            provider=GoogleProvider(api_key=settings.google_api_key),
        )

    # Default: Anthropic (claude-*)
    if not settings.anthropic_api_key:
        raise ValueError(
            f"ALFRED_MODEL is set to '{model_name}' but ANTHROPIC_API_KEY is not configured."
        )
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider
    return AnthropicModel(
        model_name,
        provider=AnthropicProvider(api_key=settings.anthropic_api_key),
    )
