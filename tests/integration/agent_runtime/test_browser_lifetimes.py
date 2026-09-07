"""Real FakeProvider, runner, conversation store, and browser pool ownership.

Only the Chromium host/session boundary is replaced; browser preparation,
lookup, resource registration, release, delegation, and task execution are real.
"""

import asyncio
from types import SimpleNamespace

import pytest

from agent_core.turn import get_execution_context
from agent_runtime import AgentRunRequest, AgentRunner, AgentRuntime
from browser.profile_store import BrowserProfileStore
from browser.runtime import BrowserRuntime, get_browser
from browser.session_pool import BrowserSessionPool
from providers._fake import FakeProvider
from tasks import TaskExecutor
from tests.e2e._protocol import call_tool, fail, say, spawn


class BrowserSession:
    def __init__(self):
        self.closed = False
        self.close_calls = 0
        self.closing = asyncio.Event()
        self.allow_close = asyncio.Event()
        self.allow_close.set()

    async def close_session(self):
        self.closing.set()
        await self.allow_close.wait()
        self.close_calls += 1
        self.closed = True


class BrowserHost:
    def __init__(self):
        self.sessions = []
        self.closed = False

    async def create_session(self, **_kwargs):
        session = BrowserSession()
        self.sessions.append(session)
        return session

    async def close(self):
        self.closed = True


@pytest.fixture
async def browsers(harness, monkeypatch, tmp_path):
    provider = FakeProvider()
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)
    created = []

    def create(*, supplied_runner=False):
        host = BrowserHost()
        pool = BrowserSessionPool()
        pool._host = host
        browser = BrowserRuntime(BrowserProfileStore(tmp_path / "profiles"), pool)
        runtime = (
            AgentRuntime(AgentRunner(browser_runtime=browser), shutdown_timeout=0.01)
            if supplied_runner else AgentRuntime(browser_runtime=browser, shutdown_timeout=0.01)
        )
        result = SimpleNamespace(runtime=runtime, browser=browser, host=host, seen=[], entered=asyncio.Event())
        created.append(result)
        return result

    async def touch_browser() -> str:
        """Open the execution's browser and record which runtime supplied it."""
        session = await get_browser()
        context = get_execution_context()
        owner = next(item for item in created if session in item.host.sessions)
        owner.seen.append((context, session))
        return "browser opened"

    async def hold_browser() -> str:
        """Open a browser and keep the execution active until cancelled."""
        await touch_browser()
        session = await get_browser()
        next(item for item in created if session in item.host.sessions).entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    harness.skill("browser-proof", touch_browser, hold_browser)
    for name in ("root", "child", "leaf"):
        harness.profile(name, allow_spawn=True, skills=["browser-proof"], browser_profile_id="empty")
    try:
        yield create
    finally:
        for item in created:
            for session in item.host.sessions:
                session.allow_close.set()
            await item.runtime.close()


def request(message, conversation="browser-lifetime"):
    return AgentRunRequest(conversation_id=conversation, profile_id="root", attachments=None, message=message)


async def test_headless_runtime_keeps_root_browser_between_turns_and_closes_descendants(browsers):
    item = browsers()
    prompt = call_tool("touch_browser") + spawn(
        call_tool("touch_browser") + spawn(call_tool("touch_browser") + say("leaf"), profile="leaf")
        + say("child"), profile="child",
    ) + say("root")
    first = await item.runtime.start(request(prompt))
    assert (await first.wait()).status == "success"
    root, child, leaf = [session for _, session in item.seen]
    assert not root.closed and child.closed and leaf.closed
    assert len({id(session) for session in (root, child, leaf)}) == 3
    first_scope = first._session.conversation
    second = await item.runtime.start(request(call_tool("touch_browser") + say("next turn")))
    assert (await second.wait()).status == "success"
    assert second._session.conversation is first_scope
    assert item.seen[-1][1] is root
    assert len(item.host.sessions) == 3
    await item.runtime.conversations.evict_conversation(first.conversation_id)
    assert [session.close_calls for session in item.host.sessions] == [1, 1, 1]
    assert item.browser._agent_bindings == {} and item.browser._resource_owners == {}


@pytest.mark.parametrize("supplied_runner", [False, True])
async def test_independent_runtimes_with_same_conversation_id_do_not_share_browsers(browsers, supplied_runner):
    left, right = browsers(supplied_runner=supplied_runner), browsers(supplied_runner=supplied_runner)
    for item in (left, right):
        handle = await item.runtime.start(request(call_tool("touch_browser") + say("opened")))
        assert (await handle.wait()).status == "success"
    assert left.seen[0][1] is not right.seen[0][1]
    await left.runtime.close()
    assert left.host.closed and left.seen[0][1].closed
    assert not right.host.closed and not right.seen[0][1].closed
    handle = await right.runtime.start(request(call_tool("touch_browser") + say("still here")))
    assert (await handle.wait()).output == "still here"
    assert right.seen[-1][1] is right.seen[0][1]
    await right.runtime.close()
    assert right.host.closed and right.seen[0][1].close_calls == 1


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_routine_closes_root_and_child_browsers_before_returning(harness, browsers, outcome):
    item = browsers()
    body = call_tool("hold_browser" if outcome == "cancel" else "touch_browser")
    body += fail("child failed") if outcome == "error" else say("child done")
    prompt = call_tool("touch_browser") + spawn(body, profile="child") + say("routine done")
    routine = harness.store.create_routine("browser lifetime", auto_run=False)
    task = harness.store.create_task(routine.id, "browse", prompt, agent_profile="root")
    workflow = harness.store.queue_run(routine.id)
    result = harness.store.get_task_results(workflow.id)[0]
    owner = asyncio.create_task(TaskExecutor(harness.store, item.runtime).run(result, task))
    try:
        if outcome == "cancel":
            await asyncio.wait_for(item.entered.wait(), 5)
            owner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await owner
        else:
            await asyncio.wait_for(owner, 5)
        assert len(item.host.sessions) == 2
        assert all(session.closed and session.close_calls == 1 for session in item.host.sessions)
        assert not item.runtime.conversations._conversations
        assert not item.runtime.conversations._leases
        assert not item.browser._resource_owners and not item.browser._agent_bindings
    finally:
        if not owner.done():
            owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)


