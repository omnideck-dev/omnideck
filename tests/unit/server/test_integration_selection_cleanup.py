"""Deletion and stale-editor saves use real stores with a controlled supervisor."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from agents._agent_profiles import AgentProfile, get_agent_profile, save_agent_profile
from brokering.supervisor_client import SupervisorError
from server._integration_cache import INTEGRATION_CACHE_KEY
from server._integration_selections import SELECTION_MUTATION_LOCK, save_selection_record
from server._integrations_routes import handle_remove_integration
from skills._store import SkillRecord, get_skill_record, save_skill_record


@pytest.fixture
def records(tmp_path, monkeypatch):
    monkeypatch.setattr("agents._agent_profiles._profiles_dir", lambda: tmp_path / "profiles")
    monkeypatch.setattr("skills._store._skills_dir", lambda: tmp_path / "skills")
    categories = ["memory", "integration:deleted", "integration:kept"]
    for enabled in (True, False):
        save_agent_profile(AgentProfile(id=str(enabled), name=f"Agent {enabled}", enabled=enabled,
                                       skills=["skill"], system_prompt="Keep instructions", tool_categories=categories))
    save_skill_record(SkillRecord(id="skill", name="Skill", prompt="Keep skill instructions", tool_categories=categories))
    request = MagicMock()
    request.match_info = {"id": "deleted"}
    request.app = {
        SELECTION_MUTATION_LOCK: asyncio.Lock(),
        INTEGRATION_CACHE_KEY: MagicMock(refresh=AsyncMock(return_value=True)),
    }
    return request


@pytest.mark.parametrize("absent", [False, True])
async def test_delete_cleans_profiles_including_disabled_and_skills(records, monkeypatch, absent):
    rpc = AsyncMock(side_effect=SupervisorError("NOT_FOUND", "Absent") if absent else None)
    monkeypatch.setattr("server._integrations_routes._supervisor_call", rpc)
    before = [get_agent_profile(str(enabled)).model_dump() for enabled in (True, False)]
    skill_before = get_skill_record("skill").model_dump()
    assert (await handle_remove_integration(records)).status == 204
    for original in before:
        original["tool_categories"] = ["memory", "integration:kept"]
        assert get_agent_profile(original["id"]).model_dump() == original
    skill_before["tool_categories"] = ["memory", "integration:kept"]
    assert get_skill_record("skill").model_dump() == skill_before


@pytest.mark.parametrize("error", [OSError("Offline"), SupervisorError("PERMISSION_DENIED", "Denied")])
async def test_failed_delete_preserves_all_assignments(records, monkeypatch, error):
    monkeypatch.setattr("server._integrations_routes._supervisor_call", AsyncMock(side_effect=error))
    assert (await handle_remove_integration(records)).status in (403, 503)
    for record in (get_agent_profile("True"), get_agent_profile("False"), get_skill_record("skill")):
        assert "integration:deleted" in record.tool_categories
    records.app[INTEGRATION_CACHE_KEY].refresh.assert_not_awaited()


async def test_partial_cleanup_can_be_retried_after_connection_is_gone(records, monkeypatch):
    monkeypatch.setattr("server._integrations_routes._supervisor_call", AsyncMock(side_effect=[
        {}, SupervisorError("NOT_FOUND", "Absent"),
    ]))
    with monkeypatch.context() as failing:
        failing.setattr("server._integration_selections.save_skill_record", MagicMock(side_effect=OSError("Disk full")))
        assert (await handle_remove_integration(records)).status == 503
    assert "integration:deleted" not in get_agent_profile("True").tool_categories
    assert "integration:deleted" in get_skill_record("skill").tool_categories
    assert (await handle_remove_integration(records)).status == 204
    assert "integration:deleted" not in get_skill_record("skill").tool_categories


@pytest.mark.parametrize("kind", ["agent", "skill"])
async def test_stale_save_strips_deleted_connection_but_keeps_stopped_connection(records, monkeypatch, kind):
    monkeypatch.setattr("server._integration_selections.supervisor_call", AsyncMock(return_value={
        "connections": [{"id": "kept", "state": "stopped"}],
    }))
    record, save = ((get_agent_profile("True"), save_agent_profile) if kind == "agent"
                    else (get_skill_record("skill"), save_skill_record))
    saved = await save_selection_record(records, record, save)
    assert saved.tool_categories == ["memory", "integration:kept"]


@pytest.mark.parametrize("result", [OSError("Offline"), {}, {"connections": None}, {"connections": [{}]}])
async def test_unavailable_or_invalid_authoritative_list_never_erases_selections(records, monkeypatch, result):
    rpc = AsyncMock(side_effect=result) if isinstance(result, Exception) else AsyncMock(return_value=result)
    monkeypatch.setattr("server._integration_selections.supervisor_call", rpc)
    with pytest.raises(web.HTTPServiceUnavailable):
        await save_selection_record(records, get_skill_record("skill"), save_skill_record)
    assert get_skill_record("skill").tool_categories == ["memory", "integration:deleted", "integration:kept"]


async def test_save_waits_for_delete_cleanup_then_cannot_restore_connection(records, monkeypatch):
    deleting, finish_delete = asyncio.Event(), asyncio.Event()
    stale = get_agent_profile("True")

    async def remove(*_args):
        deleting.set()
        await finish_delete.wait()
        return {}

    monkeypatch.setattr("server._integrations_routes._supervisor_call", remove)
    list_connections = AsyncMock(return_value={"connections": [{"id": "kept"}]})
    monkeypatch.setattr("server._integration_selections.supervisor_call", list_connections)
    deletion = asyncio.create_task(handle_remove_integration(records))
    await deleting.wait()
    saving = asyncio.create_task(save_selection_record(records, stale, save_agent_profile))
    await asyncio.sleep(0)
    list_connections.assert_not_awaited()
    finish_delete.set()
    response, saved = await asyncio.gather(deletion, saving)
    assert response.status == 204
    assert saved.tool_categories == ["memory", "integration:kept"]
