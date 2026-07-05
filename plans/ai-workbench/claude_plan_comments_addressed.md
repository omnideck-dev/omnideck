# Claude plan review — addressed

Archive of resolved review entries from
[`claude_plan_comments.md`](claude_plan_comments.md). Claude maintains this file.
Codex does not write here.

Each record keeps the entry id, title, outcome, and a one-line resolution. Full
text and discussion threads live in git history.

---

## 2026-07-05 — first verification pass

Each entry below was verified against the actual plan text by an independent
review pass, not accepted on the "Implemented" claim alone.

- C1 — Runner sandbox and dedicated runner user — RESOLVED (applied). `callable-runtime.md` Execution And Isolation documents the `runner` user, boot launcher/setuid ownership, the sandbox primitives (NO_NEW_PRIVS, dropped caps, seccomp with socket-creation denial, Landlock, resource limits, disabled core dumps, clean env), the container-boundary constraint, and the builder posture. Verified. Residual: some enforcement is best-effort (see C18); internal inconsistencies (see C21).
- C2 — Native-process runners, multi-language, Python default — RESOLVED (applied). States native-only with WASM rejected, language-neutral protocol, Python default. Verified.
- C3 — Hybrid package model — RESOLVED (applied). Baseline plus consented long-tail with bundle `package_review` linkage. Verified. `package_review` naming inconsistency tracked in C21.
- C4 — Core callables are privileged trust boundaries — RESOLVED (applied) in `callable-runtime.md` and `core-callables.md`: hostile-input validation and no broad ambient power. Verified. Residual "no containment behind core callables" tracked in C20.
- C5 — v1 baseline package set — RESOLVED (applied). Named exact list plus a requirement that the runtime expose the active list via discovery. Verified.
- C6 — Effects derived, not author-written — RESOLVED (applied). Author field renamed `declared_effects_summary` (documentation only); review effects derived from `core_dependencies` including transitive. Verified. Completeness follow-ons in C15.
- C7 — Disclose packages at import, isolate imported install — RESOLVED (applied). Review lists extra packages; import requires approval before isolated env prep; validation runs no app code while package hooks run in the builder. Verified. Builder-isolation depth tracked in C19.
- C9 — Cross-version storage compatibility — RESOLVED (applied). Shared-across-versions stance, `schema_version` tagging, tolerant reads. Verified. Detection gap tracked in C16.
- C10 — Single source of truth for `app_visibility` — RESOLVED (applied). Bundle manifest authoritative; per-callable field removed and rejected at validation. Verified.
- C11 — Nested-call latency — RESOLVED (applied). v1 accepts per-call spawn latency with batching guidance; pooling deferred. Verified; latency ceiling stated only qualitatively.
- C12 — Discovery surface and build skill — RESOLVED (applied) in `agent-build-tooling.md`. Discovery and the build skill are concretely specified. Verified. Follow-ons: C14 (integration selection), C17 (invoke envelope, validation codes, manifest example); minor: discovery shows input but not output schemas.

## 2026-07-05 — second verification pass

Codex answered C8 and C13–C22 and edited the plan files. Each below was verified
against the current plan text, with direct greps where an async check raced
Codex's concurrent edits.

