"""Real HTTP controls reaching a root/child SDK loop and durable events."""

import json

import pytest

from tests.e2e._api import ApiClient
from tests.e2e._protocol import bash, say, slow, spawn
from .test_contract import _conversation_id, _default_profile_id, _resume, _stop_and_delete_conversation


@pytest.mark.parametrize("action,child", [("nudge", False), ("nudge", True), ("stop", True)],
                         ids=["nudge-root", "nudge-child", "stop-child"])
def test_control_reaches_running_agent_and_is_persisted(api_client: ApiClient, action: str, child: bool) -> None:
    conversation = _conversation_id(f"{action}_{child}")
    profile = _default_profile_id(api_client)
    body = (bash("sleep 2") + say("obsolete answer")) if action == "nudge" else (
        slow() + say("child partial " * 250 + "UNREACHED-TAIL")
    )
    message = spawn(body, profile=profile, name="CHILD") + say("parent done") if child else body
    response = api_client.open_stream("POST", "/api/chat", data={
        "conversation_id": conversation, "profile_id": profile, "message": message,
    }, timeout=15)
    events = []
    try:
        assert response.status == 200
        while True:
            raw = response.readline()
            assert raw, "run ended before control could be sent"
            event = json.loads(raw)
            events.append(event)
            p = event["payload"]
            is_target = event.get("depth", 0) == (1 if child else 0)
            ready = (p["type"] == "iteration" and any(
                tc["name"] == "run_bash_cmd" for tc in p.get("tool_calls", [])
            )) if action == "nudge" else p["type"] == "content"
            if is_target and ready:
                target_id = event["agent_id"]
                break
        if action == "nudge":
            control = api_client.post("/api/nudge", data={
                "conversation_id": conversation, "agent_id": target_id, "message": say("new priority answer"),
            })
        else:
            control = api_client.post(f"/api/chat/stop?conversation_id={conversation}")
        assert control.status == 200, control.text
        events.extend(json.loads(line) for line in response.read().decode().splitlines() if line.strip())
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
        assert sum(e["payload"]["type"] == "turn_end" for e in events) == 1
        assert events[-1]["payload"]["type"] == "turn_end"
        snapshot = _resume(api_client, conversation)
        assert snapshot["active_run"] is None
        persisted = snapshot["events"]
        ends = [e for e in persisted if e["type"] == "agent_completed"]
        assert len(ends) == (2 if child else 1)
        assert {e["status"] for e in ends} == ({"success"} if action == "nudge" else {"stopped"})
        iterations = [e for e in persisted if e["type"] == "iteration" and e["agent_id"] == target_id]
        if action == "nudge":
            nudges = [e for e in persisted if e["type"] == "user_message" and e.get("is_nudge")]
            assert len(nudges) == 1 and nudges[0]["agent_id"] == target_id
            assert iterations[-1]["content"] == "new priority answer"
            assert not any(e.get("content") == "obsolete answer" for e in iterations)
        else:
            assert "child partial" in iterations[-1]["content"]
            assert "UNREACHED-TAIL" not in iterations[-1]["content"]
    finally:
        response.close()
        _stop_and_delete_conversation(api_client, conversation)
