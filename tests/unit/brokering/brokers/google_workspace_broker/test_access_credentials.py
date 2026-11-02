"""Google brokers get access-only credentials and never renew or replay calls."""

from unittest.mock import Mock

import httplib2
import pytest
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.errors import HttpError

from brokering._rpc import RpcError
from brokering.brokers.google_workspace_broker.__main__ import create_session
from brokering.brokers.google_workspace_broker._verbs import _wrap_http_error
from brokering.connection_data import BrokerConnectionData
from brokering.supervisor._spawn import connection_fields
from integrations.catalog._defaults import _GOOGLE_WORKSPACE


async def test_google_401_returns_to_supervisor_without_broker_refresh_or_replay(tmp_path):
    async with create_session({'OAUTH_ACCESS_TOKEN': 'access', 'OAUTH_SCOPES': 'https://www.googleapis.com/auth/gmail.modify'}, tmp_path) as dispatcher:
        creds = dispatcher._creds
        assert creds.refresh_token is creds.client_secret is creds.client_id is None
        http = Mock(request=Mock(return_value=(httplib2.Response({'status': '401'}), b'{}')))
        transport = AuthorizedHttp(creds, http=http)
        dispatcher._gmail.send_message = lambda *args: transport.request('https://gmail.googleapis.com/send', method='POST', body='message')
        dispatcher.replace_operation_grants(frozenset({'email.messages.send'}))
        with pytest.raises(RpcError) as error:
            await dispatcher.dispatch('email.messages.send', {'to': ['a@example.test'], 'subject': 'test', 'body': 'test'})
        assert error.value.code == 'AUTH'
        assert http.request.call_count == 1


def test_google_403_does_not_request_token_renewal():
    error = _wrap_http_error(HttpError(httplib2.Response({'status': '403'}), b'{"error":{"message":"private response"}}'))
    assert error.code != 'AUTH'
    assert 'Check provider permissions' in error.message
    assert 'private response' not in error.message


def test_google_child_fields_exclude_refresh_and_client_secrets():
    fields = connection_fields(_GOOGLE_WORKSPACE, BrokerConnectionData({
        'access_token': 'access', 'scopes': 'scope', 'refresh_token': 'refresh',
        'client_id': 'client', 'client_secret': 'secret', 'expires_at': '123', 'token_uri': 'https://oauth2.googleapis.com/token',
    }))
    assert fields == {'OAUTH_ACCESS_TOKEN': 'access', 'OAUTH_SCOPES': 'scope'}