- C13 — Runner scratch, file refs, large-file handoff — RESOLVED (applied). The fd-passing handoff (parent opens an omnideck-owned file and passes the write descriptor via fork/setuid/exec or SCM_RIGHTS; runner streams in; no host path) is now written explicitly in `callable-runtime.md` and `files-artifacts.md`, the three file areas are named distinctly, and the seccomp SCM_RIGHTS exception is stated. Verified. Residual scope-name overlap → C23.
- C14 — Integration targeting and `http.request` scoping — RESOLVED (applied). `http.request` takes an app-declared `integration_binding` resolved server-side and host-locked (localhost, link-local, private-network, and metadata targets unreachable); the "generic HTTP" framing is reconciled to a named threat/test; the GitHub issue write/close path is represented. Verified. Closes the SSRF and network-escape concern.
- C15 — Effects derivation completeness — RESOLVED (applied). Effect-kind-to-sentence mapping table added, the sample includes the `file.write` effect, and author effect text is marked documentation-only. Verified.
- C16 — Storage schema-change detection — RESOLVED (applied). Per-collection `document_schema` and `document_schema_version`, an explicit best-effort fallback, a compatibility-check flag, and the `schema_version` collision resolved by renaming the per-document field. Verified. Residual stale example → C23.
- C17 — Agent build/test loop and authoring artifact — RESOLVED (applied). `app_preview.invoke` returns a `call_id` and structured errors, the pre-preview validation gate has an error-code table, and there are concrete callable and draft manifest examples. Verified. Residual example-code mismatch → C23.
- C18 — v1 isolation floor — RESOLVED (applied). App execution is gated on the mandatory floor (per-app runner uid, no-new-privs, dropped capabilities, mandatory seccomp network denial and Landlock, resource limits, disabled core dumps); cross-app isolation via per-app uid plus mandatory Landlock. The two contradictory Open Decision bullets were confirmed removed by direct grep. Verified.
- C19 — Environment builder isolation — RESOLVED (applied). Dedicated build user, dropped caps, resource limits, disabled core dumps, offline network-denied build hooks, and sealed immutable envs; the env-poisoning risk is called out. Verified. Residual hardening gaps (NO_NEW_PRIVS/Landlock, launch path, shared cache) → C24.
- C20 — Core-callable privileged surface and log exfil — RESOLVED (applied). The plan states core-callable bugs are unmitigated privileged compromise and names HTTP/file/Drive as worker-process isolation candidates; default support-bundle log capture is reduced and full logs gated behind a second confirmation. Verified.
- C21 — callable-runtime internal inconsistencies — RESOLVED (applied). Server-to-launcher handoff described; `package_review` given one review location with a validation cross-check; seccomp SCM_RIGHTS exception stated; the CAP_SETUID assumption and standing privileged launcher acknowledged. Verified. Residual manifest-example gap → C23.
- C22 — Mockup design-language fixes — RESOLVED (applied). Badge, layout tokens, input focus and dark surface, callout borders, and the terminal log treatment are fixed. JetBrains Mono is named first but not remote-imported by design, which is correct under the app-frame CSP; accepted. Verified.

## 2026-07-05 — third verification pass (REVIEW COMPLETE)

Codex answered C8, C23, and C24. Each verified against the current plan text by
direct grep.

- C8 — Frontend and isolation design — RESOLVED (applied) over three rounds. `frontend-runtime.md` and `app-router.md` now specify a sandboxed opaque-origin iframe, `connect-src 'none'`, a server-minted per-frame app capability token validated server-side so cross-app invokes are rejected independently of the client bridge, a coherent SDK plus `MessagePort` bootstrap with an inert SDK, an explicit frame binding route and token lifecycle, a v1 Design Tokens section, and a CSP that names the explicit Omnideck asset origin instead of `'self'`. The round-3 fixes (bridge obtains rather than mints the token; explicit asset origin) were grep-confirmed.
- C23 — Round-2 doc-consistency cleanup — RESOLVED (applied). "scratch" scope-name reconciled to managed invocation files, `callable-runtime.md` named normative for the fd handoff, the app-storage example updated with document schemas, the preview example error code corrected to `CALLABLE_SCHEMA_INVALID`, and `package_review` confirmed in the manifest example. Verified (spot-checked).
- C24 — Environment builder hardening — RESOLVED (applied). The builder now has a hard execution floor (dedicated non-root build user, `NO_NEW_PRIVS`, dropped capabilities, seccomp network denial during hook execution, resource limits, disabled core dumps, Landlock), a defined launcher-based launch and privilege-drop path, and a read-only package cache with lock-file hash verification so a build hook cannot poison a shared env. Verified by grep.

All 24 review entries resolved. REVIEW COMPLETE.
