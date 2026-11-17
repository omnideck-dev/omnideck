"""Coordinate connection deletion with saves of connection-bound selections."""

import asyncio
import json
from collections.abc import Callable
from typing import TypeVar

from aiohttp import web

from agents._agent_profiles import AgentProfile, list_agent_profiles, save_agent_profile
from brokering.supervisor_client import SupervisorError
from server._brokering import supervisor_call
from skills._store import SkillRecord, list_skill_records, save_skill_record

SELECTION_MUTATION_LOCK = web.AppKey("integration_selection_mutation_lock", asyncio.Lock)
Record = TypeVar("Record", AgentProfile, SkillRecord)


def remove_integration_assignments(connection_id: str) -> None:
    """Remove exactly this connection from all saved profiles and skills.

    Called only after confirmed removal/absence, never from discovery polling.
    Repeating after a partial storage failure is safe; unrelated fields remain.
    """
    category_id = f"integration:{connection_id}"
    for profile in list_agent_profiles(include_disabled=True):
        if category_id in profile.tool_categories:
            save_agent_profile(profile.model_copy(update={
                "tool_categories": [item for item in profile.tool_categories if item != category_id],
            }))
    for skill in list_skill_records():
        if category_id in skill.tool_categories:
            save_skill_record(skill.model_copy(update={
                "tool_categories": [item for item in skill.tool_categories if item != category_id],
            }))


async def save_selection_record(
    request: web.Request, record: Record, save: Callable[[Record], Record],
) -> Record:
    """Save a draft without reintroducing connections deleted in another editor.

    The authoritative list includes stopped connections. Failure blocks the save
    rather than interpreting an unavailable discovery cache as deletion. Holding
    the same lock as DELETE closes the list/check/write race within the app.
    """
    if not any(item.startswith("integration:") for item in record.tool_categories):
        return save(record)
    async with request.app[SELECTION_MUTATION_LOCK]:
        try:
            result = await supervisor_call("list", {"kind": "integration"})
            connections = result["connections"]
            if not isinstance(connections, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("id"), str)
                for item in connections
            ):
                raise ValueError("Invalid connection list")
            valid = {f"integration:{item['id']}" for item in connections}
        except (OSError, SupervisorError, KeyError, TypeError, ValueError) as exc:
            raise web.HTTPServiceUnavailable(
                text=json.dumps({"message": "Could not verify integrations. Try saving again."}),
                content_type="application/json",
            ) from exc
        return save(record.model_copy(update={"tool_categories": [
            item for item in record.tool_categories
            if not item.startswith("integration:") or item in valid
        ]}))
