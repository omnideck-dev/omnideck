---
target: app
type: fixed
area: integrations
---

Listing events from CalDAV calendars (e.g. iCloud) no longer times out.
The client now waits long enough for slow calendar searches to finish, and
correctly detects a dropped connection instead of silently giving up.
