"""Migration 007: events-first persistence.

Collapses the per-conversation ``history.json`` / ``events.json`` /
``summaries/*.json`` / ``sub_agents/*.json`` files into a single
append-only ``events.jsonl`` log per conversation. ``metadata.json``
is preserved untouched.

After this migration, ``events.jsonl`` is the source of truth for
conversation state. The old files are archived under
``{state_dir}/.backups/007_events_first/conversations/{conv_id}/`` and
can be deleted at any time.

Entry point: ``migrate(state_dir)`` scans
``{state_dir}/conversations/`` and migrates each conversation that
hasn't already been converted (idempotent — skipped when
``events.jsonl`` already exists).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from migrations._screenshot_prune import latest_tab_snapshots
from migrations._terminal_collapse import merge_terminal_transcripts

logger = logging.getLogger(__name__)

# Same constants used by the compaction strategy. Kept in sync with
# agent_runtime/_compaction.py; if those change there, update here.
_SUMMARY_PREFIX = "[Conversation summary — earlier messages were compacted]\n\n"
_INTENT_PREFIX = "[User intent history]\n"
# Same chars/token approximation the live strategy and view layer use.
_CHARS_PER_TOKEN = 4

# Augmentation footer added by _augment_message_with_attachments. We parse
# the user message content to extract the original text + attachment list.
_AUG_MARKER = "\n\n[Attached files written to virtual computer]\n"
_AUG_LINE_RE = re.compile(r"^  - (.+?) \((.+?)\) -> (.+)$")


# ──────────────────────────────────────────────────────────────────────
# Data classes — internal to the migration. The final events.jsonl uses
# plain dicts; these wrappers exist for clarity during reconstruction.
# ──────────────────────────────────────────────────────────────────────


@dataclass
class Event:
    """A single event ready to write to events.jsonl."""
    id: str
    type: str
    timestamp: str
    conversation_id: str
    agent_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        # depth + parent_agent_id are derived from the dotted agent_id so
        # every event carries the same envelope shape the live runtime
        # emits. Without depth, the UI's depth>0 sub-agent filter can't
        # hide sub-agent traffic and it leaks into the main chat.
        out = {
            "id": self.id,
            "type": self.type,
            "timestamp": self.timestamp,
            "conversation_id": self.conversation_id,
            "agent_id": self.agent_id,
            **self.payload,
            # Derived last so they're authoritative over any stale value a
            # spread payload carried in from the source record.
            "depth": _depth_from_agent_id(self.agent_id),
        }
        if self.type == "agent_started":
            out["parent_agent_id"] = _parent_id_from_agent_id(self.agent_id)
        return out


@dataclass
class MigrationResult:
    """Outcome of migrating one conversation."""
    conv_id: str
    events_written: int
    compaction_events: int
    sub_agents_migrated: int
    attachments_recovered: int
    warnings: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex}"


def _new_round_id() -> str:
    return f"round_{uuid.uuid4().hex[:12]}"


# Trailing timezone marker: ``Z``, ``+HH:MM`` / ``-HH:MM``, or
# ``+HHMM`` / ``-HHMM``. Anchored to end-of-string so a literal ``-``
# inside the date (``2026-06-01``) is never matched.
_TZ_SUFFIX_RE = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def _parse_iso(ts: str) -> datetime:
    """Parse ISO-8601 timestamp (with or without timezone).

    Naive timestamps in legacy files came from ``datetime.utcnow()``
    and are actually UTC — attach ``tzinfo`` so downstream comparisons
    and formatted output stay consistent.

    The recovery branch handles oddly-formatted strings by stripping
    the timezone suffix before re-parsing (then re-attaching UTC).
    Splitting on ``+`` or ``-`` directly would mangle negative-offset
    timestamps like ``2026-06-01T16:28:03-05:00``, so the suffix gets
    matched by regex anchored to the end of the string.
    """
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        stripped = _TZ_SUFFIX_RE.sub("", ts)
        dt = datetime.fromisoformat(stripped)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_iso(dt: datetime) -> str:
    """Render *dt* as ISO-8601, always with a timezone marker."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _offset_ts(anchor: datetime, micros: int) -> str:
    """Anchor + N microseconds. Used to give synthesized events ordering."""
    return _fmt_iso(anchor + timedelta(microseconds=micros))


