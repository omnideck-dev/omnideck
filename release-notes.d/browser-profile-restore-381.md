---
target: app
type: fixed
area: browser
---
Saved browser profiles now preserve binary IndexedDB keys and values during export. Older snapshots skip records with invalid primary keys so cookies, local storage, and valid database records can still restore. Retrying a failed browser session also retains the selected profile instead of opening an empty session.
