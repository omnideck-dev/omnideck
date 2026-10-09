from __future__ import annotations

import pytest

from brokering.catalog import DEFAULT_CATALOG, build_default_catalog, validate_catalog, validate_host_path_bindings
from integrations.catalog import IntegrationCatalogEntry, OperationDisplayGroup, integration_catalog
from brokering.brokers.llm_proxy.catalog import ModelProviderCatalogEntry, model_provider_catalog
from brokering.drivers import BrokerDriver, HostPathBinding
from integrations.operations import OPERATIONS_BY_GROUP


def test_catalogs_are_separated_by_domain_type() -> None:
    assert all(isinstance(entry, IntegrationCatalogEntry) for entry in integration_catalog().values())
    assert all(isinstance(entry, ModelProviderCatalogEntry) for entry in model_provider_catalog().values())
    assert set(integration_catalog()).isdisjoint(model_provider_catalog())


def test_catalog_entries_can_share_one_driver() -> None:
    assert DEFAULT_CATALOG["icloud"].driver is DEFAULT_CATALOG["gmail"].driver


@pytest.mark.parametrize("include_test_integrations", [False, True])
def test_default_catalog_is_valid(include_test_integrations: bool) -> None:
    validate_catalog(build_default_catalog(include_test_integrations=include_test_integrations))


def test_host_path_validation_uses_role_names_without_runtime_state() -> None:
    entry = IntegrationCatalogEntry(
        slug="test",
        title="Test",
        description="Test",
        category="Test",
        driver=BrokerDriver(
            id="test",
            command=("true",),
            host_paths=(HostPathBinding(role="downloads", env_var="DOWNLOADS", mode="write"),),
        ),
    )

    validate_host_path_bindings({"test": entry}, {"downloads"})
    with pytest.raises(ValueError, match="host-path role 'downloads'"):
        validate_host_path_bindings({"test": entry}, set())


def test_model_providers_have_no_operations() -> None:
    for entry in model_provider_catalog().values():
        assert entry.resolve_operations(frozenset({"anything"})) == frozenset()


def test_google_remote_scopes_bound_available_operations() -> None:
    entry = DEFAULT_CATALOG["google_workspace"]
    readonly = entry.resolve_operations(
        frozenset({"https://www.googleapis.com/auth/gmail.readonly"})
    )
    assert "email.messages.search" in readonly
    assert "email.messages.send" not in readonly

    modify = entry.resolve_operations(
        frozenset({"https://www.googleapis.com/auth/gmail.modify"})
    )
    assert modify == OPERATIONS_BY_GROUP["email"]


def test_scope_mapping_adds_to_unconditional_operations() -> None:
    entry = IntegrationCatalogEntry(
        slug="mixed",
        title="Mixed",
        description="Mixed authorization",
        category="Test",
        driver=BrokerDriver(id="test", command=("true",)),
        operations=frozenset({"http.request"}),
        scope_operations={
            "scope-a": frozenset({"email.messages.search"}),
        },
    )

    assert entry.resolve_operations(frozenset({"scope-a"})) == frozenset(
        {
            "http.request",
            "email.messages.search",
        }
    )


def test_display_groups_are_optional_catalog_metadata() -> None:
    google = integration_catalog()["google_workspace"]
    assert {group.id for group in google.operation_groups} == {
        "email",
        "calendar",
        "drive",
        "contacts",
    }
    assert integration_catalog()["http"].operation_groups == ()


@pytest.mark.parametrize("scopes", [frozenset(), frozenset({"unknown-scope"})])
def test_unknown_or_missing_scopes_do_not_offer_google_operations(scopes) -> None:
    assert DEFAULT_CATALOG["google_workspace"].resolve_operations(scopes) == frozenset()


def test_test_integration_is_excluded_unless_explicitly_enabled() -> None:
    production_catalog = build_default_catalog(include_test_integrations=False)
    test_catalog = build_default_catalog(include_test_integrations=True)

    assert "test" not in production_catalog
    assert test_catalog["test"].resolve_operations() == OPERATIONS_BY_GROUP["test"]
    assert test_catalog["test"].driver_id == "test.fake"


def test_catalog_validation_rejects_unknown_or_undeclared_group_operations() -> None:
    entry = IntegrationCatalogEntry(
        slug="bad",
        title="Bad",
        description="Bad",
        category="Test",
        driver=BrokerDriver(id="test", command=("true",)),
        operations=frozenset({"http.request"}),
        operation_groups=(
            OperationDisplayGroup(
                id="bad",
                title="Bad",
                operation_ids=frozenset({"email.messages.search"}),
            ),
        ),
    )

    with pytest.raises(ValueError, match="groups undeclared operations"):
        validate_catalog({"bad": entry})
