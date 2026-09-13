"""Oversized output remains available without entering model history inline."""

from pathlib import Path
import re
import stat

import pytest

from agent_core.hooks._result_cap import ToolResultCapHook


@pytest.fixture(autouse=True)
def temporary_results(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))


@pytest.mark.parametrize("value", ["", "hello", "x" * 1024])
def test_inline_results_are_unchanged(value):
    assert ToolResultCapHook(4096).after_tool("read_file", {}, value) == value


@pytest.mark.parametrize("context", [0, 4096, 1_048_576])
def test_spill_preserves_exact_utf8_and_limits_notice(context):
    original = "α😄token-dense\\\"\n" * 10000
    notice = ToolResultCapHook(context).after_tool("../../escape", {}, original)
    path = Path(re.search(r"temporary file: (.+)\n", notice)[1])
    assert path.read_text() == original
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(notice.encode()) < 1200
    assert "Preview (incomplete)" in notice
    assert "rerun" in notice


def test_parallel_results_get_distinct_paths(tmp_path):
    hook = ToolResultCapHook(4096)
    a = hook.after_tool("read_file", {}, "a" * 2000)
    b = hook.after_tool("read_file", {}, "b" * 2000)
    assert a != b
    assert {p.read_text() for p in tmp_path.iterdir()} == {"a" * 2000, "b" * 2000}


def test_disk_failure_does_not_publish_large_result(monkeypatch):
    def fail(**kwargs):
        raise OSError("disk full")
    monkeypatch.setattr("tempfile.NamedTemporaryFile", fail)
    result = ToolResultCapHook(4096).after_tool("grep", {}, "x" * 10000)
    assert "could not be saved" in result
    assert len(result) < 512
