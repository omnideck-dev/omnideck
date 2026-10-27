---
target: app
type: removed
area: ui
---

Hand-edited `custom.css` overrides no longer apply: the app no longer reads or
serves that file. An existing `custom.css` is left where it is but has no
effect, and its contents are not carried over. To customize colors and fonts,
ask the agent, which saves your choices in a new `theme.json` beside your
settings.
