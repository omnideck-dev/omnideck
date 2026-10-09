"""Oversized real tools spill, remain inspectable, and do not poison chat reload."""

import json
import re
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import bash, call_tool, say
from tests.e2e._runtime import agent_profile, delete_conversation, resume
from tests.e2e.pages import ChatView


@pytest.mark.parametrize("tool", ["grep", "read_file", "run_bash_cmd"])
def test_oversized_output_can_be_inspected_and_chat_continues_after_reload(page: Page, tool):
    source = f"/tmp/e2e-output-{uuid4().hex}.txt"
    captured = {}
    responses = []
    saved_paths = set()
    page.on("request", lambda request: captured.update(request.post_data_json)
            if request.method == "POST" and request.url.endswith("/api/chat") else None)
    page.on("response", lambda response: responses.append(response)
            if response.request.method == "POST" and response.url.endswith("/api/chat") else None)
    with agent_profile(allow_spawn=False, context_window=1_048_576) as profile:
        try:
            chat = ChatView(page).goto().new_conversation()
            page.get_by_label("Agent profile").click()
            page.get_by_role("option", name=profile["name"], exact=True).click()
            # Generate large data with a real tool; the prompt itself stays small.
            create = bash(f"python3 -c \"from pathlib import Path; Path('{source}').write_text(('needle ' + 'abcdef0123456789' * 100 + '\\n') * 200)\"")
            args = {"path": source}
            if tool == "grep":
                args.update(pattern="needle", context=0)
            elif tool == "run_bash_cmd":
                args = {"cmd": f"cat {source}"}
            chat.send(create + call_tool(tool, **args) + say("large output handled")).wait_streaming(20_000)
            expect(page.get_by_test_id("entry-content").last).to_contain_text("large output handled")
            conversation = captured["conversation_id"]
            snapshot = resume(conversation)
            results = [e["content"] for e in snapshot["events"]
                       if e["type"] == "tool_result" and e["tool_name"] == tool and "temporary file:" in e["content"]]
            assert len(results) == 1
            notice = results[0]
            path = re.search(r"temporary file: (.+)\n", notice)[1]
            saved_paths.add(path)
            assert path.startswith("/tmp/")
            assert int(container_exec(f"from pathlib import Path; print(Path({path!r}).stat().st_size)")) > 64 * 1024
            assert len(notice.encode()) < 1500
            streamed = [json.loads(line) for response in responses for line in response.text().splitlines() if line]
            assert any(e["payload"].get("content") == notice for e in streamed)
            assert not any(e["payload"]["type"] == "error" for e in streamed)

            page.reload()
            expect(page.get_by_test_id("entry-content").last).to_contain_text("large output handled")
            chat.send(call_tool("grep", path=path, pattern="needle", context=0) + say("saved output inspected")).wait_streaming(20_000)
            expect(page.get_by_test_id("entry-content").last).to_contain_text("saved output inspected")
            latest = resume(conversation)
            inspection = [e["content"] for e in latest["events"] if e["type"] == "tool_result" and e["tool_name"] == "grep"][-1]
            assert "needle" in inspection and "temporary file:" not in inspection
            chat.send(say("next turn still works")).wait_streaming()
            expect(page.get_by_test_id("entry-content").last).to_contain_text("next turn still works")
            assert all(e["status"] == "success" for e in resume(conversation)["events"] if e["type"] == "agent_completed")
        finally:
            if captured.get("conversation_id"):
                delete_conversation(captured["conversation_id"])
            container_exec(f"from pathlib import Path; [Path(p).unlink(missing_ok=True) for p in {list(saved_paths | {source})!r}]")


def test_grep_timeout_keeps_app_responsive_and_next_turn_works(page: Page):
    source = f"/tmp/e2e-regex-{uuid4().hex}.txt"
    captured = {}
    page.on("request", lambda request: captured.update(request.post_data_json)
            if request.method == "POST" and request.url.endswith("/api/chat") else None)
    try:
        chat = ChatView(page).goto().new_conversation()
        chat.send(bash(f"python3 -c \"from pathlib import Path; Path('{source}').write_text('aaaa\\n' + 'a' * 100 + '!\\n')\"")
                  + call_tool("grep", path=source, pattern="(a+)+$", context=0) + say("search limit handled"))
        expect(chat.stop_button).to_be_visible()
        # A normal HTTP request must not wait for the blocking regex to finish.
        response = page.request.get("/api/settings", timeout=2000)
        assert response.ok
        chat.wait_streaming(20_000)
        expect(page.get_by_test_id("entry-content").last).to_contain_text("search limit handled")
        snapshot = resume(captured["conversation_id"])
        result = next(e["content"] for e in snapshot["events"] if e["type"] == "tool_result" and e["tool_name"] == "grep")
        assert "Search stopped after 10 seconds" in result
        assert "aaaa" in result and "incomplete" in result
        chat.send(say("recovered after timeout")).wait_streaming()
        expect(page.get_by_test_id("entry-content").last).to_contain_text("recovered after timeout")
    finally:
        if captured.get("conversation_id"):
            delete_conversation(captured["conversation_id"])
        container_exec(f"from pathlib import Path; Path({source!r}).unlink(missing_ok=True)")
