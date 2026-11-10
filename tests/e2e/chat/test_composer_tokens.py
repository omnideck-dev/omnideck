"""End-to-end: `/skill` composer tokens through real chat execution.

The composer's tokens are rewritten into an explicit natural-language
instruction only in the model-facing view built at read time — the
stored/displayed message stays exactly what the user typed. Against the fake
provider these tests only prove the enriched view still round-trips through
the real HTTP/agent-runtime pipeline without corrupting the scripted
directives embedded in it — proving the model actually *chooses* to call
load_skill because of the enrichment requires a real provider, which these
tests don't have available.
"""

from uuid import uuid4

from playwright.sync_api import Page

from tests.e2e._protocol import model_script, model_tool
from tests.e2e._runtime import agent_profile, delete_conversation, run_turn


def tool_calls(events, name):
    return [e["payload"] for e in events if e["payload"]["type"] == "tool_call" and e["payload"]["name"] == name]


def test_bare_skill_token_loads_skill_in_same_run(page: Page):
    conversation = f"e2e_composer_load_{uuid4().hex}"
    with agent_profile(skills=[]) as profile:
        try:
            events = run_turn(
                conversation,
                "/coder " + model_script(
                    {"tool_calls": [model_tool("load_skill", name="coder")]},
                    {"content": "loaded"},
                ),
                profile_id=profile["id"],
            )
            assert tool_calls(events, "load_skill")
            assert tool_calls(events, "spawn_agent") == []
        finally:
            delete_conversation(conversation)

