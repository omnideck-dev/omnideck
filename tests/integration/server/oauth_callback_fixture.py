"""A real loopback listener for shared OAuth callback integration tests."""
import math
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from aiohttp import web
from server.oauth_setup.callback import OAuthCallback
from server.oauth_setup.routes import receive_callback

CALLBACK_PATH = "/api/integrations/mcp/oauth/callback"

@asynccontextmanager
async def listen_for_oauth(*, port: int = 0, timeout: float = 600) -> AsyncIterator[OAuthCallback]:
    """Bind a host-local listener for one explicitly initiated setup attempt.

    Port zero is useful for tests/providers accepting ephemeral loopback ports.
    Pre-registered clients such as Slack supply their configured fixed port.
    An occupied port fails; it never silently changes the registered redirect.
    The owner must close the context when setup ends or is cancelled.
    """
    if not 0 <= port <= 65535 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("A valid loopback port and positive finite timeout are required.")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))
        sock.setblocking(False)
        callback = OAuthCallback(redirect_uri=f"http://localhost:{sock.getsockname()[1]}{CALLBACK_PATH}", timeout=timeout)
        app = web.Application(client_max_size=1024)
        async def handle(request):
            return receive_callback(callback, request)
        app.router.add_get(CALLBACK_PATH, handle, allow_head=False)
        # aiohttp's default access log includes the query (code and state).
        # This dedicated app must never enable it or inherit the main app's log.
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=1)
        try:
            await runner.setup()
            await web.SockSite(runner, sock).start()
            yield callback
        finally:
            callback.cancel()
            await runner.cleanup()
