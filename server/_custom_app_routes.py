"""HTTP surface for experimental Custom Apps."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import load_config
from settings import custom_apps_enabled, load_settings, save_settings

logger = logging.getLogger(__name__)

_APP_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62})$")
_ACTION_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_RUNNER_PATH = Path(__file__).with_name("_custom_app_runner.py")
_MAX_RUNNER_OUTPUT = 1024 * 1024
_RUNNER_TIMEOUT_SECONDS = 120.0


class CustomAppManifest(BaseModel):
    """User-authored metadata that marks a folder as an app."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    icon: str = Field(default="bi-window", pattern=r"^bi-[a-z0-9-]+$")


class InvokeRequest(BaseModel):
    """Arguments supplied by an app frontend to one backend action."""

    model_config = ConfigDict(extra="forbid")

    args: dict[str, Any] = Field(default_factory=dict)


class HomeAppRequest(BaseModel):
    """A request to assign one discovered app to the Home slot."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,62})$")


class RunnerError(BaseModel):
    """Structured action failure emitted by the subprocess runner."""

    code: str
    message: str


class RunnerEnvelope(BaseModel):
    """One complete response emitted by the subprocess runner."""

    ok: bool
    result: Any = None
    error: RunnerError | None = None


@dataclass(frozen=True)
class CustomApp:
    """A validated app folder discovered beneath an allowed root."""

    slug: str
    path: Path
    manifest: CustomAppManifest

    def to_dict(self) -> dict[str, str | bool]:
        """Return metadata safe to expose to the frontend."""
        return {
            "slug": self.slug,
            "title": self.manifest.title,
            "description": self.manifest.description,
            "icon": self.manifest.icon,
            "has_actions": (self.path / "app.py").is_file(),
        }


class CustomAppRuntimeError(Exception):
    """A failure to locate or execute a Custom App action."""

    def __init__(self, code: str, message: str, *, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def custom_app_roots() -> tuple[Path, ...]:
    """Return the user-owned Custom Apps root."""
    config = load_config()
    user = Path(config.virtual_computer.home_dir) / "apps"
    return (user,)


def discover_custom_apps() -> list[CustomApp]:
    """Discover valid direct-child app directories or directory symlinks."""
    discovered: dict[str, CustomApp] = {}
    for root in custom_app_roots():
        if not root.is_dir():
            continue
        for candidate in root.iterdir():
            if not _APP_SLUG.fullmatch(candidate.name):
                continue
            try:
                app_path = candidate.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                logger.warning("Ignoring unresolved Custom App %s: %s", candidate.name, exc)
                continue
            if not app_path.is_dir():
                continue
            manifest_path = app_path / "omnideck.json"
            frontend_path = app_path / "web" / "index.html"
            if not manifest_path.is_file() or not frontend_path.is_file():
                continue
            try:
                manifest = CustomAppManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValidationError) as exc:
                logger.warning("Ignoring invalid Custom App %s: %s", candidate.name, exc)
                continue
            discovered[candidate.name] = CustomApp(
                slug=candidate.name,
                path=app_path,
                manifest=manifest,
            )
    return sorted(discovered.values(), key=lambda app: (app.manifest.title.casefold(), app.slug))


def resolve_custom_app(slug: str) -> CustomApp | None:
    """Resolve one currently valid app by slug."""
    if not _APP_SLUG.fullmatch(slug):
        return None
    return next((app for app in discover_custom_apps() if app.slug == slug), None)


def _feature_disabled() -> web.Response | None:
    if custom_apps_enabled():
        return None
    return web.json_response(
        {"ok": False, "error": {"code": "FEATURE_DISABLED", "message": "Custom Apps are disabled."}},
        status=403,
    )


def _error_response(code: str, message: str, status: int) -> web.Response:
    return web.json_response({"ok": False, "error": {"code": code, "message": message}}, status=status)


async def list_custom_apps_handler(_request: web.Request) -> web.Response:
    """List every currently valid Custom App."""
    if disabled := _feature_disabled():
        return disabled
    return web.json_response({
        "apps": [app.to_dict() for app in discover_custom_apps()],
        "home_app_slug": load_settings().get("home_app_slug"),
    })


async def set_home_custom_app_handler(request: web.Request) -> web.Response:
    """Assign one currently valid Custom App to the trusted Home slot."""
    if disabled := _feature_disabled():
        return disabled
    try:
        payload = HomeAppRequest.model_validate_json(await request.text())
    except ValidationError:
        return _error_response("VALIDATION_ERROR", "Expected a valid custom-app slug.", 400)
    if resolve_custom_app(payload.slug) is None:
        return _error_response("APP_NOT_FOUND", "Custom App not found.", 404)
    save_settings({"home_app_slug": payload.slug})
    return web.json_response({"ok": True, "home_app_slug": payload.slug})


async def clear_home_custom_app_handler(_request: web.Request) -> web.Response:
    """Restore Chat as the default landing view."""
    if disabled := _feature_disabled():
        return disabled
    save_settings({"home_app_slug": None})
    return web.json_response({"ok": True, "home_app_slug": None})


async def custom_app_sdk_handler(_request: web.Request) -> web.Response:
    """Serve the tiny frame-to-shell invocation bridge."""
    if disabled := _feature_disabled():
        return disabled
    source = """(() => {
  let sequence = 0;
  const pending = new Map();
  const shellOrigin = window.location.origin;

  window.addEventListener('message', (event) => {
    if (event.source !== window.parent || event.origin !== shellOrigin) return;
    const message = event.data;
    if (!message || message.type !== 'omnideck:result') return;
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.ok) request.resolve(message.result);
    else request.reject(new Error(message.error?.message || 'App action failed'));
  });

  window.omnideck = Object.freeze({
    invoke(action, args = {}) {
      return new Promise((resolve, reject) => {
        const id = `custom-app-${Date.now()}-${++sequence}`;
        pending.set(id, { resolve, reject });
        window.parent.postMessage({ type: 'omnideck:invoke', id, action, args }, shellOrigin);
      });
    },
    chat: Object.freeze({
      open() {
        window.parent.postMessage({ type: 'omnideck:chat-open' }, shellOrigin);
      },
      compose({ text = '', context = null } = {}) {
        window.parent.postMessage({ type: 'omnideck:chat-compose', text, context }, shellOrigin);
      },
    }),
  });
})();
"""
    return web.Response(
        text=source,
        content_type="text/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def custom_app_web_handler(request: web.Request) -> web.StreamResponse:
    """Serve one file from an app's frontend directory."""
    if disabled := _feature_disabled():
        return disabled
    app = resolve_custom_app(request.match_info["slug"])
    if app is None:
        return _error_response("APP_NOT_FOUND", "Custom App not found.", 404)

    relative = request.match_info.get("path", "") or "index.html"
    if relative.endswith("/"):
        relative += "index.html"
    web_root = (app.path / "web").resolve()
    target = (web_root / relative).resolve()
    if not target.is_relative_to(web_root) or not target.is_file():
        return _error_response("FILE_NOT_FOUND", "App file not found.", 404)

    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "frame-ancestors 'self'",
    }
    return web.FileResponse(target, headers=headers)


