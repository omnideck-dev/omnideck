"""Saved reasoning is downloaded only when its activity is opened."""

from playwright.sync_api import expect

from tests.e2e._protocol import model_script, say, spawn
from tests.e2e.pages import ChatView, RecentConversations


def _reopen(page, prompt):
    chat = ChatView(page).goto().new_conversation()
    chat.send(prompt).wait_streaming()
    cid = page.request.get('/api/conversations/sessions').json()[0]['conversation_id']
    chat.new_conversation()
    requests = []
    page.on('request', lambda request: requests.append(request.url) if request.url.endswith('/thinking') else None)
    with page.expect_response(lambda response: response.url.endswith(f'/{cid}/resume')) as resumed:
        RecentConversations(page).open_by_id(cid)
    snapshot = resumed.value.json()
    assert any(event.get('thinking_ref') for event in snapshot['events'])
    assert all(not event.get('thinking') for event in snapshot['events'] if event['type'] == 'iteration')
    expect(page.get_by_test_id('message-assistant').first).to_be_visible()
    assert not requests
    return requests


def test_resumed_root_thinking_loads_when_activity_expands(page):
    text = 'Saved root reasoning remains available.'
    requests = _reopen(page, model_script({'thinking': text, 'content': 'Finished answer'}))
    with page.expect_response(lambda response: response.url.endswith('/thinking')):
        page.get_by_test_id('activity-toggle').first.click()
    expect(page.get_by_test_id('activity-panel')).to_contain_text(text)
    assert len(requests) == 1
    page.get_by_test_id('activity-toggle').first.click()
    page.get_by_test_id('activity-toggle').first.click()
    expect(page.get_by_test_id('activity-panel')).to_contain_text(text)
    assert len(requests) == 1


def test_resumed_child_thinking_loads_when_agent_activity_opens(page):
    text = 'Saved child reasoning remains available.'
    requests = _reopen(page, spawn(model_script({'thinking': text, 'content': 'Child answer'}), name='researcher') + say('Finished'))
    with page.expect_response(lambda response: response.url.endswith('/thinking')):
        page.get_by_test_id('spawn-card-row').first.click()
    expect(page.get_by_test_id('agent-activity-view')).to_contain_text(text)
    assert len(requests) == 1


def test_saved_thinking_can_retry_after_network_failure(page):
    text = 'Reasoning recovered after a network failure.'
    _reopen(page, model_script({'thinking': text, 'content': 'Answer stays visible'}))
    page.route('**/thinking', lambda route: route.fulfill(status=503, body='temporarily unavailable'), times=1)
    page.get_by_test_id('activity-toggle').first.click()
    panel = page.get_by_test_id('activity-panel')
    expect(panel.get_by_role('alert')).to_contain_text('Couldn’t load thinking')
    expect(page.get_by_test_id('message-assistant')).to_contain_text('Answer stays visible')
    panel.get_by_role('button', name='Retry', exact=True).click()
    expect(panel).to_contain_text(text)
    expect(panel.get_by_role('alert')).to_have_count(0)
