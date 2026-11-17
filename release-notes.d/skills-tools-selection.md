---
target: app
type: changed
area: agents
---

Choose skills, built-in tools, and individual integrations in one expandable list
when editing an agent. Skill editors use the same tool list, with links to each
integration's approvals. Agents can now select tools without attaching a skill.

**Upgrade note: existing agents and skills may gain access to more tools.**
The upgrade automatically converts broad categories such as Email, Calendar,
and Drive into selections of matching existing integrations. Each selection
includes **all tools already approved for that integration**, not just tools
from the old category.

For example, if an agent or skill previously selected only Email, and Work
Google already has approved Email, Calendar, and Drive tools, the migration
selects Work Google and makes all of those approved tools available to it.
Other existing integrations with approved email tools are also selected.

The migration does not approve additional tools, and integrations added later
are not automatically selected. After upgrading, review the integrations
selected on your agents and skills and their tool approvals in Settings →
Integrations if you want to narrow access.

**Import/export compatibility note: select integrations again after import.**
Existing skill and agent export files still import, preserving their
instructions and built-in tool selections. However, importing an older file
now removes broad integration categories such as Email and Calendar instead
of automatically mapping them to connections. New exports also omit local
integration selections.

After importing, edit the skill or agent and select the integrations it needs
before using features that depend on them. This also applies when importing
back into the same installation. Existing saved agents and skills upgraded in
place use the automatic migration described above; imported files do not.

Deleting an integration removes its assignments from saved agents and skills,
including disabled agents. Saving an older editor draft cannot restore the
deleted link; temporary connection outages do not erase assignments.
