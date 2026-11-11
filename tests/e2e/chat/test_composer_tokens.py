"""End-to-end: a `/skill` composer token loads the skill before the agent runs."""

from uuid import uuid4

from playwright.sync_api import Page

from tests.e2e._protocol import model_script
from tests.e2e._runtime import agent_profile, delete_conversation, run_turn


def payloads(events, event_type):
    return [e["payload"] for e in events if e["payload"]["type"] == event_type]


def test_skill_token_loads_skill_without_a_model_tool_call(page: Page):
    conversation = f"e2e_composer_load_{uuid4().hex}"
    with agent_profile(skills=[]) as profile:
        try:
            message = "/coder " + model_script({"content": "done"})
            events = run_turn(conversation, message, profile_id=profile["id"])

            loaded = payloads(events, "skill_loaded")
            assert [(p["skill_id"], p["status"]) for p in loaded] == [("coder", "loaded")]
            assert not [p for p in payloads(events, "tool_call") if p["name"] == "load_skill"]
            assert payloads(events, "user_message")[0]["content"] == message
        finally:
            delete_conversation(conversation)


def test_unknown_token_loads_nothing(page: Page):
    conversation = f"e2e_composer_inert_{uuid4().hex}"
    with agent_profile(skills=[]) as profile:
        try:
            events = run_turn(
                conversation, "check /etc/hosts " + model_script({"content": "ok"}), profile_id=profile["id"],
            )
            assert payloads(events, "skill_loaded") == []
        finally:
            delete_conversation(conversation)
