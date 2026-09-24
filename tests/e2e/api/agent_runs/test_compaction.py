"""Trigger compaction through the production loop, without seeding events."""

import time

from tests.e2e._api import ApiClient
from .test_contract import _conversation_id, _resume, _run_agent, _stop_and_delete_conversation


def test_real_compaction_is_streamed_persisted_and_can_resume(api_client: ApiClient) -> None:
    conversation = _conversation_id("compaction")
    profile = f"runtime_compaction_{time.time_ns()}"
    settings = api_client.get("/api/settings").json()
    keys = ("compaction_provider", "compaction_model")
    original_compaction = {key: settings.get(key) for key in keys}
    created = api_client.post("/api/profiles", data={
        "id": profile, "name": "Compaction contract", "provider": "ollama", "model": "fake-model",
        "system_prompt": "Respond to the user.", "skills": [], "allow_spawn": False,
        "allow_load_skills": False, "context_window": 1000, "compaction_threshold": 0.01,
    })
    assert created.status == 201, created.text
    try:
        response = api_client.request("PUT", "/api/settings", data={
            "compaction_provider": "ollama", "compaction_model": "fake-model",
        })
        assert response.status == 200, response.text
        streamed = []
        for i in range(4):
            events = _run_agent(api_client, conversation_id=conversation, profile_id=profile,
                                message=f"plain conversation round {i}")
            assert not any(e["payload"]["type"] == "error" for e in events)
            streamed.extend(events)
        compacted = [e for e in streamed if e["payload"]["type"] == "compaction"]
        assert compacted, "the actual context hook never triggered compaction"
        assert all(e["payload"]["summary_text"] for e in compacted)
        snapshot = _resume(api_client, conversation)
        assert snapshot["active_run"] is None
        assert {e["id"] for e in snapshot["events"] if e["type"] == "compaction"} == {e["id"] for e in compacted}
        continued = _run_agent(api_client, conversation_id=conversation, profile_id=profile,
                                message="continue after compaction")
        assert continued[-1]["payload"]["type"] == "turn_end"
        assert [e["payload"]["status"] for e in continued if e["payload"]["type"] == "agent_completed"] == ["success"]
    finally:
        _stop_and_delete_conversation(api_client, conversation)
        api_client.delete(f"/api/profiles/{profile}")
        api_client.request("PUT", "/api/settings", data=original_compaction)
