"""Server composition key for application-owned integration discovery."""

from aiohttp import web

from integrations.connection_cache import IntegrationConnectionCache

INTEGRATION_CACHE_KEY = web.AppKey("integration_connection_cache", IntegrationConnectionCache)
