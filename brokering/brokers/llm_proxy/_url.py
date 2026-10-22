"""URL routing for model provider requests."""


def build_upstream_url(base_url: str, relative_url: str, *, provider: str) -> str:
    """Join a base URL with no trailing slash to an SDK request path and query."""
    if (
        provider == "openai"
        and base_url.endswith("/v1")
        and relative_url.startswith("/v1/")
    ):
        relative_url = relative_url.removeprefix("/v1")
    return base_url + relative_url
