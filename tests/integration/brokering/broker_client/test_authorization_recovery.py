"""Real broker RPC -> supervisor renewal -> existing tool -> agent guidance."""

import pytest

from agent_core.tools._helpers import _execute_tool_call
from brokering._rpc import RpcError, serve_rpc
from brokering.broker_client._call import call
from tools.integrations.send_email import send_email


@pytest.mark.parametrize('renewal', ['renewed', 'newer', 'failed'])
async def test_auth_recovery_reaches_existing_email_tool_without_replay(tmp_path, monkeypatch, renewal):
    calls = []
    renewals = []
    async def broker(verb, args):
        calls.append(verb)
        raise RpcError('AUTH', 'Access token rejected')
    async def supervisor(verb, args):
        if verb == 'resolve':
            return {'socket': str(tmp_path/'broker.sock'), 'authorization_generation': 'generation'}
        assert verb == 'renew_authorization'
        renewals.append(args)
        if renewal == 'failed':
            raise RpcError('AUTH', 'private token response')
        return {'renewed': renewal == 'renewed'}
    broker_server = await serve_rpc(tmp_path/'broker.sock', broker)
    sup_server = await serve_rpc(tmp_path/'app.sock', supervisor)
    async with broker_server, sup_server:
        async def invoke(connection_id, operation_id, args, *, app_sock_path):
            return await call(connection_id, operation_id, args, app_sock_path=tmp_path/'app.sock')
        monkeypatch.setattr('brokering.broker_client.call', invoke)
        result = await _execute_tool_call('send_email', {'integration_id': 'google', 'to': 'a@example.test', 'subject': 'test', 'body': 'test'}, [send_email])
    assert calls == ['email.messages.send']
    assert renewals == [{'id': 'google', 'generation': 'generation'}]
    assert 'The operation was not retried' in result
    assert 'Check the service before retrying' in result
    assert 'private token response' not in result
    expected = {'renewed': 'Authorization was renewed.', 'newer': 'Newer authorization is already available.', 'failed': 'Authorization could not be renewed.'}[renewal]
    assert expected in result


@pytest.mark.parametrize('code', ['PERMISSION_DENIED', 'UPSTREAM'])
async def test_non_auth_failures_never_trigger_renewal(tmp_path, code):
    verbs = []
    async def broker(verb, args):
        raise RpcError(code, 'failure')
    async def supervisor(verb, args):
        verbs.append(verb)
        return {'socket': str(tmp_path/'broker.sock'), 'authorization_generation': 'generation'}
    a = await serve_rpc(tmp_path/'broker.sock', broker)
    b = await serve_rpc(tmp_path/'app.sock', supervisor)
    from brokering.broker_client import IntegrationError
    async with a, b:
        with pytest.raises(IntegrationError):
            await call('google', 'email.messages.send', {}, app_sock_path=tmp_path/'app.sock')
    assert verbs == ['resolve']
