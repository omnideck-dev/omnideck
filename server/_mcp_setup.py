"""Explicit MCP OAuth setup and its connection commit, scoped to one app."""

import asyncio
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
from pydantic import AnyUrl

from brokering.brokers.mcp_broker.authorization import OAuthStorage, PersistentOAuthProvider
from brokering.brokers.mcp_broker.client import discover
from brokering.brokers.mcp_broker._network import mcp_http_client, validated_address
from server._mcp_oauth_callback import MCPOAuthCallback


@dataclass(repr=False)
class PendingMCPSetup:
    handle: str
    receiver: MCPOAuthCallback
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    created_at: float = field(default_factory=time.monotonic)
    status: str = "pending"
    authorize_url: str | None = None
    oauth_state: str | None = None
    integration_id: str | None = None

    def public_status(self) -> dict[str, Any]:
        result: dict[str, Any] = {"state": self.handle, "status": self.status, "integration_id": self.integration_id}
        if self.status == "error":
            result["error"] = {"code": "AUTH", "message": "Could not connect. Check the server and sign-in settings, then retry."}
        return result


class MCPSetupManager:
    """Bounded in-memory setup attempts; no tokens in status responses or logs."""

    def __init__(
        self, *, callback_origin: str, commit: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
        allow_loopback: bool = False,
    ) -> None:
        origin = urlsplit(callback_origin)
        if (
            origin.scheme != "http" or origin.hostname != "localhost" or not origin.port
            or origin.username or origin.password or origin.query or origin.fragment or origin.path not in {"", "/"}
        ):
            raise ValueError("MCP callback origin must be http://localhost:<published app port>.")
        self._port = origin.port
        self._commit = commit
        self._allow_loopback = allow_loopback
        self._pending: dict[str, PendingMCPSetup] = {}

    @property
    def redirect_uri(self) -> str:
        return f"http://localhost:{self._port}/api/integrations/mcp/oauth/callback"

    async def start(self, settings: dict[str, str]) -> PendingMCPSetup:
        self._prune()
        if len(self._pending) >= 32:
            raise ValueError("Too many sign-in attempts. Close an existing attempt and retry.")
        endpoint = settings["endpoint"]
        await validated_address(httpx2.URL(endpoint), allow_loopback=self._allow_loopback)
        pending = PendingMCPSetup("mcp_" + secrets.token_urlsafe(32), MCPOAuthCallback(port=self._port, timeout=600))
        self._pending[pending.handle] = pending
        pending.task = asyncio.create_task(self._run(pending, dict(settings)), name="mcp-setup")
        try:
            async with asyncio.timeout(35):
                await pending.ready.wait()
        except (Exception, asyncio.CancelledError):
            await self.cancel(pending.handle)
            raise
        return pending

    async def _run(self, pending: PendingMCPSetup, settings: dict[str, str]) -> None:
        try:
            async with asyncio.timeout(600):
                fields = await self._authorize_and_discover(pending, settings)
            # Persistence is outside the interactive deadline. Once it starts,
            # the UI must wait for a definitive outcome instead of cancelling
            # a supervisor request that may already have created a connection.
            pending.status = "committing"
            pending.ready.set()
            args: dict[str, Any] = {"kind": "integration", "auth_blob": fields}
            reconnect_id = settings.get("reconnect_id")
            if reconnect_id:
                args["id"] = reconnect_id
            else:
                args.update(slug=settings["slug"], label=settings["label"], user_suffix=secrets.token_hex(8), operation_grants=[])
            result = await self._commit("reconnect" if reconnect_id else "add", args)
            pending.integration_id = result["id"]
            pending.status = "success"
        except asyncio.CancelledError:
            pending.status = "cancelled"
            raise
        except TimeoutError:
            pending.status = "expired"
        except Exception:
            # Provider errors may embed credentials, callback codes or state.
            pending.status = "error"
        finally:
            settings.clear()
            pending.receiver.cancel()
            pending.authorize_url = None
            pending.oauth_state = None
            pending.ready.set()

    async def _authorize_and_discover(self, pending: PendingMCPSetup, settings: dict[str, str]) -> dict[str, str]:
        storage = OAuthStorage()
        metadata = OAuthClientMetadata(
            client_name="omnideck", redirect_uris=[AnyUrl(self.redirect_uri)],
            token_endpoint_auth_method="none", scope=settings.get("scopes") or None,
        )
        if settings.get("client_id"):
            if not settings.get("issuer"):
                raise ValueError("A preregistered client must name its authorization server.")
            await validated_address(httpx2.URL(settings["issuer"]), allow_loopback=self._allow_loopback)
            storage.client_info = OAuthClientInformationFull(
                **metadata.model_dump(), client_id=settings["client_id"], issuer=settings["issuer"],
            )

        async def redirect(url: str) -> None:
            await validated_address(httpx2.URL(url), allow_loopback=self._allow_loopback)
            pending.receiver.arm(url)
            pending.authorize_url = url
            pending.oauth_state = parse_qs(urlsplit(url).query)["state"][0]
            pending.ready.set()

        provider = PersistentOAuthProvider(
            server_url=settings["endpoint"], storage=storage, client_metadata=metadata,
            requested_scopes=settings.get("scopes") or None,
            redirect_handler=redirect, callback_handler=pending.receiver.wait_for_result,
        )
        async with mcp_http_client(auth=provider, allow_loopback=self._allow_loopback, resource_endpoint=settings["endpoint"]) as http:
            async with Client(streamable_http_client(settings["endpoint"], http_client=http), cache=None) as client:
                operations = await discover(client)
        storage.capture_metadata(provider)
        return {
            "endpoint": settings["endpoint"],
            "access_token": storage.tokens.access_token if storage.tokens else "",
            "oauth_state": storage.serialize(),
            "discovered_operations": json.dumps([operation.public_dict() for operation in operations]),
        }

    def status(self, handle: str) -> PendingMCPSetup | None:
        self._prune()
        return self._pending.get(handle)

    def callback(self, state: str) -> MCPOAuthCallback | None:
        return next((pending.receiver for pending in self._pending.values() if pending.oauth_state == state), None)

    async def cancel(self, handle: str) -> PendingMCPSetup | None:
        pending = self.status(handle)
        if pending is not None and pending.status == "pending" and pending.task is not None:
            pending.task.cancel()
            await asyncio.gather(pending.task, return_exceptions=True)
        elif pending is not None and pending.status == "committing" and pending.task is not None:
            await asyncio.shield(pending.task)
        return pending

    def _prune(self) -> None:
        self._pending = {
            handle: pending for handle, pending in self._pending.items()
            if pending.status in {"pending", "committing"} or time.monotonic() - pending.created_at < 3600
        }

    async def close(self) -> None:
        tasks = [pending.task for pending in self._pending.values() if pending.task is not None]
        for pending in self._pending.values():
            if pending.status == "pending" and pending.task is not None:
                pending.task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._pending.clear()
