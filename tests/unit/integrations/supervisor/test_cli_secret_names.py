"""Tests for ``_cli_secret_names`` — the env-var-name extraction used by the
CLI-exec secret collision check in ``BrokerManager.add``/``update``.

Pure function: given a catalog entry and an (unencrypted, in-memory) auth
blob, returns the set of env var names that integration's bundle would
inject. Non-CLI entries always return an empty set so they never
participate in the collision check.
"""

from __future__ import annotations

from integrations.permissions import Access, Capability
from integrations.supervisor._catalog import _CLI, _HTTP, CatalogEntry
from integrations.supervisor._manager import _cli_secret_names


def test_cli_entry_reports_bundle_var_names() -> None:
    blob = {"command": ["bin"], "vars": {"SLACK_TOKEN": "x", "SLACK_APP_TOKEN": "y"}}
    assert _cli_secret_names(_CLI, blob) == frozenset({"SLACK_TOKEN", "SLACK_APP_TOKEN"})


def test_cli_entry_with_no_vars_is_empty() -> None:
    assert _cli_secret_names(_CLI, {"command": ["bin"]}) == frozenset()


def test_non_cli_entry_is_always_empty() -> None:
    assert _cli_secret_names(_HTTP, {"token": "whatever"}) == frozenset()


def test_unrelated_capability_entry_is_empty() -> None:
    entry = CatalogEntry(
        slug="fake",
        command=["true"],
        capabilities={Capability.EMAIL: Access.READ},
        env_injection={"password": "SOME_VAR"},
    )
    assert _cli_secret_names(entry, {"password": "hunter2"}) == frozenset()
