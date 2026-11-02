"""Broker-specific preparation cleans partial candidates and retires old clients."""

from unittest.mock import AsyncMock, Mock

import pytest

from brokering._control import CredentialRejected
from brokering._session_slot import BrokerSessionSlot
from brokering.brokers.email_broker import __main__ as email
from brokering.brokers.email_broker._imap_client import ImapClient
from brokering.brokers.email_broker._smtp_client import SmtpClient
from brokering.brokers.email_broker._caldav_client import CalDavClient

FIELDS = {
    "IMAP_HOST": "local", "IMAP_PORT": "993", "EMAIL_USER": "local", "EMAIL_PASS": "local",
    "SMTP_HOST": "local", "SMTP_PORT": "587", "CALDAV_URL": "https://local",
}


@pytest.mark.parametrize("service,error", [
    ("ImapClient", email.ImapAuthError("private")),
    ("SmtpClient", email.SmtpAuthError("private")),
    ("CalDavClient", email.CalDavAuthError("private")),
])
async def test_email_rejection_closes_partial_candidate_not_current(tmp_path, monkeypatch, service, error):
    old, new = {}, {}
    for name in ("ImapClient", "SmtpClient", "CalDavClient"):
        old[name] = Mock(connect=AsyncMock())
        new[name] = Mock(connect=AsyncMock())
        monkeypatch.setattr(email, name, Mock(side_effect=[old[name], new[name]]))
    slot = BrokerSessionSlot(lambda fields: email.create_session(fields, tmp_path))
    await (await slot.prepare(FIELDS)).activate()
    current = slot.current
    new[service].connect.side_effect = error
    with pytest.raises(CredentialRejected) as rejected:
        await slot.prepare(FIELDS)
    assert rejected.value.code == "AUTH"
    assert slot.current is current
    for name, client in new.items():
        if client.connect.await_count:
            client.close.assert_called_once()
    for client in old.values():
        client.close.assert_not_called()
    await slot.close()
    for client in old.values():
        client.close.assert_called_once()


@pytest.mark.parametrize("make,transport", [
    (lambda: ImapClient("local", 993, "local", "secret"), "_imap"),
    (lambda: SmtpClient("local", 587, "local", "secret"), "_smtp"),
    (lambda: CalDavClient(url="https://local", username="local", password="secret"), "_client"),
])
def test_retired_email_client_cannot_reauthenticate(make, transport):
    client = make()
    session = Mock()
    setattr(client, transport, session)
    client.close()
    with pytest.raises(RuntimeError, match="retired"):
        client._blocking_connect()
    (session.shutdown if transport == "_imap" else session.close).assert_called_once()
