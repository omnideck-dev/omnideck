"""Prepare saved browser state for restoration without invalid IndexedDB keys."""

from __future__ import annotations

import copy
import logging
import math
from typing import Any, TypedDict

logger = logging.getLogger(__name__)
_MISSING = object()
_VALID_ENCODED_KEY = object()
_INVALID_ENCODED_VALUE = object()


class _Record(TypedDict, total=False):
    key: Any
    keyEncoded: Any
    value: Any
    valueEncoded: Any


class _Store(TypedDict, total=False):
    keyPath: str | None
    keyPathArray: list[str]
    autoIncrement: bool
    records: list[_Record]


def _decode(value: Any, refs: dict[int, Any]) -> Any:
    # Only decode enough of Playwright's wire format to inspect primary keys.
    # Keep the original serialized records intact for restoration.
    if not isinstance(value, dict):
        return value
    if "ref" in value:
        return refs.get(value["ref"], _MISSING)
    if "v" in value:
        return {
            "undefined": _MISSING,
            "null": None,
            "NaN": math.nan,
            "Infinity": math.inf,
            "-Infinity": -math.inf,
            "-0": 0,
        }.get(value["v"], _INVALID_ENCODED_VALUE)
    if "d" in value or "ta" in value or "ab" in value:
        # Serialized Dates, typed arrays, and ArrayBuffers are valid scalar keys.
        return _VALID_ENCODED_KEY
    if "a" in value:
        items: list[Any] = []
        refs[value["id"]] = items
        items.extend(_decode(item, refs) for item in value["a"])
        return items
    if "o" in value:
        properties: dict[str, Any] = {}
        refs[value["id"]] = properties
        for entry in value["o"]:
            properties[entry["k"]] = _decode(entry["v"], refs)
        return properties
    return _INVALID_ENCODED_VALUE


def _valid_key(value: Any, ancestors: frozenset[int] = frozenset()) -> bool:
    if value is _VALID_ENCODED_KEY or isinstance(value, str):
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return not math.isnan(value)
    if isinstance(value, list):
        if id(value) in ancestors:
            return False
        return all(_valid_key(item, ancestors | {id(value)}) for item in value)
    return False


def _key_path(value: Any, path: str) -> Any:
    if path == "":
        return value
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part, _MISSING)
        elif isinstance(value, (str, list)) and part == "length":
            value = len(value)
        else:
            return _MISSING
    return value


def _record_has_valid_key(store: _Store, record: _Record) -> bool:
    path = store.get("keyPathArray", store.get("keyPath"))
    if path is None:
        key = record.get("key", _MISSING)
        if key is _MISSING or key is None:
            key = _decode(record.get("keyEncoded", _MISSING), {})
    else:
        value = record.get("value", _MISSING)
        if value is _MISSING or value is None:
            value = _decode(record.get("valueEncoded", _MISSING), {})
        key = [_key_path(value, part) for part in path] if isinstance(path, list) else _key_path(value, path)
    if key is _MISSING and store.get("autoIncrement", False):
        return True
    return _valid_key(key)


def prepare_storage_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a restore copy excluding records with unusable primary keys."""
    prepared = copy.deepcopy(state)
    for origin in prepared.get("origins", []):
        skipped = 0
        for database in origin.get("indexedDB", []):
            for store in database.get("stores", []):
                records = store.get("records", [])
                kept = [record for record in records if _record_has_valid_key(store, record)]
                skipped += len(records) - len(kept)
                store["records"] = kept
        if skipped:
            # Do not log record contents: profiles can contain credentials.
            logger.warning(
                "Skipped %d IndexedDB records with invalid primary keys while restoring origin %s",
                skipped,
                origin["origin"],
            )
    return prepared
