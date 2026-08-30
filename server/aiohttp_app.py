# Standard library imports
"""aiohttp web server exposing the COMPUTRON_9000 agent API.

This module now exposes a create_app() factory instead of instantiating the
application at import time. It also separates route handlers, uses Pydantic
models for structured validation, centralizes streaming logic, and configures
static file serving through aiohttp's built-in static route helpers.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from pydantic import ValidationError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Awaitable, Callable

    from aiohttp.web_request import Request
    from aiohttp.web_response import StreamResponse

from agent_runtime import ActiveRunManager
from config import load_config
from server._agent_run_routes import register_agent_run_routes
from server._agent_runtime import ACTIVE_RUN_MANAGER_KEY, build_agent_runner
from server._artifacts_routes import register_artifacts_routes
from server._browser_control_routes import register_browser_control_routes
from server._browser_profile_routes import register_browser_profile_routes
from server._container_file_routes import register_container_file_routes
from server._conversation_routes import register_conversation_routes
from server._custom_app_routes import register_custom_app_routes
from server._custom_tool_routes import register_custom_tool_routes
from server._desktop_routes import register_desktop_routes
from server._feature_routes import register_feature_routes
from server._integrations_oauth_routes import register_oauth_routes
from server._integrations_routes import register_integrations_routes
from server._memory_routes import register_memory_routes
from server._model_routes import register_model_routes
from server._pack_routes import register_pack_routes
from server._profile_routes import register_profile_routes
from server._provider_routes import register_provider_routes
from server._settings_routes import register_settings_routes
from server._setup_routes import register_setup_routes
from server._skill_routes import register_skill_routes
from server._task_routes import register_task_routes
from server._tool_category_routes import register_tool_category_routes
from server._ui_routes import register_ui_routes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, PUT, OPTIONS, GET, DELETE",
    # X-Requested-With is intentionally NOT listed here — cross-origin requests
    # cannot set it (browser blocks them at preflight), so its presence signals
    # that a request is same-origin. This is a lightweight CSRF guard.
    "Access-Control-Allow-Headers": "Content-Type",
}

_CSRF_METHODS = {"POST", "PUT", "DELETE"}


@web.middleware
async def cors_and_error_middleware(
    request: Request, handler: Callable[[Request], Awaitable[StreamResponse]]
) -> StreamResponse:
    """Add CORS headers, enforce CSRF check, and convert validation errors to JSON."""
    if request.method == "OPTIONS":
        return web.Response(status=200, headers=_CORS_HEADERS)
    # CSRF: mutating requests must carry X-Requested-With: XMLHttpRequest.
    # Same-origin JS can always set this header; cross-origin JS cannot because
    # the server does not list it in Access-Control-Allow-Headers.
    if request.method in _CSRF_METHODS and request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return web.json_response({"error": "CSRF check failed"}, status=403, headers=_CORS_HEADERS)
    try:
        resp: StreamResponse = await handler(request)
    except ValidationError as exc:  # pragma: no cover - handled uniformly
        logger.warning("Validation error: %s", exc)
        return web.json_response({"error": "Invalid request"}, status=400, headers=_CORS_HEADERS)
    if isinstance(resp, web.StreamResponse):
        for k, v in _CORS_HEADERS.items():
            resp.headers.setdefault(k, v)
    return resp


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    client_max_size: int = 50 * 1024**2,
) -> web.Application:
    """Create and configure the aiohttp application.

    Args:
        client_max_size: Maximum allowed request body size in bytes.

    Returns:
        Configured aiohttp web.Application instance.
    """
    from browser_profiles._conversation import register_conversation_browser_cleanup

    register_conversation_browser_cleanup()
    app = web.Application(client_max_size=client_max_size, middlewares=[cors_and_error_middleware])
    app[ACTIVE_RUN_MANAGER_KEY] = ActiveRunManager(build_agent_runner())

    # Agent-run HTTP channel adapter
    register_agent_run_routes(app)

    # Custom tools and memory
    register_custom_tool_routes(app)
    register_memory_routes(app)

    # Feature flags
    register_feature_routes(app)

    # Experimental Custom Apps
    register_custom_app_routes(app)

    # Models + agents + providers
    register_model_routes(app)
    register_provider_routes(app)

    # Agent profiles
    register_profile_routes(app)

    # Editable skills
    register_skill_routes(app)

    # Sharing: export/import for profiles and skills
    register_pack_routes(app)

    # Tool-category catalog
    register_tool_category_routes(app)

    # Application settings
    register_settings_routes(app)

    # Setup wizard completion
    register_setup_routes(app)

    # Desktop API
    register_desktop_routes(app)

    # Browser takeover side channel (WebSocket)
    register_browser_control_routes(app)
    register_browser_profile_routes(app)

    # Conversation sessions API
    register_conversation_routes(app)

    # Artifacts hub API
    register_artifacts_routes(app)

    # Task engine routes
    register_task_routes(app)

    # Integrations (supervisor / brokers)
    register_integrations_routes(app)
    register_oauth_routes(app)

    # Container file serving — lets the frontend (and agent-authored HTML) reference
    # container files by their real path instead of base64-encoding them.
    register_container_file_routes(app)

    # UI routes
    register_ui_routes(app)

    # Phase 1: Data migrations — synchronous, must complete before anything
    # else reads state.  No user interaction needed.
    app.on_startup.append(_run_data_migrations)

    # Phase 2: Readiness signals — each contributor hook calls
    # ``register_ready_contributor`` and signals its event when its
    # prerequisite is met. ``_init_ready_signal`` aggregates them all into
    # ``app["ready"]``; it MUST run after every contributor hook so the
    # contributor list is fully populated before the aggregator inspects it.
    # Adding a new gating signal: a new ``_init_*_signal`` hook above the
    # aggregator. The deferred init in Phase 3 stays unchanged.
    #   * setup readiness — fires when the setup wizard completes (or
    #     immediately if it already did on a previous boot).
    #   * integrations readiness — fires when the supervisor cache load
    #     finishes, which transitively means every registered broker has
    #     completed its READY handshake.
    app.on_startup.append(_init_setup_signal)
    app.on_startup.append(_init_integrations_signal)
    app.on_startup.append(_init_ready_signal)

    # Phase 3: Deferred subsystems — a single background task awaits
    # ``app["ready"]`` and then initializes everything that needed to wait.
    app.on_startup.append(_start_deferred_subsystems)
    app.on_cleanup.append(_stop_deferred_subsystems)
    app.on_cleanup.append(_stop_active_run_manager)

    return app


async def _stop_active_run_manager(app: web.Application) -> None:
    """Gracefully stop process-owned agent runs during server shutdown."""
    await app[ACTIVE_RUN_MANAGER_KEY].close()


async def _run_data_migrations(_app: web.Application) -> None:
    """Run pending data migrations against the state directory."""
    from migrations import run_migrations

    config = load_config()
    state_dir = Path(config.settings.home_dir)
    run_migrations(state_dir)


def register_ready_contributor(app: web.Application, name: str) -> asyncio.Event:
    """Register a contributor to the aggregate ``app["ready"]`` event.

    Returns the ``asyncio.Event`` the caller signals when its prerequisite
    is met. ``_init_ready_signal`` collects every registered contributor and
    sets ``app["ready"]`` once they're all signalled.

    Must be called from an on-startup hook registered before
    ``_init_ready_signal`` so the aggregator sees the contributor.
    """
    event = asyncio.Event()
    app.setdefault("_ready_contributors", []).append((name, event))
    return event


async def _init_setup_signal(app: web.Application) -> None:
    """Register the setup-readiness contributor."""
    import setup

    app["setup_ready"] = register_ready_contributor(app, "setup")
    if setup.is_ready():
        app["setup_ready"].set()
        logger.info("Setup already complete — setup-ready signal set")
    else:
        logger.info("Setup not complete — waiting for wizard to finish")


_INTEGRATIONS_LOAD_DEADLINE_SECONDS = 30.0
_INTEGRATIONS_LOAD_RETRY_INTERVAL_SECONDS = 1.0


async def _init_integrations_signal(app: web.Application) -> None:
    """Register the integrations-readiness contributor and load the cache.

    The supervisor binds ``app.sock`` after reconciling stored brokers
    (an upstream IMAP/CalDAV login per integration), which can take a
    couple of seconds during a cold container start. We retry the cache
    load until it succeeds or a generous deadline elapses, so the chat
    agent's first turn finds the cache already warm. If the deadline
    fires (supervisor permanently unreachable), the readiness event
    still fires so deferred subsystems aren't held up forever — chat
    keeps working without integration tools and the UI surfaces the
    "Integrations unavailable" state.
    """
    from tools.integrations import cache_loaded, registered_integrations

    app["integrations_ready"] = register_ready_contributor(app, "integrations")

    async def _load_with_retry() -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _INTEGRATIONS_LOAD_DEADLINE_SECONDS
        try:
            while True:
                await registered_integrations()
                if cache_loaded():
                    logger.info("Integrations cache loaded")
                    return
                if loop.time() >= deadline:
                    logger.warning(
                        "Integrations cache failed to load within %.0fs; "
                        "deferred subsystems starting without integrations",
                        _INTEGRATIONS_LOAD_DEADLINE_SECONDS,
                    )
                    return
                await asyncio.sleep(_INTEGRATIONS_LOAD_RETRY_INTERVAL_SECONDS)
        finally:
            app["integrations_ready"].set()

    # Store the task on the app so the GC doesn't drop it before it completes.
    app["_integrations_load"] = asyncio.create_task(
        _load_with_retry(),
        name="integrations-load-gate",
    )


async def _init_ready_signal(app: web.Application) -> None:
    """Aggregate every registered contributor into ``app["ready"]``.

    Spawns a watcher task that awaits each contributor's event in turn and
    sets ``app["ready"]`` once they're all signalled. Runs after every
    ``_init_*_signal`` hook so the contributor list is complete.
    """
    app["ready"] = asyncio.Event()
    contributors = app.get("_ready_contributors", [])
    if not contributors:
        app["ready"].set()
        return

    async def _watch() -> None:
        for name, event in contributors:
            if not event.is_set():
                logger.info("Waiting on readiness signal: %s", name)
            await event.wait()
        app["ready"].set()
        logger.info("All readiness signals set")

    app["_ready_watcher"] = asyncio.create_task(_watch(), name="ready-watcher")


async def _start_deferred_subsystems(app: web.Application) -> None:
    """Wait for ``app["ready"]``, then initialize all deferred subsystems."""

    async def _deferred() -> None:
        try:
            if not app["ready"].is_set():
                logger.info("Deferred subsystems waiting for readiness")
            await app["ready"].wait()
            logger.info("Ready — starting deferred subsystems")
            await _init_task_runner(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to start deferred subsystems")

    app["_deferred_init"] = asyncio.create_task(_deferred(), name="deferred-init")


async def _init_task_runner(app: web.Application) -> None:
    """Initialize and start the task runner."""
    config = load_config()
    if not config.routines.enabled:
        return

    from tasks import TaskExecutor, TaskRunner, TelegramNotifier, get_store

    store = get_store()
    executor = TaskExecutor(store)

    notifier = None
    if config.routines.notifications.enabled:
        notifier = TelegramNotifier(config.routines.notifications)
        if not notifier.enabled:
            notifier = None

    runner = TaskRunner(store, executor, config.routines, notifier=notifier)
    app["task_runner"] = runner
    await runner.start()


async def _stop_deferred_subsystems(app: web.Application) -> None:
    """Cancel the deferred init task and stop all subsystems."""
    init_task = app.get("_deferred_init")
    if init_task and not init_task.done():
        init_task.cancel()
    runner = app.get("task_runner")
    if runner:
        await runner.stop()


__all__ = ["ACTIVE_RUN_MANAGER_KEY", "create_app"]
