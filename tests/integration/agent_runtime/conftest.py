"""Use real profiles, skills, hooks, scopes, history, runners, and disk writers.

Only provider I/O, browser I/O, category discovery, and storage locations are
substituted. This directory deliberately does not inherit the SDK unit suite's
legacy history/event compatibility fixture.
"""

from collections import OrderedDict

import pytest
import pytest_asyncio

from agent_runtime import ActiveRunManager, AgentRunner
from config import load_config
from conversations import get_or_create_conversation
from sdk.events import get_current_agent_id
from sdk.turn import get_conversation_id
from tasks._file_store import FileTaskStore

from ._support import Harness, ScriptedProvider


@pytest_asyncio.fixture
async def harness(tmp_path, monkeypatch):
    config = load_config().model_copy(deep=True)
    config.settings.home_dir = str(tmp_path / "state")
    config.virtual_computer.home_dir = str(tmp_path / "home")
    config.parallel.enabled = False
    home = tmp_path / "home"
    home.mkdir()

    # Patch imported config bindings at the infrastructure edges; resolution,
    # parsing, skill composition, and all disk serialization still run.
    for target in (
        "agents._agent_profiles.load_config",
        "sdk.skills._store.load_config",
        "tools.memory.memory.load_config",
        "tools.virtual_computer.receive_file.load_config",
        "tools.scratchpad.scratchpad.load_config",
        "artifacts._store.load_config",
    ):
        monkeypatch.setattr(target, lambda: config)
    monkeypatch.setattr("conversations._store._get_conversations_dir", lambda: tmp_path / "conversations")
    monkeypatch.setattr("conversations._cache._conversations", OrderedDict())
    monkeypatch.setattr("sdk.lifecycle._hooks", [])
    monkeypatch.setattr("conversations._lifecycle._hooks", [])
    monkeypatch.setattr("agent_runtime._execution_context.load_config", lambda: config)

    provider = ScriptedProvider()
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _name: provider)
    monkeypatch.setattr("sdk.context._strategy.get_provider", lambda _name: provider)
    # Compaction settings are application configuration, not the strategy.
    monkeypatch.setattr("sdk.context._strategy.load_settings", lambda: {
        "compaction_provider": "scripted", "compaction_model": "summary", "compaction_options": {},
    })

    manager = ActiveRunManager(AgentRunner(get_or_create_conversation), shutdown_timeout=0.1)
    h = Harness(manager, provider, home, FileTaskStore(tmp_path / "routines"), config)

    async def categories():
        return h.categories

    monkeypatch.setattr("sdk.skills._resolve.tool_categories", categories)
    monkeypatch.setattr("tools.browser.capability.tool_categories", categories)

    class BrowserService:
        async def prepare_current_agent_browser(self, **kwargs):
            h.browser_calls.append({
                **kwargs, "agent_id": get_current_agent_id(),
                "conversation_id": get_conversation_id(),
            })

    browser = BrowserService()
    monkeypatch.setattr("agent_runtime._runner.get_browser_runtime", lambda: browser)

    from sdk.lifecycle import register_agent_span_exit_hook
    from conversations import register_conversation_exit_hook

    async def agent_exit(agent_id):
        h.exited_agents.append(agent_id)

    async def conversation_exit(conversation_id):
        h.exited_conversations.append(conversation_id)

    register_agent_span_exit_hook(agent_exit)
    register_conversation_exit_hook(conversation_exit)
    try:
        yield h
    finally:
        await manager.close()
