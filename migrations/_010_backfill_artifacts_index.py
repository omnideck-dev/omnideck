"""Backfill the artifacts index from existing conversation event logs.

Scans every ``{state_dir}/conversations/<id>/events.jsonl`` for file_output
events, records each into the artifacts index, then prunes the entries whose
file no longer exists. Most historical sends point at files long since deleted
or overwritten; we don't want those as dead entries, and (unlike the live
reconcile) there is no existing entry to preserve, so dropping them loses
nothing. We reuse the store's own prune rather than a migration-only existence
check.

Idempotent: record_artifact upserts by (conversation_id, path) and the final
prune is deterministic, so a re-run yields the same index.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from artifacts import load_index, prune_missing, record_artifact

logger = logging.getLogger(__name__)


def _index_conversation(conversation_id: str, events_path: Path) -> int:
    """Record the file_output events of one conversation. Returns count recorded.

    Events are read in append (chronological) order, so the first send of a
    given path sets created_at and the last sets updated_at.
    """
    recorded = 0
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "file_output":
            continue
        path = event.get("path")
        if not path:
            continue
        record_artifact(
            conversation_id=conversation_id,
            path=path,
            filename=event.get("filename") or Path(path).name,
            content_type=event.get("content_type") or "application/octet-stream",
            agent_name=event.get("agent_name"),
            sent_at=event.get("timestamp") or "",
        )
        recorded += 1
    return recorded


def migrate(state_dir: Path) -> None:
    """Build the artifacts index from existing conversations under state_dir."""
    conv_root = state_dir / "conversations"
    if not conv_root.is_dir():
        return
    recorded = 0
    for conv_dir in sorted(conv_root.iterdir()):
        events_path = conv_dir / "events.jsonl"
        if not events_path.is_file():
            continue
        recorded += _index_conversation(conv_dir.name, events_path)
    # Drop entries whose file is already gone (reuses the feature's prune).
    pruned = prune_missing()
    indexed = len(load_index().artifacts)
    logger.info(
        "Backfill: %d file_output event(s) -> %d artifact(s) indexed, %d pruned as missing",
        recorded, indexed, pruned,
    )
