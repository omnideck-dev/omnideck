---
target: app
type: fixed
area: agents
---

Oversized tool output is saved to a temporary file with a preview and path,
keeping large results out of conversation context while allowing focused
inspection with existing tools. File search now uses find_files for filenames
and search_text for contents, backed by ripgrep with bounded output and a
cancellable deadline. Searches report incomplete results explicitly and retain
case-insensitive regex matching, two context lines, and hidden/ignored file scope.
