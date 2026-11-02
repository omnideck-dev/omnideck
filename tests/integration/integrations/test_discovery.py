"""Real supervisor polling and skill resolution share immutable run snapshots."""

import asyncio

from agent_core.events import agent_span
from agent_runtime._factory import AgentFactory
from agents import AgentProfile
from brokering import supervisor_client
from skills._store import SkillRecord, save_skill_record
from skills._tools import load_skill

from .fixtures._catalog import make_fake_email_catalog
from .fixtures.fake_email import FakeEmail


async def test_existing_and_dynamic_skills_keep_snapshot_after_http_grant_edit(
    integration_app, monkeypatch, tmp_path,
):
    monkeypatch.setattr("skills._store._skills_dir", lambda: tmp_path / "skills")
    save_skill_record(SkillRecord(id="mail", name="Mail", tool_categories=["email"]))
    fake = FakeEmail()
    await fake.start()
    try:
        async with integration_app(make_fake_email_catalog(fake)) as h:
            response = await h.client.post("/api/integrations", json={
                "slug": "icloud", "label": "Local", "auth_blob": {
                    "email": fake.user, "password": fake.password,
                }, "operation_grants": ["email.mailboxes.list"],
            })
            assert response.status == 201, await response.text()
            connection_id = (await response.json())["id"]
            snapshot = h.cache.snapshot()
            factory = AgentFactory()
            profile = AgentProfile(id="test", name="Test", model="test", skills=["mail"])

            async def spawn_agent():
                raise AssertionError("No children should run in this test")

            initial = await factory.build_capabilities(
                profile, spawn_agent=spawn_agent, connections=snapshot,
            )
            dynamic = await factory.build_capabilities(
                profile.model_copy(update={"skills": []}),
                spawn_agent=spawn_agent, connections=snapshot,
            )
            assert "list_email_folders" in {t.__name__ for t in initial.tools}
            response = await h.client.patch(
                f"/api/integrations/{connection_id}", json={"operation_grants": []},
            )
            assert response.status == 200, await response.text()
            assert h.cache.snapshot()[0].operation_grants == frozenset()
            async with agent_span("test", agent_capabilities=dynamic):
                assert "Loaded skill" in await load_skill("Mail")
            assert "list_email_folders" in {t.__name__ for t in dynamic.tools}
            assert "list_email_folders" in {t.__name__ for t in initial.tools}

            next_run = await factory.build_capabilities(
                profile, spawn_agent=spawn_agent, connections=h.cache.snapshot(),
            )
            assert "list_email_folders" not in {t.__name__ for t in next_run.tools}

            response = await h.client.delete(f"/api/integrations/{connection_id}")
            assert response.status == 204
            assert h.cache.snapshot() == ()
    finally:
        await fake.stop()


async def test_background_poll_observes_supervisor_changes_without_http_or_agent_reads(integration_app):
    fake = FakeEmail()
    await fake.start()
    try:
        async with integration_app(make_fake_email_catalog(fake)) as h:
            response = await h.client.post("/api/integrations", json={
                "slug": "icloud", "label": "Local", "auth_blob": {
                    "email": fake.user, "password": fake.password,
                }, "operation_grants": ["email.mailboxes.list"],
            })
            assert response.status == 201, await response.text()
            connection_id = (await response.json())["id"]
            before = h.cache.snapshot()
            # Bypass the app routes: only periodic discovery can observe this.
            await supervisor_client.call(
                "remove", {"id": connection_id}, app_sock_path=h.supervisor.app_sock_path,
            )
            async with asyncio.timeout(2):
                while h.cache.snapshot():
                    await asyncio.sleep(.01)
            assert before[0].id == connection_id
            assert h.cache.available
    finally:
        await fake.stop()
