"""End-to-end: a skill selected in the composer loads before the agent runs."""

import json
from uuid import uuid4

from playwright.sync_api import Page

from tests.e2e._protocol import model_script
from tests.e2e._runtime import agent_profile, api, delete_conversation


def chat(conversation, message, profile_id, skills=None):
    body = {"conversation_id": conversation, "profile_id": profile_id, "message": message}
    if skills:
        body["skills"] = skills
    response = api().post("/api/chat", data=body, timeout=30)
    assert response.status == 200, response.text
    return [json.loads(line)["payload"] for line in response.text.splitlines() if line.strip()]


def of_type(payloads, event_type):
    return [p for p in payloads if p["type"] == event_type]


def test_selected_skill_loads_without_a_model_tool_call(page: Page):
    conversation = f"e2e_composer_load_{uuid4().hex}"
    with agent_profile(skills=[]) as profile:
        try:
            message = "/coder " + model_script({"content": "done"})
            payloads = chat(conversation, message, profile["id"], skills=[{"id": "coder", "name": "coder"}])

            assert [(p["skill_id"], p["status"]) for p in of_type(payloads, "skill_loaded")] == [("coder", "loaded")]
            assert not [p for p in of_type(payloads, "tool_call") if p["name"] == "load_skill"]
        finally:
            delete_conversation(conversation)


def test_shortcut_text_without_a_selection_loads_nothing(page: Page):
    conversation = f"e2e_composer_text_{uuid4().hex}"
    with agent_profile(skills=[]) as profile:
        try:
            payloads = chat(conversation, "/coder " + model_script({"content": "ok"}), profile["id"])
            assert of_type(payloads, "skill_loaded") == []
        finally:
            delete_conversation(conversation)
