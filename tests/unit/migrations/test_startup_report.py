"""The startup contract exposes a failed step, never saved data or credentials."""

import json

import pytest

from migrations._engine import _load_applied, run_migration_plan
from migrations._startup_report import PREFIX, report_migrations


def events(capsys):
    return [json.loads(line.removeprefix(PREFIX)) for line in capsys.readouterr().err.splitlines() if line.startswith(PREFIX)]


def test_failed_step_reports_safe_diagnostics_and_retry_clears_failure(tmp_path, capsys):
    def fail(_state):
        raise ValueError("secret-token and private record contents")

    with pytest.raises(ValueError, match="secret-token"), report_migrations():
        run_migration_plan(tmp_path, [("broker:001_operation_grants", fail)])
    failed = events(capsys)
    assert [event["status"] for event in failed] == ["starting", "failed"]
    assert all(event["phase"] == "migrations" for event in failed)
    assert failed[-1]["code"] == "MIGRATION_FAILED"
    assert failed[-1]["step"] == "broker:001_operation_grants"
    assert "secret-token" not in json.dumps(failed)
    assert _load_applied(tmp_path) == set()

    with report_migrations():
        run_migration_plan(tmp_path, [("broker:001_operation_grants", lambda _: None)])
    recovered = events(capsys)
    assert [event["status"] for event in recovered] == ["starting", "complete"]
    assert all(event["phase"] == "migrations" for event in recovered)
    assert recovered[0]["timestamp"] > failed[-1]["timestamp"]
    assert _load_applied(tmp_path) == {"broker:001_operation_grants"}


def test_invalid_history_reports_history_step_without_record_contents(tmp_path, capsys):
    (tmp_path / ".migrations.json").write_text("private invalid history")
    with pytest.raises(ValueError), report_migrations():
        run_migration_plan(tmp_path, [])
    failed = events(capsys)[-1]
    assert failed["step"] == "migration_history"
    assert failed["code"] == "MIGRATION_FAILED"
    assert "private" not in json.dumps(failed)
