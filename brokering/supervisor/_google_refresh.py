"""Google token renewal and rotation persistence, owned by the supervisor."""

import math
import time
from collections.abc import Callable

import aiohttp

from brokering.connection_data import BrokerConnectionData


_TOKEN_ENDPOINTS = {"https://oauth2.googleapis.com/token", "https://www.googleapis.com/oauth2/v4/token"}


async def refresh_google_authorization(
    fields: BrokerConnectionData, persist: Callable[[BrokerConnectionData], None], *, force: bool,
) -> BrokerConnectionData:
    expiry = float(fields["expires_at"])
    lifetime = float(fields.get("expires_in", "600"))
    if not math.isfinite(expiry) or not math.isfinite(lifetime) or lifetime < 0:
        raise ValueError("Invalid saved token expiry")
    if not force and (expiry == 0 or time.time() < expiry - min(60, lifetime * 0.1)):
        return fields
    # Google is a fixed provider. Never send its refresh/client secrets to an
    # arbitrary token URI supplied in saved connection data.
    if fields["token_uri"] not in _TOKEN_ENDPOINTS:
        raise ValueError("Unsupported Google token endpoint; sign in again.")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), trust_env=False) as http:
        async with http.post(fields["token_uri"], allow_redirects=False, data={
            "grant_type": "refresh_token", "refresh_token": fields["refresh_token"],
            "client_id": fields["client_id"], "client_secret": fields["client_secret"],
        }) as response:
            if response.status != 200:
                raise ValueError("Google could not renew authorization. Reconnect in Settings.")
            token = await response.json()
            result = _rotated_fields(fields, token)
            persist(result)
            return result


def _rotated_fields(fields: BrokerConnectionData, token: object) -> BrokerConnectionData:
    if not isinstance(token, dict) or not isinstance(token.get("access_token"), str) or not token["access_token"]:
        raise ValueError("Invalid Google token response")
    lifetime = token.get("expires_in")
    if lifetime is not None and (isinstance(lifetime, bool) or not isinstance(lifetime, (int, float)) or not math.isfinite(lifetime) or lifetime <= 0):
        raise ValueError("Invalid Google token lifetime")
    refresh_token = token.get("refresh_token", fields["refresh_token"])
    if not isinstance(refresh_token, str) or not refresh_token:
        raise ValueError("Invalid Google refresh token")
    result = BrokerConnectionData({
        **fields, "access_token": token["access_token"], "refresh_token": refresh_token,
        "expires_at": str(time.time() + lifetime if lifetime is not None else 0),
        "expires_in": str(lifetime or 0),
    })
    return result
