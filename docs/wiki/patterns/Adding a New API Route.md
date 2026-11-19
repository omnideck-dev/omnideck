---
title: Adding a New API Route
type: pattern
tags: [server, http, api, extension]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "server/"
  - "server/aiohttp_app.py"
---

# Adding a New API Route

## Overview

Routes are grouped by feature domain into `server/_*_routes.py` modules. Each module exports a `register_*_routes(app)` function that mounts its routes on the aiohttp `Application`. The main factory (`create_app()`) calls each one. Re-verified against current `create_app()` — now 23 route modules (was 10 at the previous wiki pass), but the pattern itself is unchanged. See [[API Routes]] for the full current inventory.

## Where It's Used

`server/aiohttp_app.py:create_app()` — all `register_*_routes` calls are here.

## How to Extend This

### 1. Create (or find) the route module

For a new feature domain (e.g., analytics), create:
```
server/_analytics_routes.py
```

For an existing domain (e.g., adding a route to conversations), open `server/_conversation_routes.py`.

### 2. Write the handler

```python
# server/_analytics_routes.py
import logging
from aiohttp import web
from aiohttp.web_request import Request
from aiohttp.web_response import Response

logger = logging.getLogger(__name__)


async def get_analytics_handler(request: Request) -> Response:
    """Return usage analytics."""
    data = {"total_conversations": 42}
    return web.json_response(data)


def register_analytics_routes(app: web.Application) -> None:
    app.router.add_route("GET", "/api/analytics", get_analytics_handler)
```

Rules:
- Use `web.json_response(data)` for JSON — don't build the response manually.
- For mutating requests (POST/PUT/DELETE): the CSRF middleware requires `X-Requested-With: XMLHttpRequest`. The frontend already sends this on all `fetch` calls; external API consumers must add it.
- Parse request bodies with Pydantic: `payload = MyModel.model_validate_json(await request.text())`. `ValidationError` is caught by the CORS/error middleware and returns 400.
- Log at `INFO` level for normal operation; `WARNING` for expected error conditions; `EXCEPTION` for unexpected failures.

### 3. Register in `create_app()`

```python
# server/aiohttp_app.py
from server._analytics_routes import register_analytics_routes

def create_app(...) -> web.Application:
    ...
    register_analytics_routes(app)
    ...
```

### 4. Wire the frontend

If the route is called from the React UI, add the `fetch` call in the appropriate hook or component. All fetches should include `headers: { 'X-Requested-With': 'XMLHttpRequest' }` for POST/PUT/DELETE to pass the CSRF check.

## Deviations From Textbook Form

- CORS and CSRF are handled globally by `cors_and_error_middleware` — don't add them per-handler.
- aiohttp routes don't use class-based views — plain async functions only.
- `ValidationError` from Pydantic doesn't need a try/except in each handler — the middleware catches it.
- **The CSRF check's method set is `{POST, PUT, DELETE}` — it does not include `PATCH`.** Several existing routes (e.g. conversation/folder/provider updates) use PATCH and are therefore not CSRF-gated today. If you add a mutating PATCH route, treat this as a known gap rather than an intentional exemption — don't assume PATCH is protected the way POST/PUT/DELETE are.

## Related Entities

- [[API Routes]] — full route inventory
- [[App Startup]] — where `create_app()` is called
