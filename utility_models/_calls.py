"""Prepare calls for the utility models: vision, compaction and titles.

Each utility model has its own provider and model in settings, separate from
any agent profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, NamedTuple

from llm import ModelClient, ModelInfo, accepted_options, find_model, with_output_cap
from provider_catalog import get_client
from settings import load_settings

UtilityModel = Literal["vision", "compaction", "title"]


@dataclass(frozen=True)
class _UtilitySettings:
    """The settings keys one utility model reads, and its output limit."""

    provider_key: str
    model_key: str
    options_key: str | None
    think_key: str | None
    # Output limit used when the settings leave output unset.
    output_cap: int


_SETTINGS: dict[UtilityModel, _UtilitySettings] = {
    "vision": _UtilitySettings("vision_provider", "vision_model", "vision_options", "vision_think", 512),
    "compaction": _UtilitySettings("compaction_provider", "compaction_model", "compaction_options", None, 8192),
    "title": _UtilitySettings("title_provider", "title_model", None, None, 50),
}

OUTPUT_CAPS: dict[UtilityModel, int] = {name: spec.output_cap for name, spec in _SETTINGS.items()}


class UtilityCall(NamedTuple):
    """Everything one utility-model request needs."""

    client: ModelClient
    model: str
    options: dict[str, Any]
    think: bool
    # The model's listed details, or None when the provider could not list them.
    model_info: ModelInfo | None


def configured_model(utility: UtilityModel, *, model: str | None = None) -> str | None:
    """Return the model *utility* uses, or None when its provider or model is unset.

    *model* replaces the configured model.
    """
    spec = _SETTINGS[utility]
    settings = load_settings()
    model = model or settings.get(spec.model_key) or ""
    return model if model and settings.get(spec.provider_key) else None


async def prepare_utility_call(utility: UtilityModel, *, model: str | None = None) -> UtilityCall | None:
    """Return the request for *utility*, or None when it has no model set.

    *model* replaces the configured model. Options and thinking are limited
    to what the model accepts. Sampling values are never invented: leaving
    them out lets the model use its own defaults.
    """
    model = configured_model(utility, model=model)
    if model is None:
        return None
    spec = _SETTINGS[utility]
    settings = load_settings()
    provider_name = settings[spec.provider_key]
    options: dict[str, Any] = dict(settings.get(spec.options_key) or {}) if spec.options_key else {}
    think = bool(settings.get(spec.think_key)) if spec.think_key else False

    client = get_client(provider_name)
    model_info = await find_model(client, model)
    if model_info is not None:
        think = model_info.thinking_required or (think and model_info.supports_thinking)
    accepted = accepted_options(model_info, options, think=think)
    return UtilityCall(client, model, with_output_cap(accepted, model_info, spec.output_cap), think, model_info)


__all__ = ["OUTPUT_CAPS", "UtilityCall", "UtilityModel", "configured_model", "prepare_utility_call"]
