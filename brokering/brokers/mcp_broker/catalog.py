"""One executable contract shared by all remote MCP integration presets."""

from brokering.drivers import BrokerDriver


MCP_DRIVER = BrokerDriver(
    id="remote.mcp",
    command=("python", "-m", "brokering.brokers.mcp_broker"),
    env_injection={"endpoint": "MCP_ENDPOINT", "access_token": "MCP_ACCESS_TOKEN"},
)
