"""Slack preset policy; the remote MCP broker remains provider-independent."""

SLACK_MCP_ENDPOINT = "https://mcp.slack.com/mcp"
SLACK_MCP_ISSUER = "https://mcp.slack.com"

# Explicitly reviewed user-token scopes for Slack's full MCP tool catalog.
# Source: https://docs.slack.dev/ai/slack-mcp-server/ (2026-09-27).
# Do not replace this with all scopes returned by discovery: new upstream
# permissions must not silently broaden consent. OAuth access is separate from
# local operation grants; discovery and reconnect never select new tools.
SLACK_MCP_SCOPES = (
    "canvases:read", "canvases:write",
    "channels:history", "channels:read", "channels:write",
    "chat:write", "emoji:read", "files:read", "files:write",
    "groups:history", "groups:read", "groups:write",
    "im:history", "im:read", "im:write",
    "lists:read", "lists:write",
    "mpim:history", "mpim:read", "mpim:write",
    "reactions:read", "reactions:write",
    "search:read.files", "search:read.im", "search:read.mpim",
    "search:read.private", "search:read.public", "search:read.users",
    "users:read", "users:read.email",
)


def slack_app_manifest(redirect_uri: str) -> dict:
    """Build the internal-app template with this installation's callback."""
    return {
        "display_information": {"name": "omnideck", "description": "Connect your workspace to omnideck"},
        "oauth_config": {
            "redirect_urls": [redirect_uri], "pkce_enabled": True,
            "scopes": {"user": list(SLACK_MCP_SCOPES)},
        },
        "settings": {"token_rotation_enabled": True, "is_mcp_enabled": True},
    }
