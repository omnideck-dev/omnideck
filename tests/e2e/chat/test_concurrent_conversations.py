"""Concurrent chats retain independent runs and browser-session activity indicators."""

import json
import time

import pytest

from playwright.sync_api import Page, expect

from tests.e2e._activity_relay import activity_relay
from tests.e2e._api import ApiClient
from tests.e2e._protocol import bash, fail, say, slow
from tests.e2e.pages import ChatView, RecentConversations
from tests.e2e.pages.desktop_layout import DesktopLayout


def _start(page: Page, chat: ChatView, marker: str) -> str:
    with page.expect_request(lambda req: req.method == 'POST' and req.url.endswith('/api/chat')) as started:
        chat.send(slow() + say((marker + ' ') * 250))
    cid = started.value.post_data_json['conversation_id']
    expect(_indicator(page, cid)).to_have_attribute('data-status', 'running')
    expect(page.get_by_test_id('message-assistant').last).to_contain_text(marker)
    return cid


def _row(page: Page, cid: str):
    return page.locator(f'[data-testid="recent-item"][data-conversation-id="{cid}"]')


def _indicator(page: Page, cid: str):
    return _row(page, cid).get_by_test_id('conversation-activity')


def _resume(page: Page, cid: str) -> dict:
    return page.request.post(f'/api/conversations/sessions/{cid}/resume').json()


def test_switching_running_chats_and_explicit_stop_are_independent(page: Page):
    chat = ChatView(page).goto().new_conversation()
    first = _start(page, chat, 'FIRST-CONCURRENT')
    chat.new_conversation()
    second = _start(page, chat, 'SECOND-CONCURRENT')
    assert _resume(page, first)['active_run'] is not None
    assert _resume(page, second)['active_run'] is not None

    RecentConversations(page).open_by_id(first)
    expect(chat.stop_button).to_be_visible()
    expect(page.get_by_test_id('message-assistant').last).to_contain_text('FIRST-CONCURRENT')
    expect(page.get_by_test_id('message-assistant').last).not_to_contain_text('SECOND-CONCURRENT')
    chat.stop_button.click()
    chat.wait_streaming()
    expect(_indicator(page, first)).to_have_count(0)
    assert _resume(page, second)['active_run'] is not None

    RecentConversations(page).open_by_id(second)
    expect(chat.stop_button).to_be_visible()
    expect(page.get_by_test_id('message-assistant').last).not_to_contain_text('FIRST-CONCURRENT')
    chat.new_conversation()
    expect(_indicator(page, second)).to_have_attribute('data-status', 'finished', timeout=30000)
    RecentConversations(page).open_by_id(second)
    expect(_indicator(page, second)).to_have_count(0)
    expect(page.get_by_test_id('message-assistant').last).to_contain_text('SECOND-CONCURRENT')
    expect(page.get_by_test_id('message-user')).to_have_count(1)


def test_activity_reconnect_reconciles_finished_background_run_and_reload_clears_dot(
    page: Page, api_client: ApiClient,
):
    with activity_relay(api_client) as relay:
        _assert_activity_reconnect(page, api_client, relay)


