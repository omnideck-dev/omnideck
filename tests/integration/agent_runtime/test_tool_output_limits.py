"""Real tools, FakeProvider, persisted history, and interruptible grep workers."""

import asyncio
import json
from pathlib import Path
import re

import pytest

from conversations import load_events_jsonl
from providers._fake import FakeProvider
from tests.e2e._protocol import call_tool, say, spawn
from tools.virtual_computer import grep, read_file


class RecordingFakeProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def chat_stream(self, **kwargs):
        self.requests.append(json.dumps(kwargs["messages"], ensure_ascii=False))
        async for item in super().chat_stream(**kwargs):
            yield item


@pytest.mark.parametrize("tool", ["grep", "read_file"])
@pytest.mark.parametrize("delegated", [False, True], ids=["root", "child"])
async def test_large_results_spill_before_persistence_and_followup_can_read_them(
    harness, monkeypatch, tmp_path, tool, delegated,
):
    h = harness
    provider = RecordingFakeProvider()
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    h.skill("files", grep, read_file)
    h.profile("leaf", skills=["files"], context_window=1_048_576)
    h.profile("root", skills=["files"], context_window=1_048_576, allow_spawn=True)
    source = tmp_path / "dense.txt"
    source.write_text(("needle " + "0123456789abcdef" * 100 + "\n") * 200)
    args = {"path": str(source)}
    if tool == "grep":
        args.update(pattern="needle", context=0)
    message = call_tool(tool, **args) + say("searched")
    if delegated:
        message = spawn(message, profile="leaf", name="LEAF") + say("root finished")

    async def run(message):
        handle, events = await h.start("root", message=message)
        records = await asyncio.wait_for(_collect(events), 15)
        assert (await handle.wait()).status == "success"
        return [record.event for record in records]

    events = await run(message)
    results = [event.payload.content for event in events
               if event.payload.type == "tool_result" and event.payload.tool_name == tool]
    assert len(results) == 1
    notice = results[0]
    saved = Path(re.search(r"temporary file: (.+)\n", notice)[1])
    assert saved.exists() and saved.stat().st_size > 64 * 1024
    assert len(notice.encode()) < 1500
    persisted = load_events_jsonl("contract")
    assert next(event["content"] for event in persisted
                if event["type"] == "tool_result" and event["tool_name"] == tool) == notice
    assert all(len(request.encode()) < 100_000 for request in provider.requests)
    # Reloaded model history contains the pointer, not the oversized output.
    followup = await run(call_tool("read_file", path=str(saved), start=1, end=1) + say("followup worked"))
    # Serialized tool output is one long line: rereading it spills again
    # instead of bypassing the cap. Either way, the next model call succeeds.
    assert any(event.payload.type == "agent_completed" and event.payload.status == "success" for event in followup)
    assert all(len(request.encode()) < 100_000 for request in provider.requests)
    inspected = await run(call_tool("grep", path=str(saved), pattern="needle", context=0) + say("inspected"))
    inspection = next(event.payload.content for event in inspected
                      if event.payload.type == "tool_result" and event.payload.tool_name == "grep")
    assert "needle" in inspection and "temporary file:" not in inspection
    await run(say("another turn works"))


async def _collect(events):
    return [record async for record in events]


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "owner-cancellation"])
async def test_grep_kills_and_reaps_stuck_regex_without_blocking_event_loop(tmp_path, monkeypatch, cancel):
    from tools.virtual_computer import search_ops

    source = tmp_path / "backtracking.txt"
    source.write_text("aaaa\n" + "a" * 100 + "!\n")
    processes = []
    original = asyncio.create_subprocess_exec

    async def capture(*args, **kwargs):
        worker = await original(*args, **kwargs)
        processes.append(worker)
        return worker

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    monkeypatch.setattr(search_ops, "_SEARCH_TIMEOUT_SECONDS", 2)
    task = asyncio.create_task(grep("(a+)+$", path=str(source), context=0))
    # The server event loop must remain responsive while the actual regex runs.
    await asyncio.wait_for(asyncio.sleep(0.1), 0.5)
    assert not task.done()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await asyncio.wait_for(task, 5)
        assert result.truncated and "Search stopped" in result.notice
        assert [match.line for match in result.matches] == ["aaaa"]
    assert len(processes) == 1 and processes[0].returncode is not None
    assert not Path(f"/proc/{processes[0].pid}").exists()
    assert (await grep("aaaa", path=str(source), regex=False, context=0)).success
