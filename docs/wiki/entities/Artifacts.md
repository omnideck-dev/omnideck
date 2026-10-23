---
title: Artifacts
type: entity
tags: [artifacts, files, index, persistence]
created: 2026-10-18
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "artifacts/"
---

# Artifacts

## Overview

A persistent catalog of files an agent has produced and explicitly sent out via the
`send_file` tool (or, by convention, the image/music generation tools) — not every file
the agent writes to its workspace, only ones it has handed to the user. The index exists
because artifact-ness is otherwise unrecoverable from disk: once a file is indexed, it
survives deletion of the conversation that produced it, and the index is the only
record that the file was ever significant.

## Location

`artifacts/` package.

## Details

| Model | Role |
|-------|------|
| `ArtifactEntry` | One indexed file, keyed by `make_id(conversation_id, path)` — a stable SHA-256-derived id, so re-sending the same path (or re-running a backfill) updates one entry instead of duplicating it. Carries `conversation_id`, `path`, `filename`, `content_type`, `agent_name`, `created_at`/`updated_at`. |
| `ArtifactView` | `ArtifactEntry` plus two read-time-only overlays: `status` (`present`/`missing`, computed by checking the file on disk) and `conversation_title` (joined from the live conversation, or `None` if it no longer exists). Neither field is persisted. |
| `ArtifactsIndex` | The whole store: `{version, artifacts: {id: ArtifactEntry}}`, persisted as one JSON file at `{home_dir}/artifacts/index.json`. |

Key operations (`artifacts/_store.py`):

- `record_artifact(...)` — upsert by `(conversation_id, path)`; first sight sets `created_at`, every send refreshes `updated_at` and display fields.
- `list_artifacts(conversation_id=None)` — newest-first, optionally scoped to one conversation.
- `reconcile(entries)` — pure function overlaying live on-disk presence onto entries; never mutates the store, so listing never silently drops a file's history.
- `delete_artifact(id, delete_file=False)` — remove from the index, optionally unlink the file (best-effort; guarded to resolve under the virtual-computer home dir).
- `prune_missing(conversation_id=None)` — remove entries whose backing file is gone; returns the count removed.

`ArtifactsIndexWriter` (`_index_writer.py`) is a synchronous event observer — it runs on
the event loop thread, so the read-modify-write JSON cycle needs no explicit locking.

Path safety: every path is resolved against the virtual-computer home dir
(`AppConfig.virtual_computer.home_dir`) and rejected if it would escape that root —
the same guard the artifact-serving HTTP route uses, so a crafted path can't be statted
or unlinked outside the sandbox.

## Related Entities

- [[Task Engine]] — `TaskResult.file_outputs` references artifact paths produced by routine runs
- [[Tool Architecture]] — `send_file` and the generation tools are what populate this index

## Sources

- `migrations/_010_backfill_artifacts_index.py` — backfilled the index for files that predated it
