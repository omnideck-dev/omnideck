---
target: app
type: security
area: api
---

PATCH requests to the API now require the same same-origin signal already
enforced on POST, PUT, and DELETE, closing a gap that left a few
state-changing endpoints (conversation and folder renames, provider and
integration updates) without CSRF protection.
