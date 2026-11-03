"""Real entrypoint failure/retry proof, isolated from the developer's state."""

import json
import os
from pathlib import Path
import subprocess


def test_failed_root_startup_reports_migration_and_blocks_services():
    if os.environ.get("OMNIDECK_BOOTSTRAP_DISPOSABLE_TEST") != "1":
        import pytest

        pytest.skip("requires a disposable root container with no mounted state")
    assert os.geteuid() == 0
    from migrations._runner import _migration_plan
    from migrations._startup_report import PREFIX

    state = Path("/var/lib/omnideck")
    assert not (state / ".migrations.json").exists(), "requires fresh container state"
    creds = state / "vault" / "creds"
    creds.mkdir(parents=True, exist_ok=True)
    # Model an existing installation at the category migration barrier.
    prior = [name for name, _ in _migration_plan(state / "vault") if not name.startswith("016_")]
    (state / ".migrations.json").write_text(json.dumps(prior))
    bad_record = creds / "test.meta"
    bad_record.write_text("private-invalid-record")
    sentinel = state / "keep.txt"
    sentinel.write_text("preserve user data")

    result = subprocess.run(["/opt/entrypoint.sh"], capture_output=True, timeout=30)
    assert result.returncode != 0
    output = result.stdout + result.stderr
    events = [json.loads(line[len(PREFIX):]) for line in result.stderr.decode().splitlines() if line.startswith(PREFIX)]
    assert all(event["phase"] == "migrations" for event in events)
    assert [event["status"] for event in events] == ["starting", "failed"]
    assert events[-1]["code"] == "MIGRATION_FAILED"
    assert events[-1]["step"] == "016_connection_tool_categories"
    assert "private-invalid-record" not in json.dumps(events)
    assert b"Starting integrations supervisor" not in output
    assert b"Starting app server" not in output
    assert not Path("/run/cvault/app.sock").exists()
    assert "016_connection_tool_categories" not in json.loads((state / ".migrations.json").read_text())
    assert sentinel.read_text() == "preserve user data"

    # Correct only the disposable fixture, then exercise the real root command.
    bad_record.write_text(json.dumps({"version": 3, "id": "test", "kind": "integration", "agent_operation_grants": []}))
    result = subprocess.run(["python3.12", "-m", "migrations"], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode()
    events = [json.loads(line[len(PREFIX):]) for line in result.stderr.decode().splitlines() if line.startswith(PREFIX)]
    assert all(event["phase"] == "migrations" for event in events)
    assert [event["status"] for event in events] == ["starting", "complete"]
    assert "016_connection_tool_categories" in json.loads((state / ".migrations.json").read_text())
    assert sentinel.read_text() == "preserve user data"


if __name__ == "__main__":
    assert os.environ.get("OMNIDECK_BOOTSTRAP_DISPOSABLE_TEST") == "1"
    test_failed_root_startup_reports_migration_and_blocks_services()
    print("ROOT STARTUP FAILURE / SAFE DIAGNOSTICS / PRESERVED DATA / RETRY PASSED")
