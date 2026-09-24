"""Migration 013: rename the Goals feature to Routines in stored state.

The task engine's on-disk store, its run conversations, and the skill and
profile identifiers that drive it were all named after "goals". This migration
moves them to their "routines" equivalents so existing installs keep working
after the rename:

- the task store directory and the run-conversation directory are moved to
  their new names;
- the ``goal_id`` field in stored task and run records becomes ``routine_id``,
  and the ``goals/`` conversation-id prefix becomes ``routines/`` wherever it is
  stored (run records, event logs, the artifacts index);
- the installed ``goal_planner`` skill is renamed to ``routine_planner`` along
  with the planning tool names, and those identifiers are rewritten in profiles
  and conversation metadata that reference them.

A no-op on a fresh install and on a second run, since nothing still carries the
old names, and each step is independently idempotent so a re-run after a mid-way
failure finishes the job.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_OLD_STORE_DIR = "goals"
_NEW_STORE_DIR = "routines"
_CONVERSATIONS_DIR = "conversations"
_SKILLS_DIR = "skills"
_PROFILES_DIR = "agent_profiles"

_OLD_CONV_PREFIX = "goals/"
_NEW_CONV_PREFIX = "routines/"

# Skill and tool identifiers renamed alongside the feature. Each is a compound
# token that never occurs as an ordinary English word, so a plain substring
# replace is safe even on prose-bearing files (profiles, conversation metadata).
_IDENTIFIER_RENAMES: tuple[tuple[str, str], ...] = (
    ("goal_planner", "routine_planner"),
    ("begin_goal", "begin_routine"),
    ("commit_goal", "commit_routine"),
    ("list_goals", "list_routines"),
    ("trigger_goal", "trigger_routine"),
)


# -- Generic helpers ---------------------------------------------------------


def _case_preserving_goal_to_routine(text: str) -> str:
    """Replace 'goal' with 'routine' in ``text``, preserving the matched case."""

    def repl(match: re.Match[str]) -> str:
        word = match.group(0)
        if word == "GOAL":
            return "ROUTINE"
        if word[0].isupper():
            return "Routine"
        return "routine"

    return re.sub(r"goal", repl, text, flags=re.IGNORECASE)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _move_dir(old: Path, new: Path) -> bool:
    """Move ``old`` to ``new``, merging into ``new`` if it already exists.

    Returns True if anything was moved. A pre-existing ``new`` is only expected
    when a subsystem raced ahead and created an empty store; its own entries win
    over the old ones so no live data is clobbered.
    """
    if not old.exists():
        return False
    if not new.exists():
        old.rename(new)
        return True
    for child in old.iterdir():
        dest = new / child.name
        if not dest.exists():
            shutil.move(str(child), str(dest))
    try:
        old.rmdir()
    except OSError:
        pass  # still holds entries that collided with new — leave them in place
    return True


# -- Task store records ------------------------------------------------------


def _rewrite_record(obj: object) -> bool:
    """Rename ``goal_id``→``routine_id`` and reprefix ``conversation_id``.

    Walks the whole JSON tree so it covers both the routine files (task
    definitions nested under ``tasks``) and the run files (a top-level
    ``goal_id`` plus ``conversation_id`` inside each task result).
    """
    changed = False
    if isinstance(obj, dict):
        if "goal_id" in obj and "routine_id" not in obj:
            obj["routine_id"] = obj.pop("goal_id")
            changed = True
        if _reprefix_conversation_id(obj):
            changed = True
        for value in list(obj.values()):
            if _rewrite_record(value):
                changed = True
    elif isinstance(obj, list):
        for item in obj:
            if _rewrite_record(item):
                changed = True
    return changed


def _reprefix_conversation_id(obj: dict) -> bool:
    """Swap a ``goals/`` conversation-id prefix for ``routines/`` in place."""
    cid = obj.get("conversation_id")
    if isinstance(cid, str) and cid.startswith(_OLD_CONV_PREFIX):
        obj["conversation_id"] = _NEW_CONV_PREFIX + cid[len(_OLD_CONV_PREFIX) :]
        return True
    return False


def _rewrite_store(store_dir: Path) -> None:
    count = 0
    for path in store_dir.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Skipping unreadable store file %s", path)
            continue
        if not _rewrite_record(data):
            continue
        _atomic_write(path, json.dumps(data, indent=2, default=str))
        count += 1
    if count:
        logger.info("Rewrote %d task store file(s)", count)


# -- Run conversation event logs ---------------------------------------------


def _rewrite_event_logs(conv_dir: Path) -> None:
    count = 0
    for path in conv_dir.rglob("events.jsonl"):
        if _rewrite_event_log(path):
            count += 1
    if count:
        logger.info("Rewrote conversation ids in %d event log(s)", count)


def _rewrite_event_log(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("Skipping unreadable event log %s", path)
        return False
    out: list[str] = []
    changed = False
    for line in lines:
        if not line.strip():
            out.append(line)
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        if isinstance(event, dict) and _reprefix_conversation_id(event):
            out.append(json.dumps(event, default=str))
            changed = True
        else:
            out.append(line)
    if not changed:
        return False
    _atomic_write(path, "\n".join(out) + "\n")
    return True


# -- Artifacts index ---------------------------------------------------------


def _artifact_id(conversation_id: str, path: str) -> str:
    """Derive an artifact's index key the same way the artifacts store does."""
    digest = hashlib.sha256(f"{conversation_id}\x00{path}".encode("utf-8"))
    return digest.hexdigest()


