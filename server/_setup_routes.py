"""HTTP route handlers for the setup-completion API.

The setup wizard's finish step is a single server-side orchestration
instead of a chain of client-side calls. The client sends the user's
picks (provider, main model, optional vision model); this handler seeds
the per-use settings, stamps the shipped profiles, and flips
``setup_complete`` last — so a partial failure doesn't leave the app in
an incomplete-but-flagged-complete state.
"""

from __future__ import annotations

import json
import logging
import os

from aiohttp import web
from pydantic import BaseModel, ConfigDict, ValidationError

from agents import apply_llm_config_to_profiles
from artifacts import list_artifacts, reconcile
from conversations import conversation_exists
from migrations._welcome_constants import (
    WELCOME_CONVERSATION_ID,
    WELCOME_DASHBOARD_FILENAME,
)
from sdk.providers import get_provider
from settings import load_settings, save_settings
from setup import mark_ready

logger = logging.getLogger(__name__)


class _CompleteBody(BaseModel):
    """Schema for ``POST /api/setup/complete``."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    main_model: str
    vision_model: str | None = None
    context_window: int | None = None
    default_agent: str = "omnideck"


def _welcome_startup_payload() -> dict[str, object] | None:
    """Resolve the seeded welcome content used by the first Desktop mount.

    The server returns domain identities and data only. The browser remains
    responsible for translating them into a Desktop Layout snapshot.
    """
    try:
        # The artifact index intentionally keeps provenance after a
        # conversation is archived or deleted. Do not let that stale index
        # entry resurrect welcome content the user removed from the active
        # list.
        if not conversation_exists(WELCOME_CONVERSATION_ID):
            return None
        artifacts = reconcile(list_artifacts(WELCOME_CONVERSATION_ID))
    except Exception:
        # Welcome placement is optional. Setup has already succeeded and must
        # not report a false failure because optional onboarding data could
        # not be resolved.
        logger.exception("could not resolve welcome startup content")
        return None
    dashboard = next(
        (
            artifact
            for artifact in artifacts
            if artifact.filename == WELCOME_DASHBOARD_FILENAME
        ),
        None,
    )
    if dashboard is None or dashboard.status != "present":
        logger.warning("welcome dashboard artifact was not available at setup completion")
        return None
    return {
        "conversation_id": WELCOME_CONVERSATION_ID,
        "artifact": dashboard.model_dump(),
    }


async def handle_defaults(_request: web.Request) -> web.Response:
    """Return setup-time defaults derived from the server environment."""
    ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
    return web.json_response({"ollama_host": ollama_host or None})


async def handle_complete(request: web.Request) -> web.Response:
    """Finish the setup wizard server-side.

    Steps, in order so any failure short of the final flag-flip leaves
    a recoverable state:

    1. Validate the provider is actually configured (raises if not).
    2. Seed ``vision_provider`` / ``vision_model`` / ``compaction_provider``
       / ``compaction_model`` / ``title_provider`` / ``title_model`` and
       ``default_agent`` in settings.
    3. Stamp the shipped profiles with the chosen provider+model via
       ``apply_llm_config_to_profiles``.
    4. Flip ``setup_complete`` to true (last) and call ``mark_ready`` so
       any ready-gated waiters fire.
    """
    # A repeated API call must not re-offer onboarding content to an existing
    # installation. The browser normally cannot remount the wizard once this
    # is true, but the server enforces the transition as well.
    was_setup_complete = load_settings().get("setup_complete") is True

    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "request body must be a JSON object"}, status=400)
    try:
        spec = _CompleteBody(**body)
    except ValidationError as exc:
        logger.warning("invalid /api/setup/complete body: %s", exc)
        return web.json_response({"error": "Unknown or invalid field"}, status=400)

    try:
        get_provider(spec.provider)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    save_settings({
        "default_agent": spec.default_agent,
        # Vision is optional — if the wizard skipped, leave the per-use
        # fields empty so vision_generate returns its "no model configured"
        # error rather than half-resolving.
        "vision_provider": spec.provider if spec.vision_model else "",
        "vision_model": spec.vision_model or "",
        "compaction_provider": spec.provider,
        "compaction_model": spec.main_model,
        "title_provider": spec.provider,
        "title_model": spec.main_model,
    })

    apply_llm_config_to_profiles(
        spec.main_model,
        provider=spec.provider,
        context_window=spec.context_window,
    )

    saved = save_settings({"setup_complete": True})
    mark_ready(request.app)
    return web.json_response({
        **saved,
        "welcome": (
            None
            if was_setup_complete
            else _welcome_startup_payload()
        ),
    })


def register_setup_routes(app: web.Application) -> None:
    """Register setup API routes."""
    app.router.add_route("GET", "/api/setup/defaults", handle_defaults)
    app.router.add_route("POST", "/api/setup/complete", handle_complete)
