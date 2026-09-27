"""Connection data stays typed; catalogs receive only scope metadata."""

import json

import pytest

from brokering.connection_data import BrokerConnectionData


def test_auth_data_copies_fields_and_redacts_representation():
    fields = {"token": "secret-value", "custom_header": "custom-value"}
    auth = BrokerConnectionData(fields)
    fields["token"] = "changed"
    assert auth["token"] == "secret-value"
    assert "secret-value" not in repr(auth)
    assert "custom-value" not in str(auth)
    with pytest.raises(TypeError):
        auth["token"] = "changed"
    # JSON serialization is explicit at the existing wire/storage boundary.
    assert json.loads(json.dumps(dict(auth))) == {
        "token": "secret-value", "custom_header": "custom-value",
    }


@pytest.mark.parametrize("scopes", [" scope-a  scope-b scope-a ", ["scope-a", "scope-b", "scope-a"]])
def test_granted_scopes_are_normalized_without_exposing_credentials(scopes):
    auth = BrokerConnectionData.from_wire({"access_token": "secret-value", "scopes": scopes})
    assert auth.granted_scopes == frozenset({"scope-a", "scope-b"})
    assert all(isinstance(value, str) for value in auth.values())


def test_missing_and_empty_scopes_grant_nothing():
    assert BrokerConnectionData({"token": "secret-value"}).granted_scopes == frozenset()
    assert BrokerConnectionData({"scopes": ""}).granted_scopes == frozenset()


@pytest.mark.parametrize("value", [None, [], {1: "secret-value"}, {"token": None}, {"token": 42}, {"scopes": ["scope-a", 42]}])
def test_invalid_authentication_data_is_rejected_without_values(value):
    with pytest.raises(ValueError) as caught:
        BrokerConnectionData.from_wire(value)
    assert "secret-value" not in str(caught.value)
