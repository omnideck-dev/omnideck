"""MCP protocol is shared infrastructure, independent of its runtime owners."""

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def test_mcp_protocol_imports_without_server_supervisor_or_brokers():
    # Execute imports in a fresh process: a preloaded package could conceal
    # an accidental dependency on a consumer's initialization or configuration.
    subprocess.run([sys.executable, "-c", """
import importlib.abc
import sys

class OwnerBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        for owner in ('server', 'brokering.supervisor', 'brokering.brokers'):
            if fullname == owner or fullname.startswith(owner + '.'):
                raise AssertionError('Protocol imported its owner: ' + fullname)

sys.meta_path.insert(0, OwnerBlocker())
import brokering.mcp_protocol
"""], cwd=ROOT, check=True)


def test_production_consumers_use_public_mcp_protocol_api():
    for directory in ("server", "brokering", "integrations"):
        for path in (ROOT / directory).rglob("*.py"):
            if path.is_relative_to(ROOT / "brokering/mcp_protocol"):
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                imports = ([node.module] if isinstance(node, ast.ImportFrom)
                           else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                for name in imports:
                    assert not (name and name.startswith("brokering.mcp_protocol._")), str(path)
                    if path.is_relative_to(ROOT / "server/oauth_setup") or path.name == "_mcp_refresh.py":
                        assert not (name and name.startswith("brokering.brokers.mcp_broker")), str(path)
