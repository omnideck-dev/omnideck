"""Messages sent while the agent works wait in the queue strip until the agent reads them."""

from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, say
from tests.e2e._runtime import delete_conversation, resume
from tests.e2e.pages import ChatView
from tests.e2e.pages.goals_view import goal_conversation

QUEUE_TITLE = "Queued for the agent's next step"


def _start_slow_run(page: Page, captured: dict) -> ChatView:
    page.on("request", lambda request: captured.update(request.post_data_json)
            if request.method == "POST" and request.url.endswith("/api/chat") else None)
    chat = ChatView(page).goto().new_conversation()
    chat.send(bash("sleep 8") + say("first step done"))
    expect(chat.stop_button).to_be_visible(timeout=10_000)
    page.wait_for_timeout(2_000)
    expect(chat.composer).to_have_attribute("placeholder", "Message the agent while it works…")
    return chat


def test_message_sent_during_a_tool_call_waits_in_the_strip_then_moves_into_the_chat(page: Page):
    captured = {}
    chat = _start_slow_run(page, captured)
    try:
        with page.expect_response(lambda r: r.url.endswith("/api/chat")
                                  and (r.request.post_data_json or {}).get("message") == "Also check Thursday") as sent:
            chat.send("Also check Thursday")
        assert sent.value.status == 202, sent.value.text()
        strip = page.get_by_role("region", name=QUEUE_TITLE)
        expect(strip).to_contain_text("Also check Thursday")
        expect(chat.composer).to_have_value("")
        expect(page.locator("[role='region'][aria-label='Notifications']")).not_to_contain_text("sent")
        expect(page.get_by_test_id("message-user").filter(has_text="Also check Thursday")).to_be_visible(timeout=20_000)
        expect(strip).to_have_count(0)
        chat.wait_streaming(timeout=20_000)
        events = resume(captured["conversation_id"])["events"]
        read = [e for e in events if e["type"] == "user_message" and e["content"] == "Also check Thursday"]
        assert len(read) == 1 and read[0]["nudge_id"]
        assert not any(e["type"] in ("nudge_queued", "nudge_removed") for e in events)
    finally:
        if captured:
            delete_conversation(captured["conversation_id"])


def test_removing_a_queued_message_keeps_it_from_the_agent(page: Page):
    captured = {}
    chat = _start_slow_run(page, captured)
    try:
        chat.send("Forget the calendar")
        strip = page.get_by_role("region", name=QUEUE_TITLE)
        expect(strip).to_contain_text("Forget the calendar")
        with page.expect_response(lambda r: r.request.method == "DELETE" and "/api/chat/nudges/" in r.url) as removed:
            strip.get_by_role("button", name="Remove queued message").click()
        assert removed.value.status == 200, removed.value.text()
        expect(strip).to_have_count(0)
        chat.wait_streaming(timeout=20_000)
        expect(page.get_by_test_id("message-assistant").filter(has_text="first step done")).to_be_visible()
        events = resume(captured["conversation_id"])["events"]
        assert not any(e["type"] == "user_message" and "Forget the calendar" in e["content"] for e in events)
        assert not any(e["type"] == "iteration" and "Forget the calendar" in (e.get("content") or "") for e in events)
    finally:
        if captured:
            delete_conversation(captured["conversation_id"])


def test_clicking_a_queued_message_puts_it_back_in_the_box(page: Page):
    captured = {}
    chat = _start_slow_run(page, captured)
    try:
        chat.send("Check Friday too")
        strip = page.get_by_role("region", name=QUEUE_TITLE)
        strip.get_by_role("button", name="Check Friday too").click()
        expect(strip).to_have_count(0)
        expect(chat.composer).to_have_value("Check Friday too")
    finally:
        if captured:
            delete_conversation(captured["conversation_id"])


def test_stop_returns_queued_text_to_the_message_box(page: Page):
    captured = {}
    chat = _start_slow_run(page, captured)
    try:
        chat.send("First note")
        chat.send("Second note")
        strip = page.get_by_role("region", name=QUEUE_TITLE)
        expect(strip).to_contain_text("Second note")
        chat.stop_button.click()
        chat.wait_streaming(timeout=20_000)
        expect(strip).to_have_count(0)
        expect(chat.composer).to_have_value("First note\nSecond note")
    finally:
        if captured:
            delete_conversation(captured["conversation_id"])


def test_answers_return_to_the_card_when_stop_ends_the_run(page: Page):
    with goal_conversation(page) as view:
        view.assign()
        view.ask()
        view.questions.get_by_role("button", name="Hide", exact=True).click()
        view.composer.fill(bash("sleep 8") + say("Still checking."))
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(page.get_by_test_id("chat-stop-btn")).to_be_visible(timeout=8_000)
        page.get_by_role("button", name="Show goal questions", exact=True).click()
        page.get_by_role("button", name="Saturday", exact=True).click()
        page.get_by_role("button", name="Send answer", exact=True).click()
        strip = page.get_by_role("region", name=QUEUE_TITLE)
        expect(strip).to_contain_text("Answers to 1 question")
        expect(view.questions).not_to_contain_text("Which day works for you?")
        page.get_by_test_id("chat-stop-btn").click()
        expect(strip).to_have_count(0, timeout=20_000)
        expect(view.questions).to_contain_text("of 2")
        view.questions.get_by_role("button", name="Question 1, answer drafted", exact=True).click()
        expect(view.questions).to_contain_text("Which day works for you?")
        expect(page.get_by_role("button", name="Saturday", exact=True)).to_have_attribute("aria-pressed", "true")
        assert all(not question["answers"] for question in view.current()["questions"])
