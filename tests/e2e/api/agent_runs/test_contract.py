"""E2E characterization tests for the application-level agent-run contract.

These tests intentionally inspect the real ``/api/chat`` JSONL response and
the real conversation-resume API. UI tests can still pass when lifecycle
events are duplicated, reordered, or omitted, so this file protects the
backend behavior while its execution code moves behind ``AgentRunner``.
"""

from __future__ import annotations

import json
import time

from tests.e2e._api import ApiClient
from tests.e2e._protocol import provider_fail, say, slow


def _conversation_id(label: str) -> str:
    return f"e2e_agent_run_{label}_{time.time_ns()}"


def _default_profile_id(api_client: ApiClient) -> str:
    response = api_client.get("/api/settings")
    assert response.status == 200
    settings = response.json()
    profile_id = settings.get("default_agent")
    assert isinstance(profile_id, str) and profile_id
    return profile_id


def _run_agent(
    api_client: ApiClient,
    *,
    conversation_id: str,
    profile_id: str,
    message: str,
) -> list[dict]:
    response = api_client.post(
        "/api/chat",
        data={
            "conversation_id": conversation_id,
            "profile_id": profile_id,
            "message": message,
        },
        timeout=20,
    )
    body = response.text
    assert response.status == 200, f"agent run failed with {response.status}: {body}"
    events = [json.loads(line) for line in body.splitlines() if line.strip()]
    assert events, "agent run returned an empty event stream"
    return events


def _resume(api_client: ApiClient, conversation_id: str) -> dict:
    response = api_client.post(
        f"/api/conversations/sessions/{conversation_id}/resume",
    )
    assert response.status == 200, f"conversation resume failed with {response.status}: {response.text}"
    return response.json()


def _delete_conversation(
    api_client: ApiClient,
    conversation_id: str,
) -> None:
    api_client.delete(f"/api/conversations/sessions/{conversation_id}")


def _payload_types(events: list[dict]) -> list[str]:
    return [event["payload"]["type"] for event in events]


def _assert_one_complete_lifecycle(events: list[dict], *, status: str) -> None:
    types = _payload_types(events)
    assert types.count("agent_started") == 1
    assert types.count("user_message") == 1
    assert types.count("agent_completed") == 1
    assert types.count("turn_end") == 1
    assert types[-1] == "turn_end"

    started_index = types.index("agent_started")
    user_index = types.index("user_message")
    completed_index = types.index("agent_completed")
    assert started_index < user_index < completed_index < len(types) - 1

    started = events[started_index]["payload"]
    completed = events[completed_index]["payload"]
    assert started["agent_id"] == completed["agent_id"]
    assert completed["status"] == status

    ids = [event["id"] for event in events]
    assert len(ids) == len(set(ids)), "the stream contains duplicate event IDs"
    run_ids = {event["run_id"] for event in events}
    assert len(run_ids) == 1
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))


def test_resume_discovers_disconnected_run_and_replays_to_completion(
    api_client: ApiClient,
) -> None:
    """Closing the initial HTTP body does not cancel its manager-owned run."""
    conversation_id = _conversation_id("disconnect_replay")
    profile_id = _default_profile_id(api_client)
    tail_marker = f"RECONNECTED-TAIL-{time.time_ns()}"
    body = ("keep running after disconnect " * 50) + tail_marker

    response = api_client.open_stream(
        "POST",
        "/api/chat",
        data={
            "conversation_id": conversation_id,
            "profile_id": profile_id,
            "message": slow() + say(body),
        },
        timeout=10,
    )
    prefix: list[dict] = []
    try:
        assert response.status == 200
        while True:
            raw = response.readline()
            assert raw, "initial stream ended before producing content"
            event = json.loads(raw)
            prefix.append(event)
            if event["payload"]["type"] == "content":
                break
    finally:
        response.close()

    # Let several records land with no subscriber so the GET must replay a gap
    # before it transitions to following live events.
    time.sleep(0.25)

    snapshot = _resume(api_client, conversation_id)
    active_run = snapshot["active_run"]
    assert active_run is not None
    assert active_run["run_id"] == prefix[-1]["run_id"]
    assert active_run["status"] == "running"
    assert active_run["last_seq"] >= prefix[-1]["seq"]
    after_seq = active_run["resume_after_seq"]
    assert 0 <= after_seq <= active_run["last_seq"]
    run_id = active_run["run_id"]

    resumed_response = api_client.get(
        f"/api/chat/runs/{run_id}/events?after={after_seq}",
        timeout=20,
    )
    assert resumed_response.status == 200, resumed_response.text
    tail = [
        json.loads(line)
        for line in resumed_response.text.splitlines()
        if line.strip()
    ]

    try:
        assert tail
        assert tail[0]["seq"] == after_seq + 1
        assert [event["seq"] for event in tail] == list(
            range(after_seq + 1, after_seq + 1 + len(tail)),
        )
        assert {event["run_id"] for event in tail} == {run_id}
        assert tail[-1]["payload"]["type"] == "turn_end"
        iteration = next(
            event for event in tail if event["payload"]["type"] == "iteration"
        )
        assert tail_marker in iteration["payload"]["content"]

        completed = api_client.get(
            f"/api/chat/runs/{run_id}/events?after={tail[-1]['seq']}",
        )
        assert completed.status == 404
        final_snapshot = _resume(api_client, conversation_id)
        assert final_snapshot["active_run"] is None
        persisted_iterations = [
            event
            for event in final_snapshot["events"]
            if event["type"] == "iteration"
        ]
        assert tail_marker in persisted_iterations[-1]["content"]
    finally:
        _delete_conversation(api_client, conversation_id)


