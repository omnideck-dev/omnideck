"""Upgrade/history regression tests for the one pre-service migration barrier."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

from migrations import _runner as runner
from migrations._engine import _load_applied, _save_applied
from migrations.__main__ import bootstrap

pytestmark = pytest.mark.unit


def test_concurrent_startup_attempts_do_not_execute_the_same_step_twice(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    calls = []

    def migrate(_state):
        calls.append("ran")
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(runner, "_migration_plan", lambda _vault: [("once", migrate)])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runner.run_migrations, tmp_path)
        try:
            assert entered.wait(5)
            second = pool.submit(runner.run_migrations, tmp_path)
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert calls == ["ran"]


def test_interrupted_history_import_never_executes_old_steps(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    _save_applied(tmp_path, {"old_app"})
    _save_applied(vault, {"old_broker"})
    old = Mock(side_effect=AssertionError("replayed"))
    new = Mock()
    monkeypatch.setattr(
        runner,
        "_migration_plan",
        lambda _vault: [
            ("old_app", old),
            ("broker:old_broker", old),
            ("new", new),
        ],
    )
    with monkeypatch.context() as patch:
        patch.setattr(runner, "_save_applied", Mock(side_effect=OSError("disk full")))
        with pytest.raises(OSError, match="disk full"):
            runner.run_migrations(tmp_path)
    old.assert_not_called()
    new.assert_not_called()
    assert _load_applied(tmp_path) == {"old_app"}
    runner.run_migrations(tmp_path)
    old.assert_not_called()
    new.assert_called_once()


def test_all_historical_steps_are_skipped_and_only_new_steps_run(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    real_plan = runner._migration_plan(vault)
    app_ids = [name for name, _ in real_plan if name[:3].isdigit() and int(name[:3]) <= 15]
    assert len(app_ids) == 15
    _save_applied(tmp_path, set(app_ids) | {"unknown_old_app_step"})
    _save_applied(vault, {"001_operation_grants", "unknown_old_broker_step"})
    old_vault_bytes = (vault / ".migrations.json").read_bytes()
    completed = Mock(side_effect=AssertionError("Completed migration replayed"))
    new_calls = []
    monkeypatch.setattr(
        runner,
        "_migration_plan",
        lambda _vault: [
            *[(name, completed) for name in app_ids],
            ("broker:001_operation_grants", completed),
            ("016_connection_tool_categories", lambda _state: new_calls.append("categories")),
            ("016_connection_tool_categories_cleanup", lambda _state: new_calls.append("cleanup")),
        ],
    )
    runner.run_migrations(tmp_path)
    snapshot = (tmp_path / ".migrations.json").read_bytes()
    runner.run_migrations(tmp_path)
    assert new_calls == ["categories", "cleanup"]
    completed.assert_not_called()
    assert (tmp_path / ".migrations.json").read_bytes() == snapshot
    assert (vault / ".migrations.json").read_bytes() == old_vault_bytes
    assert {"unknown_old_app_step", "broker:unknown_old_broker_step"} <= _load_applied(tmp_path)


@pytest.mark.parametrize("store", ["app", "vault"])
@pytest.mark.parametrize("raw", ["broken", "{}", '"one"', "[1]", "[null]", '[""]'])
def test_corrupt_history_never_runs_any_migration(tmp_path, monkeypatch, store, raw):
    vault = tmp_path / "vault"
    vault.mkdir()
    path = (tmp_path if store == "app" else vault) / ".migrations.json"
    path.write_text(raw)
    migration = Mock()
    monkeypatch.setattr(runner, "_migration_plan", lambda _vault: [("old", migration)])
    with pytest.raises(ValueError):
        runner.run_migrations(tmp_path)
    migration.assert_not_called()
    assert path.read_text() == raw


def test_failed_cross_store_step_preserves_import_and_retries_only_pending(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    _save_applied(tmp_path, {"old_app"})
    _save_applied(vault, {"old_broker"})
    old = Mock(side_effect=AssertionError("replayed"))
    first = Mock()
    failing = Mock(side_effect=RuntimeError("interrupted"))
    monkeypatch.setattr(
        runner,
        "_migration_plan",
        lambda _vault: [
            ("old_app", old),
            ("broker:old_broker", old),
            ("new_first", first),
            ("new_second", failing),
        ],
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        runner.run_migrations(tmp_path)
    assert _load_applied(tmp_path) == {"old_app", "broker:old_broker", "new_first"}
    failing.side_effect = None
    runner.run_migrations(tmp_path)
    runner.run_migrations(tmp_path)
    old.assert_not_called()
    first.assert_called_once()
    assert failing.call_count == 2


def test_real_vault_then_category_migration_without_running_broker(tmp_path):
    vault = tmp_path / "vault"
    creds = vault / "creds"
    creds.mkdir(parents=True)
    _save_applied(
        tmp_path, {name for name, _ in runner._migration_plan(vault) if name[:3].isdigit() and int(name[:3]) <= 15}
    )
    meta = {
        "version": 2,
        "id": "work",
        "slug": "gmail",
        "label": "Work",
        "added_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "permissions": {"email": "r"},
    }
    (creds / "work.meta").write_text(json.dumps(meta))
    (creds / "work.enc").write_bytes(b"ciphertext sentinel")
    (vault / ".master-key").write_bytes(b"key sentinel")
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "mail.json").write_text('{"tool_categories":["email","memory"]}')
    runner.run_migrations(tmp_path)
    assert json.loads((creds / "work.meta").read_text())["version"] == 3
    assert json.loads((skills / "mail.json").read_text())["tool_categories"] == ["integration:work", "memory"]
    assert (creds / "work.enc").read_bytes() == b"ciphertext sentinel"
    assert (vault / ".master-key").read_bytes() == b"key sentinel"
    snapshot = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    runner.run_migrations(tmp_path)
    assert snapshot == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("fail", [False, True])
def test_bootstrap_restores_separate_owners_even_after_failure(tmp_path, monkeypatch, fail):
    from migrations import __main__ as startup

    state, vault = tmp_path / "state", tmp_path / "state" / "vault"
    external = tmp_path / "outside"
    external.mkdir()
    (external / "untouched").touch()

    def migrate(state, vault):
        (state / "skill.json").write_text("{}")
        (vault / "meta").write_text("{}")
        (state / "link").symlink_to(external, target_is_directory=True)
        if fail:
            raise RuntimeError("stop startup")

    monkeypatch.setattr(startup, "run_migrations", migrate)
    chowns = []
    monkeypatch.setattr(os, "chown", lambda path, uid, gid, **kw: chowns.append((Path(path), uid, gid, kw)))
    kwargs = dict(app_uid=1000, app_gid=1000, broker_uid=1001, broker_gid=1001)
    if fail:
        with pytest.raises(RuntimeError, match="stop startup"):
            bootstrap(state, vault, **kwargs)
    else:
        bootstrap(state, vault, **kwargs)
    assert (vault / "meta", 1001, 1001, {"follow_symlinks": False}) in chowns
    assert (state / "skill.json", 1000, 1000, {"follow_symlinks": False}) in chowns
    assert not any(path == external or external in path.parents for path, *_ in chowns)
    assert not any(uid == 1000 and (path == vault or vault in path.parents) for path, uid, *_ in chowns)
    assert vault.stat().st_mode & 0o777 == 0o700


def test_entrypoint_has_failure_stopping_barrier_before_services():
    root = Path(__file__).resolve().parents[3]
    script = (root / "container/entrypoint.sh").read_text()
    barrier = script.index("python3.12 -m migrations || exit 1")
    assert barrier < script.index("\nXvfb ")
    assert barrier < script.index("gosu broker python3.12 -m brokering.supervisor")
    assert barrier < script.index("gosu omnideck python3.12 main.py")
    assert "run_vault_migrations" not in (root / "brokering/supervisor/_lifecycle.py").read_text()
    assert "_run_data_migrations" not in (root / "server/aiohttp_app.py").read_text()
