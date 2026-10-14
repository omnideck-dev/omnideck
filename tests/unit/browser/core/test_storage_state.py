"""Regression coverage for saved IndexedDB primary-key validation."""

import copy
import math

import pytest

from browser.core._storage_state import prepare_storage_state


def state_with_records(records, **store_options):
    return {
        "cookies": [{"name": "session", "value": "secret"}],
        "origins": [
            {
                "origin": "https://example.test",
                "localStorage": [{"name": "session", "value": "secret"}],
                "indexedDB": [
                    {
                        "name": "cache",
                        "version": 1,
                        "stores": [
                            {
                                "name": "records",
                                "indexes": [],
                                "records": records,
                                **store_options,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def records(state):
    return state["origins"][0]["indexedDB"][0]["stores"][0]["records"]


@pytest.mark.parametrize("key", [{}, None, True, False, math.nan, ["valid", {}]])
def test_invalid_inline_keys_are_skipped_without_changing_saved_state(key, caplog):
    state = state_with_records(
        [{"value": {"id": key}}, {"value": {"id": "valid"}}],
        keyPath="id",
    )
    original = copy.deepcopy(state)
    prepared = prepare_storage_state(state)
    assert records(prepared) == [{"value": {"id": "valid"}}]
    assert len(records(state)) == len(records(original)) == 2
    assert prepared["cookies"] == state["cookies"]
    assert prepared["origins"][0]["localStorage"] == state["origins"][0]["localStorage"]
    assert "Skipped 1 IndexedDB records" in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.parametrize("key", [0, -1, "", "valid", math.inf, -math.inf, [], ["valid", 1, []]])
def test_valid_keys_including_zero_empty_strings_and_infinity_survive(key):
    state = state_with_records([{"value": {"id": key}}], keyPath="id")
    assert prepare_storage_state(state) == state


def test_encoded_empty_object_key_is_removed_but_valid_encoded_records_survive():
    invalid = {"valueEncoded": {"o": [{"k": "id", "v": {"o": [], "id": 2}}], "id": 1}}
    valid = {"valueEncoded": {"o": [{"k": "id", "v": "valid"}], "id": 1}}
    state = state_with_records([invalid, valid], keyPath="id")
    prepared = prepare_storage_state(state)
    assert records(prepared) == [valid]
    assert records(state) == [invalid, valid]


@pytest.mark.parametrize(
    "key",
    [
        {"d": "2026-09-25T00:00:00.000Z"},
        {"ta": {"b": "AQI=", "k": "ui8"}},
        {"ab": {"b": "AQI="}},
        {"ab": {"b": ""}},
        {"v": "Infinity"},
        {"v": "-Infinity"},
        {"v": "-0"},
        {"a": ["x", 1], "id": 1},
    ],
)
def test_encoded_out_of_line_keys_survive(key):
    state = state_with_records([{"keyEncoded": key, "value": "payload"}])
    assert prepare_storage_state(state) == state


@pytest.mark.parametrize("key", [{"v": "NaN"}, {"v": "null"}, {"bi": "1"}, {"o": [], "id": 1}])
def test_invalid_encoded_out_of_line_keys_are_skipped(key):
    state = state_with_records([{"keyEncoded": key, "value": "payload"}])
    assert records(prepare_storage_state(state)) == []


def test_compound_and_nested_key_paths():
    valid = {"value": {"user": {"id": "abc"}, "version": 1}}
    invalid = {"value": {"user": {"id": {}}, "version": 1}}
    state = state_with_records([valid, invalid], keyPathArray=["user.id", "version"])
    assert records(prepare_storage_state(state)) == [valid]


def test_empty_key_path_and_length_key_path():
    for path, value in [("", "text"), ("length", "text"), ("items.length", {"items": [1, 2]})]:
        state = state_with_records([{"value": value}], keyPath=path)
        assert prepare_storage_state(state) == state


def test_auto_increment_allows_missing_keys_but_not_invalid_keys():
    missing = {"value": {"payload": "hello"}}
    invalid = {"value": {"id": {}}}
    state = state_with_records([missing, invalid], keyPath="id", autoIncrement=True)
    assert records(prepare_storage_state(state)) == [missing]
    out_of_line = state_with_records([missing], autoIncrement=True)
    assert prepare_storage_state(out_of_line) == out_of_line


def test_encoded_references_and_cycles():
    valid = {
        "valueEncoded": {
            "o": [
                {"k": "shared", "v": {"a": ["x"], "id": 2}},
                {"k": "id", "v": {"ref": 2}},
            ],
            "id": 1,
        }
    }
    cyclic = {
        "valueEncoded": {
            "o": [
                {"k": "id", "v": {"a": [{"ref": 2}], "id": 2}},
            ],
            "id": 1,
        }
    }
    state = state_with_records([valid, cyclic], keyPath="id")
    assert records(prepare_storage_state(state)) == [valid]
