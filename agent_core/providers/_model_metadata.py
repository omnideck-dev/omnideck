"""Metadata-first model capability resolution shared by all providers.

Provider APIs remain authoritative. The declarative ``model_metadata.json``
catalog fills only fields an API omitted, keeping model-family knowledge in a
single reviewable file that can be refreshed without editing provider logic.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from ._models import ModelInfo

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).with_name("model_metadata.json")

_COMMON_CONTROLS = [
    "temperature",
    "top_p",
    "num_predict",
    "max_iterations",
    "compaction_threshold",
]

# "context_window" means the user may choose how much context to allocate.
# Only a locally run Ollama model allows that; hosted models have a fixed size.
_API_CONTROLS = {
    "ollama": [*_COMMON_CONTROLS, "top_k", "repeat_penalty", "context_window"],
    "openai_responses": _COMMON_CONTROLS,
    "openai_chat": _COMMON_CONTROLS,
    "anthropic_messages": [*_COMMON_CONTROLS, "top_k"],
}

_PARAMETER_CONTROLS = {
    "temperature": "temperature",
    "top_k": "top_k",
    "top_p": "top_p",
    "repeat_penalty": "repeat_penalty",
    "max_tokens": "num_predict",
    "max_completion_tokens": "num_predict",
    "max_output_tokens": "num_predict",
    "reasoning": "reasoning_effort",
    "reasoning_effort": "reasoning_effort",
    "reasoning_summary": "reasoning_summary",
    "thinking": "think",
    "thinking_budget": "thinking_budget",
}

_LOCAL_CONTROLS = {"context_window", "max_iterations", "compaction_threshold"}
_SAMPLING_CONTROLS = ("temperature", "top_p", "top_k")

# Option keys a request carries, and the control each one belongs to.
OPTION_CONTROLS = {
    "temperature": "temperature",
    "top_k": "top_k",
    "top_p": "top_p",
    "repeat_penalty": "repeat_penalty",
    "num_ctx": "context_window",
    "num_predict": "num_predict",
    "max_tokens": "num_predict",
    "reasoning_effort": "reasoning_effort",
    "reasoning_summary": "reasoning_summary",
    "thinking_budget": "thinking_budget",
}

# Responses requests that carry a reasoning block cannot also carry sampling
# overrides. Anthropic rejects temperature and top_k on any request that thinks.
_THINKING_EXCLUDED_CONTROLS = {
    "openai_responses": ("temperature", "top_p"),
    "anthropic_messages": ("temperature", "top_k"),
}


def model_slug(model_id: str) -> str:
    """Strip a gateway provider qualifier and OpenAI's Bedrock prefix."""
    slug = model_id.rsplit("/", 1)[-1]
    return slug.removeprefix("openai.")


@lru_cache(maxsize=1)
def _catalog_entries() -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        entries = payload.get("models", [])
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ValueError("models must be a list of objects")
        return tuple(entries)
    except (OSError, json.JSONDecodeError, ValueError):
        logger.exception("Could not load model metadata catalog at %s", _CATALOG_PATH)
        return ()


def fallback_metadata(model_id: str) -> dict[str, Any]:
    """Return catalog metadata for *model_id*, or an empty dict if unknown."""
    slug = model_slug(model_id).lower()
    for entry in _catalog_entries():
        patterns = entry.get("patterns")
        if isinstance(patterns, list) and any(
            isinstance(pattern, str) and fnmatch.fnmatchcase(slug, pattern.lower())
            for pattern in patterns
        ):
            return {key: value for key, value in entry.items() if key != "patterns"}
    return {}


