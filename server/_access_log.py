"""Keep authorization responses and sign-in handles out of HTTP access logs."""

from aiohttp.web_log import AccessLogger
from aiohttp.web_request import BaseRequest
from aiohttp.web_response import StreamResponse


class SafeAccessLogger(AccessLogger):
    def log(self, request: BaseRequest, response: StreamResponse, time: float) -> None:
        if request.path.startswith(("/api/integrations/oauth/", "/api/integrations/mcp/oauth/")):
            self.logger.info("Integration authorization request completed (%s)", response.status)
            return
        super().log(request, response, time)
