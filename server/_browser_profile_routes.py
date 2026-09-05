"""HTTP routes for Browser working state and explicitly saved profiles."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agents import get_agent_profile, list_agent_profiles, save_agent_profile
from browser import BrowserProfile, summarize_browser_sites
from browser.runtime import get_browser_runtime


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LoadBrowserSessionRequest(_RequestModel):
    profile_id: str = Field(min_length=1, max_length=128)


class SaveBrowserStateRequest(_RequestModel):
    profile_id: str | None = Field(default=None, min_length=1, max_length=128)
    name: str = Field(default="", max_length=100)
    icon: str = Field(default="bi-globe2", pattern=r"^bi-[a-z0-9-]+$", max_length=64)
    assign_to_agent: bool = False


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


def _profile_json(profile: BrowserProfile) -> web.Response:
    return web.json_response(profile.model_dump(mode="json"))


async def handle_browser_session(_request: web.Request) -> web.Response:
    runtime = get_browser_runtime()
    await runtime.ensure_user_browser()
    return web.json_response(await runtime.summarize_user_browser())


async def handle_load_browser_session(request: web.Request) -> web.Response:
    body = await _validated_json(request, LoadBrowserSessionRequest)
    assert isinstance(body, LoadBrowserSessionRequest)
    try:
        runtime = get_browser_runtime()
        await runtime.load_user_browser_profile(body.profile_id)
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    return web.json_response(await runtime.summarize_user_browser())


async def handle_save_browser_session(request: web.Request) -> web.Response:
    body = await _validated_json(request, SaveBrowserStateRequest)
    assert isinstance(body, SaveBrowserStateRequest)
    runtime = get_browser_runtime()
    try:
        if body.profile_id:
            profile = await runtime.save_user_browser_to_existing(body.profile_id)
        else:
            profile = await runtime.save_user_browser_as_new(
                name=body.name,
                icon=body.icon,
            )
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    except OSError:
        return web.json_response({"error": "Browser profile could not be saved"}, status=500)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return _profile_json(profile)


async def handle_preview_browser_session(_request: web.Request) -> web.Response:
    runtime = get_browser_runtime()
    sites = await runtime.preview_user_browser()
    return web.json_response(
        {
            "browser_profile_id": runtime.user_browser_profile_id,
            "sites": [site.model_dump(mode="json") for site in sites],
        }
    )


async def handle_list_browser_profiles(_request: web.Request) -> web.Response:
    profiles = await asyncio.to_thread(get_browser_runtime().profiles.list)
    return web.json_response([profile.model_dump(mode="json") for profile in profiles])


async def handle_update_browser_profile(request: web.Request) -> web.Response:
    body = await _validated_json(request, UpdateBrowserProfileRequest)
    assert isinstance(body, UpdateBrowserProfileRequest)
    try:
        profile = await asyncio.to_thread(
            get_browser_runtime().profiles.update_metadata,
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
    runtime = get_browser_runtime()
    live_agent_profile_ids = await runtime.agent_profiles_using_live_profile(profile_id)
    agent_names = {profile.id: profile.name for profile in agent_profiles}
    assigned_profile_ids = {
        profile.id for profile in agent_profiles if profile.browser_profile_id == profile_id
    } | live_agent_profile_ids
    assigned = sorted(
        {agent_names.get(agent_profile_id, agent_profile_id) for agent_profile_id in assigned_profile_ids},
        key=str.casefold,
    )
    loaded_in_browser = runtime.user_browser_profile_id == profile_id
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
    try:
        await asyncio.to_thread(runtime.profiles.delete, profile_id)
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    except OSError:
        return web.json_response({"error": "Browser profile could not be deleted"}, status=500)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.Response(status=204)


async def handle_remove_browser_profile_sites(request: web.Request) -> web.Response:
    body = await _validated_json(request, RemoveBrowserProfileSitesRequest)
    assert isinstance(body, RemoveBrowserProfileSitesRequest)
    try:
        profile = await asyncio.to_thread(
            get_browser_runtime().profiles.remove_domains,
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
            get_browser_runtime().profiles.clear_state,
            request.match_info["id"],
        )
    except KeyError:
        return web.json_response({"error": "Browser profile not found"}, status=404)
    except OSError:
        return web.json_response({"error": "Browser profile could not be updated"}, status=500)
    return _profile_json(profile)


async def handle_save_takeover(request: web.Request) -> web.Response:
    conversation_id = request.match_info["conversation_id"]
    runtime = get_browser_runtime()
    browser = await runtime.get_conversation_browser(conversation_id)
    if browser is None:
        return web.json_response({"error": "No active browser session"}, status=404)
    body = await _validated_json(request, SaveBrowserStateRequest)
    assert isinstance(body, SaveBrowserStateRequest)
    binding = await runtime.get_conversation_binding(conversation_id)
    if binding is None or not binding.browser_access_enabled:
        return web.json_response({"error": "No active Browser assignment"}, status=409)
    if body.profile_id and body.profile_id != binding.browser_profile_id:
        return web.json_response(
            {"error": "This Browser session can only update its loaded profile"},
            status=409,
        )
    if body.profile_id and body.assign_to_agent:
        return web.json_response(
            {"error": "Only a new profile can be assigned during takeover"},
            status=400,
        )
    try:
        if body.profile_id:
            profile = await runtime.save_browser_to_existing(browser, body.profile_id)
        else:
            profile = await runtime.save_browser_as_new(
                browser,
                name=body.name,
                icon=body.icon,
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
            binding.agent_profile_id,
        )
        if agent_profile is not None:
            await asyncio.to_thread(
                save_agent_profile,
                agent_profile.model_copy(update={"browser_profile_id": profile.id}),
            )
            await runtime.assign_profile_to_live_conversation(
                conversation_id,
                profile.id,
            )
            assigned = True
    return web.json_response({"profile": profile.model_dump(mode="json"), "assigned_to_agent": assigned})


async def handle_preview_takeover(request: web.Request) -> web.Response:
    conversation_id = request.match_info["conversation_id"]
    runtime = get_browser_runtime()
    browser = await runtime.get_conversation_browser(conversation_id)
    if browser is None:
        return web.json_response({"error": "No active browser session"}, status=404)
    binding = await runtime.get_conversation_binding(conversation_id)
    if binding is None or not binding.browser_access_enabled:
        return web.json_response({"error": "No active Browser assignment"}, status=409)
    storage_state = await browser.capture_storage_state()
    agent_profile = await asyncio.to_thread(
        get_agent_profile,
        binding.agent_profile_id,
    )
    sites = summarize_browser_sites(storage_state)
    return web.json_response(
        {
            "browser_profile_id": binding.browser_profile_id,
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