def inference_controls(
    api: str,
    supports_thinking: bool,
    thinking_control: str | None = None,
    *,
    model_id: str | None = None,
    supported_parameters: list[str] | None = None,
) -> list[str]:
    """Return controls accepted by one model over one wire API.

    A provider's parameter list is authoritative. The catalog removes controls
    only when the provider did not say which parameters the model accepts.
    """
    controls = list(_API_CONTROLS.get(api, _COMMON_CONTROLS))
    if supports_thinking:
        if thinking_control == "reasoning_effort":
            controls.extend(["think", "reasoning_effort"])
            if api == "openai_responses":
                controls.append("reasoning_summary")
        elif thinking_control == "thinking_budget":
            controls.extend(["think", "thinking_budget"])

    if supported_parameters is not None:
        discovered_controls = {
            control
            for parameter in supported_parameters
            if (control := _PARAMETER_CONTROLS.get(parameter)) is not None
        }
        # Thinking support is normalized separately because several model
        # APIs expose it as a capability instead of a request parameter.
        if supports_thinking:
            discovered_controls.update(
                control for control in controls
                if control in {"think", thinking_control, "reasoning_summary"}
            )
        controls = [
            control for control in controls
            if control in _LOCAL_CONTROLS or control in discovered_controls
        ]

    elif model_id:
        unsupported = fallback_metadata(model_id).get("unsupported_controls", [])
        if isinstance(unsupported, list):
            controls = [control for control in controls if control not in unsupported]
    return controls


def request_control_supported(
    model: ModelInfo,
    control: str,
    *,
    think: bool = False,
) -> bool:
    """Return whether a request may safely include one optional control.

    Runtime model discovery normally removes invalid options before provider
    invocation. This last-mile check protects direct adapter callers.
    """
    if think and control in (model.thinking_excluded_controls or ()):
        return False
    return model.inference_controls is None or control in model.inference_controls


def accepted_options(
    model: ModelInfo | None,
    options: Mapping[str, Any],
    *,
    think: bool,
) -> dict[str, Any]:
    """Return the options *model* accepts, dropping any it would refuse.

    Without model details every set option is kept. With them, an option is
    dropped when the model does not accept it, refuses it while thinking, or
    names a thinking level the model does not have. When the model refuses a
    group of options together, the first one set in the group is kept.
    """
    accepted = {key: value for key, value in options.items() if value is not None}
    if model is None:
        return accepted
    accepted = {
        key: value
        for key, value in accepted.items()
        if (control := OPTION_CONTROLS.get(key)) is not None
        and request_control_supported(model, control, think=think)
    }
    levels = model.thinking_levels
    if levels and accepted.get("reasoning_effort") not in (None, *levels):
        accepted.pop("reasoning_effort")
    for group in model.exclusive_controls or ():
        present = [key for control in group for key in accepted if OPTION_CONTROLS[key] == control]
        for key in present[1:]:
            accepted.pop(key)
    return accepted


def request_sampling(
    model: ModelInfo,
    options: Mapping[str, Any],
    *,
    think: bool,
) -> dict[str, Any]:
    """Return the sampling values one request may send to this model."""
    accepted = accepted_options(model, options, think=think)
    return {key: accepted[key] for key in _SAMPLING_CONTROLS if key in accepted}


def with_output_cap(
    options: Mapping[str, Any],
    model: ModelInfo | None,
    cap: int,
) -> dict[str, Any]:
    """Limit output to the model's maximum, defaulting to *cap* when unset."""
    capped = dict(options)
    model_cap = model.max_output_tokens if model else None
    for key in ("num_predict", "max_tokens"):
        if model_cap and isinstance(capped.get(key), (int, float)):
            capped[key] = min(capped[key], model_cap)
    if "num_predict" not in capped and "max_tokens" not in capped:
        capped["num_predict"] = min(cap, model_cap) if model_cap else cap
    return capped


def reasoning_efforts(model_id: str) -> list[str]:
    """Return catalog reasoning levels, with a conservative generic fallback."""
    efforts = fallback_metadata(model_id).get("reasoning_efforts")
    if isinstance(efforts, list) and all(isinstance(effort, str) for effort in efforts):
        return efforts
    return ["low", "medium", "high"]


