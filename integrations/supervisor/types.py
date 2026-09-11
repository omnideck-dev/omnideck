"""Pydantic models for brokered-connection metadata and host paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, field_serializer, field_validator

from integrations.operation_grants import OperationGrants


@dataclass(frozen=True)
class HostPath:
    """A directory the supervisor will hand out to brokers that bind its role.

    The fields together record both the location and the permission posture
    the directory is supposed to have. ``container/entrypoint.sh`` is what
    actually enforces the posture (it runs as root before any process drops
    privilege); the values here are the canonical record of what the
    entrypoint should set, so changes happen in lockstep.
    """

    path: Path
    description: str
    owner: str
    group: str
    mode: int


class BrokeredConnectionMeta(BaseModel):
    """Common non-secret metadata for anything using a broker process."""

    version: Literal[3] = 3
    id: str
    slug: str
    label: str
    kind: Literal["integration", "model_provider"]
    added_at: datetime
    updated_at: datetime


class IntegrationMeta(BrokeredConnectionMeta):
    """A configured tool integration and its explicit agent grants."""

    kind: Literal["integration"] = "integration"
    agent_operation_grants: OperationGrants = frozenset()

    @field_validator("agent_operation_grants", mode="before")
    @classmethod
    def _parse_operation_grants(cls, value: Any) -> OperationGrants:
        if value is None:
            return frozenset()
        if isinstance(value, (list, set, frozenset, tuple)) and all(
            isinstance(item, str) for item in value
        ):
            return frozenset(value)
        raise ValueError("agent_operation_grants must be an array of strings")

    @field_serializer("agent_operation_grants")
    def _serialize_operation_grants(self, grants: OperationGrants) -> list[str]:
        return sorted(grants)


class ModelProviderMeta(BrokeredConnectionMeta):
    """A brokered LLM provider; it deliberately has no operation grants."""

    kind: Literal["model_provider"] = "model_provider"


ConnectionMeta: TypeAlias = IntegrationMeta | ModelProviderMeta


def connection_meta_from_dict(raw: dict[str, Any]) -> ConnectionMeta:
    """Validate version-3 metadata using its explicit domain discriminator."""
    if raw.get("kind") == "model_provider":
        return ModelProviderMeta.model_validate(raw)
    return IntegrationMeta.model_validate(raw)
