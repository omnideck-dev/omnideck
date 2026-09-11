# Integration subsystem tests

Run `uv run pytest tests/integration/integrations/` or `just integration`.
These tests require no accounts, real credentials, running app, or container.
Servers use loopback addresses and random ports; each vault and socket directory
is temporary. Supervisor tests launch the production brokers as subprocesses.

| Coverage | Test |
|---|---|
| Registration, exact grants, reconnect, rollback, model-provider lifecycle | `supervisor/test_supervisor.py` |
| Persisted restart, v2 migration, degraded connection recovery | `supervisor/test_reconcile.py` |
| Crash respawn and terminal authentication failure | `supervisor/test_watch.py` |
| Client error mapping, real RPC and mail protocols | `broker_client/`, `brokers/` |
| OAuth authorization redirect, token exchange, Google broker refresh, narrowed scopes, cancellation, denial, failed refresh cleanup | `test_oauth_flow.py` |
| HTTP revocation, agent discovery refresh, rejection of a retained agent tool | `test_revocation.py` |
| SDK completion and streaming through the LLM broker before/after credential replacement | `test_model_provider.py` |

OAuth tests replace only external endpoint URLs with a local server; they keep
the real OAuth library, application HTTP routes, supervisor, encrypted vault,
and Google broker. They verify startup refresh and authorization boundaries,
not live Google consent screens or Gmail/Drive API responses. HTTP for the local
token endpoint is enabled only within the test fixture.

The container/browser suite remains in `tests/e2e/settings/`. Its fake-integration
tests cover setup, real operation invocation, revocation, cancellation (including
failed cleanup and retry), and reconnect failure followed by successful retry.
Only the failed DELETE transport response is intercepted; successful creation,
broker calls, reconnect, and cleanup use the actual application.

Isolated parsing, catalog mapping, migration conversion, and dispatcher tests
remain under `tests/unit/integrations/`. The application integration CI job runs
`tests/integration/` before merge; the container E2E job currently runs on main before
publishing an image.
