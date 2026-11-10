"""HTTP grant edits update discovery and invalidate previously issued tools."""

from importlib import import_module

import pytest

from brokering import broker_client
from integrations.service import integration_service
from skills._tool_categories import tool_categories

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
            run_snapshot = h.cache.snapshot()
            category_id = f"integration:{iid}"
            categories = await tool_categories(run_snapshot)
            old_tools = categories[category_id].tools
            assert len(old_tools) == 1
            assert old_tools[0].__name__.startswith("list_email_folders_")
            assert "integration_id" not in old_tools[0].definition()["function"]["parameters"]["properties"]
            assert "INBOX" in await old_tools[0]()
            with pytest.raises(ValueError, match="routing cannot be overridden"):
                await old_tools[0](integration_id="another-account")

            saved = await h.client.patch(f"/api/integrations/{iid}", json={"operation_grants": []})
            assert saved.status == 200, await saved.text()
            categories = await tool_categories(h.cache.snapshot())
            assert categories[category_id].tools == []
            assert (await tool_categories(run_snapshot))[category_id].tools
            with pytest.raises(broker_client.IntegrationPermissionDenied):
                await integration_service.invoke(
                    iid,
                    "email.mailboxes.list",
                    {},
                    app_sock_path=h.supervisor.app_sock_path,
                )
            # A tool retained by an in-flight agent is still gated by the broker.
            assert "not granted" in await old_tools[0]()
    finally:
        await fake.stop()