def _rewrite_artifacts_index(state_dir: Path) -> None:
    path = state_dir / "artifacts" / "index.json"
    if not path.exists():
        return
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Skipping unreadable artifacts index")
        return
    artifacts = index.get("artifacts")
    if not isinstance(artifacts, dict):
        return

    rekeyed: dict[str, dict] = {}
    changed = False
    for art_id, entry in artifacts.items():
        cid = entry.get("conversation_id") if isinstance(entry, dict) else None
        if isinstance(cid, str) and cid.startswith(_OLD_CONV_PREFIX):
            new_cid = _NEW_CONV_PREFIX + cid[len(_OLD_CONV_PREFIX) :]
            new_id = _artifact_id(new_cid, entry.get("path", ""))
            entry["conversation_id"] = new_cid
            entry["id"] = new_id
            rekeyed[new_id] = entry
            changed = True
        else:
            rekeyed[art_id] = entry
    if not changed:
        return
    index["artifacts"] = rekeyed
    _atomic_write(path, json.dumps(index, indent=2, default=str))
    logger.info("Re-keyed goal-run artifacts to their routine conversation ids")


# -- Skill and profile identifiers -------------------------------------------


def _rename_skill(state_dir: Path) -> None:
    old = state_dir / _SKILLS_DIR / "goal_planner.json"
    if not old.exists():
        return
    new = state_dir / _SKILLS_DIR / "routine_planner.json"
    new.write_text(_case_preserving_goal_to_routine(old.read_text(encoding="utf-8")), encoding="utf-8")
    old.unlink()
    logger.info("Renamed goal_planner skill to routine_planner")


def _rewrite_identifiers(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Skipping unreadable file %s", path)
        return False
    updated = text
    for old, new in _IDENTIFIER_RENAMES:
        updated = updated.replace(old, new)
    if updated == text:
        return False
    _atomic_write(path, updated)
    return True


def _rewrite_profiles(state_dir: Path) -> None:
    profiles_dir = state_dir / _PROFILES_DIR
    if not profiles_dir.is_dir():
        return
    count = sum(_rewrite_identifiers(path) for path in sorted(profiles_dir.glob("*.json")))
    if count:
        logger.info("Rewrote skill identifiers in %d profile(s)", count)


def _rewrite_conversation_metadata(state_dir: Path) -> None:
    conv_root = state_dir / _CONVERSATIONS_DIR
    if not conv_root.is_dir():
        return
    count = sum(_rewrite_identifiers(path) for path in conv_root.rglob("metadata.json"))
    if count:
        logger.info("Rewrote skill identifiers in %d conversation(s)", count)


# -- Entry point -------------------------------------------------------------


def migrate(state_dir: Path) -> None:
    """Rename the goals feature to routines across stored state."""
    # 1. Move the task store, then fix the records inside it.
    store_new = state_dir / _NEW_STORE_DIR
    if _move_dir(state_dir / _OLD_STORE_DIR, store_new):
        logger.info("Moved task store to routines/")
    if store_new.is_dir():
        _rewrite_store(store_new)

    # 2. Move the run conversations, then fix the ids embedded in their logs.
    conv_root = state_dir / _CONVERSATIONS_DIR
    conv_new = conv_root / _NEW_STORE_DIR
    if _move_dir(conv_root / _OLD_STORE_DIR, conv_new):
        logger.info("Moved run conversations to conversations/routines/")
    if conv_new.is_dir():
        _rewrite_event_logs(conv_new)

    # 3. Re-key goal-run artifacts to their new conversation ids.
    _rewrite_artifacts_index(state_dir)

    # 4. Rename the planning skill and the identifiers that reference it.
    _rename_skill(state_dir)
    _rewrite_profiles(state_dir)
    _rewrite_conversation_metadata(state_dir)
