"""Only the resource request's explicit token rejection triggers renewal."""

from unittest.mock import AsyncMock

import httpx2
import pytest

from brokering.mcp_protocol import MCPRequestError
from brokering.mcp_protocol._network import MCPTransport


@pytest.mark.parametrize('method,status,challenge,renew', [
    ('POST', 401, 'Bearer error="invalid_token"', True),
    ('GET', 401, 'Bearer error="invalid_token"', False),
    ('POST', 403, 'Bearer error="insufficient_scope"', False),
    ('POST', 401, '', False),
    ('POST', 200, '', False),
])
async def test_mcp_renewal_signal_requires_resource_post_rejection(monkeypatch, method, status, challenge, renew):
    monkeypatch.setattr('brokering.mcp_protocol._network.validated_address', AsyncMock(return_value='203.0.113.1'))
    endpoint = 'https://mcp.example/mcp'
    transport = MCPTransport(resource_endpoint=endpoint)
    await transport._transport.aclose()
    transport._transport = httpx2.MockTransport(lambda request: httpx2.Response(status, headers={'WWW-Authenticate': challenge}, json={'error': 'unauthorized'}))
    try:
        request = httpx2.Request(method, endpoint, headers={'Authorization': 'Bearer access'})
        if renew:
            with pytest.raises(MCPRequestError) as error:
                await transport.handle_async_request(request)
            assert error.value.code == 'AUTH'
        else:
            response = await transport.handle_async_request(request)
            assert response.status_code == status
            await response.aclose()
    finally:
        await transport.aclose()
