"""HTTP route handlers for the task engine API."""

from __future__ import annotations

import logging

from aiohttp import web

from conversations import delete_conversation
from tasks import TaskStore, get_store
from tasks._models import Run

logger = logging.getLogger(__name__)


def _cleanup_conversations(conv_ids: list[str]) -> None:
    """Delete conversation records for removed routines/runs."""
    for cid in conv_ids:
        delete_conversation(cid)


def _profile_names() -> dict[str, str]:
    """Build a mapping of profile ID → display name."""
    try:
        from agents._agent_profiles import list_agent_profiles
        return {p.id: p.name for p in list_agent_profiles()}
    except Exception:
        return {}


def _enrich_task(task_data: dict, names: dict[str, str]) -> dict:
    """Add agent_profile_name to a serialized task dict."""
    pid = task_data.get("agent_profile")
    if pid:
        task_data["agent_profile_name"] = names.get(pid, pid)
    return task_data


def _serialize_run(
    store: TaskStore,
    run: Run,
    profile_name_map: dict[str, str] | None = None,
) -> dict[str, object]:
    """Serialize a run with its task_results for JSON responses."""
    results = store.get_task_results(run.id)
    return {**run.model_dump(), "task_results": [tr.model_dump() for tr in results]}


async def handle_list_routines(request: web.Request) -> web.Response:
    """List routines, optionally filtered by status."""
    status = request.query.get("status")
    store = get_store()
    routines = store.list_routines(status=status)
    result = []
    for g in routines:
        data = g.model_dump()
        runs = store.get_routine_runs(g.id)
        if runs:
            latest = max(runs, key=lambda r: r.started_at or r.created_at)
            data["last_run_at"] = latest.started_at or latest.created_at
        result.append(data)
    return web.json_response({"routines": result})


async def handle_get_routine(request: web.Request) -> web.Response:
    """Get full routine detail including tasks and runs with task_results."""
    routine_id = request.match_info["routine_id"]
    store = get_store()
    routine = store.get_routine(routine_id)
    if not routine:
        return web.json_response({"error": "Not found"}, status=404)
    tasks = store.list_tasks(routine_id)
    runs = store.get_routine_runs(routine_id)
    names = _profile_names()
    return web.json_response({
        "routine": routine.model_dump(),
        "tasks": [_enrich_task(t.model_dump(), names) for t in tasks],
        "runs": [_serialize_run(store, r) for r in runs],
    })


async def handle_delete_routine(request: web.Request) -> web.Response:
    """Delete a routine and all its runs/conversations."""
    routine_id = request.match_info["routine_id"]
    _cleanup_conversations(get_store().delete_routine(routine_id))
    return web.json_response({"deleted": routine_id})


async def handle_pause_routine(request: web.Request) -> web.Response:
    """Pause a routine — its tasks won't be picked up by the runner."""
    routine_id = request.match_info["routine_id"]
    get_store().set_routine_status(routine_id, "paused")
    return web.json_response({"status": "paused"})


async def handle_resume_routine(request: web.Request) -> web.Response:
    """Resume a paused routine."""
    routine_id = request.match_info["routine_id"]
    get_store().set_routine_status(routine_id, "active")
    return web.json_response({"status": "active"})


async def handle_trigger_routine(request: web.Request) -> web.Response:
    """Manually trigger a run for any routine (one-shot or recurring)."""
    routine_id = request.match_info["routine_id"]
    store = get_store()
    routine = store.get_routine(routine_id)
    if not routine:
        return web.json_response({"error": "Not found"}, status=404)
    run = store.queue_run(routine_id)
    return web.json_response({"run_id": run.id, "run_number": run.run_number}, status=201)


async def handle_list_runs(request: web.Request) -> web.Response:
    """List runs for a routine with their task_results."""
    routine_id = request.match_info["routine_id"]
    store = get_store()
    runs = store.get_routine_runs(routine_id)
    return web.json_response({"runs": [_serialize_run(store, r) for r in runs]})


async def handle_delete_run(request: web.Request) -> web.Response:
    """Delete a run and its conversations."""
    run_id = request.match_info["run_id"]
    _cleanup_conversations(get_store().delete_run(run_id))
    return web.json_response({"deleted": run_id})


async def handle_runner_status(request: web.Request) -> web.Response:
    """Return the current runner status."""
    runner = request.app.get("task_runner")
    if not runner:
        return web.json_response({
            "running": False,
            "paused": False,
            "active_tasks": 0,
            "max_concurrent": 0,
        })
    return web.json_response(runner.status)


async def handle_runner_pause(request: web.Request) -> web.Response:
    """Pause the task runner."""
    runner = request.app.get("task_runner")
    if runner:
        runner.pause()
    return web.json_response({"paused": True})


async def handle_runner_resume(request: web.Request) -> web.Response:
    """Resume the task runner."""
    runner = request.app.get("task_runner")
    if runner:
        runner.resume()
    return web.json_response({"paused": False})


def register_task_routes(app: web.Application) -> None:
    """Register all task engine HTTP routes on the application."""
    app.router.add_route("GET", "/api/routines", handle_list_routines)
    app.router.add_route("GET", "/api/routines/{routine_id}", handle_get_routine)
    app.router.add_route("DELETE", "/api/routines/{routine_id}", handle_delete_routine)
    app.router.add_route("POST", "/api/routines/{routine_id}/pause", handle_pause_routine)
    app.router.add_route("POST", "/api/routines/{routine_id}/resume", handle_resume_routine)
    app.router.add_route("POST", "/api/routines/{routine_id}/trigger", handle_trigger_routine)
    app.router.add_route("GET", "/api/routines/{routine_id}/runs", handle_list_runs)
    app.router.add_route("DELETE", "/api/routines/{routine_id}/runs/{run_id}", handle_delete_run)
    app.router.add_route("GET", "/api/runner/status", handle_runner_status)
    app.router.add_route("POST", "/api/runner/pause", handle_runner_pause)
    app.router.add_route("POST", "/api/runner/resume", handle_runner_resume)


__all__ = ["register_task_routes"]
