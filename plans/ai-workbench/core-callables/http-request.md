# HTTP Request Core Callable

> Design for `omnideck.http.request@1`: authenticated HTTP/API calls through
> existing HTTP integrations, including method/body/header handling, read/write
> effect metadata, response body handling, errors, and logs.

## Scope

`omnideck.http.request@1` is the programmatic core wrapper around the existing
authenticated HTTP integration broker verb, `http_request`.

It lets app/local callables call configured APIs such as GitHub without direct
network access or direct credential access. It is not a generic HTTP client. The
integration owns the base URL and auth token; the caller supplies a path under
that base URL.

For app-building agents, connected HTTP integrations appear in the callable
catalog as integration facade callables, such as
`integration.github.request@1`. Those facades are backed by this core callable.
The agent depends on the facade; Omnideck derives the app integration use and
user account mapping. The agent does not author integration configuration.

## Callable Surface

Recommended v1 package:

| Callable | Purpose | Effects |
|---|---|---|
| `omnideck.http.request@1` | Make an authenticated HTTP/API request through an integration | `http.read` or `http.write` |

`@1` is a retained runtime API for saved apps. Breaking changes require a new
version under the lifecycle rules in
[../callable-runtime.md](../callable-runtime.md#core-callable-version-lifecycle).

## Input

```json
{
  "integration_alias": "github",
  "method": "GET",
  "path": "/repos/owner/repo/issues",
  "query": {
    "state": "open"
  },
  "headers": {
    "Accept": "application/vnd.github+json"
  },
  "body": null,
  "body_file_ref": null,
  "body_content_type": null,
  "response_mode": "auto"
}
```

`integration_alias` names a derived app integration use, not an arbitrary URL or
connected account id. The saved app manifest records the derived use, such as:

```json
{
  "integration_uses": {
    "github": {
      "ref": "integration.github.request@1",
      "kind": "http",
      "provider": "github",
      "access": "read_write",
      "backing_core_callable": "omnideck.http.request@1"
    }
  }
}
```

At install or app setup time, Omnideck maps that alias to one connected
integration selected by the user. App callable code can request the app-level
alias exposed by its declared dependency, but it cannot choose a raw host,
localhost URL, cloud metadata address, raw connected integration id, or another
integration that was not derived from the app's callable dependencies.

Body inputs:

- `body` accepts a string, object, or array.
- `body_file_ref` streams or reads a runtime-owned file ref as the request
  body.
- `body` and `body_file_ref` are mutually exclusive.
- `body_content_type` applies to `body_file_ref` and may override guessed MIME
  type when safe.

Response modes:

```text
auto   small text/json inline, large or binary as file_ref
inline fail if response cannot be safely returned inline
file   always write response body to a file_ref
none   discard response body after status/header capture
```

## Return

```json
{
  "status": 200,
  "headers": {
    "Content-Type": "application/json"
  },
  "content_type": "application/json",
  "size": 12043,
  "body": "[...]",
  "body_file_ref": null,
  "effect": {
    "kind": "http.read",
    "integration_alias": "github",
    "method": "GET",
    "path": "/repos/owner/repo/issues"
  }
}
```

HTTP 4xx and 5xx responses are successful callable results with `status` and
body metadata. They are not runtime errors. Transport failures, missing
integrations, denied permissions, invalid inputs, and response-size violations
are structured errors.

## Broker Mapping

The core callable should preserve the existing HTTP broker safety properties:

- the integration owns the base URL and auth token,
- caller supplies only a path under that base URL,
- caller identifies only a derived app integration alias,
- Omnideck resolves that alias to a connected integration server-side,
- absolute URLs or protocol-relative URLs that resolve to another host are
  rejected,
- localhost, private-network, link-local, and metadata-service targets are
  unreachable because callers never provide a host,
- the broker attaches the integration auth header server-side,
- caller-supplied auth, cookie, host, content-length, and hop-by-hop headers are
  dropped or rejected,
- redirects are returned to the caller, not followed automatically,
- large or binary responses spill to a runtime file,
- response size and request timeout are bounded.

Access metadata depends on method:

```text
GET, HEAD, OPTIONS -> http.read
POST, PUT, PATCH, DELETE -> http.write
```

The broker remains the final authority. If a configured HTTP integration has
only read access, the broker denies mutating methods even if the app manifest
declares `omnideck.http.request@1`.

SSRF stance: v1 `omnideck.http.request@1` is host-locked to a connected
integration's configured base URL and does not follow redirects automatically.
Do not add a generic outbound HTTP callable for app/local code.

The callable manifest can describe the broad possible effect:

```json
{
  "kind": "http.request",
  "summary": "Makes requests through connected HTTP/API integrations",
  "dynamic_access": {
    "read_methods": ["GET", "HEAD", "OPTIONS"],
    "write_methods": ["POST", "PUT", "PATCH", "DELETE"]
  }
}
```

Each invocation log records the concrete effect.

## Header Handling

Caller-supplied headers are convenience headers, not an auth channel. The core
callable and broker must preserve the existing forbidden-header behavior:

```text
authorization
x-api-key
cookie
host
content-length
connection
keep-alive
proxy-authenticate
proxy-authorization
te
trailers
transfer-encoding
upgrade
```

The integration's configured auth header always wins.

Response headers should omit hop-by-hop headers and `Set-Cookie`. A returned
`Location` header is useful for 3xx handling, but redirects are not followed
automatically.

## Body And File Refs

Small JSON/text request bodies can be passed through `body`. File uploads and
large request payloads should use `body_file_ref`.

When the broker returns a large or binary response, the core callable should
convert broker spill files into managed file refs before returning to app/local
callables. App frontends should not receive backend-only file refs directly. If
app-created downloadable artifacts are added later, app callables can promote
user-visible outputs through `omnideck.artifact.create@1`.

## Errors

Relevant structured error codes:

| Code | Meaning |
|---|---|
| `VALIDATION_ERROR` | Input failed JSON schema or callable validation |
| `FILE_NOT_FOUND` | `body_file_ref` is missing or no longer available |
| `FILE_ACCESS_DENIED` | `body_file_ref` is outside the caller's allowed roots |
| `FILE_TOO_LARGE` | Request or response file exceeds callable limit |
| `INTEGRATION_NOT_CONNECTED` | Supervisor has no connected integration |
| `INTEGRATION_PERMISSION_DENIED` | Broker denied capability/access |
| `INTEGRATION_AUTH_FAILED` | Upstream rejected credentials |
| `UPSTREAM_ERROR` | Broker or upstream returned a non-auth transport error |
| `UPSTREAM_TIMEOUT` | Broker request timed out |
| `RESPONSE_TOO_LARGE` | HTTP response exceeded configured limit |

The app router should include the callable `call_id` with these errors so the
frontend can show a short message and the agent can inspect logs.

## Logs

Every invocation should emit a structured effect event:

```json
{
  "type": "effect",
  "kind": "http.read",
  "integration_alias": "github",
  "resolved_integration_id": "github_api",
  "method": "GET",
  "path": "/repos/owner/repo/issues",
  "status": 200,
  "duration_ms": 431
}
```

Do not log credentials, auth headers, request bodies by default, or full
response bodies. Log file refs, sizes, content types, status codes, selected
safe headers, and hashes where useful.

## Backlog Manager Use

The project backlog app can use `omnideck.http.request@1` to:

- list GitHub issues,
- fetch details for a selected issue,
- close an issue with a mutating request,
- snapshot issues during backup.

Close issue example:

```json
{
  "integration_alias": "github",
  "method": "PATCH",
  "path": "/repos/owner/repo/issues/123",
  "body": {
    "state": "closed"
  },
  "response_mode": "none"
}
```

If GitHub rate limits or returns a 403/429 through HTTP, the HTTP callable
returns the upstream status and response body metadata. The app decides whether
that is a failed action, a retryable action, or a partial backup.

## Open Decisions

- Whether `omnideck.http.request@1` should allow response streaming later, or
  always materialize response bodies into inline text or file refs.
- Whether mutating HTTP calls should support optional app-level idempotency
  metadata, or leave that to app callables.
- Exact response header allowlist for frontend-safe summaries.