def thinking_configuration(
    api: str,
    model_id: str,
    supports_thinking: bool,
) -> tuple[str | None, list[str] | None, bool]:
    """Return how thinking is set for a model, its levels, and whether it is required.

    Wire API semantics determine how a selected level is encoded. Model
    metadata can narrow the available values or make thinking mandatory.
    """
    if not supports_thinking:
        return None, None, False

    meta = fallback_metadata(model_id)
    explicit_control = meta.get("thinking_control")
    explicit_levels = meta.get("thinking_levels")
    if (
        explicit_control in {"reasoning_effort", "thinking_budget"}
        and isinstance(explicit_levels, list)
        and all(isinstance(level, str) for level in explicit_levels)
    ):
        return explicit_control, explicit_levels, bool(meta.get("thinking_required", False))
    if api in {"openai_responses", "openai_chat"}:
        levels = reasoning_efforts(model_id)
        return "reasoning_effort", levels, bool(meta.get("thinking_required", False))
    if api == "anthropic_messages":
        return "thinking_budget", ["minimal", "standard", "extended"], bool(
            meta.get("thinking_required", False),
        )
    if api == "ollama":
        return "reasoning_effort", ["low", "medium", "high", "max"], bool(
            meta.get("thinking_required", False),
        )
    # An unknown request format has no way to set thinking.
    return None, None, False


def thinking_default(model_id: str, control: str | None, levels: list[str] | None) -> str | None:
    """Return the thinking level the model uses when none is chosen."""
    configured = fallback_metadata(model_id).get("thinking_default")
    if isinstance(configured, str) and (levels is None or configured in levels):
        return configured
    if control == "thinking_budget":
        return "standard"
    if levels:
        return "medium" if "medium" in levels else levels[0]
    return None


def metadata_value(model_id: str, field: str, discovered: Any = None) -> Any:
    """Prefer a provider-discovered value, then consult the fallback catalog."""
    if discovered is not None:
        return discovered
    return fallback_metadata(model_id).get(field)


