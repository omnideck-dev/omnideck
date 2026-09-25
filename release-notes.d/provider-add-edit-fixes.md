---
target: app
type: fixed
area: providers
---

Adding a provider that fails its connection test no longer leaves a
broken entry behind. Brokered providers with a custom endpoint (like
OpenAI-compatible servers) now show and let you edit their base URL,
and the provider list stays current after a failed add.
