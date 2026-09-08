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


@pytest.mark.parametrize("tool", ["search_text", "read_file", "run_bash_cmd"])
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
            if tool == "search_text":
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
            chat.send(call_tool("search_text", path=path, pattern="needle", context=0, max_results=1) + say("saved output inspected")).wait_streaming(20_000)
            expect(page.get_by_test_id("entry-content").last).to_contain_text("saved output inspected")
            latest = resume(conversation)
            inspection = [e["content"] for e in latest["events"] if e["type"] == "tool_result" and e["tool_name"] == "search_text"][-1]
            assert "needle" in inspection and "temporary file:" not in inspection
            chat.send(say("next turn still works")).wait_streaming()
            expect(page.get_by_test_id("entry-content").last).to_contain_text("next turn still works")
            assert all(e["status"] == "success" for e in resume(conversation)["events"] if e["type"] == "agent_completed")
        finally:
            if captured.get("conversation_id"):
                delete_conversation(captured["conversation_id"])
            container_exec(f"from pathlib import Path; [Path(p).unlink(missing_ok=True) for p in {list(saved_paths | {source})!r}]")



def test_file_discovery_and_search_modes_use_real_tools_and_survive_reload(page: Page):
    root = f"/tmp/e2e-search-{uuid4().hex}"
    captured = {}
    page.on("request", lambda request: captured.update(request.post_data_json)
            if request.method == "POST" and request.url.endswith("/api/chat") else None)
    files = {
        "main.py": "before\nHello needle\nafter\n",
        "nested/other.py": "hello needle\nhello again\n",
        ".hidden.txt": "hello hidden\n",
        "ignored.txt": "hello ignored\n",
        ".gitignore": "ignored.txt\n",
        "node_modules/skip.py": "hello excluded\n",
    }
    import shlex
    script = (
        f"from pathlib import Path; root = Path({root!r}); "
        f"[( (root / name).parent.mkdir(parents=True, exist_ok=True), "
        f"(root / name).write_text(text)) for name, text in {files!r}.items()]"
    )
    try:
        chat = ChatView(page).goto().new_conversation()
        chat.send(
            bash("python3 -c " + shlex.quote(script))
            + call_tool("find_files", pattern="**/*.py", path=root)
            + call_tool("search_text", pattern="hello|absent", path=root + "/main.py")
            + call_tool("search_text", pattern="hello", path=root, output="files")
            + call_tool("search_text", pattern="hello", path=root, output="count")
            + call_tool("search_text", pattern="(?<=hello) needle", path=root)
            + say("file search checks done")
        ).wait_streaming(20_000)
        expect(page.get_by_test_id("entry-content").last).to_contain_text("file search checks done")
        conversation = captured["conversation_id"]
        events = resume(conversation)["events"]
        results = [e for e in events if e["type"] == "tool_result"]
        found = next(e["content"] for e in results if e["tool_name"] == "find_files")
        assert "main.py" in found and "nested/other.py" in found and "skip.py" not in found
        searched = [e["content"] for e in results if e["tool_name"] == "search_text"]
        assert len(searched) == 4
        assert "main.py:2: Hello needle" in searched[0] and "main.py-1- before" in searched[0]
        assert ".hidden.txt" in searched[1] and "ignored.txt" in searched[1]
        assert "nested/other.py: 2" in searched[2]
        assert "Search incomplete: error" in searched[3] and "regex=false" in searched[3]
        page.reload()
        expect(page.get_by_test_id("entry-content").last).to_contain_text("file search checks done")
        chat.send(call_tool("search_text", pattern="hello|absent", path=root, regex=False) + say("literal retry done")).wait_streaming()
        expect(page.get_by_test_id("entry-content").last).to_contain_text("literal retry done")
        latest = resume(conversation)["events"]
        last_result = [e["content"] for e in latest if e["type"] == "tool_result"][-1]
        assert "Returned 0 matching lines. Search complete" in last_result
        assert all(e["status"] == "success" for e in latest if e["type"] == "agent_completed")
    finally:
        if captured.get("conversation_id"):
            delete_conversation(captured["conversation_id"])
        container_exec(f"import shutil; shutil.rmtree({root!r}, ignore_errors=True)")
