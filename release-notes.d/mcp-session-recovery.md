---
target: app
type: fixed
area: integrations
---

A slow or failed MCP tool call no longer breaks the integration's other calls. Tools can now run for up to 10 minutes. MCP integrations reconnect automatically for the next tool call after a connection drops. If a tool loses its response, omnideck reports the uncertain outcome and leaves the retry decision to you.
