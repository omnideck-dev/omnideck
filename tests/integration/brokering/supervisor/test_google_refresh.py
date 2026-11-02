"""Google renewal uses real HTTP and persists rotation before broker handoff."""

import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from brokering.connection_data import BrokerConnectionData
from brokering.supervisor import _google_refresh


@pytest.mark.parametrize("expiry", [None, 5, 3600])
@pytest.mark.parametrize("rotate", [False, True])
async def test_google_refresh_persists_rotation_and_optional_expiry(monkeypatch, expiry, rotate):
    requests = []

    async def token(request):
        requests.append(dict(await request.post()))
        result = {"access_token": "new-access", "token_type": "Bearer"}
        if expiry is not None:
            result["expires_in"] = expiry
        if rotate:
            result["refresh_token"] = "new-refresh"
        return web.json_response(result)

    app = web.Application()
    app.router.add_post('/token', token)
    async with TestServer(app) as server:
        endpoint = str(server.make_url('/token'))
        monkeypatch.setattr(_google_refresh, '_TOKEN_ENDPOINTS', {endpoint})
        fields = BrokerConnectionData({
            "access_token": "old-access", "refresh_token": "old-refresh", "client_id": "client",
            "client_secret": "secret", "token_uri": endpoint, "scopes": "scope", "expires_at": "1",
        })
        saved = []
        result = await _google_refresh.refresh_google_authorization(fields, saved.append, force=False)
        assert saved == [result]
        assert result['access_token'] == 'new-access'
        assert result['refresh_token'] == ('new-refresh' if rotate else 'old-refresh')
        assert result['scopes'] == 'scope'
        assert (float(result['expires_at']) > time.time()) if expiry else result['expires_at'] == '0'
        assert await _google_refresh.refresh_google_authorization(result, saved.append, force=False) is result
        assert len(requests) == 1
        await _google_refresh.refresh_google_authorization(result, saved.append, force=True)
        assert len(requests) == 2
        assert requests[1]['refresh_token'] == result['refresh_token']
        assert requests[0] == {'grant_type': 'refresh_token', 'refresh_token': 'old-refresh', 'client_id': 'client', 'client_secret': 'secret'}


async def test_google_refresh_rejects_untrusted_endpoint_without_sending_credentials():
    fields = BrokerConnectionData({'expires_at': '1', 'token_uri': 'https://attacker.example/token'})
    saved = []
    with pytest.raises(ValueError, match='Unsupported Google'):
        await _google_refresh.refresh_google_authorization(fields, saved.append, force=True)
    assert saved == []


@pytest.mark.parametrize('status,payload', [(400, {'error': 'invalid_grant', 'secret': 'never echo'}), (200, {'access_token': 'new', 'expires_in': -1})])
async def test_google_refresh_failure_does_not_persist_or_expose_response(monkeypatch, status, payload):
    async def token(request):
        return web.json_response(payload, status=status)
    app = web.Application()
    app.router.add_post('/token', token)
    async with TestServer(app) as server:
        endpoint = str(server.make_url('/token'))
        monkeypatch.setattr(_google_refresh, '_TOKEN_ENDPOINTS', {endpoint})
        fields = BrokerConnectionData({'expires_at': '1', 'token_uri': endpoint, 'refresh_token': 'old', 'client_id': 'id', 'client_secret': 'secret'})
        saved = []
        with pytest.raises(ValueError) as error:
            await _google_refresh.refresh_google_authorization(fields, saved.append, force=True)
        assert 'never echo' not in str(error.value)
        assert saved == []


async def test_google_supervisor_rotates_vault_and_live_access_only_broker(monkeypatch, tmp_path):
    import asyncio
    from brokering.supervisor._lifecycle import Supervisor
    from brokering.supervisor._store import read_secrets, write_secrets
    from integrations.catalog._defaults import _GOOGLE_WORKSPACE
    from tests.integration.integrations.fixtures._host_paths import make_host_paths
    from tests.integration.brokering.supervisor.test_supervisor import _rpc_call

    requests = []
    async def token(request):
        fields = dict(await request.post())
        requests.append(fields)
        return web.json_response({'access_token': f'access-{len(requests)}', 'refresh_token': f'refresh-{len(requests)}', 'expires_in': 3600})
    app = web.Application()
    app.router.add_post('/token', token)
    async with TestServer(app) as server:
        endpoint = str(server.make_url('/token'))
        monkeypatch.setattr(_google_refresh, '_TOKEN_ENDPOINTS', {endpoint})
        sup = Supervisor(vault_dir=tmp_path/'vault', app_sock_path=tmp_path/'app.sock', sockets_dir=tmp_path/'sockets',
                         host_paths=make_host_paths(tmp_path), catalog={'google_workspace': _GOOGLE_WORKSPACE})
        await sup.start()
        try:
            added = await _rpc_call(sup.app_sock_path, 'add', {
                'slug': 'google_workspace', 'label': 'Fixture', 'operation_grants': ['email.messages.send'],
                'auth_blob': {'access_token': 'old', 'refresh_token': 'refresh-0', 'client_id': 'id', 'client_secret': 'never-in-broker',
                              'token_uri': endpoint, 'expires_at': '1', 'scopes': 'https://www.googleapis.com/auth/gmail.modify'},
            })
            assert 'result' in added, added
            record = sup._registry.get('google_workspace')
            pid = record.broker.proc.pid
            from pathlib import Path
            env = Path(f'/proc/{pid}/environ').read_bytes()
            assert b'OAUTH_REFRESH_TOKEN=' not in env
            assert b'OAUTH_CLIENT_SECRET=' not in env
            assert b'never-in-broker' not in env
            initial = (await _rpc_call(sup.app_sock_path, 'resolve', {'id': 'google_workspace'}))['result']
            assert len(requests) == 1
            saved = read_secrets(sup.vault_dir, 'google_workspace', sup._manager._master_key)
            assert saved['refresh_token'] == 'refresh-1'
            write_secrets(sup.vault_dir, 'google_workspace', sup._manager._master_key, BrokerConnectionData({**saved, 'expires_at': '1'}))
            fresh = (await _rpc_call(sup.app_sock_path, 'resolve', {'id': 'google_workspace'}))['result']
            assert fresh['authorization_generation'] != initial['authorization_generation']
            assert record.broker.proc.pid == pid
            assert len(requests) == 2
            renewals = await asyncio.gather(*(_rpc_call(sup.app_sock_path, 'renew_authorization', {
                'id': 'google_workspace', 'generation': fresh['authorization_generation'],
            }) for _ in range(4)))
            assert sum(result['result']['renewed'] for result in renewals) == 1
            assert len(requests) == 3
            saved = read_secrets(sup.vault_dir, 'google_workspace', sup._manager._master_key)
            assert saved['refresh_token'] == 'refresh-3'
            assert [r['refresh_token'] for r in requests] == ['refresh-0', 'refresh-1', 'refresh-2']
            assert record.meta.agent_operation_grants == frozenset({'email.messages.send'})
            await sup.stop()
            await sup.start()
            restarted = await _rpc_call(sup.app_sock_path, 'resolve', {'id': 'google_workspace'})
            assert 'result' in restarted
            assert len(requests) == 3
        finally:
            await sup.stop()
