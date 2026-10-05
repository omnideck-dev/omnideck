"""SDK OAuth storage adapter; callers own browser UI and encrypted persistence.

The app uses an in-memory instance during explicit setup. The supervisor uses
the same serialized state for non-interactive refresh, persisting a rotated
token before any subsequent network request or broker activation can fail.
"""

import json
import math
import time
from collections.abc import Callable
from typing import Any

import httpx2

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken, ProtectedResourceMetadata


class OAuthStorage:
    """A short-lived, deliberately non-repr-able SDK credential container."""

    def __init__(self, raw: str = "", *, persist: Callable[[str, str], None] | None = None) -> None:
        value = json.loads(raw) if raw else {}
        if not isinstance(value, dict):
            raise ValueError("Invalid saved authorization")
        self.tokens = OAuthToken.model_validate(value["tokens"]) if value.get("tokens") else None
        self.client_info = OAuthClientInformationFull.model_validate(value["client"]) if value.get("client") else None
        self.metadata = OAuthMetadata.model_validate(value["metadata"]) if value.get("metadata") else None
        self.resource = ProtectedResourceMetadata.model_validate(value["resource"]) if value.get("resource") else None
        self.expires_at = value.get("expires_at")
        if self.expires_at is not None and (
            isinstance(self.expires_at, bool) or not isinstance(self.expires_at, (int, float))
            or not math.isfinite(self.expires_at)
        ):
            raise ValueError("Invalid saved token expiry")
        if self.metadata and (not self.client_info or self.client_info.issuer != str(self.metadata.issuer)):
            raise ValueError("Saved authorization issuer does not match registration")
        self._persist = persist

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens
        self.expires_at = time.time() + tokens.expires_in if tokens.expires_in is not None else None
        if self._persist is not None:
            self._persist(self.serialize(), tokens.access_token)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info

    def capture_metadata(self, provider: OAuthClientProvider) -> None:
        self.metadata = provider.context.oauth_metadata
        self.resource = provider.context.protected_resource_metadata

    def serialize(self) -> str:
        return json.dumps({
            "tokens": self.tokens.model_dump(mode="json") if self.tokens else None,
            "client": self.client_info.model_dump(mode="json") if self.client_info else None,
            "metadata": self.metadata.model_dump(mode="json") if self.metadata else None,
            "resource": self.resource.model_dump(mode="json") if self.resource else None,
            "expires_at": self.expires_at,
        })

    def needs_refresh(self) -> bool:
        # A fixed 60-second window would reject legitimately short-lived tokens
        # immediately after refreshing them. Bound skew to 10% of their lifetime.
        lifetime = self.tokens.expires_in if self.tokens else None
        margin = min(60, max(0, lifetime or 0) * 0.1)
        return self.expires_at is not None and time.time() >= self.expires_at - margin


class PersistentOAuthProvider(OAuthClientProvider):
    """Restore absolute expiry and verified discovery across process restarts.

    SDK 2.2 loads tokens but not expiry/discovery. Keep this version-specific
    adaptation in one place, covered by real HTTP restart/rotation tests. The
    SDK still owns the refresh request, token response and registration logic.
    """

    def __init__(self, *, storage: OAuthStorage, requested_scopes: str | None = None, **kwargs: Any) -> None:
        super().__init__(storage=storage, **kwargs)
        self._saved = storage
        self._requested_scopes = requested_scopes

    async def _perform_authorization(self) -> httpx2.Request:
        # SDK discovery replaces client_metadata.scope with the server's
        # advertised scopes. An explicitly selected scope set is a ceiling,
        # not permission to silently request everything advertised by a server.
        if self._requested_scopes is not None:
            self.context.client_metadata.scope = self._requested_scopes
        return await super()._perform_authorization()

    async def _initialize(self) -> None:
        await super()._initialize()
        self.context.token_expiry_time = self._saved.expires_at
        if self._saved.needs_refresh():
            self.context.token_expiry_time = time.time() - 1
        self.context.oauth_metadata = self._saved.metadata
        self.context.protected_resource_metadata = self._saved.resource
        if self._saved.metadata is not None:
            self.context.auth_server_url = str(self._saved.metadata.issuer)
