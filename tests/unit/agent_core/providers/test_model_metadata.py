"""Tests for shared provider model metadata resolution."""

import pytest

from agent_core.providers import ModelInfo
from agent_core.providers._model_metadata import (
    accepted_options,
    discovered_metadata,
    fallback_metadata,
    inference_controls,
    metadata_value,
    listed_model,
    request_control_supported,
    request_sampling,
    build_model_info,
    thinking_configuration,
    thinking_default,
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
    model = listed_model(None, "bedrock/openai.gpt-5.6-sol", "openai_responses")

    assert request_control_supported(model, "temperature") is False
    assert request_control_supported(model, "top_p") is False


@pytest.mark.unit
def test_responses_reasoning_block_disables_sampling_for_unknown_models() -> None:
    reasoning = listed_model(None, "custom-reasoning-model", "openai_responses")
    chat = listed_model(None, "custom-chat-model", "openai_responses")

    assert request_control_supported(reasoning, "temperature", think=True) is False
    assert request_control_supported(chat, "temperature", think=False) is True


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
def test_unknown_request_format_offers_no_thinking_setting() -> None:
    model = build_model_info("qwen3:8b", "unknown_api", {"supports_thinking": True})

    assert model.thinking_control is None
    assert model.thinking_levels is None
    assert "think" not in (model.inference_controls or [])


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
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model_id", "efforts"),
    [
        ("gpt-6-sol", ["none", "low", "medium", "high", "xhigh", "max"]),
        ("gpt-6-luna", ["none", "low", "medium", "high", "xhigh", "max"]),
        ("gpt-6-astra", ["low", "medium", "high", "xhigh", "max"]),
        ("gpt-6.1-sol", ["low", "medium", "high", "xhigh", "max"]),
        ("gpt-6.1-terra", ["none", "low", "medium", "high", "xhigh", "max"]),
    ],
)
def test_gpt_6_models_use_their_documented_reasoning_levels(model_id: str, efforts: list[str]) -> None:
    metadata = fallback_metadata(model_id)

    assert metadata["reasoning_efforts"] == efforts
    assert metadata["context_window"] == 1_050_000
    assert metadata["max_output_tokens"] == 128_000
    assert metadata["supports_images"] is True
    assert thinking_configuration("openai_responses", model_id, True) == ("reasoning_effort", efforts, False)


@pytest.mark.unit
def test_claude_haiku_55_uses_effort_levels_and_omits_sampling_controls() -> None:
    control, levels, required = thinking_configuration("anthropic_messages", "claude-haiku-5-5", True)
    controls = inference_controls(
        "anthropic_messages", True, control, model_id="claude-haiku-5-5",
    )

    assert control == "reasoning_effort"
    assert levels == ["low", "medium", "high", "xhigh", "max"]
    assert required is False
    assert thinking_default("claude-haiku-5-5", control, levels) == "medium"
    assert "temperature" not in controls
    assert "top_p" not in controls
    assert "top_k" not in controls


@pytest.mark.unit
def test_claude_opus_55_defaults_to_medium_effort_while_opus_5_stays_high() -> None:
    levels = ["low", "medium", "high", "xhigh", "max"]

    assert thinking_default("claude-opus-5-5", "reasoning_effort", levels) == "medium"
    assert thinking_default("claude-opus-5", "reasoning_effort", levels) == "high"


@pytest.mark.unit
def test_kimi_k3_matches_bedrock_ids_and_defaults_to_max_reasoning() -> None:
    metadata = fallback_metadata("us.moonshotai.kimi-k3")
    levels = ["none", "low", "medium", "high", "xhigh", "max"]

    assert metadata["supports_images"] is True
    assert thinking_configuration("openai_chat", "us.moonshotai.kimi-k3", True) == ("reasoning_effort", levels, False)
    assert thinking_default("us.moonshotai.kimi-k3", "reasoning_effort", levels) == "max"
    assert fallback_metadata("moonshotai.kimi-k3.1-pro") == {}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "required"),
    [
        ("claude-opus-5-5", True),
        ("claude-sonnet-5-5", True),
        ("claude-fable-5-2", True),
        ("claude-mythos-5", True),
        ("claude-haiku-5-5", False),
        ("claude-opus-5", False),
        ("claude-sonnet-5", False),
    ],
)
def test_claude_models_that_cannot_turn_thinking_off_are_marked(model: str, required: bool) -> None:
    _, _, thinking_required = thinking_configuration("anthropic_messages", model, True)

    assert thinking_required is required


@pytest.mark.unit
def test_provider_listing_wins_over_the_catalog() -> None:
    model = build_model_info("claude-opus-5-5", "anthropic_messages", {
        "context_window": 200_000,
        "supports_thinking": True,
        "thinking_control": "reasoning_effort",
        "thinking_levels": ["low", "high"],
        "thinking_required": False,
        "thinking_default": "low",
    })

    assert model.context_window == 200_000
    assert model.thinking_levels == ["low", "high"]
    assert model.thinking_required is False
    assert model.thinking_default == "low"