def _norm_ts(ts: str | None) -> str:
    """Normalize any source timestamp to tz-aware ISO.

    Some legacy timestamps are naive; routing them through parse+format
    attaches UTC and makes the whole log uniformly tz-aware so the final
    chronological sort compares like instants. A missing timestamp
    anchors to the epoch (deterministic, sorts to the front) rather than
    an unparseable empty string.
    """
    if not ts:
        return _fmt_iso(datetime.fromtimestamp(0, tz=timezone.utc))
    return _fmt_iso(_parse_iso(ts))


def _depth_from_agent_id(agent_id: str) -> int:
    """Derive nesting depth from a dotted agent_id.

    Ids look like ``root.<name>.<n>[.<name>.<n>...]`` — each name/counter
    pair past ``root`` is one level, so a single pair is the depth-0 root
    and each additional pair is a sub-agent level.
    """
    pairs = max(0, (len(agent_id.split(".")) - 1) // 2)
    return max(0, pairs - 1)


def _parent_id_from_agent_id(agent_id: str) -> str | None:
    """The parent agent's id: *agent_id* with its trailing name/counter
    pair removed. Returns None for a depth-0 root (no parent)."""
    parts = agent_id.split(".")
    if len(parts) <= 3:
        return None
    return ".".join(parts[:-2])


def parse_augmented_user_content(content: str) -> tuple[str, list[dict[str, str]]]:
    """Reverse _augment_message_with_attachments. Returns (original_text, attachments).

    The augmentation footer is appended to the user's typed text. If we don't
    detect it, return content unchanged + empty attachments.
    """
    if _AUG_MARKER not in content:
        return content, []
    head, _, rest = content.partition(_AUG_MARKER)
    attachments: list[dict[str, str]] = []
    for line in rest.splitlines():
        m = _AUG_LINE_RE.match(line)
        if m:
            attachments.append({
                "filename": m.group(1),
                "content_type": m.group(2),
                "path": m.group(3),
            })
    # If we found no valid lines, the marker was a false positive — keep original.
    if not attachments:
        return content, []
    return head, attachments


# ──────────────────────────────────────────────────────────────────────
# Phase 0: I/O — read everything off disk
# ──────────────────────────────────────────────────────────────────────


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load %s", path)
        return None


def _file_mtime_iso(path: Path) -> str:
    """Return ISO-format UTC mtime of *path*, or 'now' if it doesn't exist."""
    if not path.exists():
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _load_summary_records(summaries_dir: Path) -> list[dict[str, Any]]:
    if not summaries_dir.is_dir():
        return []
    records = []
    for p in summaries_dir.glob("*.json"):
        rec = _load_json(p)
        if rec is not None:
            records.append(rec)
    records.sort(key=lambda r: r.get("created_at", ""))
    return records


def _load_sub_agent_histories(sub_agents_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Returns {sub_agent_filename_stem: [messages]}."""
    if not sub_agents_dir.is_dir():
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for p in sub_agents_dir.glob("*.json"):
        msgs = _load_json(p)
        if isinstance(msgs, list):
            out[p.stem] = msgs
    return out


# ──────────────────────────────────────────────────────────────────────
# Phase 1: reconstruct pre-compaction history for the root agent
# ──────────────────────────────────────────────────────────────────────


def reconstruct_full_history(
    current_msgs: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, str | None]]:
    """Expand summary markers in current_msgs back into the original messages.

    Returns:
        full_msgs: the reconstructed message list with no summary markers
        msg_to_record_id: map from index in full_msgs → summary record id
            that "owned" this message (if it was originally compacted out).
            Used in phase 2 to compute covers_start_id/end_id.
    """
    msgs = list(current_msgs)
    msg_to_record_id: dict[int, str | None] = {i: None for i in range(len(msgs))}

    # Build a quick lookup of records by their summary_text for marker matching.
    records_by_text = {r.get("summary_text", ""): r for r in records}

    # Track whether we actually matched and expanded any markers. If not
    # (orphan summary records, e.g. the conversation got "restarted" within
    # the same id without removing the old records), don't restore the pin —
    # the records describe an earlier state that no longer matches.
    any_expanded = False

    # Iterate: each pass replaces any summary marker we can match. Repeat
    # until no replacements happen (handles chained summaries).
    changed = True
    while changed:
        changed = False
        new_msgs: list[dict[str, Any]] = []
        new_map: dict[int, str | None] = {}
        for i, m in enumerate(msgs):
            content = m.get("content") or ""
            if (m.get("role") in ("assistant", "user")) and content.startswith(_SUMMARY_PREFIX):
                marker_text = content[len(_SUMMARY_PREFIX):]
                record = records_by_text.get(marker_text)
                if record is None:
                    # Unmatched marker — keep as-is, this preserves data even if
                    # something's drifted. Log a warning later.
                    new_idx = len(new_msgs)
                    new_msgs.append(m)
                    new_map[new_idx] = msg_to_record_id.get(i)
                    continue
                # Expand: insert input_messages here.
                # Skip messages inside that are themselves summary markers — they'll
                # be expanded on a subsequent pass.
                for sub in record.get("input_messages", []):
                    new_idx = len(new_msgs)
                    new_msgs.append(sub)
                    new_map[new_idx] = record["id"]
                changed = True
                any_expanded = True
            else:
                new_idx = len(new_msgs)
                new_msgs.append(m)
                new_map[new_idx] = msg_to_record_id.get(i)
        msgs = new_msgs
        msg_to_record_id = new_map

    # Restore the pinned user message to the absolute original if available.
    # Only when we actually expanded a marker — otherwise the records are
    # orphans and the current conversation's pin is unrelated to them.
    earliest = records[0] if (records and any_expanded) else None
    if earliest:
        original_pin = earliest.get("user_message_pre_compaction")
        if original_pin:
            for i, m in enumerate(msgs):
                if m.get("role") == "user":
                    content = m.get("content") or ""
                    # Restore if the pin was mutated (intent prefix or differs from original).
                    if content.startswith(_INTENT_PREFIX) or content != original_pin:
                        msgs[i] = {**m, "content": original_pin}
                    break

    return msgs, msg_to_record_id


# ──────────────────────────────────────────────────────────────────────
# Phase 2: synthesize events for an agent's message history
# ──────────────────────────────────────────────────────────────────────


def _find_root_agent_starts(events_old: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return root (no parent) agent_started events sorted by timestamp."""
    out = [
        e for e in events_old
        if e.get("type") == "agent_started" and not e.get("parent_agent_id")
    ]
    out.sort(key=lambda e: e.get("timestamp", ""))
    return out


def _find_sub_agent_started(
    events_old: list[dict[str, Any]],
    agent_id: str,
) -> dict[str, Any] | None:
    """First agent_started for the given sub-agent id."""
    for e in events_old:
        if e.get("type") == "agent_started" and e.get("agent_id") == agent_id:
            return e
    return None


def _find_agent_completed(
    events_old: list[dict[str, Any]],
    agent_id: str,
    after_ts: str,
) -> dict[str, Any] | None:
    for e in events_old:
        if (
            e.get("type") == "agent_completed"
            and e.get("agent_id") == agent_id
            and e.get("timestamp", "") >= after_ts
        ):
            return e
    return None


def synthesize_agent_events(
    msgs: list[dict[str, Any]],
    conversation_id: str,
    turn_anchors: list[dict[str, Any]],
    fallback_agent_id: str,
    fallback_agent_name: str,
    msg_to_record_id: dict[int, str | None] | None = None,
) -> tuple[list[Event], dict[str, str | None], list[str]]:
    """Walk msgs in order, emit events anchored to turn_anchors.

    Each turn in msgs gets its agent_id from the corresponding turn_anchor
    (each turn has its own root agent in the legacy data, e.g. root.computron.5
    for turn 5). When more turns appear in msgs than anchors are available,
    fall back to fallback_agent_id with synthesized timestamps.

    For sub-agents: pass a single-anchor turn_anchors list and the sub-agent's
    id/name as fallback. All msgs get tagged to that one agent.

    Returns:
        events: list[Event] in chronological order
        event_id_to_record_id: per-event record-id ownership (for phase 3)
        warnings: list of human-readable warning strings
    """
    events: list[Event] = []
    event_id_to_record_id: dict[str, str | None] = {}
    warnings: list[str] = []

    if msg_to_record_id is None:
        msg_to_record_id = {}

    turn_idx = -1
    seq = 0
    current_anchor: datetime | None = None
    current_agent_id: str = fallback_agent_id
    current_agent_name: str = fallback_agent_name

    def emit(event: Event, record_id: str | None) -> Event:
        nonlocal seq
        events.append(event)
        event_id_to_record_id[event.id] = record_id
        seq += 1
        return event

    def open_turn(record_id: str | None) -> None:
        nonlocal turn_idx, seq, current_anchor, current_agent_id, current_agent_name
        turn_idx += 1
        seq = 0
        if turn_idx < len(turn_anchors):
            anchor_event = turn_anchors[turn_idx]
            current_anchor = _parse_iso(anchor_event["timestamp"])
            current_agent_id = anchor_event.get("agent_id") or fallback_agent_id
            current_agent_name = anchor_event.get("agent_name") or fallback_agent_name
            emit(
                Event(
                    id=_new_event_id(),
                    type="agent_started",
                    timestamp=_norm_ts(anchor_event.get("timestamp")),
                    conversation_id=conversation_id,
                    agent_id=current_agent_id,
                    payload={
                        "agent_name": current_agent_name,
                        "parent_agent_id": anchor_event.get("parent_agent_id"),
                        "correlation_id": anchor_event.get("correlation_id"),
                        "instruction": anchor_event.get("instruction") or "",
                    },
                ),
                record_id,
            )
        else:
            # More turns in msgs than agent_started events in events.json.
            # Synthesize a UNIQUE fallback agent_id per turn (live emission
            # always produces a fresh agent_id per turn; migration should
            # mimic that or build_llm_view sees duplicate agent_completed
            # events for the same id, which violates live-emission invariants).
            warnings.append(
                f"Turn {turn_idx} has no matching agent_started in events.json; "
                f"using synthesized timestamp."
            )
            if current_anchor is None:
                current_anchor = datetime.fromtimestamp(0, tz=timezone.utc)
            current_anchor = current_anchor + timedelta(seconds=1)
            # Inherit name + parent from the last real anchor; mint a unique id.
            template = turn_anchors[-1] if turn_anchors else None
            parent_aid = template.get("parent_agent_id") if template else None
            base_name = (template.get("agent_name") if template else fallback_agent_name) or fallback_agent_name
            base_id = (template.get("agent_id") if template else fallback_agent_id) or fallback_agent_id
            current_agent_id = f"{base_id}__migrated_synth_{turn_idx}"
            current_agent_name = base_name
            emit(
                Event(
                    id=_new_event_id(),
                    type="agent_started",
                    timestamp=_fmt_iso(current_anchor),
                    conversation_id=conversation_id,
                    agent_id=current_agent_id,
                    payload={
                        "agent_name": current_agent_name,
                        "parent_agent_id": parent_aid,
                        "correlation_id": None,
                        "instruction": "",
                    },
                ),
                record_id,
            )

    def close_turn(record_id: str | None) -> None:
        nonlocal current_anchor
        if current_anchor is None:
            return
        emit(
            Event(
                id=_new_event_id(),
                type="agent_completed",
                timestamp=_offset_ts(current_anchor, seq + 1),
                conversation_id=conversation_id,
                agent_id=current_agent_id,
                payload={"agent_name": current_agent_name, "status": "success"},
            ),
            record_id,
        )

    prev_role: str | None = None
    iteration_index: int = -1  # bumped to 0 on first iteration of each turn

    for i, m in enumerate(msgs):
        role = m.get("role")
        record_id = msg_to_record_id.get(i)

        if role == "system":
            continue

        if role == "user":
            # Only open a new turn when transitioning from non-user to user.
            # Consecutive user messages (rare — e.g. UI retries) stay within
                # the same turn so we don't burn through turn_anchors prematurely.
            if prev_role is not None and prev_role != "user":
                close_turn(msg_to_record_id.get(i - 1) if i > 0 else None)
                open_turn(record_id)
                iteration_index = -1
            elif prev_role is None:
                open_turn(record_id)
                iteration_index = -1
            content, attachments = parse_augmented_user_content(m.get("content") or "")
            emit(
                Event(
                    id=_new_event_id(),
                    type="user_message",
                    timestamp=_offset_ts(current_anchor or datetime.fromtimestamp(0, tz=timezone.utc), seq),
                    conversation_id=conversation_id,
                    agent_id=current_agent_id,
                    payload={"content": content, "attachments": attachments},
                ),
                record_id,
            )

        elif role == "assistant":
            if current_anchor is None:
                open_turn(record_id)
            content = m.get("content") or ""
            if content.startswith(_SUMMARY_PREFIX):
                warnings.append(
                    f"Unmatched summary marker at msg index {i}; skipping (events not synthesized)."
                )
                continue
            # Bundle thinking + content + tool_calls into one iteration event.
            thinking = m.get("thinking") or ""
            tool_calls_out = []
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"_raw": args}
                tool_calls_out.append({
                    "id": tc.get("id"),   # preserve None faithfully
                    "name": fn.get("name") or "",
                    "arguments": args or {},
                })
            iteration_index += 1
            emit(
                Event(
                    id=_new_event_id(),
                    type="iteration",
                    timestamp=_offset_ts(current_anchor, seq),
                    conversation_id=conversation_id,
                    agent_id=current_agent_id,
                    payload={
                        "iteration_index": iteration_index,
                        "thinking": thinking or None,
                        "content": content or None,
                        "tool_calls": tool_calls_out,
                    },
                ),
                record_id,
            )

        elif role == "tool":
            if current_anchor is None:
                continue
            emit(
                Event(
                    id=_new_event_id(),
                    type="tool_result",
                    timestamp=_offset_ts(current_anchor, seq),
                    conversation_id=conversation_id,
                    agent_id=current_agent_id,
                    payload={
                        "tool_call_id": m.get("tool_call_id") or "",
                        "tool_name": m.get("tool_name") or "",
                        "content": m.get("content") or "",
                    },
                ),
                record_id,
            )

        prev_role = role

    if prev_role is not None:
        close_turn(msg_to_record_id.get(len(msgs) - 1) if msgs else None)

    return events, event_id_to_record_id, warnings


# ──────────────────────────────────────────────────────────────────────
# Phase 3: synthesize compaction events from summary records
# ──────────────────────────────────────────────────────────────────────


def _scope_for_compacted_range(
    compacted: list[Event],
) -> dict[str, int]:
    """Count what a compaction summarized.

    Mirrors what the live ``LLMCompactionStrategy._compute_stats`` records
    on a fresh compaction so migrated and live chips read the same fields.
    """
    return {
        "user_messages": sum(1 for e in compacted if e.type == "user_message"),
        "iterations": sum(1 for e in compacted if e.type == "iteration"),
        "tool_results": sum(1 for e in compacted if e.type == "tool_result"),
    }


def synthesize_compaction_events(
    records: list[dict[str, Any]],
    conversation_id: str,
    agent_id: str,
    event_id_to_record_id: dict[str, str | None],
    all_events_in_order: list[Event],
) -> list[Event]:
    """For each summary record, emit a CompactionPayload with the new shape:
    kept_from_id (first kept event at that compaction's moment), kept_to_id
    (last event in the log at that compaction's moment), summary_text,
    pinned_user_override, and audit. Only the latest is consulted at
    LLM-build time; older ones are audit-only.

    Each record's kept_from_id is the FIRST non-record event id chronologically
    after this record's last owned event (the start of the recent-kept group
    at the time it fired). kept_to_id is the most recent event in the log up
    to the moment this compaction fires — approximated as the LAST owned event
    overall before this record's created_at. For migration we simplify: use
    the last event that was owned by THIS or any prior record as kept_to_id,
    since the kept-recent boundary at fire time was right after.
    """
    events: list[Event] = []

    by_record: dict[str, list[str]] = {}
    for evt_id, rec_id in event_id_to_record_id.items():
        if rec_id:
            by_record.setdefault(rec_id, []).append(evt_id)

    sorted_records = sorted(records, key=lambda r: r.get("created_at", ""))

    # Build an index from event_id -> position to find the "next event after"
    # for each compaction.
    id_to_index = {ev.id: i for i, ev in enumerate(all_events_in_order)}

    # Track which events have been claimed by earlier compactions so a
    # later compaction's scope doesn't double-count them.
    consumed_up_to_idx = -1

    for record in sorted_records:
        rid = record.get("id") or ""
        owned = by_record.get(rid, [])
        if not owned:
            continue
        # kept_from_id: first event after this record's last owned event.
        last_owned = owned[-1]
        last_idx = id_to_index.get(last_owned)
        if last_idx is None or last_idx + 1 >= len(all_events_in_order):
            kept_from = last_owned
            kept_to = last_owned
            kept_from_idx = last_idx if last_idx is not None else len(all_events_in_order)
        else:
            kept_from = all_events_in_order[last_idx + 1].id
            # kept_to_id: the most recent event in the log at the time
            # this compaction fired. For migration we use the last event
            # that any record (this or prior) owned, since real-time kept
            # group is right after the compacted range.
            # Simpler approximation: use the last event ID before the next
            # record's first owned id, or last in log.
            kept_to = all_events_in_order[-1].id
            kept_from_idx = last_idx + 1

        # Scope = events strictly after the previous compaction's range and
        # before this compaction's kept_from_id. Match the live strategy's
        # CompactionStats shape so chips read the same fields regardless
        # of provenance.
        compacted_slice = all_events_in_order[consumed_up_to_idx + 1:kept_from_idx]
        scope = _scope_for_compacted_range(compacted_slice)
        summary_text = record.get("summary_text") or ""
        events.append(
            Event(
                id=_new_event_id(),
                type="compaction",
                timestamp=_norm_ts(record.get("created_at")),
                conversation_id=conversation_id,
                agent_id=agent_id,
                payload={
                    "kept_from_id": kept_from,
                    "kept_to_id": kept_to,
                    "summary_text": summary_text,
                    "user_intent_summary": record.get("user_message_post_compaction"),
                    "audit": {
                        "model": record.get("model") or "",
                        "input_char_count": record.get("input_char_count") or 0,
                        "elapsed_seconds": record.get("elapsed_seconds"),
                    },
                    "stats": {
                        "scope": scope,
                        "summary_chars": len(summary_text),
                        "summary_tokens": len(summary_text) // _CHARS_PER_TOKEN,
                        "summary_lines": (
                            summary_text.count("\n") + 1 if summary_text else 0
                        ),
                    },
                },
            )
        )
        consumed_up_to_idx = kept_from_idx - 1
    return events


# ──────────────────────────────────────────────────────────────────────
# Phase 4: merge structural events (file_output)
# ──────────────────────────────────────────────────────────────────────


# browser_screenshot and terminal_output are intentionally NOT carried into
# events.jsonl: the UI only shows the latest snapshot per tab and the last N
# terminal commands, so both would bloat the append-only log forever. They
# collapse into the bounded browser_tabs.json / terminal.json sidecars
# instead (see migrate_conversation).
_STRUCTURAL_TYPES = {"file_output"}


def synthesize_structural_events(
    events_old: list[dict[str, Any]], conversation_id: str,
) -> list[Event]:
    """Carry over file_output events from the old format. These
    already had timestamps and agent_ids."""
    out: list[Event] = []
    for e in events_old:
        if e.get("type") not in _STRUCTURAL_TYPES:
            continue
        payload = {k: v for k, v in e.items() if k not in ("type", "timestamp", "agent_id")}
        out.append(
            Event(
                id=_new_event_id(),
                type=e["type"],
                timestamp=_norm_ts(e.get("timestamp")),
                conversation_id=conversation_id,
                agent_id=e.get("agent_id") or "",
                payload=payload,
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────
# Top-level orchestration
# ──────────────────────────────────────────────────────────────────────


def _first_user_event_id(events: list[Event]) -> str | None:
    for e in events:
        if e.type == "user_message":
            return e.id
    return None


def migrate_conversation(
    conv_dir: Path,
    archive: Callable[[Path], None] | None = None,
) -> MigrationResult:
    """Migrate one conversation directory to events-first.

    Reads history.json, events.json (legacy), summaries/*.json, sub_agents/*.json.
    Writes events.jsonl. Archives the old files (renamed *.bak / sub_agents.bak/).
    Idempotent: if events.jsonl already exists, returns a no-op result.
    """
    conv_id = conv_dir.name
    result = MigrationResult(conv_id=conv_id, events_written=0,
                              compaction_events=0, sub_agents_migrated=0,
                              attachments_recovered=0)

    out_path = conv_dir / "events.jsonl"
    if out_path.exists():
        result.warnings.append(f"{out_path.name} already exists; skipping migration.")
        return result

    history = _load_json(conv_dir / "history.json") or []
    events_old = _load_json(conv_dir / "events.json") or []
    records = _load_summary_records(conv_dir / "summaries")
    sub_agents = _load_sub_agent_histories(conv_dir / "sub_agents")

    if not history and not events_old:
        result.warnings.append("Nothing to migrate (no history.json or events.json).")
        return result

    # Root agent fallback identity from the FIRST root agent_started.
    root_starts = _find_root_agent_starts(events_old)
    if not root_starts:
        # Old conversations sometimes have history.json but no events.json
        # (pre-lifecycle-events era). Synthesize a single root agent_started
        # bracketing the whole history so reconstruction can proceed.
        if history:
            anchor_ts = _file_mtime_iso(conv_dir / "history.json")
            synthesized = {
                "type": "agent_started",
                "agent_id": "root.computron.1",
                "agent_name": "COMPUTRON",
                "parent_agent_id": None,
                "timestamp": anchor_ts,
            }
            events_old = [synthesized, *events_old]
            root_starts = [synthesized]
            result.warnings.append(
                "Synthesized root agent_started — original events.json missing."
            )
        else:
            result.warnings.append("No root agent_started found; cannot anchor turns. Aborting.")
            return result
    fallback_root_id = root_starts[0]["agent_id"]
    fallback_root_name = root_starts[0].get("agent_name") or "AGENT"

    # Split summary records by which agent they belong to (via source_history).
    # Sub-agent records have source_history = "{conv_id}/{NAME}_{shortid}".
    # Root records have source_history = conversation_id (or empty).
    sub_records_by_stem: dict[str, list[dict[str, Any]]] = {}
    root_records: list[dict[str, Any]] = []
    for r in records:
        sh = r.get("source_history", "")
        # If source_history has a "/", the part after is the sub-agent stem.
        if "/" in sh:
            stem = sh.rsplit("/", 1)[1]
            sub_records_by_stem.setdefault(stem, []).append(r)
        else:
            root_records.append(r)

    # Phase 1: reconstruct full pre-compaction message list (ROOT only).
    full_msgs, msg_to_record_id = reconstruct_full_history(history, root_records)

    # Phase 2: synthesize per-message events. Each turn's anchor brings its
    # own agent_id (each turn = a fresh root span in the agent core today).
    root_events, evt_to_rec, warns = synthesize_agent_events(
        full_msgs, conv_id, root_starts, fallback_root_id, fallback_root_name, msg_to_record_id,
    )
    result.warnings.extend(warns)
    result.attachments_recovered = sum(
        1 for e in root_events if e.type == "user_message" and e.payload.get("attachments")
    )

    # Phase 3: root compaction events. Tagged with the fallback (first) root
    # agent_id — compaction is logically per-conversation, not per-turn.
    compaction_events = synthesize_compaction_events(
        root_records, conv_id, fallback_root_id, evt_to_rec, root_events,
    )
    result.compaction_events = len(compaction_events)

    # Phase 4: structural events (file/browser/terminal).
    structural = synthesize_structural_events(events_old, conv_id)

    # Phase 5: sub-agents. For each sub-agent: reconstruct its full pre-
    # compaction message list (expanding any summary markers via its own
    # records), synthesize events, then emit compaction events tagged with
    # the sub-agent's agent_id.
    sub_agent_events: list[Event] = []
    sub_compaction_events: list[Event] = []
    for stem, sub_msgs in sub_agents.items():
        sub_id = _infer_sub_agent_id(stem, events_old)
        if not sub_id:
            result.warnings.append(f"Sub-agent {stem}: no matching agent_started in events.json; skipping.")
            continue
        sub_start = _find_sub_agent_started(events_old, sub_id)
        if sub_start is None:
            result.warnings.append(f"Sub-agent {stem}: no agent_started; skipping.")
            continue

        # Reconstruct full sub-agent message list using this sub-agent's records.
        my_records = sub_records_by_stem.get(stem, [])
        sub_full_msgs, sub_msg_to_record_id = reconstruct_full_history(sub_msgs, my_records)

        sub_events, sub_evt_to_rec, sub_warns = synthesize_agent_events(
            sub_full_msgs, conv_id, [sub_start], sub_id,
            sub_start.get("agent_name") or stem, sub_msg_to_record_id,
        )
        result.warnings.extend(sub_warns)
        sub_agent_events.extend(sub_events)
        result.sub_agents_migrated += 1

        # Emit sub-agent compaction events (tagged with the sub-agent's agent_id).
        if my_records:
            sub_comps = synthesize_compaction_events(
                my_records, conv_id, sub_id, sub_evt_to_rec, sub_events,
            )
            sub_compaction_events.extend(sub_comps)
            result.compaction_events += len(sub_comps)

    # Combine all events and sort chronologically. Parse to instants so a
    # mix of naive and tz-aware source timestamps compares correctly — a
    # plain string sort would interleave them wrongly.
    all_events: list[Event] = (
        root_events + compaction_events + structural
        + sub_agent_events + sub_compaction_events
    )
    all_events.sort(key=lambda e: _parse_iso(e.timestamp))

    # Write atomically.
    tmp = out_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for e in all_events:
            f.write(json.dumps(e.to_dict(), separators=(",", ":")) + "\n")
    tmp.replace(out_path)

    result.events_written = len(all_events)

    # Panel state stays out of the log; the final snapshot per tab and the
    # merged terminal transcripts go to their bounded sidecars so the
    # preview panels restore on resume.
    tabs = latest_tab_snapshots(events_old)
    if tabs:
        tabs_tmp = (conv_dir / "browser_tabs.json").with_suffix(".tmp")
        tabs_tmp.write_text(json.dumps(tabs), encoding="utf-8")
        tabs_tmp.replace(conv_dir / "browser_tabs.json")
    transcripts = merge_terminal_transcripts(events_old)
    if transcripts:
        term_tmp = (conv_dir / "terminal.json").with_suffix(".tmp")
        term_tmp.write_text(json.dumps(transcripts), encoding="utf-8")
        term_tmp.replace(conv_dir / "terminal.json")

    # Archive the legacy files so they can be rolled back if needed.
    # Default archive target is a sibling ``_pre_007`` directory so the
    # function is usable standalone (e.g. one-off scripts) without the
    # state-dir backup helper.
    if archive is None:
        archive = _local_pre_007_archive(conv_dir)
    for name in ("history.json", "events.json"):
        p = conv_dir / name
        if p.exists():
            archive(p)
    for subdir in ("summaries", "sub_agents"):
        d = conv_dir / subdir
        if d.exists():
            archive(d)

    return result


def _local_pre_007_archive(conv_dir: Path) -> Callable[[Path], None]:
    """Default archive: move each file/dir to ``{conv_dir}/_pre_007/``."""
    pre = conv_dir / "_pre_007"
    pre.mkdir(exist_ok=True)
    def _move(p: Path) -> None:
        p.rename(pre / p.name)
    return _move


def _infer_sub_agent_id(stem: str, events_old: list[dict[str, Any]]) -> str | None:
    """Sub-agent filename is {NAME}_{short_hex}.json. The agent_id in events.json
    is the context id like 'root.computron.9.research_agent.10'. We can match
    by looking for an agent_started event whose agent_name and a hex suffix in
    its agent_id match the stem.

    This is best-effort. Falls back to None if ambiguous.
    """
    # Stem format: NAME_shorthex (e.g. RESEARCH_AGENT_a1b2c3d4)
    parts = stem.rsplit("_", 1)
    if len(parts) != 2:
        return None
    name_upper, suffix = parts
    candidates = [
        e for e in events_old
        if e.get("type") == "agent_started"
        and e.get("parent_agent_id")
        and (e.get("agent_name") or "").upper().replace(" ", "_") == name_upper
    ]
    if not candidates:
        return None
    # Prefer one whose agent_id contains the suffix.
    for e in candidates:
        if suffix.lower() in (e.get("agent_id") or "").lower():
            return e["agent_id"]
    # Fallback: first one with that name.
    return candidates[0]["agent_id"]


def _backup_archive(state_dir: Path) -> Callable[[Path, Path], None]:
    """Archive callback that places each legacy file under
    ``{state_dir}/.backups/007_events_first/`` preserving its path
    relative to ``state_dir``.
    """
    from migrations._backup import _BACKUPS_DIR
    backups_root = state_dir / _BACKUPS_DIR / "007_events_first"

    def _archive(conv_dir: Path) -> Callable[[Path], None]:
        rel = conv_dir.relative_to(state_dir)
        dest_dir = backups_root / rel
        dest_dir.mkdir(parents=True, exist_ok=True)
        def _move(p: Path) -> None:
            target = dest_dir / p.name
            if p.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(p), str(target))
            else:
                p.rename(target)
        return _move

    # Type-erased wrapper so callers don't have to know the inner shape.
    return _archive  # type: ignore[return-value]


def migrate(state_dir: Path) -> None:
    """Migrate every conversation under ``state_dir/conversations``.

    Idempotent — conversations that already have ``events.jsonl`` are
    skipped. Legacy files for each migrated conversation are moved
    under ``{state_dir}/.backups/007_events_first/conversations/{id}/``.
    """
    conv_root = state_dir / "conversations"
    if not conv_root.is_dir():
        logger.debug("No conversations directory at %s, skipping", conv_root)
        return

    archive_factory = _backup_archive(state_dir)
    migrated = skipped = failed = 0
    for entry in conv_root.iterdir():
        if not entry.is_dir():
            continue
        # Recognise pre-events conversations: those with history.json
        # but no events.jsonl yet.
        if (entry / "events.jsonl").exists():
            skipped += 1
            continue
        if not (entry / "history.json").exists():
            skipped += 1
            continue
        try:
            result = migrate_conversation(entry, archive=archive_factory(entry))
            if result.events_written > 0:
                migrated += 1
            else:
                failed += 1
                logger.warning(
                    "Conversation %s: nothing written — %s",
                    entry.name, result.warnings[:1],
                )
        except Exception:
            failed += 1
            logger.exception("Failed to migrate conversation %s", entry.name)

    logger.info(
        "007_events_first complete: migrated=%d skipped=%d failed=%d",
        migrated, skipped, failed,
    )
