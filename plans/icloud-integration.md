# iCloud Drive integration — status & summary

## Goal

Add iCloud Drive as a first-class Drive backend alongside Google Drive,
behind a unified agent-tool surface so the agent doesn't have to know
which backend is behind a given verb call.

## Where we landed

The branch `feat/icloud-drive-rclone` carries the full integration. It's
been merged with `origin/main` multiple times along the way and is
currently 18 commits ahead.

### Backend / broker

- New **`rclone_broker`** integration broker that runs a long-lived
  `rclone rcd` daemon per integration. The broker talks to rcd over a
  per-process Unix socket using rclone's JSON-RPC API.
- Backend config (Apple ID, password, trust token, cached cookies) is
  pushed into rcd in-process via the RC API after spawn — never written
  to a config file. rcd holds the credential state and PCS cookies in
  its own heap; nothing about it touches disk.
- Multi-stage Dockerfile build pulls **rclone PR #9447** so ADP-enabled
  iCloud accounts acquire PCS cookies for `iclouddrive` (not just
  `photos`). Pinned to commit `0f2ac246e8438123d3aab736ee7b777edbb2fee2`
  on the fork; revisit once the PR merges upstream and a release ships.
- **Apple SRP-6a sign-in** implemented end-to-end in
  `integrations/_icloud_auth.py` (widget key, srpinit/srpcomplete, 2FA
  challenge, trust-token issuance).
- Wizard UI step set under
  `server/ui/src/components/integrations/add-wizard/IcloudDriveSteps.jsx`
  plus matching server preauth routes.

### Permission model (cross-broker cleanup)

- Renamed `ATTACHMENT_FILE_MODE` → `AGENT_OWNED_FILE_MODE` (0o660) and
  added `AGENT_OWNED_DIR_MODE` (0o2770, setgid, **no sticky bit**).
- All three brokers (email, Google Workspace, rclone) now `chmod` files
  they drop into the shared downloads dir to `AGENT_OWNED_FILE_MODE`.
  The agent's uid is in the broker group, so group rw is enough for the
  agent to read, modify, and (thanks to the non-sticky dir) delete
  broker-written files.
- Entrypoint sets the shared downloads dir to mode 2770 to mirror the
  constant.
- Supervisor first-boot `_maintenance.py` walks legacy 0o640 files and
  the previously sticky downloads dir, chmods broker-owned entries to
  the new modes, and writes a sentinel JSON in the vault so it never
  re-runs.

### Persistent broker secret state

- New supervisor RPC verb `update_secrets`, gated by `SO_PEERCRED` on
  the app socket (only broker-uid peers may call it).
- Catalog entries grew `optional_env_injection` (env vars that may be
  absent on first spawn — used for cached state) and
  `patchable_secret_keys` (allow-list of keys a broker may rewrite via
  `update_secrets`).
- rclone broker uses these to persist PCS cookies and the client_id
  back into the encrypted secret bundle, so they survive container
  restarts and don't have to be re-acquired every boot.

### Unified Drive tool layer

- Both brokers expose the same Drive verbs:
  `drive_list`, `drive_search`, `drive_download`, `drive_upload`,
  `drive_mkdir`, `drive_move`, `drive_delete` (and `drive_share` for
  Google only).
- Each entry projects to the unified shape
  `{name, handle, is_dir, size, mime_type, modified}`.
- Tool wrappers live in `tools/integrations/drive/` and are registered
  by `sdk/tools/_core.py` based on the integration's DRIVE capability
  access level.

### Search (`drive_search`)

- Added a unified search verb with backend-dispatched semantics.
  - **Google**: builds a Drive q-string (`name contains '…' and
    trashed = false and [mimeType = '…']`) and uses the server-side
    index. Truncation never flagged.
  - **Rclone**: no server-side iCloud search, so the broker asks rcd
    for a recursive list and filters client-side by name (case-
    insensitive) and optional mime type. A scan budget of 2000 entries
    caps the work; truncation flagged when the budget hits or the
    result limit is reached with more entries pending.

## Known fragilities & follow-ups

- **Handle shape isn't unified across backends.** Google handles are
  `id:<file_id>`; rclone handles are POSIX-style paths. The agent has
  no in-band reason to suspect they're different shapes, which tempts
  LLMs to "normalize" the `id:` prefix away on Google handles. The
  agreed cleanup (not yet done) is to drop the `id:` prefix and the
  path-walk fallback in `_resolve_handle` — handles become "the raw
  fileId string the agent should echo verbatim." Smallest change,
  biggest LLM-confusion reduction. We explicitly chose **not** to
  base64-encode handles unless we see real mangling in the wild.
- **Rclone path-shaped handles invalidate on rename/move.** If the user
  renames `Tax/2024` to `Tax/2024-old` mid-conversation, any handle the
  agent already has stops working. This is an iCloud API property
  (there are no stable node IDs) and isn't fixable from our side —
  document in tool docstring.
- **Search scope.** `drive_search` searches the whole drive — no
  `handle` argument to scope to a subtree yet. Adding it for rclone is
  trivial (pass the handle as the recursive list's `remote` arg);
  adding it for Google requires walking the parent chain because the
  Drive `q` language doesn't have a transitive `descendant_of`
  operator. Defer.
- **Cross-backend gaps.** iCloud Drive is a strict feature subset of
  Google Drive at the API level. Things Google has and iCloud lacks at
  the rclone layer: server-side search by content, native Doc export,
  sharing/ACLs, revisions/version history, comments, real-time change
  feed. Most of these aren't exposed as agent tools today; the search
  gap is the only one with concrete agent-side impact, and that's now
  filled.
- **Manual-test container is destructive on restart.** A `docker
  restart` against the manual-test container triggers its `--rm`
  cleanup and wipes bind-mounted state, losing all added integrations.
  Live source sync only works against the `just dev` container (which
  uses DEV_MODE respawn loops + persistent `~/.computron_9000/`
  state). The manual-test path is for fresh-state validation only.

## Remote state

- Branch: `feat/icloud-drive-rclone`, currently 18 commits ahead of
  `origin/main`.
- Remote branch was deleted sometime after the May 29 push — none of
  the feature work landed on main, so this was a manual remote-side
  delete, not a merge. Re-pushing now to recreate it and open a PR.
- 1334 unit tests passing after the most recent merge with main.
