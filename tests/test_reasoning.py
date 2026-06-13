"""
tests/test_reasoning.py — Tests for Alfred's adaptive reasoning configuration.

Run from the repo root (so config.py finds .env):
    venv\\Scripts\\python -m pytest tests -q

The live smoke test is skipped unless RUN_LIVE_SMOKE=1 is set, because it
makes a real (small) Anthropic API call:
    $env:RUN_LIVE_SMOKE = "1"; venv\\Scripts\\python -m pytest tests -q
"""

from __future__ import annotations

import os

import pytest

from alfred.agent import resolve_alfred_model, resolve_thinking_settings


# =============================================================================
# resolve_thinking_settings — the reasoning policy
# =============================================================================


def test_default_claude_enables_adaptive_thinking():
    settings = resolve_thinking_settings("")
    assert settings is not None
    assert settings["thinking"] is True
    assert settings["max_tokens"] == 16000


@pytest.mark.parametrize("model_str", ["claude-sonnet-4-6", "claude-opus-4-8", "CLAUDE-SONNET-4-6"])
def test_explicit_claude_models_enable_thinking(model_str):
    settings = resolve_thinking_settings(model_str)
    assert settings is not None
    assert settings["thinking"] is True


def test_deep_reasoning_mode_uses_max_effort():
    settings = resolve_thinking_settings("extended-thinking")
    assert settings is not None
    assert settings["thinking"] == "xhigh"
    assert settings["max_tokens"] == 32000


@pytest.mark.parametrize(
    "model_str",
    ["gpt-4o", "gpt-4o-mini", "gemini-2.0-flash", "gemini-1.5-pro", "sonar-pro", "sonar-reasoning-pro"],
)
def test_non_claude_models_get_no_thinking_settings(model_str):
    # Forcing a reasoning flag onto non-reasoning models (e.g. gpt-4o) would 400.
    assert resolve_thinking_settings(model_str) is None


# =============================================================================
# resolve_alfred_model — model routing unchanged by the reasoning upgrade
# =============================================================================


def test_empty_and_extended_thinking_use_default_model():
    assert resolve_alfred_model("") is None
    assert resolve_alfred_model("extended-thinking") is None


def test_default_claude_model_returns_none():
    from config import settings

    assert resolve_alfred_model(settings.alfred_model) is None


def test_non_default_claude_model_returns_override():
    from pydantic_ai.models.anthropic import AnthropicModel

    model = resolve_alfred_model("claude-opus-4-8")
    assert isinstance(model, AnthropicModel)
    assert model.model_name == "claude-opus-4-8"


# =============================================================================
# pydantic-ai translation — thinking=True must become {'type': 'adaptive'}
# on the configured default model (no network involved)
# =============================================================================


def test_unified_thinking_translates_to_adaptive_on_default_model():
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
    from pydantic_ai.profiles.anthropic import AnthropicModelProfile
    from pydantic_ai.providers.anthropic import AnthropicProvider

    from config import settings as app_settings

    model = AnthropicModel(
        app_settings.alfred_model,
        provider=AnthropicProvider(api_key="test-key-no-network"),
    )

    profile = AnthropicModelProfile.from_profile(model.profile)
    assert profile.anthropic_supports_adaptive_thinking, (
        f"Configured model '{app_settings.alfred_model}' does not support adaptive "
        f"thinking; resolve_thinking_settings would fall back to budget thinking."
    )

    thinking_settings = resolve_thinking_settings("")
    prepared_settings, params = model.prepare_request(thinking_settings, ModelRequestParameters())
    config = model._translate_thinking(prepared_settings or AnthropicModelSettings(), params)
    assert config == {"type": "adaptive"}


def test_deep_mode_translates_to_adaptive_with_effort():
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
    from pydantic_ai.profiles.anthropic import AnthropicModelProfile
    from pydantic_ai.providers.anthropic import AnthropicProvider

    from config import settings as app_settings

    model = AnthropicModel(
        app_settings.alfred_model,
        provider=AnthropicProvider(api_key="test-key-no-network"),
    )

    thinking_settings = resolve_thinking_settings("extended-thinking")
    prepared_settings, params = model.prepare_request(thinking_settings, ModelRequestParameters())
    config = model._translate_thinking(prepared_settings or AnthropicModelSettings(), params)
    assert config == {"type": "adaptive"}

    # The 'xhigh' level must also map to an effort the profile supports.
    profile = AnthropicModelProfile.from_profile(model.profile)
    assert profile.anthropic_supports_effort
    assert params.thinking == "xhigh"


# =============================================================================
# Live smoke test — one real API call, opt-in only
# =============================================================================


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_SMOKE") != "1",
    reason="Set RUN_LIVE_SMOKE=1 to run the live Anthropic smoke test (costs a few cents).",
)
def test_live_alfred_run_with_adaptive_thinking():
    import asyncio

    from alfred.agent import AlfredAgent, AlfredDependencies
    from notion_bridge.client import NotionBridge
    from notion_bridge.project_pages import ProjectPages
    from notion_bridge.watch_list import WatchList

    bridge = NotionBridge()
    deps = AlfredDependencies(
        bridge=bridge,
        project_pages=ProjectPages(bridge),
        watch_list=WatchList(bridge),
    )

    async def _run():
        return await AlfredAgent.run(
            "Without using any tools: in two sentences, explain how you would "
            "approach the question 'which of our matters is most at risk this "
            "week' if you were asked it.",
            deps=deps,
            model_settings=resolve_thinking_settings(""),
        )

    result = asyncio.run(_run())
    assert result.output and len(result.output) > 20

    # Adaptive thinking may or may not produce thinking blocks on a small
    # prompt; just confirm the request succeeded and report what happened.
    thinking_parts = sum(
        1
        for msg in result.all_messages()
        for part in getattr(msg, "parts", [])
        if type(part).__name__ == "ThinkingPart"
    )
    print(f"\nLive smoke OK. Thinking parts in response: {thinking_parts}")
    print(f"Answer: {result.output[:300]}")
