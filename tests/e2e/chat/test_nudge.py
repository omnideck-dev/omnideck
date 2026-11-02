"""Nudge UI drives actual running/completed agents through the public API."""

from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, say, spawn
from tests.e2e._runtime import delete_conversation, resume
from tests.e2e.pages import ChatView, NetworkView


def test_nudge_sends_correct_agent_id(page: Page):
    captured = {}
    page.on("request", lambda request: captured.update(request.post_data_json)
            if request.method == "POST" and request.url.endswith("/api/chat") else None)
    chat = ChatView(page).goto().new_conversation()
    try:
        chat.send(spawn(bash("sleep 8") + say("obsolete answer"), name="research_agent") + say("parent done"))
        network = NetworkView(page)
        expect(network.indicator).to_be_visible(timeout=10_000)
        network.open()
        activity = network.select_agent(1)
        nudge_input = activity.root.locator("input[placeholder*='Send a nudge']")
        nudge_input.fill("hey focus on the API")
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/api/nudge")) as sent:
            nudge_input.press("Enter")
        response = sent.value
        assert response.status == 200, response.text()
        assert response.request.post_data_json["agent_id"] == activity.agent_id
        assert response.request.post_data_json["message"] == "hey focus on the API"
        expect(page.locator("[role='region'][aria-label='Notifications']")).to_contain_text("Nudge sent")
        expect(activity.root).to_contain_text("hey focus on the API", timeout=15_000)
        network.back_to_chat()
        chat.wait_streaming(timeout=15_000)
        events = resume(captured["conversation_id"])["events"]
        nudges = [e for e in events if e["type"] == "user_message" and e.get("is_nudge")]
        assert len(nudges) == 1 and nudges[0]["agent_id"] == activity.agent_id
        assert any(e["type"] == "iteration" and e["agent_id"] == activity.agent_id
                   and e["content"] == "hey focus on the API" for e in events)
    finally:
        if captured:
            delete_conversation(captured["conversation_id"])


def test_nudge_shows_error_toast_on_409(page: Page):
    captured = {}
    page.on("request", lambda request: captured.update(request.post_data_json)
            if request.method == "POST" and request.url.endswith("/api/chat") else None)
    chat = ChatView(page).goto().new_conversation()
    try:
        chat.send(spawn(say("finished"), name="research_agent") + say("parent done")).wait_streaming()
        network = NetworkView(page).open()
        activity = network.select_agent(1)
        nudge_input = activity.root.locator("input[placeholder*='Send a nudge']")
        nudge_input.fill("hello")
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/api/nudge")) as sent:
            nudge_input.press("Enter")
        assert sent.value.status == 409
        assert sent.value.json() == {"error": "No active turn for this conversation."}
        expect(page.locator("[role='region'][aria-label='Notifications']")).to_contain_text("no longer running")
    finally:
        if captured:
            delete_conversation(captured["conversation_id"])
