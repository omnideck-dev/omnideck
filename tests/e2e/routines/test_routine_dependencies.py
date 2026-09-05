"""Public API coverage for the actual background runner and a delegated DAG."""

import time

import pytest

from tests.e2e._api import ApiClient
from tests.e2e._protocol import call_tool, say, spawn
from tests.e2e.api.agent_runs.test_contract import (
    _conversation_id, _default_profile_id, _run_agent, _stop_and_delete_conversation,
)


def test_routine_dependency_and_delegated_task_complete_in_background(api_client: ApiClient) -> None:
    conversation_id = _conversation_id("routine_dag")
    profile = _default_profile_id(api_client)
    description = f"Runtime dependency contract {time.time_ns()}"
    routine_id = None
    draft = {
        "description": description, "cron": "0 0 1 1 *", "timezone": "UTC",
        "tasks": [
            {"key": "first", "description": "Gather", "agent_profile": profile, "depends_on": [],
             "instruction": spawn(say("delegated findings"), profile=profile, name="RESEARCHER") + say("first result")},
            {"key": "second", "description": "Summarize", "agent_profile": profile, "depends_on": ["first"],
             "instruction": say("second result")},
        ],
    }
    try:
        events = _run_agent(api_client, conversation_id=conversation_id, profile_id=profile,
                            message=call_tool("commit_routine", draft=draft) + say("planned"))
        assert not any(e["payload"]["type"] == "error" for e in events)
        matches = [r for r in api_client.get("/api/routines").json()["routines"] if r["description"] == description]
        assert len(matches) == 1
        routine_id = matches[0]["id"]
        response = api_client.post(f"/api/routines/{routine_id}/trigger")
        assert response.status in (200, 201), response.text
        deadline = time.monotonic() + 30
        while True:
            detail = api_client.get(f"/api/routines/{routine_id}").json()
            if detail["runs"] and detail["runs"][0]["status"] in ("completed", "failed"):
                break
            if time.monotonic() >= deadline:
                pytest.fail(f"dependency run did not finish: {detail}")
            time.sleep(0.1)
        run = detail["runs"][0]
        assert run["status"] == "completed", detail
        results = run["task_results"]
        assert len(results) == 2 and all(r["status"] == "completed" for r in results)
        assert {r["result"] for r in results} == {"first result", "second result"}
        assert len({r["conversation_id"] for r in results}) == 2
        assert all(r["retry_count"] == 0 for r in results)
        first = next(r for r in results if r["result"] == "first result")
        second = next(r for r in results if r["result"] == "second result")
        assert first["completed_at"] <= second["started_at"]
    finally:
        if routine_id:
            api_client.delete(f"/api/routines/{routine_id}")
        _stop_and_delete_conversation(api_client, conversation_id)
