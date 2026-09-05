"""Review probes for 6d02b60d; assert observed defects, not desired behavior.

Run from the worktree: PYTHONPATH=. uv run python tests/review_runtime_20260905.py
Only scripted providers and in-memory tools are used. No model or browser calls.
"""

import asyncio
import json
import logging
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from agents.types import Agent
from sdk.agent_state import AgentState
from sdk.context import ConversationHistory
from sdk.events import AgentEvent, UserMessagePayload, agent_span, publish_event
from sdk.hooks import BudgetGuard, StopHook
from sdk.providers import ChatDelta, ChatMessage, ChatResponse, ToolCall, ToolCallFunction
from sdk.turn import StopRequestedError, run_turn, turn_scope
from tasks._file_store import FileTaskStore
from tasks._runner import TaskRunner
from tasks._tools import commit_routine


def response(*names, content=None):
    return ChatResponse(message=ChatMessage(content=content, tool_calls=[
        ToolCall(id=f"call_{i}", function=ToolCallFunction(name=name, arguments={}))
        for i, name in enumerate(names)
    ]))


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.tool_counts = []

    async def chat_stream(self, **kwargs):
        self.tool_counts.append(len(kwargs["tools"]))
        yield next(self.responses)


async def execute(provider, tools, seen, *, hooks=None, stop=None, parallel=False):
    agent = Agent(name="PROBE", description="", instruction="probe", provider="probe",
                  model="probe", options={}, tools=tools, max_iterations=1)
    history = ConversationHistory(system_message="probe", conversation_id="review-probe")
    history.subscribe(seen.append)
    cfg = SimpleNamespace(enabled=parallel, max_concurrent=2)
    with patch("sdk.turn._execution.get_provider", return_value=provider), \
         patch("sdk.turn._execution._get_parallel_config", return_value=cfg):
        async with turn_scope(history, conversation_id="review-probe", stop_event=stop):
            async with agent_span("PROBE", agent_state=AgentState(tools)):
                publish_event(AgentEvent(payload=UserMessagePayload(type="user_message", content="go")))
                await run_turn(history, agent, hooks=hooks or [])
    return history


async def budget_probe():
    calls = []

    async def work():
        calls.append("work")
        return "done"

    provider = ScriptedProvider([response("work") for _ in range(3)] + [response(content="done")])
    await execute(provider, [work], [], hooks=[BudgetGuard(1)])
    assert len(calls) == 3 and provider.tool_counts == [1, 1, 1, 1]
    return {"max_iterations": 1, "tool_rounds_executed": len(calls), "tools_per_model_call": provider.tool_counts}


async def stop_between_tools_probe():
    stop = asyncio.Event()
    calls = []

    async def first():
        calls.append("first")
        stop.set()
        return "stop was requested during first tool"

    async def second():
        calls.append("second")
        return "side effect after stop"

    provider = ScriptedProvider([response("first", "second")])
    with suppress(StopRequestedError):
        await execute(provider, [first, second], [], hooks=[StopHook()], stop=stop)
    assert calls == ["first", "second"]
    return {"executed_after_stop": calls[1:]}


async def cancellation_probe():
    streamed = asyncio.Event()
    seen = []

    class HangingProvider:
        async def chat_stream(self, **kwargs):
            yield ChatDelta(content="partial answer already shown")
            streamed.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(execute(HangingProvider(), [], seen))
    await streamed.wait()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    statuses = [e.payload.status for e in seen if e.payload.type == "agent_completed"]
    iterations = [e for e in seen if e.payload.type == "iteration"]
    assert statuses == ["success"] and not iterations
    return {"cancelled_agent_status": statuses[0], "persistable_partial_iterations": len(iterations)}


async def orphan_tool_probe():
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    seen = []

    async def slow():
        started.set()
        await release.wait()
        finished.set()
        return "effect completed after turn ended"

    async def stop_now():
        await started.wait()
        raise StopRequestedError()

    provider = ScriptedProvider([response("slow", "stop_now")])
    with suppress(StopRequestedError):
        await execute(provider, [slow, stop_now], seen, parallel=True)
    ended_before_effect = any(e.payload.type == "turn_end" for e in seen) and not finished.is_set()
    release.set()
    await finished.wait()
    await asyncio.sleep(0)
    kinds = [e.payload.type for e in seen]
    assert ended_before_effect and kinds.index("turn_end") < kinds.index("tool_result")
    return {"tool_finished_after_turn_end": True, "event_order": kinds}


async def routine_retry_probe():
    with TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "artifacts") as tmp:
        store = FileTaskStore(Path(tmp))
        routine = store.create_routine("probe", auto_run=False)
        task = store.create_task(routine.id, "probe", "probe")
        run = store.queue_run(routine.id)
        result = store.get_task_results(run.id)[0]

        class SideEffectThenFailure:
            effects = 0

            async def run(self, *args):
                self.effects += 1
                if self.effects == 1:
                    raise RuntimeError("provider failed after tool side effect")
                return "done", []

        executor = SideEffectThenFailure()
        runner = TaskRunner(store, executor, SimpleNamespace())
        store.mark_task_result_running(result.id)
        await runner._execute(result, task)
        retry = store.get_task_results(run.id)[0]
        assert retry.status == "pending" and retry.retry_count == 1
        store.mark_task_result_running(result.id)
        await runner._execute(retry, task)
        assert executor.effects == 2
        return {"side_effect_executions_after_one_retry": executor.effects}


async def routine_self_dependency_probe():
    with TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "artifacts") as tmp:
        store = FileTaskStore(Path(tmp))
        draft = {"description": "self dependency", "tasks": [{
            "key": "a", "description": "a", "instruction": "go",
            "agent_profile": "probe", "depends_on": ["a"],
        }]}
        with patch("tasks._tools.get_store", return_value=store), \
             patch("tasks._tools.get_agent_profile", return_value=SimpleNamespace(enabled=True)):
            output = await commit_routine(draft)
        routine = store.list_routines()[0]
        task = store.list_tasks(routine.id)[0]
        run = store.get_routine_runs(routine.id)[0]
        assert output.startswith("Created routine")
        assert task.depends_on == [task.id] and not store.get_ready_task_results()
        return {"self_dependency_accepted": True, "run_status": run.status, "ready_tasks": 0}


async def main():
    logging.disable(logging.CRITICAL)
    results = {}
    for probe in (budget_probe, stop_between_tools_probe, cancellation_probe,
                  orphan_tool_probe, routine_retry_probe, routine_self_dependency_probe):
        results[probe.__name__] = await probe()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
