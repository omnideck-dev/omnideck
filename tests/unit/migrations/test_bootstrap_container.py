"""Opt-in smoke test: run only in a disposable container with no mounted state."""

import json
import os
from pathlib import Path
import pwd
import subprocess


def test_real_root_bootstrap_preserves_history_and_runtime_boundaries(tmp_path):
    if os.environ.get("OMNIDECK_BOOTSTRAP_DISPOSABLE_TEST") != "1":
        import pytest

        pytest.skip("requires isolated root container and disposable /var/lib/omnideck")
    from migrations.__main__ import bootstrap
    from migrations._runner import _migration_plan

    assert os.geteuid() == 0
    app, broker = pwd.getpwnam("omnideck"), pwd.getpwnam("broker")
    owner_args = dict(app_uid=app.pw_uid, app_gid=app.pw_gid, broker_uid=broker.pw_uid, broker_gid=broker.pw_gid)
    # An upgrade with both old histories. Deleted default records must stay gone.
    state, vault = tmp_path / "state", tmp_path / "state" / "vault"
    creds = vault / "creds"
    creds.mkdir(parents=True)
    old_ids = [name for name, _ in _migration_plan(vault) if name[:3].isdigit() and int(name[:3]) <= 15]
    (state / ".migrations.json").write_text(json.dumps(old_ids))
    (vault / ".migrations.json").write_text('["001_operation_grants"]')
    (creds / "work.meta").write_text(
        json.dumps(
            {
                "version": 3,
                "id": "work",
                "kind": "integration",
                "agent_operation_grants": ["email.messages.search"],
            }
        )
    )
    (creds / "work.enc").write_bytes(b"encrypted sentinel")
    (vault / ".master-key").write_bytes(b"key sentinel")
    (state / "skills").mkdir()
    skill = state / "skills" / "mail.json"
    skill.write_text('{"tool_categories":["email"]}')
    bootstrap(state, vault, **owner_args)
    assert json.loads(skill.read_text())["tool_categories"] == ["integration:work"]
    assert not (state / "skills" / "assistant.json").exists()
    assert not (state / "agent_profiles").exists()
    for path in [state, *state.rglob("*")]:
        expected = broker if path == vault or vault in path.parents else app
        assert (path.stat().st_uid, path.stat().st_gid) == (expected.pw_uid, expected.pw_gid), path
    assert vault.stat().st_mode & 0o777 == 0o700
    assert (vault / ".migrations.json").read_text() == '["001_operation_grants"]'
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in state.rglob("*") if p.is_file()}
    bootstrap(state, vault, **owner_args)
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in state.rglob("*") if p.is_file()}

    # Exercise the actual fixed CLI at its production paths (container layer only).
    actual = Path("/var/lib/omnideck")
    assert not (actual / ".migrations.json").exists(), "test requires fresh container state"
    subprocess.run(["python3.12", "-m", "migrations"], check=True)
    assistant = actual / "skills" / "assistant.json"
    assert assistant.exists()
    for name in ("welcome_dashboard.html", "checklist.json", "build_page.py"):
        assert (Path("/home/omnideck") / name).stat().st_uid == app.pw_uid
    assistant.unlink()  # A user deletion must not be undone by a subsequent boot.
    before = {p: p.read_bytes() for p in actual.rglob("*") if p.is_file()}
    subprocess.run(["python3.12", "-m", "migrations"], check=True)
    assert before == {p: p.read_bytes() for p in actual.rglob("*") if p.is_file()}
    assert not assistant.exists()
    assert (actual / ".migrations.json").stat().st_uid == app.pw_uid
    assert (actual / "vault").stat().st_uid == broker.pw_uid

    denied = subprocess.run(["gosu", "omnideck", "ls", str(actual / "vault")], capture_output=True)
    assert denied.returncode != 0

    # Bad history makes the command fail; no service can start past the barrier.
    (actual / ".migrations.json").write_text("invalid history")
    failed = subprocess.run(["python3.12", "-m", "migrations"], capture_output=True)
    assert failed.returncode != 0
    assert (actual / ".migrations.json").stat().st_uid == app.pw_uid
    assert (actual / "vault").stat().st_uid == broker.pw_uid
    failed_entrypoint = subprocess.run(["bash", "container/entrypoint.sh"], capture_output=True, timeout=30)
    assert failed_entrypoint.returncode != 0
    assert b"Starting integrations supervisor" not in failed_entrypoint.stdout
    assert b"Starting app server" not in failed_entrypoint.stdout


if __name__ == "__main__":
    import tempfile

    assert os.environ.get("OMNIDECK_BOOTSTRAP_DISPOSABLE_TEST") == "1"
    with tempfile.TemporaryDirectory() as directory:
        test_real_root_bootstrap_preserves_history_and_runtime_boundaries(Path(directory))
    print("ROOT BOOTSTRAP / HISTORY / OWNERSHIP SMOKE PASSED")
