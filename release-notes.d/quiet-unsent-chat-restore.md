---
target: app
type: fixed
area: chat
---

Reloading a workspace with an unsent chat now restores the empty chat directly,
without trying to load a conversation that has not been saved or showing an error
over tabs and settings controls. After sending the first message, refresh restores
the saved conversation. Failed attempts to open a saved conversation still show
an error and preserve the current chat.
