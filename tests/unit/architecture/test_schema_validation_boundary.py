"""Schema validation stays independent of application and agent owners."""

from pathlib import Path
import subprocess
import sys


def test_schema_validation_imports_without_runtime_or_integration_packages():
    subprocess.run([sys.executable, "-c", """
import importlib.abc
import sys

class OwnerBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'agent_core', 'agents', 'brokering', 'integrations', 'server', 'tools'}:
            raise AssertionError('Schema validation imported its consumer: ' + fullname)

sys.meta_path.insert(0, OwnerBlocker())
from utils.schema_validation import schema_validator
schema_validator({'type': 'object'}).validate({})
"""], cwd=Path(__file__).resolve().parents[3], check=True)
