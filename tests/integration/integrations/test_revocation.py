"""HTTP grant edits update discovery and invalidate previously issued tools."""

from importlib import import_module

import pytest

from integrations import broker_client
from integrations.service import AGENT_CONTEXT, integration_service
from tools.integrations._tool_resolution import integration_tools_by_category

from .fixtures._catalog import make_fake_email_catalog
from .fixtures.fake_email import FakeEmail


async def test_revocation_removes_discovery_and_blocks_previously_usable_operation(integration_app, monkeypatch):
    fake = FakeEmail()
    await fake.start()
    try:
        async with integration_app(make_fake_email_catalog(fake)) as h:
            monkeypatch.setattr(import_module("tools.integrations.list_email_folders"), "load_config", lambda: h.config)
            response = await h.client.post(
                "/api/integrations",
                json={
                    "slug": "icloud",
                    "label": "Local email",
                    "auth_blob": {"email": fake.user, "password": fake.password},
                    "operation_grants": ["email.mailboxes.list"],
                },
            )
            assert response.status == 201, await response.text()
            record = await response.json()
            iid = record["id"]
            categories = await integration_tools_by_category()
            old_tools = categories["email"].tools
            assert [tool.__name__ for tool in old_tools] == ["list_email_folders"]
            assert "INBOX" in await old_tools[0](integration_id=iid)

            saved = await h.client.patch(f"/api/integrations/{iid}", json={"operation_grants": []})
            assert saved.status == 200, await saved.text()
            categories = await integration_tools_by_category()
            assert categories["email"].tools == []
            assert categories["email"].available is False
            with pytest.raises(broker_client.IntegrationPermissionDenied):
                await integration_service.invoke(
                    AGENT_CONTEXT,
                    iid,
                    "email.mailboxes.list",
                    {},
                    app_sock_path=h.supervisor.app_sock_path,
                )
            # A tool retained by an in-flight agent is still gated by the broker.
            assert "not granted" in await old_tools[0](integration_id=iid)
    finally:
        await fake.stop()
