"""Real HTTP routes, supervisor, vault, and broker processes on local transports."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from config import load_config
from integrations import service
from brokering.supervisor._lifecycle import Supervisor
from server import _brokering, _integrations_oauth_routes, _integrations_routes, _oauth
from integrations.connection_cache import IntegrationConnectionCache
from server._integration_cache import INTEGRATION_CACHE_KEY

from .fixtures._host_paths import make_host_paths


@pytest.fixture
def integration_app(tmp_path_factory, monkeypatch):
    @asynccontextmanager
    async def start(catalog):
        # Short paths keep Unix socket names below the platform's length limit.
        root = tmp_path_factory.mktemp("integrations")
        config = load_config().model_copy(deep=True)
        config.integrations.app_sock_path = str(root / "app.sock")
        config.integrations.sockets_dir = str(root / "s")
        for module in (_brokering, _integrations_oauth_routes, service):
            monkeypatch.setattr(module, "load_config", lambda: config)
        monkeypatch.setattr(_integrations_oauth_routes, "_oauth", _oauth.OAuthIntegrationManager())
        public_catalog = {key: entry for key, entry in catalog.items() if entry.kind == "integration"}
        for module in (_integrations_routes, _integrations_oauth_routes):
            monkeypatch.setattr(module, "integration_catalog", lambda: public_catalog)
        supervisor = Supervisor(
            vault_dir=root / "vault",
            app_sock_path=root / "app.sock",
            sockets_dir=root / "s",
            host_paths=make_host_paths(root),
            catalog=catalog,
        )
        await supervisor.start()
        app = web.Application()
        cache = IntegrationConnectionCache(service.integration_service, poll_interval=.05)
        app[INTEGRATION_CACHE_KEY] = cache
        cache.start()
        _integrations_oauth_routes.register_oauth_routes(app)
        _integrations_routes.register_integrations_routes(app)
        try:
            async with TestClient(TestServer(app)) as client:
                yield SimpleNamespace(client=client, supervisor=supervisor, config=config, cache=cache)
        finally:
            await cache.close()
            await supervisor.stop()

    return start
