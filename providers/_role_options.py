"""Request options for the helper roles: vision, compaction and titles."""

from __future__ import annotations

from typing import Any, NamedTuple

from agent_core.providers import ModelInfo, Provider, accepted_options, find_model, with_output_cap

# Output limit each role uses when its settings leave output unset.
ROLE_OUTPUT_CAPS = {
    "vision": 512,
    "compaction": 8192,
    "title": 50,
}


class RoleRequest(NamedTuple):
    """What one helper-role request sends, and the model details it used."""

    options: dict[str, Any]
    think: bool
    model: ModelInfo | None


async def resolve_role_options(
    provider: Provider,
    model: str,
    role: str,
    options: dict[str, Any] | None = None,
    *,
    think: bool = False,
) -> RoleRequest:
    """Return the options and thinking switch the model accepts for *role*.

    Sampling values are never invented. Leaving them out lets the model use
    its own defaults.
    """
    model_info = await find_model(provider, model)
    if model_info is not None:
        think = model_info.thinking_required or (think and model_info.supports_thinking)
    accepted = accepted_options(model_info, options or {}, think=think)
    return RoleRequest(with_output_cap(accepted, model_info, ROLE_OUTPUT_CAPS[role]), think, model_info)


__all__ = ["ROLE_OUTPUT_CAPS", "RoleRequest", "resolve_role_options"]
