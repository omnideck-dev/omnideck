"""Capability behavior through real chat execution, persistence, and the UI."""

from uuid import uuid4

from playwright.sync_api import Page, expect

from tests.e2e._protocol import model_script, model_tool, say, spawn
from tests.e2e._runtime import agent_profile, delete_conversation, resume, run_turn
from tests.e2e.pages import ChatView, RecentConversations


def tool_results(events, name):
    return [e["payload"] for e in events if e["payload"]["type"] == "tool_result" and e["payload"]["tool_name"] == name]


def test_loaded_capabilities_restore_on_the_next_turn(page: Page):
    conversation = f"e2e_capabilities_{uuid4().hex}"
    with agent_profile(skills=[]) as profile:
        try:
            first = run_turn(
                conversation,
                model_script(
                    {"tool_calls": [model_tool("load_skill", name="coder")]},
                    {"tool_calls": [model_tool("run_bash_cmd", cmd="printf first-capability-proof")]},
                    {"content": "first execution complete"},
                ),
                profile_id=profile["id"],
            )
            assert "first-capability-proof" in tool_results(first, "run_bash_cmd")[0]["content"]
            second = run_turn(
                conversation,
                model_script(
                    {"tool_calls": [model_tool("run_bash_cmd", cmd="printf restored-capability-proof")]},
                    {"content": "restored execution complete"},
                ),
                profile_id=profile["id"],
            )
            assert tool_results(second, "load_skill") == []
            assert "restored-capability-proof" in tool_results(second, "run_bash_cmd")[0]["content"]
            assert [e["payload"]["type"] for e in second].count("turn_end") == 1
            ChatView(page).goto().new_conversation()
            RecentConversations(page).open_by_id(conversation)
            expect(page.get_by_test_id("message-assistant").last).to_contain_text("restored execution complete")
            completed = [e for e in resume(conversation)["events"] if e["type"] == "agent_completed"]
            assert len(completed) == 2 and all(e["status"] == "success" for e in completed)
        finally:
            delete_conversation(conversation)


def test_child_load_does_not_grant_tools_to_parent(page: Page):
    conversation = f"e2e_child_capabilities_{uuid4().hex}"
    with agent_profile(skills=[]) as parent, agent_profile(skills=[]) as child:
        try:
            child_prompt = model_script(
                {"tool_calls": [model_tool("load_skill", name="coder")]},
                {"tool_calls": [model_tool("run_bash_cmd", cmd="printf child-capability-proof")]},
                {"content": "child complete"},
            )
            first = run_turn(
                conversation,
                spawn(child_prompt, profile=child["id"], name="CHILD") + say("parent complete"),
                profile_id=parent["id"],
            )
            assert "child-capability-proof" in tool_results(first, "run_bash_cmd")[0]["content"]
            # FakeProvider auto-loads missing tool skills, including for MODEL
            # scripts. Explicitly request the load and verify it is fresh; an
            # inherited or persisted child skill would report already loaded.
            second = run_turn(
                conversation,
                model_script(
                    {"tool_calls": [model_tool("load_skill", name="coder")]},
                    {"tool_calls": [model_tool("run_bash_cmd", cmd="printf independent-parent-proof")]},
                    {"content": "parent remains isolated"},
                ),
                profile_id=parent["id"],
            )
            result = tool_results(second, "load_skill")[0]["content"]
            assert "Loaded skill" in result and "already loaded" not in result, result
            assert "independent-parent-proof" in tool_results(second, "run_bash_cmd")[0]["content"]
            assert [e["payload"]["type"] for e in first].count("turn_end") == 1
            ChatView(page).goto().new_conversation()
            RecentConversations(page).open_by_id(conversation)
            expect(page.get_by_test_id("message-assistant").last).to_contain_text("parent remains isolated")
        finally:
            delete_conversation(conversation)