@pytest.mark.unit
def test_catalog_fills_only_what_the_provider_left_out() -> None:
    model = build_model_info("claude-opus-5-5", "anthropic_messages", {"context_window": 200_000})

    assert model.context_window == 200_000
    assert model.max_output_tokens == 128_000
    assert model.thinking_required is True
    assert model.thinking_default == "medium"


@pytest.mark.unit
def test_provider_parameter_list_wins_over_catalog_unsupported_controls() -> None:
    listed = build_model_info("gpt-5.4", "openai_chat", {
        "supported_parameters": ["temperature", "max_tokens", "reasoning"],
    })
    unlisted = build_model_info("gpt-5.4", "openai_chat", {})

    assert "temperature" in (listed.inference_controls or [])
    assert "temperature" not in (unlisted.inference_controls or [])


@pytest.mark.unit
def test_listed_model_prefers_the_provider_listing() -> None:
    listing = build_model_info("claude-new-model", "anthropic_messages", {
        "supports_thinking": True,
        "thinking_control": "reasoning_effort",
        "thinking_levels": ["low", "medium", "high"],
    })

    assert listed_model([listing], "claude-new-model", "anthropic_messages") is listing
    assert listed_model([], "claude-new-model", "anthropic_messages").thinking_control != "reasoning_effort"


@pytest.mark.unit
def test_model_info_lists_fields_that_thinking_turns_off() -> None:
    claude = build_model_info("claude-opus-4-5", "anthropic_messages", {})
    gpt = build_model_info("custom-model", "openai_responses", {})
    local = build_model_info("qwen3:8b", "ollama", {})

    assert claude.thinking_excluded_controls == ["temperature", "top_k"]
    assert gpt.thinking_excluded_controls == ["temperature", "top_p"]
    assert local.thinking_excluded_controls == []


@pytest.mark.unit
def test_exclusive_controls_only_list_fields_the_model_accepts() -> None:
    sonnet = build_model_info("claude-sonnet-4-5", "anthropic_messages", {})
    trimmed = build_model_info("claude-sonnet-4-5", "anthropic_messages", {
        "supported_parameters": ["temperature", "max_tokens"],
    })

    assert sonnet.exclusive_controls == [["temperature", "top_p"]]
    assert trimmed.exclusive_controls == []


@pytest.mark.unit
def test_model_without_a_known_request_format_leaves_refusal_rules_unknown() -> None:
    model = ModelInfo(name="fake-model")

    assert model.thinking_excluded_controls is None
    assert model.exclusive_controls is None
    assert request_sampling(model, {"temperature": 0.5, "top_p": 0.9}, think=True) == {
        "temperature": 0.5,
        "top_p": 0.9,
    }


_OLDER_CLAUDE = ModelInfo(
    name="claude-sonnet-4-5",
    supports_thinking=True,
    inference_controls=["temperature", "top_p", "top_k", "num_predict", "think", "thinking_budget"],
    thinking_excluded_controls=["temperature", "top_k"],
    exclusive_controls=[["temperature", "top_p"]],
)


@pytest.mark.unit
def test_accepted_options_keeps_everything_without_model_details() -> None:
    assert accepted_options(None, {"temperature": 0.2, "custom": 1, "top_p": None}, think=True) == {
        "temperature": 0.2,
        "custom": 1,
    }


@pytest.mark.unit
def test_accepted_options_drops_options_the_model_does_not_accept() -> None:
    model = ModelInfo(name="m", inference_controls=["temperature", "num_predict"])

    assert accepted_options(model, {"temperature": 0.2, "top_k": 20, "num_ctx": 8192, "custom": 1}, think=False) == {
        "temperature": 0.2,
    }


@pytest.mark.unit
def test_accepted_options_drops_options_refused_while_thinking() -> None:
    options = {"temperature": 0.2, "top_k": 20, "num_predict": 512}

    assert accepted_options(_OLDER_CLAUDE, options, think=True) == {"num_predict": 512}
    assert accepted_options(_OLDER_CLAUDE, options, think=False) == options


@pytest.mark.unit
def test_accepted_options_keeps_the_first_of_a_refused_pair() -> None:
    assert accepted_options(_OLDER_CLAUDE, {"top_p": 0.9, "temperature": 0.2}, think=False) == {
        "temperature": 0.2,
    }


@pytest.mark.unit
def test_accepted_options_drops_a_thinking_level_the_model_lacks() -> None:
    model = ModelInfo(
        name="m",
        inference_controls=["think", "reasoning_effort"],
        thinking_levels=["low", "medium", "high"],
    )

    assert accepted_options(model, {"reasoning_effort": "max"}, think=True) == {}
    assert accepted_options(model, {"reasoning_effort": "high"}, think=True) == {"reasoning_effort": "high"}


@pytest.mark.unit
@pytest.mark.parametrize(("api", "is_cloud", "configurable"), [
    ("ollama", False, True),
    ("ollama", True, False),
    ("openai_chat", False, False),
    ("anthropic_messages", False, False),
])
def test_only_local_ollama_models_let_users_set_the_context_size(
    api: str, is_cloud: bool, configurable: bool,
) -> None:
    info = build_model_info("some-model", api, {}, is_cloud=is_cloud)

    assert ("context_window" in (info.inference_controls or [])) is configurable
