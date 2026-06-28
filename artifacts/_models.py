"""Data models for the artifacts index."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ArtifactEntry(BaseModel):
    """One file an agent sent via send_file, keyed by (conversation_id, path).

    Attributes:
        id: Stable id derived from conversation_id + path (see make_id).
        conversation_id: The conversation that produced the file (provenance;
            may point at a conversation that has since been deleted).
        path: Absolute path of the file at send time. Every file_output event
            in practice carries a path under the virtual-computer home dir —
            send_file enforces it, and the generation tools write there by
            convention — which is also the only location the file route serves
            from. Together with conversation_id this is the artifact's identity.
        filename: Basename for display/download.
        content_type: MIME type.
        agent_name: Human-readable name of the agent that sent it, if known.
        created_at: ISO-8601 timestamp of the first time this (conv, path) was sent.
        updated_at: ISO-8601 timestamp of the most recent send.
    """

    id: str
    conversation_id: str
    path: str
    filename: str
    content_type: str
    agent_name: str | None = None
    created_at: str
    updated_at: str


class ArtifactView(ArtifactEntry):
    """An index entry plus its live on-disk status, computed fresh on each read.

    ``status`` is never persisted — it is a read-time overlay so a file that
    has since vanished from disk shows as ``missing`` without mutating the index.
    """

    status: Literal["present", "missing"]


class ArtifactsIndex(BaseModel):
    """The whole persisted index: every artifact keyed by its id."""

    version: int = 1
    artifacts: dict[str, ArtifactEntry] = Field(default_factory=dict)
