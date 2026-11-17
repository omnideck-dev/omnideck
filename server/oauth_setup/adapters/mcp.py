"""MCP authorization and discovery, delegated to the pinned SDK."""

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx2
from mcp import Client
from mcp.client.auth import AuthorizationCodeResult
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
from pydantic import AnyUrl

from brokering.mcp_protocol import (
    MCPRequestError, OAuthStorage, PersistentOAuthProvider, discover,
    mcp_error_boundary, mcp_http_client, validated_address,
)
from ..callback import OAuthCallbackError
from ..models import BrowserAuthorization, PreparedConnection, SetupError

MCP_CALLBACK_PATH = "/api/integrations/mcp/oauth/callback"


def callback_uri(origin: str) -> str:
    # This is operator configuration, never an origin inferred from a request.
    # Reject components that cannot belong to an HTTP origin before urlsplit
    # silently strips whitespace/control characters.
    if any(char.isspace() or ord(char) < 32 for char in origin) or any(char in origin for char in "\\?#"):
        raise ValueError("MCP callback origin must be an HTTP or HTTPS origin without a path, credentials, query or fragment.")
    url = urlsplit(origin)
    port = url.port  # Also rejects invalid/out-of-range ports.
    if (url.scheme not in {"http", "https"} or not url.hostname
            or url.username is not None or url.password is not None
            or url.netloc.endswith(":") or port == 0 or url.path not in {"", "/"}):
        raise ValueError("MCP callback origin must be an HTTP or HTTPS origin without a path, credentials, query or fragment.")
    host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
    # Browsers omit default ports in Host, which the callback checks exactly.
    authority = host if port is None or port == {"http": 80, "https": 443}[url.scheme] else f"{host}:{port}"
    return f"{url.scheme}://{authority}{MCP_CALLBACK_PATH}"


@dataclass(repr=False)
class MCPOAuthAdapter:
    settings: dict[str, str]

    async def prepare(self, browser: BrowserAuthorization) -> PreparedConnection:
        try:
            with mcp_error_boundary():
                return await self._authorize_and_discover(browser)
        except OAuthCallbackError:
            raise
        except MCPRequestError as exc:
            raise SetupError(exc.code, exc.message) from exc

    async def _authorize_and_discover(self, browser: BrowserAuthorization) -> PreparedConnection:
        settings = self.settings
        await validated_address(httpx2.URL(settings["endpoint"]))
        storage = OAuthStorage()
        metadata = OAuthClientMetadata(
            client_name="omnideck", redirect_uris=[AnyUrl(browser.receiver.redirect_uri)],
            token_endpoint_auth_method="none", scope=settings.get("scopes") or None,
        )
        if settings.get("client_id"):
            if not settings.get("issuer"):
                raise ValueError("A preregistered client must name its authorization server.")
            await validated_address(httpx2.URL(settings["issuer"]))
            storage.client_info = OAuthClientInformationFull(
                **metadata.model_dump(), client_id=settings["client_id"], issuer=settings["issuer"],
            )

        async def redirect(url: str) -> None:
            await validated_address(httpx2.URL(url))
            browser.present(url)

        callback_error: OAuthCallbackError | None = None

        async def callback() -> AuthorizationCodeResult:
            nonlocal callback_error
            try:
                response = await browser.receiver.wait_for_result()
            except OAuthCallbackError as exc:
                # The SDK transport replaces callback exceptions on teardown.
                # Retain only our safe local outcome, never upstream error text.
                callback_error = exc
                raise
            return AuthorizationCodeResult(code=response.code, state=response.state, iss=response.iss)

        provider = PersistentOAuthProvider(
            server_url=settings["endpoint"], storage=storage, client_metadata=metadata,
            requested_scopes=settings.get("scopes") or None,
            redirect_handler=redirect, callback_handler=callback,
        )
        try:
            async with mcp_http_client(auth=provider, resource_endpoint=settings["endpoint"]) as http:
                async with Client(streamable_http_client(settings["endpoint"], http_client=http), cache=None) as client:
                    operations = await discover(client)
        except Exception:
            if callback_error is not None:
                raise callback_error
            raise
        storage.capture_metadata(provider)
        return PreparedConnection({
            "endpoint": settings["endpoint"],
            # Preserve the user's choice separately from SDK/provider metadata:
            # discovery and granted token scopes need not match requested scopes.
            "requested_scopes": settings.get("scopes", ""),
            "access_token": storage.tokens.access_token if storage.tokens else "",
            "oauth_state": storage.serialize(),
        }, operations)
