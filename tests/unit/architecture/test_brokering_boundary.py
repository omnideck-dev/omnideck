"""Keep transport/proxy primitives independent of tool-integration policy."""

import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import tomllib

from brokering.catalog import build_default_catalog
from brokering.brokers.llm_proxy.catalog import model_provider_catalog
from integrations.catalog import integration_catalog

ROOT = Path(__file__).resolve().parents[3]


def test_clients_and_llm_proxy_import_without_tool_integrations():
    # A fresh interpreter also catches accidental dependencies in package roots.
    # The supervisor/catalog composition layer intentionally knows both domains;
    # low-level clients and the HTTP proxy must not need either domain loaded.
    code = """
import importlib
import importlib.abc
import sys

class DomainBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'integrations', 'providers', 'agent_core', 'tools', 'server'}:
            raise AssertionError(f'Unexpected domain import: {fullname}')

sys.meta_path.insert(0, DomainBlocker())
for name in (
    'brokering.connection_data', 'brokering.drivers', 'brokering._env', 'brokering._perms',
    'brokering._rpc', 'brokering._ready', 'brokering._exit_codes',
    'brokering._control', 'brokering._session_slot',
    'brokering.broker_client', 'brokering.supervisor_client', 'brokering.brokers',
    'brokering.brokers.llm_proxy.catalog', 'brokering.brokers.llm_proxy.__main__',
):
    importlib.import_module(name)
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_catalog_composition_preserves_separate_broker_entry_points():
    catalog = build_default_catalog(include_test_integrations=False)
    assert set(catalog) == (set(integration_catalog()) - {"test"}) | set(model_provider_catalog())
    assert catalog["http"].driver.command == ("python", "-m", "brokering.brokers.http_broker")
    for entry in model_provider_catalog().values():
        assert entry.driver.command == ("python", "-m", "brokering.brokers.llm_proxy")
        assert entry.resolve_operations() == frozenset()


def test_provider_routes_do_not_depend_on_integration_routes():
    tree = ast.parse((ROOT / "server/_provider_routes.py").read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert "server._brokering" in imports
    assert not any(name and name.startswith("server._integrations") for name in imports)


def test_all_catalog_drivers_resolve_under_brokering_brokers():
    # Include the development-only broker: its production launch path must
    # remain valid even though normal catalog listings hide it.
    catalog = build_default_catalog(include_test_integrations=True)
    modules = {entry.driver.command[2] for entry in catalog.values()}
    assert modules == {
        "brokering.brokers.email_broker",
        "brokering.brokers.google_workspace_broker",
        "brokering.brokers.http_broker",
        "brokering.brokers.llm_proxy",
        "brokering.brokers.test_broker",
    }
    for entry in catalog.values():
        assert entry.driver.command[:2] == ("python", "-m")
    for module in modules:
        spec = importlib.util.find_spec(f"{module}.__main__")
        assert spec is not None and spec.origin is not None
        assert Path(spec.origin).is_relative_to(ROOT / "brokering" / "brokers")


def test_distribution_and_container_include_new_brokering_package():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    included = config["tool"]["setuptools"]["packages"]["find"]["include"]
    assert "brokering*" in included
    assert "integrations*" in included
    entrypoint = (ROOT / "container/entrypoint.sh").read_text()
    assert "-m brokering.supervisor" in entrypoint
    assert "-m integrations.supervisor" not in entrypoint
