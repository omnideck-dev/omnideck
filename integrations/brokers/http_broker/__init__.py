"""Generic HTTP integration broker.

One process per configured integration. Each instance is scoped to a single
``BASE_URL`` and attaches a static token to every outbound request. Acts as a
narrow proxy: the agent tool asks for ``http_request(method, path, ...)`` over
the UDS, the broker resolves the path against the base URL, rejects off-host
results, attaches auth, forwards, then either returns the response body inline
or spills it to ``DOWNLOADS_DIR`` and returns a path.
"""
