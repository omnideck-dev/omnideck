# Security Review

> Consolidated checklist and threat model for AI workbench apps. This does not
> replace the detailed design docs; it gives implementation and review one place
> to verify boundaries.

## Assets To Protect

- Host machine outside the Omnideck container.
- Omnideck server process and durable state.
- Broker credential vault and integration tokens.
- User app data and saved app versions.
- Other apps' data.
- Conversation data, settings, logs, and artifacts.
- User browser session and XSRF authority.
- Connected external services such as Drive, email, and GitHub.

## Trust Boundaries

| Boundary | Trusted side | Untrusted side |
|---|---|---|
| Container boundary | Host | Omnideck container |
| Runner boundary | Omnideck app/broker | Local/app callable code |
| Broker boundary | Broker vault | Core integration callables and callers |
| Core callable boundary | `omnideck` process | Runner-provided args |
| App router boundary | Omnideck app | App frontend requests |
| Frontend frame boundary | Omnideck shell | App HTML/JS |
| Import boundary | Local install | Imported app archive |

The runner boundary is defense in depth inside the container. The container is
the host boundary. V1 app execution is disabled unless the runner launcher can
enforce the documented execution floor: app-specific runner uid, no-new-privs,
dropped capabilities, seccomp network denial, resource limits, disabled core
dumps, and Landlock filesystem confinement.

## Threats

Primary threats:

- agent-authored callable accidentally does too much,
- imported app contains malicious frontend or callable code,
- package install/build hook runs malicious code,
- callable tries to read credentials, app data, or other apps' data,
- callable tries direct network access,
- app frontend tries arbitrary Omnideck API calls,
- app frontend tries to impersonate shell UI,
- core callable accepts broad or unsafe input,
- core callable bug compromises the privileged `omnideck` process,
- a supposed HTTP/API callable becomes a generic network client or SSRF vector,
- approved public fetch hosts become an exfiltration destination through GET
  query parameters,
- logs or support bundles leak secrets,
- import/export compatibility silently changes behavior,
- runaway callables consume CPU, memory, processes, or disk.

Out of scope for v1:

- protecting the host if the container boundary is broken,
- treating imported apps as safe after static inspection,
- a marketplace trust/reputation system,
- browser support for legacy engines.

## Required Controls

Feature gates:

- `ai_workbench.enabled` defaults off in production,
- builder, runtime, import/export, and public-fetch subfeatures have separate
  server-enforced flags,
- disabled flags block direct API calls, agent tools, frame minting, app invoke,
  import/export, and runner launch for the gated surface,
- flag checks happen before loading untrusted app code, preparing environments,
  invoking broker-backed work, or starting runner processes,
- disabling the runtime flag cancels active app runner call trees and prevents
  new child callable launches.

Runner execution:

- local/app callables run out-of-process,
- local/app callables run as app-specific runner users, not one shared runner
  uid for all apps,
- no broker group membership,
- no provider tokens or integration credentials in env,
- no Omnideck server `PYTHONPATH`,
- `NO_NEW_PRIVS`,
- Linux capabilities dropped,
- mandatory seccomp network denial and reduced syscall surface,
- mandatory Landlock filesystem restrictions for normal app execution,
- resource limits and disabled core dumps,
- parent-enforced timeout and cancellation.

Core callable surface:

- every core callable has schema validation,
- every core callable treats runner input as untrusted,
- no general shell/process/file-system escape callable,
- no credential passthrough to runner,
- broker remains source of truth for integration permissions,
- authenticated HTTP/API core callables are integration-scoped and host-locked,
- public no-auth fetch is limited to `web_allowlist` hosts, GET/HEAD methods,
  no credentials, no redirect-following, response-size/time caps, and
  public-IP-only SSRF checks,
- no app/local callable gets generic outbound network,
- effect summaries are accurate and reviewable.

Core-callable bugs are unmitigated privileged compromise unless that callable
opts into process isolation. Treat HTTP/API, file parsing/conversion, archive,
Drive upload, and future document/media processing callables as candidates for
separate worker-process execution even if simpler core callables remain
in-process.

Package dependencies:

- saved callables use exact pins and lock files,
- extra packages require user approval,
- package install/build hooks run outside Omnideck server process,
- environment builder uses a dedicated build user, `NO_NEW_PRIVS`, dropped
  capabilities, no credentials, Landlock confinement, offline build hooks,
  network-denied seccomp during hook execution, read-only hash-verified package
  cache access for hooks, and sealed immutable envs,
- install logs are sanitized before display/export.

App frontend:

- app frontend runs in sandboxed opaque-origin iframe,
- shell owns trusted app chrome,
- parent bridge exposes named operations only,
- bridge validates expected frame/source and request ids,
- app frame cannot set trusted XSRF headers directly,
- CSP denies broad network and remote code,
- app frame `img-src` and `media-src` may include exact user-approved
  `web_allowlist` hosts, but `connect-src` remains `none`,
- cookies are not part of the app-frame contract.

Bundles/import:

- saved versions are immutable,
- app/local callable code is vendored into saved versions,
- core callable ids are exact retained APIs,
- archive hashes are verified,
- import review is explicit,
- imported apps default disabled until review completes.

Logs/support:

- run logs are bounded and pruned,
- logs avoid credentials and raw host paths,
- support bundle export requires explicit user action,
- support bundles redact known secret shapes,
- stdout/stderr/package-install logs are captured with byte caps, secret-pattern
  scanning, and default excerpts instead of full logs,
- redaction is not treated as a security boundary.

## Review Checklist

Before enabling app execution:

- feature flags are enabled only for the intended environment/account/cohort,
- every route/tool/runtime entry point has a direct `FEATURE_DISABLED` test,
- runner cannot access broker socket,
- runner cannot import Omnideck server modules,
- runner cannot write outside scratch without core callable,
- runner cannot create network sockets,
- one app runner cannot read another app runner's scratch or app data path,
- cancellation kills child processes,
- large JSON results are rejected,
- call graph limits are enforced before launching child runners.

Before exposing a core callable to apps:

- schema rejects malformed input,
- paths are refs, not host paths,
- auth headers/tokens are never returned,
- effect metadata is accurate,
- errors are structured and sanitized,
- logs do not include credentials by default,
- tests cover permission denied and malformed input.
- risky core callables have an explicit decision: in-process with rationale or
  worker-process isolation.

Before allowing import:

- manifest schema version is supported,
- core callable ids exist and are enabled,
- file hashes match,
- package locks exist,
- extra packages are shown to user,
- effects and storage metadata are shown to user,
- `web_allowlist` hosts and purposes are shown to user,
- imported app is disabled until accepted.

Before shipping frontend runtime:

- app iframe uses opaque sandbox origin,
- same-origin app HTML is not allowed,
- app frame cannot call arbitrary `/api/*`,
- bridge rejects messages from unexpected frames,
- CSP blocks remote scripts and browser network,
- shell chrome cannot be hidden by app frame.

## Security Test Ideas

- callable attempts `socket(AF_INET, ...)`,
- callable attempts to open broker socket,
- callable attempts to read another app's storage path,
- callable attempts to return a huge JSON result,
- callable forks until process limit,
- callable ignores cancellation,
- package build hook tries to read environment secrets,
- app frontend calls `/api/settings`,
- app frontend sends forged bridge message from another frame,
- app frame creation and app invoke return `FEATURE_DISABLED` when runtime flags
  are off,
- agent app-building tools return `FEATURE_DISABLED` when builder flags are off,
- callable runtime refuses app runner launch when runtime flags are off,
- imported bundle has modified file hash,
- core callable receives path traversal input,
- `omnideck.http.request@1` receives absolute URL, localhost, link-local,
  metadata-service, unmapped integration alias, or raw integration target and
  rejects it,
- `omnideck.http.fetch@1` rejects non-allowlisted hosts, IP literals, POST or
  body input, caller auth/cookie headers, localhost, private ranges, link-local
  addresses, `169.254.169.254`, and DNS rebinding to non-public addresses,
- `omnideck.http.fetch@1` returns redirects instead of following them,
- `omnideck.http.fetch@1` spills large/binary bodies to `file_ref` or rejects
  oversized responses according to response mode,
- public-fetch effect logs include host, method, status, size, and duration but
  do not include raw query strings by default,
- save/import review shows public fetch hosts as potential data destinations,
- support bundle contains fake token-like strings and verifies redaction.
- package build hook attempts network during hook execution and is denied.

## Vulnerability Handling

If a core callable version has a security issue:

- keep the callable id registered,
- mark it disabled,
- return `CORE_CALLABLE_DISABLED` with migration guidance,
- prevent activation of saved/imported apps that require it,
- let the agent migrate the app to a fixed core callable version when possible.

If an imported app is suspected malicious:

- disable the app,
- preserve saved version and logs for investigation,
- prevent app actions from running,
- allow data export only through trusted Omnideck flows,
- offer support bundle export.

## Open Decisions

- Exact seccomp profile and how it varies by runtime.
- Minimum kernel and Landlock version policy for normal app execution.
- Exact support bundle redaction patterns.
- Security review process for adding new core callables.
