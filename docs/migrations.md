# Data Migrations

Data migrations transform on-disk state when the application is upgraded.
They run once at startup, before the server accepts requests, and require
no user interaction.

## When to use a migration

Use a migration when you need to change the shape of persisted data — renaming
fields, restructuring JSON files, populating new default data, etc.  If the
change only affects code (not stored state), you don't need a migration.

## How they work

1. The fixed container entrypoint runs `python3.12 -m migrations` as root,
   before the desktop, broker supervisor or app starts. It calls the one
   `run_migrations(state_dir, vault_dir)` runner.
2. The runner loads `.migrations.json` from the state directory to see which
   migrations have already been applied.
3. It walks the `_migration_plan(vault_dir)` registry in order and runs any whose name isn't in
   the applied set.
4. After each migration succeeds, its name is appended to `.migrations.json`
   so it won't run again.

Migrations are synchronous and blocking — neither service starts if they fail.
Bootstrap restores app-owned files to `omnideck` and vault files to `broker`,
even after failure. The services then run under their normal restricted users.
The vault remains mode 0700. No broker API, socket or live discovery is needed.
`just restart-app` restarts the container through this barrier; respawning a
service alone never migrates live state. Standalone deployments must explicitly
run bootstrap before starting either service.

## Broker-owned vault migrations

There is one registry and one active completion ledger: the existing
`{state_dir}/.migrations.json`. Existing app IDs are unchanged. Before running
anything, the runner imports completed names from the legacy vault ledger as
`broker:<old-name>` (for example `broker:001_operation_grants`). The old vault
ledger is preserved as read-only history, not updated or independently executed.
Unknown historical names are retained. Imports and completion updates are atomic;
a process lock prevents concurrent runners. Corrupt history stops startup, never
defaults to an empty history. Thus completed old migrations are not replayed.

Vault transformation code stays in `brokering/migrations/`, but its function is
registered alongside app migrations in `migrations/_runner.py`. There is no
supervisor migration hook or separate broker runner.

Vault migration `001_operation_grants` converts v1/v2 connection metadata using
frozen permission mappings. It neither reads nor decrypts credential files and
does not consult OAuth scopes or the current catalog. Ciphertext stays unchanged.
Original metadata is preserved as `creds/<id>.meta.pre-v3.bak` (including backups
from the earlier in-place upgrader). Metadata and backup writes are atomic and
owner-only; retries never replace the original backup. Existing v3 records are
left unchanged. Orphan metadata is also migrated so a later credential repair
does not reintroduce legacy records after the plan has completed.

A failed vault migration stops container startup without marking it complete.
Record conversion is idempotent, so a later startup can resume partially
completed work. Unknown legacy presets or malformed metadata require repair;
they are not silently discarded or marked migrated. The completion ledger is
also written atomically with owner-only permissions.

## Adding a new migration

### Connection-scoped tool selections (016)

`016_connection_tool_categories` runs in the same startup plan, after vault
`001_operation_grants`. It reads saved v3 `.meta` approvals directly from disk,
without reading keys or encrypted credentials. Like the supervisor inventory,
it includes only metadata with a matching `.enc` file, including connections
that are stopped or offline. Invalid metadata stops migration; an empty on-disk
inventory is authoritative. Discovery polling never writes migration state.

Existing Email, Calendar, Drive, Contacts, HTTP/API and MCP selections are mapped
to the existing connection IDs that have approved operations in those categories,
including stopped connections. **This intentionally broadens a partial selection
(for example Email) to all approved tools on each mapped connection (for example
Work Google, including its approved calendar tools).** This is the owner-approved
one-time migration, not an exact-permission-preserving conversion. Individual
operation approvals remain enforced by Integrations; unapproved tools are not granted.

The original mapping is frozen in `.connection-category-mapping.json` before
records change. Originals are preserved under
`migration-backups/016_connection_tool_categories/`; atomic record writes and
the ordinary `.migrations.json` ledger allow safe retries without expanding the
mapping. Legacy selections with no matching connection are removed. A follow-up
cleanup pass also removes these obsolete IDs from already-migrated preview
records, with its own backups; it never remaps them to newer connections.
Connections created later are never automatically selected. Renaming or
reconnecting the same ID preserves selection; replacing a connection does not.

Agent `tool_categories` selections combine with saved attached-skill selections
as a deduplicated union. Removing one source does not deny another source's tools.
Browser access remains a separate agent setting. Exported/imported packs retain
built-in groups but omit local connection selections and legacy broad grants;
recipients select their own integrations. Fresh default skills grant only built-ins.

### Filesystem-only migrations

1. Create a new file in `migrations/`, following the naming convention
   `_NNN_short_description.py` (e.g. `_017_add_profile_version.py`).
   Define a ``migrate`` function that takes the state directory:

   ```python
   from pathlib import Path

   def migrate(state_dir: Path) -> None:
       ...
   ```

2. Register it in ``migrations/_runner.py`` by appending to the
   ``_migration_plan`` registry. Every migration module exports a function named
   ``migrate`` — if you imported them plainly, each new one would shadow
   the last. So import each under an alias that matches its module name,
   then append a ``(name, migrate_fn)`` tuple to the list:

   ```python
   from migrations._017_add_profile_version import migrate as _017_add_profile_version

   def _migration_plan(vault_dir):
       return [
           # Existing entries stay in their existing order.
           ("017_add_profile_version", _017_add_profile_version),
       ]
   ```

   Order matters: always append at the bottom so existing
   installations keep the same sequence.

## Guidelines

- **Back up before modifying.** If you're rewriting files, save a copy first
  (see `_001_task_agent_to_profile.py` for the pattern).
- **Be idempotent within the migration.** If a file has already been partially
  migrated (e.g. from a crash), handle that gracefully.
- **Don't import application code that has side effects.** Migrations run
  early in startup.  Importing heavy modules (LLM providers, browser tools)
  can cause problems.  Stick to stdlib + config.
- **Keep migrations fast.** They block startup.

## File layout

```
migrations/
  __init__.py                         # re-exports run_migrations
  __main__.py                         # root bootstrap + store ownership
  _runner.py                          # one registry, history import + applier
  _001_task_agent_to_profile.py       # example: field rename
  _002_install_default_profiles.py    # example: seed default data
```

## Tracking file

Applied migrations are recorded in `{state_dir}/.migrations.json`:

```json
[
  "001_task_agent_to_profile",
  "002_install_default_profiles"
]
```

Delete an entry from this file to re-run a migration (useful during
development).
