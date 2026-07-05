# HTTP Fetch Core Callable

> Design for `omnideck.http.fetch@1`: unauthenticated public HTTP reads through
> an app-approved host allowlist.

## Scope

`omnideck.http.fetch@1` is for public, no-auth data sources that are not
connected integrations: public APIs, datasets, status feeds, and similar
read-only resources.

It is deliberately separate from `omnideck.http.request@1`:

- `omnideck.http.request@1` is authenticated, integration-scoped, and
  host-locked to a connected integration.
- `omnideck.http.fetch@1` is unauthenticated, public internet read-only, and
  restricted by the app's approved `web_allowlist`.

Do not use `omnideck.http.fetch@1` for authenticated services, OAuth-backed
APIs, user accounts, internal services, or arbitrary browser fetch.

## Callable Surface

Recommended v1 package:

| Callable | Purpose | Effects |
|---|---|---|
| `omnideck.http.fetch@1` | Fetch public unauthenticated HTTP data from app-approved hosts | `http.read` |

`@1` is a retained runtime API for saved apps. Breaking changes require a new
version under the lifecycle rules in
[../callable-runtime.md](../callable-runtime.md#core-callable-version-lifecycle).

This callable is gated by `ai_workbench.enabled` and
`ai_workbench.public_fetch_enabled`. When disabled, it returns
`FEATURE_DISABLED` before validating or resolving the target URL.

## Input

```json
{
  "url": "https://status.example.com/feed.json",
  "method": "GET",
  "headers": {
    "Accept": "application/json"
  },
  "response_mode": "auto",
  "timeout_ms": 5000
}
```

Rules:

- `method` is `GET` or `HEAD` only.
- `url` must be absolute `https://` for v1.
- The URL host must match the app manifest's approved `web_allowlist`.
- No request body is accepted.
- Caller-supplied auth, cookie, host, content-length, and hop-by-hop headers are
  rejected.
- Omnideck attaches no credentials, cookies, integration tokens, or broker auth.
- Redirects are returned to the caller and are not followed automatically.

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
  "body": "{...}",
  "body_file_ref": null,
  "effect": {
    "kind": "http.read",
    "host": "status.example.com",
    "method": "GET",
    "url": "https://status.example.com/feed.json"
  }
}
```

HTTP 4xx and 5xx responses are successful callable results with `status` and
body metadata. They are not runtime errors. Validation failures, denied hosts,
transport failures, timeout, and response-size violations are structured errors.

## App Manifest Grant

Apps declare public fetch destinations in `web_allowlist`:

```json
{
  "web_allowlist": [
    {
      "host": "status.example.com",
      "purpose": "Read the public service status feed"
    },
    {
      "host": "data.example.org",
      "purpose": "Read public dataset metadata"
    }
  ]
}
```

Rules:

- Hosts must be exact hostnames. No wildcards in v1.
- No IP literals in v1.
- No userinfo, path, query, or scheme in the allowlist entry.
- Save/import review shows every host and purpose.
- The user approves the allowlist alongside effects, packages, and integration
  bindings.

The allowlist is a network grant. App-authored text may describe why a host is
needed, but enforcement uses only the structured `web_allowlist` entries.

## SSRF Hardening

`omnideck.http.fetch@1` runs in trusted Omnideck code so it can enforce network
safety before making an outbound request:

1. Parse URL with a structured URL parser.
2. Require `https://`.
3. Match the normalized host against the app's `web_allowlist`.
4. Resolve DNS server-side.
5. Reject loopback, private, link-local, multicast, unspecified, reserved, and
   cloud metadata ranges, including `169.254.169.254`.
6. Connect only to the validated resolved address.
7. Re-check the connected peer address to reduce DNS rebinding risk.
8. Do not follow redirects automatically.
9. Apply per-request timeout and response-size caps.

If a redirect points at another URL, return the 3xx status and `Location` header
metadata to the caller. The app may request a second fetch only if the redirected
host is also on `web_allowlist` and passes the same public-IP checks.

## Logs And Effects

Every invocation emits a structured effect event:

```json
{
  "type": "effect",
  "kind": "http.read",
  "host": "status.example.com",
  "method": "GET",
  "status": 200,
  "size": 12043,
  "duration_ms": 241
}
```

Do not log request query strings by default. Query parameters can carry
exfiltrated data, so logs should include host, method, status, size, and a
redacted URL or path summary only.

## Honest Residual Risk

An app with an approved `web_allowlist` can encode data into GET query
parameters sent to an allowlisted host. The v1 control is the explicit,
user-reviewed destination list. Import/save review should present this as a real
risk: approved public hosts can receive data from app code through backend fetch
requests.

## Errors

Relevant structured error codes:

| Code | Meaning |
|---|---|
| `VALIDATION_ERROR` | Input failed JSON schema or URL validation |
| `FEATURE_DISABLED` | Public unauthenticated fetch is disabled by feature flag |
| `WEB_HOST_NOT_ALLOWED` | URL host is not in the app's approved web_allowlist |
| `WEB_HOST_NOT_PUBLIC` | DNS resolution or connected peer address is not public |
| `METHOD_NOT_ALLOWED` | Method is not GET or HEAD |
| `UPSTREAM_ERROR` | Upstream transport failed |
| `UPSTREAM_TIMEOUT` | Request timed out |
| `RESPONSE_TOO_LARGE` | Response exceeded configured limit |
