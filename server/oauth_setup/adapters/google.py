"""Google protocol adapter; setup lifetime and persistence belong to the coordinator."""

import asyncio
import os
import secrets
from dataclasses import dataclass
from datetime import UTC

from google_auth_oauthlib.flow import Flow
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

from brokering.connection_data import BrokerConnectionData
from ..models import BrowserAuthorization, PreparedConnection, SetupError

# Google's expanded scope URIs differ from requested shorthand aliases.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


@dataclass(repr=False)
class GoogleOAuthAdapter:
    client_id: str
    client_secret: str
    scopes: list[str]

    async def prepare(self, browser: BrowserAuthorization) -> PreparedConnection:
        if not self.client_id or not self.client_secret or not self.scopes:
            raise SetupError("BAD_REQUEST", "Client credentials and provider access are required.")
        flow = Flow.from_client_config({"installed": {
            "client_id": self.client_id, "client_secret": self.client_secret,
            "auth_uri": _AUTH_URI, "token_uri": _TOKEN_URI,
            "redirect_uris": [browser.receiver.redirect_uri],
        }}, scopes=list(self.scopes), autogenerate_code_verifier=True)
        flow.redirect_uri = browser.receiver.redirect_uri
        url, _ = flow.authorization_url(
            access_type="offline", include_granted_scopes="true", prompt="consent",
            state=secrets.token_urlsafe(32),
        )
        browser.present(url)
        response = await browser.receiver.wait_for_result()
        try:
            # requests has its own network timeout: cancelling to_thread cannot
            # stop the worker, but the cancelled adapter can never commit it.
            async with asyncio.timeout(60):
                await asyncio.to_thread(flow.fetch_token, code=response.code, timeout=30)
            return PreparedConnection(dict(build_auth_blob(flow, fallback_scopes=self.scopes)))
        except TimeoutError as exc:
            raise SetupError("UPSTREAM", "The provider took too long to complete authorization.") from exc
        except OAuth2Error as exc:
            raise SetupError("AUTH", "The provider could not complete sign-in. Try again.") from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise SetupError("AUTH", "The provider did not return reusable credentials. Try authorizing again.") from exc


def build_auth_blob(flow: Flow, *, fallback_scopes: list[str]) -> BrokerConnectionData:
    """Convert ``Credentials`` to the auth_blob shape the supervisor's ``add`` verb expects."""
    creds = flow.credentials
    # google-auth commonly returns a naive UTC datetime but can also
    # provide an aware value. Normalize both without changing the instant.
    expiry = creds.expiry
    if expiry is not None:
        expiry = (
            expiry.replace(tzinfo=UTC)
            if expiry.tzinfo is None
            else expiry.astimezone(UTC)
        )
    expires_at = (
        int(expiry.timestamp())
        if expiry is not None else 0
    )
    # google-auth keeps requested scopes in ``scopes`` and the token
    # endpoint's actual consent result in ``granted_scopes``. Only fall
    # back when that result is absent, never when it is explicitly empty.
    granted_scopes = getattr(creds, "granted_scopes", None)
    scopes = granted_scopes if granted_scopes is not None else (creds.scopes or fallback_scopes)
    scopes_str = scopes if isinstance(scopes, str) else " ".join(scopes)
    auth_blob = {
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "scopes": scopes_str,
        "expires_at": str(expires_at),
    }
    missing = [
        key
        for key, value in auth_blob.items()
        if not isinstance(value, str) or not value
    ]
    if missing:
        raise ValueError(
            f"token response missing string fields: {', '.join(sorted(missing))}",
        )
    return BrokerConnectionData.from_wire(auth_blob)
