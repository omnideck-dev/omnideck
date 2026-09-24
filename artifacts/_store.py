"""Persistent index of files agents emit as file_output events.

Sources today: the send_file tool (home-dir enforced) and the image/music
generation tools (home-dir by convention).


The index lives in the state folder, outside the per-conversation directories,
so artifacts survive deletion of their source conversation. It is the only
record that a file was ever an artifact (artifact-ness can't be recovered from
disk), so reconcile-on-read never deletes — it overlays a present/missing
status and leaves removal to explicit user actions (delete / prune).

Writes are a read-modify-write of one JSON file with an atomic temp-file +
rename. The index writer is a synchronous event observer, so the event loop
serializes writes and no locking is needed.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from config import load_config

from ._models import ArtifactEntry, ArtifactsIndex, ArtifactView

logger = logging.getLogger(__name__)


def _artifacts_dir() -> Path:
    return Path(load_config().settings.home_dir) / "artifacts"


def _index_path() -> Path:
    return _artifacts_dir() / "index.json"


def _vc_home() -> Path:
    return Path(load_config().virtual_computer.home_dir).resolve()


def make_id(conversation_id: str, path: str) -> str:
    """Stable id for an artifact, keyed by conversation + path.

    Deterministic, so re-sending the same path — or re-running the backfill —
    updates the one entry instead of creating duplicates.
    """
    digest = hashlib.sha256(f"{conversation_id}\x00{path}".encode("utf-8")).hexdigest()
    return digest[:16]


def _resolve_under_home(path: str) -> Path | None:
    """Resolve an artifact path under the virtual-computer home dir.

    Returns None if it escapes the home dir — the same guard the file route
    uses, so a poisoned path can't be statted or unlinked outside the sandbox.
    """
    home = _vc_home()
    resolved = (home / path).resolve()
    if not resolved.is_relative_to(home):
        return None
    return resolved


def _file_exists(path: str) -> bool:
    # Servable is the bar: a path that escapes the home dir resolves to None and
    # counts as not existing, since the UI couldn't serve it anyway.
    resolved = _resolve_under_home(path)
    return bool(resolved and resolved.is_file())


def load_index() -> ArtifactsIndex:
    """Load the index, returning an empty one if it's absent or unreadable."""
    path = _index_path()
    if not path.exists():
        return ArtifactsIndex()
    try:
        return ArtifactsIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Artifacts index unreadable at %s; starting empty", path)
        return ArtifactsIndex()


def _save_index(index: ArtifactsIndex) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(index.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def record_artifact(
    *,
    conversation_id: str,
    path: str,
    filename: str,
    content_type: str,
    agent_name: str | None,
    sent_at: str,
) -> ArtifactEntry:
    """Upsert an artifact by (conversation_id, path).

    ``sent_at`` is when this send happened (the file_output event's timestamp).
    First sight sets created_at to it; every send sets updated_at to it and
    refreshes the display fields. Returns the stored entry.
    """
    index = load_index()
    artifact_id = make_id(conversation_id, path)
    existing = index.artifacts.get(artifact_id)
    entry = ArtifactEntry(
        id=artifact_id,
        conversation_id=conversation_id,
        path=path,
        filename=filename,
        content_type=content_type,
        agent_name=agent_name,
        created_at=existing.created_at if existing else sent_at,
        updated_at=sent_at,
    )
    index.artifacts[artifact_id] = entry
    _save_index(index)
    return entry


def list_artifacts(conversation_id: str | None = None) -> list[ArtifactEntry]:
    """List indexed artifacts (optionally one conversation's), newest first."""
    index = load_index()
    entries = list(index.artifacts.values())
    if conversation_id is not None:
        entries = [e for e in entries if e.conversation_id == conversation_id]
    entries.sort(key=lambda e: e.updated_at, reverse=True)
    return entries


def get_artifact(artifact_id: str) -> ArtifactEntry | None:
    """Return one indexed artifact by its stable id."""
    return load_index().artifacts.get(artifact_id)


def reconcile(entries: list[ArtifactEntry]) -> list[ArtifactView]:
    """Overlay live on-disk status onto entries. Pure — never mutates the store."""
    return [
        ArtifactView(
            **entry.model_dump(),
            status="present" if _file_exists(entry.path) else "missing",
        )
        for entry in entries
    ]


def delete_artifact(artifact_id: str, *, delete_file: bool = False) -> bool:
    """Remove one artifact from the index; optionally unlink its file.

    Returns True if an entry was removed. File deletion is guarded to the
    virtual-computer home dir and best-effort (an already-gone file is fine).
    """
    index = load_index()
    entry = index.artifacts.pop(artifact_id, None)
    if entry is None:
        return False
    if delete_file:
        resolved = _resolve_under_home(entry.path)
        if resolved and resolved.is_file():
            try:
                resolved.unlink()
            except OSError:
                logger.exception("Failed to delete artifact file %s", resolved)
    _save_index(index)
    return True


def prune_missing(conversation_id: str | None = None) -> int:
    """Remove entries whose file is gone from disk. Returns the count removed."""
    index = load_index()
    stale = [
        aid
        for aid, entry in index.artifacts.items()
        if (conversation_id is None or entry.conversation_id == conversation_id)
        and not _file_exists(entry.path)
    ]
    for aid in stale:
        del index.artifacts[aid]
    if stale:
        _save_index(index)
    return len(stale)