async def test_child_completion_waits_for_browser_cleanup(browsers):
    item = browsers()
    handle = await item.runtime.start(request(spawn(call_tool("hold_browser"), profile="child") + say("done")))
    await asyncio.wait_for(item.entered.wait(), 5)
    child_context, child_browser = item.seen[0]
    child_browser.allow_close.clear()
    handle.cancel()
    try:
        await asyncio.wait_for(child_browser.closing.wait(), 5)
        assert item.runtime.get(handle.run_id) is not None
        assert not any(record.event.payload.type == "agent_completed" and
                       record.event.agent_id == child_context.execution_id for record in handle._session.records)
        assert not any(record.event.payload.type == "turn_end" for record in handle._session.records)
    finally:
        child_browser.allow_close.set()
        result = await asyncio.wait_for(handle.wait(), 5)
    assert result.status == "stopped" and child_browser.close_calls == 1


async def test_failed_child_browser_preparation_releases_binding(browsers, monkeypatch):
    item = browsers()
    original = item.browser.sessions.prepare

    async def prepare(key, state_loader):
        await original(key, state_loader)
        if not key.startswith("conversation:"):
            raise RuntimeError("browser preparation failed")

    monkeypatch.setattr(item.browser.sessions, "prepare", prepare)
    handle = await item.runtime.start(request(spawn(say("child"), profile="child") + say("parent recovered")))
    assert (await handle.wait()).output == "parent recovered"
    assert set(item.browser._agent_bindings) == {"conversation:browser-lifetime"}
    assert set(item.browser._resource_owners) == {"conversation:browser-lifetime"}
    children = [result for _, result in (await handle.wait()).executions if result.status == "error"]
    assert len(children) == 1 and children[0].error == "browser preparation failed"


async def test_http_application_uses_its_own_browser_service_and_closes_it_after_runs(harness, monkeypatch):
    from server.aiohttp_app import create_app
    from server._agent_runtime import AGENT_RUNTIME_KEY
    from server._browser_runtime import BROWSER_RUNTIME_KEY

    provider = FakeProvider()
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)
    apps = [create_app(), create_app()]
    hosts = []
    for app in apps:
        host = BrowserHost()
        app[BROWSER_RUNTIME_KEY].sessions._host = host
        hosts.append(host)
    entered = asyncio.Event()

    async def hold_application_browser() -> str:
        """Open the application's browser until runtime shutdown cancels the tool."""
        await get_browser()
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    harness.skill("app-browser", hold_application_browser)
    harness.profile("root", skills=["app-browser"], browser_profile_id="empty")
    runtime = apps[0][AGENT_RUNTIME_KEY]
    runtime._shutdown_timeout = 0.01
    try:
        handle = await runtime.start(request(call_tool("hold_application_browser")))
        await asyncio.wait_for(entered.wait(), 5)
        assert runtime._runner.browser_runtime is apps[0][BROWSER_RUNTIME_KEY]
        assert apps[0][BROWSER_RUNTIME_KEY] is not apps[1][BROWSER_RUNTIME_KEY]
        assert apps[0][AGENT_RUNTIME_KEY].conversations is not apps[1][AGENT_RUNTIME_KEY].conversations
        await asyncio.wait_for(runtime.close(), 5)
        assert (await handle.wait()).status == "stopped"
        assert hosts[0].sessions[0].closed and hosts[0].closed
        assert not hosts[1].closed
        with pytest.raises(RuntimeError, match="outside a prepared agent execution"):
            await get_browser()
    finally:
        for app in apps:
            await app[AGENT_RUNTIME_KEY].close()


async def test_forced_shutdown_waits_for_browser_cleanup_already_in_progress(browsers, monkeypatch):
    item = browsers()
    created = asyncio.Queue()
    original = item.host.create_session

    async def create_session(**kwargs):
        session = await original(**kwargs)
        session.allow_close.clear()
        created.put_nowait(session)
        return session

    monkeypatch.setattr(item.host, "create_session", create_session)
    handle = await item.runtime.start(request(spawn(call_tool("touch_browser") + say("child"), profile="child")))
    session = await asyncio.wait_for(created.get(), 5)
    await asyncio.wait_for(session.closing.wait(), 5)
    shutdown = asyncio.create_task(item.runtime.close())
    try:
        # Wait for runtime shutdown to deliver its forced cancellation while
        # browser cleanup is already suspended, rather than while a tool runs.
        await asyncio.sleep(0.05)
        assert not shutdown.done()
        assert not handle._session.completed
        assert not session.closed
    finally:
        session.allow_close.set()
        await asyncio.wait_for(shutdown, 5)
    assert session.closed and session.close_calls == 1
    assert (await handle.wait()).status == "stopped"
