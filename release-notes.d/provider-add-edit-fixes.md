---
target: app
type: fixed
area: providers
---

Fixes provider add/edit bugs: adding a provider that fails its connection
test no longer leaves a broken entry behind, brokered providers with a
custom endpoint (e.g. OpenAI-compatible servers) now show and let you edit
their base URL, and the provider list stays current after a failed add.
