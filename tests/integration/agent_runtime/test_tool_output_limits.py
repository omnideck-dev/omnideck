"""Real tools, FakeProvider, persisted history, and interruptible search_text workers."""

import asyncio
import json
from pathlib import Path
import re

import pytest

from conversations import load_events_jsonl
from providers._fake import FakeProvider
from tests.e2e._protocol import call_tool, say, spawn
from tools.virtual_computer import find_files, search_text, read_file


class RecordingFakeProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def chat_stream(self, **kwargs):
        self.requests.append(json.dumps(kwargs["messages"], ensure_ascii=False))
        async for item in super().chat_stream(**kwargs):
            yield item


@pytest.mark.parametrize("tool", ["search_text", "read_file"])
@pytest.mark.parametrize("delegated", [False, True], ids=["root", "child"])
async def test_large_results_spill_before_persistence_and_followup_can_read_them(
    harness, monkeypatch, tmp_path, tool, delegated,
):
    h = harness
    provider = RecordingFakeProvider()
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    h.skill("files", find_files, search_text, read_file)
    h.profile("leaf", skills=["files"], context_window=1_048_576)
    h.profile("root", skills=["files"], context_window=1_048_576, allow_spawn=True)
    source = tmp_path / "dense.txt"
    source.write_text(("needle " + "0123456789abcdef" * 100 + "\n") * 200)
    args = {"path": str(source)}
    if tool == "search_text":
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
    # read_file results remain serialized records, while search results are
    # line-oriented text. Neither can bypass the cap on a subsequent read.
    assert any(event.payload.type == "agent_completed" and event.payload.status == "success" for event in followup)
    assert all(len(request.encode()) < 100_000 for request in provider.requests)
    inspected = await run(call_tool("search_text", path=str(saved), pattern="needle", context=0, max_results=1) + say("inspected"))
    inspection = next(event.payload.content for event in inspected
                      if event.payload.type == "tool_result" and event.payload.tool_name == "search_text")
    assert "needle" in inspection and "temporary file:" not in inspection
    await run(say("another turn works"))


async def _collect(events):
    return [record async for record in events]


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "owner-cancellation"])
async def test_search_kills_and_reaps_blocked_rg_without_blocking_event_loop(tmp_path, monkeypatch, cancel):
    from tools.virtual_computer import search_ops

    source = tmp_path / "search.txt"
    source.write_text("aaaa\n")
    processes = []
    original = asyncio.create_subprocess_exec
    started = asyncio.Event()

    async def capture(*args, **kwargs):
        # Real ripgrep, with an open input pipe to model a stalled input source.
        # Search parsing, timeout, subprocess ownership, and cleanup stay real.
        kwargs["stdin"] = asyncio.subprocess.PIPE
        worker = await original(*args[:-1], "-", **kwargs)
        processes.append(worker)
        worker.stdin.write(b"aaaa\n")
        await worker.stdin.drain()
        started.set()
        return worker

    monkeypatch.setattr(search_ops, "_SEARCH_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    task = asyncio.create_task(search_text("aaaa", path=str(source), context=0))
    await asyncio.wait_for(started.wait(), 2)
    await asyncio.wait_for(asyncio.sleep(0.05), 0.2)
    assert not task.done()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await asyncio.wait_for(task, 3)
        assert "Search incomplete: timeout" in result
        assert "aaaa" in result
    assert len(processes) == 1 and processes[0].returncode is not None
    assert not Path(f"/proc/{processes[0].pid}").exists()
    processes[0].stdin.close()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", original)
    assert "Search complete" in await search_text("aaaa", path=str(source))


async def test_discovery_and_content_modes_share_runtime_registration_and_history(harness, monkeypatch, tmp_path):
    h = harness
    provider = RecordingFakeProvider()
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)
    h.skill("files", find_files, search_text)
    h.profile(skills=["files"])
    (tmp_path / "runner.py").write_text("before\nHello runner\nafter\n")
    handle, events = await h.start(message=(
        call_tool("find_files", pattern="**/*runner*", path=str(tmp_path))
        + call_tool("search_text", pattern="hello|absent", path=str(tmp_path / "runner.py"))
        + call_tool("search_text", pattern="hello", path=str(tmp_path), output="count")
        + say("found and inspected")
    ))
    await _collect(events)
    assert (await handle.wait()).status == "success"
    results = [e for e in load_events_jsonl("contract") if e["type"] == "tool_result"]
    assert [e["tool_name"] for e in results] == ["find_files", "search_text", "search_text"]
    assert "runner.py" in results[0]["content"]
    assert "runner.py:2: Hello runner" in results[1]["content"]
    assert "runner.py-1- before" in results[1]["content"]
    assert "runner.py: 1" in results[2]["content"]


async def test_existing_stock_skill_upgrade_reaches_real_model_context(harness, monkeypatch, tmp_path):
    from migrations._016_search_tool_guidance import migrate
    from skills._store import get_skill_record, save_skill_record

    h = harness
    provider = RecordingFakeProvider()
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)
    h.skill("coder", find_files, search_text)
    record = get_skill_record("coder")
    fixture = Path(__file__).parents[2] / "unit/migrations/fixtures/coder_before_search_tools.json"
    record.prompt = json.loads(fixture.read_text())["prompt"]
    save_skill_record(record)
    migrate(Path(h.config.settings.home_dir))
    h.profile(skills=["coder"])
    (tmp_path / "runner.py").write_text("needle")
    handle, events = await h.start(message=call_tool("find_files", pattern="**/*.py", path=str(tmp_path)) + say("done"))
    await _collect(events)
    assert (await handle.wait()).status == "success"
    assert "use find_files" in provider.requests[0] and "Use search_text" in provider.requests[0]
    assert "Use grep" not in provider.requests[0]
