"""Keep the model client library independent of the agent core and the app."""

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
# The only first-party package the library may use is the tool schema leaf.
BLOCKED = {
    p.stem if p.is_file() else p.name
    for p in ROOT.iterdir()
    if (p.is_file() and p.suffix == ".py") or (p.is_dir() and (p / "__init__.py").exists())
} - {"llm", "tool_schemas"}


def test_llm_imports_do_not_cross_into_other_first_party_packages():
    violations = []
    for path in (ROOT / "llm").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            for module in modules:
                if module.split(".")[0] in BLOCKED:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {module}")
    assert violations == []


def test_llm_and_its_clients_import_with_other_packages_blocked():
    # A fresh interpreter catches indirect imports hidden behind package exports.
    code = r"""
import importlib
import importlib.abc
import pkgutil
import sys

blocked = set(sys.argv[1:])
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in blocked:
            raise ImportError("llm attempted a first-party import: " + fullname)
sys.meta_path.insert(0, Blocker())

import llm
for module in pkgutil.walk_packages(llm.__path__, "llm."):
    importlib.import_module(module.name)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, *sorted(BLOCKED)], cwd=ROOT, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_importing_llm_types_loads_no_provider_sdk():
    # Callers that only need the shared types should not pay for the SDKs.
    code = "import sys, llm; print(sorted(m for m in ('anthropic', 'openai', 'ollama') if m in sys.modules))"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
