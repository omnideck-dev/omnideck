"""Tests for shared provider model metadata resolution."""

import pytest

from sdk.providers._model_metadata import (
    discovered_metadata,
    fallback_metadata,
    inference_controls,
    metadata_value,
    request_control_supported,
    thinking_configuration,
)


@pytest.mark.unit
def test_catalog_matches_provider_qualified_model_ids() -> None:
    metadata = fallback_metadata("bedrock/openai.gpt-5.6-luna")

    assert metadata["context_window"] == 1_050_000
    assert metadata["reasoning_efforts"][-2:] == ["xhigh", "max"]


@pytest.mark.unit
def test_gpt_56_controls_omit_unsupported_sampling_parameters() -> None:
    controls = inference_controls(
        "openai_responses",
        True,
        "reasoning_effort",
        model_id="bedrock/openai.gpt-5.6-sol",
    )

    assert "reasoning_effort" in controls
    assert "temperature" not in controls
    assert "top_p" not in controls


@pytest.mark.unit
def test_request_guard_handles_provider_qualified_reasoning_models() -> None:
    assert request_control_supported(
        "openai_responses",
        "bedrock/openai.gpt-5.6-sol",
        "temperature",
    ) is False
    assert request_control_supported(
        "openai_responses",
        "bedrock/openai.gpt-5.6-sol",
        "top_p",
    ) is False


@pytest.mark.unit
def test_responses_reasoning_block_disables_sampling_for_unknown_models() -> None:
    assert request_control_supported(
        "openai_responses", "custom-reasoning-model", "temperature", think=True,
    ) is False
    assert request_control_supported(
        "openai_responses", "custom-chat-model", "temperature", think=False,
    ) is True


@pytest.mark.unit
def test_discovered_values_take_precedence_even_when_false() -> None:
    discovered = discovered_metadata({
        "id": "gpt-5.6",
        "metadata": {
            "context_length": 42,
            "supports_images": False,
            "supported_parameters": ["reasoning_effort"],
        },
    })

    assert metadata_value("gpt-5.6", "context_window", discovered["context_window"]) == 42
    assert discovered["supports_images"] is False
    assert discovered["supports_thinking"] is True
    assert discovered["supported_parameters"] == ["reasoning_effort"]


@pytest.mark.unit
def test_ollama_gpt_oss_uses_required_graded_thinking() -> None:
    control, levels, required = thinking_configuration("ollama", "gpt-oss:20b", True)

    assert control == "reasoning_effort"
    assert levels == ["low", "medium", "high"]
    assert required is True


@pytest.mark.unit
def test_ollama_thinking_uses_documented_generic_levels() -> None:
    control, levels, required = thinking_configuration("ollama", "qwen3:8b", True)

    assert control == "reasoning_effort"
    assert levels == ["low", "medium", "high", "max"]
    assert required is False


@pytest.mark.unit
def test_anthropic_nested_capabilities_are_normalized() -> None:
    metadata = discovered_metadata({
        "id": "claude-opus-5",
        "max_input_tokens": 1_000_000,
        "max_tokens": 128_000,
        "capabilities": {
            "image_input": {"supported": True},
            "thinking": {
                "supported": True,
                "types": {"adaptive": {"supported": True}},
            },
            "effort": {
                "supported": True,
                "low": {"supported": True},
                "medium": {"supported": True},
                "high": {"supported": True},
                "xhigh": {"supported": False},
                "max": {"supported": True},
            },
        },
    })

    assert metadata == {
        "context_window": 1_000_000,
        "max_output_tokens": 128_000,
        "supports_images": True,
        "supports_thinking": True,
        "thinking_control": "reasoning_effort",
        "thinking_levels": ["low", "medium", "high", "max"],
        "thinking_default": "high",
    }
