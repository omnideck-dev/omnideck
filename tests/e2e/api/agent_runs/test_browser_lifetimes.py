"""Browser ownership through actual FakeProvider runs and public APIs."""

from uuid import uuid4

import pytest

from tests.e2e._protocol import open_url, say, spawn
from tests.e2e._runtime import agent_profile, delete_conversation, run_turn
from tests.e2e.preview._browser_fixture import fixture_url, install_fixture


@pytest.mark.parametrize("ending", ["archive", "delete"])
def test_conversation_retains_root_browser_across_turns_and_releases_it_on_removal(api_client, ending):
    install_fixture()
    conversation = f"e2e-browser-scope-{uuid4().hex}"
    preview = f"/api/browser/conversations/{conversation}/preview"
    with agent_profile(browser_profile_id="empty", skills=[]) as profile:
        try:
            first = run_turn(conversation, open_url(fixture_url("profile-seed") + "&value=root") + say("ready"),
                             profile_id=profile["id"])
            assert any(event["payload"]["type"] == "browser_screenshot" for event in first)
            assert api_client.get(preview).status == 200

            # The child changes its own storage. The next root turn must retain
            # the first turn's browser state, even after that child completes.
            run_turn(conversation, spawn(open_url(fixture_url("profile-seed") + "&value=child") + say("done"),
                                         profile=profile["id"]) + say("delegated"), profile_id=profile["id"])
            events = run_turn(conversation, open_url(fixture_url("profile-report")) + say("checked"),
                              profile_id=profile["id"])
            urls = [event["payload"]["url"] for event in events if event["payload"]["type"] == "browser_screenshot"]
            assert any("mode=profile-result&cookie=root&local=root&indexed=root" in url for url in urls), urls
            assert api_client.get(preview).status == 200

            path = f"/api/conversations/sessions/{conversation}"
            removed = api_client.post(path + "/archive") if ending == "archive" else api_client.delete(path)
            assert removed.status == 204, removed.text
            assert api_client.get(preview).status == 404
            if ending == "archive":
                assert api_client.post(path + "/unarchive").status == 204
                # Restoring persisted history must not resurrect a live browser.
                assert api_client.post(path + "/resume").status == 200
                assert api_client.get(preview).status == 404
        finally:
            api_client.post(f"/api/conversations/sessions/{conversation}/unarchive")
            delete_conversation(conversation)
