"""Artifacts index — a persistent catalog of files agents emit (file_output events)."""

from ._index_writer import ArtifactsIndexWriter
from ._models import ArtifactEntry, ArtifactsIndex, ArtifactView
from ._store import (
    delete_artifact,
    get_artifact,
    list_artifacts,
    load_index,
    make_id,
    prune_missing,
    reconcile,
    record_artifact,
)

__all__ = [
    "ArtifactEntry",
    "ArtifactView",
    "ArtifactsIndex",
    "ArtifactsIndexWriter",
    "delete_artifact",
    "get_artifact",
    "list_artifacts",
    "load_index",
    "make_id",
    "prune_missing",
    "reconcile",
    "record_artifact",
]
