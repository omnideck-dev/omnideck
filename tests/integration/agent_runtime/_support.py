"""External service doubles and drivers; never replace runtime orchestration."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime import ActiveRunManager, AgentRunRequest
from agents import AgentProfile
from agents._agent_profiles import save_agent_profile
from sdk.events import AgentEvent, get_current_agent_id
from sdk.providers import ChatDelta, ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolCallFunction
from sdk.skills._store import SkillRecord, save_skill_record
from sdk.skills._tool_categories import ToolCategory
from sdk.turn import get_conversation_id
from sdk.turn._models import _current_execution
from tasks._file_store import FileTaskStore


def reply(content="done", *, calls=()):
    return ChatResponse(
        message=ChatMessage(content=content, tool_calls=list(calls)),
        usage=TokenUsage(prompt_tokens=50, completion_tokens=10),
        done_reason="tool_calls" if calls else "stop",
    )


def call(tool_name, **arguments):
    # IDs intentionally omitted: the production loop must create/pair them.
    return ToolCall(function=ToolCallFunction(name=tool_name, arguments=arguments))


class ScriptedProvider:
    def __init__(self):
        self.scripts = defaultdict(deque)
        self.requests = []

    def plan(self, model, *steps):
        self.scripts[model].extend(steps)

    def take(self, kwargs):
        execution = _current_execution.get()
        request = {
            "run_id": execution.run_id if execution is not None else None,
            "parent_execution_id": execution.parent_execution_id if execution is not None else None,
            **deepcopy(kwargs),
            "tools": [tool.__name__ for tool in kwargs.get("tools", [])],
            "agent_id": get_current_agent_id(),
            "conversation_id": get_conversation_id(),
        }
        self.requests.append(request)
        if not self.scripts[kwargs["model"]]:
            raise RuntimeError(f"Unscripted provider call: {kwargs['model']}")
        return request, self.scripts[kwargs["model"]].popleft()

    async def chat_stream(self, **kwargs):
        request, step = self.take(kwargs)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            async for chunk in step(request):
                yield chunk
        elif isinstance(step, list):
            for chunk in step:
                yield chunk
        else:
            yield step

    async def chat(self, **kwargs):
        _request, step = self.take(kwargs)
        if isinstance(step, Exception):
            raise step
        return step


@dataclass
class Harness:
    manager: ActiveRunManager
    provider: ScriptedProvider
    home: Path
    store: FileTaskStore
    config: object
    categories: dict = field(default_factory=dict)
    browser_calls: list = field(default_factory=list)
    exited_agents: list = field(default_factory=list)
    exited_conversations: list = field(default_factory=list)

    def profile(self, identifier="leaf", **options):
        values = dict(
            id=identifier, name=identifier.upper(), provider="scripted",
            model=identifier, system_prompt=f"system:{identifier}",
            allow_spawn=False, allow_load_skills=False,
            context_window=100_000, max_iterations=10,
        )
        values.update(options)
        return save_agent_profile(AgentProfile(**values))

    def skill(self, identifier, *tools):
        self.categories[identifier] = ToolCategory(
            identifier, identifier, "Contract fixture tools", list(tools),
        )
        return save_skill_record(SkillRecord(
            id=identifier, name=identifier, prompt=f"guidance:{identifier}",
            tool_categories=[identifier],
        ))

    async def start(self, profile="leaf", *, conversation="contract", message="input", attachments=None):
        info = await self.manager.start(AgentRunRequest(
            conversation_id=conversation, profile_id=profile,
            message=message, attachments=attachments,
        ))
        return info, self.manager.subscribe(info.run_id, after_seq=0)

    async def run(self, profile="leaf", **kwargs):
        info, stream = await self.start(profile, **kwargs)
        records = await collect(stream)
        assert all(record.run_id == info.run_id for record in records)
        matching = [r for r in self.provider.requests if r["conversation_id"] == info.conversation_id]
        assert matching[-1]["run_id"] == info.run_id
        assert [r.seq for r in records] == list(range(1, len(records) + 1))
        return [r.event for r in records]


async def collect(stream):
    async def drain():
        return [record async for record in stream]
    return await asyncio.wait_for(drain(), timeout=5)


def payloads(events, kind):
    return [event.payload for event in events if event.payload.type == kind]


def assert_lifecycle(events, statuses):
    starts = payloads(events, "agent_started")
    ends = payloads(events, "agent_completed")
    assert len(starts) == len(ends) == len(statuses)
    assert {p.agent_id for p in starts} == {p.agent_id for p in ends}
    assert {p.agent_name: p.status for p in ends} == statuses
    assert len(payloads(events, "turn_end")) == 1
    assert events[-1].payload.type == "turn_end"
    assert len({event.id for event in events}) == len(events)
