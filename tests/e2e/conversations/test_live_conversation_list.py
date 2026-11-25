"""Chat list changes made in one page reach another open page without a reload."""

import json

from playwright.sync_api import BrowserContext, Page, expect

from tests.e2e._activity_relay import ActivityRelay, activity_relay
from tests.e2e._api import ApiClient
from tests.e2e._protocol import say
from tests.e2e._runtime import delete_conversation
from tests.e2e.pages import ChatView, RecentConversations

_LIST_URL = '/api/conversations/sessions'


def _probe_script(relay_url: str | None = None) -> str:
    return "const activityRelayUrl = " + json.dumps(relay_url) + ";" + """
        const NativeEventSource = window.EventSource;
        window.__activityProbe = { opens: 0, errors: 0, messages: [], source: null };
        window.EventSource = class extends NativeEventSource {
            constructor(url, options) {
                const activity = new URL(url, location.href).pathname === '/api/chat/activity';
                super(activity && activityRelayUrl ? activityRelayUrl : url, options);
                if (!activity) return;
                const probe = window.__activityProbe;
                probe.source = this;
                this.addEventListener('open', () => { probe.opens += 1; });
                this.addEventListener('error', () => { probe.errors += 1; });
                this.addEventListener('message', ({ data }) => {
                    probe.messages.push({ connection: probe.opens, event: JSON.parse(data) });
                });
            }
        };
    """


class Watcher:
    """A second open page that only watches its chat list."""

    def __init__(self, context: BrowserContext, relay_url: str | None = None):
        self.page = context.new_page()
        self.page.set_default_timeout(5_000)
        self.page.add_init_script(_probe_script(relay_url))
        self.list_loads = 0
        self.page.on('request', self._count)
        with self.page.expect_response(lambda response: response.url.endswith(_LIST_URL)):
            ChatView(self.page).goto()
        self.recent = RecentConversations(self.page)
        expect(self.recent.root).to_be_visible()
        self.page.wait_for_function(
            "__activityProbe.messages.some(({ event }) => event.type === 'conversation_resync')",
        )

    def _count(self, request) -> None:
        if request.method == 'GET' and request.url.endswith(_LIST_URL):
            self.list_loads += 1

    def row(self, cid: str):
        return self.page.locator(f'[data-testid="recent-item"][data-conversation-id="{cid}"]')

    def archived_row(self, cid: str):
        return self.recent.archived_item_by_id(cid).root


def _start_chat(page: Page, text: str) -> str:
    chat = ChatView(page)
    chat.new_conversation()
    with page.expect_request(lambda req: req.method == 'POST' and req.url.endswith('/api/chat')) as started:
        chat.send(say(text))
    chat.wait_streaming()
    return started.value.post_data_json['conversation_id']


def test_a_chat_started_in_one_page_appears_in_another_open_page(page: Page):
    ChatView(page).goto()
    watcher = Watcher(page.context)
    cid = None
    try:
        cid = _start_chat(page, 'LIVE-CREATED')

        expect(watcher.row(cid)).to_be_visible(timeout=10_000)
        assert watcher.list_loads == 1
    finally:
        if cid:
            delete_conversation(cid)


def test_rename_pin_archive_restore_and_delete_reach_another_open_page(page: Page):
    ChatView(page).goto()
    cid = _start_chat(page, 'LIVE-MANAGED')
    watcher = Watcher(page.context)
    recent = RecentConversations(page)
    try:
        expect(watcher.row(cid)).to_be_visible()

        recent.item_by_id(cid).rename('Renamed in the first page')
        expect(watcher.row(cid)).to_contain_text('Renamed in the first page')

        recent.item_by_id(cid).toggle_pin()
        expect(watcher.row(cid)).to_have_attribute('data-pinned', 'true')

        watcher.recent.expand_archived()
        recent.item_by_id(cid).archive()
        expect(watcher.row(cid)).to_have_count(0)
        expect(watcher.archived_row(cid)).to_be_visible()

        recent.expand_archived()
        recent.archived_item_by_id(cid).restore()
        expect(watcher.archived_row(cid)).to_have_count(0)
        expect(watcher.row(cid)).to_contain_text('Renamed in the first page')

        recent.item_by_id(cid).delete()
        expect(watcher.row(cid)).to_have_count(0)
        expect(watcher.archived_row(cid)).to_have_count(0)
        assert watcher.list_loads == 1
    finally:
        delete_conversation(cid)


def test_a_reconnected_page_catches_up_on_changes_it_missed(page: Page, api_client: ApiClient):
    with activity_relay(api_client) as relay:
        _assert_catches_up(page, relay)


def _assert_catches_up(page: Page, relay: ActivityRelay):
    ChatView(page).goto()
    renamed = _start_chat(page, 'LIVE-BEFORE-DISCONNECT')
    watcher = Watcher(page.context, relay.url)
    created = None
    try:
        expect(watcher.row(renamed)).to_be_visible()
        before = watcher.page.evaluate('({ opens: __activityProbe.opens, errors: __activityProbe.errors })')

        relay.disconnect()
        watcher.page.wait_for_function(
            "errors => __activityProbe.errors > errors && __activityProbe.source.readyState === EventSource.CONNECTING",
            arg=before['errors'],
        )
        RecentConversations(page).item_by_id(renamed).rename('Renamed while disconnected')
        created = _start_chat(page, 'LIVE-WHILE-DISCONNECTED')
        expect(watcher.row(created)).to_have_count(0)
        expect(watcher.row(renamed)).not_to_contain_text('Renamed while disconnected')

        relay.resume()
        watcher.page.wait_for_function('opens => __activityProbe.opens > opens', arg=before['opens'], timeout=15_000)

        expect(watcher.row(created)).to_be_visible(timeout=10_000)
        expect(watcher.row(renamed)).to_contain_text('Renamed while disconnected')
        assert watcher.list_loads == 2
    finally:
        delete_conversation(renamed)
        if created:
            delete_conversation(created)
