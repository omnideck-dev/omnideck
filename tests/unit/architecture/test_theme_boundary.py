"""Keep the theme subsystem a shared leaf: the server and the agent tools depend on it, never the reverse."""

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    modules = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append((node.lineno, node.module))
    return modules


def test_theme_depends_only_on_config_and_the_standard_library():
    allowed = {"config"} | set(sys.stdlib_module_names)
    violations = [
        f"{path.relative_to(ROOT)}:{lineno}: {module}"
        for path in (ROOT / "theme").rglob("*.py")
        for lineno, module in _imported_modules(path)
        if module.split(".")[0] not in allowed
    ]
    assert violations == []


def test_server_reaches_the_theme_subsystem_directly_not_through_the_agent_tools():
    violations = [
        f"{path.relative_to(ROOT)}:{lineno}: {module}"
        for path in (ROOT / "server").glob("*.py")
        for lineno, module in _imported_modules(path)
        if module == "tools.theme" or module.startswith("tools.theme.")
    ]
    assert violations == []


def test_theme_imports_and_works_with_server_and_tools_blocked():
    # A fresh interpreter also catches an indirect dependency hidden behind a package export.
    code = """
import importlib.abc
import sys

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'server', 'tools', 'skills', 'agent_core', 'agents'}:
            raise AssertionError(f'Unexpected import: {fullname}')

sys.meta_path.insert(0, Blocker())
import theme
theme.theme_css
theme.update_theme
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)
