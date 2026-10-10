"""Goal questions stay in the composer and answers travel through real chat runs."""

import json
import textwrap
from pathlib import Path

from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import call_tool, say
from tests.e2e.pages import ChatView


def test_goal_question_carousel_submits_partial_answers_and_preserves_transcript(page: Page, output_path: str) -> None:
    settings = page.request.get("/api/settings").json()
    assert page.request.put("/api/settings", data={"goals_enabled": True}).ok
    captured = {}

    def capture(request):
        if request.method == "POST" and request.url.endswith("/api/chat"):
            captured.update(json.loads(request.post_data))

    page.on("request", capture)
    chat = ChatView(page).goto().new_conversation()
    chat.send(say("I can help find a dentist.")).wait_streaming()
    conversation_id = captured["conversation_id"]
    base = f"/api/conversations/sessions/{conversation_id}/goal"
    try:
        # Seed through the real persistence contract in the isolated application container.
        container_exec(textwrap.dedent(f"""
            from pathlib import Path
            from config import load_config
            from goals import GoalStore, GoalQuestionChange
            store = GoalStore(Path(load_config().settings.home_dir) / 'session-goals')
            goal = store.create({conversation_id!r}, 'Find and book a dentist', {settings['default_agent']!r})
            goal = store.claim(goal.id, goal.wake_id, 'seed')
            goal = store.update_questions(goal.id, [
                GoalQuestionChange(id='insurance', question='Which insurance plan?', status='open', choices=['Aetna Dental PPO']),
                GoalQuestionChange(id='travel', question='How far can you travel?', status='open'),
            ], '', goal.revision, claim_id='seed')
            store.wait_for_input(goal.id, ['insurance', 'travel'], claim_id='seed')
            store.release(goal.id, 'seed')
        """))
        page.reload()
        expect(page.get_by_label("Goal questions")).to_be_visible(timeout=10000)
        expect(page.get_by_role("textbox", name="Answer the goal question")).to_have_count(1)
        for width, label in [(1280, "desktop"), (390, "mobile")]:
            page.set_viewport_size({"width": width, "height": 900})
            if width == 390:
                page.get_by_role("button", name="Collapse sidebar", exact=True).click()
                expect(page.get_by_test_id("sidebar")).to_have_css("width", "44px")
            composer = page.get_by_label("Goal questions")
            expect(composer).to_be_visible()
            box = composer.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= width
            for name in ["Send answers & resume", "Chat instead", "Next question"]:
                control = page.get_by_role("button", name=name, exact=True).bounding_box()
                assert control and control["x"] >= 0 and control["x"] + control["width"] <= width
            page.screenshot(path=str(Path(output_path) / f"goal-questions-{label}.png"))
        page.set_viewport_size({"width": 1280, "height": 900})
        page.get_by_role("button", name="Expand sidebar", exact=True).click()
        page.get_by_role("button", name="Aetna Dental PPO", exact=True).click()
        page.get_by_role("button", name="Next question").click()
        page.get_by_role("textbox", name="Answer the goal question").fill("Within 10 miles")
        page.get_by_role("button", name="Previous question").click()
        expect(page.get_by_role("textbox", name="Answer the goal question")).to_have_value("Aetna Dental PPO")
        page.reload()
        expect(page.get_by_role("textbox", name="Answer the goal question")).to_have_value("Aetna Dental PPO")
        # Send a partial batch. The unanswered question stays available.
        page.get_by_role("button", name="Next question").click()
        page.get_by_role("textbox", name="Answer the goal question").fill("")
        page.get_by_role("button", name="Send answers & resume").click()
        expect(page.get_by_test_id("message-user").last).to_contain_text("[insurance] Which insurance plan?")
        expect(page.get_by_test_id("message-user").last).to_contain_text("Aetna Dental PPO")
        expect(page.get_by_label("Goal questions")).to_contain_text("How far can you travel?", timeout=10000)
        current = page.request.get(base).json()["goal"]
        assert current["questions"][0]["answers"][0]["answer"] == "Aetna Dental PPO"
        assert current["questions"][0]["status"] == "open"
        assert current["questions"][1]["answers"] == []
        chat.wait_streaming()
        # The real tool closes one question and withdraws the other; history is rendered.
        current = page.request.get(base).json()["goal"]
        message = call_tool("update_goal_questions", changes=[
            {"id": "insurance", "question": "Which insurance plan?", "status": "resolved"},
            {"id": "travel", "question": "How far can you travel?", "status": "withdrawn"},
        ], known_facts="Insurance: Aetna Dental PPO. Search the user's local area.", expected_revision=current["revision"] + 1) + say("The plan is recorded.")
        response = page.request.post("/api/chat", data={"conversation_id": conversation_id, "profile_id": settings["default_agent"], "message": message})
        assert response.ok
        page.reload()
        expect(page.get_by_label("Goal question update")).to_contain_text("No longer needed", timeout=10000)
        expect(page.get_by_label("Goal questions")).to_have_count(0)
        expect(page.get_by_test_id("message-user").filter(has_text="Aetna Dental PPO").first).to_be_visible()
    finally:
        page.request.post(base + "/cancel", data={})
        page.request.delete(f"/api/conversations/sessions/{conversation_id}")
        page.request.put("/api/settings", data={"goals_enabled": settings.get("goals_enabled", False)})


