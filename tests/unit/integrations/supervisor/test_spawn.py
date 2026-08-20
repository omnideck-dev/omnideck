"""Tests for the dynamic-spawn env-var validation used by CLI integrations.

``_apply_dynamic_spawn`` is where a ``cli`` integration's bundle
(user-supplied binary + secret var names) gets turned into the child
process's env. It's the one place a malformed or malicious bundle could
clobber a spawn-critical env var (``PATH``, ``PERMISSIONS``, ...) or smuggle
in a name the shell/process would treat specially — these tests are the
validation contract, independent of the rest of the spawn path.
"""

from __future__ import annotations

import json

import pytest

from integrations.supervisor._catalog import DEFAULT_CATALOG
from integrations.supervisor._spawn import BrokerSpawnError, _apply_dynamic_spawn


def test_apply_dynamic_spawn_sets_cli_bin_and_args() -> None:
    env: dict[str, str] = {}
    names = _apply_dynamic_spawn(
        env, {"command": ["python", "/opt/script.py"], "vars": {"SLACK_TOKEN": "xoxb-abc"}},
    )
    assert env["CLI_BIN"] == "python"
    assert json.loads(env["CLI_BIN_ARGS"]) == ["/opt/script.py"]
    assert env["SLACK_TOKEN"] == "xoxb-abc"
    assert names == ["SLACK_TOKEN"]


def test_apply_dynamic_spawn_requires_command() -> None:
    with pytest.raises(BrokerSpawnError, match="command"):
        _apply_dynamic_spawn({}, {"vars": {}})


def test_apply_dynamic_spawn_rejects_empty_command_list() -> None:
    with pytest.raises(BrokerSpawnError, match="command"):
        _apply_dynamic_spawn({}, {"command": []})


def test_apply_dynamic_spawn_rejects_non_string_command_items() -> None:
    with pytest.raises(BrokerSpawnError, match="command"):
        _apply_dynamic_spawn({}, {"command": ["ok", 123]})


def test_apply_dynamic_spawn_rejects_lowercase_var_name() -> None:
    with pytest.raises(BrokerSpawnError, match="invalid env var name"):
        _apply_dynamic_spawn({}, {"command": ["bin"], "vars": {"lowercase": "x"}})


def test_apply_dynamic_spawn_rejects_name_with_bad_characters() -> None:
    with pytest.raises(BrokerSpawnError, match="invalid env var name"):
        _apply_dynamic_spawn({}, {"command": ["bin"], "vars": {"NOT-VALID": "x"}})


@pytest.mark.parametrize("reserved", ["PATH", "HOME", "INTEGRATION_ID", "BROKER_SOCKET", "PERMISSIONS", "CLI_BIN", "CLI_BIN_ARGS"])
def test_apply_dynamic_spawn_rejects_reserved_names(reserved: str) -> None:
    with pytest.raises(BrokerSpawnError, match="reserved"):
        _apply_dynamic_spawn({}, {"command": ["bin"], "vars": {reserved: "x"}})


def test_apply_dynamic_spawn_rejects_non_string_value() -> None:
    with pytest.raises(BrokerSpawnError, match="must be a string"):
        _apply_dynamic_spawn({}, {"command": ["bin"], "vars": {"TOKEN": 123}})


def test_apply_dynamic_spawn_allows_empty_vars() -> None:
    env: dict[str, str] = {}
    names = _apply_dynamic_spawn(env, {"command": ["bin"]})
    assert names == []
    assert env["CLI_BIN"] == "bin"
    assert json.loads(env["CLI_BIN_ARGS"]) == []


def test_apply_dynamic_spawn_honors_caller_supplied_reserved_set() -> None:
    """A caller can widen the reserved set beyond the static default."""
    # Not in the default reserved set, so it's allowed without an override.
    _apply_dynamic_spawn({}, {"command": ["bin"], "vars": {"HOME_DIR": "x"}})

    # But rejected once the caller reserves it explicitly.
    with pytest.raises(BrokerSpawnError, match="reserved"):
        _apply_dynamic_spawn(
            {}, {"command": ["bin"], "vars": {"HOME_DIR": "x"}}, reserved=frozenset({"HOME_DIR"}),
        )


def test_cli_catalog_entry_reserves_its_own_host_paths_env_vars() -> None:
    """Regression: a cli integration's var named HOME_DIR must be rejected.

    ``HOME_DIR`` isn't in the static reserved list — it only exists because
    the ``cli`` catalog entry binds the "workspace" host-path role to that
    env var name. If the caller (``spawn_broker``) didn't fold host_paths
    env vars into the reserved set, a bundle-supplied ``HOME_DIR`` would get
    silently overwritten by the real workspace path while still being
    treated as a secret to redact.
    """
    entry = DEFAULT_CATALOG["cli"]
    reserved = (
        frozenset({"PATH", "HOME", "USER", "SHELL", "LANG", "TERM", "INTEGRATION_ID",
                   "BROKER_SOCKET", "PERMISSIONS", "PATH_PREFIX", "CLI_BIN", "CLI_BIN_ARGS"})
        | set(entry.static_env)
        | set(entry.env_injection.values())
        | {binding.env_var for binding in entry.host_paths}
    )
    assert "HOME_DIR" in reserved
    with pytest.raises(BrokerSpawnError, match="reserved"):
        _apply_dynamic_spawn(
            {}, {"command": ["bin"], "vars": {"HOME_DIR": "x"}}, reserved=reserved,
        )
