---
target: app
type: fixed
area: integrations
---

Google and MCP integrations now renew authorization through the supervisor. Refresh tokens stay out of broker processes, rotated credentials are saved before activation, and active calls retain their original session during renewal. Token rejection can renew authorization without replaying the tool operation; the agent receives guidance to verify the outcome before repeating an action.
