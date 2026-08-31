"""HTTP routes for Browser working state and explicitly saved profiles."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agents import get_agent_profile, list_agent_profiles, save_agent_profile
from browser_profiles import get_browser_profile_store
from browser_profiles._conversation import (
    detach_deleted_browser_profile,
    get_conversation_browser_session,
    set_conversation_browser_source_profile_id,
)
from browser_profiles._preview import (
    capture_browser_state_preview,
    consume_browser_state_preview,
)
from browser_profiles._session import (
    browser_session_summary,
    ensure_user_browser,
    load_user_browser_profile,
    save_browser_context_as_new,
    save_browser_context_to_existing,
    save_user_browser_as_new,
    save_user_browser_to_existing,
    start_user_browser_fresh,
)
from browser_profiles._store import summarize_browser_sites
from tools.browser.core.pool import (
    get_browser_by_conversation_id,
    get_user_browser_source_profile_id,
)


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LoadBrowserSessionRequest(_RequestModel):
    profile_id: str | None = Field(default=None, min_length=1, max_length=128)


class SaveBrowserStateRequest(_RequestModel):
    profile_id: str | None = Field(default=None, min_length=1, max_length=128)
    name: str = Field(default="", max_length=100)
    icon: str = Field(default="bi-globe2", pattern=r"^bi-[a-z0-9-]+$", max_length=64)
    assign_to_agent: bool = False
    preview_token: str | None = Field(default=None, min_length=1, max_length=128)


class UpdateBrowserProfileRequest(_RequestModel):
    name: str | None = Field(default=None, max_length=100)
    icon: str | None = Field(
        default=None,
        pattern=r"^bi-[a-z0-9-]+$",
        max_length=64,
    )


class RemoveBrowserProfileSitesRequest(_RequestModel):
    domains: list[Annotated[str, Field(min_length=1, max_length=253)]] = Field(
        min_length=1,
        max_length=500,
    )


async def _json(request: web.Request) -> dict:
    try:
        value = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="Invalid JSON") from None
    if not isinstance(value, dict):
        raise web.HTTPBadRequest(text="Invalid JSON")
    return value


async def _validated_json(
    request: web.Request,
    model: type[_RequestModel],
) -> _RequestModel:
    try:
        return model.model_validate(await _json(request))
    except ValidationError as exc:
        details = exc.errors(include_url=False)
        message = details[0]["msg"] if details else "Invalid request"
        raise web.HTTPBadRequest(
            text=json.dumps({"error": message}),
            content_type="application/json",
        ) from None


def _profile_json(profile: object) -> web.Response:
    return web.json_response(profile.model_dump(mode="json"))  # type: ignore[attr-defined]


async def handle_browser_session(_request: web.Request) -> web.Response:
    await ensure_user_browser()
    return web.json_response(await asyncio.to_thread(browser_session_summary))


async def handle_load_browser_session(request: web.Request) -> web.Response:
    body = await _validated_json(request, LoadBrowserSessionRequest)
    assert isinstance(body, LoadBrowserSessionRequest)
    profile_id = body.profile_id
    try:
        if profile_id is None:
            await start_user_browser_fresh()
        else:
            await load_user_browser_profile(str(profile_id))
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    return web.json_response(await asyncio.to_thread(browser_session_summary))


async def handle_save_browser_session(request: web.Request) -> web.Response:
    body = await _validated_json(request, SaveBrowserStateRequest)
    assert isinstance(body, SaveBrowserStateRequest)
    browser = await ensure_user_browser()
    storage_state = consume_browser_state_preview(
        body.preview_token,
        scope="user",
        browser=browser,
    )
    if body.preview_token and storage_state is None:
        return web.json_response(
            {"error": "Browser changed. Close this dialog and save again."},
            status=409,
        )
    try:
        if body.profile_id:
            profile = await save_user_browser_to_existing(
                body.profile_id,
                storage_state=storage_state,
            )
        else:
            profile = await save_user_browser_as_new(
                name=body.name,
                icon=body.icon,
                storage_state=storage_state,
            )
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    except OSError:
        return web.json_response({"error": "Browser profile could not be saved"}, status=500)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return _profile_json(profile)


async def handle_preview_browser_session(_request: web.Request) -> web.Response:
    browser = await ensure_user_browser()
    token, storage_state = await capture_browser_state_preview(browser, scope="user")
    sites = summarize_browser_sites(storage_state)
    return web.json_response(
        {
            "preview_token": token,
            "source_profile_id": get_user_browser_source_profile_id(),
            "sites": [site.model_dump(mode="json") for site in sites],
        }
    )


async def handle_list_browser_profiles(_request: web.Request) -> web.Response:
    profiles = await asyncio.to_thread(get_browser_profile_store().list)
    return web.json_response([profile.model_dump(mode="json") for profile in profiles])


async def handle_update_browser_profile(request: web.Request) -> web.Response:
    body = await _validated_json(request, UpdateBrowserProfileRequest)
    assert isinstance(body, UpdateBrowserProfileRequest)
    try:
        profile = await asyncio.to_thread(
            get_browser_profile_store().update_metadata,
            request.match_info["id"],
            name=body.name,
            icon=body.icon,
        )
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    except OSError:
        return web.json_response({"error": "Browser profile could not be updated"}, status=500)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return _profile_json(profile)


async def handle_delete_browser_profile(request: web.Request) -> web.Response:
    profile_id = request.match_info["id"]
    agent_profiles = await asyncio.to_thread(
        list_agent_profiles,
        include_disabled=True,
    )
    assigned = [
        profile.name
        for profile in agent_profiles
        if profile.browser_access and profile.browser_profile_id == profile_id
    ]
    loaded_in_browser = get_user_browser_source_profile_id() == profile_id
    if assigned or loaded_in_browser:
        return web.json_response(
            {
                "error": "This browser profile is in use",
                "usage": {
                    "loaded_in_browser": loaded_in_browser,
                    "agents": assigned,
                },
            },
            status=409,
        )
    disabled_references = [
        profile for profile in agent_profiles if not profile.browser_access and profile.browser_profile_id == profile_id
    ]
    try:
        await asyncio.to_thread(get_browser_profile_store().delete, profile_id)
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    except OSError:
        return web.json_response({"error": "Browser profile could not be deleted"}, status=500)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    for profile in disabled_references:
        await asyncio.to_thread(
            save_agent_profile,
            profile.model_copy(update={"browser_profile_id": None}),
        )
    detach_deleted_browser_profile(profile_id)
    return web.Response(status=204)


async def handle_remove_browser_profile_sites(request: web.Request) -> web.Response:
    body = await _validated_json(request, RemoveBrowserProfileSitesRequest)
    assert isinstance(body, RemoveBrowserProfileSitesRequest)
    try:
        profile = await asyncio.to_thread(
            get_browser_profile_store().remove_domains,
            request.match_info["id"],
            body.domains,
        )
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    except OSError:
        return web.json_response({"error": "Browser profile could not be updated"}, status=500)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return _profile_json(profile)


async def handle_clear_browser_profile_state(request: web.Request) -> web.Response:
    try:
        profile = await asyncio.to_thread(
            get_browser_profile_store().clear_state,
            request.match_info["id"],
        )
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    except OSError:
        return web.json_response({"error": "Browser profile could not be updated"}, status=500)
    return _profile_json(profile)


async def handle_save_takeover(request: web.Request) -> web.Response:
    conversation_id = request.match_info["conversation_id"]
    browser = await get_browser_by_conversation_id(conversation_id)
    if browser is None:
        return web.json_response({"error": "No active browser session"}, status=404)
    body = await _validated_json(request, SaveBrowserStateRequest)
    assert isinstance(body, SaveBrowserStateRequest)
    session = get_conversation_browser_session(conversation_id)
    if session is None or not session.browser_access:
        return web.json_response({"error": "No active Browser assignment"}, status=409)
    if body.profile_id and body.profile_id != session.source_profile_id:
        return web.json_response(
            {"error": "This Browser session can only update its loaded profile"},
            status=409,
        )
    if body.profile_id and body.assign_to_agent:
        return web.json_response(
            {"error": "Only a new profile can be assigned during takeover"},
            status=400,
        )
    storage_state = consume_browser_state_preview(
        body.preview_token,
        scope=f"conversation:{conversation_id}",
        browser=browser,
    )
    if body.preview_token and storage_state is None:
        return web.json_response(
            {"error": "Browser changed. Close this dialog and save again."},
            status=409,
        )
    try:
        if body.profile_id:
            profile = await save_browser_context_to_existing(
                browser,
                body.profile_id,
                storage_state=storage_state,
            )
        else:
            profile = await save_browser_context_as_new(
                browser,
                name=body.name,
                icon=body.icon,
                storage_state=storage_state,
            )
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    except OSError:
        return web.json_response({"error": "Browser profile could not be saved"}, status=500)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    assigned = False
    if body.assign_to_agent:
        agent_profile = await asyncio.to_thread(
            get_agent_profile,
            session.agent_profile_id,
        )
        if agent_profile is not None:
            await asyncio.to_thread(
                save_agent_profile,
                agent_profile.model_copy(update={"browser_access": True, "browser_profile_id": profile.id}),
            )
            assigned = True
    if not body.profile_id:
        set_conversation_browser_source_profile_id(
            conversation_id,
            profile.id,
            assigned_to_agent=assigned,
        )
    return web.json_response({"profile": profile.model_dump(mode="json"), "assigned_to_agent": assigned})


async def handle_preview_takeover(request: web.Request) -> web.Response:
    conversation_id = request.match_info["conversation_id"]
    browser = await get_browser_by_conversation_id(conversation_id)
    if browser is None:
        return web.json_response({"error": "No active browser session"}, status=404)
    session = get_conversation_browser_session(conversation_id)
    if session is None or not session.browser_access:
        return web.json_response({"error": "No active Browser assignment"}, status=409)
    token, storage_state = await capture_browser_state_preview(
        browser,
        scope=f"conversation:{conversation_id}",
    )
    agent_profile = await asyncio.to_thread(
        get_agent_profile,
        session.agent_profile_id,
    )
    sites = summarize_browser_sites(storage_state)
    return web.json_response(
        {
            "preview_token": token,
            "source_profile_id": session.source_profile_id,
            "agent_name": agent_profile.name if agent_profile is not None else "",
            "sites": [site.model_dump(mode="json") for site in sites],
        }
    )


def register_browser_profile_routes(app: web.Application) -> None:
    app.router.add_route("GET", "/api/browser/session", handle_browser_session)
    app.router.add_route("POST", "/api/browser/session/load", handle_load_browser_session)
    app.router.add_route("POST", "/api/browser/session/save", handle_save_browser_session)
    app.router.add_route("GET", "/api/browser/session/preview", handle_preview_browser_session)
    app.router.add_route("GET", "/api/browser/profiles", handle_list_browser_profiles)
    app.router.add_route("PUT", "/api/browser/profiles/{id}", handle_update_browser_profile)
    app.router.add_route("DELETE", "/api/browser/profiles/{id}", handle_delete_browser_profile)
    app.router.add_route(
        "DELETE",
        "/api/browser/profiles/{id}/sites",
        handle_remove_browser_profile_sites,
    )
    app.router.add_route(
        "DELETE",
        "/api/browser/profiles/{id}/state",
        handle_clear_browser_profile_state,
    )
    app.router.add_route(
        "POST",
        "/api/browser/conversations/{conversation_id}/save",
        handle_save_takeover,
    )
    app.router.add_route(
        "GET",
        "/api/browser/conversations/{conversation_id}/preview",
        handle_preview_takeover,
    )


__all__ = ["register_browser_profile_routes"]