def test_goal_history_loads_older_work_on_demand_and_keeps_current_state_small(page: Page, output_path: str) -> None:
    settings = page.request.get('/api/settings').json()
    assert page.request.put('/api/settings', data={'goals_enabled': True}).ok
    captured = {}
    page.on('request', lambda request: captured.update(json.loads(request.post_data))
            if request.method == 'POST' and request.url.endswith('/api/chat') else None)
    chat = ChatView(page).goto().new_conversation()
    chat.send(say('Reviewing the newsletter campaign.')).wait_streaming()
    conversation_id = captured['conversation_id']
    base = f'/api/conversations/sessions/{conversation_id}/goal'
    history_requests = []
    page.on('request', lambda request: history_requests.append(request.url) if '/goal/history?' in request.url else None)
    try:
        container_exec(textwrap.dedent(f'''
            from pathlib import Path
            from config import load_config
            from goals import GoalStore, GoalStep
            store = GoalStore(Path(load_config().settings.home_dir) / 'session-goals')
            goal = store.create({conversation_id!r}, 'Grow the neighborhood newsletter', {settings['default_agent']!r}, kind='ongoing')
            store.pause(goal.id)
            for index in range(65):
                store.record_progress(goal.id, f'Campaign review {{index}}: checked signups', 'Review next week')
            goal = store.get(goal.id)
            store.update(goal.id, goal.revision, summary='Library referrals brought in new subscribers. Continue the partnership.',
                plan=[GoalStep(id='library', title='Expand the library partnership')], reason='Referrals outperformed paid ads')
        '''))
        page.reload()
        page.get_by_label('Goal: Paused').last.click()
        expect(page.get_by_text('Library referrals brought in new subscribers. Continue the partnership.')).to_be_visible()
        assert history_requests == []
        page.get_by_text('Goal history', exact=True).click()
        expect(page.get_by_text('Campaign review 64: checked signups', exact=True)).to_be_visible()
        assert len(history_requests) == 1
        page.get_by_role('button', name='Load older entries').click()
        expect(page.get_by_text('Campaign review 30: checked signups', exact=True)).to_be_attached()
        page.get_by_role('searchbox', name='Search goal history').fill('Campaign review 0:')
        page.get_by_role('button', name='Search', exact=True).click()
        expect(page.get_by_text('Campaign review 0: checked signups', exact=True)).to_be_visible()
        expect(page.get_by_text('Campaign review 64: checked signups', exact=True)).to_have_count(0)
        page.screenshot(path=str(Path(output_path) / 'goal-history-search.png'))
        snapshot = page.request.get(base).json()['goal']
        assert len(snapshot['progress']) == 20 and snapshot['progress_count'] == 65
        assert snapshot['summary'].startswith('Library referrals')
    finally:
        page.request.post(base + '/cancel', data={})
        page.request.delete(f'/api/conversations/sessions/{conversation_id}')
        page.request.put('/api/settings', data={'goals_enabled': settings.get('goals_enabled', False)})