def discovered_metadata(raw: Any) -> dict[str, Any]:
    """Normalize common fields returned by model-list metadata APIs.

    This intentionally recognizes only explicit values. Missing fields are
    left absent so callers can fill them from the fallback catalog.
    """
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        return {}

    nested = raw.get("metadata")
    sources = [raw, nested] if isinstance(nested, dict) else [raw]
    result: dict[str, Any] = {}

    def first(*keys: str) -> Any:
        for source in sources:
            for key in keys:
                value = source.get(key)
                if value is not None:
                    return value
        return None

    context_window = first("context_window", "context_length", "max_input_tokens")
    if isinstance(context_window, int) and not isinstance(context_window, bool) and context_window > 0:
        result["context_window"] = context_window
    max_output_tokens = first("max_output_tokens", "max_completion_tokens", "max_tokens")
    if isinstance(max_output_tokens, int) and not isinstance(max_output_tokens, bool) and max_output_tokens > 0:
        result["max_output_tokens"] = max_output_tokens

    modalities = first("input_modalities", "modalities")
    supports_images = first("supports_images", "vision")
    if isinstance(supports_images, bool):
        result["supports_images"] = supports_images
    elif isinstance(modalities, list):
        result["supports_images"] = "image" in modalities or "vision" in modalities

    supports_thinking = first("supports_thinking", "thinking")
    if isinstance(supports_thinking, bool):
        result["supports_thinking"] = supports_thinking
    supported_parameters = first("supported_parameters")
    if isinstance(supported_parameters, list) and all(
        isinstance(value, str) for value in supported_parameters
    ):
        result["supported_parameters"] = supported_parameters
    if "supports_thinking" not in result and isinstance(supported_parameters, list):
        result["supports_thinking"] = any(
            value in supported_parameters
            for value in ("reasoning", "reasoning_effort", "thinking", "thinking_budget")
        )

    levels = first("thinking_levels", "reasoning_efforts")
    if isinstance(levels, list) and all(isinstance(level, str) for level in levels):
        result["thinking_levels"] = levels
    thinking_required = first("thinking_required")
    if isinstance(thinking_required, bool):
        result["thinking_required"] = thinking_required

    capabilities = first("capabilities")
    if isinstance(capabilities, dict):
        def capability_supported(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            return isinstance(value, dict) and value.get("supported") is True

        image_input = capabilities.get("image_input")
        if image_input is not None:
            result["supports_images"] = capability_supported(image_input)

        thinking = capabilities.get("thinking")
        if thinking is not None:
            result["supports_thinking"] = capability_supported(thinking)

        effort = capabilities.get("effort")
        thinking_types = thinking.get("types") if isinstance(thinking, dict) else None
        adaptive = thinking_types.get("adaptive") if isinstance(thinking_types, dict) else None
        disabled = thinking_types.get("disabled") if isinstance(thinking_types, dict) else None
        if disabled is not None:
            result["thinking_required"] = not capability_supported(disabled)
        if isinstance(effort, dict) and capability_supported(effort) and capability_supported(adaptive):
            result["thinking_control"] = "reasoning_effort"
            effort_levels = [
                level
                for level in ("low", "medium", "high", "xhigh", "max")
                if capability_supported(effort.get(level))
            ]
            result["thinking_levels"] = effort_levels or ["low", "medium", "high"]
    return result


def build_model_info(
    name: str,
    api: str,
    discovered: Mapping[str, Any],
    **fields: Any,
) -> ModelInfo:
    """Merge what a provider says about one model with the catalog.

    Anything the provider states wins. The catalog fills only the fields the
    provider left out. *fields* carries provider-only details such as a
    display name.
    """
    def value(field: str) -> Any:
        return metadata_value(name, field, discovered.get(field))

    supports_thinking = bool(value("supports_thinking"))
    control, levels, required = thinking_configuration(api, name, supports_thinking)
    controls = inference_controls(
        api,
        supports_thinking,
        control,
        model_id=name,
        supported_parameters=discovered.get("supported_parameters"),
    )
    if fields.get("is_cloud"):
        controls = [control for control in controls if control != "context_window"]
    if supports_thinking:
        control = discovered.get("thinking_control") or control
        levels = discovered.get("thinking_levels") or levels
        required = bool(discovered.get("thinking_required", required))
    return ModelInfo(
        name=name,
        context_window=value("context_window"),
        max_output_tokens=value("max_output_tokens"),
        supports_images=bool(value("supports_images")),
        supports_thinking=supports_thinking,
        inference_api=api,
        inference_controls=controls,
        thinking_control=control,
        thinking_levels=levels,
        thinking_default=discovered.get("thinking_default") or thinking_default(
            name, control, levels,
        ),
        thinking_required=required,
        thinking_excluded_controls=[
            excluded for excluded in _THINKING_EXCLUDED_CONTROLS.get(api, ()) if excluded in controls
        ],
        exclusive_controls=_exclusive_controls(name, controls),
        **fields,
    )


def _exclusive_controls(model_id: str, controls: list[str]) -> list[list[str]]:
    groups = fallback_metadata(model_id).get("exclusive_controls")
    if not isinstance(groups, list):
        return []
    return [
        [control for control in group if control in controls]
        for group in groups
        if isinstance(group, list)
        and all(isinstance(control, str) for control in group)
        and sum(control in controls for control in group) > 1
    ]


def listed_model(models: Iterable[ModelInfo] | None, name: str, api: str) -> ModelInfo:
    """Return the provider's listing for one model.

    Before the provider has listed its models, or when it does not list this
    one, the catalog stands in.
    """
    for model in models or ():
        if model.name == name:
            return model
    return build_model_info(name, api, {})


__all__ = [
    "OPTION_CONTROLS",
    "accepted_options",
    "build_model_info",
    "fallback_metadata",
    "discovered_metadata",
    "inference_controls",
    "listed_model",
    "metadata_value",
    "model_slug",
    "request_control_supported",
    "request_sampling",
    "reasoning_efforts",
    "thinking_configuration",
    "thinking_default",
    "with_output_cap",
]
