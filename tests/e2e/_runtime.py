"""Produce E2E fixtures through real agent execution and public storage APIs."""

import json
import os
import time
from contextlib import contextmanager
from uuid import uuid4

from ._api import ApiClient
from ._protocol import model_script, model_tool


def api() -> ApiClient:
    return ApiClient(os.environ["OMNIDECK_URL"])


def default_profile() -> str:
    return api().get("/api/settings").json()["default_agent"]


def run_turn(conversation_id, message, *, profile_id=None, attachments=None):
    response = api().post("/api/chat", data={
        "conversation_id": conversation_id, "profile_id": profile_id or default_profile(),
        "message": message, "data": attachments,
    }, timeout=30)
    assert response.status == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events and events[-1]["payload"]["type"] == "turn_end"
    assert not any(e["payload"]["type"] == "error" for e in events), events
    return events


def resume(conversation_id):
    response = api().post(f"/api/conversations/sessions/{conversation_id}/resume")
    assert response.status == 200, response.text
    return response.json()


def update_conversation(conversation_id, **metadata):
    response = api().request("PATCH", f"/api/conversations/sessions/{conversation_id}", data=metadata)
    assert response.status == 204, response.text


def create_conversation(conversation_id, messages, *, title="", pinned=False):
    """Run user/assistant examples through the model protocol, then set metadata."""
    for i, message in enumerate(messages):
        if message["role"] != "user":
            continue
        following = messages[i + 1] if i + 1 < len(messages) else None
        prompt = message["content"]
        if following and following["role"] == "assistant":
            prompt += "\n" + model_script({"content": following["content"]})
        run_turn(conversation_id, prompt)
    update_conversation(conversation_id, title=title, pinned=pinned)
    return conversation_id


def delete_conversation(conversation_id):
    client = api()
    client.post(f"/api/chat/stop?conversation_id={conversation_id}")
    for _ in range(60):
        snapshot = client.post(f"/api/conversations/sessions/{conversation_id}/resume")
        if snapshot.status != 200 or snapshot.json().get("active_run") is None:
            break
        time.sleep(0.1)
    response = client.delete(f"/api/conversations/sessions/{conversation_id}")
    assert response.status in (204, 404), response.text


@contextmanager
def agent_profile(**options):
    identifier = f"e2e_runtime_{uuid4().hex}"
    values = {
        "id": identifier, "name": identifier, "provider": "ollama", "model": "fake-model",
        "system_prompt": "Follow the task.", "skills": ["coder"],
        "allow_spawn": True, "allow_load_skills": True, "context_window": 100_000,
        "max_iterations": 20, **options,
    }
    created = api().post("/api/profiles", data=values)
    assert created.status == 201, created.text
    try:
        yield created.json()
    finally:
        api().delete(f"/api/profiles/{identifier}")


@contextmanager
def compaction_settings():
    client = api()
    settings = client.get("/api/settings").json()
    original = {key: settings.get(key) for key in ("compaction_provider", "compaction_model")}
    changed = client.request("PUT", "/api/settings", data={
        "compaction_provider": "ollama", "compaction_model": "fake-model",
    })
    assert changed.status == 200, changed.text
    try:
        yield
    finally:
        client.request("PUT", "/api/settings", data=original)


def compaction_script():
    """Three real tool iterations trigger one compaction before the final response."""
    return model_script(*[
        {"content": f"pre-compaction work {i}", "tool_calls": [model_tool(
            "run_bash_cmd",
            # Enough real output to shrink when the summarizer caps tool text,
            # while remaining below the profile's tool-result safety limit.
            cmd="printf 'step zero %.0s' {1..250}" if i == 0 else f"printf 'step {i}'",
        )]}
        for i in range(3)
    ], {"content": "post-compaction work"})
