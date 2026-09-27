# Integration subsystem tests

Run `uv run pytest tests/integration/brokering/ tests/integration/integrations/`
or `just integration`.
These tests require no accounts, real credentials, running app, or container.
Servers use loopback addresses and random ports; each vault and socket directory
is temporary. Supervisor tests launch the production brokers as subprocesses.

| Coverage | Test |
|---|---|
| Registration, exact grants, reconnect, model-provider lifecycle | `../brokering/supervisor/test_supervisor.py` |
| Degraded reconnect readiness, save failures, cancellation, and no old-credential fallback | `../brokering/supervisor/test_degraded_reconnect.py` |
| Persisted restart, startup migration/failure, scope-independent grants, degraded connection recovery | `../brokering/supervisor/test_reconcile.py` |
| Crash respawn and terminal authentication failure | `../brokering/supervisor/test_watch.py` |
| Client error mapping, real RPC and mail protocols | `../brokering/broker_client/`, `../brokering/test_rpc.py`, `../brokering/brokers/` |
| OAuth authorization redirect, token exchange, Google broker refresh, narrower configuration choices with preserved grants, cancellation, denial, failed refresh cleanup | `test_oauth_flow.py` |
| HTTP revocation, agent discovery refresh, rejection of a retained agent tool | `test_revocation.py` |
| Background polling, post-edit snapshots, fixed initial/dynamically loaded skill tools | `test_discovery.py` |
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
remain under `tests/unit/integrations/` and `tests/unit/brokering/`. Cross-domain
OAuth, revocation, and model-provider tests here share an HTTP application fixture.
The application integration CI job runs
`tests/integration/` before merge; the container E2E job currently runs on main before
publishing an image.