async def _invoke_custom_app_action(app: CustomApp, action: str, args: dict[str, Any]) -> Any:
    """Invoke one action in a fresh isolated-mode Python subprocess."""
    if not _ACTION_NAME.fullmatch(action):
        raise CustomAppRuntimeError("ACTION_NOT_FOUND", "App action not found.", status=404)
    if not (app.path / "app.py").is_file():
        raise CustomAppRuntimeError("APP_HAS_NO_ACTIONS", "This app has no backend actions.", status=404)

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        str(_RUNNER_PATH),
        str(app.path),
        action,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        cwd=str(app.path),
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
    )
    request_bytes = json.dumps({"args": args}).encode("utf-8")
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(request_bytes),
            timeout=_RUNNER_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        raise CustomAppRuntimeError("ACTION_TIMEOUT", "App action exceeded its time limit.", status=504) from exc
    except asyncio.CancelledError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        raise

    if len(stdout) > _MAX_RUNNER_OUTPUT:
        raise CustomAppRuntimeError("ACTION_RESULT_TOO_LARGE", "App action returned too much data.", status=500)
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[:500]
        logger.warning("Custom App runner failed for %s/%s: %s", app.slug, action, detail)
        raise CustomAppRuntimeError("ACTION_RUNNER_FAILED", "App action runner failed.", status=500)
    try:
        envelope = RunnerEnvelope.model_validate_json(stdout)
    except ValidationError as exc:
        logger.warning("Invalid Custom App runner response for %s/%s: %s", app.slug, action, exc)
        raise CustomAppRuntimeError("ACTION_PROTOCOL_ERROR", "App action returned an invalid response.", status=500) from exc
    if not envelope.ok:
        error = envelope.error or RunnerError(code="ACTION_FAILED", message="App action failed.")
        status = 404 if error.code == "ACTION_NOT_FOUND" else 400
        raise CustomAppRuntimeError(error.code, error.message, status=status)
    return envelope.result


async def invoke_custom_app_action_handler(request: web.Request) -> web.Response:
    """Validate and execute one public action from a Custom App."""
    if disabled := _feature_disabled():
        return disabled
    app = resolve_custom_app(request.match_info["slug"])
    if app is None:
        return _error_response("APP_NOT_FOUND", "Custom App not found.", 404)
    try:
        payload = InvokeRequest.model_validate_json(await request.text())
    except ValidationError:
        return _error_response("VALIDATION_ERROR", "Expected a JSON object containing an args object.", 400)
    try:
        result = await _invoke_custom_app_action(app, request.match_info["action"], payload.args)
    except CustomAppRuntimeError as exc:
        return _error_response(exc.code, str(exc), exc.status)
    return web.json_response({"ok": True, "result": result})


def register_custom_app_routes(app: web.Application) -> None:
    """Register the experimental custom-app routes."""
    app.router.add_route("GET", "/api/custom-apps", list_custom_apps_handler)
    app.router.add_route("PUT", "/api/custom-apps/home", set_home_custom_app_handler)
    app.router.add_route("DELETE", "/api/custom-apps/home", clear_home_custom_app_handler)
    app.router.add_route("GET", "/api/custom-apps/sdk.js", custom_app_sdk_handler)
    app.router.add_route("GET", "/api/custom-apps/{slug}/web/{path:.*}", custom_app_web_handler)
    app.router.add_route("POST", "/api/custom-apps/{slug}/invoke/{action}", invoke_custom_app_action_handler)


__all__ = [
    "CustomApp",
    "CustomAppRuntimeError",
    "discover_custom_apps",
    "custom_app_roots",
    "register_custom_app_routes",
    "resolve_custom_app",
]
