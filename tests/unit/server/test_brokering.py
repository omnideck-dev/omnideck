"""Connection management uses one neutral server-side client contract."""

from types import SimpleNamespace

from server import _brokering, _integrations_oauth_routes, _integrations_routes, _provider_routes


async def test_supervisor_call_preserves_config_and_rollback_timeout(monkeypatch):
    config = SimpleNamespace(integrations=SimpleNamespace(app_sock_path="/test/app.sock"))
    monkeypatch.setattr(_brokering, "load_config", lambda: config)
    calls = []

    async def call(verb, args, *, app_sock_path):
        calls.append((verb, args, app_sock_path))
        return {"id": "llm_openai"}

    async def wait_for(awaitable, *, timeout):
        assert timeout == 90.0
        return await awaitable

    monkeypatch.setattr(_brokering.supervisor_client, "call", call)
    monkeypatch.setattr(_brokering.asyncio, "wait_for", wait_for)
    args = {"slug": "llm_openai"}
    assert await _brokering.supervisor_call("add", args) == {"id": "llm_openai"}
    assert calls == [("add", args, "/test/app.sock")]


def test_route_families_use_neutral_connection_client():
    for module in (_integrations_routes, _integrations_oauth_routes, _provider_routes):
        assert module._supervisor_call is _brokering.supervisor_call