def _assert_activity_reconnect(page, api_client, relay):
    # Observe native transport and route only its URL through a real network relay.
    page.add_init_script("const activityRelayUrl = " + json.dumps(relay.url) + ";" + """
        const NativeEventSource = window.EventSource;
        window.__activityProbe = { opens: 0, errors: 0, messages: [], source: null };
        window.EventSource = class extends NativeEventSource {
            constructor(url, options) {
                const activity = new URL(url, location.href).pathname === '/api/chat/activity';
                super(activity ? activityRelayUrl : url, options);
                if (new URL(url, location.href).pathname !== '/api/chat/activity') return;
                const probe = window.__activityProbe;
                probe.source = this;
                this.addEventListener('open', () => { probe.opens += 1; });
                this.addEventListener('error', () => { probe.errors += 1; });
                this.addEventListener('message', ({ data }) => {
                    probe.messages.push({ connection: probe.opens, event: JSON.parse(data) });
                });
            }
        };
    """)
    chat = ChatView(page).goto().new_conversation()
    cid = _start(page, chat, 'OFFLINE-CONCURRENT')
    chat.new_conversation()
    before = page.evaluate('({ opens: __activityProbe.opens, errors: __activityProbe.errors })')
    assert before['opens'] >= 1
    assert api_client.post(f'/api/conversations/sessions/{cid}/resume').json()['active_run'] is not None
    relay.disconnect()
    try:
        page.wait_for_function(
            "errors => __activityProbe.errors > errors && __activityProbe.source.readyState === EventSource.CONNECTING",
            arg=before['errors'],
        )
        messages_at_disconnect = page.evaluate('__activityProbe.messages.length')
        # Poll the real server independently of the disconnected browser, rather than
        # assuming a fixed sleep was long enough for completion.
        deadline = time.monotonic() + 30
        while True:
            snapshot = api_client.post(f'/api/conversations/sessions/{cid}/resume').json()
            if snapshot['active_run'] is None:
                break
            assert time.monotonic() < deadline, 'Background run did not finish'
            page.wait_for_timeout(100)
        assert any(event['type'] == 'agent_completed' for event in snapshot['events'])
        assert page.evaluate('__activityProbe.messages.length') == messages_at_disconnect
        expect(_indicator(page, cid)).to_have_attribute('data-status', 'running')
    finally:
        with page.expect_response(
            lambda response: response.url == relay.url and response.status == 200, timeout=10000,
        ):
            relay.resume()
    page.wait_for_function('opens => __activityProbe.opens > opens', arg=before['opens'])
    expect(_indicator(page, cid)).to_have_attribute('data-status', 'finished', timeout=10000)
    messages = page.evaluate('__activityProbe.messages')
    reconnect_snapshots = [
        item['event'] for item in messages
        if item['connection'] > before['opens'] and item['event']['type'] == 'snapshot'
    ]
    assert reconnect_snapshots
    assert all(run['conversation_id'] != cid for run in reconnect_snapshots[0]['runs'])
    assert not any(
        item['event']['type'] == 'finished'
        and any(run['conversation_id'] == cid for run in item['event']['runs'])
        for item in messages
    )
    page.reload()
    expect(_row(page, cid)).to_be_visible()
    expect(_indicator(page, cid)).to_have_count(0)


def test_fresh_browser_load_discovers_running_chat(page: Page):
    chat = ChatView(page).goto().new_conversation()
    cid = _start(page, chat, 'RELOAD-CONCURRENT')
    chat.new_conversation()
    page.reload()
    expect(_indicator(page, cid)).to_have_attribute('data-status', 'running')
    RecentConversations(page).open_by_id(cid)
    expect(chat.stop_button).to_be_visible()
    chat.stop_button.click()
    chat.wait_streaming()
    expect(_indicator(page, cid)).to_have_count(0)


@pytest.mark.parametrize('outcome', ['stopped', 'error'])
def test_background_stop_and_failure_both_show_finished_dot(page: Page, outcome: str):
    chat = ChatView(page).goto().new_conversation()
    if outcome == 'stopped':
        cid = _start(page, chat, 'STOP-BACKGROUND')
    else:
        with page.expect_request(lambda req: req.method == 'POST' and req.url.endswith('/api/chat')) as started:
            chat.send(bash('sleep 3') + fail('Background test failure'))
        cid = started.value.post_data_json['conversation_id']
        expect(_indicator(page, cid)).to_have_attribute('data-status', 'running')
    chat.new_conversation()
    if outcome == 'stopped':
        response = page.request.post(f'/api/chat/stop?conversation_id={cid}')
        assert response.ok
    expect(_indicator(page, cid)).to_have_attribute('data-status', 'finished', timeout=10000)
    snapshot = _resume(page, cid)
    completed = [event for event in snapshot['events'] if event['type'] == 'agent_completed']
    assert completed[-1]['status'] == outcome
    RecentConversations(page).open_by_id(cid)
    expect(_indicator(page, cid)).to_have_count(0)


