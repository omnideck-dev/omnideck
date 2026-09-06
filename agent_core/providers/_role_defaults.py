"""Model-aware defaults for specialized LLM roles.

Vision, compaction, and title generation should use the selected model's
capabilities instead of inheriting historical Ollama-shaped settings.  The
helpers here deliberately keep provider-native sampling defaults (an omitted
option) while applying small, role-appropriate output ceilings.
"""

from __future__ import annotations

import logging
from typing import Any

from ._models import ModelInfo

logger = logging.getLogger(__name__)

_ROLE_OUTPUT_CAPS = {
    "vision": 512,
    "compaction": 8192,
    "title": 50,
}

_OPTION_CONTROLS = {
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


async def resolve_model_info(provider: Any, model: str) -> ModelInfo | None:
    """Best-effort lookup of one model in a provider's cached catalog."""
    try:
        models = await provider.list_models()
    except Exception:
        logger.debug("Could not resolve metadata for model %s", model, exc_info=True)
        return None
    return next((candidate for candidate in models if candidate.name == model), None)


def _supported_options(
    options: dict[str, Any],
    model_info: ModelInfo | None,
) -> dict[str, Any]:
    """Remove settings known to be incompatible with the selected model."""
    if model_info is None or model_info.inference_controls is None:
        return {key: value for key, value in options.items() if value is not None}

    supported = set(model_info.inference_controls)
    return {
        key: value
        for key, value in options.items()
        if value is not None
        and (control := _OPTION_CONTROLS.get(key)) is not None
        and control in supported
    }


async def resolve_role_options(
    provider: Any,
    model: str,
    role: str,
    options: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ModelInfo | None]:
    """Return compatible explicit options plus a role-specific output cap.

    Sampling values are intentionally not invented: leaving temperature/top-p
    absent lets the selected provider and model use their own defaults.
    """
    model_info = await resolve_model_info(provider, model)
    resolved = _supported_options(dict(options or {}), model_info)

    role_cap = _ROLE_OUTPUT_CAPS.get(role)
    model_cap = model_info.max_output_tokens if model_info else None
    if model_cap and isinstance(resolved.get("num_predict"), (int, float)):
        resolved["num_predict"] = min(resolved["num_predict"], model_cap)
    if model_cap and isinstance(resolved.get("max_tokens"), (int, float)):
        resolved["max_tokens"] = min(resolved["max_tokens"], model_cap)
    if role_cap is not None and "num_predict" not in resolved and "max_tokens" not in resolved:
        resolved["num_predict"] = min(role_cap, model_cap) if model_cap else role_cap

    return resolved, model_info


__all__ = ["resolve_model_info", "resolve_role_options"]