def test_successful_runs_preserve_stream_and_persistence_contract(
    api_client: ApiClient,
) -> None:
    """Two runs preserve lifecycle order and append canonical events once."""
    conversation_id = _conversation_id("success")
    profile_id = _default_profile_id(api_client)
    first_token = f"FIRST-{time.time_ns()}"
    second_token = f"SECOND-{time.time_ns()}"
    first_prompt = say(first_token)
    second_prompt = say(second_token)

    try:
        first = _run_agent(
            api_client,
            conversation_id=conversation_id,
            profile_id=profile_id,
            message=first_prompt,
        )
        second = _run_agent(
            api_client,
            conversation_id=conversation_id,
            profile_id=profile_id,
            message=second_prompt,
        )

        _assert_one_complete_lifecycle(first, status="success")
        _assert_one_complete_lifecycle(second, status="success")
        assert _payload_types(first).count("iteration") == 1
        assert _payload_types(second).count("iteration") == 1

        first_user = next(event for event in first if event["payload"]["type"] == "user_message")
        second_user = next(event for event in second if event["payload"]["type"] == "user_message")
        assert first_user["payload"]["content"] == first_prompt
        assert second_user["payload"]["content"] == second_prompt

        first_iteration = next(event for event in first if event["payload"]["type"] == "iteration")
        second_iteration = next(event for event in second if event["payload"]["type"] == "iteration")
        assert first_iteration["payload"]["content"] == first_token
        assert second_iteration["payload"]["content"] == second_token

        resumed = _resume(api_client, conversation_id)
        persisted = resumed["events"]
        persisted_types = [event["type"] for event in persisted]
        for required_type in (
            "agent_started",
            "user_message",
            "iteration",
            "agent_completed",
        ):
            assert persisted_types.count(required_type) == 2
        assert resumed["profile_id"] == profile_id

        streamed = [*first, *second]
        streamed_ids = [event["id"] for event in streamed]
        persisted_ids = [event["id"] for event in persisted]
        persisted_id_set = set(persisted_ids)
        assert persisted_ids == [event_id for event_id in streamed_ids if event_id in persisted_id_set], (
            "disk persistence changed stream order or duplicated an event"
        )
        assert len(persisted_ids) == len(set(persisted_ids))
    finally:
        _delete_conversation(api_client, conversation_id)


def test_provider_failure_preserves_single_error_and_terminal_event(
    api_client: ApiClient,
) -> None:
    """A runner failure produces one error, one failed lifecycle, and one end."""
    conversation_id = _conversation_id("provider_failure")
    profile_id = _default_profile_id(api_client)
    error_message = f"contract failure {time.time_ns()}"

    try:
        events = _run_agent(
            api_client,
            conversation_id=conversation_id,
            profile_id=profile_id,
            message=provider_fail(error_message),
        )

        _assert_one_complete_lifecycle(events, status="error")
        types = _payload_types(events)
        assert types.count("error") == 1
        error = next(event for event in events if event["payload"]["type"] == "error")
        assert error_message in error["payload"]["message"]

        resumed = _resume(api_client, conversation_id)
        persisted_errors = [event for event in resumed["events"] if event["type"] == "error"]
        assert len(persisted_errors) == 1
        assert persisted_errors[0]["id"] == error["id"]
        assert persisted_errors[0]["message"] == error["payload"]["message"]
    finally:
        _delete_conversation(api_client, conversation_id)


def test_preflight_failure_still_closes_the_stream(
    api_client: ApiClient,
) -> None:
    """Failure before agent setup remains a visible error followed by turn_end."""
    conversation_id = _conversation_id("preflight_failure")
    profile_id = f"e2e-invalid-runner-profile-{time.time_ns()}"
    response = api_client.post(
        "/api/profiles",
        data={
            "id": profile_id,
            "name": "Invalid runner profile",
            "provider": "",
            "model": "configured-without-a-provider",
            "system_prompt": "",
            "skills": [],
        },
    )
    assert response.status == 201, f"failed to create setup-failure profile: {response.text}"

    try:
        events = _run_agent(
            api_client,
            conversation_id=conversation_id,
            profile_id=profile_id,
            message="this must not reach a provider",
        )

        assert _payload_types(events) == ["error", "turn_end"]
        assert events[0]["payload"]["message"] == ("An error occurred while processing your message.")
    finally:
        _delete_conversation(api_client, conversation_id)
        api_client.delete(f"/api/profiles/{profile_id}")
