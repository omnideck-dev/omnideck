import json

import pytest

from migrations._016_connection_tool_categories import NAME, CLEANUP_NAME
from migrations._runner import run_migrations, _migration_plan
from packs._pack import Pack, PackedProfile, PackedSkill, import_pack


@pytest.fixture(autouse=True)
def migrated_app_history(tmp_path):
    (tmp_path / ".migrations.json").write_text(json.dumps([
        name for name, _fn in _migration_plan(tmp_path / "vault") if name not in (NAME, CLEANUP_NAME)
    ]))


def _connection(state, iid, grants, *, kind="integration", credentials=True):
    creds = state / "vault" / "creds"
    creds.mkdir(parents=True, exist_ok=True)
    (creds / f"{iid}.meta").write_text(json.dumps({
        "id": iid, "version": 3, "kind": kind, "agent_operation_grants": grants,
    }))
    if credentials:
        (creds / f"{iid}.enc").write_bytes(b"opaque credentials; never decrypted")


@pytest.mark.unit
def test_migration_freezes_existing_connections_and_keeps_backup(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    original = {"id": "mail", "name": "Mail", "tool_categories": ["email", "calendar", "memory", "mcp"]}
    path = skills / "mail.json"
    path.write_text(json.dumps(original))
    profiles = tmp_path / "agent_profiles"
    profiles.mkdir()
    (profiles / "a.json").write_text('{"id":"a","name":"A"}')
    _connection(tmp_path, "one", ["email.messages.search", "calendar.events.list"])
    _connection(tmp_path, "provider", ["email.messages.search"], kind="model_provider")
    _connection(tmp_path, "orphan", ["email.messages.search"], credentials=False)
    run_migrations(tmp_path)
    assert json.loads(path.read_text())["tool_categories"] == ["integration:one", "memory"]
    assert json.loads((tmp_path / "migration-backups" / NAME / "skills" / "mail.json").read_text()) == original
    assert json.loads((profiles / "a.json").read_text())["tool_categories"] == []
    _connection(tmp_path, "later", ["email.messages.search"])
    run_migrations(tmp_path)
    assert "integration:later" not in path.read_text()


@pytest.mark.unit
def test_failed_migration_resumes_frozen_mapping(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "mail.json").write_text('broken')
    _connection(tmp_path, "one", ["email.messages.search"])
    with pytest.raises(json.JSONDecodeError):
        run_migrations(tmp_path)
    (skills / "mail.json").write_text('{"tool_categories":["email"]}')
    _connection(tmp_path, "two", ["email.messages.search"])
    run_migrations(tmp_path)
    assert json.loads((skills / "mail.json").read_text())["tool_categories"] == ["integration:one"]


@pytest.mark.unit
def test_packs_do_not_transfer_connection_authority():
    for cls in (PackedSkill, PackedProfile):
        packed = cls(name="Test", tool_categories=["integration:same-id", "email", "mcp", "memory"])
        assert packed.tool_categories == ["memory"]


@pytest.mark.unit
def test_pack_cannot_import_browser_as_a_direct_tool():
    pack = Pack(profiles=[PackedProfile(name="Test", tool_categories=["browser"])])
    with pytest.raises(ValueError, match="configured locally"):
        import_pack(pack)


@pytest.mark.unit
def test_cleanup_of_migrated_preview_does_not_select_new_connections(tmp_path):
    ledger = tmp_path / ".migrations.json"
    ledger.write_text(json.dumps([*json.loads(ledger.read_text()), NAME]))
    (tmp_path / "skills").mkdir()
    path = tmp_path / "skills" / "mail.json"
    original = {"tool_categories": ["email", "calendar", "memory", "integration:offline", "unknown"]}
    path.write_text(json.dumps(original))
    _connection(tmp_path, "later", ["email.messages.search"])
    run_migrations(tmp_path)
    assert json.loads(path.read_text())["tool_categories"] == ["memory", "integration:offline", "unknown"]
    backup = tmp_path / "migration-backups" / CLEANUP_NAME / "skills" / "mail.json"
    assert json.loads(backup.read_text()) == original
    run_migrations(tmp_path)
    assert json.loads(backup.read_text()) == original
