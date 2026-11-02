"""Schema validation stays independent of application and agent owners."""

from pathlib import Path
import subprocess
import sys


def test_schema_validation_imports_without_runtime_or_integration_packages():
    root = Path(__file__).resolve().parents[3]
    blocked = {
        path.stem if path.is_file() else path.name
        for path in root.iterdir()
        if (path.is_file() and path.suffix == ".py")
        or (path.is_dir() and (path / "__init__.py").exists())
    } - {"tool_schemas"}
    subprocess.run([sys.executable, "-c", """
import importlib.abc
import sys

class OwnerBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in set(sys.argv[1:]):
            raise AssertionError('Schema validation imported its consumer: ' + fullname)

sys.meta_path.insert(0, OwnerBlocker())
from tool_schemas import schema_validator
schema_validator({'type': 'object'}).validate({})
""", *sorted(blocked)], cwd=root, check=True)