@pytest.mark.parametrize('failure', ['http', 'network'])
def test_failed_navigation_preserves_live_chat_stop_and_draft(page: Page, failure: str):
    chat = ChatView(page).goto().new_conversation()
    with page.expect_request(lambda req: req.method == 'POST' and req.url.endswith('/api/chat')) as destination_request:
        chat.send(say('Destination ready'))
    destination = destination_request.value.post_data_json['conversation_id']
    chat.wait_streaming()
    chat.new_conversation()
    current = _start(page, chat, 'NAVIGATION-STILL-RUNNING')
    chat.composer.fill('Keep this draft')
    destination_url = f'**/api/conversations/sessions/{destination}/resume'

    def fail_load(route):
        if failure == 'network':
            route.abort('failed')
        else:
            route.fulfill(status=503, content_type='application/json', body='{"error":"Unavailable"}')

    page.route(destination_url, fail_load)
    RecentConversations(page).open_by_id(destination)
    expect(page.get_by_text("Couldn't open that conversation. Your current chat is still open.")).to_be_visible()
    expect(chat.stop_button).to_be_visible()
    expect(chat.composer).to_have_value('Keep this draft')
    expect(_indicator(page, current)).to_have_attribute('data-status', 'running')
    assistant = page.get_by_test_id('message-assistant').last
    before = len(assistant.inner_text())
    page.wait_for_function(
        """length => {
            const messages = document.querySelectorAll('[data-testid="message-assistant"]');
            return messages[messages.length - 1]?.innerText.length > length;
        }""",
        arg=before,
    )
    with page.expect_request(lambda req: '/api/chat/stop?' in req.url) as stopped:
        chat.stop_button.click()
    assert f'conversation_id={current}' in stopped.value.url
    chat.wait_streaming()
    assert _resume(page, current)['active_run'] is None

    page.unroute(destination_url, fail_load)
    RecentConversations(page).open_by_id(destination)
    expect(page.get_by_test_id('message-assistant').last).to_contain_text('Destination ready')
    expect(page.get_by_test_id('message-assistant').last).not_to_contain_text('NAVIGATION-STILL-RUNNING')


def test_hidden_selected_chat_completion_shows_dot_until_reopened(page: Page):
    chat = ChatView(page).goto().new_conversation()
    cid = _start(page, chat, 'HIDDEN-SELECTED')
    desktop = DesktopLayout(page)
    page.get_by_test_id('sidebar-settings').click()
    expect(desktop.view('destination:conversation')).to_have_attribute('data-visible', 'false')
    expect(_indicator(page, cid)).to_have_attribute('data-status', 'finished', timeout=30000)
    RecentConversations(page).open_by_id(cid)
    expect(desktop.view('destination:conversation')).to_have_attribute('data-visible', 'true')
    expect(_indicator(page, cid)).to_have_count(0)
    expect(page.get_by_test_id('message-assistant').last).to_contain_text('HIDDEN-SELECTED')


def test_visible_split_chat_completion_has_no_dot_when_other_pane_is_focused(page: Page):
    chat = ChatView(page).goto().new_conversation()
    cid = _start(page, chat, 'VISIBLE-SPLIT')
    desktop = DesktopLayout(page)
    page.get_by_test_id('sidebar-settings').click()
    desktop.move('destination:settings', 'right')
    expect(desktop.view('destination:conversation')).to_have_attribute('data-visible', 'true')
    expect(desktop.view('destination:settings')).to_have_attribute('data-visible', 'true')
    desktop.tab('destination:settings').click()
    expect(desktop.tab('destination:settings')).to_be_focused()
    chat.wait_streaming()
    expect(_indicator(page, cid)).to_have_count(0)
    assert _resume(page, cid)['active_run'] is None
    # Hiding the chat afterward must not reveal a completion dot that was merely masked.
    desktop.move('destination:settings', 'left')
    expect(desktop.view('destination:conversation')).to_have_attribute('data-visible', 'false')
    expect(_indicator(page, cid)).to_have_count(0)


def test_fullscreen_covering_chat_records_unseen_completion(page: Page):
    chat = ChatView(page).goto().new_conversation()
    cid = _start(page, chat, 'FULLSCREEN-COVERED')
    desktop = DesktopLayout(page)
    page.get_by_test_id('sidebar-settings').click()
    desktop.move('destination:settings', 'right')
    desktop.maximize('destination:settings')
    expect(desktop.view('destination:conversation')).to_have_attribute('data-visible', 'false')
    expect(_indicator(page, cid)).to_have_attribute('data-status', 'finished', timeout=30000)
    desktop.restore('destination:settings')
    expect(desktop.view('destination:conversation')).to_have_attribute('data-visible', 'true')
    expect(_indicator(page, cid)).to_have_count(0)
